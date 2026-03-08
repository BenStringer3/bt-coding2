import importlib.util
import pathlib
import pytest


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_compute_discount_returns_float():
    mod = load_module(FIXTURE)
    result = mod.compute_discount(100, 20)
    assert result is not None, "compute_discount returned None"
    assert isinstance(result, (int, float))


def test_compute_discount_value():
    mod = load_module(FIXTURE)
    assert mod.compute_discount(200, 10) == pytest.approx(180.0)
    assert mod.compute_discount(50, 50) == pytest.approx(25.0)


def test_apply_discounts():
    mod = load_module(FIXTURE)
    results = mod.apply_discounts([100, 200], 10)
    assert results == pytest.approx([90.0, 180.0])
    assert None not in results
