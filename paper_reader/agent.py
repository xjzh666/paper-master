import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from paper_reader.blocks import PaperMemory, ContentBlock


@dataclass
class Resource:
    """工具返回的资源引用，只存索引不存数据，避免上下文膨胀。"""
    type: str              # "image" | "table"
    id: str                # "img_3", "table_2"
    path: str              # 文件路径，describe_image 时才加载
    caption: str           # 图注 / 周边文本

    def load_data(self) -> bytes:
        p = Path(self.path)
        if p.exists():
            return p.read_bytes()
        return b""


@dataclass
class ToolResult:
    text: str
    resources: list[Resource] = field(default_factory=list)


@dataclass
class LLMToolResponse:
    text: str | None = None
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict       # JSON Schema
    callable: Callable[..., ToolResult]


def _format_memory(memory: PaperMemory) -> str:
    """Serialize PaperMemory for injection into system prompt."""
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


def _tool_to_openai_schema(tool: Tool) -> dict:
    """Convert a Tool to OpenAI function-calling schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _make_tools(ctx, vision_client, resources_store: dict) -> list[Tool]:
    """Create the standard tool set for PaperAgent."""

    def search_paper(query: str) -> ToolResult:
        chunks = ctx.search_chunks(query, top_k=3)
        if not chunks:
            return ToolResult(text="[检索结果为空]")
        text, image_blocks = ctx.build_context(chunks, window=2)
        resources = []
        for i, img in enumerate(image_blocks):
            if img.image_path:
                rid = f"img_{img.page_idx}_{i}"
                full_path = str(Path(ctx.paper.result_dir) / img.image_path)
                r = Resource(type="image", id=rid, path=full_path, caption=img.text or "")
                resources.append(r)
        return ToolResult(text=text, resources=resources)

    def get_section(reference: str) -> ToolResult:
        blocks = ctx.find_section(reference)
        if blocks is None:
            return ToolResult(text=f"[未找到章节: {reference}]")
        text = "\n".join(b.text for b in blocks if b.text.strip())
        full_len = len(text)
        if full_len > 3000:
            text = text[:3000] + f"\n[已截断，原文共 {full_len} 字，请用更具体的 reference 缩小范围]"
        resources = []
        for i, b in enumerate(blocks):
            if b.type in ("image", "table") and b.image_path:
                rid = f"{b.type}_{b.page_idx}_{i}"
                full_path = str(Path(ctx.paper.result_dir) / b.image_path)
                r = Resource(type=b.type, id=rid, path=full_path, caption=b.text or "")
                resources.append(r)
        return ToolResult(text=text, resources=resources)

    def describe_image(resource_id: str) -> ToolResult:
        res = resources_store.get(resource_id)
        if res is None:
            return ToolResult(text=f"[未找到资源: {resource_id}]")
        data = res.load_data()
        if not data:
            return ToolResult(text="[图片无法读取]")
        description = vision_client.chat_with_images(
            "请详细描述这张图片的内容，包括图表类型、关键数据、趋势或结构。",
            [data],
        )
        return ToolResult(text=description)

    return [
        Tool(
            name="search_paper",
            description=(
                "在当前论文中语义检索相关段落。适合开放性问题，如'核心思想是什么'、'怎么解决XX问题'。"
                "返回相关文本片段。结果可能包含图片/表格资源引用（resources 字段），"
                "涉及图表内容时需调用 describe_image 解析。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "中文或英文检索查询"},
                },
                "required": ["query"],
            },
            callable=search_paper,
        ),
        Tool(
            name="get_section",
            description=(
                "按章节编号或标题关键词精确获取章节完整内容。"
                "适合'第3.2节讲了什么'、'实验结果是什么'这类精确引用问题。"
                "结果可能包含图片/表格资源引用（resources 字段），"
                "涉及图表内容时需调用 describe_image 解析。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "description": "章节编号如'3.2'或标题关键词如'Experiments'"},
                },
                "required": ["reference"],
            },
            callable=get_section,
        ),
        Tool(
            name="describe_image",
            description=(
                "解析图片/表格内容。传入前一步 ToolResult 中 resources 列表里的 resource id，"
                "返回图片的详细文字描述。仅当用户问题涉及图表内容时才调用。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "resource_id": {"type": "string", "description": "ToolResult resources 中的 id 字段"},
                },
                "required": ["resource_id"],
            },
            callable=describe_image,
        ),
    ]


SYSTEM_PROMPT = """你是一个论文阅读助手。你根据提供的论文内容帮助用户理解学术论文，用中文回答问题。

准则:
- 仅根据提供的论文内容作答
- 回答准确、简洁
- 用中文回复
- 如果提供的内容不足以回答问题，请明确说明
- 讨论图表时，描述其展示的内容
- 引用章节标题来为回答提供上下文

你可以使用工具来检索论文内容。根据用户问题自主判断是否需要调用工具。"""


class PaperAgent:
    def __init__(self, text_client, vision_client, ctx):
        self._text_client = text_client
        self._vision_client = vision_client
        self._ctx = ctx
        self._resources: dict[str, Resource] = {}
        self._tools = _make_tools(ctx, vision_client, self._resources)

    def run(self, question: str, history: list[dict] | None = None,
            memory: PaperMemory | None = None) -> str:
        system = SYSTEM_PROMPT
        if memory is not None:
            system = system + "\n\n" + _format_memory(memory)

        messages = list(history) if history else []
        messages.append({"role": "user", "content": question})

        tool_schemas = [_tool_to_openai_schema(t) for t in self._tools]

        for _ in range(7):
            response = self._text_client.chat_with_tools(
                messages, tool_schemas, system_prompt=system,
            )

            if response.text and not response.tool_calls:
                return response.text

            if not response.tool_calls:
                return response.text or ""

            # Append assistant message with tool_calls
            openai_tool_calls = []
            for tc in response.tool_calls:
                openai_tool_calls.append({
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc["arguments"] if isinstance(tc["arguments"], str) else json.dumps(tc["arguments"]),
                    },
                })
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": openai_tool_calls,
            })

            # Execute each tool call
            for tc in response.tool_calls:
                name = tc["name"]
                raw_args = tc["arguments"]

                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {}

                tool = next((t for t in self._tools if t.name == name), None)
                if tool is None:
                    result = ToolResult(text=f"[未知工具: {name}]")
                else:
                    try:
                        result = tool.callable(**args)
                    except Exception as e:
                        result = ToolResult(text=f"[工具执行失败: {e}]")

                print(f"  [agent] {name}({str(raw_args)[:60]}{'...' if len(str(raw_args)) > 60 else ''})"
                      f" → {len(result.text)} chars, {len(result.resources)} resources")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result.text,
                })

        return "抱歉，暂时没能找到相关信息，请尝试换一个问法。"
