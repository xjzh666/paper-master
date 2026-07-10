import io
import tempfile
import fitz
from pathlib import Path
from PIL import Image, ImageDraw
from unittest.mock import patch, MagicMock

from paper_reader.parser import parse_pdf
from paper_reader.llm import LLMRouter
from paper_reader.context import ConversationContext
from paper_reader.parser import Section, ImageBlock


def create_test_pdf() -> str:
    """Create a realistic multi-page PDF with an embedded image."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc = fitz.open()

    # Page 1: Title + abstract
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Deep Learning for Paper Reading", fontsize=18)
    p1.insert_text((72, 110), "A. Researcher, B. Scholar", fontsize=12)
    p1.insert_text((72, 160), "Abstract", fontsize=14)
    p1.insert_text((72, 190),
        "We propose a novel approach to automated paper reading using "
        "large language models combined with visual understanding. "
        "Our system achieves state-of-the-art results on the PaperQA benchmark.", fontsize=11)

    # Page 2: Introduction
    p2 = doc.new_page()
    p2.insert_text((72, 72), "1. Introduction", fontsize=16)
    p2.insert_text((72, 110),
        "Reading academic papers is a time-consuming task for researchers. "
        "On average, a researcher spends 4-6 hours per paper. Automated tools "
        "can significantly reduce this burden.", fontsize=11)

    # Page 3: Method (with an embedded image)
    p3 = doc.new_page()
    p3.insert_text((72, 72), "2. Method", fontsize=16)
    p3.insert_text((72, 110),
        "Our architecture has three components: PDF parser, LLM router, "
        "and context manager. See Figure 1 for the architecture diagram.", fontsize=11)
    # Create a small PNG image in memory and embed it
    img = Image.new("RGB", (200, 100), (200, 200, 200))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 190, 90], outline=(0, 0, 0), width=2)
    draw.text((50, 40), "Architecture", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    p3.insert_image(fitz.Rect(72, 200, 272, 300), stream=buf.getvalue())
    p3.insert_text((72, 320), "Figure 1: System architecture", fontsize=10)

    # Page 4: Results
    p4 = doc.new_page()
    p4.insert_text((72, 72), "3. Results", fontsize=16)
    p4.insert_text((72, 110),
        "Our system achieves 95% accuracy on paper summarization and "
        "answers user questions with 87% relevance score.", fontsize=11)

    # Page 5: Conclusion
    p5 = doc.new_page()
    p5.insert_text((72, 72), "4. Conclusion", fontsize=16)
    p5.insert_text((72, 110),
        "We have demonstrated an effective paper reading assistant. "
        "Future work will extend this to multi-paper comparison.", fontsize=11)

    doc.save(tmp.name)
    doc.close()
    return tmp.name


class FakeTextClient:
    def chat(self, messages, system_prompt=""):
        user_msg = messages[-1]["content"] if messages else ""
        return f"[Text model response based on provided content]"


class FakeVisionClient:
    def chat_with_images(self, text, images, system_prompt=""):
        return f"[Vision model response with {len(images)} image(s)]"


def test_full_pipeline_parse_and_overview():
    pdf_path = create_test_pdf()
    try:
        paper = parse_pdf(pdf_path)
        assert paper.title
        assert len(paper.sections) > 0
        assert paper.abstract

        ctx = ConversationContext(paper)
        overview = ctx.get_overview()
        assert "Deep Learning" in overview
        assert "1. Introduction" in overview
        assert "2. Method" in overview
        assert "3. Results" in overview
        assert "4. Conclusion" in overview
    finally:
        Path(pdf_path).unlink()


def test_full_pipeline_question_routing():
    pdf_path = create_test_pdf()
    try:
        paper = parse_pdf(pdf_path)
        ctx = ConversationContext(paper)

        router = LLMRouter.__new__(LLMRouter)
        router._text_client = FakeTextClient()
        router._vision_client = FakeVisionClient()

        ctx.add_message("user", "What is the method?")
        section = ctx.find_section("method")
        assert section is not None

        answer = router.answer(section, "What is the method?", ctx.history[:-1])
        assert answer is not None
        assert len(answer) > 0
    finally:
        Path(pdf_path).unlink()


def test_full_pipeline_section_with_visuals():
    """Section with drawings (treated as images) uses vision model."""
    pdf_path = create_test_pdf()
    try:
        paper = parse_pdf(pdf_path)
        ctx = ConversationContext(paper)

        router = LLMRouter.__new__(LLMRouter)
        router._text_client = FakeTextClient()
        router._vision_client = FakeVisionClient()

        section = ctx.find_section("method")
        assert section is not None

        answer = router.answer(section, "Explain the architecture", [])
        assert "Vision" in answer or "image" in answer.lower()
    finally:
        Path(pdf_path).unlink()
