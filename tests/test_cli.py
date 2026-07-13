# tests/test_cli.py
from unittest.mock import MagicMock

from paper_reader.context import ConversationContext
from paper_reader.blocks import PaperDocument, ContentBlock, SemanticChunk, merge_blocks
from paper_reader.llm import LLMRouter
from main import handle_question


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
