import sys
from pathlib import Path

from prompt_toolkit import PromptSession

from paper_reader.mineru_parser import MinerUParser
from paper_reader.llm import load_config, LLMRouter
from paper_reader.context import ConversationContext
from paper_reader.memory import extract_memory, load_memory_cache
from paper_reader.observations import load_observations, save_observations
from paper_reader.zotero import ZoteroItem, ZoteroLibrary, resolve_zotero_data_dir


def show_overview(ctx: ConversationContext) -> None:
    print("\n" + "=" * 60)
    print(ctx.get_overview())
    print("=" * 60)
    print("\n直接输入问题即可。输入 /help 查看命令，exit、/quit 或 /exit 退出。\n")


def show_help() -> None:
    print("""
命令:
  /overview  - 重新显示论文概览
  /sections  - 列出所有章节
  /help      - 显示帮助
  exit       - 退出（不用斜杠也行）
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
    save_observations(ctx.paper.filepath, [o.to_dict() for o in ctx.observations])
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

    # 恢复跨提问累积的 session 观察
    from paper_reader.agent import Observation
    ctx.observations = [Observation.from_dict(o)
                        for o in load_observations(paper.filepath)]
    if ctx.observations:
        print(f"  [observations] 恢复 {len(ctx.observations)} 条历史发现")

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

        if user_input in ("/quit", "/exit", "exit"):
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


def zotero_interactive() -> None:
    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        config = None
    try:
        data_dir = resolve_zotero_data_dir(config)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)
    print(f"正在连接 Zotero 库: {data_dir}")
    lib = ZoteroLibrary(data_dir)
    try:
        _zotero_loop(lib)
    finally:
        lib.close()


def _zotero_loop(lib: ZoteroLibrary) -> None:
    session = PromptSession()
    current_items: list[ZoteroItem] = []
    while True:
        try:
            user_input = session.prompt("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not user_input:
            continue
        if user_input in ("/quit", "/exit", "exit"):
            print("\n再见！")
            break
        elif user_input == "/help":
            _zotero_help()
        elif user_input == "/collections":
            current_items = _pick_collection_items(lib, session)
        elif user_input == "/search":
            print("用法: /search <关键字>")
        elif user_input.startswith("/search "):
            current_items = _search_and_show(lib, user_input[len("/search "):].strip())
        elif user_input.isdigit():
            idx = int(user_input) - 1
            if 0 <= idx < len(current_items):
                _open_item(lib, current_items[idx])
            else:
                print("序号无效")
        else:
            current_items = _search_and_show(lib, user_input)


def _search_and_show(lib: ZoteroLibrary, keyword: str) -> list[ZoteroItem]:
    if not keyword:
        return []
    items = lib.search(keyword)
    _show_items(items)
    print("\n输入序号打开该论文，或继续搜索")
    return items


def _pick_collection_items(lib: ZoteroLibrary, session) -> list[ZoteroItem]:
    collections = lib.collections()
    top = [c for c in collections if c.parent_id is None]
    rows: list[tuple] = []

    def walk(cols, depth):
        for c in cols:
            rows.append((c, depth))
            walk([x for x in collections if x.parent_id == c.collection_id], depth + 1)

    walk(top, 0)
    for i, (c, d) in enumerate(rows, 1):
        print(f"[{i}] {'  ' * d}{c.name} ({c.item_count})")
    choice = session.prompt("选收藏夹(0 返回)> ").strip()
    if not choice.isdigit():
        return []
    n = int(choice)
    if n == 0:
        return []
    if not (0 < n <= len(rows)):
        print("序号无效")
        return []
    items = lib.items(collection_id=rows[n - 1][0].collection_id)
    _show_items(items)
    return items


def _show_items(items: list[ZoteroItem]) -> None:
    if not items:
        print("(无匹配条目)")
        return
    for i, it in enumerate(items, 1):
        colls = ", ".join(it.collections) if it.collections else "未分类"
        pdf = "" if it.has_pdf else " (无 PDF)"
        print(f"[{i}] {_format_authors(it.creators)} {it.year or '?'} — {it.title} ({colls}){pdf}")


def _format_authors(creators: list[str]) -> str:
    if not creators:
        return ""
    if len(creators) <= 3:
        return ", ".join(creators)
    return f"{', '.join(creators[:3])} et al."


def _open_item(lib: ZoteroLibrary, item: ZoteroItem) -> None:
    pdf = lib.resolve_pdf(item)
    if pdf is None:
        print("该条目没有可用 PDF，跳过")
        return
    print(f"正在加载论文: {pdf}")
    try:
        interactive_loop(str(pdf))
    except SystemExit:
        print("\n返回 Zotero 列表...")


def _zotero_help() -> None:
    print("""
命令:
  直接输入关键字  搜索论文（标题/作者）
  /collections   浏览收藏夹树
  /search <kw>   显式搜索
  /help          帮助
  exit / /quit   退出
""")


def main():
    if len(sys.argv) < 2:
        print("用法: python main.py <论文.pdf>")
        print("      python main.py --batch <论文目录>")
        print("      python main.py --zotero")
        sys.exit(1)

    if sys.argv[1] == "--batch":
        if len(sys.argv) < 3:
            print("用法: python main.py --batch <论文目录>")
            sys.exit(1)
        batch_parse(sys.argv[2])
        return

    if sys.argv[1] == "--zotero":
        zotero_interactive()
        return

    paper_path = sys.argv[1]
    if not Path(paper_path).exists():
        print(f"错误: 文件不存在: {paper_path}")
        sys.exit(1)

    interactive_loop(paper_path)


if __name__ == "__main__":
    main()
