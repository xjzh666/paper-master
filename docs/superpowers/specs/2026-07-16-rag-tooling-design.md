# P0: RAG 工具化 — 设计文档

## 目标

将检索能力从 pipeline 中解耦为独立工具，引入 Agent 循环，让 LLM 自主决定何时检索、检索什么，而非每问必查。

## 架构

```
用户问题
  │
  └── PaperAgent.run(question, history)
        │
        ├── 第 1 轮: LLM (text 模型) + tools 定义
        │     ├── 无 tool_calls → 直接返回文本回答
        │     └── 有 tool_calls → 执行工具，结果传回
        │
        ├── 第 N 轮: LLM 综合工具结果
        │     ├── 需要 describe_image → 调用 vision 模型解析图片
        │     └── 不需要 → 综合文本生成最终回答
        │
        └── 最多 7 轮，超限强制终止
```

### 新增文件

- `paper_reader/agent.py` — Agent 编排逻辑
- `tests/test_agent.py` — Agent 相关测试

### 修改文件

- `paper_reader/llm.py` — 新增 `chat_with_tools()`、`LLMToolResponse`
- `main.py` — `handle_question()` 重构为 Agent 调用；删除 `_is_section_query()`

## 数据模型

```python
@dataclass
class Resource:
    """工具返回的资源引用，只存索引不存数据，避免上下文膨胀。"""
    type: str              # "image" | "table"
    id: str                # "img_3", "table_2"
    path: str              # 文件路径，describe_image 时才加载
    caption: str           # 图注 / 周边文本

    def load_data(self) -> bytes:
        """懒加载：调用时才读文件。"""
        ...

@dataclass
class ToolResult:
    text: str
    resources: list[Resource]   # 资源引用列表

@dataclass
class LLMToolResponse:
    text: str | None
    tool_calls: list[dict]  # [{"id", "name", "arguments"}]

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict       # JSON Schema
    callable: Callable[..., ToolResult]
```

## 工具

工具描述中强化规则：返回结果可能包含图片/表格资源引用（`resources` 字段），涉及图表内容时需调用 `describe_image` 解析。

### search_paper

- 参数: `query: str`
- 内部: `ctx.search_chunks(query, top_k=3)` → `ctx.build_context(chunks, window=2)`
- 返回: `ToolResult` (text + resources，含图片/表格的资源引用)
- top_k、window 由工具内部管理，Agent 不感知

### get_section

- 参数: `reference: str`（章节编号 "3.2" 或标题关键词 "Experiments"）
- 内部: `ctx.find_section(reference)` → 收集该节全部文本
- 截断: 超过 3000 字截断，尾部标注 `[已截断，原文共 N 字，请用更具体的 reference 缩小范围]`
- 返回: `ToolResult` (text + 该节内 images/table 的资源引用)

### describe_image

- 参数: `resource_id: str`
- 内部: 根据 id 找到 Resource，调用 `resource.load_data()` 加载图片二进制 → 调 vision 模型
- 返回: `str`（图片内容描述）
- vision 模型只做图片内容提取，不参与最终回答

## Agent 循环

`PaperAgent.run(question, history, memory) -> str`:

1. 构建初始 messages: 用户问题 + 上下文
2. system_prompt = SYSTEM_PROMPT + memory 注入
3. 调用 `text_client.chat_with_tools(messages, tools, system_prompt)`
4. 如果 LLM 返回 text（无 tool_calls）→ 返回 text
5. 如果 LLM 返回 tool_calls → 并行执行互不依赖的工具，依赖工具串行执行
6. 结果以 OpenAI tool result 格式 append 到 messages
7. 回到步骤 3，最多 7 轮
8. 超过 7 轮：返回终止消息

**并行 vs 串行：**

- `search_paper` / `get_section`：无相互依赖，同一轮内可并行执行
- `describe_image`：依赖前一步 ToolResult 中的 resource id，必须在前一步结果返回后才能调用

同一轮 LLM 返回的 tool_calls 如果是同一类无依赖工具，直接并行执行，结果按顺序一起传回。

## LLMRouter 改动

```python
class LLMRouter:
    def chat_with_tools(
        self, messages: list[dict], tools: list[dict],
        system_prompt: str = "",
    ) -> LLMToolResponse:
        # 用 OpenAIClient 的 tool calling API
        # tool_choice="auto"（LLM 自主决定是否调用工具）

    # answer() 方法保留（batch memory 抽取用），不做改动
```

`chat_with_tools` 用 text 模型（deepseek-v4-pro）做工具选择和执行编排。图片解析由 `describe_image` 工具通过 `_vision_client` 完成。

## main.py 改动

```python
def handle_question(question, ctx, router):
    ctx.add_message("user", question)
    agent = PaperAgent(
        text_client=router._text_client,
        vision_client=router._vision_client,
        ctx=ctx,
    )
    answer = agent.run(question, history=ctx.history[:-1], memory=ctx.paper.memory)
    ctx.add_message("assistant", answer)
    return answer
```

Agent 执行过程中打印工具调用日志：

```
  [agent] search_paper("核心贡献") → 3 chunks, 2 resources
  [agent] describe_image("img_3") → 完成
```

## 错误处理

| 场景 | 处理 |
|------|------|
| 工具返回空结果 | 返回 `ToolResult(text="[检索结果为空]", resources=[])`，Agent 自然告知 |
| get_section 内容过长 | 截断到 3000 字，尾部标注原文总字数 |
| LLM API 调用失败 | 重试 2 次（指数退避），仍失败向上抛 |
| 超过 7 轮 | 返回 `"抱歉，暂时没能找到相关信息，请尝试换一个问法。"` |
| describe_image 加载失败 | 返回 `"[图片无法读取]"` |
| 幻觉工具名/参数格式错误 | 返回 `ToolResult(text="[工具调用失败: {error}]", resources=[])` |

## 测试

`tests/test_agent.py`:

- `test_agent_answers_without_tools` — LLM 直接回答
- `test_agent_calls_search_paper` — 调用 search_paper 路径
- `test_agent_calls_get_section` — 调用 get_section 路径
- `test_agent_describe_image` — resource → describe_image 路径
- `test_agent_max_rounds` — 7 轮后强制终止
- `test_tool_empty_result` — 空检索结果不崩溃
- `test_memory_injection` — PaperMemory 注入 system prompt

已有 91 个测试保持通过。`LLMRouter.answer` 的测试保持不动（批量模式仍用）。
