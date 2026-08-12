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
    yield
    papers.sessions.clear()
    papers.parse_tasks.clear()


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
