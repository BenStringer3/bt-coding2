import importlib.util
import pathlib
import pytest


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_average_empty_returns_zero():
    mod = load_module(FIXTURE)
    assert mod.average([]) == 0.0, "average([]) should return 0.0, not raise"


def test_average_single():
    mod = load_module(FIXTURE)
    assert mod.average([5]) == pytest.approx(5.0)


def test_average_multiple():
    mod = load_module(FIXTURE)
    assert mod.average([1, 2, 3, 4]) == pytest.approx(2.5)


def test_median_unchanged():
    mod = load_module(FIXTURE)
    assert mod.median([]) is None
    assert mod.median([1, 2, 3]) == 2
    assert mod.median([1, 2, 3, 4]) == pytest.approx(2.5)
