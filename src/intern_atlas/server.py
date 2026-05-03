"""FastAPI app for querying a local Intern Atlas SQLite graph."""

from collections import deque
from pathlib import Path
from typing import Any

from .db import connect, edge_summary, graph_stats, paper_summary


def create_app(db_path: str | Path):
    from fastapi import FastAPI, HTTPException, Query
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
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        clauses = ["fine_edge_type IS NOT NULL", "fine_edge_type != 'background'"]
        params: list[Any] = []
        if paper_id:
            clauses.append("(source_id = ? OR target_id = ?)")
            params.extend([paper_id, paper_id])
        if edge_type:
            clauses.append("fine_edge_type = ?")
            params.append(edge_type)
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
        seed_rows = conn.execute(
            """
            SELECT internal_id FROM papers
            WHERE title LIKE ? OR abstract LIKE ?
            ORDER BY year DESC, title
            LIMIT 10
            """,
            (f"%{req.query}%", f"%{req.query}%"),
        ).fetchall()
        ids: set[str] = set()
        for row in seed_rows:
            ids |= bfs_papers(conn, row["internal_id"], depth=1, max_nodes=req.max_nodes)
            if len(ids) >= req.max_nodes:
                break
        return subgraph(conn, set(list(ids)[: req.max_nodes]))

    @app.post("/api/assist/context")
    def assist_context(req: QueryRequest) -> dict[str, Any]:
        sg = query(req)
        papers = list(sg["papers"].values())[:12]
        edges = sg["edges"][:20]
        return {
            "query": req.query,
            "papers": papers,
            "evolution_edges": edges,
            "suggested_prompt_context": prompt_context(req.query, papers, edges),
        }

    return app


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
