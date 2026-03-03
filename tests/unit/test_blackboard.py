from pathlib import Path

from bt_agent.tree.blackboard import AgentBlackboard, StrReplaceEdit


def test_blackboard_round_trip() -> None:
    bb = AgentBlackboard(task_description="fix bug", repo_path=Path("."))
    bb.proposed_edit = StrReplaceEdit(old_str="a", new_str="b", target_file="x.py")

    data = bb.model_dump()
    bb2 = AgentBlackboard.model_validate(data)

    assert bb2.task_description == "fix bug"
    assert bb2.proposed_edit is not None
    assert bb2.proposed_edit.target_file == "x.py"
