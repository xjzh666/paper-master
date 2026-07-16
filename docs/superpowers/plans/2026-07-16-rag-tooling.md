# P0 RAG 工具化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple RAG retrieval from the answer pipeline into an Agent loop with native function calling, letting the LLM decide when to search.

**Architecture:** New `paper_reader/agent.py` with `Resource`, `ToolResult`, `Tool` dataclasses and `PaperAgent` orchestrator. `LLMRouter` gains `chat_with_tools()` using OpenAI tool-calling API. `main.py` `handle_question()` delegates to `PaperAgent.run()`.

**Tech Stack:** Python 3.10+, dataclasses, OpenAI SDK (tool calling), existing BGE-M3, existing MinerU

## Global Constraints

- 3 tools: `search_paper`, `get_section`, `describe_image`
- Agent 循环最多 7 轮，text 模型做编排，vision 模型仅做图片解析
- `Resource` 只存 id/type/path，懒加载，不随 ToolResult 传 bytes
- `get_section` 截断 3000 字
- 工具参数 top_k/window 内部管理，Agent 不感知
- 现有 91 个测试保持通过
- 不引入新依赖

---

### Task 1: Add data models to agent.py

**Files:**
- Create: `paper_reader/agent.py`

**Interfaces:**
- Produces: `Resource`, `ToolResult`, `LLMToolResponse`, `Tool` dataclasses

- [ ] **Step 1: Write the test**

Create `tests/test_agent.py`:

```python
from paper_reader.agent import Resource, ToolResult, LLMToolResponse, Tool


def test_resource_creation():
    r = Resource(type="image", id="img_3", path="/tmp/img.png", caption="Fig. 1")
    assert r.type == "image"
    assert r.id == "img_3"
    assert r.path == "/tmp/img.png"
    assert r.caption == "Fig. 1"


def test_resource_load_data_reads_file(tmp_path):
    p = tmp_path / "test.png"
    p.write_bytes(b"fake_image_data")
    r = Resource(type="image", id="img_1", path=str(p), caption="")
    assert r.load_data() == b"fake_image_data"


def test_resource_load_data_missing_file():
    r = Resource(type="image", id="img_1", path="/nonexistent.png", caption="")
    assert r.load_data() == b""


def test_tool_result_creation():
    r = Resource(type="image", id="img_1", path="/tmp/a.png", caption="Fig 1")
    tr = ToolResult(text="some text", resources=[r])
    assert tr.text == "some text"
    assert len(tr.resources) == 1


def test_tool_result_default_resources():
    tr = ToolResult(text="text only")
    assert tr.resources == []


def test_llm_tool_response_text_only():
    resp = LLMToolResponse(text="hello")
    assert resp.text == "hello"
    assert resp.tool_calls == []


def test_llm_tool_response_with_calls():
    tc = {"id": "call_1", "name": "search_paper", "arguments": {"query": "test"}}
    resp = LLMToolResponse(tool_calls=[tc])
    assert resp.text is None
    assert len(resp.tool_calls) == 1


def test_tool_dataclass():
    t = Tool(
        name="search_paper",
        description="语义检索",
        parameters={"type": "object", "properties": {}},
        callable=lambda query: ToolResult(text=query),
    )
    result = t.callable(query="hello")
    assert result.text == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_agent.py -v
```
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Write minimal implementation**

Create `paper_reader/agent.py`:

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Resource:
    """工具返回的资源引用，只存索引不存数据，避免上下文膨胀。"""
    type: str              # "image" | "table"
    id: str                # "img_3", "table_2"
    path: str              # 文件路径，describe_image 时才加载
    caption: str           # 图注 / 周边文本

    def load_data(self) -> bytes:
        p = Path(self.path)
        if p.exists():
            return p.read_bytes()
        return b""


@dataclass
class ToolResult:
    text: str
    resources: list[Resource] = field(default_factory=list)


@dataclass
class LLMToolResponse:
    text: str | None = None
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict       # JSON Schema
    callable: Callable[..., ToolResult]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_agent.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paper_reader/agent.py tests/test_agent.py
git commit -m "feat: add Resource, ToolResult, Tool data models for agent"
```

---

### Task 2: Add chat_with_tools to OpenAIClient and LLMRouter

**Files:**
- Modify: `paper_reader/llm.py`

**Interfaces:**
- Produces: `OpenAIClient.chat_with_tools(messages, tools, system_prompt) -> LLMToolResponse`
- Produces: `LLMRouter.chat_with_tools(messages, tools, system_prompt) -> LLMToolResponse`

- [ ] **Step 1: Write the test**

Append to `tests/test_llm.py`:

```python
from paper_reader.llm import LLMToolResponse


class FakeOpenAIWithTools:
    """Fake OpenAI client that returns tool_calls."""
    def __init__(self):
        self.chat = type("chat", (), {"completions": type("completions", (), {"create": self._create})()})()

    def _create(self, *, model, messages, tools=None, tool_choice=None, max_tokens=None, **kwargs):
        from unittest.mock import Mock
        msg = Mock()
        if tools and any(t["function"]["name"] == "search_paper" for t in tools):
            tc = Mock()
            tc.id = "call_001"
            tc.function.name = "search_paper"
            tc.function.arguments = '{"query":"test query"}'
            msg.tool_calls = [tc]
            msg.content = None
        else:
            msg.tool_calls = None
            msg.content = "direct answer"
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = msg
        return response


def test_openai_chat_with_tools_returns_tool_calls():
    from paper_reader.llm import OpenAIClient
    client = OpenAIClient(api_key="test-key", model="gpt-4o")
    client._client = FakeOpenAIWithTools()

    tools = [{
        "type": "function",
        "function": {
            "name": "search_paper",
            "description": "搜索论文内容",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    }]

    response = client.chat_with_tools(
        messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        system_prompt="You are helpful.",
    )

    assert isinstance(response, LLMToolResponse)
    assert response.text is None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["name"] == "search_paper"


def test_openai_chat_with_tools_returns_text_when_no_tool_calls():
    from paper_reader.llm import OpenAIClient
    client = OpenAIClient(api_key="test-key", model="gpt-4o")
    # Use a different fake that returns text
    class FakeNoTools:
        def __init__(self):
            self.chat = type("chat", (), {"completions": type("completions", (), {"create": self._create})()})()

        def _create(self, *, model, messages, tools=None, tool_choice=None, max_tokens=None, **kwargs):
            from unittest.mock import Mock
            msg = Mock()
            msg.tool_calls = None
            msg.content = "plain text answer"
            response = Mock()
            response.choices = [Mock()]
            response.choices[0].message = msg
            return response

    client._client = FakeNoTools()

    response = client.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    )

    assert response.text == "plain text answer"
    assert response.tool_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_llm.py::test_openai_chat_with_tools_returns_tool_calls -v
```
Expected: FAIL with AttributeError (no `chat_with_tools` method)

- [ ] **Step 3: Write minimal implementation**

In `paper_reader/llm.py`, add import at top:

```python
from paper_reader.agent import LLMToolResponse
```

Wait — this creates a circular import since agent.py doesn't exist yet in this task context, but we already created it in Task 1. Actually, agent.py already exists from Task 1 and it only has dataclasses, no imports from llm. So `from paper_reader.agent import LLMToolResponse` is safe.

But wait — better to define `LLMToolResponse` in llm.py and have agent.py import from llm.py. Let me reconsider...

Actually, looking at the spec, `LLMToolResponse` is in the data model section of agent.py. But logically it's about LLM response. Let me keep it in llm.py since that's where the LLM client lives, and have agent.py import it from there. I need to adjust Task 1 slightly.

Hmm, but Task 1 already committed with LLMToolResponse in agent.py. Let me just move it. Actually, let me reconsider the plan order. It's fine to define it in llm.py and import it in agent.py. Let me adjust.

In Task 1, I'll put LLMToolResponse in agent.py (it's a simple dataclass with no llm deps). Then in Task 2, I import it from agent.py in llm.py. No circular dependency.

OK let me continue writing the plan with this in mind.

In `paper_reader/llm.py`, add to `OpenAIClient`:

```python
def chat_with_tools(
    self, messages: list[dict], tools: list[dict],
    system_prompt: str = "",
) -> "LLMToolResponse":
    from paper_reader.agent import LLMToolResponse

    api_messages = []
    if system_prompt:
        api_messages.append({"role": "system", "content": system_prompt})
    api_messages.extend(messages)

    response = self._client.chat.completions.create(
        model=self.model,
        messages=api_messages,
        tools=tools if tools else None,
        tool_choice="auto" if tools else None,
        max_tokens=4096,
    )

    msg = response.choices[0].message
    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            })

    return LLMToolResponse(text=msg.content, tool_calls=tool_calls)
```

Add to `LLMRouter`:

```python
def chat_with_tools(
    self, messages: list[dict], tools: list[dict],
    system_prompt: str = "",
) -> "LLMToolResponse":
    return self._text_client.chat_with_tools(messages, tools, system_prompt)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_llm.py::test_openai_chat_with_tools_returns_tool_calls tests/test_llm.py::test_openai_chat_with_tools_returns_text_when_no_tool_calls -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
python3 -m pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add paper_reader/llm.py tests/test_llm.py
git commit -m "feat: add chat_with_tools to OpenAIClient and LLMRouter"
```

---

### Task 3: Implement tool functions

**Files:**
- Modify: `paper_reader/agent.py`

**Interfaces:**
- Consumes: `ConversationContext.search_chunks()`, `ConversationContext.find_section()`, `ConversationContext.build_context()`, `ContentBlock.image_path`, `PaperDocument.result_dir`
- Produces: `_make_tools(ctx, vision_client, resources_store) -> list[Tool]`

- [ ] **Step 1: Write the test**

Append to `tests/test_agent.py`:

```python
from paper_reader.agent import _make_tools


class FakeCtx:
    """Fake ConversationContext for testing tools."""
    def __init__(self):
        from paper_reader.blocks import ContentBlock, SemanticChunk, PaperDocument
        self.paper = PaperDocument(
            filepath="/tmp/test.pdf",
            title="Test Paper",
            result_dir="/tmp/test_result",
        )
        b1 = ContentBlock(type="text", text="Hello world", level=0, page_idx=0)
        b2 = ContentBlock(type="text", text="Methods section content", level=1, page_idx=1)
        b2.text = "Methods"  # heading text for find_section match
        b3 = ContentBlock(type="text", text="More method details here.", level=0, page_idx=1)
        self.paper.blocks = [b1, b2, b3]
        chunk = SemanticChunk(
            chunk_id="ch_0", text="Hello world",
            blocks=[b1], section_path=[], images=[],
        )
        self.paper.chunks = [chunk]
        self._chunk_texts = [c.text for c in self.paper.chunks]
        self.history = []

    def search_chunks(self, query, top_k=3):
        return [c for c in self.paper.chunks if query.lower() in c.text.lower()][:top_k]

    def build_context(self, chunks, window=2):
        text = "\n".join(c.text for c in chunks)
        images = []
        for c in chunks:
            images.extend(c.images)
        return text, images

    def find_section(self, reference):
        ref_lower = reference.strip().lower()
        for i, b in enumerate(self.paper.blocks):
            if b.level > 0 and ref_lower in b.text.strip().lower():
                return self.paper.blocks[i:]
        return None


class FakeVisionClient:
    def __init__(self):
        self.calls = []

    def chat_with_images(self, text, images, system_prompt=""):
        self.calls.append((text, images, system_prompt))
        return f"图片描述: {len(images)} 张图"


def test_search_paper_tool_returns_results():
    ctx = FakeCtx()
    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store)
    search_fn = next(t for t in tools if t.name == "search_paper").callable

    result = search_fn(query="hello")
    assert "Hello world" in result.text
    assert result.resources == []


def test_search_paper_empty_results():
    ctx = FakeCtx()
    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store)
    search_fn = next(t for t in tools if t.name == "search_paper").callable

    result = search_fn(query="nonexistent")
    assert "检索结果为空" in result.text


def test_get_section_tool_finds_section():
    ctx = FakeCtx()
    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store)
    section_fn = next(t for t in tools if t.name == "get_section").callable

    result = section_fn(reference="Methods")
    assert "Methods" in result.text
    assert "More method details" in result.text


def test_get_section_not_found():
    ctx = FakeCtx()
    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store)
    section_fn = next(t for t in tools if t.name == "get_section").callable

    result = section_fn(reference="NonexistentSection")
    assert "未找到章节" in result.text


def test_get_section_truncates_long_content():
    ctx = FakeCtx()
    # Create a section with very long text
    from paper_reader.blocks import ContentBlock
    long_text = "X" * 4000
    heading = ContentBlock(type="text", text="Long Section", level=1, page_idx=0)
    body = ContentBlock(type="text", text=long_text, level=0, page_idx=0)
    ctx.paper.blocks = [heading, body]

    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store)
    section_fn = next(t for t in tools if t.name == "get_section").callable

    result = section_fn(reference="Long Section")
    assert len(result.text) <= 3100  # ~3000 + truncation notice
    assert "已截断" in result.text


def test_describe_image_tool():
    from paper_reader.agent import Resource
    vision = FakeVisionClient()
    store = {"img_1": Resource(
        type="image", id="img_1", path="/tmp/fake.png", caption="Fig 1"
    )}
    # Override load_data to avoid FS access
    store["img_1"].load_data = lambda: b"fake_image_data"

    tools = _make_tools(FakeCtx(), vision, store)
    desc_fn = next(t for t in tools if t.name == "describe_image").callable

    result = desc_fn(resource_id="img_1")
    assert "图片描述" in result.text
    assert len(vision.calls) == 1


def test_describe_image_missing_resource():
    vision = FakeVisionClient()
    tools = _make_tools(FakeCtx(), vision, {})
    desc_fn = next(t for t in tools if t.name == "describe_image").callable

    result = desc_fn(resource_id="nonexistent")
    assert "未找到资源" in result.text
    assert len(vision.calls) == 0


def test_describe_image_load_failure():
    from paper_reader.agent import Resource
    vision = FakeVisionClient()
    store = {"img_1": Resource(
        type="image", id="img_1", path="/nonexistent.png", caption=""
    )}
    tools = _make_tools(FakeCtx(), vision, store)
    desc_fn = next(t for t in tools if t.name == "describe_image").callable

    result = desc_fn(resource_id="img_1")
    assert "图片无法读取" in result.text


def test_search_paper_includes_image_resources():
    from paper_reader.blocks import ContentBlock, SemanticChunk
    ctx = FakeCtx()
    # Add a chunk with an image block
    img_block = ContentBlock(
        type="image", text="Figure 1: Architecture",
        level=0, page_idx=0,
        image_path="images/arch.png",
    )
    chunk = SemanticChunk(
        chunk_id="ch_1", text="See Figure 1 for architecture.",
        blocks=[img_block], section_path=[], images=[img_block],
    )
    ctx.paper.chunks.append(chunk)
    ctx._chunk_texts.append(chunk.text)

    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store)
    search_fn = next(t for t in tools if t.name == "search_paper").callable

    result = search_fn(query="architecture")
    assert len(result.resources) == 1
    assert result.resources[0].type == "image"
    assert result.resources[0].id == "img_0_0"


def test_tool_parameters_are_valid_json_schema():
    ctx = FakeCtx()
    tools = _make_tools(ctx, FakeVisionClient(), {})

    for tool in tools:
        params = tool.parameters
        assert params["type"] == "object"
        assert "properties" in params
        if "required" in params:
            for r in params["required"]:
                assert r in params["properties"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_agent.py::test_search_paper_tool_returns_results -v
```
Expected: FAIL with ImportError/AttributeError (no `_make_tools`)

- [ ] **Step 3: Write minimal implementation**

Append to `paper_reader/agent.py`:

```python
import json

from paper_reader.blocks import PaperMemory, ContentBlock


def _format_memory(memory: PaperMemory) -> str:
    """Serialize PaperMemory for injection into system prompt (moved from LLMRouter)."""
    lines = ["[当前论文记忆]"]
    fields = [
        ("研究问题", memory.research_problem),
        ("动机", memory.motivation),
        ("核心方法", memory.method),
        ("方法设计原理", memory.method_why),
        ("实验设计", memory.experiments),
        ("关键结果", memory.key_results),
        ("核心贡献", memory.contributions),
        ("局限性", memory.limitations),
        ("要点总结", memory.takeaways),
    ]
    for label, value in fields:
        if value and value != "未提及":
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def _tool_to_openai_schema(tool: Tool) -> dict:
    """Convert a Tool to OpenAI function-calling schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _make_tools(ctx, vision_client, resources_store: dict) -> list[Tool]:
    """Create the standard tool set for PaperAgent."""

    def search_paper(query: str) -> ToolResult:
        chunks = ctx.search_chunks(query, top_k=3)
        if not chunks:
            return ToolResult(text="[检索结果为空]")
        text, image_blocks = ctx.build_context(chunks, window=2)
        resources = []
        for i, img in enumerate(image_blocks):
            if img.image_path:
                rid = f"img_{img.page_idx}_{i}"
                full_path = str(Path(ctx.paper.result_dir) / img.image_path)
                r = Resource(type="image", id=rid, path=full_path, caption=img.text or "")
                resources.append(r)
        return ToolResult(text=text, resources=resources)

    def get_section(reference: str) -> ToolResult:
        blocks = ctx.find_section(reference)
        if blocks is None:
            return ToolResult(text=f"[未找到章节: {reference}]")
        text = "\n".join(b.text for b in blocks if b.text.strip())
        full_len = len(text)
        if full_len > 3000:
            text = text[:3000] + f"\n[已截断，原文共 {full_len} 字，请用更具体的 reference 缩小范围]"
        resources = []
        for i, b in enumerate(blocks):
            if b.type in ("image", "table") and b.image_path:
                rid = f"{b.type}_{b.page_idx}_{i}"
                full_path = str(Path(ctx.paper.result_dir) / b.image_path)
                r = Resource(type=b.type, id=rid, path=full_path, caption=b.text or "")
                resources.append(r)
        return ToolResult(text=text, resources=resources)

    def describe_image(resource_id: str) -> ToolResult:
        res = resources_store.get(resource_id)
        if res is None:
            return ToolResult(text=f"[未找到资源: {resource_id}]")
        data = res.load_data()
        if not data:
            return ToolResult(text="[图片无法读取]")
        description = vision_client.chat_with_images(
            "请详细描述这张图片的内容，包括图表类型、关键数据、趋势或结构。",
            [data],
        )
        return ToolResult(text=description)

    return [
        Tool(
            name="search_paper",
            description=(
                "在当前论文中语义检索相关段落。适合开放性问题，如'核心思想是什么'、'怎么解决XX问题'。"
                "返回相关文本片段。结果可能包含图片/表格资源引用（resources 字段），"
                "涉及图表内容时需调用 describe_image 解析。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "中文或英文检索查询"},
                },
                "required": ["query"],
            },
            callable=search_paper,
        ),
        Tool(
            name="get_section",
            description=(
                "按章节编号或标题关键词精确获取章节完整内容。"
                "适合'第3.2节讲了什么'、'实验结果是什么'这类精确引用问题。"
                "结果可能包含图片/表格资源引用（resources 字段），"
                "涉及图表内容时需调用 describe_image 解析。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "description": "章节编号如'3.2'或标题关键词如'Experiments'"},
                },
                "required": ["reference"],
            },
            callable=get_section,
        ),
        Tool(
            name="describe_image",
            description=(
                "解析图片/表格内容。传入前一步 ToolResult 中 resources 列表里的 resource id，"
                "返回图片的详细文字描述。仅当用户问题涉及图表内容时才调用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "resource_id": {"type": "string", "description": "ToolResult resources 中的 id 字段"},
                },
                "required": ["resource_id"],
            },
            callable=describe_image,
        ),
    ]
```

- [ ] **Step 4: Run tool tests to verify they pass**

```bash
python3 -m pytest tests/test_agent.py -v
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add paper_reader/agent.py tests/test_agent.py
git commit -m "feat: implement tool functions (search_paper, get_section, describe_image)"
```

---

### Task 4: Implement PaperAgent run loop

**Files:**
- Modify: `paper_reader/agent.py`

**Interfaces:**
- Produces: `PaperAgent.__init__(text_client, vision_client, ctx)`, `PaperAgent.run(question, history, memory) -> str`

- [ ] **Step 1: Write the test**

Append to `tests/test_agent.py`:

```python
from paper_reader.agent import PaperAgent


class FakeTextClient:
    """Fake text LLM client that can be scripted for multi-turn agent tests."""
    def __init__(self, responses=None):
        self.calls = []
        self._responses = responses or []
        self._idx = 0

    def chat_with_tools(self, messages, tools, system_prompt=""):
        self.calls.append({"messages": list(messages), "tools": tools, "system_prompt": system_prompt})
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        from paper_reader.agent import LLMToolResponse
        return LLMToolResponse(text="fallback answer")


class FakeVisionClient:
    def chat_with_images(self, text, images, system_prompt=""):
        return f"Vision: {text[:50]}"


def test_agent_answers_without_tools():
    """When LLM returns text with no tool_calls, return it directly."""
    from paper_reader.agent import LLMToolResponse
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[LLMToolResponse(text="直接回答")])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="你好", history=[])
    assert answer == "直接回答"
    assert len(text_client.calls) == 1


def test_agent_calls_search_paper_then_answers():
    """Two-turn: LLM calls search_paper, then returns final answer."""
    from paper_reader.agent import LLMToolResponse

    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "search_paper", "arguments": '{"query":"core idea"}'},
        }]),
        LLMToolResponse(text="根据检索结果，核心思想是..."),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="核心思想是什么？", history=[])
    assert "核心思想" in answer
    assert len(text_client.calls) == 2
    # Second call should include tool result in messages
    second_messages = text_client.calls[1]["messages"]
    tool_messages = [m for m in second_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1


def test_agent_calls_get_section():
    """Agent calls get_section tool."""
    from paper_reader.agent import LLMToolResponse

    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "get_section", "arguments": '{"reference":"Methods"}'},
        }]),
        LLMToolResponse(text="Methods 章节包含..."),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="Methods 章节讲了什么？", history=[])
    assert "Methods" in answer
    assert len(text_client.calls) == 2


def test_agent_describe_image_flow():
    """Three-turn: search_paper → describe_image → answer."""
    from paper_reader.agent import LLMToolResponse
    from paper_reader.blocks import ContentBlock, SemanticChunk

    ctx = FakeCtx()
    # Add a chunk with an image
    import tempfile, os
    tmpdir = tempfile.mkdtemp()
    img_path = os.path.join(tmpdir, "images", "arch.png")
    os.makedirs(os.path.dirname(img_path), exist_ok=True)
    with open(img_path, "wb") as f:
        f.write(b"fake_png_data")
    ctx.paper.result_dir = tmpdir

    img_block = ContentBlock(
        type="image", text="Figure 1: Architecture",
        level=0, page_idx=0, image_path="images/arch.png",
    )
    chunk = SemanticChunk(
        chunk_id="ch_img", text="See Figure 1 for architecture.",
        blocks=[img_block], section_path=[], images=[img_block],
    )
    ctx.paper.chunks.append(chunk)
    ctx._chunk_texts.append(chunk.text)

    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "search_paper", "arguments": '{"query":"architecture"}'},
        }]),
        LLMToolResponse(tool_calls=[{
            "id": "call_2",
            "type": "function",
            "function": {"name": "describe_image", "arguments": '{"resource_id":"img_0_0"}'},
        }]),
        LLMToolResponse(text="架构图展示了..."),
    ])

    vision = FakeVisionClient()
    agent = PaperAgent(text_client=text_client, vision_client=vision, ctx=ctx)

    answer = agent.run(question="描述一下架构图", history=[])
    assert "架构" in answer
    assert len(text_client.calls) == 3

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_agent_max_rounds_enforced():
    """After 7 rounds, agent returns termination message."""
    from paper_reader.agent import LLMToolResponse

    ctx = FakeCtx()
    # Always return tool_calls to force another round
    responses = [
        LLMToolResponse(tool_calls=[{
            "id": f"call_{i}",
            "type": "function",
            "function": {"name": "search_paper", "arguments": '{"query":"test"}'},
        }])
        for i in range(10)
    ]
    text_client = FakeTextClient(responses=responses)
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="test", history=[])
    assert "暂时没能找到相关信息" in answer
    assert len(text_client.calls) == 7


def test_agent_injects_memory_into_system_prompt():
    """When memory is provided, it appears in system prompt."""
    from paper_reader.agent import LLMToolResponse
    from paper_reader.blocks import PaperMemory

    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[LLMToolResponse(text="got it")])

    memory = PaperMemory(
        research_problem="测试问题",
        method="测试方法",
    )
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent.run(question="test", history=[], memory=memory)

    system_prompt = text_client.calls[0]["system_prompt"]
    assert "当前论文记忆" in system_prompt
    assert "测试问题" in system_prompt
    assert "测试方法" in system_prompt


def test_agent_handles_unknown_tool():
    """LLM hallucinates a tool name → returns error, agent doesn't crash."""
    from paper_reader.agent import LLMToolResponse

    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "nonexistent_tool", "arguments": '{}'},
        }]),
        LLMToolResponse(text="retrying after error"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="test", history=[])
    assert "retrying" in answer


def test_agent_handles_bad_arguments():
    """LLM provides bad JSON arguments → tool error, agent doesn't crash."""
    from paper_reader.agent import LLMToolResponse

    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "search_paper", "arguments": "not json"},
        }]),
        LLMToolResponse(text="recovered"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="test", history=[])
    assert "recovered" in answer


def test_agent_prints_tool_calls(capsys):
    """Agent prints tool execution log during run."""
    from paper_reader.agent import LLMToolResponse

    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "search_paper", "arguments": '{"query":"hello"}'},
        }]),
        LLMToolResponse(text="answer"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent.run(question="hello", history=[])

    captured = capsys.readouterr().out
    assert "[agent]" in captured
    assert "search_paper" in captured


def test_agent_tool_result_empty():
    """Empty retrieval result is handled gracefully."""
    from paper_reader.agent import LLMToolResponse

    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "type": "function",
            "function": {"name": "search_paper", "arguments": '{"query":"zzz_nonexistent_zzz"}'},
        }]),
        LLMToolResponse(text="没有找到相关内容"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    answer = agent.run(question="zzz nonexistent zzz", history=[])
    assert "没有找到" in answer
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_agent.py::test_agent_answers_without_tools -v
```
Expected: FAIL with ImportError/AttributeError (no `PaperAgent`)

- [ ] **Step 3: Write minimal implementation**

Append to `paper_reader/agent.py`:

```python
SYSTEM_PROMPT = """你是一个论文阅读助手。你根据提供的论文内容帮助用户理解学术论文，用中文回答问题。

准则:
- 仅根据提供的论文内容作答
- 回答准确、简洁
- 用中文回复
- 如果提供的内容不足以回答问题，请明确说明
- 讨论图表时，描述其展示的内容
- 引用章节标题来为回答提供上下文

你可以使用工具来检索论文内容。根据用户问题自主判断是否需要调用工具。"""


class PaperAgent:
    def __init__(self, text_client, vision_client, ctx):
        self._text_client = text_client
        self._vision_client = vision_client
        self._ctx = ctx
        self._resources: dict[str, Resource] = {}
        self._tools = _make_tools(ctx, vision_client, self._resources)

    def run(self, question: str, history: list[dict] | None = None,
            memory: PaperMemory | None = None) -> str:
        system = SYSTEM_PROMPT
        if memory is not None:
            system = system + "\n\n" + _format_memory(memory)

        messages = list(history) if history else []
        messages.append({"role": "user", "content": question})

        tool_schemas = [_tool_to_openai_schema(t) for t in self._tools]

        for _ in range(7):
            response = self._text_client.chat_with_tools(
                messages, tool_schemas, system_prompt=system,
            )

            if response.text and not response.tool_calls:
                return response.text

            if not response.tool_calls:
                return response.text or ""

            # Append assistant message with tool_calls
            openai_tool_calls = []
            for tc in response.tool_calls:
                fn = tc.get("function", {})
                openai_tool_calls.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": fn.get("name", tc.get("name", "")),
                        "arguments": fn.get("arguments", tc.get("arguments", "{}")),
                    },
                })
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": openai_tool_calls,
            })

            # Execute each tool call
            for tc in response.tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", tc.get("name", "unknown"))
                raw_args = fn.get("arguments", tc.get("arguments", "{}"))

                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}

                # Find and execute tool
                tool = next((t for t in self._tools if t.name == name), None)
                if tool is None:
                    result = ToolResult(text=f"[未知工具: {name}]")
                else:
                    try:
                        result = tool.callable(**args)
                    except Exception as e:
                        result = ToolResult(text=f"[工具执行失败: {e}]")

                print(f"  [agent] {name}({raw_args[:60]}{'...' if len(str(raw_args)) > 60 else ''})"
                      f" → {len(result.text)} chars, {len(result.resources)} resources")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result.text,
                })

        return "抱歉，暂时没能找到相关信息，请尝试换一个问法。"
```

- [ ] **Step 4: Run agent tests to verify they pass**

```bash
python3 -m pytest tests/test_agent.py -v
```
Expected: all tests pass

- [ ] **Step 5: Run full test suite**

```bash
python3 -m pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add paper_reader/agent.py tests/test_agent.py
git commit -m "feat: implement PaperAgent run loop with 7-round max"
```

---

### Task 5: Refactor main.py to use PaperAgent

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `PaperAgent` from `paper_reader.agent`

- [ ] **Step 1: Update handle_question**

In `main.py`, replace the `handle_question` function and remove `_is_section_query`:

Remove lines 13-15:
```python
def _is_section_query(query: str) -> bool:
    return bool(re.search(r'\bsection\b', query.lower())) or \
           bool(re.search(r'\b\d+(\.\d+)+\b', query))
```

Replace `handle_question` (lines 41-80):

```python
def handle_question(
    question: str, ctx: ConversationContext, router: LLMRouter
) -> str:
    ctx.add_message("user", question)

    from paper_reader.agent import PaperAgent
    agent = PaperAgent(
        text_client=router._text_client,
        vision_client=router._vision_client,
        ctx=ctx,
    )
    answer = agent.run(
        question=question,
        history=ctx.history[:-1],
        memory=ctx.paper.memory,
    )
    ctx.add_message("assistant", answer)
    return answer
```

Also update the import at the top of `main.py`. Remove `import re` (line 1) since it's no longer needed, and add the `PaperAgent` import (it's imported inline in the function, so no top-level import needed).

- [ ] **Step 2: Verify existing tests still pass**

```bash
python3 -m pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "refactor: delegate question handling to PaperAgent"
```

---

### Task 6: Clean up — remove duplicate SYSTEM_PROMPT from llm.py

**Files:**
- Modify: `paper_reader/llm.py`
- Modify: `paper_reader/agent.py`

**Rationale:** `SYSTEM_PROMPT` is now in `agent.py` (Task 4). The copy in `llm.py` should remain for `LLMRouter.answer()` which batch mode still uses. But `LLMRouter._format_memory()` is now duplicated in `agent.py._format_memory()`. Keep `LLMRouter._format_memory()` for `answer()` backward compatibility, no changes needed.

Actually, let me re-check. `LLMRouter.answer()` is kept for batch paper memory extraction. It uses `LLMRouter._format_memory()`. The new `PaperAgent.run()` uses `agent._format_memory()`. Both have their own copy. This is fine — no cleanup needed.

Actually, this task is a no-op. Skip it.

---

### Task 6 (revised): Final integration validation

**Files:**
- No changes — validation only

- [ ] **Step 1: Run full test suite**

```bash
python3 -m pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 2: Verify import chain works**

```bash
python3 -c "from paper_reader.agent import PaperAgent, Resource, ToolResult, Tool, _make_tools; print('agent imports OK')"
python3 -c "from paper_reader.llm import LLMRouter; print('llm imports OK')"
python3 -c "from main import handle_question; print('main imports OK')"
```
Expected: all three print OK

- [ ] **Step 3: Commit**

```bash
git add -A
git diff --cached --stat
git commit -m "chore: final validation of P0 RAG tooling integration"
```
