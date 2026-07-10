from paper_reader.parser import PaperDocument, Section


class ConversationContext:
    def __init__(self, paper: PaperDocument):
        self.paper = paper
        self.history: list[dict] = []

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def find_section(self, query: str) -> Section | None:
        query_lower = query.strip().lower()

        # Try exact match first
        for section in self.paper.sections:
            if section.title.strip().lower() == query_lower:
                return section

        # Try title contains query
        for section in self.paper.sections:
            if query_lower in section.title.strip().lower():
                return section

        # Try query contains section number (e.g. "what does 2.1 say")
        for section in self.paper.sections:
            title_lower = section.title.strip().lower()
            if title_lower and title_lower.split()[0] in query_lower:
                return section

        return None

    def get_overview(self) -> str:
        lines = [
            f"Paper: {self.paper.title}",
            "",
        ]
        if self.paper.abstract:
            abstract_preview = self.paper.abstract[:500]
            if len(self.paper.abstract) > 500:
                abstract_preview += "..."
            lines.append(f"Abstract: {abstract_preview}")
            lines.append("")

        lines.append("Sections:")
        for section in self.paper.sections:
            indent = "  " * (section.level - 1)
            lines.append(f"{indent}{section.title}")

        return "\n".join(lines)
