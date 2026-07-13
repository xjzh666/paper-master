# MinerU Integration — Design Spec

## Overview

将 PDF 解析从 PyMuPDF 切换到 MinerU，重新设计数据模型以利用 MinerU 的 block 级版面解析能力，为后续 RAG 和多论文分析铺路。

## Architecture

```
PDF → MinerU CLI → content_list.json + images/
                         │
                         ▼
                  MinerUParser
                         │
                         ▼
              ┌─ ContentBlock[] ──────────┐
              │  type, text, level,       │
              │  bbox, page_idx, image    │
              └────────┬──────────────────┘
                       │ merge()
                       ▼
              ┌─ SemanticChunk[] ─────────┐
              │  合并 text blocks         │
              │  ~512 tokens + 64 重叠    │
              │  章节边界断开             │
              │  图片作为附属挂载         │
              └────────┬──────────────────┘
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
   PaperDocument              Phase 2: VectorIndex
   (对话用)                   (RAG 用)
```

## Data Model

### ContentBlock — 版面解析层

```python
@dataclass
class ContentBlock:
    type: str                      # "text" | "image" | "table" | "formula"
    text: str                      # 文本 / LaTeX / 表格 markdown
    level: int                     # 0=正文, 1=一级标题, 2=二级标题...
    page_idx: int
    bbox: tuple[float, float, float, float]
    image_path: str | None         # MinerU 输出目录下的相对路径
    image_bytes: bytes | None      # 懒加载
    children: list[ContentBlock]   # 嵌套（表格单元格等）
```

职责：保留 MinerU 原始解析结果，不做语义加工。用于溯源定位。

### SemanticChunk — 语义检索层

```python
@dataclass
class SemanticChunk:
    chunk_id: str
    text: str                      # 合并后文本，~512 tokens
    blocks: list[ContentBlock]     # 来源 block 引用
    section_path: list[str]        # 所属章节路径
    images: list[ContentBlock]     # 关联图片
    embedding: list[float] | None  # Phase 2，懒计算
```

### 合并算法

遍历 ContentBlock 列表：
- image/table block → 追加到当前 chunk.images
- level > 0（标题）→ 截断当前 chunk，开启新 chunk
- 连续 text block → 拼接，token 数达到 480 时截断
- 下一个 chunk 从前一个 chunk 末尾 64 token 开始（滑动重叠）

### 合并算法详情

```
输入: blocks: list[ContentBlock]
输出: list[SemanticChunk]

current_text = ""
current_blocks = []
current_images = []
current_path = []
chunks = []

for block in blocks:
    if block.level > 0:
        if current_text:
            chunks.append(SemanticChunk(...))
        current_text = ""
        current_blocks = []
        current_images = []
        update current_path with block.text at block.level
        current_blocks.append(block)
        current_text = block.text
    elif block.type == "image" or block.type == "table":
        current_images.append(block)
        current_blocks.append(block)
    else:  # text block
        if token_count(current_text + block.text) > 480:
            chunks.append(SemanticChunk(text=current_text, ...))
            overlap = last_64_tokens(current_text)
            current_text = overlap + block.text
            current_blocks = [blocks near overlap] + [block]
            current_images = []
        else:
            current_text += block.text
            current_blocks.append(block)

if current_text:
    chunks.append(SemanticChunk(...))
```

### PaperDocument

```python
@dataclass
class PaperDocument:
    filepath: str
    title: str
    abstract: str
    blocks: list[ContentBlock]
    chunks: list[SemanticChunk]
    metadata: dict    # {authors, year, venue}
```

## MinerUParser

### 调用方式

```python
class MinerUParser:
    def parse(self, pdf_path: str, output_dir: str = "/tmp/mineru-output") -> PaperDocument:
```

- 子进程调用 `mineru -p pdf_path -o output_dir -m auto`
- 优先读取 `content_list_v2.json`，回退到 `content_list.json`
- 从 markdown 提取 title（首个 `#` 标题）和 abstract

### 映射

| MinerU 字段 | ContentBlock 字段 |
|-------------|-------------------|
| `type` | `type` |
| `text` | `text` |
| `text_level` | `level` |
| `bbox` | `bbox` |
| `page_idx` | `page_idx` |
| `img_path` | `image_path`（拼接 output_dir 前缀） |

### 缓存

- 路径: `~/.cache/paper-master/{sha256(pdf_content)}.json`
- 序列化整个 PaperDocument（不含 image_bytes）
- 检查: pdf hash 命中 → 直接加载，跳过 MinerU

### 图片加载

- ContentBlock.image_bytes 初始为 None
- 调用 `block.load_image()` 时按 `image_path` 读取
- LLM 需要时才加载，避免内存膨胀

## Phase 1: Core Pipeline

### 检索

双路检索，互补使用：

**1. TF-IDF chunk 检索（主路径）**
- 对 paper.chunks 的 text 字段建 TF-IDF 索引（`sklearn.feature_extraction.text.TfidfVectorizer`）
- 用户提问 → TF-IDF 打分 → 取 top-3 相关 chunk
- 每个 chunk 扩展前后 2 个兄弟 chunk（上下文窗口）
- 合并窗口内 text + images → 构建 prompt → 发 LLM

**2. 章节查找（辅助）**
- 用户明确引用章节号→ find_section() 直接定位
- 逻辑：匹配 level>0 的 ContentBlock.text，找到章节起始位置，取该章节范围内所有 blocks

### Prompt 构建

```python
def build_prompt(title, chunks, question):
    text = ""
    images = []
    for c in chunks:
        text += c.text + "\n"
        for img in c.images:
            images.append(img)
            text += f"[Image {len(images)}]\n"

    return f"""Section from "{title}":

{text}

Question: {question}

Answer based on the content above. If not found, say so."""
```

### 路由规则（不变）

窗口内有图片 → vision 模型，纯文字 → text 模型。

### 不改的部分

- `llm.py`: LLMClient / LLMRouter 接口不变，内部适配 block 模型
- `main.py`: CLI 交互循环不变
- `config.yaml` 格式不变
- `SYSTEM_PROMPT` 不变

### 保留文件

- `parser.py` — 保留不动，未来场景可能不需要 MinerU

## Phase 2: Vector RAG

（本次不实现）

- 用 text 模型的 API 或本地 embedding 模型为每个 SemanticChunk 生成向量
- ChromaDB 存储向量 + 元数据
- 语义检索替代 TF-IDF
- 跨 chunk 的上下文扩展
- 引用溯源：回答中标注来源 chunk / page_idx

## Phase 3: Multi-Paper & Knowledge

（本次不实现）

- `MultiPaperSession`: 管理多篇论文的向量索引
- `/load`, `/compare`, `/summarize` 命令
- PaperKnowledge: LLM 离线抽取 Problem/Method/Contribution 等结构化字段
- 论文推荐

## Files Changed

| 文件 | 操作 | 说明 |
|------|------|------|
| `paper_reader/blocks.py` | 新增 | ContentBlock, SemanticChunk, PaperDocument |
| `paper_reader/mineru_parser.py` | 新增 | MinerUParser, chunk 合并, 缓存 |
| `paper_reader/context.py` | 修改 | 适配 block 模型, TF-IDF 检索, 窗口构建 |
| `paper_reader/llm.py` | 微调 | prompt 构建适配 block 模型 |
| `main.py` | 微调 | 适配新 PaperDocument |
| `requirements.txt` | 修改 | 加 scikit-learn |

## Non-Goals

- 不用 LangChain / LlamaIndex 等框架
- 不引入数据库（Phase 2 的 ChromaDB 除外）
- PaperKnowledge 结构化抽取延后
- 旧的 PyMuPDF parser.py 保留不动
