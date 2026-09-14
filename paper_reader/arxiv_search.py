"""arXiv 外部论文搜索与 PDF 下载（P6.1，源选型见决策 #20）。

按查询词检索 arXiv API（Atom XML）返回结构化结果；按 arxiv_id 下载 PDF
到本地目录。两个入口共享一个模块级限速闸：任意两次 arXiv 网络调用
间隔 ≥3 秒（arXiv 官方礼貌准则），不足则自动等待补足。

零第三方依赖：HTTP 用 urllib.request，XML 用 xml.etree.ElementTree。
"""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_DOWNLOAD_DIR",
    "ArxivRateLimitError",
    "ArxivResult",
    "RETRY_WAIT_SECONDS",
    "download_pdf",
    "search",
]

QUERY_API = "https://export.arxiv.org/api/query"
PDF_URL_TEMPLATE = "https://arxiv.org/pdf/{arxiv_id}"
ABS_URL_TEMPLATE = "https://arxiv.org/abs/{arxiv_id}"

#: 默认下载目录（Task 2/3 的端点与 agent 工具用）
DEFAULT_DOWNLOAD_DIR = Path.home() / ".local/share/paper-master/downloads"

#: HTTP 429 退避重试前的等待秒数（决策 #21 扩展 A）
RETRY_WAIT_SECONDS = 15


class ArxivRateLimitError(Exception):
    """arXiv 限流（HTTP 429 退避重试一次仍失败）；str 固定为友好文案。"""

    def __str__(self) -> str:
        return "arXiv 限流中，请稍后 1-2 分钟再试"

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_ABS_ID_PREFIXES = ("http://arxiv.org/abs/", "https://arxiv.org/abs/")

_MIN_INTERVAL = 3.0  # arXiv 官方礼貌准则：调用间隔 ≥3 秒
_TIMEOUT = 30
_CHUNK_SIZE = 64 * 1024
_USER_AGENT = "paper-master/0.1 (+https://github.com/xjzh666/paper-master)"

# 模块级串行限速闸：search 与 download_pdf 共用
_RATE_LOCK = threading.Lock()
_last_call_time: float | None = None


@dataclass
class ArxivResult:
    """一条 arXiv 检索结果（published/updated 保留 feed 中的 ISO 字符串原样）。"""

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    categories: list[str]
    pdf_url: str
    abs_url: str


def search(query: str, max_results: int = 10) -> list[ArxivResult]:
    """按查询词检索 arXiv，返回结构化结果列表；无 entry 的响应返回 []。"""
    encoded = urllib.parse.quote(query, safe="")
    url = (
        f"{QUERY_API}?search_query=all:%22{encoded}%22"
        f"&start=0&max_results={max_results}"
    )
    with _open(url) as response:
        data = response.read()
    return _parse_feed(data)


def download_pdf(arxiv_id: str, dest_dir: str | Path) -> Path:
    """下载 https://arxiv.org/pdf/{arxiv_id} 到 dest_dir。

    文件名为 {arxiv_id 消毒}.pdf（"/" 替换为 "_"）；文件已存在时不发起
    网络请求（也不消耗限速闸），直接返回现有路径。
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{arxiv_id.replace('/', '_')}.pdf"
    if dest.exists():
        return dest

    url = PDF_URL_TEMPLATE.format(arxiv_id=arxiv_id)
    # 原子写：先落 .part，全部写成功后 os.replace；流中途失败时清理 .part
    # 并上抛，dest 不落盘——避免截断 PDF 留在缓存路径上被 exists 早退永久命中。
    tmp = dest.with_name(dest.name + ".part")
    try:
        with _open(url) as response, open(tmp, "wb") as fh:
            while chunk := response.read(_CHUNK_SIZE):
                fh.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, dest)
    return dest


# ---------------------------------------------------------------------------
# 限速闸与 HTTP
# ---------------------------------------------------------------------------


def _throttle() -> None:
    """保证任意两次 arXiv 网络调用间隔 ≥ _MIN_INTERVAL 秒。

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


def _open(url: str):
    """限速后发起 GET，返回可作上下文管理器的 response。

    HTTP 429 自动退避重试一次：等待 RETRY_WAIT_SECONDS 后过闸重发同一
    URL；重试仍 429 抛 ArxivRateLimitError。非 429 的 HTTPError 直接
    上抛（不等待、不重试）。
    """
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    _throttle()
    try:
        return urllib.request.urlopen(request, timeout=_TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code != 429:
            raise
        time.sleep(RETRY_WAIT_SECONDS)
        _throttle()
        try:
            return urllib.request.urlopen(request, timeout=_TIMEOUT)
        except urllib.error.HTTPError as retry_err:
            if retry_err.code == 429:
                raise ArxivRateLimitError() from retry_err
            raise


# ---------------------------------------------------------------------------
# Atom 解析
# ---------------------------------------------------------------------------


def _parse_feed(data: bytes) -> list[ArxivResult]:
    root = ET.fromstring(data)
    return [_parse_entry(entry) for entry in root.findall(f"{{{_ATOM_NS}}}entry")]


def _parse_entry(entry: ET.Element) -> ArxivResult:
    arxiv_id = _strip_version(entry.findtext(f"{{{_ATOM_NS}}}id", default=""))
    return ArxivResult(
        arxiv_id=arxiv_id,
        title=_clean_title(entry.findtext(f"{{{_ATOM_NS}}}title", default="")),
        authors=_parse_authors(entry),
        abstract=(entry.findtext(f"{{{_ATOM_NS}}}summary", default="") or "").strip(),
        published=entry.findtext(f"{{{_ATOM_NS}}}published", default=""),
        updated=entry.findtext(f"{{{_ATOM_NS}}}updated", default=""),
        categories=_parse_categories(entry),
        pdf_url=_link_href(entry, title="pdf")
        or PDF_URL_TEMPLATE.format(arxiv_id=arxiv_id),
        abs_url=_link_href(entry, rel="alternate")
        or ABS_URL_TEMPLATE.format(arxiv_id=arxiv_id),
    )


def _strip_version(raw_id: str) -> str:
    """http://arxiv.org/abs/1706.03762v2 → 1706.03762（保留老式 archive 前缀）。"""
    for prefix in _ABS_ID_PREFIXES:
        if raw_id.startswith(prefix):
            raw_id = raw_id[len(prefix):]
            break
    return re.sub(r"v\d+$", "", raw_id)


def _clean_title(raw: str | None) -> str:
    """标题是单行语义字段：折叠换行与连续空白。"""
    return " ".join(raw.split()) if raw else ""


def _parse_authors(entry: ET.Element) -> list[str]:
    authors: list[str] = []
    for author in entry.findall(f"{{{_ATOM_NS}}}author"):
        name = author.findtext(f"{{{_ATOM_NS}}}name")
        if name:
            authors.append(name)
    return authors


def _parse_categories(entry: ET.Element) -> list[str]:
    """按文档序收集 <category term>，primary_category 的 term 不在列时追加。"""
    categories = [
        term
        for category in entry.findall(f"{{{_ATOM_NS}}}category")
        if (term := category.get("term"))
    ]
    primary = entry.find(f"{{{_ARXIV_NS}}}primary_category")
    if primary is not None:
        term = primary.get("term")
        if term and term not in categories:
            categories.append(term)
    return categories


def _link_href(
    entry: ET.Element, *, title: str | None = None, rel: str | None = None
) -> str:
    """返回匹配 title/rel 属性的 <link> 的 href，找不到返回空串。"""
    for link in entry.findall(f"{{{_ATOM_NS}}}link"):
        if title is not None and link.get("title") != title:
            continue
        if rel is not None and link.get("rel") != rel:
            continue
        return link.get("href") or ""
    return ""
