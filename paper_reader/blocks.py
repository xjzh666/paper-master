# paper_reader/blocks.py
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Roman numeral handling ───────────────────────────────────────────

_ROMAN_VALUES = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100}


def _roman_to_int(s: str) -> int | None:
    """Convert a Roman numeral string to integer. Returns None if invalid."""
    if not s or not all(c in _ROMAN_VALUES for c in s.upper()):
        return None
    result = 0
    prev = 0
    for ch in reversed(s.upper()):
        cur = _ROMAN_VALUES[ch]
        result += -cur if cur < prev else cur
        prev = cur
    return result


# ── Label normalization ──────────────────────────────────────────────

# Matches: Fig. 1, Figure 3, TABLE I, Table 2, Algorithm 1
_LABEL_RE = re.compile(
    r'(Fig(?:ure)?|TABLE|Table|Algorithm)\s*\.?\s*([IVXLCDM]+|\d+)',
    re.IGNORECASE,
)


def _normalize_label(text: str) -> tuple[str, list[str]]:
    """Convert a figure/table/algorithm caption into (canonical_text, aliases).

    Example:
        "TABLE III FPA UNIVERSALITY..." →
            ("TABLE III (Table 3) FPA UNIVERSALITY...",
             ["TABLE III", "Table 3", "表3", "表 3"])
    """
    if not text:
        return text, []

    m = _LABEL_RE.match(text.strip())
    if not m:
        return text, []

    prefix = m.group(1)       # e.g. "TABLE", "Fig", "Algorithm"
    num_token = m.group(2)    # e.g. "III", "3"
    original_label = m.group(0)

    # Convert to Arabic integer
    if num_token.isdigit():
        num = int(num_token)
    else:
        num = _roman_to_int(num_token.upper())
        if num is None:
            return text, [original_label]

    # Canonical English label (always Arabic numeral)
    if prefix.lower().startswith('fig'):
        canonical_en = f'Figure {num}'
    elif prefix.upper() == 'TABLE':
        canonical_en = f'Table {num}'
    else:  # Algorithm
        canonical_en = f'Algorithm {num}'

    # Aliases (English + Chinese)
    if prefix.lower().startswith('fig'):
        aliases = [
            original_label,
            f'Fig. {num}',
            f'Figure {num}',
            f'Fig {num}',
            f'图{num}',
            f'图 {num}',
        ]
    elif prefix.upper() == 'TABLE':
        aliases = [
            original_label,
            f'Table {num}',
            f'表{num}',
            f'表 {num}',
        ]
    else:  # Algorithm
        aliases = [
            original_label,
            f'Algorithm {num}',
            f'算法{num}',
            f'算法 {num}',
        ]

    # Inject canonical label into text
    canonical_text = text.replace(original_label, f'{original_label} ({canonical_en})', 1)

    return canonical_text, aliases


def _extract_label(text: str) -> str:
    """Extract short label from figure/table caption, e.g. 'Fig. 1' from 'Fig. 1. Description.'."""
    m = _LABEL_RE.match(text.strip()) if text else None
    return m.group(0) if m else ""


@dataclass
class ContentBlock:
    type: str  # "text" | "image" | "table" | "formula"
    text: str
    level: int = 0  # 0=body, 1=h1, 2=h2, ...
    page_idx: int = 0
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    image_path: str | None = None
    image_bytes: bytes | None = None
    children: list["ContentBlock"] = field(default_factory=list)

    def load_image(self, base_dir: str) -> bytes:
        if self.image_bytes is not None:
            return self.image_bytes
        if self.image_path:
            full_path = Path(base_dir) / self.image_path
            if full_path.exists():
                self.image_bytes = full_path.read_bytes()
                return self.image_bytes
        return b""

    def to_dict(self) -> dict:
        d = {
            "type": self.type, "text": self.text, "level": self.level,
            "page_idx": self.page_idx, "bbox": list(self.bbox),
            "image_path": self.image_path, "children": [c.to_dict() for c in self.children],
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ContentBlock":
        return cls(
            type=d["type"], text=d.get("text", ""), level=d.get("level", 0),
            page_idx=d.get("page_idx", 0), bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
            image_path=d.get("image_path"), children=[cls.from_dict(c) for c in d.get("children", [])],
        )


@dataclass
class SemanticChunk:
    chunk_id: str
    text: str
    blocks: list[ContentBlock]
    section_path: list[str]
    images: list[ContentBlock] = field(default_factory=list)
    figure_labels: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    # Sparse lexical weights from BGE-M3, keyed by token id (str for JSON compat)
    lexical_weights: dict[str, float] | None = None

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id, "text": self.text,
            "block_indices": [],  # filled by PaperDocument.to_dict()
            "section_path": self.section_path,
            "figure_labels": self.figure_labels,
            "aliases": self.aliases,
            "embedding": self.embedding,
            "lexical_weights": self.lexical_weights,
        }

    @classmethod
    def from_dict(cls, d: dict, blocks: list[ContentBlock]) -> "SemanticChunk":
        chunk = cls(
            chunk_id=d["chunk_id"], text=d["text"],
            blocks=[blocks[i] for i in d.get("block_indices", [])],
            section_path=d.get("section_path", []),
            figure_labels=d.get("figure_labels", []),
            aliases=d.get("aliases", []),
            embedding=d.get("embedding"),
            lexical_weights=d.get("lexical_weights"),
        )
        for b in chunk.blocks:
            if b.type in ("image", "table"):
                chunk.images.append(b)
        return chunk


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


@dataclass
class PaperDocument:
    filepath: str
    title: str = ""
    abstract: str = ""
    blocks: list[ContentBlock] = field(default_factory=list)
    chunks: list[SemanticChunk] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    result_dir: str = ""
    memory: PaperMemory | None = None

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


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def merge_blocks(blocks: list[ContentBlock]) -> list[SemanticChunk]:
    chunks: list[SemanticChunk] = []
    current_text_parts: list[str] = []
    current_blocks: list[ContentBlock] = []
    current_images: list[ContentBlock] = []
    current_labels: list[str] = []
    current_aliases: list[str] = []
    section_path: list[str] = []
    chunk_idx = 0

    def flush() -> None:
        nonlocal chunk_idx
        if current_text_parts:
            combined = "\n".join(current_text_parts).strip()
            if combined:
                chunks.append(SemanticChunk(
                    chunk_id=f"chunk_{chunk_idx}",
                    text=combined,
                    blocks=list(current_blocks),
                    section_path=list(section_path),
                    images=list(current_images),
                    figure_labels=list(current_labels),
                    aliases=sorted(set(current_aliases)),
                ))
                chunk_idx += 1
        current_text_parts.clear()
        current_blocks.clear()
        current_images.clear()
        current_labels.clear()
        current_aliases.clear()

    def take_last_tokens(text: str, n: int) -> str:
        words = text.split()
        target_words = max(1, int(n * 3 / 4))
        return " ".join(words[-target_words:])

    for block in blocks:
        if block.level > 0:
            flush()
            section_path = section_path[:block.level - 1]
            title_clean = block.text.strip()
            section_path.append(title_clean)
            current_text_parts.append(block.text)
            current_blocks.append(block)
        elif block.type in ("image", "table"):
            current_images.append(block)
            current_blocks.append(block)
            label = _extract_label(block.text)
            if label:
                current_labels.append(label)
            if block.text.strip():
                canonical_text, aliases = _normalize_label(block.text.strip())
                current_text_parts.append(canonical_text)
                current_aliases.extend(aliases)
        else:
            combined = "\n".join(current_text_parts)
            if estimate_tokens(combined) + estimate_tokens(block.text) > 480:
                prev_text = combined
                flush()
                overlap = take_last_tokens(prev_text, 64)
                if overlap:
                    current_text_parts.append(overlap)
                current_text_parts.append(block.text)
                current_blocks.append(block)
            else:
                current_text_parts.append(block.text)
                current_blocks.append(block)

    flush()
    return chunks
