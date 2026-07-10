# tests/test_cli.py
from unittest.mock import MagicMock

from paper_reader.context import ConversationContext
from paper_reader.parser import PaperDocument, Section
from paper_reader.llm import LLMRouter
from main import handle_question


def make_paper():
    return PaperDocument(
        filepath="test.pdf",
        title="Test Paper",
        sections=[
            Section(title="1. Intro", level=1, text="Intro text", page_start=0, page_end=0),
            Section(title="2. Methods", level=1, text="Methods text", page_start=1, page_end=1),
        ],
        abstract="Test abstract.",
    )


def test_handle_question_finds_section_and_answers():
    ctx = ConversationContext(make_paper())
    router = MagicMock()
    router.answer.return_value = "This is the answer."

    question = "What does section 2 say?"
    answer = handle_question(question, ctx, router)

    router.answer.assert_called_once()
    assert answer == "This is the answer."
    assert len(ctx.history) >= 2  # user + assistant messages


def test_handle_question_general_without_section():
    ctx = ConversationContext(make_paper())
    router = MagicMock()
    router.answer.return_value = "General answer."

    question = "What is this paper about?"
    answer = handle_question(question, ctx, router)

    router.answer.assert_called_once()
    assert answer == "General answer."
