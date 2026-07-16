# Paper Memory — Design Spec

## Overview

让 Agent 对单篇论文形成结构化认知（研究问题、方法、贡献等），不再只依赖 chunk embedding 的碎片化检索。Memory 在解析时由 LLM 一次性抽取，存入缓存，对话中作为背景知识注入 system prompt。后续多论文场景下改造为工具，Agent 按需调用。

## 核心原则

- **Memory 补充 RAG，不替代 RAG**：RAG 负责"找到相关段落"，Memory 负责"理解论文全貌"
- **当前简单，后续可演进**：单论文直接注入 system prompt，接口预留工具化空间
- **一次抽取，缓存复用**：LLM 调用只在解析时发生一次

## Data Structure

```python
@dataclass
class PaperMemory:
    research_problem: str      # 论文试图解决什么问题？
    motivation: str            # 为什么这个问题重要？现有方法有什么不足？
    method: str                # 核心方法/算法是什么？
    method_why: str            # 方法为什么有效？关键设计选择的原因
    experiments: str           # 实验设计、数据集、baseline、关键指标
    key_results: str           # 主要实验结果和发现
    contributions: str         # 核心贡献（通常 3-4 点）
    limitations: str           # 方法局限、未解决的问题
    takeaways: str             # 2-3 句话总结，帮助 Agent 快速判断论文相关性
    keywords: list[str]        # 5-8 个英文术语，覆盖方法/领域/任务维度
```

### 字段设计说明

- `method` 和 `method_why` 分开：对比论文时不仅要知道"方法是什么"，还要知道"为什么这样设计"
- `experiments` 和 `key_results` 分开：实验设置和结论是两个不同的检索需求
- `takeaways`：快速摘要，Agent 判断"这篇论文和用户问题相关吗"时使用
- `keywords`：英文术语，多论文场景下用于筛选和路由

### 挂载位置

```python
# paper_reader/blocks.py — PaperDocument 新增字段
memory: PaperMemory | None = None
```

## 存储

### 文件路径

```
~/.cache/paper-master/{sha256}.json        # MinerU 结果（已存在）
~/.cache/paper-master/{sha256}-memory.json # Paper Memory（新增）
```

### 选择独立文件的理由

- 生命周期解耦：Memory 升级提示词或重抽取不需要重写 chunk 缓存
- 职责分离：MinerU 是 VLM 版面解析，Memory 是 LLM 文本理解
- 通过 sha256 自然关联，无需额外字段

### 格式

```json
{
  "sha256": "abc123...",
  "memory": {
    "research_problem": "...",
    "motivation": "...",
    "method": "...",
    "method_why": "...",
    "experiments": "...",
    "key_results": "...",
    "contributions": "...",
    "limitations": "...",
    "takeaways": "...",
    "keywords": ["code-repair", "tree-of-thought", "llm-agent"]
  }
}
```

带 sha256 自校验，防止文件损坏或关联错乱。

## 抽取流程

### 输入源

使用 MinerU 生成的 `.md` 文件作为 LLM 输入。理由：
- `.md` 无文本重叠（chunk 有 64-token 重叠，拼接有冗余）
- 保留标题层级和文档结构
- 文本量适中（一篇论文约 8k-15k token）

如果 `.md` 文件不存在，回退到 `paper.blocks` 按顺序取 text（也无重叠，但缺乏文档结构信息）。

### 模型

使用用户配置的 text 模型（deepseek-v4-pro）。一次 LLM 调用，输入约 8k-15k token，输出约 1k token。

### 触发时机

解析时自动执行，与 batch 流程保持一致：

```
Phase 1: MinerU 解析 (VLM, GPU)
Phase 2: BGE-M3 编码 (GPU)
Phase 3: Paper Memory 抽取 (LLM API)    ← 新增
```

### 提示词

系统提示词要求：
- 结构化 JSON 输出
- 每个字段 2-5 句中文
- 论文中未提及的字段写"未提及"
- 关键词用英文，5-8 个，覆盖方法/领域/任务

用户提示词：论文全文（`.md` 内容）。

## 对话中使用

### 当前阶段：单论文直接注入

`LLMRouter.answer()` 新增 `memory: PaperMemory | None = None` 参数。有 memory 时，序列化后追加到 system prompt 末尾，作为论文背景知识。

```
[System]
你是科研助手...

[当前论文记忆]
- 研究问题: ...
- 核心方法: ...
- 主要贡献: ...
```

### 后续演进：工具化接口

预留方向而非本次实现：

- `get_paper_memory(paper_id: str) -> PaperMemory` — 按需获取单篇 memory
- `list_paper_keywords() -> dict[str, list[str]]` — 列出所有已加载论文的关键词
- `compare_papers(ids: list[str]) -> str` — 对比指定论文的 memory

Agent 决策流程：用户问题 → 匹配关键词筛选候选论文 → 决定调哪些 paper 的 memory → 对比分析。

## 集成点

### 新增文件

| 文件 | 说明 |
|------|------|
| `paper_reader/memory.py` | `extract_memory()` + 缓存读写 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `paper_reader/blocks.py` | 新增 `PaperMemory` dataclass；`PaperDocument` 加 `memory` 字段 |
| `paper_reader/llm.py` | `LLMRouter.answer()` 加 `memory` 参数，注入 system prompt |
| `main.py` | `interactive_loop` 和 `batch_parse` 加 Phase 3 memory 抽取 |
| `paper_reader/mineru_parser.py` | 新增 `_load_markdown()` 方法 |

### 测试

- `tests/test_memory.py`：mock LLM 响应，测试 extract/缓存/反序列化
- 现有 65 个测试保持通过

## Non-Goals

- 不做多论文对比（后续阶段）
- 不做 memory 工具化（预留接口，不实现工具调用循环）
- 不做关键词路由/聚类（当前单论文用不上）
- 不修改 MinerU 解析逻辑
- 不引入新的模型配置
