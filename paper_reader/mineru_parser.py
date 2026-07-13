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
    def parse(self, pdf_path: str, output_dir: str = "/tmp/mineru-output") -> PaperDocument:
        pdf_path = str(Path(pdf_path).resolve())
        cache_key = self._cache_key(pdf_path)
        cached = self._load_cache(cache_key)
        if cached is not None:
            return cached

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
        # Try to find any hybrid_auto under the output
        for d in Path(output_dir).rglob("hybrid_auto"):
            return d
        raise FileNotFoundError(
            f"MinerU result directory not found under {output_dir}/{stem}"
        )

    def _build_paper(self, pdf_path: str, result_dir: Path) -> PaperDocument:
        content_list = self._load_json(result_dir)
        if not content_list:
            raise ValueError(f"No content in {result_dir}")

        blocks: list[ContentBlock] = []
        for item in content_list:
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
        )

    def _load_json(self, result_dir: Path) -> list[dict]:
        for name in ["content_list_v2.json", "content_list.json"]:
            path = result_dir / name
            if path.exists():
                with open(path) as f:
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
        in_abstract = False
        parts: list[str] = []
        for b in blocks:
            if b.type != "text":
                continue
            text = b.text.strip().lower()
            if text == "abstract":
                in_abstract = True
                continue
            if in_abstract:
                if b.level > 0:
                    break
                parts.append(b.text.strip())
        return " ".join(parts)
