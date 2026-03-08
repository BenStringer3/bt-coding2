import importlib.util
import pathlib
import pytest


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_split_bill_fractional():
    mod = load_module(FIXTURE)
    result = mod.split_bill(100, 3)
    assert result == pytest.approx(33.333, rel=1e-3), (
        f"Expected ~33.333 but got {result} — floor division still in use?"
    )


def test_split_bill_even():
    mod = load_module(FIXTURE)
    assert mod.split_bill(90, 3) == pytest.approx(30.0)


def test_percentage_fractional():
    mod = load_module(FIXTURE)
    result = mod.percentage(1, 3)
    assert result == pytest.approx(33.333, rel=1e-3), (
        f"Expected ~33.333 but got {result}"
    )


def test_percentage_whole():
    mod = load_module(FIXTURE)
    assert mod.percentage(1, 4) == pytest.approx(25.0)
