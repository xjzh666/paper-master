"""Tests for the LaTeX normalization in paper_reader/latex_fix.py."""

import re

import pytest

from paper_reader.latex_fix import fix_latex_math, fix_markdown_math


# ── HTML tags ──────────────────────────────────────────────────────────

def test_html_sub_sup_in_math():
    # GenCert is a known function, so it also becomes \operatorname.
    assert fix_latex_math("$\\mathrm{GenCert}<sub>X</sub>(m)$") == \
        "$\\operatorname{GenCert}_{X}(m)$"
    # OTK is a known identifier, so it also becomes \mathrm{OTK}.
    assert fix_latex_math("$OTK<sup>i</sup>_{A}$") == "$\\mathrm{OTK}^{i}_{A}$"


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


def test_display_math_keeps_newline_before_closing_delim():
    """Multi-line display math ending in ``}``/``)`` must keep the newline
    before the closing ``$$``.

    Regression: ``_clean_spacing`` used ``\\s*`` around braces, which also
    stripped the ``\\n``, merging the closing ``$$`` onto the content line
    (``...\\tag{1}$$``). remark-math then failed to see ``$$`` as the closing
    delimiter: the ``$$`` leaked into the KaTeX value (red ``katex-error``)
    and the next block's opening ``$$`` got swallowed (raw ``\\begin{array}``
    text). See the Attention-is-All-you-Need markdown (blocks ending in
    ``\\tag{1}``/``\\end{array}``).
    """
    src = "$$\n\\operatorname{Attention}(Q, K, V) V\\tag{1}\n$$"
    out = fix_markdown_math(src)
    assert out == "$$\n\\operatorname{Attention}(Q, K, V)V\\tag{1}\n$$"
    assert out.endswith("\n$$"), out
    assert "\\tag{1}$$" not in out


# ── Section 1: semantic normalization (identifiers / functions) ─────────

def test_bare_identifiers_wrapped_in_mathrm():
    assert fix_latex_math(r"$aid_A = uid_U : name_A$") == \
        r"$\mathrm{aid}_A = \mathrm{uid}_U : \mathrm{name}_A$"
    assert fix_latex_math(r"$device_A, IP_A, port_A$") == \
        r"$\mathrm{device}_A, \mathrm{IP}_A, \mathrm{port}_A$"


def test_key_names_wrapped_in_mathrm():
    for src, want in [
        (r"$PK_A$", r"$\mathrm{PK}_A$"),
        (r"$SK_A$", r"$\mathrm{SK}_A$"),
        (r"$OTK_A^i$", r"$\mathrm{OTK}_A^i$"),
        (r"$SOTK_A^i$", r"$\mathrm{SOTK}_A^i$"),
        (r"$Cert_A$", r"$\mathrm{Cert}_A$"),
    ]:
        assert fix_latex_math(src) == want, f"{src} -> {fix_latex_math(src)}"


def test_split_identifier_merged():
    # OCR split "SK" into a bare "S" + "\mathrm{K}".
    assert fix_latex_math(r"$S \mathrm{K}_{\mathbb{U}}$") == \
        r"$\mathrm{SK}_{\mathbb{U}}$"


def test_identifier_inside_subscript_wrapped():
    assert fix_latex_math(r"$\sigma^U_{OTK^i}$") == r"$\sigma^U_{\mathrm{OTK}^i}$"


def test_identifier_not_double_wrapped():
    # Already-wrapped identifiers must not gain a second \mathrm layer.
    assert fix_latex_math(r"$\mathrm{PK}_A$") == r"$\mathrm{PK}_A$"
    assert fix_latex_math(r"$\mathrm{OTK}_A^i$") == r"$\mathrm{OTK}_A^i$"


def test_function_names_become_operatorname_with_subscript():
    assert fix_latex_math(r"$\mathrm{GenCert}_{SK_{CA}}$") == \
        r"$\operatorname{GenCert}_{\mathrm{SK}_{CA}}$"
    assert fix_latex_math(r"$\mathrm{Sign}_{SK_U}$") == \
        r"$\operatorname{Sign}_{\mathrm{SK}_U}$"


def test_blackboard_letter_spacing_collapsed():
    # \mathbb { I P } -> \mathbb{IP} (keep the font, drop OCR spacing).
    assert fix_latex_math(r"$\mathbb{I P}_{\mathtt{A}}$") == \
        r"$\mathbb{IP}_{\mathtt{A}}$"


def test_set_tuple_ellipsis():
    src = r"$\{(\mathrm{OTK}_A^1,\mathrm{SOTK}_A^1),...\}$"
    assert fix_latex_math(src) == \
        r"$\{(\mathrm{OTK}_A^1,\mathrm{SOTK}_A^1),\dots\}$"
