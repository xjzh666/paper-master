from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Iterator

from paper_reader.agent import Observation, PaperAgent
from paper_reader.blocks import PaperDocument
from paper_reader.context import ConversationContext
from paper_reader.memory import extract_memory, load_memory_cache
from paper_reader.mineru_parser import MinerUParser
from paper_reader.observations import (clear_observations, load_observations,
                                       save_observations)

CACHE_DIR = Path.home() / ".cache" / "paper-master"
PARSER = MinerUParser()
ROUTER = None

sessions: dict[str, "Session"] = {}
parse_tasks: dict[str, dict] = {}
memory_jobs: set[str] = set()
CHAT_LOCK = threading.Lock()
PARSE_LOCK = threading.Lock()
MEMORY_JOB_LOCK = threading.Lock()


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


def _ensure_memory_background(paper_id: str) -> None:
    """Extract Paper Memory in a background thread if it is missing.

    Mirrors the CLI path (main.py Phase 3): only extract when no cache was
    loaded; failure leaves paper.memory as None and chat degrades to pure RAG.
    """
    session = sessions.get(paper_id)
    if session is None or session.paper.memory is not None:
        return
    paper = session.paper
    with MEMORY_JOB_LOCK:
        if paper_id in memory_jobs:
            return
        memory_jobs.add(paper_id)

    def _worker() -> None:
        try:
            router = _get_router()
            paper.memory = extract_memory(paper, router._text_client)
        except Exception:
            pass
        finally:
            with MEMORY_JOB_LOCK:
                memory_jobs.discard(paper_id)

    threading.Thread(target=_worker, daemon=True).start()


def _history_cache_path(paper_id: str) -> Path:
    return CACHE_DIR / f"{paper_id}-history.json"


def load_chat_history(paper_id: str) -> list[dict]:
    path = _history_cache_path(paper_id)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            messages = json.load(f).get("messages", [])
        return [
            m for m in messages
            if isinstance(m, dict)
            and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)
        ]
    except (json.JSONDecodeError, IOError, AttributeError):
        return []


def save_chat_history(paper_id: str, history: list[dict]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_history_cache_path(paper_id), "w", encoding="utf-8") as f:
            json.dump({"paper_id": paper_id, "messages": history}, f,
                      ensure_ascii=False, indent=2)
    except (IOError, OSError, TypeError):
        pass


def get_chat_history(paper_id: str) -> list[dict]:
    """Live session history if available; fall back to the persisted file."""
    session = sessions.get(paper_id)
    if session is not None:
        return list(session.ctx.history)
    return load_chat_history(paper_id)


def clear_chat_history(paper_id: str) -> None:
    session = sessions.get(paper_id)
    if session is not None:
        session.ctx.history.clear()
        session.ctx.observations.clear()
    clear_observations(paper_id)
    try:
        _history_cache_path(paper_id).unlink(missing_ok=True)
    except OSError:
        pass


def _restore_session_state(session: Session, paper_id: str) -> None:
    """Load persisted per-session state (history + observations) onto ctx."""
    session.ctx.history = load_chat_history(paper_id)
    session.ctx.observations = [
        Observation.from_dict(o)
        for o in load_observations(session.paper.filepath)
    ]


def open_paper(pdf_path: str) -> dict:
    paper_id = _paper_id_for_path(pdf_path)
    if paper_id in sessions:
        return {"paper_id": paper_id, "status": "ready"}

    cache_file = CACHE_DIR / f"{paper_id}.json"
    if cache_file.exists():
        with open(cache_file, encoding="utf-8") as f:
            paper = PaperDocument.from_dict(json.load(f))
        if paper.memory is None:
            paper.memory = load_memory_cache(paper)
        session = Session(paper)
        _restore_session_state(session, paper_id)
        sessions[paper_id] = session
        parse_tasks[paper_id] = {"status": "ready"}
        _ensure_memory_background(paper_id)
        return {"paper_id": paper_id, "status": "ready"}

    parse_tasks[paper_id] = {"status": "parsing", "message": "正在版面解析 (MinerU)..."}

    def _worker() -> None:
        try:
            with PARSE_LOCK:
                paper = PARSER.parse(pdf_path)
            paper.memory = load_memory_cache(paper)
            session = Session(paper)
            _restore_session_state(session, paper_id)
            sessions[paper_id] = session
            parse_tasks[paper_id] = {"status": "ready"}
            _ensure_memory_background(paper_id)
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

    # Normalize OCR'd LaTeX (math blocks) + prose OCR/encoding cleanup.
    from paper_reader.math_quality import fix_paper_markdown
    text = fix_paper_markdown(text)

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
            save_chat_history(paper_id, ctx.history)
            save_observations(session.paper.filepath,
                              [o.to_dict() for o in ctx.observations])
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
