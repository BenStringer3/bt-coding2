from __future__ import annotations

import ast
from pathlib import Path

from pyflakes.api import check
from pyflakes.reporter import Reporter


class _Buffer:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, s: str) -> None:
        self.parts.append(s)

    def flush(self) -> None:
        return None

    def text(self) -> str:
        return "".join(self.parts).strip()


def validate_python(filepath: Path) -> tuple[bool, str]:
    source = filepath.read_text(encoding="utf-8")
    try:
        ast.parse(source)
    except SyntaxError as exc:
        lineno = exc.lineno or 0
        return False, f"SyntaxError at line {lineno}: {exc.msg}"

    out = _Buffer()
    err = _Buffer()
    warnings = check(source, str(filepath), Reporter(out, err))
    warning_text = out.text() or err.text()
    if warnings and warning_text:
        return True, warning_text
    return True, ""
