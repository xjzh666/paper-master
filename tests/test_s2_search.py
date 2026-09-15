# tests/test_s2_search.py
"""s2_search 单测：零触网零真睡（模块边界打桩：urllib.request.urlopen、
time.monotonic/sleep、s2_search.load_api_key / s2_search.load_config）。

FakeResponse / FakeUrlopen / ScriptedUrlopen / FakeClock 复制自
tests/test_arxiv_search.py 的同名工具（模式一致，状态互不共享）。
"""
import io
import logging
from urllib.error import HTTPError, URLError

import pytest
import yaml

import paper_reader.s2_search as s2_search
from paper_reader.arxiv_search import ArxivResult

#: 假 key（非真值）：仅用于断言请求头透传，绝不触网
FAKE_KEY = "fake-s2-key-not-a-real-secret"

_SEARCH_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,authors,abstract,tldr,citationCount,externalIds,year"

# brief Oracle fixture：覆盖 null 作者名 / null abstract / tldr 对象 /
# 无 ArXiv id 记录 / null year 的全部映射边界
ORACLE_BODY = {
    "data": [
        {
            "title": "Attention  is\nAll You Need",
            "authors": [{"name": "A"}, {"name": None}, {"name": "B"}],
            "abstract": None,
            "tldr": {"model": "x", "text": "TL;text"},
            "citationCount": 192499,
            "externalIds": {"ArXiv": "1706.03762"},
            "year": 2017,
        },
        {"title": "No ArXiv Here", "externalIds": {"DOI": "10.1/x"}},
        {"title": "Yearless", "externalIds": {"ArXiv": "2401.00001"}, "year": None},
    ]
}


# ---------------------------------------------------------------------------
# 打桩工具（复制自 tests/test_arxiv_search.py）
# ---------------------------------------------------------------------------


class FakeResponse:
    """urlopen 返回值替身：支持上下文管理器与 read()。"""

    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeUrlopen:
    """urllib.request.urlopen 打桩：记录请求 URL 与 Request 对象（查头）。"""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls: list[str] = []
        self.requests = []

    def __call__(self, request, timeout=None):
        self.calls.append(request.full_url)
        self.requests.append(request)
        return FakeResponse(self.payload)


class ScriptedUrlopen:
    """urlopen 打桩：按脚本逐次给出响应载荷或异常，驱动 429/坏 key 路径。

    script 每项是 bytes（作为响应载荷）或 Exception（抛出），
    调用次数超过脚本长度时 IndexError（脚本长度即预期调用次数）。
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
def s2_isolated(monkeypatch):
    """每个测试重置模块级限速闸时间戳；默认把 load_config 打桩为抛
    FileNotFoundError（真实 config.yaml 永不读取）→ load_api_key() 返回
    None、S2 禁用，保证零触网。需要 key 的测试用 fake_key 覆盖
    load_api_key；直接测 load_api_key 的用例自行覆盖 load_config。"""
    monkeypatch.setattr(s2_search, "_last_call_time", None)

    def no_real_config(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(s2_search, "load_config", no_real_config)


@pytest.fixture
def fake_key(monkeypatch):
    monkeypatch.setattr(s2_search, "load_api_key", lambda: FAKE_KEY)


@pytest.fixture
def fake_clock(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("time.monotonic", clock.monotonic)
    monkeypatch.setattr("time.sleep", clock.sleep)
    return clock


def _http(status: int) -> HTTPError:
    return HTTPError(_SEARCH_API, status, "err", None, None)


def _oracle_json() -> bytes:
    import json

    return json.dumps(ORACLE_BODY).encode()


# ---------------------------------------------------------------------------
# 映射与请求格式
# ---------------------------------------------------------------------------


class TestSearch:
    def test_oracle_mapping_and_arxiv_filtering(self, monkeypatch, fake_key):
        monkeypatch.setattr("urllib.request.urlopen", FakeUrlopen(_oracle_json()))

        results = s2_search.search("attention is all you need")

        assert len(results) == 2  # 无 ArXiv id 的记录被过滤
        first = results[0]
        assert isinstance(first, ArxivResult)
        assert first.arxiv_id == "1706.03762"
        assert first.title == "Attention is All You Need"  # 空白折叠
        assert first.authors == ["A", "B"]  # null 名剔除
        assert first.abstract == ""  # abstract 为 null → ""
        assert first.tldr == "TL;text"  # tldr 对象取 text
        assert first.citation_count == 192499
        assert first.published == "2017"  # year → str
        assert first.updated == ""
        assert first.categories == []
        assert first.pdf_url == ""
        assert first.abs_url == ""
        second = results[1]
        assert second.arxiv_id == "2401.00001"
        assert second.title == "Yearless"
        assert second.published == ""  # year 为 null → ""
        assert second.tldr == ""
        assert second.citation_count is None  # citationCount 缺失 → None
        assert second.abstract == ""
        assert second.authors == []

    def test_request_url_format(self, monkeypatch, fake_key):
        fake = FakeUrlopen(_oracle_json())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        s2_search.search("attention is all you need")

        assert fake.calls == [
            f"{_SEARCH_API}?query=attention%20is%20all%20you%20need"
            f"&limit=10&fields={_FIELDS}"
        ]

    def test_api_key_header_sent(self, monkeypatch, fake_key):
        fake = FakeUrlopen(_oracle_json())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        s2_search.search("attention")

        # urllib 把头名 capitalize 为 X-api-key
        assert fake.requests[0].headers.get("X-api-key") == FAKE_KEY

    @pytest.mark.parametrize(
        "max_results,expected_limit", [(0, 1), (99, 50), (10, 10)]
    )
    def test_max_results_clamped_to_bounds(
        self, monkeypatch, fake_key, max_results, expected_limit
    ):
        fake = FakeUrlopen(_oracle_json())
        monkeypatch.setattr("urllib.request.urlopen", fake)

        s2_search.search("attention", max_results=max_results)

        assert f"&limit={expected_limit}&" in fake.calls[0]


# ---------------------------------------------------------------------------
# load_api_key（config 读取容错）
# ---------------------------------------------------------------------------


class TestLoadApiKey:
    @pytest.mark.parametrize("config", [
        None,                       # 空 yaml（safe_load → None）
        {},                         # 无 external_search 段
        {"external_search": {}},    # 无 semantic_scholar 段
        {"external_search": {"semantic_scholar": {}}},   # 无 api_key 键
        {"external_search": {"semantic_scholar": {"api_key": ""}}},  # 空值
    ], ids=["empty-yaml", "no-section", "no-s2-section", "no-key",
            "blank-key"])
    def test_missing_or_blank_config_returns_none(self, monkeypatch, config):
        monkeypatch.setattr(s2_search, "load_config", lambda path: config)

        assert s2_search.load_api_key() is None

    @pytest.mark.parametrize("error", [
        FileNotFoundError("config.yaml"),
        yaml.YAMLError("bad yaml"),
    ], ids=["file-not-found", "yaml-error"])
    def test_unreadable_config_returns_none(self, monkeypatch, error):
        def boom(path):
            raise error

        monkeypatch.setattr(s2_search, "load_config", boom)

        assert s2_search.load_api_key() is None

    def test_configured_key_returned(self, monkeypatch):
        monkeypatch.setattr(
            s2_search, "load_config",
            lambda path: {"external_search": {"semantic_scholar":
                                              {"api_key": "k-123"}}},
        )

        assert s2_search.load_api_key() == "k-123"


# ---------------------------------------------------------------------------
# 未配置 key
# ---------------------------------------------------------------------------


class TestNotConfigured:
    def test_missing_key_raises_before_any_network(self, monkeypatch):
        def no_network(*args, **kwargs):
            raise AssertionError("missing key must not issue a network request")

        monkeypatch.setattr("urllib.request.urlopen", no_network)
        # load_config 已被 autouse fixture 打桩 → load_api_key() 为 None

        with pytest.raises(s2_search.S2NotConfiguredError):
            s2_search.search("attention")


# ---------------------------------------------------------------------------
# 限速闸（1 req/s）
# ---------------------------------------------------------------------------


class TestRateGate:
    def test_second_call_sleeps_one_second(self, monkeypatch, fake_key,
                                           fake_clock):
        monkeypatch.setattr("urllib.request.urlopen",
                            FakeUrlopen(_oracle_json()))
        s2_search.search("first")
        assert fake_clock.sleeps == []  # 首次调用不等待

        s2_search.search("second")
        assert fake_clock.sleeps == [1.0]  # 时钟未走 → 补足 1 秒

    def test_no_sleep_when_interval_elapsed(self, monkeypatch, fake_key,
                                            fake_clock):
        monkeypatch.setattr("urllib.request.urlopen",
                            FakeUrlopen(_oracle_json()))
        s2_search.search("first")
        fake_clock.now += 2.0  # 距上次调用已过 2 秒（> 1 秒间隔）

        s2_search.search("second")

        assert fake_clock.sleeps == []


# ---------------------------------------------------------------------------
# 429 退避重试
# ---------------------------------------------------------------------------


class TestRetryOn429:
    def test_constants_and_friendly_message(self):
        assert s2_search.RETRY_WAIT_SECONDS == 5
        assert (str(s2_search.S2RateLimitError())
                == "Semantic Scholar 限流中，请稍后重试")

    def test_first_429_retries_once_and_succeeds(self, monkeypatch, fake_key,
                                                 fake_clock):
        fake = ScriptedUrlopen([_http(429), _oracle_json()])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        results = s2_search.search("attention")

        assert len(results) == 2  # 重试拿到正常响应，正常返回
        assert fake.calls[0] == fake.calls[1]  # 重试同一 URL
        assert fake_clock.sleeps == [5]  # 退避恰好一次 RETRY_WAIT_SECONDS

    def test_persistent_429_raises_friendly_error_after_one_retry(
        self, monkeypatch, fake_key, fake_clock
    ):
        fake = ScriptedUrlopen([_http(429), _http(429)])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        with pytest.raises(s2_search.S2RateLimitError) as exc_info:
            s2_search.search("attention")

        assert str(exc_info.value) == "Semantic Scholar 限流中，请稍后重试"
        assert len(fake.calls) == 2  # 只重试一次，不再第三次
        assert fake_clock.sleeps == [5]  # 只睡一次


# ---------------------------------------------------------------------------
# 坏 key（401/403）
# ---------------------------------------------------------------------------


class TestBadKey:
    @pytest.mark.parametrize("status", [401, 403])
    def test_bad_key_raises_s2_error_with_single_warning(
        self, monkeypatch, fake_key, fake_clock, caplog, status
    ):
        fake = ScriptedUrlopen([_http(status)])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(s2_search.S2Error) as exc_info:
                s2_search.search("attention")

        assert not isinstance(exc_info.value, s2_search.S2RateLimitError)
        assert len(fake.calls) == 1  # 坏 key 不重试
        assert fake_clock.sleeps == []  # 不 sleep
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1  # logging.warning 恰好一句


# ---------------------------------------------------------------------------
# 其余异常透传
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_non_special_http_error_propagates(self, monkeypatch, fake_key,
                                               fake_clock):
        fake = ScriptedUrlopen([_http(404)])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        with pytest.raises(HTTPError) as exc_info:
            s2_search.search("attention")

        assert exc_info.value.code == 404  # 原异常直接抛，不包 S2Error
        assert len(fake.calls) == 1
        assert fake_clock.sleeps == []

    def test_urlerror_propagates(self, monkeypatch, fake_key, fake_clock):
        fake = ScriptedUrlopen([URLError("connection refused")])
        monkeypatch.setattr("urllib.request.urlopen", fake)

        with pytest.raises(URLError):
            s2_search.search("attention")

        assert fake_clock.sleeps == []
