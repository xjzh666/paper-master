from abc import ABC, abstractmethod

import yaml

from paper_reader.blocks import PaperMemory


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


SYSTEM_PROMPT = """你是一个论文阅读助手。你根据提供的论文内容帮助用户理解学术论文，用中文回答问题。

准则:
- 仅根据提供的论文内容作答
- 回答准确、简洁
- 用中文回复
- 如果提供的内容不足以回答问题，请明确说明
- 讨论图表时，描述其展示的内容
- 引用章节标题来为回答提供上下文"""


class LLMRouter:
    def __init__(self, config: dict):
        self._text_client = create_client(config["models"]["text"])
        self._vision_client = create_client(config["models"]["vision"])

    def _format_memory(self, memory: PaperMemory) -> str:
        """Serialize PaperMemory for injection into system prompt."""
        # Note: keywords intentionally omitted — reserved for future multi-paper routing
        lines = ["[当前论文记忆]"]
        fields = [
            ("研究问题", memory.research_problem),
            ("动机", memory.motivation),
            ("核心方法", memory.method),
            ("方法设计原理", memory.method_why),
            ("实验设计", memory.experiments),
            ("关键结果", memory.key_results),
            ("核心贡献", memory.contributions),
            ("局限性", memory.limitations),
            ("要点总结", memory.takeaways),
        ]
        for label, value in fields:
            if value and value != "未提及":
                lines.append(f"- {label}: {value}")
        return "\n".join(lines)

    def answer(
        self, text: str, images: list[bytes], question: str,
        history: list[dict], title: str = "",
        memory: PaperMemory | None = None,
    ) -> str:
        content = self._build_content(text, question, title)

        # Build system prompt with optional memory
        system = SYSTEM_PROMPT
        if memory is not None:
            system = system + "\n\n" + self._format_memory(memory)

        if images:
            print(f"  [路由: vision]")
            return self._vision_client.chat_with_images(
                content, images, system_prompt=system
            )

        print(f"  [路由: text]")
        messages = list(history)
        messages.append({"role": "user", "content": content})
        return self._text_client.chat(messages, system_prompt=system)

    def _build_content(self, text: str, question: str, title: str = "") -> str:
        parts = []
        if title:
            parts.append(f'论文: "{title}"')
        parts.append(text)
        parts.append("")
        parts.append(f"问题: {question}")
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
