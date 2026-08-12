# Zotero Connection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read papers + metadata from a local Zotero library (PDF on disk, no manual placement) and feed them into the existing paper-master pipeline, exposed via both a CLI (`main.py --zotero`) and a thin FastAPI layer — all sharing one read-only data module.

**Architecture:** A new `paper_reader/zotero.py` is the single shared core: it opens the Zotero sqlite read-only, assembles `ZoteroItem` objects (metadata + creators + collections + resolved PDF path), and offers `collections()/items()/search()/get_item()/resolve_pdf()`. Two thin consumers on top: `main.py --zotero` (selection loop → existing `interactive_loop`) and `paper_reader/server.py` (4 GET endpoints, per-request dependency-injected library). Spec: `docs/superpowers/specs/2026-08-12-zotero-connection-design.md`.

**Tech Stack:** Python 3.10+, stdlib `sqlite3` (read-only URI), `dataclasses`, `pathlib`, `prompt_toolkit` (existing), `fastapi` 0.139.0 + `uvicorn` 0.51.0 + `httpx` 0.28.1 (already installed in venv), pytest.

## Global Constraints

- **Read-only, always:** open sqlite with `file:{db}?mode=ro`, never write to any Zotero file.
- **Readable items only:** exclude `itemTypes.typeName IN ('attachment','note','annotation')` AND exclude `itemID IN deletedItems`.
- **PDF resolution:** if attachment `path` starts with `"storage:"`, the file is at `{data_dir}/storage/{attachment_item.key}/{path-minus-storage-prefix}`; else treat `path` as an absolute filesystem path. Only set `has_pdf=True` / `pdf_path` when `os.path.exists()` and it's a file.
- **Authors:** join `creatorTypes`, keep only `creatorType = 'author'`, ordered by `itemCreators.orderIndex`. `creators.fieldMode=1` means `lastName` holds the full single name.
- **Year:** first `\d{4}` match in the `date` field value; `None` if absent/unparseable.
- **Search:** case-insensitive substring on `title` and creator names, results sorted by lowercase title, capped at `limit` (default 20).
- **API scope (this phase):** only `collections` / `items` / `search` / `items/{id}` — no paper-content or conversation endpoints.
- Existing code conventions: no comments unless the WHY is non-obvious; follow existing `paper_reader/` style; all commits via `git add <files>` + heredoc message.

---

### Task 1: Test fixture + ZoteroLibrary collections()

The shared sqlite fixture is the foundation every later test uses. It builds a minimal copy of the real Zotero schema (only the tables/columns our queries touch) plus seed data covering every branch later tasks exercise.

**Files:**
- Create: `tests/conftest.py`
- Create: `paper_reader/zotero.py`
- Create: `tests/test_zotero.py`

**Interfaces:**
- Consumes: nothing.
- Produces: pytest fixture `zotero_db(tmp_path) -> pathlib.Path` (a dir containing `zotero.sqlite`); `paper_reader.zotero.ZoteroCollection(collection_id: int, name: str, parent_id: int | None, item_count: int)`; `paper_reader.zotero.ZoteroLibrary(data_dir: str | pathlib.Path)` with `.close()`, `.collections() -> list[ZoteroCollection]`, and attribute `data_dir: pathlib.Path`.

- [ ] **Step 1: Write the fixture in `tests/conftest.py`**

```python
import sqlite3

import pytest


def _create_schema(cur: sqlite3.Cursor) -> None:
    cur.executescript("""
        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT, itemTypeID INT);
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT,
                               lastName TEXT, fieldMode INT);
        CREATE TABLE itemCreators (itemID INT, creatorID INT, creatorTypeID INT,
                                   orderIndex INT);
        CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
        CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT,
                                  parentCollectionID INT);
        CREATE TABLE collectionItems (collectionID INT, itemID INT);
        CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INT,
                                      linkMode INT, contentType TEXT, path TEXT);
        CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY, dateDeleted TEXT);
        CREATE TABLE deletedCollections (collectionID INTEGER PRIMARY KEY);
    """)


def _seed(cur: sqlite3.Cursor, data_dir, tmp_path) -> None:
    cur.executemany("INSERT INTO creatorTypes VALUES (?,?)",
                    [(1, "author"), (10, "editor")])
    cur.executemany("INSERT INTO itemTypes VALUES (?,?)",
                    [(1, "journalArticle"), (2, "conferencePaper"), (3, "preprint"),
                     (4, "note"), (5, "attachment")])
    cur.executemany("INSERT INTO fields VALUES (?,?)",
                    [(1, "title"), (2, "date"), (3, "DOI"), (4, "publicationTitle")])
    cur.executemany("INSERT INTO collections VALUES (?,?,?)",
                    [(1, "课题组", None), (2, "蜜罐", 1), (3, "研讨厅第一篇", None),
                     (4, "已删除收藏夹", None)])
    cur.execute("INSERT INTO deletedCollections VALUES (4)")
    # items: 1-3 readable, 4 deleted, 5 note, 6 ghost(no pdf file), 11/13/17 attachments
    cur.executemany("INSERT INTO items VALUES (?,?,?)",
                    [(1, "ITEM1", 1), (2, "ITEM2", 2), (3, "ITEM3", 3),
                     (4, "DELETED", 1), (5, "NOTE5", 4), (6, "GHOST6", 1),
                     (11, "ATT11", 5), (13, "ATT13", 5), (17, "ATT17", 5)])
    cur.execute("INSERT INTO deletedItems VALUES (4, '2024-01-01 00:00:00')")
    cur.executemany("INSERT INTO itemData VALUES (?,?,?)",
                    [(1, 1, 1), (1, 2, 2), (1, 3, 3), (1, 4, 4),
                     (2, 1, 5), (2, 2, 6), (3, 1, 7), (3, 2, 8), (6, 1, 9)])
    cur.executemany("INSERT INTO itemDataValues VALUES (?,?)",
                    [(1, "Honeypot Evolution"), (2, "2024-03-00 2024"),
                     (3, "10.1000/example"), (4, "Security"),
                     (5, "Agentic AI Threats"), (6, "2023"),
                     (7, "Retrieval for Science"), (8, "2022-07-01 2022-7-1"),
                     (9, "Ghost Paper")])
    cur.executemany("INSERT INTO creators VALUES (?,?,?,?)",
                    [(1, "Alice", "Smith", 0), (2, "Bob", "Jones", 0),
                     (3, "Carol", "Brown", 0), (4, "", "Dave", 1),
                     (5, "George", "Editor", 0)])
    # item 1: Alice+Bob authors; item 2: Carol author + George editor(excluded);
    # item 3: Dave single-field author
    cur.executemany("INSERT INTO itemCreators VALUES (?,?,?,?)",
                    [(1, 1, 1, 1), (1, 2, 1, 2),
                     (2, 3, 1, 1), (2, 5, 10, 2),
                     (3, 4, 1, 1)])
    cur.executemany("INSERT INTO collectionItems VALUES (?,?)",
                    [(1, 1), (2, 1), (3, 2)])
    storage_dir = data_dir / "storage" / "ATT11"
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "Honeypot Evolution.pdf").write_bytes(b"%PDF-1.4 dummy")
    linked_pdf = tmp_path / "linked.pdf"
    linked_pdf.write_text("dummy")
    cur.executemany("INSERT INTO itemAttachments VALUES (?,?,?,?,?)",
                    [(11, 1, 0, "application/pdf", "storage:Honeypot Evolution.pdf"),
                     (13, 3, 2, "application/pdf", str(linked_pdf)),
                     (17, 6, 0, "application/pdf", "storage:Ghost.pdf")])


@pytest.fixture
def zotero_db(tmp_path):
    data_dir = tmp_path / "zotero"
    data_dir.mkdir()
    con = sqlite3.connect(str(data_dir / "zotero.sqlite"))
    cur = con.cursor()
    _create_schema(cur)
    _seed(cur, data_dir, tmp_path)
    con.commit()
    con.close()
    return data_dir
```

- [ ] **Step 2: Write the failing test in `tests/test_zotero.py`**

```python
from paper_reader.zotero import ZoteroLibrary


def test_collections_tree(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        by_name = {c.name: c for c in lib.collections()}
    finally:
        lib.close()
    assert set(by_name) == {"课题组", "蜜罐", "研讨厅第一篇"}  # deleted collection excluded
    assert by_name["课题组"].parent_id is None
    assert by_name["蜜罐"].parent_id == by_name["课题组"].collection_id
    assert by_name["课题组"].item_count == 1
    assert by_name["研讨厅第一篇"].item_count == 1
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py::test_collections_tree -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paper_reader.zotero'`

- [ ] **Step 4: Implement `paper_reader/zotero.py` (collections only)**

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py::test_collections_tree -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py paper_reader/zotero.py tests/test_zotero.py
git commit -m "feat: add Zotero read layer with collections tree and test fixture"
```

---

### Task 2: Item metadata assembly

`items()` loads all readable items and assembles `ZoteroItem` objects with title, creators, year, item type, publication, DOI, and collection names.

**Files:**
- Modify: `paper_reader/zotero.py`
- Modify: `tests/test_zotero.py`

**Interfaces:**
- Consumes: `ZoteroLibrary` (Task 1), fixture `zotero_db`.
- Produces: `paper_reader.zotero.ZoteroItem(item_id: int, key: str, title: str, creators: list[str], year: int | None, item_type: str, publication: str | None, doi: str | None, collections: list[str], has_pdf: bool = False, pdf_path: Path | None = None)`; `ZoteroLibrary.items(collection_id: int | None = None) -> list[ZoteroItem]`; module helpers `_format_creator(first_name: str | None, last_name: str | None, field_mode: int) -> str` and `_parse_year(date_value: str | None) -> int | None`.

- [ ] **Step 1: Write the failing tests in `tests/test_zotero.py`**

```python
from paper_reader.zotero import ZoteroLibrary


def _item_by_title(lib, title):
    for it in lib.items():
        if it.title == title:
            return it
    raise AssertionError(f"item not found: {title}")


def test_item_metadata(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = _item_by_title(lib, "Honeypot Evolution")
    finally:
        lib.close()
    assert it.item_type == "journalArticle"
    assert it.creators == ["Alice Smith", "Bob Jones"]
    assert it.year == 2024
    assert it.publication == "Security"
    assert it.doi == "10.1000/example"
    assert set(it.collections) == {"课题组", "蜜罐"}
    assert it.key == "ITEM1"


def test_item_editors_excluded_and_single_field(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = _item_by_title(lib, "Agentic AI Threats")
        it3 = _item_by_title(lib, "Retrieval for Science")
    finally:
        lib.close()
    assert it.creators == ["Carol Brown"]  # editor George excluded
    assert it3.creators == ["Dave"]  # fieldMode=1: lastName holds full name


def test_item_year_parsing(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = _item_by_title(lib, "Retrieval for Science")
    finally:
        lib.close()
    assert it.year == 2022


def test_deleted_and_note_items_excluded(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        titles = [it.title for it in lib.items()]
    finally:
        lib.close()
    assert "Ghost Paper" in titles
    assert "DELETED" not in titles
    assert "NOTE5" not in titles


def test_items_by_collection(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        in_seminar = [it.title for it in lib.items(collection_id=3)]
        empty = lib.items(collection_id=99)
    finally:
        lib.close()
    assert in_seminar == ["Agentic AI Threats"]
    assert empty == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py -v`
Expected: FAIL — `ImportError` for `ZoteroItem` / `AttributeError: 'ZoteroLibrary' object has no attribute 'items'`

- [ ] **Step 3: Implement item assembly in `paper_reader/zotero.py`**

Add the `ZoteroItem` dataclass and `items()` plus helpers. Append `import re` at the top of the module:

```python
import re
```

```python
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
```

Inside `ZoteroLibrary`, add:

```python
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
        items = []
        for r in rows:
            m = meta.get(r["itemID"], {})
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
            ))
        return items
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add paper_reader/zotero.py tests/test_zotero.py
git commit -m "feat: assemble ZoteroItem metadata (title, authors, year, collections)"
```

---

### Task 3: PDF path resolution

`items()` gains `has_pdf` and `pdf_path` by querying `itemAttachments` (contentType `application/pdf` for the item's children) and resolving stored vs. linked files, with existence checks. `resolve_pdf(item)` returns the resolved path.

**Files:**
- Modify: `paper_reader/zotero.py`
- Modify: `tests/test_zotero.py`

**Interfaces:**
- Consumes: `ZoteroItem` dataclass (Task 2), fixture with attachments.
- Produces: `ZoteroItem.has_pdf: bool`, `ZoteroItem.pdf_path: Path | None`; `ZoteroLibrary.resolve_pdf(item: ZoteroItem) -> Path | None`; private `ZoteroLibrary._resolve_pdf_path(att: tuple[str, str] | None) -> Path | None` where `att = (attachment.path, attachment_item.key)`.

- [ ] **Step 1: Write the failing tests in `tests/test_zotero.py`**

```python
from paper_reader.zotero import ZoteroLibrary


def test_resolve_pdf_stored(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = next(i for i in lib.items() if i.title == "Honeypot Evolution")
    finally:
        lib.close()
    assert it.has_pdf is True
    assert it.pdf_path == zotero_db / "storage" / "ATT11" / "Honeypot Evolution.pdf"


def test_resolve_pdf_linked_file(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = next(i for i in lib.items() if i.title == "Retrieval for Science")
    finally:
        lib.close()
    assert it.has_pdf is True
    assert it.pdf_path is not None and it.pdf_path.is_absolute()
    assert it.pdf_path.name == "linked.pdf"


def test_resolve_pdf_missing_file(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = next(i for i in lib.items() if i.title == "Ghost Paper")
    finally:
        lib.close()
    assert it.has_pdf is False
    assert it.pdf_path is None


def test_item_without_pdf(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = next(i for i in lib.items() if i.title == "Agentic AI Threats")
    finally:
        lib.close()
    assert it.has_pdf is False
    assert it.pdf_path is None
    assert lib.resolve_pdf(it) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py::test_resolve_pdf_stored -v`
Expected: FAIL — `has_pdf is False` for Honeypot Evolution

- [ ] **Step 3: Implement PDF resolution**

Add `resolve_pdf` and `_resolve_pdf_path` to `ZoteroLibrary`, and wire attachment query into `_assemble`. In `_assemble`, replace the section that builds `colls` with the same plus attachment lookup:

```python
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
```

And in the item-building loop, set the PDF fields:

```python
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
```

Add these two methods to `ZoteroLibrary`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add paper_reader/zotero.py tests/test_zotero.py
git commit -m "feat: resolve Zotero attachment PDF paths (stored + linked) with existence check"
```

---

### Task 4: search() and get_item()

`search()` filters all items by case-insensitive keyword and sorts by title; `get_item()` returns a single item by ID. Both are needed by the CLI (search) and the API (`/items/{id}`).

**Files:**
- Modify: `paper_reader/zotero.py`
- Modify: `tests/test_zotero.py`

**Interfaces:**
- Consumes: `_assemble`, `_NON_READABLE` (Tasks 2-3).
- Produces: `ZoteroLibrary.search(keyword: str, limit: int = 20) -> list[ZoteroItem]`; `ZoteroLibrary.get_item(item_id: int) -> ZoteroItem | None`.

- [ ] **Step 1: Write the failing tests in `tests/test_zotero.py`**

```python
from paper_reader.zotero import ZoteroLibrary


def test_search_title_case_insensitive(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        hits = [it.title for it in lib.search("HONEYPOT")]
    finally:
        lib.close()
    assert hits == ["Honeypot Evolution"]


def test_search_creator(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        hits = [it.title for it in lib.search("bob")]
    finally:
        lib.close()
    assert hits == ["Honeypot Evolution"]


def test_search_sorted_and_limited(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        hits = [it.title for it in lib.search("i", limit=1)]
    finally:
        lib.close()
    assert hits == ["Agentic AI Threats"]  # first of [Agentic..., Retrieval...] sorted


def test_search_no_match(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        hits = lib.search("zzz")
    finally:
        lib.close()
    assert hits == []


def test_get_item(zotero_db):
    lib = ZoteroLibrary(zotero_db)
    try:
        it = lib.get_item(1)
        missing = lib.get_item(999)
    finally:
        lib.close()
    assert it is not None and it.title == "Honeypot Evolution"
    assert missing is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py::test_search_title_case_insensitive -v`
Expected: FAIL — `AttributeError: 'ZoteroLibrary' object has no attribute 'search'`

- [ ] **Step 3: Implement search() and get_item()**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add paper_reader/zotero.py tests/test_zotero.py
git commit -m "feat: add ZoteroLibrary.search() and get_item()"
```

---

### Task 5: data_dir resolution helper

`resolve_zotero_data_dir()` reads `config.yaml`'s `zotero.data_dir`, falling back to auto-detection (`~/Zotero`, then `/mnt/c/Users/*/Zotero`), raising a clear `FileNotFoundError` if nothing is found. Both CLI and server consume it.

**Files:**
- Modify: `paper_reader/zotero.py`
- Modify: `tests/test_zotero.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `paper_reader.zotero.resolve_zotero_data_dir(config: dict | None = None) -> Path`.

- [ ] **Step 1: Write the failing tests in `tests/test_zotero.py`**

```python
from paper_reader.zotero import resolve_zotero_data_dir


def test_resolve_from_config(zotero_db):
    assert resolve_zotero_data_dir({"zotero": {"data_dir": str(zotero_db)}}) == zotero_db


def test_resolve_autodetect(monkeypatch, tmp_path):
    (tmp_path / "Zotero").mkdir()
    (tmp_path / "Zotero" / "zotero.sqlite").write_text("x")
    monkeypatch.setattr("paper_reader.zotero._autodetect_candidates",
                        lambda: [tmp_path / "Zotero"])
    assert resolve_zotero_data_dir({}) == tmp_path / "Zotero"


def test_resolve_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("paper_reader.zotero._autodetect_candidates",
                        lambda: [tmp_path / "nope"])
    try:
        resolve_zotero_data_dir({"zotero": {"data_dir": ""}})
    except FileNotFoundError as e:
        assert "zotero.data_dir" in str(e)
    else:
        raise AssertionError("expected FileNotFoundError")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py::test_resolve_from_config -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_zotero_data_dir'`

- [ ] **Step 3: Implement resolve_zotero_data_dir()**

Append to `paper_reader/zotero.py` (after the class):

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
git add paper_reader/zotero.py tests/test_zotero.py
git commit -m "feat: add Zotero data_dir resolution with auto-detect"
```

---

### Task 6: CLI `--zotero` mode + config

Adds `python3 main.py --zotero`: connects to the library, searches / browses collections, opens a picked paper through the existing `interactive_loop`. Adds `zotero.data_dir` to both config files.

**Files:**
- Modify: `main.py`
- Modify: `config.yaml`
- Modify: `config.example.yaml`

**Interfaces:**
- Consumes: `ZoteroLibrary`, `ZoteroItem`, `resolve_zotero_data_dir`, existing `interactive_loop`, `load_config`.
- Produces: CLI entry; config key `zotero.data_dir`.

- [ ] **Step 1: Add config keys**

`config.yaml` (append):
```yaml
zotero:
  data_dir: /mnt/c/Users/ASUS/Zotero
```

`config.example.yaml` (append):
```yaml
zotero:
  data_dir: ""   # Zotero 数据目录（zotero.sqlite 所在目录），留空自动探测
```

- [ ] **Step 2: Add the import to `main.py`**

In `main.py`, after the existing imports:

```python
from paper_reader.zotero import ZoteroItem, ZoteroLibrary, resolve_zotero_data_dir
```

- [ ] **Step 3: Add the zotero mode functions to `main.py`**

Append before `def main()`:

```python
def zotero_interactive() -> None:
    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        config = None
    try:
        data_dir = resolve_zotero_data_dir(config)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)
    print(f"正在连接 Zotero 库: {data_dir}")
    lib = ZoteroLibrary(data_dir)
    try:
        _zotero_loop(lib)
    finally:
        lib.close()


def _zotero_loop(lib: ZoteroLibrary) -> None:
    session = PromptSession()
    current_items: list[ZoteroItem] = []
    while True:
        try:
            user_input = session.prompt("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not user_input:
            continue
        if user_input in ("/quit", "/exit"):
            print("\n再见！")
            break
        elif user_input == "/help":
            _zotero_help()
        elif user_input == "/collections":
            current_items = _pick_collection_items(lib, session)
        elif user_input.startswith("/search "):
            current_items = _search_and_show(lib, user_input[len("/search "):].strip())
        elif user_input.isdigit():
            idx = int(user_input) - 1
            if 0 <= idx < len(current_items):
                _open_item(lib, current_items[idx])
            else:
                print("序号无效")
        else:
            current_items = _search_and_show(lib, user_input)


def _search_and_show(lib: ZoteroLibrary, keyword: str) -> list[ZoteroItem]:
    if not keyword:
        return []
    items = lib.search(keyword)
    _show_items(items)
    print("\n输入序号打开该论文，或继续搜索")
    return items


def _pick_collection_items(lib: ZoteroLibrary, session) -> list[ZoteroItem]:
    collections = lib.collections()
    top = [c for c in collections if c.parent_id is None]
    rows: list[tuple] = []

    def walk(cols, depth):
        for c in cols:
            rows.append((c, depth))
            walk([x for x in collections if x.parent_id == c.collection_id], depth + 1)

    walk(top, 0)
    for i, (c, d) in enumerate(rows, 1):
        print(f"[{i}] {'  ' * d}{c.name} ({c.item_count})")
    choice = session.prompt("选收藏夹(0 返回)> ").strip()
    if not choice.isdigit():
        return []
    n = int(choice)
    if n == 0:
        return []
    if not (0 < n <= len(rows)):
        print("序号无效")
        return []
    items = lib.items(collection_id=rows[n - 1][0].collection_id)
    _show_items(items)
    return items


def _show_items(items: list[ZoteroItem]) -> None:
    if not items:
        print("(无匹配条目)")
        return
    for i, it in enumerate(items, 1):
        colls = ", ".join(it.collections) if it.collections else "未分类"
        pdf = "" if it.has_pdf else " (无 PDF)"
        print(f"[{i}] {_format_authors(it.creators)} {it.year or '?'} — {it.title} ({colls}){pdf}")


def _format_authors(creators: list[str]) -> str:
    if not creators:
        return ""
    if len(creators) <= 3:
        return ", ".join(creators)
    return f"{', '.join(creators[:3])} et al."


def _open_item(lib: ZoteroLibrary, item: ZoteroItem) -> None:
    pdf = lib.resolve_pdf(item)
    if pdf is None:
        print("该条目没有可用 PDF，跳过")
        return
    print(f"正在加载论文: {pdf}")
    interactive_loop(str(pdf))


def _zotero_help() -> None:
    print("""
命令:
  直接输入关键字  搜索论文（标题/作者）
  /collections   浏览收藏夹树
  /search <kw>   显式搜索
  /help          帮助
  /quit          退出
""")
```

- [ ] **Step 4: Wire `--zotero` into `main()`**

In `main()`, after the `--batch` block:

```python
    if sys.argv[1] == "--zotero":
        zotero_interactive()
        return
```

And update the usage string:

```python
        print("用法: python main.py <论文.pdf>")
        print("      python main.py --batch <论文目录>")
        print("      python main.py --zotero")
```

- [ ] **Step 5: Verify the CLI search flow against the real library**

Run: `source .venv/bin/activate && echo "honeypot
/quit" | python3 main.py --zotero`
Expected: prints the Zotero dir and a search result list containing honeypot papers, then exits. (The full open-one-paper flow is verified in Task 8 Step 3.)

- [ ] **Step 6: Run the full test suite**

Run: `source .venv/bin/activate && python3 -m pytest tests/ -q`
Expected: all tests pass (existing 146 + new 17).

- [ ] **Step 7: Commit**

```bash
git add main.py config.yaml config.example.yaml
git commit -m "feat: add --zotero CLI mode to select and open papers from Zotero"
```

---

### Task 7: FastAPI server + API tests + requirements

`paper_reader/server.py` exposes four read-only GET endpoints over the shared `ZoteroLibrary`, with per-request dependency injection. Adds `fastapi`/`uvicorn` to `requirements.txt`.

**Files:**
- Create: `paper_reader/server.py`
- Create: `tests/test_zotero_api.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `ZoteroLibrary`, `resolve_zotero_data_dir`, `load_config`, fixture `zotero_db`.
- Produces: `paper_reader.server.create_app(data_dir: Path | None = None) -> FastAPI`; module-level `app`; endpoints `GET /api/zotero/collections`, `GET /api/zotero/items?collection_id=`, `GET /api/zotero/search?q=`, `GET /api/zotero/items/{item_id}` (404 if missing). All JSON lists/dicts of dataclasses with `pdf_path` as `str | None`.

- [ ] **Step 1: Write the failing API tests in `tests/test_zotero_api.py`**

```python
from fastapi.testclient import TestClient

from paper_reader.server import create_app


def test_collections_endpoint(zotero_db):
    app = create_app(zotero_db)
    res = TestClient(app).get("/api/zotero/collections")
    assert res.status_code == 200
    names = {c["name"] for c in res.json()}
    assert names == {"课题组", "蜜罐", "研讨厅第一篇"}


def test_items_endpoint(zotero_db):
    app = create_app(zotero_db)
    res = TestClient(app).get("/api/zotero/items")
    assert res.status_code == 200
    titles = [it["title"] for it in res.json()]
    assert "Honeypot Evolution" in titles


def test_items_by_collection_endpoint(zotero_db):
    app = create_app(zotero_db)
    res = TestClient(app).get("/api/zotero/items", params={"collection_id": 3})
    assert res.status_code == 200
    assert [it["title"] for it in res.json()] == ["Agentic AI Threats"]


def test_search_endpoint(zotero_db):
    app = create_app(zotero_db)
    res = TestClient(app).get("/api/zotero/search", params={"q": "honeypot"})
    assert res.status_code == 200
    assert [it["title"] for it in res.json()] == ["Honeypot Evolution"]


def test_item_detail_endpoint(zotero_db):
    app = create_app(zotero_db)
    res = TestClient(app).get("/api/zotero/items/1")
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Honeypot Evolution"
    assert body["pdf_path"] == str(zotero_db / "storage" / "ATT11" / "Honeypot Evolution.pdf")


def test_item_not_found_endpoint(zotero_db):
    app = create_app(zotero_db)
    res = TestClient(app).get("/api/zotero/items/999")
    assert res.status_code == 404
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'paper_reader.server'`

- [ ] **Step 3: Implement `paper_reader/server.py`**

```python
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
```

- [ ] **Step 4: Add deps to `requirements.txt`**

Append:
```
fastapi>=0.115.0
uvicorn>=0.30.0
```

- [ ] **Step 5: Run the API tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_zotero_api.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Run the full test suite**

Run: `source .venv/bin/activate && python3 -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add paper_reader/server.py tests/test_zotero_api.py requirements.txt
git commit -m "feat: add FastAPI Zotero read endpoints with per-request library injection"
```

---

### Task 8: Documentation + final verification

Update `CLAUDE.md` per repo convention (code changes → doc must be synced), then run the whole suite and a live smoke test of both interfaces.

**Files:**
- Modify: `CLAUDE.md`
- (no code)

- [ ] **Step 1: Update `CLAUDE.md`**

In the architecture tree, add:
```
  ├── zotero.py           # Zotero 只读数据层（collections/items/search/get_item/resolve_pdf）
  └── server.py           # FastAPI：/api/zotero/* 只读接口
```

Under "已完成", add a `Zotero 连接（P4 第一步）` bullet block:
- [x] **Zotero 连接（CLI + API）** — `zotero.py` 只读读取 Windows 侧 Zotero sqlite（`/mnt/c/Users/ASUS/Zotero`），解析条目元数据（标题/作者/年份/期刊/DOI/收藏夹）+ 定位 PDF（storage: 路径 → `storage/{attachment_key}/{filename}`）；`main.py --zotero` 搜索/收藏夹选论文进入对话；FastAPI 暴露 collections/items/search/items/{id} 四端点，前端/模型 agent 复用

Update 常用命令 with:
```bash
python3 main.py --zotero                 # 从 Zotero 库选论文阅读
uvicorn paper_reader.server:app          # FastAPI（Zotero 检索接口）
```

Under 下一步优先级 P4, mark the first three items done:
- [x] 摸清 Zotero 数据库 schema
- [x] FastAPI 后端：Zotero 条目列表 API + 打开论文
- [ ] Tauri 工程脚手架 + 双击启动自动拉起 FastAPI
- [ ] React 前端：论文列表 + 收藏夹树 + 阅读区（markdown 渲染）+ 对话区
- [ ] 本地知识库：多论文统一索引

- [ ] **Step 2: Run the full test suite**

Run: `source .venv/bin/activate && python3 -m pytest tests/ -q`
Expected: all tests pass (existing 146 + ~23 new).

- [ ] **Step 3: Live smoke test — CLI open flow**

Run: `source .venv/bin/activate && echo "honeypot
1
/quit" | python3 main.py --zotero`
Expected: lists honeypot papers, opens the first result through the full pipeline (MinerU parse or cache), prints the overview, enters the conversation loop, then exits. Note: first open of an uncached paper runs MinerU (~1-2 min).

- [ ] **Step 4: Live smoke test — API**

Run: `source .venv/bin/activate && uvicorn paper_reader.server:app --port 8899 & sleep 2 && curl -s 'http://127.0.0.1:8899/api/zotero/search?q=honeypot' | python3 -m json.tool; kill %1`
Expected: JSON array of honeypot items with title/creators/year/pdf_path.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for Zotero connection (CLI + API)"
```
