"""OpenAI-compatible chat client used by the local graph builder."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .util import parse_json_object


class LLMClient:
    """Minimal OpenAI-compatible chat client with model fallback.

    Configuration is read from environment variables:

    - S4S_LLM_BASE_URL or OPENAI_BASE_URL
    - S4S_LLM_API_KEY or OPENAI_API_KEY
    - S4S_LLM_MODELS or S4S_LLM_MODEL or OPENAI_MODEL
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        models: list[str] | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = (base_url or _env("S4S_LLM_BASE_URL", "OPENAI_BASE_URL", default="https://api.openai.com/v1")).rstrip("/")
        self.api_key = api_key or _env("S4S_LLM_API_KEY", "OPENAI_API_KEY", default="")
        raw_models = models or _split_models(
            _env("S4S_LLM_MODELS", "S4S_LLM_MODEL", "OPENAI_MODEL", default="gpt-4o-mini")
        )
        self.models = raw_models or ["gpt-4o-mini"]
        self.timeout = timeout_seconds
        self._client = httpx.Client(timeout=timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        self._client.close()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
        json_object: bool = False,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("Set S4S_LLM_API_KEY or OPENAI_API_KEY before using LLM mode.")

        last_error: Exception | None = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for model in self.models:
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_object:
                payload["response_format"] = {"type": "json_object"}
            try:
                res = self._client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if res.status_code >= 400 and json_object:
                    payload.pop("response_format", None)
                    res = self._client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                res.raise_for_status()
                data = res.json()
                return str(data["choices"][0]["message"]["content"] or "")
            except Exception as exc:  # try the next configured model
                last_error = exc
        raise RuntimeError(f"LLM request failed after {len(self.models)} model(s): {last_error}")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        raw = self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_object=True,
        )
        return parse_json_object(raw)


def llm_configured() -> bool:
    return bool(_env("S4S_LLM_API_KEY", "OPENAI_API_KEY", default=""))


def _env(*names: str, default: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _split_models(value: str) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return [x.strip() for x in value.split(",") if x.strip()]

