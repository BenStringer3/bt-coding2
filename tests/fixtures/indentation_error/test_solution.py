import importlib.util
import pathlib


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_module_loads_without_syntax_error():
    load_module(FIXTURE)


def test_categorise_all_grades():
    mod = load_module(FIXTURE)
    assert mod.categorise(95) == "A"
    assert mod.categorise(85) == "B"
    assert mod.categorise(75) == "C"
    assert mod.categorise(65) == "D"
    assert mod.categorise(55) == "F"


def test_boundaries():
    mod = load_module(FIXTURE)
    assert mod.categorise(90) == "A"
    assert mod.categorise(80) == "B"
    assert mod.categorise(70) == "C"
    assert mod.categorise(60) == "D"
