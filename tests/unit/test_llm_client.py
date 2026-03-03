from unittest.mock import patch

import pytest

from bt_agent.llm.client import LLMCallResult, LLMClient


class DummyChoice:
    def __init__(self, content: str) -> None:
        self.message = type("Message", (), {"content": content})


class DummyUsage:
    prompt_tokens = 10
    completion_tokens = 5


class DummyResponse:
    def __init__(self, content: str) -> None:
        self.choices = [DummyChoice(content)]
        self.usage = DummyUsage()


@patch("litellm.completion", return_value=DummyResponse("```json\n{\"a\": 1}\n```"))
def test_call_json_strips_fences(_mock_completion) -> None:
    client = LLMClient("test-model")
    data = client.call_json("sys", "user")
    assert data["a"] == 1


@patch("litellm.completion", return_value=DummyResponse('{"a": 2}'))
def test_call_json_plain(_mock_completion) -> None:
    client = LLMClient("test-model")
    data = client.call_json("sys", "user")
    assert data["a"] == 2


def test_call_json_invalid() -> None:
    client = LLMClient("test-model")

    def _bad_call(_system: str, _user: str) -> LLMCallResult:
        return LLMCallResult(text="not json", raw_response="not json", prompt_tokens=None, completion_tokens=None)

    client.call = _bad_call  # type: ignore[method-assign]
    with pytest.raises(ValueError):
        client.call_json("sys", "user", max_retries=0)
