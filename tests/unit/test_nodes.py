from pathlib import Path

import py_trees

from bt_agent.llm.client import LLMCallResult
from bt_agent.tree.blackboard import AgentBlackboard, StrReplaceEdit
from bt_agent.tree.nodes.base import BaseLLMNode
from bt_agent.tree.nodes.commit import GitCommit
from bt_agent.tree.nodes.edit import ApplyEdit, ReadTargetFile
from bt_agent.tree.nodes.gather import BuildRepoMap
from bt_agent.tree.nodes.validate import ValidateEdit


class DummyLLM:
    def call(self, _system: str, _user: str) -> LLMCallResult:
        return LLMCallResult(text='{"ok": true}', raw_response='{"ok": true}', prompt_tokens=1, completion_tokens=1)

    @staticmethod
    def clean_json_text(text: str) -> str:
        return text


def test_build_repo_map_success(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("x=1\n", encoding="utf-8")
    bb = AgentBlackboard(task_description="t", repo_path=tmp_path)
    node = BuildRepoMap(bb)
    assert node.update() == py_trees.common.Status.SUCCESS
    assert bb.repo_map is not None


def test_read_target_file_success(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x=1\n", encoding="utf-8")
    bb = AgentBlackboard(task_description="t", repo_path=tmp_path, selected_file="a.py")
    node = ReadTargetFile(bb)
    assert node.update() == py_trees.common.Status.SUCCESS
    assert bb.current_file_content == "x=1\n"


def test_apply_edit_failure(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    bb = AgentBlackboard(
        task_description="t",
        repo_path=tmp_path,
        proposed_edit=StrReplaceEdit(old_str="missing", new_str="y", target_file="a.py"),
    )
    node = ApplyEdit(bb)
    assert node.update() == py_trees.common.Status.FAILURE
    assert bb.last_error is not None


def test_validate_edit_reverts_on_failure(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x=1\n", encoding="utf-8")
    bb = AgentBlackboard(
        task_description="t",
        repo_path=tmp_path,
        selected_file="a.py",
        current_file_content="x=1\n",
        target_language="python",
    )
    f.write_text("def bad(:\n", encoding="utf-8")
    node = ValidateEdit(bb)
    assert node.update() == py_trees.common.Status.FAILURE
    assert bb.edit_attempts == 1
    assert f.read_text(encoding="utf-8") == "x=1\n"


def test_git_commit_dry_run(tmp_path: Path) -> None:
    bb = AgentBlackboard(task_description="t", repo_path=tmp_path)
    node = GitCommit(bb, dry_run=True)
    assert node.update() == py_trees.common.Status.SUCCESS


class _ProbeNode(BaseLLMNode):
    def update(self) -> py_trees.common.Status:
        return py_trees.common.Status.SUCCESS


class _FlakyLLM:
    def __init__(self, fail_times: int, response_text: str):
        self.fail_times = fail_times
        self.response_text = response_text
        self.calls = 0

    def call(self, _system: str, _user: str) -> LLMCallResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("temporary connection error")
        return LLMCallResult(
            text=self.response_text,
            raw_response=self.response_text,
            prompt_tokens=1,
            completion_tokens=1,
        )

    @staticmethod
    def clean_json_text(text: str) -> str:
        return text


def test_base_llm_json_retries_on_call_failure(tmp_path: Path) -> None:
    bb = AgentBlackboard(task_description="t", repo_path=tmp_path)
    llm = _FlakyLLM(fail_times=1, response_text='{"k":"v"}')
    node = _ProbeNode("probe", bb, llm)
    payload = node._call_llm_json("sys", "user", retries=2, retry_delay_s=0.0)
    assert payload == {"k": "v"}
    assert llm.calls == 2


def test_base_llm_text_retries_on_call_failure(tmp_path: Path) -> None:
    bb = AgentBlackboard(task_description="t", repo_path=tmp_path)
    llm = _FlakyLLM(fail_times=1, response_text="hello")
    node = _ProbeNode("probe", bb, llm)
    text = node._call_llm_text("sys", "user", retries=2, retry_delay_s=0.0)
    assert text == "hello"
    assert llm.calls == 2
