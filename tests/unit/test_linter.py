from pathlib import Path

from bt_agent.tools.linter import validate_python


def test_validate_python_ok(tmp_path: Path) -> None:
    f = tmp_path / "ok.py"
    f.write_text("x = 1\n", encoding="utf-8")
    ok, _ = validate_python(f)
    assert ok


def test_validate_python_syntax_error(tmp_path: Path) -> None:
    f = tmp_path / "bad.py"
    f.write_text("def f(:\n    pass\n", encoding="utf-8")
    ok, err = validate_python(f)
    assert not ok
    assert "SyntaxError" in err
