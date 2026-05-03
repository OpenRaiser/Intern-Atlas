"""Small data containers used by the local graph builder."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MethodMention:
    name: str
    relationship: str = "uses"
    description: str = ""
    confidence: float = 0.7


@dataclass
class PaperRecord:
    paper_id: str
    title: str
    abstract: str = ""
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str = ""
    text: str = ""
    source_path: str = ""
    order: int = 0
    methods: list[MethodMention] = field(default_factory=list)
    bottlenecks: list[str] = field(default_factory=list)
    contribution: str = ""


@dataclass
class RelationEdge:
    source_id: str
    target_id: str
    edge_type: str
    bottleneck: str = ""
    mechanism: str = ""
    dimension: str = ""
    confidence: float = 0.5
    source_method: str = ""
    target_method: str = ""
    method_relation: str = ""

