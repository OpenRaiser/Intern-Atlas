# Local Graph Builder

The local builder turns a small paper collection into a method-evolution graph.
It is meant for project-level exploration: papers from a reading list, a lab's
PDF folder, or a survey bibliography.

## Quick Start

```bash
intern-atlas build \
  --input examples/papers.txt \
  --out outputs/local_graph.db \
  --json outputs/local_graph.json
```

Use `--no-llm` to validate inputs without network calls:

```bash
intern-atlas build --input examples/papers.txt --out outputs/smoke.db --no-llm
```

## LLM Configuration

```bash
export S4S_LLM_BASE_URL="https://your-openai-compatible-host/v1"
export S4S_LLM_API_KEY="YOUR_API_KEY"
export S4S_LLM_MODELS="model-a,model-b"
```

The API must implement:

```text
POST /chat/completions
```

with an OpenAI-compatible request and response shape.

## TXT Format

Separate papers with a blank line:

```text
Title: FlashAttention: Fast and Memory-Efficient Exact Attention
Year: 2022
Abstract: Transformers are slow and memory-hungry on long sequences...

Title: LoRA: Low-Rank Adaptation of Large Language Models
Year: 2021
Abstract: We propose low-rank adaptation for efficient fine-tuning...
```

## JSONL Format

One paper per line:

```json
{"paper_id":"p1","title":"FlashAttention","abstract":"...","year":2022,"authors":["Dao"],"venue":"NeurIPS"}
{"paper_id":"p2","title":"LoRA","abstract":"...","year":2021,"authors":["Hu"],"venue":"ICLR"}
```

## CSV Format

Required columns: `title,abstract`.

Recommended columns: `paper_id,year,authors,venue`.

```csv
paper_id,title,abstract,year,venue
p1,FlashAttention,...,2022,NeurIPS
```

## PDF Format

```bash
intern-atlas build --pdf-dir ./papers --out outputs/pdf_graph.db
```

The builder reads the first `--max-pdf-pages` pages from each PDF. The default
is 8 pages. Increase this if the paper collection has long front matter.

## Output Tables

The SQLite output contains:

- `papers`: paper metadata and extracted abstracts.
- `methods`: canonical method nodes.
- `method_aliases`: method surface forms.
- `paper_methods`: paper-method links.
- `citations`: method-evolution edges.

Important edge fields:

- `fine_edge_type`: `extends`, `improves`, `replaces`, `adapts`, `combines`,
  `uses_component`, or `compares`.
- `fine_bottleneck`: the older method's limitation.
- `fine_mechanism`: how the newer paper addresses that limitation.
- `fine_bottleneck_dimension`: dimension such as memory, compute, accuracy,
  scalability, or robustness.
- `fine_confidence`: classifier confidence.

## Quality Boundaries

For a tiny paper set, the graph only describes relationships inside that set.
It does not claim full-field coverage. Use the hosted Intern Atlas API when
you need broad literature evidence.

Heuristic mode is intentionally conservative. Use LLM mode for serious graph
construction, then inspect `local_graph.json` before relying on the result.

