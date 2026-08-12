import sqlite3
import tempfile
from pathlib import Path

import fitz
import numpy as np
import pytest


class _FakeModel:
    """Fake embedding model: simple word-overlap vector, fast and semantic-ish.

    Each dimension corresponds to a character bigram, so texts sharing words
    get similar embeddings — just enough for tests to exercise the retrieval path.
    """

    _dim = 64

    def encode(self, texts, batch_size=12, max_length=512,
               return_dense=True, return_sparse=False, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        n = len(texts)
        dim = self._dim
        vecs = np.zeros((n, dim), dtype=np.float32)
        sparse_weights: list[dict] = []
        for i, t in enumerate(texts):
            lower = t.lower()
            token_weights: dict[int, float] = {}
            for j in range(len(lower) - 1):
                idx = (ord(lower[j]) + ord(lower[j + 1])) % dim
                vecs[i, idx] += 1.0
                token_weights[idx] = token_weights.get(idx, 0.0) + 0.1
            norm = np.linalg.norm(vecs[i])
            if norm > 0:
                vecs[i] /= norm
            else:
                vecs[i, 0] = 1.0
            sparse_weights.append(token_weights)
        result = {}
        if return_dense:
            result["dense_vecs"] = vecs
        if return_sparse:
            result["lexical_weights"] = sparse_weights
        return result

    def compute_lexical_matching_score(self, q_weights: dict, d_weights: dict) -> float:
        score = 0.0
        for tid, w in q_weights.items():
            score += w * d_weights.get(tid, 0.0)
        return score


@pytest.fixture(autouse=True)
def mock_embedding_model(monkeypatch):
    """Replace BGE-M3 with a fast fake model for all tests."""
    fake = _FakeModel()

    def fake_get_model():
        return fake

    monkeypatch.setattr(
        "paper_reader.context._get_embedding_model", fake_get_model
    )
    monkeypatch.setattr("paper_reader.context._embedding_model", None)


@pytest.fixture
def sample_pdf_path():
    """Create a minimal multi-section PDF for parser tests."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc = fitz.open()

    # Page 1: Title and abstract
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Sample Research Paper", fontsize=18)
    page1.insert_text((72, 120), "John Doe, Jane Smith", fontsize=12)
    page1.insert_text((72, 160), "Abstract", fontsize=14)
    page1.insert_text((72, 190), "This paper presents a novel approach to "
                      "sample generation for testing purposes. We demonstrate "
                      "that our method outperforms baselines by 42%.", fontsize=11)

    # Page 2: Introduction
    page2 = doc.new_page()
    page2.insert_text((72, 72), "1. Introduction", fontsize=16)
    page2.insert_text((72, 110), "Sample generation is a fundamental problem "
                      "in computer science. Prior work has focused on random "
                      "approaches, which fail to capture real-world distributions.",
                      fontsize=11)

    # Page 3: Method
    page3 = doc.new_page()
    page3.insert_text((72, 72), "2. Method", fontsize=16)
    page3.insert_text((72, 110), "Our approach uses a three-stage pipeline. "
                      "First, we collect seed data. Second, we train a generative "
                      "model. Third, we refine outputs with rejection sampling.",
                      fontsize=11)

    doc.save(tmp.name)
    doc.close()
    yield tmp.name
    Path(tmp.name).unlink()


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
