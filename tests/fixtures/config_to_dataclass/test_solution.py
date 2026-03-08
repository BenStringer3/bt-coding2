import importlib.util
import pathlib
import dataclasses


FIXTURE_DIR = pathlib.Path(__file__).parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_config_is_dataclass():
    mod = load_module("config", FIXTURE_DIR / "config.py")
    assert hasattr(mod, "CONFIG")
    assert dataclasses.is_dataclass(mod.CONFIG), "CONFIG should be a dataclass instance"


def test_config_is_frozen():
    mod = load_module("config", FIXTURE_DIR / "config.py")
    cfg = mod.CONFIG
    try:
        cfg.host = "changed"
        assert False, "Frozen dataclass should not allow mutation"
    except (dataclasses.FrozenInstanceError, AttributeError):
        pass


def test_config_attribute_access():
    mod = load_module("config", FIXTURE_DIR / "config.py")
    cfg = mod.CONFIG
    assert hasattr(cfg, "host")
    assert hasattr(cfg, "port")
    assert hasattr(cfg, "timeout")
    assert hasattr(cfg, "max_retries")


def test_no_dict_subscripts_in_server():
    source = (FIXTURE_DIR / "server.py").read_text()
    assert 'CONFIG["' not in source, "server.py still uses dict subscript access"
    assert "CONFIG['" not in source


def test_no_dict_subscripts_in_client():
    source = (FIXTURE_DIR / "client.py").read_text()
    assert 'CONFIG["' not in source, "client.py still uses dict subscript access"
    assert "CONFIG['" not in source
