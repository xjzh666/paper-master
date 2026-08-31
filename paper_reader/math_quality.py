"""Math coverage validation + OCR/encoding anomaly detection + pollution checks.

This is the "quality" layer of the PDF -> Markdown -> LaTeX -> KaTeX pipeline.
``latex_fix`` normalizes LaTeX *inside* math; this module measures how much
math actually survives to KaTeX and flags OCR / encoding / Unicode / pollution
problems that would degrade rendering or leak into embeddings/RAG.

Sections covered:
- (3) math coverage: raw math candidate counting (the remark-math / KaTeX half
  of the report lives in ``frontend/scripts/math-coverage.mjs``).
- (4) OCR / encoding anomaly detection + prose-only normalization.
- (5) Unicode math character detection in prose.
- (6) Markdown / LaTeX pollution detection (unclosed delimiters, escapes,
  bad math inside ``\\text{}``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from paper_reader.latex_fix import _MATH_SPLIT


# ── Section 4: OCR / encoding anomalies ───────────────────────────────────

# Combining marks that MinerU/OCR commonly fabricates on Latin letters
# (e.g. "DCGUARD" -> "ḊCGḌ"). Only these two are stripped so legitimate
# accents (café, naïve) are preserved.
_OCR_DOT_MARKS = frozenset("\u0307\u0323")  # combining dot above / dot below

# Unicode replacement character: encoding failure, information unrecoverable.
_REPLACEMENT_CHAR = "\ufffd"


def _strip_ocr_marks(text: str) -> str:
    """Remove fabricated dot-above / dot-below diacritics from Latin text."""
    decomposed = unicodedata.normalize("NFKD", text)
    filtered = "".join(c for c in decomposed if c not in _OCR_DOT_MARKS)
    return unicodedata.normalize("NFC", filtered)


def _iter_spans(md: str):
    """Yield ``(is_math, text)`` chunks, mirroring ``fix_markdown_math``."""
    last = 0
    for m in _MATH_SPLIT.finditer(md):
        if m.start() > last:
            yield (False, md[last:m.start()])
        yield (True, m.group(0))
        last = m.end()
    if last < len(md):
        yield (False, md[last:])


def normalize_ocr_prose(md: str) -> str:
    """Clean OCR artifacts in prose only (title/body/caption text).

    Math blocks are left untouched (per spec: never modify math content here).
    Strips fabricated dot diacritics and removes the Unicode replacement
    character so it cannot reach embeddings/RAG.
    """
    out: list[str] = []
    for is_math, text in _iter_spans(md):
        if is_math:
            out.append(text)
        else:
            out.append(_strip_ocr_marks(text).replace(_REPLACEMENT_CHAR, ""))
    return "".join(out)


def fix_paper_markdown(md: str) -> str:
    """Full serve-time clean: LaTeX normalization + prose OCR cleanup."""
    from paper_reader.latex_fix import fix_markdown_math
    return normalize_ocr_prose(fix_markdown_math(md))


@dataclass
class Anomaly:
    kind: str          # "replacement_char" | "ocr_diacritic"
    line: int
    char: str | None = None
    text: str = ""     # surrounding context


def detect_encoding_errors(md: str) -> list[Anomaly]:
    """Report Unicode replacement characters (U+FFFD)."""
    out: list[Anomaly] = []
    for i, line in enumerate(md.splitlines(), 1):
        if _REPLACEMENT_CHAR in line:
            idx = line.index(_REPLACEMENT_CHAR)
            out.append(Anomaly(
                kind="replacement_char", line=i,
                text=line[max(0, idx - 20):idx + 20],
            ))
    return out


def detect_ocr_diacritics(md: str) -> list[Anomaly]:
    """Report fabricated dot diacritics (prose and math, for review)."""
    out: list[Anomaly] = []
    for i, line in enumerate(md.splitlines(), 1):
        # Only flag the precomposed Latin letters that decompose to dot marks.
        for ch in set(line):
            dec = unicodedata.normalize("NFKD", ch)
            if len(dec) > 1 and any(c in _OCR_DOT_MARKS for c in dec):
                idx = line.index(ch)
                out.append(Anomaly(
                    kind="ocr_diacritic", line=i, char=ch,
                    text=line[max(0, idx - 15):idx + 15],
                ))
    return out


# ── Section 5: Unicode math characters in prose ───────────────────────────

# Unicode math symbols that have a canonical LaTeX form. Detected in prose so
# authors can move them into math mode for renderer-consistent output.
_UNICODE_MATH_TO_LATEX = {
    "σ": r"\sigma", "Σ": r"\Sigma", "π": r"\pi", "Π": r"\Pi",
    "θ": r"\theta", "Θ": r"\Theta", "λ": r"\lambda", "Λ": r"\Lambda",
    "μ": r"\mu", "φ": r"\phi", "ψ": r"\psi", "ω": r"\omega", "Ω": r"\Omega",
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\epsilon", "Δ": r"\Delta", "Γ": r"\Gamma",
    "∈": r"\in", "∉": r"\notin", "≤": r"\le", "≥": r"\ge", "≠": r"\ne",
    "→": r"\rightarrow", "←": r"\leftarrow", "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow", "⇐": r"\Leftarrow", "⇔": r"\Leftrightarrow",
    "∑": r"\sum", "∏": r"\prod", "√": r"\sqrt", "∞": r"\infty",
    "∫": r"\int", "×": r"\times", "⋅": r"\cdot", "±": r"\pm", "∓": r"\mp",
    "≈": r"\approx", "∼": r"\sim", "≡": r"\equiv", "≪": r"\ll", "≫": r"\gg",
    "∂": r"\partial", "∇": r"\nabla", "∅": r"\emptyset", "∩": r"\cap",
    "∪": r"\cup", "⊆": r"\subseteq", "⊕": r"\oplus", "⊗": r"\otimes",
    "∧": r"\land", "∨": r"\lor", "¬": r"\neg", "∀": r"\forall", "∃": r"\exists",
    "−": "-", "⟨": r"\langle", "⟩": r"\rangle", "…": r"\dots",
}
_UNICODE_MATH = frozenset(_UNICODE_MATH_TO_LATEX)


@dataclass
class UnicodeMath:
    line: int
    char: str
    suggestion: str
    context: str = ""


def detect_unicode_math(md: str) -> list[UnicodeMath]:
    """Report Unicode math symbols appearing in prose (outside math blocks)."""
    out: list[UnicodeMath] = []
    offset = 0
    for is_math, text in _iter_spans(md):
        if not is_math:
            base_line = md[:offset].count("\n") + 1
            for idx, ch in enumerate(text):
                if ch in _UNICODE_MATH:
                    out.append(UnicodeMath(
                        line=base_line + text[:idx].count("\n"),
                        char=ch,
                        suggestion=_UNICODE_MATH_TO_LATEX[ch],
                        context=text[max(0, idx - 15):idx + 15],
                    ))
        offset += len(text)
    return out


# ── Section 6: Markdown / LaTeX pollution ─────────────────────────────────

@dataclass
class PollutionReport:
    unclosed_dollar: bool = False
    dollar_count: int = 0
    paren_math_unbalanced: bool = False   # \( \) balance
    bracket_math_unbalanced: bool = False  # \[ \] balance
    markdown_escapes: int = 0             # \_ escaped underscores
    text_math: list[str] = field(default_factory=list)  # \text{...} with math

    def to_dict(self) -> dict:
        return {
            "unclosed_dollar": self.unclosed_dollar,
            "dollar_count": self.dollar_count,
            "paren_math_unbalanced": self.paren_math_unbalanced,
            "bracket_math_unbalanced": self.bracket_math_unbalanced,
            "markdown_escapes": self.markdown_escapes,
            "text_math": self.text_math,
        }


def detect_pollution(md: str) -> PollutionReport:
    """Flag unclosed math delimiters, markdown escapes, and bad ``\\text{}``."""
    report = PollutionReport()
    report.dollar_count = md.count("$")
    report.unclosed_dollar = report.dollar_count % 2 == 1

    report.paren_math_unbalanced = md.count(r"\(") != md.count(r"\)")
    report.bracket_math_unbalanced = md.count(r"\[") != md.count(r"\]")
    report.markdown_escapes = len(re.findall(r"\\_", md))

    # \text{...} containing math-only content (digits / =) is a smell.
    for m in re.finditer(r"\\text\s*\{([^{}]*)\}", md):
        body = m.group(1)
        if re.search(r"[=0-9]", body):
            report.text_math.append(body.strip())
    return report


# ── Section 3: raw math candidate coverage ────────────────────────────────

@dataclass
class MathCoverage:
    display: int = 0
    inline: int = 0

    @property
    def total(self) -> int:
        return self.display + self.inline


def count_math_candidates(md: str) -> MathCoverage:
    """Count raw ``$...$`` / ``$$...$$`` candidates before remark-math parsing."""
    cov = MathCoverage()
    for m in _MATH_SPLIT.finditer(md):
        if m.group(0).startswith("$$"):
            cov.display += 1
        else:
            cov.inline += 1
    return cov


# ── Aggregate + CLI ───────────────────────────────────────────────────────

def analyze(md: str) -> dict:
    """Produce the Python-side quality report (coverage counts + anomalies)."""
    cov = count_math_candidates(md)
    pollution = detect_pollution(md)
    return {
        "raw_math_candidates": {"display": cov.display, "inline": cov.inline,
                                "total": cov.total},
        "replacement_chars": [a.__dict__ for a in detect_encoding_errors(md)],
        "ocr_diacritics": [a.__dict__ for a in detect_ocr_diacritics(md)],
        "unicode_math": [u.__dict__ for u in detect_unicode_math(md)],
        "pollution": pollution.to_dict(),
    }


def _main(argv: list[str]) -> int:
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Analyze math coverage / OCR / pollution in a markdown file.")
    parser.add_argument("path", help="markdown file to analyze")
    parser.add_argument("--fix", metavar="OUT", help="write cleaned markdown to OUT")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args(argv)

    md = Path(args.path).read_text(encoding="utf-8", errors="replace")

    if args.fix:
        Path(args.fix).write_text(fix_paper_markdown(md), encoding="utf-8")

    report = analyze(md)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        cov = report["raw_math_candidates"]
        pol = report["pollution"]
        print(f"Raw math candidates: {cov['total']} "
              f"(display {cov['display']}, inline {cov['inline']})")
        print(f"replacement chars (U+FFFD): {len(report['replacement_chars'])}")
        print(f"OCR dot diacritics: {len(report['ocr_diacritics'])}")
        print(f"Unicode math in prose: {len(report['unicode_math'])}")
        for u in report["unicode_math"][:10]:
            print(f"  line {u['line']}: {u['char']!r} -> {u['suggestion']}")
        print(f"pollution: unclosed_dollar={pol['unclosed_dollar']} "
              f"dollar_count={pol['dollar_count']} "
              f"paren_math_unbalanced={pol['paren_math_unbalanced']} "
              f"bracket_math_unbalanced={pol['bracket_math_unbalanced']} "
              f"markdown_escapes={pol['markdown_escapes']}")
        if pol["text_math"]:
            print(f"bad \\text{{..}} math: {pol['text_math']}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
