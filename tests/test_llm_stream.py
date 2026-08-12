from types import SimpleNamespace

from paper_reader.llm import OpenAIClient


class _FakeCompletions:
    def __init__(self, chunks):
        self._chunks = chunks
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return iter(self._chunks)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions):
        self.chat = _FakeChat(completions)


def _chunk(content=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def test_stream_yields_text_deltas():
    chunks = [_chunk(content="你好"), _chunk(content="世界")]
    client = OpenAIClient(api_key="k", model="m", base_url="http://x")
    client._client = _FakeClient(_FakeCompletions(chunks))
    events = list(client.chat_with_tools_stream(
        [{"role": "user", "content": "hi"}], []))
    deltas = [p for t, p in events if t == "text_delta"]
    assert deltas == ["你好", "世界"]
    tool_calls = [p for t, p in events if t == "tool_calls"]
    assert tool_calls == [[]]


def test_stream_accumulates_tool_call_arguments():
    tc1 = [SimpleNamespace(index=0, id="call_1",
                           function=SimpleNamespace(name="search_paper",
                                                    arguments='{"que'))]
    tc2 = [SimpleNamespace(index=0, id=None,
                           function=SimpleNamespace(name=None,
                                                    arguments='ry":"x"}'))]
    chunks = [_chunk(content=None, tool_calls=tc1),
              _chunk(content=None, tool_calls=tc2)]
    client = OpenAIClient(api_key="k", model="m", base_url="http://x")
    client._client = _FakeClient(_FakeCompletions(chunks))
    events = list(client.chat_with_tools_stream(
        [{"role": "user", "content": "hi"}], [{"type": "function"}]))
    tool_calls = [p for t, p in events if t == "tool_calls"][0]
    assert tool_calls == [{"id": "call_1", "name": "search_paper",
                           "arguments": '{"query":"x"}'}]


def test_stream_passes_stream_true_and_tools():
    chunks = [_chunk(content="ok")]
    completions = _FakeCompletions(chunks)
    client = OpenAIClient(api_key="k", model="m", base_url="http://x")
    client._client = _FakeClient(completions)
    tools = [{"type": "function"}]
    list(client.chat_with_tools_stream(
        [{"role": "user", "content": "hi"}], tools, system_prompt="sys"))
    kwargs = completions.last_kwargs
    assert kwargs["stream"] is True
    assert kwargs["tools"] == tools
    assert kwargs["model"] == "m"
