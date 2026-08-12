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
