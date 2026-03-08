import importlib.util
import pathlib


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_factorial_zero():
    mod = load_module(FIXTURE)
    assert mod.factorial(0) == 1, "factorial(0) should be 1"


def test_factorial_one():
    mod = load_module(FIXTURE)
    assert mod.factorial(1) == 1


def test_factorial_five():
    mod = load_module(FIXTURE)
    assert mod.factorial(5) == 120


def test_factorial_ten():
    mod = load_module(FIXTURE)
    assert mod.factorial(10) == 3628800
