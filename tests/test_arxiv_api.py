# tests/test_arxiv_api.py
"""arXiv HTTP 端点单测：全部在模块边界打桩（monkeypatch
arxiv_search.search / download_pdf 与 papers.open_paper 的模块属性），
零触网、零真睡；限速闸在真实函数内部，打桩后不会被触发。"""
from pathlib import Path
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient

import paper_reader.arxiv_search as arxiv_search
import paper_reader.openalex_search as openalex_search
import paper_reader.papers as papers
from paper_reader.arxiv_search import DEFAULT_DOWNLOAD_DIR, ArxivResult
from paper_reader.server import create_app


def _attention_result() -> ArxivResult:
    return ArxivResult(
        arxiv_id="1706.03762",
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        abstract="The dominant sequence transduction models.",
        published="2017-06-12T01:19:08Z",
        updated="2017-07-26T09:22:34Z",
        categories=["cs.CL", "cs.AI"],
        pdf_url="https://arxiv.org/pdf/1706.03762",
        abs_url="https://arxiv.org/abs/1706.03762",
    )


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/arxiv/search
# ---------------------------------------------------------------------------


class TestArxivSearchEndpoint:
    def test_returns_results_with_all_nine_fields(self, client, monkeypatch):
        calls = {}

        def fake_fallback(query, max_results=10):
            calls["args"] = (query, max_results)
            return [_attention_result()], "arxiv"

        monkeypatch.setattr(arxiv_search, "search_with_fallback", fake_fallback)

        res = client.get("/api/arxiv/search", params={"q": "attention"})

        assert res.status_code == 200
        assert res.json()["source"] == "arxiv"
        results = res.json()["results"]
        assert len(results) == 1
        assert results[0]["arxiv_id"] == "1706.03762"
        assert set(results[0]) == {
            "arxiv_id", "title", "authors", "abstract",
            "published", "updated", "categories", "pdf_url", "abs_url",
            "tldr", "citation_count",
        }
        assert results[0]["title"] == "Attention Is All You Need"
        # 端点把参数原样传给模块层（限速闸所在层）
        assert calls["args"] == ("attention", 10)

    def test_max_results_forwarded(self, client, monkeypatch):
        calls = {}

        def fake_fallback(query, max_results=10):
            calls["args"] = (query, max_results)
            return [], "arxiv"

        monkeypatch.setattr(arxiv_search, "search_with_fallback", fake_fallback)

        res = client.get("/api/arxiv/search",
                         params={"q": "attention", "max_results": 50})

        assert res.status_code == 200
        assert calls["args"] == ("attention", 50)

    def test_no_results_returns_empty_list_not_error(self, client, monkeypatch):
        monkeypatch.setattr(arxiv_search, "search_with_fallback",
                            lambda query, max_results=10: ([], "arxiv"))

        res = client.get("/api/arxiv/search", params={"q": "no such topic"})

        assert res.status_code == 200
        assert res.json() == {"results": [], "source": "arxiv"}

    def test_search_failure_returns_502(self, client, monkeypatch):
        def boom(query, max_results=10):
            raise URLError("timeout")

        monkeypatch.setattr(arxiv_search, "search_with_fallback", boom)

        res = client.get("/api/arxiv/search", params={"q": "attention"})

        assert res.status_code == 502
        assert res.json()["detail"].startswith("外部检索失败")

    @pytest.mark.parametrize("params", [
        {},                      # q 缺失
        {"q": ""},               # q 为空
        {"q": "attention", "max_results": 0},   # 越下界
        {"q": "attention", "max_results": 51},  # 越上界
    ])
    def test_query_validation_returns_422(self, client, monkeypatch, params):
        def must_not_run(*args, **kwargs):
            raise AssertionError("validation failure must not reach search")

        monkeypatch.setattr(arxiv_search, "search_with_fallback", must_not_run)

        res = client.get("/api/arxiv/search", params=params)

        assert res.status_code == 422

    def test_rate_limited_falls_back_to_openalex(self, client, monkeypatch):
        """Oracle：arXiv 打桩抛 ArxivRateLimitError、OpenAlex 打桩返回 1 条
        → 编排层吃掉限流，端点 200 且 source == "openalex"。"""
        def rate_limited(query, max_results=10):
            raise arxiv_search.ArxivRateLimitError()

        monkeypatch.setattr(arxiv_search, "search", rate_limited)
        monkeypatch.setattr(openalex_search, "search",
                            lambda query, max_results=10: [_attention_result()])

        res = client.get("/api/arxiv/search", params={"q": "attention"})

        assert res.status_code == 200
        assert res.json()["source"] == "openalex"
        assert res.json()["results"][0]["arxiv_id"] == "1706.03762"

    def test_both_sources_fail_returns_502(self, client, monkeypatch):
        """Oracle：arXiv 与 OpenAlex 打桩都抛 URLError → 502，
        detail 以 外部检索失败 开头。"""
        def arxiv_down(query, max_results=10):
            raise URLError("arxiv down")

        def openalex_down(query, max_results=10):
            raise URLError("openalex down")

        monkeypatch.setattr(arxiv_search, "search", arxiv_down)
        monkeypatch.setattr(openalex_search, "search", openalex_down)

        res = client.get("/api/arxiv/search", params={"q": "attention"})

        assert res.status_code == 502
        assert res.json()["detail"].startswith("外部检索失败")


# ---------------------------------------------------------------------------
# POST /api/arxiv/open
# ---------------------------------------------------------------------------


class TestArxivOpenEndpoint:
    def test_downloads_then_opens_paper(self, client, monkeypatch):
        download_calls = []
        open_calls = []

        def fake_download(arxiv_id, dest_dir):
            download_calls.append((arxiv_id, dest_dir))
            return Path("/x/1706.03762.pdf")

        def fake_open(pdf_path):
            open_calls.append(pdf_path)
            return {"paper_id": "abc", "status": "parsing"}

        monkeypatch.setattr(arxiv_search, "download_pdf", fake_download)
        monkeypatch.setattr(papers, "open_paper", fake_open)

        res = client.post("/api/arxiv/open", json={"arxiv_id": "1706.03762"})

        assert res.status_code == 200
        assert res.json() == {"paper_id": "abc", "status": "parsing"}
        # 下载目标目录用模块常量，路径以 str 传给 open_paper
        assert download_calls == [("1706.03762", DEFAULT_DOWNLOAD_DIR)]
        assert open_calls == ["/x/1706.03762.pdf"]

    @pytest.mark.parametrize("good_id", [
        "1706.03762",        # 新式
        "1706.03762v7",      # 新式 + 版本号
        "hep-th/9901001",    # 旧式 archive
        "cs.LG/0303012",     # 旧式带子分类
    ])
    def test_valid_id_formats_are_accepted(self, client, monkeypatch, good_id):
        download_calls = []

        def fake_download(arxiv_id, dest_dir):
            download_calls.append((arxiv_id, dest_dir))
            return Path(f"/x/{arxiv_id.replace('/', '_')}.pdf")

        monkeypatch.setattr(arxiv_search, "download_pdf", fake_download)
        monkeypatch.setattr(papers, "open_paper",
                            lambda pdf_path: {"paper_id": "abc",
                                              "status": "ready"})

        res = client.post("/api/arxiv/open", json={"arxiv_id": good_id})

        assert res.status_code == 200
        assert download_calls == [(good_id, DEFAULT_DOWNLOAD_DIR)]

    @pytest.mark.parametrize("bad_id", [
        "../../etc/passwd",       # 路径穿越
        "",                      # 空
        "1706.03",               # 小数部分不足 4 位
        "1706.03762/extra",      # 尾部多余片段
        "not-an-id",
        "CS/123",                # 大写 archive 不允许
        42,                      # 非字符串
    ])
    def test_invalid_arxiv_id_returns_400(self, client, monkeypatch, bad_id):
        download_calls = []

        def fake_download(arxiv_id, dest_dir):
            download_calls.append((arxiv_id, dest_dir))
            return Path("/x/never.pdf")

        monkeypatch.setattr(arxiv_search, "download_pdf", fake_download)

        res = client.post("/api/arxiv/open", json={"arxiv_id": bad_id})

        assert res.status_code == 400
        assert download_calls == []  # 非法 ID 不发起下载

    def test_missing_arxiv_id_returns_400(self, client, monkeypatch):
        download_calls = []

        def fake_download(arxiv_id, dest_dir):
            download_calls.append(arxiv_id)

        monkeypatch.setattr(arxiv_search, "download_pdf", fake_download)

        res = client.post("/api/arxiv/open", json={})

        assert res.status_code == 400
        assert download_calls == []

    def test_download_failure_returns_502(self, client, monkeypatch):
        def boom(arxiv_id, dest_dir):
            raise OSError("connection refused")

        monkeypatch.setattr(arxiv_search, "download_pdf", boom)
        monkeypatch.setattr(papers, "open_paper", lambda p: {})

        res = client.post("/api/arxiv/open", json={"arxiv_id": "1706.03762"})

        assert res.status_code == 502
        assert res.json()["detail"]  # 带可读 detail

    def test_open_paper_failure_returns_500(self, client, monkeypatch):
        monkeypatch.setattr(arxiv_search, "download_pdf",
                            lambda arxiv_id, dest_dir: Path("/x/a.pdf"))

        def boom(pdf_path):
            raise RuntimeError("parse failed")

        monkeypatch.setattr(papers, "open_paper", boom)

        res = client.post("/api/arxiv/open", json={"arxiv_id": "1706.03762"})

        assert res.status_code == 500
        assert res.json()["detail"]


# ---------------------------------------------------------------------------
# ArxivRateLimitError → 友好 502（open 端点保留；search 端点已被
# search_with_fallback 编排层吃掉，见 TestArxivSearchEndpoint 兜底测试）
# ---------------------------------------------------------------------------


class TestArxivRateLimitErrorMapping:
    def test_open_rate_limited_returns_friendly_502(self, client, monkeypatch):
        def rate_limited(arxiv_id, dest_dir):
            raise arxiv_search.ArxivRateLimitError()

        monkeypatch.setattr(arxiv_search, "download_pdf", rate_limited)
        monkeypatch.setattr(papers, "open_paper", lambda p: {})

        res = client.post("/api/arxiv/open", json={"arxiv_id": "1706.03762"})

        assert res.status_code == 502
        assert res.json()["detail"] == "arXiv 限流中，请稍后 1-2 分钟再试"
