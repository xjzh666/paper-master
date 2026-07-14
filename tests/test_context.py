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
