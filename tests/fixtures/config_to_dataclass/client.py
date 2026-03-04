"""HTTP client that reads connection settings from the shared config dict."""

import time

from config import CONFIG


def fetch(url: str) -> str:
    timeout = CONFIG["timeout"]
    retries = CONFIG["max_retries"]
    for attempt in range(retries):
        try:
            # Simulated request
            time.sleep(0)
            return f"response from {url}"
        except Exception:
            if attempt == retries - 1:
                raise
    return ""
