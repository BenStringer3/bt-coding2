import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.getenv("BT_AGENT_INTEGRATION") != "1", reason="set BT_AGENT_INTEGRATION=1")
def test_integration_off_by_one() -> None:
    cmd = [
        sys.executable,
        "-m",
        "bt_agent.cli",
        "run",
        "--task",
        "Fix the IndexError in get_pairs",
        "--repo",
        "tests/fixtures/off_by_one",
        "--dry-run",
        "--model",
        "ollama/qwen2.5-coder:7b",
    ]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert completed.returncode == 0
