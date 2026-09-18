# Paper Master — 架构与设计

> 本文件是架构详情的唯一真源。文档分工：当前状态与活跃路线图见 `CLAUDE.md`（路线图唯一真源）；设计决策全文见 `docs/decisions.md`；已完成条目完整清单见 `docs/history.md`。

## 工作原理

**论文预处理（一次性）：**

```
PDF → MinerU CLI (VLM 版面分析) → content_list_v2.json + images/ + .md
  → MinerUParser → ContentBlock[] → merge_blocks() → SemanticChunk[]
  → PaperDocument → sha256 缓存到 ~/.cache/paper-master/
  → BGE-M3 编码 → 1024-d dense vectors + sparse lexical weights（内嵌 chunk）
  → Paper Memory 抽取 → 读 .md → LLM 结构化 JSON → {sha256}-memory.json
```

**对话时（Agent 循环）：**

```
用户提问
  → PaperAgent.run()
  → system prompt 注入：Paper Memory + [论文章节目录] + session 观察（最近 20 条，带来源提问标记）
  → 每轮发送前 _compact_messages() 压缩往轮 tool result
  → LLM 决策调用工具（最多 7 轮）:
      ├── search_paper(query)     — BGE-M3 混合检索 + aliases 精确匹配
      ├── get_section(reference)  — 章节精确引用（编号深度有效层级 + 平层级兜底），3000 字截断
      ├── describe_image(rid)     — VLM 图片内容解析（描述按图片路径缓存 {sha}-images.json，命中不调 API）
      ├── record_observation(...) — 结构化记录发现（summary + facts + entities + sources；与当前问题无关但有价值的也记）
      └── search_external_papers(query, max_results) — 外部论文搜索（S2 主源 → arXiv → OpenAlex 降级链，结果带 tldr/摘要/被引数）
  → 往轮 tool result 替换为 observation 摘要（无 observation 则智能截断降级）
  → run 结束 flush 本轮观察到 ctx.observations（打 question 标记），落盘 {sha}-observations.json
  → 中文回答
```

遗留的简单路径 `LLMRouter.answer()` 仍然可用，但主要路径是 PaperAgent。

**Web 版数据流（浏览器 + 异步解析 + SSE 对话）：**

```
浏览器 (localhost:8000)
  → GET /api/zotero/*              — 论文列表 / 收藏夹 / 搜索（只读）
  → POST /api/papers/open          — 选论文，返回 paper_id + status（ready | parsing）
       ├─ 有缓存 → 直接 ready；无缓存 → 后台线程异步 MinerU 解析（不阻塞）
       └─ 前端轮询 /api/papers/{id}/status 直到 ready
  → GET /api/papers/{id}/overview|content|images/*  — 摘要 / markdown 阅读区 / 图片
  → GET /api/papers/{id}/chunks-index  — chunk 定位索引（id/page/section/snippets，snippets 已剥 HTML 与公式定界符，公式内容以 LaTeX 源保留参与匹配）
  → GET|DELETE /api/papers/{id}/history  — 对话历史读取（前端打开论文自动恢复 + 分割线）/ 清空（联动清 session 观察）
  → POST /api/papers/{id}/chat     — SSE 对话（StreamingResponse）
       → papers.chat_events() 在 worker 线程驱动 PaperAgent.run_stream()
       → 队列转发 on_event → SSE 帧：event: <etype>\ndata: <json>\n\n
       → 回答中的 [§x.x p.N](cite:chunk_N) 链接由 ChatPanel 拦截点击，App 按 chunks-index 让 ReadingPanel 滚动高亮
```

**SSE 事件协议**（`papers.chat_events` yield `(etype, payload)`，前端 `sse.ts` 解析）：

| event | payload | 说明 |
|-------|---------|------|
| `tool_start` | `{name, arguments}` | Agent 开始调用工具 |
| `tool_result` | `{name, chars, resources}` | 工具返回摘要（正文在服务端已压缩） |
| `answer_chunk` | `{delta}` | 流式答案片段（增量追加） |
| `clear` | `{}` | 清空面板（新一轮回答开始前） |
| `done` | `{}` | 本轮结束 |
| `error` | `{message}` | 出错（如 paper not parsed） |

> Web 端 Paper Memory：`open_paper` 两条路径（缓存命中 / 首次解析）都会先 `load_memory_cache` 加载 `{sha256}-memory.json`；仍缺失时由 `_ensure_memory_background` 起后台线程调 `extract_memory` 抽取（不阻塞 ready 状态），失败静默降级为纯 RAG。`memory_jobs` 集合防同论文重复抽取。
>
> Web 端对话历史持久化：`load_chat_history` / `save_chat_history` 读写 `~/.cache/paper-master/{paper_id}-history.json`（`paper_id` 即 PDF sha256）。`open_paper` 创建 Session 时经 `_restore_session_state` 与 session 观察（`{paper_id}-observations.json`）一并加载，`chat_events` 回答完成后两者一起落盘（出错不保存，磁盘保留最近一次成功状态）；损坏文件静默加载为空。`GET /api/papers/{id}/history`（内存 session 优先、磁盘兜底）供前端打开论文时自动恢复，`DELETE` 清空并联动删 observations（图像描述 `{paper_id}-images.json` 是论文级产物，不清）。重启 uvicorn 后对话与检索发现均可恢复。

## 为什么用 MinerU？

相比 PyMuPDF 直接读 PDF 内嵌文本，MinerU 用 VLM 模型「看」整个页面：

| | PyMuPDF | MinerU |
|------|---------|--------|
| 双栏布局 | 文字混杂 | 正确识别 |
| 公式 | 乱码 | LaTeX |
| 表格 | 截图 | 结构化 Markdown |
| 阅读顺序 | 依赖 PDF 标签 | VLM 重建 |
| 图片 caption | 需手动关联 | 自动挂钩 |
| 速度 | 秒级 | 1-2 分钟（GPU 推理） |

## 数据模型

**论文层（blocks.py）：**

```
ContentBlock          — 版面元素，1:1 映射 MinerU 输出
  type: text | image | table | formula
  level: 0=正文, 1=一级标题, 2=二级标题...
  page_idx, bbox, image_path, image_bytes

SemanticChunk         — 语义单元，RAG 检索最小粒度（合并 ~512 tokens，64 tokens 重叠）
  chunk_id, text
  blocks: list[ContentBlock]
  section_path: list[str]        — 层级标题路径
  images: list[ContentBlock]     — 挂载的图片/表格
  figure_labels: list[str]       — 原始标签 ["Fig. 1", "TABLE III"]
  aliases: list[str]             — 标准化别名，含中文 ["Fig. 1", "Figure 1", "图1", ...]
  embedding: list[float] | None  — 1024-d BGE-M3 稠密向量
  lexical_weights: dict | None   — BGE-M3 稀疏词权重
  合并规则: 标题断开 | ~512 tokens 截断 | 64 tokens 重叠
  图片/表格 caption 注入标准化标签后写入 text

PaperMemory           — 结构化论文理解，LLM 一次性抽取 10 字段
  research_problem, motivation, method, method_why, experiments,
  key_results, contributions, limitations, takeaways, keywords
  注入对话 system prompt，与 RAG 检索互补

PaperDocument
  blocks: list[ContentBlock]     chunks: list[SemanticChunk]
  memory: PaperMemory | None
```

**Agent 层（agent.py）：**

```
Observation           — 每轮检索后的结构化观察（L2 记忆，session 级落盘）
  summary, round_num, facts, entities, sources, question（来源提问）
  per-run 列表供压缩；run 结束 flush 到 ctx.observations，落盘 {sha}-observations.json

Resource              — 工具返回的图片/表格引用，懒加载
ToolResult            — 工具返回 {text, resources}
Tool                  — 工具定义 {name, description, parameters (JSON Schema), callable}
LLMToolResponse       — LLM 返回解析 {text, tool_calls}
```

## 检索策略

**BGE-M3 混合检索**（dense + sparse）：

1. **Dense 检索**（语义）— 1024 维向量 cosine similarity，跨语言语义匹配
2. **Sparse 检索**（词法）— BGE-M3 学习的 token 权重，类似升级版 BM25，精确术语匹配
3. **标准化标签 + aliases** — 罗马数字 → 阿拉伯数字转换（TABLE I → Table 3），注入中文别名（图1、表2）；`search_paper` 里 aliases 精确匹配优先于向量检索
4. **章节查找**（辅助）— 用户明确说 "section 2.1" → `get_section` 直接定位章节范围

检索瘦身：chunk 阈值 240 tokens，`search_paper` window=0，单次返回 3-5K 字符。

## Agent 与记忆

- **工具调用**：LLM 原生 function calling（OpenAI 兼容 tools 协议），最多 7 轮；System prompt 含停止准则
- **三层记忆**：L1 对话（最新轮完整，往轮压缩）、L2 Observation（结构化观察，session 级累积 + 落盘，注入最近 20 条带「未经复核」标注）、L3 Evidence（`Observation.sources` 来源追溯，P3 引用溯源已完善）
- **压缩**：每轮发送前压缩往轮 tool result，保留最近 3 轮完整（保证模型能回读证据）；无 observation 时降级为句子边界智能截断

## 外部论文搜索（P6.1）

摆脱 Zotero 本地库限制，按查询获取外部论文并复用既有管线（选型见决策 #20，范围扩展见 #21，主源切换见 #22）。检索链：**Semantic Scholar（主源，配置了 key 才参与）→ arXiv → OpenAlex（降级兜底）**。**边界：下载只走 arXiv CDN**（下载流程不兜底，#21 扩展 D——arXiv PDF 域名与 export API 是不同服务，通常独立可用；#22 维持不变）。

**模块职责（零第三方依赖：urllib + 标准库 XML/JSON）：**
- `arxiv_search.py` — arXiv 搜索客户端 + 三源编排。Atom XML 解析（`search`）；模块级限速闸：任意两次 arXiv 网络调用间隔 ≥3s（search 与 download_pdf 共享，串行锁实现）；HTTP 429 等 15s 重试一次，仍 429 抛 `ArxivRateLimitError`（str 为友好文案）；`download_pdf` 原子写（先落 `.part` 全部写成功后 `os.replace`，中途失败清理且不留截断文件——防 exists 早退永久命中坏缓存；文件已存在跳过网络请求）；`search_with_fallback` 编排 S2（有 key）→ arXiv → OpenAlex 降级链，返回三元组 `(results, source, notice)`——source ∈ {"s2","arxiv","openalex"}，notice 区分「未配置」（静默走下家，空串）与「失败」（降级标注文案）；空结果不算失败、不兜底；OpenAlex 也失败时异常透传给调用方
- `s2_search.py` — Semantic Scholar 客户端（主源）。GET `graph/v1/paper/search`（头 `x-api-key`）；只保留 `externalIds.ArXiv` 非空的记录，映射结果自带 abstract/tldr/引用数（triage 字段，arXiv/OpenAlex 腿不填）；限速闸 1 req/s（模块级时间戳 + 锁）；HTTP 429 等 5s 重试一次，仍 429 抛 `S2RateLimitError`；401/403（坏 key）抛 `S2Error` 并 logging.warning；`load_api_key()` 读 config.yaml `external_search.semantic_scholar.api_key`，缺失/为空即禁用 S2 源（编排静默跳过）
- `openalex_search.py` — OpenAlex 薄客户端（降级兜底）。works API + mailto 礼貌参数；filter 把主位置限定为 arXiv（source `S4306400194`），纯期刊记录不进响应；从 doi（`10.48550/arxiv.*`）、`best_oa_location.pdf_url`（`arxiv.org/pdf/*`）或 `primary_location.landing_page_url`（`arxiv.org/abs/*`）提取 arxiv_id，提取不出的非 arXiv 记录直接丢弃；按 arxiv_id 去重保序；不重建摘要（OpenAlex 倒排索引格式，范围外）

**数据流：**

```
查询（前端「arXiv 搜索」页签 / agent 工具 search_external_papers）
  → search_with_fallback()   — 三源链 S2（有 key）→ arXiv Atom → OpenAlex；失败降级下家，notice 标注降级来源
  → (结果, source, notice)   — 前端结果列表 / 工具编号列表（S2 腿带被引数/摘要），arxiv_id 对用户可见
  → POST /api/arxiv/open     — {arxiv_id}
  → download_pdf()           — arXiv CDN 下载至 ~/.local/share/paper-master/downloads/（原子写，已存在跳过）
  → papers.open_paper(path)  — 进入既有管线（缓存/异步 MinerU 解析/SSE 对话），与 Zotero 打开同一入口
```

**端点契约（server.py）：**

| 端点 | 契约 |
|------|------|
| `GET /api/arxiv/search?q=&max_results=` | 200 `{results: ArxivResult[], source: "s2" \| "arxiv" \| "openalex"}`（source 标识实际来源，前端缺失视为 arxiv）；三源皆败 502「外部检索失败: …」；notice 不进前端响应，仅供 agent 工具与日志 |
| `POST /api/arxiv/open` `{arxiv_id}` | body 缺失/格式非法 400（正则校验，兼防路径穿越）；下载限流或失败 502（限流时 detail 为友好文案）；`open_paper` 失败 500；成功返回与 `POST /api/papers/open` 同构的 paper_id + status |

agent 工具 `search_external_papers(query, max_results)` 走同一编排：结果首行为 notice（非空时——「[Semantic Scholar 不可用，以下为 arXiv 检索结果]」或「[arXiv 暂不可用，以下为 OpenAlex 兜底结果]」），每条含被引数（citation_count 非 None 时「被引 N」）与摘要行（tldr 优先，否则 abstract，截断 200 字），末行提示把 arxiv_id 提供给用户在 Web 端打开。

## 子系统注意事项

### BGE-M3

- 模型：`BAAI/bge-m3`，约 2.27 GB，路径指向 `~/.cache/modelscope/models/BAAI--bge-m3/`（modelscope 下载）
- 如果 modelscope 路径不存在，自动回退到 HuggingFace `'BAAI/bge-m3'`
- 进程级单例，首次加载约 2-3 秒（GPU fp16），之后常驻显存
- 查询编码 ~10ms，numpy cosine sim ~微秒级，检索开销可忽略
- 测试用 bigram-overlap fake model 替代，不需要真实模型

### Paper Memory

- 输入源优先 MinerU 生成的 `.md` 文件（无重叠），回退到 blocks 按序取 text
- 每次打开论文自动尝试加载缓存 `{sha256}-memory.json`，无缓存则调 LLM 抽取
- 抽取失败不阻塞主流程，`paper.memory` 保持 `None`，对话降级为纯 RAG
- 字段含"未提及"的不注入 system prompt（减少噪音）

### MinerU

- MinerU 需要 CUDA GPU + CUDA Toolkit。当前环境已配好（驱动 610.53 + CUDA 12.8）
- 首次解析一篇论文约 1-2 分钟（VLM 模型加载 + 推理），之后从缓存秒加载
- MinerU 自动下载模型到 `~/.cache/modelscope/models/`（MinerU2.5-Pro-2605-1.2B，约 2.15 GiB）
- `content_list_v2.json` 是分页嵌套结构，v1 是平铺列表。`_normalize_items` 方法统一处理

## 数学渲染流水线

数学渲染是一个多阶段流水线：`PDF → Markdown → 公式/OCR/HTML 清洗 → LaTeX 语义规范化 → Math coverage 校验 → KaTeX 渲染`。

**后端（Python）—— serve-time 清洗：**
- `papers.get_content` 调 `math_quality.fix_paper_markdown(md)` = `fix_markdown_math()` + `normalize_ocr_prose()`，再重写图片 URL。
- `latex_fix.fix_latex_math` 语义规范化（按顺序）：① HTML `<sub>/<sup>`→`_{}/^{}` ② `\mathrm{...}` 等 font 命令字母间距折叠（含 `\mathbb`/`\mathcal`/`\boldsymbol`）③ 跨命令边界拆分的标识符合并（`S \mathrm{K}`→`\mathrm{SK}`）④ 下标内上标嵌套修复 ⑤ `...`/`\bullet\bullet\bullet`→`\dots` ⑥ 函数名→`\operatorname` ⑦ 裸标识符（`PK`/`SK`/`OTK`/`aid`/`uid`/`name`…白名单）→`\mathrm{}` ⑧ 括号/上下标空白折叠。
- **显示公式结尾的 `$$` 必须独占一行**：`_clean_spacing` 只折叠空格/制表符（`[ \t]*`），**绝不能折叠换行**——否则 remark-math 不认行尾 `$$` 为闭合符（回归测试 `test_display_math_keeps_newline_before_closing_delim`）。
- **改 latex_fix.py / math_quality.py 后重启后端即可**（serve-time 应用，无需前端重建）。

**`math_quality.py`（公式覆盖率 + OCR/编码/污染检测）：**
- `count_math_candidates`（raw `$...$`/`$$...$$` 计数）、`detect_encoding_errors`（`�`）、`detect_ocr_diacritics`（Ḋ/Ḍ 类点号）、`detect_unicode_math`（prose 内 σ/∈/≤→…）、`detect_pollution`（未闭合 `$`/`\(`/`\[`、`\_` 转义、`\text{}` 内错误数学）。
- `normalize_ocr_prose`：只清洗 **prose**（标题/正文/caption）的点号重音 + 移除 `�`，**不改 math block**（避免破坏公式）。
- CLI：`python3 -m paper_reader.math_quality <file.md> [--fix out.md] [--json]`。

**前端（TS）—— HTML table 内公式：**
- remark-math 只处理 markdown AST，看不到原生 `<table>` 里的 `$...$`；`rehypeRaw` 在 `rehypeKatex` 之后才展开 HTML。`frontend/src/markdown/rehypeMathInHtml.ts` 插件挂在 **rehypeRaw 之后**，把 table 单元格文本里的 `$...$`/`$$...$$` 用 KaTeX 渲染（分隔符正则与 `_MATH_SPLIT` 保持一致）。改前端后需 `npm run build`。

**KaTeX 版本必须全局对齐（2026-08-31 修复的公式重叠 bug）：**
- 症状：display 公式（`$$`）正常，**inline 高公式**（如 `$\begin{array}...\end{array}$`）与上下行文字垂直重叠。
- 根因：`main.tsx` 的 CSS import 解析到顶层 katex，而 `rehype-katex@7`（最新版，锁定 `katex@^0.16`）用嵌套 katex 渲染。顶层装 0.18.4 时 CSS 类名（`katex-strut`/`katex-base`/`katex-sizing`）与 DOM 类名（`strut`/`base`/`sizing`）不匹配，关键规则 `.katex .strut{display:inline-block}` 缺失 → strut 沦为普通 inline span（height 无效）→ 行盒不再为高公式保留高度 → 溢出重叠。
- 修复：顶层 `katex` 降到 `^0.16.47` 与渲染器 dedupe 成同一份（CSS / rehype-katex / rehypeMathInHtml 三处一致），`npm run build` 重建 dist。
- 回归测试：`frontend/src/markdown/katexCssSync.test.ts` 锁住"渲染器输出类名 ⇔ CSS 规则覆盖"不变量（版本一致 + strut/sizing 规则存在 + 多行 inline array strut 高度 > 2em）。
- **升级 katex / rehype-katex 前必查**：rehype-katex 最新版只支持 katex ^0.16；若未来升级，CSS 与渲染器必须同步，跑 `npx vitest run` 验证。

**Math coverage 校验（`frontend/scripts/math-coverage.mjs`）：**
- `node scripts/math-coverage.mjs <cleaned.md> [...]` 输出：`Raw math candidates` / `remark-math nodes` / `raw-HTML math` / `KaTeX rendered` / `Lost candidates`。5 篇真实论文实测 594 candidates → 594 rendered，**Lost = 0**（此前 table 内 198 条是 lost，现已全部渲染）。

**已知限制（未处理）：** 公式内部的 OCR 点号重音（如 `\mathrm{ḊCGḌ}`）**不在 prose 清洗范围内**（"不改 math block"），KaTeX 以警告 + 回退字形渲染，不报错。

## 项目结构

```
paper-master/
├── main.py                  # CLI 入口，交互循环 + 批量解析 + --zotero
├── config.example.yaml      # 配置模板
├── requirements.txt         # 依赖
├── paper_reader/
│   ├── blocks.py            # 数据模型 + 标签标准化 + chunk 合并
│   ├── agent.py             # Agent 循环 + 工具定义 + 压缩 + Observation Memory + 流式
│   ├── mineru_parser.py     # MinerU 解析器 + sha256 缓存
│   ├── memory.py            # Paper Memory 抽取 + 缓存读写
│   ├── parser.py            # PyMuPDF 解析器（旧，保留）
│   ├── llm.py               # LLM 客户端（Anthropic/OpenAI 兼容）+ 路由 + 配置加载
│   ├── context.py           # BGE-M3 混合检索 + 对话上下文 + 窗口构建
│   ├── zotero.py            # Zotero 只读数据层（直读 sqlite）
│   ├── papers.py            # Web 会话仓库：Session + 异步解析 + 历史/观察落盘 + SSE 事件源 + chunks-index
│   ├── observations.py      # Session Observation + 图像描述缓存读写
│   ├── arxiv_search.py      # arXiv 搜索客户端：限速闸 + 429 退避重试 + 三源兜底编排（S2→arXiv→OpenAlex）
│   ├── s2_search.py         # Semantic Scholar 客户端：主源搜索 + 1rps 闸 + 429 重试 + key 加载
│   ├── openalex_search.py   # OpenAlex 薄客户端，降级兜底
│   ├── latex_fix.py         # OCR 公式 LaTeX 语义规范化（serve-time）
│   ├── math_quality.py      # 数学质量层：覆盖率统计 + OCR/污染检测（含 CLI）
│   └── server.py            # FastAPI：/api/zotero/* + /api/papers/* + /api/arxiv/* + 前端静态托管
├── frontend/                # React + TypeScript + Ant Design + Vite
│   ├── src/citation.ts      # 引用归一化/定位纯函数（chunk snippets → 已渲染 DOM 命中元素）
│   ├── src/markdown/        # 共享 remark/rehype 插件栈 + rehypeMathInHtml + KaTeX CSS 同步回归测试
│   ├── scripts/             # math-coverage.mjs 公式覆盖率校验
│   └── dist/                # 构建产物（server.py 静态托管）
└── tests/                   # 392 个 Python 测试 + 55 个前端 vitest
```

## 模型路由

- Agent 检索窗口内含图片/表格 → Vision 模型，带 `[路由: vision]` 日志
- 纯文字 → Text 模型，带 `[路由: text]` 日志
- 两个模型独立配置（provider / api_key / base_url），均支持 OpenAI 兼容端点或 Anthropic

## 缓存

- `~/.cache/paper-master/{sha256(pdf)}.json` — 完整 PaperDocument：blocks + chunks（含 embedding + lexical_weights + aliases）
- `~/.cache/paper-master/{sha256}-memory.json` — Paper Memory（独立文件，生命周期解耦）
- `~/.cache/paper-master/{sha256}-history.json` — 对话历史（Web 端；GET/DELETE `/api/papers/{id}/history`）
- `~/.cache/paper-master/{sha256}-observations.json` — session 观察（全量不去重，注入最近 20 条；随 history 一并清空）
- `~/.cache/paper-master/{sha256}-images.json` — describe_image 图像描述（论文级，按图片相对路径 key，清空对话不影响）
- `~/.cache/paper-master/mineru-output/` — MinerU 原始输出（持久化，不自动清理）
- PDF 内容 hash 作 key，相同文件只解析一次；`--batch` 分三阶段（MinerU 解析 → BGE-M3 编码 → Memory 抽取）

## 标签标准化

解析阶段对图片/表格/算法 caption 做标准化处理：

```
原始: "TABLE III FPA UNIVERSALITY..."
注入: "TABLE III (Table 3) FPA UNIVERSALITY..."

aliases: ["TABLE III", "Table 3", "表3", "表 3"]
```

支持的引用类型：Fig/Figure、Table/TABLE、Algorithm

## 路线图

路线图的唯一真源是 `CLAUDE.md` 的「下一步优先级」节（含 P6 自主调研方向）。已完成条目的完整清单见 `docs/history.md`。
