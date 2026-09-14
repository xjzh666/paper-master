# tests/test_arxiv_search.py
"""arxiv_search 单测：零触网（urllib.request.urlopen 全打桩，Atom 响应用
录制片段做 fixture）；限速测试打桩 time（FakeClock），全程不真睡。"""
import io
from pathlib import Path
from urllib.error import HTTPError

import pytest

import paper_reader.arxiv_search as arxiv_search
from paper_reader.arxiv_search import (
    DEFAULT_DOWNLOAD_DIR,
    ArxivResult,
    download_pdf,
    search,
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
