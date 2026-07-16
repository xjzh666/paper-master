import pytest
import tempfile
import yaml
from paper_reader.llm import (
    load_config,
    create_client,
    AnthropicClient,
    OpenAIClient,
)


@pytest.fixture
def config_file():
    config = {
        "models": {
            "text": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key": "test-anthropic-key",
            },
            "vision": {
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "test-openai-key",
            },
        },
    }
    tmp = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w")
    yaml.dump(config, tmp)
    tmp.close()
    yield tmp.name
    import os

    os.unlink(tmp.name)


def test_load_config_returns_dict(config_file):
    config = load_config(config_file)
    assert isinstance(config, dict)
    assert "models" in config


def test_load_config_has_text_model(config_file):
    config = load_config(config_file)
    assert config["models"]["text"]["provider"] == "anthropic"


def test_create_anthropic_client(config_file):
    config = load_config(config_file)
    client = create_client(config["models"]["text"])
    assert isinstance(client, AnthropicClient)


def test_create_openai_client(config_file):
    config = load_config(config_file)
    client = create_client(config["models"]["vision"])
    assert isinstance(client, OpenAIClient)


def test_anthropic_client_chat_returns_string(config_file):
    config = load_config(config_file)
    client = create_client(config["models"]["text"])
    assert client.model == "claude-sonnet-4-6"
    assert client.api_key == "test-anthropic-key"


def test_openai_client_chat_returns_string(config_file):
    config = load_config(config_file)
    client = create_client(config["models"]["vision"])
    assert client.model == "gpt-4o"
    assert client.api_key == "test-openai-key"


from paper_reader.llm import LLMRouter


class FakeClient:
    """Fake LLM client that records calls without real API."""

    def __init__(self):
        self.calls = []

    def chat(self, messages, system_prompt=""):
        self.calls.append(("chat", messages, system_prompt))
        return "text model response"

    def chat_with_images(self, text, images, system_prompt=""):
        self.calls.append(("chat_with_images", text, images, system_prompt))
        return "vision model response"


def test_router_uses_text_model_when_no_images():
    text_client = FakeClient()
    vision_client = FakeClient()
    router = LLMRouter.__new__(LLMRouter)
    router._text_client = text_client
    router._vision_client = vision_client

    result = router.answer(
        text="Some text content", images=[], question="What method?",
        history=[], title="Methods",
    )

    assert len(text_client.calls) == 1
    assert len(vision_client.calls) == 0


def test_router_uses_vision_model_when_images_present():
    text_client = FakeClient()
    vision_client = FakeClient()
    router = LLMRouter.__new__(LLMRouter)
    router._text_client = text_client
    router._vision_client = vision_client

    result = router.answer(
        text="Some text", images=[b"fake_image"], question="Show results",
        history=[], title="Results",
    )

    assert len(vision_client.calls) == 1


def test_router_formats_section_content():
    text_client = FakeClient()
    vision_client = FakeClient()
    router = LLMRouter.__new__(LLMRouter)
    router._text_client = text_client
    router._vision_client = vision_client

    result = router.answer(
        text="Method text here.", images=[], question="What is the method?",
        history=[], title="2. Methods",
    )

    call_messages = text_client.calls[0][1]
    user_message = call_messages[-1]["content"]
    assert "2. Methods" in user_message
    assert "Method text here." in user_message


def test_create_client_raises_on_missing_api_key():
    """create_client should raise when api_key is missing or empty."""
    with pytest.raises(ValueError, match="API key is missing"):
        create_client({"provider": "openai", "model": "gpt-4o"})

    with pytest.raises(ValueError, match="API key is missing"):
        create_client({"provider": "openai", "model": "gpt-4o", "api_key": ""})


def test_llm_router_constructor_with_valid_config():
    """LLMRouter(config) should construct successfully."""
    config = {
        "models": {
            "text": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key": "test-key",
            },
            "vision": {
                "provider": "openai",
                "model": "gpt-4o",
                "api_key": "test-key",
            },
        },
    }
    router = LLMRouter(config)
    assert router._text_client is not None
    assert router._vision_client is not None


def test_llm_router_constructor_raises_on_missing_keys():
    """LLMRouter(config) should raise when API keys are missing."""
    config = {
        "models": {
            "text": {"provider": "openai", "model": "gpt-4o-mini"},
            "vision": {"provider": "openai", "model": "gpt-4o"},
        },
    }
    with pytest.raises(ValueError):
        LLMRouter(config)


def test_router_answer_text_only():
    from paper_reader.llm import LLMRouter

    class FakeText:
        def chat(self, messages, system_prompt=""):
            return "text response"

    class FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return "vision response"

    router = LLMRouter.__new__(LLMRouter)
    router._text_client = FakeText()
    router._vision_client = FakeVision()

    result = router.answer(
        text="some content", images=[], question="what?",
        history=[], title="Test",
    )
    assert result == "text response"


def test_router_answer_with_images():
    from paper_reader.llm import LLMRouter

    class FakeText:
        def chat(self, messages, system_prompt=""):
            return "text response"

    class FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return f"vision with {len(images)} images"

    router = LLMRouter.__new__(LLMRouter)
    router._text_client = FakeText()
    router._vision_client = FakeVision()

    result = router.answer(
        text="content with figure", images=[b"img1", b"img2"],
        question="explain", history=[], title="Test",
    )
    assert "2 images" in result


def test_build_content_includes_title_and_question():
    from paper_reader.llm import LLMRouter

    router = LLMRouter.__new__(LLMRouter)
    content = router._build_content("body text", "what is this?", "My Paper")
    assert "My Paper" in content
    assert "body text" in content
    assert "what is this?" in content


def test_router_injects_memory_into_system_prompt():
    """When memory is provided, it should appear in the system prompt."""
    from paper_reader.blocks import PaperMemory

    class FakeText:
        def chat(self, messages, system_prompt=""):
            return system_prompt  # Return the system prompt for inspection

    class FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return system_prompt

    router = LLMRouter.__new__(LLMRouter)
    router._text_client = FakeText()
    router._vision_client = FakeVision()

    memory = PaperMemory(
        research_problem="如何测试？",
        method="注入测试",
        keywords=["test"],
    )

    result = router.answer(
        text="content", images=[], question="q?",
        history=[], title="T", memory=memory,
    )

    assert "当前论文记忆" in result
    assert "如何测试？" in result
    assert "注入测试" in result


def test_router_skips_memory_when_none():
    """When memory is None, system prompt should be the default."""
    class FakeText:
        def chat(self, messages, system_prompt=""):
            return system_prompt

    class FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return system_prompt

    router = LLMRouter.__new__(LLMRouter)
    router._text_client = FakeText()
    router._vision_client = FakeVision()

    result = router.answer(
        text="content", images=[], question="q?",
        history=[], title="T", memory=None,
    )

    assert "当前论文记忆" not in result


def test_router_omits_weizhi_fields_in_memory():
    """Fields with '未提及' should not appear in the formatted memory."""
    from paper_reader.blocks import PaperMemory

    class FakeText:
        def chat(self, messages, system_prompt=""):
            return system_prompt

    class FakeVision:
        def chat_with_images(self, text, images, system_prompt=""):
            return system_prompt

    router = LLMRouter.__new__(LLMRouter)
    router._text_client = FakeText()
    router._vision_client = FakeVision()

    memory = PaperMemory(
        research_problem="真实问题",
        method="真实方法",
        motivation="未提及",
        experiments="未提及",
    )

    result = router.answer(
        text="content", images=[], question="q?",
        history=[], title="T", memory=memory,
    )

    assert "真实问题" in result
    assert "动机" not in result
    assert "实验设计" not in result


def test_openai_chat_with_tools_returns_tool_calls():
    from unittest.mock import Mock
    from paper_reader.llm import OpenAIClient
    from paper_reader.agent import LLMToolResponse

    client = OpenAIClient(api_key="test-key", model="gpt-4o")

    tc = Mock()
    tc.id = "call_001"
    tc.function.name = "search_paper"
    tc.function.arguments = '{"query":"test query"}'

    msg = Mock()
    msg.tool_calls = [tc]
    msg.content = None

    choice = Mock()
    choice.message = msg
    response = Mock()
    response.choices = [choice]

    client._client = Mock()
    client._client.chat.completions.create = Mock(return_value=response)

    tools = [{
        "type": "function",
        "function": {
            "name": "search_paper",
            "description": "搜索论文内容",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    }]

    result = client.chat_with_tools(
        messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        system_prompt="You are helpful.",
    )

    assert isinstance(result, LLMToolResponse)
    assert result.text is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "search_paper"


def test_openai_chat_with_tools_returns_text_when_no_tool_calls():
    from unittest.mock import Mock
    from paper_reader.llm import OpenAIClient

    client = OpenAIClient(api_key="test-key", model="gpt-4o")

    msg = Mock()
    msg.tool_calls = None
    msg.content = "plain text answer"

    choice = Mock()
    choice.message = msg
    response = Mock()
    response.choices = [choice]

    client._client = Mock()
    client._client.chat.completions.create = Mock(return_value=response)

    result = client.chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    )

    assert result.text == "plain text answer"
    assert result.tool_calls == []
