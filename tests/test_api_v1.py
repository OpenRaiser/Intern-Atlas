from fastapi.testclient import TestClient

import intern_atlas.server as server_module
from intern_atlas.builder import build_from_sources
from intern_atlas.remote import InternAtlasClient, normalize_hosted_base_url
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


def test_v1_evidence_deep_allows_explicit_depth(tmp_path):
    db_path = build_sample_graph(tmp_path)
    with TestClient(create_app(db_path)) as client:
        response = client.post(
            "/api/v1/evidence/context",
            json={
                "query": "efficient attention",
                "mode": "deep",
                "depth": 4,
                "max_papers": 100,
                "max_edges": 300,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["parameters"]["mode"] == "deep"
        assert payload["parameters"]["depth"] == 4
        assert payload["parameters"]["max_papers"] == 100
        assert payload["parameters"]["max_edges"] == 300


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

        missing = client.get("/api/v1/papers/not-a-real-paper/neighborhood", params={"depth": 1, "limit": 20})
        assert missing.status_code == 404

        tools = client.get("/api/v1/llm/tools").json()
        tool_names = {tool["name"] for tool in tools["tools"]}
        assert "intern_atlas_evidence_context" in tool_names
        assert "intern_atlas_hosted_evidence_context" in tool_names
        assert "intern_atlas_hosted_query" in tool_names
        assert "intern_atlas_hosted_evolution_chain" in tool_names
        assert "intern_atlas_evolution_edges" in tool_names
        evidence_tool = next(tool for tool in tools["tools"] if tool["name"] == "intern_atlas_evidence_context")
        assert "mode" in evidence_tool["input_schema"]["properties"]
        assert "year_from" in evidence_tool["input_schema"]["properties"]


def test_v1_remote_proxy_uses_hosted_client(tmp_path, monkeypatch):
    db_path = build_sample_graph(tmp_path)

    class FakeClient:
        def __init__(self, base_url=None, *, api_key=None):
            self.base_url = base_url
            self.api_key = api_key

        def close(self):
            pass

        def health(self):
            return {"status": "ok", "base_url": self.base_url, "has_key": bool(self.api_key)}

        def stats(self):
            return {"total_papers": 123}

        def get_paper(self, paper_id):
            return {"paper_id": paper_id, "title": "Remote Paper"}

        def search_papers(self, query, *, limit=30):
            return [{"paper_id": "p1", "title": query, "limit": limit}]

        def unified_search(self, query, *, search_type="auto", limit=20, include_subgraph=False):
            return {
                "papers": [{"paper_id": "p1", "title": query}],
                "search_type_used": search_type,
                "total_results": 1,
                "subgraph": {"papers": {}, "methods": {}, "edges": []} if include_subgraph else None,
            }

        def query_subgraph(self, query, *, max_nodes=30):
            return {"papers": {"p1": {"paper_id": "p1", "title": query}}, "methods": {}, "edges": []}

        def evidence_context(self, query, **kwargs):
            return {
                "query": query,
                "papers": [],
                "method_edges": [],
                "bottlenecks": [],
                "mechanisms": [],
                "timeline": [],
                "suggested_prompt_context": "",
                "counts": {"papers": 0, "method_edges": 0, "bottlenecks": 0, "mechanisms": 0},
                "parameters": kwargs,
            }

        def paper_neighborhood(self, paper_id, *, depth=1, limit=100):
            return {"papers": {paper_id: {"paper_id": paper_id}}, "methods": {}, "edges": [], "center_id": paper_id}

        def paper_branch(self, paper_id, *, depth=2, limit=100):
            return {"papers": {paper_id: {"paper_id": paper_id}}, "methods": {}, "edges": [], "center_id": paper_id}

        def paper_ancestry(self, paper_id, *, depth=2, limit=100):
            return {"papers": {paper_id: {"paper_id": paper_id}}, "methods": {}, "edges": [], "center_id": paper_id}

        def find_path(self, from_id, to_id, *, direction="evolution", max_depth=10):
            return [{"source_paper_id": from_id, "target_paper_id": to_id, "direction": direction}]

        def evolution_chain(self, domain, *, max_chains=5, max_depth=8, beam_width=3, strategy="mcts"):
            return {"domain": domain, "nodes": [], "edges": [], "chains": [], "strategy": strategy}

    monkeypatch.setattr(server_module, "InternAtlasClient", FakeClient)
    with TestClient(server_module.create_app(db_path)) as client:
        health = client.post(
            "/api/v1/remote/health",
            json={"base_url": "https://example.test/api", "api_key": "secret"},
        )
        assert health.status_code == 200
        assert health.json()["source"] == "hosted"
        assert health.json()["base_url"] == "https://example.test/api"
        assert health.json()["has_key"] is True

        evidence = client.post(
            "/api/v1/remote/evidence/context",
            json={"query": "efficient attention", "mode": "deep", "depth": 4},
        )
        assert evidence.status_code == 200
        assert evidence.json()["source"] == "hosted"
        assert evidence.json()["parameters"]["mode"] == "deep"
        assert evidence.json()["parameters"]["depth"] == 4

        search = client.post(
            "/api/v1/remote/search",
            json={"query": "attention", "search_type": "direction", "include_subgraph": True},
        )
        assert search.status_code == 200
        assert search.json()["source"] == "hosted"
        assert search.json()["search_type_used"] == "direction"
        assert search.json()["subgraph"] is not None

        query = client.post("/api/v1/remote/query", json={"query": "attention", "max_nodes": 20})
        assert query.status_code == 200
        assert query.json()["source"] == "hosted"
        assert "p1" in query.json()["papers"]

        detail = client.post("/api/v1/remote/papers/detail", json={"paper_id": "p1"})
        assert detail.status_code == 200
        assert detail.json()["paper_id"] == "p1"

        path = client.post("/api/v1/remote/path", json={"from_id": "p2", "to_id": "p1", "direction": "both"})
        assert path.status_code == 200
        assert path.json()[0]["direction"] == "both"

        chain = client.post(
            "/api/v1/remote/visualization/evolution-chain",
            json={"domain": "attention", "strategy": "beam"},
        )
        assert chain.status_code == 200
        assert chain.json()["source"] == "hosted"
        assert chain.json()["domain"] == "attention"

        bad_url = client.post(
            "/api/v1/remote/health",
            json={"base_url": "file:///tmp/not-an-api"},
        )
        assert bad_url.status_code == 400


def test_hosted_base_url_accepts_site_root():
    assert normalize_hosted_base_url("https://intern-atlas.opendatalab.org.cn/") == (
        "https://intern-atlas.opendatalab.org.cn/api"
    )
    assert normalize_hosted_base_url("https://intern-atlas.opendatalab.org.cn/api") == (
        "https://intern-atlas.opendatalab.org.cn/api"
    )
    client = InternAtlasClient("https://intern-atlas.opendatalab.org.cn/")
    try:
        assert client.base_url == "https://intern-atlas.opendatalab.org.cn/api"
    finally:
        client.close()


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
            'id="filterBar"',
            'id="loadingShade"',
            'id="remoteSettings"',
            'id="remoteBaseUrl"',
            'id="remoteApiKey"',
            'id="remoteHealthBtn"',
            'data-source="local"',
            'data-source="hosted"',
            "/api/v1/remote/evidence/context",
            "/api/v1/remote/papers/neighborhood",
            "function clearWorkspace",
            "function currentPromptContext",
            'data-mode="light"',
            'data-mode="deep"',
            "/api/v1/evidence/context",
        ):
            assert marker in html
