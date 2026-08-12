# Zotero 连接（CLI 优先）— 设计

日期：2026-08-12
状态：已批准

## 目标

从 Zotero 本地库拿到论文 PDF + 元数据，不用手动拷贝文件，喂给现有 paper-master 管线（MinerU 解析 → 语义块 → Paper Memory → 对话循环）。读取层做成独立模块（zotero.py，共享核心），同时提供两种消费接口：CLI（本阶段实际读论文的交互入口）和 FastAPI（后续桌面前端 / 模型 agent 复用的数据接口）。

成功标准：
1. `python3 main.py --zotero` 能列出/搜索 Zotero 库中的论文（含元数据：标题、作者、年份、类型、期刊、收藏夹）
2. 选中论文后直接解析 PDF 进入现有对话循环，无需手动把 PDF 放进 `papers/`
3. FastAPI 暴露 Zotero 收藏夹 / 条目 / 搜索接口，CLI 与 API 共用 `zotero.py` 数据层
4. 读取层是只读的，不修改 Zotero 任何文件

## 已核实的现状（2026-08-12）

- Zotero 安装在 Windows 主机，数据在 `/mnt/c/Users/ASUS/Zotero/`（WSL2 可访问）
  - `zotero.sqlite`（15MB）+ `storage/`（125 个附件目录）
- 库内容：112 条可读条目（44 journalArticle / 39 conferencePaper / 11 webpage / 8 preprint / 8 note / 1 report / 1 blogPost），100 个 PDF 附件
- 收藏夹树：`课题组`（父，含 蜜罐/蜜罐识别/论文分享/运营商项目/多智能体 5 个子）+ 顶层 `研讨厅第一篇/第二篇/第三篇`；同一篇论文可在多个收藏夹
- linkMode 分布：1（stored file，111 个）→ `storage/{attachment_key}/{filename}`；0（linked file，14 个）→ 磁盘绝对路径
- 已验证 stored PDF 解析：`{zotero_dir}/storage/{attachment_item.key}/{filename}` 存在（如 `storage/I3UTCUKN/Shao...pdf`）
- Zotero **无结构化引用关系**：`itemRelations` 为空（0 行）；论文内 References 列表非结构化（paper-master 解析的 PDF 内容里本来就有，但不可当图查询）
- 现有管线：`main.py interactive_loop(paper_path)` 已封装 加载（MinerU+缓存+memory）→ 对话 整条链，Zotero 模式复用

## 架构

```
                      ┌─ main.py --zotero ── CLI（本阶段交互入口）
                      │      └─ zotero_interactive()  选论文循环（搜索/收藏夹）
                      │            └─ resolve_pdf(item) → 路径
                      │                  └─ interactive_loop(路径)  复用现有加载+对话
paper_reader/zotero.py ─┤
  ZoteroLibrary(data_dir)   ← 共享核心（只读数据层）
    .collections() -> list[ZoteroCollection]   # 收藏夹树
    .items(collection_id=None) -> list[ZoteroItem]
    .search(keyword) -> list[ZoteroItem]       # 标题/作者模糊匹配
    .resolve_pdf(item) -> Path | None
    .close()
                      │
                      └─ paper_reader/server.py ── FastAPI（供桌面前端/模型 agent 复用）
                             GET /api/zotero/collections
                             GET /api/zotero/items?collection_id=
                             GET /api/zotero/search?q=
                             GET /api/zotero/items/{item_id}

config.yaml 新增:
  zotero:
    data_dir: /mnt/c/Users/ASUS/Zotero
```

依赖：fastapi + uvicorn 已装在 venv（fastapi 0.139.0 / uvicorn 0.51.0），无需新增依赖。

## 数据模型（zotero.py）

```python
@dataclass
class ZoteroCollection:
    collection_id: int
    name: str
    parent_id: int | None
    item_count: int

@dataclass
class ZoteroItem:
    item_id: int
    key: str
    title: str
    creators: list[str]        # 作者（有序）
    year: int | None           # 从 date 字段取前 4 位
    item_type: str             # journalArticle / conferencePaper ...
    publication: str | None    # 期刊/会议名
    doi: str | None
    collections: list[str]     # 所在收藏夹名
    has_pdf: bool
    pdf_path: Path | None      # resolve 后填充
```

## SQLite 只读访问

连接：`sqlite3.connect('file:{data_dir}/zotero.sqlite?mode=ro', uri=True)`。全连接共用只读模式，绝不写。

查询要点：
- 排除 `deletedItems`；排除 attachment / note / annotation 类型条目（只列可读论文条目）
- 元数据：`itemData` join `itemDataValues` join `fields` 拼 title / date / DOI / abstractNote / publicationTitle
- 作者：`itemCreators` join `creators`（按 orderIndex 排序），`fieldMode=1` 时 `lastName` 为完整姓名（无空格）
- 年份：date 字段取前 4 位数字，解析失败置 `None`
- 收藏夹：`collectionItems` join `collections`，保留去重后的名称列表
- 条目是否可读：有 `itemAttachments` 中 `contentType='application/pdf'` 且 `parentItemID=本条目` 的附件

## PDF 路径解析（核心）

对条目找到的 PDF 附件按 linkMode 处理：
- `linkMode=1`（stored file）：文件在 `{zotero_dir}/storage/{attachment_item.key}/{filename}`，其中 `filename` = `path` 去掉 `storage:` 前缀
- `linkMode=0`（linked file）：`path` 是磁盘绝对路径，直接检查存在性
- 其它（imported_url 等）：`has_pdf=False`
- 解析后 `os.path.exists()` 校验，不存在则 `has_pdf=False`

## CLI 交互（main.py --zotero）

```
$ python3 main.py --zotero
正在连接 Zotero 库: /mnt/c/Users/ASUS/Zotero
> honeypot                    ← 直接输关键字 = 搜索（标题/作者模糊匹配）
  [1] Sladić 2024 — LLM in the Shell: Generative Honeypots (蜜罐, 蜜罐识别)
  [2] Cabral 2021 — Advanced Cowrie Configuration... (蜜罐)
> 1                            ← 输序号打开
正在加载论文: /mnt/c/.../storage/9AUSNEXD/Sladić...pdf
[memory] 从缓存加载
===== 论文概览 =====
> ...                         ← 进入现有对话循环
```

- 命令：`/collections`（顶层收藏夹编号列出，子收藏夹缩进显示→选收藏夹→列其中论文）、`/search <kw>`（显式搜索）、`/quit`、`/help`
- 搜索匹配：大小写不敏感的标题 / 作者子串匹配，按标题排序
- 列表显示：`序号 作者 年份 — 标题 (收藏夹)`，无 PDF 标 `(无 PDF)`
- 选中后打印 PDF 路径 → 复用 `interactive_loop(pdf_path)`：首次走 MinerU 解析（1-2 分钟），之后 sha256 缓存秒开；Paper Memory 缓存照常加载
- 搜索结果显示后保持在同一选择循环，直到输入序号打开或退出

## FastAPI API 层

`paper_reader/server.py`，复用 `load_config` + `ZoteroLibrary`：

| 端点 | 说明 |
|---|---|
| `GET /api/zotero/collections` | 收藏夹树（含 item_count） |
| `GET /api/zotero/items?collection_id=X` | 条目列表；无参数返回全部可读条目 |
| `GET /api/zotero/search?q=<kw>` | 标题/作者模糊匹配（同 CLI 搜索逻辑） |
| `GET /api/zotero/items/{item_id}` | 单条目详情（含 pdf_path / has_pdf） |

- 每请求用依赖注入创建 `ZoteroLibrary(data_dir)`（只读连接，用完关闭），避免线程共享问题
- `data_dir` 读取 config.yaml 的 `zotero.data_dir`，未配置时自动探测
- 响应序列化 `ZoteroItem` / `ZoteroCollection`（`dataclasses.asdict`）
- 启动：`uvicorn paper_reader.server:app`（桌面阶段再由 Tauri 自动拉起）
- **本阶段 API 不返回论文内容**：前端读论文用 MinerU 的 markdown 渲染（设计决策 #4，不集成 pdf.js）。"按条目返回解析内容（markdown + 章节 + 图片）"端点属桌面阶段——管线已能产出 `.md`，届时加一个端点即可。本阶段 API 只暴露检索 / 元数据 / PDF 路径

## 配置

```yaml
zotero:
  data_dir: /mnt/c/Users/ASUS/Zotero   # zotero.sqlite 所在目录
```

默认自动探测顺序：`data_dir` 配置 → `~/Zotero`（Linux）→ `/mnt/c/Users/*/Zotero`（WSL2 Windows 侧）→ 找不到则报错提示配置。

## 错误处理

- `data_dir` 无 `zotero.sqlite` → 报错并提示在 config.yaml 配置
- sqlite 读锁 / journal 恢复异常（Zotero 正在运行）→ 提示"关闭 Zotero 后重试"
- 条目无 PDF / PDF 文件丢失 → 列表标 `(无 PDF)`，打开时提示跳过
- 全程只读，不写 Zotero 任何文件

## 测试

- fixture：临时目录造最小 Zotero schema（items / collections / collectionItems / itemAttachments / itemData / itemDataValues / fields / itemTypes / creators / itemCreators / deletedItems），插入假数据，测试后清理
- 覆盖用例：
  - `search()` 标题/作者模糊匹配
  - `resolve_pdf()` stored / linked / 无PDF 三分支
  - `collections()` 树形结构 + 子收藏夹
  - 元数据拼接（作者顺序、年份解析、fieldMode 单字段作者）
  - 删除条目排除、多收藏夹去重
- 不依赖真实 Zotero 库，本机与 CI 均可运行
- API 层：用 fastapi TestClient + fixture sqlite，测 collections / items / search / items/{id} 四个端点

## 范围外（本阶段明确不做）

- Tauri / React 桌面界面（下阶段）
- 按条目返回解析内容（markdown + 章节 + 图片）的端点，以及对话会话管理（均属桌面阶段）
- 多论文统一索引（跨论文检索）
- 引用图（Semantic Scholar / PDF 引用列表结构化）
- Zotero 写操作、笔记/标注读取
