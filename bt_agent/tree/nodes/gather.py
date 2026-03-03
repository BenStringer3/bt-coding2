from __future__ import annotations

from pathlib import Path

import py_trees

from bt_agent.llm.prompts import LOCATE_FILES_SYSTEM, LOCATE_FILES_USER
from bt_agent.tools.repo_map import build_repo_map
from bt_agent.tree.nodes.base import BaseLLMNode


class BuildRepoMap(py_trees.behaviour.Behaviour):
    def __init__(self, blackboard):
        super().__init__(name="BuildRepoMap")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        self.bb.repo_map = build_repo_map(self.bb.repo_path)
        return py_trees.common.Status.SUCCESS


class LocateRelevantFiles(BaseLLMNode):
    def __init__(self, blackboard, llm):
        super().__init__("LocateRelevantFiles", blackboard, llm)

    def update(self) -> py_trees.common.Status:
        if not self.bb.repo_map or not self.bb.parsed_goal:
            self.bb.last_error = "LocateRelevantFiles missing repo_map or parsed_goal"
            return py_trees.common.Status.FAILURE

        try:
            payload = self._call_llm_json(
                LOCATE_FILES_SYSTEM,
                LOCATE_FILES_USER.format(repo_map=self.bb.repo_map, parsed_goal=self.bb.parsed_goal),
            )
        except Exception as exc:  # noqa: BLE001
            self.bb.last_error = f"LocateRelevantFiles failed: {exc}"
            return py_trees.common.Status.FAILURE

        candidate_files = payload.get("candidate_files") or []
        selected_file = (payload.get("selected_file") or "").strip()
        if not selected_file:
            self.bb.last_error = "LocateRelevantFiles returned empty selected_file"
            return py_trees.common.Status.FAILURE

        selected = self.bb.repo_path / selected_file
        if not selected.exists() or not selected.is_file():
            self.bb.last_error = f"selected_file does not exist: {selected_file}"
            return py_trees.common.Status.FAILURE

        self.bb.candidate_files = [str(Path(f)) for f in candidate_files][:3] or [selected_file]
        self.bb.selected_file = selected_file
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS
