# Agents Guide — bt-agent

## Purpose

This repository is a proof-of-concept for a **behavior-tree-driven code editing agent** that uses a small local LLM (e.g., `qwen2.5-coder:7b`) to fix bugs. The behavior tree externalizes control flow from the model, making agent behavior deterministic, inspectable, and improvable.

**Your role as a frontier model agent (Claude, Codex, etc.):**
You are the **optimizer**, not the subject. The small local model is the subject under test. Your job is to read benchmark results, diagnose failure patterns, and improve the agent architecture so that the small model succeeds on more problems.

---

## Two-Level Mental Model

```
┌─────────────────────────────────────────────────────┐
│  Frontier model (YOU — Claude / Codex)              │
│  Reads reports, edits bt_agent/ source, improves    │
│  prompts/nodes/config, reruns bench                 │
└──────────────────┬──────────────────────────────────┘
                   │ improves
┌──────────────────▼──────────────────────────────────┐
│  bt-agent (behavior tree harness)                   │
│  py-trees 2.4 control flow + LLM leaf nodes         │
│  Driven by small local model via LiteLLM            │
└──────────────────┬──────────────────────────────────┘
                   │ edits
┌──────────────────▼──────────────────────────────────┐
│  Coding fixtures (Python bugs)                      │
│  tests/fixtures/<id>/buggy.py                       │
│  Success = pytest test_solution.py passes           │
└─────────────────────────────────────────────────────┘
```

---

## Key Commands

```bash
# Setup (once)
python -m venv .venv && pip install -e .
source .venv/bin/activate

# Run a single problem interactively (manual testing)
./scripts/run-problem.sh

# Run a full benchmark suite
./scripts/bench.sh --suite suites/phase1.yaml --tag p1-baseline

# View latest report
cat reports/latest.md

# Run the full iterative tuning loop (you may be invoked this way)
./scripts/bench-tune.sh --suite suites/phase1.yaml --max-iterations 3 --auto-tune

# Run unit tests (after code changes)
.venv/bin/python -m pytest tests/unit/ -q
```

---

## Improvement Workflow

> See **`WORKFLOW.md`** for the full detailed description of both loops (dev loop and bench-tune loop), including a mermaid flowchart of the iteration cycle and the complete artifact layout.

This is the core loop you operate in:

1. **Read** `reports/latest.md` — understand what failed and why
2. **Read** `runs/<latest-run>/<problem>/trial-1/trajectory.jsonl` — inspect node-level failures
3. **Diagnose** the root cause (see Failure Modes below)
4. **Change** tree nodes, prompts, or config (see What to Change)
5. **Verify** unit tests still pass: `pytest tests/unit/ -q`
6. **Rerun** bench: `./scripts/bench.sh --suite suites/phase1.yaml --tag my-fix`
7. **Check gate**: if `metrics.json → success_gate.passed == true`, phase complete; else loop

`bench-tune.sh` automates steps 1–6 when called with `--auto-tune`. Steps 2–3 (trajectory inspection) require reading actual log files.

### Benchmark Preflight (Required)

Before any `bench.sh` or `bench-tune.sh` run, perform this preflight:

1. Verify LM Studio is reachable:
   - `curl -sS http://127.0.0.1:1234/v1/models`
2. Verify expected model is listed (default: `qwen/qwen3-14b` unless overridden)
3. Run a smoke benchmark and ensure artifacts are produced:
   - `./scripts/bench.sh --suite suites/phase1.yaml --tag preflight-smoke --runs-per-problem 1`
   - Confirm run directory contains `result.json` (per trial), `results.json`, and `metrics.json`
4. Only start iterative tuning after a complete benchmark run succeeds end-to-end

If running in a sandboxed coding agent, local socket access to `127.0.0.1:1234` may require escalated permissions.

### Triage Rule: Infra vs Agent

Do not tune prompts/nodes from incomplete runs.

- **Infrastructure/harness failures** (connection errors, script runtime errors, missing artifacts) must be fixed first.
- **Agent behavior failures** (e.g., `old_str_not_found`, `json_parse_error`, `syntax_error`) are valid tuning targets only after infrastructure is stable.

---

## Architecture Overview

### Tree Types

| CLI command | Builder | Use |
|-------------|---------|-----|
| `bt-agent run` | `bt_agent/tree/builder.py` | Single-file bugs (Phase 1–2) |
| `bt-agent run-multi` | `bt_agent/tree/multifile_builder.py` | Multi-file refactoring (Phase 3+) |

### Single-File Tree

```
Root [Sequence]
├── UnderstandTask           ← LLM: parse goal from task description
├── GatherContext [Sequence]
│   ├── BuildRepoMap         ← AST: directory tree + file summaries
│   └── LocateRelevantFiles  ← LLM: pick which file(s) to edit
├── PlanEdits                ← LLM: describe what change to make
├── EditLoop [RetryUntilSuccess, max=5]
│   └── EditAttempt [Sequence]
│       ├── ReadTargetFile   ← tool: read current file content
│       ├── GenerateEdit     ← LLM: produce {old_str, new_str}
│       ├── ApplyEdit        ← tool: str_replace in file
│       └── ValidateEdit     ← tool: AST parse + pyflakes check
└── CommitChanges [Sequence]
    ├── GenerateCommitMsg    ← LLM: write commit message
    └── GitCommit            ← tool: git commit
```

### Blackboard (shared state)

`AgentBlackboard` (Pydantic) holds all state between nodes:
- `task_description`, `repo_path` — inputs
- `parsed_goal`, `target_language` — from UnderstandTask
- `repo_map`, `candidate_files`, `selected_file` — from GatherContext
- `edit_plan`, `edit_intent` — from PlanEdits
- `current_file_content`, `proposed_edit`, `edit_attempts`, `last_error` — EditLoop state
- `commit_message`, `committed` — output

**`committed == True` is the definition of success.** Bench scripts read this from trajectory.

### Key Source Paths

| Path | Description |
|------|-------------|
| `bt_agent/tree/nodes/understand.py` | UnderstandTask node |
| `bt_agent/tree/nodes/gather.py` | BuildRepoMap, LocateRelevantFiles |
| `bt_agent/tree/nodes/plan.py` | PlanEdits |
| `bt_agent/tree/nodes/edit.py` | ReadTargetFile, GenerateEdit, ApplyEdit |
| `bt_agent/tree/nodes/validate.py` | ValidateEdit |
| `bt_agent/tree/nodes/commit.py` | GenerateCommitMsg, GitCommit |
| `bt_agent/tree/nodes/multifile.py` | All Phase 3+ nodes + ForEachFileIterator |
| `bt_agent/tree/nodes/base.py` | BaseLLMNode (JSON extraction, thought tags) |
| `bt_agent/llm/prompts.py` | All single-file LLM prompt templates |
| `bt_agent/llm/multifile_prompts.py` | Multi-file prompt templates |
| `bt_agent/tree/blackboard.py` | AgentBlackboard + MultiFileBlackboard |
| `bt_agent/tools/file_ops.py` | read, write, str_replace, windowed view |
| `bt_agent/tools/linter.py` | AST + pyflakes validation |
| `config/default.yaml` | model, temperature, max_tokens, max_edit_attempts |

---

## Failure Modes and Diagnosis

### Reading a Trajectory

Each `trajectory.jsonl` line is a node tick event:
```json
{
  "ts": "...",
  "node": "GenerateEdit",
  "status": "FAILURE",
  "error": "old_str not found in file",
  "blackboard": { "last_error": "...", "edit_attempts": 2, ... },
  "llm_call": { "prompt_tokens": 412, "completion_tokens": 89, "raw_response": "..." }
}
```

Look for nodes with `"status": "FAILURE"` and non-null `"error"` or `"blackboard.last_error"`.

### Common Failure Modes

| Failure Mode | Where it appears | Root Cause | Fix direction |
|---|---|---|---|
| `ApplyEdit.old_str_not_found` | ApplyEdit FAILURE | `old_str` in GenerateEdit response doesn't match actual file text | Shorten old_str in prompt; add file window context |
| `ValidateEdit.syntax_error` | ValidateEdit FAILURE | New code has syntax errors | Strengthen GenerateEdit prompt; add error feedback in retry |
| `ValidateEdit.import_error` | ValidateEdit FAILURE | New code introduces bad import | Improve pyflakes feedback in retry prompt |
| `LLM.json_parse_error` | any LLM node FAILURE | Model returned non-JSON | Fix prompt format instructions; add JSON schema example |
| `EditLoop.max_attempts` | EditLoop exhausted | All 5 retries failed | Check `last_error` chain in trajectory; improve retry prompt |
| `LocateRelevantFiles.no_file` | GatherContext FAILURE | Model didn't identify target file | Improve repo map format; fix LocateRelevantFiles prompt |
| `GenerateEdit.empty` | GenerateEdit FAILURE | Model returned empty or null edit | Add explicit output format requirements in prompt |

### Reading metrics.json

`runs/<run-id>/metrics.json` → key sections:
- `summary.success_rate` — overall pass rate
- `success_gate.passed` — whether phase gate is met
- `failure_modes` — counts by failure type
- `recommendations` — auto-generated hints
- `per_problem.<id>.success_rate` — per-problem breakdown

---

## What You Can Change

These are the legitimate targets for improvement. All changes should be followed by `pytest tests/unit/ -q` to verify nothing regressed.

### 1. LLM Prompts (`bt_agent/llm/prompts.py`, `bt_agent/llm/multifile_prompts.py`)
The highest-leverage lever. Common improvements:
- Tighten JSON output format instructions (add explicit schema, example response)
- Add `last_error` context to retry prompts so the model learns from previous attempt
- Shorten `old_str` guidance (small models often copy too much context)
- Add thought-chain structure: `<thought>` before JSON output improves reasoning

### 2. Leaf Node Logic (`bt_agent/tree/nodes/`)
- `GenerateEdit`: adjust how `old_str`/`new_str` are extracted from LLM response
- `ValidateEdit`: add or tune post-edit checks (pyflakes severity, additional checks)
- `PlanEdits`: improve how edit intent is structured and passed downstream
- `BaseLLMNode`: adjust JSON extraction regex, thought tag handling, retry logic

### 3. Tree Structure (`bt_agent/tree/builder.py`, `bt_agent/tree/multifile_builder.py`)
- Add a new validation node after `GenerateEdit` (pre-application sanity check)
- Add a `ReflectOnFailure` node inside `EditLoop` to inject structured error feedback
- Adjust `max_edit_attempts` in config or in the tree builder
- Add a `VerifyUnderstanding` subtree if `UnderstandTask` output is consistently poor

### 4. Config (`config/default.yaml`)
- `temperature`: keep at 0.0 for determinism; raise to 0.1–0.3 only if model is stuck
- `max_edit_attempts`: raise if retries are helping; lower if model loops pointlessly
- `window_size`: increase if model misses context; decrease if prompts are too long
- `max_tokens`: raise if model is truncating edits; lower to force conciseness

### 5. New Nodes
If a systematic gap is identified (e.g., model never correctly locates the right line), add a new leaf node. Follow `BaseLLMNode` for LLM nodes or implement a simple `py_trees.behaviour.Behaviour` subclass for tool-only nodes.

---

## What NOT to Change

- **`tests/fixtures/*/`** — fixture source files and `test_solution.py` are ground truth; never modify
- **`tests/fixtures/*/problem.yaml`** — problem specifications are fixed
- **`suites/*.yaml`** — suite definitions and success gates are spec, not config
- **`scripts/bench.sh`, `bench-analyze.py`, `bench-report.py`** — evaluation infrastructure
  - Exception: if the benchmark pipeline itself is broken (cannot produce valid `result.json`/`metrics.json`), fix infrastructure correctness first, then resume agent tuning
- **`tests/unit/`** — unit tests are ground truth for the harness itself; fix failures, don't delete tests

---

## Phase Gates

The roadmap in `ROADMAP.md` defines 5 phases with quantitative success gates. **Do not advance to the next phase until the current gate passes.**

| Phase | Suite | Gate |
|-------|-------|------|
| 1 — Syntactic bugs | `suites/phase1.yaml` | ≥ 90% success, ≤ 2 retries, ≤ 4 LLM calls |
| 2 — Logic/algorithm bugs | `suites/phase2.yaml` | ≥ 80% success, ≤ 3 retries |
| 3 — Multi-file refactoring | `suites/phase3.yaml` | ≥ 70% success; rollback fires correctly |
| 4 — Design pattern application | `suites/phase4.yaml` | ≥ 60% success |
| 5 — Feature addition from spec | `suites/phase5.yaml` | ≥ 40% success; ≥ 2 tree improvements identified |

---

## Design Principles

Before making structural or prompt changes, read:

- **`BT_DESIGN_PRINCIPLES.md`** — BT structural invariants (C&Ö), small-model
  coding task guidelines, retry loop feedback rules, and optimizer behavior rules.
  Contains the quick checklist for new or modified nodes.
- **`03_SWE_AGENT_CONVENTIONS.md`** — ACI/SWE-agent tool design patterns that
  motivated this project's interface choices.

---

## py-trees 2.4 Constraints

The tree engine uses generator-based ticking. Custom composites **must** implement `tick()` as a generator:
```python
def tick(self):
    # set up state
    for child in self.children:
        for node in child.tick():
            yield node
        if child.status == Status.FAILURE:
            self.status = Status.FAILURE
            return
    self.status = Status.SUCCESS
```
Do not use `update()` on composites — that's py-trees < 2.0 API.

---

## Environment

```
.venv/           Python venv — always use .venv/bin/python or .venv/bin/bt-agent
config/          default.yaml — runtime config
suites/          phase1-3.yaml + all.yaml — benchmark suites
tests/fixtures/  14 problem fixtures (Phase 1–3)
runs/            Benchmark output (git-ignored)
reports/         Generated Markdown reports
```

Model and API base are read from `.env` (copy `.env.example`). Override model per-run with `--model`.

---

## Recommended First Steps When Invoked

1. `cat reports/latest.md` — understand current state
2. Run preflight:
   - `curl -sS http://127.0.0.1:1234/v1/models`
   - confirm expected model id is available
   - ensure latest benchmark completed and produced `metrics.json`
3. Check `success_gate.passed` in `runs/<latest>/metrics.json`
4. If gate not passed: read `failure_modes` and pick the highest-count failure
5. Find one or two problematic trajectories in `runs/<latest>/<problem>/trial-1/trajectory.jsonl`
6. Read the relevant node source (`bt_agent/tree/nodes/`) and prompt (`bt_agent/llm/prompts.py`)
7. Make a targeted change; explain your reasoning before editing
8. Run `pytest tests/unit/ -q` to confirm no regressions
9. Run `./scripts/bench.sh --suite suites/phase1.yaml --tag fix-<description>` to validate
