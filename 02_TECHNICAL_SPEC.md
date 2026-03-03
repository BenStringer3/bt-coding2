# BT-Agent: Technical Specification

## 1. Behavior Tree Structure

Assembled in `bt_agent/tree/builder.py`. Runs as one-shot: tick root until it returns `SUCCESS` or `FAILURE`. Does not tick continuously.

### Full Tree

```
Root  [Sequence]
├── UnderstandTask          [Leaf / LLM]
├── GatherContext           [Sequence]
│   ├── BuildRepoMap        [Leaf / deterministic]
│   └── LocateRelevantFiles [Leaf / LLM]
├── PlanEdits               [Leaf / LLM]
├── EditLoop                [Repeat-Until-Success, max_iterations=5]
│   └── EditAttempt         [Sequence]
│       ├── ReadTargetFile  [Leaf / deterministic]
│       ├── GenerateEdit    [Leaf / LLM]
│       ├── ApplyEdit       [Leaf / deterministic]
│       └── ValidateEdit    [Leaf / deterministic]
└── CommitChanges           [Sequence]
    ├── GenerateCommitMsg   [Leaf / LLM]
    └── GitCommit           [Leaf / deterministic]
```

### Return Semantics

- `SUCCESS` — completed correctly
- `FAILURE` — could not complete (triggers parent fallback or loop retry)
- `RUNNING` — not used in POC; all nodes complete synchronously

### Retry Logic

`EditLoop` is `py_trees.behaviours.Repeat` wrapping the EditAttempt Sequence. If the inner Sequence returns `FAILURE`, Repeat retries up to `max_iterations`. Retry count and last error are on the blackboard so subsequent ticks have context.

Do NOT implement retry inside individual leaf nodes. Let the tree handle it.

---

## 2. Blackboard Schema

Define as Pydantic model in `bt_agent/tree/blackboard.py`:

```python
class StrReplaceEdit(BaseModel):
    old_str: str
    new_str: str
    target_file: str  # relative path from repo root

class AgentBlackboard(BaseModel):
    # Input
    task_description: str
    repo_path: Path

    # Set by UnderstandTask
    parsed_goal: str | None = None
    target_language: str | None = None

    # Set by GatherContext
    repo_map: str | None = None
    candidate_files: list[str] = []
    selected_file: str | None = None

    # Set by PlanEdits
    edit_plan: str | None = None
    edit_intent: str | None = None

    # Set by EditLoop nodes
    current_file_content: str | None = None
    proposed_edit: StrReplaceEdit | None = None
    edit_attempts: int = 0
    last_error: str | None = None

    # Set by CommitChanges
    commit_message: str | None = None
    committed: bool = False
```

For POC: maintain a single `AgentBlackboard` instance and pass it to nodes at construction. This avoids py-trees' key-based blackboard complexity. Revisit if parallel subtrees are needed later.

---

## 3. Node Specifications

### 3.1 UnderstandTask (LLM leaf)

Reads: `task_description`
Writes: `parsed_goal`, `target_language`

```
System: You are a code editing assistant.
User:
Given this task description, extract:
1. A single clear sentence describing the code change needed
2. The programming language involved

Respond ONLY with JSON (no markdown fences):
{"parsed_goal": "...", "target_language": "python"}

Task: {task_description}
```

Returns FAILURE if: response is not valid JSON, or `parsed_goal` is empty.

---

### 3.2 BuildRepoMap (deterministic leaf)

Reads: `repo_path`
Writes: `repo_map`

Walk with `os.walk`. Skip: `.git`, `__pycache__`, `node_modules`, `.venv`, `dist`, `build`.
Max depth: 3. Max output: 200 lines (truncate with count of omitted files).

Format:
```
bt_agent/
  tree/
    builder.py
    nodes/
      edit.py
  tools/
    file_ops.py
```

Always returns SUCCESS.

---

### 3.3 LocateRelevantFiles (LLM leaf)

Reads: `repo_map`, `parsed_goal`
Writes: `candidate_files`, `selected_file`

```
System: You are a code navigation assistant.
User:
Given a repository map and a task, identify the 1-3 files most likely to need editing.
Pick the single most likely file as `selected_file`.

Respond ONLY with JSON:
{"candidate_files": ["path/to/file.py"], "selected_file": "path/to/file.py"}

Repository map:
{repo_map}

Task: {parsed_goal}
```

Returns FAILURE if: JSON invalid, `selected_file` doesn't exist on disk, or no files identified.

---

### 3.4 PlanEdits (LLM leaf)

Reads: `parsed_goal`, `selected_file`, first 100 lines of selected file (read directly, not from blackboard)
Writes: `edit_plan`, `edit_intent`

```
System: You are planning a code edit.
User:
Given a task and the beginning of a file, produce:
1. A step-by-step plan (2-5 steps)
2. A single-sentence intent summary

Respond ONLY with JSON:
{"edit_plan": "1. ...\n2. ...", "edit_intent": "..."}

Task: {parsed_goal}
File: {selected_file}
File content (first 100 lines):
{file_preview}
```

Returns FAILURE if: JSON invalid or `edit_intent` empty.

---

### 3.5 ReadTargetFile (deterministic leaf)

Reads: `selected_file`, `repo_path`
Writes: `current_file_content`

Simple `Path.read_text()`. Runs on every edit loop iteration for fresh content.
Returns FAILURE only if file doesn't exist.

---

### 3.6 GenerateEdit (LLM leaf)

Reads: `current_file_content`, `edit_intent`, `edit_plan`, `edit_attempts`, `last_error`
Writes: `proposed_edit`

Base prompt:
```
System: You are a code editor. Generate a str_replace edit.

Rules for old_str:
- Must be an EXACT substring of the file (including all whitespace and indentation)
- Must appear exactly ONCE in the file
- Include enough context lines (3-5) to be unique

Rules for new_str:
- Complete replacement for old_str
- Preserve surrounding indentation style
- Minimal change — only what is necessary

Respond ONLY with JSON (no markdown, no explanation):
{"old_str": "...", "new_str": "...", "target_file": "{selected_file}"}

User:
Task: {edit_intent}

Plan:
{edit_plan}

File content:
{current_file_content}
```

Retry addition (appended when `edit_attempts > 0`):
```
Your previous attempt failed:
Error: {last_error}

Try again. Common fixes:
- Check that old_str exactly matches the file including spaces and newlines
- Make old_str longer to ensure uniqueness
- Check indentation carefully (spaces vs tabs)
```

Returns FAILURE if: JSON invalid, required fields missing, or `old_str`/`new_str` empty.

---

### 3.7 ApplyEdit (deterministic leaf)

Reads: `proposed_edit`, `repo_path`
Writes: file on disk; sets `last_error` on failure

```python
def str_replace(repo_path: Path, edit: StrReplaceEdit) -> tuple[bool, str]:
    filepath = repo_path / edit.target_file
    content = filepath.read_text()
    count = content.count(edit.old_str)
    if count == 0:
        return False, f"old_str not found in {edit.target_file}. Check exact whitespace."
    if count > 1:
        return False, f"old_str found {count} times — it must be unique. Make old_str longer."
    new_content = content.replace(edit.old_str, edit.new_str, 1)
    filepath.write_text(new_content)
    return True, ""
```

Returns FAILURE if: count == 0, count > 1, or write fails. Does NOT write partial content on failure.

---

### 3.8 ValidateEdit (deterministic leaf)

Reads: `selected_file`, `repo_path`, `current_file_content` (pre-edit, for revert)
Writes: increments `edit_attempts`; sets `last_error` with lint output; reverts file on failure

```python
def validate_python(filepath: Path) -> tuple[bool, str]:
    source = filepath.read_text()
    try:
        ast.parse(source)
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"
    return True, ""
```

On FAILURE:
1. Write `current_file_content` back to disk (revert)
2. Increment `blackboard.edit_attempts`
3. Set `blackboard.last_error` to lint output
4. Return FAILURE

On SUCCESS: return SUCCESS (file stays on disk as-is).

Language detection: check `target_language` on blackboard. Only run Python AST check for Python files. For other languages, skip lint and return SUCCESS for POC (can extend later).

---

### 3.9 GenerateCommitMsg (LLM leaf)

Reads: `edit_intent`, `selected_file`
Writes: `commit_message`

```
System: Generate a git commit message.
User:
Write a one-line conventional commit message (under 72 chars).
Format: type(scope): description
Types: fix, feat, refactor, chore

Change: {edit_intent}
File: {selected_file}

Respond with ONLY the commit message string.
```

Returns FAILURE if: response empty or over 200 chars.

---

### 3.10 GitCommit (deterministic leaf)

Reads: `repo_path`, `selected_file`, `commit_message`
Writes: `committed = True`

```python
def stage_and_commit(repo_path: Path, file_path: str, message: str) -> tuple[bool, str]:
    try:
        repo = git.Repo(repo_path)
        repo.index.add([file_path])
        repo.index.commit(message)
        return True, ""
    except git.exc.InvalidGitRepositoryError:
        return False, "Not a git repository"
    except Exception as e:
        return False, str(e)
```

Returns FAILURE if: not a git repo, nothing staged, or commit fails.
In `--dry-run` mode: skip this node entirely (return SUCCESS without committing).

---

## 4. LLM Client (`bt_agent/llm/client.py`)

All LLM calls go through this. No direct LiteLLM calls in node code.

```python
class LLMClient:
    def __init__(self, model: str, temperature: float = 0.0, max_tokens: int = 2048):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def call(self, system: str, user: str) -> str:
        response = litellm.completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content

    def call_json(self, system: str, user: str) -> dict:
        raw = self.call(system, user)
        # Strip markdown code fences
        cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned)
        return json.loads(cleaned)
```

Config (`config/default.yaml`):
```yaml
model: ollama/qwen2.5-coder:7b
temperature: 0.0
max_tokens: 2048
max_edit_attempts: 5
window_size: 100
window_overlap: 2
```

Override with env var: `BT_AGENT_MODEL`.

---

## 5. Trajectory Logger (`bt_agent/logging/trajectory.py`)

Log every node tick to JSONL:

```json
{
  "timestamp": "2025-03-03T12:00:00Z",
  "node": "GenerateEdit",
  "status": "SUCCESS",
  "blackboard_snapshot": { "edit_attempts": 1, "last_error": null, "...": "..." },
  "llm_call": {
    "prompt_tokens": 412,
    "completion_tokens": 88,
    "raw_response": "..."
  },
  "error": null
}
```

`llm_call` is null for deterministic nodes.

Wire via py-trees visitor:

```python
class TrajectoryLogger(py_trees.visitors.VisitorBase):
    def __init__(self, output_path: Path):
        self.f = open(output_path, "a")

    def run(self, behaviour) -> None:
        entry = build_log_entry(behaviour)
        self.f.write(json.dumps(entry) + "\n")
        self.f.flush()
```

The base LLM node class stores its last call metadata as an instance attribute so the visitor can read it.

---

## 6. CLI (`bt_agent/cli.py`)

```
bt-agent run \
  --task "Fix the off-by-one error in list slicing" \
  --repo ./path/to/repo \
  [--model ollama/qwen2.5-coder:7b] \
  [--output ./trajectory.jsonl] \
  [--dry-run] \
  [--max-attempts 5]
```

Terminal output via `rich`:
1. Print behavior tree structure at start (py-trees ascii render)
2. Live node status as ticks complete (SUCCESS=green, FAILURE=red)
3. Final unified diff of all changes

---

## 7. File Ops Windowed View (`bt_agent/tools/file_ops.py`)

```python
def read_windowed(filepath: Path, start_line: int = 1,
                  window: int = 100, overlap: int = 2) -> str:
    lines = filepath.read_text().splitlines()
    total = len(lines)
    start = max(0, start_line - 1)
    end = min(total, start + window)

    header = f"[File: {filepath} ({total} lines total)]\n"
    if start > 0:
        header += f"[Lines {start+1}-{end} shown. Lines 1-{start} omitted.]\n"
    else:
        header += f"[Lines 1-{end} shown.]\n"

    body = "\n".join(
        f"{i + start + 1}: {line}"
        for i, line in enumerate(lines[start:end])
    )

    if end < total:
        body += f"\n[... {total - end} more lines not shown]"

    return header + body
```

---

## 8. Testing

### Unit tests
- `test_file_ops.py` — str_replace: not found, multiple matches, empty file, correct replace
- `test_linter.py` — valid Python, SyntaxError, valid with warnings
- `test_blackboard.py` — Pydantic validation, serialization round-trip
- `test_llm_client.py` — JSON parsing, code fence stripping (mock LiteLLM)
- `test_nodes.py` — each deterministic node in isolation with a mock blackboard

### Integration tests
Small synthetic repos in `tests/fixtures/`. Each has one known simple bug.
Run with: `BT_AGENT_INTEGRATION=1 pytest tests/integration/`

Fixtures:
- `fixtures/off_by_one/` — list index error
- `fixtures/wrong_operator/` — `>` should be `>=`
- `fixtures/missing_return/` — function returns None incorrectly

---

## 9. Open Design Questions

1. **py-trees blackboard vs custom**: py-trees 2.x has built-in key-based blackboard. Custom Pydantic model is simpler for POC. Either works.
2. **Async**: LiteLLM supports async. Synchronous is fine for POC.
3. **Multi-file**: Tree supports single-file only. `candidate_files` list is scaffolded for future extension.
4. **pyflakes strictness**: Only AST syntax errors block edits for now. Pyflakes warnings are logged only.
