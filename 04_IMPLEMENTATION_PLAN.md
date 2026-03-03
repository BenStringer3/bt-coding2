# BT-Agent: Implementation Plan

This is the step-by-step build order for the coding agent. Read `01_PROJECT_OVERVIEW.md`, `02_TECHNICAL_SPEC.md`, and `03_SWE_AGENT_CONVENTIONS.md` before starting. This plan is written so each phase produces something runnable.

---

## Phase 0: Project Scaffolding

**Goal**: Repo exists with correct structure, dependencies install, and `bt-agent --help` runs.

Tasks:
1. Initialize repo with `pyproject.toml` using the dependency list from `01_PROJECT_OVERVIEW.md`
2. Create all package directories and `__init__.py` files per the structure in `01_PROJECT_OVERVIEW.md`
3. Create `config/default.yaml` with the values from Section 4 of `02_TECHNICAL_SPEC.md`
4. Implement the `cli.py` entrypoint (Click) with `run` command and all flags — stub the actual execution for now
5. Verify: `pip install -e .` and `bt-agent --help` shows the command and options

**Done when**: `bt-agent --help` works and shows all flags.

---

## Phase 1: Blackboard + Tools (no LLM, no tree)

**Goal**: The data model and file/git tools work correctly in isolation.

Tasks:
1. Implement `bt_agent/tree/blackboard.py` — `StrReplaceEdit` and `AgentBlackboard` Pydantic models
2. Implement `bt_agent/tools/file_ops.py`:
   - `read_windowed(filepath, start_line, window, overlap)` → formatted string
   - `str_replace(repo_path, edit)` → `(bool, str)`
3. Implement `bt_agent/tools/repo_map.py`:
   - `build_repo_map(repo_path, max_depth=3, max_lines=200)` → string
4. Implement `bt_agent/tools/linter.py`:
   - `validate_python(filepath)` → `(bool, str)` using `ast.parse`
5. Implement `bt_agent/tools/git_ops.py`:
   - `stage_and_commit(repo_path, file_path, message)` → `(bool, str)`
6. Write unit tests for all tools (see Section 8 of `02_TECHNICAL_SPEC.md`)
   - Create `tests/fixtures/off_by_one/` as a minimal git repo with one known bug

**Done when**: All unit tests pass. `str_replace` handles not-found, multiple-match, and success cases correctly. `validate_python` catches `SyntaxError`.

---

## Phase 2: LLM Client

**Goal**: LLM calls work against both a local Ollama model and a cloud API.

Tasks:
1. Implement `bt_agent/llm/client.py` — `LLMClient` with `call()` and `call_json()` as specified in Section 4 of `02_TECHNICAL_SPEC.md`
2. Implement `bt_agent/llm/prompts.py` — all prompt templates as named constants (see conventions in `03_SWE_AGENT_CONVENTIONS.md`)
3. Write unit tests for `call_json()`:
   - Test code fence stripping (` ```json ... ``` `)
   - Test plain JSON response
   - Test invalid JSON raises `ValueError`
   - Mock LiteLLM so tests don't need a real API key

**Done when**: `call_json()` correctly strips fences and parses JSON from mocked responses. Client instantiates with `ollama/qwen2.5-coder:7b` without errors.

---

## Phase 3: Base Node Class + Trajectory Logger

**Goal**: The infrastructure that all nodes share is in place.

Tasks:
1. Implement `bt_agent/tree/nodes/base.py`:
   - `BaseLLMNode(py_trees.behaviour.Behaviour)` — abstract base for LLM leaf nodes
   - Constructor takes `blackboard: AgentBlackboard` and `llm: LLMClient`
   - Abstract method `update()` — subclasses implement this
   - Helper: `_call_llm_json(system, user)` — wraps `llm.call_json()`, extracts `<thought>` block, stores call metadata for logger
   - Stores `last_llm_call` as instance attribute (prompt tokens, completion tokens, raw response, thought)

2. Implement `bt_agent/logging/trajectory.py`:
   - `TrajectoryLogger(py_trees.visitors.VisitorBase)` — JSONL writer
   - Log entry format per Section 5 of `02_TECHNICAL_SPEC.md`
   - `blackboard_snapshot` should be the full dict of non-None blackboard fields

3. Wire the logger: the `run()` method of the visitor reads `behaviour.last_llm_call` if present (set by `BaseLLMNode`), else `llm_call` is null.

**Done when**: A trivial subclass of `BaseLLMNode` can be instantiated and ticked, and the logger writes a valid JSONL entry for it.

---

## Phase 4: Deterministic Nodes

**Goal**: All non-LLM nodes are implemented and individually testable.

Tasks (implement and unit test each):
1. `BuildRepoMap` — calls `build_repo_map()`, writes to blackboard, always returns SUCCESS
2. `ReadTargetFile` — reads file content into blackboard
3. `ApplyEdit` — calls `str_replace()`, writes error to blackboard on failure
4. `ValidateEdit` — calls `validate_python()`, reverts file and increments `edit_attempts` on failure
5. `GitCommit` — calls `stage_and_commit()`, respects `--dry-run` flag (pass dry_run bool at construction)

Test each node with a mock blackboard containing the minimum required fields.

**Done when**: Each deterministic node passes its unit tests, including failure paths (bad file, syntax error, not a git repo).

---

## Phase 5: LLM Nodes

**Goal**: All LLM-powered nodes are implemented.

Tasks (implement each, test with mocked LLM client):
1. `UnderstandTask` — uses `UNDERSTAND_TASK_*` prompts, writes `parsed_goal` and `target_language`
2. `LocateRelevantFiles` — uses `LOCATE_FILES_*` prompts, validates that `selected_file` exists on disk
3. `PlanEdits` — uses `PLAN_EDITS_*` prompts, reads first 100 lines of selected file directly
4. `GenerateEdit` — uses `GENERATE_EDIT_*` prompts, handles retry case when `edit_attempts > 0`
5. `GenerateCommitMsg` — uses `COMMIT_MSG_*` prompts

For each node, test:
- Happy path (valid JSON response → SUCCESS)
- Invalid JSON response → FAILURE
- Missing required fields in JSON → FAILURE
- (For GenerateEdit) Retry prompt is used when `edit_attempts > 0`

**Done when**: All LLM nodes pass their tests with mocked responses.

---

## Phase 6: Tree Assembly

**Goal**: The behavior tree is assembled and ticks correctly end-to-end with mocked nodes.

Tasks:
1. Implement `bt_agent/tree/builder.py`:
   - `build_tree(blackboard, llm, dry_run)` → returns root `py_trees.behaviour.Behaviour`
   - Assembles the exact structure from Section 1 of `02_TECHNICAL_SPEC.md`
   - `EditLoop` is `py_trees.behaviours.Repeat(child=EditAttempt, num_success=1, num_failure=max_attempts)`

2. Wire the `TrajectoryLogger` visitor to the tree root

3. Implement the `run` command in `cli.py`:
   - Load config (YAML + CLI overrides)
   - Instantiate `AgentBlackboard`, `LLMClient`, `TrajectoryLogger`
   - Call `build_tree()`, add visitor
   - Tick the tree until SUCCESS or FAILURE: `while tree.root.status == RUNNING or tick_count == 0: tree.tick()`
   - Print final status and diff to terminal with `rich`

4. Write a tree assembly test: instantiate the full tree with mock nodes, run it, verify each node was visited in the expected order.

**Done when**: The tree can be assembled and ticked with mock nodes that always return SUCCESS, completing all nodes in order.

---

## Phase 7: Integration Test

**Goal**: The full system works end-to-end on a real (small) task with a real LLM.

Tasks:
1. Create `tests/fixtures/off_by_one/` — a minimal Python git repo with a simple bug:
   ```python
   # bug: should be range(len(items) - 1), not range(len(items))
   def get_pairs(items):
       return [(items[i], items[i+1]) for i in range(len(items))]
   ```
2. Run: `bt-agent run --task "Fix the IndexError in get_pairs" --repo tests/fixtures/off_by_one --dry-run --model ollama/qwen2.5-coder:7b`
3. Verify:
   - Tree completes with SUCCESS
   - `proposed_edit.old_str` is found in the file
   - `proposed_edit.new_str` fixes the bug
   - Trajectory JSONL is written and readable
   - `--dry-run` means no git commit was made

**Done when**: Integration test passes on at least one fixture with a local Ollama model.

---

## Phase 8: Polish

**Goal**: The CLI output is readable and the project is documented.

Tasks:
1. Rich terminal output:
   - Print tree structure at start using `py_trees.display.ascii_tree(root)`
   - Show node name + status (color coded) as each tick completes
   - Show final unified diff using `difflib.unified_diff`
2. Write `README.md`:
   - Installation (`pip install -e .`)
   - Quickstart (run against a local repo)
   - Config options
   - How to add a new node
3. Add `--verbose` flag that prints full blackboard state after each node

**Done when**: Running the tool looks clean in a terminal and README covers the basics.

---

## Build Order Summary

```
Phase 0: Scaffolding          → bt-agent --help works
Phase 1: Blackboard + Tools   → All unit tests pass
Phase 2: LLM Client           → JSON parsing works with mock
Phase 3: Base Node + Logger   → Infrastructure in place
Phase 4: Deterministic Nodes  → File/git nodes tested
Phase 5: LLM Nodes            → All nodes tested with mock LLM
Phase 6: Tree Assembly        → Full tree ticks with mock nodes
Phase 7: Integration Test     → Real task, real LLM, --dry-run passes
Phase 8: Polish               → Good CLI output, README written
```

Each phase is a clean stopping point. Do not start Phase N+1 if Phase N's tests are failing.

---

## Implementation Notes

- **Temperature = 0.0** for all LLM calls. Determinism is more important than creativity here.
- **Never hardcode model name** outside of `config/default.yaml` and the `--model` CLI flag.
- **No print statements** in node/tool code. Use Python `logging` module. The CLI controls output via `rich`.
- **All file paths on blackboard** are relative to `repo_path`. Absolute paths only in tool functions.
- **Git operations require a clean working tree** before starting. Add a pre-flight check in the `run` command: warn (not fail) if there are uncommitted changes.
- **The `edit_attempts` counter must increment before returning FAILURE** from `ValidateEdit`. If it doesn't, the retry prompt won't include the right attempt number.
