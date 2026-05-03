"""Small client for the hosted Intern Atlas API."""

from __future__ import annotations

from typing import Any

import httpx


class InternAtlasClient:
    def __init__(
        self,
        base_url: str = "https://intern-atlas.opendatalab.org.cn/api",
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def assist_context(
        self,
        query: str,
        *,
        budget: str = "balanced",
        use_mcts: bool = True,
        token_budget: int = 6000,
    ) -> dict[str, Any]:
        return self._post(
            "/assist/context",
            {
                "query": query,
                "budget": budget,
                "use_mcts": use_mcts,
                "token_budget": token_budget,
            },
        )

    def generate_ideas(
        self,
        query: str,
        *,
        use_llm: bool = False,
        evidence_budget: str = "balanced",
    ) -> dict[str, Any]:
        return self._post(
            "/ideas",
            {
                "query": query,
                "use_llm": use_llm,
                "evidence_budget": evidence_budget,
            },
        )

    def evaluate_idea(self, idea: str, *, use_llm: bool = False) -> dict[str, Any]:
        return self._post("/eval", {"idea": idea, "use_llm": use_llm})

    def _get(self, path: str) -> dict[str, Any]:
        res = self._client.get(self.base_url + path, headers=self._headers())
        res.raise_for_status()
        return res.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        res = self._client.post(self.base_url + path, headers=self._headers(), json=payload)
        res.raise_for_status()
        return res.json()

