# Paper Master

基于 LLM 的 PDF 论文阅读助手。打开论文，像聊天一样提问，AI 帮你理解文章内容。支持自动抽取论文结构化认知（研究问题、方法、贡献等），RAG 检索与论文全局理解互补。

## 环境要求

- Python 3.10+
- CUDA GPU（MinerU VLM 推理需要，例如 RTX 3060 6GB 以上）
- OpenAI 或 Anthropic API Key

## 安装

```bash
git clone https://github.com/xjzh666/paper-master.git
cd paper-master
pip install -r requirements.txt
```

## 配置

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，填入 API Key：

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

支持的 provider：`anthropic`、`openai`。text 和 vision 可以用同一个 provider。

## 使用

### 单篇阅读

```bash
python3 main.py paper.pdf
```

打开后自动展示摘要和目录，直接提问：

```
> 这篇论文的核心贡献是什么？
> 第 3.2 节的方法是怎么实现的？
> 实验用的什么数据集？
> Figure 1 展示了什么？
```

### 批量预热

```bash
python3 main.py --batch papers/
```

遍历目录下所有 PDF，预先解析并缓存。之后单篇打开秒加载。

### 命令

| 命令 | 说明 |
|------|------|
| `/help` | 帮助 |
| `/overview` | 重新显示概览 |
| `/sections` | 列出所有章节 |
| `/quit` | 退出 |

## License

MIT
