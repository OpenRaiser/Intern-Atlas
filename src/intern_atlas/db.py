"""SQLite storage and read helpers for local Intern Atlas graphs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import PaperRecord, RelationEdge
from .util import method_id_for, method_key

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS papers (
  internal_id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  abstract TEXT NOT NULL DEFAULT '',
  year INTEGER,
  authors_json TEXT NOT NULL DEFAULT '[]',
  venue TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'full',
  paper_type TEXT NOT NULL DEFAULT 'research',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS methods (
  method_id TEXT PRIMARY KEY,
  canonical_name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  origin_paper_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS method_aliases (
  alias_lower TEXT NOT NULL,
  method_id TEXT NOT NULL,
  alias_display TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (alias_lower, method_id)
);

CREATE TABLE IF NOT EXISTS paper_methods (
  paper_id TEXT NOT NULL,
  method_id TEXT NOT NULL,
  relationship TEXT NOT NULL DEFAULT 'uses',
  confidence REAL NOT NULL DEFAULT 1.0,
  source TEXT NOT NULL DEFAULT 'local_builder',
  PRIMARY KEY (paper_id, method_id)
);

CREATE TABLE IF NOT EXISTS citations (
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  fine_edge_type TEXT,
  fine_bottleneck TEXT,
  fine_mechanism TEXT,
  fine_bottleneck_dimension TEXT,
  fine_confidence REAL,
  fine_status TEXT,
  source_method TEXT,
  target_method TEXT,
  method_relation TEXT,
  contexts_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (source_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_citations_source ON citations(source_id);
CREATE INDEX IF NOT EXISTS idx_citations_target ON citations(target_id);
CREATE INDEX IF NOT EXISTS idx_citations_type ON citations(fine_edge_type);
CREATE INDEX IF NOT EXISTS idx_paper_methods_paper ON paper_methods(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_methods_method ON paper_methods(method_id);
"""


def connect(db_path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    path = Path(db_path)
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if not readonly:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    return conn


def write_graph(db_path: str | Path, records: list[PaperRecord], edges: list[RelationEdge]) -> dict[str, int]:
    conn = connect(db_path)
    method_ids: dict[str, str] = {}

    for rec in records:
        conn.execute(
            """
            INSERT OR REPLACE INTO papers
              (internal_id, title, abstract, year, authors_json, venue, status, paper_type)
            VALUES (?, ?, ?, ?, ?, ?, 'full', 'research')
            """,
            (
                rec.paper_id,
                rec.title,
                rec.abstract,
                rec.year,
                json.dumps(rec.authors, ensure_ascii=False),
                rec.venue,
            ),
        )
        for mention in rec.methods:
            key = method_key(mention.name)
            method_id = method_ids.setdefault(key, method_id_for(mention.name))
            conn.execute(
                """
                INSERT OR IGNORE INTO methods
                  (method_id, canonical_name, description, origin_paper_id)
                VALUES (?, ?, ?, ?)
                """,
                (
                    method_id,
                    mention.name,
                    mention.description,
                    rec.paper_id if mention.relationship == "introduces" else None,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO method_aliases
                  (alias_lower, method_id, alias_display)
                VALUES (?, ?, ?)
                """,
                (key, method_id, mention.name),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO paper_methods
                  (paper_id, method_id, relationship, confidence, source)
                VALUES (?, ?, ?, ?, 'local_builder')
                """,
                (rec.paper_id, method_id, mention.relationship, mention.confidence),
            )

    for edge in edges:
        conn.execute(
            """
            INSERT OR REPLACE INTO citations
              (source_id, target_id, fine_edge_type, fine_bottleneck,
               fine_mechanism, fine_bottleneck_dimension, fine_confidence,
               fine_status, source_method, target_method, method_relation,
               contexts_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'success', ?, ?, ?, '[]')
            """,
            (
                edge.source_id,
                edge.target_id,
                edge.edge_type,
                edge.bottleneck,
                edge.mechanism,
                edge.dimension,
                edge.confidence,
                edge.source_method,
                edge.target_method,
                edge.method_relation,
            ),
        )

    conn.commit()
    stats = graph_stats(conn)
    conn.close()
    return stats


def export_json(db_path: str | Path, json_path: str | Path) -> None:
    conn = connect(db_path, readonly=True)
    payload = {
        "papers": [dict(row) for row in conn.execute("SELECT * FROM papers ORDER BY year, title")],
        "methods": [dict(row) for row in conn.execute("SELECT * FROM methods ORDER BY canonical_name")],
        "paper_methods": [dict(row) for row in conn.execute("SELECT * FROM paper_methods")],
        "edges": [
            dict(row)
            for row in conn.execute(
                """
                SELECT source_id, target_id, fine_edge_type AS edge_type,
                       fine_bottleneck AS bottleneck,
                       fine_mechanism AS mechanism,
                       fine_bottleneck_dimension AS dimension,
                       fine_confidence AS confidence
                FROM citations
                WHERE fine_edge_type IS NOT NULL AND fine_edge_type != 'background'
                ORDER BY fine_confidence DESC
                """
            )
        ],
    }
    conn.close()
    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def graph_stats(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "papers": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
        "methods": conn.execute("SELECT COUNT(*) FROM methods").fetchone()[0],
        "edges": conn.execute(
            "SELECT COUNT(*) FROM citations WHERE fine_edge_type IS NOT NULL AND fine_edge_type != 'background'"
        ).fetchone()[0],
    }


def paper_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "paper_id": row["internal_id"],
        "title": row["title"],
        "abstract": row["abstract"],
        "year": row["year"],
        "authors": json.loads(row["authors_json"] or "[]"),
        "venue": row["venue"],
        "status": row["status"],
        "paper_type": row["paper_type"],
    }


def edge_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_paper_id": row["source_id"],
        "target_paper_id": row["target_id"],
        "edge_type": row["fine_edge_type"],
        "bottleneck": row["fine_bottleneck"] or "",
        "mechanism": row["fine_mechanism"] or "",
        "dimension": row["fine_bottleneck_dimension"] or "",
        "confidence": row["fine_confidence"] or 0.0,
        "source_method": row["source_method"] or "",
        "target_method": row["target_method"] or "",
    }

