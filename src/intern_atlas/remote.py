"""Small client for the hosted Intern Atlas API."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


DEFAULT_HOSTED_BASE_URL = "https://intern-atlas.opendatalab.org.cn/api"


def normalize_hosted_base_url(base_url: str) -> str:
    """Accept either the website root or the API root."""
    cleaned = base_url.strip().rstrip("/")
    parts = urlsplit(cleaned)
    if not parts.scheme or not parts.netloc:
        return cleaned
    path = parts.path.rstrip("/")
    if path in {"", "/"}:
        path = "/api"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


class InternAtlasClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        configured_base_url = base_url or os.getenv("INTERN_ATLAS_REMOTE_BASE_URL") or DEFAULT_HOSTED_BASE_URL
        self.base_url = normalize_hosted_base_url(configured_base_url)
        self.api_key = api_key or os.getenv("INTERN_ATLAS_API_KEY") or os.getenv("INTERN_ATLAS_REMOTE_API_KEY")
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

    def manifest(self) -> dict[str, Any]:
        return self._get("")  # type: ignore[return-value]

    def stats(self) -> dict[str, Any]:
        return self._get("/stats")  # type: ignore[return-value]

    def list_papers(
        self,
        *,
        status: str | None = None,
        tier: str | None = None,
        paper_type: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params = {"offset": str(offset), "limit": str(limit)}
        if status:
            params["status"] = status
        if tier:
            params["tier"] = tier
        if paper_type:
            params["type"] = paper_type
        return self._get("/papers", params=params)  # type: ignore[return-value]

    def search_papers(self, q: str, *, limit: int = 30) -> list[dict[str, Any]]:
        return self._get("/papers/search", params={"q": q, "limit": str(limit)})  # type: ignore[return-value]

    def get_paper(self, paper_id: str) -> dict[str, Any]:
        return self._get(f"/papers/{paper_id}")  # type: ignore[return-value]

    def unified_search(
        self,
        query: str,
        *,
        search_type: str = "auto",
        limit: int = 20,
        include_subgraph: bool = False,
    ) -> dict[str, Any]:
        return self._post(
            "/search",
            {
                "query": query,
                "type": search_type,
                "limit": limit,
                "include_subgraph": include_subgraph,
            },
        )

    def query_subgraph(self, query: str, *, max_nodes: int = 30) -> dict[str, Any]:
        return self._post("/query", {"query": query, "max_nodes": max_nodes})

    def evidence_context(
        self,
        query: str,
        *,
        max_papers: int = 20,
        max_edges: int = 40,
        mode: str = "balanced",
        depth: int | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        edge_type: str | None = None,
        method: str | None = None,
        include_prompt_context: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "max_papers": max_papers,
            "max_edges": max_edges,
            "mode": mode,
            "include_prompt_context": include_prompt_context,
        }
        if depth is not None:
            payload["depth"] = depth
        if year_from is not None:
            payload["year_from"] = year_from
        if year_to is not None:
            payload["year_to"] = year_to
        if edge_type:
            payload["edge_type"] = edge_type
        if method:
            payload["method"] = method
        try:
            return self._post("/v1/evidence/context", payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {404, 405}:
                raise
        return self.assist_context(
            query,
            budget=mode,
            use_mcts=True,
            token_budget=6000,
            max_seeds=min(max_papers, 30),
            max_edges=min(max_edges, 200),
        )

    def search_methods(self, q: str, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self._get(
            "/methods",
            params={"q": q, "limit": str(limit), "offset": str(offset)},
        )  # type: ignore[return-value]

    def evolution_edges(
        self,
        *,
        paper_id: str | None = None,
        edge_type: str | None = None,
        method: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
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
        if year_from is not None:
            params["year_from"] = str(year_from)
        if year_to is not None:
            params["year_to"] = str(year_to)
        return self._get("/edges", params=params)  # type: ignore[return-value]

    def paper_neighborhood(self, paper_id: str, *, depth: int = 1, limit: int = 100) -> dict[str, Any]:
        return self._get(f"/papers/{paper_id}/neighborhood", params={"depth": str(depth), "limit": str(limit)})

    def paper_branch(self, paper_id: str, *, depth: int = 2, limit: int = 100) -> dict[str, Any]:
        return self._get(f"/papers/{paper_id}/branch", params={"depth": str(depth), "limit": str(limit)})

    def paper_ancestry(self, paper_id: str, *, depth: int = 2, limit: int = 100) -> dict[str, Any]:
        return self._get(f"/papers/{paper_id}/ancestry", params={"depth": str(depth), "limit": str(limit)})

    def find_path(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "evolution",
        max_depth: int = 10,
    ) -> list[dict[str, Any]]:
        return self._get(
            "/path",
            params={
                "from_id": from_id,
                "to_id": to_id,
                "direction": direction,
                "max_depth": str(max_depth),
            },
        )  # type: ignore[return-value]

    def evolution_chain(
        self,
        domain: str,
        *,
        max_chains: int = 5,
        max_depth: int = 8,
        beam_width: int = 3,
        strategy: str = "mcts",
    ) -> dict[str, Any]:
        return self._get(
            "/visualization/evolution-chain",
            params={
                "domain": domain,
                "max_chains": str(max_chains),
                "max_depth": str(max_depth),
                "beam_width": str(beam_width),
                "strategy": strategy,
            },
        )  # type: ignore[return-value]

    def assist_context(
        self,
        query: str,
        *,
        budget: str = "balanced",
        use_mcts: bool = True,
        token_budget: int = 6000,
        max_seeds: int = 10,
        max_edges: int = 80,
    ) -> dict[str, Any]:
        return self._post(
            "/assist/context",
            {
                "query": query,
                "budget": budget,
                "use_mcts": use_mcts,
                "token_budget": token_budget,
                "max_seeds": max_seeds,
                "max_edges": max_edges,
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
