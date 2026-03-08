THOUGHT_INSTRUCTION = (
    "Before responding, write your reasoning in <thought>...</thought> tags. "
    "Then provide your final answer in the required format."
)

UNDERSTAND_TASK_SYSTEM = "You are a code editing assistant."
UNDERSTAND_TASK_USER = (
    f"{THOUGHT_INSTRUCTION}\n\n"
    "Given this task description, extract:\n"
    "1. A single clear sentence describing the code change needed\n"
    "2. The programming language involved\n\n"
    "Respond ONLY with JSON (no markdown fences):\n"
    '{{"parsed_goal": "...", "target_language": "python"}}\n\n'
    "Task: {task_description}"
)

LOCATE_FILES_SYSTEM = "You are a code navigation assistant."
LOCATE_FILES_USER = (
    f"{THOUGHT_INSTRUCTION}\n\n"
    "Given a repository map and a task, identify the 1-3 files most likely to need editing.\n"
    "Pick the single most likely file as selected_file.\n\n"
    "Respond ONLY with JSON:\n"
    '{{"candidate_files": ["path/to/file.py"], "selected_file": "path/to/file.py"}}\n\n'
    "Repository map:\n{repo_map}\n\nTask: {parsed_goal}"
)

PLAN_EDITS_SYSTEM = "You are planning a code edit."
PLAN_EDITS_USER = (
    f"{THOUGHT_INSTRUCTION}\n\n"
    "Given a task and the beginning of a file, produce:\n"
    "1. A step-by-step plan (2-5 steps)\n"
    "2. A single-sentence intent summary\n\n"
    "Respond ONLY with JSON:\n"
    '{{"edit_plan": "1. ...\\n2. ...", "edit_intent": "..."}}\n\n'
    "Task: {parsed_goal}\n"
    "File: {selected_file}\n"
    "File content (first 100 lines):\n{file_preview}"
)

GENERATE_EDIT_SYSTEM = "You are a code editor. Generate a str_replace edit."
GENERATE_EDIT_USER = (
    "Do not output reasoning or <thought>/<think> tags. Return JSON only.\n\n"
    "Rules for old_str:\n"
    "- Must be an EXACT substring of the file (including all whitespace and indentation)\n"
    "- Must appear exactly ONCE in the file\n"
    "- Prefer the SHORTEST unique snippet (usually 1 line, sometimes 2)\n"
    "- Never use identifier-only snippets like variable names; prefer a full line\n"
    "- If a token appears multiple times, include surrounding syntax so old_str is unique\n"
    "- Do NOT include unrelated surrounding lines\n\n"
    "Rules for new_str:\n"
    "- Complete replacement for old_str\n"
    "- Preserve surrounding indentation style\n"
    "- Minimal change - only what is necessary\n\n"
    "Respond ONLY with JSON (no markdown, no explanation):\n"
    '{{"old_str": "...", "new_str": "...", "target_file": "{selected_file}"}}\n\n'
    "Task: {edit_intent}\n\nPlan:\n{edit_plan}\n\nFile content:\n{current_file_content}"
)

GENERATE_EDIT_RETRY_ADDITION = (
    "\n\nYour previous attempt failed:\n"
    "Error: {last_error}\n\n"
    "Try again. Common fixes:\n"
    "- Check that old_str exactly matches the file including spaces and newlines\n"
    "- If old_str was not found, make old_str shorter and more exact\n"
    "- Check indentation carefully (spaces vs tabs)"
)

COMMIT_MSG_SYSTEM = "Generate a git commit message."
COMMIT_MSG_USER = (
    f"{THOUGHT_INSTRUCTION}\n\n"
    "Write a one-line conventional commit message (under 72 chars).\n"
    "Format: type(scope): description\n"
    "Types: fix, feat, refactor, chore\n\n"
    "Change: {edit_intent}\n"
    "File: {selected_file}\n\n"
    "Respond with ONLY the commit message string."
)
