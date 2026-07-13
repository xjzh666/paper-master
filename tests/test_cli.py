# tests/test_cli.py
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from paper_reader.context import ConversationContext
from paper_reader.blocks import PaperDocument, ContentBlock, SemanticChunk, merge_blocks
from paper_reader.llm import LLMRouter
from main import handle_question, batch_parse


def make_paper():
    blocks = [
        ContentBlock(type="text", text="Test Paper", level=1, page_idx=0),
        ContentBlock(type="text", text="Introduction text describing the paper.", level=0, page_idx=0),
        ContentBlock(type="text", text="2. Methods", level=1, page_idx=1),
        ContentBlock(type="text", text="Methods text describing the experimental approach.", level=0, page_idx=1),
    ]
    chunks = merge_blocks(blocks)
    return PaperDocument(
        filepath="test.pdf",
        title="Test Paper",
        abstract="Test abstract.",
        blocks=blocks,
        chunks=chunks,
    )


def test_handle_question_finds_section_and_answers():
    ctx = ConversationContext(make_paper())
    router = MagicMock()
    router.answer.return_value = "This is the answer."

    question = "methods"
    answer = handle_question(question, ctx, router)

    router.answer.assert_called_once()
    assert answer == "This is the answer."
    assert len(ctx.history) >= 2  # user + assistant messages


def test_handle_question_general_without_section():
    ctx = ConversationContext(make_paper())
    router = MagicMock()
    router.answer.return_value = "General answer."

    question = "overview of the paper"
    answer = handle_question(question, ctx, router)

    router.answer.assert_called_once()
    assert answer == "General answer."


def test_batch_parse_no_pdfs(tmp_path):
    """batch_parse exits gracefully when no PDFs found."""
    import sys
    try:
        batch_parse(str(tmp_path))
    except SystemExit as e:
        assert e.code == 1


def test_batch_parse_with_pdfs(tmp_path):
    """batch_parse processes PDFs successfully."""
    # Create dummy PDF files
    for name in ["paper1.pdf", "paper2.pdf"]:
        (tmp_path / name).write_bytes(b"%PDF-1.4 fake pdf")

    fake_paper = make_paper()
    with patch("main.MinerUParser") as mock_cls:
        mock_cls.return_value.parse.return_value = fake_paper
        batch_parse(str(tmp_path))

    assert mock_cls.return_value.parse.call_count == 2
