# Paper Master — 架构与设计

## 工作原理

**论文预处理（一次性）：**

```
PDF → MinerU CLI (VLM 版面分析) → content_list_v2.json + images/ + .md
  ├── 识别章节层级、公式、表格、图片、阅读顺序
  ├── ContentBlock（版面原样）→ SemanticChunk（语义合并，~240 tokens，64 tokens 重叠）
  ├── PaperDocument → sha256 缓存到 ~/.cache/paper-master/
  ├── BGE-M3 编码（1024-d dense + sparse lexical weights，随 chunk 缓存）
  └── Paper Memory 结构化抽取（LLM 一次性，独立缓存）
```

**对话时（Agent + 工具循环）：**

```
用户提问 → PaperAgent.run()
  ├── system prompt 注入：Paper Memory + 论文章节目录 + session 观察（最近 20 条）
  ├── LLM 决策调用工具（原生 function calling，最多 7 轮）：
  │     search_paper(query)     — BGE-M3 混合检索 + 图表 aliases 精确匹配
  │     get_section(reference)  — 章节精确引用（编号深度有效层级 + 平层级兜底，3000 字截断）
  │     describe_image(rid)     — VLM 图片内容解析（描述按图片路径落盘，命中缓存不调 API）
  │     record_observation(...) — 结构化记录发现（session 级累积，落盘 {sha}-observations.json）
  ├── 往轮 tool result 压缩为 observation 摘要（保留最近 3 轮完整）
  └── 中文回答（工具参数用英文，论文是英文，检索匹配更好）
```

**Web 版（localhost:8000 单端口）：**

```
浏览器 → FastAPI (server.py)
  ├── GET  /api/zotero/*           — 只读 Zotero 库（收藏夹树/条目/搜索，直读 sqlite）
  ├── POST /api/papers/open        — 打开论文（有缓存直接 ready；无缓存后台线程异步解析，前端轮询 /status）
  ├── GET  /api/papers/{id}/content — markdown 阅读区（serve-time 数学清洗 + 图片 URL 重写）
  └── POST /api/papers/{id}/chat   — SSE 流式对话（驱动 PaperAgent.run_stream()）
前端（React + TypeScript + Ant Design + Vite）：论文列表 / markdown 阅读区 / SSE 对话区
```

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

```
ContentBlock          — 版面元素，1:1 映射 MinerU 输出
  type: text | image | table | formula
  level: 0=正文, 1=一级标题, 2=二级标题...
  page_idx, bbox, image_path

SemanticChunk         — 语义单元，RAG 检索最小粒度
  chunk_id, text
  blocks: list[ContentBlock]
  section_path: list[str]        — 层级标题路径
  images: list[ContentBlock]     — 挂载的图片/表格
  figure_labels: list[str]       — 原始标签 ["Fig. 1", "TABLE III"]
  aliases: list[str]             — 标准化别名，含中文 ["Fig. 1", "Figure 1", "图1", ...]
  embedding: list[float] | None  — 1024-d BGE-M3 稠密向量
  lexical_weights: dict | None   — BGE-M3 稀疏词权重
  合并规则: 标题断开 | ~240 tokens 截断 | 64 tokens 重叠
  图片/表格 caption 注入标准化标签后写入 text

PaperMemory           — 结构化论文理解，LLM 一次性抽取 10 字段
  research_problem, motivation, method, method_why, experiments,
  key_results, contributions, limitations, takeaways, keywords
  注入对话 system prompt，与 RAG 检索互补

Observation           — Agent 每轮检索后的结构化观察（L2 记忆，session 级）
  summary, round_num, facts, entities, sources, question（来源提问）
  存 ConversationContext.observations 跨提问累积；落盘 {sha256}-observations.json

PaperDocument
  blocks: list[ContentBlock]
  chunks: list[SemanticChunk]
  memory: PaperMemory | None
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
- **三层记忆**：L1 对话（最新轮完整，往轮压缩）、L2 Observation（结构化观察，session 级累积 + 落盘，注入最近 20 条带「未经复核」标注）、L3 Evidence（`Observation.sources` 来源追溯，引用溯源预留）
- **压缩**：每轮发送前压缩往轮 tool result，保留最近 3 轮完整（保证模型能回读证据）；无 observation 时降级为句子边界智能截断

## 数学渲染流水线

MinerU 输出的公式带 OCR 伪影，直接喂 KaTeX 会渲染失败或排版重叠，因此是一条多阶段流水线：

```
PDF → Markdown → serve-time 清洗（后端） → KaTeX 渲染（前端）
```

- **后端 `latex_fix.py`**：OCR LaTeX 语义规范化 — HTML `<sub>/<sup>` → `_{}/^{}`、字母间距折叠（`\mathrm { V e r i f y }` → `Verify`）、跨命令边界拆分的标识符合并、下标内上标嵌套修复、`...` → `\dots`、函数名 → `\operatorname`、裸标识符/密钥 → `\mathrm{}`。serve-time 应用，不改原始缓存
- **后端 `math_quality.py`**：编码异常（`�`）/点号重音检测、prose OCR 清洗（不改 math block）、Unicode 数学字符与 Markdown/LaTeX 污染检测（含 CLI）
- **前端**：react-markdown + remark-math + rehype-katex（公式）+ rehype-raw（HTML 表格）+ 自研 `rehypeMathInHtml` 插件（渲染原生 HTML table 单元格里的 `$..$`，remark-math 看不到的部分）
- **约束**：KaTeX 的 CSS 与渲染器版本必须全局对齐（当前统一 0.16.x），否则类名不匹配导致行盒塌陷、高 inline 公式与正文重叠；`frontend/scripts/math-coverage.mjs` 校验公式覆盖率（5 篇真实论文 594→594，Lost=0）

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
│   ├── papers.py            # Web 会话仓库：Session + 异步解析 + 历史/观察落盘 + SSE 事件源
│   ├── observations.py      # Session Observation + 图像描述缓存读写
│   ├── latex_fix.py         # OCR 公式 LaTeX 语义规范化（serve-time）
│   ├── math_quality.py      # 数学质量层：覆盖率统计 + OCR/污染检测（含 CLI）
│   └── server.py            # FastAPI：/api/zotero/* + /api/papers/* + 前端静态托管
├── frontend/                # React + TypeScript + Ant Design + Vite
│   ├── src/markdown/        # rehypeMathInHtml 插件 + KaTeX CSS 同步回归测试
│   ├── scripts/             # math-coverage.mjs 公式覆盖率校验
│   └── dist/                # 构建产物（server.py 静态托管）
└── tests/                   # 256 个 Python 测试 + 17 个前端 vitest
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

- [x] PDF 解析（PyMuPDF → MinerU）
- [x] 版面级数据模型 + 语义块合并
- [x] BGE-M3 dense + sparse 混合检索 + 标准化标签/中文别名
- [x] 多 LLM 后端 + 多模态路由
- [x] RAG 工具化（Agent 循环 + search_paper / get_section / describe_image / record_observation）
- [x] Paper Memory 结构化抽取（10 字段，独立缓存）
- [x] Tool Result 压缩 + Observation Memory（三层记忆）
- [x] Zotero 只读对接（CLI + FastAPI）
- [x] Web 应用（localhost:8000 单端口，异步解析 + SSE 流式对话）
- [x] 数学渲染清洗流水线（latex_fix + math_quality + KaTeX 前端渲染）
- [x] 对话历史持久化 + 前端恢复/清空（GET/DELETE /api/papers/{id}/history）
- [x] get_section 平层级修复（编号深度有效层级 + heading-only 兜底）+ 章节目录注入 system prompt
- [x] Session Observation 跨提问累积与落盘 + describe_image 描述缓存
- [ ] 引用溯源（回答标注来源章节/页码，Observation.sources 已就绪）
- [ ] 本地知识库（多论文统一索引）
