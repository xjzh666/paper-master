from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Resource:
    """工具返回的资源引用，只存索引不存数据，避免上下文膨胀。"""
    type: str              # "image" | "table"
    id: str                # "img_3", "table_2"
    path: str              # 文件路径，describe_image 时才加载
    caption: str           # 图注 / 周边文本

    def load_data(self) -> bytes:
        p = Path(self.path)
        if p.exists():
            return p.read_bytes()
        return b""


@dataclass
class ToolResult:
    text: str
    resources: list[Resource] = field(default_factory=list)


@dataclass
class LLMToolResponse:
    text: str | None = None
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict       # JSON Schema
    callable: Callable[..., ToolResult]
