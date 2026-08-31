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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> 依赖安装在虚拟环境 `.venv` 中（包括 MinerU CLI）。**每次使用前必须先激活虚拟环境**，否则 `mineru` 命令找不到，解析 PDF 会报 `No such file or directory: 'mineru'`。

## 使用

> 所有 `python3 main.py` 命令都需在已激活的虚拟环境中运行：

```bash
cd /home/xiejiezhen/paper-master
source .venv/bin/activate
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

可选：配置 Zotero 数据目录（不配置则自动探测 `~/Zotero` 或 WSL2 下的 `/mnt/c/Users/*/Zotero`）：

```yaml
zotero:
  data_dir: ""   # Zotero 数据目录（zotero.sqlite 所在目录），留空自动探测
```

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

### 从 Zotero 库阅读

对接本机 Zotero 库，不用手动拷贝 PDF：

```bash
python3 main.py --zotero
```

直接输关键字搜索（标题/作者），或 `/collections` 浏览收藏夹树，输入序号打开论文进入对话（首次走 MinerU 解析，之后缓存秒开）。

### Zotero 检索接口（FastAPI）

```bash
uvicorn paper_reader.server:app
```

只读接口，供前端或模型 agent 复用：

| 接口 | 说明 |
|------|------|
| `GET /api/zotero/collections` | 收藏夹树 |
| `GET /api/zotero/items?collection_id=` | 条目列表 |
| `GET /api/zotero/search?q=` | 标题/作者搜索 |
| `GET /api/zotero/items/{id}` | 单条目详情 |

## Web 版（浏览器使用）

paper-master 现在是**本地 Web 应用**：浏览器访问 `localhost:8000`，在 Zotero 库里选论文 → 异步解析 → 阅读 markdown + SSE 流式对话。API 与前端单端口托管，无需分开起服务。

### 首次使用（一次性准备）

后端依赖已装在 `.venv`（含 MinerU）；前端需要另外构建一次，并创建一条一键启动命令：

```bash
# 1. 构建前端产物
cd frontend && npm install && npm run build
# 产物生成到 frontend/dist/，server.py 自动托管

# 2. 创建 paper-web 一键启动命令（任意目录可敲，无需参数）
cat > ~/.local/bin/paper-web <<'EOF'
#!/bin/bash
cd /home/xiejiezhen/paper-master
source .venv/bin/activate
( sleep 2; explorer.exe "http://localhost:8000" >/dev/null 2>&1 || true ) &
exec uvicorn paper_reader.server:app --host 127.0.0.1 --port 8000
EOF
chmod +x ~/.local/bin/paper-web
```

> 跳过第 1 步直接启动，浏览器会看到 `404 Not Found`（`frontend/dist/` 不存在时，server.py 按设计跳过静态托管）。

### 启动（每次使用）

在 WSL 终端里敲一条命令（自动激活 venv、起后端、打开浏览器）：

```bash
paper-web
```

- 无需参数，任意目录可敲；启动后自动打开浏览器访问 `http://localhost:8000`
- 停止：在终端按 `Ctrl+C`
- 端口被占用（上次没停干净）时，先 `pkill -f "uvicorn paper_reader.server"` 再启动

手动启动等同：

```bash
cd /home/xiejiezhen/paper-master
source .venv/bin/activate
uvicorn paper_reader.server:app --host 127.0.0.1 --port 8000
# 浏览器打开 http://localhost:8000
```

### 开发（前端热更新）

```bash
# 终端 1：先起后端
source .venv/bin/activate && uvicorn paper_reader.server:app

# 终端 2：前端 Vite HMR（默认 5173 端口，代理到 8000）
cd frontend && npm run dev
```

### Web 版功能

- 左栏：Zotero 收藏夹树 + 论文列表（搜索/按收藏夹筛选）
- 中间：SSE 流式对话（`tool_start` / `answer_chunk` 增量渲染）
- 右栏：MinerU 解析的 markdown 阅读区（章节 + 图片）
- 首次打开论文后台异步解析（MinerU），前端轮询 `/status` 到 `ready`

### 命令

| 命令 | 说明 |
|------|------|
| `/help` | 帮助 |
| `/overview` | 重新显示概览 |
| `/sections` | 列出所有章节 |
| `exit` / `/quit` | 退出 |

## License

MIT
