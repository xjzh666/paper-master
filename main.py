import re
import sys
from pathlib import Path

from paper_reader.mineru_parser import MinerUParser
from paper_reader.llm import load_config, LLMRouter
from paper_reader.context import ConversationContext


def _is_section_query(query: str) -> bool:
    return bool(re.search(r'\bsection\b', query.lower())) or \
           bool(re.search(r'\b\d+(\.\d+)+\b', query))


def show_overview(ctx: ConversationContext) -> None:
    print("\n" + "=" * 60)
    print(ctx.get_overview())
    print("=" * 60)
    print("\nYou can ask questions about any section. Type /help for commands, /quit to exit.\n")


def show_help() -> None:
    print("""
Commands:
  /overview  - Show paper overview again
  /sections  - List all sections
  /help      - Show this help
  /quit      - Exit

You can ask questions about the paper content directly.
Refer to sections by number (e.g., "What does section 2.1 say?")
""")


def handle_question(
    question: str, ctx: ConversationContext, router: LLMRouter
) -> str:
    ctx.add_message("user", question)

    # Try section lookup only for explicit section references
    blocks = ctx.find_section(question) if _is_section_query(question) else None
    if blocks is not None:
        # Build a temporary chunk list from these blocks for build_context
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
        # TF-IDF chunk search
        chunks = ctx.search_chunks(question, top_k=3)
        if not chunks:
            # Fallback: use all chunks
            chunks = ctx.paper.chunks[:5]
        text, images = ctx.build_context(chunks, window=2)

    # Load image bytes
    image_bytes_list: list[bytes] = []
    for img_block in images:
        data = img_block.load_image(ctx.paper.result_dir)
        if data:
            image_bytes_list.append(data)

    answer = router.answer(
        text=text, images=image_bytes_list, question=question,
        history=ctx.history[:-1], title=ctx.paper.title,
    )
    ctx.add_message("assistant", answer)
    return answer


def interactive_loop(paper_path: str) -> None:
    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        print("Error: config.yaml not found. Copy config.example.yaml to config.yaml and edit it.")
        sys.exit(1)

    print(f"\nLoading paper: {paper_path}...")
    try:
        parser = MinerUParser()
        paper = parser.parse(paper_path)
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        sys.exit(1)

    if not paper.blocks:
        print("Warning: No content detected in this PDF. You can still ask questions.")

    ctx = ConversationContext(paper)
    router = LLMRouter(config)
    show_overview(ctx)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("Goodbye!")
            break
        elif user_input == "/help":
            show_help()
        elif user_input == "/overview":
            show_overview(ctx)
        elif user_input == "/sections":
            print(ctx.get_overview())
        else:
            print("\nThinking...")
            try:
                answer = handle_question(user_input, ctx, router)
                print(f"\n{answer}")
            except Exception as e:
                print(f"\nError: {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <path/to/paper.pdf>")
        sys.exit(1)

    paper_path = sys.argv[1]
    if not Path(paper_path).exists():
        print(f"Error: File not found: {paper_path}")
        sys.exit(1)

    interactive_loop(paper_path)


if __name__ == "__main__":
    main()
