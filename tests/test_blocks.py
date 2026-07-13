# tests/test_blocks.py
from paper_reader.blocks import (
    ContentBlock, SemanticChunk, PaperDocument,
    estimate_tokens, merge_blocks,
)


class TestContentBlock:
    def test_default_values(self):
        b = ContentBlock(type="text", text="hello")
        assert b.type == "text"
        assert b.text == "hello"
        assert b.level == 0
        assert b.image_path is None
        assert b.image_bytes is None
        assert b.children == []

    def test_to_dict_and_from_dict_roundtrip(self):
        b = ContentBlock(
            type="image", text="Figure 1", level=0,
            page_idx=3, bbox=(10, 20, 100, 200),
            image_path="images/fig.jpg",
        )
        d = b.to_dict()
        b2 = ContentBlock.from_dict(d)
        assert b2.type == b.type
        assert b2.text == b.text
        assert b2.page_idx == b.page_idx
        assert b2.bbox == b.bbox
        assert b2.image_path == b.image_path

    def test_to_dict_nested_children(self):
        child = ContentBlock(type="text", text="cell")
        parent = ContentBlock(type="table", text="", children=[child])
        d = parent.to_dict()
        assert len(d["children"]) == 1
        assert d["children"][0]["text"] == "cell"

    def test_load_image_reads_file(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        img_file = img_dir / "fig.jpg"
        img_file.write_bytes(b"\xff\xd8fake")
        b = ContentBlock(type="image", text="", image_path="images/fig.jpg")
        data = b.load_image(str(tmp_path))
        assert data == b"\xff\xd8fake"
        assert b.image_bytes == b"\xff\xd8fake"

    def test_load_image_cached(self, tmp_path):
        b = ContentBlock(type="image", text="", image_path="x.jpg", image_bytes=b"cached")
        data = b.load_image(str(tmp_path))
        assert data == b"cached"

    def test_load_image_missing_file(self, tmp_path):
        b = ContentBlock(type="image", text="", image_path="nonexistent.jpg")
        data = b.load_image(str(tmp_path))
        assert data == b""


class TestEstimateTokens:
    def test_english_text(self):
        text = "hello world " * 100  # ~1100 chars
        assert estimate_tokens(text) == len(text) // 4

    def test_short_text(self):
        assert estimate_tokens("hi") == 1


class TestMergeBlocks:
    def test_empty_blocks(self):
        assert merge_blocks([]) == []

    def test_single_text_block(self):
        blocks = [ContentBlock(type="text", text="hello world")]
        chunks = merge_blocks(blocks)
        assert len(chunks) == 1
        assert chunks[0].text == "hello world"

    def test_section_heading_breaks_chunk(self):
        blocks = [
            ContentBlock(type="text", text="some body text"),
            ContentBlock(type="text", text="1. Introduction", level=1),
            ContentBlock(type="text", text="intro body"),
        ]
        chunks = merge_blocks(blocks)
        assert len(chunks) >= 2
        assert chunks[0].text == "some body text"
        assert "1. Introduction" in chunks[1].text

    def test_image_attached_to_chunk(self):
        blocks = [
            ContentBlock(type="text", text="see figure:"),
            ContentBlock(type="image", text="", image_path="fig.jpg"),
            ContentBlock(type="text", text="more text"),
        ]
        chunks = merge_blocks(blocks)
        assert len(chunks) == 1
        assert len(chunks[0].images) == 1
        assert chunks[0].images[0].image_path == "fig.jpg"

    def test_section_path_tracks_headings(self):
        blocks = [
            ContentBlock(type="text", text="3. Method", level=1),
            ContentBlock(type="text", text="method body"),
            ContentBlock(type="text", text="3.1 Dataset", level=2),
            ContentBlock(type="text", text="dataset body"),
        ]
        chunks = merge_blocks(blocks)
        # First chunk: under "3. Method"
        assert "3. Method" in chunks[0].section_path
        # Second chunk: under "3. Method" > "3.1 Dataset"
        assert "3.1 Dataset" in chunks[1].section_path

    def test_long_text_splits_with_overlap(self):
        # Two blocks whose combined estimate exceeds 480 tokens,
        # triggering a split at the block boundary.
        blocks = [
            ContentBlock(type="text", text="word " * 200),  # ~250 tokens
            ContentBlock(type="text", text="word " * 200),  # ~250 tokens
        ]
        chunks = merge_blocks(blocks)
        assert len(chunks) >= 2
        # Second chunk should start with some overlap from first
        assert len(chunks[0].text) > 0
        assert len(chunks[1].text) > 0
        # The first chunk should match the first block
        assert chunks[0].text.strip() == ("word " * 200).strip()


class TestPaperDocument:
    def test_roundtrip(self):
        blocks = [
            ContentBlock(type="text", text="hello", level=1, page_idx=0),
            ContentBlock(type="text", text="body"),
        ]
        chunks = [
            SemanticChunk(
                chunk_id="chunk_0", text="hello\nbody",
                blocks=blocks, section_path=["hello"],
            ),
        ]
        doc = PaperDocument(
            filepath="/tmp/test.pdf", title="Test",
            abstract="abstract", blocks=blocks, chunks=chunks,
            metadata={"year": "2025"},
        )
        d = doc.to_dict()
        doc2 = PaperDocument.from_dict(d)
        assert doc2.title == "Test"
        assert doc2.abstract == "abstract"
        assert len(doc2.blocks) == 2
        assert len(doc2.chunks) == 1
        assert doc2.metadata["year"] == "2025"
