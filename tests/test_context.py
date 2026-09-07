from paper_reader.context import ConversationContext
from paper_reader.blocks import PaperDocument, ContentBlock, SemanticChunk, merge_blocks


def make_paper() -> PaperDocument:
    blocks = [
        ContentBlock(type="text", text="1. Introduction", level=1, page_idx=0),
        ContentBlock(type="text", text="Introduction text about the problem.", page_idx=0),
        ContentBlock(type="text", text="2. Methods", level=1, page_idx=0),
        ContentBlock(type="text", text="Methods text about the approach.", page_idx=1),
        ContentBlock(type="text", text="We use a novel dataset called ReposVul.", page_idx=1),
        ContentBlock(type="text", text="2.1 Dataset", level=2, page_idx=1),
        ContentBlock(type="text", text="Dataset details with specific numbers.", page_idx=1),
    ]
    chunks = merge_blocks(blocks)
    return PaperDocument(
        filepath="test.pdf",
        title="Test Paper",
        abstract="This is a test abstract.",
        blocks=blocks,
        chunks=chunks,
    )


def test_context_stores_paper():
    paper = make_paper()
    ctx = ConversationContext(paper)
    assert ctx.paper == paper


def test_context_starts_with_empty_history():
    ctx = ConversationContext(make_paper())
    assert ctx.history == []


def test_add_message_appends_to_history():
    ctx = ConversationContext(make_paper())
    ctx.add_message("user", "Hello")
    ctx.add_message("assistant", "Hi there")
    assert len(ctx.history) == 2
    assert ctx.history[0] == {"role": "user", "content": "Hello"}
    assert ctx.history[1] == {"role": "assistant", "content": "Hi there"}


def test_search_chunks_returns_relevant_results():
    ctx = ConversationContext(make_paper())
    chunks = ctx.search_chunks("dataset ReposVul", top_k=2)
    assert len(chunks) >= 1
    found = " ".join(c.text for c in chunks)
    assert "ReposVul" in found or "dataset" in found.lower()


def test_search_chunks_empty_query():
    ctx = ConversationContext(make_paper())
    chunks = ctx.search_chunks("")
    assert isinstance(chunks, list)


def test_search_chunks_no_chunks():
    paper = PaperDocument(filepath="empty.pdf", blocks=[], chunks=[])
    ctx = ConversationContext(paper)
    chunks = ctx.search_chunks("hello")
    assert chunks == []


def test_search_chunks_embeddings_cached():
    """Chunks get embedding values after ConversationContext init."""
    paper = make_paper()
    ctx = ConversationContext(paper)
    for c in paper.chunks:
        assert c.embedding is not None, f"{c.chunk_id} should have embedding after init"
        assert len(c.embedding) > 0


def test_embeddings_reused_from_cache():
    """Second init reuses embeddings from chunk cache, no re-encode."""
    paper = make_paper()
    # First init encodes and stores embeddings
    ctx1 = ConversationContext(paper)
    emb1 = paper.chunks[0].embedding
    # Second init should reuse cached embeddings
    ctx2 = ConversationContext(paper)
    emb2 = paper.chunks[0].embedding
    assert emb1 == emb2


def test_build_context_returns_text_and_images():
    ctx = ConversationContext(make_paper())
    chunks = ctx.paper.chunks[:2]
    text, images = ctx.build_context(chunks, window=1)
    assert len(text) > 0
    assert isinstance(images, list)


def test_build_context_empty_chunks():
    ctx = ConversationContext(make_paper())
    text, images = ctx.build_context([], window=1)
    assert text == ""
    assert images == []


def test_find_section_exact_match():
    ctx = ConversationContext(make_paper())
    blocks = ctx.find_section("2. Methods")
    assert blocks is not None
    texts = [b.text for b in blocks]
    assert any("Methods text" in t for t in texts)


def test_find_section_partial_match():
    ctx = ConversationContext(make_paper())
    blocks = ctx.find_section("Methods")
    assert blocks is not None
    texts = [b.text for b in blocks]
    assert any("Methods text" in t for t in texts)


def test_find_section_no_match():
    ctx = ConversationContext(make_paper())
    blocks = ctx.find_section("Conclusion")
    assert blocks is None


def test_find_section_by_number():
    ctx = ConversationContext(make_paper())
    blocks = ctx.find_section("2.1")
    assert blocks is not None
    texts = [b.text for b in blocks]
    assert any("Dataset details" in t for t in texts)


def test_find_section_does_not_leak_to_next():
    ctx = ConversationContext(make_paper())
    blocks = ctx.find_section("2. Methods")
    assert blocks is not None
    # Should NOT contain the Introduction text
    all_text = " ".join(b.text for b in blocks)
    assert "Introduction text" not in all_text


def test_get_overview():
    ctx = ConversationContext(make_paper())
    overview = ctx.get_overview()
    assert "Test Paper" in overview
    assert "test abstract" in overview
    assert "1. Introduction" in overview
    assert "2. Methods" in overview
    assert "2.1 Dataset" in overview


def make_flat_level_paper() -> PaperDocument:
    """Mimic MinerU output where every section heading shares one level."""
    blocks = [
        ContentBlock(type="text", text="Flat Paper Title", level=1, page_idx=0),
        ContentBlock(type="text", text="5 Training", level=2, page_idx=0),
        ContentBlock(type="text", text="Training intro text.", page_idx=0),
        ContentBlock(type="text", text="5.1 Hardware", level=2, page_idx=0),
        ContentBlock(type="text", text="Trained on 8 GPUs.", page_idx=0),
        ContentBlock(type="text", text="6 Results", level=2, page_idx=1),
        ContentBlock(type="text", text="Results intro.", page_idx=1),
        ContentBlock(type="text", text="6.1 Machine Translation", level=2, page_idx=1),
        ContentBlock(type="text", text="BLEU 28.4 on EN-DE.", page_idx=1),
        ContentBlock(type="text", text="6.2 Model Variations", level=2, page_idx=1),
        ContentBlock(type="text", text="Smaller models underperform.", page_idx=1),
        ContentBlock(type="text", text="7 Conclusion", level=2, page_idx=1),
        ContentBlock(type="text", text="Conclusion text.", page_idx=1),
    ]
    return PaperDocument(filepath="flat.pdf", title="Flat", blocks=blocks, chunks=[])


def test_find_section_flat_levels_include_subsections():
    """All headings at one level: parent section must still gather subsection bodies."""
    ctx = ConversationContext(make_flat_level_paper())
    blocks = ctx.find_section("6 Results")
    assert blocks is not None
    all_text = " ".join(b.text for b in blocks)
    assert "Results intro." in all_text
    assert "BLEU 28.4" in all_text
    assert "Smaller models" in all_text
    assert "Conclusion text" not in all_text
    assert "Trained on 8 GPUs" not in all_text


def test_find_section_flat_levels_subsection_stays_scoped():
    ctx = ConversationContext(make_flat_level_paper())
    blocks = ctx.find_section("6.1")
    assert blocks is not None
    all_text = " ".join(b.text for b in blocks)
    assert "BLEU 28.4" in all_text
    assert "Smaller models" not in all_text


def test_find_section_heading_only_extends_into_following_blocks():
    """Unnumbered flat parse: a heading-only match extends into later blocks."""
    blocks = [
        ContentBlock(type="text", text="Experiments", level=1, page_idx=0),
        ContentBlock(type="text", text="Setup", level=1, page_idx=0),
        ContentBlock(type="text", text="We train on 8 GPUs with Adam.", page_idx=0),
        ContentBlock(type="text", text="Results", level=1, page_idx=1),
        ContentBlock(type="text", text="We achieve 99 percent accuracy.", page_idx=1),
    ]
    paper = PaperDocument(filepath="x.pdf", title="X", blocks=blocks, chunks=[])
    ctx = ConversationContext(paper)
    found = ctx.find_section("Experiments")
    assert found is not None
    all_text = " ".join(b.text for b in found)
    assert "We train on 8 GPUs" in all_text


def test_find_section_with_body_does_not_extend():
    ctx = ConversationContext(make_paper())
    blocks = ctx.find_section("2.1")
    assert blocks is not None
    # "2.1 Dataset" has a body, so no fallback: nothing past the paper end anyway,
    # and the section must not pull in earlier sections
    all_text = " ".join(b.text for b in blocks)
    assert "Dataset details" in all_text
    assert "Introduction text" not in all_text


def test_context_session_fields_start_empty():
    ctx = ConversationContext(make_paper())
    assert ctx.observations == []
    assert ctx.image_descriptions is None
