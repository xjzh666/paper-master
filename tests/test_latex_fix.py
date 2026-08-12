"""Tests for the LaTeX normalization in paper_reader/latex_fix.py."""

import re

import pytest

from paper_reader.latex_fix import fix_latex_math, fix_markdown_math


# ── HTML tags ──────────────────────────────────────────────────────────

def test_html_sub_sup_in_math():
    # GenCert is a known function, so it also becomes \operatorname.
    assert fix_latex_math("$\\mathrm{GenCert}<sub>X</sub>(m)$") == \
        "$\\operatorname{GenCert}_{X}(m)$"
    assert fix_latex_math("$OTK<sup>i</sup>_{A}$") == "$OTK^{i}_{A}$"


# ── letter-spacing ─────────────────────────────────────────────────────

def test_collapse_letter_spacing():
    # Verify is a function -> \operatorname; letter-spacing collapsed.
    assert fix_latex_math("$\\mathrm { V e r i f y } _ { \\mathrm { P K } }$") == \
        "$\\operatorname{Verify}_{\\mathrm{PK}}$"
    assert fix_latex_math("$\\mathrm { S K }$") == "$\\mathrm{SK}$"


def test_letter_spacing_preserves_command_delimiter():
    # ``\tt A`` must not become ``\ttA`` (space is the command delimiter).
    assert fix_latex_math("$\\mathrm { a i d _ { \\tt A } }$") == \
        "$\\mathrm{aid_{\\tt A}}$"
    assert fix_latex_math("$\\mathrm { \\Delta B u d g e t }$") == \
        "$\\mathrm{\\Delta Budget}$"


# ── sub/sup nesting ────────────────────────────────────────────────────

def test_fix_sigma_otk_nesting():
    # \sigma_{OTK^i}^U  ->  \sigma_{OTK_i}^{U}
    src = r"$\sigma_ {\mathrm{OTK} ^ {\mathrm{i}}} ^ {\mathrm{U}}$"
    out = fix_latex_math(src)
    assert re.sub(r"\s+", "", out) == r"$\sigma_{\mathrm{OTK}_{\mathrm{i}}}^{\mathrm{U}}$"
    assert "OTK^" not in out


def test_sibling_sub_sup_untouched():
    # \mathrm{OTK}_A^i with ^i as a SIBLING of _A stays as-is.
    src = r"$\mathrm{OTK} _ {\mathrm{A}} ^ {\mathrm{i}}$"
    assert re.sub(r"\s+", "", fix_latex_math(src)) == \
        r"$\mathrm{OTK}_{\mathrm{A}}^{\mathrm{i}}$"


# ── dots ───────────────────────────────────────────────────────────────

def test_ellipsis_to_dots():
    assert fix_latex_math(r"$\{t_1, . . . , t_k\}$") == r"$\{t_1, \dots, t_k\}$"
    assert fix_latex_math(r"$\{t_1, \bullet \bullet \bullet , t_k\}$") == \
        r"$\{t_1, \dots, t_k\}$"


# ── operatorname ───────────────────────────────────────────────────────

def test_function_names_become_operatorname():
    out = fix_latex_math(r"$\mathrm { V e r i f y } _ { \mathrm { P K } } \left( m \right)$")
    assert "\\operatorname{Verify}" in out
    out = fix_latex_math(r"$\mathrm { G e n C e r t } _ { X } ( m )$")
    assert "\\operatorname{GenCert}" in out


def test_identifiers_not_converted():
    for src in [
        r"$\mathrm { E D } _ { \mathrm { A } }$",
        r"$\mathrm { C e r t } _ { \mathrm { A } }$",
        r"$\mathrm { a i d } _ { \mathrm { A } }$",
        r"$\mathrm { P K } _ { \mathbb { U } }$",
        r"$\mathrm { C o u n t e r } _ { \mathrm { O T K } } [ x ]$",
    ]:
        out = fix_latex_math(src)
        assert "\\operatorname" not in out, f"{src} -> {out}"


def test_operatorname_known_set_without_call():
    # Sign used as a function even when the "(" is split across \left.
    out = fix_latex_math(r"$\mathrm { S i g n } _ { \mathrm { S K } } \left( m \right)$")
    assert "\\operatorname{Sign}" in out


# ── whole document ─────────────────────────────────────────────────────

def test_fix_markdown_math_only_touches_math():
    md = "prose text with **bold** and `code`\n\n$\\mathrm { E D } _ { A }$\n\nmore prose\n\n$$\\sigma_ {\\mathrm{OTK} ^ {\\mathrm{i}}} ^ {\\mathrm{U}}$$"
    out = fix_markdown_math(md)
    assert "**bold**" in out            # prose untouched
    assert "`code`" in out              # prose untouched
    assert "\\mathrm{ED}_{A}" in out    # inline math fixed
    assert "\\sigma_{\\mathrm{OTK}_{\\mathrm{i}}}" in out  # display math nesting fixed


def test_math_blocks_still_renderable():
    """Every math block must survive as valid-ish LaTeX (no stray delimiters)."""
    blocks = re.findall(r"\$\$.*?\$\$|\$[^$\n]*?\$",
                        fix_markdown_math("$a$ $\\mathrm { V e r i f y }$ $$x^{2}$$"),
                        re.DOTALL)
    assert len(blocks) == 3
