"""Tests for the math coverage / OCR / pollution quality layer."""

from paper_reader.math_quality import (
    count_math_candidates,
    detect_encoding_errors,
    detect_ocr_diacritics,
    detect_pollution,
    detect_unicode_math,
    fix_paper_markdown,
    normalize_ocr_prose,
)


# ── Section 3: coverage counting ────────────────────────────────────────

def test_count_math_candidates():
    md = "prose $a$ and $$x^2$$ and $b + c$\n\n$$y$$"
    cov = count_math_candidates(md)
    assert cov.display == 2
    assert cov.inline == 2
    assert cov.total == 4


# ── Section 4: OCR / encoding normalization ─────────────────────────────

def test_normalize_ocr_prose_strips_dots_and_replacement():
    md = "The ḊCGḌ algorithm found \ufffd issues."
    out = normalize_ocr_prose(md)
    assert "DCGD" in out
    assert "\ufffd" not in out


def test_normalize_ocr_prose_leaves_math_untouched():
    md = r"text $P_{\mathrm{ḊCGḌ}}$ end"
    out = normalize_ocr_prose(md)
    # The math block keeps its diacritic (spec: never modify math blocks).
    assert r"$P_{\mathrm{ḊCGḌ}}$" in out


def test_normalize_ocr_preserves_legitimate_accents():
    out = normalize_ocr_prose("café naïve résumé")
    assert "café" in out
    assert "naïve" in out


def test_detect_encoding_errors():
    md = "line one\nbad \ufffd here\nline three"
    errs = detect_encoding_errors(md)
    assert len(errs) == 1
    assert errs[0].line == 2
    assert errs[0].kind == "replacement_char"


def test_detect_ocr_diacritics():
    md = "The ḊCGḌ algorithm"
    anomalies = detect_ocr_diacritics(md)
    assert len(anomalies) >= 2  # Ḋ and Ḍ
    assert all(a.kind == "ocr_diacritic" for a in anomalies)


# ── Section 5: Unicode math in prose ────────────────────────────────────

def test_detect_unicode_math_in_prose_only():
    md = "the value σ is used, and $x \\in S$"
    hits = detect_unicode_math(md)
    # Only the prose σ is flagged; \in inside math is not a Unicode char.
    assert any(h.char == "σ" for h in hits)
    assert not any(h.char == "∈" for h in hits)


def test_detect_unicode_math_suggestion():
    md = "σ and ∈ and ≤"
    hits = {h.char: h.suggestion for h in detect_unicode_math(md)}
    assert hits["σ"] == r"\sigma"
    assert hits["∈"] == r"\in"
    assert hits["≤"] == r"\le"


# ── Section 6: pollution detection ──────────────────────────────────────

def test_detect_unclosed_dollar():
    md = "open $a + b without close"
    report = detect_pollution(md)
    assert report.unclosed_dollar is True
    assert report.dollar_count == 1


def test_detect_balanced_dollar():
    report = detect_pollution("$a$ and $b$")
    assert report.unclosed_dollar is False


def test_detect_unbalanced_paren_and_bracket():
    report = detect_pollution(r"\( x + \[ y ")
    assert report.paren_math_unbalanced is True
    assert report.bracket_math_unbalanced is True


def test_detect_markdown_escapes():
    report = detect_pollution(r"PK\_A and foo")
    assert report.markdown_escapes == 1


def test_detect_bad_text_math():
    report = detect_pollution(r"$\text{N=10}$ samples")
    assert "N=10" in report.text_math


# ── end-to-end ──────────────────────────────────────────────────────────

def test_fix_paper_markdown_combines_latex_and_ocr():
    md = "The ḊCGḌ approach uses $\\mathrm { V e r i f y }$."
    out = fix_paper_markdown(md)
    assert "DCGD" in out                       # OCR prose cleanup
    assert "\\operatorname{Verify}" in out      # LaTeX normalization
