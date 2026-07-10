from abc import ABC, abstractmethod
from pathlib import Path

import yaml


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], system_prompt: str = "") -> str:
        ...

    @abstractmethod
    def chat_with_images(
        self, text: str, images: list[bytes], system_prompt: str = ""
    ) -> str:
        ...


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def chat(self, messages: list[dict], system_prompt: str = "") -> str:
        system_params = {}
        if system_prompt:
            system_params["system"] = system_prompt

        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=messages,
            **system_params,
        )
        return response.content[0].text

    def chat_with_images(
        self, text: str, images: list[bytes], system_prompt: str = ""
    ) -> str:
        import base64

        content = [{"type": "text", "text": text}]
        for img_bytes in images:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })

        messages = [{"role": "user", "content": content}]
        system_params = {}
        if system_prompt:
            system_params["system"] = system_prompt

        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=messages,
            **system_params,
        )
        return response.content[0].text


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.api_key = api_key
        self.model = model
        import openai
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**kwargs)

    def chat(self, messages: list[dict], system_prompt: str = "") -> str:
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        response = self._client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            max_tokens=4096,
        )
        return response.choices[0].message.content

    def chat_with_images(
        self, text: str, images: list[bytes], system_prompt: str = ""
    ) -> str:
        import base64

        content = [{"type": "text", "text": text}]
        for img_bytes in images:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.append({"role": "user", "content": content})

        response = self._client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            max_tokens=4096,
        )
        return response.choices[0].message.content


def create_client(provider: str, config: dict) -> LLMClient:
    api_keys = config.get("api_keys", {})
    models = config.get("models", {})

    if provider == "anthropic":
        model_config = models.get("text", {})
        return AnthropicClient(
            api_key=api_keys.get("anthropic", ""),
            model=model_config.get("model", "claude-sonnet-4-6"),
        )
    elif provider == "openai":
        model_config = models.get("vision", {})
        return OpenAIClient(
            api_key=api_keys.get("openai", ""),
            model=model_config.get("model", "gpt-4o"),
            base_url=model_config.get("base_url"),
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
