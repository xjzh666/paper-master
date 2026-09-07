# paper_reader/observations.py
"""会话级观察与图像描述的磁盘缓存。

- observations：会话级产物，跨提问累积，与 history 同生同灭
- image_descriptions：论文级产物（describe_image 结果），独立于会话

沿用 memory.py 的 sha256 keying 模式。为免循环 import（agent.py 需要
save_image_descriptions），本模块只处理 dict，Observation 序列化在 agent.py。
"""
import hashlib
import json
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "paper-master"


def _paper_key(filepath: str) -> str | None:
    if not filepath or not Path(filepath).exists():
        return None
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def observations_path(key: str) -> Path:
    return CACHE_DIR / f"{key}-observations.json"


def load_observations(filepath: str) -> list[dict]:
    key = _paper_key(filepath)
    if key is None:
        return []
    path = observations_path(key)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [o for o in data.get("observations", []) if isinstance(o, dict)]
    except (json.JSONDecodeError, IOError, AttributeError):
        return []


def save_observations(filepath: str, observations: list[dict]) -> None:
    key = _paper_key(filepath)
    if key is None:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(observations_path(key), "w", encoding="utf-8") as f:
            json.dump({"paper_id": key, "observations": observations},
                      f, ensure_ascii=False, indent=2)
    except (IOError, OSError, TypeError):
        pass


def clear_observations(key: str) -> None:
    try:
        observations_path(key).unlink(missing_ok=True)
    except OSError:
        pass


def _images_path(key: str) -> Path:
    return CACHE_DIR / f"{key}-images.json"


def load_image_descriptions(filepath: str) -> dict[str, str]:
    key = _paper_key(filepath)
    if key is None:
        return {}
    path = _images_path(key)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        images = data.get("images", {})
        return {k: v for k, v in images.items()
                if isinstance(k, str) and isinstance(v, str)}
    except (json.JSONDecodeError, IOError, AttributeError):
        return {}


def save_image_descriptions(filepath: str, images: dict[str, str]) -> None:
    key = _paper_key(filepath)
    if key is None:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(_images_path(key), "w", encoding="utf-8") as f:
            json.dump({"paper_id": key, "images": images},
                      f, ensure_ascii=False, indent=2)
    except (IOError, OSError, TypeError):
        pass
