import numpy as np
import pytest
import fitz
import tempfile
from pathlib import Path


class _FakeModel:
    """Fake embedding model: simple word-overlap vector, fast and semantic-ish.

    Each dimension corresponds to a character bigram, so texts sharing words
    get similar embeddings — just enough for tests to exercise the retrieval path.
    """

    _dim = 64

    def encode(self, texts, batch_size=12, max_length=512,
               return_dense=True, return_sparse=False, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        n = len(texts)
        dim = self._dim
        vecs = np.zeros((n, dim), dtype=np.float32)
        sparse_weights: list[dict] = []
        for i, t in enumerate(texts):
            lower = t.lower()
            token_weights: dict[int, float] = {}
            for j in range(len(lower) - 1):
                idx = (ord(lower[j]) + ord(lower[j + 1])) % dim
                vecs[i, idx] += 1.0
                token_weights[idx] = token_weights.get(idx, 0.0) + 0.1
            norm = np.linalg.norm(vecs[i])
            if norm > 0:
                vecs[i] /= norm
            else:
                vecs[i, 0] = 1.0
            sparse_weights.append(token_weights)
        result = {}
        if return_dense:
            result["dense_vecs"] = vecs
        if return_sparse:
            result["lexical_weights"] = sparse_weights
        return result

    def compute_lexical_matching_score(self, q_weights: dict, d_weights: dict) -> float:
        score = 0.0
        for tid, w in q_weights.items():
            score += w * d_weights.get(tid, 0.0)
        return score


@pytest.fixture(autouse=True)
def mock_embedding_model(monkeypatch):
    """Replace BGE-M3 with a fast fake model for all tests."""
    fake = _FakeModel()

    def fake_get_model():
        return fake

    monkeypatch.setattr(
        "paper_reader.context._get_embedding_model", fake_get_model
    )
    monkeypatch.setattr("paper_reader.context._embedding_model", None)


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
