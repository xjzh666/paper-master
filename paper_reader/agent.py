import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import paper_reader.arxiv_search as arxiv_search
from paper_reader.blocks import ContentBlock, PaperDocument, PaperMemory, SemanticChunk
from paper_reader.observations import load_image_descriptions, save_image_descriptions


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
class Observation:
    """LLM 在每轮检索后记录的结构化观察。"""
    summary: str
    round_num: int = -1     # 记录该观察的 agent 轮次
    facts: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    question: str = ""      # 产生该观察的用户提问（flush 到 session 时标记）

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "facts": list(self.facts),
            "entities": list(self.entities),
            "sources": list(self.sources),
            "question": self.question,
            "round_num": self.round_num,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Observation":
        return cls(
            summary=str(d.get("summary", "")),
            facts=[str(x) for x in d.get("facts", [])],
            entities=[str(x) for x in d.get("entities", [])],
            sources=[str(x) for x in d.get("sources", [])],
            question=str(d.get("question", "")),
            round_num=int(d.get("round_num", -1)),
        )


def _smart_truncate(text: str, max_chars: int = 300) -> str:
    """在句子边界截断文本，避免断句。"""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    for sep in ['. ', '。', '\n', '；', '; ']:
        idx = truncated.rfind(sep)
        if idx > max_chars * 0.5:
            truncated = truncated[:idx + len(sep)]
            break
    return truncated.rstrip() + f"\n[已截断，原文共 {len(text)} 字]"


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


def _format_toc(paper: PaperDocument) -> str:
    """Serialize section headings for injection into system prompt."""
    headings = [b.text.strip() for b in paper.blocks if b.level > 0 and b.text.strip()]
    if not headings:
        return ""
    lines = ["[论文章节目录]"]
    lines.extend(f"- {h}" for h in headings[:50])
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


def _match_figure_alias(chunks: list, query: str) -> list:
    """Match figure/table references in query against chunk aliases.

    Supports: Figure 2, Fig. 3, Table 1, 图2, 图 2, 表1, etc.
    """
    # Match Figure/Fig/Table/图/表 + optional dot + number
    m = re.search(r'(Fig(?:ure)?|Table|图|表)\s*\.?\s*(\d+)', query, re.IGNORECASE)
    if not m:
        return []
    label = f"{m.group(1)} {m.group(2)}"
    label_dot = f"{m.group(1)}. {m.group(2)}"
    matched = []
    for chunk in chunks:
        aliases_lower = [a.lower() for a in chunk.aliases]
        if label.lower() in aliases_lower or label_dot.lower() in aliases_lower:
            matched.append(chunk)
    return matched


def _chunk_src_label(chunk: SemanticChunk) -> str:
    """来源标签：[src chunk_<N> §<标题> p.<页>]。

    - 标题 = section_path 末条剥 HTML 标签；section_path 为空则省略 § 部分
    - 页码 = 组内块的最小 page_idx + 1（page_idx 0-based），格式 p.4
    """
    section = ""
    if chunk.section_path:
        section = re.sub(r"<[^>]+>", "", chunk.section_path[-1]).strip()
    page_part = ""
    if chunk.blocks:
        page_part = f" p.{min(b.page_idx for b in chunk.blocks) + 1}"
    if section:
        return f"[src {chunk.chunk_id} §{section}{page_part}]"
    return f"[src {chunk.chunk_id}{page_part}]"


def _labeled_chunks_text(chunks: list[SemanticChunk]) -> str:
    """按给定（检索）顺序拼接 chunk 文本，每组前置一行 [src] 标签。"""
    return "\n\n".join(f"{_chunk_src_label(c)}\n{c.text}" for c in chunks)


def _group_blocks_by_chunk(
        blocks: list[ContentBlock],
        chunks: list[SemanticChunk]) -> list[tuple[SemanticChunk | None, list[ContentBlock]]]:
    """把连续的、属于同一 chunk 的 block 归为一组（对象身份匹配）。

    返回 [(chunk | None, blocks)]；block 找不到所属 chunk 时组为 None（无标签）。
    """
    owner: dict[int, SemanticChunk] = {}
    for c in chunks:
        for b in c.blocks:
            owner[id(b)] = c
    groups: list[tuple[SemanticChunk | None, list[ContentBlock]]] = []
    for b in blocks:
        chunk = owner.get(id(b))
        if groups and groups[-1][0] is chunk:
            groups[-1][1].append(b)
        else:
            groups.append((chunk, [b]))
    return groups


def _relative_image_path(ctx, full_path: str) -> str | None:
    """Resource path → path relative to the paper's result_dir (stable cache key)."""
    try:
        return str(Path(full_path).resolve().relative_to(
            Path(ctx.paper.result_dir).resolve()))
    except (ValueError, OSError):
        return None


def _image_description_cache(ctx) -> dict:
    """Lazy-load the persisted image-description cache onto ctx."""
    if getattr(ctx, "image_descriptions", None) is None:
        ctx.image_descriptions = load_image_descriptions(ctx.paper.filepath)
    return ctx.image_descriptions


def _make_tools(ctx, vision_client, resources_store: dict, observations_store: list) -> list[Tool]:
    """Create the standard tool set for PaperAgent."""

    def search_paper(query: str) -> ToolResult:
        # Exact alias match for figure/table references (Fig. 2, Table 1, 图3, etc.)
        alias_chunks = _match_figure_alias(ctx.paper.chunks, query)
        if alias_chunks:
            chunks = alias_chunks
        else:
            chunks = ctx.search_chunks(query, top_k=3)
            if not chunks:
                return ToolResult(text="[检索结果为空]")
        # 图片资源仍经 build_context 收集（行为不变）；文本按检索顺序重建并加 [src] 标签
        _, image_blocks = ctx.build_context(chunks, window=0)
        text = _labeled_chunks_text(chunks)
        resources = []
        for i, img in enumerate(image_blocks):
            if img.image_path:
                rid = f"{img.type}_{img.page_idx}_{i}"
                full_path = str(Path(ctx.paper.result_dir) / img.image_path)
                r = Resource(type=img.type, id=rid, path=full_path, caption=img.text or "")
                resources.append(r)
                resources_store[rid] = r
        if resources:
            lines = [text, "", "可用资源:"]
            for r in resources:
                lines.append(f"  [{r.id}] {r.caption or r.type}")
            text = "\n".join(lines)
        return ToolResult(text=text, resources=resources)

    def get_section(reference: str) -> ToolResult:
        blocks = ctx.find_section(reference)
        if blocks is None:
            return ToolResult(text=f"[未找到章节: {reference}]")
        # 按 block→chunk 归组，每组前置该 chunk 的 [src] 标签（映射缺失的组无标签）
        parts: list[str] = []
        for chunk, group_blocks in _group_blocks_by_chunk(blocks, ctx.paper.chunks):
            body = "\n".join(b.text for b in group_blocks if b.text.strip())
            if not body:
                continue
            if chunk is not None:
                parts.append(f"{_chunk_src_label(chunk)}\n{body}")
            else:
                parts.append(body)
        text = "\n\n".join(parts)
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
                resources_store[rid] = r
        if resources:
            lines = [text, "", "可用资源:"]
            for r in resources:
                lines.append(f"  [{r.id}] {r.caption or r.type}")
            text = "\n".join(lines)
        return ToolResult(text=text, resources=resources)

    def describe_image(resource_id: str) -> ToolResult:
        res = resources_store.get(resource_id)
        if res is None:
            return ToolResult(text=f"[未找到资源: {resource_id}]")
        # 图像描述是论文级产物：按图片相对路径缓存，避免重复调 vision API
        rel_path = _relative_image_path(ctx, res.path)
        cache = _image_description_cache(ctx)
        if rel_path is not None and rel_path in cache:
            return ToolResult(text=cache[rel_path])
        data = res.load_data()
        if not data:
            return ToolResult(text="[图片无法读取]")
        description = vision_client.chat_with_images(
            "请详细描述这张图片的内容，包括图表类型、关键数据、趋势或结构。",
            [data],
        )
        if rel_path is not None:
            cache[rel_path] = description
            save_image_descriptions(ctx.paper.filepath, cache)
        return ToolResult(text=description)

    def record_observation(summary: str, facts: list[str] | None = None,
                           entities: list[str] | None = None,
                           sources: list[str] | None = None) -> ToolResult:
        obs = Observation(
            summary=summary,
            facts=facts or [],
            entities=entities or [],
            sources=sources or [],
        )
        observations_store.append(obs)
        parts = [f"[已记录观察 #{len(observations_store)}] {summary}"]
        if facts:
            parts.append("关键事实: " + "; ".join(facts))
        return ToolResult(text="\n".join(parts))

    def search_external_papers(query: str, max_results: int = 10) -> ToolResult:
        # 异常不在此捕获：网络错误由 agent 循环统一兜底为 [工具执行失败: ...]
        results = arxiv_search.search(query, max_results)
        if not results:
            return ToolResult(text="[外部检索无结果]")
        lines = [
            f"{i}. {r.title} ({r.published[:4]}) — {', '.join(r.authors)} "
            f"[arxiv_id: {r.arxiv_id}]"
            for i, r in enumerate(results, start=1)
        ]
        lines.append("")
        lines.append("提示：可把上述 arxiv_id 提供给用户，在 Web 端打开对应论文。")
        return ToolResult(text="\n".join(lines))

    return [
        Tool(
            name="search_paper",
            description=(
                "Search the current paper for semantically relevant passages. Use for open-ended "
                "questions such as 'what is the core idea' or 'how does the method solve X'. "
                "Returns text snippets from relevant chunks. May include figure/table resource "
                "references (resources field) — if so, call describe_image to analyze their content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in English (paper content is in English)"},
                },
                "required": ["query"],
            },
            callable=search_paper,
        ),
        Tool(
            name="get_section",
            description=(
                "Retrieve the full content of a specific section by section number or heading keyword. "
                "Use for precise-reference questions such as 'what does section 3.2 cover' or "
                "'what are the experimental results'. May include figure/table resource references "
                "(resources field) — if so, call describe_image to analyze their content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reference": {"type": "string", "description": "Section number like '3.2' or heading keyword like 'Experiments'"},
                },
                "required": ["reference"],
            },
            callable=get_section,
        ),
        Tool(
            name="describe_image",
            description=(
                "Analyze the content of an image or table. Pass the resource id from the resources "
                "field of a previous ToolResult. Returns a detailed textual description of the image. "
                "Only call this when the user's question involves figure or table content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "resource_id": {"type": "string", "description": "The id field from a ToolResult's resources list"},
                },
                "required": ["resource_id"],
            },
            callable=describe_image,
        ),
        Tool(
            name="record_observation",
            description=(
                "Record the key findings of the current retrieval round as a structured observation. "
                "Call this AFTER reviewing the results returned by search_paper or get_section to "
                "summarize what you learned this round — this preserves knowledge across rounds and "
                "keeps the conversation context compact. summary is a one-sentence summary of the "
                "findings; facts is a list of key facts; entities is a list of key concepts/methods/"
                "metrics; sources is provenance in the retrieval label format like "
                "['chunk_3 §3.2 p.4']."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "One-sentence summary of the key findings from this round"},
                    "facts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of key facts learned this round",
                    },
                    "entities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Key concepts, methods, or metrics involved",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Provenance annotations reusing the [src ...] labels attached to the "
                            "retrieved text, e.g. ['chunk_3 §3.2 p.4']"
                        ),
                    },
                },
                "required": ["summary"],
            },
            callable=record_observation,
        ),
        Tool(
            name="search_external_papers",
            description=(
                "Search arXiv for external papers by keyword, beyond the currently open "
                "paper and the local library. Use when the user asks to find papers or "
                "survey a research direction (e.g. '帮我找某方向的论文'). Returns a "
                "numbered list with title, year, authors and arxiv_id; the arxiv_id can "
                "be given to the user to open the corresponding paper in the Web UI."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in English (arXiv metadata is in English)"},
                    "max_results": {"type": "integer", "description": "Maximum number of results to return, default 10"},
                },
                "required": ["query"],
            },
            callable=search_external_papers,
        ),
    ]


KEEP_RECENT_ROUNDS = 3  # 压缩时保留最近几轮 tool result 完整

SESSION_OBSERVATION_LIMIT = 20  # 注入 system prompt 的 session 观察条数上限


SYSTEM_PROMPT = """你是一个论文阅读助手。你根据提供的论文内容帮助用户理解学术论文。

准则:
- 仅根据提供的论文内容作答
- 回答准确、简洁
- 最终回答用中文
- 工具调用参数（检索查询、章节引用、观察记录）一律用英文，因为论文内容是英文
- 如果提供的内容不足以回答问题，请明确说明
- 讨论图表时，描述其展示的内容
- 引用章节标题来为回答提供上下文
- get_section 的 reference 一律从[论文章节目录]中选取，不要猜测章节名或编号
- 拿到足够的检索结果后就应该尝试回答，不要反复更换查询词搜索
- describe_image 返回"[图片无法读取]"说明图片文件不可用，直接用已有文本回答即可，不要再重试
- 如果连续两次检索都没有找到新信息，请基于已有内容作答
- 每次调用 search_paper 或 get_section 后，请同时调用 record_observation 记录本轮关键发现，便于后续推理时回顾
- record_observation 的记录标准：有独立价值的事实（关键数字、实验设置、结论性陈述）即使与当前问题无直接关系也应记录，并始终在 sources 注明出处

引用来源标注:
- search_paper / get_section 返回的每组文本前带有来源标签 [src chunk_N §标题 p.页]，标明该段内容的出处
- 最终回答中，关键陈述（实验数据、结论、方法要点）后附引用链接，格式为 [§<编号> p.<页>](cite:chunk_<N>)，例如「……准确率达 92% [§5.1 p.6](cite:chunk_4)。」
- 章节没有编号时（如 Abstract、References），链接文本写 [p.<页>](cite:chunk_N)，例如 [p.1](cite:chunk_0)
- 链接中的 chunk_<N> 只能取当前上下文中可见 [src ...] 标签里出现过的编号，禁止编造
- 早期轮次的工具结果会被压缩，若 [src ...] 标签已不在当前上下文中，宁可不加链接

你可以使用工具来检索论文内容。根据用户问题自主判断是否需要调用工具。"""


class PaperAgent:
    def __init__(self, text_client, vision_client, ctx):
        self._text_client = text_client
        self._vision_client = vision_client
        self._ctx = ctx
        self._resources: dict[str, Resource] = {}
        self._observations: list[Observation] = []
        self._tool_round_map: dict[str, int] = {}
        self._tools = _make_tools(ctx, vision_client, self._resources, self._observations)

    def _record_tool_round(self, tool_call_id: str, round_num: int) -> None:
        self._tool_round_map[tool_call_id] = round_num

    def _compact_messages(self, messages: list[dict], current_round: int) -> list[dict]:
        """替换往轮 tool result 为 observation 摘要或截断。

        保留最近 KEEP_RECENT_ROUNDS 轮完整（含刚执行完的那轮，模型能回读证据），
        更早的往轮替换为对应 observation 摘要，无 observation 则截断降级。
        """
        compacted: list[dict] = []
        for msg in messages:
            if msg["role"] == "tool":
                tc_id = msg.get("tool_call_id", "")
                round_num = self._tool_round_map.get(tc_id)
                if round_num is not None and round_num < current_round - KEEP_RECENT_ROUNDS:
                    # 观察记录在 round R+1 总结 round R 的结果
                    matching = [o for o in self._observations if o.round_num == round_num + 1]
                    obs = matching[0] if matching else None
                    if obs is not None:
                        compacted.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"[已记录观察] {obs.summary}",
                        })
                    else:
                        compacted.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": _smart_truncate(msg["content"], max_chars=300),
                        })
                    continue
            compacted.append(msg)
        return compacted

    def run(self, question: str, history: list[dict] | None = None,
            memory: PaperMemory | None = None) -> str:
        return self._run_loop(question, history, memory, None, False)

    def run_stream(self, question: str, history: list[dict] | None = None,
                   memory: PaperMemory | None = None,
                   on_event: Callable[[str, dict], None] | None = None) -> str:
        return self._run_loop(question, history, memory, on_event, True)

    def _run_loop(self, question: str, history: list[dict] | None = None,
                  memory: PaperMemory | None = None,
                  on_event: Callable[[str, dict], None] | None = None,
                  stream: bool = False) -> str:
        system = SYSTEM_PROMPT
        if memory is not None:
            system = system + "\n\n" + _format_memory(memory)
        toc = _format_toc(self._ctx.paper)
        if toc:
            system = system + "\n\n" + toc

        messages = list(history) if history else []
        messages.append({"role": "user", "content": question})

        # 注入 session 中已累积的 observations（最近若干条，跨提问复用）
        session_obs = getattr(self._ctx, "observations", None) or []
        if session_obs:
            obs_lines = ["[已知信息 — 之前提问已检索到，未经复核]"]
            for i, obs in enumerate(session_obs[-SESSION_OBSERVATION_LIMIT:]):
                prefix = f"(问: {obs.question}) " if obs.question else ""
                obs_lines.append(f"{i + 1}. {prefix}{obs.summary}")
            system = system + "\n\n" + "\n".join(obs_lines)

        tool_schemas = [_tool_to_openai_schema(t) for t in self._tools]

        # 重置轮次追踪和本轮观察（session 观察在 ctx 上，不清）
        self._tool_round_map.clear()
        self._observations.clear()

        try:
            for round_num in range(7):
                # 发送前压缩往轮 tool result
                compacted_messages = self._compact_messages(messages, round_num)

                text_parts: list[str] = []
                tool_calls: list[dict] = []
                if stream:
                    for evt, payload in self._text_client.chat_with_tools_stream(
                            compacted_messages, tool_schemas, system_prompt=system):
                        if evt == "text_delta":
                            text_parts.append(payload)
                            if on_event is not None:
                                on_event("answer_chunk", {"delta": payload})
                        elif evt == "tool_calls":
                            tool_calls = payload
                    response = LLMToolResponse(
                        text="".join(text_parts) if not tool_calls else None,
                        tool_calls=tool_calls,
                    )
                else:
                    response = self._text_client.chat_with_tools(
                        compacted_messages, tool_schemas, system_prompt=system)

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

                # tool-calling round: discard speculative text that was streamed live
                if stream and on_event is not None and text_parts:
                    on_event("clear", {})

                # Execute each tool call
                for tc in response.tool_calls:
                    name = tc["name"]
                    raw_args = tc["arguments"]

                    if on_event is not None:
                        on_event("tool_start", {"name": name, "arguments": raw_args})

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
                    if on_event is not None:
                        on_event("tool_result", {"name": name,
                                                 "chars": len(result.text),
                                                 "resources": len(result.resources)})

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result.text,
                    })
                    # 记录 tool 消息所属轮次
                    self._tool_round_map[tc["id"]] = round_num
                    # 标记 record_observation 发生在哪一轮
                    if name == "record_observation" and self._observations:
                        self._observations[-1].round_num = round_num

            if stream and on_event is not None:
                on_event("answer_chunk", {"delta": "抱歉，暂时没能找到相关信息，请尝试换一个问法。"})
            return "抱歉，暂时没能找到相关信息，请尝试换一个问法。"
        finally:
            self._flush_observations(question)

    def _flush_observations(self, question: str) -> None:
        """把本轮产生的观察并入 session 存储（ctx.observations），标记来源提问。"""
        if not self._observations:
            return
        store = getattr(self._ctx, "observations", None)
        if store is None:
            return
        for obs in self._observations:
            obs.question = question
        store.extend(self._observations)
