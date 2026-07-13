from abc import ABC, abstractmethod

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


SYSTEM_PROMPT = """You are a paper-reading assistant. You help users understand academic papers by answering questions based on the paper content provided to you.

Guidelines:
- Answer based only on the provided paper content
- Be accurate and concise
- If the provided content doesn't contain enough information to answer, say so
- When discussing figures or tables, describe what they show
- Use the section title to contextualize your answer"""


class LLMRouter:
    def __init__(self, config: dict):
        self._text_client = create_client(config["models"]["text"])
        self._vision_client = create_client(config["models"]["vision"])

    def answer(
        self, text: str, images: list[bytes], question: str,
        history: list[dict], title: str = "",
    ) -> str:
        content = self._build_content(text, question, title)

        if images:
            return self._vision_client.chat_with_images(
                content, images, system_prompt=SYSTEM_PROMPT
            )

        messages = list(history)
        messages.append({"role": "user", "content": content})
        return self._text_client.chat(messages, system_prompt=SYSTEM_PROMPT)

    def _build_content(self, text: str, question: str, title: str = "") -> str:
        parts = []
        if title:
            parts.append(f'From "{title}":')
        parts.append(text)
        parts.append("")
        parts.append(f"Question: {question}")
        return "\n".join(parts)


def create_client(model_config: dict) -> LLMClient:
    provider = model_config.get("provider", "openai")
    api_key = model_config.get("api_key", "")
    if not api_key:
        raise ValueError(
            f"API key is missing or empty for '{provider}' model. "
            f"Add 'api_key' under the model in config.yaml"
        )
    model = model_config.get("model", "gpt-4o")
    base_url = model_config.get("base_url")

    if provider == "anthropic":
        return AnthropicClient(api_key=api_key, model=model)
    elif provider == "openai":
        return OpenAIClient(api_key=api_key, model=model, base_url=base_url)
    else:
        raise ValueError(f"Unknown provider: {provider}")
