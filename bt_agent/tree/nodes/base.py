from __future__ import annotations

import json
import re
from abc import ABC

import py_trees

from bt_agent.llm.client import LLMClient
from bt_agent.tree.blackboard import AgentBlackboard


class BaseLLMNode(py_trees.behaviour.Behaviour, ABC):
    def __init__(self, name: str, blackboard: AgentBlackboard, llm: LLMClient):
        super().__init__(name=name)
        self.bb = blackboard
        self.llm = llm
        self.last_llm_call: dict | None = None

    @staticmethod
    def _extract_thought(raw_text: str) -> tuple[str | None, str]:
        match = re.search(r"<thought>(.*?)</thought>", raw_text, flags=re.DOTALL | re.IGNORECASE)
        thought = match.group(1).strip() if match else None
        cleaned = re.sub(r"<thought>.*?</thought>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
        return thought, cleaned

    def _call_llm_json(self, system: str, user: str, retries: int = 2) -> dict:
        current_user = user
        last_error = ""
        for _ in range(retries + 1):
            result = self.llm.call(system, current_user)
            thought, cleaned = self._extract_thought(result.text)
            cleaned = self.llm.clean_json_text(cleaned)
            self.last_llm_call = {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "raw_response": result.raw_response,
                "thought": thought,
            }
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as exc:
                last_error = str(exc)
                current_user = (
                    f"{user}\n\nYour prior output was invalid JSON: {exc}. "
                    "Return valid JSON only and preserve the required keys."
                )

        raise ValueError(f"Invalid JSON: {last_error}")

    def _call_llm_text(self, system: str, user: str) -> str:
        result = self.llm.call(system, user)
        thought, cleaned = self._extract_thought(result.text)
        self.last_llm_call = {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "raw_response": result.raw_response,
            "thought": thought,
        }
        return cleaned.strip()
