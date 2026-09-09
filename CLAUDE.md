# CLAUDE.md — Paper Master 项目接手文档

## 文档维护约定（重要）

**每次代码修改完成后、确认一个功能做好后，都必须同步更新本文件**（架构、已完成、进行中、下一步优先级、测试数、数据模型、设计决策等受影响部分），并随改动一起提交。文档落后于代码视为缺陷。

## 项目概述

paper-master 是一个科研智能体（Research Agent），帮助研究人员"读论文、查论文、思考 idea"。当前处于早期阶段，先构建扎实的论文理解和检索基础设施，逐步从"论文问答 RAG"演进为能够理解、比较、产生新想法的科研伙伴。目前功能：打开 PDF → MinerU 版面解析 → BGE-M3 向量编码 → Paper Memory 结构化抽取 → 展示摘要和目录 → 交互式中文论文对话。

GitHub: https://github.com/xjzh666/paper-master

## 环境

- Python 3.10+，WSL2 (Ubuntu 22.04)
- CUDA GPU（RTX 3060 6GB），NVIDIA 驱动 610.53
- CUDA Toolkit 12.8 已安装在 WSL2 中（`/usr/local/cuda-12.8`）
- 虚拟环境: `source .venv/bin/activate`
- 依赖: pymupdf, anthropic, openai, pyyaml, pillow, scikit-learn, flagembedding, prompt_toolkit, mineru
- 安装: `pip install -r requirements.txt`
- GitHub 推送需要 `GIT_SSL_NO_VERIFY=true`（本机网络 TLS 问题）
- 没有 `gh` CLI（已安装但未认证），用 HTTPS + token 推送

## 架构

```
main.py                  # CLI 入口，交互循环 + 批量解析
paper_reader/
  ├── blocks.py          # 数据模型（ContentBlock / SemanticChunk / PaperMemory / PaperDocument）
  ├── agent.py           # Agent 循环 + 工具定义 + 压缩 + Session Observation（跨提问累积+落盘）+ 流式 run_stream()
  ├── mineru_parser.py   # MinerU 解析器 + sha256 缓存
  ├── memory.py          # Paper Memory 抽取 + 缓存读写
  ├── observations.py    # Session Observation + 图像描述缓存读写（{sha}-observations.json / {sha}-images.json）
  ├── parser.py          # PyMuPDF 解析器（旧，保留不用）
  ├── llm.py             # LLM 客户端 + 路由 + 配置加载
  ├── context.py         # 对话上下文 + BGE-M3 向量检索 + 窗口构建
  ├── zotero.py          # Zotero 只读数据层（collections/items/search/get_item/resolve_pdf）
  ├── papers.py          # Web 会话仓库：Session 管理 + 异步 MinerU 解析 + 后台 Paper Memory 抽取 + 会话历史/观察落盘与恢复 + chat_events SSE 事件源 + chunks-index 定位索引
  ├── latex_fix.py       # OCR 公式 LaTeX 语义规范化（HTML→上下标、字母间距、上下标嵌套、\dots、\operatorname、标识符 \mathrm 包装），serve-time 应用
  ├── math_quality.py    # 数学质量层：公式覆盖率统计 + OCR/编码异常检测 + prose OCR 规范化 + Unicode 数学字符/污染检测（含 CLI）
  └── server.py          # FastAPI：/api/zotero/* + /api/papers/* 接口 + 前端静态托管（mount("/")）
docs/
  ├── architecture.md    # 架构文档
  ├── specs/             # 功能 spec 存档（docs/specs/YYYY-MM-DD-<slug>.md）
  └── superpowers/specs/ # 设计 spec 存档（同源格式，如 2026-09-01-session-observation-design.md）
frontend/                # Web 前端（React + TypeScript + Ant Design + Vite）
  ├── src/               # App 三栏：论文列表 / markdown 阅读区 / SSE 对话区 + api client
  │   ├── citation.ts    # 引用归一化/定位纯函数（chunk snippets → 已渲染 DOM 命中元素）
  │   ├── cite-highlight.css # 引用定位高亮样式（.cite-flash，ReadingPanel 引用定位用）
  │   ├── markdown/      # plugins.ts 共享 remark/rehype 插件栈（阅读区 + 对话区共用）
  │   │                  # rehypeMathInHtml 插件：渲染原生 HTML table 内的 $..$（remark-math 看不到的部分）
  │   │                  # 渲染栈：react-markdown + remark-math/rehype-katex（公式）+ rehype-raw（HTML 表格/sub/sup）+ rehypeMathInHtml + github-markdown-css
  │   │                  # 对话区：助手消息同样走该渲染栈（memo 化，流式增量重渲染仅最后一条）
  │   └── ...
  ├── scripts/           # math-coverage.mjs：公式覆盖率校验（raw → remark-math → raw-HTML → KaTeX 渲染计数）
  └── dist/              # 构建产物（npm run build 输出，server.py 静态托管）
tests/                   # 281 个 Python 测试 + 43 个前端 vitest，全过
config.example.yaml      # 配置模板（提交）
config.yaml              # 实际配置（gitignore）
.venv/                   # 虚拟环境（gitignore）
papers/                  # 测试用 PDF 论文（gitignore）
```

### 当前数据流（Agent + 工具模式，已实现）

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
      └── record_observation(...) — 结构化记录发现（summary + facts + entities + sources；与当前问题无关但有价值的也记）
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

### 数据模型

**论文层（blocks.py）：**
```
ContentBlock          — 版面元素，1:1 映射 MinerU 输出
  type: text | image | table | formula
  level: 0=正文, 1=一级标题, 2=二级标题...
  page_idx, bbox, image_path, image_bytes

SemanticChunk         — 语义单元，合并 ~512 tokens，64 tokens 重叠
  合并规则: 遇标题断开 | 512 tokens 截断 | 图片挂载

PaperMemory           — 结构化论文理解，LLM 一次性抽取
  research_problem, motivation, method, method_why, experiments,
  key_results, contributions, limitations, takeaways, keywords (10 字段)

PaperDocument
  blocks: list[ContentBlock]   chunks: list[SemanticChunk]
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

## 已完成

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
- [x] **数学渲染清洗 pipeline（论文级公式质量优化）** — 见"公式渲染注意事项"。包含：
  - [x] **LaTeX 语义规范化（`latex_fix.py`）** — 裸标识符/密钥/字段统一 `\mathrm{}`（白名单：PK/SK/OTK/SOTK/Cert/aid/uid/name/device/IP/port…）、跨命令边界拆分的标识符合并（`S \mathrm{K}`→`\mathrm{SK}`）、函数名 `\operatorname`、`\mathbb`/`\mathcal`/`\boldsymbol` 字母间距折叠、下标内上标嵌套、集合/元组 `\dots`
  - [x] **HTML table 内公式渲染（`rehypeMathInHtml.ts`）** — 修复 remark-math 看不到原生 `<table>` 内 `$..$` 的问题，挂在 rehypeRaw 之后用 KaTeX 渲染
  - [x] **公式覆盖率校验（`math-coverage.mjs`）** — raw → remark-math → raw-HTML → KaTeX 计数 + Lost candidates；5 篇真实论文 594→594，Lost=0
  - [x] **OCR/编码异常检测与 prose 规范化（`math_quality.py`）** — `\ufffd` 检测+移除、Ḋ/Ḍ 点号重音检测 + prose-only 规范化（不改 math block）、Unicode 数学字符检测（σ/∈/≤→…）、Markdown/LaTeX 污染检测（未闭合 `$`/`\(`/`\[`、`\_` 转义、`\text{}` 内错误数学）
  - [x] 测试：231 个 Python + 17 个前端 vitest 全过
- [x] **Web 后台 Paper Memory 抽取** — `papers.open_paper` 缓存命中路径补上 `load_memory_cache`（此前只有解析路径加载，已有记忆的论文会被白白重抽）；记忆仍缺失时 `_ensure_memory_background` 后台线程抽取，不阻塞 ready，失败静默降级，`memory_jobs` 防重
- [x] **对话面板 markdown+公式渲染** — 助手消息从纯文本改为 `MarkdownMessage`（memo 化的 react-markdown），复用与阅读区一致的插件栈（公式/HTML 表格/列表）；新增 `frontend/src/markdown/plugins.ts` 共享插件配置，`plugins.test.tsx` 锁住渲染行为；流式输出按"增量 buffer + 全量重渲染最后一条"处理，未闭合 `$$`/代码块在中间态按普通文本显示、闭合后自动成型
- [x] **对话历史落盘持久化** — `papers.py` 新增 `load_chat_history` / `save_chat_history`（`~/.cache/paper-master/{paper_id}-history.json`），`open_paper` 创建 Session 时加载、`chat_events` 回答完成后保存；损坏文件静默加载为空，出错不落盘（保留最近成功状态）。重启后端对话可恢复
- [x] **对话历史前端恢复 + 清空** — `GET /api/papers/{id}/history`（内存 session 优先，磁盘兜底）+ `DELETE` 清空；ChatPanel 打开论文自动拉取历史恢复展示（历史与本轮新消息间插「以上是历史对话」分割线），标题栏「清空」按钮联动清磁盘 history 与 session 观察；顺带修复换论文旧对话残留
- [x] **get_section 平层级修复 + 章节目录注入** — MinerU 把父子节标题全标成同一层级时，`find_section` 用编号深度（6 < 6.1 < 6.1.1）算有效层级，父章节正确收编子节正文；heading-only 结果兜底顺延后续块（2000 字上限）；system prompt 注入 `[论文章节目录]` 并要求 reference 从目录选取，杜绝瞎猜章节名
- [x] **Session Observation 跨提问 + 中间产物落盘** — observations 所有权上移到 `ConversationContext`（每问新建 agent 也跨提问累积），run 结束 finally flush 并打 question 标记；落盘 `{sha}-observations.json`（全量不去重），注入最近 20 条带「未经复核」标注；`describe_image` 结果按图片相对路径缓存 `{sha}-images.json`（命中不调 vision API）；记录标准放宽为"有独立价值即使与当次问题无关也记 + sources 必填"；清空对话联动清观察（图像描述不清）；CLI 端同样恢复/保存

## 进行中

- **P4 后续：本地知识库（下一版）** — Web 应用 MVP 已可用（列表→打开→解析→对话→阅读）；下一版把多论文统一索引做成本地知识库（见下一步优先级）

## 下一步优先级

核心转向：从"更好的论文问答 RAG" → "能理解论文、查论文、思考 idea 的科研 Agent"。

不再把检索做得更精细，而是让 Agent 真正理解论文内容，能跨章节推理。

### P0：RAG 工具化 ✅ 已完成

- [x] `search_paper(query)` — 单论文语义检索 + 图/表 aliases 精确匹配，BGE-M3 混合检索，window=1
- [x] `get_section(reference)` — 章节精确引用（含 HTML 标签剥离匹配），3000 字截断
- [x] `describe_image(resource_id)` — VLM 图片内容解析，图片懒加载
- [x] `record_observation(summary, facts, entities, sources)` — 结构化记录本轮检索发现，为压缩和长期记忆提供摘要
- [x] PaperAgent 完整 Agent 循环（LLM 原生 function calling，最多 7 轮）
- [x] Resource/ToolResult 结构化工具返回（text + resources，资源引用不传 bytes）
- [x] MinerU 输出持久化到 `~/.cache/paper-master/mineru-output/`
- [x] System prompt 含停止准则（拿到足够信息就回答、图片不可用不再重试）
- [x] Agent 打印工具调用日志（`[agent] tool_name(args) → N chars, M resources`）

### P1：Paper Memory（论文结构化理解）✅ 已完成

- [x] Paper Memory 数据结构（Research Problem, Motivation, Method, Experiment, Limitation, Contribution...）
- [x] LLM 驱动的论文结构化抽取（一次解析，存入缓存 `{sha256}-memory.json`）
- [x] 对话中注入 system prompt，RAG 检索 + Memory 全局理解互补

### P2：Tool Result 压缩 ✅ 已完成

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

### P3：引用溯源 ✅ 已完成

回答标注来源，让用户知道每段信息来自论文的哪一部分。已实现形态：回答内嵌引用链接 + 阅读区滚动高亮。

- [x] system prompt 引导 LLM 在 record_observation 和最终回答中引用来源
- [x] 最终回答中标注来源 chunk / page_idx / 章节
- [x] 引用链接 + 阅读区滚动高亮 — 回答中的 `[§x.x p.N](cite:chunk_N)` 链接由 ChatPanel 拦截点击，App 按 chunks-index 让 ReadingPanel 滚动高亮（设计见关键设计决策 #18）

### P4：Web 应用（当前方向，MVP 已完成）

核心目标转向：把 paper-master 做成**本地 Web 应用**（类似 Zotero），对接 Zotero 库里的论文，浏览器访问 `localhost:8000` 单端口使用。**暂不做"上网搜论文"**。

**已确认的技术选型：**
- 形态：**Web 应用**（不再用 Tauri，理由见关键设计决策 #13）
- 前端：**React + TypeScript + Ant Design**（Vite 构建）
- 后端：**FastAPI**（复用 `paper_reader/`，Python 直接读 Zotero sqlite + 单端口静态托管）
- PDF 阅读：**渲染 MinerU 解析结果（markdown + 章节 + 图片）**，不集成 pdf.js
- Zotero：**只读**（列出条目 + 打开论文）
- 启动：**`paper-web`** 一条命令（`~/.local/bin/paper-web` 脚本，拉起 uvicorn + 打开浏览器），或手动 `uvicorn paper_reader.server:app`

**规划任务（Web 应用 MVP）：**
- [x] 摸清 Zotero 数据库 schema
- [x] FastAPI 后端：Zotero 条目列表 API + 打开论文
- [x] `papers.py` 会话仓库 + 异步解析 + SSE 对话
- [x] React 前端：论文列表 + 收藏夹树 + 阅读区（markdown 渲染）+ 对话区
- [x] 生产静态托管（单端口）+ `paper-web` 命令
- [ ] **本地知识库：多论文统一索引（下一版）** — 当前单论文会话；下一版做跨论文检索/统一索引

### P5：暂缓

以下功能暂缓，等 Web 应用稳定后再评估：
- [ ] 上网搜论文（文献搜索）——**明确暂不做**
- [ ] 多轮对话 query rewriting（代词和省略会降低检索精度）
- [ ] 检索语义 section 过滤（"找实验结果"而非"找相似文本"）
- [ ] 多论文对比（/load + /compare）
- [ ] AnthropicClient 的 base_url 支持

## 用户当前配置

用户使用两个不同的模型（config.yaml）:
- text: glm-5.3-flash @ 智谱 open.bigmodel.cn — **GLM Coding Plan 套餐**，base_url 必须用 Coding Plan 专用端点 `https://open.bigmodel.cn/api/coding/paas/v4`；通用端点 `/api/paas/v4` 只扣普通余额，会报 429 code 1113「余额不足或无可用资源包」。Coding Plan 也有 Anthropic 协议端点（`/api/anthropic`），但项目 AnthropicClient 尚不支持 base_url 与工具调用，未走此路径
- vision: qwen3.5-plus @ dashscope.aliyuncs.com

两者都用 OpenAI 兼容格式（provider: openai）。

## 关键设计决策

1. **PDF 解析**：MinerU CLI（`mineru -p file -o dir -m auto`）的子进程调用，自动启停本地 API 服务，输出 content_list_v2.json
2. **检索策略**：BGE-M3 混合检索（dense + sparse）。dense 覆盖语义匹配，sparse 覆盖术语精确匹配。numpy 暴力 cosine similarity，无外部向量数据库。alises + 标准化标签（Roman→Arabic + 中文）辅助精确引用
3. **RAG 定位**：RAG 应作为 Agent 可调用的工具，而非整个系统的核心流程。Agent 决定什么时候需要检索，不强制每轮走 RAG
4. **路由规则**：检索窗口中包含图片/表格 → vision 模型；纯文字 → text 模型。路由日志 `[路由: vision/text]` 开箱可见。未来 Query Router 将区分定位/理解/比较三类问题
5. **系统提示词**：两个模型共用一个 SYSTEM_PROMPT。工具调用参数用英文（论文是英文，检索匹配更好），最终回答用中文
6. **缓存策略**：PDF 内容 sha256 → `~/.cache/paper-master/{hash}.json`（含 blocks + chunks + embeddings + lexical_weights + aliases）+ `{hash}-memory.json`（Paper Memory，独立文件用于生命周期解耦）+ `{hash}-history.json`（对话历史）+ `{hash}-observations.json`（session 观察，随 history 清空）+ `{hash}-images.json`（图像描述，论文级不清）。MinerU 原始输出留在 `~/.cache/paper-master/mineru-output/`（持久化，不自动清理）。batch 分三阶段（MinerU 解析 → BGE-M3 编码 → Memory 抽取）
7. **图片加载**：ContentBlock.image_bytes 懒加载，仅 LLM 需要时才读文件
8. **暂不引入 LangChain/LangGraph**：当前是简单流水线。后续 Agent 框架再评估，在此之前的工具化用纯函数接口
9. **旧 parser.py 保留不动**，mineru_parser.py 是主要解析路径
10. **Paper Memory**：论文理解不止依赖 chunk embedding，LLM 一次性抽取 10 个结构化字段（研究问题、动机、方法、实验、局限、关键词等），存入独立缓存。当前单论文直接注入 system prompt，后续多论文时改造为 Agent 工具按需调用。关键词留作多论文路由筛选
11. **Tool Result 压缩**：不增加额外 API 调用，利用 LLM 同一轮的多工具调用能力（record_observation + search_paper 在同一个 tool_calls 里发出）。保留最近 `KEEP_RECENT_ROUNDS=3` 轮完整（保证模型能回读证据，避免"证据被压后反复重搜"），更早的替换为 observation 摘要，无 observation 时降级为智能截断。压缩阈值必须严格保证"工具结果在第一次被模型读到前完整"（曾有 off-by-one bug）
12. **三层记忆架构**：L1 Conversation Memory（messages，最新轮完整，往轮压缩）、L2 Observation Memory（结构化观察，session 级存 `ctx.observations` 并落盘，注入最近 20 条）、L3 Evidence Memory（来源追溯，Observation.sources 字段已就绪，P3 完善）
13. **桌面形态从 Tauri 改为 Web 应用**：早期定 Tauri，后改为纯 Web 应用（React+Vite 前端 + FastAPI 单端口静态托管 + `paper-web` 命令一键启动）。理由：GPU 与 Zotero 数据都在 WSL2，浏览器天然跨 Windows/WSL 边界（无需 WSLg）；免装 Rust 工具链；单端口部署简单。代价：无系统托盘/原生窗口，但当前功能（读 PDF + 对话）浏览器足够。启动命令 `paper-web` 是 `~/.local/bin/paper-web` 脚本（激活 venv + 拉起 uvicorn + 开浏览器），旧 `launch.bat` 双击方案已废弃
14. **静态托管挂在 `/`**：`server.py` 的 `create_app(data_dir=None, frontend_dist=None)` 在**所有 API 路由之后** `mount("/", StaticFiles(html=True))`（默认指向 `frontend/dist`）。FastAPI 按注册顺序匹配，API 路由优先，前端 SPA 兜底。`frontend_dist` 可显式传入（测试用临时目录），dist 不存在时静默跳过（纯 API 模式不受影响）
15. **`paper-web` 一键启动 + 两个启动前置**：启动命令是 `~/.local/bin/paper-web` bash 脚本（`cd` 项目 + `source .venv/bin/activate` + 后台 `explorer.exe` 开浏览器 + `exec uvicorn`），任意目录可敲、无参数。两个易踩的坑：① **前端 `npm run build` 是首次启动前置**——`frontend/dist/` 不存在时 server.py 静默跳过静态托管，根路径 `/` 返回 404（需构建后重启后端才生效）；② **Zotero sqlite 连接必须 `check_same_thread=False`**——`get_library` 是带 yield 的同步依赖，FastAPI 线程池里创建连接与执行查询在不同线程，默认 `check_same_thread=True` 会报 `SQLite objects created in a thread can only be used in that same thread`；只读连接（`mode=ro`）+ `sqlite3.threadsafety=1`（serialized）下关掉检查是安全的。旧 `launch.bat`（需 CRLF + 纯 ASCII）已废弃
16. **中间产物落盘原则：可重建的不存，不可重建的才存**（2026-09-01）— `search_paper`/`get_section` 的检索原文不落盘（chunk 索引本身就是持久化 + 检索层，BGE-M3 本地重查免费）；只落盘模型产物：session observations（跨提问证据链，`{sha}-observations.json` 全量 append 不去重，prompt 只注入最近 20 条）和 `describe_image` 图像描述（`{sha}-images.json`，论文级，key 用图片相对路径——resource id 尾号是当次枚举序号，跨调用不稳定）。观察注入带「未经复核」标注，定位为线索而非事实；记录标准是"有独立价值的事实即使与当次问题无关也记"，sources 必填。observations 与 history 同生同灭，图像描述独立存在。spec: `docs/superpowers/specs/2026-09-01-session-observation-design.md`
17. **章节层级以编号深度为准**：MinerU 可能把父子节标题标成同一 level（如全部 level 2），`find_section` 因此用编号深度（`6` < `6.1` < `6.1.1`）计算有效层级，无编号标题退回 parser level；heading-only 的匹配结果兜底顺延后续块（2000 字上限）。注意 `merge_blocks` 的 `section_path` 仍按原始 level 截断（平层级解析下路径也是平的），目前无读取方，暂未修
18. **P3 引用溯源：引用即文本**：chunk 是引用的统一锚点。链路：检索文本带 `[src chunk_N §标题 p.页]` 标签 → system prompt 要求回答内嵌 `[§x.x p.N](cite:chunk_N)` 链接（编号只能取上下文中可见的 [src] 标签）——链接就是普通 markdown 文本，SSE 通道与历史持久化零协议改动 → 前端 ChatPanel 的 urlTransform 放行 `cite:` scheme，点击后 App 按 chunks-index 定位，DOM 归一化匹配（两侧同规则剥空白/标点，snippet 侧只剥 `$`/`$$` 定界符保留公式 LaTeX 内容，DOM 侧 `.katex` 子树替换为其 MathML annotation 的 LaTeX 源参与归一化——无 annotation 时删除兜底，多处命中取最深元素）。已知限制：早期轮次工具结果被压缩移除 [src] 标签后，对应 chunk 不再可引用（prompt 约束宁可不加链接）

## 常用命令

```bash
cd /home/xiejiezhen/paper-master
source .venv/bin/activate

python3 main.py paper.pdf                     # 单篇阅读（CLI）
python3 main.py --batch papers/               # 批量预热
python3 main.py --zotero                 # 从 Zotero 库选论文阅读（CLI）

uvicorn paper_reader.server:app          # FastAPI（Web 版后端，单端口 8000 托管 API + 前端）
paper-web                              # 一键启动 Web 版（激活 venv + 起 uvicorn + 开浏览器）

cd frontend && npm run dev              # 前端开发模式（Vite HMR，需后端已起）
cd frontend && npm run build            # 构建前端到 dist/（server.py 静态托管）

python3 -m pytest tests/ -v                   # Python 测试 (281)
cd frontend && npx vitest run                 # 前端 vitest (43)
python3 -m paper_reader.math_quality paper.md        # 数学质量分析（OCR/编码/污染）
python3 -m paper_reader.math_quality paper.md --fix out.md  # 输出清洗后的 md
cd frontend && node scripts/math-coverage.mjs out.md      # 公式覆盖率校验
GIT_SSL_NO_VERIFY=true git push               # 推送
```

## BGE-M3 注意事项

- 模型：`BAAI/bge-m3`，约 2.27 GB，路径指向 `~/.cache/modelscope/models/BAAI--bge-m3/`（modelscope 下载）
- 如果 modelscope 路径不存在，自动回退到 HuggingFace `'BAAI/bge-m3'`
- 进程级单例，首次加载约 2-3 秒（GPU fp16），之后常驻显存
- 查询编码 ~10ms，numpy cosine sim ~微秒级，检索开销可忽略
- 测试用 bigram-overlap fake model 替代，不需要真实模型

## Paper Memory 注意事项

- 输入源优先 MinerU 生成的 `.md` 文件（无重叠），回退到 blocks 按序取 text
- 每次打开论文自动尝试加载缓存 `{sha256}-memory.json`，无缓存则调 LLM 抽取
- 抽取失败不阻塞主流程，`paper.memory` 保持 `None`，对话降级为纯 RAG
- 字段含"未提及"的不注入 system prompt（减少噪音）

## MinerU 注意事项

- MinerU 需要 CUDA GPU + CUDA Toolkit。当前环境已配好（驱动 610.53 + CUDA 12.8）
- 首次解析一篇论文约 1-2 分钟（VLM 模型加载 + 推理），之后从缓存秒加载
- MinerU 自动下载模型到 `~/.cache/modelscope/models/`（MinerU2.5-Pro-2605-1.2B，约 2.15 GiB）
- `content_list_v2.json` 是分页嵌套结构，v1 是平铺列表。`_normalize_items` 方法统一处理

## 公式渲染注意事项（数学渲染清洗 pipeline）

数学渲染是一个多阶段流水线：`PDF → Markdown → 公式/OCR/HTML 清洗 → LaTeX 语义规范化 → Math coverage 校验 → KaTeX 渲染`。

**后端（Python）—— serve-time 清洗：**
- `papers.get_content` 调 `math_quality.fix_paper_markdown(md)` = `fix_markdown_math()` + `normalize_ocr_prose()`，再重写图片 URL。
- `latex_fix.fix_latex_math` 语义规范化（按顺序）：① HTML `<sub>/<sup>`→`_{}/^{}` ② `\mathrm{...}` 等 font 命令字母间距折叠（含 `\mathbb`/`\mathcal`/`\boldsymbol`）③ 跨命令边界拆分的标识符合并（`S \mathrm{K}`→`\mathrm{SK}`）④ 下标内上标嵌套修复 ⑤ `...`/`\bullet\bullet\bullet`→`\dots` ⑥ 函数名→`\operatorname` ⑦ 裸标识符（`PK`/`SK`/`OTK`/`aid`/`uid`/`name`…白名单）→`\mathrm{}` ⑧ 括号/上下标空白折叠。
- **显示公式结尾的 `$$` 必须独占一行**：`_clean_spacing` 只折叠空格/制表符（`[ \t]*`），**绝不能折叠换行**——否则 remark-math 不认行尾 `$$` 为闭合符（回归测试 `test_display_math_keeps_newline_before_closing_delim`）。
- **改 latex_fix.py / math_quality.py 后重启后端即可**（serve-time 应用，无需前端重建）。

**`math_quality.py`（公式覆盖率 + OCR/编码/污染检测）：**
- `count_math_candidates`（raw `$...$`/`$$...$$` 计数）、`detect_encoding_errors`（`\ufffd`）、`detect_ocr_diacritics`（Ḋ/Ḍ 类点号）、`detect_unicode_math`（prose 内 σ/∈/≤→…）、`detect_pollution`（未闭合 `$`/`\(`/`\[`、`\_` 转义、`\text{}` 内错误数学）。
- `normalize_ocr_prose`：只清洗 **prose**（标题/正文/caption）的点号重音 + 移除 `\ufffd`，**不改 math block**（避免破坏公式）。
- CLI：`python3 -m paper_reader.math_quality <file.md> [--fix out.md] [--json]`。

**前端（TS）—— HTML table 内公式：**
- remark-math 只处理 markdown AST，看不到原生 `<table>` 里的 `$...$`；`rehypeRaw` 在 `rehypeKatex` 之后才展开 HTML。新增 `frontend/src/markdown/rehypeMathInHtml.ts` 插件，挂在 **rehypeRaw 之后**，把 table 单元格文本里的 `$...$`/`$$...$$` 用 KaTeX 渲染（分隔符正则与 `_MATH_SPLIT` 保持一致）。改前端后需 `npm run build`。

**KaTeX 版本必须全局对齐（2026-08-31 修复的公式重叠 bug）：**
- 症状：display 公式（`$$`）正常，**inline 高公式**（如 `$\begin{array}...\end{array}$`）与上下行文字垂直重叠。
- 根因：`main.tsx` 的 CSS import 解析到顶层 katex，而 `rehype-katex@7`（最新版，锁定 `katex@^0.16`）用嵌套 katex 渲染。顶层装 0.18.4 时 CSS 类名（`katex-strut`/`katex-base`/`katex-sizing`）与 DOM 类名（`strut`/`base`/`sizing`）不匹配，关键规则 `.katex .strut{display:inline-block}` 缺失 → strut 沦为普通 inline span（height 无效）→ 行盒不再为高公式保留高度 → 溢出重叠。
- 修复：顶层 `katex` 降到 `^0.16.47` 与渲染器 dedupe 成同一份（CSS / rehype-katex / rehypeMathInHtml 三处一致），`npm run build` 重建 dist。
- 回归测试：`frontend/src/markdown/katexCssSync.test.ts` 锁住"渲染器输出类名 ⇔ CSS 规则覆盖"不变量（版本一致 + strut/sizing 规则存在 + 多行 inline array strut 高度 > 2em）。
- **升级 katex / rehype-katex 前必查**：rehype-katex 最新版只支持 katex ^0.16；若未来升级，CSS 与渲染器必须同步，跑 `npx vitest run` 验证。

**Math coverage 校验（`frontend/scripts/math-coverage.mjs`）：**
- `node scripts/math-coverage.mjs <cleaned.md> [...]` 输出：`Raw math candidates` / `remark-math nodes` / `raw-HTML math` / `KaTeX rendered` / `Lost candidates`。5 篇真实论文实测 594 candidates → 594 rendered，**Lost = 0**（此前 table 内 198 条是 lost，现已全部渲染）。

**已知限制（未处理）：** 公式内部的 OCR 点号重音（如 `\mathrm{ḊCGḌ}`）**不在 prose 清洗范围内**（"不改 math block"），KaTeX 以警告 + 回退字形渲染，不报错。
