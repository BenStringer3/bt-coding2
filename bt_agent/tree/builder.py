from __future__ import annotations

import py_trees

from bt_agent.llm.client import LLMClient
from bt_agent.tree.blackboard import AgentBlackboard
from bt_agent.tree.nodes import (
    ApplyEdit,
    BuildRepoMap,
    GenerateCommitMsg,
    GenerateEdit,
    GitCommit,
    LocateRelevantFiles,
    PlanEdits,
    ReadTargetFile,
    UnderstandTask,
    ValidateEdit,
)


class RetryUntilSuccess(py_trees.decorators.Decorator):
    def __init__(self, child: py_trees.behaviour.Behaviour, max_failures: int):
        super().__init__(name="EditLoop", child=child)
        self.max_failures = max_failures
        self.failures = 0

    def initialise(self) -> None:
        self.failures = 0

    def update(self) -> py_trees.common.Status:
        if self.decorated.status == py_trees.common.Status.SUCCESS:
            return py_trees.common.Status.SUCCESS
        if self.decorated.status == py_trees.common.Status.FAILURE:
            self.failures += 1
            if self.failures >= self.max_failures:
                return py_trees.common.Status.FAILURE
            return py_trees.common.Status.RUNNING
        return self.decorated.status


def build_tree(blackboard: AgentBlackboard, llm: LLMClient, dry_run: bool, max_attempts: int = 5) -> py_trees.behaviour.Behaviour:
    root = py_trees.composites.Sequence(name="Root", memory=True)

    gather_context = py_trees.composites.Sequence(name="GatherContext", memory=True)
    gather_context.add_children(
        [
            BuildRepoMap(blackboard),
            LocateRelevantFiles(blackboard, llm),
        ]
    )

    edit_attempt = py_trees.composites.Sequence(name="EditAttempt", memory=True)
    edit_attempt.add_children(
        [
            ReadTargetFile(blackboard),
            GenerateEdit(blackboard, llm),
            ApplyEdit(blackboard),
            ValidateEdit(blackboard),
        ]
    )
    edit_loop = RetryUntilSuccess(child=edit_attempt, max_failures=max_attempts)

    commit_changes = py_trees.composites.Sequence(name="CommitChanges", memory=True)
    commit_changes.add_children(
        [
            GenerateCommitMsg(blackboard, llm),
            GitCommit(blackboard, dry_run=dry_run),
        ]
    )

    root.add_children(
        [
            UnderstandTask(blackboard, llm),
            gather_context,
            PlanEdits(blackboard, llm),
            edit_loop,
            commit_changes,
        ]
    )
    return root
