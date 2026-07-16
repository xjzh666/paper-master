import sys
from pathlib import Path

from prompt_toolkit import PromptSession

from paper_reader.mineru_parser import MinerUParser
from paper_reader.llm import load_config, LLMRouter
from paper_reader.context import ConversationContext
from paper_reader.memory import extract_memory, load_memory_cache


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

    from paper_reader.agent import PaperAgent
    agent = PaperAgent(
        text_client=router._text_client,
        vision_client=router._vision_client,
        ctx=ctx,
    )
    answer = agent.run(
        question=question,
        history=ctx.history[:-1],
        memory=ctx.paper.memory,
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
    print("── 阶段 1/3: MinerU 版面解析 ──")
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
    print("── 阶段 2/3: BGE-M3 向量编码 ──")
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

    # ── Phase 3: Paper Memory (LLM API) ──
    print("── 阶段 3/3: Paper Memory 结构化抽取 ──")
    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        print("  跳过: 未找到 config.yaml")
        config = None

    phase3_ok = 0
    if config:
        from paper_reader.llm import create_client
        text_client = create_client(config["models"]["text"])
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
          f"{phase3_ok} memory")


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
