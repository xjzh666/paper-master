from paper_reader.agent import PaperAgent, LLMToolResponse
from tests.test_agent import FakeCtx, FakeVisionClient, FakeTextClient


class FakeStreamTextClient:
    """Fake LLM client exposing chat_with_tools_stream for agent streaming tests."""
    def __init__(self, streams=None):
        self.calls = []
        self._streams = streams or []
        self._idx = 0

    def chat_with_tools_stream(self, messages, tools, system_prompt=""):
        self.calls.append({"messages": list(messages), "tools": tools,
                           "system_prompt": system_prompt})
        if self._idx < len(self._streams):
            evs = self._streams[self._idx]
            self._idx += 1
        else:
            evs = [("text_delta", "fallback"), ("tool_calls", [])]
        yield from evs


def test_run_stream_emits_tool_and_answer_events():
    ctx = FakeCtx()
    text_client = FakeStreamTextClient(streams=[
        [("text_delta", "让我查一下"),
         ("tool_calls", [{"id": "call_1", "name": "search_paper",
                          "arguments": '{"query":"x"}'}])],
        [("text_delta", "核心思想"),
         ("text_delta", "是注意力机制"),
         ("tool_calls", [])],
    ])
    agent = PaperAgent(text_client=text_client,
                       vision_client=FakeVisionClient(), ctx=ctx)
    events: list[tuple[str, dict]] = []
    answer = agent.run_stream(question="Q", history=[],
                              on_event=lambda t, p: events.append((t, p)))
    assert answer == "核心思想是注意力机制"
    types = [e[0] for e in events]
    assert types == ["answer_chunk", "clear", "tool_start", "tool_result",
                     "answer_chunk", "answer_chunk"]
    assert len(text_client.calls) == 2


def test_run_stream_no_tools_no_clear():
    ctx = FakeCtx()
    text_client = FakeStreamTextClient(streams=[
        [("text_delta", "直接回答"), ("tool_calls", [])],
    ])
    agent = PaperAgent(text_client=text_client,
                       vision_client=FakeVisionClient(), ctx=ctx)
    events: list[tuple[str, dict]] = []
    answer = agent.run_stream(question="Q", history=[],
                              on_event=lambda t, p: events.append((t, p)))
    assert answer == "直接回答"
    assert [e[0] for e in events] == ["answer_chunk"]


def test_run_stream_pure_tool_round_emits_no_clear():
    """Tool round with no text emits no answer_chunk/clear."""
    ctx = FakeCtx()
    text_client = FakeStreamTextClient(streams=[
        [("tool_calls", [{"id": "c1", "name": "search_paper",
                          "arguments": '{"query":"x"}'}])],
        [("text_delta", "结果"), ("tool_calls", [])],
    ])
    agent = PaperAgent(text_client=text_client,
                       vision_client=FakeVisionClient(), ctx=ctx)
    events: list[tuple[str, dict]] = []
    answer = agent.run_stream(question="Q", history=[],
                              on_event=lambda t, p: events.append((t, p)))
    assert answer == "结果"
    types = [e[0] for e in events]
    assert types == ["tool_start", "tool_result", "answer_chunk"]
    assert "clear" not in types


def test_run_stream_cap_emits_fallback_answer_chunk():
    ctx = FakeCtx()
    streams = [[("tool_calls", [{"id": f"c{i}", "name": "search_paper",
                                 "arguments": '{"query":"x"}'}])] for i in range(8)]
    text_client = FakeStreamTextClient(streams=streams)
    agent = PaperAgent(text_client=text_client,
                       vision_client=FakeVisionClient(), ctx=ctx)
    events: list[tuple[str, dict]] = []
    answer = agent.run_stream(question="Q", history=[],
                              on_event=lambda t, p: events.append((t, p)))
    assert answer == "抱歉，暂时没能找到相关信息，请尝试换一个问法。"
    chunks = [p["delta"] for t, p in events if t == "answer_chunk"]
    assert any("抱歉" in c for c in chunks)


def test_run_stream_synthesis_round_emits_answer_chunks():
    """轮次耗尽且已有 observations → 第 8 次空工具合成调用，其 text_delta
    逐段以 answer_chunk 发出。"""
    ctx = FakeCtx()
    streams = [[("tool_calls", [{"id": f"c{i}", "name": "search_paper",
                                 "arguments": '{"query":"x"}'}])] for i in range(6)]
    streams.append([("tool_calls", [{"id": "c_obs", "name": "record_observation",
                                     "arguments": '{"summary":"发现"}'}])])
    streams.append([("text_delta", "根据已收集信息"),
                    ("text_delta", "：部分回答"),
                    ("tool_calls", [])])
    text_client = FakeStreamTextClient(streams=streams)
    agent = PaperAgent(text_client=text_client,
                       vision_client=FakeVisionClient(), ctx=ctx)
    events: list[tuple[str, dict]] = []
    answer = agent.run_stream(question="Q", history=[],
                              on_event=lambda t, p: events.append((t, p)))

    assert answer == "根据已收集信息：部分回答"
    chunks = [p["delta"] for t, p in events if t == "answer_chunk"]
    assert chunks == ["根据已收集信息", "：部分回答"]
    assert len(text_client.calls) == 8
    assert text_client.calls[7]["tools"] == []
    assert text_client.calls[7]["messages"][-1]["role"] == "user"


def test_run_still_works_non_stream():
    ctx = FakeCtx()
    text_client = FakeTextClient(responses=[LLMToolResponse(text="fallback")])
    agent = PaperAgent(text_client=text_client,
                       vision_client=FakeVisionClient(), ctx=ctx)
    answer = agent.run(question="Q", history=[])
    assert answer == "fallback"
    assert len(text_client.calls) == 1  # non-streaming chat_with_tools used
