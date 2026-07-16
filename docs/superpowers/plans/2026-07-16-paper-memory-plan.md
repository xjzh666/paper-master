# Paper Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured paper understanding (PaperMemory) extracted by LLM at parse time, cached alongside MinerU results, and injected into conversation context.

**Architecture:** New `PaperMemory` dataclass in `blocks.py` with 10 fields. New `memory.py` module handles extraction via LLM + cache I/O. `LLMRouter` gains a `memory` parameter that serializes into the system prompt. `main.py` adds Phase 3 extraction after BGE-M3 encoding.

**Tech Stack:** Python 3.10+, dataclasses, JSON, hashlib

## Global Constraints

- PaperMemory 独立缓存文件 `{sha256}-memory.json`，与 chunk 缓存同目录
- 输入源优先 MinerU `.md` 文件，回退到 blocks 按序取 text
- 使用现有 text 模型（deepseek-v4-pro），一次 LLM 调用
- 现有 65 个测试保持通过
- 不引入新依赖

---

### Task 1: Add PaperMemory dataclass and update PaperDocument

**Files:**
- Modify: `paper_reader/blocks.py`

**Interfaces:**
- Produces: `PaperMemory` dataclass with `to_dict()` / `from_dict()`, `PaperDocument.memory: PaperMemory | None`

- [ ] **Step 1: Add PaperMemory dataclass**

Insert after `PaperDocument` class (before `estimate_tokens`):

```python
@dataclass
class PaperMemory:
    research_problem: str = ""
    motivation: str = ""
    method: str = ""
    method_why: str = ""
    experiments: str = ""
    key_results: str = ""
    contributions: str = ""
    limitations: str = ""
    takeaways: str = ""
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "research_problem": self.research_problem,
            "motivation": self.motivation,
            "method": self.method,
            "method_why": self.method_why,
            "experiments": self.experiments,
            "key_results": self.key_results,
            "contributions": self.contributions,
            "limitations": self.limitations,
            "takeaways": self.takeaways,
            "keywords": self.keywords,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PaperMemory":
        return cls(
            research_problem=d.get("research_problem", ""),
            motivation=d.get("motivation", ""),
            method=d.get("method", ""),
            method_why=d.get("method_why", ""),
            experiments=d.get("experiments", ""),
            key_results=d.get("key_results", ""),
            contributions=d.get("contributions", ""),
            limitations=d.get("limitations", ""),
            takeaways=d.get("takeaways", ""),
            keywords=d.get("keywords", []),
        )
```

- [ ] **Step 2: Add memory field to PaperDocument**

```python
@dataclass
class PaperDocument:
    filepath: str
    title: str = ""
    abstract: str = ""
    blocks: list[ContentBlock] = field(default_factory=list)
    chunks: list[SemanticChunk] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    result_dir: str = ""
    memory: PaperMemory | None = None       # <-- add this line
```

- [ ] **Step 3: Update PaperDocument.to_dict()**

In `to_dict()`, add memory serialization before the return:

```python
def to_dict(self) -> dict:
    block_index_map = {id(b): i for i, b in enumerate(self.blocks)}
    d = {
        "filepath": self.filepath, "title": self.title,
        "abstract": self.abstract,
        "blocks": [b.to_dict() for b in self.blocks],
        "chunks": [
            {**c.to_dict(), "block_indices": [block_index_map[id(b)] for b in c.blocks]}
            for c in self.chunks
        ],
        "metadata": self.metadata,
        "result_dir": self.result_dir,
    }
    if self.memory is not None:
        d["memory"] = self.memory.to_dict()
    return d
```

Note: change the current return to build `d` dict first, then conditionally add memory.

- [ ] **Step 4: Update PaperDocument.from_dict()**

```python
@classmethod
def from_dict(cls, d: dict) -> "PaperDocument":
    blocks = [ContentBlock.from_dict(bd) for bd in d["blocks"]]
    chunks = [
        SemanticChunk.from_dict(cd, blocks)
        for cd in d.get("chunks", [])
    ]
    memory = None
    if "memory" in d:
        memory = PaperMemory.from_dict(d["memory"])
    return cls(
        filepath=d["filepath"], title=d.get("title", ""),
        abstract=d.get("abstract", ""), blocks=blocks, chunks=chunks,
        metadata=d.get("metadata", {}),
        result_dir=d.get("result_dir", ""),
        memory=memory,
    )
```

- [ ] **Step 5: Add PaperMemory to __init__.py exports**

Read `paper_reader/__init__.py` and add `PaperMemory` to the imports if there's an `__all__` or re-export list. If it's empty, skip this step.

- [ ] **Step 6: Run existing tests to verify no breakage**

```bash
cd /home/xiejiezhen/paper-master && source .venv/bin/activate && python3 -m pytest tests/test_blocks.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add paper_reader/blocks.py
git commit -m "feat: add PaperMemory dataclass and memory field to PaperDocument"
```

---

### Task 2: Create memory.py with extraction logic and cache I/O

**Files:**
- Create: `paper_reader/memory.py`

**Interfaces:**
- Consumes: `PaperMemory`, `PaperDocument` from `paper_reader.blocks`; `LLMRouter` from `paper_reader.llm` (for `extract_json` method added in Task 3)
- Produces: `extract_memory(paper, text_client) -> PaperMemory`, `load_memory_cache(paper) -> PaperMemory | None`, `save_memory_cache(paper, memory) -> None`

- [ ] **Step 1: Create memory.py with all functions**

```python
# paper_reader/memory.py
import hashlib
import json
import re
from pathlib import Path

from paper_reader.blocks import PaperDocument, PaperMemory

CACHE_DIR = Path.home() / ".cache" / "paper-master"

MEMORY_EXTRACTION_PROMPT = """你是一位资深科研助手。请仔细阅读以下论文，提取关键信息。

对于每个字段，用中文简洁回答（每项2-5句话）。如果论文中没有明确提及，写"未提及"。
关键词用英文，5-8个，覆盖方法/领域/任务维度。

输出纯JSON（不要markdown代码块）：
{
  "research_problem": "论文试图解决什么问题？",
  "motivation": "为什么这个问题重要？现有方法有什么不足？",
  "method": "核心方法/算法是什么？",
  "method_why": "方法为什么有效？关键设计选择的原因是什么？",
  "experiments": "实验设计、数据集、baseline、关键指标",
  "key_results": "主要实验结果和发现",
  "contributions": "核心贡献（通常3-4点）",
  "limitations": "方法局限、未解决的问题",
  "takeaways": "2-3句话总结，这篇论文对研究者的启示",
  "keywords": ["keyword1", "keyword2", ...]
}"""


def _compute_sha256(filepath: str) -> str:
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _memory_cache_path(paper: PaperDocument) -> Path | None:
    if not paper.filepath or not Path(paper.filepath).exists():
        return None
    key = _compute_sha256(paper.filepath)
    return CACHE_DIR / f"{key}-memory.json"


def load_memory_cache(paper: PaperDocument) -> PaperMemory | None:
    path = _memory_cache_path(paper)
    if path is None or not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return PaperMemory.from_dict(data.get("memory", {}))
    except (json.JSONDecodeError, KeyError, IOError):
        return None


def save_memory_cache(paper: PaperDocument, memory: PaperMemory) -> None:
    path = _memory_cache_path(paper)
    if path is None:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "sha256": _compute_sha256(paper.filepath),
        "memory": memory.to_dict(),
    }
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_markdown(paper: PaperDocument) -> str:
    """Load MinerU-generated markdown, fall back to blocks text."""
    result_dir = Path(paper.result_dir) if paper.result_dir else None
    if result_dir and result_dir.exists():
        md_files = list(result_dir.glob("*.md"))
        if md_files:
            return md_files[0].read_text()
    # Fallback: concat blocks in order (no overlap)
    return "\n\n".join(b.text for b in paper.blocks if b.text.strip())


def _parse_json_response(raw: str) -> dict:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try to extract from ```json ... ``` block
    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    if m:
        return json.loads(m.group(1))
    # Try to find first { ... } span
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"Failed to parse JSON from LLM response: {raw[:200]}")


def extract_memory(paper: PaperDocument, text_client) -> PaperMemory:
    """Extract structured understanding from a paper using LLM.

    Args:
        paper: Parsed PaperDocument with result_dir set.
        text_client: An LLMClient instance for text chat (e.g. router._text_client).

    Returns:
        PaperMemory with extracted fields.
    """
    markdown = _load_markdown(paper)
    if not markdown.strip():
        return PaperMemory()

    messages = [{"role": "user", "content": markdown}]
    response = text_client.chat(messages, system_prompt=MEMORY_EXTRACTION_PROMPT)
    data = _parse_json_response(response)
    memory = PaperMemory.from_dict(data)
    save_memory_cache(paper, memory)
    return memory
```

- [ ] **Step 2: Verify the module imports correctly**

```bash
cd /home/xiejiezhen/paper-master && source .venv/bin/activate && python3 -c "from paper_reader.memory import extract_memory, load_memory_cache, save_memory_cache; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add paper_reader/memory.py
git commit -m "feat: add memory extraction module with LLM-driven paper understanding"
```

---

### Task 3: Update LLMRouter.answer() with memory parameter

**Files:**
- Modify: `paper_reader/llm.py`

**Interfaces:**
- Consumes: `PaperMemory` from `paper_reader.blocks`
- Produces: `LLMRouter.answer(memory=...)` updated signature

- [ ] **Step 1: Add memory parameter to answer()**

Add `memory` parameter and `_format_memory()` helper. Update `answer()` to include memory in system prompt:

```python
from paper_reader.blocks import PaperMemory

# In LLMRouter class:

def _format_memory(self, memory: PaperMemory) -> str:
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

def answer(
    self, text: str, images: list[bytes], question: str,
    history: list[dict], title: str = "",
    memory: PaperMemory | None = None,       # <-- new parameter
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
```

- [ ] **Step 2: Run existing LLM tests to verify no breakage**

```bash
cd /home/xiejiezhen/paper-master && source .venv/bin/activate && python3 -m pytest tests/test_llm.py -v
```

Expected: all tests pass (existing tests don't pass `memory`, so it defaults to `None`).

- [ ] **Step 3: Verify import works**

```bash
cd /home/xiejiezhen/paper-master && source .venv/bin/activate && python3 -c "from paper_reader.llm import LLMRouter; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add paper_reader/llm.py
git commit -m "feat: add memory parameter to LLMRouter.answer for paper-level context"
```

---

### Task 4: Integrate Phase 3 memory extraction into main.py

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `extract_memory`, `load_memory_cache` from `paper_reader.memory`

- [ ] **Step 1: Add top-level import for memory module**

Add after the existing imports at the top of `main.py`:

```python
from paper_reader.memory import extract_memory, load_memory_cache
```

- [ ] **Step 2: Update interactive_loop() to extract/load memory**

After `ctx = ConversationContext(paper)` and before `show_overview(ctx)`, add memory loading/extraction:

```python
    ctx = ConversationContext(paper)
    router = LLMRouter(config)

    # ── Phase 3: Paper Memory ──
    memory = load_memory_cache(paper)
    if memory is not None:
        print("  [memory] 从缓存加载")
        paper.memory = memory
    elif paper.result_dir:
        print("  [memory] 正在抽取论文结构化理解...")
        try:
            paper.memory = extract_memory(paper, router._text_client)
            print("  [memory] 抽取完成")
        except Exception as e:
            print(f"  [memory] 抽取失败: {e}")

    show_overview(ctx)

    session = PromptSession()
    while True:
        try:
            user_input = session.prompt("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input in ("/quit", "/exit"):
            print("再见！")
            break
        elif user_input == "/help":
            show_help()
        elif user_input == "/overview":
            show_overview(ctx)
        elif user_input == "/sections":
            print(ctx.get_overview())
        else:
            print("\n思考中...")
            try:
                answer = handle_question(user_input, ctx, router)
                print(f"\n{answer}")
            except Exception as e:
                print(f"\n错误: {e}")
```

- [ ] **Step 3: Update handle_question() to pass memory**

In `handle_question()`, pass `ctx.paper.memory` to `router.answer()`:

```python
def handle_question(
    question: str, ctx: ConversationContext, router: LLMRouter
) -> str:
    ctx.add_message("user", question)

    blocks = ctx.find_section(question) if _is_section_query(question) else None
    if blocks is not None:
        from paper_reader.blocks import SemanticChunk
        chunk = SemanticChunk(
            chunk_id="section_match", text="\n".join(b.text for b in blocks),
            blocks=blocks, section_path=[],
        )
        for b in blocks:
            if b.type in ("image", "table"):
                chunk.images.append(b)
        text, images = ctx.build_context([chunk], window=0)
    else:
        chunks = ctx.search_chunks(question, top_k=3)
        if not chunks:
            chunks = ctx.paper.chunks[:5]
        text, images = ctx.build_context(chunks, window=2)

    image_bytes_list: list[bytes] = []
    for img_block in images:
        data = img_block.load_image(ctx.paper.result_dir)
        if data:
            image_bytes_list.append(data)

    answer = router.answer(
        text=text, images=image_bytes_list, question=question,
        history=ctx.history[:-1], title=ctx.paper.title,
        memory=ctx.paper.memory,          # <-- pass memory
    )
    ctx.add_message("assistant", answer)
    return answer
```

- [ ] **Step 4: Update batch_parse() to include Phase 3**

Add Phase 3 after the Phase 2 loop:

```python
def batch_parse(papers_dir: str) -> None:
    # ... (keep existing Phase 1 and Phase 2 code the same) ...

    # ── Phase 3: Paper Memory (LLM API) ──
    print("── 阶段 3/3: Paper Memory 结构化抽取 ──")
    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        print("  跳过: 未找到 config.yaml")
        config = None

    if config:
        from paper_reader.llm import create_client
        from paper_reader.memory import extract_memory, load_memory_cache
        text_client = create_client(config["models"]["text"])
        phase3_ok = 0
        for paper in parsed:
            print(f"  {Path(paper.filepath).name}")
            cached = load_memory_cache(paper)
            if cached is not None:
                paper.memory = cached
                print(f"    (已缓存)")
                phase3_ok += 1
            else:
                try:
                    paper.memory = extract_memory(paper, text_client)
                    print(f"    抽取完成 — {len(paper.memory.keywords)} 个关键词")
                    phase3_ok += 1
                except Exception as e:
                    print(f"    抽取失败 — {e}")
        print(f"  完成: {phase3_ok} 抽取")
    print(f"\n总计: {phase1_ok} 解析, {phase1_fail} 失败 | {phase2_ok} 编码 | "
          f"{phase3_ok if config else 0} memory")
```

- [ ] **Step 5: Run existing CLI test to check import**

```bash
cd /home/xiejiezhen/paper-master && source .venv/bin/activate && python3 -c "import main; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: integrate Phase 3 Paper Memory extraction into CLI and batch"
```

---

### Task 5: Write tests for memory module

**Files:**
- Create: `tests/test_memory.py`

**Interfaces:**
- Consumes: `PaperMemory`, `PaperDocument` from `paper_reader.blocks`; `extract_memory`, `load_memory_cache`, `save_memory_cache`, `_parse_json_response` from `paper_reader.memory`

- [ ] **Step 1: Write the test file**

```python
# tests/test_memory.py
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from paper_reader.blocks import PaperDocument, PaperMemory, ContentBlock
from paper_reader.memory import (
    extract_memory,
    load_memory_cache,
    save_memory_cache,
    _parse_json_response,
    _load_markdown,
    _compute_sha256,
    _memory_cache_path,
    CACHE_DIR,
)


class TestPaperMemory:
    def test_default_values(self):
        m = PaperMemory()
        assert m.research_problem == ""
        assert m.keywords == []

    def test_to_dict_and_from_dict_roundtrip(self):
        m = PaperMemory(
            research_problem="测试问题",
            method="测试方法",
            keywords=["kw1", "kw2"],
        )
        d = m.to_dict()
        m2 = PaperMemory.from_dict(d)
        assert m2.research_problem == "测试问题"
        assert m2.method == "测试方法"
        assert m2.keywords == ["kw1", "kw2"]

    def test_from_dict_missing_fields_defaults_to_empty(self):
        m = PaperMemory.from_dict({})
        assert m.research_problem == ""
        assert m.keywords == []

    def test_from_dict_partial_fields(self):
        m = PaperMemory.from_dict({"method": "only method", "takeaways": "good"})
        assert m.method == "only method"
        assert m.takeaways == "good"
        assert m.research_problem == ""


class TestParseJsonResponse:
    def test_parses_plain_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parses_json_with_markdown_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_parses_json_without_lang_specifier(self):
        raw = '```\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_parses_json_with_surrounding_text(self):
        raw = '一些前置文字 {"key": "value"} 一些后置文字'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_raises_on_invalid_input(self):
        with pytest.raises(ValueError):
            _parse_json_response("not json at all")


class TestCacheIO:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """Save a memory, then load it back."""
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )

        # Create a real PDF file so _compute_sha256 works
        pdf = tmp_path / "test.pdf"
        pdf.write_text("fake pdf content for hashing")

        paper = PaperDocument(
            filepath=str(pdf),
            title="Test Paper",
            result_dir="/nonexistent",
        )
        memory = PaperMemory(
            research_problem="如何测试缓存？",
            method="写个测试",
            keywords=["testing", "cache"],
        )

        save_memory_cache(paper, memory)
        loaded = load_memory_cache(paper)

        assert loaded is not None
        assert loaded.research_problem == "如何测试缓存？"
        assert loaded.keywords == ["testing", "cache"]

    def test_load_returns_none_when_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "no-cache.pdf"
        pdf.write_text("some content")

        paper = PaperDocument(filepath=str(pdf))
        result = load_memory_cache(paper)
        assert result is None

    def test_load_returns_none_for_invalid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "bad.pdf"
        pdf.write_text("bad pdf content")
        key = _compute_sha256(str(pdf))
        cache_file = tmp_path / f"{key}-memory.json"
        cache_file.write_text("not valid json")

        paper = PaperDocument(filepath=str(pdf))
        result = load_memory_cache(paper)
        assert result is None

    def test_memory_cache_path_returns_none_for_missing_file(self):
        paper = PaperDocument(filepath="/nonexistent/path.pdf")
        assert _memory_cache_path(paper) is None


class TestLoadMarkdown:
    def test_loads_md_file_when_present(self, tmp_path):
        result_dir = tmp_path / "result"
        result_dir.mkdir()
        md_file = result_dir / "paper.md"
        md_file.write_text("# Title\n\nContent here.")

        paper = PaperDocument(
            filepath=str(tmp_path / "paper.pdf"),
            result_dir=str(result_dir),
        )
        text = _load_markdown(paper)
        assert "Title" in text
        assert "Content here." in text

    def test_falls_back_to_blocks_when_no_md(self, tmp_path):
        result_dir = tmp_path / "empty_result"
        result_dir.mkdir()

        blocks = [
            ContentBlock(type="text", text="段落一"),
            ContentBlock(type="text", text="段落二"),
        ]
        paper = PaperDocument(
            filepath=str(tmp_path / "paper.pdf"),
            result_dir=str(result_dir),
            blocks=blocks,
        )
        text = _load_markdown(paper)
        assert "段落一" in text
        assert "段落二" in text

    def test_loads_first_md_when_multiple_present(self, tmp_path):
        result_dir = tmp_path / "multi_md"
        result_dir.mkdir()
        (result_dir / "a.md").write_text("first file")
        (result_dir / "b.md").write_text("second file")

        paper = PaperDocument(
            filepath=str(tmp_path / "paper.pdf"),
            result_dir=str(result_dir),
        )
        text = _load_markdown(paper)
        assert text == "first file"


class TestExtractMemory:
    def test_extract_memory_with_markdown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "paper.pdf"
        pdf.write_text("pdf content for hashing")

        result_dir = tmp_path / "result"
        result_dir.mkdir()
        (result_dir / "paper.md").write_text("# Test Paper\n\nSome content.")

        paper = PaperDocument(
            filepath=str(pdf),
            result_dir=str(result_dir),
        )

        fake_client = MagicMock()
        fake_client.chat.return_value = json.dumps({
            "research_problem": "测试问题",
            "motivation": "测试动机",
            "method": "测试方法",
            "method_why": "测试原理",
            "experiments": "测试实验",
            "key_results": "测试结果",
            "contributions": "测试贡献",
            "limitations": "测试局限",
            "takeaways": "测试总结",
            "keywords": ["test", "memory"],
        })

        memory = extract_memory(paper, fake_client)
        assert memory.research_problem == "测试问题"
        assert memory.keywords == ["test", "memory"]
        fake_client.chat.assert_called_once()

        # Verify cache was saved
        loaded = load_memory_cache(paper)
        assert loaded is not None
        assert loaded.research_problem == "测试问题"

    def test_extract_memory_handles_empty_paper(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "empty.pdf"
        pdf.write_text("empty content")

        paper = PaperDocument(filepath=str(pdf), result_dir="")

        fake_client = MagicMock()
        memory = extract_memory(paper, fake_client)
        assert memory.research_problem == ""
        fake_client.chat.assert_not_called()

    def test_extract_memory_handles_markdown_fence_response(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "fence.pdf"
        pdf.write_text("fence content")

        result_dir = tmp_path / "result"
        result_dir.mkdir()
        (result_dir / "out.md").write_text("# Fence Paper")

        paper = PaperDocument(
            filepath=str(pdf),
            result_dir=str(result_dir),
        )

        fake_client = MagicMock()
        fake_client.chat.return_value = '```json\n{"research_problem": "fenced", "keywords": ["x"]}\n```'

        memory = extract_memory(paper, fake_client)
        assert memory.research_problem == "fenced"


class TestPaperDocumentWithMemory:
    def test_to_dict_includes_memory_when_present(self):
        paper = PaperDocument(
            filepath="test.pdf",
            memory=PaperMemory(research_problem="RP", keywords=["k"]),
        )
        d = paper.to_dict()
        assert "memory" in d
        assert d["memory"]["research_problem"] == "RP"

    def test_to_dict_excludes_memory_when_none(self):
        paper = PaperDocument(filepath="test.pdf")
        d = paper.to_dict()
        assert "memory" not in d

    def test_from_dict_loads_memory(self):
        d = {
            "filepath": "test.pdf",
            "blocks": [],
            "memory": {"research_problem": "from dict", "keywords": ["a"]},
        }
        paper = PaperDocument.from_dict(d)
        assert paper.memory is not None
        assert paper.memory.research_problem == "from dict"

    def test_from_dict_handles_missing_memory(self):
        d = {"filepath": "test.pdf", "blocks": []}
        paper = PaperDocument.from_dict(d)
        assert paper.memory is None
```

- [ ] **Step 2: Run the new tests**

```bash
cd /home/xiejiezhen/paper-master && source .venv/bin/activate && python3 -m pytest tests/test_memory.py -v
```

Expected: all 19 tests pass.

- [ ] **Step 3: Run all tests to verify no regressions**

```bash
cd /home/xiejiezhen/paper-master && source .venv/bin/activate && python3 -m pytest tests/ -v --ignore=tests/test_cli.py
```

Expected: all tests pass (test_cli.py may fail due to missing prompt_toolkit, which is pre-existing).

- [ ] **Step 4: Commit**

```bash
git add tests/test_memory.py
git commit -m "test: add tests for PaperMemory extraction, cache I/O, and serialization"
```

---

### Task 6: Write tests for LLM memory injection

**Files:**
- Modify: `tests/test_llm.py`

**Interfaces:**
- Consumes: `LLMRouter`, `PaperMemory` from respective modules

- [ ] **Step 1: Add test for memory injection into system prompt**

Append to `tests/test_llm.py`:

```python
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
```

- [ ] **Step 2: Run the new LLM tests**

```bash
cd /home/xiejiezhen/paper-master && source .venv/bin/activate && python3 -m pytest tests/test_llm.py -v
```

Expected: all tests pass (existing + 3 new).

- [ ] **Step 3: Commit**

```bash
git add tests/test_llm.py
git commit -m "test: add memory injection tests for LLMRouter.answer"
```
