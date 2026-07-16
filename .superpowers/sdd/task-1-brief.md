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
