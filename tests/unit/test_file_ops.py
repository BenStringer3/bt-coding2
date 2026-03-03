from pathlib import Path

from bt_agent.tools.file_ops import read_windowed, str_replace
from bt_agent.tree.blackboard import StrReplaceEdit


def test_str_replace_not_found(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("print('x')\n", encoding="utf-8")
    ok, err = str_replace(tmp_path, StrReplaceEdit(old_str="missing", new_str="new", target_file="a.py"))
    assert not ok
    assert "not found" in err


def test_str_replace_multiple(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x\nx\n", encoding="utf-8")
    ok, err = str_replace(tmp_path, StrReplaceEdit(old_str="x", new_str="y", target_file="a.py"))
    assert not ok
    assert "must be unique" in err


def test_str_replace_success(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("a = 1\n", encoding="utf-8")
    ok, err = str_replace(tmp_path, StrReplaceEdit(old_str="a = 1", new_str="a = 2", target_file="a.py"))
    assert ok
    assert err == ""
    assert f.read_text(encoding="utf-8") == "a = 2\n"


def test_read_windowed(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("\n".join([f"line{i}" for i in range(1, 6)]) + "\n", encoding="utf-8")
    out = read_windowed(f, start_line=2, window=2)
    assert "Lines 2-3 shown" in out
    assert "2: line2" in out
    assert "3: line3" in out
