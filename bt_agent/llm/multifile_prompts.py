"""
Prompt templates for multi-file editing nodes.

Follows the same conventions as prompts.py:
- f-strings only for THOUGHT_INSTRUCTION interpolation
- .format() placeholders are literal {key} strings
- JSON shape examples use {{ }} to produce literal braces after .format()
"""
from bt_agent.llm.prompts import THOUGHT_INSTRUCTION

EXTRACT_FILES_SYSTEM = "You are a multi-file code editing planner."

EXTRACT_FILES_USER = (
    f"{THOUGHT_INSTRUCTION}\n\n"
    "Given a task description and a repository map, identify:\n"
    "1. ALL files that need to be edited to complete this task (relative paths)\n"
    "2. A global plan: what changes are needed in each file and why\n"
    "3. A single-sentence summary of the overall goal\n\n"
    "Respond ONLY with JSON (no markdown fences):\n"
    '{{"file_edit_queue": ["path/to/a.py", "path/to/b.py"], '
    '"global_plan": "1. In a.py: rename foo to bar.\\n2. In b.py: update call sites.", '
    '"parsed_goal": "Rename function foo to bar across all files"}}\n\n'
    "Repository map:\n{repo_map}\n\nTask: {task_description}"
)

PLAN_FILE_CHANGES_SYSTEM = (
    "You are planning edits to a single file as part of a larger multi-file task."
)

PLAN_FILE_CHANGES_USER = (
    f"{THOUGHT_INSTRUCTION}\n\n"
    "Overall task plan:\n{global_plan}\n\n"
    "You are now planning edits to: {selected_file}\n\n"
    "Symbol index (symbol → files that define it):\n{symbol_summary}\n\n"
    "Other files being edited (previews):\n{other_files_summary}\n\n"
    "Current content of '{selected_file}':\n"
    "```\n{current_file_content}\n```\n\n"
    "Produce a plan for THIS file only:\n"
    "1. A step-by-step plan (2-5 steps)\n"
    "2. A single-sentence intent for this file's change\n\n"
    "Respond ONLY with JSON:\n"
    '{{"edit_plan": "1. ...\\n2. ...", "edit_intent": "..."}}'
)

MULTIFILE_COMMIT_MSG_SYSTEM = "Generate a git commit message for a multi-file change."

MULTIFILE_COMMIT_MSG_USER = (
    f"{THOUGHT_INSTRUCTION}\n\n"
    "Write a one-line conventional commit message (under 72 chars).\n"
    "Format: type(scope): description\n"
    "Types: fix, feat, refactor, chore\n\n"
    "Task summary: {global_plan}\n"
    "Files changed: {files_changed}\n\n"
    "Respond with ONLY the commit message string, no quotes."
)
