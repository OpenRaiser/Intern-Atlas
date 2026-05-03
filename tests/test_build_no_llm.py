from intern_atlas.builder import build_from_sources


def test_build_no_llm(tmp_path):
    input_path = tmp_path / "papers.txt"
    input_path.write_text(
        """
Title: Attention Is All You Need
Year: 2017
Abstract: We introduce the Transformer.

Title: FlashAttention
Year: 2022
Abstract: FlashAttention improves Transformer attention memory efficiency.
""".strip(),
        encoding="utf-8",
    )
    db_path = tmp_path / "graph.db"
    result = build_from_sources(
        inputs=[str(input_path)],
        pdf_dirs=[],
        out_db=db_path,
        use_llm=False,
        max_pairs=10,
    )
    assert result.papers == 2
    assert result.methods >= 1
    assert result.edges >= 1

