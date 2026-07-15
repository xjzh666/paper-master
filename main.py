import re
import sys
from pathlib import Path

from prompt_toolkit import PromptSession

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
    print("\n直接输入问题即可。输入 /help 查看命令，/quit 或 /exit 退出。\n")


def show_help() -> None:
    print("""
命令:
  /overview  - 重新显示论文概览
  /sections  - 列出所有章节
  /help      - 显示帮助
  /quit      - 退出
  /exit      - 退出

直接输入问题即可，例如：
  这篇论文的核心贡献是什么？
  第 2.1 节的方法是怎么实现的？
  实验用的什么数据集？
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
        print("错误: 未找到 config.yaml。请复制 config.example.yaml 为 config.yaml 并填入 API Key。")
        sys.exit(1)

    print(f"\n正在加载论文: {paper_path}...")
    try:
        parser = MinerUParser()
        paper = parser.parse(paper_path)
    except Exception as e:
        print(f"解析失败: {e}")
        sys.exit(1)

    if not paper.blocks:
        print("警告: 未检测到论文内容，但你仍然可以提问。")

    ctx = ConversationContext(paper)
    router = LLMRouter(config)
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


def batch_parse(papers_dir: str) -> None:
    dir_path = Path(papers_dir)
    if not dir_path.is_dir():
        print(f"错误: 不是目录: {papers_dir}")
        sys.exit(1)

    pdf_files = sorted(dir_path.glob("*.pdf"))
    if not pdf_files:
        print(f"目录中没有 PDF 文件: {papers_dir}")
        sys.exit(1)

    print(f"在 {papers_dir} 中找到 {len(pdf_files)} 个 PDF\n")

    # ── Phase 1: MinerU parsing (VLM on GPU) ──
    print("── 阶段 1/2: MinerU 版面解析 ──")
    parser = MinerUParser()
    parsed: list[PaperDocument] = []
    phase1_ok = 0
    phase1_fail = 0

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"  [{i}/{len(pdf_files)}] {pdf_path.name}")
        try:
            paper = parser.parse(str(pdf_path))
            parsed.append(paper)
            phase1_ok += 1
            print(f"    成功 — {len(paper.blocks)} 个块, {len(paper.chunks)} 个语义块, "
                  f"标题: {paper.title[:60]}")
        except Exception as e:
            phase1_fail += 1
            print(f"    失败 — {e}")
        print()

    # ── Phase 2: BGE-M3 encoding (embedding model on GPU) ──
    print("── 阶段 2/2: BGE-M3 向量编码 ──")
    phase2_ok = 0
    for paper in parsed:
        print(f"  {Path(paper.filepath).name}")
        try:
            ctx = ConversationContext(paper)
            embedded = sum(1 for c in paper.chunks if c.embedding)
            phase2_ok += 1
            print(f"    {len(paper.chunks)} 个语义块 ({embedded} 已编码)")
        except Exception as e:
            print(f"    编码失败 — {e}")
        print()

    print(f"完成: {phase1_ok} 解析, {phase1_fail} 失败 | {phase2_ok} 编码")


def main():
    if len(sys.argv) < 2:
        print("用法: python main.py <论文.pdf>")
        print("      python main.py --batch <论文目录>")
        sys.exit(1)

    if sys.argv[1] == "--batch":
        if len(sys.argv) < 3:
            print("用法: python main.py --batch <论文目录>")
            sys.exit(1)
        batch_parse(sys.argv[2])
        return

    paper_path = sys.argv[1]
    if not Path(paper_path).exists():
        print(f"错误: 文件不存在: {paper_path}")
        sys.exit(1)

    interactive_loop(paper_path)


if __name__ == "__main__":
    main()
