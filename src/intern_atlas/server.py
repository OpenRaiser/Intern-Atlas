"""FastAPI app for querying a local Intern Atlas SQLite graph."""

from pathlib import Path
from typing import Any

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
from .ui import INDEX_HTML


def create_app(db_path: str | Path):
    from fastapi import FastAPI, HTTPException, Query
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

    return app
