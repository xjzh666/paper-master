from paper_reader.agent import Resource, ToolResult, LLMToolResponse, Tool, _make_tools, PaperAgent, _match_figure_alias


def test_match_figure_alias_finds_fig_2():
    from paper_reader.blocks import SemanticChunk
    chunk = SemanticChunk(
        chunk_id="c1", text="figure content",
        blocks=[], section_path=[], images=[],
        aliases=["Fig. 2", "Figure 2", "图2"],
    )
    result = _match_figure_alias([chunk], "讲解一下 Figure 2")
    assert len(result) == 1


def test_match_figure_alias_finds_table_1():
    from paper_reader.blocks import SemanticChunk
    chunk = SemanticChunk(
        chunk_id="c1", text="table content",
        blocks=[], section_path=[], images=[],
        aliases=["Table 1", "表1"],
    )
    result = _match_figure_alias([chunk], "Table 1 的数据是什么")
    assert len(result) == 1


def test_match_figure_alias_no_match():
    from paper_reader.blocks import SemanticChunk
    chunk = SemanticChunk(
        chunk_id="c1", text="text",
        blocks=[], section_path=[], images=[],
        aliases=["Fig. 1", "Figure 1"],
    )
    result = _match_figure_alias([chunk], "讲解一下 Figure 2")
    assert len(result) == 0


def test_match_figure_alias_not_a_figure_query():
    from paper_reader.blocks import SemanticChunk
    chunk = SemanticChunk(chunk_id="c1", text="text", blocks=[], section_path=[], images=[])
    result = _match_figure_alias([chunk], "核心贡献是什么")
    assert len(result) == 0


def test_search_paper_exact_match_includes_figure_resource():
    """When query contains 'Figure 2', alias match should find the image resource."""
    from paper_reader.blocks import ContentBlock, SemanticChunk
    ctx = FakeCtx()
    img_block = ContentBlock(
        type="image", text="Fig. 2. Architecture",
        level=0, page_idx=6,
        image_path="images/fig2.png",
    )
    chunk = SemanticChunk(
        chunk_id="ch_fig2", text="The system architecture is shown in Fig. 2.",
        blocks=[img_block], section_path=[], images=[img_block],
        aliases=["Fig. 2", "Figure 2"],
    )
    ctx.paper.chunks.append(chunk)
    ctx._chunk_texts.append(chunk.text)

    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store)
    search_fn = next(t for t in tools if t.name == "search_paper").callable

    result = search_fn(query="讲解一下 Figure 2")
    assert len(result.resources) == 1
    assert result.resources[0].id == "image_6_0"


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
    assert "image_0_0" in result.text  # resource ID exposed to LLM


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


# ── PaperAgent tests ───────────────────────────────────────────────────


class FakeTextClient:
    """Fake text LLM client scriptable for multi-turn agent tests."""
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
        return LLMToolResponse(text="fallback answer")


def test_agent_answers_without_tools():
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[LLMToolResponse(text="直接回答")])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="你好", history=[])
    assert answer == "直接回答"
    assert len(text_client.calls) == 1


def test_agent_calls_search_paper_then_answers():
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "search_paper",
            "arguments": '{"query":"core idea"}',
        }]),
        LLMToolResponse(text="根据检索结果，核心思想是..."),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="核心思想是什么？", history=[])
    assert "核心思想" in answer
    assert len(text_client.calls) == 2
    second_messages = text_client.calls[1]["messages"]
    tool_messages = [m for m in second_messages if m["role"] == "tool"]
    assert len(tool_messages) == 1


def test_agent_calls_get_section():
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "get_section",
            "arguments": '{"reference":"Methods"}',
        }]),
        LLMToolResponse(text="Methods 章节包含..."),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="Methods 章节讲了什么？", history=[])
    assert "Methods" in answer
    assert len(text_client.calls) == 2


def test_agent_describe_image_flow():
    from paper_reader.blocks import ContentBlock, SemanticChunk
    import tempfile, os

    ctx = FakeCtx()
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
            "name": "search_paper",
            "arguments": '{"query":"architecture"}',
        }]),
        LLMToolResponse(tool_calls=[{
            "id": "call_2",
            "name": "describe_image",
            "arguments": '{"resource_id":"image_0_0"}',
        }]),
        LLMToolResponse(text="架构图展示了..."),
    ])

    vision = FakeVisionClient()
    agent = PaperAgent(text_client=text_client, vision_client=vision, ctx=ctx)

    answer = agent.run(question="描述一下架构图", history=[])
    assert "架构" in answer
    assert len(text_client.calls) == 3
    assert len(vision.calls) == 1

    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_agent_max_rounds_enforced():
    ctx = FakeCtx()
    responses = [
        LLMToolResponse(tool_calls=[{
            "id": f"call_{i}",
            "name": "search_paper",
            "arguments": '{"query":"test"}',
        }])
        for i in range(10)
    ]
    text_client = FakeTextClient(responses=responses)
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="test", history=[])
    assert "暂时没能找到相关信息" in answer
    assert len(text_client.calls) == 7


def test_agent_injects_memory_into_system_prompt():
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
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "nonexistent_tool",
            "arguments": '{}',
        }]),
        LLMToolResponse(text="retrying after error"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="test", history=[])
    assert "retrying" in answer


def test_agent_handles_bad_arguments():
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "search_paper",
            "arguments": "not json",
        }]),
        LLMToolResponse(text="recovered"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="test", history=[])
    assert "recovered" in answer


def test_agent_prints_tool_calls(capsys):
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "search_paper",
            "arguments": '{"query":"hello"}',
        }]),
        LLMToolResponse(text="answer"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent.run(question="hello", history=[])

    captured = capsys.readouterr().out
    assert "[agent]" in captured
    assert "search_paper" in captured


def test_agent_tool_result_empty():
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "search_paper",
            "arguments": '{"query":"zzz_nonexistent_zzz"}',
        }]),
        LLMToolResponse(text="没有找到相关内容"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    answer = agent.run(question="zzz nonexistent zzz", history=[])
    assert "没有找到" in answer
