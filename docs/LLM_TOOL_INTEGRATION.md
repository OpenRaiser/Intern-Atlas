# LLM Tool Integration

Intern Atlas is designed to be the evidence and data layer for research agents.
It does not need to generate ideas by itself. Instead, it exposes papers,
method-evolution edges, bottlenecks, mechanisms, and timeline context that an
LLM application can call before generating or evaluating ideas.

The intended flow is:

```text
PDFs or title/abstract files
  -> intern-atlas build
  -> local or hosted Intern Atlas API
  -> LLM tool call retrieves evidence
  -> LLM generates or evaluates ideas grounded in paper IDs
```

## Quick Start

Build a smoke graph:

```bash
intern-atlas build \
  --input examples/evidence_papers.json \
  --out outputs/evidence_graph.db \
  --json outputs/evidence_graph.json \
  --no-llm
```

Start the API:

```bash
intern-atlas serve --db outputs/evidence_graph.db --host 127.0.0.1 --port 8000
```

Fetch an evidence pack:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/evidence/context" \
  -H "Content-Type: application/json" \
  -d '{"query":"efficient attention","max_papers":20,"max_edges":40}'
```

Fetch the machine-readable tool manifest:

```bash
curl "http://127.0.0.1:8000/api/v1/llm/tools"
```

## Core Tool

Use this endpoint as the main LLM tool:

```text
POST /api/v1/evidence/context
```

Request:

```json
{
  "query": "efficient long-context attention",
  "max_papers": 20,
  "max_edges": 40,
  "include_prompt_context": true
}
```

Response fields:

| Field | Meaning |
| --- | --- |
| `papers` | Ranked papers relevant to the query, each with extracted methods. |
| `method_edges` | Evidence edges between newer and older papers. |
| `bottlenecks` | Limitations or gaps associated with older methods. |
| `mechanisms` | How newer papers address those bottlenecks. |
| `timeline` | Older-to-newer paper sequence for idea grounding. |
| `suggested_prompt_context` | Compact text context that can be passed to an LLM. |
| `counts` | Counts for papers, edges, bottlenecks, and mechanisms. |

Edge direction in `method_edges` is citation-style:

```text
source_paper_id -> target_paper_id
newer paper -> older paper
```

For human reasoning, read it as:

```text
older paper -> newer paper
```

## Graph Lookup Tools

Use these when an agent needs targeted graph access instead of a full evidence
pack.

```text
GET /api/v1/methods/search?q=Transformer
GET /api/v1/evolution/edges?method=attention&limit=100
GET /api/v1/papers/{paper_id}/neighborhood?depth=1&limit=100
GET /api/v1/papers/search?q=long-context&limit=20
POST /api/v1/query
```

`/api/v1/llm/tools` returns tool names, methods, paths, descriptions, and JSON
schemas. Use it to generate provider-specific wrappers.

## Provider Integration Pattern

Most LLM tool systems follow the same pattern:

1. Register one function/tool named `intern_atlas_evidence_context`.
2. When the model calls it, your application sends the JSON arguments to
   `POST /api/v1/evidence/context`.
3. Return the JSON evidence pack to the model as the tool result.
4. Ask the model to cite paper IDs from `papers` and `method_edges`.

OpenAI's function calling guide describes tools as JSON-schema-backed functions
that let models access data outside their training data:
https://developers.openai.com/api/docs/guides/function-calling

## Generic Tool Definition

This schema is provider-neutral. Adapt field names to the SDK you use.

```json
{
  "type": "function",
  "name": "intern_atlas_evidence_context",
  "description": "Retrieve papers, methodology evolution edges, bottlenecks, mechanisms, and timeline evidence for a research query.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Research topic, hypothesis, or idea seed."
      },
      "max_papers": {
        "type": "integer",
        "minimum": 1,
        "maximum": 100,
        "default": 20
      },
      "max_edges": {
        "type": "integer",
        "minimum": 0,
        "maximum": 300,
        "default": 40
      },
      "include_prompt_context": {
        "type": "boolean",
        "default": true
      }
    },
    "required": ["query"],
    "additionalProperties": false
  },
  "strict": true
}
```

## Python Adapter

This is the application-side function that a tool call should execute.

```python
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"


def intern_atlas_evidence_context(
    query: str,
    max_papers: int = 20,
    max_edges: int = 40,
    include_prompt_context: bool = True,
) -> dict:
    response = requests.post(
        f"{BASE_URL}/evidence/context",
        json={
            "query": query,
            "max_papers": max_papers,
            "max_edges": max_edges,
            "include_prompt_context": include_prompt_context,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
```

## Prompt Contract

After the tool returns evidence, use a system or developer instruction like:

```text
Use Intern Atlas tool results as the only literature evidence.
When proposing research ideas, cite paper IDs from `papers` or `method_edges`.
Separate evidence-backed claims from speculation.
Do not invent paper titles, venues, metrics, or results.
Prefer ideas that address a listed bottleneck using or recombining a listed mechanism.
```

## Idea Generation Workflow

1. User asks for research ideas.
2. Agent calls `intern_atlas_evidence_context`.
3. Agent summarizes:
   - the method timeline;
   - known bottlenecks;
   - mechanisms that solved earlier bottlenecks;
   - missing combinations or underexplored transfers.
4. Agent proposes ideas and cites supporting paper IDs.
5. Agent optionally calls the graph endpoints again for method-specific checks.

## Idea Evaluation Workflow

1. User provides an idea.
2. Agent extracts key methods and target bottlenecks.
3. Agent calls `intern_atlas_evidence_context` with that idea as the query.
4. Agent checks novelty pressure:
   - Is the idea already represented by an edge?
   - Does it target a real bottleneck in the evidence pack?
   - Does it recombine mechanisms from unrelated lines?
   - Which papers would be baselines?
5. Agent returns a review with evidence IDs and uncertainty notes.

## Deployment Notes

For local use, no authentication is enabled by default. For a public or hosted
deployment, place the FastAPI app behind a gateway that provides:

- HTTPS;
- API keys or OAuth;
- rate limiting;
- request logging;
- corpus access controls;
- a policy for deleting uploaded papers and generated graphs.

Never expose a private paper corpus from a laptop-bound local server to the
public internet without access control.
