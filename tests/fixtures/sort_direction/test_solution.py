import importlib.util
import pathlib


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_top_scores_descending():
    mod = load_module(FIXTURE)
    result = mod.top_scores([40, 10, 90, 55, 70], 3)
    assert result == [90, 70, 55], f"Expected [90, 70, 55], got {result}"


def test_top_scores_default_n():
    mod = load_module(FIXTURE)
    result = mod.top_scores([5, 3, 8, 1, 9, 2])
    assert result == [9, 8, 5]


def test_top_scores_all():
    mod = load_module(FIXTURE)
    result = mod.top_scores([3, 1, 2], 3)
    assert result == [3, 2, 1]


def test_top_scores_single():
    mod = load_module(FIXTURE)
    assert mod.top_scores([7, 2, 5], 1) == [7]
