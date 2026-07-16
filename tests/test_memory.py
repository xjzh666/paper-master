# tests/test_memory.py
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from paper_reader.blocks import PaperDocument, PaperMemory, ContentBlock
from paper_reader.memory import (
    extract_memory,
    load_memory_cache,
    save_memory_cache,
    _parse_json_response,
    _load_markdown,
    _compute_sha256,
    _memory_cache_path,
    CACHE_DIR,
)


class TestPaperMemory:
    def test_default_values(self):
        m = PaperMemory()
        assert m.research_problem == ""
        assert m.keywords == []

    def test_to_dict_and_from_dict_roundtrip(self):
        m = PaperMemory(
            research_problem="测试问题",
            method="测试方法",
            keywords=["kw1", "kw2"],
        )
        d = m.to_dict()
        m2 = PaperMemory.from_dict(d)
        assert m2.research_problem == "测试问题"
        assert m2.method == "测试方法"
        assert m2.keywords == ["kw1", "kw2"]

    def test_from_dict_missing_fields_defaults_to_empty(self):
        m = PaperMemory.from_dict({})
        assert m.research_problem == ""
        assert m.keywords == []

    def test_from_dict_partial_fields(self):
        m = PaperMemory.from_dict({"method": "only method", "takeaways": "good"})
        assert m.method == "only method"
        assert m.takeaways == "good"
        assert m.research_problem == ""


class TestParseJsonResponse:
    def test_parses_plain_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parses_json_with_markdown_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_parses_json_without_lang_specifier(self):
        raw = '```\n{"key": "value"}\n```'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_parses_json_with_surrounding_text(self):
        raw = '一些前置文字 {"key": "value"} 一些后置文字'
        result = _parse_json_response(raw)
        assert result == {"key": "value"}

    def test_raises_on_invalid_input(self):
        with pytest.raises(ValueError):
            _parse_json_response("not json at all")


class TestCacheIO:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """Save a memory, then load it back."""
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )

        # Create a real PDF file so _compute_sha256 works
        pdf = tmp_path / "test.pdf"
        pdf.write_text("fake pdf content for hashing")

        paper = PaperDocument(
            filepath=str(pdf),
            title="Test Paper",
            result_dir="/nonexistent",
        )
        memory = PaperMemory(
            research_problem="如何测试缓存？",
            method="写个测试",
            keywords=["testing", "cache"],
        )

        save_memory_cache(paper, memory)
        loaded = load_memory_cache(paper)

        assert loaded is not None
        assert loaded.research_problem == "如何测试缓存？"
        assert loaded.keywords == ["testing", "cache"]

    def test_load_returns_none_when_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "no-cache.pdf"
        pdf.write_text("some content")

        paper = PaperDocument(filepath=str(pdf))
        result = load_memory_cache(paper)
        assert result is None

    def test_load_returns_none_for_invalid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "bad.pdf"
        pdf.write_text("bad pdf content")
        key = _compute_sha256(str(pdf))
        cache_file = tmp_path / f"{key}-memory.json"
        cache_file.write_text("not valid json")

        paper = PaperDocument(filepath=str(pdf))
        result = load_memory_cache(paper)
        assert result is None

    def test_memory_cache_path_returns_none_for_missing_file(self):
        paper = PaperDocument(filepath="/nonexistent/path.pdf")
        assert _memory_cache_path(paper) is None


class TestLoadMarkdown:
    def test_loads_md_file_when_present(self, tmp_path):
        result_dir = tmp_path / "result"
        result_dir.mkdir()
        md_file = result_dir / "paper.md"
        md_file.write_text("# Title\n\nContent here.")

        paper = PaperDocument(
            filepath=str(tmp_path / "paper.pdf"),
            result_dir=str(result_dir),
        )
        text = _load_markdown(paper)
        assert "Title" in text
        assert "Content here." in text

    def test_falls_back_to_blocks_when_no_md(self, tmp_path):
        result_dir = tmp_path / "empty_result"
        result_dir.mkdir()

        blocks = [
            ContentBlock(type="text", text="段落一"),
            ContentBlock(type="text", text="段落二"),
        ]
        paper = PaperDocument(
            filepath=str(tmp_path / "paper.pdf"),
            result_dir=str(result_dir),
            blocks=blocks,
        )
        text = _load_markdown(paper)
        assert "段落一" in text
        assert "段落二" in text

    def test_loads_first_md_when_multiple_present(self, tmp_path):
        result_dir = tmp_path / "multi_md"
        result_dir.mkdir()
        (result_dir / "a.md").write_text("first file")
        (result_dir / "b.md").write_text("second file")

        paper = PaperDocument(
            filepath=str(tmp_path / "paper.pdf"),
            result_dir=str(result_dir),
        )
        text = _load_markdown(paper)
        assert text == "first file"


class TestExtractMemory:
    def test_extract_memory_with_markdown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "paper.pdf"
        pdf.write_text("pdf content for hashing")

        result_dir = tmp_path / "result"
        result_dir.mkdir()
        (result_dir / "paper.md").write_text("# Test Paper\n\nSome content.")

        paper = PaperDocument(
            filepath=str(pdf),
            result_dir=str(result_dir),
        )

        fake_client = MagicMock()
        fake_client.chat.return_value = json.dumps({
            "research_problem": "测试问题",
            "motivation": "测试动机",
            "method": "测试方法",
            "method_why": "测试原理",
            "experiments": "测试实验",
            "key_results": "测试结果",
            "contributions": "测试贡献",
            "limitations": "测试局限",
            "takeaways": "测试总结",
            "keywords": ["test", "memory"],
        })

        memory = extract_memory(paper, fake_client)
        assert memory.research_problem == "测试问题"
        assert memory.keywords == ["test", "memory"]
        fake_client.chat.assert_called_once()

        # Verify cache was saved
        loaded = load_memory_cache(paper)
        assert loaded is not None
        assert loaded.research_problem == "测试问题"

    def test_extract_memory_handles_empty_paper(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "empty.pdf"
        pdf.write_text("empty content")

        paper = PaperDocument(filepath=str(pdf), result_dir="")

        fake_client = MagicMock()
        memory = extract_memory(paper, fake_client)
        assert memory.research_problem == ""
        fake_client.chat.assert_not_called()

    def test_extract_memory_handles_markdown_fence_response(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "paper_reader.memory.CACHE_DIR", tmp_path
        )
        pdf = tmp_path / "fence.pdf"
        pdf.write_text("fence content")

        result_dir = tmp_path / "result"
        result_dir.mkdir()
        (result_dir / "out.md").write_text("# Fence Paper")

        paper = PaperDocument(
            filepath=str(pdf),
            result_dir=str(result_dir),
        )

        fake_client = MagicMock()
        fake_client.chat.return_value = '```json\n{"research_problem": "fenced", "keywords": ["x"]}\n```'

        memory = extract_memory(paper, fake_client)
        assert memory.research_problem == "fenced"


class TestPaperDocumentWithMemory:
    def test_to_dict_includes_memory_when_present(self):
        paper = PaperDocument(
            filepath="test.pdf",
            memory=PaperMemory(research_problem="RP", keywords=["k"]),
        )
        d = paper.to_dict()
        assert "memory" in d
        assert d["memory"]["research_problem"] == "RP"

    def test_to_dict_excludes_memory_when_none(self):
        paper = PaperDocument(filepath="test.pdf")
        d = paper.to_dict()
        assert "memory" not in d

    def test_from_dict_loads_memory(self):
        d = {
            "filepath": "test.pdf",
            "blocks": [],
            "memory": {"research_problem": "from dict", "keywords": ["a"]},
        }
        paper = PaperDocument.from_dict(d)
        assert paper.memory is not None
        assert paper.memory.research_problem == "from dict"

    def test_from_dict_handles_missing_memory(self):
        d = {"filepath": "test.pdf", "blocks": []}
        paper = PaperDocument.from_dict(d)
        assert paper.memory is None
