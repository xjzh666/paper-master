"""Normalize OCR'd LaTeX in markdown before KaTeX rendering.

MinerU's PDF->markdown pipeline leaves formula artifacts that render badly
in KaTeX. This module rewrites math blocks to standard LaTeX without
changing the underlying mathematical meaning. Applied at serve time so the
raw cache stays untouched.

Handled artifacts:
- HTML <sub>/<sup> tags leaked into math
- letter-spaced tokens like ``\\mathrm { V e r i f y }``
- mis-nested sub/superscripts like ``\\sigma_{OTK^i}^U``
- literal ``...`` / ``. . .`` instead of ``\\dots``
- upright function names not marked ``\\operatorname``
"""

from __future__ import annotations

import re

# Split markdown into display math ($$..$$), inline math ($..$), and prose.
_MATH_SPLIT = re.compile(r"(\$\$.*?\$\$|\$[^$\n]*?\$)", re.DOTALL)

# Commands whose argument is a single upright token (letter-spacing collapsed).
# Includes font-switching commands that keep math mode (spaces are ignored in
# math mode, but collapsing them makes the source canonical and readable).
_UPRIGHT_CMDS = frozenset({
    "mathrm", "mathbf", "mathsf", "mathtt", "text", "operatorname",
    "mathbb", "mathcal", "boldsymbol",
})

# Known multi-letter identifiers / protocol fields / key names that should be
# rendered upright (\\mathrm{...}) rather than as a product of italic variables.
_IDENTIFIER_TOKENS = frozenset({
    "PK", "SK", "OTK", "SOTK", "Cert", "cert", "aid", "uid", "name",
    "device", "IP", "port", "MAC", "KDF", "DH", "PRF", "PRG", "IV",
})

# Bare identifier token (standalone). ``\\`` and alphanumerics are excluded as
# boundaries; ``{``/``_``/``^`` are *allowed* so sub/superscript groups and
# bare subscript braces are wrapped too (font-command args are protected first).
_IDENT_ALT = "|".join(sorted(_IDENTIFIER_TOKENS, key=len, reverse=True))
_BARE_IDENT = re.compile(rf"(?<![A-Za-z0-9\\])({_IDENT_ALT})(?![A-Za-z0-9])")

# A bare leading letter glued onto a following \\mathrm{...} (OCR split an
# identifier across the command boundary): ``S \\mathrm{K}`` -> ``\\mathrm{SK}``.
_MERGE_SPLIT = re.compile(r"(?<![A-Za-z0-9\\])([A-Za-z])\s*\\mathrm\s*\{([^{}]*)\}")

# Known crypto-operation names (multi-letter). Converted to \operatorname even
# when the ``(`` call is not immediately visible (e.g. split across \left).
_KNOWN_FUNCS = frozenset({
    "Verify", "Sign", "GenCert", "Enc", "Dec", "KDF", "DH", "Hash",
    "Budget", "Request", "MAC", "PRF", "PRG", "SignVerify", "VerifyPK",
    "A2ACard", "A2ARequest", "Check", "Compute", "Setup",
})

# Letter-spacing inside upright command args: "V e r i f y" -> "Verify".
_LETTER_SPACE = re.compile(r"([A-Za-z])\s+([A-Za-z])")

# ``...`` / ``. . .`` -> \dots, and ``\bullet \bullet \bullet`` (set ellipsis) -> \dots
_DOTS = re.compile(r"\.\s*\.\s*\.")
_BULLETS = re.compile(r"\\bullet\s*\\bullet\s*\\bullet")


def _match_brace(s: str, i: int) -> int:
    """s[i] == '{'. Return index just past the matching '}' (len(s) if unbalanced)."""
    depth = 0
    n = len(s)
    j = i
    while j < n:
        c = s[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return n


def _collapse_letter_spacing(s: str) -> str:
    """Collapse ``V e r i f y`` -> ``Verify`` inside an upright command arg.

    Control sequences (``\\tt``, ``\\Delta`` ...) are protected first so a
    space that separates a command from the next token is preserved
    (``\\tt A`` must not become ``\\ttA``).
    """
    protected: dict[str, str] = {}

    def _protect(m: re.Match) -> str:
        key = f"\x00{len(protected)}\x00"
        protected[key] = m.group(0)
        return key

    s = re.sub(r"\\[A-Za-z]+", _protect, s)
    prev = None
    while prev != s:
        prev = s
        s = _LETTER_SPACE.sub(r"\1\2", s)
    for key, val in protected.items():
        s = s.replace(key, val)
    return s


def _fix_upright_args(s: str) -> str:
    """Collapse letter-spacing inside \\mathrm{...} args (any nesting depth)."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n and s[i + 1].isalpha():
            j = i + 1
            while j < n and s[j].isalpha():
                j += 1
            cmd = s[i + 1:j]
            k = j
            while k < n and s[k].isspace():
                k += 1
            if cmd in _UPRIGHT_CMDS and k < n and s[k] == "{":
                end = _match_brace(s, k)
                body = _collapse_letter_spacing(s[k + 1:end - 1]).strip()
                out.append(f"\\{cmd}{{{body}}}")
                i = end
            else:
                out.append(s[i:j])
                i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _convert_sup_to_sub(s: str) -> str:
    """Inside a subscript group, turn ``^{...}`` into ``_{...}``.

    ``\\sigma_{OTK^i}^U`` is an OCR mis-nesting of ``\\sigma_{OTK_i}^{U}``.
    """
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "^":
            k = i + 1
            while k < n and s[k].isspace():
                k += 1
            if k < n and s[k] == "{":
                end = _match_brace(s, k)
                out.append("_{" + s[k + 1:end - 1] + "}")
                i = end
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _fix_subscript_nesting(s: str) -> str:
    """For each ``_{...}`` group, fix superscripts nested inside it."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "_":
            k = i + 1
            while k < n and s[k].isspace():
                k += 1
            if k < n and s[k] == "{":
                end = _match_brace(s, k)
                inner = s[k + 1:end - 1]
                inner = _convert_sup_to_sub(inner)
                out.append("_{" + inner + "}")
                i = end
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


_CMD_TOKEN = re.compile(r"\\(?:mathrm|mathbf|mathsf|mathtt|text|operatorname)\{([A-Za-z][A-Za-z]*)\}")


def _skip_ws_and_subscripts(s: str, i: int) -> int:
    """Return index of the next meaningful char, skipping spaces and sub/sup
    groups (brace-balanced) that sit between a token and a ``(``."""
    n = len(s)
    while i < n:
        while i < n and s[i].isspace():
            i += 1
        if i >= n or s[i] not in "_^":
            break
        k = i + 1
        while k < n and s[k].isspace():
            k += 1
        if k >= n or s[k] != "{":
            break
        i = _match_brace(s, k)
    return i


def _to_operatorname(s: str) -> str:
    """Wrap upright multi-letter tokens in \\operatorname when they are
    known functions or appear as function calls (followed by ``(``)."""
    out: list[str] = []
    pos = 0
    for m in _CMD_TOKEN.finditer(s):
        out.append(s[pos:m.start()])
        token = m.group(1)
        j = _skip_ws_and_subscripts(s, m.end())
        if token in _KNOWN_FUNCS or (j < len(s) and s[j] == "("):
            out.append(f"\\operatorname{{{token}}}")
        else:
            out.append(m.group(0))
        pos = m.end()
    out.append(s[pos:])
    return "".join(out)


def _merge_split_identifiers(s: str) -> str:
    """Merge a bare letter glued to a following ``\\mathrm{...}`` when the
    concatenation is a known identifier: ``S \\mathrm{K}`` -> ``\\mathrm{SK}``.

    MinerU sometimes splits a single upright identifier across the command
    boundary (``S \\mathrm { K }`` for "SK"). Run this *before*
    ``_to_operatorname`` so a merged token can still be recognized as a
    function name afterwards.
    """
    def _merge(m: re.Match) -> str:
        lead = m.group(1)
        body = m.group(2).strip().replace(" ", "")
        joined = lead + body
        if joined in _IDENTIFIER_TOKENS or joined in _KNOWN_FUNCS:
            return f"\\mathrm{{{joined}}}"
        return m.group(0)
    return _MERGE_SPLIT.sub(_merge, s)


def _wrap_bare_identifiers(s: str) -> str:
    """Wrap standalone multi-letter identifiers in ``\\mathrm{...}``.

    Only tokens in the explicit ``_IDENTIFIER_TOKENS`` whitelist are touched,
    and only when they are not already inside a font command's argument. This
    changes typesetting (italic -> upright) without changing meaning.

    Existing ``\\command{...}`` arguments are protected (placeholder-swapped)
    first so their contents are never double-wrapped, while identifiers inside
    ordinary ``_{...}``/``^{...}`` groups are still wrapped.
    """
    protected: dict[str, str] = {}

    # Protect every ``\cmd{...}`` argument (brace-matched, any nesting).
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n and s[i + 1].isalpha():
            j = i + 1
            while j < n and s[j].isalpha():
                j += 1
            k = j
            while k < n and s[k].isspace():
                k += 1
            if k < n and s[k] == "{":
                end = _match_brace(s, k)
                key = f"\x00{len(protected)}\x00"
                protected[key] = s[i:end]
                out.append(key)
                i = end
                continue
        out.append(s[i])
        i += 1
    s = "".join(out)

    s = _BARE_IDENT.sub(lambda m: f"\\mathrm{{{m.group(1)}}}", s)

    for key, val in protected.items():
        s = s.replace(key, val)
    return s


def _clean_spacing(s: str) -> str:
    """Remove OCR whitespace around sub/sup and structural braces."""
    protected: dict[str, str] = {}

    def _protect(m: re.Match) -> str:
        key = f"\x00{len(protected)}\x00"
        protected[key] = m.group(0)
        return key

    # ``\ {`` is an escaped space followed by a group brace; collapsing it
    # into ``\{`` would unbalance the group. Protect ``\ `` first.
    s = re.sub(r"\\\s", _protect, s)
    s = re.sub(r"\s+([_^])", r"\1", s)
    s = re.sub(r"\s*,", r",", s)
    # Collapse OCR spacing around braces/parens, but never newlines:
    # a display-math block ending ``content}\n$$`` must keep the ``\n``
    # before the closing ``$$`` or remark-math won't see it as a close.
    s = re.sub(r"[ \t]*([{}()])[ \t]*", lambda b: b.group(1), s)
    for key, val in protected.items():
        s = s.replace(key, val)
    return s


def fix_latex_math(block: str) -> str:
    """Normalize one math block (with or without ``$`` delimiters)."""
    inner = block
    if inner.startswith("$$") and inner.endswith("$$"):
        delim = "$$"
        inner = inner[2:-2]
    elif inner.startswith("$") and inner.endswith("$"):
        delim = "$"
        inner = inner[1:-1]
    else:
        delim = ""

    # 1. HTML sub/sup leaked into math.
    inner = re.sub(r"<sub>([^<]*)</sub>", r"_{\1}", inner)
    inner = re.sub(r"<sup>([^<]*)</sup>", r"^{\1}", inner)

    # 2. Collapse letter-spaced upright tokens (any nesting depth).
    inner = _fix_upright_args(inner)

    # 3. Re-join identifiers split across a command boundary ("S \mathrm{K}").
    inner = _merge_split_identifiers(inner)

    # 4. Fix superscripts nested inside subscripts.
    prev = None
    while prev != inner:
        prev = inner
        inner = _fix_subscript_nesting(inner)

    # 5. ``...`` / ``. . .`` -> \dots, ``\bullet \bullet \bullet`` -> \dots
    inner = _DOTS.sub(r"\\dots", inner)
    inner = _BULLETS.sub(r"\\dots", inner)

    # 6. Function names -> \operatorname.
    inner = _to_operatorname(inner)

    # 7. Wrap remaining bare identifiers (keys / fields / entities) in \mathrm.
    inner = _wrap_bare_identifiers(inner)

    # 8. Cosmetic spacing around braces and sub/sup.
    inner = _clean_spacing(inner)

    return f"{delim}{inner}{delim}"


def fix_markdown_math(md: str) -> str:
    """Apply LaTeX normalization to every math block in a markdown document."""
    out: list[str] = []
    last = 0
    for m in _MATH_SPLIT.finditer(md):
        out.append(md[last:m.start()])
        out.append(fix_latex_math(m.group(0)))
        last = m.end()
    out.append(md[last:])
    return "".join(out)
