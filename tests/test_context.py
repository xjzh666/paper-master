from paper_reader.context import ConversationContext
from paper_reader.parser import PaperDocument, Section


def make_paper() -> PaperDocument:
    return PaperDocument(
        filepath="test.pdf",
        title="Test Paper",
        sections=[
            Section(
                title="1. Introduction", level=1,
                text="Introduction text.", page_start=0, page_end=0,
            ),
            Section(
                title="2. Methods", level=1,
                text="Methods text.", page_start=1, page_end=1,
            ),
            Section(
                title="2.1 Dataset", level=2,
                text="Dataset details.", page_start=1, page_end=1,
            ),
        ],
        abstract="This is a test abstract.",
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


def test_find_section_exact_match():
    ctx = ConversationContext(make_paper())
    section = ctx.find_section("2. Methods")
    assert section is not None
    assert section.title == "2. Methods"


def test_find_section_partial_match():
    ctx = ConversationContext(make_paper())
    section = ctx.find_section("Methods")
    assert section is not None
    assert "Methods" in section.title


def test_find_section_no_match():
    ctx = ConversationContext(make_paper())
    section = ctx.find_section("Conclusion")
    assert section is None


def test_find_section_by_number():
    ctx = ConversationContext(make_paper())
    section = ctx.find_section("2.1")
    assert section is not None
    assert section.title == "2.1 Dataset"


def test_get_overview():
    ctx = ConversationContext(make_paper())
    overview = ctx.get_overview()
    assert "Test Paper" in overview
    assert "test abstract" in overview
    assert "1. Introduction" in overview
    assert "2. Methods" in overview
    assert "2.1 Dataset" in overview
