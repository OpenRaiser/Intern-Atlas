# API Usage

Intern Atlas has two API modes:

1. Local API: served from a SQLite graph you build yourself.
2. Hosted API client: calls the public Intern Atlas graph service.

## Local API

Start a local server:

```bash
intern-atlas serve --db outputs/local_graph.db --host 127.0.0.1 --port 8000
```

Browser UI:

```text
http://127.0.0.1:8000/
```

The UI lets you search papers/methods, inspect local evolution edges, open a
paper neighborhood, and copy graph context for your own LLM workflow.

OpenAPI docs:

```text
http://127.0.0.1:8000/api/docs
```

### Health

```bash
curl http://127.0.0.1:8000/api/health
```

### Stats

```bash
curl http://127.0.0.1:8000/api/stats
```

Response:

```json
{"papers": 3, "methods": 5, "edges": 2}
```

### Search Papers

```bash
curl "http://127.0.0.1:8000/api/papers/search?q=attention&limit=10"
```

### Get One Paper

```bash
curl "http://127.0.0.1:8000/api/papers/local_flashattention_xxx"
```

### List Edges

```bash
curl "http://127.0.0.1:8000/api/edges?edge_type=improves&limit=20"
```

### Search Methods

```bash
curl "http://127.0.0.1:8000/api/methods?q=Transformer&limit=20"
```

### Neighborhood Subgraph

```bash
curl "http://127.0.0.1:8000/api/papers/PAPER_ID/neighborhood?depth=1&limit=80"
```

### Query Subgraph

```bash
curl -X POST "http://127.0.0.1:8000/api/query" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_nodes":80}'
```

### Context For Your Own LLM

```bash
curl -X POST "http://127.0.0.1:8000/api/assist/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_nodes":80}'
```

The response includes:

- `papers`: relevant local papers.
- `evolution_edges`: local method-evolution edges.
- `suggested_prompt_context`: compact text you can put into another LLM prompt.

## Hosted API Client

The hosted service is useful when your local paper set is too small and you
want broad graph evidence.

CLI:

```bash
intern-atlas remote health
intern-atlas remote context "efficient long-context attention"
intern-atlas remote ideas "efficient long-context attention" --use-llm
intern-atlas remote eval "Use FlashAttention and LoRA for efficient ViT tuning."
```

Python:

```python
from intern_atlas.remote import InternAtlasClient

client = InternAtlasClient()
try:
    ctx = client.assist_context(
        "efficient long-context attention",
        budget="balanced",
        use_mcts=True,
        token_budget=6000,
    )
    print(ctx["suggested_prompt_context"])
finally:
    client.close()
```

If your hosted deployment requires an API key:

```python
client = InternAtlasClient(api_key="YOUR_ATLAS_API_KEY")
```

Do not commit API keys. Put them in environment variables or a secret manager.
