# P3 引用溯源 spec：回答引用可点击 + 阅读区滚动高亮

> 状态：已完成 2026-09-08。分支 feature/p3-citations 保留待合并（提交 aea3cc9..c8582f5，277 pytest + 39 vitest 全过，终审可合并）。用户选择暂不合并。

（2026-09-08 经 onegate 流程批准；执行期间本文件是唯一权威源，偏差记台账，收尾折入本节末尾）

## 目标

回答中的关键陈述带可点击的来源引用；点击后右侧阅读区滚动到对应原文位置并高亮来源块，让用户逐段核对「这段话来自论文哪里」。

## 架构决定

三层各加一件小事，用 chunk 作为引用的统一锚点：

1. **检索层标注**（agent.py）：`search_paper` / `get_section` 返回给 LLM 的文本按 chunk 分组，每组前加来源标签 `[src chunk_N §<标题> p.<页>]`。LLM 从此有真实来源可引。
2. **回答协议**（system prompt）：LLM 在关键陈述后输出 markdown 链接 `[§x.x p.N](cite:chunk_N)`——引用即文本，SSE 流式与历史持久化零额外协议。ChatPanel 配置 `urlTransform` 放行 `cite:` scheme（react-markdown 默认白名单会滤掉自定义 scheme），并用事件委托拦截 `cite:` 链接点击。
3. **定位数据**：新端点 `GET /api/papers/{id}/chunks-index` 返回每 chunk 的 `{id, page, section, snippets[]}`；App 在论文 ready 后拉取存入 state；ReadingPanel 收到点击目标后在已渲染 DOM 中按 snippet 归一化匹配，scrollIntoView + 高亮闪烁。

数据流：点击 `[§3.2 p.4](cite:chunk_12)` → ChatPanel `onCite("chunk_12")` → App state（一次性事件）→ ReadingPanel 定位高亮。

## 全局约束

- **链接格式**：`[§<编号> p.<页>](cite:chunk_<N>)`；section 无编号时（Abstract/References 等）链接文本写 `[p.<页>](cite:chunk_N)`；`chunk_N` 只能取**当前上下文中可见标签**里出现过的编号，禁止编造；压缩移除了标签的早期 chunk 宁可不加链接
- **标签格式**：`[src chunk_<N> §<标题> p.<页>]`，置于该组文本之前独立一行；section = section_path 末条剥 HTML，为空则省略 § 部分写作 `[src chunk_N p.N]`；页码统一 `p.4` 格式，值 = 块的**最小** page_idx + 1
- **snippets**（chunks-index）：取 chunk 的**前 6 个** text 类块（跳过 image/table/formula），先剥除 `$...$`/`$$...$$` 数学区段，再剥 HTML 标签，取前 80 字符
- **归一化规则**（snippet 与 DOM textContent 两侧同规则）：lowercase + 移除所有空白 + 移除 ASCII 标点 `.,;:!?(){}[]<>"'` ~@#$%^*+=|\/-_`；DOM 侧取元素 textContent 时**排除 `.katex` 子树**
- **DOM 候选元素**：`p, li, h1-h6, blockquote, td, th, pre`；多处命中取**最深**元素；表格/公式块本就不在 snippets 里，匹配不到属预期
- **交互生命周期**：citeTarget 为一次性事件（递增序号，消费不重放）；切换论文清空 citeTarget 与 chunks-index；索引未就绪时点击 → antd message「原文索引尚未就绪」，不滚动
- **高亮**：命中元素加高亮类，3000ms 后移除；多 snippet 命中滚到**第一个**命中块
- 新端点挂 `/api/papers/*` 路由组，paper 未解析返回 404；历史持久化格式不变，重启后旧链接仍可点；CLI 路径不改（终端原样显示 markdown 链接，接受）

## 验收标准

后端（pytest）：
1. mock paper 含 2 chunk（chunk_0: section_path=["3.2 Method"]、blocks page_idx=3），`search_paper` 返回文本每个 chunk 文本前恰好一行 `[src chunk_0 §3.2 Method p.4]` 形式标签
2. `get_section("3.2")` 返回内容按 block→chunk 映射分组、每组前置标签，截断发生在组内该组标签照加；标题块找不到所属 chunk 时无标签不报错
3. `GET /api/papers/{id}/chunks-index`：跨页 chunk（blocks page_idx=3,4）→ `"page": 4`；snippet 已剥公式与 HTML、≤80 字符/条、≤6 条、只含 text 块；未解析 paper → 404
4. SYSTEM_PROMPT 断言含 `"(cite:chunk_"` 与「禁止编造」语义的关键句
5. **合同测试**：mock LLM 固定回答 `[§3.2 p.4](cite:chunk_0)`，经 `chat_events` 的 answer_chunk 流透传后拼接文本含该链接

前端（vitest + jsdom）：
6. MarkdownMessage 渲染产物存在 `a[href="cite:chunk_12"]`（先断言 scheme 未被 urlTransform 滤掉）；点击不导航、`onCite` 收到 `"chunk_12"`；`http(s)` 链接不受影响
7. 定位函数：归一化子串匹配（取最深元素）；含公式 DOM（`.katex` 子树被排除）与 `- ` 列表项开头 snippet 各一个用例；chunk 多 snippets 逐一匹配、部分命中只高亮命中块、scrollIntoView 调用于第一个命中
8. 无一命中 → antd message「未在原文中定位到该片段」，不滚动；高亮类 3000ms 后移除

归一化正例：snippet `"We evaluate <b>SOTK</b> on 200 nodes."` → key `weevaluatesotkon200nodes`，DOM `<p>We evaluate SOTK on 200 nodes…</p>` 命中。反例（公式）：含 `$x^2$` 的源文本对应 DOM 中 `.katex` 区域，排除后不产生虚假匹配/失败。

## 任务清单（串行执行序）

1. **检索标签**：agent.py `search_paper`/`get_section` 按 block→chunk 对象身份映射分组加标签（含 3000 字截断语义）+ 单测（验收 1/2）；**允许同步更新断言工具返回文本的既有测试**
2. **引用协议**：SYSTEM_PROMPT 增加协议段（链接格式、无编号规则、禁止编造、压缩后宁可不引）+ record_observation 的 sources 沿用检索标签格式 + 单测（验收 4）
3. **chunks-index 端点**：papers.py `get_chunks_index`（最小 page_idx+1、公式/HTML 剥离、前 6 text 块 80 字符）+ server.py 路由 + 单测（验收 3）
4. **前端 api client**：`chunksIndex(pid)` + TS 类型
5. **ChatPanel 点击拦截**：`urlTransform` 放行 `cite:` + 事件委托 → `onCite(chunkId)`；App 增加 citeTarget（一次性序号）与 chunks-index 拉取/清空 + vitest（验收 6）
6. **ReadingPanel 定位高亮**：归一化/匹配纯函数 + 高亮闪烁 3000ms + scrollIntoView + 未命中/未就绪 message + vitest（验收 7/8）
7. **合同测试 + 收尾**：chat_events 透传链接的合同测试（验收 5）+ `npm run build` + 全量测试 + CLAUDE.md 更新（P3 状态、数据流、端点）

## 执行默认

当前分支 feature/p3-citations 直接执行（不开 worktree）；每任务一次提交；永不 push/merge（finishing 阶段用户决定）。

## 执行结果与裁决（收尾折入）

实现映射：任务 1 检索标签（agent.py `_chunk_src_label`/`_group_blocks_by_chunk`/`_labeled_chunks_text`，f23df38）；任务 2 引用协议（SYSTEM_PROMPT + record_observation 描述，cc818f4）；任务 3 端点（papers.py `get_chunks_index` + server.py，eeb5357）；任务 4+5 前端链路（client.ts `chunksIndex`/`ChunkIndexEntry`、ChatPanel `citeUrlTransform`+`onCite`、App `chunkIndex`/`citeTarget{chunkId,seq}`，7cdd007）；任务 6 定位高亮（frontend/src/citation.ts `normalizeKey`/`elementKeyText`/`locateCiteTargets` + ReadingPanel props + cite-highlight.css，3fc1bc8）；任务 7 合同测试 + 文档（c8582f5）。

与 spec 字面的偏差（均为评审/控制者裁决接受）：
- search_paper 返回文本按**检索顺序**组装（spec 未明说顺序；真实 build_context 按 paper 序 sorted，实现丢弃其文本）
- record_observation **顶层** description 例值同步改为 chunk 格式（第三处文本改动，避免与参数级示例矛盾）
- chunks-index 对零 blocks 退化 chunk 用 `min(default=0)` 防护（page=1）；归一化后为空的 snippet 按未命中跳过（防 `includes('')` 恒真误高亮）；同深度多命中取文档序第一个
- App 拉取 chunks-index 失败降级为"未就绪"（catch → null），不阻塞论文加载

终审遗留（合并后处理）：prompt 断言加"可见"子串收紧；合同测试补磁盘 {paper_id}-history.json 断言；未配对 `$` 误剥 snippet 文本（可复用 math_quality 检测）；citation.ts 候选 key memoize（O(snippets×candidates)）。
终审建议：合并后用真实论文手动冒烟一次（提问→点击引用→阅读区高亮）——`.md` 渲染文本与 block.text 的对应性无自动化覆盖。
