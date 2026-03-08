# Agent Harness Testing Roadmap

This document defines the staged problem roadmap for validating the bt-agent behavior tree
harness. Each phase tests a distinct capability tier. A phase must meet its **success gate**
before the next phase is treated as meaningful signal.

---

## How to Read This Document

- **Phase N** = a distinct capability tier (syntax → logic → multi-file → design → feature)
- **Success gate** = quantitative criteria the harness must meet across all phase problems
- **Fixture path** = `tests/fixtures/<id>/` — contains source files, `problem.yaml`, and `test_solution.py`
- **Suite file** = `suites/phase<N>.yaml` — machine-readable problem list used by `bench.sh`

---

## Phase 1 — Single-File, Syntactic & Obvious Bugs

**Goal:** Confirm the harness can locate, edit, and validate clear, local, single-edit fixes.
Problems are unambiguous; the correct fix is self-evident from the error message or docstring.

**Tree:** `run` (single-file)

| ID | Fixture | Bug Type | Description |
|----|---------|----------|-------------|
| P1-A | `off_by_one` | Index error | `range(len(items))` → `range(len(items) - 1)` |
| P1-B | `missing_return` | Missing statement | `compute_discount` computes but never `return`s |
| P1-C | `wrong_operator` | Off-by-one predicate | `> 0` should be `>= 0` in `is_valid_age` |
| P1-D | `typo_in_variable` | Name typo | `recieved_at` → `received_at` |
| P1-E | `unused_import_error` | Bad import name | `ChainMapp` → `ChainMap` in collections import |
| P1-F | `indentation_error` | Syntax | Over-indented `elif` branch body |

### Success Gate (Phase 1)

| Criterion | Threshold |
|-----------|-----------|
| Success rate (committed=True) | **≥ 90%** |
| Avg EditLoop retries per run | ≤ 2 |
| Avg total LLM calls per run | ≤ 4 |
| `ValidateEdit` false-positive rate | 0% |

### What This Validates

- `UnderstandTask` → `LocateRelevantFiles` path is stable
- `GenerateEdit` produces valid `old_str` on first or second attempt
- `ValidateEdit` (AST + pyflakes) correctly gates bad edits
- `GitCommit` fires correctly after a successful edit

---

## Phase 2 — Single-File, Logic & Algorithm Bugs

**Goal:** Confirm the harness can reason about *what* code should do (semantics), not just
*how it looks* (syntax). Bugs require understanding docstrings, examples, or intended behavior.

**Tree:** `run` (single-file)

| ID | Fixture | Bug Type | Description |
|----|---------|----------|-------------|
| P2-A | `sort_direction` | Wrong algorithm variant | `sorted()` ascending instead of `reverse=True` |
| P2-B | `missing_edge_case` | Missing guard | `average([])` raises `ZeroDivisionError`; should return `0.0` |
| P2-C | `wrong_accumulator` | Wrong variable in loop | Accumulates `item['qty']` instead of `price × qty` |
| P2-D | `incorrect_recursion` | Bad base case | `factorial` base is `n==1`, breaks on `n==0` |
| P2-E | `state_mutation_bug` | Mutable default arg | `def f(lst=[])` — state leaks across calls |
| P2-F | `integer_division` | Wrong operator | `//` (floor div) should be `/` (true div) |

### Success Gate (Phase 2)

| Criterion | Threshold |
|-----------|-----------|
| Success rate | **≥ 80%** |
| Avg EditLoop retries per run | ≤ 3 |
| Avg total tokens per run | ≤ 1,500 |
| No Phase 1 regressions | required |

### What This Validates

- `PlanEdits` produces a useful plan (not just "fix the bug")
- `edit_intent` from `PlanEdits` meaningfully guides `GenerateEdit`
- Retry prompts with `last_error` measurably help (compare first-attempt vs retry success rate)
- The harness can distinguish docstring-described intent from code behavior

---

## Phase 3 — Multi-File Refactoring

**Goal:** Validate the multi-file tree's dependency ordering, cross-file consistency checks,
and rollback. Problems touch 2–4 files in a consistent way.

**Tree:** `run-multi` (multi-file)

| ID | Fixture | Files | Description |
|----|---------|-------|-------------|
| P3-A | `rename_across_files` | 2 | Rename `compute_total` → `sum_items` in `utils.py` + `main.py` |
| P3-B | `config_to_dataclass` | 3 | `CONFIG` dict → frozen `@dataclass` across `config.py`, `server.py`, `client.py` |

*Additional fixtures to be added as Phase 2 gate is cleared:*

| ID | Fixture (planned) | Files | Description |
|----|-------------------|-------|-------------|
| P3-C | `extract_constant` | 3 | Magic number → `constants.py`, update all references |
| P3-D | `add_parameter` | 4 | Add `timeout=None` param; update all call sites |
| P3-E | `split_module` | 3 | Split one large module into two; fix all imports |
| P3-F | `rename_class` | 4 | Rename class + update all instantiation sites |
| P3-G | `remove_dead_code` | 2 | Delete unused function + remove from `__init__` exports |

### Success Gate (Phase 3)

| Criterion | Threshold |
|-----------|-----------|
| Success rate (all files consistent) | **≥ 70%** |
| `CheckImportConsistency` passes on all successful runs | required |
| `CheckCircularDependencies` passes on all successful runs | required |
| Rollback fires correctly on at least 1 forced failure | required |
| `file_edit_queue` order respects dependency graph | verifiable from trajectory |

### What This Validates

- `BuildDependencyGraph` + `PrioritizeEditOrder` produce a correct edit ordering
- Per-file plan (`PlanFileChanges`) is aware of changes in other files
- `ResolveConflicts` node handles cross-file symbol collisions
- `FinalizeOrRollback` correctly restores snapshots when validation fails

---

## Phase 4 — Design Pattern Application & Interface Changes

**Goal:** Confirm the harness can apply structured design decisions from a natural language
description. No obvious "bug" — the existing code works, but needs restructuring.

**Tree:** `run` or `run-multi` depending on scope

| ID | Fixture (planned) | Description |
|----|-------------------|-------------|
| P4-A | `add_protocol` | Extract implicit interface to `typing.Protocol` class |
| P4-B | `strategy_pattern` | Replace `if/elif` dispatch with a strategy dict |
| P4-C | `dependency_injection` | Hardcoded dep → constructor parameter |
| P4-D | `add_dataclass` | Plain dict return → `@dataclass` |
| P4-E | `factory_function` | Scattered `MyClass(...)` → `create_*` factory |
| P4-F | `context_manager` | Manual open/close → `__enter__`/`__exit__` |

### Success Gate (Phase 4)

| Criterion | Threshold |
|-----------|-----------|
| Success rate (provided tests pass) | **≥ 60%** |
| At least 1 problem solved via retry (demonstrating retry value) | required |
| No regressions on Phase 1–3 | required |

### What This Validates

- `PlanEdits` output guides *multi-step* changes, not just single-line fixes
- The harness can operate on code that is syntactically valid but semantically incomplete
- `ValidateEdit` does not over-reject structurally correct partial changes

---

## Phase 5 — Feature Addition from Natural Language Spec

**Goal:** The hardest tier. Requirements are open-ended; no "bug" to find — the agent must
*add* functionality based on a description of desired behavior.

**Tree:** `run` or `run-multi`

| ID | Fixture (planned) | Description |
|----|-------------------|-------------|
| P5-A | `add_logging` | Add `logging` calls to all public functions |
| P5-B | `add_cli` | Add `click`-based CLI to a library-only module |
| P5-C | `add_pagination` | Add `limit`/`offset` params to a data-fetching function |
| P5-D | `add_retry_decorator` | Wrap `requests.get(...)` calls with exponential backoff |
| P5-E | `add_type_hints` | Add `mypy`-compatible type hints to all signatures |
| P5-F | `add_async` | Convert sync I/O to `async`/`await` with caller updates |

### Success Gate (Phase 5)

| Criterion | Threshold |
|-----------|-----------|
| Success rate (provided tests pass) | **≥ 40%** |
| Failures produce analyzable trajectories | required |
| ≥ 2 tree improvements identified from failure patterns | required |

### What This Validates

- The harness's upper capability ceiling at current tree design
- Which failure patterns (context overflow, vague planning, bad edit targeting) dominate
- What new tree nodes or phases are needed for the next harness iteration

---

## Evaluation Framework

### Script Overview

```
scripts/
  bench.sh            # Run a suite → runs/<id>/{manifest,results}.json
  bench-analyze.py    # Parse trajectories → runs/<id>/metrics.json
  bench-report.py     # Generate Markdown → reports/<ts>-summary.md
  # Iterative tuning is driven by the active TUI frontier agent session
  # (Codex/Claude): bench → analyze/report → inspect trajectories → edit bt-agent → rerun
  run-problem.sh      # Interactive single-problem runner (unchanged)
  collect-logs.sh     # Human-readable log formatter (unchanged)
```

### Typical Workflow

```bash
# 1. Run Phase 1 benchmark (1 trial per problem)
./scripts/bench.sh --suite suites/phase1.yaml --tag p1-baseline

# 2. View the auto-generated report
cat reports/latest.md

# 3. Run iterative tuning in your active TUI agent session
#    Each iteration: bench → analyze/report → inspect trajectories → edit bt-agent → rerun
./scripts/bench.sh --suite suites/phase1.yaml --tag p1-iter1 --runs-per-problem 1

# 4. Check cumulative progress
cat reports/progress.md

# 5. Once Phase 1 gate passes, move to Phase 2
./scripts/bench.sh --suite suites/phase2.yaml --tag p2-baseline

# 6. Run the full regression suite after harness changes
./scripts/bench.sh --suite suites/all.yaml --tag regression
```

### Directory Layout After a Bench Run

```
runs/
  20240315-143022-p1-baseline/
    manifest.json               ← suite, model, config snapshot
    results.json                ← aggregated pass/fail per trial
    metrics.json                ← token counts, retry rates, failure modes
    off_by_one/
      trial-1/
        buggy.py                ← cloned fixture
        trajectory.jsonl        ← full node trace
        agent.log               ← bt-agent stdout
        diff.patch              ← git diff from initial state
        result.json             ← {success, exit_code, wall_time_s, ...}
    missing_return/
      trial-1/
        ...
reports/
  20240315-143022-p1-baseline-summary.md   ← per-run Markdown report
  latest.md                                ← symlink to most recent report
  progress.md                              ← cumulative one-line-per-run table
```

### metrics.json Structure

```json
{
  "run_id": "20240315-143022-p1-baseline",
  "suite_name": "Phase 1 — Single-File Syntactic & Obvious Bugs",
  "summary": {
    "total_trials": 6,
    "passed": 5,
    "success_rate": 0.833,
    "avg_retries": 1.2,
    "avg_tokens": 980,
    "avg_wall_time_s": 38.4,
    "avg_llm_calls": 3.8
  },
  "per_problem": { "off_by_one": { "success_rate": 1.0, ... }, ... },
  "failure_modes": { "ApplyEdit.old_str_not_found": 1 },
  "success_gate": { "passed": false, "actual_success_rate": 0.833, ... },
  "recommendations": [
    "1 failure in ApplyEdit.old_str_not_found — consider using shorter old_str excerpts."
  ]
}
```

---

## Implementation Status

| Item | Status |
|------|--------|
| Phase 1 fixtures (P1-A through P1-F) | ✅ Complete |
| Phase 2 fixtures (P2-A through P2-F) | ✅ Complete |
| Phase 3 fixtures (P3-A, P3-B) | ✅ Complete (others planned) |
| `suites/phase1.yaml` | ✅ Complete |
| `suites/phase2.yaml` | ✅ Complete |
| `suites/phase3.yaml` | ✅ Complete (P3-A, P3-B only) |
| `suites/all.yaml` | ✅ Complete |
| `scripts/bench.sh` | ✅ Complete |
| `scripts/bench-analyze.py` | ✅ Complete |
| `scripts/bench-report.py` | ✅ Complete |
| TUI-agent-driven iterative tuning workflow | ✅ Complete |
| Phase 4 fixtures | 🔲 Planned (after Phase 3 gate) |
| Phase 5 fixtures | 🔲 Planned (after Phase 4 gate) |
| Additional P3 fixtures (C–G) | 🔲 Planned (after Phase 2 gate) |

---

## Design Principles for Future Fixtures

1. **One clear bug per fixture.** Compound bugs mask which tree node failed.
2. **Docstring-driven ground truth.** The expected behavior is stated in the source, not assumed.
3. **`test_solution.py` is the oracle.** Every fixture ships pytest tests that define "correct."
4. **Minimal surface area.** Fixtures are 10–50 lines. Large files slow the model and obscure failures.
5. **No external dependencies.** Fixtures use only stdlib so they run without network access.
6. **Phase gating.** Do not invest time building Phase N+1 fixtures until Phase N gate clears —
   failure patterns at N may reshape the problems needed at N+1.
