import importlib.util
import pathlib
import ast


def load_module(path):
    spec = importlib.util.spec_from_file_location("buggy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FIXTURE = pathlib.Path(__file__).parent / "buggy.py"


def test_no_typo_in_source():
    source = FIXTURE.read_text()
    assert "recieved" not in source, "Typo 'recieved' still present in source"


def test_parse_response_returns_received_at():
    mod = load_module(FIXTURE)
    result = mod.parse_response({"timestamp": "2024-01-01", "status": 200})
    assert "received_at" in result
    assert result["received_at"] == "2024-01-01"


def test_parse_response_defaults():
    mod = load_module(FIXTURE)
    result = mod.parse_response({})
    assert result["received_at"] is None
    assert result["status"] == 200
    assert result["payload"] == {}
