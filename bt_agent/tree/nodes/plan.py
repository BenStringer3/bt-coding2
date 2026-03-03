from __future__ import annotations

import py_trees

from bt_agent.llm.prompts import PLAN_EDITS_SYSTEM, PLAN_EDITS_USER
from bt_agent.tree.nodes.base import BaseLLMNode


class PlanEdits(BaseLLMNode):
    def __init__(self, blackboard, llm):
        super().__init__("PlanEdits", blackboard, llm)

    def update(self) -> py_trees.common.Status:
        if not self.bb.selected_file or not self.bb.parsed_goal:
            self.bb.last_error = "PlanEdits missing selected_file or parsed_goal"
            return py_trees.common.Status.FAILURE

        selected_path = self.bb.repo_path / self.bb.selected_file
        if not selected_path.exists():
            self.bb.last_error = f"PlanEdits file does not exist: {self.bb.selected_file}"
            return py_trees.common.Status.FAILURE

        file_preview = "\n".join(selected_path.read_text(encoding="utf-8").splitlines()[:100])

        try:
            payload = self._call_llm_json(
                PLAN_EDITS_SYSTEM,
                PLAN_EDITS_USER.format(
                    parsed_goal=self.bb.parsed_goal,
                    selected_file=self.bb.selected_file,
                    file_preview=file_preview,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.bb.last_error = f"PlanEdits failed: {exc}"
            return py_trees.common.Status.FAILURE

        edit_plan = (payload.get("edit_plan") or "").strip()
        edit_intent = (payload.get("edit_intent") or "").strip()
        if not edit_intent:
            self.bb.last_error = "PlanEdits returned empty edit_intent"
            return py_trees.common.Status.FAILURE

        self.bb.edit_plan = edit_plan
        self.bb.edit_intent = edit_intent
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS
