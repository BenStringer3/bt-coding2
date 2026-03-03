from __future__ import annotations

import json
import re
from dataclasses import dataclass

import litellm


@dataclass
class LLMCallResult:
    text: str
    raw_response: str
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMClient:
    def __init__(self, model: str, temperature: float = 0.0, max_tokens: int = 2048):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def call(self, system: str, user: str) -> LLMCallResult:
        response = litellm.completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
        return LLMCallResult(
            text=content,
            raw_response=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    @staticmethod
    def clean_json_text(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def call_json(self, system: str, user: str, max_retries: int = 2) -> dict:
        current_user = user
        errors: list[str] = []
        for _ in range(max_retries + 1):
            result = self.call(system, current_user)
            try:
                return json.loads(self.clean_json_text(result.text))
            except json.JSONDecodeError as exc:
                errors.append(str(exc))
                current_user = (
                    f"{user}\n\nYour last response was invalid JSON: {exc}. "
                    "Respond with valid JSON only."
                )
        raise ValueError(f"Invalid JSON after retries: {errors[-1]}")
