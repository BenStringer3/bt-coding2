"""
Unit tests for multi-file behavior tree components.

Tests cover:
  - dependency.py tools (graph building, topo sort, cycle detection)
  - MultiFileBlackboard schema
  - Deterministic nodes (no LLM) in isolation
  - ForEachFileIterator composite ticking
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import py_trees
import pytest

from bt_agent.tools.dependency import (
    build_dependency_graph,
    check_import_consistency,
    detect_cycles,
    extract_python_imports,
    extract_top_level_symbols,
    topological_sort,
)
from bt_agent.tree.blackboard import MultiFileBlackboard, StrReplaceEdit
from bt_agent.tree.nodes.multifile import (
    BuildDependencyGraph,
    CheckCircularDependencies,
    CheckImportConsistency,
    ForEachFileIterator,
    LoadAllRelevantFiles,
    PrioritizeEditOrder,
    ResolveConflicts,
    RollbackToSnapshot,
    SnapshotCurrentState,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "rename_across_files"


# ---------------------------------------------------------------------------
# dependency.py tools
# ---------------------------------------------------------------------------


def test_extract_imports_basic(tmp_path):
    src = tmp_path / "a.py"
    src.write_text("import os\nfrom pathlib import Path\nimport utils\n")
    result = extract_python_imports(src)
    assert "os" in result
    assert "pathlib" in result
    assert "utils" in result


def test_extract_imports_bad_syntax(tmp_path):
    src = tmp_path / "bad.py"
    src.write_text("def (broken:\n")
    # Should return empty list, not raise
    assert extract_python_imports(src) == []


def test_extract_top_level_symbols(tmp_path):
    src = tmp_path / "m.py"
    src.write_text(textwrap.dedent("""\
        X = 1
        def foo(): pass
        class Bar: pass
        def _private(): pass
    """))
    syms = extract_top_level_symbols(src)
    assert "foo" in syms
    assert "Bar" in syms
    assert "X" in syms
    assert "_private" in syms


def test_build_dependency_graph_fixture():
    files = ["main.py", "utils.py"]
    dep_graph, symbol_index = build_dependency_graph(FIXTURE, files)

    # main.py imports utils → dep_graph["main.py"] contains "utils.py"
    assert "utils.py" in dep_graph["main.py"]
    # utils.py does not import main
    assert dep_graph["utils.py"] == []

    # Symbol index should know compute_total is in utils.py
    assert "utils.py" in symbol_index.get("compute_total", [])


def test_topological_sort_orders_deps_first():
    # main depends on utils → utils should come first
    files = ["main.py", "utils.py"]
    dep_graph = {"main.py": ["utils.py"], "utils.py": []}
    result = topological_sort(files, dep_graph)
    assert result.index("utils.py") < result.index("main.py")


def test_topological_sort_no_cycle():
    files = ["a.py", "b.py", "c.py"]
    dep_graph = {"a.py": [], "b.py": ["a.py"], "c.py": ["b.py"]}
    result = topological_sort(files, dep_graph)
    assert result == ["a.py", "b.py", "c.py"]


def test_topological_sort_cycle_returns_original():
    files = ["a.py", "b.py"]
    dep_graph = {"a.py": ["b.py"], "b.py": ["a.py"]}
    result = topological_sort(files, dep_graph)
    assert result == files  # fallback to original order


def test_detect_cycles_no_cycle():
    dep_graph = {"a.py": ["b.py"], "b.py": []}
    assert detect_cycles(dep_graph) == []


def test_detect_cycles_simple_cycle():
    dep_graph = {"a.py": ["b.py"], "b.py": ["a.py"]}
    cycles = detect_cycles(dep_graph)
    assert len(cycles) >= 1


def test_check_import_consistency_ok(tmp_path):
    # utils.py is in the set and exists → no error
    (tmp_path / "main.py").write_text("from utils import foo\n")
    (tmp_path / "utils.py").write_text("def foo(): pass\n")
    errors = check_import_consistency(tmp_path, ["main.py", "utils.py"])
    assert errors == []


def test_check_import_consistency_missing(tmp_path):
    # utils.py listed in set but deleted from disk
    (tmp_path / "main.py").write_text("from utils import foo\n")
    # utils.py intentionally NOT created
    errors = check_import_consistency(tmp_path, ["main.py", "utils.py"])
    assert any("utils" in e for e in errors)


# ---------------------------------------------------------------------------
# MultiFileBlackboard
# ---------------------------------------------------------------------------


def test_multifile_blackboard_inherits_agent_fields():
    bb = MultiFileBlackboard(task_description="test", repo_path=Path("/tmp"))
    assert bb.file_edit_queue == []
    assert bb.file_snapshots == {}
    assert bb.cross_file_errors == []
    # Inherited from AgentBlackboard
    assert bb.edit_attempts == 0
    assert bb.committed is False


def test_multifile_blackboard_snapshot_includes_new_fields():
    bb = MultiFileBlackboard(task_description="test", repo_path=Path("/tmp"))
    bb.global_plan = "rename foo"
    snap = bb.snapshot()
    assert snap["global_plan"] == "rename foo"


# ---------------------------------------------------------------------------
# Deterministic node tests
# ---------------------------------------------------------------------------


def _make_bb(**kwargs) -> MultiFileBlackboard:
    return MultiFileBlackboard(
        task_description="test", repo_path=FIXTURE, **kwargs
    )


def test_load_all_relevant_files_success():
    bb = _make_bb(file_edit_queue=["utils.py", "main.py"])
    node = LoadAllRelevantFiles(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.SUCCESS
    assert "utils.py" in bb.all_file_contents
    assert "main.py" in bb.all_file_contents
    assert "compute_total" in bb.all_file_contents["utils.py"]


def test_load_all_relevant_files_missing_file():
    bb = _make_bb(file_edit_queue=["nonexistent.py"])
    node = LoadAllRelevantFiles(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.FAILURE
    assert "nonexistent.py" in (bb.last_error or "")


def test_snapshot_current_state():
    bb = _make_bb()
    bb.all_file_contents = {"utils.py": "original content"}
    node = SnapshotCurrentState(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.SUCCESS
    # Snapshot is a separate dict (deep copy)
    bb.all_file_contents["utils.py"] = "modified content"
    assert bb.file_snapshots["utils.py"] == "original content"


def test_build_dependency_graph_node():
    bb = _make_bb(file_edit_queue=["main.py", "utils.py"])
    node = BuildDependencyGraph(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.SUCCESS
    assert "utils.py" in bb.dependency_graph.get("main.py", [])


def test_prioritize_edit_order_node():
    bb = _make_bb(
        file_edit_queue=["main.py", "utils.py"],
        dependency_graph={"main.py": ["utils.py"], "utils.py": []},
    )
    node = PrioritizeEditOrder(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.SUCCESS
    assert bb.file_edit_queue.index("utils.py") < bb.file_edit_queue.index("main.py")


def test_resolve_conflicts_no_conflict():
    bb = _make_bb()
    bb.proposed_edit = StrReplaceEdit(
        old_str="def compute_total", new_str="def sum_items", target_file="utils.py"
    )
    bb.file_edits_applied = []
    node = ResolveConflicts(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.SUCCESS


def test_resolve_conflicts_detects_overlap():
    bb = _make_bb()
    # An earlier edit already replaced "compute_total" with "sum_items"
    bb.file_edits_applied = [
        {
            "old_str": "def compute_total",
            "new_str": "def sum_items",
            "target_file": "utils.py",
        }
    ]
    # Proposed edit's old_str overlaps with the replaced old_str
    bb.proposed_edit = StrReplaceEdit(
        old_str="def compute_total",
        new_str="def sum_items",
        target_file="utils.py",
    )
    node = ResolveConflicts(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.FAILURE
    assert bb.edit_attempts == 1


def test_rollback_to_snapshot(tmp_path):
    # Write original content, then overwrite it, then rollback
    f = tmp_path / "a.py"
    f.write_text("original\n")
    bb = MultiFileBlackboard(
        task_description="test",
        repo_path=tmp_path,
        file_snapshots={"a.py": "original\n"},
    )
    # Simulate an edit applied to disk
    f.write_text("modified\n")
    assert f.read_text() == "modified\n"

    node = RollbackToSnapshot(bb)
    node.tick_once()

    # RollbackToSnapshot always returns FAILURE
    assert node.status == py_trees.common.Status.FAILURE
    # But the file is restored
    assert f.read_text() == "original\n"


def test_check_import_consistency_node_ok():
    bb = _make_bb(file_edit_queue=["main.py", "utils.py"])
    node = CheckImportConsistency(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.SUCCESS


def test_check_circular_dependencies_node_no_cycle():
    bb = _make_bb(file_edit_queue=["main.py", "utils.py"])
    node = CheckCircularDependencies(bb)
    node.tick_once()
    assert node.status == py_trees.common.Status.SUCCESS


# ---------------------------------------------------------------------------
# ForEachFileIterator
# ---------------------------------------------------------------------------


def _make_always(status: py_trees.common.Status) -> py_trees.behaviour.Behaviour:
    """Helper: a behaviour that always returns a fixed status."""
    b = py_trees.behaviours.StatusQueue(
        name=f"Always{status.name}",
        queue=[status],
        eventually=status,
    )
    return b


def test_foreach_iterator_empty_queue():
    bb = _make_bb(file_edit_queue=[])
    child = _make_always(py_trees.common.Status.SUCCESS)
    iterator = ForEachFileIterator(name="Iter", blackboard=bb, children=[child])
    iterator.tick_once()
    assert iterator.status == py_trees.common.Status.SUCCESS


def test_foreach_iterator_success_path(tmp_path):
    """Iterator runs a success-child for each file and returns SUCCESS."""
    (tmp_path / "a.py").write_text("x=1\n")
    (tmp_path / "b.py").write_text("x=2\n")

    bb = MultiFileBlackboard(
        task_description="test",
        repo_path=tmp_path,
        file_edit_queue=["a.py", "b.py"],
        all_file_contents={"a.py": "x=1\n", "b.py": "x=2\n"},
    )
    visited_files: list[str] = []

    class RecordFile(py_trees.behaviour.Behaviour):
        def __init__(self):
            super().__init__("RecordFile")

        def update(self):
            visited_files.append(bb.selected_file)
            return py_trees.common.Status.SUCCESS

    iterator = ForEachFileIterator(
        name="Iter", blackboard=bb, children=[RecordFile()]
    )
    iterator.tick_once()
    assert iterator.status == py_trees.common.Status.SUCCESS
    assert visited_files == ["a.py", "b.py"]


def test_foreach_iterator_failure_stops_early(tmp_path):
    """Iterator stops as soon as a child returns FAILURE."""
    (tmp_path / "a.py").write_text("x=1\n")
    (tmp_path / "b.py").write_text("x=2\n")

    bb = MultiFileBlackboard(
        task_description="test",
        repo_path=tmp_path,
        file_edit_queue=["a.py", "b.py"],
        all_file_contents={"a.py": "x=1\n", "b.py": "x=2\n"},
    )
    calls: list[str] = []

    class AlwaysFail(py_trees.behaviour.Behaviour):
        def __init__(self):
            super().__init__("AlwaysFail")

        def update(self):
            calls.append(bb.selected_file or "")
            return py_trees.common.Status.FAILURE

    iterator = ForEachFileIterator(
        name="Iter", blackboard=bb, children=[AlwaysFail()]
    )
    iterator.tick_once()
    assert iterator.status == py_trees.common.Status.FAILURE
    # Should stop after the first file fails
    assert calls == ["a.py"]


def test_foreach_records_applied_edit(tmp_path):
    """Iterator records proposed_edit in file_edits_applied after each file."""
    (tmp_path / "a.py").write_text("x=1\n")

    bb = MultiFileBlackboard(
        task_description="test",
        repo_path=tmp_path,
        file_edit_queue=["a.py"],
        all_file_contents={"a.py": "x=1\n"},
    )

    class SetEdit(py_trees.behaviour.Behaviour):
        def __init__(self):
            super().__init__("SetEdit")

        def update(self):
            bb.proposed_edit = StrReplaceEdit(
                old_str="x=1", new_str="x=2", target_file="a.py"
            )
            return py_trees.common.Status.SUCCESS

    iterator = ForEachFileIterator(
        name="Iter", blackboard=bb, children=[SetEdit()]
    )
    iterator.tick_once()
    assert iterator.status == py_trees.common.Status.SUCCESS
    assert len(bb.file_edits_applied) == 1
    assert bb.file_edits_applied[0]["old_str"] == "x=1"
