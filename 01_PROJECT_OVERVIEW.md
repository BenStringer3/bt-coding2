# BT-Agent: Behavior Tree Code Editing Agent — Project Overview

## What We're Building

A proof-of-concept Python library that uses a **behavior tree** (via `py-trees`) as the control harness for an LLM-driven code editing agent. The core insight is that a behavior tree provides deterministic, inspectable, resumable control flow — replacing the flat ReAct loop used by most current agents (SWE-agent, Claude Code, etc.) with structured, hierarchical logic that the LLM only touches at leaf nodes.

This is not a product. It is a research prototype to validate the hypothesis that externalizing agent strategy into a behavior tree structure improves reliability and debuggability, especially for smaller models.

---

## Motivation

Current LLM coding agents use a ReAct loop: observe → think → act → repeat. Problems with this:

- **Strategy drift**: On long tasks (10+ steps), models rediscover their own plan from scratch each tick, burning tokens and introducing inconsistency
- **No structured fallback**: When a tool call fails, the model decides ad-hoc what to do next
- **Opaque state**: Hard to know where in the task the agent is, or why it's doing what it's doing
- **Poor resumability**: If the process crashes mid-task, there is no clean way to resume

A behavior tree addresses all four:
- Control flow is encoded structurally, so the model never needs to "remember" strategy
- Fallback nodes are explicit (`Selector` nodes cascade to alternatives deterministically)
- Current position in the tree is always visible and loggable
- The blackboard can be serialized to disk for crash recovery

---

## Scope for POC

### In scope
- A working behavior tree that takes a task description + local repo path and produces a code edit + git commit
- Leaf nodes that call an LLM (via LiteLLM for model-agnostic support, including local Ollama)
- A blackboard for shared state across nodes
- File read/write/edit tooling (`str_replace` style, informed by SWE-agent ACI conventions)
- Inline linting on every edit (AST + pyflakes) — edits that introduce syntax errors are rejected before touching disk
- Basic git operations (stage, commit)
- Trajectory logging: every node tick + blackboard state saved to JSONL for inspection
- CLI runner: `bt-agent run --task "..." --repo ./path/to/repo`

### Out of scope for POC
- Web search
- Semantic/embedding-based code search
- Multi-file plans (single file edit only for POC)
- SWE-bench evaluation harness
- GUI or TUI
- Parallel subtrees

---

## Success Criteria

1. The tree successfully completes at least one end-to-end task: given a plain-English bug description + a repo, produces a correct committed fix
2. When the LLM produces a malformed edit, the tree retries deterministically — not via model judgment
3. When the edit introduces a syntax error, the linter catches it, the edit is discarded, and the tree retries
4. The trajectory log makes it easy to see exactly what happened at each step
5. The whole thing works with a local Ollama model (`qwen2.5-coder:7b`) — not just cloud APIs

---

## Repository Structure (target)

```
bt-agent/
├── bt_agent/
│   ├── __init__.py
│   ├── tree/
│   │   ├── __init__.py
│   │   ├── builder.py         # Assembles the full behavior tree
│   │   ├── blackboard.py      # Blackboard schema + helpers
│   │   └── nodes/
│   │       ├── __init__.py
│   │       ├── base.py        # Base LLM leaf node class
│   │       ├── understand.py  # Parse task, write structured goal to blackboard
│   │       ├── gather.py      # Read repo map, locate relevant files
│   │       ├── plan.py        # Generate edit plan
│   │       ├── edit.py        # Apply str_replace edit
│   │       ├── validate.py    # Lint + AST syntax check
│   │       └── commit.py      # Git stage + commit
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── file_ops.py        # read, write, str_replace, windowed view
│   │   ├── linter.py          # AST + pyflakes checking
│   │   ├── git_ops.py         # Git interface via GitPython
│   │   └── repo_map.py        # Directory tree + file summary builder
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py          # LiteLLM wrapper with retry + error handling
│   │   └── prompts.py         # All prompt templates (no inline strings elsewhere)
│   ├── logging/
│   │   ├── __init__.py
│   │   └── trajectory.py      # JSONL trajectory logger
│   └── cli.py                 # Click CLI entrypoint
├── tests/
│   ├── fixtures/              # Small synthetic repos for integration tests
│   └── test_*.py
├── config/
│   └── default.yaml           # Default model, retry limits, window size, etc.
├── pyproject.toml
└── README.md
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `py-trees` | Behavior tree engine |
| `litellm` | Model-agnostic LLM calls (OpenAI, Anthropic, Ollama, etc.) |
| `click` | CLI |
| `gitpython` | Git operations |
| `pyflakes` | Inline linting |
| `pydantic` | Blackboard schema validation |
| `rich` | Terminal output and tree visualization |
| `pytest` | Testing |
| `pyyaml` | Config loading |

No Docker dependency. Runs directly against a local repo on disk.

---

## Design Principles (drawn from SWE-agent research)

1. **Compact, model-centric tool feedback** — Every tool response is formatted for LLM consumption, not human readability. Line numbers, file paths, and error messages are always present.
2. **Linting as a hard gate** — Invalid edits never reach disk. The linter runs synchronously before any write and returns `FAILURE` if it fails, triggering the tree's built-in retry logic.
3. **Windowed file view** — Files are never dumped in full. A configurable window (default 100 lines) with current position, total lines, and 2-line overlap is the standard view format.
4. **Error message collapsing** — After a retry succeeds, prior error messages are collapsed to a single-line summary in the context. They don't pile up.
5. **Thought + action per step** — Every LLM leaf node is prompted to produce a `<thought>` block before its action. The thought is parsed, logged in the trajectory, but not echoed back to the model.
6. **The model controls nothing outside leaf nodes** — All branching, sequencing, retry counting, and fallback logic lives in the tree structure. The model only fills in cognitive tasks at leaves.

---

## Key Files to Read Before Implementing

1. `02_TECHNICAL_SPEC.md` — component-by-component implementation spec
2. `03_SWE_AGENT_CONVENTIONS.md` — ACI design patterns and tool conventions to adopt
