import sys
from pathlib import Path

from paper_reader.parser import parse_pdf, Section, ImageBlock
from paper_reader.llm import load_config, LLMRouter
from paper_reader.context import ConversationContext


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

You can also just type a question about the paper.
Refer to sections by number (e.g., "What does section 2.1 say?")
""")


def handle_question(
    question: str, ctx: ConversationContext, router: LLMRouter
) -> str:
    ctx.add_message("user", question)

    # Try to find which section the user is asking about
    section = ctx.find_section(question)

    if section is None:
        # General question — use full paper content
        all_text = ""
        all_images = []
        for s in ctx.paper.sections:
            all_text += f"\n\n## {s.title}\n{s.text}"
            all_images.extend(img.image_bytes for img in s.images)
        section = Section(
            title="Full Paper", level=0, text=all_text,
            page_start=0, page_end=999, images=[
                ImageBlock(page=0, bbox=(0, 0, 0, 0), image_bytes=b)
                for b in all_images
            ],
        )

    answer = router.answer(section, question, ctx.history[:-1])
    ctx.add_message("assistant", answer)
    return answer


def interactive_loop(paper_path: str) -> None:
    # Load config
    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        print("Error: config.yaml not found. Copy config.example.yaml to config.yaml and edit it.")
        sys.exit(1)

    # Parse PDF
    print(f"\nLoading paper: {paper_path}...")
    try:
        paper = parse_pdf(paper_path)
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        sys.exit(1)

    if not paper.sections:
        print("Warning: No sections detected in this PDF. You can still ask questions.")

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
