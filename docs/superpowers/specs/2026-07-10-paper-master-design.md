# Paper Master — Design Spec

## Overview

Paper Master 是一个 CLI 工具，读取 PDF 论文并进行智能对话。核心能力：PDF 文本/图片/表格提取 → LLM 理解 → 对话交互。

## Architecture

```
CLI (对话模式)
  └── 阅读控制器 (ReadingController)
        ├── PDF 解析器 (parser.py)    — 文本/图片/表格提取，章节分割
        ├── LLM 路由 (llm.py)         — 文本模型 + 多模态模型，按内容分发
        └── 上下文管理器 (context.py)  — 对话历史，章节索引，阅读深度
```

## 阅读流程

1. 打开 PDF → 提取摘要和章节结构 → 展示概览
2. 用户提问 → 定位章节 → 提取该章文字+图片 → 路由到对应模型 → 合并回答

## 核心模块

### PDF 解析器 (parser.py)
- PyMuPDF 提取文本、图片、表格
- 识别章节标题，按章节分割内容
- 图片/表格保留元数据（页码、坐标、所属章节）

### LLM 路由 (llm.py)
- 纯文本内容 → 文本模型
- 图片/表格 → 多模态模型
- 支持多后端: Anthropic, OpenAI
- 后端通过 config.yaml 配置

### 上下文管理 (context.py)
- 当前论文的章节索引
- 对话历史
- 阅读深度（摘要层 / 全文层）

### CLI (main.py)
- `python main.py paper.pdf` 进入交互对话
- 启动时展示摘要和目录
- 交互式问答循环

## 阅读策略

A+B 混合策略：
- 打开论文时先展示摘要 + 章节目录（论文地图）
- 用户提问时定位到对应章节，提取该章节的文本和图片发给模型
- 摘要/结论随时可查，细节按需加载

## 配置 (config.yaml)

```yaml
models:
  text:
    provider: anthropic
    model: claude-sonnet-4-6
  vision:
    provider: openai
    model: gpt-4o
```

## 项目命名

paper-master，开源项目，托管 GitHub。

## 技术选型

- 语言: Python 3.11+
- PDF 解析: PyMuPDF
- LLM API: httpx + 各 SDK
- 配置: PyYAML
