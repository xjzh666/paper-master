# tests/test_openalex_search.py
"""openalex_search 单测：零触网（urllib.request.urlopen 全打桩，OpenAlex
JSON 响应用录制片段做 fixture）。"""
import io
from urllib.error import URLError

import pytest

import paper_reader.openalex_search as openalex_search
from paper_reader.arxiv_search import ArxivResult

# ---------------------------------------------------------------------------
# 录制的 OpenAlex works 响应片段（fixture）
# ---------------------------------------------------------------------------

# Oracle fixture：3 条记录——① arXiv DOI ② 期刊 DOI + arXiv pdf_url
# ③ 纯期刊无任何 arXiv 痕迹 → 只 ①② 能提取出 arxiv_id
WORKS_PAYLOAD = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.48550/arxiv.2312.10997",
            "display_name": "RAPTOR: Recursive Abstractive\n  Processing for Tree-Organized Retrieval",
            "publication_year": 2023,
            "publication_date": "2023-12-18",
            "authorships": [
                {"author": {"display_name": "Sarthick Saroff"}},
                {"author": {"display_name": "Matthew Purohit"}},
            ],
            "best_oa_location": None,
        },
        {
            "id": "https://openalex.org/W2",
            "doi": "https://doi.org/10.1038/s41586-020-2649-2",
            "display_name": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
            "publication_year": None,
            "publication_date": "2020-05-28",
            "authorships": [{"author": {"display_name": "Patrick Lewis"}}],
            "best_oa_location": {"pdf_url": "https://arxiv.org/pdf/2005.11401v2"},
        },
        {
            "id": "https://openalex.org/W3",
            "doi": "https://doi.org/10.1038/s41586-021-03819-2",
            "display_name": "AlphaFold 2: pure journal record",
            "publication_year": 2021,
            "publication_date": "2021-07-15",
            "authorships": [],
            "best_oa_location": {"pdf_url": "https://nature.com/articles/s41586.pdf"},
        },
    ]
}


def _works_bytes(payload: dict = WORKS_PAYLOAD) -> bytes:
    import json

    return json.dumps(payload).encode()


# ---------------------------------------------------------------------------
# 打桩工具
# ---------------------------------------------------------------------------


class FakeResponse:
    """urlopen 返回值替身：支持上下文管理器与 read。"""

    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeUrlopen:
    """urllib.request.urlopen 打桩：记录每次请求 URL，返回预置 JSON 载荷。"""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls: list[str] = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        return FakeResponse(self.payload)

    @property
    def last_url(self) -> str:
        return self.calls[-1]


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_keeps_only_records_with_extractable_arxiv_id(self, monkeypatch):
        """Oracle：3 条记录 → 2 条（③ 纯期刊被丢弃），版本号已去。"""
        fake = FakeUrlopen(_works_bytes())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        results = openalex_search.search("raptor")

        assert [r.arxiv_id for r in results] == ["2312.10997", "2005.11401"]

    def test_maps_fields_to_arxiv_result(self, monkeypatch):
        fake = FakeUrlopen(_works_bytes())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        results = openalex_search.search("raptor")

        first, second = results
        assert isinstance(first, ArxivResult)
        # doi=10.48550/arxiv.{id} 提取；title 空白折叠；published 取 publication_year
        assert first.title == (
            "RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval"
        )
        assert first.authors == ["Sarthick Saroff", "Matthew Purohit"]
        assert first.published == "2023"
        # 期刊 DOI 走 best_oa_location.pdf_url 提取；publication_year 缺失
        # 回退 publication_date 前 4 位
        assert second.published == "2020"
        # 固定映射字段
        for r in (first, second):
            assert r.abstract == ""
            assert r.updated == ""
            assert r.categories == []
            assert r.pdf_url == f"https://arxiv.org/pdf/{r.arxiv_id}"
            assert r.abs_url == f"https://arxiv.org/abs/{r.arxiv_id}"

    def test_missing_year_and_date_gives_empty_published(self, monkeypatch):
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.48550/arxiv.2312.10997",
                    "display_name": "No year at all",
                    "publication_year": None,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": None,
                }
            ]
        }
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(_works_bytes(payload))
        )

        results = openalex_search.search("raptor")

        assert results[0].published == ""

    def test_request_url_format(self, monkeypatch):
        fake = FakeUrlopen(_works_bytes())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        openalex_search.search("attention is all you need")

        assert fake.calls == [
            "https://api.openalex.org/works"
            "?search=attention%20is%20all%20you%20need"
            "&filter=primary_location.source.id:S4306400194"
            "&per_page=10"
            "&select=id,doi,display_name,publication_year,publication_date,"
            "authorships,best_oa_location,primary_location"
            "&mailto=paper-master@example.com"
        ]

    def test_per_page_clamped_to_1_and_50(self, monkeypatch):
        fake = FakeUrlopen(_works_bytes())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        openalex_search.search("q", max_results=100)
        openalex_search.search("q", max_results=0)

        assert "per_page=50" in fake.calls[0]  # 越上界 → 50
        assert "per_page=1" in fake.calls[1]  # 越下界 → 1

    def test_pdf_url_with_dot_pdf_suffix_and_version(self, monkeypatch):
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": None,
                    "display_name": "Suffix and version",
                    "publication_year": 2023,
                    "publication_date": "2023-10-10",
                    "authorships": [],
                    "best_oa_location": {
                        "pdf_url": "https://arxiv.org/pdf/2310.06670v3.pdf"
                    },
                }
            ]
        }
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(_works_bytes(payload))
        )

        results = openalex_search.search("q")

        assert results[0].arxiv_id == "2310.06670"  # 去尾 .pdf + 去版本号

    def test_dedupes_by_arxiv_id_preserving_order(self, monkeypatch):
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.48550/arxiv.2312.10997",
                    "display_name": "First occurrence",
                    "publication_year": 2023,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": None,
                },
                {
                    "id": "https://openalex.org/W2",
                    "doi": None,
                    "display_name": "Same paper via pdf_url",
                    "publication_year": 2023,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": {
                        "pdf_url": "https://arxiv.org/pdf/2312.10997v1"
                    },
                },
            ]
        }
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(_works_bytes(payload))
        )

        results = openalex_search.search("q")

        assert [r.arxiv_id for r in results] == ["2312.10997"]
        assert results[0].title == "First occurrence"  # 保序：先出现的留下

    def test_truncates_to_max_results(self, monkeypatch):
        payload = {
            "results": [
                {
                    "id": f"https://openalex.org/W{i}",
                    "doi": f"https://doi.org/10.48550/arxiv.2312.1000{i}",
                    "display_name": f"Paper {i}",
                    "publication_year": 2023,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": None,
                }
                for i in range(3)
            ]
        }
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(_works_bytes(payload))
        )

        results = openalex_search.search("q", max_results=2)

        assert [r.arxiv_id for r in results] == ["2312.10000", "2312.10001"]

    def test_third_path_extraction_priority_and_dedup(self, monkeypatch):
        """Oracle：A doi 提取（1106.1234v2 去版本）；B 无 doi、pdf_url 为
        期刊 landing 页（无 pdf）、primary 亦非 arXiv → 丢弃；C 无 doi 无
        pdf_url，primary_location.landing_page_url 为 arXiv abs 形态 → 第三条
        路径提取；D 与 A 同 arxiv_id → 去重。"""
        payload = {
            "results": [
                {   # A: doi 提取，id 带版本号
                    "id": "https://openalex.org/WA",
                    "doi": "https://doi.org/10.48550/arxiv.1106.1234v2",
                    "display_name": "Paper A",
                    "publication_year": 2015,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": None,
                    "primary_location": None,
                },
                {   # B: 无 doi；pdf_url 为 landing 页无 pdf → 提取不出，丢弃
                    "id": "https://openalex.org/WB",
                    "doi": None,
                    "display_name": "Paper B",
                    "publication_year": 2020,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": {
                        "pdf_url": (
                            "https://www.nature.com/articles/s41586-020-2649-2"
                        )
                    },
                    "primary_location": {
                        "landing_page_url": (
                            "https://www.nature.com/articles/s41586-020-2649-2"
                        )
                    },
                },
                {   # C: 无 doi 无 pdf_url，landing_page_url 为 arXiv abs 形态
                    "id": "https://openalex.org/WC",
                    "doi": None,
                    "display_name": "Paper C",
                    "publication_year": 2019,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": None,
                    "primary_location": {
                        "landing_page_url": "http://arxiv.org/abs/1901.01234"
                    },
                },
                {   # D: 与 A 同 arxiv_id（经 pdf_url 提取）→ 重复被去重
                    "id": "https://openalex.org/WD",
                    "doi": None,
                    "display_name": "Paper D duplicate of A",
                    "publication_year": 2015,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": {
                        "pdf_url": "https://arxiv.org/pdf/1106.1234v1"
                    },
                    "primary_location": None,
                },
            ]
        }
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(_works_bytes(payload))
        )

        results = openalex_search.search("q")

        assert [r.arxiv_id for r in results] == ["1106.1234", "1901.01234"]
        assert results[0].title == "Paper A"  # 保序：先出现的 A 留下，D 去重

    def test_doi_takes_priority_over_pdf_url_and_landing_page(
        self, monkeypatch
    ):
        """三条路径同时命中且 id 不同 → doi 优先。"""
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.48550/arxiv.1106.1234",
                    "display_name": "Priority doi",
                    "publication_year": 2015,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": {
                        "pdf_url": "https://arxiv.org/pdf/1901.01234"
                    },
                    "primary_location": {
                        "landing_page_url": "https://arxiv.org/abs/2001.03045"
                    },
                }
            ]
        }
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(_works_bytes(payload))
        )

        results = openalex_search.search("q")

        assert results[0].arxiv_id == "1106.1234"

    def test_pdf_url_takes_priority_over_landing_page(self, monkeypatch):
        """无 doi，pdf_url 与 landing_page_url 都指向 arXiv 但 id 不同
        → best_oa_location.pdf_url 优先。"""
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": None,
                    "display_name": "Priority pdf_url",
                    "publication_year": 2019,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": {
                        "pdf_url": "https://arxiv.org/pdf/1901.01234"
                    },
                    "primary_location": {
                        "landing_page_url": "https://arxiv.org/abs/2001.03045"
                    },
                }
            ]
        }
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(_works_bytes(payload))
        )

        results = openalex_search.search("q")

        assert results[0].arxiv_id == "1901.01234"

    def test_landing_page_url_version_stripped(self, monkeypatch):
        """第三条路径同样剥版本号：abs/2310.06670v3 → 2310.06670。"""
        payload = {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": None,
                    "display_name": "Versioned landing page",
                    "publication_year": 2023,
                    "publication_date": None,
                    "authorships": [],
                    "best_oa_location": None,
                    "primary_location": {
                        "landing_page_url": "https://arxiv.org/abs/2310.06670v3"
                    },
                }
            ]
        }
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(_works_bytes(payload))
        )

        results = openalex_search.search("q")

        assert results[0].arxiv_id == "2310.06670"

    def test_empty_results_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            FakeUrlopen(_works_bytes({"results": []})),
        )

        assert openalex_search.search("no such topic") == []

    def test_network_error_propagates(self, monkeypatch):
        def boom(request, timeout=None):
            raise URLError("connection refused")

        monkeypatch.setattr("urllib.request.urlopen", boom)

        with pytest.raises(URLError):
            openalex_search.search("q")
