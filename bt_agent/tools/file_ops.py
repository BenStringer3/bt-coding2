from __future__ import annotations

from pathlib import Path

from bt_agent.tree.blackboard import StrReplaceEdit


def read_windowed(filepath: Path, start_line: int = 1, window: int = 100, overlap: int = 2) -> str:
    _ = overlap
    lines = filepath.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    start = max(0, start_line - 1)
    end = min(total, start + window)

    header = f"[File: {filepath} ({total} lines total)]\n"
    if start > 0:
        header += f"[Lines {start + 1}-{end} shown. Lines 1-{start} omitted.]\n"
    else:
        header += f"[Lines 1-{end} shown.]\n"

    body = "\n".join(f"{i + start + 1}: {line}" for i, line in enumerate(lines[start:end]))
    if end < total:
        body += f"\n[... {total - end} more lines not shown]"

    return header + body


def str_replace(repo_path: Path, edit: StrReplaceEdit) -> tuple[bool, str]:
    filepath = repo_path / edit.target_file
    if not filepath.exists():
        return False, f"target file not found: {edit.target_file}"
    content = filepath.read_text(encoding="utf-8")
    count = content.count(edit.old_str)
    if count == 0:
        return False, f"old_str not found in {edit.target_file}. Check exact whitespace."
    if count > 1:
        return False, f"old_str found {count} times - it must be unique. Make old_str longer."

    new_content = content.replace(edit.old_str, edit.new_str, 1)
    try:
        filepath.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        return False, f"failed writing {edit.target_file}: {exc}"
    return True, ""
