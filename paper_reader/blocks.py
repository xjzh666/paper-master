# paper_reader/blocks.py
from dataclasses import dataclass, field
from pathlib import Path


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
    embedding: list[float] | None = None

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id, "text": self.text,
            "block_indices": [],  # filled by PaperDocument.to_dict()
            "section_path": self.section_path,
            "embedding": self.embedding,
        }

    @classmethod
    def from_dict(cls, d: dict, blocks: list[ContentBlock]) -> "SemanticChunk":
        chunk = cls(
            chunk_id=d["chunk_id"], text=d["text"],
            blocks=[blocks[i] for i in d.get("block_indices", [])],
            section_path=d.get("section_path", []),
            embedding=d.get("embedding"),
        )
        for b in chunk.blocks:
            if b.type in ("image", "table"):
                chunk.images.append(b)
        return chunk


@dataclass
class PaperDocument:
    filepath: str
    title: str = ""
    abstract: str = ""
    blocks: list[ContentBlock] = field(default_factory=list)
    chunks: list[SemanticChunk] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    result_dir: str = ""

    def to_dict(self) -> dict:
        block_index_map = {id(b): i for i, b in enumerate(self.blocks)}
        return {
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

    @classmethod
    def from_dict(cls, d: dict) -> "PaperDocument":
        blocks = [ContentBlock.from_dict(bd) for bd in d["blocks"]]
        chunks = [
            SemanticChunk.from_dict(cd, blocks)
            for cd in d.get("chunks", [])
        ]
        return cls(
            filepath=d["filepath"], title=d.get("title", ""),
            abstract=d.get("abstract", ""), blocks=blocks, chunks=chunks,
            metadata=d.get("metadata", {}),
            result_dir=d.get("result_dir", ""),
        )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def merge_blocks(blocks: list[ContentBlock]) -> list[SemanticChunk]:
    chunks: list[SemanticChunk] = []
    current_text_parts: list[str] = []
    current_blocks: list[ContentBlock] = []
    current_images: list[ContentBlock] = []
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
                ))
                chunk_idx += 1
        current_text_parts.clear()
        current_blocks.clear()
        current_images.clear()

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
