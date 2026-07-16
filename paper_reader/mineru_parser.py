# paper_reader/mineru_parser.py
import hashlib
import json
import subprocess
from pathlib import Path

from paper_reader.blocks import (
    ContentBlock,
    SemanticChunk,
    PaperDocument,
    merge_blocks,
)

CACHE_DIR = Path.home() / ".cache" / "paper-master"


class MinerUParser:
    def parse(self, pdf_path: str, output_dir: str | None = None) -> PaperDocument:
        if output_dir is None:
            output_dir = str(Path.home() / ".cache" / "paper-master" / "mineru-output")
        pdf_path = str(Path(pdf_path).resolve())
        cache_key = self._cache_key(pdf_path)
        cached = self._load_cache(cache_key)
        if cached is not None:
            return cached

        # Skip MinerU if output already exists (e.g. from manual run)
        try:
            result_dir = self._find_result_dir(output_dir, pdf_path)
            paper = self._build_paper(pdf_path, result_dir)
        except (FileNotFoundError, ValueError):
            self._run_mineru(pdf_path, output_dir)
            result_dir = self._find_result_dir(output_dir, pdf_path)
            paper = self._build_paper(pdf_path, result_dir)

        self._save_cache(cache_key, paper)
        return paper

    def _cache_key(self, pdf_path: str) -> str:
        with open(pdf_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _load_cache(self, key: str) -> PaperDocument | None:
        cache_file = CACHE_DIR / f"{key}.json"
        if cache_file.exists():
            with open(cache_file) as f:
                return PaperDocument.from_dict(json.load(f))
        return None

    def _save_cache(self, key: str, paper: PaperDocument) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{key}.json"
        with open(cache_file, "w") as f:
            json.dump(paper.to_dict(), f, ensure_ascii=False, indent=2)

    def _run_mineru(self, pdf_path: str, output_dir: str) -> None:
        cmd = [
            "mineru", "-p", pdf_path, "-o", output_dir, "-m", "auto",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"mineru failed (exit {result.returncode}):\n"
                f"stderr: {result.stderr[-1000:]}"
            )

    def _find_result_dir(self, output_dir: str, pdf_path: str) -> Path:
        stem = Path(pdf_path).stem
        base = Path(output_dir) / stem / "hybrid_auto"
        if base.exists():
            return base
        raise FileNotFoundError(
            f"MinerU result directory not found under {output_dir}/{stem}"
        )

    def _build_paper(self, pdf_path: str, result_dir: Path) -> PaperDocument:
        raw_data = self._load_json(result_dir)
        if not raw_data:
            raise ValueError(f"No content in {result_dir}")

        items = self._normalize_items(raw_data)

        blocks: list[ContentBlock] = []
        for item in items:
            block = ContentBlock(
                type=item.get("type", "text"),
                text=item.get("text", ""),
                level=item.get("text_level", 0),
                page_idx=item.get("page_idx", 0),
                bbox=tuple(item.get("bbox", (0, 0, 0, 0))),
                image_path=item.get("img_path"),
            )
            blocks.append(block)

        title = self._extract_title(blocks)
        abstract = self._extract_abstract(blocks)
        chunks = merge_blocks(blocks)

        return PaperDocument(
            filepath=pdf_path,
            title=title,
            abstract=abstract,
            blocks=blocks,
            chunks=chunks,
            metadata={},
            result_dir=str(result_dir),
        )

    def _normalize_items(self, raw_data: list) -> list[dict]:
        """Normalize v1 (flat) and v2 (paginated) formats to a flat item list."""
        if not raw_data:
            return []

        # v2 format: list of pages, each page is a list of items
        if isinstance(raw_data[0], list):
            return self._flatten_v2(raw_data)

        # v1 format: flat list of dicts
        return raw_data

    def _flatten_v2(self, pages: list) -> list[dict]:
        items: list[dict] = []
        for page_idx, page in enumerate(pages):
            for item in page:
                flat = self._convert_v2_item(item, page_idx)
                if flat:
                    items.append(flat)
        return items

    # v2 noise types to skip
    _NOISE_TYPES = {"page_number", "page_footnote", "page_aside_text"}

    # v2 types that produce text blocks
    _TEXT_TYPES = {"paragraph", "title", "code", "algorithm", "list",
                   "chart", "equation_interline"}

    def _convert_v2_item(self, item: dict, page_idx: int) -> dict | None:
        item_type = item.get("type", "text")
        if item_type in self._NOISE_TYPES:
            return None

        content = item.get("content", {})
        bbox = item.get("bbox", (0, 0, 0, 0))

        text = ""
        level = 0
        img_path = None

        if item_type == "title":
            parts = content.get("title_content", [])
            text = " ".join(p.get("content", "") for p in parts)
            level = content.get("level", 1)
        elif item_type in ("paragraph", "code", "algorithm", "list",
                           "chart", "equation_interline"):
            key = f"{item_type}_content"
            parts = content.get(key, [])
            text = " ".join(p.get("content", "") for p in parts)
        elif item_type == "image":
            img_source = content.get("image_source", {})
            img_path = img_source.get("path")
            caption_parts = content.get("image_caption", [])
            text = " ".join(p.get("content", "") for p in caption_parts)
        elif item_type == "table":
            table_caption = content.get("table_caption", [])
            text = " ".join(p.get("content", "") for p in table_caption)
        elif item_type == "formula":
            formula_content = content.get("formula_content", [])
            text = " ".join(p.get("content", "") for p in formula_content)
        else:
            text = content.get("content", "") if isinstance(content, dict) else str(content)

        if not text and not img_path:
            return None

        return {
            "type": item_type if item_type in ("image", "table", "formula") else "text",
            "text": text,
            "text_level": level,
            "page_idx": page_idx,
            "bbox": tuple(bbox),
            "img_path": img_path,
        }

        title = self._extract_title(blocks)
        abstract = self._extract_abstract(blocks)
        chunks = merge_blocks(blocks)

        return PaperDocument(
            filepath=pdf_path,
            title=title,
            abstract=abstract,
            blocks=blocks,
            chunks=chunks,
            metadata={},
            result_dir=str(result_dir),
        )

    def _load_json(self, result_dir: Path) -> list[dict]:
        for suffix in ["content_list_v2.json", "content_list.json"]:
            for name in [suffix, f"*_{suffix}"]:
                matches = list(result_dir.glob(name))
                if matches:
                    with open(matches[0]) as f:
                        return json.load(f)
        raise FileNotFoundError(f"No content_list JSON in {result_dir}")

    def _extract_title(self, blocks: list[ContentBlock]) -> str:
        for b in blocks:
            if b.level == 1 and len(b.text.strip()) > 10:
                return b.text.strip()
        # Fallback: first long text block
        for b in blocks:
            if b.type == "text" and len(b.text.strip()) > 20:
                return b.text.strip()[:200]
        return ""

    def _extract_abstract(self, blocks: list[ContentBlock]) -> str:
        # v2 format: paragraph starting with "Abstract—" or "Abstract:"
        for b in blocks:
            if b.type != "text":
                continue
            text = b.text.strip()
            text_lower = text.lower()
            if text_lower.startswith("abstract") and len(text) > 20:
                return text

        # v1 format: standalone "Abstract" heading then next block
        for i, b in enumerate(blocks):
            if b.type == "text" and b.text.strip().lower() == "abstract":
                if i + 1 < len(blocks) and blocks[i + 1].type == "text":
                    return blocks[i + 1].text.strip()
        return ""
