"""
Behavior tree builder for multi-file editing tasks.

Tree structure:

  Root [Sequence]
  ├── ParseAndPlanTask [Sequence]
  │   ├── BuildRepoMap
  │   ├── ExtractFilesAndIntent
  │   ├── BuildDependencyGraph
  │   └── PrioritizeEditOrder
  │
  ├── PrepareContext [Sequence]
  │   ├── LoadAllRelevantFiles
  │   └── SnapshotCurrentState       ← rollback point
  │
  ├── ForEachFileIterator             ← iterates bb.file_edit_queue
  │   ├── PlanFileChanges
  │   ├── GenerateEdit
  │   ├── ResolveConflicts
  │   ├── ApplyEdit
  │   └── ValidateEdit
  │
  ├── CrossFileValidation [Parallel]
  │   ├── CheckImportConsistency
  │   └── CheckCircularDependencies
  │
  └── FinalizeOrRollback [Selector]
      ├── CommitAllChanges
      └── RollbackToSnapshot          ← always returns FAILURE
"""
from __future__ import annotations

import py_trees

from bt_agent.llm.client import LLMClient
from bt_agent.tree.blackboard import MultiFileBlackboard
from bt_agent.tree.nodes.edit import ApplyEdit, GenerateEdit
from bt_agent.tree.nodes.gather import BuildRepoMap
from bt_agent.tree.nodes.multifile import (
    BuildDependencyGraph,
    CheckCircularDependencies,
    CheckImportConsistency,
    CommitAllChanges,
    ExtractFilesAndIntent,
    ForEachFileIterator,
    LoadAllRelevantFiles,
    PlanFileChanges,
    PrioritizeEditOrder,
    ResolveConflicts,
    RollbackToSnapshot,
    SnapshotCurrentState,
)
from bt_agent.tree.nodes.validate import ValidateEdit


def build_multifile_tree(
    blackboard: MultiFileBlackboard,
    llm: LLMClient,
    dry_run: bool,
) -> py_trees.behaviour.Behaviour:
    """
    Assemble and return the multi-file editing behavior tree root.

    Args:
        blackboard: MultiFileBlackboard pre-populated with task_description
                    and repo_path.
        llm:        Configured LLM client.
        dry_run:    If True, skip the actual git commit.

    Returns:
        The root Sequence node of the assembled tree.
    """
    # ── Phase 1: Planning ────────────────────────────────────────────────────
    parse_and_plan = py_trees.composites.Sequence(
        name="ParseAndPlanTask", memory=True
    )
    parse_and_plan.add_children([
        BuildRepoMap(blackboard),
        ExtractFilesAndIntent(blackboard, llm),
        BuildDependencyGraph(blackboard),
        PrioritizeEditOrder(blackboard),
    ])

    # ── Phase 2: Context Preparation ─────────────────────────────────────────
    prepare_context = py_trees.composites.Sequence(
        name="PrepareContext", memory=True
    )
    prepare_context.add_children([
        LoadAllRelevantFiles(blackboard),
        SnapshotCurrentState(blackboard),
    ])

    # ── Phase 3: Per-File Edit Loop ───────────────────────────────────────────
    #
    # GenerateEdit and ApplyEdit/ValidateEdit are reused from the single-file
    # tree. PlanFileChanges sets up current_file_content, edit_plan, and
    # edit_intent before GenerateEdit runs.
    #
    # ResolveConflicts sits between GenerateEdit and ApplyEdit to catch
    # cross-file semantic collisions before they touch disk.
    execute_edits = ForEachFileIterator(
        name="ForEachFile",
        blackboard=blackboard,
        children=[
            PlanFileChanges(blackboard, llm),
            GenerateEdit(blackboard, llm),
            ResolveConflicts(blackboard),
            ApplyEdit(blackboard),
            ValidateEdit(blackboard),
        ],
    )

    # ── Phase 4: Cross-File Validation ────────────────────────────────────────
    cross_file_validation = py_trees.composites.Parallel(
        name="CrossFileValidation",
        policy=py_trees.common.ParallelPolicy.SuccessOnAll(synchronise=False),
    )
    cross_file_validation.add_children([
        CheckImportConsistency(blackboard),
        CheckCircularDependencies(blackboard),
    ])

    # ── Phase 5: Finalize or Rollback ─────────────────────────────────────────
    #
    # Selector tries CommitAllChanges first. If it fails, RollbackToSnapshot
    # restores files and returns FAILURE, propagating failure to the root.
    finalize_or_rollback = py_trees.composites.Selector(
        name="FinalizeOrRollback", memory=True
    )
    finalize_or_rollback.add_children([
        CommitAllChanges(blackboard, llm, dry_run=dry_run),
        RollbackToSnapshot(blackboard),
    ])

    # ── Root ──────────────────────────────────────────────────────────────────
    root = py_trees.composites.Sequence(name="MultiFileRoot", memory=True)
    root.add_children([
        parse_and_plan,
        prepare_context,
        execute_edits,
        cross_file_validation,
        finalize_or_rollback,
    ])

    return root
