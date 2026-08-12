from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


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
