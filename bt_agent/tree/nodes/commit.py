from __future__ import annotations

import py_trees

from bt_agent.llm.prompts import COMMIT_MSG_SYSTEM, COMMIT_MSG_USER
from bt_agent.tools.git_ops import stage_and_commit
from bt_agent.tree.nodes.base import BaseLLMNode


class GenerateCommitMsg(BaseLLMNode):
    def __init__(self, blackboard, llm):
        super().__init__("GenerateCommitMsg", blackboard, llm)

    def update(self) -> py_trees.common.Status:
        if not self.bb.edit_intent or not self.bb.selected_file:
            self.bb.last_error = "GenerateCommitMsg missing edit_intent or selected_file"
            return py_trees.common.Status.FAILURE

        try:
            text = self._call_llm_text(
                COMMIT_MSG_SYSTEM,
                COMMIT_MSG_USER.format(edit_intent=self.bb.edit_intent, selected_file=self.bb.selected_file),
            )
        except Exception as exc:  # noqa: BLE001
            self.bb.last_error = f"GenerateCommitMsg failed: {exc}"
            return py_trees.common.Status.FAILURE

        if not text or len(text) > 200:
            self.bb.last_error = "GenerateCommitMsg returned empty or too long message"
            return py_trees.common.Status.FAILURE

        self.bb.commit_message = text
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS


class GitCommit(py_trees.behaviour.Behaviour):
    def __init__(self, blackboard, dry_run: bool = False):
        super().__init__(name="GitCommit")
        self.bb = blackboard
        self.dry_run = dry_run

    def update(self) -> py_trees.common.Status:
        if self.dry_run:
            return py_trees.common.Status.SUCCESS

        if not self.bb.selected_file or not self.bb.commit_message:
            self.bb.last_error = "GitCommit missing selected_file or commit_message"
            return py_trees.common.Status.FAILURE

        ok, err = stage_and_commit(self.bb.repo_path, self.bb.selected_file, self.bb.commit_message)
        if not ok:
            self.bb.last_error = err
            return py_trees.common.Status.FAILURE

        self.bb.committed = True
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS
