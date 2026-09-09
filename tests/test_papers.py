import json
import time
from pathlib import Path

import pytest

import paper_reader.papers as papers
from paper_reader.blocks import PaperDocument


@pytest.fixture(autouse=True)
def _clean_state():
    papers.sessions.clear()
    papers.parse_tasks.clear()
    papers.memory_jobs.clear()
    yield
    papers.sessions.clear()
    papers.parse_tasks.clear()
    papers.memory_jobs.clear()


def _make_paper(filepath, title="Test", result_dir=None):
    return PaperDocument(
        filepath=str(filepath), title=title, abstract="Abstract",
        blocks=[], chunks=[], result_dir=str(result_dir or Path(filepath).parent),
    )


def test_open_cached_paper_returns_ready(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = _make_paper(str(pdf))
    (cache_dir / f"{key}.json").write_text(
        json.dumps(paper.to_dict()), encoding="utf-8")
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)

    result = papers.open_paper(str(pdf))
    assert result["status"] == "ready"
    assert result["paper_id"] == key
    assert key in papers.sessions


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_open_cached_paper_loads_memory_file_skips_extraction(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = _make_paper(str(pdf))
    (cache_dir / f"{key}.json").write_text(
        json.dumps(paper.to_dict()), encoding="utf-8")
    (cache_dir / f"{key}-memory.json").write_text(
        json.dumps({"sha256": key, "memory": {"research_problem": "cached"}}),
        encoding="utf-8")
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    monkeypatch.setattr("paper_reader.memory.CACHE_DIR", cache_dir)

    def _fail_extract(p, client):
        raise AssertionError("extract_memory should not be called")

    monkeypatch.setattr(papers, "extract_memory", _fail_extract)

    result = papers.open_paper(str(pdf))
    assert result["status"] == "ready"
    assert papers.sessions[key].paper.memory.research_problem == "cached"


def test_open_cached_paper_extracts_memory_in_background(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = _make_paper(str(pdf))
    (cache_dir / f"{key}.json").write_text(
        json.dumps(paper.to_dict()), encoding="utf-8")
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    monkeypatch.setattr("paper_reader.memory.CACHE_DIR", cache_dir)

    class _FakeMemory:
        research_problem = "fresh"

    def _fake_extract(p, client):
        return _FakeMemory()

    monkeypatch.setattr(papers, "extract_memory", _fake_extract)

    result = papers.open_paper(str(pdf))
    assert result["status"] == "ready"
    assert papers.sessions[key].paper.memory is None  # returns before extraction
    assert _wait_for(lambda: papers.sessions[key].paper.memory is not None)
    assert papers.sessions[key].paper.memory.research_problem == "fresh"
    assert key not in papers.memory_jobs


def test_memory_extraction_failure_degrades_silently(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = _make_paper(str(pdf))
    (cache_dir / f"{key}.json").write_text(
        json.dumps(paper.to_dict()), encoding="utf-8")
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)

    def _boom(p, client):
        raise RuntimeError("llm boom")

    monkeypatch.setattr(papers, "extract_memory", _boom)

    papers.open_paper(str(pdf))
    assert _wait_for(lambda: key not in papers.memory_jobs)
    assert papers.sessions[key].paper.memory is None
    assert papers.get_status(key)["status"] == "ready"


def test_open_paper_loads_persisted_history(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = _make_paper(str(pdf))
    (cache_dir / f"{key}.json").write_text(
        json.dumps(paper.to_dict()), encoding="utf-8")
    (cache_dir / f"{key}-history.json").write_text(
        json.dumps({"paper_id": key, "messages": [
            {"role": "user", "content": "这篇论文讲什么？"},
            {"role": "assistant", "content": "讲的是 X。"},
        ]}),
        encoding="utf-8")
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)

    papers.open_paper(str(pdf))
    history = papers.sessions[key].ctx.history
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["content"] == "讲的是 X。"


def test_corrupt_history_file_loads_empty(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = _make_paper(str(pdf))
    (cache_dir / f"{key}.json").write_text(
        json.dumps(paper.to_dict()), encoding="utf-8")
    (cache_dir / f"{key}-history.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)

    result = papers.open_paper(str(pdf))
    assert result["status"] == "ready"
    assert papers.sessions[key].ctx.history == []


def test_chat_events_persists_history_to_disk(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = PaperDocument(filepath=str(pdf), title="T", abstract="",
                          blocks=[], chunks=[], result_dir=str(tmp_path))
    papers.sessions[key] = papers.Session(paper)
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)

    class _FakeStreamText:
        def chat_with_tools_stream(self, messages, tools, system_prompt=""):
            yield from [("text_delta", "答案是B"), ("tool_calls", [])]

    class _FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return "desc"

    class _FakeRouter:
        def __init__(self):
            self._text_client = _FakeStreamText()
            self._vision_client = _FakeVision()

    monkeypatch.setattr(papers, "ROUTER", _FakeRouter())

    list(papers.chat_events(key, "第二个问题？"))

    history_file = cache_dir / f"{key}-history.json"
    assert history_file.exists()
    data = json.loads(history_file.read_text(encoding="utf-8"))
    roles = [m["role"] for m in data["messages"]]
    assert roles == ["user", "assistant"]
    assert data["messages"][1]["content"] == "答案是B"


def test_open_uncached_spawns_background_parse(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    monkeypatch.setattr(papers, "CACHE_DIR", tmp_path / "cache")

    class _FakeParser:
        def parse(self, path):
            return _make_paper(path)

    monkeypatch.setattr(papers, "PARSER", _FakeParser())

    result = papers.open_paper(str(pdf))
    assert result["status"] == "parsing"
    for _ in range(100):
        if papers.get_status(key)["status"] in ("ready", "error"):
            break
        time.sleep(0.05)
    assert papers.get_status(key)["status"] == "ready"


def test_open_uncached_parse_failure_sets_error(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    monkeypatch.setattr(papers, "CACHE_DIR", tmp_path / "cache")

    class _FailingParser:
        def parse(self, path):
            raise RuntimeError("mineru boom")

    monkeypatch.setattr(papers, "PARSER", _FailingParser())

    papers.open_paper(str(pdf))
    for _ in range(100):
        if papers.get_status(key)["status"] == "error":
            break
        time.sleep(0.05)
    assert papers.get_status(key)["status"] == "error"
    assert "mineru boom" in papers.get_status(key)["message"]


def test_overview_and_content(tmp_path, monkeypatch):
    from paper_reader.blocks import ContentBlock
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "paper.md").write_text(
        "## Introduction\n\nText with ![figure](images/a.png)\n",
        encoding="utf-8",
    )
    paper = PaperDocument(
        filepath=str(pdf), title="My Paper", abstract="Abstract",
        result_dir=str(result_dir),
        blocks=[ContentBlock(type="text", text="Introduction",
                             level=1, page_idx=0)],
        chunks=[],
    )
    papers.sessions[key] = papers.Session(paper)

    overview = papers.get_overview(key)
    assert overview["title"] == "My Paper"
    assert overview["toc"][0]["title"] == "Introduction"

    md = papers.get_content(key)
    assert "## Introduction" in md
    assert f"/api/papers/{key}/images/images/a.png" in md


def test_get_image_path_resolves_within_result_dir(tmp_path):
    from paper_reader.blocks import ContentBlock
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    result_dir = tmp_path / "result"
    images = result_dir / "images"
    images.mkdir(parents=True)
    (images / "a.png").write_bytes(b"png")
    paper = PaperDocument(filepath=str(pdf), title="T", blocks=[], chunks=[],
                          result_dir=str(result_dir))
    papers.sessions[key] = papers.Session(paper)

    p = papers.get_image_path(key, "images/a.png")
    assert p is not None and p.name == "a.png"
    # path traversal rejected
    assert papers.get_image_path(key, "../secret") is None


def test_chat_events_streams_tools_then_answer(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    paper = PaperDocument(filepath=str(pdf), title="T", abstract="",
                          blocks=[], chunks=[], result_dir=str(tmp_path))
    papers.sessions[key] = papers.Session(paper)

    class _FakeStreamText:
        def __init__(self):
            self._streams = [
                [("text_delta", "查一下"),
                 ("tool_calls", [{"id": "c1", "name": "search_paper",
                                  "arguments": '{"query":"x"}'}])],
                [("text_delta", "答案是A"), ("tool_calls", [])],
            ]
            self._i = 0

        def chat_with_tools_stream(self, messages, tools, system_prompt=""):
            evs = self._streams[self._i] if self._i < len(self._streams) else []
            self._i += 1
            yield from evs

    class _FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return "desc"

    class _FakeRouter:
        def __init__(self):
            self._text_client = _FakeStreamText()
            self._vision_client = _FakeVision()

    monkeypatch.setattr(papers, "ROUTER", _FakeRouter())

    events = list(papers.chat_events(key, "问题?"))
    types = [t for t, _ in events]
    assert "tool_start" in types
    assert "tool_result" in types
    assert "answer_chunk" in types
    assert types[-1] == "done"
    # answer stored in session history
    last = papers.sessions[key].ctx.history[-1]
    assert last["role"] == "assistant"
    assert "答案是A" in last["content"]


def test_chat_events_preserves_citation_link_in_answer_chunks(tmp_path, monkeypatch):
    """Contract test (P3 citations): a `[§x.x p.N](cite:chunk_N)` link emitted
    by the LLM must pass through the chat_events SSE channel unchanged."""
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = PaperDocument(filepath=str(pdf), title="T", abstract="",
                          blocks=[], chunks=[], result_dir=str(tmp_path))
    papers.sessions[key] = papers.Session(paper)
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    monkeypatch.setattr("paper_reader.observations.CACHE_DIR", cache_dir)

    class _FakeStreamText:
        def chat_with_tools_stream(self, messages, tools, system_prompt=""):
            yield from [
                ("text_delta", "准确率达 92% "),
                ("text_delta", "[§3.2 p.4](cite:chunk_0)"),
                ("text_delta", "。"),
                ("tool_calls", []),
            ]

    class _FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return "desc"

    class _FakeRouter:
        def __init__(self):
            self._text_client = _FakeStreamText()
            self._vision_client = _FakeVision()

    monkeypatch.setattr(papers, "ROUTER", _FakeRouter())

    events = list(papers.chat_events(key, "实验效果如何?"))

    types = [t for t, _ in events]
    assert "error" not in types
    assert types[-1] == "done"
    answer = "".join(p["delta"] for t, p in events if t == "answer_chunk")
    assert "[§3.2 p.4](cite:chunk_0)" in answer
    # persisted history keeps the link verbatim (restart-safe clickability)
    assert "[§3.2 p.4](cite:chunk_0)" in papers.sessions[key].ctx.history[-1]["content"]


def test_get_chat_history_prefers_session_over_disk(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    key = "somepaper"
    # no session, no file → empty
    assert papers.get_chat_history(key) == []
    # disk fallback
    (cache_dir / f"{key}-history.json").write_text(
        json.dumps({"paper_id": key, "messages": [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧答案"},
        ]}), encoding="utf-8")
    assert [m["content"] for m in papers.get_chat_history(key)] == ["旧问题", "旧答案"]
    # live session wins over disk
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    session = papers.Session(_make_paper(str(pdf)))
    session.ctx.add_message("user", "新问题")
    papers.sessions[key] = session
    assert papers.get_chat_history(key) == [{"role": "user", "content": "新问题"}]


def test_clear_chat_history_clears_session_and_disk(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    session = papers.Session(_make_paper(str(pdf)))
    session.ctx.add_message("user", "问题")
    session.ctx.add_message("assistant", "答案")
    papers.sessions[key] = session
    papers.save_chat_history(key, session.ctx.history)
    assert (cache_dir / f"{key}-history.json").exists()

    papers.clear_chat_history(key)
    assert papers.sessions[key].ctx.history == []
    assert not (cache_dir / f"{key}-history.json").exists()
    # idempotent: clearing again (or a paper with no session/file) is a no-op
    papers.clear_chat_history(key)
    papers.clear_chat_history("nonexistent")


def _mk_chunk(chunk_id, text, blocks, section_path):
    """Build a chunk with embeddings pre-set so ConversationContext
    skips BGE-M3 encoding (and cache writes) when building a Session."""
    from paper_reader.blocks import SemanticChunk
    return SemanticChunk(chunk_id=chunk_id, text=text, blocks=blocks,
                         section_path=section_path,
                         embedding=[0.0], lexical_weights={})


def _chunks_index_session(tmp_path, chunks):
    """Register a session with the given chunks under a fresh paper id."""
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    paper = PaperDocument(filepath=str(pdf), title="T", abstract="",
                          blocks=[], chunks=chunks, result_dir=str(tmp_path))
    papers.sessions[key] = papers.Session(paper)
    return key


def test_get_chunks_index_page_section_order(tmp_path):
    from paper_reader.blocks import ContentBlock
    c0 = _mk_chunk("chunk_0", "a",
                   [ContentBlock(type="text", text="Alpha.", page_idx=3),
                    ContentBlock(type="text", text="Beta.", page_idx=4)],
                   ["1 Intro", "3.2 Method"])
    c1 = _mk_chunk("chunk_1", "b",
                   [ContentBlock(type="text", text="Gamma.", page_idx=9)], [])
    key = _chunks_index_session(tmp_path, [c0, c1])

    idx = papers.get_chunks_index(key)
    assert [c["id"] for c in idx["chunks"]] == ["chunk_0", "chunk_1"]
    assert idx["chunks"][0]["page"] == 4  # min(3, 4) + 1, cross-page chunk
    assert idx["chunks"][0]["section"] == "3.2 Method"  # last section_path entry
    assert idx["chunks"][0]["snippets"] == ["Alpha.", "Beta."]
    assert idx["chunks"][1]["page"] == 10
    assert idx["chunks"][1]["section"] == ""


def test_get_chunks_index_section_strips_html(tmp_path):
    from paper_reader.blocks import ContentBlock
    chunk = _mk_chunk("chunk_0", "t",
                      [ContentBlock(type="text", text="x", page_idx=0)],
                      ["<b>4.1</b> Setup"])
    key = _chunks_index_session(tmp_path, [chunk])
    assert papers.get_chunks_index(key)["chunks"][0]["section"] == "4.1 Setup"


def test_get_chunks_index_skips_non_text_blocks(tmp_path):
    from paper_reader.blocks import ContentBlock
    chunk = _mk_chunk("chunk_0", "t",
                      [ContentBlock(type="image", text="Fig. 1", page_idx=0),
                       ContentBlock(type="table", text="TABLE I", page_idx=0),
                       ContentBlock(type="formula", text="E=mc^2", page_idx=0),
                       ContentBlock(type="text", text="Only text.", page_idx=0)],
                      ["2"])
    key = _chunks_index_session(tmp_path, [chunk])
    idx = papers.get_chunks_index(key)
    assert idx["chunks"][0]["snippets"] == ["Only text."]


def test_get_chunks_index_snippet_keeps_math_content(tmp_path):
    from paper_reader.blocks import ContentBlock
    chunk = _mk_chunk("chunk_0", "t",
                      [ContentBlock(type="text",
                                    text="We evaluate <b>SOTK</b> on $x^2$ nodes.",
                                    page_idx=0),
                       ContentBlock(type="text", text="$$E = mc^2$$", page_idx=0),
                       ContentBlock(type="text",
                                    text="  display $$a+b$$ tail", page_idx=0)],
                      [])
    key = _chunks_index_session(tmp_path, [chunk])
    snippets = papers.get_chunks_index(key)["chunks"][0]["snippets"]
    # delimiters stripped first, then HTML tags; math content kept; inner double space preserved
    assert snippets[0] == "We evaluate SOTK on x^2 nodes."
    # display-only block no longer dropped: its LaTeX content is the snippet
    assert snippets[1] == "E = mc^2"
    assert snippets[2] == "display a+b tail"
    assert len(snippets) == 3


def test_snippet_for_block_keeps_math_content():
    # math delimiters stripped (display then inline, non-greedy), content kept
    assert papers._snippet_for_block(
        "We evaluate <b>SOTK</b> on $x^2$ nodes.") == "We evaluate SOTK on x^2 nodes."
    # pure-formula block yields its LaTeX content instead of empty
    assert papers._snippet_for_block("$$E = mc^2$$") == "E = mc^2"


def test_snippet_for_block_bare_math_untouched():
    # bare math (no $ delimiters, as in content_list text blocks) kept as-is
    text = "While for small values of  d _ { k } the two..."
    assert papers._snippet_for_block(text) == text


def test_snippet_for_block_unpaired_dollar_keeps_content():
    # "$5 and $10" pairs as one math span; new semantics keeps inner content
    assert papers._snippet_for_block("a $5 and $10 b") == "a 5 and 10 b"
    # a lone $ pairs with nothing: not a math span, text kept as-is
    assert papers._snippet_for_block("a $5 b") == "a $5 b"


def test_snippet_for_block_math_angle_brackets_survive_html_strip():
    # regression: math content containing < / > must not be swallowed as
    # fake HTML tags (real tags like <b> are stripped first, then $ delims)
    assert papers._snippet_for_block(
        "for $d_k < n$ we have attention if $m > 0$ works"
    ) == "for d_k < n we have attention if m > 0 works"
    assert papers._snippet_for_block(
        "We find $a < b$ in <b>Table</b> notes"
    ) == "We find a < b in Table notes"


def test_get_chunks_index_caps_snippets_at_six(tmp_path):
    from paper_reader.blocks import ContentBlock
    blocks = [ContentBlock(type="text", text=f"Block {i}.", page_idx=0)
              for i in range(7)]
    chunk = _mk_chunk("chunk_0", "t", blocks, [])
    key = _chunks_index_session(tmp_path, [chunk])
    snippets = papers.get_chunks_index(key)["chunks"][0]["snippets"]
    assert snippets == [f"Block {i}." for i in range(6)]


def test_get_chunks_index_truncates_snippet_to_80_chars(tmp_path):
    from paper_reader.blocks import ContentBlock
    chunk = _mk_chunk("chunk_0", "t",
                      [ContentBlock(type="text", text="w" * 100, page_idx=0)], [])
    key = _chunks_index_session(tmp_path, [chunk])
    snippets = papers.get_chunks_index(key)["chunks"][0]["snippets"]
    assert len(snippets[0]) == 80


def test_get_chunks_index_unparsed_paper_raises_keyerror():
    with pytest.raises(KeyError):
        papers.get_chunks_index("no-such-paper")


def test_open_paper_restores_observations(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = _make_paper(str(pdf))
    (cache_dir / f"{key}.json").write_text(
        json.dumps(paper.to_dict()), encoding="utf-8")
    (cache_dir / f"{key}-observations.json").write_text(
        json.dumps({"paper_id": key, "observations": [
            {"summary": "训练用了 8 张 GPU", "facts": [], "entities": [],
             "sources": ["p5 §5.2"], "question": "训练硬件？", "round_num": 1},
        ]}), encoding="utf-8")
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    monkeypatch.setattr("paper_reader.observations.CACHE_DIR", cache_dir)

    papers.open_paper(str(pdf))
    obs = papers.sessions[key].ctx.observations
    assert len(obs) == 1
    assert obs[0].summary == "训练用了 8 张 GPU"
    assert obs[0].question == "训练硬件？"


def test_chat_events_persists_observations_to_disk(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    paper = PaperDocument(filepath=str(pdf), title="T", abstract="",
                          blocks=[], chunks=[], result_dir=str(tmp_path))
    papers.sessions[key] = papers.Session(paper)
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    monkeypatch.setattr("paper_reader.observations.CACHE_DIR", cache_dir)

    class _FakeStreamText:
        def __init__(self):
            self._streams = [
                [("tool_calls", [{"id": "c1", "name": "record_observation",
                                  "arguments": '{"summary":"发现X","sources":["p1"]}'}])],
                [("text_delta", "答案是B"), ("tool_calls", [])],
            ]
            self._i = 0

        def chat_with_tools_stream(self, messages, tools, system_prompt=""):
            evs = self._streams[self._i] if self._i < len(self._streams) else []
            self._i += 1
            yield from evs

    class _FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return "desc"

    class _FakeRouter:
        def __init__(self):
            self._text_client = _FakeStreamText()
            self._vision_client = _FakeVision()

    monkeypatch.setattr(papers, "ROUTER", _FakeRouter())

    list(papers.chat_events(key, "问题?"))

    obs_file = cache_dir / f"{key}-observations.json"
    assert obs_file.exists()
    data = json.loads(obs_file.read_text(encoding="utf-8"))
    assert data["observations"][0]["summary"] == "发现X"
    assert data["observations"][0]["question"] == "问题?"


def test_clear_chat_history_also_clears_observations(tmp_path, monkeypatch):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"pdfdata")
    key = papers._paper_id_for_path(str(pdf))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    monkeypatch.setattr("paper_reader.observations.CACHE_DIR", cache_dir)
    session = papers.Session(_make_paper(str(pdf)))
    session.ctx.add_message("user", "问题")
    from paper_reader.agent import Observation
    session.ctx.observations.append(Observation(summary="发现", question="问题"))
    papers.sessions[key] = session
    papers.save_chat_history(key, session.ctx.history)
    papers.save_observations(str(pdf), [o.to_dict() for o in session.ctx.observations])
    assert (cache_dir / f"{key}-observations.json").exists()

    papers.clear_chat_history(key)
    assert session.ctx.history == []
    assert session.ctx.observations == []
    assert not (cache_dir / f"{key}-observations.json").exists()
