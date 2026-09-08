from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

import paper_reader.papers as papers
from paper_reader.llm import load_config
from paper_reader.zotero import ZoteroLibrary, resolve_zotero_data_dir


def _config_data_dir() -> Path:
    try:
        config = load_config("config.yaml")
    except (FileNotFoundError, yaml.YAMLError):
        config = None
    try:
        return resolve_zotero_data_dir(config)
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="未找到 Zotero 数据库，请在 config.yaml 配置 zotero.data_dir",
        )


def create_app(data_dir: Path | None = None,
               frontend_dist: str | None = None) -> FastAPI:
    app = FastAPI(title="paper-master", version="0.1.0")

    def get_library():
        base = data_dir if data_dir is not None else _config_data_dir()
        lib = ZoteroLibrary(base)
        try:
            yield lib
        finally:
            lib.close()

    def item_dict(it):
        d = asdict(it)
        d["pdf_path"] = str(d["pdf_path"]) if d["pdf_path"] else None
        return d

    @app.get("/api/zotero/collections")
    def collections(lib: ZoteroLibrary = Depends(get_library)):
        return [asdict(c) for c in lib.collections()]

    @app.get("/api/zotero/items")
    def items(collection_id: int | None = None,
              lib: ZoteroLibrary = Depends(get_library)):
        return [item_dict(i) for i in lib.items(collection_id=collection_id)]

    @app.get("/api/zotero/search")
    def search(q: str, lib: ZoteroLibrary = Depends(get_library)):
        return [item_dict(i) for i in lib.search(q)]

    @app.get("/api/zotero/items/{item_id}")
    def item(item_id: int, lib: ZoteroLibrary = Depends(get_library)):
        it = lib.get_item(item_id)
        if it is None:
            raise HTTPException(status_code=404, detail="item not found")
        return item_dict(it)

    @app.post("/api/papers/open")
    def open_paper(body: dict, lib: ZoteroLibrary = Depends(get_library)):
        item_id = body.get("zotero_item_id")
        if item_id is None:
            raise HTTPException(status_code=400, detail="missing zotero_item_id")
        item = lib.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        pdf = lib.resolve_pdf(item)
        if pdf is None:
            raise HTTPException(status_code=404, detail="item has no PDF")
        return papers.open_paper(str(pdf))

    @app.get("/api/papers/{paper_id}/status")
    def paper_status(paper_id: str):
        return papers.get_status(paper_id)

    @app.get("/api/papers/{paper_id}/overview")
    def paper_overview(paper_id: str):
        try:
            return papers.get_overview(paper_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="paper not parsed")

    @app.get("/api/papers/{paper_id}/content")
    def paper_content(paper_id: str):
        try:
            return {"markdown": papers.get_content(paper_id)}
        except KeyError:
            raise HTTPException(status_code=404, detail="paper not parsed")

    @app.get("/api/papers/{paper_id}/chunks-index")
    def paper_chunks_index(paper_id: str):
        try:
            return papers.get_chunks_index(paper_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="paper not parsed")

    @app.get("/api/papers/{paper_id}/history")
    def paper_history(paper_id: str):
        return {"messages": papers.get_chat_history(paper_id)}

    @app.delete("/api/papers/{paper_id}/history")
    def paper_history_clear(paper_id: str):
        papers.clear_chat_history(paper_id)
        return {"ok": True}

    @app.get("/api/papers/{paper_id}/images/{relpath:path}")
    def paper_image(paper_id: str, relpath: str):
        p = papers.get_image_path(paper_id, relpath)
        if p is None:
            raise HTTPException(status_code=404, detail="image not found")
        return FileResponse(p)

    @app.post("/api/papers/{paper_id}/chat")
    def paper_chat(paper_id: str, body: dict):
        question = (body.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="empty question")

        def gen():
            for etype, payload in papers.chat_events(paper_id, question):
                yield f"event: {etype}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    if frontend_dist is None:
        frontend_dist = str(Path(__file__).resolve().parent.parent / "frontend" / "dist")
    if Path(frontend_dist).is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=frontend_dist, html=True),
                  name="frontend")

    return app


app = create_app()
