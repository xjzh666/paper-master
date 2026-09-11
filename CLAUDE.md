# CLAUDE.md — Paper Master 项目接手文档

## 文档维护约定（重要）

**每次代码修改完成后、确认一个功能做好后，都必须同步更新相关文档**（架构、路线图、测试数、数据模型、设计决策等受影响部分），并随改动一起提交。文档落后于代码视为缺陷。

文档分工（单一真源，防漂移）：
- `CLAUDE.md`（本文件）— 当前状态 + 活跃路线图 + 索引。**路线图的唯一真源。**
- `docs/architecture.md` — 架构详情：数据流、SSE 协议、数据模型、子系统注意事项、数学渲染流水线。
- `docs/decisions.md` — 关键设计决策全文（编号稳定，别处以 #N 引用）。
- `docs/history.md` — 已完成条目完整清单（新完成的条目在此追加，本文件只留一行摘要）。

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
main.py                  # CLI 入口，交互循环 + 批量解析 + --zotero
paper_reader/
  ├── blocks.py          # 数据模型（ContentBlock / SemanticChunk / PaperMemory / PaperDocument）
  ├── agent.py           # Agent 循环 + 工具 + 压缩 + Session Observation + run_stream()
  ├── mineru_parser.py   # MinerU 解析器 + sha256 缓存
  ├── memory.py          # Paper Memory 抽取 + 缓存读写
  ├── observations.py    # Observation + 图像描述缓存读写
  ├── parser.py          # PyMuPDF 解析器（旧，保留不用）
  ├── llm.py             # LLM 客户端 + 路由 + 配置加载
  ├── context.py         # 对话上下文 + BGE-M3 混合检索
  ├── zotero.py          # Zotero 只读数据层（collections/items/search/resolve_pdf）
  ├── papers.py          # Web 会话仓库：Session + 异步解析 + SSE 事件源 + chunks-index
  ├── latex_fix.py       # 公式 LaTeX 语义规范化（serve-time 应用）
  ├── math_quality.py    # 数学质量层：覆盖率 + OCR/污染检测（含 CLI）
  └── server.py          # FastAPI：/api/zotero/* + /api/papers/* + 前端静态托管
docs/
  ├── architecture.md    # 架构详情（数据流 / SSE 协议 / 数据模型 / 子系统 / 数学渲染）
  ├── decisions.md       # 关键设计决策全文（#1-#20）
  ├── history.md         # 已完成条目完整清单
  ├── deep-research-report.md          # 论文源 API 调研报告（15 源横评，2026-09）
  ├── openalex-deep-research-report.md # OpenAlex API 专项调研报告
  ├── superpowers/specs/ # 历史 spec 存档（superpowers 工作流时期）
  └── onegate/specs/     # 设计 spec 存档（现行，YYYY-MM-DD-<slug>.md）
frontend/                # Web 前端（React + TypeScript + Ant Design + Vite）
  ├── src/               # 三栏 App + citation.ts（引用定位）+ markdown/ 共享插件栈（详见 architecture.md）
  ├── scripts/           # math-coverage.mjs 公式覆盖率校验
  └── dist/              # 构建产物（npm run build 输出，server.py 静态托管）
tests/                   # 281 个 Python 测试 + 43 个前端 vitest，全过
config.example.yaml      # 配置模板（提交）
config.yaml              # 实际配置（gitignore）
.venv/                   # 虚拟环境（gitignore）
papers/                  # 测试用 PDF 论文（gitignore）
```

数据流（论文预处理 / Agent 循环 / Web 版 / SSE 事件协议）与数据模型的完整描述见 `docs/architecture.md`「工作原理」「数据模型」。遗留的简单路径 `LLMRouter.answer()` 仍可用，主路径是 PaperAgent。

## 已完成（摘要，详情见 docs/history.md）

- 早期基础设施：MinerU 解析 → 数据模型 → BGE-M3 混合检索 → sha256 缓存 → CLI / Zotero 对接
- [x] **P0：RAG 工具化** — Agent 循环 + search_paper / get_section / describe_image / record_observation
- [x] **P1：Paper Memory** — 10 字段结构化抽取，注入 system prompt
- [x] **P2：Tool Result 压缩** — 保留最近 3 轮完整 + observation 摘要压缩（含 off-by-one 修复）
- [x] **P3：引用溯源** — `[cite:chunk_N]` 链接 + 阅读区滚动高亮（决策 #18）
- [x] **P4：Web 应用 MVP** — 异步解析 + SSE 流式对话 + 历史持久化/恢复 + 数学渲染清洗 pipeline

## 进行中

- **P6：自主调研（新方向）** — Web 应用 MVP 已可用（列表→打开→解析→对话→阅读）；当前转向自主调研能力：外部论文搜索（P6.1）→ llmwiki 知识库（P6.2），见下一步优先级

## 下一步优先级

核心转向：从"更好的论文问答 RAG" → "能自主调研、多论文对比的科研 Agent"。

不再把检索做得更精细。自主调研的能力分解：**搜索**（拿得到论文，P6.1）+ **理解**（持久化研究记忆，P6.2）+ **对比**（跨论文综合，P6.2）。

### P4：Web 应用 ✅ MVP 已完成

把 paper-master 做成**本地 Web 应用**（类似 Zotero），浏览器访问 `localhost:8000` 单端口使用。（当时**暂缓"上网搜论文"**，现已作为 P6.1 提前，见 P6。）

**技术选型（约束仍有效）：**
- 形态：Web 应用（理由见决策 #13）；前端 React + TypeScript + Ant Design（Vite 构建）
- 后端 FastAPI（复用 `paper_reader/`）；PDF 阅读渲染 MinerU 结果（markdown + 章节 + 图片），不集成 pdf.js
- Zotero 只读；启动 `paper-web` 一键脚本（启动前置与坑见决策 #15）
- MVP 完成清单见 `docs/history.md`；遗留项「本地知识库：多论文统一索引」由 P6.2 实现

### P6：自主调研（新方向）

最终目标：Agent 能自主做调研、多论文对比。

#### P6.1 外部论文搜索（下一步优先）

摆脱 Zotero 本地库限制，按查询获取外部论文。**先做最小可用闭环：查询 → 结果列表 → 获取原文 PDF → 进入现有解析/阅读/对话流程**。选型已定（决策 #20）：arXiv 单源起步，OpenAlex 预留第二源（本期不接），Semantic Scholar 排除。设计 spec：`docs/onegate/specs/2026-09-11-external-paper-search.md`（待实现）。（此条反转早期"明确暂不做上网搜论文"的决策，理由：自主调研目标下本地库覆盖不了获取端。）

#### P6.2 llmwiki 知识库（P6.1 之后）

把 LLM Wiki 思想（Karpathy）融入项目，作为原"本地知识库：多论文统一索引"的架构方案。战略原则：

- Wiki 是持久化研究记忆，**不替代外部搜索**（与 P6.1 互补）
- 默认按研究问题**按需形成知识**，不做打开论文时的全量 ingest（Paper Memory 现状不变）
- **跨论文综合**（comparison/synthesis 页）在比较类问题、研究问题驱动下产生

参考资料（本地，未入库）：`docs/llm-wiki.md`（Karpathy 原文）、`docs/TencentDB-Agent-Memory-feat-server_team/`（服务端 wiki 引擎参考）、`docs/claude-obsidian-main/`（vault 事务与溯源参考）。具体机制（知识升格路径、页面 merge/锁定策略、schema 页面类型等）待独立 designing，不在路线图层绑定。

### P5：暂缓

以下功能暂缓：
- [ ] 多轮对话 query rewriting（代词和省略会降低检索精度）
- [ ] 检索语义 section 过滤（"找实验结果"而非"找相似文本"）
- [ ] 多论文对比（/load + /compare）— 由 P6.2（跨论文综合）覆盖
- [ ] AnthropicClient 的 base_url 支持

## 用户当前配置

用户使用两个不同的模型（config.yaml）:
- text: glm-5.3-flash @ 智谱 open.bigmodel.cn — **GLM Coding Plan 套餐**，base_url 必须用 Coding Plan 专用端点 `https://open.bigmodel.cn/api/coding/paas/v4`；通用端点 `/api/paas/v4` 只扣普通余额，会报 429 code 1113「余额不足或无可用资源包」。Coding Plan 也有 Anthropic 协议端点（`/api/anthropic`），但项目 AnthropicClient 尚不支持 base_url 与工具调用，未走此路径
- vision: qwen3.5-plus @ dashscope.aliyuncs.com

两者都用 OpenAI 兼容格式（provider: openai）。

## 关键设计决策（索引，全文见 docs/decisions.md）

1. **PDF 解析** — MinerU CLI 子进程调用
2. **检索策略** — BGE-M3 混合检索（dense+sparse），无外部向量库
3. **RAG 定位** — Agent 可调用的工具，非核心流程
4. **路由规则** — 图/表→vision，纯文字→text
5. **系统提示词** — 共用 SYSTEM_PROMPT；中文回答、英文工具参数
6. **缓存策略** — sha256 多文件缓存，生命周期解耦
7. **图片加载** — image_bytes 懒加载
8. **暂不引入 LangChain/LangGraph** — 纯函数接口工具化
9. **旧 parser.py 保留不动**
10. **Paper Memory** — 一次性 10 字段抽取，独立缓存
11. **Tool Result 压缩** — 同轮 record_observation，保留 3 轮完整
12. **三层记忆架构** — L1 对话 / L2 观察 / L3 证据
13. **桌面形态 Tauri → Web 应用**
14. **静态托管挂在 `/`** — API 路由优先，SPA 兜底
15. **`paper-web` 一键启动** — 两个启动前置（dist 构建 / check_same_thread）
16. **中间产物落盘原则** — 可重建的不存，不可重建的才存（2026-09-01）
17. **章节层级以编号深度为准** — find_section 有效层级计算
18. **P3 引用溯源：引用即文本** — cite:chunk_N 链接 + DOM 归一化匹配
19. **P6 方向：外部搜索先行、wiki 按需形成**（2026-09-10）
20. **P6.1 论文源选型：arXiv 起步，OpenAlex 预留，S2 排除**（2026-09-11）

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
