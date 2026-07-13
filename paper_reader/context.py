from sklearn.feature_extraction.text import TfidfVectorizer

from paper_reader.blocks import PaperDocument, ContentBlock, SemanticChunk


class ConversationContext:
    def __init__(self, paper: PaperDocument):
        self.paper = paper
        self.history: list[dict] = []
        self._chunk_texts: list[str] = [c.text for c in paper.chunks]
        self._vectorizer: TfidfVectorizer | None = None
        self._tfidf_matrix = None
        if self._chunk_texts:
            self._vectorizer = TfidfVectorizer(stop_words="english")
            self._tfidf_matrix = self._vectorizer.fit_transform(self._chunk_texts)

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def search_chunks(self, query: str, top_k: int = 3) -> list[SemanticChunk]:
        if not self.paper.chunks:
            return []
        if len(self.paper.chunks) <= top_k:
            return list(self.paper.chunks)

        if self._vectorizer is None or self._tfidf_matrix is None:
            return list(self.paper.chunks[:top_k])

        from sklearn.metrics.pairwise import cosine_similarity

        query_vec = self._vectorizer.transform([query])
        similarities = cosine_similarity(query_vec, self._tfidf_matrix).flatten()
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
            f"Paper: {self.paper.title}",
            "",
        ]
        if self.paper.abstract:
            preview = self.paper.abstract[:500]
            if len(self.paper.abstract) > 500:
                preview += "..."
            lines.append(f"Abstract: {preview}")
            lines.append("")

        lines.append("Sections:")
        seen: set[str] = set()
        for b in self.paper.blocks:
            if b.level > 0:
                title = b.text.strip()
                if title not in seen:
                    indent = "  " * (b.level - 1)
                    lines.append(f"{indent}{title}")
                    seen.add(title)

        return "\n".join(lines)
