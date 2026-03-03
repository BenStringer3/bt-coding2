from __future__ import annotations

import os
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "dist", "build"}


def build_repo_map(repo_path: Path, max_depth: int = 3, max_lines: int = 200) -> str:
    repo_path = repo_path.resolve()
    lines: list[str] = []
    omitted = 0

    for root, dirs, files in os.walk(repo_path):
        root_path = Path(root)
        rel_parts = root_path.relative_to(repo_path).parts
        depth = len(rel_parts)

        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if depth >= max_depth:
            dirs[:] = []

        if depth > 0:
            indent = "  " * (depth - 1)
            lines.append(f"{indent}{root_path.name}/")

        for name in sorted(files):
            indent = "  " * depth
            lines.append(f"{indent}{name}")
            if len(lines) >= max_lines:
                remaining_here = len(files) - sorted(files).index(name) - 1
                omitted += max(0, remaining_here)
                lines.append(f"... truncated, {omitted} additional files omitted")
                return "\n".join(lines[:max_lines])

    return "\n".join(lines[:max_lines])
