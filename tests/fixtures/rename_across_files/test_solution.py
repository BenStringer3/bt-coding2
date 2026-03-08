import importlib.util
import pathlib


FIXTURE_DIR = pathlib.Path(__file__).parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_utils_has_sum_items():
    mod = load_module("utils", FIXTURE_DIR / "utils.py")
    assert hasattr(mod, "sum_items"), "utils.py must define sum_items"
    assert not hasattr(mod, "compute_total"), "compute_total should be removed"


def test_sum_items_works():
    mod = load_module("utils", FIXTURE_DIR / "utils.py")
    assert mod.sum_items([1, 2, 3]) == 6


def test_main_imports_sum_items():
    source = (FIXTURE_DIR / "main.py").read_text()
    assert "sum_items" in source, "main.py should reference sum_items"
    assert "compute_total" not in source, "main.py still references compute_total"
