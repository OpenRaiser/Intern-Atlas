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
    for name in ("health", "context", "ideas", "eval"):
        r = remote_sub.add_parser(name)
        r.add_argument("text", nargs="?", default="")
        r.add_argument("--base-url", default="https://intern-atlas.opendatalab.org.cn/api")
        r.add_argument("--api-key", default=None)
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

