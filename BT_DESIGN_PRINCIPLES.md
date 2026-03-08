# Behavior Tree Design Principles — bt-agent

Invariants and guidelines for anyone (human or frontier model) modifying
`bt_agent/tree/` or `bt_agent/llm/`. Sources: Colledanchise & Ögren *Behavior
Trees in Robotics and AI* (C&Ö), small-model coding task research, control
systems, and benchmark optimization methodology.

Violations should be deliberate, documented, and rare.

---

## Part I — BT Structure (Colledanchise & Ögren)

### 1. The Node Contract: Precondition → Action → Postcondition

Every leaf node has a **contract**. Document it. Enforce it in code.

| Term | Meaning | Where to enforce |
|---|---|---|
| **Precondition** | Blackboard fields this node reads and requires non-null | Guard block at top of `update()` |
| **Postcondition (SUCCESS)** | Blackboard fields this node writes on SUCCESS | Must be set before every `return SUCCESS` |
| **Postcondition (FAILURE)** | `bb.last_error` is a non-empty, actionable string | Must be set before every `return FAILURE` |

A node that returns SUCCESS without writing its promised fields is a bug.
A node that returns FAILURE without writing `bb.last_error` is a bug.

**Example (GenerateEdit)**:
```
Preconditions:  bb.current_file_content, bb.edit_intent, bb.edit_plan, bb.selected_file
SUCCESS writes: bb.proposed_edit (valid StrReplaceEdit), bb.last_error = None
FAILURE writes: bb.last_error (descriptive string), bb.proposed_edit unchanged
```

---

### 2. Condition Nodes vs Action Nodes

C&Ö define two fundamentally different leaf types.

**Condition nodes** — pure observers:
- Only **read** blackboard and world state. Never write.
- Return SUCCESS or FAILURE immediately. Never RUNNING.
- Must be **side-effect-free**: calling them twice on the same state yields the
  same result and the same world.

**Action nodes** — state changers:
- May read and write blackboard state.
- May return RUNNING for multi-tick operations.
- Must write `bb.last_error` on FAILURE.

**Current violation to watch**: `ReadTargetFile` increments `bb.edit_attempts`
on failure. That node is logically a precondition check (does the file exist and
is it readable?), but `edit_attempts` is loop-level accounting. Counter
increments on a guard node create hidden coupling between the guard and the retry
controller. When adding new guard nodes, check: does this `update()` write
anything other than `bb.last_error`? If yes, ask whether it should.

---

### 3. Sequence Child Ordering

A `Sequence` fails immediately when the first child fails. C&Ö give ordering
guidance:

1. **Cheapest checks first** — fast condition checks before expensive actions.
2. **Most-likely-to-fail first** among checks of equal cost.
3. **Prerequisite before dependent** — a node that reads `bb.X` must follow the
   node that writes `bb.X`.

**Applied to EditAttempt**:
```
ReadTargetFile  ← cheap I/O check; fails fast if file is missing
GenerateEdit    ← expensive LLM call; only runs if file is readable
ApplyEdit       ← fast I/O
ValidateEdit    ← moderate (AST + pyflakes)
```
This ordering is correct. When adding nodes to an existing Sequence, insert
before any expensive step that depends on your node's output, not after.

---

### 4. Selector Semantics and Fallback Structure

A `Selector` returns SUCCESS on the **first succeeding child**, trying
subsequent children only when earlier ones fail. Order children
most-preferred → least-preferred → fallback.

**Pattern for recoverable failures**:
```
Selector
├── Condition (is goal already achieved?)  ← skip if already done
└── Sequence
    ├── Action (attempt goal)
    └── Condition (verify success)
```

**The sentinel FAILURE pattern** (`FinalizeOrRollback`):
```
Selector
├── CommitAllChanges      ← succeeds if commit works
└── RollbackToSnapshot   ← always returns FAILURE
```
The trailing FAILURE child is intentional. It ensures the Selector propagates
FAILURE to the root when the commit fails, so the run is recorded as failed.
Do not replace the sentinel with a SUCCESS node "to be safe."

---

### 5. Every Composite Must Have a Control-Flow Justification

C&Ö embrace hierarchy as a core BT virtue — deep, modular subtrees that
compose cleanly are good design. But each composite must earn its place by
providing a control-flow structure that cannot be achieved by adding children to
an existing composite.

A composite earns its place if it:
- Groups children that are **retried or recovered independently** from siblings
  (e.g., `EditAttempt` exists specifically to be the child of `RetryUntilSuccess`)
- Groups children under a **different Selector/Sequence/Parallel semantics**
  than the parent
- Groups children that are **logically reused** as a named subtree elsewhere

A composite does **not** earn its place if it just wraps two children that
always run together with the same success/failure semantics as everything around
them. In that case, add the children to the existing Sequence instead.

*Test*: if removing the composite and flattening its children into the parent
produces identical runtime behavior, the composite is decorative and should be
removed.

---

### 6. Memory vs Reactive Composites

| Mode | Behavior on re-tick | Use when |
|---|---|---|
| `memory=True` | Resumes from last active child | Pipeline steps are non-idempotent and expensive to re-run |
| `memory=False` | Restarts from first child every time | Reactive monitoring where conditions may change between ticks |

All pipeline Sequences in this project use `memory=True`. This is correct: the
pipeline is `Understand → Gather → Plan → Edit → Commit`. Re-running
`UnderstandTask` on each EditLoop tick would waste tokens and risk inconsistent
outputs.

**Rule**: Do not change `memory=True` to `memory=False` on a pipeline Sequence
without a specific reason to re-evaluate earlier stages on re-entry. The
consequence is every node re-runs from the start on each tick, multiplying LLM
calls.

---

### 7. Idempotent Actions

If an action node is called when its goal is already achieved, it should return
SUCCESS immediately without doing redundant work.

**Example**: `GitCommit` should detect "nothing to commit" and return SUCCESS
rather than erroring. `ApplyEdit` on a file that already contains `new_str`
should ideally detect this case.

When adding work to an action node, ask: *what happens if this runs when the
work is already done?* If the answer is "it errors," add an idempotency guard.

---

### 8. RUNNING State Discipline

A node returning RUNNING promises it will be ticked again and will eventually
terminate. This requires:

1. Per-tick state is stored on the blackboard or as node instance variables,
   not in locals that vanish between ticks.
2. `terminate(new_status)` must clean up any in-progress work when the tree
   is halted.
3. Blocking calls inside `update()` block the entire tick. For the POC this is
   acceptable; for production, move blocking LLM calls to async workers and
   return RUNNING while waiting.

All current nodes are single-tick. If you add a genuinely multi-tick node,
implement `initialise()` and `terminate()`.

---

### 9. Failure Is Data, Not an Exception

FAILURE is a normal return value, not an error condition. It is the mechanism by
which the tree selects fallback behavior. Do not `raise` exceptions for expected
failure cases — catch them, write `bb.last_error`, return FAILURE.

`bb.last_error` after a FAILURE must be a **diagnostic string useful to the
retry prompt**, not a Python traceback, not `"Error"`, not `None`.

Bad: `"ApplyEdit failed"`

Good: `"old_str not found in utils.py. The exact string you specified does not
appear verbatim in the file. Check indentation and whitespace. Re-read the
relevant section before retrying."`

---

### 10. Blackboard Write Discipline

| Rule | Rationale |
|---|---|
| One canonical writer per field | Two writers on the same field means the second silently overwrites the first |
| Write postcondition fields only on SUCCESS | Partial writes on the FAILURE path corrupt downstream nodes |
| Do not clear fields you didn't write | `ValidateEdit` reverts the file but should not null `bb.proposed_edit` — that is `GenerateEdit`'s domain |
| Reset loop counters at loop boundaries, not inside nodes | Nodes that reset `edit_attempts` create hidden ordering dependencies with the retry controller |

---

## Part II — Small-Model Coding Tasks

The subject under test is `qwen2.5-coder:7b`. Improvements must account for
the specific failure modes of 7B-scale instruction-following models on code
tasks.

### 11. Format Errors vs Content Errors Are Different Failure Modes

Small models fail at **expressing** correct answers as valid JSON more often
than they fail at **knowing** what change to make. These require different fixes:

| Failure type | Symptom | Fix direction |
|---|---|---|
| **Format error** | `json_parse_error`, empty response, missing keys | Tighten JSON schema in prompt; add a worked example; reduce instruction count |
| **Content error** | `old_str_not_found`, wrong file targeted, semantically incorrect edit | Improve context quality; add `<thought>` structure; improve planning prompt |

Applying a content fix to a format failure (or vice versa) wastes an iteration.
Read the raw LLM response in the trajectory before choosing a fix direction.

---

### 12. Context Placement (Lost-in-the-Middle)

7B models show sharper "lost in the middle" degradation than frontier models.
When constructing prompts:

- Put the **most important constraint** (e.g., the required JSON schema) at the
  **top or bottom** of the user prompt, not buried mid-prompt.
- Put **file content** (long, less critical for format adherence) in the middle.
- Put the **specific task instruction** ("make the following change") at the
  end, immediately before the model generates.

---

### 13. Instruction Count Sensitivity

A prompt with 3 instructions is followed reliably. A prompt with 8 instructions
sees selective compliance — the model satisfies some and quietly ignores others.

When a prompt fails repeatedly, count the distinct requirements it makes. If the
count exceeds ~4, consider whether some can be moved to the system prompt,
collapsed, or enforced structurally (e.g., via JSON schema) rather than stated
in natural language.

---

### 14. Few-Shot Examples Outperform Long Natural-Language Instructions

For structured output tasks at 7B scale, one worked example in the prompt is
worth more than two paragraphs of format description. If a node's output format
is repeatedly malformed, the first fix to try is adding a single correct
example, not expanding the format description.

---

### 15. Chain-of-Thought at 7B Scale

Structured thought before output improves reasoning quality even at 7B.
`BaseLLMNode` already extracts `<thought>` tags. But unconstrained
`<thought>` content can ramble and consume context budget.

Prefer a **structured thought prompt** over an open-ended one:
```
# Less effective
Before responding, write your reasoning in <thought>...</thought> tags.

# More effective
Before responding, write in <thought>...</thought>:
- What needs to change and why
- What old_str you will use (must be verbatim from the file)
```

---

## Part III — Retry Loop as Feedback Controller

### 16. Signal Quality Determines Correction Quality

The retry prompt is the only control signal the model receives after a failed
attempt. The quality of the correction is bounded by the quality of the signal.

A vague error message (`"edit failed"`) produces vague corrections. A precise
error message with the specific mismatch, the relevant file section, and an
actionable directive produces targeted corrections.

When improving retry behavior, improve the error signal first. More retries with
a bad signal produce more failures, not different ones.

---

### 17. Classify Failures as Retryable or Terminal

Not all failures benefit from retrying. Continuing to retry a terminal failure
wastes tokens and obscures the root cause.

| Failure type | Retryable? | Indicator |
|---|---|---|
| `old_str_not_found` | Yes — model can re-read and correct | Usually resolves in 1–2 retries with better context |
| `json_parse_error` (once) | Yes | `_call_llm_json` handles this internally |
| `json_parse_error` (every attempt) | No — structural prompt problem | Model cannot format output; fix prompt first |
| Empty/null response on every attempt | No — model or API issue | Not a retry target |
| `syntax_error` after edit | Yes | Model can correct with error feedback |
| Same `syntax_error` repeated | No — feedback loop is broken | The error message isn't informing the correction |

**Oscillation** (model alternates between two failure modes across retries) is a
signal to stop and fix the prompt or tree structure. More retries will not break
the oscillation.

---

## Part IV — Optimizer Behavior (Auto-Tune Loop)

These rules govern how the frontier model (Claude) should behave when invoked
with `--auto-tune`.

### 18. Diagnose Before Changing

Read the trajectory before touching any code. The failure may be upstream of
where the error manifests. A `ValidateEdit` FAILURE whose `last_error` says
"syntax error on line 3" is almost always caused by `GenerateEdit`'s output,
not by `ValidateEdit`'s logic.

Diagnosis sequence:
1. `reports/latest.md` — identify which problems failed and what failure mode
2. `runs/<latest>/<problem>/trial-1/trajectory.jsonl` — find the failing node
3. The `llm_call.raw_response` field — read what the model actually produced
4. The relevant node source and prompt — understand why it failed

---

### 19. One Change Per Iteration

Multiple simultaneous changes make it impossible to attribute improvement or
regression to a specific cause. If the pass rate improves after two changes,
you don't know which one helped (or whether they interfered). If it regresses,
you don't know which change caused it.

Make one targeted change per iteration. Use the bench-tune loop's iteration
structure for this: each iteration is one hypothesis test.

---

### 20. Classify Changes by Blast Radius

| Change type | Blast radius | Risk level |
|---|---|---|
| Prompt text in `prompts.py` (one node) | One node's behavior | Low — trivially reversible |
| Error message in a leaf node | One failure path | Low |
| `BaseLLMNode` logic | Every LLM node | Medium — test all LLM nodes |
| Tree structure (add/remove/reorder node) | All downstream nodes | Medium-High |
| Composite type change (`Sequence` → `Selector`) | Subtree semantics | High |
| Blackboard schema change | All nodes that read the field | High |

Start with low blast-radius changes. A prompt fix that solves the problem is
strictly better than a structural fix that solves the same problem.

---

### 21. Prefer Changes with Broad Mechanistic Justification

The bench-tune loop is an optimizer against a fixed benchmark. Goodhart's Law
applies: a change that boosts the metric by teaching the model to handle one
fixture's idiosyncrasies may harm generalization.

Prefer changes that have a mechanistic justification that would apply to
**unseen fixtures**: "adding file line numbers to the context window helps the
model construct exact `old_str` matches" is broad. "Adding the string `utils.py`
to the LocateRelevantFiles prompt" is overfit.

Before applying a change, ask: *would this change make sense for a fixture I
haven't seen?* If the answer is no, it's a brittle fix.

---

### 22. Unit Tests Are a Structural Guarantee

Every leaf node must have unit tests covering:
1. **Precondition missing** → FAILURE with descriptive `bb.last_error`
2. **Happy path** → SUCCESS with correct postcondition fields written
3. **Tool/LLM failure** → FAILURE with descriptive `bb.last_error`

After any change, run:
```bash
.venv/bin/python -m pytest tests/unit/ -q
```

A failing unit test means the node's contract is broken. Fix the node, not the
test.

---

## Quick Checklist for New or Modified Nodes

- [ ] Node has a single, named responsibility
- [ ] `update()` has a guard block checking all preconditions
- [ ] Every `return FAILURE` path writes a non-empty, actionable `bb.last_error`
- [ ] Every `return SUCCESS` path writes all promised postcondition fields
- [ ] No side effects (counter increments, file writes) in guard/condition checks
- [ ] If RUNNING is returned: `initialise()` and `terminate()` are implemented
- [ ] Prompt strings live in `prompts.py`, not inline in the node file
- [ ] If a new composite was added: its control-flow justification is documented
- [ ] Unit tests cover all three contract paths
- [ ] `pytest tests/unit/ -q` passes
