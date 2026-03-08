import importlib.util
import pathlib


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_get_pairs_no_index_error():
    mod = load_module(FIXTURE)
    mod.get_pairs([1, 2, 3])  # must not raise


def test_get_pairs_two_elements():
    mod = load_module(FIXTURE)
    assert mod.get_pairs([1, 2]) == [(1, 2)]


def test_get_pairs_three_elements():
    mod = load_module(FIXTURE)
    assert mod.get_pairs([10, 20, 30]) == [(10, 20), (20, 30)]


def test_get_pairs_empty():
    mod = load_module(FIXTURE)
    assert mod.get_pairs([]) == []


def test_get_pairs_single():
    mod = load_module(FIXTURE)
    assert mod.get_pairs([42]) == []
