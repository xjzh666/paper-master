"""Semantic Scholar 检索（S2 主源，spec 2026-09-15-s2-primary-search）。

带 API key 的关键词搜索：GET graph/v1/paper/search，只保留
externalIds.ArXiv 非空的记录（下载链路仍按 arxiv_id 走 arXiv CDN），
映射为 ArxivResult（结果自带 abstract/tldr/引用数，供 triage）。

零第三方依赖：HTTP 用 urllib.request，JSON 用 json。限速闸 1 req/s、
429 退避重试一次、坏 key（401/403）抛 S2Error 并 warning 一句，均参照
arxiv_search 的既有模式，但闸与异常为本模块自建，与 arXiv 路径互不影响。
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NoReturn

import yaml

from paper_reader.arxiv_search import ArxivResult
from paper_reader.llm import load_config

__all__ = [
    "RETRY_WAIT_SECONDS",
    "S2Error",
    "S2NotConfiguredError",
    "S2RateLimitError",
    "load_api_key",
    "search",
]

SEARCH_API = "https://api.semanticscholar.org/graph/v1/paper/search"

#: 响应只取映射 ArxivResult 所需字段
_FIELDS = "title,authors,abstract,tldr,citationCount,externalIds,year"

#: HTTP 429 退避重试前的等待秒数
RETRY_WAIT_SECONDS = 5

_MIN_INTERVAL = 1.0  # S2 免费档限速：1 req/s
_TIMEOUT = 30

# 模块级串行限速闸：任意两次 S2 网络调用（含 429 后的重试）共用
_RATE_LOCK = threading.Lock()
_last_call_time: float | None = None


class S2Error(Exception):
    """Semantic Scholar 请求失败（坏 key 等）。"""


class S2NotConfiguredError(S2Error):
    """未配置 API key（config.yaml external_search.semantic_scholar.api_key）。"""


class S2RateLimitError(S2Error):
    """S2 限流（HTTP 429 退避重试一次仍失败）；str 固定为友好文案。"""

    def __str__(self) -> str:
        return "Semantic Scholar 限流中，请稍后重试"


def search(query: str, max_results: int = 10) -> list[ArxivResult]:
    """按查询词检索 Semantic Scholar，返回带 arXiv id 的结果列表。"""
    api_key = load_api_key()
    if api_key is None:
        raise S2NotConfiguredError(
            "Semantic Scholar 未配置 API key"
            "（config.yaml external_search.semantic_scholar.api_key）"
        )
    encoded = urllib.parse.quote(query, safe="")
    limit = max(1, min(50, max_results))  # API 限制 limit ∈ [1, 50]
    url = f"{SEARCH_API}?query={encoded}&limit={limit}&fields={_FIELDS}"
    with _open(url, api_key) as response:
        payload = json.load(response)
    return _parse_results(payload)


def load_api_key() -> str | None:
    """读 config.yaml 的 external_search.semantic_scholar.api_key。

    文件缺失 / 坏 YAML / 段缺失 / 值为空一律返回 None（调用方据此禁用 S2 源）。
    """
    try:
        config = load_config("config.yaml") or {}
    except (FileNotFoundError, yaml.YAMLError):
        return None
    section = (config.get("external_search") or {}).get("semantic_scholar") or {}
    key = section.get("api_key")
    return key or None


# ---------------------------------------------------------------------------
# 限速闸与 HTTP
# ---------------------------------------------------------------------------


def _throttle() -> None:
    """保证任意两次 S2 网络调用间隔 ≥ _MIN_INTERVAL 秒。

    时间戳记为「本次调用的礼貌调度时刻」而非睡眠后的真实时钟，因此
    打桩的 time（sleep 不推进真实时钟）下逻辑依然正确。
    """
    global _last_call_time
    with _RATE_LOCK:
        now = time.monotonic()
        if _last_call_time is None:
            _last_call_time = now
            return
        scheduled = _last_call_time + _MIN_INTERVAL
        if now < scheduled:
            time.sleep(scheduled - now)
            _last_call_time = scheduled
        else:
            _last_call_time = now


def _open(url: str, api_key: str):
    """限速后带 x-api-key 发起 GET，返回可作上下文管理器的 response。

    HTTP 429 自动退避重试一次：等待 RETRY_WAIT_SECONDS 后过闸重发同一
    URL；重试仍 429 抛 S2RateLimitError。401/403（坏 key）抛 S2Error
    并 logging.warning 一句。其余 HTTPError 与 URLError/OSError 直接上抛。
    """
    request = urllib.request.Request(url, headers={"x-api-key": api_key})
    _throttle()
    try:
        return urllib.request.urlopen(request, timeout=_TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code != 429:
            _raise_for_http_error(e)
        time.sleep(RETRY_WAIT_SECONDS)
        _throttle()
        try:
            return urllib.request.urlopen(request, timeout=_TIMEOUT)
        except urllib.error.HTTPError as retry_err:
            if retry_err.code == 429:
                raise S2RateLimitError() from retry_err
            _raise_for_http_error(retry_err)


def _raise_for_http_error(e: urllib.error.HTTPError) -> NoReturn:
    """把非 429 的 HTTPError 翻译成 S2 异常：401/403 坏 key 可诊断，其余透传。"""
    if e.code in (401, 403):
        logging.warning(
            "Semantic Scholar API key 无效或无权限（HTTP %d），请检查"
            " config.yaml external_search.semantic_scholar.api_key", e.code,
        )
        raise S2Error(f"S2 请求被拒（HTTP {e.code}）：API key 无效或无权限") from e
    raise e


# ---------------------------------------------------------------------------
# 响应映射
# ---------------------------------------------------------------------------


def _parse_results(payload: dict) -> list[ArxivResult]:
    """信封键 data；仅保留 externalIds.ArXiv 非空的记录。"""
    results = []
    for p in payload.get("data") or []:
        arxiv_id = (p.get("externalIds") or {}).get("ArXiv")
        if not arxiv_id:
            continue
        results.append(_to_result(p, arxiv_id))
    return results


def _to_result(p: dict, arxiv_id: str) -> ArxivResult:
    return ArxivResult(
        arxiv_id=arxiv_id,
        title=" ".join(p["title"].split()) if p.get("title") else "",
        authors=[a["name"] for a in p.get("authors") or [] if a.get("name")],
        abstract=p.get("abstract") or "",
        published=str(p["year"]) if p.get("year") is not None else "",
        updated="",
        categories=[],
        pdf_url="",
        abs_url="",
        tldr=(p.get("tldr") or {}).get("text") or "",
        citation_count=p.get("citationCount"),
    )
