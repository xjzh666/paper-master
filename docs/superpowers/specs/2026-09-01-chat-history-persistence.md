# Spec: 对话历史落盘持久化

日期: 2026-09-01（实现后补写存档）
状态: 已实现

## 背景

对话历史 `ctx.history` 只存在于 `papers.sessions` 内存字典：关浏览器不丢（只要 uvicorn 活着），但**重启后端即全部丢失**。对话连续性是"科研伙伴"定位的前提，今天问过的结论明天必须还在。

## 目标

- 对话历史随论文持久化，重启服务后打开同一篇论文可恢复完整对话
- 与现有缓存体系同构（同一目录、同一命名模式）
- 任何异常不阻塞打开论文 / 对话主流程

## 非目标

- 不做历史的压缩或长度控制——prompt 尺寸问题留给"跨提问 session observation"（第二档）一起处理
- 不做加密、多设备同步、多会话分支

## 方案

- `papers.py` 新增 `load_chat_history(paper_id)` / `save_chat_history(paper_id, history)`，读写 `~/.cache/paper-master/{paper_id}-history.json`（`paper_id` 即 PDF sha256，与 `{sha256}-memory.json` 命名同构）
- 加载时机：`open_paper` 两条路径（缓存命中 / 首次解析）创建 Session 时 `session.ctx.history = load_chat_history(paper_id)`
- 保存时机：`chat_events` worker 中 `ctx.add_message("assistant", answer)` 之后立即保存
- 容错策略：
  - 加载侧轻校验（role ∈ {user, assistant}、content 为 str），损坏/非法内容静默过滤；JSON 解析失败返回空列表
  - 保存失败（IO 异常）静默忽略，不影响本轮回答
  - **回答出错不保存**——磁盘保留最近一次成功状态，避免留下悬空的用户提问

## 涉及文件

- `paper_reader/papers.py`（新增两个函数 + open_paper / chat_events 两处接线）
- `tests/test_papers.py`（3 个新测试）

## 测试计划

- 打开论文加载已持久化历史（内容与顺序断言）
- 损坏 history 文件 → 加载为空且状态 ready
- 完成一轮对话 → history 文件落盘且含 user/assistant 两条、内容正确
- 全量 pytest（231 例）通过

## 验收标准

- 问一轮 → 重启 uvicorn → 打开同一篇论文，对话记录完整恢复
- history 文件损坏不影响打开论文（降级为空历史）
- 对话出错不影响磁盘上已有历史
