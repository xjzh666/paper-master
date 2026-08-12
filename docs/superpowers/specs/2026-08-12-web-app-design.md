# Web 应用（论文阅读 + 对话）设计

日期：2026-08-12
状态：已认可

## 背景与目标

paper-master 当前是纯 CLI（`main.py`）：Zotero 选论文 → MinerU 解析 → 对话。P4 目标是做"本地桌面应用"，原定 Tauri 外壳。经评估，**改为 Web 应用**：React 前端 + FastAPI 后端（WSL2），Windows 浏览器访问 `localhost`。原因是 GPU（MinerU/BGE-M3）和 Zotero 数据都在 WSL2，浏览器天然跨 Windows/WSL2 边界；Tauri 需要额外装 Rust + 系统依赖 + WSLg，且 Windows 目标构建痛苦，收益有限。

## 已确认决策

1. **形态**：Web 应用（非 Tauri）。React + TypeScript + Ant Design + Vite 前端；FastAPI 后端跑在 WSL2；Windows 浏览器直接访问。
2. **首次打开**：异步解析 + 进度轮询。点开未缓存论文 → 后台线程跑 MinerU → 前端轮询状态，完成后进阅读区。
3. **对话**：**SSE 真流式**。工具日志（`tool_start`/`tool_result`）实时推送，最终回答 token 级流式推送。
4. **MVP 范围**：单论文阅读 + 对话。多论文本地知识库放下一版。
5. **布局**：三栏。左=论文列表（收藏夹树+搜索+条目）｜ 中=对话 ｜ 右=markdown 阅读。
6. **阅读区**：直接渲染 MinerU 生成的 `.md` + 后端重写图片路径；TOC 从 markdown 标题生成锚点。blocks 结构化渲染后置。

## 架构

```
Windows 浏览器 ──localhost:8000──▶ FastAPI (WSL2)
                                  ├─ /api/zotero/*        (已有，不动)
                                  ├─ /api/papers/*        (新增)
                                  ├─ /                    (prod 托管 React 构建)
                                  └─ 复用 paper_reader/：MinerUParser /
                                     ConversationContext / PaperAgent /
                                     ZoteroLibrary / resolve_pdf
```

### Session 仓库（进程内）

```python
# 新增 paper_reader/sessions.py（或并入 server）
sessions: dict[str, Session] = {}   # key = paper_id (sha256 前 12 位)
class Session:
    ctx: ConversationContext        # 持有 history，跨对话轮次保留
    lock: threading.Lock            # 每论文串行，避免并发对话污染
parse_tasks: dict[str, dict]        # paper_id -> {status, message}
```

- 单用户本地，内存即可，无持久化。
- BGE-M3 是进程级单例且非线程安全：对话与编码用**全局锁**串行化（`CHAT_LOCK`）。单用户够用，不做更复杂并发。
- MinerU 解析也占 GPU 显存：解析任务用独立 `PARSE_LOCK` 串行化（与对话锁互不阻塞，避免正在对话时解析卡 GPU）。

## 后端新增 API

| 端点 | 方法 | 行为 |
|---|---|---|
| `/api/papers/open` | POST `{zotero_item_id}` | `resolve_pdf` → 查 `~/.cache/paper-master/{sha}.json` 缓存。有缓存→立即 `{paper_id, status:"ready"}`；无缓存→后台线程跑 `MinerUParser.parse()`，返回 `{paper_id, status:"parsing"}` |
| `/api/papers/{id}/status` | GET | 轮询 `{status: parsing\|ready\|error, message}` |
| `/api/papers/{id}/overview` | GET | `{title, abstract, toc: [{title, level}]}` |
| `/api/papers/{id}/content` | GET | 返回 `.md` 内容，图片相对路径重写为 `/api/papers/{id}/images/{relpath}` |
| `/api/papers/{id}/images/{relpath}` | GET | 返回图片字节（`FileResponse`） |
| `/api/papers/{id}/chat` | POST SSE | 见下节事件协议 |

- `POST /api/papers/open` 返回 `paper_id`；`overview`/`content`/`chat` 统一用 `paper_id`（对前端隐藏 sha256）。
- 解析完成或失败都会写 `parse_tasks[paper_id]`；失败时前端显示错误并可重试。

### chat SSE 事件协议

`Content-Type: text/event-stream`，事件格式 `event: <type>\ndata: <json>\n\n`：

| 事件 | data | 说明 |
|---|---|---|
| `tool_start` | `{name, arguments}` | agent 决定调用工具 |
| `tool_result` | `{name, chars, resources}` | 工具执行完毕（原 `print("[agent] ...")`） |
| `answer_chunk` | `{delta}` | 最终回答的 token 片段 |
| `done` | `{}` | 回答结束 |
| `error` | `{message}` | 出错（中断） |

## SSE agent 改造（核心）

### LLM 客户端流式

`OpenAIClient` 新增：

```python
def chat_with_tools_stream(self, messages, tools, system_prompt=""):
    # stream=True；逐 chunk yield 结构化事件：
    #   ("text_delta", str) 或 ("tool_call_delta", {index, id, name, arguments_partial})
```

- 累加各 index 的 tool_calls delta（partial JSON arguments 拼接），流结束后组装成 `LLMToolResponse`。
- 用户当前两个模型（deepseek / qwen）都是 OpenAI provider，覆盖此路径。`AnthropicClient` 暂不加流式（非当前使用），`run_stream` 遇到 anthropic 可退化为整段。

### PaperAgent 循环重构

```python
def _run_loop(self, question, history, memory, on_event, stream) -> str
def run(self, question, history, memory) -> str        # 旧入口，on_event=None, stream=False，行为不变
def run_stream(self, question, history, memory, on_event) -> None  # 新入口
```

- `run()` 保持现有行为 → CLI + 170 测试无回归。
- `stream=True` 时用 `chat_with_tools_stream`，`stream=False` 用 `chat_with_tools`。
- **每轮缓冲 text deltas**：流中先攒着；轮末判断——
  - 无 tool_calls（最终回答）→ 把缓冲的 deltas 逐个发 `answer_chunk`；
  - 有 tool_calls → 丢弃文本缓冲（避免展示"被取消的思考文字"），执行工具并逐个发 `tool_start` / `tool_result`。
- `record_observation` 的 round 映射逻辑、压缩逻辑完全复用。

## 前端

### 结构

```
frontend/
  package.json, tsconfig, vite.config.ts (proxy /api → :8000)
  src/
    main.tsx, App.tsx
    api/            # REST 封装 + SSE(fetch ReadableStream) 解析器
    state/          # 轻量状态（React context / hooks），不用重型状态库
    components/
      PaperListSidebar/   # 收藏夹树 + 搜索框 + 条目列表（Ant Design）
      ChatPanel/          # 消息列表 + 输入框 + 工具日志时间线 + 流式渲染
      ReadingPanel/       # markdown 渲染 + TOC 锚点 + 图片
```

### 关键点

- **三栏布局**：Ant `Layout` + 两个 `Sider`（左/右可折叠）+ 中间 `Content`。
- **SSE 解析**：POST SSE 不能用 `EventSource`，用 `fetch` + `response.body.getReader()` + `ReadableStream` 手动解析 `event:`/`data:` 帧。
- **markdown**：`react-markdown` + `remark-gfm`；图片 `<img>` 用后端重写后的 URL；TOC 用 `rehype` 提取标题 + 锚点跳转。
- **解析进度**：`POST /open` 返回 `parsing` 后，前端 `setInterval` 轮询 `/status`，显示 Ant `Spin` + 状态文案，直到 `ready`/`error`。
- **对话流式渲染**：`answer_chunk` 逐段 append 到当前 assistant 气泡（纯文本；MVP 不渲染回答内 markdown，避免流式中断的排版问题）。
- **dev**：`vite`（5173）代理 `/api` → `localhost:8000`。
- **prod**：`vite build` 产物由 FastAPI 挂载（`StaticFiles` + SPA fallback 到 `index.html`），单端口单进程。

## 测试

### 后端（pytest）

- 新增 `tests/test_papers_api.py`：
  - `open`：有缓存→`ready`；无缓存→后台任务 `parsing` → 状态流转到 `ready`
  - `/status` / `/overview` / `/content` / `/images` 返回正确
  - `chat` SSE：用 fake client（记录流式事件），断言 `tool_start` → `tool_result` → `answer_chunk*` → `done` 序列
- `PaperAgent.run_stream` 单测：fake streaming client，验证缓冲/丢弃逻辑
- 170 个既有测试保持绿色（`run()` 未改）

### 前端

- `tsc --noEmit` + `vite build` 通过
- 浏览器手测主路径：Zotero 列表选论文 → 解析进度 → 阅读区 TOC/图片 → 提问 → 工具日志 + 流式回答
- 不做重型前端单测（MVP 阶段手动验证）

## 交付物

1. 后端：papers API + session/parse_tasks + `run_stream` + 流式 client
2. 前端：`frontend/` 工程 + 三栏 UI
3. 启动脚本 `launch.bat`（Windows）：`wsl -e bash -lc "cd ... && source .venv/bin/activate && uvicorn paper_reader.server:app"` + 打开浏览器
4. 文档：CLAUDE.md / README 更新

## 暂缓（明确不做）

- 多论文本地知识库（跨论文检索/汇总）→ 下一版
- 前端重型单测、状态库（zustand/redux）
- 回答内 markdown 渲染、PDF 原版预览、Tauri 外壳
