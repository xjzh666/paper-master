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
