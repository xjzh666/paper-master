"""OpenAlex 检索兜底（P6.1 决策 #21 扩展 D）。

检索 OpenAlex works API，只保留能提取出 arxiv_id 的记录（即 arXiv 预印本），
映射为 ArxivResult 供 arxiv_search.search_with_fallback 降级使用；提取不出
arxiv_id 的纯期刊记录直接丢弃（不做打开支持）。下载流程不兜底：仍按
arxiv_id 走 arXiv CDN。

零第三方依赖：HTTP 用 urllib.request，JSON 用 json。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from paper_reader.arxiv_search import (
    ABS_URL_TEMPLATE,
    PDF_URL_TEMPLATE,
    ArxivResult,
)

__all__ = ["search"]

WORKS_API = "https://api.openalex.org/works"

#: select 精简响应：只取映射 ArxivResult 所需字段
_SELECT_FIELDS = (
    "id,doi,display_name,publication_year,publication_date,"
    "authorships,best_oa_location"
)

#: OpenAlex 礼貌池标识（官方推荐在请求中带 mailto）
_MAILTO = "paper-master@example.com"

_TIMEOUT = 30
_USER_AGENT = "paper-master/0.1 (+https://github.com/xjzh666/paper-master)"

# arXiv DOI：10.48550/arxiv.{id}（OpenAlex 存小写，Ignore大小写 稳妥）
_DOI_ARXIV_RE = re.compile(r"10\.48550/arxiv\.(.+)", re.IGNORECASE)
# arXiv PDF URL：arxiv.org/pdf/{id}（id 可能含老式 archive 前缀的斜杠）
_PDF_URL_ARXIV_RE = re.compile(r"arxiv\.org/pdf/([^?#]+)", re.IGNORECASE)


def search(query: str, max_results: int = 10) -> list[ArxivResult]:
    """按查询词检索 OpenAlex，返回能提取出 arxiv_id 的结果列表。

    只保留 arXiv 预印本记录（doi 或 best_oa_location.pdf_url 可提取出
    arxiv_id）；按 arxiv_id 去重保序，截取前 max_results 条。
    """
    encoded = urllib.parse.quote(query, safe="")
    per_page = max(1, min(50, max_results))
    url = (
        f"{WORKS_API}?search={encoded}"
        f"&per_page={per_page}"
        f"&select={_SELECT_FIELDS}"
        f"&mailto={_MAILTO}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        data = response.read()
    return _parse_works(json.loads(data), max_results)


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------


def _parse_works(payload: dict, max_results: int) -> list[ArxivResult]:
    """提取 arxiv_id → 去重保序 → 截取前 max_results 条。"""
    results: list[ArxivResult] = []
    seen: set[str] = set()
    for work in payload.get("results", []):
        arxiv_id = _extract_arxiv_id(work)
        if not arxiv_id or arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        results.append(_to_result(work, arxiv_id))
        if len(results) >= max_results:
            break
    return results


def _extract_arxiv_id(work: dict) -> str | None:
    """从 doi（10.48550/arxiv.{id}）或 pdf_url（arxiv.org/pdf/{id}）提取
    arxiv_id；去尾 .pdf、去版本号。两处都提取不出返回 None。"""
    doi = work.get("doi") or ""
    m = _DOI_ARXIV_RE.search(doi)
    if m:
        return _strip_version(m.group(1))
    location = work.get("best_oa_location") or {}
    pdf_url = location.get("pdf_url") or ""
    m = _PDF_URL_ARXIV_RE.search(pdf_url)
    if m:
        raw = m.group(1)
        if raw.endswith(".pdf"):
            raw = raw[: -len(".pdf")]
        return _strip_version(raw)
    return None


def _strip_version(raw_id: str) -> str:
    """2312.10997v5 / cs/0112017v1 → 去掉尾部版本号。"""
    return re.sub(r"v\d+$", "", raw_id)


def _to_result(work: dict, arxiv_id: str) -> ArxivResult:
    return ArxivResult(
        arxiv_id=arxiv_id,
        title=_clean_title(work.get("display_name")),
        authors=[
            authorship["author"]["display_name"]
            for authorship in work.get("authorships") or []
            if (authorship.get("author") or {}).get("display_name")
        ],
        abstract="",  # OpenAlex 摘要是倒排索引格式，不做重建（范围外）
        published=_published(work),
        updated="",
        categories=[],
        pdf_url=PDF_URL_TEMPLATE.format(arxiv_id=arxiv_id),
        abs_url=ABS_URL_TEMPLATE.format(arxiv_id=arxiv_id),
    )


def _published(work: dict) -> str:
    """publication_year 字符串；缺失回退 publication_date 前 4 位；再缺失空串。"""
    year = work.get("publication_year")
    if year is not None:
        return str(year)
    return (work.get("publication_date") or "")[:4]


def _clean_title(raw) -> str:
    """标题是单行语义字段：折叠换行与连续空白。"""
    return " ".join(raw.split()) if raw else ""
