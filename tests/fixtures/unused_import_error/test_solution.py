import importlib.util
import pathlib


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_module_imports_without_error():
    # This will raise ImportError if ChainMapp is still present
    load_module(FIXTURE)


def test_no_chainmapp_typo():
    source = FIXTURE.read_text()
    assert "ChainMapp" not in source, "Typo 'ChainMapp' still present"


def test_group_by_key_works():
    mod = load_module(FIXTURE)
    result = mod.group_by_key(["apple", "ant", "banana"], lambda s: s[0])
    assert set(result["a"]) == {"apple", "ant"}
    assert result["b"] == ["banana"]


def test_get_env_works():
    mod = load_module(FIXTURE)
    assert mod.get_env("NONEXISTENT_VAR_XYZ", "default") == "default"
