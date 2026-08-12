from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Iterator

from paper_reader.agent import PaperAgent
from paper_reader.blocks import PaperDocument
from paper_reader.context import ConversationContext
from paper_reader.mineru_parser import MinerUParser

CACHE_DIR = Path.home() / ".cache" / "paper-master"
PARSER = MinerUParser()
ROUTER = None

sessions: dict[str, "Session"] = {}
parse_tasks: dict[str, dict] = {}
CHAT_LOCK = threading.Lock()
PARSE_LOCK = threading.Lock()


class Session:
    def __init__(self, paper: PaperDocument):
        self.paper = paper
        self.ctx = ConversationContext(paper)
        self.lock = threading.Lock()


def _get_router():
    global ROUTER
    if ROUTER is None:
        from paper_reader.llm import LLMRouter, load_config
        ROUTER = LLMRouter(load_config("config.yaml"))
    return ROUTER


def _paper_id_for_path(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def open_paper(pdf_path: str) -> dict:
    paper_id = _paper_id_for_path(pdf_path)
    if paper_id in sessions:
        return {"paper_id": paper_id, "status": "ready"}

    cache_file = CACHE_DIR / f"{paper_id}.json"
    if cache_file.exists():
        with open(cache_file, encoding="utf-8") as f:
            paper = PaperDocument.from_dict(json.load(f))
        sessions[paper_id] = Session(paper)
        parse_tasks[paper_id] = {"status": "ready"}
        return {"paper_id": paper_id, "status": "ready"}

    parse_tasks[paper_id] = {"status": "parsing", "message": "正在版面解析 (MinerU)..."}

    def _worker() -> None:
        try:
            with PARSE_LOCK:
                paper = PARSER.parse(pdf_path)
            from paper_reader.memory import load_memory_cache
            paper.memory = load_memory_cache(paper)
            sessions[paper_id] = Session(paper)
            parse_tasks[paper_id] = {"status": "ready"}
        except Exception as e:
            parse_tasks[paper_id] = {"status": "error", "message": str(e)}

    threading.Thread(target=_worker, daemon=True).start()
    return {"paper_id": paper_id, "status": "parsing"}


def get_status(paper_id: str) -> dict:
    task = parse_tasks.get(paper_id)
    if task is None:
        return {"status": "unknown"}
    return dict(task)


def _require_session(paper_id: str) -> Session:
    session = sessions.get(paper_id)
    if session is None:
        raise KeyError(paper_id)
    return session


def get_overview(paper_id: str) -> dict:
    session = _require_session(paper_id)
    toc = []
    seen = set()
    for b in session.paper.blocks:
        if b.level > 0:
            title = b.text.strip()
            if title not in seen:
                seen.add(title)
                toc.append({"title": title, "level": b.level})
    return {"title": session.paper.title,
            "abstract": session.paper.abstract, "toc": toc}


def get_content(paper_id: str) -> str:
    session = _require_session(paper_id)
    result_dir = Path(session.paper.result_dir)
    md_files = sorted(result_dir.glob("*.md"))
    if not md_files:
        return ""
    text = md_files[0].read_text(encoding="utf-8", errors="replace")

    def _rewrite(m: re.Match) -> str:
        rel = m.group(2)
        quoted = urllib.parse.quote(rel.lstrip("/"))
        return f"![{m.group(1)}](/api/papers/{paper_id}/images/{quoted})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _rewrite, text)


def get_image_path(paper_id: str, relpath: str) -> Path | None:
    session = _require_session(paper_id)
    result_dir = Path(session.paper.result_dir).resolve()
    target = (result_dir / relpath).resolve()
    if not str(target).startswith(str(result_dir) + "/"):
        return None
    if not target.is_file():
        return None
    return target


def chat_events(paper_id: str, question: str) -> Iterator[tuple[str, dict]]:
    """Drive PaperAgent in a worker thread, yielding SSE events to the caller."""
    try:
        session = _require_session(paper_id)
    except KeyError:
        yield ("error", {"message": "paper not parsed"})
        return

    ctx = session.ctx
    ctx.add_message("user", question)
    q: "queue.Queue[tuple | None]" = queue.Queue()

    def on_event(etype: str, payload: dict) -> None:
        q.put((etype, payload))

    def _worker() -> None:
        try:
            router = _get_router()
            with session.lock, CHAT_LOCK:
                agent = PaperAgent(
                    text_client=router._text_client,
                    vision_client=router._vision_client,
                    ctx=ctx,
                )
                answer = agent.run_stream(
                    question, history=ctx.history[:-1],
                    memory=ctx.paper.memory, on_event=on_event,
                )
            ctx.add_message("assistant", answer)
        except Exception as e:
            q.put(("error", {"message": str(e)}))
        finally:
            q.put(None)

    threading.Thread(target=_worker, daemon=True).start()
    while True:
        item = q.get()
        if item is None:
            yield ("done", {})
            return
        yield item
