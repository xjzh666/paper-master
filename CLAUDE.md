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
  ├── agent.py           # Agent 循环 + 工具定义 + 压缩 + Observation Memory
  ├── mineru_parser.py   # MinerU 解析器 + sha256 缓存
  ├── memory.py          # Paper Memory 抽取 + 缓存读写
  ├── parser.py          # PyMuPDF 解析器（旧，保留不用）
  ├── llm.py             # LLM 客户端 + 路由 + 配置加载
  ├── context.py         # 对话上下文 + BGE-M3 向量检索 + 窗口构建
  ├── zotero.py           # Zotero 只读数据层（collections/items/search/get_item/resolve_pdf）
  └── server.py           # FastAPI：/api/zotero/* 只读接口
tests/                   # 178 个测试，全过
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
  → 每轮发送前 _compact_messages() 压缩往轮 tool result
  → LLM 决策调用工具（最多 7 轮）:
      ├── search_paper(query)     — BGE-M3 混合检索 + aliases 精确匹配
      ├── get_section(reference)  — 章节精确引用，3000 字截断
      ├── describe_image(rid)     — VLM 图片内容解析
      └── record_observation(...) — 结构化记录本轮发现（summary + facts + entities + sources）
  → 往轮 tool result 替换为 observation 摘要（无 observation 则智能截断降级）
  → 中文回答
```

遗留的简单路径 `LLMRouter.answer()` 仍然可用，但主要路径是 PaperAgent。

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
Observation           — 每轮检索后的结构化观察（L2 记忆）
  summary, round_num, facts, entities, sources

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
- [x] 178 个测试全覆盖（单元 + 集成，含 embedding mock）
- [x] 中文 README + docs/architecture.md
- [x] **Zotero 连接（CLI + API）** — `zotero.py` 只读读取 Windows 侧 Zotero sqlite（`/mnt/c/Users/ASUS/Zotero`），解析条目元数据（标题/作者/年份/期刊/DOI/收藏夹）+ 定位 PDF（storage: 路径 → `storage/{attachment_key}/{filename}`）；`main.py --zotero` 搜索/收藏夹选论文进入对话；FastAPI 暴露 collections/items/search/items/{id} 四端点，前端/模型 agent 复用

## 进行中

- **P4 桌面应用 + 本地知识库**：技术选型已定（Tauri + React + TS + Ant Design + FastAPI），待开始开发。PDF 用 markdown 渲染、Zotero 只读、Tauri 双击启动自动拉起 FastAPI

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
- [x] 每次 `run()` 调用重置 `_tool_round_map` 和 `_observations`，跨对话不污染
- [x] `round_num` 字段解决 observation-to-round 的索引映射问题
- [x] **off-by-one 修复**：压缩阈值 `round_num < current_round - KEEP_RECENT_ROUNDS`，保证工具结果第一次被模型读到前完整保留（此前早压一轮导致模型永远读不到完整结果，陷入无限检索）
- [x] **检索瘦身**：chunk 阈值 480→240 tokens（约 960 字），`search_paper` window=1→0，返回量从 13-16K 降到 3-5K
- [x] **工具调用语言**：工具参数（查询、章节引用、观察记录）一律英文（论文是英文），仅最终回答中文；工具描述改写为英文

### P3：引用溯源（下一步）

回答标注来源，让用户知道每段信息来自论文的哪一部分。

`Observation.sources` 字段已支持 `['p3 §2.1']` 格式的引用标注（基础设施就绪），待做：
- [ ] system prompt 引导 LLM 在 record_observation 和最终回答中引用来源
- [ ] 最终回答中标注来源 chunk / page_idx / 章节

### P4：桌面应用 + 本地知识库（当前方向，规划中）

核心目标转向：把 paper-master 做成**本地桌面应用**（类似 Zotero），对接 Zotero 库里的论文，形成本地知识库。**暂不做"上网搜论文"**。

**已确认的技术选型：**
- 桌面外壳：**Tauri**（双击启动，自动拉起 FastAPI，不要求手动起服务）
- 前端：**React + TypeScript + Ant Design**
- 后端：**FastAPI**（复用 `paper_reader/`，Python 直接读 Zotero sqlite）
- PDF 阅读：**渲染 MinerU 解析结果（markdown + 章节 + 图片）**，不集成 pdf.js
- Zotero：**只读**（列出条目 + 打开论文）

**规划任务：**
- [x] 摸清 Zotero 数据库 schema
- [x] FastAPI 后端：Zotero 条目列表 API + 打开论文
- [ ] Tauri 工程脚手架 + 双击启动自动拉起 FastAPI
- [ ] React 前端：论文列表 + 收藏夹树 + 阅读区（markdown 渲染）+ 对话区
- [ ] 本地知识库：多论文统一索引

### P5：暂缓

以下功能暂缓，等桌面应用稳定后再评估：
- [ ] 上网搜论文（文献搜索）——**明确暂不做**
- [ ] 多轮对话 query rewriting（代词和省略会降低检索精度）
- [ ] 检索语义 section 过滤（"找实验结果"而非"找相似文本"）
- [ ] 多论文对比（/load + /compare）
- [ ] AnthropicClient 的 base_url 支持

## 用户当前配置

用户使用两个不同的模型（config.yaml）:
- text: deepseek-v4-flash @ api.deepseek.com
- vision: qwen3.5-plus @ dashscope.aliyuncs.com

两者都用 OpenAI 兼容格式（provider: openai）。

## 关键设计决策

1. **PDF 解析**：MinerU CLI（`mineru -p file -o dir -m auto`）的子进程调用，自动启停本地 API 服务，输出 content_list_v2.json
2. **检索策略**：BGE-M3 混合检索（dense + sparse）。dense 覆盖语义匹配，sparse 覆盖术语精确匹配。numpy 暴力 cosine similarity，无外部向量数据库。alises + 标准化标签（Roman→Arabic + 中文）辅助精确引用
3. **RAG 定位**：RAG 应作为 Agent 可调用的工具，而非整个系统的核心流程。Agent 决定什么时候需要检索，不强制每轮走 RAG
4. **路由规则**：检索窗口中包含图片/表格 → vision 模型；纯文字 → text 模型。路由日志 `[路由: vision/text]` 开箱可见。未来 Query Router 将区分定位/理解/比较三类问题
5. **系统提示词**：两个模型共用一个 SYSTEM_PROMPT。工具调用参数用英文（论文是英文，检索匹配更好），最终回答用中文
6. **缓存策略**：PDF 内容 sha256 → `~/.cache/paper-master/{hash}.json`（含 blocks + chunks + embeddings + lexical_weights + aliases）+ `{hash}-memory.json`（Paper Memory，独立文件用于生命周期解耦）。MinerU 原始输出留在 `~/.cache/paper-master/mineru-output/`（持久化，不自动清理）。batch 分三阶段（MinerU 解析 → BGE-M3 编码 → Memory 抽取）
7. **图片加载**：ContentBlock.image_bytes 懒加载，仅 LLM 需要时才读文件
8. **暂不引入 LangChain/LangGraph**：当前是简单流水线。后续 Agent 框架再评估，在此之前的工具化用纯函数接口
9. **旧 parser.py 保留不动**，mineru_parser.py 是主要解析路径
10. **Paper Memory**：论文理解不止依赖 chunk embedding，LLM 一次性抽取 10 个结构化字段（研究问题、动机、方法、实验、局限、关键词等），存入独立缓存。当前单论文直接注入 system prompt，后续多论文时改造为 Agent 工具按需调用。关键词留作多论文路由筛选
11. **Tool Result 压缩**：不增加额外 API 调用，利用 LLM 同一轮的多工具调用能力（record_observation + search_paper 在同一个 tool_calls 里发出）。保留最近 `KEEP_RECENT_ROUNDS=3` 轮完整（保证模型能回读证据，避免"证据被压后反复重搜"），更早的替换为 observation 摘要，无 observation 时降级为智能截断。压缩阈值必须严格保证"工具结果在第一次被模型读到前完整"（曾有 off-by-one bug）
12. **三层记忆架构**：L1 Conversation Memory（messages，最新轮完整，往轮压缩）、L2 Observation Memory（结构化观察，`self._observations`，注入 system prompt）、L3 Evidence Memory（来源追溯，Observation.sources 字段已就绪，P3 完善）

## 常用命令

```bash
cd /home/xiejiezhen/paper-master
source .venv/bin/activate

python3 main.py paper.pdf                     # 单篇阅读
python3 main.py --batch papers/               # 批量预热
python3 main.py --zotero                 # 从 Zotero 库选论文阅读
uvicorn paper_reader.server:app          # FastAPI（Zotero 检索接口）
python3 -m pytest tests/ -v                   # 测试 (178)
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
