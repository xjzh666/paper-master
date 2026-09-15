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
    tools = _make_tools(ctx, FakeVisionClient(), store, [])
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
        self.observations = []
        self.image_descriptions = None

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
    tools = _make_tools(ctx, FakeVisionClient(), store, [])
    search_fn = next(t for t in tools if t.name == "search_paper").callable

    result = search_fn(query="hello")
    assert "Hello world" in result.text
    assert result.resources == []


def test_search_paper_empty_results():
    ctx = FakeCtx()
    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store, [])
    search_fn = next(t for t in tools if t.name == "search_paper").callable

    result = search_fn(query="nonexistent")
    assert "检索结果为空" in result.text


def test_get_section_tool_finds_section():
    ctx = FakeCtx()
    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store, [])
    section_fn = next(t for t in tools if t.name == "get_section").callable

    result = section_fn(reference="Methods")
    assert "Methods" in result.text
    assert "More method details" in result.text


def test_get_section_not_found():
    ctx = FakeCtx()
    store = {}
    tools = _make_tools(ctx, FakeVisionClient(), store, [])
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
    tools = _make_tools(ctx, FakeVisionClient(), store, [])
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

    tools = _make_tools(FakeCtx(), vision, store, [])
    desc_fn = next(t for t in tools if t.name == "describe_image").callable

    result = desc_fn(resource_id="img_1")
    assert "图片描述" in result.text
    assert len(vision.calls) == 1


def test_describe_image_missing_resource():
    vision = FakeVisionClient()
    tools = _make_tools(FakeCtx(), vision, {}, [])
    desc_fn = next(t for t in tools if t.name == "describe_image").callable

    result = desc_fn(resource_id="nonexistent")
    assert "未找到资源" in result.text
    assert len(vision.calls) == 0


def test_describe_image_load_failure():
    vision = FakeVisionClient()
    store = {
        "img_1": Resource(type="image", id="img_1", path="/nonexistent.png", caption=""),
    }
    tools = _make_tools(FakeCtx(), vision, store, [])
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
    tools = _make_tools(ctx, FakeVisionClient(), store, [])
    search_fn = next(t for t in tools if t.name == "search_paper").callable

    result = search_fn(query="architecture")
    assert len(result.resources) == 1
    assert result.resources[0].type == "image"
    assert "image_0_0" in result.text  # resource ID exposed to LLM


def test_tool_parameters_are_valid_json_schema():
    ctx = FakeCtx()
    tools = _make_tools(ctx, FakeVisionClient(), {}, [])

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


# ── _compact_messages tests ────────────────────────────────────────────


def test_compact_messages_preserves_recent_three_rounds():
    """最近 3 轮 tool result 保持完整，更早的压缩。"""
    from paper_reader.agent import PaperAgent
    ctx = FakeCtx()
    agent = PaperAgent(text_client=FakeTextClient(), vision_client=FakeVisionClient(), ctx=ctx)
    for i in range(5):
        agent._tool_round_map[f"call_{i}"] = i

    long_old = "A" * 500
    messages = [
        {"role": "tool", "tool_call_id": "call_0", "content": long_old},
        {"role": "tool", "tool_call_id": "call_1", "content": long_old},
        {"role": "tool", "tool_call_id": "call_2", "content": "结果2"},
        {"role": "tool", "tool_call_id": "call_3", "content": "结果3"},
        {"role": "tool", "tool_call_id": "call_4", "content": "结果4"},
    ]

    compacted = agent._compact_messages(messages, current_round=5)

    tool_msgs = [m for m in compacted if m["role"] == "tool"]
    assert "已截断" in tool_msgs[0]["content"]  # round 0 压缩
    assert "已截断" in tool_msgs[1]["content"]  # round 1 压缩
    assert tool_msgs[2]["content"] == "结果2"   # round 2 完整保留
    assert tool_msgs[3]["content"] == "结果3"   # round 3 完整保留
    assert tool_msgs[4]["content"] == "结果4"   # round 4 完整保留


def test_compact_messages_replaces_old_round_with_observation():
    """更早的往轮 tool result 被 observation 摘要替换。"""
    from paper_reader.agent import PaperAgent, Observation
    ctx = FakeCtx()
    agent = PaperAgent(text_client=FakeTextClient(), vision_client=FakeVisionClient(), ctx=ctx)
    agent._tool_round_map["call_0"] = 0
    agent._tool_round_map["call_4"] = 4
    agent._observations = [Observation(summary="注意力机制的核心是 QKV", round_num=1)]

    messages = [
        {"role": "tool", "tool_call_id": "call_0", "content": "很长的旧结果"},
        {"role": "tool", "tool_call_id": "call_4", "content": "最新结果"},
    ]

    compacted = agent._compact_messages(messages, current_round=5)

    tool_msgs = [m for m in compacted if m["role"] == "tool"]
    assert "已记录观察" in tool_msgs[0]["content"]  # round 0 → observation
    assert "注意力机制的核心是 QKV" in tool_msgs[0]["content"]
    assert tool_msgs[1]["content"] == "最新结果"     # round 4 完整保留


def test_compact_messages_fallback_truncate_when_no_observation():
    """无 observation 时降级为智能截断。"""
    from paper_reader.agent import PaperAgent
    ctx = FakeCtx()
    agent = PaperAgent(text_client=FakeTextClient(), vision_client=FakeVisionClient(), ctx=ctx)
    agent._tool_round_map["call_0"] = 0
    agent._tool_round_map["call_4"] = 4

    old_text = "A" * 500
    messages = [
        {"role": "tool", "tool_call_id": "call_0", "content": old_text},
        {"role": "tool", "tool_call_id": "call_4", "content": "新结果"},
    ]

    compacted = agent._compact_messages(messages, current_round=5)

    tool_msgs = [m for m in compacted if m["role"] == "tool"]
    assert "已截断" in tool_msgs[0]["content"]  # round 0 截断
    assert len(tool_msgs[0]["content"]) < len(old_text)
    assert tool_msgs[1]["content"] == "新结果"   # round 4 完整保留


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
        # 第 2-3 轮：继续搜（凑够轮次，触发保留最近 3 轮后的压缩）
        LLMToolResponse(tool_calls=[{
            "id": "call_4",
            "name": "search_paper",
            "arguments": '{"query":"result"}',
        }]),
        LLMToolResponse(tool_calls=[{
            "id": "call_5",
            "name": "search_paper",
            "arguments": '{"query":"analysis"}',
        }]),
        # 第 4 轮：回答
        LLMToolResponse(text="根据检索，方法使用了梯度下降..."),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="这篇论文的方法是什么？", history=[])

    assert "梯度下降" in answer
    assert len(text_client.calls) == 5

    # 第 5 轮发送时（call index=4），第 0 轮结果已被 observation 替换
    fifth_call_messages = text_client.calls[4]["messages"]
    tool_msgs = [m for m in fifth_call_messages if m["role"] == "tool"]
    # 第 0 轮的 search_paper 结果应已被 observation 替换（不含 # 编号）
    obs_replacements = [m for m in tool_msgs if m["content"].startswith("[已记录观察] ")]
    assert len(obs_replacements) == 1


def test_agent_injects_observations_into_system_prompt():
    """验证累积的 session observations 注入到 system prompt 中。"""
    from paper_reader.agent import PaperAgent, Observation
    ctx = FakeCtx()
    ctx.observations = [
        Observation(summary="方法使用强化学习", facts=["PPO算法"], question="方法是什么"),
        Observation(summary="在ImageNet上验证", facts=["Top-1 85%"]),
    ]

    text_client = FakeTextClient(responses=[
        LLMToolResponse(text="已回答"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    agent.run(question="总结方法", history=[])

    system_prompt = text_client.calls[0]["system_prompt"]
    assert "已知信息" in system_prompt
    assert "强化学习" in system_prompt
    assert "ImageNet" in system_prompt
    assert "问: 方法是什么" in system_prompt


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


def test_agent_injects_toc_into_system_prompt():
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[LLMToolResponse(text="got it")])

    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent.run(question="test", history=[])

    system_prompt = text_client.calls[0]["system_prompt"]
    assert "论文章节目录" in system_prompt
    assert "Methods section heading" in system_prompt


# ── session observation 持久化 ───────────────────────────────────────────

def test_observation_dict_roundtrip():
    from paper_reader.agent import Observation
    obs = Observation(summary="摘要", facts=["f1"], entities=["e1"],
                      sources=["p1 §1"], question="问题?", round_num=2)
    assert Observation.from_dict(obs.to_dict()) == obs


def test_run_flushes_observations_to_session_store():
    from paper_reader.agent import PaperAgent
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "record_observation",
            "arguments": '{"summary":"训练用了8张GPU","sources":["p5 §5.2"]}',
        }]),
        LLMToolResponse(text="已回答"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent.run(question="训练硬件？", history=[])

    assert len(ctx.observations) == 1
    assert ctx.observations[0].summary == "训练用了8张GPU"
    assert ctx.observations[0].question == "训练硬件？"


def test_second_run_sees_first_run_observations():
    from paper_reader.agent import PaperAgent
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1", "name": "record_observation",
            "arguments": '{"summary":"BLEU 28.4 on EN-DE"}',
        }]),
        LLMToolResponse(text="第一问答案"),
        LLMToolResponse(text="第二问答案"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent.run(question="结果如何？", history=[])
    agent.run(question="追问", history=[])

    second_prompt = text_client.calls[2]["system_prompt"]
    assert "BLEU 28.4" in second_prompt
    assert "问: 结果如何？" in second_prompt
    # 不重复 flush
    assert len(ctx.observations) == 1


def test_session_observation_injection_limited_to_recent():
    from paper_reader.agent import PaperAgent, Observation, SESSION_OBSERVATION_LIMIT
    ctx = FakeCtx()
    ctx.observations = [Observation(summary=f"发现{i}") for i in range(25)]
    text_client = FakeTextClient(responses=[LLMToolResponse(text="ok")])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)
    agent.run(question="q", history=[])

    prompt = text_client.calls[0]["system_prompt"]
    assert "发现24" in prompt
    assert f"发现{25 - SESSION_OBSERVATION_LIMIT}" in prompt
    assert "发现4" not in prompt  # 最旧的被截掉


def test_describe_image_uses_cache_when_available():
    ctx = FakeCtx()
    ctx.image_descriptions = {"images/a.png": "缓存的描述"}
    vision = FakeVisionClient()
    store = {"img_1": Resource(type="image", id="img_1",
                               path="/tmp/test_result/images/a.png", caption="Fig 1")}
    tools = _make_tools(ctx, vision, store, [])
    desc_fn = next(t for t in tools if t.name == "describe_image").callable

    result = desc_fn(resource_id="img_1")
    assert result.text == "缓存的描述"
    assert len(vision.calls) == 0


def test_describe_image_caches_api_result():
    ctx = FakeCtx()
    ctx.image_descriptions = {}
    vision = FakeVisionClient()
    res = Resource(type="image", id="img_1",
                   path="/tmp/test_result/images/a.png", caption="Fig 1")
    res.load_data = lambda: b"fake_image_data"
    store = {"img_1": res}
    tools = _make_tools(ctx, vision, store, [])
    desc_fn = next(t for t in tools if t.name == "describe_image").callable

    result = desc_fn(resource_id="img_1")
    assert "图片描述" in result.text
    assert ctx.image_descriptions["images/a.png"] == result.text
    # 第二次调用走缓存，不再调 vision API
    assert desc_fn(resource_id="img_1").text == result.text
    assert len(vision.calls) == 1


# ── P3 citation source labels ([src chunk_N §<标题> p.<页>]) ───────────


class CitationCtx:
    """Fake ctx with controllable retrieval order and block→chunk object mapping.

    build_context mirrors the real ConversationContext at window=0: dedup + paper
    order. search_chunks returns the configured retrieval order, which may differ.
    """

    def __init__(self, chunks, blocks, retrieval_order=None):
        from paper_reader.blocks import PaperDocument
        self.paper = PaperDocument(
            filepath="/tmp/test.pdf", title="Test Paper", result_dir="/tmp/test_result",
        )
        self.paper.chunks = list(chunks)
        self.paper.blocks = list(blocks)
        self._retrieval_order = list(retrieval_order) if retrieval_order else list(chunks)
        self.history = []
        self.observations = []
        self.image_descriptions = None

    def search_chunks(self, query, top_k=3):
        return list(self._retrieval_order)[:top_k]

    def build_context(self, chunks, window=2):
        index = {id(c): i for i, c in enumerate(self.paper.chunks)}
        ordered = sorted({index[id(c)] for c in chunks if id(c) in index})
        text = "\n\n".join(self.paper.chunks[i].text for i in ordered)
        images = []
        for i in ordered:
            images.extend(self.paper.chunks[i].images)
        return text, images

    def find_section(self, reference):
        ref = reference.strip().lower()
        heading_idx = None
        heading_level = 0
        for i, b in enumerate(self.paper.blocks):
            if b.level > 0 and ref in b.text.strip().lower():
                heading_idx = i
                heading_level = b.level
                break
        if heading_idx is None:
            return None
        result = []
        for b in self.paper.blocks[heading_idx:]:
            if result and b.level > 0 and b.level <= heading_level:
                break
            result.append(b)
        return result


def _citation_search_fn(ctx):
    tools = _make_tools(ctx, FakeVisionClient(), {}, [])
    return next(t for t in tools if t.name == "search_paper").callable


def _citation_section_fn(ctx):
    tools = _make_tools(ctx, FakeVisionClient(), {}, [])
    return next(t for t in tools if t.name == "get_section").callable


def test_search_paper_labels_each_chunk_in_retrieval_order():
    from paper_reader.blocks import ContentBlock, SemanticChunk
    b_a1 = ContentBlock(type="text", text="3.2 Method", level=1, page_idx=3)
    b_a2 = ContentBlock(type="text", text="We propose the SOTK scheme.", level=0, page_idx=3)
    chunk_a = SemanticChunk(chunk_id="chunk_0", text="3.2 Method\nWe propose the SOTK scheme.",
                            blocks=[b_a1, b_a2], section_path=["3.2 Method"])
    b_b1 = ContentBlock(type="text", text="Intro text", level=0, page_idx=0)
    chunk_b = SemanticChunk(chunk_id="chunk_5", text="Intro text",
                            blocks=[b_b1], section_path=[])
    # 检索顺序 [chunk_b, chunk_a] 不同于 paper 顺序：标签必须按检索顺序排
    ctx = CitationCtx(chunks=[chunk_a, chunk_b], blocks=[b_b1, b_a1, b_a2],
                      retrieval_order=[chunk_b, chunk_a])

    result = _citation_search_fn(ctx)(query="anything")
    assert result.text == (
        "[src chunk_5 p.1]\n"
        "Intro text\n"
        "\n"
        "[src chunk_0 §3.2 Method p.4]\n"
        "3.2 Method\n"
        "We propose the SOTK scheme."
    )
    assert result.resources == []


def test_search_paper_label_strips_html_and_takes_min_page():
    from paper_reader.blocks import ContentBlock, SemanticChunk
    b1 = ContentBlock(type="text", text="First page of discussion", level=0, page_idx=7)
    b2 = ContentBlock(type="text", text="Second page", level=0, page_idx=8)
    chunk = SemanticChunk(chunk_id="chunk_2", text="First page of discussion\nSecond page",
                          blocks=[b1, b2], section_path=["<h1>6 Discussion</h1>"])
    ctx = CitationCtx(chunks=[chunk], blocks=[b1, b2])

    result = _citation_search_fn(ctx)(query="discussion")
    assert result.text.startswith("[src chunk_2 §6 Discussion p.8]\n")


def test_search_paper_alias_path_has_labels_and_resources():
    from paper_reader.blocks import ContentBlock, SemanticChunk
    img = ContentBlock(type="image", text="Fig. 2. Architecture", level=0, page_idx=6,
                       image_path="images/fig2.png")
    chunk = SemanticChunk(chunk_id="chunk_3", text="Fig. 2. Architecture",
                          blocks=[img], section_path=["3 Method"], images=[img],
                          aliases=["Fig. 2", "Figure 2"])
    ctx = CitationCtx(chunks=[chunk], blocks=[img])

    result = _citation_search_fn(ctx)(query="讲解一下 Figure 2")
    # alias 命中路径同样带标签；图片资源收集与「可用资源」附录行为不变
    assert "[src chunk_3 §3 Method p.7]\nFig. 2. Architecture" in result.text
    assert len(result.resources) == 1
    assert "可用资源" in result.text
    assert "image_6_0" in result.text


def test_get_section_groups_blocks_by_chunk_with_labels():
    from paper_reader.blocks import ContentBlock, SemanticChunk
    h0 = ContentBlock(type="text", text="3 Method", level=1, page_idx=3)
    h1 = ContentBlock(type="text", text="3.2 Setup", level=2, page_idx=3)
    m1 = ContentBlock(type="text", text="We propose SOTK.", level=0, page_idx=4)
    h2 = ContentBlock(type="text", text="3.3 Results", level=2, page_idx=7)
    e1 = ContentBlock(type="text", text="We evaluate on 200 nodes.", level=0, page_idx=8)
    chunk_a = SemanticChunk(chunk_id="chunk_0", text="3 Method\n3.2 Setup\nWe propose SOTK.",
                            blocks=[h0, h1, m1], section_path=["3 Method", "3.2 Setup"])
    chunk_b = SemanticChunk(chunk_id="chunk_2", text="3.3 Results\nWe evaluate on 200 nodes.",
                            blocks=[h2, e1], section_path=["3 Method", "3.3 Results"])
    ctx = CitationCtx(chunks=[chunk_a, chunk_b], blocks=[h0, h1, m1, h2, e1])

    result = _citation_section_fn(ctx)(reference="3 Method")
    assert result.text == (
        "[src chunk_0 §3.2 Setup p.4]\n"
        "3 Method\n"
        "3.2 Setup\n"
        "We propose SOTK.\n"
        "\n"
        "[src chunk_2 §3.3 Results p.8]\n"
        "3.3 Results\n"
        "We evaluate on 200 nodes."
    )


def test_get_section_truncation_keeps_group_label():
    from paper_reader.blocks import ContentBlock, SemanticChunk
    h = ContentBlock(type="text", text="5 Results", level=1, page_idx=2)
    body = ContentBlock(type="text", text="R" * 4000, level=0, page_idx=2)
    chunk = SemanticChunk(chunk_id="chunk_7", text="5 Results\n" + "R" * 4000,
                          blocks=[h, body], section_path=["5 Results"])
    ctx = CitationCtx(chunks=[chunk], blocks=[h, body])

    result = _citation_section_fn(ctx)(reference="Results")
    # 截断发生在组内时，该组标签已在截断前的文本里
    assert "[src chunk_7 §5 Results p.3]" in result.text
    assert result.text.index("[src chunk_7 §5 Results p.3]") < 3000
    assert "已截断" in result.text
    assert len(result.text) <= 3100


def test_get_section_unmapped_blocks_have_no_label():
    from paper_reader.blocks import ContentBlock
    h = ContentBlock(type="text", text="6 Discussion", level=1, page_idx=0)
    b = ContentBlock(type="text", text="We discuss limitations.", level=0, page_idx=0)
    ctx = CitationCtx(chunks=[], blocks=[h, b])

    result = _citation_section_fn(ctx)(reference="6 Discussion")
    # block 找不到所属 chunk → 该组无标签、不报错
    assert "[src" not in result.text
    assert "We discuss limitations." in result.text


# ── P3 citation protocol (SYSTEM_PROMPT + record_observation sources) ──


def test_system_prompt_contains_citation_link_format():
    """引用协议段给出可点击引用链接格式（要点 1：链接格式说明）。"""
    from paper_reader.agent import SYSTEM_PROMPT
    assert "(cite:chunk_" in SYSTEM_PROMPT
    assert "[§<编号> p.<页>](cite:chunk_<N>)" in SYSTEM_PROMPT


def test_system_prompt_chunk_ids_from_visible_src_labels_only():
    """编号来源约束：chunk_<N> 只能取当前上下文可见 [src ...] 标签里的编号，禁止编造（要点 2）。"""
    from paper_reader.agent import SYSTEM_PROMPT
    assert "[src" in SYSTEM_PROMPT
    assert "编造" in SYSTEM_PROMPT


def test_system_prompt_unnumbered_section_link_format():
    """无编号章节（Abstract/References 等）的链接写法（要点 3）。"""
    from paper_reader.agent import SYSTEM_PROMPT
    assert "[p.<页>](cite:chunk_N)" in SYSTEM_PROMPT


def test_system_prompt_no_link_when_label_compacted():
    """压缩约束：往轮工具结果被压缩、标签已不在上下文时宁可不加链接（要点 4，对应 KEEP_RECENT_ROUNDS）。"""
    from paper_reader.agent import SYSTEM_PROMPT
    assert "压缩" in SYSTEM_PROMPT
    assert "宁可不加链接" in SYSTEM_PROMPT


def test_record_observation_sources_description_uses_src_label_format():
    """sources 参数描述沿用检索标签格式，例值含 chunk_ 编号。"""
    ctx = FakeCtx()
    tools = _make_tools(ctx, FakeVisionClient(), {}, [])
    tool = next(t for t in tools if t.name == "record_observation")
    desc = tool.parameters["properties"]["sources"]["description"]
    assert "chunk_" in desc
    assert "['chunk_3 §3.2 p.4']" in desc


# ── search_external_papers tool (P6.1 外部论文搜索) ────────────────────


def _fake_arxiv_result(arxiv_id, title, authors, published):
    from paper_reader.arxiv_search import ArxivResult
    return ArxivResult(
        arxiv_id=arxiv_id, title=title, authors=authors, abstract="Abstract text.",
        published=published, updated=published, categories=["cs.CL"],
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
    )


def _external_search_fn():
    tools = _make_tools(FakeCtx(), FakeVisionClient(), {}, [])
    return next(t for t in tools if t.name == "search_external_papers").callable


def test_search_external_papers_in_tool_list():
    """工具集含 search_external_papers，schema 有 query（必填）与 max_results（可选）。"""
    ctx = FakeCtx()
    tools = _make_tools(ctx, FakeVisionClient(), {}, [])
    tool = next(t for t in tools if t.name == "search_external_papers")
    props = tool.parameters["properties"]
    assert props["query"]["type"] == "string"
    assert "query" in tool.parameters["required"]
    assert props["max_results"]["type"] == "integer"
    assert "max_results" not in tool.parameters["required"]


def test_search_external_papers_formats_numbered_list(monkeypatch):
    """打桩返回 (2 条, "arxiv") → 编号列表（标题/年份/作者/arxiv_id）+ 尾部
    arxiv_id 提示；参数原样转发；source=="arxiv" 时输出与无兜底版逐字一致。"""
    from paper_reader import arxiv_search
    calls = []

    def fake_fallback(query, max_results=10):
        calls.append((query, max_results))
        return [
            _fake_arxiv_result("1706.03762", "Attention Is All You Need",
                               ["A Vaswani", "N Shazeer"], "2015-06-12T00:00:00Z"),
            _fake_arxiv_result("2005.14165", "Language Models are Few-Shot Learners",
                               ["T Brown"], "2020-05-28T00:00:00Z"),
        ], "arxiv", ""

    monkeypatch.setattr(arxiv_search, "search_with_fallback", fake_fallback)
    result = _external_search_fn()(query="rag", max_results=2)

    assert calls == [("rag", 2)]  # (query, max_results) 原样转发
    lines = result.text.split("\n")
    assert lines[0] == ("1. Attention Is All You Need (2015) — "
                        "A Vaswani, N Shazeer [arxiv_id: 1706.03762]")
    assert lines[1] == ("2. Language Models are Few-Shot Learners (2020) — "
                        "T Brown [arxiv_id: 2005.14165]")
    assert lines[2] == ""  # 列表后空一行
    assert lines[3] == "提示：可把上述 arxiv_id 提供给用户，在 Web 端打开对应论文。"
    assert result.resources == []


def test_search_external_papers_empty_results(monkeypatch):
    """打桩返回 ([], "arxiv") → 恰为 '[外部检索无结果]'。"""
    from paper_reader import arxiv_search
    monkeypatch.setattr(arxiv_search, "search_with_fallback",
                        lambda query, max_results=10: ([], "arxiv", ""))

    result = _external_search_fn()(query="nonexistent topic")
    assert result.text == "[外部检索无结果]"
    assert result.resources == []


def test_search_external_papers_openalex_fallback_header(monkeypatch):
    """source=="openalex" → 文本首行兜底标注，其余格式不变。"""
    from paper_reader import arxiv_search
    calls = []

    def fake_fallback(query, max_results=10):
        calls.append((query, max_results))
        return [
            _fake_arxiv_result("2312.10997", "RAPTOR: Recursive Abstractive Processing",
                               ["S Saroff"], "2023-12-18T00:00:00Z"),
        ], "openalex", "[arXiv 暂不可用，以下为 OpenAlex 兜底结果]"

    monkeypatch.setattr(arxiv_search, "search_with_fallback", fake_fallback)
    result = _external_search_fn()(query="raptor", max_results=1)

    assert calls == [("raptor", 1)]
    lines = result.text.split("\n")
    assert lines[0] == "[arXiv 暂不可用，以下为 OpenAlex 兜底结果]"
    assert lines[1] == ("1. RAPTOR: Recursive Abstractive Processing (2023) — "
                        "S Saroff [arxiv_id: 2312.10997]")
    assert lines[2] == ""  # 列表后空一行
    assert lines[3] == "提示：可把上述 arxiv_id 提供给用户，在 Web 端打开对应论文。"
    assert result.resources == []


def test_search_external_papers_openalex_empty_results(monkeypatch):
    """source=="openalex" 且空结果 → 首行兜底标注 + [外部检索无结果]。"""
    from paper_reader import arxiv_search
    monkeypatch.setattr(arxiv_search, "search_with_fallback",
                        lambda query, max_results=10: (
                            [], "openalex", "[arXiv 暂不可用，以下为 OpenAlex 兜底结果]"))

    result = _external_search_fn()(query="nonexistent topic")

    assert result.text == ("[arXiv 暂不可用，以下为 OpenAlex 兜底结果]"
                           "\n[外部检索无结果]")
    assert result.resources == []


def test_search_external_papers_rate_limit_falls_back(monkeypatch):
    """Oracle：arXiv 打桩抛 ArxivRateLimitError、OpenAlex 打桩返回 1 条
    （走真 search_with_fallback 编排）→ 工具文本首行为兜底标注。"""
    from paper_reader import arxiv_search
    import paper_reader.openalex_search as openalex_search

    def rate_limited(query, max_results=10):
        raise arxiv_search.ArxivRateLimitError()

    monkeypatch.setattr(arxiv_search, "search", rate_limited)
    monkeypatch.setattr(
        openalex_search, "search",
        lambda query, max_results=10: [
            _fake_arxiv_result("2312.10997", "RAPTOR", ["S Saroff"],
                               "2023-12-18T00:00:00Z"),
        ])

    result = _external_search_fn()(query="raptor")

    assert result.text.split("\n")[0] == "[arXiv 暂不可用，以下为 OpenAlex 兜底结果]"


def test_search_external_papers_error_becomes_tool_failure(monkeypatch):
    """工具自身不吞异常：search_with_fallback 抛错（双源皆败）由 agent
    循环兜底转成 '[工具执行失败: ...]'。"""
    from paper_reader import arxiv_search

    def boom(query, max_results=10):
        raise ConnectionError("network down")

    monkeypatch.setattr(arxiv_search, "search_with_fallback", boom)

    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[
        LLMToolResponse(tool_calls=[{
            "id": "call_1",
            "name": "search_external_papers",
            "arguments": '{"query":"rag","max_results":2}',
        }]),
        LLMToolResponse(text="外部检索暂时失败"),
    ])
    agent = PaperAgent(text_client=text_client, vision_client=FakeVisionClient(), ctx=ctx)

    answer = agent.run(question="帮我找 rag 方向的论文", history=[])
    assert answer == "外部检索暂时失败"
    tool_msgs = [m for m in text_client.calls[1]["messages"] if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "[工具执行失败: network down]"
