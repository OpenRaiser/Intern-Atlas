"""FastAPI app for querying a local Intern Atlas SQLite graph."""

from collections import deque
from pathlib import Path
from typing import Any

from .db import connect, edge_summary, graph_stats, paper_summary
from .util import tokens


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


def fetch_edges(
    conn,
    *,
    paper_id: str | None = None,
    edge_type: str | None = None,
    method: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = ["fine_edge_type IS NOT NULL", "fine_edge_type != 'background'"]
    params: list[Any] = []
    if paper_id:
        clauses.append("(source_id = ? OR target_id = ?)")
        params.extend([paper_id, paper_id])
    if edge_type:
        clauses.append("fine_edge_type = ?")
        params.append(edge_type)
    if method and method.strip():
        clauses.append(
            """
            (
              LOWER(source_method) LIKE ? OR LOWER(target_method) LIKE ?
              OR source_id IN (
                SELECT pm.paper_id
                FROM paper_methods pm
                JOIN methods m ON m.method_id = pm.method_id
                WHERE LOWER(m.canonical_name) LIKE ?
              )
              OR target_id IN (
                SELECT pm.paper_id
                FROM paper_methods pm
                JOIN methods m ON m.method_id = pm.method_id
                WHERE LOWER(m.canonical_name) LIKE ?
              )
            )
            """
        )
        method_like = f"%{method.strip().lower()}%"
        params.extend([method_like, method_like, method_like, method_like])
    if year_from is not None:
        clauses.append(
            """
            source_id IN (SELECT internal_id FROM papers WHERE year >= ?)
            AND target_id IN (SELECT internal_id FROM papers WHERE year >= ?)
            """
        )
        params.extend([year_from, year_from])
    if year_to is not None:
        clauses.append(
            """
            source_id IN (SELECT internal_id FROM papers WHERE year <= ?)
            AND target_id IN (SELECT internal_id FROM papers WHERE year <= ?)
            """
        )
        params.extend([year_to, year_to])
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT * FROM citations
        WHERE {where}
        ORDER BY COALESCE(fine_confidence, 0) DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    return [edge_summary(row) for row in rows]


def fetch_methods(conn, *, q: str = "", offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if q.strip():
        where = "WHERE canonical_name LIKE ? OR description LIKE ?"
        params.extend([f"%{q}%", f"%{q}%"])
    rows = conn.execute(
        f"""
        SELECT method_id, canonical_name, description, origin_paper_id
        FROM methods
        {where}
        ORDER BY canonical_name
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    return [dict(row) for row in rows]


def collect_relevant_paper_ids(
    conn,
    query: str,
    *,
    max_nodes: int,
    depth: int = 1,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[str]:
    seed_ids = search_relevant_paper_ids(conn, query, limit=max_nodes, year_from=year_from, year_to=year_to)
    return expand_from_seed_papers(conn, seed_ids, max_nodes=max_nodes, depth=depth)


def search_relevant_paper_ids(
    conn,
    query: str,
    *,
    limit: int,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[str]:
    rows = conn.execute("SELECT * FROM papers ORDER BY year DESC, title").fetchall()
    if not rows:
        return []
    rows = [row for row in rows if paper_in_year_range(row, year_from=year_from, year_to=year_to)]
    paper_ids = [row["internal_id"] for row in rows]
    method_names = method_names_by_paper(conn, paper_ids)
    phrase = " ".join(query.lower().split())
    query_terms = sorted(tokens(query))

    scored: list[tuple[float, int, str, str]] = []
    for row in rows:
        paper_id = row["internal_id"]
        title = (row["title"] or "").lower()
        abstract = (row["abstract"] or "").lower()
        methods = " ".join(method_names.get(paper_id, [])).lower()
        score = 0.0
        if phrase:
            if phrase in title:
                score += 12
            if phrase in methods:
                score += 10
            if phrase in abstract:
                score += 6
        for term in query_terms:
            if term in title:
                score += 4
            if term in methods:
                score += 3
            if term in abstract:
                score += 1
        if score > 0:
            scored.append((score, row["year"] or 0, row["title"] or "", paper_id))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [paper_id for _, _, _, paper_id in scored[:limit]]


def paper_in_year_range(row, *, year_from: int | None, year_to: int | None) -> bool:
    year = row["year"]
    if year is None:
        return year_from is None and year_to is None
    if year_from is not None and year < year_from:
        return False
    if year_to is not None and year > year_to:
        return False
    return True


def expand_from_seed_papers(
    conn,
    seed_ids: list[str],
    *,
    max_nodes: int,
    depth: int,
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(paper_id: str) -> bool:
        if paper_id in seen or len(ordered) >= max_nodes:
            return False
        seen.add(paper_id)
        ordered.append(paper_id)
        return True

    for seed_id in seed_ids:
        if len(ordered) >= max_nodes:
            break
        add(seed_id)
        frontier = deque([(seed_id, 0)])
        while frontier and len(ordered) < max_nodes:
            current, current_depth = frontier.popleft()
            if current_depth >= depth:
                continue
            rows = conn.execute(
                """
                SELECT c.source_id AS neighbor, COALESCE(c.fine_confidence, 0) AS confidence
                FROM citations c
                JOIN papers p ON p.internal_id = c.source_id
                WHERE c.target_id = ?
                  AND c.fine_edge_type IS NOT NULL AND c.fine_edge_type != 'background'
                  AND (? IS NULL OR p.year >= ?)
                  AND (? IS NULL OR p.year <= ?)
                UNION ALL
                SELECT c.target_id AS neighbor, COALESCE(c.fine_confidence, 0) AS confidence
                FROM citations c
                JOIN papers p ON p.internal_id = c.target_id
                WHERE c.source_id = ?
                  AND c.fine_edge_type IS NOT NULL AND c.fine_edge_type != 'background'
                  AND (? IS NULL OR p.year >= ?)
                  AND (? IS NULL OR p.year <= ?)
                ORDER BY confidence DESC
                """,
                (
                    current,
                    year_from,
                    year_from,
                    year_to,
                    year_to,
                    current,
                    year_from,
                    year_from,
                    year_to,
                    year_to,
                ),
            ).fetchall()
            for row in rows:
                neighbor = row["neighbor"]
                if add(neighbor):
                    frontier.append((neighbor, current_depth + 1))
                if len(ordered) >= max_nodes:
                    break
    return ordered


def build_evidence_pack(
    conn,
    query: str,
    *,
    max_papers: int,
    max_edges: int,
    mode: str = "balanced",
    depth: int | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    edge_type: str | None = None,
    method: str | None = None,
    include_prompt_context: bool,
) -> dict[str, Any]:
    params = normalize_evidence_params(
        mode=mode,
        max_papers=max_papers,
        max_edges=max_edges,
        depth=depth,
        year_from=year_from,
        year_to=year_to,
        edge_type=edge_type,
        method=method,
    )
    seed_ids = search_relevant_paper_ids(
        conn,
        query,
        limit=params["seed_limit"],
        year_from=params["year_from"],
        year_to=params["year_to"],
    )
    paper_ids = expand_from_seed_papers(
        conn,
        seed_ids,
        max_nodes=params["max_papers"],
        depth=params["depth"],
        year_from=params["year_from"],
        year_to=params["year_to"],
    )
    sg = subgraph(conn, set(paper_ids))
    methods_by_paper = method_mentions_by_paper(conn, paper_ids)
    seed_set = set(seed_ids)

    papers: list[dict[str, Any]] = []
    for idx, paper_id in enumerate(paper_ids):
        paper = sg["papers"].get(paper_id)
        if not paper:
            continue
        item = dict(paper)
        item["relevance_rank"] = idx + 1
        item["evidence_role"] = "seed" if paper_id in seed_set else "neighbor"
        item["methods"] = methods_by_paper.get(paper_id, [])
        papers.append(item)

    papers_by_id = {paper["paper_id"]: paper for paper in papers}
    method_edges = filter_evidence_edges(
        sg["edges"],
        papers_by_id,
        edge_type=params["edge_type"],
        method=params["method"],
    )
    method_edges = enrich_edges(method_edges[: params["max_edges"]], papers_by_id)
    bottlenecks = extract_bottlenecks(method_edges)
    mechanisms = extract_mechanisms(method_edges)
    timeline = build_timeline(papers)
    suggested_prompt_context = (
        evidence_prompt_context(query, timeline, method_edges, bottlenecks, mechanisms)
        if include_prompt_context
        else ""
    )

    return {
        "query": query,
        "papers": papers,
        "method_edges": method_edges,
        "bottlenecks": bottlenecks,
        "mechanisms": mechanisms,
        "timeline": timeline,
        "suggested_prompt_context": suggested_prompt_context,
        "counts": {
            "papers": len(papers),
            "method_edges": len(method_edges),
            "bottlenecks": len(bottlenecks),
            "mechanisms": len(mechanisms),
        },
        "parameters": {
            "mode": params["mode"],
            "depth": params["depth"],
            "max_papers": params["max_papers"],
            "max_edges": params["max_edges"],
            "year_from": params["year_from"],
            "year_to": params["year_to"],
            "edge_type": params["edge_type"],
            "method": params["method"],
        },
    }


def normalize_evidence_params(
    *,
    mode: str,
    max_papers: int,
    max_edges: int,
    depth: int | None,
    year_from: int | None,
    year_to: int | None,
    edge_type: str | None,
    method: str | None,
) -> dict[str, Any]:
    mode = mode if mode in {"light", "balanced", "deep"} else "balanced"
    presets = {
        "light": {"max_papers": 12, "max_edges": 18, "depth": 0, "seed_limit": 12},
        "balanced": {"max_papers": 24, "max_edges": 50, "depth": 1, "seed_limit": 24},
        "deep": {"max_papers": 80, "max_edges": 160, "depth": 2, "seed_limit": 40},
    }
    preset = presets[mode]
    effective_max_papers = min(max(1, max_papers), preset["max_papers"])
    effective_max_edges = min(max(0, max_edges), preset["max_edges"])
    effective_depth = preset["depth"] if depth is None else min(max(depth, 0), preset["depth"])
    if year_from is not None and year_to is not None and year_from > year_to:
        year_from, year_to = year_to, year_from
    cleaned_edge_type = (edge_type or "").strip() or None
    cleaned_method = (method or "").strip() or None
    return {
        "mode": mode,
        "max_papers": effective_max_papers,
        "max_edges": effective_max_edges,
        "depth": effective_depth,
        "seed_limit": min(preset["seed_limit"], effective_max_papers),
        "year_from": year_from,
        "year_to": year_to,
        "edge_type": cleaned_edge_type,
        "method": cleaned_method,
    }


def filter_evidence_edges(
    edges: list[dict[str, Any]],
    papers_by_id: dict[str, dict[str, Any]],
    *,
    edge_type: str | None,
    method: str | None,
) -> list[dict[str, Any]]:
    method_query = (method or "").strip().lower()
    filtered: list[dict[str, Any]] = []
    for edge in edges:
        if edge_type and edge.get("edge_type") != edge_type:
            continue
        if method_query and not edge_mentions_method(edge, papers_by_id, method_query):
            continue
        filtered.append(edge)
    return filtered


def edge_mentions_method(edge: dict[str, Any], papers_by_id: dict[str, dict[str, Any]], method_query: str) -> bool:
    values = [
        edge.get("source_method", ""),
        edge.get("target_method", ""),
    ]
    for paper_id in (edge.get("source_paper_id"), edge.get("target_paper_id")):
        paper = papers_by_id.get(paper_id or "", {})
        for item in paper.get("methods", []):
            values.append(item.get("canonical_name", ""))
    return any(method_query in str(value).lower() for value in values)


def method_names_by_paper(conn, paper_ids: list[str]) -> dict[str, list[str]]:
    methods = method_mentions_by_paper(conn, paper_ids)
    return {
        paper_id: [item["canonical_name"] for item in items]
        for paper_id, items in methods.items()
    }


def method_mentions_by_paper(conn, paper_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not paper_ids:
        return {}
    placeholders = ",".join("?" for _ in paper_ids)
    rows = conn.execute(
        f"""
        SELECT pm.paper_id, m.method_id, m.canonical_name, m.description,
               pm.relationship, pm.confidence
        FROM paper_methods pm
        JOIN methods m ON m.method_id = pm.method_id
        WHERE pm.paper_id IN ({placeholders})
        ORDER BY pm.confidence DESC, m.canonical_name
        """,
        paper_ids,
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {paper_id: [] for paper_id in paper_ids}
    for row in rows:
        out.setdefault(row["paper_id"], []).append(
            {
                "method_id": row["method_id"],
                "canonical_name": row["canonical_name"],
                "description": row["description"] or "",
                "relationship": row["relationship"],
                "confidence": row["confidence"],
            }
        )
    return out


def enrich_edges(edges: list[dict[str, Any]], papers_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for edge in edges:
        item = dict(edge)
        newer = papers_by_id.get(edge["source_paper_id"], {})
        older = papers_by_id.get(edge["target_paper_id"], {})
        item["newer_paper"] = {
            "paper_id": edge["source_paper_id"],
            "title": newer.get("title", ""),
            "year": newer.get("year"),
        }
        item["older_paper"] = {
            "paper_id": edge["target_paper_id"],
            "title": older.get("title", ""),
            "year": older.get("year"),
        }
        out.append(item)
    return out


def extract_bottlenecks(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        text = edge.get("bottleneck", "").strip()
        if not text:
            continue
        key = (edge["source_paper_id"], edge["target_paper_id"], text.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "older_paper_id": edge["target_paper_id"],
                "newer_paper_id": edge["source_paper_id"],
                "edge_type": edge["edge_type"],
                "dimension": edge.get("dimension", ""),
                "bottleneck": text,
                "confidence": edge.get("confidence", 0.0),
            }
        )
    return out


def extract_mechanisms(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        text = edge.get("mechanism", "").strip()
        if not text:
            continue
        key = (edge["source_paper_id"], edge["target_paper_id"], text.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "older_paper_id": edge["target_paper_id"],
                "newer_paper_id": edge["source_paper_id"],
                "edge_type": edge["edge_type"],
                "source_method": edge.get("source_method", ""),
                "target_method": edge.get("target_method", ""),
                "mechanism": text,
                "confidence": edge.get("confidence", 0.0),
            }
        )
    return out


def build_timeline(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for paper in papers:
        rows.append(
            {
                "year": paper.get("year"),
                "paper_id": paper["paper_id"],
                "title": paper["title"],
                "evidence_role": paper.get("evidence_role", "neighbor"),
                "methods": [method["canonical_name"] for method in paper.get("methods", [])[:6]],
            }
        )
    rows.sort(key=lambda item: (item["year"] is None, item["year"] or 9999, item["title"]))
    return rows


def evidence_prompt_context(
    query: str,
    timeline: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    bottlenecks: list[dict[str, Any]],
    mechanisms: list[dict[str, Any]],
) -> str:
    lines = [
        "Use this Intern Atlas evidence pack to support research idea generation.",
        "Ground claims in the listed paper IDs and avoid inventing papers or results.",
        f"Research query: {query}",
        "",
        "Timeline:",
    ]
    for item in timeline[:20]:
        year = item.get("year") or "unknown"
        methods = ", ".join(item.get("methods") or []) or "methods not extracted"
        lines.append(f"- [{year}] {item['title']} ({item['paper_id']}): {methods}")

    lines.extend(["", "Method-evolution edges:"])
    for edge in edges[:30]:
        newer = edge.get("newer_paper", {})
        older = edge.get("older_paper", {})
        newer_title = newer.get("title") or edge["source_paper_id"]
        older_title = older.get("title") or edge["target_paper_id"]
        lines.append(
            f"- {older_title} -> {newer_title}: {edge['edge_type']}; "
            f"bottleneck={edge.get('bottleneck', '')}; mechanism={edge.get('mechanism', '')}"
        )

    lines.extend(["", "Bottlenecks to inspect:"])
    for item in bottlenecks[:12]:
        lines.append(f"- {item['dimension'] or 'unknown'}: {item['bottleneck']}")

    lines.extend(["", "Mechanisms to reuse or recombine:"])
    for item in mechanisms[:12]:
        lines.append(f"- {item['source_method'] or 'method'}: {item['mechanism']}")
    return "\n".join(lines)


def llm_tool_manifest() -> dict[str, Any]:
    return {
        "service": "Intern Atlas Local API",
        "purpose": "Provide evidence packs and graph lookups for LLM research agents.",
        "base_path": "/api/v1",
        "tools": [
            {
                "name": "intern_atlas_evidence_context",
                "method": "POST",
                "path": "/api/v1/evidence/context",
                "description": "Return papers, method-evolution edges, bottlenecks, mechanisms, and prompt context for a research query.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Research topic or idea seed."},
                        "max_papers": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                        "max_edges": {"type": "integer", "minimum": 0, "maximum": 300, "default": 40},
                        "mode": {"type": "string", "enum": ["light", "balanced", "deep"], "default": "balanced"},
                        "depth": {"type": "integer", "minimum": 0, "maximum": 4},
                        "year_from": {"type": "integer", "minimum": 1900, "maximum": 2100},
                        "year_to": {"type": "integer", "minimum": 1900, "maximum": 2100},
                        "edge_type": {"type": "string"},
                        "method": {"type": "string"},
                        "include_prompt_context": {"type": "boolean", "default": True},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "intern_atlas_search_methods",
                "method": "GET",
                "path": "/api/v1/methods/search",
                "description": "Search extracted method entities by name or description.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                    },
                    "required": ["q"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "intern_atlas_evolution_edges",
                "method": "GET",
                "path": "/api/v1/evolution/edges",
                "description": "List method-evolution edges, optionally filtered by method, edge type, or paper id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "paper_id": {"type": "string"},
                        "edge_type": {"type": "string"},
                        "method": {"type": "string"},
                        "year_from": {"type": "integer", "minimum": 1900, "maximum": 2100},
                        "year_to": {"type": "integer", "minimum": 1900, "maximum": 2100},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "intern_atlas_paper_neighborhood",
                "method": "GET",
                "path": "/api/v1/papers/{paper_id}/neighborhood",
                "description": "Return a bounded local subgraph around one paper.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "paper_id": {"type": "string"},
                        "depth": {"type": "integer", "minimum": 0, "maximum": 4, "default": 1},
                        "limit": {"type": "integer", "minimum": 10, "maximum": 300, "default": 100},
                    },
                    "required": ["paper_id"],
                    "additionalProperties": False,
                },
            },
        ],
    }


def bfs_papers(conn, start_id: str, *, depth: int, max_nodes: int) -> set[str]:
    visited = {start_id}
    frontier = deque([(start_id, 0)])
    while frontier and len(visited) < max_nodes:
        current, d = frontier.popleft()
        if d >= depth:
            continue
        rows = conn.execute(
            """
            SELECT source_id AS neighbor FROM citations WHERE target_id = ?
            UNION
            SELECT target_id AS neighbor FROM citations WHERE source_id = ?
            """,
            (current, current),
        ).fetchall()
        for row in rows:
            nid = row["neighbor"]
            if nid not in visited:
                visited.add(nid)
                frontier.append((nid, d + 1))
                if len(visited) >= max_nodes:
                    break
    return visited


def subgraph(conn, paper_ids: set[str], *, center_id: str | None = None) -> dict[str, Any]:
    if not paper_ids:
        return {"papers": {}, "edges": [], "center_id": center_id}
    placeholders = ",".join("?" for _ in paper_ids)
    papers = {
        row["internal_id"]: paper_summary(row)
        for row in conn.execute(f"SELECT * FROM papers WHERE internal_id IN ({placeholders})", list(paper_ids))
    }
    edge_rows = conn.execute(
        f"""
        SELECT * FROM citations
        WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
          AND fine_edge_type IS NOT NULL AND fine_edge_type != 'background'
        ORDER BY COALESCE(fine_confidence, 0) DESC
        LIMIT 800
        """,
        list(paper_ids) + list(paper_ids),
    ).fetchall()
    return {
        "papers": papers,
        "edges": [edge_summary(row) for row in edge_rows],
        "center_id": center_id,
    }


def prompt_context(query: str, papers: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    lines = [f"Research query: {query}", "", "Relevant papers:"]
    for idx, paper in enumerate(papers, 1):
        lines.append(f"{idx}. [{paper.get('year')}] {paper.get('title')} ({paper.get('paper_id')})")
    lines.append("")
    lines.append("Method-evolution edges:")
    for idx, edge in enumerate(edges, 1):
        lines.append(
            f"{idx}. {edge['source_paper_id']} {edge['edge_type']} {edge['target_paper_id']}; "
            f"bottleneck={edge.get('bottleneck', '')}; mechanism={edge.get('mechanism', '')}"
        )
    return "\n".join(lines)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Intern Atlas Evidence Workspace</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f3ef;
      --sidebar: #eef2f0;
      --panel: #ffffff;
      --panel-soft: #faf8f4;
      --ink: #1f2933;
      --muted: #637083;
      --line: #d9ddd7;
      --blue: #285f83;
      --green: #0f766e;
      --amber: #a15c07;
      --red: #b42318;
      --violet: #5b5f97;
      --shadow: 0 14px 36px rgba(31, 41, 51, 0.09);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--bg);
    }
    button, input, select { font: inherit; }
    button {
      min-height: 38px;
      border: 1px solid var(--blue);
      border-radius: 8px;
      background: var(--blue);
      color: #fff;
      padding: 9px 12px;
      font-weight: 760;
      cursor: pointer;
    }
    button.secondary {
      background: #fff;
      color: var(--blue);
      border-color: var(--line);
    }
    button.subtle {
      background: transparent;
      color: var(--muted);
      border-color: var(--line);
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.48;
    }
    input, select {
      width: 100%;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      padding: 9px 10px;
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--blue);
      box-shadow: 0 0 0 3px rgba(40, 95, 131, 0.15);
    }
    label {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      margin-bottom: 6px;
      text-transform: uppercase;
    }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 366px minmax(0, 1fr);
    }
    .sidebar {
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      padding: 22px;
      border-right: 1px solid var(--line);
      background: var(--sidebar);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 18px;
    }
    .mark {
      width: 40px;
      height: 40px;
      display: grid;
      place-items: center;
      border-radius: 8px;
      background: var(--ink);
      color: #fff;
      font-weight: 900;
    }
    .brand h1 {
      margin: 0;
      font-size: 18px;
      line-height: 1.1;
    }
    .brand p {
      margin: 3px 0 0;
      color: var(--muted);
      font-size: 12px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 16px;
    }
    .stat {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.74);
      padding: 10px;
    }
    .stat strong {
      display: block;
      font-size: 20px;
      line-height: 1;
    }
    .stat span {
      display: block;
      margin-top: 6px;
      color: var(--muted);
      font-size: 11px;
    }
    .control-group {
      display: grid;
      gap: 11px;
      margin-top: 16px;
    }
    .split {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .triple {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .row > * { min-width: 0; }
    .segmented {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
    }
    .segmented button {
      background: #fff;
      color: var(--muted);
      border-color: var(--line);
      padding: 8px 6px;
    }
    .segmented button.is-active {
      color: #fff;
      border-color: var(--green);
      background: var(--green);
    }
    .checkline {
      display: flex;
      gap: 8px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }
    .checkline input {
      width: 16px;
      height: 16px;
    }
    .side-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 16px;
    }
    .toast {
      min-height: 19px;
      margin-top: 10px;
      color: var(--red);
      font-size: 12px;
      line-height: 1.45;
    }
    .main {
      min-width: 0;
      padding: 24px;
    }
    .hero {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 16px;
    }
    .hero h2 {
      margin: 0;
      font-size: 26px;
      line-height: 1.14;
    }
    .hero p {
      max-width: 850px;
      margin: 7px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }
    .status-pill {
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 9px 11px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px;
      box-shadow: var(--shadow);
    }
    .metric strong {
      display: block;
      font-size: 21px;
      line-height: 1;
    }
    .metric span {
      display: block;
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
    }
    .workspace {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(360px, 0.8fr);
      gap: 16px;
      align-items: start;
    }
    .panel {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel-head {
      min-height: 54px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 13px 15px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    .panel-head h3 {
      margin: 0;
      font-size: 15px;
    }
    .panel-head span {
      color: var(--muted);
      font-size: 12px;
    }
    .graph-wrap {
      position: relative;
      height: 430px;
      background: var(--panel-soft);
      border-bottom: 1px solid var(--line);
    }
    svg {
      width: 100%;
      height: 100%;
      display: block;
    }
    .graph-empty {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 13px;
      text-align: center;
      padding: 20px;
    }
    .node circle {
      fill: var(--blue);
      stroke: #fff;
      stroke-width: 2;
    }
    .node.seed circle { fill: var(--green); }
    .node.active circle { fill: var(--amber); }
    .node text {
      fill: var(--ink);
      font-size: 11px;
      paint-order: stroke;
      stroke: #fff;
      stroke-width: 4px;
      stroke-linejoin: round;
    }
    .edge-line {
      stroke: #8c8174;
      stroke-width: 1.5;
      opacity: 0.72;
    }
    .list {
      max-height: 475px;
      overflow: auto;
    }
    .dense-list {
      max-height: 300px;
      overflow: auto;
    }
    .paper-card, .edge-card, .fact-row, .timeline-row {
      border-bottom: 1px solid var(--line);
      padding: 13px 15px;
    }
    .paper-card {
      cursor: pointer;
    }
    .paper-card:hover, .edge-card:hover {
      background: #f4faf8;
    }
    .paper-card.is-active {
      background: #fff7ea;
      border-left: 4px solid var(--amber);
      padding-left: 11px;
    }
    .title {
      font-weight: 800;
      line-height: 1.33;
      overflow-wrap: anywhere;
    }
    .meta {
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .abstract {
      margin-top: 8px;
      color: #3f4b57;
      font-size: 13px;
      line-height: 1.45;
    }
    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 9px;
    }
    .chip {
      border: 1px solid #d5e3e0;
      border-radius: 999px;
      background: #f0f7f5;
      color: var(--green);
      padding: 3px 7px;
      font-size: 11px;
      font-weight: 760;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .edge-type {
      display: inline-flex;
      align-items: center;
      margin-right: 7px;
      border-radius: 999px;
      background: #f7ead8;
      color: var(--amber);
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 850;
    }
    .edge-detail {
      margin-top: 8px;
      color: #3f4b57;
      font-size: 12px;
      line-height: 1.45;
    }
    .right-stack {
      display: grid;
      gap: 16px;
    }
    .download-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      padding: 15px;
    }
    .selection {
      padding: 15px;
      border-top: 1px solid var(--line);
      background: #fbfbf8;
    }
    .selection h4 {
      margin: 0 0 6px;
      font-size: 13px;
    }
    .selection p {
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .empty {
      padding: 30px 18px;
      color: var(--muted);
      text-align: center;
      font-size: 13px;
      line-height: 1.45;
    }
    @media (max-width: 1180px) {
      .shell { grid-template-columns: 1fr; }
      .sidebar { position: relative; height: auto; }
      .workspace { grid-template-columns: 1fr; }
      .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      .main, .sidebar { padding: 16px; }
      .hero { flex-direction: column; }
      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .split, .triple, .download-grid, .side-actions { grid-template-columns: 1fr; }
      .graph-wrap { height: 360px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="mark">IA</div>
        <div>
          <h1>Intern Atlas</h1>
          <p>Evidence layer for research agents</p>
        </div>
      </div>

      <div class="stats">
        <div class="stat"><strong id="papersStat">-</strong><span>Papers</span></div>
        <div class="stat"><strong id="methodsStat">-</strong><span>Methods</span></div>
        <div class="stat"><strong id="edgesStat">-</strong><span>Edges</span></div>
      </div>

      <div class="control-group">
        <div>
          <label for="query">Research query</label>
          <input id="query" value="efficient attention" placeholder="efficient attention, LoRA tuning, long context..." />
        </div>

        <div>
          <label>Retrieval mode</label>
          <div class="segmented" role="group" aria-label="Retrieval mode">
            <button type="button" data-mode="light">Light</button>
            <button type="button" data-mode="balanced" class="is-active">Balanced</button>
            <button type="button" data-mode="deep">Deep</button>
          </div>
        </div>

        <div class="split">
          <div>
            <label for="yearFrom">Year from</label>
            <input id="yearFrom" type="number" min="1900" max="2100" placeholder="any" />
          </div>
          <div>
            <label for="yearTo">Year to</label>
            <input id="yearTo" type="number" min="1900" max="2100" placeholder="any" />
          </div>
        </div>

        <div class="split">
          <div>
            <label for="edgeType">Edge type</label>
            <select id="edgeType">
              <option value="">Any edge</option>
              <option value="extends">extends</option>
              <option value="improves">improves</option>
              <option value="replaces">replaces</option>
              <option value="adapts">adapts</option>
              <option value="combines">combines</option>
              <option value="uses_component">uses_component</option>
              <option value="compares">compares</option>
            </select>
          </div>
          <div>
            <label for="methodFilter">Method filter</label>
            <input id="methodFilter" placeholder="attention, LoRA..." />
          </div>
        </div>

        <div class="triple">
          <div>
            <label for="maxPapers">Papers</label>
            <input id="maxPapers" type="number" min="1" max="100" value="24" />
          </div>
          <div>
            <label for="maxEdges">Edges</label>
            <input id="maxEdges" type="number" min="0" max="300" value="50" />
          </div>
          <div>
            <label for="depth">Depth</label>
            <input id="depth" type="number" min="0" max="4" value="1" />
          </div>
        </div>

        <label class="checkline">
          <input id="includeContext" type="checkbox" checked />
          Include prompt-ready context
        </label>

        <div class="row">
          <button id="runBtn" type="button">Run evidence search</button>
          <button id="resetBtn" type="button" class="secondary">Reset</button>
        </div>
        <div class="side-actions">
          <button id="copyBtn" type="button" class="secondary" disabled>Copy context</button>
          <button id="docsBtn" type="button" class="subtle">API docs</button>
        </div>
        <div id="toast" class="toast"></div>
      </div>
    </aside>

    <main class="main">
      <div class="hero">
        <div>
          <h2>Evidence Workspace</h2>
          <p id="subtitle">Build a query-specific evidence pack, inspect method evolution, and export data for downstream LLM or agent workflows.</p>
        </div>
        <div id="statusPill" class="status-pill">Ready</div>
      </div>

      <div class="metric-grid">
        <div class="metric"><strong id="viewPapers">0</strong><span>Evidence papers</span></div>
        <div class="metric"><strong id="viewEdges">0</strong><span>Method edges</span></div>
        <div class="metric"><strong id="viewBottlenecks">0</strong><span>Bottlenecks</span></div>
        <div class="metric"><strong id="viewMechanisms">0</strong><span>Mechanisms</span></div>
        <div class="metric"><strong id="viewMode">balanced</strong><span>Mode applied</span></div>
      </div>

      <div class="workspace">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Method Evolution Graph</h3>
              <span id="graphMeta">0 papers, 0 edges</span>
            </div>
            <button id="openNeighborhoodBtn" type="button" class="secondary" disabled>Open neighborhood</button>
          </div>
          <div class="graph-wrap">
            <svg id="graphSvg" role="img" aria-label="methodology evolution graph"></svg>
            <div id="graphEmpty" class="graph-empty">Run an evidence search to draw a graph.</div>
          </div>
          <div class="selection">
            <h4 id="selectionTitle">No paper selected</h4>
            <p id="selectionMeta">Select a node or paper row to inspect a local neighborhood.</p>
          </div>
          <div class="panel-head">
            <h3>Evidence Papers</h3>
            <span id="paperMeta">0 papers</span>
          </div>
          <div id="paperList" class="list"><div class="empty">No papers loaded yet.</div></div>
        </section>

        <div class="right-stack">
          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Downloads</h3>
                <span>Export the current evidence view</span>
              </div>
            </div>
            <div class="download-grid">
              <button id="downloadJsonBtn" type="button" class="secondary" disabled>Evidence JSON</button>
              <button id="downloadPapersBtn" type="button" class="secondary" disabled>Papers CSV</button>
              <button id="downloadEdgesBtn" type="button" class="secondary" disabled>Edges CSV</button>
              <button id="downloadContextBtn" type="button" class="secondary" disabled>Context MD</button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Timeline</h3>
                <span id="timelineMeta">0 entries</span>
              </div>
            </div>
            <div id="timelineList" class="dense-list"><div class="empty">Timeline appears after search.</div></div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Bottlenecks and Mechanisms</h3>
                <span id="factMeta">0 items</span>
              </div>
            </div>
            <div id="factList" class="dense-list"><div class="empty">No bottlenecks or mechanisms loaded.</div></div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Method Edges</h3>
                <span id="edgeMeta">0 edges</span>
              </div>
            </div>
            <div id="edgeList" class="list"><div class="empty">No edges loaded yet.</div></div>
          </section>
        </div>
      </div>
    </main>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const modePresets = {
      light: { maxPapers: 12, maxEdges: 18, depth: 0 },
      balanced: { maxPapers: 24, maxEdges: 50, depth: 1 },
      deep: { maxPapers: 80, maxEdges: 160, depth: 2 },
    };
    const state = {
      evidence: null,
      papers: {},
      edges: [],
      active: null,
      mode: 'balanced',
      busy: false,
    };

    async function api(path, opts = {}) {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`API ${res.status}: ${text.slice(0, 220)}`);
      }
      return res.json();
    }

    function setMode(mode, applyPreset = true) {
      state.mode = modePresets[mode] ? mode : 'balanced';
      document.querySelectorAll('[data-mode]').forEach((button) => {
        button.classList.toggle('is-active', button.dataset.mode === state.mode);
      });
      if (applyPreset) {
        const preset = modePresets[state.mode];
        $('maxPapers').value = preset.maxPapers;
        $('maxEdges').value = preset.maxEdges;
        $('depth').value = preset.depth;
      }
    }

    function parseNumber(id) {
      const raw = $(id).value.trim();
      return raw === '' ? null : Number(raw);
    }

    function buildPayload() {
      const query = $('query').value.trim();
      if (!query) throw new Error('Enter a research query first.');
      const payload = {
        query,
        mode: state.mode,
        max_papers: parseNumber('maxPapers') || modePresets[state.mode].maxPapers,
        max_edges: parseNumber('maxEdges') ?? modePresets[state.mode].maxEdges,
        depth: parseNumber('depth'),
        include_prompt_context: $('includeContext').checked,
      };
      const yearFrom = parseNumber('yearFrom');
      const yearTo = parseNumber('yearTo');
      const edgeType = $('edgeType').value;
      const method = $('methodFilter').value.trim();
      if (yearFrom !== null) payload.year_from = yearFrom;
      if (yearTo !== null) payload.year_to = yearTo;
      if (edgeType) payload.edge_type = edgeType;
      if (method) payload.method = method;
      return payload;
    }

    async function runEvidenceSearch() {
      showMessage('');
      setBusy(true);
      try {
        const payload = buildPayload();
        setStatus(`Searching ${payload.mode} evidence...`);
        const data = await api('/api/v1/evidence/context', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        applyEvidence(data);
        const p = data.parameters || {};
        setStatus(`Loaded ${data.counts?.papers || 0} papers, depth ${p.depth ?? payload.depth ?? 0}`);
      } catch (error) {
        showMessage(error);
        setStatus('Error');
      } finally {
        setBusy(false);
      }
    }

    function applyEvidence(data) {
      state.evidence = data;
      state.papers = Object.fromEntries((data.papers || []).map((paper) => [paper.paper_id, paper]));
      state.edges = data.method_edges || [];
      state.active = null;
      renderAll();
    }

    async function openSelectedNeighborhood() {
      if (!state.active) return;
      showMessage('');
      setBusy(true);
      try {
        const depth = Math.max(1, parseNumber('depth') || 1);
        const limit = Math.max(10, parseNumber('maxPapers') || 80);
        const sg = await api(`/api/v1/papers/${encodeURIComponent(state.active)}/neighborhood?depth=${depth}&limit=${limit}`);
        state.papers = sg.papers || {};
        state.edges = sg.edges || [];
        renderAll();
        setStatus(`Neighborhood loaded for ${state.active}`);
      } catch (error) {
        showMessage(error);
        setStatus('Error');
      } finally {
        setBusy(false);
      }
    }

    async function copyContext() {
      const context = state.evidence?.suggested_prompt_context || '';
      if (!context) return;
      try {
        await navigator.clipboard.writeText(context);
        setStatus('Context copied');
      } catch (error) {
        showMessage('Clipboard permission denied. Use Context MD download instead.');
      }
    }

    function resetFilters() {
      $('query').value = 'efficient attention';
      $('yearFrom').value = '';
      $('yearTo').value = '';
      $('edgeType').value = '';
      $('methodFilter').value = '';
      $('includeContext').checked = true;
      setMode('balanced', true);
      showMessage('');
      setStatus('Ready');
    }

    async function loadStats() {
      const s = await api('/api/stats');
      $('papersStat').textContent = s.papers ?? 0;
      $('methodsStat').textContent = s.methods ?? 0;
      $('edgesStat').textContent = s.edges ?? 0;
    }

    function renderAll() {
      renderMetrics();
      renderGraph();
      renderPapers();
      renderTimeline();
      renderFacts();
      renderEdges();
      renderSelection();
      updateDownloadState();
    }

    function renderMetrics() {
      const counts = state.evidence?.counts || {};
      const params = state.evidence?.parameters || {};
      $('viewPapers').textContent = counts.papers ?? Object.keys(state.papers).length;
      $('viewEdges').textContent = counts.method_edges ?? state.edges.length;
      $('viewBottlenecks').textContent = counts.bottlenecks ?? 0;
      $('viewMechanisms').textContent = counts.mechanisms ?? 0;
      $('viewMode').textContent = params.mode || state.mode;
      const filters = [];
      if (params.year_from || params.year_to) filters.push(`${params.year_from || 'any'}-${params.year_to || 'any'}`);
      if (params.edge_type) filters.push(params.edge_type);
      if (params.method) filters.push(`method: ${params.method}`);
      $('subtitle').textContent = filters.length
        ? `Evidence pack filtered by ${filters.join(', ')}.`
        : 'Build a query-specific evidence pack, inspect method evolution, and export data for downstream LLM or agent workflows.';
    }

    function renderGraph() {
      const svg = $('graphSvg');
      const papers = Object.values(state.papers).slice(0, 80);
      const ids = new Set(papers.map((paper) => paper.paper_id));
      const edges = state.edges.filter((edge) => ids.has(edge.source_paper_id) && ids.has(edge.target_paper_id)).slice(0, 180);
      $('graphMeta').textContent = `${papers.length} papers, ${edges.length} edges`;
      $('graphEmpty').style.display = papers.length ? 'none' : 'grid';
      if (!papers.length) {
        svg.innerHTML = '';
        return;
      }
      const width = svg.clientWidth || 860;
      const height = svg.clientHeight || 430;
      const padX = 58;
      const padY = 48;
      const years = papers.map((paper) => Number(paper.year)).filter(Boolean);
      const minYear = years.length ? Math.min(...years) : 0;
      const maxYear = years.length ? Math.max(...years) : papers.length - 1;
      const span = Math.max(1, maxYear - minYear);
      const sorted = [...papers].sort((a, b) => (a.year || 9999) - (b.year || 9999) || String(a.title).localeCompare(String(b.title)));
      const pos = {};
      sorted.forEach((paper, index) => {
        const hasYear = Number(paper.year);
        const x = hasYear
          ? padX + ((Number(paper.year) - minYear) / span) * (width - padX * 2)
          : padX + (index / Math.max(1, sorted.length - 1)) * (width - padX * 2);
        const lane = index % 5;
        const y = padY + lane * ((height - padY * 2) / 4);
        pos[paper.paper_id] = { x, y };
      });
      const yearLabels = years.length ? Array.from(new Set([minYear, maxYear])).map((year) => {
        const x = padX + ((year - minYear) / span) * (width - padX * 2);
        return `<text x="${x}" y="${height - 18}" text-anchor="middle" fill="#637083" font-size="11">${year}</text>`;
      }).join('') : '';
      const edgeSvg = edges.map((edge) => {
        const older = pos[edge.target_paper_id];
        const newer = pos[edge.source_paper_id];
        if (!older || !newer) return '';
        const midY = (older.y + newer.y) / 2 - 18;
        return `<path class="edge-line" d="M ${older.x} ${older.y} C ${older.x + 40} ${midY}, ${newer.x - 40} ${midY}, ${newer.x} ${newer.y}" fill="none" marker-end="url(#arrow)" />`;
      }).join('');
      const nodeSvg = sorted.map((paper) => {
        const xy = pos[paper.paper_id];
        const active = paper.paper_id === state.active;
        const seed = paper.evidence_role === 'seed';
        const label = escapeHtml(short(paper.title || paper.paper_id, 34));
        return `<g class="node ${active ? 'active' : ''} ${seed ? 'seed' : ''}" data-id="${escapeHtml(paper.paper_id)}">
          <circle cx="${xy.x}" cy="${xy.y}" r="${active ? 10 : 7}"></circle>
          <text x="${xy.x + 11}" y="${xy.y + 4}">${label}</text>
        </g>`;
      }).join('');
      svg.innerHTML = `<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8c8174"></path></marker></defs>${yearLabels}${edgeSvg}${nodeSvg}`;
      svg.querySelectorAll('.node').forEach((node) => {
        node.addEventListener('click', () => selectPaper(node.dataset.id));
      });
    }

    function renderPapers() {
      const papers = Object.values(state.papers);
      $('paperMeta').textContent = `${papers.length} papers`;
      $('paperList').innerHTML = papers.length ? papers.map((paper) => {
        const methods = (paper.methods || []).slice(0, 6).map((method) => `<span class="chip">${escapeHtml(method.canonical_name)}</span>`).join('');
        const meta = [paper.year, paper.venue, paper.evidence_role, paper.paper_id].filter(Boolean).join(' | ');
        return `<article class="paper-card ${state.active === paper.paper_id ? 'is-active' : ''}" data-id="${escapeHtml(paper.paper_id)}">
          <div class="title">${escapeHtml(paper.title || paper.paper_id)}</div>
          <div class="meta">${escapeHtml(meta)}</div>
          <div class="abstract">${escapeHtml(short(paper.abstract, 240))}</div>
          ${methods ? `<div class="chips">${methods}</div>` : ''}
        </article>`;
      }).join('') : '<div class="empty">No papers found for the current filters.</div>';
      document.querySelectorAll('.paper-card').forEach((el) => {
        el.addEventListener('click', () => selectPaper(el.dataset.id));
      });
    }

    function renderTimeline() {
      const timeline = state.evidence?.timeline || buildTimelineFromCurrentPapers();
      $('timelineMeta').textContent = `${timeline.length} entries`;
      $('timelineList').innerHTML = timeline.length ? timeline.map((item) => `
        <div class="timeline-row">
          <div class="title">${escapeHtml(item.year || 'unknown')} | ${escapeHtml(item.title)}</div>
          <div class="meta">${escapeHtml(item.paper_id)}${item.evidence_role ? ' | ' + escapeHtml(item.evidence_role) : ''}</div>
          <div class="chips">${(item.methods || []).slice(0, 5).map((name) => `<span class="chip">${escapeHtml(name)}</span>`).join('')}</div>
        </div>
      `).join('') : '<div class="empty">Timeline appears after search.</div>';
    }

    function renderFacts() {
      const bottlenecks = state.evidence?.bottlenecks || [];
      const mechanisms = state.evidence?.mechanisms || [];
      $('factMeta').textContent = `${bottlenecks.length + mechanisms.length} items`;
      const rows = [
        ...bottlenecks.map((item) => ({ kind: 'Bottleneck', text: item.bottleneck, meta: `${item.dimension || 'unknown'} | ${item.older_paper_id} -> ${item.newer_paper_id}` })),
        ...mechanisms.map((item) => ({ kind: 'Mechanism', text: item.mechanism, meta: `${item.source_method || 'method'} | ${item.older_paper_id} -> ${item.newer_paper_id}` })),
      ];
      $('factList').innerHTML = rows.length ? rows.map((row) => `
        <div class="fact-row">
          <div><span class="edge-type">${escapeHtml(row.kind)}</span></div>
          <div class="edge-detail">${escapeHtml(short(row.text, 220))}</div>
          <div class="meta">${escapeHtml(row.meta)}</div>
        </div>
      `).join('') : '<div class="empty">No bottlenecks or mechanisms loaded.</div>';
    }

    function renderEdges() {
      $('edgeMeta').textContent = `${state.edges.length} edges`;
      $('edgeList').innerHTML = state.edges.length ? state.edges.map((edge) => {
        const olderTitle = edge.older_paper?.title || edge.target_paper_id;
        const newerTitle = edge.newer_paper?.title || edge.source_paper_id;
        return `<article class="edge-card">
          <div><span class="edge-type">${escapeHtml(edge.edge_type || 'edge')}</span><span class="title">${escapeHtml(olderTitle)} -> ${escapeHtml(newerTitle)}</span></div>
          <div class="meta">${escapeHtml(edge.target_paper_id)} -> ${escapeHtml(edge.source_paper_id)} | confidence ${formatConfidence(edge.confidence)}</div>
          <div class="edge-detail"><strong>Bottleneck:</strong> ${escapeHtml(short(edge.bottleneck, 220))}</div>
          <div class="edge-detail"><strong>Mechanism:</strong> ${escapeHtml(short(edge.mechanism, 220))}</div>
        </article>`;
      }).join('') : '<div class="empty">No edges in current view.</div>';
    }

    function renderSelection() {
      const paper = state.active ? state.papers[state.active] : null;
      $('openNeighborhoodBtn').disabled = !paper || state.busy;
      if (!paper) {
        $('selectionTitle').textContent = 'No paper selected';
        $('selectionMeta').textContent = 'Select a node or paper row to inspect a local neighborhood.';
        return;
      }
      $('selectionTitle').textContent = paper.title || paper.paper_id;
      $('selectionMeta').textContent = [paper.year, paper.venue, paper.paper_id].filter(Boolean).join(' | ');
    }

    function selectPaper(paperId) {
      if (!paperId) return;
      state.active = paperId;
      renderGraph();
      renderPapers();
      renderSelection();
    }

    function updateDownloadState() {
      const hasPapers = Object.keys(state.papers).length > 0;
      const hasEdges = state.edges.length > 0;
      const hasContext = Boolean(state.evidence?.suggested_prompt_context);
      $('downloadJsonBtn').disabled = !hasPapers;
      $('downloadPapersBtn').disabled = !hasPapers;
      $('downloadEdgesBtn').disabled = !hasEdges;
      $('downloadContextBtn').disabled = !hasContext;
      $('copyBtn').disabled = !hasContext || state.busy;
    }

    function downloadJson() {
      const payload = state.evidence || { papers: Object.values(state.papers), method_edges: state.edges };
      downloadFile('intern-atlas-evidence.json', JSON.stringify(payload, null, 2), 'application/json');
    }

    function downloadPapersCsv() {
      const rows = Object.values(state.papers).map((paper) => ({
        paper_id: paper.paper_id,
        title: paper.title,
        year: paper.year || '',
        venue: paper.venue || '',
        role: paper.evidence_role || '',
        methods: (paper.methods || []).map((item) => item.canonical_name).join('; '),
        abstract: paper.abstract || '',
      }));
      downloadFile('intern-atlas-papers.csv', toCsv(rows), 'text/csv');
    }

    function downloadEdgesCsv() {
      const rows = state.edges.map((edge) => ({
        source_paper_id: edge.source_paper_id,
        target_paper_id: edge.target_paper_id,
        edge_type: edge.edge_type,
        confidence: edge.confidence,
        source_method: edge.source_method || '',
        target_method: edge.target_method || '',
        bottleneck: edge.bottleneck || '',
        mechanism: edge.mechanism || '',
      }));
      downloadFile('intern-atlas-edges.csv', toCsv(rows), 'text/csv');
    }

    function downloadContextMd() {
      const text = state.evidence?.suggested_prompt_context || '';
      downloadFile('intern-atlas-context.md', text, 'text/markdown');
    }

    function toCsv(rows) {
      if (!rows.length) return '';
      const headers = Object.keys(rows[0]);
      const quote = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
      return [headers.join(','), ...rows.map((row) => headers.map((header) => quote(row[header])).join(','))].join('\n');
    }

    function downloadFile(filename, text, type) {
      const blob = new Blob([text], { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus(`Downloaded ${filename}`);
    }

    function buildTimelineFromCurrentPapers() {
      return Object.values(state.papers).map((paper) => ({
        year: paper.year,
        paper_id: paper.paper_id,
        title: paper.title,
        evidence_role: paper.evidence_role || '',
        methods: (paper.methods || []).map((item) => item.canonical_name),
      })).sort((a, b) => (a.year || 9999) - (b.year || 9999));
    }

    function setBusy(value) {
      state.busy = value;
      $('runBtn').disabled = value;
      $('resetBtn').disabled = value;
      renderSelection();
      updateDownloadState();
    }

    function setStatus(text) {
      $('statusPill').textContent = text;
    }

    function showMessage(message) {
      $('toast').textContent = message ? String(message.message || message) : '';
    }

    function short(text, n = 180) {
      text = String(text || '');
      return text.length > n ? text.slice(0, n - 1) + '...' : text;
    }

    function formatConfidence(value) {
      const num = Number(value || 0);
      return num ? num.toFixed(2) : 'n/a';
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      }[ch]));
    }

    document.querySelectorAll('[data-mode]').forEach((button) => {
      button.addEventListener('click', () => setMode(button.dataset.mode, true));
    });
    $('runBtn').addEventListener('click', runEvidenceSearch);
    $('resetBtn').addEventListener('click', resetFilters);
    $('copyBtn').addEventListener('click', copyContext);
    $('docsBtn').addEventListener('click', () => { window.location.href = '/api/docs'; });
    $('openNeighborhoodBtn').addEventListener('click', openSelectedNeighborhood);
    $('downloadJsonBtn').addEventListener('click', downloadJson);
    $('downloadPapersBtn').addEventListener('click', downloadPapersCsv);
    $('downloadEdgesBtn').addEventListener('click', downloadEdgesCsv);
    $('downloadContextBtn').addEventListener('click', downloadContextMd);
    $('query').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') runEvidenceSearch();
    });

    setMode('balanced', true);
    updateDownloadState();
    loadStats().catch(showMessage).finally(runEvidenceSearch);
  </script>
</body>
</html>"""
