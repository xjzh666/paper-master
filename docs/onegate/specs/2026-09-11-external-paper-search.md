# P6.1 外部论文搜索（arXiv 单源）— 设计

日期：2026-09-11
状态：草案（选型与范围已批准，实现未开始）
决策依据：决策 #19（P6 方向）、#20（论文源选型）

## 目标

用户在 Web 应用输入查询 → arXiv 搜索 → 结果列表 → 选择论文 → 下载 PDF → 进入现有解析/阅读/对话流程；Agent 对话中也能通过工具搜索外部论文。

成功标准：
1. `GET /api/arxiv/search?q=...` 返回结构化结果列表
2. `POST /api/arxiv/open` 下载 PDF 并走现有 `open_paper` 流程，解析完成后可对话
3. Agent 调用 `search_external_papers` 工具能返回搜索结果
4. pytest 全绿；不新增第三方依赖

## 已核实的现状（2026-09-11 探针 + 代码）

- 本机直连 arXiv API 正常：`https://export.arxiv.org/api/query` 返回 Atom XML，条目内 `<link title="pdf" href="https://arxiv.org/pdf/{id}">`；PDF 链接 HEAD 实测 200
- 现有打开流程契约：`POST /api/papers/open`（zotero_item_id）→ `lib.resolve_pdf(item)` → `papers.open_paper(str(path))`（papers.py:140）→ 返回 `paper_id` = PDF 内容 sha256（papers.py:47）；status/overview/content/chat 全部以 paper_id 为键
- 内容级 sha256 缓存天然去重：同一 PDF 重复打开复用缓存，不重解析
- requirements.txt 无 HTTP 客户端显式依赖（openai SDK 传递依赖 httpx）；标准库 `urllib.request` 足够覆盖本期的 GET + 下载
- 前端三栏 App，论文列表现来源于 Zotero collections/items

## 架构

数据流：查询 → `arxiv_search.search()` → 结果列表（前端展示 / Agent 工具返回）→ 选中 → `download_pdf()` 落盘 → `papers.open_paper(path)` → 现有异步解析 → 三栏阅读 + 对话（SSE / 引用溯源零改动）。

### 新模块 `paper_reader/arxiv_search.py`

- `ArxivResult` dataclass：`arxiv_id / title / authors / abstract / published / updated / categories / pdf_url / abs_url`
- `search(query, max_results=10) -> list[ArxivResult]`：urllib GET + `xml.etree.ElementTree` 解析 Atom；模块级限速（上次请求时间戳，间隔不足 3s 则补足等待）
- `download_pdf(arxiv_id, dest_dir) -> Path`：流式下载到 `{dest_dir}/{arxiv_id 消毒}.pdf`（旧式 id 含 `/` 替换为 `_`）；文件已存在则跳过下载直接返回路径
- 下载目录：`~/.local/share/paper-master/downloads/`（下载的 PDF 是打开流程的输入、用户资产，落盘保留；区别于 `~/.cache` 的可重建产物，符合决策 #16）

### server.py 新端点（与 `/api/zotero/*` 同层注册）

- `GET /api/arxiv/search?q=...&max_results=10` → `{"results": [...]}`，空结果返回空数组（非错误）
- `POST /api/arxiv/open` body `{"arxiv_id": "..."}` → 本地 downloads 无则下载（同步，数秒级）→ `papers.open_paper(path)` → 响应与 `/api/papers/open` 同构（paper_id + 初始 status），后续轮询 `/api/papers/{paper_id}/status` 复用现有协议

### Agent 工具

- `search_external_papers(query, max_results=10)`：调 `arxiv_search.search`，返回格式化文本列表（编号 + 标题 + 作者 + 年份 + arxiv_id），并在结果尾部提示"可用 arxiv_id 让用户打开对应论文"；与库内 `search_paper`（当前论文内容检索）严格区分命名

### 前端

- 侧栏列表区新增搜索入口（输入框 + 搜索按钮）→ `GET /api/arxiv/search` → 结果列表（标题/作者/年份/摘要截断/arxiv_id）→ 点击某条 → `POST /api/arxiv/open` → 复用现有 paper_id 打开后的全部流程

## 全局约束

- 限速：arXiv API 调用间隔 ≥3 秒（官方礼貌准则），模块级串行
- 单源：本期只接 arXiv；OpenAlex / Semantic Scholar 不引入（决策 #20）；不做多源聚合与排序调优
- 零新依赖：HTTP 用标准库 `urllib.request`，XML 用 `xml.etree.ElementTree`
- 命名：HTTP 命名空间 `/api/arxiv/*`（单源期诚实命名，未来多源时再做抽象层）；工具名 `search_external_papers`
- 测试不触网：全部 mock（`urllib.request.urlopen` 打桩），Atom 解析用录制的响应片段做 fixture
- 错误路径：无结果 → 空列表；网络/下载失败 → HTTP 502 带可读 detail；非法 arxiv_id → 400

## 验收标准

1. `arxiv_search.search("attention is all you need", 5)` 返回列表，含 `1706.03762`（标题含 "Attention Is All You Need"，`pdf_url` 非空）
2. `GET /api/arxiv/search?q=rag` → 200，`results` 数组元素含全部 ArxivResult 字段
3. `POST /api/arxiv/open {"arxiv_id": "1706.03762"}` → PDF 落在 downloads 目录 → 返回 paper_id；轮询 status 至 done 后 overview/content 可用
4. 同一 arxiv_id 二次 open：不发起网络下载（本地已存在），返回相同 paper_id
5. Agent 对话"帮我搜一下 RAG 综述论文" → 触发 `search_external_papers`，回答含结果列表
6. 前端 `npm run build` 成功；浏览器走通 查询→列表→打开→解析→对话 全链
7. `python3 -m pytest tests/` 全绿（新增：Atom 解析、限速补足、两端点、工具格式化）

## 不做清单

- OpenAlex / Semantic Scholar 接入（决策 #20：预留不实现）
- 引用图谱、相关性排序优化、查询改写
- 搜索历史、结果分页 UI（`max_results` 参数即可）
- 下载 PDF 的库管理界面（目录扁平放置，按 arxiv_id 命名）

## 实施拆解（建议顺序）

1. `arxiv_search.py` + 单测（解析 / 限速 / 下载 mock）
2. `server.py` 两个端点 + 端点测试
3. `agent.py` 工具 + 测试
4. 前端搜索入口 + 构建
5. 浏览器全链手动验证 + 文档同步（CLAUDE.md P6.1 状态、history.md、测试数）
6. 429 退避重试 + 友好文案（arxiv_search.py + server.py + 测试）【2026-09-14 追加】
7. OpenAlex 降级兜底（openalex_search.py + search_with_fallback + server source + 工具标注 + 前端 Tag + 测试）【2026-09-14 追加】

## 范围扩展（2026-09-14 用户批准，决策 #21）

背景：浏览器验收时遭遇 arXiv API 全局性 429"Rate exceeded"（跨校园网/热点/代理三个出口网络均复现，同刻 OpenAlex 200 正常）——单源可用性风险从理论变为已发生。

### 扩展 A：429 退避重试与友好文案

- `_open` 层：捕获 HTTPError 且 code==429 → `time.sleep(RETRY_WAIT_SECONDS=15)` 后重试同一 URL 一次；再次 429 抛 `ArxivRateLimitError`（`str` 为"arXiv 限流中，请稍后 1-2 分钟再试"）；非 429 异常行为不变。`search` 与 `download_pdf` 经共用 `_open` 自动获得重试
- server 两端点捕获 `ArxivRateLimitError` → 502，detail 用异常消息原文（前端已透传 detail，前端零改动）
- 测试：429→sleep(15)→成功（打桩 time 断言 sleeps）；429×2→`ArxivRateLimitError`；非 429 HTTPError 不 sleep 直抛；端点 502 文案精确断言

### 扩展 D：OpenAlex 降级兜底

- 新模块 `paper_reader/openalex_search.py`：`search(query, max_results=10) -> list[ArxivResult]`；`GET https://api.openalex.org/works?search={q}&per_page={n}&mailto=paper-master@example.com`（`select` 限定字段）；从 doi（`10.48550/arxiv.{id}`）或 `best_oa_location.pdf_url`（`arxiv.org/pdf/{id}`）提取 arxiv_id（去版本号），提取失败的记录丢弃；按 arxiv_id 去重；`abstract` 留空（兜底降级不取摘要）；`published` 取 publication_year
- 编排 `arxiv_search.search_with_fallback(query, max_results=10) -> tuple[list[ArxivResult], str]`：先走 arXiv；失败（ArxivRateLimitError/URLError/OSError/ET.ParseError）→ OpenAlex 兜底，返回 `(结果, "arxiv" | "openalex")`；OpenAlex 再失败异常透传
- **空结果不触发兜底**（空是合法答案）
- server：`GET /api/arxiv/search` 改用 `search_with_fallback`，响应增加 `"source"` 字段；前端缺失 source 时默认按 arxiv 处理（向后兼容）
- agent 工具：`search_external_papers` 改用 `search_with_fallback`；source=="openalex" 时结果首行加 `[arXiv 暂不可用，以下为 OpenAlex 兜底结果]`
- 下载不兜底：open 流程仍按 arxiv_id 走 arXiv CDN（与 export API 不同服务，通常独立可用）；CDN 也失败 → 既有 502 错误路径
- 不做：OpenAlex 记录的摘要重建、非 arXiv 记录（纯期刊 OA）的打开支持——留后续迭代

### 不做清单（更新）

- ~~OpenAlex / Semantic Scholar 接入（决策 #20：预留不实现）~~ → OpenAlex 以降级兜底形式接入（2026-09-14，决策 #21）；Semantic Scholar 仍不接
