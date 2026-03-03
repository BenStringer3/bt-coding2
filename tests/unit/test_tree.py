from pathlib import Path

import py_trees

from bt_agent.llm.client import LLMCallResult
from bt_agent.tree.blackboard import AgentBlackboard
from bt_agent.tree.builder import build_tree


class SeqLLM:
    def __init__(self) -> None:
        self.responses = [
            '<thought>x</thought>{"parsed_goal":"Fix bug","target_language":"python"}',
            '<thought>x</thought>{"candidate_files":["a.py"],"selected_file":"a.py"}',
            '<thought>x</thought>{"edit_plan":"1. change","edit_intent":"Fix range"}',
            '<thought>x</thought>{"old_str":"range(len(items))","new_str":"range(len(items)-1)","target_file":"a.py"}',
            '<thought>x</thought>fix(a): avoid off-by-one',
        ]

    def call(self, _system: str, _user: str) -> LLMCallResult:
        text = self.responses.pop(0)
        return LLMCallResult(text=text, raw_response=text, prompt_tokens=1, completion_tokens=1)

    @staticmethod
    def clean_json_text(text: str) -> str:
        return text.strip()


def test_build_tree_and_tick_success(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f(items):\n    return [(items[i], items[i+1]) for i in range(len(items))]\n", encoding="utf-8")
    bb = AgentBlackboard(task_description="fix", repo_path=tmp_path)
    llm = SeqLLM()
    root = build_tree(bb, llm, dry_run=True, max_attempts=2)
    tree = py_trees.trees.BehaviourTree(root)

    tick_count = 0
    while root.status == py_trees.common.Status.RUNNING or tick_count == 0:
        tree.tick()
        tick_count += 1

    assert root.status == py_trees.common.Status.SUCCESS
    assert "len(items)-1" in f.read_text(encoding="utf-8")
