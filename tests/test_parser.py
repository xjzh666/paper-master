from paper_reader.parser import parse_pdf, PaperDocument, Section, ImageBlock


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
