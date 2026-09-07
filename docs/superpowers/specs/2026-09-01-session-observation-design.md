# Session Observation Memory 与中间产物落盘 — Design Spec

## 问题

两处中间产物目前都在流失：

1. **observations 活不过单次提问**。`record_observation` 只在单次提问的 agent 循环内发挥作用（压缩往轮 tool result）。两个入口（server 的 `chat_events`、CLI 的 `handle_question`）都是每问新建 `PaperAgent`，`_observations` 随实例销毁；`agent.py` 中"注入已累积观察"的代码因此是死代码。跨提问时模型不知道之前检索发现过什么，追问只能从 history 的最终答案里找线索。
2. **`describe_image` 的结果不可重建**。图表描述调 vision API，花钱耗时，且无法从论文文本索引重建。同一篇论文再次问到同一张图，只能再烧一次 API 调用。

明确**不存**的一类：`search_paper` / `get_section` 返回的检索原文。论文 chunk 索引本身就是这些内容的持久化 + 检索层，BGE-M3 本地重查免费且即时，没有东西会丢。

## 核心原则

- **可重建的不存，不可重建的才存**：检索原文不存；模型产物（观察摘要、图表描述）落盘。
- **observations 所有权上移**：从 `PaperAgent`（提问级）移到 `ConversationContext`（session 级），并持久化到磁盘。
- **磁盘全量、注入有界**：磁盘是 append-only 的证据日志；注入 system prompt 只取最近 N 条。
- **生命周期分清**：observations 是会话级产物，与 history 同生同灭；图像描述是论文级产物，独立于会话，清空对话不影响。

## 数据流

```
提问 N:
  run 开始:  system prompt 注入 ctx.observations 最近 20 条（含之前提问的发现）
  run 中:    record_observation → 追加到 agent 的 per-run 列表（压缩用，逻辑不变）
             describe_image → 先查图像描述缓存，命中直接返回；未命中调 API 并写盘
  run 结束:  per-run 观察打上 question 标记，并入 ctx.observations（finally，异常也保留）；
             ctx.observations 全量写入 {sha}-observations.json

提问 N+1（或重启后重新打开论文）:
  ctx.observations 从磁盘恢复，注入生效
```

## 设计细节

### 1. Session 级存储

```python
# paper_reader/context.py — ConversationContext 新增字段
self.observations: list[Observation] = []
self.image_descriptions: dict[str, str] | None = None  # 懒加载
```

`Observation` 仍定义在 `agent.py`，context.py 用 `TYPE_CHECKING` 引用避免循环 import。

```python
# Observation 新增字段
question: str = ""   # 产生该观察的用户提问，flush 时由 agent 统一标记
```

### 2. 记录标准放宽

system prompt 引导语从"记录本轮关键发现"放宽为：

- 检索中看到的关键数字、实验设置、结论性陈述，**即使与当前问题无直接关系**，只要对理解论文有长期价值就记录
- `sources` 事实上必填——落盘后这些是跨 session 证据，无出处无法复核

不做"全录每轮检索结果"：observation 的价值就在于模型的过滤层，全录等于囤积原文，体积和噪声都会冲垮注入质量。

### 3. Observations 落盘

新模块 `paper_reader/observations.py`，沿用 memory.py 的 sha256 keying 模式：

```
~/.cache/paper-master/{sha}-observations.json
{
  "paper_id": "…",
  "observations": [
    {"summary": "…", "facts": ["…"], "entities": ["…"],
     "sources": ["p3 §3.1"], "question": "实验用了什么数据集？", "round_num": 2}
  ]
}
```

- `Observation` 补 `to_dict` / `from_dict`
- **写**：server 在 `chat_events` 保存 history 的同一调用点；CLI 在 `handle_question` 答完后
- **读**：`open_paper` / CLI 启动加载 history 处一并恢复进 `ctx.observations`
- **清**：`DELETE /api/papers/{id}/history` 联动删除文件并清空 `ctx.observations`
- 磁盘全量保存（不去重，不同提问可能记到同一条事实，标注为已知限制）；**注入只取最近 20 条**（`SESSION_OBSERVATION_LIMIT`）

注入格式（替换现有死代码段）：

```
[已知信息 — 之前提问已检索到，未经复核]
1. (问: 实验用了什么数据集？) WMT 2014 EN-DE 4.5M 句对……
2. (问: base 和 big 模型差多少？) big 模型 BLEU 高 1.0……
```

"未经复核"标注是故意的：观察是 agent 中间产物，注入定位为线索而非事实，重要处模型应重新调工具验证。

### 4. describe_image 缓存

```
~/.cache/paper-master/{sha}-images.json
{
  "paper_id": "…",
  "images": {"images/img_3_0.jpg": "该图展示了……"}
}
```

- **key 用图片相对路径**（`image_path`），不能用 resource id——`image_5_0` 的尾号是当次调用的枚举序号，跨调用不稳定
- `describe_image` 首次调用时懒加载缓存到 `ctx.image_descriptions`；查缓存命中直接返回，未命中调 vision API、写入缓存并落盘
- 论文级产物：清空对话**不**清除；重新打开论文直接复用

### 5. 正确性与并发

- `_compact_messages` 继续只匹配 per-run 列表（每次 run 开始清空，现状不变），session 累积不参与压缩匹配
- server 的 `chat_events` 在 agent run 期间持有 `session.lock` + `CHAT_LOCK`，`ctx.observations` 读写串行化；CLI 单线程

## 实现范围

| 文件 | 改动 |
|------|------|
| `paper_reader/observations.py` | 新增：observations / image-descriptions 两个 JSON 缓存的读写（仿 memory.py） |
| `paper_reader/agent.py` | `Observation` 加 `question` + 序列化；`_run_loop` 注入源改 `ctx.observations`（最近 20 条）；finally flush 到 ctx；`describe_image` 查缓存/写缓存；system prompt 引导语放宽 |
| `paper_reader/context.py` | `ConversationContext` 新增 `observations`、`image_descriptions` 字段 |
| `paper_reader/papers.py` | `open_paper` 恢复 observations；`chat_events` 保存 observations；`clear_chat_history` 联动清除 |
| `main.py` | `interactive_loop` 启动时恢复、`handle_question` 答完后保存 |

### 测试

- `Observation` 序列化 roundtrip（含 question 字段）
- session 内：run 中 record 后 `ctx.observations` 增长且带 question；第二次 run 的 system prompt 含第一次的摘要
- 注入上限：ctx 中 25 条时 prompt 只含最近 20 条
- 落盘：保存→重开恢复；DELETE /history 后文件删除且 ctx 清空
- `describe_image`：缓存命中不调 vision client；未命中调一次后再次命中；按图片路径 key
- `FakeCtx` 补 `observations` / `image_descriptions`；修改 `test_agent_injects_observations_into_system_prompt` 的 seed 方式
- 现有压缩相关测试（per-run 行为）保持不变、保持通过

## Non-Goals

- 不存检索原文（`search_paper` / `get_section` 输出）——可由 chunk 索引免费重建
- 不做观察的去重 / 合并 / LLM 再总结（超注入上限自然截断，磁盘全量保留）
- 不做"检索轨迹索引"（每次工具调用的元数据日志）——讨论的折中方案，本期不做
- 不做 recall 工具——磁盘上超出注入上限的旧观察暂时不可达，留待后续
- 不改 `_compact_messages`、`_make_tools` 的其它逻辑、`merge_blocks`

## 与后续关系

- **L3 Evidence Memory（引用溯源）**：全量 observations + sources 就是"事实 → 出处"的数据基础，加 recall 工具即可激活
- **Paper Memory 增量更新**：累积的观察可作为 memory 修正输入
- **图像描述反哺 RAG**：`{sha}-images.json` 可在解析流程中预热，或并入 chunk 文本提升图表检索质量
