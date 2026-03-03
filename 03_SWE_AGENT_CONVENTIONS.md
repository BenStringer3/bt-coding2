# SWE-Agent Conventions & ACI Patterns to Adopt

This document summarizes the key design decisions from SWE-agent's Agent-Computer Interface (ACI) research that should inform the BT-Agent implementation. These are empirically validated patterns — not theoretical preferences. Deviating from them should require justification.

Source: Yang et al. (2024), "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering", NeurIPS 2024.

---

## Core Principle: The Interface Matters As Much As The Model

SWE-agent's central finding: **a baseline agent with a well-designed ACI outperforms a stronger model with a poor ACI by 3-4x on code editing tasks.** This is the entire motivation for this project. The behavior tree is our ACI — the interface between the LLM and the codebase.

Specific finding: moving from a raw Linux shell interface to a purpose-built ACI raised resolution rates from ~4% (RAG baseline) to ~12.5%, using the same underlying model.

---

## Tool Design Conventions

### 1. Search tools must return concise, bounded output

**Pattern**: SWE-agent's `search_file`, `search_dir`, and `find_file` commands all cap output at **50 results**. If a query returns more than 50 results, the agent is told to refine the query — it does not receive a truncated dump.

**Why it matters**: Models given excessive search output exhibit "thrashing" — they scan without finding what they need, burning context budget. Bounded results force specificity.

**BT-Agent application**: `BuildRepoMap` truncates at 200 lines. `LocateRelevantFiles` returns at most 3 candidate files. If the LLM asks to search file contents (future feature), cap results at 50 and prompt for refinement.

---

### 2. File viewer must show line numbers and position context

**Pattern**: SWE-agent's `open` command displays:
- Full file path
- Total number of lines in file
- Which lines are currently shown
- How many lines are omitted above/below
- Line numbers prefixed on each line

This exact format is what `read_windowed()` in the spec implements. Do not simplify it.

**Why it matters**: Without position context, models lose track of where they are in large files and make edits relative to the wrong section. Line numbers are critical for the model to construct correct `old_str` in str_replace.

---

### 3. Linting is a hard gate, not advisory

**Pattern**: SWE-agent integrates a linter directly into the edit command. Invalid edits are **discarded before they reach disk**. The agent is shown the error and asked to try again. The paper notes this "significantly improves performance" vs. alternatives.

**BT-Agent application**: This is `ValidateEdit`. It runs synchronously after `ApplyEdit`. If lint fails, the file is reverted to its pre-edit state before the node returns FAILURE. The edit never persists.

**Important implementation detail**: Show the model a snippet of the file around the error location when a lint error occurs, not just the error message. SWE-agent provides "a snippet of the file contents before/after the error was introduced." This gives the model the context it needs to fix the specific line.

---

### 4. Actions should consolidate multiple sub-operations

**Pattern**: SWE-agent does not give the model separate "open file", "validate edit", "write edit", "re-open file" commands. Instead, the `edit` command handles all of: opening, validating, writing, and updating the agent's view in one call.

**Why it matters**: More tool calls = more context used = more opportunities for the model to drift. Fewer, more powerful tools keep the context lean.

**BT-Agent application**: `GenerateEdit` + `ApplyEdit` + `ValidateEdit` are separate *tree nodes* but the model only invokes *one LLM call* (`GenerateEdit`). The apply and validate happen deterministically without another LLM call. The model doesn't "request" apply and validate — the tree does it automatically after every edit generation.

---

### 5. Error messages must be LLM-centric, not human-centric

**Pattern**: SWE-agent's error messages are designed to help the model understand and correct its mistake, not to help a human debug the system. Every error includes:
- What went wrong (specific, not generic)
- What the model should do differently (actionable)
- Relevant context (file snippet, line number, etc.)

**Example of bad error**: `FileNotFoundError: [Errno 2] No such file or directory`

**Example of good error** (SWE-agent style): `old_str not found in tools/file_ops.py. The exact string you provided does not appear in the file. Check: (1) whitespace and indentation, (2) that you copied the text exactly. Use the view command to re-read the relevant section.`

**BT-Agent application**: Every FAILURE return from a deterministic node must write a descriptive, actionable error message to `blackboard.last_error`. This message is included verbatim in the next `GenerateEdit` prompt.

---

### 6. Context management: collapse old observations

**Pattern**: SWE-agent's history processor collapses observations older than the last 5 into a single line each. This prevents the context window from filling with stale file contents and old error messages.

**Why it matters**: Without collapsing, a 10-step trajectory could use 80% of the context window on outdated file views. The model's effective attention is then dominated by old information.

**BT-Agent application**: In the trajectory logger and any prompt that assembles history, implement a `Last5Observations` rule: the last 5 node results are shown in full; older ones are collapsed to `[{node_name}: {status} at {timestamp}]`. 

For the POC's single-loop structure, this mainly affects the edit retry prompts — after multiple failed attempts, don't include all previous attempts in full detail. Include only the most recent error.

---

### 7. Generate thought before action

**Pattern**: SWE-agent instructs models to generate a `<thought>` block before every action. This is parsed and logged but not shown back to the model in the next step.

**Why it matters**: The thought step improves reasoning quality (CoT effect) and makes trajectories interpretable. Researchers can read the trajectory log and understand *why* the model made each decision.

**BT-Agent application**: All LLM leaf node prompts should include: `Before responding, write your reasoning in <thought>...</thought> tags. Then provide your JSON response.`

The base LLM node class (`bt_agent/tree/nodes/base.py`) should:
1. Extract and strip the `<thought>` block from the response before JSON parsing
2. Store the thought in the trajectory log entry
3. Never include the thought in subsequent prompts to the model

---

### 8. Malformed generations: retry with error, then collapse

**Pattern**: When a model generates a malformed response (bad JSON, missing fields, etc.), SWE-agent:
1. Shows the model an error message and asks it to retry
2. Keeps retrying until a valid generation is received
3. **Collapses all but the first error message** from history once a valid generation is received

**BT-Agent application**: The `call_json()` method should retry up to 2 times on JSON parse errors before returning a FAILURE. The node itself should not retry — that's the tree's job. But a single LLM call retrying 2x on malformed JSON is reasonable and avoids unnecessary tree-level retries for trivial formatting failures.

When including previous errors in the retry prompt, include only the most recent one (not all of them).

---

## What SWE-Agent Does NOT Do (That We're Doing Differently)

### ReAct loop vs behavior tree

SWE-agent uses a ReAct loop: the model sees the full history and decides its next action on every step. Our approach moves all control flow out of the model and into the tree. The tradeoffs:

| | SWE-agent ReAct | BT-Agent |
|---|---|---|
| Model flexibility | High — model can choose any tool | Low — tree decides order |
| Strategy consistency | Depends on model | Deterministic |
| Debuggability | Inspect trajectory | Inspect tree + trajectory |
| Small model suitability | Poor (drift, confusion) | Better (structure compensates) |
| Novelty handling | Good (model adapts) | Poor (tree is fixed) |

For the POC, the tradeoff favors us: the tasks are well-structured (find file, plan edit, apply edit, validate), so the fixed tree covers the space well.

---

## Prompt Template Conventions

All prompts live in `bt_agent/llm/prompts.py` as constants. No inline prompt strings in node files.

Naming convention: `{NODE_NAME}_{CASE}_SYSTEM` and `{NODE_NAME}_{CASE}_USER`

Example:
```python
GENERATE_EDIT_BASE_SYSTEM = "You are a code editor. Generate a str_replace edit..."
GENERATE_EDIT_BASE_USER = "Task: {edit_intent}\n\nPlan:\n{edit_plan}\n\nFile content:\n{current_file_content}"
GENERATE_EDIT_RETRY_ADDITION = "Your previous attempt failed:\nError: {last_error}\n\nTry again..."
```

This makes it easy to iterate on prompts without touching node logic, and makes prompt changes visible in version control diffs.

---

## SWE-Bench Compatibility (future)

The POC does not target SWE-bench, but the architecture should not preclude it. Key differences to note:

- SWE-bench requires Docker isolation (the POC runs directly on disk)
- SWE-bench evaluates on Python repos only
- SWE-bench uses `FAIL_TO_PASS` tests as the evaluation signal — running tests and checking they pass is the gold standard, not just lint

When extending beyond POC: add a `RunTests` node between `ValidateEdit` and the loop exit condition, and wire its output into the FAILURE/SUCCESS signal.

---

## Key Numbers from SWE-Agent Research

Use these as calibration for the POC's design choices:

- Window size of 100 lines was found optimal (larger windows don't help and burn context)
- History of last 5 observations is the sweet spot before context degradation
- Limiting search to 50 results prevents thrashing
- Inline linting improved edit success rate significantly vs. no linting
- Models fail more often at *expressing* edits (bad format) than at *understanding* what to change — hence the importance of retry logic and clear error messages
