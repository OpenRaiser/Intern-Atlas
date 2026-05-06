"""FastAPI app for querying a local Intern Atlas SQLite graph."""

import os
from pathlib import Path
from typing import Any

import httpx

from .db import connect, graph_stats, paper_summary
from .evidence import (
    bfs_papers,
    build_evidence_pack,
    collect_relevant_paper_ids,
    fetch_edges,
    fetch_methods,
    llm_tool_manifest,
    subgraph,
)
from .remote import InternAtlasClient
from .ui import INDEX_HTML


def create_app(db_path: str | Path):
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel, Field

    conn = connect(db_path, readonly=True)
    app = FastAPI(
        title="Intern Atlas Local API",
        version="0.1.0",
        description="Read API for a local methodology-evolution graph.",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    extra_origins = [
        origin.strip()
        for origin in os.getenv("INTERN_ATLAS_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=extra_origins,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class QueryRequest(BaseModel):
        query: str = Field(..., min_length=1, max_length=500)
        max_nodes: int = Field(60, ge=1, le=300)

    class EvidenceRequest(BaseModel):
        query: str = Field(..., min_length=1, max_length=500)
        max_papers: int = Field(20, ge=1, le=100)
        max_edges: int = Field(40, ge=0, le=300)
        mode: str = Field("balanced", pattern="^(light|balanced|deep)$")
        depth: int | None = Field(None, ge=0, le=4)
        year_from: int | None = Field(None, ge=1900, le=2100)
        year_to: int | None = Field(None, ge=1900, le=2100)
        edge_type: str | None = Field(None, max_length=80)
        method: str | None = Field(None, max_length=200)
        include_prompt_context: bool = True

    class RemoteConfigRequest(BaseModel):
        base_url: str | None = Field(None, max_length=500)
        api_key: str | None = Field(None, max_length=500)

    class RemoteEvidenceRequest(EvidenceRequest):
        base_url: str | None = Field(None, max_length=500)
        api_key: str | None = Field(None, max_length=500)

    class RemoteNeighborhoodRequest(RemoteConfigRequest):
        paper_id: str = Field(..., min_length=1, max_length=200)
        depth: int = Field(1, ge=0, le=4)
        limit: int = Field(100, ge=10, le=300)

    class RemotePaperListRequest(RemoteConfigRequest):
        status: str | None = Field(None, max_length=20)
        tier: str | None = Field(None, max_length=20)
        paper_type: str | None = Field(None, max_length=50)
        offset: int = Field(0, ge=0)
        limit: int = Field(50, ge=1, le=200)

    class RemotePaperDetailRequest(RemoteConfigRequest):
        paper_id: str = Field(..., min_length=1, max_length=200)

    class RemoteSearchRequest(RemoteConfigRequest):
        query: str = Field(..., min_length=1, max_length=500)
        search_type: str = Field("auto", pattern="^(auto|keyword|title|direction|paper_id)$")
        limit: int = Field(20, ge=1, le=100)
        include_subgraph: bool = False

    class RemoteQueryRequest(RemoteConfigRequest):
        query: str = Field(..., min_length=1, max_length=500)
        max_nodes: int = Field(30, ge=1, le=300)

    class RemotePathRequest(RemoteConfigRequest):
        from_id: str = Field(..., min_length=1, max_length=200)
        to_id: str = Field(..., min_length=1, max_length=200)
        direction: str = Field("evolution", pattern="^(evolution|ancestry|both)$")
        max_depth: int = Field(10, ge=1, le=12)

    class RemoteChainRequest(RemoteConfigRequest):
        domain: str = Field(..., min_length=1, max_length=200)
        max_chains: int = Field(5, ge=1, le=10)
        max_depth: int = Field(8, ge=2, le=15)
        beam_width: int = Field(3, ge=1, le=8)
        strategy: str = Field("mcts", pattern="^(mcts|beam)$")

    class RemoteAssistRequest(RemoteConfigRequest):
        query: str = Field(..., min_length=1, max_length=500)
        budget: str = Field("balanced", pattern="^(light|balanced|deep)$")
        use_mcts: bool = True
        token_budget: int = Field(6000, ge=1000, le=30000)

    class RemoteIdeaRequest(RemoteConfigRequest):
        query: str = Field(..., min_length=1, max_length=500)
        use_llm: bool = False
        evidence_budget: str = Field("balanced", pattern="^(light|balanced|deep)$")

    class RemoteEvalRequest(RemoteConfigRequest):
        idea: str = Field(..., min_length=1, max_length=4000)
        use_llm: bool = False

    def call_remote(req: RemoteConfigRequest, fn) -> Any:
        base_url = (req.base_url or "").strip() or None
        api_key = (req.api_key or "").strip() or None
        if base_url and not base_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="base_url must start with http:// or https://")
        client = InternAtlasClient(base_url, api_key=api_key)
        try:
            return fn(client)
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] or exc.response.reason_phrase
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"hosted API unavailable: {exc}") from exc
        finally:
            client.close()

    def mark_remote(data: Any) -> Any:
        if isinstance(data, dict):
            data.setdefault("source", "hosted")
        return data

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return INDEX_HTML

    @app.on_event("shutdown")
    def _shutdown() -> None:
        conn.close()

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": {"file": Path(db_path).name, "connected": True}}

    @app.get("/api/stats")
    def stats() -> dict[str, int]:
        return graph_stats(conn)

    @app.get("/api/manifest")
    def manifest() -> dict[str, Any]:
        return {
            "name": "Intern Atlas Local API",
            "version": "0.1.0",
            "database": Path(db_path).name,
            "docs": "/api/docs",
            "endpoints": [
                "GET /api/health",
                "GET /api/stats",
                "GET /api/papers/search?q=...",
                "GET /api/papers/{paper_id}",
                "GET /api/edges",
                "POST /api/v1/evidence/context",
                "GET /api/v1/methods/search?q=...",
                "GET /api/v1/evolution/edges",
                "POST /api/v1/remote/health",
                "POST /api/v1/remote/search",
                "POST /api/v1/remote/query",
                "POST /api/v1/remote/evidence/context",
                "POST /api/v1/remote/papers",
                "POST /api/v1/remote/papers/detail",
                "POST /api/v1/remote/papers/neighborhood",
                "POST /api/v1/remote/path",
                "POST /api/v1/remote/visualization/evolution-chain",
                "POST /api/query",
                "POST /api/assist/context",
            ],
        }

    @app.get("/api/papers")
    def list_papers(
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM papers ORDER BY year DESC, title LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [paper_summary(row) for row in rows]

    @app.get("/api/papers/search")
    def search_papers(
        q: str = Query("", max_length=200),
        limit: int = Query(20, ge=1, le=50),
    ) -> list[dict[str, Any]]:
        if not q.strip():
            return []
        rows = conn.execute(
            """
            SELECT * FROM papers
            WHERE title LIKE ? OR abstract LIKE ?
            ORDER BY year DESC, title
            LIMIT ?
            """,
            (f"%{q}%", f"%{q}%", limit),
        ).fetchall()
        return [paper_summary(row) for row in rows]

    @app.get("/api/papers/{paper_id}")
    def get_paper(paper_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM papers WHERE internal_id = ?", (paper_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="paper not found")
        paper = paper_summary(row)
        paper["methods"] = [
            dict(r)
            for r in conn.execute(
                """
                SELECT m.method_id, m.canonical_name, pm.relationship, pm.confidence
                FROM paper_methods pm
                JOIN methods m ON m.method_id = pm.method_id
                WHERE pm.paper_id = ?
                ORDER BY pm.confidence DESC
                """,
                (paper_id,),
            )
        ]
        return paper

    @app.get("/api/edges")
    def list_edges(
        paper_id: str | None = None,
        edge_type: str | None = None,
        method: str | None = Query(None, max_length=200),
        year_from: int | None = Query(None, ge=1900, le=2100),
        year_to: int | None = Query(None, ge=1900, le=2100),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return fetch_edges(
            conn,
            paper_id=paper_id,
            edge_type=edge_type,
            method=method,
            year_from=year_from,
            year_to=year_to,
            offset=offset,
            limit=limit,
        )

    @app.get("/api/methods")
    def list_methods(
        q: str = Query("", max_length=200),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return fetch_methods(conn, q=q, offset=offset, limit=limit)

    @app.get("/api/papers/{paper_id}/neighborhood")
    def neighborhood(
        paper_id: str,
        depth: int = Query(1, ge=0, le=4),
        limit: int = Query(100, ge=10, le=300),
    ) -> dict[str, Any]:
        ids = bfs_papers(conn, paper_id, depth=depth, max_nodes=limit)
        if not ids:
            raise HTTPException(status_code=404, detail="paper not found")
        return subgraph(conn, ids, center_id=paper_id)

    @app.post("/api/query")
    def query(req: QueryRequest) -> dict[str, Any]:
        ids = collect_relevant_paper_ids(conn, req.query, max_nodes=req.max_nodes, depth=1)
        return subgraph(conn, set(ids))

    @app.post("/api/v1/query")
    def v1_query(req: QueryRequest) -> dict[str, Any]:
        return query(req)

    @app.post("/api/v1/evidence/context")
    def v1_evidence_context(req: EvidenceRequest) -> dict[str, Any]:
        return build_evidence_pack(
            conn,
            req.query,
            max_papers=req.max_papers,
            max_edges=req.max_edges,
            mode=req.mode,
            depth=req.depth,
            year_from=req.year_from,
            year_to=req.year_to,
            edge_type=req.edge_type,
            method=req.method,
            include_prompt_context=req.include_prompt_context,
        )

    @app.post("/api/assist/context")
    def assist_context(req: QueryRequest) -> dict[str, Any]:
        pack = build_evidence_pack(
            conn,
            req.query,
            max_papers=min(req.max_nodes, 20),
            max_edges=40,
            mode="balanced",
            depth=1,
            year_from=None,
            year_to=None,
            edge_type=None,
            method=None,
            include_prompt_context=True,
        )
        return {
            "query": req.query,
            "papers": pack["papers"][:12],
            "evolution_edges": pack["method_edges"][:20],
            "suggested_prompt_context": pack["suggested_prompt_context"],
            "evidence_pack": pack,
        }

    @app.post("/api/v1/assist/context")
    def v1_assist_context(req: QueryRequest) -> dict[str, Any]:
        return assist_context(req)

    @app.get("/api/v1/manifest")
    def v1_manifest() -> dict[str, Any]:
        data = manifest()
        data["api_version"] = "v1"
        data["llm_tool_endpoint"] = "/api/v1/llm/tools"
        return data

    @app.get("/api/v1/methods/search")
    def v1_search_methods(
        q: str = Query("", max_length=200),
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        return fetch_methods(conn, q=q, offset=offset, limit=limit)

    @app.get("/api/v1/evolution/edges")
    def v1_evolution_edges(
        paper_id: str | None = None,
        edge_type: str | None = None,
        method: str | None = Query(None, max_length=200),
        year_from: int | None = Query(None, ge=1900, le=2100),
        year_to: int | None = Query(None, ge=1900, le=2100),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return fetch_edges(
            conn,
            paper_id=paper_id,
            edge_type=edge_type,
            method=method,
            year_from=year_from,
            year_to=year_to,
            offset=offset,
            limit=limit,
        )

    @app.get("/api/v1/papers/{paper_id}/neighborhood")
    def v1_neighborhood(
        paper_id: str,
        depth: int = Query(1, ge=0, le=4),
        limit: int = Query(100, ge=10, le=300),
    ) -> dict[str, Any]:
        return neighborhood(paper_id, depth=depth, limit=limit)

    @app.get("/api/v1/papers/search")
    def v1_search_papers(
        q: str = Query("", max_length=200),
        limit: int = Query(20, ge=1, le=50),
    ) -> list[dict[str, Any]]:
        return search_papers(q=q, limit=limit)

    @app.get("/api/v1/llm/tools")
    def llm_tools() -> dict[str, Any]:
        return llm_tool_manifest()

    @app.post("/api/v1/remote/health")
    def remote_health(req: RemoteConfigRequest) -> dict[str, Any]:
        return mark_remote(call_remote(req, lambda client: client.health()))

    @app.post("/api/v1/remote/stats")
    def remote_stats(req: RemoteConfigRequest) -> dict[str, Any]:
        return mark_remote(call_remote(req, lambda client: client.stats()))

    @app.post("/api/v1/remote/papers")
    def remote_list_papers(req: RemotePaperListRequest) -> list[dict[str, Any]]:
        return call_remote(
            req,
            lambda client: client.list_papers(
                status=req.status,
                tier=req.tier,
                paper_type=req.paper_type,
                offset=req.offset,
                limit=req.limit,
            ),
        )

    @app.post("/api/v1/remote/papers/search")
    def remote_search_papers(req: RemoteSearchRequest) -> list[dict[str, Any]]:
        return call_remote(req, lambda client: client.search_papers(req.query, limit=req.limit))

    @app.post("/api/v1/remote/papers/detail")
    def remote_paper_detail(req: RemotePaperDetailRequest) -> dict[str, Any]:
        return mark_remote(call_remote(req, lambda client: client.get_paper(req.paper_id)))

    @app.post("/api/v1/remote/search")
    def remote_search(req: RemoteSearchRequest) -> dict[str, Any]:
        return mark_remote(
            call_remote(
                req,
                lambda client: client.unified_search(
                    req.query,
                    search_type=req.search_type,
                    limit=req.limit,
                    include_subgraph=req.include_subgraph,
                ),
            )
        )

    @app.post("/api/v1/remote/query")
    def remote_query(req: RemoteQueryRequest) -> dict[str, Any]:
        return mark_remote(call_remote(req, lambda client: client.query_subgraph(req.query, max_nodes=req.max_nodes)))

    @app.post("/api/v1/remote/evidence/context")
    def remote_evidence_context(req: RemoteEvidenceRequest) -> dict[str, Any]:
        return mark_remote(
            call_remote(
                req,
                lambda client: client.evidence_context(
                    req.query,
                    max_papers=req.max_papers,
                    max_edges=req.max_edges,
                    mode=req.mode,
                    depth=req.depth,
                    year_from=req.year_from,
                    year_to=req.year_to,
                    edge_type=req.edge_type,
                    method=req.method,
                    include_prompt_context=req.include_prompt_context,
                ),
            )
        )

    @app.post("/api/v1/remote/papers/neighborhood")
    def remote_paper_neighborhood(req: RemoteNeighborhoodRequest) -> dict[str, Any]:
        return mark_remote(
            call_remote(
                req,
                lambda client: client.paper_neighborhood(req.paper_id, depth=req.depth, limit=req.limit),
            )
        )

    @app.post("/api/v1/remote/papers/branch")
    def remote_paper_branch(req: RemoteNeighborhoodRequest) -> dict[str, Any]:
        return mark_remote(
            call_remote(
                req,
                lambda client: client.paper_branch(req.paper_id, depth=req.depth, limit=req.limit),
            )
        )

    @app.post("/api/v1/remote/papers/ancestry")
    def remote_paper_ancestry(req: RemoteNeighborhoodRequest) -> dict[str, Any]:
        return mark_remote(
            call_remote(
                req,
                lambda client: client.paper_ancestry(req.paper_id, depth=req.depth, limit=req.limit),
            )
        )

    @app.post("/api/v1/remote/path")
    def remote_path(req: RemotePathRequest) -> list[dict[str, Any]]:
        return call_remote(
            req,
            lambda client: client.find_path(
                req.from_id,
                req.to_id,
                direction=req.direction,
                max_depth=req.max_depth,
            ),
        )

    @app.post("/api/v1/remote/visualization/evolution-chain")
    def remote_evolution_chain(req: RemoteChainRequest) -> dict[str, Any]:
        return mark_remote(
            call_remote(
                req,
                lambda client: client.evolution_chain(
                    req.domain,
                    max_chains=req.max_chains,
                    max_depth=req.max_depth,
                    beam_width=req.beam_width,
                    strategy=req.strategy,
                ),
            )
        )

    @app.post("/api/v1/remote/assist/context")
    def remote_assist_context(req: RemoteAssistRequest) -> dict[str, Any]:
        return mark_remote(
            call_remote(
                req,
                lambda client: client.assist_context(
                    req.query,
                    budget=req.budget,
                    use_mcts=req.use_mcts,
                    token_budget=req.token_budget,
                ),
            )
        )

    @app.post("/api/v1/remote/ideas")
    def remote_ideas(req: RemoteIdeaRequest) -> dict[str, Any]:
        return mark_remote(
            call_remote(
                req,
                lambda client: client.generate_ideas(
                    req.query,
                    use_llm=req.use_llm,
                    evidence_budget=req.evidence_budget,
                ),
            )
        )

    @app.post("/api/v1/remote/eval")
    def remote_eval(req: RemoteEvalRequest) -> dict[str, Any]:
        return mark_remote(call_remote(req, lambda client: client.evaluate_idea(req.idea, use_llm=req.use_llm)))

    return app
