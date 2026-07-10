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
