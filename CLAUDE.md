# CLAUDE.md — Paper Master 项目接手文档

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
  ├── mineru_parser.py   # MinerU 解析器 + sha256 缓存
  ├── memory.py          # Paper Memory 抽取 + 缓存读写
  ├── parser.py          # PyMuPDF 解析器（旧，保留不用）
  ├── llm.py             # LLM 客户端 + 路由 + 配置加载
  └── context.py         # 对话上下文 + BGE-M3 向量检索 + 窗口构建
tests/                   # 91 个测试，全过
config.example.yaml      # 配置模板（提交）
config.yaml              # 实际配置（gitignore）
.venv/                   # 虚拟环境（gitignore）
papers/                  # 测试用 PDF 论文（gitignore）
```

### 当前数据流（Pipeline 模式，后续将演进为 Agent + 工具模式）

```
PDF → MinerU CLI (VLM 版面分析) → content_list_v2.json + images/ + .md
  → MinerUParser → ContentBlock[] → merge_blocks() → SemanticChunk[]
  → PaperDocument → sha256 缓存到 ~/.cache/paper-master/
  → ConversationContext → BGE-M3 编码 → 1024-d dense vectors + sparse lexical weights
  → Paper Memory 抽取 → 读 .md → LLM 结构化 JSON → {sha256}-memory.json
  → 用户提问 → BGE-M3 混合检索（dense + sparse）→ top-3 → 窗口扩展
  → LLMRouter.answer(text, images, question, history, title, memory) → 中文回答
  → 有图片走 vision 模型，纯文字走 text 模型（带 `[路由: xxx]` 日志）
```

### 目标架构（Agent + 工具模式）

```
用户问题
  │
  ├── Query Router（规则：图/表/章节引用 → 精确匹配，开放问题 → 语义检索）
  │
  └── Agent 决策调用哪些工具
        ├── RAG 检索工具（search_paper / search_literature）
        ├── Paper Memory（论文结构化理解：Problem/Method/Contribution/...）
        ├── 精确引用匹配（aliases / section_path）
        └── （未来）文献搜索、代码实验、总结写作...
```

### 数据模型（四层）

```
ContentBlock          — 版面元素，1:1 映射 MinerU 输出
  type: text | image | table | formula
  level: 0=正文, 1=一级标题, 2=二级标题...
  page_idx, bbox, image_path, image_bytes

SemanticChunk         — 语义单元，合并 ~512 tokens，64 tokens 重叠
  合并规则: 遇标题断开 | 512 tokens 截断 | 图片挂载

PaperMemory           — 结构化论文理解，LLM 一次性抽取
  research_problem, motivation, method, method_why, experiments,
  key_results, contributions, limitations, takeaways, keywords

PaperDocument
  blocks: list[ContentBlock]   chunks: list[SemanticChunk]
  memory: PaperMemory | None
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
- [x] **全中文**：系统提示词、UI 提示、LLM 回答均为中文
- [x] **MinerU v1/v2 格式兼容**（content_list.json 平铺格式 + content_list_v2.json 分页嵌套格式）
- [x] 配置文件：每个模型独立配 api_key、base_url、provider
- [x] **Paper Memory 结构化理解** — LLM 抽取论文的研究问题、方法、贡献等 10 个字段，独立缓存 `{sha256}-memory.json`，注入对话 system prompt
- [x] 91 个测试全覆盖（单元 + 集成，含 embedding mock）
- [x] 中文 README + docs/architecture.md

## 进行中

（无）

## 下一步优先级

核心转向：从"更好的论文问答 RAG" → "能理解论文、查论文、思考 idea 的科研 Agent"。

不再把检索做得更精细，而是让 Agent 真正理解论文内容，能跨章节推理。

### P0：RAG 工具化

将检索能力从 pipeline 中解耦为独立接口，让 Agent 决定什么时候调用 RAG，而不是每个问题固定走检索。

- [ ] `search_paper(query, scope="current")` — 单论文内检索
- [ ] 交互循环中 Agent 自主判断是否需要检索（而非每问必查）

### P1：Paper Memory（论文结构化理解）✅ 已完成

读完论文后形成结构化认识，不依赖 chunk embedding 做跨章节推理。

- [x] Paper Memory 数据结构（Research Problem, Motivation, Method, Experiment, Limitation, Contribution...）
- [x] LLM 驱动的论文结构化抽取（一次解析，存入缓存 `{sha256}-memory.json`）
- [x] 对话中注入 system prompt，RAG 检索 + Memory 全局理解互补
- [ ] 后续：让检索能按语义 section 过滤（"找实验结果"而非"找相似文本"）

### P2：Query Router

区分问题类型，不同问题走不同检索路径。第一阶段用规则，不引入 LLM 分类。

- [ ] 规则路由：图/表/章节引用 → aliases 精确匹配（已具备 aliases 数据）
- [ ] 规则路由：开放理解问题 → 语义检索
- [ ] 规则路由：比较/综述类问题 → 后续多论文能力支撑

### P3：后续扩展

- [ ] 多轮对话 query rewriting（代词和省略会降低检索精度）
- [ ] 图片内容理解（图片做 VLM 描述纳入 Paper Memory）
- [ ] 引用溯源（回答标注来源 chunk / page_idx / 章节）
- [ ] 多论文对比（/load + /compare）
- [ ] AnthropicClient 的 base_url 支持（目前只有 OpenAI 格式支持 base_url）

## 用户当前配置

用户使用两个不同的模型（config.yaml）:
- text: deepseek-v4-pro @ api.deepseek.com
- vision: qwen3.5-plus @ dashscope.aliyuncs.com

两者都用 OpenAI 兼容格式（provider: openai）。

## 关键设计决策

1. **PDF 解析**：MinerU CLI（`mineru -p file -o dir -m auto`）的子进程调用，自动启停本地 API 服务，输出 content_list_v2.json
2. **检索策略**：BGE-M3 混合检索（dense + sparse）。dense 覆盖语义匹配，sparse 覆盖术语精确匹配。numpy 暴力 cosine similarity，无外部向量数据库。alises + 标准化标签（Roman→Arabic + 中文）辅助精确引用
3. **RAG 定位**：RAG 应作为 Agent 可调用的工具，而非整个系统的核心流程。Agent 决定什么时候需要检索，不强制每轮走 RAG
4. **路由规则**：检索窗口中包含图片/表格 → vision 模型；纯文字 → text 模型。路由日志 `[路由: vision/text]` 开箱可见。未来 Query Router 将区分定位/理解/比较三类问题
5. **系统提示词**：两个模型共用一个中文 SYSTEM_PROMPT
6. **缓存策略**：PDF 内容 sha256 → `~/.cache/paper-master/{hash}.json`（含 blocks + chunks + embeddings + lexical_weights + aliases）+ `{hash}-memory.json`（Paper Memory，独立文件用于生命周期解耦）。MinerU 原始输出留在 `/tmp/mineru-output/`（不自动清理）。batch 分三阶段（MinerU 解析 → BGE-M3 编码 → Memory 抽取）
7. **图片加载**：ContentBlock.image_bytes 懒加载，仅 LLM 需要时才读文件
8. **暂不引入 LangChain/LangGraph**：当前是简单流水线。后续 Agent 框架再评估，在此之前的工具化用纯函数接口
9. **旧 parser.py 保留不动**，mineru_parser.py 是主要解析路径
10. **Paper Memory**：论文理解不止依赖 chunk embedding，LLM 一次性抽取 10 个结构化字段（研究问题、动机、方法、实验、局限、关键词等），存入独立缓存。当前单论文直接注入 system prompt，后续多论文时改造为 Agent 工具按需调用。关键词留作多论文路由筛选

## 常用命令

```bash
cd /home/xiejiezhen/paper-master
source .venv/bin/activate

python3 main.py paper.pdf                     # 单篇阅读
python3 main.py --batch papers/               # 批量预热
python3 -m pytest tests/ -v                   # 测试 (91)
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
