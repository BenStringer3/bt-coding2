"""
Dependency analysis tools for multi-file editing.

Provides AST-based import graph construction, topological ordering,
cycle detection, and post-edit import consistency checks.
"""
from __future__ import annotations

import ast
import logging
from collections import defaultdict, deque
from pathlib import Path

log = logging.getLogger(__name__)


def extract_python_imports(filepath: Path) -> list[str]:
    """Return top-level module names imported by a Python file."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])
    return imports


def extract_top_level_symbols(filepath: Path) -> list[str]:
    """Return top-level function, class, and variable names defined in a Python file."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return []

    symbols: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols.append(target.id)
    return symbols


def build_dependency_graph(
    repo_path: Path, files: list[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Build an import dependency graph among the given files.

    Returns:
        dep_graph:    {file → [files within the set that it imports from]}
        symbol_index: {symbol_name → [files that define it]}

    Only edges between files in the provided list are included.
    """
    # Map module stem → relative file path (within the files list)
    stem_to_file: dict[str, str] = {Path(f).stem: f for f in files}

    dep_graph: dict[str, list[str]] = {f: [] for f in files}
    symbol_index: dict[str, list[str]] = defaultdict(list)

    for f in files:
        path = repo_path / f
        if not path.exists():
            continue

        if path.suffix == ".py":
            for imp in extract_python_imports(path):
                if imp in stem_to_file and stem_to_file[imp] != f:
                    dep_graph[f].append(stem_to_file[imp])

            for sym in extract_top_level_symbols(path):
                symbol_index[sym].append(f)

    return dep_graph, dict(symbol_index)


def topological_sort(files: list[str], dep_graph: dict[str, list[str]]) -> list[str]:
    """
    Return files in topological order so dependencies come before dependents.

    Uses Kahn's algorithm. Falls back to the original order on cycles.

    Example: if B imports A, A appears before B so A is edited first,
    ensuring B's edit can reference A's new API.
    """
    # Build reverse adjacency: for each file, which files depend on it?
    dependents: dict[str, list[str]] = {f: [] for f in files}
    in_degree: dict[str, int] = {f: 0 for f in files}

    for f, deps in dep_graph.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[f] += 1
                dependents[dep].append(f)

    queue: deque[str] = deque(f for f in files if in_degree[f] == 0)
    result: list[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for dependent in dependents.get(node, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(files):
        log.warning("Cyclic dependency detected; using original file order.")
        return files

    return result


def detect_cycles(dep_graph: dict[str, list[str]]) -> list[list[str]]:
    """
    Return all cycles found in the dependency graph.
    Each cycle is represented as a list of file paths.
    """
    visited: set[str] = set()
    rec_stack: set[str] = set()
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in dep_graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
        path.pop()
        rec_stack.discard(node)

    for node in list(dep_graph):
        if node not in visited:
            dfs(node, [])

    return cycles


def check_import_consistency(repo_path: Path, edited_files: list[str]) -> list[str]:
    """
    Verify that imports referencing other files in the set still resolve on disk.
    Returns a list of error strings (empty list = OK).
    """
    all_stems = {p.stem for p in repo_path.rglob("*.py")}
    stem_to_file = {Path(f).stem: f for f in edited_files}
    errors: list[str] = []

    for f in edited_files:
        path = repo_path / f
        if not path.exists() or path.suffix != ".py":
            continue
        for imp in extract_python_imports(path):
            # Only check imports that used to resolve to one of the edited files
            if imp in stem_to_file:
                target = repo_path / stem_to_file[imp]
                if not target.exists():
                    errors.append(
                        f"{f}: import '{imp}' no longer resolves "
                        f"(expected at {stem_to_file[imp]})"
                    )
            elif imp not in all_stems:
                # It was never a local module — skip (stdlib/third-party)
                pass

    return errors
