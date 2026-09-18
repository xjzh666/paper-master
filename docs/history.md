# Paper Master — 项目进展史（history）

CLAUDE.md 只保留当前状态与活跃路线图；已完成条目的完整清单在本文件，需要追溯时读。
更新约定：条目从 CLAUDE.md 移入时保持原文；新完成的条目在此追加（CLAUDE.md 侧压缩为一行摘要）。

## 已完成清单（按时间）

- [x] **MinerU 版面解析** — VLM（Qwen2VL 1.2B）+ vLLM 推理，识别章节层级、公式、表格、图片、阅读顺序
- [x] **Block 级数据模型** — ContentBlock → SemanticChunk → PaperDocument，含合并算法 + 序列化
- [x] **TF-IDF 语义块检索** — 对 SemanticChunk 建索引，top-3 + 窗口上下文
- [x] **Phase 2: 向量 RAG** — BGE-M3 dense embedding 替代 TF-IDF，embedding 随 chunk 缓存到 JSON
- [x] **论文缓存** — sha256(pdf) → `~/.cache/paper-master/` JSON，含 blocks + chunks + embeddings
- [x] **批量预热** — `python3 main.py --batch papers/` 遍历目录预解析全部 PDF
- [x] **LLM 多后端支持**（Anthropic SDK + OpenAI SDK）
- [x] **模型路由**：窗口有图片/表格 → vision 模型；纯文字 → text 模型（带 `[路由: xxx]` 日志）
- [x] **对话上下文管理**（历史记录、章节查找、概览生成）
- [x] **CLI 交互循环**（/help, /overview, /sections, /quit, /exit）
- [x] **中文回答 / 英文工具调用**：LLM 回答为中文，工具调用参数用英文（论文是英文，检索匹配更好）
- [x] **检索瘦身**：chunk 阈值 480→240 tokens，`search_paper` window=1→0，返回量从 13-16K 降到 3-5K
- [x] **压缩 off-by-one 修复**：`KEEP_RECENT_ROUNDS=3` 保留最近 3 轮完整，修复"工具结果被读前已压"导致的无限检索循环
- [x] **MinerU v1/v2 格式兼容**（content_list.json 平铺格式 + content_list_v2.json 分页嵌套格式）
- [x] 配置文件：每个模型独立配 api_key、base_url、provider
- [x] **Paper Memory 结构化理解** — LLM 抽取论文的研究问题、方法、贡献等 10 个字段，独立缓存 `{sha256}-memory.json`，注入对话 system prompt
- [x] **PaperAgent 流式改造** — 把 `run()` 方法体重构为 `_run_loop(question, history, memory, on_event, stream)`，新增 `run_stream()` 事件回调入口（事件协议：`answer_chunk`/`clear`/`tool_start`/`tool_result`）；非流式 `run()` 行为不变（调用 `chat_with_tools`）
- [x] 190 个测试全覆盖（单元 + 集成，含 embedding mock + SSE 事件序列）
- [x] 中文 README + docs/architecture.md
- [x] **Zotero 连接（CLI + API）** — `zotero.py` 只读读取 Windows 侧 Zotero sqlite（`/mnt/c/Users/ASUS/Zotero`），解析条目元数据（标题/作者/年份/期刊/DOI/收藏夹）+ 定位 PDF（storage: 路径 → `storage/{attachment_key}/{filename}`）；`main.py --zotero` 搜索/收藏夹选论文进入对话；FastAPI 暴露 collections/items/search/items/{id} 四端点，前端/模型 agent 复用
- [x] **P4 Web 应用（桌面形态改为 Web 应用）** — 从 Tauri 改为 Web 应用（理由见关键设计决策 #13）。已完成：
  - [x] **papers.py 会话仓库** — Session 管理（论文→会话单例）、`open_paper` 后台线程异步 MinerU 解析（`/status` 轮询 ready）、`chat_events` 队列转发 SSE 事件
  - [x] **/api/papers/* 端点** — `open` / `{id}/status` / `{id}/overview` / `{id}/content`（markdown 图片重写为 `/api/papers/{id}/images/*`）/ `{id}/chat`（SSE 真流式）
  - [x] **前端脚手架 + 三栏布局** — React + TypeScript + Ant Design + Vite；左栏论文列表/收藏夹、中间 SSE 对话面板、右侧 markdown 阅读面板
  - [x] **API client + SSE 解析器** — `frontend/src/api/client.ts` + `sse.ts`（按 `event:` 帧解析并分发 tool_start/answer_chunk/clear/done/error）
  - [x] **生产静态托管** — `server.py` 末尾 `mount("/", StaticFiles(html=True))`，单端口 8000 同时服务 API 与前端；`paper-web` 命令一键启动
- [x] **数学渲染清洗 pipeline（论文级公式质量优化）** — 见 architecture.md「数学渲染流水线」。包含：
  - [x] **LaTeX 语义规范化（`latex_fix.py`）** — 裸标识符/密钥/字段统一 `\mathrm{}`（白名单：PK/SK/OTK/SOTK/Cert/aid/uid/name/device/IP/port…）、跨命令边界拆分的标识符合并（`S \mathrm{K}`→`\mathrm{SK}`）、函数名 `\operatorname`、`\mathbb`/`\mathcal`/`\boldsymbol` 字母间距折叠、下标内上标嵌套、集合/元组 `\dots`
  - [x] **HTML table 内公式渲染（`rehypeMathInHtml.ts`）** — 修复 remark-math 看不到原生 `<table>` 内 `$..$` 的问题，挂在 rehypeRaw 之后用 KaTeX 渲染
  - [x] **公式覆盖率校验（`math-coverage.mjs`）** — raw → remark-math → raw-HTML → KaTeX 计数 + Lost candidates；5 篇真实论文 594→594，Lost=0
  - [x] **OCR/编码异常检测与 prose 规范化（`math_quality.py`）** — `�` 检测+移除、Ḋ/Ḍ 点号重音检测 + prose-only 规范化（不改 math block）、Unicode 数学字符检测（σ/∈/≤→…）、Markdown/LaTeX 污染检测（未闭合 `$`/`\(`/`\[`、`\_` 转义、`\text{}` 内错误数学）
  - [x] 测试：231 个 Python + 17 个前端 vitest 全过
- [x] **Web 后台 Paper Memory 抽取** — `papers.open_paper` 缓存命中路径补上 `load_memory_cache`（此前只有解析路径加载，已有记忆的论文会被白白重抽）；记忆仍缺失时 `_ensure_memory_background` 后台线程抽取，不阻塞 ready，失败静默降级，`memory_jobs` 防重
- [x] **对话面板 markdown+公式渲染** — 助手消息从纯文本改为 `MarkdownMessage`（memo 化的 react-markdown），复用与阅读区一致的插件栈（公式/HTML 表格/列表）；新增 `frontend/src/markdown/plugins.ts` 共享插件配置，`plugins.test.tsx` 锁住渲染行为；流式输出按"增量 buffer + 全量重渲染最后一条"处理，未闭合 `$$`/代码块在中间态按普通文本显示、闭合后自动成型
- [x] **对话历史落盘持久化** — `papers.py` 新增 `load_chat_history` / `save_chat_history`（`~/.cache/paper-master/{paper_id}-history.json`），`open_paper` 创建 Session 时加载、`chat_events` 回答完成后保存；损坏文件静默加载为空，出错不落盘（保留最近成功状态）。重启后端对话可恢复
- [x] **对话历史前端恢复 + 清空** — `GET /api/papers/{id}/history`（内存 session 优先，磁盘兜底）+ `DELETE` 清空；ChatPanel 打开论文自动拉取历史恢复展示（历史与本轮新消息间插「以上是历史对话」分割线），标题栏「清空」按钮联动清磁盘 history 与 session 观察；顺带修复换论文旧对话残留
- [x] **get_section 平层级修复 + 章节目录注入** — MinerU 把父子节标题全标成同一层级时，`find_section` 用编号深度（6 < 6.1 < 6.1.1）算有效层级，父章节正确收编子节正文；heading-only 结果兜底顺延后续块（2000 字上限）；system prompt 注入 `[论文章节目录]` 并要求 reference 从目录选取，杜绝瞎猜章节名
- [x] **Session Observation 跨提问 + 中间产物落盘** — observations 所有权上移到 `ConversationContext`（每问新建 agent 也跨提问累积），run 结束 finally flush 并打 question 标记；落盘 `{sha}-observations.json`（全量不去重），注入最近 20 条带「未经复核」标注；`describe_image` 结果按图片相对路径缓存 `{sha}-images.json`（命中不调 vision API）；记录标准放宽为"有独立价值即使与当次问题无关也记 + sources 必填"；清空对话联动清观察（图像描述不清）；CLI 端同样恢复/保存
- [x] **P6.1 外部论文搜索** — 摆脱 Zotero 本地库限制，按查询获取外部论文并进入既有解析/阅读/对话管线（查询 → 结果列表 → 下载原文 PDF → 打开）。选型见决策 #20（arXiv 起步、Semantic Scholar 排除），范围扩展见决策 #21（429 退避重试 + OpenAlex 降级兜底）。提交范围 e578117..9103415 + b519850（docs）。包含：
  - [x] **`arxiv_search.py`** — arXiv 搜索客户端（Atom XML 解析，零第三方依赖）；模块级 3s 限速闸（search 与 download_pdf 共享）；HTTP 429 等 15s 重试一次，仍失败抛 `ArxivRateLimitError`（友好文案）；`download_pdf` 原子写（先落 `.part` 再 `os.replace`，中途失败清理不留截断文件）；`search_with_fallback` 编排 arXiv 检索失败时降级 OpenAlex（空结果不触发兜底）
  - [x] **`openalex_search.py`** — OpenAlex 薄客户端（降级兜底，mailto 礼貌参数）；从 doi（`10.48550/arxiv.*`）或 `best_oa_location.pdf_url`（`arxiv.org/pdf/*`）提取 arxiv_id，非 arXiv 记录直接丢弃；按 arxiv_id 去重保序；下载不兜底（仍走 arXiv CDN）
  - [x] **`/api/arxiv/*` 端点** — `GET /api/arxiv/search`（响应带 `source: arxiv|openalex`，双源皆败 502）；`POST /api/arxiv/open`（校验 arxiv_id，下载至 `~/.local/share/paper-master/downloads/` 后复用 `papers.open_paper`；错误映射 400/502/500）
  - [x] **`search_external_papers` agent 工具** — 编号列表（title/year/authors/arxiv_id）供回答引用；OpenAlex 兜底时首行标注「arXiv 暂不可用，以下为 OpenAlex 兜底结果」
  - [x] **前端 arXiv 搜索页签** — `PaperListSidebar` Tabs 新增「arXiv 搜索」：搜索结果列表 + 点击打开（走 `/api/arxiv/open` 进既有打开流程）；source 为 openalex 时结果区显示「OpenAlex 兜底」Tag
  - [x] **验证** — pytest 348 / vitest 51 全过；浏览器全链验证通过（搜索→打开→下载→MinerU 解析→三栏阅读→对话、Zotero 无回归）；期间遭遇 arXiv 全局 429，OpenAlex 兜底真实生效
  - 遗留：台账延期 Minor 与两个优化项（兜底提示增强：候选数/存活数；兜底超采样：per_page 放大再过滤）
- [x] **P6.1 S2 主源扩展** — S2 key 获批后搜索主源切换为 Semantic Scholar（决策 #22）：结果自带摘要/tldr/引用数，agent 工具具备「值不值得下载精读」的 triage 能力；检索链 S2 → arXiv → OpenAlex（source 三值 `s2|arxiv|openalex`，notice 三态区分「未配置」与「失败」）；下载链路不变（arxiv_id → arXiv CDN）。#20 中"S2 排除"废止。提交范围 33f4042..27d081e + 本提交（config 占位 + 文档同步 + agent 工具 description 措辞）。包含：
  - [x] **`s2_search.py`** — Semantic Scholar 客户端（主源）：GET `graph/v1/paper/search` + `x-api-key`，只留 `externalIds.ArXiv` 非空的记录；1rps 限速闸；429 等 5s 重试一次；401/403 坏 key 抛 `S2Error` + warning（可诊断）；`load_api_key()` 读 config.yaml `external_search.semantic_scholar.api_key`（缺失/为空即禁用 S2 源；config.example.yaml 留空占位，真实 key 不入 git）
  - [x] **`ArxivResult` 扩展 + 编排链重排（`arxiv_search.py`）** — 新增带默认值字段 `tldr`/`citation_count`（arXiv/OpenAlex 腿不填）；`search_with_fallback` 返回三元组 `(results, source, notice)`，S2 未配置静默走 arXiv、配置但失败降级并 notice 标注；空结果不触发兜底；conftest autouse fixture 默认禁用 S2（配 key 机器上测试不真触网）
  - [x] **OpenAlex 末位腿改进（`openalex_search.py`）** — filter 加 arXiv 主位置（source `S4306400194`），提取优先级 doi → `best_oa_location.pdf_url` → `primary_location.landing_page_url`，可提取率实测 1/10→10/10
  - [x] **server + 前端** — `/api/arxiv/search` 透传 source 三值（notice 不进前端响应）；前端 source=='s2' 蓝 Tag「Semantic Scholar」、作者行追加「被引 N」；client.ts source 类型三值 + `tldr?`/`citation_count?`
  - [x] **agent 工具输出增强（`agent.py`）** — 每条含「被引 N」（citation_count 非 None 时）与摘要行（tldr 优先，截断 200 字），首行 notice；description 更新为多源现实（S2 主源、arXiv/OpenAlex 兜底）
  - [x] **验证** — pytest 392 / vitest 55 全过（含 agent.py description 措辞更新后复跑 tests/test_agent.py 79 passed）；实测依据：搜索 10/10 带 arXiv id/摘要/tldr；浏览器真实 key 全链验证为独立后续任务（spec 验收第 9 条）

## 阶段详情（已完成阶段）

### P0：RAG 工具化 ✅

- [x] `search_paper(query)` — 单论文语义检索 + 图/表 aliases 精确匹配，BGE-M3 混合检索，window=1
- [x] `get_section(reference)` — 章节精确引用（含 HTML 标签剥离匹配），3000 字截断
- [x] `describe_image(resource_id)` — VLM 图片内容解析，图片懒加载
- [x] `record_observation(summary, facts, entities, sources)` — 结构化记录本轮检索发现，为压缩和长期记忆提供摘要
- [x] PaperAgent 完整 Agent 循环（LLM 原生 function calling，最多 7 轮）
- [x] Resource/ToolResult 结构化工具返回（text + resources，资源引用不传 bytes）
- [x] MinerU 输出持久化到 `~/.cache/paper-master/mineru-output/`
- [x] System prompt 含停止准则（拿到足够信息就回答、图片不可用不再重试）
- [x] Agent 打印工具调用日志（`[agent] tool_name(args) → N chars, M resources`）

### P1：Paper Memory（论文结构化理解）✅

- [x] Paper Memory 数据结构（Research Problem, Motivation, Method, Experiment, Limitation, Contribution...）
- [x] LLM 驱动的论文结构化抽取（一次解析，存入缓存 `{sha256}-memory.json`）
- [x] 对话中注入 system prompt，RAG 检索 + Memory 全局理解互补

### P2：Tool Result 压缩 ✅

- [x] `_smart_truncate(text, max_chars=300)` — 句子边界智能截断，避免断句
- [x] `_compact_messages(messages, current_round)` — 每轮发送前压缩，保留最近 `KEEP_RECENT_ROUNDS=3` 轮完整，更早的替换为 observation 摘要
- [x] `record_observation` 工具 — LLM 同一轮内顺手记录，不增加额外 API 调用
- [x] 降级策略：LLM 不调 record_observation 时自动回退截断
- [x] Observation 注入 system prompt — 累积的观察作为"已知信息"注入
- [x] 每次 `run()` 重置 per-run `_tool_round_map` 和 `_observations`（压缩匹配只限本轮）；session 观察存 `ctx.observations`，跨提问累积并落盘
- [x] `round_num` 字段解决 observation-to-round 的索引映射问题
- [x] **off-by-one 修复**：压缩阈值 `round_num < current_round - KEEP_RECENT_ROUNDS`，保证工具结果第一次被模型读到前完整保留（此前早压一轮导致模型永远读不到完整结果，陷入无限检索）
- [x] **检索瘦身**：chunk 阈值 480→240 tokens（约 960 字），`search_paper` window=1→0，返回量从 13-16K 降到 3-5K
- [x] **工具调用语言**：工具参数（查询、章节引用、观察记录）一律英文（论文是英文），仅最终回答中文；工具描述改写为英文

### P3：引用溯源 ✅

回答标注来源，让用户知道每段信息来自论文的哪一部分。已实现形态：回答内嵌引用链接 + 阅读区滚动高亮。

- [x] system prompt 引导 LLM 在 record_observation 和最终回答中引用来源
- [x] 最终回答中标注来源 chunk / page_idx / 章节
- [x] 引用链接 + 阅读区滚动高亮 — 回答中的 `[§x.x p.N](cite:chunk_N)` 链接由 ChatPanel 拦截点击，App 按 chunks-index 让 ReadingPanel 滚动高亮（设计见关键设计决策 #18）

### P4：Web 应用 MVP ✅（技术选型与遗留项见 CLAUDE.md）

**规划任务（Web 应用 MVP）：**
- [x] 摸清 Zotero 数据库 schema
- [x] FastAPI 后端：Zotero 条目列表 API + 打开论文
- [x] `papers.py` 会话仓库 + 异步解析 + SSE 对话
- [x] React 前端：论文列表 + 收藏夹树 + 阅读区（markdown 渲染）+ 对话区
- [x] 生产静态托管（单端口）+ `paper-web` 命令
