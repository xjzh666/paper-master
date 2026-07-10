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
