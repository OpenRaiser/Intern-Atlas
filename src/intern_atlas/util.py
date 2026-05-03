"""Shared parsing and normalization helpers."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


VALID_EDGE_TYPES = {
    "extends",
    "improves",
    "replaces",
    "adapts",
    "combines",
    "uses_component",
    "compares",
    "background",
}

VALID_PAPER_METHOD_RELS = {"introduces", "uses", "extends", "compares"}

VALID_METHOD_RELATIONS = {
    "variant_of",
    "component_of",
    "specializes",
    "combines",
    "optimizes",
    "inspired_by",
}


def paper_id_for(seed: str) -> str:
    slug = slugify(seed)[:60] or "paper"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"local_{slug}_{digest}"


def method_id_for(name: str) -> str:
    slug = slugify(name)[:70] or "method"
    digest = hashlib.sha1(name.lower().encode("utf-8")).hexdigest()[:8]
    return f"m_{slug}_{digest}"


def slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return re.sub(r"_+", "_", text)


def method_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def tokens(text: str) -> set[str]:
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "using",
        "based",
        "method",
        "methods",
        "model",
        "models",
        "paper",
        "approach",
    }
    return {
        t
        for t in re.findall(r"[a-z][a-z0-9-]{2,}", (text or "").lower())
        if t not in stop
    }


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d{4}", str(value))
    return int(match.group(0)) if match else None


def to_float(value: Any, default: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        out = default
    return max(0.0, min(1.0, out))


def clean(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).replace("\n", " ").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "..."


def as_text_list(value: Any, max_items: int, item_limit: int) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [x.strip(" -") for x in re.split(r"\n+|;", value) if x.strip(" -")]
    elif isinstance(value, list):
        raw = value
    else:
        raw = [value]
    return [clean(x, item_limit) for x in raw[:max_items] if clean(x, item_limit)]


def parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}

