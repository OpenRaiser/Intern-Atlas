# Intern Atlas

Intern Atlas is a small toolkit for building a local methodology-evolution graph
from a folder of papers. Give it PDFs or title/abstract files, configure an
OpenAI-compatible chat API, and it writes a SQLite graph that can be queried by
a local FastAPI service.

This repository is intentionally not the Intern Atlas website. It contains the
reusable local builder, local API, and a small client for the hosted Intern Atlas
API.

## What It Builds

The local graph has:

- `papers`: paper nodes from PDFs or metadata files.
- `methods`: normalized method names extracted from each paper.
- `paper_methods`: which papers introduce, use, extend, or compare methods.
- `citations`: method-evolution edges such as `extends`, `improves`,
  `replaces`, `adapts`, `combines`, and `uses_component`.

The output is a SQLite database and, optionally, a JSON export.

## Install

```bash
git clone https://github.com/OpenRaiser/Intern-Atlas.git
cd Intern-Atlas
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configure An LLM

The builder uses an OpenAI-compatible `/chat/completions` endpoint.

```bash
export S4S_LLM_BASE_URL="https://your-openai-compatible-host/v1"
export S4S_LLM_API_KEY="YOUR_API_KEY"
export S4S_LLM_MODELS="gpt-4o-mini"
```

Multiple fallback models are comma-separated:

```bash
export S4S_LLM_MODELS="model-a,model-b,model-c"
```

For a smoke test without any network call, add `--no-llm`. The heuristic mode
is useful for checking input format, but LLM mode gives much better bottlenecks
and mechanisms.

## Build A Graph

TXT input:

```bash
intern-atlas build \
  --input examples/papers.txt \
  --out outputs/local_graph.db \
  --json outputs/local_graph.json
```

PDF input:

```bash
intern-atlas build \
  --pdf-dir ./papers \
  --out outputs/local_graph.db \
  --json outputs/local_graph.json \
  --max-pdf-pages 8
```

Smoke test without LLM:

```bash
intern-atlas build \
  --input examples/papers.txt \
  --out outputs/smoke.db \
  --json outputs/smoke.json \
  --no-llm
```

## Serve The Local API

```bash
intern-atlas serve --db outputs/local_graph.db --host 127.0.0.1 --port 8000
```

Then open:

- `http://127.0.0.1:8000/api/docs`
- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:8000/api/stats`

Example:

```bash
curl "http://127.0.0.1:8000/api/papers/search?q=attention"
curl -X POST "http://127.0.0.1:8000/api/assist/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_nodes":80}'
```

## Use The Hosted Intern Atlas API

The CLI can also call the hosted Intern Atlas API for larger graph evidence,
idea generation, and idea evaluation.

```bash
intern-atlas remote health

intern-atlas remote context "efficient long-context attention"

intern-atlas remote ideas "long-context efficient attention" --use-llm

intern-atlas remote eval \
  "Use FlashAttention and LoRA for parameter-efficient vision transformer tuning."
```

See [docs/API_USAGE.md](docs/API_USAGE.md) for endpoint details and Python
client examples.

## Input Formats

Supported input types:

- PDF directory: `--pdf-dir ./papers`
- TXT file with repeated `Title:`, `Year:`, `Abstract:` blocks
- JSON or JSONL with `paper_id`, `title`, `abstract`, `year`, `authors`, `venue`
- CSV with at least `title,abstract`

See [docs/LOCAL_GRAPH_BUILDER.md](docs/LOCAL_GRAPH_BUILDER.md).

## Security

Do not commit `.env`, API keys, generated SQLite databases, or PDF corpora.
The `.gitignore` excludes those by default.

