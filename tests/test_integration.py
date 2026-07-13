import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from paper_reader.blocks import PaperDocument, ContentBlock, SemanticChunk, merge_blocks
from paper_reader.mineru_parser import MinerUParser
from paper_reader.llm import LLMRouter
from paper_reader.context import ConversationContext


SAMPLE_CONTENT = [
    {"type": "text", "text": "Deep Learning for Paper Reading", "text_level": 1, "bbox": [72, 72, 500, 100], "page_idx": 0},
    {"type": "text", "text": "A. Researcher", "text_level": 0, "bbox": [72, 120, 500, 140], "page_idx": 0},
    {"type": "text", "text": "Abstract", "text_level": 0, "bbox": [72, 160, 500, 180], "page_idx": 0},
    {"type": "text", "text": "We propose a novel approach to automated paper reading.", "text_level": 0, "bbox": [72, 190, 500, 220], "page_idx": 0},
    {"type": "text", "text": "1. Introduction", "text_level": 1, "bbox": [72, 250, 500, 280], "page_idx": 1},
    {"type": "text", "text": "Reading academic papers is time-consuming. Researchers spend hours per paper.", "text_level": 0, "bbox": [72, 290, 500, 320], "page_idx": 1},
    {"type": "text", "text": "2. Method", "text_level": 1, "bbox": [72, 350, 500, 380], "page_idx": 2},
    {"type": "text", "text": "Our architecture has three components: PDF parser, LLM router, context manager.", "text_level": 0, "bbox": [72, 390, 500, 420], "page_idx": 2},
    {"type": "image", "text": "", "img_path": "images/arch.jpg", "bbox": [100, 450, 500, 600], "page_idx": 2},
    {"type": "text", "text": "3. Results", "text_level": 1, "bbox": [72, 620, 500, 640], "page_idx": 3},
    {"type": "text", "text": "Our system achieves 95% accuracy on paper summarization.", "text_level": 0, "bbox": [72, 650, 500, 680], "page_idx": 3},
    {"type": "text", "text": "4. Conclusion", "text_level": 1, "bbox": [72, 710, 500, 730], "page_idx": 4},
    {"type": "text", "text": "We demonstrated an effective paper reading assistant.", "text_level": 0, "bbox": [72, 740, 500, 770], "page_idx": 4},
]


def make_fake_mineru_output():
    d = tempfile.mkdtemp()
    result_dir = Path(d) / "test" / "hybrid_auto"
    result_dir.mkdir(parents=True)
    with open(result_dir / "content_list_v2.json", "w") as f:
        json.dump(SAMPLE_CONTENT, f)
    (result_dir / "images").mkdir(exist_ok=True)
    return Path(d)


class FakeTextClient:
    def chat(self, messages, system_prompt=""):
        return "[Text model response based on provided content]"


class FakeVisionClient:
    def chat_with_images(self, text, images, system_prompt=""):
        return f"[Vision model response with {len(images)} image(s)]"


def test_full_pipeline_parse_and_overview():
    result_dir = make_fake_mineru_output()
    try:
        pdf_path = str(result_dir / "test.pdf")
        # touch the pdf file
        Path(pdf_path).write_text("fake pdf content")

        parser = MinerUParser()
        fake_hybrid = result_dir / "test" / "hybrid_auto"
        with patch.object(parser, '_run_mineru', return_value=None), \
             patch.object(parser, '_find_result_dir', return_value=fake_hybrid):
            paper = parser.parse(pdf_path)

        assert paper.title
        assert len(paper.blocks) > 0
        assert len(paper.chunks) > 0

        ctx = ConversationContext(paper)
        overview = ctx.get_overview()
        assert "Deep Learning" in overview
        assert "1. Introduction" in overview
        assert "2. Method" in overview
        assert "3. Results" in overview
        assert "4. Conclusion" in overview
    finally:
        import shutil
        shutil.rmtree(result_dir)


def test_full_pipeline_section_lookup():
    result_dir = make_fake_mineru_output()
    try:
        pdf_path = str(result_dir / "test.pdf")
        Path(pdf_path).write_text("fake pdf content")

        parser = MinerUParser()
        fake_hybrid = result_dir / "test" / "hybrid_auto"
        with patch.object(parser, '_run_mineru', return_value=None), \
             patch.object(parser, '_find_result_dir', return_value=fake_hybrid):
            paper = parser.parse(pdf_path)

        ctx = ConversationContext(paper)
        blocks = ctx.find_section("method")
        assert blocks is not None
        all_text = " ".join(b.text for b in blocks)
        assert "three components" in all_text
    finally:
        import shutil
        shutil.rmtree(result_dir)


def test_full_pipeline_tfidf_search():
    result_dir = make_fake_mineru_output()
    try:
        pdf_path = str(result_dir / "test.pdf")
        Path(pdf_path).write_text("fake pdf content")

        parser = MinerUParser()
        fake_hybrid = result_dir / "test" / "hybrid_auto"
        with patch.object(parser, '_run_mineru', return_value=None), \
             patch.object(parser, '_find_result_dir', return_value=fake_hybrid):
            paper = parser.parse(pdf_path)

        ctx = ConversationContext(paper)
        chunks = ctx.search_chunks("accuracy summarization", top_k=3)
        assert len(chunks) >= 1
        found = " ".join(c.text for c in chunks)
        assert "95%" in found or "accuracy" in found.lower()
    finally:
        import shutil
        shutil.rmtree(result_dir)


def test_full_pipeline_llm_routing():
    result_dir = make_fake_mineru_output()
    try:
        pdf_path = str(result_dir / "test.pdf")
        Path(pdf_path).write_text("fake pdf content")

        parser = MinerUParser()
        fake_hybrid = result_dir / "test" / "hybrid_auto"
        with patch.object(parser, '_run_mineru', return_value=None), \
             patch.object(parser, '_find_result_dir', return_value=fake_hybrid):
            paper = parser.parse(pdf_path)

        ctx = ConversationContext(paper)
        router = LLMRouter.__new__(LLMRouter)
        router._text_client = FakeTextClient()
        router._vision_client = FakeVisionClient()

        text, images = ctx.build_context(paper.chunks[:2], window=0)
        answer = router.answer(
            text=text, images=[], question="What is the method?",
            history=[], title=paper.title,
        )
        assert answer is not None
        assert len(answer) > 0
    finally:
        import shutil
        shutil.rmtree(result_dir)


def test_full_pipeline_vision_routing():
    result_dir = make_fake_mineru_output()
    try:
        pdf_path = str(result_dir / "test.pdf")
        Path(pdf_path).write_text("fake pdf content")

        parser = MinerUParser()
        fake_hybrid = result_dir / "test" / "hybrid_auto"
        with patch.object(parser, '_run_mineru', return_value=None), \
             patch.object(parser, '_find_result_dir', return_value=fake_hybrid):
            paper = parser.parse(pdf_path)

        ctx = ConversationContext(paper)
        router = LLMRouter.__new__(LLMRouter)
        router._text_client = FakeTextClient()
        router._vision_client = FakeVisionClient()

        # Find chunk with image
        chunks_with_images = [c for c in paper.chunks if c.images]
        if chunks_with_images:
            text, images = ctx.build_context(chunks_with_images[:1], window=0)
            answer = router.answer(
                text=text, images=[b"fake_image"], question="Explain the architecture",
                history=[], title=paper.title,
            )
            assert "Vision" in answer or "image" in answer.lower()
    finally:
        import shutil
        shutil.rmtree(result_dir)
