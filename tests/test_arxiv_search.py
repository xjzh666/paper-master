# tests/test_arxiv_search.py
"""arxiv_search 单测：零触网（urllib.request.urlopen 全打桩，Atom 响应用
录制片段做 fixture）；限速测试打桩 time（FakeClock），全程不真睡。"""
import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

import paper_reader.arxiv_search as arxiv_search
import paper_reader.openalex_search as openalex_search
import paper_reader.s2_search as s2_search
from paper_reader.arxiv_search import (
    DEFAULT_DOWNLOAD_DIR,
    ArxivResult,
    download_pdf,
    search,
    search_with_fallback,
)

# ---------------------------------------------------------------------------
# 录制的 arXiv Atom 响应片段（fixture）
# ---------------------------------------------------------------------------

ATTENTION_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <link href="http://arxiv.org/api/query?search_query=all" rel="self" type="application/atom+xml"/>
  <title type="html">ArXiv Query: search_query=all:&quot;attention is all you need&quot;</title>
  <id>http://arxiv.org/api/query</id>
  <updated>2026-09-11T00:00:00-04:00</updated>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">2</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/1706.03762v2</id>
    <updated>2017-07-26T09:22:34Z</updated>
    <published>2017-06-12T01:19:08Z</published>
    <title>Attention Is All You Need</title>
    <summary>  The dominant sequence transduction models are based on complex recurrent or
convolutional neural networks that include an encoder and a decoder.
We propose the Transformer.  </summary>
    <author>
      <name>Ashish Vaswani</name>
    </author>
    <author>
      <name>Noam Shazeer</name>
    </author>
    <author>
      <name>Niki Parmar</name>
    </author>
    <arxiv:primary_category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="stat.ML" scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/1706.03762v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="https://arxiv.org/pdf/1706.03762v2" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/cs/0112017v1</id>
    <updated>2001-12-04T19:22:36Z</updated>
    <published>2001-12-04T19:22:36Z</published>
    <title>Applying Machine Learning to
      Higher Order Pattern Mining</title>
    <summary>An entry with no link elements, exercising fallback URL construction.</summary>
    <author>
      <name>Grace Hopper</name>
    </author>
    <arxiv:primary_category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link href="http://arxiv.org/api/query?search_query=all" rel="self" type="application/atom+xml"/>
  <title type="html">ArXiv Query: search_query=all:&quot;no such paper&quot;</title>
  <id>http://arxiv.org/api/query</id>
  <updated>2026-09-11T00:00:00-04:00</updated>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:totalResults>
</feed>
"""

PDF_PAYLOAD = b"%PDF-1.4 fake body with enough bytes to force chunking ..." + b"x" * 64

# ---------------------------------------------------------------------------
# 打桩工具
# ---------------------------------------------------------------------------



class FakeResponse:
    """urlopen 返回值替身：支持上下文管理器与 read(size)。

    chunk_limit 模拟分块传输：每次 read(size) 至多返回 chunk_limit 字节，
    逼真驱动 download_pdf 的流式拷贝循环（返回多次非空块 + 一次空块）。
    """

    def __init__(self, payload: bytes, chunk_limit: int | None = None):
        self._stream = io.BytesIO(payload)
        self._chunk_limit = chunk_limit

    def read(self, size: int = -1) -> bytes:
        if self._chunk_limit is not None and size > self._chunk_limit:
            size = self._chunk_limit
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeUrlopen:
    """urllib.request.urlopen 打桩：记录每次请求 URL，返回预置响应。

    routes 提供时按「URL 含子串」分发不同载荷（search 与 download 同测时用），
    否则所有请求返回同一 payload。
    """

    def __init__(
        self,
        payload: bytes,
        chunk_limit: int | None = None,
        routes: dict[str, bytes] | None = None,
    ):
        self.payload = payload
        self.chunk_limit = chunk_limit
        self.routes = routes or {}
        self.calls: list[str] = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        payload = self.payload
        for marker, routed in self.routes.items():
            if marker in url:
                payload = routed
                break
        return FakeResponse(payload, self.chunk_limit)

    @property
    def last_url(self) -> str:
        return self.calls[-1]


class FlakyResponse:
    """urlopen 返回值替身：read 先返回一块数据，之后抛错（模拟流中途连接重置）。"""

    def __init__(self, first_chunk: bytes, error: Exception):
        self._first_chunk = first_chunk
        self._error = error
        self._served = False

    def read(self, size: int = -1) -> bytes:
        if not self._served:
            self._served = True
            return self._first_chunk
        raise self._error

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class ScriptedUrlopen:
    """urlopen 打桩：按脚本逐次给出响应载荷或异常，驱动 429 重试路径。

    script 每项是 bytes（作为响应载荷）或 Exception（抛出），
    调用次数超过脚本长度时 IndexError（测试里脚本长度即预期调用次数）。
    """

    def __init__(self, script: list[bytes | Exception]):
        self.script = list(script)
        self.calls: list[str] = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return FakeResponse(action)


class FakeClock:
    """打桩 time：monotonic 返回可控时钟；sleep 记录时长并推进时钟（不真睡）。"""

    def __init__(self, start: float = 100.0):
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def rate_gate_reset(monkeypatch):
    """每个测试重置模块级限速闸时间戳，避免测试间状态泄漏。"""
    monkeypatch.setattr(arxiv_search, "_last_call_time", None)


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("time.monotonic", clock.monotonic)
    monkeypatch.setattr("time.sleep", clock.sleep)
    return clock


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_parses_entry_fields(self, monkeypatch):
        fake = FakeUrlopen(ATTENTION_FEED.encode())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        results = search("attention is all you need")

        assert len(results) == 2
        first = results[0]
        assert isinstance(first, ArxivResult)
        assert first.arxiv_id == "1706.03762"  # <id> 去掉 abs 前缀与版本号
        assert first.title == "Attention Is All You Need"
        assert first.authors == ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"]
        assert first.abstract == (
            "The dominant sequence transduction models are based on complex recurrent or\n"
            "convolutional neural networks that include an encoder and a decoder.\n"
            "We propose the Transformer."
        )
        assert first.published == "2017-06-12T01:19:08Z"  # feed ISO 原样
        assert first.updated == "2017-07-26T09:22:34Z"
        # primary_category 的 term 已在 <category> 列表中 → 不重复
        assert first.categories == ["cs.CL", "cs.AI", "stat.ML"]
        # feed 有值用 feed 的
        assert first.pdf_url == "https://arxiv.org/pdf/1706.03762v2"
        assert first.abs_url == "http://arxiv.org/abs/1706.03762v2"

    def test_fallbacks_for_missing_links_and_old_style_id(self, monkeypatch):
        fake = FakeUrlopen(ATTENTION_FEED.encode())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        results = search("machine learning")

        second = results[1]
        assert second.arxiv_id == "cs/0112017"  # 老式 ID 保留 archive 前缀，去 v1
        assert second.title == "Applying Machine Learning to Higher Order Pattern Mining"
        assert second.authors == ["Grace Hopper"]
        assert second.pdf_url == "https://arxiv.org/pdf/cs/0112017"  # 缺失时回退构造
        assert second.abs_url == "https://arxiv.org/abs/cs/0112017"
        assert second.categories == ["cs.AI", "cs.LG"]  # primary 不在 category 中 → 追加

    def test_request_url_format(self, monkeypatch):
        fake = FakeUrlopen(ATTENTION_FEED.encode())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        search("attention is all you need", max_results=3)

        assert fake.calls == [
            "https://export.arxiv.org/api/query"
            "?search_query=all:%22attention%20is%20all%20you%20need%22"
            "&start=0&max_results=3"
        ]

    def test_query_with_special_characters_is_encoded(self, monkeypatch):
        fake = FakeUrlopen(ATTENTION_FEED.encode())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        search("deep learning: models & optimization")

        assert (
            "search_query=all:%22deep%20learning%3A%20models%20%26%20optimization%22"
            in fake.last_url
        )

    def test_empty_feed_returns_empty_list(self, monkeypatch):
        fake = FakeUrlopen(EMPTY_FEED.encode())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        assert search("no such paper exists") == []


# ---------------------------------------------------------------------------
# download_pdf
# ---------------------------------------------------------------------------


class TestDownloadPdf:
    def test_downloads_to_sanitized_filename(self, monkeypatch, tmp_path):
        fake = FakeUrlopen(PDF_PAYLOAD, chunk_limit=7)
        monkeypatch.setattr("urllib.request.urlopen", fake)

        dest_dir = tmp_path / "downloads"  # 不存在 → 验证自动创建
        result = download_pdf("cs/0112017", str(dest_dir))  # str 路径也接受

        assert isinstance(result, Path)
        assert result == dest_dir / "cs_0112017.pdf"  # "/" 消毒为 "_"
        assert result.read_bytes() == PDF_PAYLOAD
        assert fake.calls == ["https://arxiv.org/pdf/cs/0112017"]

    def test_existing_file_skips_network_and_rate_gate(
        self, monkeypatch, tmp_path, fake_clock
    ):
        def no_network(*args, **kwargs):
            raise AssertionError("cache hit must not issue a network request")

        monkeypatch.setattr("urllib.request.urlopen", no_network)
        existing = tmp_path / "1706.03762.pdf"
        existing.write_bytes(b"cached bytes")
        # 模拟限速闸刚放过一次调用：若缓存命中仍过闸，会 sleep(3.0)
        monkeypatch.setattr(arxiv_search, "_last_call_time", fake_clock.now)

        result = download_pdf("1706.03762", tmp_path)

        assert result == existing
        assert result.read_bytes() == b"cached bytes"  # 不覆盖已有文件
        assert fake_clock.sleeps == []  # 缓存命中不过闸（网络调用才限速）

    def test_mid_stream_failure_does_not_poison_cache(
        self, monkeypatch, tmp_path, fake_clock
    ):
        """流中途失败：① dest 不留半截文件（缓存不得被毒化），
        ② 异常向上传播，③ 重试能重新下载成功。"""
        error = ConnectionResetError("connection reset mid-stream")

        def flaky_urlopen(request, timeout=None):
            return FlakyResponse(b"%PDF-1.4 truncated prefix", error)

        monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)

        dest = tmp_path / "1706.03762.pdf"
        with pytest.raises(ConnectionResetError):  # ② 异常向上传播
            download_pdf("1706.03762", tmp_path)

        assert not dest.exists()  # ① 不留截断 PDF
        assert list(tmp_path.iterdir()) == []  # .part 临时文件也清理，无残留

        # ③ 再次调用能重新下载成功，内容完整
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(PDF_PAYLOAD, chunk_limit=7)
        )
        result = download_pdf("1706.03762", tmp_path)
        assert result == dest
        assert result.read_bytes() == PDF_PAYLOAD


# ---------------------------------------------------------------------------
# 限速闸（search 与 download_pdf 共用）
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_second_call_sleeps_to_three_seconds(self, monkeypatch, fake_clock):
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(ATTENTION_FEED.encode())
        )
        search("first")
        assert fake_clock.sleeps == []  # 首次调用不等待

        search("second")
        assert fake_clock.sleeps == [3.0]  # 时钟未走 → 补足 3 秒

    def test_gate_shared_by_search_and_download(
        self, monkeypatch, fake_clock, tmp_path
    ):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            FakeUrlopen(
                PDF_PAYLOAD,
                routes={"export.arxiv.org/api/query": ATTENTION_FEED.encode()},
            ),
        )
        search("first")
        download_pdf("1706.03762", tmp_path)
        assert fake_clock.sleeps == [3.0]
        search("third")
        assert fake_clock.sleeps == [3.0, 3.0]  # 共用一个闸

    def test_no_sleep_when_interval_elapsed(self, monkeypatch, fake_clock):
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(ATTENTION_FEED.encode())
        )
        search("first")
        fake_clock.now += 5.0  # 距上次调用已过 5 秒（> 3 秒间隔）

        search("second")

        assert fake_clock.sleeps == []


def test_default_download_dir_constant():
    assert DEFAULT_DOWNLOAD_DIR == Path.home() / ".local/share/paper-master/downloads"


# ---------------------------------------------------------------------------
# 三源编排链 search_with_fallback：S2（配 key 才参与）→ arXiv → OpenAlex
# （spec 2026-09-15-s2-primary-search；OpenAlex 兜底为决策 #21 扩展 D）
# ---------------------------------------------------------------------------

#: 编排链降级标注（notice）逐字文案
S2_UNAVAILABLE_NOTICE = "[Semantic Scholar 不可用，以下为 arXiv 检索结果]"
ARXIV_UNAVAILABLE_NOTICE = "[arXiv 暂不可用，以下为 OpenAlex 兜底结果]"


def _openalex_stub(monkeypatch, results=None, calls=None, error=None):
    """打桩 openalex_search.search；记录调用参数，可选抛异常。"""

    def fake(query, max_results=10):
        if calls is not None:
            calls.append((query, max_results))
        if error is not None:
            raise error
        return results if results is not None else []

    monkeypatch.setattr(openalex_search, "search", fake)


def _forbid_openalex(monkeypatch):
    def must_not_call(*args, **kwargs):
        raise AssertionError("openalex fallback must not be triggered")

    monkeypatch.setattr(openalex_search, "search", must_not_call)


def _forbid_arxiv(monkeypatch):
    def must_not_call(*args, **kwargs):
        raise AssertionError("arxiv search must not be triggered")

    monkeypatch.setattr(arxiv_search, "search", must_not_call)


def _forbid_s2(monkeypatch):
    def must_not_call(*args, **kwargs):
        raise AssertionError("s2 search must not be triggered")

    monkeypatch.setattr(s2_search, "search", must_not_call)


def _raiser(exc: Exception):
    def f(query, max_results=10):
        raise exc

    return f


def _result(arxiv_id: str = "2312.10997", title: str = "RAPTOR") -> ArxivResult:
    return ArxivResult(
        arxiv_id=arxiv_id, title=title, authors=["S Saroff"], abstract="",
        published="2023", updated="", categories=[],
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
    )


class TestSearchWithFallback:
    def test_arxiv_success_returns_arxiv_source(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(ATTENTION_FEED.encode())
        )
        _forbid_openalex(monkeypatch)

        results, source, notice = search_with_fallback("attention")

        assert source == "arxiv"
        assert len(results) == 2
        assert notice == ""  # 无 key 静默走 arXiv，无标注

    def test_empty_results_do_not_trigger_fallback(self, monkeypatch):
        """空结果是成功而非失败：返回 ([], "arxiv", "")，不碰 OpenAlex。"""
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(EMPTY_FEED.encode())
        )
        _forbid_openalex(monkeypatch)

        results, source, notice = search_with_fallback("no such paper exists")

        assert results == []
        assert source == "arxiv"
        assert notice == ""

    @pytest.mark.parametrize("raise_", [
        arxiv_search.ArxivRateLimitError,
        lambda: URLError("timeout"),
        lambda: OSError("connection reset"),
    ], ids=["rate-limit", "urlerror", "oserror"])
    def test_arxiv_failure_falls_back_to_openalex(self, monkeypatch, raise_):
        fallback_result = _result()
        monkeypatch.setattr(arxiv_search, "search", _raiser(raise_()))
        calls = []
        _openalex_stub(monkeypatch, results=[fallback_result], calls=calls)

        results, source, notice = search_with_fallback("raptor", 5)

        assert source == "openalex"
        assert results == [fallback_result]
        assert notice == ARXIV_UNAVAILABLE_NOTICE  # 现有文案迁移进 notice
        assert calls == [("raptor", 5)]  # (query, max_results) 原样转发

    def test_arxiv_parse_error_falls_back_to_openalex(self, monkeypatch):
        """真解析路径：feed 非法 XML → ET.ParseError → 兜底。"""
        monkeypatch.setattr(
            "urllib.request.urlopen", FakeUrlopen(b"this is not atom xml")
        )
        fallback_result = _result()
        _openalex_stub(monkeypatch, results=[fallback_result])

        results, source, notice = search_with_fallback("raptor")

        assert source == "openalex"
        assert results == [fallback_result]
        assert notice == ARXIV_UNAVAILABLE_NOTICE

    def test_openalex_failure_propagates(self, monkeypatch):
        """arXiv 失败且 OpenAlex 也失败 → 异常透传（由调用方兜底为 502 等）。"""
        monkeypatch.setattr(arxiv_search, "search", _raiser(URLError("arxiv down")))
        _openalex_stub(monkeypatch, error=URLError("openalex down"))

        with pytest.raises(URLError):
            search_with_fallback("raptor")

    # -- S2 主源腿（spec 2026-09-15-s2-primary-search）----------------------

    @pytest.mark.usefixtures("s2_enabled")
    def test_s2_success_returns_s2_source(self, monkeypatch):
        """Oracle：配 key 且 S2 成功 → (结果, "s2", "")，后续腿不参与。"""
        r1 = _result("1706.03762", "Attention Is All You Need")
        calls = []

        def fake_s2(query, max_results=10):
            calls.append((query, max_results))
            return [r1]

        monkeypatch.setattr(s2_search, "search", fake_s2)
        _forbid_arxiv(monkeypatch)
        _forbid_openalex(monkeypatch)

        results, source, notice = search_with_fallback("attention", 5)

        assert (results, source, notice) == ([r1], "s2", "")
        assert calls == [("attention", 5)]  # (query, max_results) 原样转发

    def test_no_key_skips_s2_silently(self, monkeypatch):
        """Oracle：无 key → 直接走 arXiv，(结果, "arxiv", "")，且
        s2_search.search 未被调用（forbid-stub）。"""
        r2 = _result("1706.03762", "Attention Is All You Need")
        monkeypatch.setattr(s2_search, "load_api_key", lambda: None)
        _forbid_s2(monkeypatch)
        monkeypatch.setattr(
            arxiv_search, "search", lambda query, max_results=10: [r2]
        )
        _forbid_openalex(monkeypatch)

        results, source, notice = search_with_fallback("attention")

        assert (results, source, notice) == ([r2], "arxiv", "")  # 静默，无标注

    @pytest.mark.usefixtures("s2_enabled")
    @pytest.mark.parametrize("raise_", [
        lambda: s2_search.S2RateLimitError(),
        lambda: s2_search.S2Error("bad key"),
        lambda: URLError("timeout"),
        lambda: OSError("connection reset"),
        lambda: ET.ParseError("unparseable payload"),
        lambda: json.JSONDecodeError("Expecting value", "x", 0),
    ], ids=["rate-limit", "s2-error", "urlerror", "oserror", "parse-error",
            "json-decode-error"])
    def test_s2_failure_falls_back_to_arxiv_with_notice(
        self, monkeypatch, raise_
    ):
        """Oracle：配 key 但 S2 失败（六类异常）→ 落 arXiv，
        notice 为 S2 不可用标注（逐字）。"""
        r2 = _result()
        monkeypatch.setattr(s2_search, "search", _raiser(raise_()))
        monkeypatch.setattr(
            arxiv_search, "search", lambda query, max_results=10: [r2]
        )
        _forbid_openalex(monkeypatch)

        results, source, notice = search_with_fallback("attention")

        assert (results, source, notice) == (
            [r2], "arxiv", S2_UNAVAILABLE_NOTICE,
        )

    @pytest.mark.usefixtures("s2_enabled")
    def test_s2_not_configured_error_is_silent_not_failure(self, monkeypatch):
        """except 顺序陷阱：S2NotConfiguredError 继承自 S2Error，未配置分支
        必须先于 S2Error 捕获——静默跳过，不得被吞成失败标注。"""
        r2 = _result()
        monkeypatch.setattr(
            s2_search, "search",
            _raiser(s2_search.S2NotConfiguredError("key 消失了")),
        )
        monkeypatch.setattr(
            arxiv_search, "search", lambda query, max_results=10: [r2]
        )

        results, source, notice = search_with_fallback("attention")

        assert (results, source, notice) == ([r2], "arxiv", "")

    @pytest.mark.usefixtures("s2_enabled")
    def test_s2_and_arxiv_failure_falls_to_openalex(self, monkeypatch):
        """Oracle：S2、arXiv 都抛 URLError → OpenAlex 兜底；notice 为 arXiv
        不可用标注（替代 S2 标注，非叠加）。"""
        r3 = _result()
        monkeypatch.setattr(s2_search, "search", _raiser(URLError("s2 down")))
        monkeypatch.setattr(arxiv_search, "search", _raiser(URLError("arxiv down")))
        _openalex_stub(monkeypatch, results=[r3])

        results, source, notice = search_with_fallback("attention")

        assert (results, source, notice) == (
            [r3], "openalex", ARXIV_UNAVAILABLE_NOTICE,
        )

    @pytest.mark.usefixtures("s2_enabled")
    def test_s2_empty_results_are_final_answer(self, monkeypatch):
        """空结果语义不变：S2 返回 [] 即最终答案，不触发后续兜底。"""
        monkeypatch.setattr(
            s2_search, "search", lambda query, max_results=10: []
        )
        _forbid_arxiv(monkeypatch)
        _forbid_openalex(monkeypatch)

        results, source, notice = search_with_fallback("attention")

        assert (results, source, notice) == ([], "s2", "")


def test_s2_disabled_by_default_even_with_real_config(tmp_path, monkeypatch):
    """conftest autouse 质量关：真 config.yaml 配了 key 的机器上，未显式
    启用 s2_enabled 的测试 load_api_key() 也必须得 None（既有测试零触网）。"""
    (tmp_path / "config.yaml").write_text(
        "external_search:\n"
        "  semantic_scholar:\n"
        "    api_key: real-key-on-this-machine\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert s2_search.load_api_key() is None


# ---------------------------------------------------------------------------
# 429 退避重试（_open；search 与 download_pdf 共用）
# ---------------------------------------------------------------------------


def _http_429() -> HTTPError:
    return HTTPError(
        "https://export.arxiv.org/api/query", 429, "Too Many Requests", None, None
    )


class TestRetryOn429:
    def test_retry_constants_and_friendly_message(self):
        assert arxiv_search.RETRY_WAIT_SECONDS == 15
        assert (
            str(arxiv_search.ArxivRateLimitError())
            == "arXiv 限流中，请稍后 1-2 分钟再试"
        )

    def test_first_429_retries_once_and_succeeds(self, monkeypatch, fake_clock):
        fake = ScriptedUrlopen([_http_429(), ATTENTION_FEED.encode()])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        results = search("rag", 3)

        assert len(results) == 2  # 重试拿到正常 Atom，正常返回
        assert fake.calls[0] == fake.calls[1]  # 重试同一 URL
        assert fake_clock.sleeps == [15]  # 退避恰好一次 RETRY_WAIT_SECONDS

    def test_persistent_429_raises_friendly_error_after_one_retry(
        self, monkeypatch, fake_clock
    ):
        fake = ScriptedUrlopen([_http_429(), _http_429()])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        with pytest.raises(arxiv_search.ArxivRateLimitError) as exc_info:
            search("rag", 3)

        assert str(exc_info.value) == "arXiv 限流中，请稍后 1-2 分钟再试"
        assert len(fake.calls) == 2  # 只重试一次，不再第三次
        assert fake_clock.sleeps == [15]  # 只睡一次

    def test_non_429_http_error_propagates_without_sleep(
        self, monkeypatch, fake_clock
    ):
        not_found = HTTPError(
            "https://export.arxiv.org/api/query", 404, "Not Found", None, None
        )
        fake = ScriptedUrlopen([not_found])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        with pytest.raises(HTTPError) as exc_info:
            search("rag", 3)

        assert exc_info.value.code == 404  # 原异常直接抛
        assert len(fake.calls) == 1  # 不重试
        assert fake_clock.sleeps == []  # 不 sleep

    def test_download_pdf_shares_retry_via_open(self, monkeypatch, fake_clock, tmp_path):
        """download_pdf 经共用 _open 自动获得 429 退避重试。"""
        fake = ScriptedUrlopen([_http_429(), PDF_PAYLOAD])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        result = download_pdf("1706.03762", tmp_path)

        assert result.read_bytes() == PDF_PAYLOAD
        assert fake.calls == [
            "https://arxiv.org/pdf/1706.03762",
            "https://arxiv.org/pdf/1706.03762",
        ]
        assert fake_clock.sleeps == [15]
