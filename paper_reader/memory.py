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
