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
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return fetch_edges(
            conn,
            paper_id=paper_id,
            edge_type=edge_type,
            method=method,
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
            include_prompt_context=req.include_prompt_context,
        )

    @app.post("/api/assist/context")
    def assist_context(req: QueryRequest) -> dict[str, Any]:
        pack = build_evidence_pack(
            conn,
            req.query,
            max_papers=min(req.max_nodes, 20),
            max_edges=40,
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
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return fetch_edges(
            conn,
            paper_id=paper_id,
            edge_type=edge_type,
            method=method,
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


def collect_relevant_paper_ids(conn, query: str, *, max_nodes: int, depth: int = 1) -> list[str]:
    seed_ids = search_relevant_paper_ids(conn, query, limit=max_nodes)
    return expand_from_seed_papers(conn, seed_ids, max_nodes=max_nodes, depth=depth)


def search_relevant_paper_ids(conn, query: str, *, limit: int) -> list[str]:
    rows = conn.execute("SELECT * FROM papers ORDER BY year DESC, title").fetchall()
    if not rows:
        return []
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


def expand_from_seed_papers(conn, seed_ids: list[str], *, max_nodes: int, depth: int) -> list[str]:
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
                SELECT source_id AS neighbor, COALESCE(fine_confidence, 0) AS confidence
                FROM citations
                WHERE target_id = ?
                  AND fine_edge_type IS NOT NULL AND fine_edge_type != 'background'
                UNION ALL
                SELECT target_id AS neighbor, COALESCE(fine_confidence, 0) AS confidence
                FROM citations
                WHERE source_id = ?
                  AND fine_edge_type IS NOT NULL AND fine_edge_type != 'background'
                ORDER BY confidence DESC
                """,
                (current, current),
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
    include_prompt_context: bool,
) -> dict[str, Any]:
    seed_ids = search_relevant_paper_ids(conn, query, limit=max_papers)
    paper_ids = expand_from_seed_papers(conn, seed_ids, max_nodes=max_papers, depth=1)
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
    method_edges = enrich_edges(sg["edges"][:max_edges], papers_by_id)
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
    }


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
  <title>Intern Atlas Local Graph</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f7f8;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #657181;
      --line: #d7e1e6;
      --brand: #315f82;
      --brand-2: #0f766e;
      --accent: #b45309;
      --red: #b42318;
      --shadow: 0 16px 40px rgba(31, 41, 51, 0.10);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
    }
    button, input, select { font: inherit; }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
    }
    .sidebar {
      border-right: 1px solid var(--line);
      background: #e8f0f2;
      padding: 24px;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 24px;
    }
    .mark {
      width: 38px;
      height: 38px;
      border: 1px solid #244b65;
      background: #244b65;
      color: white;
      display: grid;
      place-items: center;
      font-weight: 800;
      border-radius: 8px;
    }
    .brand h1 {
      font-size: 18px;
      line-height: 1.1;
      margin: 0;
    }
    .brand p {
      color: var(--muted);
      margin: 3px 0 0;
      font-size: 12px;
    }
    .stats {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      margin-bottom: 22px;
    }
    .stat {
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    .stat strong {
      display: block;
      font-size: 24px;
      letter-spacing: 0;
    }
    .stat span {
      color: var(--muted);
      font-size: 12px;
    }
    .control {
      display: grid;
      gap: 8px;
      margin-bottom: 18px;
    }
    .control label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .search-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    input, select {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--ink);
      padding: 10px 11px;
      outline: none;
    }
    input:focus, select:focus {
      border-color: var(--brand);
      box-shadow: 0 0 0 3px rgba(49, 95, 130, 0.15);
    }
    button {
      border: 1px solid #244b65;
      border-radius: 8px;
      background: var(--brand);
      color: white;
      padding: 10px 13px;
      cursor: pointer;
      font-weight: 700;
    }
    button.secondary {
      background: transparent;
      color: var(--brand);
      border-color: var(--line);
    }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .main {
      min-width: 0;
      padding: 28px;
    }
    .toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 18px;
    }
    .toolbar h2 {
      margin: 0;
      font-size: 24px;
      letter-spacing: 0;
    }
    .toolbar p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 14px;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
      gap: 18px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel-head {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    .panel-head h3 {
      margin: 0;
      font-size: 15px;
    }
    .panel-head span {
      color: var(--muted);
      font-size: 12px;
    }
    .list {
      max-height: calc(100vh - 170px);
      overflow: auto;
    }
    .paper, .edge {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      cursor: pointer;
    }
    .paper:hover, .edge:hover {
      background: #eef6f4;
    }
    .paper.is-active {
      border-left: 4px solid var(--brand);
      padding-left: 12px;
      background: #edf3f6;
    }
    .title {
      font-weight: 760;
      line-height: 1.35;
    }
    .meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 5px;
    }
    .abstract {
      color: #3f4b57;
      margin-top: 8px;
      font-size: 13px;
      line-height: 1.45;
    }
    .edge-type {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      background: #e8f3f1;
      color: var(--brand-2);
      font-size: 12px;
      padding: 3px 8px;
      margin-right: 8px;
      font-weight: 800;
    }
    .edge .title {
      font-size: 13px;
    }
    .edge-detail {
      color: #3f4b57;
      margin-top: 8px;
      font-size: 12px;
      line-height: 1.45;
    }
    .canvas-wrap {
      height: 420px;
      background: #f7fafb;
      border-bottom: 1px solid var(--line);
    }
    svg {
      width: 100%;
      height: 100%;
      display: block;
    }
    .node circle {
      fill: #315f82;
      stroke: #fffdf8;
      stroke-width: 2;
    }
    .node text {
      font-size: 11px;
      fill: #1f2933;
      paint-order: stroke;
      stroke: #ffffff;
      stroke-width: 4px;
      stroke-linejoin: round;
    }
    .empty {
      color: var(--muted);
      padding: 28px 16px;
      text-align: center;
    }
    .toast {
      color: var(--red);
      font-size: 13px;
      margin-top: 10px;
      min-height: 18px;
    }
    @media (max-width: 920px) {
      .shell { grid-template-columns: 1fr; }
      .sidebar { position: relative; height: auto; }
      .grid { grid-template-columns: 1fr; }
      .list { max-height: none; }
      .toolbar { align-items: flex-start; flex-direction: column; }
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
          <p>Local method-evolution graph</p>
        </div>
      </div>

      <div class="stats">
        <div class="stat"><strong id="papersStat">-</strong><span>Papers</span></div>
        <div class="stat"><strong id="methodsStat">-</strong><span>Methods</span></div>
        <div class="stat"><strong id="edgesStat">-</strong><span>Evolution edges</span></div>
      </div>

      <div class="control">
        <label for="query">Search local graph</label>
        <div class="search-row">
          <input id="query" value="attention" placeholder="paper, method, bottleneck..." />
          <button id="runBtn">Search</button>
        </div>
        <div class="search-row">
          <select id="mode">
            <option value="query">Subgraph</option>
            <option value="papers">Papers</option>
            <option value="methods">Methods</option>
          </select>
          <button id="contextBtn" class="secondary">Context</button>
        </div>
        <div class="toast" id="toast"></div>
      </div>

      <button class="secondary" onclick="location.href='/api/docs'">Open API Docs</button>
    </aside>

    <main class="main">
      <div class="toolbar">
        <div>
          <h2>Graph Workspace</h2>
          <p id="subtitle">Search papers, inspect methodology edges, and copy graph evidence for your own LLM workflow.</p>
        </div>
      </div>

      <div class="grid">
        <section class="panel">
          <div class="panel-head">
            <h3>Graph</h3>
            <span id="graphMeta">0 papers · 0 edges</span>
          </div>
          <div class="canvas-wrap"><svg id="graphSvg" role="img" aria-label="method evolution graph"></svg></div>
          <div class="panel-head">
            <h3>Papers</h3>
            <span id="paperMeta">No selection</span>
          </div>
          <div class="list" id="paperList"><div class="empty">Run a search to load papers.</div></div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <h3>Evidence</h3>
            <span id="edgeMeta">Edges and context</span>
          </div>
          <div class="list" id="edgeList"><div class="empty">Evolution edges will appear here.</div></div>
        </section>
      </div>
    </main>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const state = { papers: {}, edges: [], active: null };

    async function api(path, opts = {}) {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
      });
      if (!res.ok) throw new Error(`API ${res.status}`);
      return res.json();
    }

    function showError(error) {
      $('toast').textContent = error ? String(error.message || error) : '';
    }

    function short(text, n = 180) {
      text = text || '';
      return text.length > n ? text.slice(0, n - 1) + '...' : text;
    }

    async function loadStats() {
      const s = await api('/api/stats');
      $('papersStat').textContent = s.papers ?? 0;
      $('methodsStat').textContent = s.methods ?? 0;
      $('edgesStat').textContent = s.edges ?? 0;
    }

    async function runSearch() {
      showError('');
      $('runBtn').disabled = true;
      try {
        const query = $('query').value.trim();
        const mode = $('mode').value;
        if (!query) return;
        if (mode === 'papers') {
          const papers = await api(`/api/papers/search?q=${encodeURIComponent(query)}&limit=40`);
          state.papers = Object.fromEntries(papers.map(p => [p.paper_id, p]));
          state.edges = [];
        } else if (mode === 'methods') {
          const methods = await api(`/api/methods?q=${encodeURIComponent(query)}&limit=80`);
          state.papers = Object.fromEntries(methods.map(m => [m.method_id, {
            paper_id: m.method_id,
            title: m.canonical_name,
            abstract: m.description || 'Method entity',
            year: '',
            venue: m.origin_paper_id ? `origin: ${m.origin_paper_id}` : ''
          }]));
          state.edges = [];
        } else {
          const sg = await api('/api/query', {
            method: 'POST',
            body: JSON.stringify({ query, max_nodes: 80 })
          });
          state.papers = sg.papers || {};
          state.edges = sg.edges || [];
        }
        renderAll();
      } catch (error) {
        showError(error);
      } finally {
        $('runBtn').disabled = false;
      }
    }

    async function loadContext() {
      showError('');
      $('contextBtn').disabled = true;
      try {
        const data = await api('/api/assist/context', {
          method: 'POST',
          body: JSON.stringify({ query: $('query').value.trim() || 'attention', max_nodes: 80 })
        });
        state.papers = Object.fromEntries((data.papers || []).map(p => [p.paper_id, p]));
        state.edges = data.evolution_edges || [];
        renderAll();
        await navigator.clipboard?.writeText(data.suggested_prompt_context || '');
        $('subtitle').textContent = 'Context loaded. Prompt context copied when clipboard permission is available.';
      } catch (error) {
        showError(error);
      } finally {
        $('contextBtn').disabled = false;
      }
    }

    function renderAll() {
      renderPapers();
      renderEdges();
      renderGraph();
    }

    function renderPapers() {
      const papers = Object.values(state.papers);
      $('paperMeta').textContent = `${papers.length} papers`;
      $('paperList').innerHTML = papers.length ? papers.map(p => `
        <article class="paper ${state.active === p.paper_id ? 'is-active' : ''}" data-id="${p.paper_id}">
          <div class="title">${escapeHtml(p.title || p.paper_id)}</div>
          <div class="meta">${escapeHtml([p.year, p.venue, p.paper_id].filter(Boolean).join(' · '))}</div>
          <div class="abstract">${escapeHtml(short(p.abstract, 220))}</div>
        </article>
      `).join('') : '<div class="empty">No papers found.</div>';
      document.querySelectorAll('.paper').forEach(el => {
        el.addEventListener('click', async () => {
          state.active = el.dataset.id;
          await loadNeighborhood(state.active);
        });
      });
    }

    async function loadNeighborhood(id) {
      if (!id || id.startsWith('m_')) return;
      showError('');
      try {
        const sg = await api(`/api/papers/${encodeURIComponent(id)}/neighborhood?depth=1&limit=80`);
        state.papers = sg.papers || {};
        state.edges = sg.edges || [];
        renderAll();
      } catch (error) {
        showError(error);
      }
    }

    function renderEdges() {
      $('edgeMeta').textContent = `${state.edges.length} edges`;
      $('edgeList').innerHTML = state.edges.length ? state.edges.map(e => `
        <article class="edge">
          <div><span class="edge-type">${escapeHtml(e.edge_type || 'edge')}</span><span class="title">${escapeHtml(e.source_paper_id)} -> ${escapeHtml(e.target_paper_id)}</span></div>
          <div class="edge-detail"><strong>Bottleneck:</strong> ${escapeHtml(short(e.bottleneck, 220))}</div>
          <div class="edge-detail"><strong>Mechanism:</strong> ${escapeHtml(short(e.mechanism, 220))}</div>
        </article>
      `).join('') : '<div class="empty">No edges in current view.</div>';
    }

    function renderGraph() {
      const svg = $('graphSvg');
      const papers = Object.values(state.papers).slice(0, 60);
      const ids = new Set(papers.map(p => p.paper_id));
      const edges = state.edges.filter(e => ids.has(e.source_paper_id) && ids.has(e.target_paper_id)).slice(0, 120);
      $('graphMeta').textContent = `${papers.length} papers · ${edges.length} edges`;
      if (!papers.length) {
        svg.innerHTML = '';
        return;
      }
      const width = svg.clientWidth || 800;
      const height = svg.clientHeight || 420;
      const cx = width / 2;
      const cy = height / 2;
      const radius = Math.max(90, Math.min(width, height) * 0.36);
      const pos = {};
      papers.forEach((p, i) => {
        const a = (Math.PI * 2 * i) / papers.length - Math.PI / 2;
        pos[p.paper_id] = { x: cx + Math.cos(a) * radius, y: cy + Math.sin(a) * radius };
      });
      const edgeSvg = edges.map(e => {
        const a = pos[e.source_paper_id], b = pos[e.target_paper_id];
        return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#9b8f7e" stroke-width="1.4" opacity="0.65" />`;
      }).join('');
      const nodeSvg = papers.map((p) => {
        const xy = pos[p.paper_id];
        const label = escapeHtml(short(p.title || p.paper_id, 28));
        const active = state.active === p.paper_id;
        return `<g class="node" data-id="${escapeHtml(p.paper_id)}">
          <circle cx="${xy.x}" cy="${xy.y}" r="${active ? 10 : 7}" fill="${active ? '#b45309' : '#315f82'}"></circle>
          <text x="${xy.x + 10}" y="${xy.y + 4}">${label}</text>
        </g>`;
      }).join('');
      svg.innerHTML = edgeSvg + nodeSvg;
      svg.querySelectorAll('.node').forEach(node => {
        node.addEventListener('click', () => {
          state.active = node.dataset.id;
          loadNeighborhood(state.active);
        });
      });
    }

    function escapeHtml(value) {
      return String(value || '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      }[ch]));
    }

    $('runBtn').addEventListener('click', runSearch);
    $('contextBtn').addEventListener('click', loadContext);
    $('query').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') runSearch();
    });

    loadStats().catch(showError).finally(runSearch);
  </script>
</body>
</html>"""
