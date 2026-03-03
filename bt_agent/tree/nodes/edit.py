from __future__ import annotations

import py_trees

from bt_agent.llm.prompts import GENERATE_EDIT_RETRY_ADDITION, GENERATE_EDIT_SYSTEM, GENERATE_EDIT_USER
from bt_agent.tools.file_ops import str_replace
from bt_agent.tree.blackboard import StrReplaceEdit
from bt_agent.tree.nodes.base import BaseLLMNode


class ReadTargetFile(py_trees.behaviour.Behaviour):
    def __init__(self, blackboard):
        super().__init__(name="ReadTargetFile")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        if not self.bb.selected_file:
            self.bb.last_error = "ReadTargetFile missing selected_file"
            self.bb.edit_attempts += 1
            return py_trees.common.Status.FAILURE

        path = self.bb.repo_path / self.bb.selected_file
        if not path.exists():
            self.bb.last_error = f"ReadTargetFile file does not exist: {self.bb.selected_file}"
            self.bb.edit_attempts += 1
            return py_trees.common.Status.FAILURE

        self.bb.current_file_content = path.read_text(encoding="utf-8")
        return py_trees.common.Status.SUCCESS


class GenerateEdit(BaseLLMNode):
    def __init__(self, blackboard, llm):
        super().__init__("GenerateEdit", blackboard, llm)

    def update(self) -> py_trees.common.Status:
        required = [self.bb.current_file_content, self.bb.edit_intent, self.bb.edit_plan, self.bb.selected_file]
        if any(item is None for item in required):
            self.bb.last_error = "GenerateEdit missing file content, intent, plan, or selected_file"
            self.bb.edit_attempts += 1
            return py_trees.common.Status.FAILURE

        user_prompt = GENERATE_EDIT_USER.format(
            selected_file=self.bb.selected_file,
            edit_intent=self.bb.edit_intent,
            edit_plan=self.bb.edit_plan,
            current_file_content=self.bb.current_file_content,
        )
        if self.bb.edit_attempts > 0 and self.bb.last_error:
            user_prompt += GENERATE_EDIT_RETRY_ADDITION.format(last_error=self.bb.last_error)

        try:
            payload = self._call_llm_json(GENERATE_EDIT_SYSTEM, user_prompt)
        except Exception as exc:  # noqa: BLE001
            self.bb.last_error = f"GenerateEdit failed: {exc}"
            self.bb.edit_attempts += 1
            return py_trees.common.Status.FAILURE

        old_str = (payload.get("old_str") or "")
        new_str = (payload.get("new_str") or "")
        target_file = (payload.get("target_file") or self.bb.selected_file or "").strip()
        if not old_str or not new_str or not target_file:
            self.bb.last_error = "GenerateEdit missing required fields: old_str/new_str/target_file"
            self.bb.edit_attempts += 1
            return py_trees.common.Status.FAILURE

        self.bb.proposed_edit = StrReplaceEdit(old_str=old_str, new_str=new_str, target_file=target_file)
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS


class ApplyEdit(py_trees.behaviour.Behaviour):
    def __init__(self, blackboard):
        super().__init__(name="ApplyEdit")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        if self.bb.proposed_edit is None:
            self.bb.last_error = "ApplyEdit missing proposed_edit"
            self.bb.edit_attempts += 1
            return py_trees.common.Status.FAILURE
        ok, err = str_replace(self.bb.repo_path, self.bb.proposed_edit)
        if not ok:
            self.bb.last_error = err
            self.bb.edit_attempts += 1
            return py_trees.common.Status.FAILURE
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS
