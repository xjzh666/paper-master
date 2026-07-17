# Tool Result 压缩 + 三层记忆架构

## 问题

Agent 循环中每轮 tool result 全量追加到 messages，7 轮 × 每轮数千字 → 上下文快速膨胀，token 成本和推理质量双降。

## 三层记忆架构

借鉴 Claw Code 分层思想，将 Agent 记忆分为三层：

| 层 | 名称 | 生命周期 | 内容 |
|---|---|---|---|
| L1 | Conversation Memory | 当前对话 | messages 数组，最新 1 轮 tool result 完整，往轮压缩 |
| L2 | Observation Memory | 跨轮累积 | 结构化观察：summary + facts + entities + sources |
| L3 | Evidence Memory | 长期 | 事实 → 来源映射（P3 引用溯源基础） |

当前实现 L1+L2，L3 留到 P3。

## 核心机制

### 压缩策略

发送 LLM 前遍历 messages：
- 最新一轮 tool result → 保留原文
- 往轮 tool result → 替换为对应 Observation.summary（无 observation 则截断到 300 字）
- assistant(tool_calls) 消息不动

### Observation 产生

新增 `record_observation` 工具。LLM 在看完检索结果后同一轮内调用，不增加额外 API 调用：

```json
{
  "summary": "注意力机制通过 Q/K/V 计算序列内位置间的关联权重",
  "facts": ["Scaled Dot-Product Attention 公式为 softmax(QK^T/√d_k)V",
            "Multi-head 允许不同子空间表示"],
  "entities": ["Attention", "Q/K/V", "Softmax", "Multi-head"],
  "sources": ["p3 §3.1", "p4 §3.2"]
}
```

### 降级

LLM 不调用 record_observation 时，往轮 tool result 做智能截断：找句号边界，保留前 300 字 + `[已截断]`。

## 数据流

```
第 N 轮:
  LLM 输出: tool_calls=[search_paper("...")]
  Agent 追加: assistant(tool_calls) + tool(result_N)  ← result_N 完整保留

第 N+1 轮（发送前）:
  _compact_messages(): result_N-1 → 替换为 obs_{N}.summary（或截断）

第 N+1 轮（LLM 输出）:
  tool_calls=[record_observation(summary="...", facts=[...], ...),
              search_paper("...")]
  Agent 追加: assistant(tool_calls) + tool(obs_result) + tool(result_{N+1})
```

## 实现范围

只改 `paper_reader/agent.py`：

1. `Observation` dataclass
2. `record_observation` 工具加入 `_make_tools`
3. `_compact_messages(messages, observations, current_round)` — 发送前压缩
4. agent loop 中每轮发送前调用 `_compact_messages()`
5. system prompt 增加引导：检索后调用 record_observation
6. 测试：验证压缩逻辑（截断边界、observation 替换、最新轮保留）

## 与后续关系

- P3 引用溯源：Observation.sources 直接可用
- Paper Memory 增量更新：累积 observations 可合并入 Paper Memory
- 多轮对话：Observation Memory 跨轮累积，提供长期上下文
