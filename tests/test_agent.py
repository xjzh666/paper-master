from paper_reader.agent import Resource, ToolResult, LLMToolResponse, Tool, _make_tools


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


# ── Tool function tests ────────────────────────────────────────────────


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
        b2 = ContentBlock(type="text", text="Methods section heading", level=1, page_idx=1)
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
    from paper_reader.blocks import ContentBlock
    long_text = "X" * 4000
    heading = ContentBlock(type="text", text="Long Section", level=1, page_idx=0)
    body = ContentBlock(type="text", text=long_text, level=0, page_idx=0)
    ctx.paper.blocks = [heading, body]

    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store)
    section_fn = next(t for t in tools if t.name == "get_section").callable

    result = section_fn(reference="Long Section")
    assert len(result.text) <= 3100
    assert "已截断" in result.text


def test_describe_image_tool():
    vision = FakeVisionClient()
    store = {
        "img_1": Resource(type="image", id="img_1", path="/tmp/fake.png", caption="Fig 1"),
    }
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
    vision = FakeVisionClient()
    store = {
        "img_1": Resource(type="image", id="img_1", path="/nonexistent.png", caption=""),
    }
    tools = _make_tools(FakeCtx(), vision, store)
    desc_fn = next(t for t in tools if t.name == "describe_image").callable

    result = desc_fn(resource_id="img_1")
    assert "图片无法读取" in result.text


def test_search_paper_includes_image_resources():
    from paper_reader.blocks import ContentBlock, SemanticChunk
    ctx = FakeCtx()
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
