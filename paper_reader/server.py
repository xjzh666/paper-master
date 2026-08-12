from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

from paper_reader.llm import load_config
from paper_reader.zotero import ZoteroLibrary, resolve_zotero_data_dir


def _config_data_dir() -> Path:
    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        config = None
    return resolve_zotero_data_dir(config)


def create_app(data_dir: Path | None = None) -> FastAPI:
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

    return app


app = create_app()
