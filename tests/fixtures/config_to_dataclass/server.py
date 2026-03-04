"""HTTP server that reads settings from the shared config dict."""

from config import CONFIG


def start_server() -> None:
    host = CONFIG["host"]
    port = CONFIG["port"]
    print(f"Listening on {host}:{port}")


def get_address() -> str:
    return f"{CONFIG['host']}:{CONFIG['port']}"
