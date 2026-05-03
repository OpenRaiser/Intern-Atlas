# Intern Atlas API Usage

This document describes how to use the APIs provided by this repository.

There are two different API surfaces:

1. **Local API**: starts from a SQLite graph you build with `intern-atlas build`.
2. **Hosted Intern Atlas client**: calls a hosted Intern Atlas service for broader graph evidence, idea generation, and idea evaluation.

The local API is included in this repository. The hosted API is optional and is accessed through the `intern-atlas remote ...` CLI or `InternAtlasClient`.

## Quick Start

Build a graph from the example paper metadata:

```bash
intern-atlas build \
  --input examples/papers.txt \
  --out outputs/local_graph.db \
  --json outputs/local_graph.json \
  --no-llm
```

Start the local API and UI:

```bash
intern-atlas serve \
  --db outputs/local_graph.db \
  --host 127.0.0.1 \
  --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

OpenAPI docs:

```text
http://127.0.0.1:8000/api/docs
```

Use a base URL variable for curl examples:

```bash
BASE=http://127.0.0.1:8000/api
```

## Local API Concepts

The local API reads a SQLite database produced by `intern-atlas build`.

Core objects:

- **Paper**: one paper node.
- **Method**: extracted method entity, such as `Transformer`, `LoRA`, or `FlashAttention`.
- **Paper-method link**: whether a paper introduces, uses, extends, or compares a method.
- **Evolution edge**: method-level relation between two papers, stored in the `citations` table.
- **Subgraph**: a bounded set of papers plus edges between them.

Raw edge direction:

```text
source_id -> target_id
newer paper -> older paper
```

Example: if FlashAttention extends Transformer, the edge is:

```text
FlashAttention -> Attention Is All You Need
```

This is a citation-style direction. When presenting evolution to humans, read it as older to newer:

```text
Attention Is All You Need -> FlashAttention
```

## Local UI

```text
GET /
```

Browser workspace for the local graph.

Features:

- shows graph statistics;
- searches papers or methods;
- opens a local paper neighborhood;
- renders a compact SVG graph;
- lists bottlenecks and mechanisms;
- calls `/api/assist/context` and copies prompt context when clipboard permission is available.

Example:

```bash
open http://127.0.0.1:8000/
```

On headless servers, open the URL through SSH port forwarding:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
```

## Versioned Agent API

New integrations should prefer `/api/v1/...` endpoints. The older `/api/...`
endpoints remain available for compatibility.

Core v1 endpoints:

```text
POST /api/v1/evidence/context
GET /api/v1/methods/search
GET /api/v1/evolution/edges
GET /api/v1/papers/{paper_id}/neighborhood
GET /api/v1/papers/search
POST /api/v1/query
GET /api/v1/llm/tools
```

The most important endpoint for LLM and agent systems is:

```text
POST /api/v1/evidence/context
```

It returns an evidence pack containing papers, method-evolution edges,
bottlenecks, mechanisms, a timeline, and prompt-ready context.

Request:

```json
{
  "query": "efficient long-context attention",
  "max_papers": 20,
  "max_edges": 40,
  "include_prompt_context": true
}
```

Response shape:

```json
{
  "query": "efficient long-context attention",
  "papers": [],
  "method_edges": [],
  "bottlenecks": [],
  "mechanisms": [],
  "timeline": [],
  "suggested_prompt_context": "Use this Intern Atlas evidence pack...",
  "counts": {
    "papers": 0,
    "method_edges": 0,
    "bottlenecks": 0,
    "mechanisms": 0
  }
}
```

Example:

```bash
curl -X POST "$BASE/v1/evidence/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_papers":20,"max_edges":40}'
```

Fetch tool metadata for an LLM application:

```bash
curl "$BASE/v1/llm/tools"
```

See [LLM_TOOL_INTEGRATION.md](LLM_TOOL_INTEGRATION.md) for provider-facing
integration patterns.

## Health

```text
GET /api/health
```

Checks that the API process can read the SQLite database.

Example:

```bash
curl "$BASE/health"
```

Response:

```json
{
  "status": "ok",
  "database": {
    "file": "local_graph.db",
    "connected": true
  }
}
```

## Manifest

```text
GET /api/manifest
```

Returns service metadata and the main endpoint list.

Example:

```bash
curl "$BASE/manifest"
```

Response:

```json
{
  "name": "Intern Atlas Local API",
  "version": "0.1.0",
  "database": "local_graph.db",
  "docs": "/api/docs",
  "endpoints": [
    "GET /api/health",
    "GET /api/stats",
    "GET /api/papers/search?q=...",
    "GET /api/papers/{paper_id}",
    "GET /api/edges",
    "POST /api/query",
    "POST /api/assist/context"
  ]
}
```

## Stats

```text
GET /api/stats
```

Returns counts for the local graph.

Example:

```bash
curl "$BASE/stats"
```

Response:

```json
{
  "papers": 3,
  "methods": 5,
  "edges": 1
}
```

Fields:

- `papers`: number of paper nodes.
- `methods`: number of method entities.
- `edges`: number of non-background evolution edges.

## List Papers

```text
GET /api/papers
```

Lists paper nodes.

Query parameters:

| Name | Type | Default | Max | Description |
| --- | --- | ---: | ---: | --- |
| `offset` | integer | `0` | none | Pagination offset. |
| `limit` | integer | `50` | `200` | Number of papers returned. |

Example:

```bash
curl "$BASE/papers?offset=0&limit=20"
```

Response item:

```json
{
  "paper_id": "local_attention_is_all_you_need_6843568f00",
  "title": "Attention Is All You Need",
  "abstract": "We introduce the Transformer...",
  "year": 2017,
  "authors": [],
  "venue": "NeurIPS",
  "status": "full",
  "paper_type": "research"
}
```

## Search Papers

```text
GET /api/papers/search
```

Searches paper `title` and `abstract` using SQLite `LIKE`.

Query parameters:

| Name | Type | Default | Max | Description |
| --- | --- | ---: | ---: | --- |
| `q` | string | `""` | 200 chars | Search text. |
| `limit` | integer | `20` | `50` | Number of papers returned. |

Example:

```bash
curl "$BASE/papers/search?q=attention&limit=10"
```

Python:

```python
import requests

papers = requests.get(
    "http://127.0.0.1:8000/api/papers/search",
    params={"q": "attention", "limit": 10},
    timeout=30,
).json()
```

## Get One Paper

```text
GET /api/papers/{paper_id}
```

Returns one paper plus its method links.

Example:

```bash
curl "$BASE/papers/local_attention_is_all_you_need_6843568f00"
```

Response:

```json
{
  "paper_id": "local_attention_is_all_you_need_6843568f00",
  "title": "Attention Is All You Need",
  "abstract": "We introduce the Transformer...",
  "year": 2017,
  "authors": [],
  "venue": "NeurIPS",
  "status": "full",
  "paper_type": "research",
  "methods": [
    {
      "method_id": "m_transformer_9236e026",
      "canonical_name": "Transformer",
      "relationship": "introduces",
      "confidence": 0.8
    }
  ]
}
```

Errors:

- `404`: paper id does not exist in the local graph.

## Search Methods

```text
GET /api/methods
```

Searches method names and descriptions.

Query parameters:

| Name | Type | Default | Max | Description |
| --- | --- | ---: | ---: | --- |
| `q` | string | `""` | 200 chars | Search text. |
| `offset` | integer | `0` | none | Pagination offset. |
| `limit` | integer | `50` | `200` | Number of methods returned. |

Example:

```bash
curl "$BASE/methods?q=Transformer&limit=20"
```

Response item:

```json
{
  "method_id": "m_transformer_9236e026",
  "canonical_name": "Transformer",
  "description": "",
  "origin_paper_id": "local_attention_is_all_you_need_6843568f00"
}
```

## List Evolution Edges

```text
GET /api/edges
```

Returns non-background methodology edges.

Query parameters:

| Name | Type | Default | Max | Description |
| --- | --- | ---: | ---: | --- |
| `paper_id` | string | none | none | If set, returns edges touching that paper. |
| `edge_type` | string | none | none | Filter by edge type. |
| `method` | string | none | 200 chars | Filter by source or target method text. |
| `offset` | integer | `0` | none | Pagination offset. |
| `limit` | integer | `100` | `1000` | Number of edges returned. |

Supported `edge_type` values:

- `extends`: newer work generalizes or builds on older work.
- `improves`: newer work improves a metric or capability.
- `replaces`: newer work substitutes a prior mechanism.
- `adapts`: newer work transfers a method to a new domain.
- `combines`: newer work combines multiple method lines.
- `uses_component`: newer work uses a component from older work.
- `compares`: newer work uses older work as a comparison baseline.

Example:

```bash
curl "$BASE/edges?edge_type=extends&limit=20"
curl "$BASE/edges?paper_id=local_attention_is_all_you_need_6843568f00"
curl "$BASE/v1/evolution/edges?method=transformer&limit=20"
```

Response item:

```json
{
  "source_paper_id": "local_flashattention_fast_and_memory_efficient_exact_attention_wit_70736e063f",
  "target_paper_id": "local_attention_is_all_you_need_6843568f00",
  "edge_type": "extends",
  "bottleneck": "Potential methodological continuity inferred from shared terminology.",
  "mechanism": "Heuristic relation. Rebuild with an LLM for evidence-grounded bottlenecks and mechanisms.",
  "dimension": "method_continuity",
  "confidence": 0.61,
  "source_method": "transformer",
  "target_method": "transformer"
}
```

## Paper Neighborhood

```text
GET /api/papers/{paper_id}/neighborhood
```

Returns a bounded subgraph around one paper.

Query parameters:

| Name | Type | Default | Max | Description |
| --- | --- | ---: | ---: | --- |
| `depth` | integer | `1` | `4` | BFS depth over non-background edges. |
| `limit` | integer | `100` | `300` | Maximum paper nodes returned. |

Example:

```bash
curl "$BASE/papers/local_attention_is_all_you_need_6843568f00/neighborhood?depth=1&limit=80"
```

Response:

```json
{
  "papers": {
    "PAPER_ID": {
      "paper_id": "PAPER_ID",
      "title": "Paper title",
      "abstract": "...",
      "year": 2022,
      "authors": [],
      "venue": "",
      "status": "full",
      "paper_type": "research"
    }
  },
  "edges": [
    {
      "source_paper_id": "NEWER_ID",
      "target_paper_id": "OLDER_ID",
      "edge_type": "extends",
      "bottleneck": "...",
      "mechanism": "...",
      "dimension": "...",
      "confidence": 0.9
    }
  ],
  "center_id": "PAPER_ID"
}
```

## Natural Language Query To Subgraph

```text
POST /api/query
```

Searches matching paper titles/abstracts, expands one hop over edges, and returns a subgraph.

Request body:

```json
{
  "query": "efficient attention",
  "max_nodes": 80
}
```

Fields:

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | yes | Search phrase. |
| `max_nodes` | integer | no | Maximum papers in the returned subgraph. Range: 1-300. Default: 60. |

Example:

```bash
curl -X POST "$BASE/query" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_nodes":80}'
```

Response shape is the same as `/api/papers/{paper_id}/neighborhood`.

## Assist Context For Your Own LLM

```text
POST /api/assist/context
```

Returns papers, edges, and a compact text context block that can be pasted into your own LLM workflow.

Request body:

```json
{
  "query": "efficient attention",
  "max_nodes": 80
}
```

Example:

```bash
curl -X POST "$BASE/assist/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_nodes":80}'
```

Response:

```json
{
  "query": "efficient attention",
  "papers": [
    {
      "paper_id": "local_attention_is_all_you_need_6843568f00",
      "title": "Attention Is All You Need",
      "year": 2017
    }
  ],
  "evolution_edges": [
    {
      "source_paper_id": "local_flashattention_fast_and_memory_efficient_exact_attention_wit_70736e063f",
      "target_paper_id": "local_attention_is_all_you_need_6843568f00",
      "edge_type": "extends"
    }
  ],
  "suggested_prompt_context": "Research query: efficient attention\n\nRelevant papers:\n..."
}
```

Typical downstream use:

```python
import requests
from openai import OpenAI

ctx = requests.post(
    "http://127.0.0.1:8000/api/assist/context",
    json={"query": "efficient attention", "max_nodes": 80},
    timeout=60,
).json()

client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {
            "role": "system",
            "content": "Use only the supplied graph evidence. Do not invent paper titles.",
        },
        {
            "role": "user",
            "content": ctx["suggested_prompt_context"] + "\n\nPropose two research directions.",
        },
    ],
)
print(response.choices[0].message.content)
```

## Python Local API Examples

### Search And Expand

```python
import requests

BASE = "http://127.0.0.1:8000/api"

papers = requests.get(
    f"{BASE}/papers/search",
    params={"q": "attention", "limit": 10},
    timeout=30,
).json()

first = papers[0]
subgraph = requests.get(
    f"{BASE}/papers/{first['paper_id']}/neighborhood",
    params={"depth": 1, "limit": 80},
    timeout=30,
).json()

print(first["title"])
print(len(subgraph["papers"]), len(subgraph["edges"]))
```

### Query Context

```python
import requests

ctx = requests.post(
    "http://127.0.0.1:8000/api/assist/context",
    json={"query": "long-context attention", "max_nodes": 100},
    timeout=60,
).json()

print(ctx["suggested_prompt_context"])
```

## Hosted Intern Atlas API

The hosted API is useful when your local graph is too small and you need broader literature evidence.

The CLI exposes these hosted calls:

```bash
intern-atlas remote health
intern-atlas remote evidence "efficient long-context attention"
intern-atlas remote context "efficient long-context attention"
intern-atlas remote methods "Transformer"
intern-atlas remote edges --method attention --limit 20
intern-atlas remote ideas "efficient long-context attention" --use-llm
intern-atlas remote eval "Use FlashAttention and LoRA for efficient ViT tuning."
```

The default hosted base URL is:

```text
https://intern-atlas.opendatalab.org.cn/api
```

Override it:

```bash
intern-atlas remote context \
  "efficient long-context attention" \
  --base-url "https://your-host.example.com/api"
```

If your hosted deployment requires an API key:

```bash
intern-atlas remote ideas \
  "efficient long-context attention" \
  --api-key "$INTERN_ATLAS_API_KEY" \
  --use-llm
```

Fetch a v1 evidence pack from a hosted service:

```bash
intern-atlas remote evidence \
  "efficient long-context attention" \
  --max-papers 30 \
  --max-edges 80 \
  --api-key "$INTERN_ATLAS_API_KEY"
```

## Hosted Python Client

```python
from intern_atlas.remote import InternAtlasClient

client = InternAtlasClient()
try:
    health = client.health()
    print(health)

    evidence = client.evidence_context(
        "efficient long-context attention",
        max_papers=20,
        max_edges=40,
    )
    print(evidence["suggested_prompt_context"])

    methods = client.search_methods("Transformer", limit=20)
    print(methods)

    edges = client.evolution_edges(method="attention", limit=20)
    print(edges)

    ctx = client.assist_context(
        "efficient long-context attention",
        budget="balanced",
        use_mcts=True,
        token_budget=6000,
    )
    print(ctx["suggested_prompt_context"])

    ideas = client.generate_ideas(
        "efficient long-context attention",
        use_llm=False,
        evidence_budget="balanced",
    )
    print(ideas)

    review = client.evaluate_idea(
        "Use FlashAttention and LoRA for parameter-efficient vision transformer tuning.",
        use_llm=False,
    )
    print(review)
finally:
    client.close()
```

With API key:

```python
client = InternAtlasClient(api_key="YOUR_ATLAS_API_KEY")
```

With a custom base URL:

```python
client = InternAtlasClient(
    base_url="https://your-host.example.com/api",
    api_key="YOUR_ATLAS_API_KEY",
)
```

## Hosted Client Method Reference

### `health()`

Calls:

```text
GET /api/health
```

Use it for monitoring and connectivity checks.

### `evidence_context(query, max_papers=20, max_edges=40, include_prompt_context=True)`

Calls:

```text
POST /api/v1/evidence/context
```

Arguments:

- `query`: research topic, idea seed, or evaluation target.
- `max_papers`: maximum relevant papers returned.
- `max_edges`: maximum methodology edges returned.
- `include_prompt_context`: whether to include prompt-ready context text.

### `search_methods(q, limit=50, offset=0)`

Calls:

```text
GET /api/v1/methods/search
```

Arguments:

- `q`: method name or partial method text.
- `limit`: maximum methods returned.
- `offset`: pagination offset.

### `evolution_edges(paper_id=None, edge_type=None, method=None, limit=100, offset=0)`

Calls:

```text
GET /api/v1/evolution/edges
```

Arguments:

- `paper_id`: optional paper filter.
- `edge_type`: optional edge-type filter.
- `method`: optional source or target method filter.
- `limit`: maximum edges returned.
- `offset`: pagination offset.

### `paper_neighborhood(paper_id, depth=1, limit=100)`

Calls:

```text
GET /api/v1/papers/{paper_id}/neighborhood
```

Arguments:

- `paper_id`: local paper id.
- `depth`: graph search depth.
- `limit`: maximum paper nodes returned.

### `assist_context(query, budget="balanced", use_mcts=True, token_budget=6000)`

Calls:

```text
POST /api/assist/context
```

Arguments:

- `query`: research direction.
- `budget`: `light`, `balanced`, or `deep`.
- `use_mcts`: whether to request chain search with MCTS when supported by the server.
- `token_budget`: approximate prompt context budget.

### `generate_ideas(query, use_llm=False, evidence_budget="balanced")`

Calls:

```text
POST /api/ideas
```

Arguments:

- `query`: research direction.
- `use_llm`: ask the hosted service to use its configured LLM.
- `evidence_budget`: `light`, `balanced`, or `deep`.

### `evaluate_idea(idea, use_llm=False)`

Calls:

```text
POST /api/eval
```

Arguments:

- `idea`: research idea text.
- `use_llm`: ask the hosted service to add LLM qualitative review when supported.

## Error Handling

Local API:

- `404`: requested paper was not found.
- `422`: request validation failed, usually a missing `query` or invalid `limit`.
- `500`: database or server error.

Hosted API:

- `401` or `403`: missing, invalid, or under-scoped API key.
- `429`: rate limit.
- `5xx`: hosted service unavailable or upstream LLM failed.

Python pattern:

```python
import httpx

try:
    res = httpx.post(
        "http://127.0.0.1:8000/api/query",
        json={"query": "attention", "max_nodes": 80},
        timeout=60,
    )
    res.raise_for_status()
except httpx.HTTPStatusError as exc:
    print("API error:", exc.response.status_code, exc.response.text)
except httpx.RequestError as exc:
    print("Network error:", exc)
```

## Authentication And Secrets

The local API does not require authentication by default because it is meant to run on your own machine.

The hosted client supports bearer-token auth:

```python
client = InternAtlasClient(api_key="YOUR_ATLAS_API_KEY")
```

Do not commit secrets.

Recommended shell pattern:

```bash
export INTERN_ATLAS_API_KEY="..."
intern-atlas remote context "efficient attention" --api-key "$INTERN_ATLAS_API_KEY"
```

Repository `.gitignore` excludes `.env`, generated SQLite databases, and paper corpora.

## Common Workflows

### Build Then Inspect Locally

```bash
intern-atlas build \
  --pdf-dir ./papers \
  --out outputs/my_graph.db \
  --json outputs/my_graph.json

intern-atlas serve --db outputs/my_graph.db
```

Open:

```text
http://127.0.0.1:8000/
```

### Build Without LLM For Input Validation

```bash
intern-atlas build \
  --input examples/papers.txt \
  --out outputs/smoke.db \
  --no-llm

intern-atlas stats --db outputs/smoke.db
```

### Use Local Graph Evidence In Another LLM

```bash
curl -X POST "$BASE/assist/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_nodes":80}' \
  > context.json
```

Then pass `suggested_prompt_context` to your own model.

### Use Hosted Graph Evidence Before Local Graph Exists

```bash
intern-atlas remote context "efficient long-context attention"
```

This is useful before you have enough local papers for a meaningful graph.

## Limitations

Local API limitations:

- Search is simple SQLite `LIKE`, not full semantic retrieval.
- Heuristic graphs are intentionally conservative and may miss true relationships.
- LLM-built graphs depend on the quality of the configured model and paper text extraction.
- A local graph only covers the papers you provide.

Use the hosted API when you need large-scale graph context.
