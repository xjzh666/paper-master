from fastapi.testclient import TestClient

from paper_reader.server import create_app


def test_serves_index_when_dist_exists(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>paper-master</html>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

    app = create_app(None, frontend_dist=str(dist))
    with TestClient(app) as client:
        idx = client.get("/")
        asset = client.get("/assets/app.js")
    assert idx.status_code == 200
    assert "paper-master" in idx.text
    assert asset.status_code == 200
