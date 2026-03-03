from __future__ import annotations

import py_trees

from bt_agent.tools.linter import validate_python


class ValidateEdit(py_trees.behaviour.Behaviour):
    def __init__(self, blackboard):
        super().__init__(name="ValidateEdit")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        if not self.bb.selected_file:
            self.bb.last_error = "ValidateEdit missing selected_file"
            self.bb.edit_attempts += 1
            return py_trees.common.Status.FAILURE

        path = self.bb.repo_path / self.bb.selected_file
        is_python = (self.bb.target_language or "").lower() == "python" or path.suffix == ".py"
        if not is_python:
            return py_trees.common.Status.SUCCESS

        ok, lint_output = validate_python(path)
        if ok:
            # Preserve warnings for observability but keep success.
            self.bb.last_error = lint_output or None
            return py_trees.common.Status.SUCCESS

        if self.bb.current_file_content is not None:
            path.write_text(self.bb.current_file_content, encoding="utf-8")
        self.bb.edit_attempts += 1
        self.bb.last_error = lint_output
        return py_trees.common.Status.FAILURE
