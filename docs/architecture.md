# Paper Master — 架构与设计

## 工作原理

```
打开 PDF
  │
  ├── MinerU 版面分析 + VLM 模型（Qwen2VL 1.2B）
  ├── 识别章节层级、公式、表格、图片、阅读顺序
  ├── ContentBlock（版面原样）→ SemanticChunk（语义合并，~512 tokens）
  │
  ▼
展示概览（摘要 + 目录）
  │
  ▼
用户提问
  │
  ├── BGE-M3 混合检索（dense + sparse）→ top-3 语义块
  ├── 窗口上下文扩展（前后 2 个相邻块）
  ├── 有图片 → Vision 模型，纯文字 → Text 模型
  │
  ▼
返回回答
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
  合并规则: 标题断开 | ~480 tokens 截断 | 64 tokens 重叠
  图片/表格 caption 注入标准化标签后写入 text

PaperDocument
  blocks: list[ContentBlock]
  chunks: list[SemanticChunk]
```

## 检索策略

**BGE-M3 混合检索**（0.5 dense + 0.5 sparse）：

1. **Dense 检索**（语义）— 1024 维向量 cosine similarity，跨语言语义匹配
2. **Sparse 检索**（词法）— BGE-M3 学习的 token 权重，类似升级版 BM25，精确术语匹配
3. **标准化标签** — 罗马数字 → 阿拉伯数字转换（TABLE I → Table 3），注入中文别名（图1、表2），sparse 分支可直接命中
4. **章节查找**（辅助）— 用户明确说 "section 2.1" → 直接定位章节范围

## 项目结构

```
paper-master/
├── main.py                  # CLI 入口，交互循环 + 两阶段批量
├── config.example.yaml      # 配置模板
├── requirements.txt         # 依赖
├── paper_reader/
│   ├── blocks.py            # 数据模型 + 标签标准化 + chunk 合并
│   ├── mineru_parser.py     # MinerU 解析器 + sha256 缓存
│   ├── parser.py            # PyMuPDF 解析器（旧，保留）
│   ├── llm.py               # LLM 客户端（Anthropic/OpenAI）+ 路由
│   └── context.py           # BGE-M3 混合检索 + 对话上下文 + 窗口构建
└── tests/                   # 测试（69 个）
```

## 模型路由

- 窗口内有图片/表格 → Vision 模型，带 `[路由: vision]` 日志
- 纯文字 → Text 模型，带 `[路由: text]` 日志
- 两个模型独立配置（provider / api_key / base_url）

## 缓存

- 路径: `~/.cache/paper-master/{sha256(pdf)}.json`
- PDF 内容 hash 作为 key，相同文件只解析一次
- JSON 包含完整 PaperDocument：blocks + chunks（含 embedding + lexical_weights + aliases）
- `--batch` 分两阶段：先 MinerU 解析所有 PDF，再 BGE-M3 编码所有缓存

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
- [x] BGE-M3 dense + sparse 混合检索
- [x] 标准化标签 + 中文别名
- [x] 多模态路由
- [x] 多 LLM 后端
- [x] 两阶段批量预热
- [ ] 显式引用路由（aliases 精确匹配优先于向量检索）
- [ ] 多论文对比
- [ ] PaperKnowledge 结构化抽取
