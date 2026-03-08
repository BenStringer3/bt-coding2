import importlib.util
import pathlib
import pytest


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_single_item():
    mod = load_module(FIXTURE)
    cart = [{"name": "apple", "price": 1.5, "qty": 4}]
    assert mod.total_price(cart) == pytest.approx(6.0)


def test_multiple_items():
    mod = load_module(FIXTURE)
    cart = [
        {"name": "apple", "price": 1.5, "qty": 2},
        {"name": "bread", "price": 2.0, "qty": 3},
    ]
    assert mod.total_price(cart) == pytest.approx(9.0)


def test_empty_cart():
    mod = load_module(FIXTURE)
    assert mod.total_price([]) == pytest.approx(0.0)


def test_not_just_sum_of_qty():
    mod = load_module(FIXTURE)
    cart = [{"name": "item", "price": 10.0, "qty": 2}]
    result = mod.total_price(cart)
    assert result != 2, "total_price returned qty sum instead of price*qty"
    assert result == pytest.approx(20.0)
