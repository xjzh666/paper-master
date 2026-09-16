# P6.1 扩展：S2 主源搜索与 triage 增强 — 设计

日期：2026-09-15
状态：已完成 2026-09-15（分支 p61-external-paper-search 保留未合并；最终提交 9a48ce5；整体评审合并就绪）
决策依据：决策 #21（兜底链）、#20（源选型修订）、2026-09-15 实测（S2 key 生效；搜索 10/10 带 arXiv id/摘要/tldr + 引用数）

## 目标

搜索主源切换为 Semantic Scholar（带 key），搜索结果自带摘要/tldr/引用数，agent 工具具备"判断论文值不值得下载精读"的 triage 能力；下载链路不变（arxiv_id → arXiv CDN）。

## 已确认决策

- S2 为搜索链首源（用户定）；arXiv 第二；OpenAlex 第三
- key 已申请（实现期由控制者写入 config.yaml，不入 git）
- OpenAlex 摘要重建不做（S2 覆盖，YAGNI）

## 架构

数据流：查询 → search_with_fallback() → S2（有 key）→ arXiv → OpenAlex → (结果, source, notice) → 前端列表 / agent 工具（含摘要/tldr/引用数）→ 点击 → 既有下载管线（arxiv_id → arXiv CDN）。

### 1. ArxivResult 扩展（arxiv_search.py）

新增带默认值字段 `tldr: str = ""`、`citation_count: int | None = None`（追加在末尾，既有构造零改动）；arXiv/OpenAlex 腿不填；既有"9 字段精确断言"测试同步改为 11 字段。

### 2. 新模块 paper_reader/s2_search.py

- `search(query, max_results=10) -> list[ArxivResult]`
- GET `https://api.semanticscholar.org/graph/v1/paper/search?query={URL编码}&limit={clamp 1..50}&fields=title,authors,abstract,tldr,citationCount,externalIds,year`，头 `x-api-key`
- key 缺失抛 `S2NotConfiguredError`；429 → sleep 5s 重试一次 → 再 429 抛 `S2RateLimitError`（文案"Semantic Scholar 限流中，请稍后重试"）；401/403 抛 `S2Error` 并 `logging.warning`（坏 key 可诊断）；其余网络异常透传
- 解析（S2 响应形状已实测）：信封键为 `data`；仅保留 `externalIds.ArXiv` 非空的记录；映射 `tldr=(p.get("tldr") or {}).get("text") or ""`、`abstract=p.get("abstract") or ""`、`published=str(p["year"]) if p.get("year") is not None else ""`、`authors=[a["name"] for a in p.get("authors") or [] if a.get("name")]`、`citation_count=p.get("citationCount")`、`pdf_url/abs_url/updated/categories` 留空、title 做空白折叠
- 限速闸 1 req/s（模块级时间戳+锁，同 arXiv 模式）
- `load_api_key() -> str | None`：读 config.yaml `external_search.semantic_scholar.api_key`（复用 `paper_reader.llm.load_config`，容错缺失/坏 YAML 返回 None）；`search()` 内部调用，None 即抛 S2NotConfiguredError；测试 monkeypatch 模块属性

### 3. 编排链重排（arxiv_search.search_with_fallback）

- 顺序：S2（仅当 load_api_key() 非 None）→ arXiv → OpenAlex；source ∈ {"s2","arxiv","openalex"}
- 返回值改为三元组 `(results, source, notice)`
- notice 规则（区分"未配置"与"失败"）：S2 成功 → ""；未配置 key → 静默走 arXiv，""；配置了但 S2 失败 → "[Semantic Scholar 不可用，以下为 arXiv 检索结果]"；落 OpenAlex → "[arXiv 暂不可用，以下为 OpenAlex 兜底结果]"（现有文案迁移）
- 空结果语义不变（当前腿的空结果 = 合法答案，不触发后续兜底）
- 调用点（server、agent 工具、测试）同步适配三元组

### 4. OpenAlex 末位腿改进（openalex_search.py）

- URL 加 `&filter=primary_location.source.id:S4306400194`；select 加 `primary_location`
- 提取优先级：doi（10.48550/arxiv.{id}）→ best_oa_location.pdf_url（arxiv.org/(pdf|abs)/{id}）→ primary_location.landing_page_url（arxiv.org/abs/{id}）；均剥尾 `.pdf` 与版本号；按 arxiv_id 去重（已有）

### 5. server / 前端

- server 检索端点零逻辑改动（三元组解包，source/notice 透传；notice 不进前端响应，仅供工具与日志）
- client.ts：`source?: 'arxiv' | 'openalex' | 's2'`；`ArxivResult` 接口加可选 `tldr?` / `citation_count?`
- PaperListSidebar：作者行追加 `· 被引 {n}`（citation_count 非空时）；source=='s2' 蓝 Tag「Semantic Scholar」；'openalex' 橙「OpenAlex 兜底」；'arxiv' 无标签

### 6. agent 工具输出增强（agent.py）

- 每条：`"{i}. {title} ({year}, 被引 {n}) — {authors} [arxiv_id: {id}]"`，citation_count 为 None 时省略"， 被引 N"段；第二行摘要 `tldr 优先，否则 abstract，截断 200 字`（皆空省略该行）
- 首行 = notice（非空时）；尾部提示行不变
- description 同步更新：声明返回含摘要/tldr/被引数

### 7. 配置

- config.example.yaml 追加 `external_search.semantic_scholar.api_key: ""`（空占位 + 注释"留空则 S2 源禁用"）
- 真实 key 由控制者写入 config.yaml（gitignored，不进任何被跟踪文件）

## 全局约束

- 下载链路零改动；测试零触网零真睡；打桩在模块边界
- conftest 加 autouse fixture 默认禁用 S2（monkeypatch load_api_key → None），凡触 search_with_fallback 的既有测试在配 key 机器上不得真触网；S2 专属测试显式覆盖该 fixture
- 既有三源测试保持或同步更新，零回归（基线 pytest 348 / vitest 51）

## 验收标准

1. （打桩）配置 key → source=="s2"，结果含非空 tldr 与 citation_count
2. （打桩）load_api_key → None → source=="arxiv"、notice==""、无异常
3. （打桩）S2 首 429 → sleep(5) 重试成功；双 429 → 抛 S2RateLimitError 且编排落 arXiv 且 notice 正确
4. （打桩）S2 fixture 含 2 条无 ArXiv id → 只返回 8 条
5. （打桩）OpenAlex fixture（data 键、landing_page_url 形态、含重复记录）→ 10/10 可提取、去重生效
6. （打桩）工具文本：S2 结果每条含"被引 N"+摘要行（tldr 优先）；无 citation_count 的腿不出现"被引 None"
7. 前端三种 source 标签正确（vitest）；client 类型三值
8. 全量 pytest（348+新增）+ vitest（51+新增）+ build 全绿
9. （手工，控制者+用户）浏览器真实 key 全链：搜 "retrieval augmented generation" → 蓝 S2 标签 + ≥8 条带摘要与引用数 → 点开下载解析对话正常

## 不做清单

- OpenAlex 摘要重建；S2 PDF 下载（实测不可靠）；S2 batch 端点（搜索 fields 已够，留待真实需求）；多 key 轮换

## 实施拆解（串行）

1. ArxivResult 扩展 + s2_search.py（search/闸/重试/过滤/映射/key 加载/异常）+ 单测
2. search_with_fallback 链重排（三元组 + notice + S2NotConfigured）+ OpenAlex filter/提取补全 + conftest autouse fixture + 测试
3. server 透传 + client.ts + 前端标签与引用数 + 测试
4. agent 工具输出增强 + description 更新 + 测试
5. config.example.yaml 占位 + 文档同步（CLAUDE.md、decisions #22、architecture.md、history.md）
6. 浏览器真实 key 全链验证（控制者+用户）+ 最终评审

## 执行期裁决记录

提交：33f4042（T1 s2_search 模块）→ 530af42（T2 链重排）→ b641f30（T3 前端）→ 27d081e（T4 工具增强）→ 1192cd9（T5 配置与文档）→ f5f2c7c（spec 归档）→ 9a48ce5（最终评审修复）。测试 392→393 pytest / 55 vitest。

1. **S2 直接做首源**（用户裁决，推翻控制者"第三兜底+增强"推荐）——相关性最强 + triage 字段搜索期直取。代价：依赖 key（缺失静默降 arXiv）；非 arXiv 论文被过滤；S2 索引滞后数天（arXiv 第二源吸收）
2. **conftest 受控偏差**（T2）：打桩 `load_config` 替代 brief 字面的 `load_api_key`——任务 1 围栏外测试直测真函数，逐字照做必破零回归；评审三点核实成立（理由真/效果恒等/启用机制无泄漏）
3. **description 两行措辞折进 T5**（控制者裁决）：评审指出归属缝隙，作为围栏例外显式授权
4. **浏览器验收两瑕疵均不修记台账**（用户裁决，推翻评审"顺手带上"建议）——见下节遗留清单
5. **丢弃工作区残留的 ellipsis 未提交改动**（控制者）：对齐裁决 4，修法在下节
6. **最终评审仅修 JSONDecodeError 一项**（控制者）：排除评审者顺手修 A/C 建议，用户裁决优先

## 遗留清单（合并/后续处理时参考）

- 侧栏摘要单行截断：PaperListSidebar.tsx 摘要 Paragraph ellipsis 无参 = AntD 默认单行。修法：`ellipsis={{ rows: 3 }}`（保留 160 字截断）
- agent 轮次耗尽兜底：幻觉章节名 × find_section 兜底对多查询返回同一块内容（决策 #17 既有局限）× 循环耗尽落 agent.py:658 固定文案（已收集信息未变成回答）。改善方向：耗尽时基于 observations 合成部分回答 + 兜底重复内容检测。归 P6.2 前打磨
- server.py:81 陈旧注释"双源皆败"（三源现实，一处注释）
- download_pdf .part 并发竞态唯一化（pid/tid 或 per-id 锁）——上次整体评审遗留，唯一带正确性色彩项
- agent 工具 max_results 无 clamp；429→401 组合无专测；两处假 key 常量不一致；citation_count:0 前端无回归测试
- docs/s2-folks-main/ 未跟踪（S2 官方示例库参考资料，与 llm-wiki.md 等同待遇）
