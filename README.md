# Paper Master

基于 LLM 的 PDF 论文阅读助手。打开论文，像聊天一样提问，AI 帮你理解文章内容。

## 特性

- **论文概览** — 打开 PDF 自动展示摘要和章节目录，快速判断论文价值
- **按需深读** — 提问时自动定位到对应章节，只加载相关内容，省 token
- **图表理解** — 图片和表格交给多模态模型，文字交给文本模型，效果好还省钱
- **多后端支持** — 支持 Anthropic（Claude）和 OpenAI（GPT-4o 等），配置切换
- **对话模式** — 交互式问答，像跟人讨论论文一样自然

## 环境要求

- Python 3.10+
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
  text:              # 处理文字的模型
    provider: anthropic
    model: claude-sonnet-4-6
  vision:            # 处理图片/图表的模型
    provider: openai
    model: gpt-4o

api_keys:
  anthropic: "sk-ant-xxxxxxxxxxxx"
  openai: "sk-xxxxxxxxxxxxxxxx"
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
  ├── PyMuPDF 提取文字、图片、表格
  ├── 识别章节结构（目录/字体）
  │
  ▼
展示概览（摘要 + 目录）
  │
  ▼
用户提问："第 3 节的方法是什么？"
  │
  ├── 定位到第 3 节
  ├── 提取该节的文字 → 发给文本模型
  ├── 提取该节的图表 → 发给多模态模型
  │
  ▼
合并回答，展示给用户
```

## 项目结构

```
paper-master/
├── main.py                  # CLI 入口
├── config.example.yaml      # 配置模板
├── requirements.txt         # 依赖
├── paper_reader/
│   ├── parser.py            # PDF 解析（文字/图片/章节）
│   ├── llm.py               # LLM 客户端 + 路由
│   └── context.py           # 对话上下文管理
└── tests/                   # 测试（32 个）
```

## 路线图

- [x] PDF 文本和图片提取
- [x] 章节自动识别
- [x] 结构概览 + 按需深读
- [x] 多模态图表理解
- [x] 多 LLM 后端支持
- [ ] RAG 多论文检索
- [ ] Web 界面
- [ ] 多论文对比

## License

MIT
