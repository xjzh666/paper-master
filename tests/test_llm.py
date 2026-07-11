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


from unittest.mock import MagicMock
from paper_reader.llm import LLMRouter
from paper_reader.parser import Section


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

    section = Section(
        title="Methods",
        level=1,
        text="Some text content",
        page_start=0,
        page_end=0,
    )
    result = router.answer(section, "What method?", [])

    assert len(text_client.calls) == 1
    assert len(vision_client.calls) == 0


def test_router_uses_vision_model_when_images_present():
    text_client = FakeClient()
    vision_client = FakeClient()
    router = LLMRouter.__new__(LLMRouter)
    router._text_client = text_client
    router._vision_client = vision_client

    section = Section(
        title="Results",
        level=1,
        text="Some text",
        page_start=0,
        page_end=0,
        images=[MagicMock(image_bytes=b"fake_image")],
    )
    result = router.answer(section, "Show results", [])

    assert len(vision_client.calls) == 1


def test_router_formats_section_content():
    text_client = FakeClient()
    vision_client = FakeClient()
    router = LLMRouter.__new__(LLMRouter)
    router._text_client = text_client
    router._vision_client = vision_client

    section = Section(
        title="2. Methods",
        level=1,
        text="Method text here.",
        page_start=1,
        page_end=2,
    )
    result = router.answer(section, "What is the method?", [])

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
