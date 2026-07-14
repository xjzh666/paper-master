import hashlib
import json
from pathlib import Path

import numpy as np

from paper_reader.blocks import PaperDocument, ContentBlock, SemanticChunk

CACHE_DIR = Path.home() / ".cache" / "paper-master"

# Module-level singleton — loaded once, reused across ConversationContext instances
_embedding_model = None


# Prefer local modelscope cache, fall back to HuggingFace download
import os as _os
_MODEL_PATH = "/home/xiejiezhen/.cache/modelscope/models/BAAI--bge-m3/snapshots/master"
if not _os.path.isdir(_MODEL_PATH):
    _MODEL_PATH = "BAAI/bge-m3"


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from FlagEmbedding import BGEM3FlagModel
        _embedding_model = BGEM3FlagModel(_MODEL_PATH, use_fp16=True)
    return _embedding_model


class ConversationContext:
    def __init__(self, paper: PaperDocument):
        self.paper = paper
        self.history: list[dict] = []
        self._chunk_texts: list[str] = [c.text for c in paper.chunks]
        self._embeddings: np.ndarray | None = None
        self._ensure_embeddings()

    def _ensure_embeddings(self):
        if not self._chunk_texts:
            return
        # Reuse cached embeddings from previously parsed chunks
        cached = [c.embedding for c in self.paper.chunks if c.embedding is not None]
        if len(cached) == len(self.paper.chunks):
            self._embeddings = np.array(cached)
            return
        # Encode all chunks with BGE-M3
        model = _get_embedding_model()
        result = model.encode(
            self._chunk_texts,
            batch_size=12,
            max_length=512,
        )
        self._embeddings = result["dense_vecs"]
        # Write back to chunks so they persist in cache JSON
        for i, c in enumerate(self.paper.chunks):
            c.embedding = self._embeddings[i].tolist()
        # Persist updated paper (with embeddings) to cache
        self._save_cache()

    def _save_cache(self) -> None:
        if not self.paper.filepath or not Path(self.paper.filepath).exists():
            return
        try:
            with open(self.paper.filepath, "rb") as f:
                key = hashlib.sha256(f.read()).hexdigest()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(CACHE_DIR / f"{key}.json", "w") as f:
                json.dump(self.paper.to_dict(), f, ensure_ascii=False, indent=2)
        except (IOError, OSError):
            pass

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def search_chunks(self, query: str, top_k: int = 3) -> list[SemanticChunk]:
        if not self.paper.chunks:
            return []
        if len(self.paper.chunks) <= top_k:
            return list(self.paper.chunks)

        if self._embeddings is None or self._embeddings.shape[0] == 0:
            return list(self.paper.chunks[:top_k])

        model = _get_embedding_model()
        query_emb = model.encode(
            [query], batch_size=1, max_length=512
        )["dense_vecs"][0]

        similarities = query_emb @ self._embeddings.T
        top_indices = similarities.argsort()[-top_k:][::-1]

        return [self.paper.chunks[i] for i in top_indices if similarities[i] > 0]

    def build_context(
        self, chunks: list[SemanticChunk], window: int = 2
    ) -> tuple[str, list[ContentBlock]]:
        if not chunks:
            return "", []

        all_chunks = self.paper.chunks
        selected_indices: set[int] = set()
        for c in chunks:
            try:
                idx = all_chunks.index(c)
                start = max(0, idx - window)
                end = min(len(all_chunks), idx + window + 1)
                selected_indices.update(range(start, end))
            except ValueError:
                continue

        ordered = sorted(selected_indices)
        text_parts: list[str] = []
        images: list[ContentBlock] = []

        for i in ordered:
            chunk = all_chunks[i]
            text_parts.append(chunk.text)
            for img in chunk.images:
                images.append(img)

        return "\n\n".join(text_parts), images

    def find_section(self, query: str) -> list[ContentBlock] | None:
        """Find blocks within a section by title or number match."""
        query_lower = query.strip().lower()

        # Find matching heading block
        heading_idx: int | None = None
        heading_level: int = 0

        for i, b in enumerate(self.paper.blocks):
            if b.level > 0 and query_lower in b.text.strip().lower():
                heading_idx = i
                heading_level = b.level
                break

        if heading_idx is None:
            return None

        # Collect blocks from heading to next same-or-higher-level heading
        result: list[ContentBlock] = []
        for i in range(heading_idx, len(self.paper.blocks)):
            b = self.paper.blocks[i]
            if i > heading_idx and b.level > 0 and b.level <= heading_level:
                break
            result.append(b)

        return result

    def get_overview(self) -> str:
        lines = [
            f"论文: {self.paper.title}",
            "",
        ]
        if self.paper.abstract:
            preview = self.paper.abstract[:500]
            if len(self.paper.abstract) > 500:
                preview += "..."
            lines.append(f"摘要: {preview}")
            lines.append("")

        lines.append("章节:")
        seen: set[str] = set()
        for b in self.paper.blocks:
            if b.level > 0:
                title = b.text.strip()
                if title not in seen:
                    indent = "  " * (b.level - 1)
                    lines.append(f"{indent}{title}")
                    seen.add(title)

        return "\n".join(lines)
