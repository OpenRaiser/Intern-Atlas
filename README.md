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

Then open the local graph workspace:

- `http://127.0.0.1:8000/`

API docs and health checks:

- `http://127.0.0.1:8000/api/docs`
- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:8000/api/stats`

Example:

```bash
curl "http://127.0.0.1:8000/api/papers/search?q=attention"
curl "http://127.0.0.1:8000/api/methods?q=Transformer"
curl -X POST "http://127.0.0.1:8000/api/v1/evidence/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","mode":"deep","year_from":2020,"max_papers":40,"max_edges":80}'
curl -X POST "http://127.0.0.1:8000/api/assist/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_nodes":80}'
```

For LLM and agent integrations, prefer the versioned API:

- `POST /api/v1/evidence/context`
- `GET /api/v1/methods/search`
- `GET /api/v1/evolution/edges`
- `GET /api/v1/papers/{paper_id}/neighborhood`
- `GET /api/v1/llm/tools`

See [docs/LLM_TOOL_INTEGRATION.md](docs/LLM_TOOL_INTEGRATION.md).

The browser workspace exposes the same evidence parameters: retrieval mode,
year range, edge type, method filter, graph depth, paper cap, and edge cap. It
also downloads the current evidence view as JSON, paper CSV, edge CSV, or
Markdown prompt context.

The workspace can use either the local SQLite graph or a hosted Intern Atlas API.
Choose `Hosted API` in the sidebar, set the hosted base URL and optional API
key, then run the same evidence search. The browser calls the local FastAPI
proxy at `/api/v1/remote/...`, so local frontends do not need to fight browser
CORS rules.

## Use The Hosted Intern Atlas API

The CLI can also call the hosted Intern Atlas API for larger graph evidence,
idea generation, and idea evaluation.

```bash
intern-atlas remote health

intern-atlas remote evidence "efficient long-context attention"

intern-atlas remote context "efficient long-context attention"

intern-atlas remote methods "Transformer"

intern-atlas remote edges --method attention --limit 20

intern-atlas remote ideas "long-context efficient attention" --use-llm

intern-atlas remote eval \
  "Use FlashAttention and LoRA for parameter-efficient vision transformer tuning."
```

Hosted defaults can be configured once:

```bash
export INTERN_ATLAS_REMOTE_BASE_URL="https://your-host.example.com/api"
export INTERN_ATLAS_API_KEY="YOUR_ATLAS_API_KEY"
```

You can also use the public site root as the base URL; the client normalizes it
to the API root automatically:

```bash
export INTERN_ATLAS_REMOTE_BASE_URL="https://intern-atlas.opendatalab.org.cn/"
```

If the public demo endpoint returns an upstream error, use your own deployed
base URL with the environment variable above or `--base-url`.

The local server also exposes hosted proxy endpoints:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/remote/evidence/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","mode":"deep","base_url":"https://intern-atlas.opendatalab.org.cn/"}'
```

For direct website graph data from a customer laptop:

```bash
intern-atlas remote search "FlashAttention" --include-subgraph \
  --base-url "https://intern-atlas.opendatalab.org.cn/"

intern-atlas remote query "efficient attention" --max-nodes 80 \
  --base-url "https://intern-atlas.opendatalab.org.cn/"

intern-atlas remote chain "attention" --max-chains 5 \
  --base-url "https://intern-atlas.opendatalab.org.cn/"
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
