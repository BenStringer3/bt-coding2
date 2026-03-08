import importlib.util
import pathlib


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_age_zero_is_valid():
    mod = load_module(FIXTURE)
    assert mod.is_valid_age(0) is True, "age 0 should be valid"


def test_age_120_is_valid():
    mod = load_module(FIXTURE)
    assert mod.is_valid_age(120) is True


def test_age_negative_is_invalid():
    mod = load_module(FIXTURE)
    assert mod.is_valid_age(-1) is False


def test_age_121_is_invalid():
    mod = load_module(FIXTURE)
    assert mod.is_valid_age(121) is False


def test_typical_ages():
    mod = load_module(FIXTURE)
    for age in [1, 25, 65, 100]:
        assert mod.is_valid_age(age) is True
