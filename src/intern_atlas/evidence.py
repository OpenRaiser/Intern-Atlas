"""Evidence-pack and graph query helpers for the local API."""

from __future__ import annotations

from collections import deque
from typing import Any

from .db import edge_summary, paper_summary
from .util import tokens


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
    cleaned_edge_type = (edge_type or "").strip()
    cleaned_method = (method or "").strip().lower()
    if year_from is not None and year_to is not None and year_from > year_to:
        year_from, year_to = year_to, year_from
    if paper_id:
        clauses.append("(source_id = ? OR target_id = ?)")
        params.extend([paper_id, paper_id])
    if cleaned_edge_type:
        clauses.append("fine_edge_type = ?")
        params.append(cleaned_edge_type)
    if cleaned_method:
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
        method_like = f"%{cleaned_method}%"
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
    return expand_from_seed_papers(
        conn,
        seed_ids,
        max_nodes=max_nodes,
        depth=depth,
        year_from=year_from,
        year_to=year_to,
    )


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
    search_query = f"{query} {params['method']}".strip() if params["method"] else query
    seed_ids = search_relevant_paper_ids(
        conn,
        search_query,
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
        "light": {"max_papers": 12, "max_edges": 18, "default_depth": 0, "max_depth": 0, "seed_limit": 12},
        "balanced": {"max_papers": 24, "max_edges": 50, "default_depth": 1, "max_depth": 2, "seed_limit": 24},
        "deep": {"max_papers": 100, "max_edges": 300, "default_depth": 2, "max_depth": 4, "seed_limit": 60},
    }
    preset = presets[mode]
    effective_max_papers = min(max(1, max_papers), preset["max_papers"])
    effective_max_edges = min(max(0, max_edges), preset["max_edges"])
    effective_depth = preset["default_depth"] if depth is None else min(max(depth, 0), preset["max_depth"])
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
                "name": "intern_atlas_hosted_evidence_context",
                "method": "POST",
                "path": "/api/v1/remote/evidence/context",
                "description": "Proxy the same evidence-pack request to a hosted Intern Atlas API through the local server.",
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
                        "base_url": {"type": "string", "description": "Optional hosted API base URL."},
                        "api_key": {"type": "string", "description": "Optional hosted API bearer token."},
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
    exists = conn.execute("SELECT 1 FROM papers WHERE internal_id = ?", (start_id,)).fetchone()
    if not exists:
        return set()
    visited = {start_id}
    frontier = deque([(start_id, 0)])
    while frontier and len(visited) < max_nodes:
        current, d = frontier.popleft()
        if d >= depth:
            continue
        rows = conn.execute(
            """
            SELECT source_id AS neighbor
            FROM citations
            WHERE target_id = ?
              AND fine_edge_type IS NOT NULL AND fine_edge_type != 'background'
            UNION
            SELECT target_id AS neighbor
            FROM citations
            WHERE source_id = ?
              AND fine_edge_type IS NOT NULL AND fine_edge_type != 'background'
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
