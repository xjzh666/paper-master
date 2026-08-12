from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ZoteroItem:
    item_id: int
    key: str
    title: str
    creators: list[str]
    year: int | None
    item_type: str
    publication: str | None
    doi: str | None
    collections: list[str]
    has_pdf: bool = False
    pdf_path: Path | None = None


_NON_READABLE = ("attachment", "note", "annotation")


def _format_creator(first_name, last_name, field_mode):
    if field_mode:
        return last_name or first_name or ""
    return " ".join(p for p in (first_name, last_name) if p)


def _parse_year(date_value):
    if not date_value:
        return None
    m = re.search(r"\d{4}", date_value)
    return int(m.group()) if m else None


@dataclass
class ZoteroCollection:
    collection_id: int
    name: str
    parent_id: int | None
    item_count: int


class ZoteroLibrary:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        db = self.data_dir / "zotero.sqlite"
        if not db.exists():
            raise FileNotFoundError(
                f"Zotero 数据库不存在: {db}，请在 config.yaml 配置 zotero.data_dir"
            )
        self._conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def collections(self) -> list[ZoteroCollection]:
        cur = self._conn.execute("""
            SELECT c.collectionID, c.collectionName, c.parentCollectionID,
                   (SELECT COUNT(*) FROM collectionItems ci
                     JOIN items i ON ci.itemID = i.itemID
                     JOIN itemTypes t ON i.itemTypeID = t.itemTypeID
                    WHERE ci.collectionID = c.collectionID
                      AND t.typeName NOT IN ('attachment', 'note', 'annotation')
                      AND i.itemID NOT IN (SELECT itemID FROM deletedItems)) AS n
            FROM collections c
            WHERE c.collectionID NOT IN (SELECT collectionID FROM deletedCollections)
            ORDER BY c.collectionName
        """)
        return [ZoteroCollection(r["collectionID"], r["collectionName"],
                                r["parentCollectionID"], r["n"]) for r in cur]

    def items(self, collection_id: int | None = None) -> list[ZoteroItem]:
        ph = ",".join("?" * len(_NON_READABLE))
        base = f"""
            SELECT i.itemID, i.key, t.typeName
            FROM items i JOIN itemTypes t ON i.itemTypeID = t.itemTypeID
            WHERE t.typeName NOT IN ({ph})
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
        """
        params: list = list(_NON_READABLE)
        if collection_id is not None:
            base += " AND i.itemID IN (SELECT itemID FROM collectionItems WHERE collectionID = ?)"
            params.append(collection_id)
        rows = self._conn.execute(base + " ORDER BY i.itemID", params).fetchall()
        if not rows:
            return []
        ids = [r["itemID"] for r in rows]
        return self._assemble(rows, ids)

    def search(self, keyword: str, limit: int = 20) -> list[ZoteroItem]:
        kw = keyword.lower()
        result = [
            it for it in self.items()
            if kw in it.title.lower()
            or any(kw in c.lower() for c in it.creators)
        ]
        result.sort(key=lambda it: it.title.lower())
        return result[:limit]

    def get_item(self, item_id: int) -> ZoteroItem | None:
        ph = ",".join("?" * len(_NON_READABLE))
        rows = self._conn.execute(f"""
            SELECT i.itemID, i.key, t.typeName
            FROM items i JOIN itemTypes t ON i.itemTypeID = t.itemTypeID
            WHERE i.itemID = ?
              AND t.typeName NOT IN ({ph})
              AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
        """, [item_id, *_NON_READABLE]).fetchall()
        if not rows:
            return None
        return self._assemble(rows, [rows[0]["itemID"]])[0]

    def _assemble(self, rows, ids):
        ph = ",".join("?" * len(ids))
        meta: dict[int, dict[str, str]] = {}
        for r in self._conn.execute(f"""
            SELECT d.itemID, f.fieldName, v.value
            FROM itemData d
            JOIN fields f ON d.fieldID = f.fieldID
            JOIN itemDataValues v ON d.valueID = v.valueID
            WHERE d.itemID IN ({ph})
        """, ids):
            meta.setdefault(r["itemID"], {})[r["fieldName"]] = r["value"]
        creators: dict[int, list[str]] = {}
        for r in self._conn.execute(f"""
            SELECT ic.itemID, cr.firstName, cr.lastName, cr.fieldMode
            FROM itemCreators ic
            JOIN creators cr ON ic.creatorID = cr.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            WHERE ic.itemID IN ({ph}) AND ct.creatorType = 'author'
            ORDER BY ic.itemID, ic.orderIndex
        """, ids):
            creators.setdefault(r["itemID"], []).append(
                _format_creator(r["firstName"], r["lastName"], r["fieldMode"])
            )
        colls: dict[int, list[str]] = {}
        for r in self._conn.execute(f"""
            SELECT ci.itemID, c.collectionName
            FROM collectionItems ci
            JOIN collections c ON ci.collectionID = c.collectionID
            WHERE ci.itemID IN ({ph})
              AND c.collectionID NOT IN (SELECT collectionID FROM deletedCollections)
        """, ids):
            colls.setdefault(r["itemID"], []).append(r["collectionName"])
        atts: dict[int, tuple[str, str]] = {}
        for r in self._conn.execute(f"""
            SELECT a.parentItemID, a.path, i.key AS attach_key
            FROM itemAttachments a
            JOIN items i ON a.itemID = i.itemID
            WHERE a.parentItemID IN ({ph}) AND a.contentType = 'application/pdf'
        """, ids):
            atts[r["parentItemID"]] = (r["path"], r["attach_key"])
        items = []
        for r in rows:
            m = meta.get(r["itemID"], {})
            pdf_path = self._resolve_pdf_path(atts.get(r["itemID"]))
            items.append(ZoteroItem(
                item_id=r["itemID"],
                key=r["key"],
                title=m.get("title") or "(无标题)",
                creators=creators.get(r["itemID"], []),
                year=_parse_year(m.get("date")),
                item_type=r["typeName"],
                publication=m.get("publicationTitle") or None,
                doi=m.get("DOI") or None,
                collections=colls.get(r["itemID"], []),
                has_pdf=pdf_path is not None,
                pdf_path=pdf_path,
            ))
        return items

    def _resolve_pdf_path(self, att):
        if att is None:
            return None
        path, attach_key = att
        if path.startswith("storage:"):
            full = self.data_dir / "storage" / attach_key / path[len("storage:"):]
        else:
            full = Path(path)
        if full.exists() and full.is_file():
            return full
        return None

    def resolve_pdf(self, item: ZoteroItem) -> Path | None:
        return item.pdf_path


def _autodetect_candidates() -> list[Path]:
    candidates = [Path.home() / "Zotero"]
    candidates += sorted(Path("/mnt/c/Users").glob("*/Zotero"), key=str)
    return candidates


def resolve_zotero_data_dir(config: dict | None = None) -> Path:
    configured = (config or {}).get("zotero", {}).get("data_dir")
    if configured:
        p = Path(configured)
        if (p / "zotero.sqlite").exists():
            return p
    for p in _autodetect_candidates():
        if (p / "zotero.sqlite").exists():
            return p
    raise FileNotFoundError(
        "未找到 Zotero 数据库，请在 config.yaml 配置 zotero.data_dir"
    )
