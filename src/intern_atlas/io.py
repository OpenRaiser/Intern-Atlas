"""Load papers from PDF, TXT, JSON, JSONL, or CSV inputs."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .models import PaperRecord
from .util import paper_id_for, to_int


def load_records(
    inputs: list[str],
    pdf_dirs: list[str],
    *,
    max_pdf_pages: int = 8,
) -> list[PaperRecord]:
    records: list[PaperRecord] = []

    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.suffix.lower() in {".txt", ".json", ".jsonl", ".csv"}:
                    records.extend(read_metadata_file(child, start_order=len(records)))
        else:
            records.extend(read_metadata_file(path, start_order=len(records)))

    for raw in pdf_dirs:
        for pdf in sorted(Path(raw).rglob("*.pdf")):
            text, title = read_pdf(pdf, max_pages=max_pdf_pages)
            records.append(
                PaperRecord(
                    paper_id=paper_id_for(title or pdf.stem),
                    title=title or title_from_filename(pdf),
                    text=text,
                    source_path=str(pdf),
                    order=len(records),
                )
            )

    dedup: dict[str, PaperRecord] = {}
    for rec in records:
        if not rec.paper_id:
            rec.paper_id = paper_id_for(rec.title or rec.source_path or f"paper-{rec.order}")
        if rec.paper_id in dedup:
            rec.paper_id = f"{rec.paper_id}_{rec.order}"
        dedup[rec.paper_id] = rec
    return list(dedup.values())


def read_metadata_file(path: Path, *, start_order: int = 0) -> list[PaperRecord]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        out: list[PaperRecord] = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                out.append(record_from_mapping(json.loads(line), order=start_order + i, source=path))
        return out
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("papers") or data.get("records") or [data]
        return [
            record_from_mapping(item, order=start_order + i, source=path)
            for i, item in enumerate(data or [])
            if isinstance(item, dict)
        ]
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as fh:
            return [
                record_from_mapping(row, order=start_order + i, source=path)
                for i, row in enumerate(csv.DictReader(fh))
            ]
    if suffix == ".txt":
        return read_txt_records(path, start_order=start_order)
    raise ValueError(f"Unsupported input file: {path}")


def record_from_mapping(data: dict[str, Any], *, order: int, source: Path) -> PaperRecord:
    title = str(data.get("title") or data.get("paper_title") or "").strip()
    abstract = str(data.get("abstract") or data.get("summary") or "").strip()
    paper_id = str(data.get("paper_id") or data.get("id") or "").strip()
    authors = data.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in re.split(r";|,", authors) if a.strip()]
    return PaperRecord(
        paper_id=paper_id or paper_id_for(title or f"{source}-{order}"),
        title=title or paper_id or f"paper-{order}",
        abstract=abstract,
        year=to_int(data.get("year")),
        authors=list(authors) if isinstance(authors, list) else [],
        venue=str(data.get("venue") or data.get("conference") or data.get("journal") or "").strip(),
        text=str(data.get("text") or data.get("full_text") or "").strip(),
        source_path=str(source),
        order=order,
    )


def read_txt_records(path: Path, *, start_order: int) -> list[PaperRecord]:
    raw = path.read_text(encoding="utf-8")
    blocks = [b.strip() for b in re.split(r"\n\s*\n\s*\n+", raw) if b.strip()]
    if len(blocks) == 1 and raw.lower().count("title:") > 1:
        blocks = [b.strip() for b in re.split(r"(?im)^\s*title\s*:", raw) if b.strip()]
        blocks = ["Title: " + b for b in blocks]
    out: list[PaperRecord] = []
    for i, block in enumerate(blocks):
        title, abstract, year = parse_txt_block(block)
        out.append(
            PaperRecord(
                paper_id=paper_id_for(title or f"{path.stem}-{i}"),
                title=title or f"{path.stem} #{i + 1}",
                abstract=abstract,
                year=year,
                text=block,
                source_path=str(path),
                order=start_order + i,
            )
        )
    return out


def parse_txt_block(block: str) -> tuple[str, str, int | None]:
    fields: dict[str, list[str]] = {}
    current = "body"
    for line in block.splitlines():
        match = re.match(r"^\s*(title|abstract|year|authors|venue)\s*:\s*(.*)$", line, re.I)
        if match:
            current = match.group(1).lower()
            fields.setdefault(current, []).append(match.group(2).strip())
        else:
            fields.setdefault(current, []).append(line.strip())
    title = " ".join(fields.get("title") or []).strip()
    abstract = " ".join(fields.get("abstract") or []).strip()
    year = to_int(" ".join(fields.get("year") or []))
    if not title:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        title = lines[0] if lines else ""
        if not abstract:
            abstract = " ".join(lines[1:])
    return title, abstract, year


def read_pdf(path: Path, *, max_pages: int) -> tuple[str, str]:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional wheel import
        raise RuntimeError("PyMuPDF is required for PDF input.") from exc
    doc = fitz.open(path)
    title = (doc.metadata or {}).get("title") or ""
    pages = []
    for idx, page in enumerate(doc):
        if idx >= max_pages:
            break
        pages.append(page.get_text("text"))
    doc.close()
    return "\n".join(pages), (title.strip() if title and len(title.strip()) > 4 else "")


def title_from_filename(path: Path) -> str:
    return re.sub(r"[_-]+", " ", path.stem).strip().title()

