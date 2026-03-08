from __future__ import annotations

import json
import re
from abc import ABC
from time import sleep

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
        match = re.search(r"<(?:thought|think)>(.*?)</(?:thought|think)>", raw_text, flags=re.DOTALL | re.IGNORECASE)
        thought = match.group(1).strip() if match else None
        cleaned = re.sub(r"<(?:thought|think)>.*?</(?:thought|think)>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
        return thought, cleaned

    def _call_llm_json(self, system: str, user: str, retries: int = 2, retry_delay_s: float = 0.2) -> dict:
        current_user = user
        last_error = ""
        for attempt in range(retries + 1):
            try:
                result = self.llm.call(system, current_user)
            except Exception as exc:
                last_error = str(exc)
                if attempt < retries:
                    sleep(retry_delay_s)
                    continue
                raise RuntimeError(f"LLM call failed after retries: {last_error}") from exc
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
                # Recover common small-model failure: valid JSON object followed by extra text/JSON.
                try:
                    first_obj, _ = json.JSONDecoder().raw_decode(cleaned)
                    if isinstance(first_obj, dict):
                        return first_obj
                except json.JSONDecodeError:
                    pass
                # Recover when model prepends analysis text (e.g. <think>...) before JSON.
                for opener in ("{", "["):
                    idx = cleaned.find(opener)
                    if idx < 0:
                        continue
                    try:
                        first_obj, _ = json.JSONDecoder().raw_decode(cleaned[idx:])
                        if isinstance(first_obj, dict):
                            return first_obj
                    except json.JSONDecodeError:
                        continue
                last_error = str(exc)
                current_user = (
                    f"{user}\n\nYour prior output was invalid JSON: {exc}. "
                    "Return valid JSON only and preserve the required keys."
                )
                if attempt < retries:
                    sleep(retry_delay_s)

        raise ValueError(f"Invalid JSON: {last_error}")

    def _call_llm_text(self, system: str, user: str, retries: int = 2, retry_delay_s: float = 0.2) -> str:
        last_error = ""
        for attempt in range(retries + 1):
            try:
                result = self.llm.call(system, user)
            except Exception as exc:
                last_error = str(exc)
                if attempt < retries:
                    sleep(retry_delay_s)
                    continue
                raise RuntimeError(f"LLM call failed after retries: {last_error}") from exc

            thought, cleaned = self._extract_thought(result.text)
            self.last_llm_call = {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "raw_response": result.raw_response,
                "thought": thought,
            }
            return cleaned.strip()

        raise RuntimeError(f"LLM call failed after retries: {last_error}")
