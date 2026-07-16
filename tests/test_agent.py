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
