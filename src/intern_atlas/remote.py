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

    def evidence_context(
        self,
        query: str,
        *,
        max_papers: int = 20,
        max_edges: int = 40,
        include_prompt_context: bool = True,
    ) -> dict[str, Any]:
        return self._post(
            "/v1/evidence/context",
            {
                "query": query,
                "max_papers": max_papers,
                "max_edges": max_edges,
                "include_prompt_context": include_prompt_context,
            },
        )

    def search_methods(self, q: str, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._get(
            "/v1/methods/search",
            params={"q": q, "limit": str(limit), "offset": str(offset)},
        )  # type: ignore[return-value]

    def evolution_edges(
        self,
        *,
        paper_id: str | None = None,
        edge_type: str | None = None,
        method: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params = {"limit": str(limit), "offset": str(offset)}
        if paper_id:
            params["paper_id"] = paper_id
        if edge_type:
            params["edge_type"] = edge_type
        if method:
            params["method"] = method
        return self._get("/v1/evolution/edges", params=params)  # type: ignore[return-value]

    def paper_neighborhood(self, paper_id: str, *, depth: int = 1, limit: int = 100) -> dict[str, Any]:
        return self._get(f"/v1/papers/{paper_id}/neighborhood", params={"depth": str(depth), "limit": str(limit)})

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

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        res = self._client.get(self.base_url + path, headers=self._headers(), params=params)
        res.raise_for_status()
        return res.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        res = self._client.post(self.base_url + path, headers=self._headers(), json=payload)
        res.raise_for_status()
        return res.json()
