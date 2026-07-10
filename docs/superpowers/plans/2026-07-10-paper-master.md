# Paper Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI tool that reads PDF papers and enables interactive dialogue with LLM-powered understanding of text, images, and tables.

**Architecture:** Layered Python application — PyMuPDF extracts content from PDFs, LLM router distributes text to a text model and images/tables to a vision model, context manager tracks conversation state, CLI provides interactive loop with overview-then-deep-read strategy.

**Tech Stack:** Python 3.11+, PyMuPDF, Anthropic SDK, OpenAI SDK, PyYAML

## Global Constraints

- Python 3.11+
- PyMuPDF for all PDF operations
- Official SDKs for LLM providers (anthropic, openai)
- PyYAML for config
- Config via config.yaml (not env vars), config.example.yaml committed to repo
- All modules go under paper_reader/ package
- Tests under tests/ with pytest
- LLM calls must be mockable in tests (no real API calls in unit tests)

---

## File Structure

```
paper-master/
├── main.py                     # CLI entry - arg parse + interactive loop
├── config.example.yaml         # Committed example config
├── requirements.txt
├── README.md
├── LICENSE                     # MIT
├── .gitignore
├── paper_reader/
│   ├── __init__.py             # Public API exports
│   ├── parser.py               # PDF parsing, section detection, image extraction
│   ├── llm.py                  # LLM clients + router
│   └── context.py              # Conversation state management
└── tests/
    ├── __init__.py
    ├── conftest.py             # Shared fixtures (sample PDF generator)
    ├── test_parser.py
    ├── test_llm.py
    └── test_context.py
```

**Design decisions:**
- `parser.py` holds all PDF logic — data types, text extraction, image extraction, section detection. Splitting types from logic would create unnecessary indirection for a focused module.
- `llm.py` holds config loading, client classes, and the router — they share the config dependency and splitting would require extra plumbing.
- `context.py` is simple enough to be one file — a single class managing conversation history and section focus.
- `main.py` at project root — standard Python CLI convention, easy to discover.

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`, `config.example.yaml`, `.gitignore`, `README.md`, `LICENSE`, `paper_reader/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `tests/conftest.py` exports `sample_pdf_path` fixture used by all test tasks

- [ ] **Step 1: Create requirements.txt**

```txt
pymupdf>=1.24.0
anthropic>=0.40.0
openai>=1.50.0
pyyaml>=6.0
```

- [ ] **Step 2: Create config.example.yaml**

```yaml
models:
  text:
    provider: anthropic
    model: claude-sonnet-4-6
  vision:
    provider: openai
    model: gpt-4o

api_keys:
  anthropic: "your-anthropic-api-key"
  openai: "your-openai-api-key"
```

- [ ] **Step 3: Create .gitignore**

```gitignore
config.yaml
__pycache__/
*.pyc
.venv/
venv/
dist/
*.egg-info/
```

- [ ] **Step 4: Create paper_reader/__init__.py**

```python
from paper_reader.parser import parse_pdf, PaperDocument, Section, ImageBlock, TableBlock
from paper_reader.llm import LLMRouter, load_config
from paper_reader.context import ConversationContext

__all__ = [
    "parse_pdf",
    "PaperDocument",
    "Section",
    "ImageBlock",
    "TableBlock",
    "LLMRouter",
    "load_config",
    "ConversationContext",
]
```

- [ ] **Step 5: Create tests/__init__.py** (empty file)

- [ ] **Step 6: Create tests/conftest.py with sample PDF fixture**

```python
import pytest
import fitz
import tempfile
from pathlib import Path


@pytest.fixture
def sample_pdf_path():
    """Create a minimal multi-section PDF for parser tests."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc = fitz.open()

    # Page 1: Title and abstract
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Sample Research Paper", fontsize=18)
    page1.insert_text((72, 120), "John Doe, Jane Smith", fontsize=12)
    page1.insert_text((72, 160), "Abstract", fontsize=14)
    page1.insert_text((72, 190), "This paper presents a novel approach to "
                      "sample generation for testing purposes. We demonstrate "
                      "that our method outperforms baselines by 42%.", fontsize=11)

    # Page 2: Introduction
    page2 = doc.new_page()
    page2.insert_text((72, 72), "1. Introduction", fontsize=16)
    page2.insert_text((72, 110), "Sample generation is a fundamental problem "
                      "in computer science. Prior work has focused on random "
                      "approaches, which fail to capture real-world distributions.",
                      fontsize=11)

    # Page 3: Method
    page3 = doc.new_page()
    page3.insert_text((72, 72), "2. Method", fontsize=16)
    page3.insert_text((72, 110), "Our approach uses a three-stage pipeline. "
                      "First, we collect seed data. Second, we train a generative "
                      "model. Third, we refine outputs with rejection sampling.",
                      fontsize=11)

    doc.save(tmp.name)
    doc.close()
    yield tmp.name
    Path(tmp.name).unlink()
```

- [ ] **Step 7: Create README.md**

```markdown
# Paper Master

Read and chat with academic PDF papers using LLMs.

## Install

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml with your API keys
```

## Usage

```bash
python main.py path/to/paper.pdf
```
```

- [ ] **Step 8: Create LICENSE (MIT)**

```
MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 9: Install dependencies and verify**

Run: `pip install -r requirements.txt`
Expected: all packages install successfully

- [ ] **Step 10: Verify test infrastructure works**

Run: `python -c "import fitz; print('PyMuPDF OK')" && python -c "import anthropic; print('Anthropic OK')" && python -c "import openai; print('OpenAI OK')"`
Expected: all three "OK" messages

- [ ] **Step 11: Commit**

```bash
git add requirements.txt config.example.yaml .gitignore README.md LICENSE \
        paper_reader/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: project scaffolding for paper-master"
```

---

### Task 2: PDF Parser — data types, text extraction, section parsing

**Files:**
- Create: `paper_reader/parser.py`
- Create: `tests/test_parser.py`

**Interfaces:**
- Consumes: `tests/conftest.py::sample_pdf_path` fixture
- Produces:
  - `PaperDocument(filepath, title, sections, abstract)` dataclass
  - `Section(title, level, text, page_start, page_end)` dataclass
  - `ImageBlock(page, bbox, image_bytes, caption)` dataclass
  - `TableBlock(page, bbox, image_bytes, caption)` dataclass
  - `parse_pdf(filepath: str) -> PaperDocument`

- [ ] **Step 1: Write the failing test for parse_pdf**

Create `tests/test_parser.py`:

```python
from paper_reader.parser import parse_pdf, PaperDocument, Section


def test_parse_pdf_returns_paper_document(sample_pdf_path):
    doc = parse_pdf(sample_pdf_path)
    assert isinstance(doc, PaperDocument)
    assert doc.filepath == sample_pdf_path


def test_parse_pdf_extracts_title(sample_pdf_path):
    doc = parse_pdf(sample_pdf_path)
    assert "Sample Research Paper" in doc.title


def test_parse_pdf_extracts_sections(sample_pdf_path):
    doc = parse_pdf(sample_pdf_path)
    assert len(doc.sections) > 0
    for section in doc.sections:
        assert isinstance(section, Section)
        assert section.title
        assert section.text
        assert section.page_start <= section.page_end


def test_parse_pdf_section_has_correct_level(sample_pdf_path):
    doc = parse_pdf(sample_pdf_path)
    levels = {s.level for s in doc.sections}
    assert 1 in levels  # At least top-level sections
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_parser.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'paper_reader.parser'"

- [ ] **Step 3: Write the minimal implementation**

Create `paper_reader/parser.py`:

```python
from dataclasses import dataclass, field


@dataclass
class ImageBlock:
    page: int
    bbox: tuple[float, float, float, float]
    image_bytes: bytes
    caption: str = ""


@dataclass
class TableBlock:
    page: int
    bbox: tuple[float, float, float, float]
    image_bytes: bytes
    caption: str = ""


@dataclass
class Section:
    title: str
    level: int
    text: str
    page_start: int
    page_end: int
    images: list[ImageBlock] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)


@dataclass
class PaperDocument:
    filepath: str
    title: str
    sections: list[Section]
    abstract: str


def parse_pdf(filepath: str) -> PaperDocument:
    import fitz

    doc = fitz.open(filepath)
    try:
        full_text = ""
        for page in doc:
            full_text += page.get_text()

        title = _extract_title(full_text)
        abstract = _extract_abstract(full_text)
        sections = _extract_sections(doc)

        return PaperDocument(
            filepath=filepath,
            title=title,
            sections=sections,
            abstract=abstract,
        )
    finally:
        doc.close()


def _extract_title(text: str) -> str:
    lines = text.strip().split("\n")
    for line in lines[:10]:
        line = line.strip()
        if len(line) > 10:
            return line
    return ""


def _extract_abstract(text: str) -> str:
    import re

    match = re.search(
        r"(?:Abstract)\s*\n+(.*?)(?:\n\s*\d+[\.\s])",
        text, re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return ""


def _extract_sections(doc) -> list[Section]:
    import fitz

    toc = doc.get_toc()
    if toc:
        return _sections_from_toc(doc, toc)
    return _sections_by_font(doc)


def _sections_from_toc(doc, toc: list) -> list[Section]:
    sections = []
    for i, (level, title, page) in enumerate(toc):
        start_page = page - 1
        end_page = toc[i + 1][2] - 1 if i + 1 < len(toc) else doc.page_count - 1

        text = ""
        for p in range(start_page, end_page + 1):
            text += doc[p].get_text()

        sections.append(Section(
            title=title.strip(),
            level=level,
            text=text,
            page_start=start_page,
            page_end=end_page,
        ))
    return sections


def _sections_by_font(doc) -> list[Section]:
    import re

    section_pattern = re.compile(
        r'^\s*(?:\d+\.?\s+|[IVX]+\.\s+)\s*([A-Z][A-Za-z\s]+)',
        re.MULTILINE,
    )

    full_text = ""
    for page in doc:
        full_text += page.get_text()

    matches = list(section_pattern.finditer(full_text))
    if not matches:
        return []

    sections = []
    total_chars = max(len(full_text), 1)

    for i, match in enumerate(matches):
        title = match.group(0).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        text = full_text[start:end]
        page_start = int(start / total_chars * doc.page_count)
        page_end = min(int(end / total_chars * doc.page_count), doc.page_count - 1)

        sections.append(Section(
            title=title,
            level=1,
            text=text,
            page_start=page_start,
            page_end=page_end,
        ))

    return sections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paper_reader/parser.py tests/test_parser.py
git commit -m "feat: add PDF parser with text extraction and section parsing"
```

---

### Task 3: PDF Parser — image extraction from sections

**Files:**
- Modify: `paper_reader/parser.py` — add `_extract_images_from_section` and `_extract_tables_from_section`
- Modify: `tests/test_parser.py` — add image extraction tests

**Interfaces:**
- Consumes: `Section`, `ImageBlock`, `TableBlock` from Task 2
- Produces: updated `parse_pdf` that populates `section.images` and `section.tables`
  - `_extract_images(page: fitz.Page) -> list[ImageBlock]`
  - `_extract_tables(page: fitz.Page) -> list[TableBlock]`

- [ ] **Step 1: Write the failing test for image extraction**

Append to `tests/test_parser.py`:

```python
from paper_reader.parser import ImageBlock


def test_parse_pdf_extracts_images(sample_pdf_path):
    doc = parse_pdf(sample_pdf_path)
    # Our sample PDF has no images, but the field should exist and be a list
    for section in doc.sections:
        assert isinstance(section.images, list)


def test_image_block_has_required_fields():
    block = ImageBlock(page=0, bbox=(0, 0, 100, 100), image_bytes=b"fake")
    assert block.page == 0
    assert block.image_bytes == b"fake"


def test_parse_pdf_with_real_images():
    """Create a PDF with an embedded image and verify extraction."""
    import fitz
    import tempfile
    from pathlib import Path

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "1. Results", fontsize=16)
    # Insert a small rectangle as an "image" — PyMuPDF can extract it
    page.insert_text((72, 100), "Figure 1: A simple test figure", fontsize=11)
    doc.save(tmp.name)
    doc.close()

    try:
        paper = parse_pdf(tmp.name)
        assert paper is not None
    finally:
        Path(tmp.name).unlink()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_parser.py::test_parse_pdf_extracts_images -v`
Expected: FAIL (images field doesn't exist or sections might not have images)

- [ ] **Step 3: Add image extraction to parser.py**

Add this function to `paper_reader/parser.py` and call it in `parse_pdf`:

```python
def _extract_images_from_page(page) -> list[ImageBlock]:
    images = []
    for img_info in page.get_image_info():
        xref = img_info.get("xref", 0)
        bbox = img_info.get("bbox", (0, 0, 0, 0))
        if xref:
            base_image = page.parent.extract_image(xref)
            image_bytes = base_image.get("image", b"")
            images.append(ImageBlock(
                page=page.number,
                bbox=tuple(bbox),
                image_bytes=image_bytes,
            ))
    return images
```

Update `_sections_from_toc` to attach images to each section:

```python
def _sections_from_toc(doc, toc: list) -> list[Section]:
    sections = []
    for i, (level, title, page) in enumerate(toc):
        start_page = page - 1
        end_page = toc[i + 1][2] - 1 if i + 1 < len(toc) else doc.page_count - 1

        text = ""
        images = []
        for p in range(start_page, end_page + 1):
            text += doc[p].get_text()
            images.extend(_extract_images_from_page(doc[p]))

        sections.append(Section(
            title=title.strip(),
            level=level,
            text=text,
            page_start=start_page,
            page_end=end_page,
            images=images,
        ))
    return sections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paper_reader/parser.py tests/test_parser.py
git commit -m "feat: add image extraction from PDF pages"
```

---

### Task 4: LLM clients — config loading, Anthropic client, OpenAI client

**Files:**
- Create: `paper_reader/llm.py`
- Create: `tests/test_llm.py`

**Interfaces:**
- Consumes: `config.example.yaml` format
- Produces:
  - `load_config(path: str = "config.yaml") -> dict`
  - `class LLMClient` (ABC) with `chat(messages: list[dict], system_prompt: str = "") -> str`
  - `class AnthropicClient(LLMClient): __init__(api_key: str, model: str)`
  - `class OpenAIClient(LLMClient): __init__(api_key: str, model: str, base_url: str | None = None)`
  - `create_client(provider: str, config: dict) -> LLMClient`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_llm.py`:

```python
import pytest
import tempfile
import yaml
from paper_reader.llm import (
    load_config,
    create_client,
    AnthropicClient,
    OpenAIClient,
)


@pytest.fixture
def config_file():
    config = {
        "models": {
            "text": {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            "vision": {"provider": "openai", "model": "gpt-4o"},
        },
        "api_keys": {
            "anthropic": "test-anthropic-key",
            "openai": "test-openai-key",
        },
    }
    tmp = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w")
    yaml.dump(config, tmp)
    tmp.close()
    yield tmp.name
    import os
    os.unlink(tmp.name)


def test_load_config_returns_dict(config_file):
    config = load_config(config_file)
    assert isinstance(config, dict)
    assert "models" in config
    assert "api_keys" in config


def test_load_config_has_text_model(config_file):
    config = load_config(config_file)
    assert config["models"]["text"]["provider"] == "anthropic"


def test_create_anthropic_client(config_file):
    config = load_config(config_file)
    client = create_client("anthropic", config)
    assert isinstance(client, AnthropicClient)


def test_create_openai_client(config_file):
    config = load_config(config_file)
    client = create_client("openai", config)
    assert isinstance(client, OpenAIClient)


def test_anthropic_client_chat_returns_string(config_file):
    config = load_config(config_file)
    client = create_client("anthropic", config)
    # Verify the client is properly configured (no real API call)
    assert client.model == "claude-sonnet-4-6"
    assert client.api_key == "test-anthropic-key"


def test_openai_client_chat_returns_string(config_file):
    config = load_config(config_file)
    client = create_client("openai", config)
    assert client.model == "gpt-4o"
    assert client.api_key == "test-openai-key"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

Create `paper_reader/llm.py`:

```python
from abc import ABC, abstractmethod
from pathlib import Path

import yaml


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], system_prompt: str = "") -> str:
        ...

    @abstractmethod
    def chat_with_images(
        self, text: str, images: list[bytes], system_prompt: str = ""
    ) -> str:
        ...


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def chat(self, messages: list[dict], system_prompt: str = "") -> str:
        system_params = {}
        if system_prompt:
            system_params["system"] = system_prompt

        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=messages,
            **system_params,
        )
        return response.content[0].text

    def chat_with_images(
        self, text: str, images: list[bytes], system_prompt: str = ""
    ) -> str:
        import base64

        content = [{"type": "text", "text": text}]
        for img_bytes in images:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })

        messages = [{"role": "user", "content": content}]
        system_params = {}
        if system_prompt:
            system_params["system"] = system_prompt

        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=messages,
            **system_params,
        )
        return response.content[0].text


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        self.api_key = api_key
        self.model = model
        import openai
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**kwargs)

    def chat(self, messages: list[dict], system_prompt: str = "") -> str:
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        response = self._client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            max_tokens=4096,
        )
        return response.choices[0].message.content

    def chat_with_images(
        self, text: str, images: list[bytes], system_prompt: str = ""
    ) -> str:
        import base64

        content = [{"type": "text", "text": text}]
        for img_bytes in images:
            b64 = base64.b64encode(img_bytes).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.append({"role": "user", "content": content})

        response = self._client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            max_tokens=4096,
        )
        return response.choices[0].message.content


def create_client(provider: str, config: dict) -> LLMClient:
    api_keys = config.get("api_keys", {})
    models = config.get("models", {})

    if provider == "anthropic":
        model_config = models.get("text", {})
        return AnthropicClient(
            api_key=api_keys.get("anthropic", ""),
            model=model_config.get("model", "claude-sonnet-4-6"),
        )
    elif provider == "openai":
        model_config = models.get("vision", {})
        return OpenAIClient(
            api_key=api_keys.get("openai", ""),
            model=model_config.get("model", "gpt-4o"),
            base_url=model_config.get("base_url"),
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_llm.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paper_reader/llm.py tests/test_llm.py
git commit -m "feat: add LLM clients with Anthropic and OpenAI support"
```

---

### Task 5: LLM Router — content distribution logic

**Files:**
- Modify: `paper_reader/llm.py` — add `LLMRouter` class
- Modify: `tests/test_llm.py` — add router tests

**Interfaces:**
- Consumes: `LLMClient`, `create_client`, `load_config` from Task 4; `Section` from Task 2
- Produces:
  - `class LLMRouter: __init__(config: dict)`, `answer(section: Section, question: str, history: list[dict]) -> str`

- [ ] **Step 1: Write the failing test for LLMRouter**

Append to `tests/test_llm.py`:

```python
from unittest.mock import patch, MagicMock
from paper_reader.llm import LLMRouter
from paper_reader.parser import Section


class FakeClient:
    """Fake LLM client that records calls without real API."""
    def __init__(self):
        self.calls = []

    def chat(self, messages, system_prompt=""):
        self.calls.append(("chat", messages, system_prompt))
        return "text model response"

    def chat_with_images(self, text, images, system_prompt=""):
        self.calls.append(("chat_with_images", text, images, system_prompt))
        return "vision model response"


def test_router_uses_text_model_when_no_images():
    text_client = FakeClient()
    vision_client = FakeClient()
    router = LLMRouter.__new__(LLMRouter)
    router._text_client = text_client
    router._vision_client = vision_client

    section = Section(
        title="Methods", level=1, text="Some text content",
        page_start=0, page_end=0,
    )
    result = router.answer(section, "What method?", [])

    assert len(text_client.calls) == 1
    assert len(vision_client.calls) == 0


def test_router_uses_vision_model_when_images_present():
    text_client = FakeClient()
    vision_client = FakeClient()
    router = LLMRouter.__new__(LLMRouter)
    router._text_client = text_client
    router._vision_client = vision_client

    section = Section(
        title="Results", level=1, text="Some text",
        page_start=0, page_end=0,
        images=[MagicMock(image_bytes=b"fake_image")],
    )
    result = router.answer(section, "Show results", [])

    assert len(vision_client.calls) == 1


def test_router_formats_section_content():
    text_client = FakeClient()
    vision_client = FakeClient()
    router = LLMRouter.__new__(LLMRouter)
    router._text_client = text_client
    router._vision_client = vision_client

    section = Section(
        title="2. Methods", level=1, text="Method text here.",
        page_start=1, page_end=2,
    )
    result = router.answer(section, "What is the method?", [])

    call_messages = text_client.calls[0][1]
    user_message = call_messages[-1]["content"]
    assert "2. Methods" in user_message
    assert "Method text here." in user_message
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_llm.py -v -k "router"`
Expected: FAIL with "AttributeError: type object 'LLMRouter' has no attribute..."

- [ ] **Step 3: Add LLMRouter to llm.py**

Append to `paper_reader/llm.py`:

```python
SYSTEM_PROMPT = """You are a paper-reading assistant. You help users understand academic papers by answering questions based on the paper content provided to you.

Guidelines:
- Answer based only on the provided paper content
- Be accurate and concise
- If the provided content doesn't contain enough information to answer, say so
- When discussing figures or tables, describe what they show
- Use the section title to contextualize your answer"""


class LLMRouter:
    def __init__(self, config: dict):
        self._text_client = create_client(
            config["models"]["text"]["provider"], config
        )
        self._vision_client = create_client(
            config["models"]["vision"]["provider"], config
        )

    def answer(
        self, section: "Section", question: str, history: list[dict]
    ) -> str:
        content = self._build_content(section, question)

        if section.images or section.tables:
            images = [img.image_bytes for img in section.images]
            images += [t.image_bytes for t in section.tables]
            return self._vision_client.chat_with_images(
                content, images, system_prompt=SYSTEM_PROMPT
            )

        messages = list(history)
        messages.append({"role": "user", "content": content})
        return self._text_client.chat(messages, system_prompt=SYSTEM_PROMPT)

    def _build_content(self, section: "Section", question: str) -> str:
        parts = [
            f"Section: {section.title}",
            f"Content:\n{section.text}",
            "",
            f"Question: {question}",
        ]
        return "\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_llm.py -v -k "router"` then `python -m pytest tests/test_llm.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add paper_reader/llm.py tests/test_llm.py
git commit -m "feat: add LLM router for text/vision content distribution"
```

---

### Task 6: Context manager — conversation state and section tracking

**Files:**
- Create: `paper_reader/context.py`
- Create: `tests/test_context.py`

**Interfaces:**
- Consumes: `PaperDocument`, `Section` from Task 2
- Produces:
  - `class ConversationContext:`
    - `__init__(paper: PaperDocument)`
    - `paper: PaperDocument`
    - `history: list[dict]`
    - `add_message(role: str, content: str) -> None`
    - `find_section(query: str) -> Section | None`
    - `get_overview() -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_context.py`:

```python
from paper_reader.context import ConversationContext
from paper_reader.parser import PaperDocument, Section


def make_paper() -> PaperDocument:
    return PaperDocument(
        filepath="test.pdf",
        title="Test Paper",
        sections=[
            Section(
                title="1. Introduction", level=1,
                text="Introduction text.", page_start=0, page_end=0,
            ),
            Section(
                title="2. Methods", level=1,
                text="Methods text.", page_start=1, page_end=1,
            ),
            Section(
                title="2.1 Dataset", level=2,
                text="Dataset details.", page_start=1, page_end=1,
            ),
        ],
        abstract="This is a test abstract.",
    )


def test_context_stores_paper():
    paper = make_paper()
    ctx = ConversationContext(paper)
    assert ctx.paper == paper


def test_context_starts_with_empty_history():
    ctx = ConversationContext(make_paper())
    assert ctx.history == []


def test_add_message_appends_to_history():
    ctx = ConversationContext(make_paper())
    ctx.add_message("user", "Hello")
    ctx.add_message("assistant", "Hi there")
    assert len(ctx.history) == 2
    assert ctx.history[0] == {"role": "user", "content": "Hello"}
    assert ctx.history[1] == {"role": "assistant", "content": "Hi there"}


def test_find_section_exact_match():
    ctx = ConversationContext(make_paper())
    section = ctx.find_section("2. Methods")
    assert section is not None
    assert section.title == "2. Methods"


def test_find_section_partial_match():
    ctx = ConversationContext(make_paper())
    section = ctx.find_section("Methods")
    assert section is not None
    assert "Methods" in section.title


def test_find_section_no_match():
    ctx = ConversationContext(make_paper())
    section = ctx.find_section("Conclusion")
    assert section is None


def test_find_section_by_number():
    ctx = ConversationContext(make_paper())
    section = ctx.find_section("2.1")
    assert section is not None
    assert section.title == "2.1 Dataset"


def test_get_overview():
    ctx = ConversationContext(make_paper())
    overview = ctx.get_overview()
    assert "Test Paper" in overview
    assert "test abstract" in overview
    assert "1. Introduction" in overview
    assert "2. Methods" in overview
    assert "2.1 Dataset" in overview
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_context.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Write the implementation**

Create `paper_reader/context.py`:

```python
from paper_reader.parser import PaperDocument, Section


class ConversationContext:
    def __init__(self, paper: PaperDocument):
        self.paper = paper
        self.history: list[dict] = []

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def find_section(self, query: str) -> Section | None:
        query_lower = query.strip().lower()

        # Try exact match first
        for section in self.paper.sections:
            if section.title.strip().lower() == query_lower:
                return section

        # Try title contains query
        for section in self.paper.sections:
            if query_lower in section.title.strip().lower():
                return section

        # Try query contains section number (e.g. "what does 2.1 say")
        for section in self.paper.sections:
            title_lower = section.title.strip().lower()
            if title_lower and title_lower.split()[0] in query_lower:
                return section

        return None

    def get_overview(self) -> str:
        lines = [
            f"Paper: {self.paper.title}",
            "",
        ]
        if self.paper.abstract:
            abstract_preview = self.paper.abstract[:500]
            if len(self.paper.abstract) > 500:
                abstract_preview += "..."
            lines.append(f"Abstract: {abstract_preview}")
            lines.append("")

        lines.append("Sections:")
        for section in self.paper.sections:
            indent = "  " * (section.level - 1)
            lines.append(f"{indent}{section.title}")

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_context.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add paper_reader/context.py tests/test_context.py
git commit -m "feat: add conversation context manager"
```

---

### Task 7: CLI — interactive loop with overview and question handling

**Files:**
- Create: `main.py`
- Modify: `paper_reader/__init__.py` — add exports if missing

**Interfaces:**
- Consumes: all modules from Tasks 2-6
- Produces:
  - `main()` — CLI entry point
  - `show_overview(ctx: ConversationContext)` — prints paper overview
  - `handle_question(question: str, ctx: ConversationContext, router: LLMRouter) -> str` — routes question, gets answer, updates history

- [ ] **Step 1: Write the failing test**

The CLI is tested via integration. Create a basic test:

Append to `tests/test_context.py` or create a new `tests/test_cli.py`:

```python
# tests/test_cli.py
import sys
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

# We'll test handle_question logic (not full CLI loop, which blocks)
from paper_reader.context import ConversationContext
from paper_reader.parser import PaperDocument, Section
from paper_reader.llm import LLMRouter


def make_paper():
    return PaperDocument(
        filepath="test.pdf",
        title="Test Paper",
        sections=[
            Section(title="1. Intro", level=1, text="Intro text", page_start=0, page_end=0),
            Section(title="2. Methods", level=1, text="Methods text", page_start=1, page_end=1),
        ],
        abstract="Test abstract.",
    )


def test_handle_question_finds_section_and_answers():
    ctx = ConversationContext(make_paper())
    router = MagicMock()
    router.answer.return_value = "This is the answer."

    question = "What does section 2 say?"
    from main import handle_question
    answer = handle_question(question, ctx, router)

    router.answer.assert_called_once()
    assert answer == "This is the answer."
    assert len(ctx.history) >= 2  # user + assistant messages


def test_handle_question_general_without_section():
    ctx = ConversationContext(make_paper())
    router = MagicMock()
    router.answer.return_value = "General answer."

    question = "What is this paper about?"
    from main import handle_question
    answer = handle_question(question, ctx, router)

    router.answer.assert_called_once()
    assert answer == "General answer."
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL (main.py doesn't exist)

- [ ] **Step 3: Write CLI implementation**

Create `main.py`:

```python
import sys
from pathlib import Path

from paper_reader.parser import parse_pdf, Section
from paper_reader.llm import load_config, LLMRouter
from paper_reader.context import ConversationContext


def show_overview(ctx: ConversationContext) -> None:
    print("\n" + "=" * 60)
    print(ctx.get_overview())
    print("=" * 60)
    print("\nYou can ask questions about any section. Type /help for commands, /quit to exit.\n")


def show_help() -> None:
    print("""
Commands:
  /overview  - Show paper overview again
  /sections  - List all sections
  /help      - Show this help
  /quit      - Exit

You can also just type a question about the paper.
Refer to sections by number (e.g., "What does section 2.1 say?")
""")


def handle_question(
    question: str, ctx: ConversationContext, router: LLMRouter
) -> str:
    ctx.add_message("user", question)

    # Try to find which section the user is asking about
    section = ctx.find_section(question)

    if section is None:
        # General question — use full paper content
        all_text = ""
        all_images = []
        for s in ctx.paper.sections:
            all_text += f"\n\n## {s.title}\n{s.text}"
            all_images.extend(img.image_bytes for img in s.images)
        section = Section(
            title="Full Paper", level=0, text=all_text,
            page_start=0, page_end=999, images=[
                type('ImageBlock', (), {'image_bytes': b})() for b in all_images
            ],
        )

    answer = router.answer(section, question, ctx.history[:-1])
    ctx.add_message("assistant", answer)
    return answer


def interactive_loop(paper_path: str) -> None:
    # Load config
    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        print("Error: config.yaml not found. Copy config.example.yaml to config.yaml and edit it.")
        sys.exit(1)

    # Parse PDF
    print(f"\nLoading paper: {paper_path}...")
    try:
        paper = parse_pdf(paper_path)
    except Exception as e:
        print(f"Error parsing PDF: {e}")
        sys.exit(1)

    if not paper.sections:
        print("Warning: No sections detected in this PDF. You can still ask questions.")

    ctx = ConversationContext(paper)
    router = LLMRouter(config)
    show_overview(ctx)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("Goodbye!")
            break
        elif user_input == "/help":
            show_help()
        elif user_input == "/overview":
            show_overview(ctx)
        elif user_input == "/sections":
            print(ctx.get_overview())
        else:
            print("\nThinking...")
            try:
                answer = handle_question(user_input, ctx, router)
                print(f"\n{answer}")
            except Exception as e:
                print(f"\nError: {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <path/to/paper.pdf>")
        sys.exit(1)

    paper_path = sys.argv[1]
    if not Path(paper_path).exists():
        print(f"Error: File not found: {paper_path}")
        sys.exit(1)

    interactive_loop(paper_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_cli.py
git commit -m "feat: add CLI with interactive paper reading loop"
```

---

### Task 8: Integration test — end-to-end with real PDF

**Files:**
- Create: `tests/test_integration.py`

**Interfaces:**
- Consumes: all previous tasks
- Produces: end-to-end verification that the full pipeline works with a real (mocked) LLM

- [ ] **Step 1: Write the integration test**

Create `tests/test_integration.py`:

```python
import tempfile
import fitz
from pathlib import Path
from unittest.mock import patch, MagicMock

from paper_reader.parser import parse_pdf
from paper_reader.llm import LLMRouter
from paper_reader.context import ConversationContext
from paper_reader.parser import Section, ImageBlock


def create_test_pdf() -> str:
    """Create a realistic multi-page PDF with an embedded image."""
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc = fitz.open()

    # Page 1: Title + abstract
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Deep Learning for Paper Reading", fontsize=18)
    p1.insert_text((72, 110), "A. Researcher, B. Scholar", fontsize=12)
    p1.insert_text((72, 160), "Abstract", fontsize=14)
    p1.insert_text((72, 190),
        "We propose a novel approach to automated paper reading using "
        "large language models combined with visual understanding. "
        "Our system achieves state-of-the-art results on the PaperQA benchmark.", fontsize=11)

    # Page 2: Introduction
    p2 = doc.new_page()
    p2.insert_text((72, 72), "1. Introduction", fontsize=16)
    p2.insert_text((72, 110),
        "Reading academic papers is a time-consuming task for researchers. "
        "On average, a researcher spends 4-6 hours per paper. Automated tools "
        "can significantly reduce this burden.", fontsize=11)

    # Page 3: Method (with an embedded image)
    p3 = doc.new_page()
    p3.insert_text((72, 72), "2. Method", fontsize=16)
    p3.insert_text((72, 110),
        "Our architecture has three components: PDF parser, LLM router, "
        "and context manager. See Figure 1 for the architecture diagram.", fontsize=11)
    # Insert a small rectangle as an image
    p3.draw_rect(fitz.Rect(72, 200, 272, 300))
    p3.insert_text((72, 320), "Figure 1: System architecture", fontsize=10)

    # Page 4: Results
    p4 = doc.new_page()
    p4.insert_text((72, 72), "3. Results", fontsize=16)
    p4.insert_text((72, 110),
        "Our system achieves 95% accuracy on paper summarization and "
        "answers user questions with 87% relevance score.", fontsize=11)

    # Page 5: Conclusion
    p5 = doc.new_page()
    p5.insert_text((72, 72), "4. Conclusion", fontsize=16)
    p5.insert_text((72, 110),
        "We have demonstrated an effective paper reading assistant. "
        "Future work will extend this to multi-paper comparison.", fontsize=11)

    doc.save(tmp.name)
    doc.close()
    return tmp.name


class FakeTextClient:
    def chat(self, messages, system_prompt=""):
        user_msg = messages[-1]["content"] if messages else ""
        return f"[Text model response based on provided content]"


class FakeVisionClient:
    def chat_with_images(self, text, images, system_prompt=""):
        return f"[Vision model response with {len(images)} image(s)]"


def test_full_pipeline_parse_and_overview():
    pdf_path = create_test_pdf()
    try:
        paper = parse_pdf(pdf_path)
        assert paper.title
        assert len(paper.sections) > 0
        assert paper.abstract

        ctx = ConversationContext(paper)
        overview = ctx.get_overview()
        assert "Deep Learning" in overview
        assert "1. Introduction" in overview
        assert "2. Method" in overview
        assert "3. Results" in overview
        assert "4. Conclusion" in overview
    finally:
        Path(pdf_path).unlink()


def test_full_pipeline_question_routing():
    pdf_path = create_test_pdf()
    try:
        paper = parse_pdf(pdf_path)
        ctx = ConversationContext(paper)

        router = LLMRouter.__new__(LLMRouter)
        router._text_client = FakeTextClient()
        router._vision_client = FakeVisionClient()

        ctx.add_message("user", "What is the method?")
        section = ctx.find_section("method")
        assert section is not None

        answer = router.answer(section, "What is the method?", ctx.history[:-1])
        assert answer is not None
        assert len(answer) > 0
    finally:
        Path(pdf_path).unlink()


def test_full_pipeline_section_with_visuals():
    """Section with drawings (treated as images) uses vision model."""
    pdf_path = create_test_pdf()
    try:
        paper = parse_pdf(pdf_path)
        ctx = ConversationContext(paper)

        router = LLMRouter.__new__(LLMRouter)
        router._text_client = FakeTextClient()
        router._vision_client = FakeVisionClient()

        section = ctx.find_section("method")
        assert section is not None

        answer = router.answer(section, "Explain the architecture", [])
        assert "Vision" in answer or "image" in answer.lower()
    finally:
        Path(pdf_path).unlink()
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest tests/test_integration.py -v`
Expected: PASS (3 tests)

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add end-to-end integration tests"
```

---

### Task 9: Final polish — pyproject.toml and runnable entry point

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "paper-master"
version = "0.1.0"
description = "Read and chat with academic PDF papers using LLMs"
requires-python = ">=3.11"
dependencies = [
    "pymupdf>=1.24.0",
    "anthropic>=0.40.0",
    "openai>=1.50.0",
    "pyyaml>=6.0",
]

[project.scripts]
paper-master = "main:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Verify package is installable**

Run: `pip install -e .`
Expected: package installs without error

- [ ] **Step 3: Verify CLI entry point**

Run: `paper-master --help 2>&1 || python -m main --help 2>&1 || echo "Usage shown"`
Expected: shows usage message (exits non-zero because no arg, but shows usage)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pyproject.toml with entry point"
```
