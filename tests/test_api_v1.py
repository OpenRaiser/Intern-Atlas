from fastapi.testclient import TestClient

from intern_atlas.builder import build_from_sources
from intern_atlas.server import create_app


def build_sample_graph(tmp_path):
    input_path = tmp_path / "papers.txt"
    input_path.write_text(
        """
Title: Attention Is All You Need
Year: 2017
Abstract: We introduce the Transformer attention architecture.

Title: FlashAttention: Fast and Memory-Efficient Exact Attention
Year: 2022
Abstract: FlashAttention improves Transformer attention memory efficiency with tiling.

Title: LoRA: Low-Rank Adaptation of Large Language Models
Year: 2021
Abstract: LoRA adds trainable low-rank adapters for efficient model adaptation.

Title: QLoRA: Efficient Finetuning of Quantized LLMs
Year: 2023
Abstract: QLoRA combines LoRA adapters with quantization for memory efficient finetuning.
""".strip(),
        encoding="utf-8",
    )
    db_path = tmp_path / "graph.db"
    result = build_from_sources(
        inputs=[str(input_path)],
        pdf_dirs=[],
        out_db=db_path,
        use_llm=False,
        max_pairs=20,
    )
    assert result.edges >= 1
    return db_path


def test_v1_evidence_context(tmp_path):
    db_path = build_sample_graph(tmp_path)
    with TestClient(create_app(db_path)) as client:
        response = client.post(
            "/api/v1/evidence/context",
            json={
                "query": "efficient attention",
                "mode": "deep",
                "max_papers": 10,
                "max_edges": 20,
                "depth": 2,
                "method": "attention",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["query"] == "efficient attention"
        assert payload["parameters"]["mode"] == "deep"
        assert payload["parameters"]["depth"] == 2
        assert payload["parameters"]["method"] == "attention"
        assert payload["counts"]["papers"] >= 2
        assert payload["counts"]["method_edges"] >= 1
        assert payload["timeline"]
        assert "Research query: efficient attention" in payload["suggested_prompt_context"]


def test_v1_evidence_year_filter(tmp_path):
    db_path = build_sample_graph(tmp_path)
    with TestClient(create_app(db_path)) as client:
        response = client.post(
            "/api/v1/evidence/context",
            json={
                "query": "efficient attention",
                "mode": "light",
                "year_from": 2020,
                "year_to": 2023,
                "max_papers": 12,
                "max_edges": 18,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["parameters"]["mode"] == "light"
        assert payload["parameters"]["depth"] == 0
        assert all(paper["year"] >= 2020 for paper in payload["papers"])


def test_v1_graph_tools(tmp_path):
    db_path = build_sample_graph(tmp_path)
    with TestClient(create_app(db_path)) as client:
        methods = client.get("/api/v1/methods/search", params={"q": "Transformer"}).json()
        assert any(item["canonical_name"] == "Transformer" for item in methods)

        attention_edges = client.get("/api/v1/evolution/edges", params={"method": "attention"}).json()
        assert attention_edges

        edges = client.get("/api/v1/evolution/edges", params={"method": "transformer"}).json()
        assert edges

        paper_id = edges[0]["source_paper_id"]
        neighborhood = client.get(f"/api/v1/papers/{paper_id}/neighborhood", params={"depth": 1, "limit": 20})
        assert neighborhood.status_code == 200
        assert paper_id in neighborhood.json()["papers"]

        tools = client.get("/api/v1/llm/tools").json()
        tool_names = {tool["name"] for tool in tools["tools"]}
        assert "intern_atlas_evidence_context" in tool_names
        assert "intern_atlas_evolution_edges" in tool_names
        evidence_tool = next(tool for tool in tools["tools"] if tool["name"] == "intern_atlas_evidence_context")
        assert "mode" in evidence_tool["input_schema"]["properties"]
        assert "year_from" in evidence_tool["input_schema"]["properties"]


def test_ui_exposes_real_controls(tmp_path):
    db_path = build_sample_graph(tmp_path)
    with TestClient(create_app(db_path)) as client:
        html = client.get("/").text
        for marker in (
            'id="yearFrom"',
            'id="yearTo"',
            'id="methodFilter"',
            'id="downloadJsonBtn"',
            'id="downloadPapersBtn"',
            'id="downloadEdgesBtn"',
            'id="downloadContextBtn"',
            'data-mode="light"',
            'data-mode="deep"',
            "/api/v1/evidence/context",
        ):
            assert marker in html
