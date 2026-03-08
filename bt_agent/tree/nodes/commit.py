from __future__ import annotations

import py_trees

from bt_agent.tools.git_ops import stage_and_commit
from bt_agent.tree.nodes.base import BaseLLMNode


class GenerateCommitMsg(BaseLLMNode):
    def __init__(self, blackboard, llm):
        super().__init__("GenerateCommitMsg", blackboard, llm)

    def update(self) -> py_trees.common.Status:
        if not self.bb.edit_intent or not self.bb.selected_file:
            self.bb.last_error = "GenerateCommitMsg missing edit_intent or selected_file"
            return py_trees.common.Status.FAILURE

        # Deterministic commit messages avoid an unnecessary LLM call in the hot path.
        intent = " ".join(self.bb.edit_intent.strip().split())
        if not intent:
            self.bb.last_error = "GenerateCommitMsg missing non-empty edit_intent"
            return py_trees.common.Status.FAILURE
        message = f"fix: update {self.bb.selected_file} - {intent}"
        self.bb.commit_message = message[:72]
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
