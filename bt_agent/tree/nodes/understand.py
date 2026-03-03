from __future__ import annotations

import py_trees

from bt_agent.llm.prompts import UNDERSTAND_TASK_SYSTEM, UNDERSTAND_TASK_USER
from bt_agent.tree.nodes.base import BaseLLMNode


class UnderstandTask(BaseLLMNode):
    def __init__(self, blackboard, llm):
        super().__init__("UnderstandTask", blackboard, llm)

    def update(self) -> py_trees.common.Status:
        try:
            payload = self._call_llm_json(
                UNDERSTAND_TASK_SYSTEM,
                UNDERSTAND_TASK_USER.format(task_description=self.bb.task_description),
            )
        except Exception as exc:  # noqa: BLE001
            self.bb.last_error = f"UnderstandTask failed: {exc}"
            return py_trees.common.Status.FAILURE

        parsed_goal = (payload.get("parsed_goal") or "").strip()
        target_language = (payload.get("target_language") or "").strip()
        if not parsed_goal:
            self.bb.last_error = "UnderstandTask returned empty parsed_goal"
            return py_trees.common.Status.FAILURE

        self.bb.parsed_goal = parsed_goal
        self.bb.target_language = target_language or None
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS
