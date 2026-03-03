"""
Nodes for multi-file editing behavior tree.

New nodes introduced here:
  Planning:      ExtractFilesAndIntent, BuildDependencyGraph, PrioritizeEditOrder
  Context:       LoadAllRelevantFiles, SnapshotCurrentState
  Execution:     PlanFileChanges, ResolveConflicts, ForEachFileIterator
  Validation:    CheckImportConsistency, CheckCircularDependencies
  Finalization:  CommitAllChanges, RollbackToSnapshot

Existing nodes reused from the single-file tree:
  ReadTargetFile, GenerateEdit, ApplyEdit, ValidateEdit
"""
from __future__ import annotations

import logging
import typing
from pathlib import Path

import py_trees

from bt_agent.llm.multifile_prompts import (
    EXTRACT_FILES_SYSTEM,
    EXTRACT_FILES_USER,
    MULTIFILE_COMMIT_MSG_SYSTEM,
    MULTIFILE_COMMIT_MSG_USER,
    PLAN_FILE_CHANGES_SYSTEM,
    PLAN_FILE_CHANGES_USER,
)
from bt_agent.tools.dependency import (
    build_dependency_graph,
    check_import_consistency,
    detect_cycles,
    topological_sort,
)
from bt_agent.tools.git_ops import stage_and_commit_all
from bt_agent.tree.nodes.base import BaseLLMNode

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 1 — Planning
# ---------------------------------------------------------------------------


class ExtractFilesAndIntent(BaseLLMNode):
    """
    LLM node: parse the task and identify all files to edit + a global plan.

    Populates:
      bb.file_edit_queue  — ordered list of files to edit (validated to exist)
      bb.global_plan      — cross-file narrative plan
      bb.parsed_goal      — one-sentence summary (used by GenerateEdit prompt)
    """

    def __init__(self, blackboard, llm):
        super().__init__("ExtractFilesAndIntent", blackboard, llm)

    def update(self) -> py_trees.common.Status:
        if not self.bb.repo_map:
            self.bb.last_error = "ExtractFilesAndIntent: repo_map not built yet"
            return py_trees.common.Status.FAILURE

        try:
            payload = self._call_llm_json(
                EXTRACT_FILES_SYSTEM,
                EXTRACT_FILES_USER.format(
                    repo_map=self.bb.repo_map,
                    task_description=self.bb.task_description,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.bb.last_error = f"ExtractFilesAndIntent LLM failed: {exc}"
            return py_trees.common.Status.FAILURE

        raw_queue = payload.get("file_edit_queue") or []
        global_plan = (payload.get("global_plan") or "").strip()
        parsed_goal = (payload.get("parsed_goal") or "").strip()

        # Validate files exist on disk
        valid: list[str] = []
        for f in raw_queue:
            f = str(f).strip()
            if not f:
                continue
            if (self.bb.repo_path / f).is_file():
                valid.append(f)
            else:
                log.warning("ExtractFilesAndIntent: file not found, skipping: %s", f)

        if not valid:
            self.bb.last_error = (
                "ExtractFilesAndIntent: no valid files identified. "
                f"LLM returned: {raw_queue}"
            )
            return py_trees.common.Status.FAILURE

        self.bb.file_edit_queue = valid
        self.bb.global_plan = global_plan
        self.bb.parsed_goal = parsed_goal
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS


class BuildDependencyGraph(py_trees.behaviour.Behaviour):
    """
    Deterministic node: build an AST-based import graph among file_edit_queue.

    Populates:
      bb.dependency_graph — {file → [files it imports from, within the queue]}
      bb.symbol_index     — {symbol_name → [files that define it]}
    """

    def __init__(self, blackboard):
        super().__init__(name="BuildDependencyGraph")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        if not self.bb.file_edit_queue:
            self.bb.last_error = "BuildDependencyGraph: file_edit_queue is empty"
            return py_trees.common.Status.FAILURE

        dep_graph, symbol_index = build_dependency_graph(
            self.bb.repo_path, self.bb.file_edit_queue
        )
        self.bb.dependency_graph = dep_graph
        self.bb.symbol_index = symbol_index
        log.info(
            "DependencyGraph built: %d files, %d symbols",
            len(dep_graph),
            len(symbol_index),
        )
        return py_trees.common.Status.SUCCESS


class PrioritizeEditOrder(py_trees.behaviour.Behaviour):
    """
    Deterministic node: topologically sort file_edit_queue so that files
    imported by others are edited first.

    If cycles exist, the original order is preserved (cycles are caught
    later by CheckCircularDependencies).
    """

    def __init__(self, blackboard):
        super().__init__(name="PrioritizeEditOrder")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        if not self.bb.file_edit_queue:
            return py_trees.common.Status.SUCCESS
        sorted_files = topological_sort(
            self.bb.file_edit_queue, self.bb.dependency_graph
        )
        self.bb.file_edit_queue = sorted_files
        log.info("Edit order after prioritization: %s", sorted_files)
        return py_trees.common.Status.SUCCESS


# ---------------------------------------------------------------------------
# Phase 2 — Context Preparation
# ---------------------------------------------------------------------------


class LoadAllRelevantFiles(py_trees.behaviour.Behaviour):
    """
    Deterministic node: read every file in file_edit_queue into memory.

    Populates bb.all_file_contents: {relative_path → full text}
    """

    def __init__(self, blackboard):
        super().__init__(name="LoadAllRelevantFiles")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        contents: dict[str, str] = {}
        for f in self.bb.file_edit_queue:
            path = self.bb.repo_path / f
            try:
                contents[f] = path.read_text(encoding="utf-8")
            except OSError as exc:
                self.bb.last_error = f"LoadAllRelevantFiles: cannot read {f}: {exc}"
                return py_trees.common.Status.FAILURE
        self.bb.all_file_contents = contents
        return py_trees.common.Status.SUCCESS


class SnapshotCurrentState(py_trees.behaviour.Behaviour):
    """
    Deterministic node: deep-copy all_file_contents into file_snapshots.

    This is the rollback point. RollbackToSnapshot uses file_snapshots to
    restore all files to their pre-edit state.
    """

    def __init__(self, blackboard):
        super().__init__(name="SnapshotCurrentState")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        self.bb.file_snapshots = dict(self.bb.all_file_contents)
        log.info("Snapshot taken for %d files", len(self.bb.file_snapshots))
        return py_trees.common.Status.SUCCESS


# ---------------------------------------------------------------------------
# Phase 3 — Per-File Execution
# ---------------------------------------------------------------------------


class PlanFileChanges(BaseLLMNode):
    """
    LLM node: generate a per-file edit plan from the global plan.

    Reads the current file content from bb.all_file_contents and sets:
      bb.current_file_content — used by GenerateEdit
      bb.edit_plan            — step-by-step plan for this file
      bb.edit_intent          — one-sentence intent for this file
      bb.edit_attempts        — reset to 0 for each new file
    """

    def __init__(self, blackboard, llm):
        super().__init__("PlanFileChanges", blackboard, llm)

    def update(self) -> py_trees.common.Status:
        if not self.bb.selected_file:
            self.bb.last_error = "PlanFileChanges: selected_file not set"
            return py_trees.common.Status.FAILURE
        if not self.bb.global_plan:
            self.bb.last_error = "PlanFileChanges: global_plan not set"
            return py_trees.common.Status.FAILURE

        current_content = self.bb.all_file_contents.get(self.bb.selected_file, "")
        if not current_content:
            self.bb.last_error = (
                f"PlanFileChanges: no content cached for {self.bb.selected_file}"
            )
            return py_trees.common.Status.FAILURE

        # Expose content to GenerateEdit (which reads bb.current_file_content)
        self.bb.current_file_content = current_content

        # Build short summaries of all other files
        other_parts: list[str] = []
        for f, content in self.bb.all_file_contents.items():
            if f == self.bb.selected_file:
                continue
            preview = "\n".join(content.splitlines()[:20])
            other_parts.append(f"--- {f} (first 20 lines) ---\n{preview}")
        other_files_summary = "\n".join(other_parts) or "(no other files)"

        # Summarize the symbol index (cap at 30 entries to keep prompt short)
        sym_lines = [
            f"  {sym}: {', '.join(flist)}"
            for sym, flist in (self.bb.symbol_index or {}).items()
        ][:30]
        symbol_summary = "\n".join(sym_lines) or "(none)"

        try:
            payload = self._call_llm_json(
                PLAN_FILE_CHANGES_SYSTEM,
                PLAN_FILE_CHANGES_USER.format(
                    global_plan=self.bb.global_plan,
                    selected_file=self.bb.selected_file,
                    symbol_summary=symbol_summary,
                    other_files_summary=other_files_summary,
                    current_file_content=current_content[:3000],
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.bb.last_error = f"PlanFileChanges LLM failed: {exc}"
            return py_trees.common.Status.FAILURE

        edit_plan = (payload.get("edit_plan") or "").strip()
        edit_intent = (payload.get("edit_intent") or "").strip()
        if not edit_intent:
            self.bb.last_error = "PlanFileChanges: LLM returned empty edit_intent"
            return py_trees.common.Status.FAILURE

        self.bb.edit_plan = edit_plan
        self.bb.edit_intent = edit_intent
        self.bb.per_file_plans[self.bb.selected_file] = edit_plan
        self.bb.edit_attempts = 0  # reset attempt counter for each new file
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS


class ResolveConflicts(py_trees.behaviour.Behaviour):
    """
    Deterministic node: detect whether the proposed edit conflicts with
    any previously applied edit in the same file.

    A conflict is defined as: the proposed edit's old_str appears inside
    text that was already replaced by an earlier edit's new_str (i.e. the
    proposed old_str is now gone from the file because a prior edit changed it).

    Returns FAILURE with a descriptive error if a conflict is found,
    so GenerateEdit can be retried with the updated file content.
    """

    def __init__(self, blackboard):
        super().__init__(name="ResolveConflicts")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        if self.bb.proposed_edit is None:
            return py_trees.common.Status.SUCCESS

        proposed_file = self.bb.proposed_edit.target_file
        proposed_old = self.bb.proposed_edit.old_str

        for applied in self.bb.file_edits_applied:
            if applied.get("target_file") != proposed_file:
                continue
            applied_new = applied.get("new_str", "")
            applied_old = applied.get("old_str", "")
            # Conflict: proposed old_str was part of what a prior edit replaced
            if proposed_old in applied_old or applied_new in proposed_old:
                self.bb.last_error = (
                    f"ResolveConflicts: proposed edit for '{proposed_file}' "
                    f"conflicts with a previously applied edit — "
                    f"old_str overlaps with already-replaced text. "
                    f"Regenerate using the current file state."
                )
                self.bb.edit_attempts += 1
                return py_trees.common.Status.FAILURE

        return py_trees.common.Status.SUCCESS


# ---------------------------------------------------------------------------
# Phase 4 — Cross-File Validation
# ---------------------------------------------------------------------------


class CheckImportConsistency(py_trees.behaviour.Behaviour):
    """
    Deterministic node: verify that all intra-set imports still resolve
    after edits have been applied.
    """

    def __init__(self, blackboard):
        super().__init__(name="CheckImportConsistency")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        errors = check_import_consistency(
            self.bb.repo_path, self.bb.file_edit_queue
        )
        if errors:
            self.bb.cross_file_errors.extend(errors)
            self.bb.last_error = "; ".join(errors)
            return py_trees.common.Status.FAILURE
        return py_trees.common.Status.SUCCESS


class CheckCircularDependencies(py_trees.behaviour.Behaviour):
    """
    Deterministic node: re-run the dependency graph on edited files and
    detect any newly introduced import cycles.
    """

    def __init__(self, blackboard):
        super().__init__(name="CheckCircularDependencies")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        if not self.bb.file_edit_queue:
            return py_trees.common.Status.SUCCESS

        dep_graph, _ = build_dependency_graph(
            self.bb.repo_path, self.bb.file_edit_queue
        )
        cycles = detect_cycles(dep_graph)
        if cycles:
            cycle_strs = [" → ".join(c) for c in cycles]
            msg = f"Circular dependencies detected: {'; '.join(cycle_strs)}"
            self.bb.cross_file_errors.append(msg)
            self.bb.last_error = msg
            return py_trees.common.Status.FAILURE
        return py_trees.common.Status.SUCCESS


# ---------------------------------------------------------------------------
# Phase 5 — Finalization
# ---------------------------------------------------------------------------


class CommitAllChanges(BaseLLMNode):
    """
    LLM node: generate a commit message and stage+commit all edited files.

    In dry-run mode, the commit message is generated but no git operation runs.
    """

    def __init__(self, blackboard, llm, dry_run: bool = False):
        super().__init__("CommitAllChanges", blackboard, llm)
        self.dry_run = dry_run

    def update(self) -> py_trees.common.Status:
        if not self.bb.file_edit_queue:
            self.bb.last_error = "CommitAllChanges: file_edit_queue is empty"
            return py_trees.common.Status.FAILURE

        files_changed = ", ".join(self.bb.file_edit_queue)
        try:
            msg = self._call_llm_text(
                MULTIFILE_COMMIT_MSG_SYSTEM,
                MULTIFILE_COMMIT_MSG_USER.format(
                    global_plan=self.bb.global_plan or self.bb.task_description,
                    files_changed=files_changed,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.bb.last_error = f"CommitAllChanges: commit message generation failed: {exc}"
            return py_trees.common.Status.FAILURE

        self.bb.commit_message = msg.strip()

        if self.dry_run:
            log.info("CommitAllChanges: dry-run, skipping git commit")
            self.bb.committed = True
            return py_trees.common.Status.SUCCESS

        ok, err = stage_and_commit_all(
            self.bb.repo_path, self.bb.file_edit_queue, self.bb.commit_message
        )
        if not ok:
            self.bb.last_error = f"CommitAllChanges: git failed: {err}"
            return py_trees.common.Status.FAILURE

        self.bb.committed = True
        self.bb.last_error = None
        return py_trees.common.Status.SUCCESS


class RollbackToSnapshot(py_trees.behaviour.Behaviour):
    """
    Deterministic node: restore all files to their pre-edit state.

    Always returns FAILURE — it signals that the overall task failed even
    though the rollback itself succeeded. This propagates failure out of
    the FinalizeOrRollback Selector.
    """

    def __init__(self, blackboard):
        super().__init__(name="RollbackToSnapshot")
        self.bb = blackboard

    def update(self) -> py_trees.common.Status:
        restored = 0
        failed = 0
        for f, original_content in self.bb.file_snapshots.items():
            path = self.bb.repo_path / f
            try:
                path.write_text(original_content, encoding="utf-8")
                restored += 1
            except OSError as exc:
                log.error("RollbackToSnapshot: failed to restore %s: %s", f, exc)
                failed += 1

        log.info(
            "RollbackToSnapshot: restored=%d, failed=%d", restored, failed
        )
        # Always FAILURE — rollback means the task did not complete
        return py_trees.common.Status.FAILURE


# ---------------------------------------------------------------------------
# ForEachFileIterator — custom Composite
# ---------------------------------------------------------------------------


class ForEachFileIterator(py_trees.composites.Composite):
    """
    Custom composite that iterates over bb.file_edit_queue.

    For each file in the queue:
      1. Sets bb.selected_file to the current file path
      2. Ticks all children as a Sequence (each must SUCCESS before advancing)
      3. On SUCCESS of all children: records the applied edit, refreshes
         bb.all_file_contents from disk, then advances to the next file
      4. On FAILURE of any child: stops and returns FAILURE immediately
      5. On RUNNING of any child: yields and resumes on the next tree tick

    State is maintained via _file_index and _child_index between ticks,
    since tick() is a generator that is reconstructed each tick cycle.

    Architectural note: as a true Composite subclass, all children are
    yielded to the tree's visitor system during traversal, enabling full
    trajectory logging coverage.
    """

    def __init__(
        self,
        name: str,
        blackboard,
        children: list[py_trees.behaviour.Behaviour] | None = None,
    ):
        super().__init__(name=name, children=children)
        self.bb = blackboard
        self._file_index: int = 0
        self._child_index: int = 0

    def initialise(self) -> None:
        self._file_index = 0
        self._child_index = 0
        self.bb.current_queue_index = 0

    def tick(self) -> typing.Iterator[py_trees.behaviour.Behaviour]:
        """
        Tick the iterator.

        On a fresh start (status != RUNNING): re-initialise all children
        and reset the file/child cursors.

        On resume (status == RUNNING): skip re-initialisation and pick up
        from the current _file_index / _child_index.
        """
        if self.status != py_trees.common.Status.RUNNING:
            for child in self.children:
                if child.status != py_trees.common.Status.INVALID:
                    child.stop(py_trees.common.Status.INVALID)
            self.initialise()

        queue = self.bb.file_edit_queue

        if not queue or not self.children:
            self.stop(py_trees.common.Status.SUCCESS)
            yield self
            return

        while self._file_index < len(queue):
            # Bind the current file to the blackboard
            self.bb.selected_file = queue[self._file_index]

            # Run children as a sequence for this file
            while self._child_index < len(self.children):
                child = self.children[self._child_index]
                self.current_child = child

                for node in child.tick():
                    yield node
                    if node is child:
                        status = node.status
                        if status == py_trees.common.Status.FAILURE:
                            self.stop(py_trees.common.Status.FAILURE)
                            yield self
                            return
                        elif status == py_trees.common.Status.RUNNING:
                            self.status = py_trees.common.Status.RUNNING
                            yield self
                            return
                        # SUCCESS — advance to next child
                        self._child_index += 1

            # ── All children succeeded for this file ──────────────────────
            # Record the applied edit for ResolveConflicts on later files
            if self.bb.proposed_edit is not None:
                self.bb.file_edits_applied.append(
                    self.bb.proposed_edit.model_dump()
                )

            # Refresh in-memory content with the post-edit version
            edited_path = self.bb.repo_path / queue[self._file_index]
            if edited_path.exists():
                self.bb.all_file_contents[queue[self._file_index]] = (
                    edited_path.read_text(encoding="utf-8")
                )

            # Advance to next file and reset child cursor
            self._file_index += 1
            self._child_index = 0
            self.bb.current_queue_index = self._file_index
            self.bb.proposed_edit = None

            # Stop children so they re-initialise for the next file
            for child in self.children:
                if child.status != py_trees.common.Status.INVALID:
                    child.stop(py_trees.common.Status.INVALID)

        # All files processed successfully
        self.stop(py_trees.common.Status.SUCCESS)
        yield self

    def stop(
        self, new_status: py_trees.common.Status = py_trees.common.Status.INVALID
    ) -> None:
        for child in self.children:
            if child.status == py_trees.common.Status.RUNNING:
                child.stop(new_status)
        super().stop(new_status)
