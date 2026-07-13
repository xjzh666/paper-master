# tests/test_mineru_parser.py
import json
import tempfile
from pathlib import Path

import pytest
from paper_reader.mineru_parser import MinerUParser
from paper_reader.blocks import PaperDocument, ContentBlock, SemanticChunk


SAMPLE_CONTENT_LIST = [
    {"type": "text", "text": "Test Paper Title", "text_level": 1, "bbox": [72, 72, 500, 100], "page_idx": 0},
    {"type": "text", "text": "Author Names", "text_level": 0, "bbox": [72, 120, 500, 140], "page_idx": 0},
    {"type": "text", "text": "Abstract", "text_level": 0, "bbox": [72, 160, 500, 180], "page_idx": 0},
    {"type": "text", "text": "This is the abstract content.", "text_level": 0, "bbox": [72, 190, 500, 220], "page_idx": 0},
    {"type": "text", "text": "1. Introduction", "text_level": 1, "bbox": [72, 250, 500, 280], "page_idx": 1},
    {"type": "text", "text": "Introduction body text here.", "text_level": 0, "bbox": [72, 290, 500, 320], "page_idx": 1},
    {"type": "image", "text": "", "img_path": "images/fig1.jpg", "bbox": [100, 350, 500, 500], "page_idx": 1},
    {"type": "text", "text": "Figure 1: Overview", "text_level": 0, "bbox": [72, 510, 500, 530], "page_idx": 1},
]


def make_fake_result_dir(content_list):
    """Create a temp directory with content_list_v2.json."""
    d = tempfile.mkdtemp()
    result_dir = Path(d) / "test_paper" / "hybrid_auto"
    result_dir.mkdir(parents=True)
    with open(result_dir / "content_list_v2.json", "w") as f:
        json.dump(content_list, f)
    (result_dir / "images").mkdir(exist_ok=True)
    return Path(d)


class TestMinerUParserBuildPaper:
    def test_build_paper_from_content_list(self):
        parser = MinerUParser()
        result_dir = make_fake_result_dir(SAMPLE_CONTENT_LIST)
        pdf_path = str(result_dir / ".." / "test_paper.pdf")

        paper = parser._build_paper(pdf_path, result_dir / "test_paper" / "hybrid_auto")

        assert isinstance(paper, PaperDocument)
        assert paper.title == "Test Paper Title"
        assert "abstract content" in paper.abstract.lower()
        assert len(paper.blocks) == len(SAMPLE_CONTENT_LIST)
        assert len(paper.chunks) > 0

    def test_build_paper_creates_chunks(self):
        parser = MinerUParser()
        result_dir = make_fake_result_dir(SAMPLE_CONTENT_LIST)
        pdf_path = str(result_dir / "test_paper.pdf")

        paper = parser._build_paper(
            pdf_path, result_dir / "test_paper" / "hybrid_auto"
        )

        assert len(paper.chunks) >= 2  # title+abstract chunk, intro chunk
        for chunk in paper.chunks:
            assert isinstance(chunk, SemanticChunk)
            assert chunk.text

    def test_build_paper_chunks_have_section_paths(self):
        parser = MinerUParser()
        result_dir = make_fake_result_dir(SAMPLE_CONTENT_LIST)
        pdf_path = str(result_dir / "test_paper.pdf")

        paper = parser._build_paper(
            pdf_path, result_dir / "test_paper" / "hybrid_auto"
        )

        paths = [c.section_path for c in paper.chunks if c.section_path]
        assert len(paths) >= 1
        flat = [s for p in paths for s in p]
        assert "1. Introduction" in flat

    def test_title_fallback_to_first_long_text(self):
        content = [
            {"type": "text", "text": "A Very Long Title That Exceeds Twenty Characters", "text_level": 0, "bbox": [72, 72, 500, 100], "page_idx": 0},
            {"type": "text", "text": "body", "text_level": 0, "bbox": [72, 120, 500, 140], "page_idx": 0},
        ]
        parser = MinerUParser()
        result_dir = make_fake_result_dir(content)
        paper = parser._build_paper(
            str(result_dir / "test_paper.pdf"),
            result_dir / "test_paper" / "hybrid_auto",
        )
        assert len(paper.title) > 0


class TestMinerUParserCache:
    def test_cache_key_deterministic(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"hello world")
        parser = MinerUParser()
        k1 = parser._cache_key(str(pdf))
        k2 = parser._cache_key(str(pdf))
        assert k1 == k2

    def test_cache_key_different_for_different_files(self, tmp_path):
        pdf1 = tmp_path / "a.pdf"
        pdf1.write_bytes(b"aaa")
        pdf2 = tmp_path / "b.pdf"
        pdf2.write_bytes(b"bbb")
        parser = MinerUParser()
        assert parser._cache_key(str(pdf1)) != parser._cache_key(str(pdf2))

    def test_save_and_load_cache(self, tmp_path):
        import paper_reader.mineru_parser as mp
        original_cache = mp.CACHE_DIR
        mp.CACHE_DIR = tmp_path / "cache"
        try:
            parser = MinerUParser()
            blocks = [ContentBlock(type="text", text="hello")]
            chunks = [SemanticChunk(chunk_id="c0", text="hello", blocks=blocks, section_path=[])]
            paper = PaperDocument(
                filepath="/tmp/x.pdf", title="T", abstract="A",
                blocks=blocks, chunks=chunks,
            )

            key = "test_key_123"
            parser._save_cache(key, paper)
            loaded = parser._load_cache(key)

            assert loaded is not None
            assert loaded.title == "T"
            assert loaded.abstract == "A"
            assert len(loaded.blocks) == 1
            assert len(loaded.chunks) == 1
        finally:
            mp.CACHE_DIR = original_cache
