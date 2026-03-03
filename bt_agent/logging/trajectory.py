from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import py_trees

from bt_agent.tree.blackboard import AgentBlackboard


class TrajectoryLogger(py_trees.visitors.VisitorBase):
    def __init__(self, output_path: Path, blackboard: AgentBlackboard):
        super().__init__(full=False)
        self.output_path = output_path
        self.blackboard = blackboard
        self._file = output_path.open("a", encoding="utf-8")

    def run(self, behaviour: py_trees.behaviour.Behaviour) -> None:
        llm_call = getattr(behaviour, "last_llm_call", None)
        error = self.blackboard.last_error if behaviour.status == py_trees.common.Status.FAILURE else None
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node": behaviour.name,
            "status": behaviour.status.name,
            "blackboard_snapshot": self.blackboard.snapshot(),
            "llm_call": llm_call,
            "error": error,
        }
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
