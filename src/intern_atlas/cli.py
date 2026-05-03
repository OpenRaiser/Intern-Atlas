"""Command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .builder import build_from_sources
from .db import connect, graph_stats
from .remote import InternAtlasClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="intern-atlas")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build a local method-evolution graph.")
    p_build.add_argument("--input", action="append", default=[], help="TXT/JSON/JSONL/CSV file or directory.")
    p_build.add_argument("--pdf-dir", action="append", default=[], help="Directory containing PDF files.")
    p_build.add_argument("--out", type=Path, default=Path("outputs/local_method_graph.db"))
    p_build.add_argument("--json", type=Path, default=None, help="Optional JSON export path.")
    p_build.add_argument("--no-llm", action="store_true", help="Use heuristic extraction only.")
    p_build.add_argument("--max-papers", type=int, default=0)
    p_build.add_argument("--max-pairs", type=int, default=120)
    p_build.add_argument("--min-confidence", type=float, default=0.35)
    p_build.add_argument("--max-pdf-pages", type=int, default=8)
    p_build.add_argument("--max-text-chars", type=int, default=12000)

    p_serve = sub.add_parser("serve", help="Serve a local graph with FastAPI.")
    p_serve.add_argument("--db", type=Path, required=True)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    p_stats = sub.add_parser("stats", help="Print local graph stats.")
    p_stats.add_argument("--db", type=Path, required=True)

    p_remote = sub.add_parser("remote", help="Call the hosted Intern Atlas API.")
    remote_sub = p_remote.add_subparsers(dest="remote_command", required=True)

    def add_remote_common(r: argparse.ArgumentParser) -> None:
        r.add_argument("--base-url", default="https://intern-atlas.opendatalab.org.cn/api")
        r.add_argument("--api-key", default=None)

    r_health = remote_sub.add_parser("health")
    add_remote_common(r_health)

    r_context = remote_sub.add_parser("context")
    r_context.add_argument("text")
    add_remote_common(r_context)

    r_evidence = remote_sub.add_parser("evidence")
    r_evidence.add_argument("text")
    r_evidence.add_argument("--max-papers", type=int, default=20)
    r_evidence.add_argument("--max-edges", type=int, default=40)
    r_evidence.add_argument("--mode", choices=["light", "balanced", "deep"], default="balanced")
    r_evidence.add_argument("--depth", type=int, default=None)
    r_evidence.add_argument("--year-from", type=int, default=None)
    r_evidence.add_argument("--year-to", type=int, default=None)
    r_evidence.add_argument("--edge-type", default=None)
    r_evidence.add_argument("--method", default=None)
    add_remote_common(r_evidence)

    r_methods = remote_sub.add_parser("methods")
    r_methods.add_argument("text")
    r_methods.add_argument("--limit", type=int, default=50)
    add_remote_common(r_methods)

    r_edges = remote_sub.add_parser("edges")
    r_edges.add_argument("--paper-id", default=None)
    r_edges.add_argument("--edge-type", default=None)
    r_edges.add_argument("--method", default=None)
    r_edges.add_argument("--year-from", type=int, default=None)
    r_edges.add_argument("--year-to", type=int, default=None)
    r_edges.add_argument("--limit", type=int, default=100)
    add_remote_common(r_edges)

    r_paper = remote_sub.add_parser("paper")
    r_paper.add_argument("paper_id")
    r_paper.add_argument("--depth", type=int, default=1)
    r_paper.add_argument("--limit", type=int, default=100)
    add_remote_common(r_paper)

    for name in ("ideas", "eval"):
        r = remote_sub.add_parser(name)
        r.add_argument("text")
        add_remote_common(r)
        r.add_argument("--use-llm", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "build":
        result = build_from_sources(
            inputs=args.input,
            pdf_dirs=args.pdf_dir,
            out_db=args.out,
            out_json=args.json,
            use_llm=not args.no_llm,
            max_papers=args.max_papers,
            max_pairs=args.max_pairs,
            min_confidence=args.min_confidence,
            max_pdf_pages=args.max_pdf_pages,
            max_text_chars=args.max_text_chars,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "serve":
        import uvicorn

        from .server import create_app

        uvicorn.run(create_app(args.db), host=args.host, port=args.port)
        return 0

    if args.command == "stats":
        conn = connect(args.db, readonly=True)
        try:
            print(json.dumps(graph_stats(conn), indent=2))
        finally:
            conn.close()
        return 0

    if args.command == "remote":
        client = InternAtlasClient(args.base_url, api_key=args.api_key)
        try:
            if args.remote_command == "health":
                data = client.health()
            elif args.remote_command == "context":
                data = client.assist_context(args.text)
            elif args.remote_command == "evidence":
                data = client.evidence_context(
                    args.text,
                    max_papers=args.max_papers,
                    max_edges=args.max_edges,
                    mode=args.mode,
                    depth=args.depth,
                    year_from=args.year_from,
                    year_to=args.year_to,
                    edge_type=args.edge_type,
                    method=args.method,
                )
            elif args.remote_command == "methods":
                data = client.search_methods(args.text, limit=args.limit)
            elif args.remote_command == "edges":
                data = client.evolution_edges(
                    paper_id=args.paper_id,
                    edge_type=args.edge_type,
                    method=args.method,
                    year_from=args.year_from,
                    year_to=args.year_to,
                    limit=args.limit,
                )
            elif args.remote_command == "paper":
                data = client.paper_neighborhood(args.paper_id, depth=args.depth, limit=args.limit)
            elif args.remote_command == "ideas":
                data = client.generate_ideas(args.text, use_llm=args.use_llm)
            elif args.remote_command == "eval":
                data = client.evaluate_idea(args.text, use_llm=args.use_llm)
            else:
                raise AssertionError(args.remote_command)
            print(json.dumps(data, ensure_ascii=False, indent=2))
        finally:
            client.close()
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
