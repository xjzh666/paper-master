### Task 1: 新增 Observation dataclass 和 _smart_truncate 辅助函数

**Files:**
- Modify: `paper_reader/agent.py` (在 ToolResult 之后插入)

**Interfaces:**
- Produces: `Observation` dataclass (summary: str, facts: list[str], entities: list[str], sources: list[str])
- Produces: `_smart_truncate(text: str, max_chars: int = 300) -> str`

**Description:** 在 agent.py 顶部添加 Observation 数据类和智能截断函数，为后续工具和压缩逻辑提供基础。

- [ ] **Step 1: 添加 Observation dataclass 和 _smart_truncate**

在 `agent.py` 第 28 行（ToolResult 定义之后）插入：

```python
@dataclass
class Observation:
    """LLM 在每轮检索后记录的结构化观察。"""
    summary: str
    facts: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _smart_truncate(text: str, max_chars: int = 300) -> str:
    """在句子边界截断文本，避免断句。"""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    for sep in ['. ', '。', '\n', '；', '; ']:
        idx = truncated.rfind(sep)
        if idx > max_chars * 0.5:
            truncated = truncated[:idx + len(sep)]
            break
    return truncated.rstrip() + f"\n[已截断，原文共 {len(text)} 字]"
```

- [ ] **Step 2: 运行现有测试确认无回归**

```bash
python3 -m pytest tests/test_agent.py -v
```

Expected: 全部 PASS（新代码未被引用，不影响现有测试）

- [ ] **Step 3: 提交**

```bash
git add paper_reader/agent.py
git commit -m "feat: add Observation dataclass and _smart_truncate helper"
```

---

