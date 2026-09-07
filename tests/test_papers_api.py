import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import paper_reader.papers as papers
from paper_reader.blocks import PaperDocument, ContentBlock
from paper_reader.server import create_app


@pytest.fixture(autouse=True)
def _clean_state():
    papers.sessions.clear()
    papers.parse_tasks.clear()
    yield
    papers.sessions.clear()
    papers.parse_tasks.clear()


def _seed_cached_paper(zotero_db, tmp_path, monkeypatch):
    """Seed cache for zotero item 1's pdf, return its paper_id."""
    pdf_path = zotero_db / "storage" / "ATT11" / "Honeypot Evolution.pdf"
    key = papers._paper_id_for_path(str(pdf_path))
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "paper.md").write_text(
        "## Intro\n\nText ![fig](images/a.png)", encoding="utf-8")
    paper = PaperDocument(filepath=str(pdf_path), title="Honeypot Evolution",
                          abstract="abs", result_dir=str(result_dir),
                          blocks=[ContentBlock(type="text", text="Intro",
                                               level=1, page_idx=0)],
                          chunks=[])
    (cache_dir / f"{key}.json").write_text(
        json.dumps(paper.to_dict()), encoding="utf-8")
    monkeypatch.setattr(papers, "CACHE_DIR", cache_dir)
    return key


def test_open_endpoint_ready(zotero_db, tmp_path, monkeypatch):
    key = _seed_cached_paper(zotero_db, tmp_path, monkeypatch)
    app = create_app(zotero_db)
    with TestClient(app) as client:
        res = client.post("/api/papers/open", json={"zotero_item_id": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["paper_id"] == key
    assert body["status"] == "ready"


def test_overview_and_content_endpoints(zotero_db, tmp_path, monkeypatch):
    key = _seed_cached_paper(zotero_db, tmp_path, monkeypatch)
    papers.sessions[key] = papers.Session(
        PaperDocument(filepath="/tmp/x", title="Honeypot Evolution",
                      abstract="abs", result_dir=str(tmp_path / "result"),
                      blocks=[ContentBlock(type="text", text="Intro",
                                           level=1, page_idx=0)],
                      chunks=[]))
    app = create_app(zotero_db)
    with TestClient(app) as client:
        ov = client.get(f"/api/papers/{key}/overview")
        ct = client.get(f"/api/papers/{key}/content")
    assert ov.status_code == 200
    assert ov.json()["title"] == "Honeypot Evolution"
    assert ct.status_code == 200
    assert "## Intro" in ct.json()["markdown"]


def test_open_endpoint_no_pdf(zotero_db, tmp_path, monkeypatch):
    _seed_cached_paper(zotero_db, tmp_path, monkeypatch)
    app = create_app(zotero_db)
    with TestClient(app) as client:
        res = client.post("/api/papers/open", json={"zotero_item_id": 6})
    assert res.status_code == 404  # Ghost Paper has no pdf


def test_open_endpoint_unknown_item(zotero_db, tmp_path, monkeypatch):
    _seed_cached_paper(zotero_db, tmp_path, monkeypatch)
    app = create_app(zotero_db)
    with TestClient(app) as client:
        res = client.post("/api/papers/open", json={"zotero_item_id": 999})
    assert res.status_code == 404


def test_chat_endpoint_streams_sse(zotero_db, tmp_path, monkeypatch):
    key = _seed_cached_paper(zotero_db, tmp_path, monkeypatch)
    paper = PaperDocument(filepath="/tmp/x", title="Honeypot Evolution",
                          abstract="", result_dir=str(tmp_path / "result"),
                          blocks=[], chunks=[])
    papers.sessions[key] = papers.Session(paper)

    class _FakeStreamText:
        def __init__(self):
            self._streams = [
                [("text_delta", "查一下"),
                 ("tool_calls", [{"id": "c1", "name": "search_paper",
                                  "arguments": '{"query":"x"}'}])],
                [("text_delta", "答案"), ("tool_calls", [])],
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
        _text_client = _FakeStreamText()
        _vision_client = _FakeVision()

    monkeypatch.setattr(papers, "ROUTER", _FakeRouter())

    app = create_app(zotero_db)
    with TestClient(app) as client:
        res = client.post(f"/api/papers/{key}/chat", json={"question": "hi"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert "event: tool_start" in res.text
    assert "event: answer_chunk" in res.text
    assert "event: done" in res.text


def test_history_endpoints_get_and_delete(zotero_db, tmp_path, monkeypatch):
    key = _seed_cached_paper(zotero_db, tmp_path, monkeypatch)
    cache_dir = tmp_path / "cache"
    paper = PaperDocument(filepath="/tmp/x", title="Honeypot Evolution",
                          abstract="", result_dir=str(tmp_path / "result"),
                          blocks=[], chunks=[])
    session = papers.Session(paper)
    session.ctx.add_message("user", "问题")
    session.ctx.add_message("assistant", "答案")
    papers.sessions[key] = session
    papers.save_chat_history(key, session.ctx.history)

    app = create_app(zotero_db)
    with TestClient(app) as client:
        res = client.get(f"/api/papers/{key}/history")
        assert res.status_code == 200
        assert [m["role"] for m in res.json()["messages"]] == ["user", "assistant"]
        res = client.delete(f"/api/papers/{key}/history")
        assert res.status_code == 200
        res = client.get(f"/api/papers/{key}/history")
        assert res.json()["messages"] == []
    assert not (cache_dir / f"{key}-history.json").exists()


def test_history_endpoint_unknown_paper_returns_empty(zotero_db, tmp_path, monkeypatch):
    _seed_cached_paper(zotero_db, tmp_path, monkeypatch)
    app = create_app(zotero_db)
    with TestClient(app) as client:
        res = client.get("/api/papers/unknown/history")
    assert res.status_code == 200
    assert res.json()["messages"] == []


def test_delete_history_also_clears_observations(zotero_db, tmp_path, monkeypatch):
    key = _seed_cached_paper(zotero_db, tmp_path, monkeypatch)
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("paper_reader.observations.CACHE_DIR", cache_dir)
    from paper_reader.agent import Observation
    pdf_path = zotero_db / "storage" / "ATT11" / "Honeypot Evolution.pdf"
    session = papers.Session(PaperDocument(filepath=str(pdf_path), title="t",
                                           blocks=[], chunks=[]))
    session.ctx.observations.append(Observation(summary="发现", question="q"))
    papers.sessions[key] = session
    papers.save_observations(str(pdf_path),
                             [o.to_dict() for o in session.ctx.observations])
    assert (cache_dir / f"{key}-observations.json").exists()

    app = create_app(zotero_db)
    with TestClient(app) as client:
        res = client.delete(f"/api/papers/{key}/history")
    assert res.status_code == 200
    assert session.ctx.observations == []
    assert not (cache_dir / f"{key}-observations.json").exists()
