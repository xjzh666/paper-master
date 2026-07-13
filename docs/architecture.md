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
  ├── TF-IDF 检索 top-3 相关语义块
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
  合并规则: 标题断开 | 512 tokens 截断 | 64 tokens 重叠
  图片挂载到所在位置

PaperDocument
  blocks: list[ContentBlock]
  chunks: list[SemanticChunk]
```

## 检索策略

双路互补：

1. **TF-IDF chunk 检索**（主路径）— 对所有 SemanticChunk 建 TF-IDF 索引，用户提问 → top-3 → 窗口扩展 → 发 LLM
2. **章节查找**（辅助）— 用户明确说 "section 2.1" → 直接定位章节范围

## 项目结构

```
paper-master/
├── main.py                  # CLI 入口，交互循环
├── config.example.yaml      # 配置模板
├── requirements.txt         # 依赖
├── paper_reader/
│   ├── blocks.py            # 数据模型（ContentBlock / SemanticChunk / PaperDocument）
│   ├── mineru_parser.py     # MinerU 解析器 + sha256 缓存
│   ├── parser.py            # PyMuPDF 解析器（旧，保留）
│   ├── llm.py               # LLM 客户端（Anthropic/OpenAI）+ 路由
│   └── context.py           # 对话上下文 + TF-IDF 检索 + 窗口构建
└── tests/                   # 测试（67 个）
```

## 模型路由

- 窗口内有图片/表格 → Vision 模型
- 纯文字 → Text 模型
- 两个模型独立配置（provider / api_key / base_url）

## 缓存

- 路径: `~/.cache/paper-master/{sha256(pdf)}.json`
- PDF 内容 hash 作为 key，相同文件只解析一次
- `--batch` 命令可提前预热所有论文的缓存

## 路线图

- [x] PDF 解析（PyMuPDF → MinerU）
- [x] 版面级数据模型
- [x] 语义块合并 + TF-IDF 检索
- [x] 多模态路由
- [x] 多 LLM 后端
- [x] 批量预热
- [ ] RAG 向量语义检索
- [ ] 多论文对比
- [ ] PaperKnowledge 结构化抽取
