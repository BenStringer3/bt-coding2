import importlib.util
import pathlib


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_no_mutable_default():
    source = FIXTURE.read_text()
    # The signature should not have '=[]' as a default
    assert "=[]" not in source.replace(" ", ""), (
        "Mutable default list still present in signature"
    )


def test_independent_calls():
    mod = load_module(FIXTURE)
    r1 = mod.append_item("a")
    r2 = mod.append_item("b")
    assert r1 == ["a"], f"First call should return ['a'], got {r1}"
    assert r2 == ["b"], f"Second call should return ['b'], got {r2}"


def test_explicit_collection():
    mod = load_module(FIXTURE)
    existing = [1, 2]
    result = mod.append_item(3, existing)
    assert result == [1, 2, 3]
