# Paper Master

基于 LLM 的 PDF 论文阅读助手。打开论文，像聊天一样提问，AI 帮你理解文章内容。

## 特性

- **论文概览** — 打开 PDF 自动展示摘要和章节目录，快速判断论文价值
- **精准检索** — 提问时 TF-IDF 定位相关语义块，窗口上下文扩展，精准又省 token
- **图表理解** — 图片和表格交给多模态模型，文字交给文本模型，效果好还省钱
- **多后端支持** — 支持 Anthropic（Claude）和 OpenAI（GPT-4o 等），配置切换
- **对话模式** — 交互式问答，像跟人讨论论文一样自然

## 环境要求

- Python 3.10+
- CUDA GPU（MinerU VLM 推理需要，例如 RTX 3060 6GB 以上）
- Anthropic API Key 或 OpenAI API Key（至少一个）

## 安装

```bash
git clone https://github.com/xjzh666/paper-master.git
cd paper-master
pip install -r requirements.txt
```

## 配置

复制并编辑配置文件：

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，填入你的 API Key：

```yaml
models:
  text:                       # 处理文字的模型
    provider: openai
    model: gpt-4o-mini
    api_key: "sk-your-api-key"
    # base_url: "https://your-endpoint/v1"  # 可选，第三方 API
  vision:                     # 处理图片/图表的模型
    provider: openai
    model: gpt-4o
    api_key: "sk-your-api-key"
    # base_url: "https://your-endpoint/v1"
```

**支持的 provider：** `anthropic`、`openai`

**text 和 vision 可以用同一个 provider**，比如都用 OpenAI：

```yaml
models:
  text:
    provider: openai
    model: gpt-4o-mini      # 文字用便宜的模型
  vision:
    provider: openai
    model: gpt-4o           # 图表用能看图的模型
```

## 使用

### 基础用法

```bash
python3 main.py paper.pdf
```

打开后会自动展示论文摘要和目录结构：

```
============================================================
Paper: Attention Is All You Need

Abstract: The dominant sequence transduction models are based on...

Sections:
  1. Introduction
  2. Background
  3. Model Architecture
    3.1 Encoder and Decoder Stacks
    3.2 Attention
    3.3 Position-wise Feed-Forward Networks
  4. Why Self-Attention
  5. Training
  6. Results
  7. Conclusion
============================================================

You can ask questions about any section. Type /help for commands, /quit to exit.

>
```

### 提问示例

```bash
> 这篇论文的核心贡献是什么？
> 第 3.2 节的自注意力机制是怎么算的？
> 实验用的什么数据集？
> Figure 1 展示了什么？
```

### 命令列表

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/overview` | 重新显示论文概览 |
| `/sections` | 列出所有章节 |
| `/quit` | 退出程序 |

## 工作原理

```
打开 PDF
  │
  ├── MinerU 版面分析 + VLM 模型（Qwen2VL）
  ├── 识别章节层级、公式、表格、图片
  ├── 合并语义块（SemanticChunk）
  │
  ▼
展示概览（摘要 + 目录）
  │
  ▼
用户提问
  │
  ├── TF-IDF 检索相关语义块
  ├── 窗口上下文扩展（前后相邻块）
  ├── 有图片 → Vision 模型，纯文字 → Text 模型
  │
  ▼
返回回答
```

### 为什么用 MinerU？

相比直接读 PDF 内嵌文本（PyMuPDF），MinerU 用 VLM 模型「看」整个页面，能理解双栏布局、公式转 LaTeX、表格结构化、阅读顺序重建，解析质量远超传统方案。代价是需要 GPU 推理，每次解析约 1-2 分钟。

## 项目结构

```
paper-master/
├── main.py                  # CLI 入口
├── config.example.yaml      # 配置模板
├── requirements.txt         # 依赖
├── paper_reader/
│   ├── blocks.py            # 数据模型（ContentBlock / SemanticChunk）
│   ├── mineru_parser.py     # MinerU 解析器 + 缓存
│   ├── parser.py            # PyMuPDF 解析器（旧，保留）
│   ├── llm.py               # LLM 客户端 + 路由
│   └── context.py           # 对话上下文 + TF-IDF 检索
└── tests/                   # 测试（65 个）
```

## 路线图

- [x] PDF 文本和图片提取
- [x] 章节自动识别
- [x] MinerU 版面解析（VLM + 公式 + 表格 + 阅读顺序）
- [x] 语义块合并 + TF-IDF 检索
- [x] 结构概览 + 按需深读
- [x] 多模态图表理解
- [x] 多 LLM 后端支持
- [ ] RAG 向量语义检索
- [ ] 多论文对比
- [ ] PaperKnowledge 结构化知识抽取

## License

MIT
