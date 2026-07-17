# Tool Result 压缩 + Observation Memory 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PaperAgent 循环中实现工具结果压缩，通过新增 record_observation 工具和三层记忆架构，控制上下文膨胀。

**Architecture:** 新增 Observation dataclass 作为 L2 记忆存储。在 _make_tools 中新增 record_observation 工具让 LLM 自发记录观察。在 PaperAgent.run() 每轮发送 LLM 前调用 _compact_messages()，最新一轮 tool result 保留完整，往轮替换为 observation 摘要或截断降级。

**Tech Stack:** Python 3.10+, dataclasses, 现有 agent.py 框架

## Global Constraints

- 只改 `paper_reader/agent.py` 单文件
- 只改 `tests/test_agent.py` 单文件
- 不增加额外 API 调用
- 不引入新依赖
- 现有 91 个测试必须保持通过

---

## File Structure

| 文件 | 职责 |
|------|------|
| `paper_reader/agent.py` | Observation dataclass, _smart_truncate, record_observation 工具, _compact_messages, PaperAgent 循环修改, system prompt 更新 |
| `tests/test_agent.py` | _smart_truncate 测试, record_observation 工具测试, _compact_messages 测试, 端到端压缩测试 |

---

### Task 1: 新增 Observation dataclass 和 _smart_truncate 辅助函数

**Files:**
- Modify: `paper_reader/agent.py` (在 ToolResult 之后插入)

**Interfaces:**
- Produces: `Observation` dataclass (summary: str, facts: list[str], entities: list[str], sources: list[str])
- Produces: `_smart_truncate(text: str, max_chars: int = 300) -> str`

**Description:** 在 agent.py 顶部添加 Observation 数据类和智能截断函数，为后续工具和压缩逻辑提供基础。

- [ ] **Step 1: 添加 Observation dataclass 和 _smart_truncate**

在 `agent.py` 第 28 行（ToolResult 定义之后）插入：

```python
@dataclass
class Observation:
    """LLM 在每轮检索后记录的结构化观察。"""
    summary: str
    facts: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _smart_truncate(text: str, max_chars: int = 300) -> str:
    """在句子边界截断文本，避免断句。"""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    for sep in ['. ', '。', '\n', '；', '; ']:
        idx = truncated.rfind(sep)
        if idx > max_chars * 0.5:
            truncated = truncated[:idx + len(sep)]
            break
    return truncated.rstrip() + f"\n[已截断，原文共 {len(text)} 字]"
```

- [ ] **Step 2: 运行现有测试确认无回归**

```bash
python3 -m pytest tests/test_agent.py -v
```

Expected: 全部 PASS（新代码未被引用，不影响现有测试）

- [ ] **Step 3: 提交**

```bash
git add paper_reader/agent.py
git commit -m "feat: add Observation dataclass and _smart_truncate helper"
```

---

### Task 2: 新增 record_observation 工具

**Files:**
- Modify: `paper_reader/agent.py:_make_tools (参数 + 新增工具函数)
- Modify: `paper_reader/agent.py:PaperAgent.__init__ (传入 observations 列表)

**Interfaces:**
- Consumes: `Observation` dataclass from Task 1
- Modifies: `_make_tools(ctx, vision_client, resources_store, observations_store)` — 新增第 4 个参数
- Produces: `record_observation` 工具注册到 _make_tools 返回值

- [ ] **Step 1: 修改 _make_tools 签名，新增 record_observation 工具**

修改 `_make_tools` 函数签名（第 96 行）：

```python
def _make_tools(ctx, vision_client, resources_store: dict, observations_store: list) -> list[Tool]:
```

在 `describe_image` 之后（第 158 行后），`return [` 之前，插入：

```python
        def record_observation(summary: str, facts: list[str] | None = None,
                               entities: list[str] | None = None,
                               sources: list[str] | None = None) -> ToolResult:
            obs = Observation(
                summary=summary,
                facts=facts or [],
                entities=entities or [],
                sources=sources or [],
            )
            observations_store.append(obs)
            parts = [f"[已记录观察 #{len(observations_store)}] {summary}"]
            if facts:
                parts.append("关键事实: " + "; ".join(facts))
            return ToolResult(text="\n".join(parts))
```

在 `return [` 数组中（第 208 行之前），添加新 Tool：

```python
            Tool(
                name="record_observation",
                description=(
                    "记录本轮检索的关键发现（结构化观察）。"
                    "在看完 search_paper 或 get_section 的返回结果后调用，"
                    "总结本轮学到的关键信息。summary 为一段话总结，"
                    "facts 为关键事实列表，entities 为涉及的关键概念/方法/指标，"
                    "sources 为信息来源（如 ['p3 §2.1']）。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "本轮检索发现的关键信息总结"},
                        "facts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "关键事实列表",
                        },
                        "entities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "涉及的关键概念、方法、指标等实体",
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "信息来源标注，如 ['p3 §2.1', 'p5 §4.2']",
                        },
                    },
                    "required": ["summary"],
                },
                callable=record_observation,
            ),
```

- [ ] **Step 2: 修改 PaperAgent.__init__ 传入 observations 列表**

修改 `PaperAgent.__init__`（第 229-234 行）：

```python
class PaperAgent:
    def __init__(self, text_client, vision_client, ctx):
        self._text_client = text_client
        self._vision_client = vision_client
        self._ctx = ctx
        self._resources: dict[str, Resource] = {}
        self._observations: list[Observation] = []
        self._tool_round_map: dict[str, int] = {}
        self._tools = _make_tools(ctx, vision_client, self._resources, self._observations)
```

注意更新 `_make_tools` 调用，传入 `self._observations`。

- [ ] **Step 3: 更新测试中的 _make_tools 调用**

`tests/test_agent.py` 中所有 `_make_tools(ctx, vision, store)` 调用需要加上第 4 个参数 `[]`。

用 `replace_all` 替换：
- old: `_make_tools(ctx, vision_client, store)`
- new: `_make_tools(ctx, vision_client, store, [])`

以及：
- old: `_make_tools(ctx, FakeVisionClient(), store)`
- new: `_make_tools(ctx, FakeVisionClient(), store, [])`

以及：
- old: `_make_tools(FakeCtx(), vision, store)`
- new: `_make_tools(FakeCtx(), vision, store, [])`

以及：
- old: `_make_tools(ctx, FakeVisionClient(), {})`
- new: `_make_tools(ctx, FakeVisionClient(), {}, [])`

- [ ] **Step 4: 运行测试确认通过**

```bash
python3 -m pytest tests/test_agent.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add paper_reader/agent.py tests/test_agent.py
git commit -m "feat: add record_observation tool to _make_tools"
```

---

### Task 3: 实现 _compact_messages 压缩逻辑

**Files:**
- Modify: `paper_reader/agent.py` (PaperAgent 类)

**Interfaces:**
- Consumes: `Observation`, `_smart_truncate` from Tasks 1-2
- Produces: `PaperAgent._compact_messages(messages, current_round) -> list[dict]`
- Produces: `PaperAgent._record_tool_round(tool_call_id, round_num) -> None`

- [ ] **Step 1: 在 PaperAgent 中添加 _compact_messages 方法**

在 `PaperAgent` 类的 `run` 方法之前插入：

```python
    def _record_tool_round(self, tool_call_id: str, round_num: int) -> None:
        self._tool_round_map[tool_call_id] = round_num

    def _compact_messages(self, messages: list[dict], current_round: int) -> list[dict]:
        """替换往轮 tool result 为 observation 摘要或截断。

        最新一轮 (current_round) 的 tool result 保留完整，
        往轮的替换为对应 observation 摘要，无 observation 则截断降级。
        """
        compacted: list[dict] = []
        for msg in messages:
            if msg["role"] == "tool":
                tc_id = msg.get("tool_call_id", "")
                round_num = self._tool_round_map.get(tc_id)
                if round_num is not None and round_num < current_round:
                    obs = self._observations[round_num] if round_num < len(self._observations) else None
                    if obs is not None:
                        compacted.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"[已记录观察] {obs.summary}",
                        })
                    else:
                        compacted.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": _smart_truncate(msg["content"], max_chars=300),
                        })
                    continue
            compacted.append(msg)
        return compacted
```

- [ ] **Step 2: 运行测试确认无回归**

```bash
python3 -m pytest tests/test_agent.py -v
```

Expected: 全部 PASS（新方法未被调用，不影响现有测试）

- [ ] **Step 3: 提交**

```bash
git add paper_reader/agent.py
git commit -m "feat: add _compact_messages method to PaperAgent"
```

---

### Task 4: 修改 Agent 循环，集成压缩和轮次追踪

**Files:**
- Modify: `paper_reader/agent.py:PaperAgent.run()` (第 236-303 行)

**Interfaces:**
- Consumes: `_compact_messages`, `_record_tool_round` from Task 3
- Modifies: `run()` 循环 — 每轮发送前压缩 + 追加 tool 消息时记录轮次

- [ ] **Step 1: 修改 run() 循环**

将 `run` 方法（第 236-303 行）替换为：

```python
    def run(self, question: str, history: list[dict] | None = None,
            memory: PaperMemory | None = None) -> str:
        system = SYSTEM_PROMPT
        if memory is not None:
            system = system + "\n\n" + _format_memory(memory)

        messages = list(history) if history else []
        messages.append({"role": "user", "content": question})

        # 注入当前已累积的 observations
        if self._observations:
            obs_lines = ["[已知信息 — 之前检索已发现]"]
            for i, obs in enumerate(self._observations):
                obs_lines.append(f"{i + 1}. {obs.summary}")
            system = system + "\n\n" + "\n".join(obs_lines)

        tool_schemas = [_tool_to_openai_schema(t) for t in self._tools]

        # 重置轮次追踪（每次 run 是独立对话）
        self._tool_round_map.clear()

        for round_num in range(7):
            # 发送前压缩往轮 tool result
            compacted_messages = self._compact_messages(messages, round_num)

            response = self._text_client.chat_with_tools(
                compacted_messages, tool_schemas, system_prompt=system,
            )

            if response.text and not response.tool_calls:
                return response.text

            if not response.tool_calls:
                return response.text or ""

            # Append assistant message with tool_calls
            openai_tool_calls = []
            for tc in response.tool_calls:
                openai_tool_calls.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"] if isinstance(tc["arguments"], str) else json.dumps(tc["arguments"]),
                    },
                })
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": openai_tool_calls,
            })

            # Execute each tool call
            for tc in response.tool_calls:
                name = tc["name"]
                raw_args = tc["arguments"]

                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}

                tool = next((t for t in self._tools if t.name == name), None)
                if tool is None:
                    result = ToolResult(text=f"[未知工具: {name}]")
                else:
                    try:
                        result = tool.callable(**args)
                    except Exception as e:
                        result = ToolResult(text=f"[工具执行失败: {e}]")

                print(f"  [agent] {name}({str(raw_args)[:60]}{'...' if len(str(raw_args)) > 60 else ''})"
                      f" → {len(result.text)} chars, {len(result.resources)} resources")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result.text,
                })
                # 记录 tool 消息所属轮次
                self._tool_round_map[tc["id"]] = round_num

        return "抱歉，暂时没能找到相关信息，请尝试换一个问法。"
```

关键改动（相对于原代码）：
1. L1-L5: 注入已累积 observations 到 system prompt
2. L9: `self._tool_round_map.clear()` 新对话重置轮次追踪
3. L12: `compacted_messages = self._compact_messages(messages, round_num)` 发送前压缩
4. L19: 用 `compacted_messages` 替代 `messages` 发送
5. L56: `self._tool_round_map[tc["id"]] = round_num` 记录轮次

- [ ] **Step 2: 运行测试确认无回归**

```bash
python3 -m pytest tests/test_agent.py -v
```

Expected: 全部 PASS（压缩逻辑对假 client 透明，因为假 client 不读取 tool result 内容做判断）

- [ ] **Step 3: 提交**

```bash
git add paper_reader/agent.py
git commit -m "feat: integrate tool result compression into agent loop"
```

---

### Task 5: 更新 System Prompt

**Files:**
- Modify: `paper_reader/agent.py:SYSTEM_PROMPT` (第 212-225 行)

- [ ] **Step 1: 更新 SYSTEM_PROMPT**

将 `SYSTEM_PROMPT` 替换为：

```python
SYSTEM_PROMPT = """你是一个论文阅读助手。你根据提供的论文内容帮助用户理解学术论文，用中文回答问题。

准则:
- 仅根据提供的论文内容作答
- 回答准确、简洁
- 用中文回复
- 如果提供的内容不足以回答问题，请明确说明
- 讨论图表时，描述其展示的内容
- 引用章节标题来为回答提供上下文
- 拿到足够的检索结果后就应该尝试回答，不要反复更换查询词搜索
- describe_image 返回"[图片无法读取]"说明图片文件不可用，直接用已有文本回答即可，不要再重试
- 如果连续两次检索都没有找到新信息，请基于已有内容作答
- 每次调用 search_paper 或 get_section 后，请同时调用 record_observation 记录本轮关键发现，便于后续推理时回顾

你可以使用工具来检索论文内容。根据用户问题自主判断是否需要调用工具。"""
```

改动：新增最后一条准则指导 LLM 调用 record_observation。

- [ ] **Step 2: 提交**

```bash
git add paper_reader/agent.py
git commit -m "feat: update system prompt to guide record_observation usage"
```

---

### Task 6: 测试 _smart_truncate

**Files:**
- Modify: `tests/test_agent.py` (追加测试)

- [ ] **Step 1: 添加测试**

在 `tests/test_agent.py` 末尾追加：

```python
# ── _smart_truncate tests ───────────────────────────────────────────────


def test_smart_truncate_short_text_unchanged():
    from paper_reader.agent import _smart_truncate
    text = "短文本。"
    result = _smart_truncate(text, max_chars=300)
    assert result == text


def test_smart_truncate_at_period_boundary():
    from paper_reader.agent import _smart_truncate
    text = "第一句话。第二句话。第三句话。"
    result = _smart_truncate(text, max_chars=10)
    assert "已截断" in result
    assert result.startswith("第一句话。")


def test_smart_truncate_at_newline_boundary():
    from paper_reader.agent import _smart_truncate
    text = "段落一\n段落二\n段落三"
    result = _smart_truncate(text, max_chars=10)
    assert result.startswith("段落一\n")
    assert "已截断" in result


def test_smart_truncate_includes_original_length():
    from paper_reader.agent import _smart_truncate
    text = "A" * 1000
    result = _smart_truncate(text, max_chars=300)
    assert "1000" in result
    assert "已截断" in result
```

- [ ] **Step 2: 运行测试**

```bash
python3 -m pytest tests/test_agent.py::test_smart_truncate_short_text_unchanged tests/test_agent.py::test_smart_truncate_at_period_boundary tests/test_agent.py::test_smart_truncate_at_newline_boundary tests/test_agent.py::test_smart_truncate_includes_original_length -v
```

Expected: 4 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_agent.py
git commit -m "test: add _smart_truncate tests"
```

---

### Task 7: 测试 record_observation 工具

**Files:**
- Modify: `tests/test_agent.py` (追加测试)

- [ ] **Step 1: 添加测试**

在 `tests/test_agent.py` 末尾追加：

```python
# ── record_observation tool tests ──────────────────────────────────────


def test_record_observation_stores_observation():
    from paper_reader.agent import _make_tools
    ctx = FakeCtx()
    store = {}
    obs_store = []
    tools = _make_tools(ctx, FakeVisionClient(), store, obs_store)
    record_fn = next(t for t in tools if t.name == "record_observation").callable

    result = record_fn(
        summary="注意力机制通过 Q/K/V 计算关联权重",
        facts=["公式为 softmax(QK^T/√d_k)V", "Multi-head 允许多子空间"],
        entities=["Attention", "Q/K/V"],
        sources=["p3 §3.1"],
    )
    assert len(obs_store) == 1
    assert obs_store[0].summary == "注意力机制通过 Q/K/V 计算关联权重"
    assert len(obs_store[0].facts) == 2
    assert len(obs_store[0].entities) == 2
    assert obs_store[0].sources == ["p3 §3.1"]
    assert "已记录观察" in result.text


def test_record_observation_minimal_fields():
    from paper_reader.agent import _make_tools
    ctx = FakeCtx()
    obs_store = []
    tools = _make_tools(ctx, FakeVisionClient(), {}, obs_store)
    record_fn = next(t for t in tools if t.name == "record_observation").callable

    result = record_fn(summary="简要总结")
    assert len(obs_store) == 1
    assert obs_store[0].summary == "简要总结"
    assert obs_store[0].facts == []
    assert obs_store[0].entities == []
    assert obs_store[0].sources == []


def test_record_observation_multiple_calls_accumulate():
    from paper_reader.agent import _make_tools
    ctx = FakeCtx()
    obs_store = []
    tools = _make_tools(ctx, FakeVisionClient(), {}, obs_store)
    record_fn = next(t for t in tools if t.name == "record_observation").callable

    record_fn(summary="第一轮发现")
    record_fn(summary="第二轮发现")
    assert len(obs_store) == 2
    assert obs_store[0].summary == "第一轮发现"
    assert obs_store[1].summary == "第二轮发现"


def test_record_observation_is_in_tool_list():
    from paper_reader.agent import _make_tools
    ctx = FakeCtx()
    tools = _make_tools(ctx, FakeVisionClient(), {}, [])
    names = [t.name for t in tools]
    assert "record_observation" in names
    assert "search_paper" in names
    assert "get_section" in names
    assert "describe_image" in names
```

- [ ] **Step 2: 运行测试**

```bash
python3 -m pytest tests/test_agent.py::test_record_observation_stores_observation tests/test_agent.py::test_record_observation_minimal_fields tests/test_agent.py::test_record_observation_multiple_calls_accumulate tests/test_agent.py::test_record_observation_is_in_tool_list -v
```

Expected: 4 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_agent.py
git commit -m "test: add record_observation tool tests"
```

---

### Task 8: 测试 _compact_messages 压缩逻辑

**Files:**
- Modify: `tests/test_agent.py` (追加测试)

- [ ] **Step 1: 添加测试**

在 `tests/test_agent.py` 末尾追加：

```python
# ── _compact_messages tests ────────────────────────────────────────────


def test_compact_messages_preserves_latest_round():
    """最新一轮 tool result 保持完整。"""
    from paper_reader.agent import PaperAgent, Observation
    ctx = FakeCtx()
    agent = PaperAgent(text_client=FakeTextClient(), vision_client=FakeVisionClient(), ctx=ctx)
    agent._tool_round_map["call_1"] = 0
    agent._tool_round_map["call_2"] = 1
    agent._observations = [Observation(summary="第0轮观察")]

    messages = [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "search_paper", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "第0轮结果，很多文字"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_2", "type": "function", "function": {"name": "get_section", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "call_2", "content": "第1轮结果，最新内容"},
    ]

    compacted = agent._compact_messages(messages, current_round=1)

    # 第1轮 tool result 保持完整
    tool_msgs = [m for m in compacted if m["role"] == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[1]["content"] == "第1轮结果，最新内容"


def test_compact_messages_replaces_old_round_with_observation():
    """往轮 tool result 被 observation 摘要替换。"""
    from paper_reader.agent import PaperAgent, Observation
    ctx = FakeCtx()
    agent = PaperAgent(text_client=FakeTextClient(), vision_client=FakeVisionClient(), ctx=ctx)
    agent._tool_round_map["call_1"] = 0
    agent._tool_round_map["call_2"] = 1
    agent._observations = [Observation(summary="注意力机制的核心是 QKV")]

    messages = [
        {"role": "tool", "tool_call_id": "call_1", "content": "很长的旧结果"},
        {"role": "tool", "tool_call_id": "call_2", "content": "新结果"},
    ]

    compacted = agent._compact_messages(messages, current_round=1)

    assert "已记录观察" in compacted[0]["content"]
    assert "注意力机制的核心是 QKV" in compacted[0]["content"]
    assert compacted[1]["content"] == "新结果"


def test_compact_messages_fallback_truncate_when_no_observation():
    """无 observation 时降级为智能截断。"""
    from paper_reader.agent import PaperAgent
    ctx = FakeCtx()
    agent = PaperAgent(text_client=FakeTextClient(), vision_client=FakeVisionClient(), ctx=ctx)
    agent._tool_round_map["call_1"] = 0
    agent._tool_round_map["call_2"] = 1

    old_text = "A" * 500
    messages = [
        {"role": "tool", "tool_call_id": "call_1", "content": old_text},
        {"role": "tool", "tool_call_id": "call_2", "content": "新结果"},
    ]

    compacted = agent._compact_messages(messages, current_round=1)

    assert "已截断" in compacted[0]["content"]
    assert len(compacted[0]["content"]) < len(old_text)
    assert compacted[1]["content"] == "新结果"


def test_compact_messages_round_zero_all_preserved():
    """第 0 轮时所有 tool result 都是最新的，不压缩。"""
    from paper_reader.agent import PaperAgent
    ctx = FakeCtx()
    agent = PaperAgent(text_client=FakeTextClient(), vision_client=FakeVisionClient(), ctx=ctx)
    agent._tool_round_map["call_1"] = 0
    agent._tool_round_map["call_2"] = 0

    messages = [
        {"role": "tool", "tool_call_id": "call_1", "content": "结果1"},
        {"role": "tool", "tool_call_id": "call_2", "content": "结果2"},
    ]

    compacted = agent._compact_messages(messages, current_round=0)

    assert compacted[0]["content"] == "结果1"
    assert compacted[1]["content"] == "结果2"


def test_compact_messages_handles_messages_without_tool_call_id():
    """没有 tool_call_id 的消息不被识别为旧轮次，保持原样。"""
    from paper_reader.agent import PaperAgent
    ctx = FakeCtx()
    agent = PaperAgent(text_client=FakeTextClient(), vision_client=FakeVisionClient(), ctx=ctx)

    messages = [
        {"role": "tool", "content": "no tool_call_id"},
        {"role": "user", "content": "问题"},
    ]

    compacted = agent._compact_messages(messages, current_round=2)

    assert compacted[0]["content"] == "no tool_call_id"
    assert compacted[1]["content"] == "问题"
```

- [ ] **Step 2: 运行测试**

```bash
python3 -m pytest tests/test_agent.py -k "compact" -v
```

Expected: 5 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_agent.py
git commit -m "test: add _compact_messages tests"
```

---

### Task 9: 端到端 Agent 压缩测试

**Files:**
- Modify: `tests/test_agent.py` (追加测试)

- [ ] **Step 1: 添加端到端测试**

在 `tests/test_agent.py` 末尾追加：

```python
# ── End-to-end compression tests ───────────────────────────────────────


def test_agent_passes_compacted_messages_to_llm():
    """验证 Agent 在多轮对话中发送的是压缩后的消息。"""
    from paper_reader.agent import PaperAgent, Observation
    ctx = FakeCtx()

    text_client = FakeTextClient(responses=[
        # 第 0 轮：搜索
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "search_paper",
            "arguments": '{"query":"method"}',
        }]),
        # 第 1 轮：记录观察 + 继续搜
        LLMToolResponse(tool_calls=[
            {
                "id": "call_2",
                "name": "record_observation",
                "arguments": '{"summary":"方法用的是梯度下降优化"}',
            },
            {
                "id": "call_3",
                "name": "search_paper",
                "arguments": '{"query":"experiment"}',
            },
        ]),
        # 第 2 轮：回答
        LLMToolResponse(text="根据检索，方法使用了梯度下降..."),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="这篇论文的方法是什么？", history=[])

    assert "梯度下降" in answer
    assert len(text_client.calls) == 3

    # 第 2 轮发送时（call index=1），消息中应该包含压缩后的第 0 轮结果
    second_call_messages = text_client.calls[1]["messages"]
    tool_msgs = [m for m in second_call_messages if m["role"] == "tool"]
    # 第 0 轮的 search_paper 结果应该已被 observation 替换
    obs_replacements = [m for m in tool_msgs if "已记录观察" in m["content"]]
    assert len(obs_replacements) == 1


def test_agent_injects_observations_into_system_prompt():
    """验证累积的 observations 注入到 system prompt 中。"""
    from paper_reader.agent import PaperAgent, Observation
    ctx = FakeCtx()

    text_client = FakeTextClient(responses=[
        LLMToolResponse(text="已回答"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent._observations = [
        Observation(summary="方法使用强化学习", facts=["PPO算法"]),
        Observation(summary="在ImageNet上验证", facts=["Top-1 85%"]),
    ]

    agent.run(question="总结方法", history=[])

    system_prompt = text_client.calls[0]["system_prompt"]
    assert "已知信息" in system_prompt
    assert "强化学习" in system_prompt
    assert "ImageNet" in system_prompt


def test_agent_clears_tool_round_map_on_new_run():
    """新 run() 调用应重置轮次追踪。"""
    from paper_reader.agent import PaperAgent
    ctx = FakeCtx()

    text_client = FakeTextClient(responses=[
        LLMToolResponse(text="第一次回答"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent._tool_round_map["old_call"] = 5

    agent.run(question="新问题", history=[])
    assert len(agent._tool_round_map) == 0
```

- [ ] **Step 2: 运行测试**

```bash
python3 -m pytest tests/test_agent.py -k "agent_passes_compacted\|agent_injects\|agent_clears" -v
```

Expected: 3 PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_agent.py
git commit -m "test: add end-to-end agent compression tests"
```

---

### Task 10: 运行全部测试，确认无回归

- [ ] **Step 1: 运行全部测试**

```bash
python3 -m pytest tests/ -v
```

Expected: 全部 PASS（原有 91 个 + 新增约 16 个）

- [ ] **Step 2: 提交（如有必要）**

如果测试有修正，提交修正。
