"""Build a local method-evolution graph from paper records."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import export_json, write_graph
from .io import load_records
from .llm import LLMClient, llm_configured
from .models import MethodMention, PaperRecord, RelationEdge
from .util import (
    VALID_EDGE_TYPES,
    VALID_METHOD_RELATIONS,
    VALID_PAPER_METHOD_RELS,
    as_text_list,
    clean,
    method_key,
    to_float,
    tokens,
)


@dataclass
class BuildResult:
    db_path: str
    json_path: str | None
    papers: int
    methods: int
    edges: int
    llm_used: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "db": self.db_path,
            "json": self.json_path,
            "papers": self.papers,
            "methods": self.methods,
            "edges": self.edges,
            "llm_used": self.llm_used,
        }


def build_from_sources(
    *,
    inputs: list[str],
    pdf_dirs: list[str],
    out_db: str | Path,
    out_json: str | Path | None = None,
    use_llm: bool = True,
    max_papers: int = 0,
    max_pairs: int = 120,
    min_confidence: float = 0.35,
    max_pdf_pages: int = 8,
    max_text_chars: int = 12000,
) -> BuildResult:
    records = load_records(inputs, pdf_dirs, max_pdf_pages=max_pdf_pages)
    if max_papers:
        records = records[:max_papers]
    if not records:
        raise ValueError("No papers loaded. Provide --input or --pdf-dir.")

    llm = LLMClient() if use_llm and llm_configured() else None
    try:
        for rec in records:
            enrich_paper(rec, llm=llm, max_chars=max_text_chars)
        edges = infer_relations(
            records,
            llm=llm,
            max_pairs=max_pairs,
            min_confidence=min_confidence,
        )
    finally:
        if llm is not None:
            llm.close()

    stats = write_graph(out_db, records, edges)
    if out_json:
        export_json(out_db, out_json)
    return BuildResult(
        db_path=str(out_db),
        json_path=str(out_json) if out_json else None,
        papers=stats["papers"],
        methods=stats["methods"],
        edges=stats["edges"],
        llm_used=llm is not None,
    )


def enrich_paper(rec: PaperRecord, *, llm: LLMClient | None, max_chars: int) -> None:
    text = "\n".join(x for x in [rec.title, rec.abstract, rec.text] if x).strip()
    if llm is None:
        enrich_heuristic(rec, text)
        return
    try:
        payload = llm_extract_paper(llm, rec, text[:max_chars])
    except Exception as exc:
        print(f"[warn] LLM paper extraction failed for {rec.paper_id}: {exc}")
        enrich_heuristic(rec, text)
        return

    rec.title = clean(payload.get("title") or rec.title, 300) or rec.title
    rec.abstract = clean(payload.get("abstract") or rec.abstract, 2200)
    rec.contribution = clean(payload.get("main_contribution"), 1000)
    rec.bottlenecks = as_text_list(payload.get("bottlenecks"), 8, 240)
    for item in payload.get("methods") or []:
        if not isinstance(item, dict):
            continue
        name = clean(item.get("name") or item.get("method"), 120)
        if not name:
            continue
        rel = str(item.get("relationship") or item.get("rel") or "uses").lower()
        if rel not in VALID_PAPER_METHOD_RELS:
            rel = "uses"
        rec.methods.append(
            MethodMention(
                name=name,
                relationship=rel,
                description=clean(item.get("description"), 500),
                confidence=to_float(item.get("confidence"), 0.8),
            )
        )
    if not rec.methods:
        enrich_heuristic(rec, text)


def llm_extract_paper(llm: LLMClient, rec: PaperRecord, text: str) -> dict[str, Any]:
    prompt = {
        "paper_id": rec.paper_id,
        "known_title": rec.title,
        "known_abstract": rec.abstract,
        "text": text,
    }
    return llm.chat_json(
        [
            {
                "role": "system",
                "content": (
                    "Extract structured method-evolution metadata from a computer science paper. "
                    "Return one JSON object with title, abstract, main_contribution, bottlenecks, "
                    "and methods. Each method has name, relationship "
                    "(introduces|uses|extends|compares), description, confidence."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=1200,
    )


def enrich_heuristic(rec: PaperRecord, text: str) -> None:
    candidates: set[str] = set()
    for match in re.findall(r"\b[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)?\b", text):
        if (3 <= len(match) <= 30 and match.upper() == match) or match in {
            "LoRA",
            "ResNet",
            "Transformer",
            "FlashAttention",
        }:
            candidates.add(match)
    phrase_re = re.compile(
        r"\b([A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*){0,3}\s+"
        r"(?:Attention|Transformer|Network|Model|Algorithm|Optimizer|Adapter|Encoding))\b"
    )
    candidates.update(m.group(1) for m in phrase_re.finditer(text))
    for name in sorted(candidates, key=lambda x: (-len(x), x))[:12]:
        rel = "introduces" if name.lower() in rec.title.lower() else "uses"
        rec.methods.append(MethodMention(name=name, relationship=rel, confidence=0.45))
    if not rec.abstract and rec.text:
        rec.abstract = clean(rec.text, 1200)


def infer_relations(
    records: list[PaperRecord],
    *,
    llm: LLMClient | None,
    max_pairs: int,
    min_confidence: float,
) -> list[RelationEdge]:
    pairs = select_candidate_pairs(records, max_pairs=max_pairs)
    edges: list[RelationEdge] = []
    for newer, older, score in pairs:
        if llm is None:
            edge = heuristic_relation(newer, older, score)
        else:
            try:
                edge = llm_relation(llm, newer, older)
            except Exception as exc:
                print(f"[warn] LLM relation failed for {newer.paper_id}->{older.paper_id}: {exc}")
                edge = heuristic_relation(newer, older, score)
        if not edge:
            continue
        if edge.edge_type == "background" or edge.confidence < min_confidence:
            continue
        edges.append(edge)
    return edges


def select_candidate_pairs(
    records: list[PaperRecord],
    *,
    max_pairs: int,
) -> list[tuple[PaperRecord, PaperRecord, float]]:
    pairs: list[tuple[PaperRecord, PaperRecord, float]] = []
    for i, a in enumerate(records):
        for b in records[:i] + records[i + 1 :]:
            newer, older = orient_pair(a, b)
            if newer.paper_id == older.paper_id:
                continue
            score = pair_score(newer, older)
            if score > 0:
                pairs.append((newer, older, score))

    seen: set[tuple[str, str]] = set()
    out: list[tuple[PaperRecord, PaperRecord, float]] = []
    for newer, older, score in sorted(pairs, key=lambda x: x[2], reverse=True):
        key = (newer.paper_id, older.paper_id)
        if key in seen:
            continue
        seen.add(key)
        out.append((newer, older, score))
        if len(out) >= max_pairs:
            break
    return out


def orient_pair(a: PaperRecord, b: PaperRecord) -> tuple[PaperRecord, PaperRecord]:
    ay = a.year or 0
    by = b.year or 0
    if ay != by:
        return (a, b) if ay > by else (b, a)
    return (a, b) if a.order > b.order else (b, a)


def pair_score(newer: PaperRecord, older: PaperRecord) -> float:
    new_methods = {method_key(m.name) for m in newer.methods}
    old_methods = {method_key(m.name) for m in older.methods}
    shared = len(new_methods & old_methods)
    title_overlap = len(tokens(newer.title) & tokens(older.title))
    abstract_overlap = len(tokens(newer.abstract) & tokens(older.abstract))
    if not shared and title_overlap < 2:
        # Avoid turning generic abstract overlap such as "efficient" or
        # "model" into a false methodology edge.
        return 0.0
    return shared * 4 + title_overlap * 0.8 + min(abstract_overlap, 8) * 0.2


def heuristic_relation(newer: PaperRecord, older: PaperRecord, score: float) -> RelationEdge | None:
    shared = sorted({method_key(m.name) for m in newer.methods} & {method_key(m.name) for m in older.methods})
    if not shared and score <= 0:
        return None
    return RelationEdge(
        source_id=newer.paper_id,
        target_id=older.paper_id,
        edge_type="extends" if shared else "uses_component",
        bottleneck="Potential methodological continuity inferred from shared terminology.",
        mechanism="Heuristic relation. Rebuild with an LLM for evidence-grounded bottlenecks and mechanisms.",
        dimension="method_continuity",
        confidence=min(0.65, 0.35 + score / 20),
        source_method=shared[0] if shared else "",
        target_method=shared[0] if shared else "",
    )


def llm_relation(llm: LLMClient, newer: PaperRecord, older: PaperRecord) -> RelationEdge | None:
    payload = {
        "newer_paper": paper_brief(newer),
        "older_paper": paper_brief(older),
        "instruction": (
            "Decide whether the newer paper methodologically extends, improves, adapts, "
            "combines, replaces, compares with, or uses a component from the older paper. "
            "Return background if there is no concrete methodology relation."
        ),
    }
    data = llm.chat_json(
        [
            {
                "role": "system",
                "content": (
                    "You classify methodology-evolution relations between two papers. "
                    "Return one JSON object: edge_type, confidence, bottleneck, mechanism, "
                    "dimension, method_relation, source_method, target_method. edge_type must "
                    "be extends|improves|replaces|adapts|combines|uses_component|compares|background. "
                    "method_relation, if present, must be variant_of|component_of|specializes|"
                    "combines|optimizes|inspired_by."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=800,
    )
    edge_type = str(data.get("edge_type") or "background").lower()
    if edge_type not in VALID_EDGE_TYPES:
        edge_type = "background"
    method_relation = clean(data.get("method_relation"), 80).lower()
    if method_relation and method_relation not in VALID_METHOD_RELATIONS:
        method_relation = ""
    return RelationEdge(
        source_id=newer.paper_id,
        target_id=older.paper_id,
        edge_type=edge_type,
        bottleneck=clean(data.get("bottleneck"), 700),
        mechanism=clean(data.get("mechanism"), 700),
        dimension=clean(data.get("dimension"), 120),
        confidence=to_float(data.get("confidence"), 0.0),
        source_method=clean(data.get("source_method"), 160),
        target_method=clean(data.get("target_method"), 160),
        method_relation=method_relation,
    )


def paper_brief(rec: PaperRecord) -> dict[str, Any]:
    return {
        "paper_id": rec.paper_id,
        "title": rec.title,
        "year": rec.year,
        "abstract": rec.abstract[:1800],
        "contribution": rec.contribution[:800],
        "bottlenecks": rec.bottlenecks[:6],
        "methods": [
            {"name": m.name, "relationship": m.relationship, "description": m.description}
            for m in rec.methods[:12]
        ],
    }
