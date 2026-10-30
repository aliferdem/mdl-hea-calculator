"""Chemistry-aware lexer for expression documents (no Qt) - the one tokenizer behind the editor's syntax
highlighting, its diagnostics and the automatic range declarations.

It reads a line exactly the way the calculation parser (:mod:`.expression`) does, so the editor never shows a
reading the backend would not use:

* **expression lines** (the first line of a block) are read with their spaces removed, as ``_Parser`` does.
  Element symbols are matched greedily against the periodic table of the loaded dataset: an upper-case letter
  followed by a lower-case letter is a two-letter symbol when that symbol exists (``Co`` cobalt, ``Ni`` nickel),
  otherwise the upper-case letter alone is the symbol (``CO`` = C + O, ``Cx`` = C + x).  An upper-case letter
  that is no element is an *invalid* token.  Amounts are numbers (``1.6``, ``.5``; exponents only inside
  ``{…}``), lower-case variables (``x``, ``y1``, ``al_frac``) and the operators ``+ - * / ^``; groups use
  ``( )`` or ``[ ]``; ``{…}`` and ``_(…)`` hold arithmetic.  ``CrMnFeCoNiyCux`` = Cr Mn Fe Co Ni y Cu x.
* **declaration lines** (the following lines of a block): numbers, the comparisons ``<=`` / ``≤`` / ``<``, the
  variable name, commas, and ``key=value`` options whose key is a *keyword* (``step``, ``points``, ``p`` and the
  documented aliases ``preview``, ``point``, ``n``).

Token kinds (``Token.kind``): ``element``, ``number``, ``variable``, ``keyword``, ``operator`` (arithmetic and
``=``), ``comparison``, ``punctuation`` (brackets, braces, ``_``, commas), ``space`` and ``invalid``.  Token
spans are columns of the original line (``start`` inclusive, ``end`` exclusive).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ELEMENT = "element"
NUMBER = "number"
VARIABLE = "variable"
KEYWORD = "keyword"
OPERATOR = "operator"
COMPARISON = "comparison"
PUNCTUATION = "punctuation"
SPACE = "space"
INVALID = "invalid"

KEYWORDS = ("step", "points", "p", "preview", "point", "n")
ROLE_BLANK, ROLE_EXPRESSION, ROLE_DECLARATION = "blank", "expression", "declaration"

_NUM_SIMPLE = re.compile(r"\d+(?:\.\d*)?|\.\d+")
_NUM_FULL = re.compile(r"\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?")
_IDENT = re.compile(r"[a-z][a-z0-9_]*")
_DECL_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# Character classes in the regexes' own terms (ASCII).  ``str.isdigit`` / ``isalpha`` / ``islower`` are true for
# any Unicode digit or letter ("²", "ü", "ı", "ş", "İ"...), which the regexes above do not match: deciding a token
# class with them and then matching left ``None`` - the editor crashed on a Turkish-keyboard letter.  Any other
# character is an ``invalid`` token, which the editor marks and the document parser reports.
def _digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _lower(ch: str) -> bool:
    return "a" <= ch <= "z"


def _ident_start(ch: str) -> bool:
    return ch == "_" or "a" <= ch <= "z" or "A" <= ch <= "Z"


@dataclass(frozen=True)
class Token:
    kind: str
    start: int
    end: int
    text: str


def _is_element(datasets, sym: str) -> bool:
    return bool(datasets is not None and datasets.is_element(sym))


def lex_formula(line: str, datasets) -> list[Token]:
    """Tokens of an expression line (see the module docstring).  Spaces are their own tokens; every other
    token is read from the space-free text, as the parser reads it, and mapped back to original columns."""
    cols = [i for i, ch in enumerate(line) if ch != " "]
    s = "".join(line[i] for i in cols)
    raw: list[tuple[str, int, int]] = []          # (kind, start, end) in the space-free text
    i, depth_brace = 0, 0
    while i < len(s):
        ch = s[i]
        if ch.isupper():
            two = s[i:i + 2]
            if len(two) == 2 and two[1].islower() and _is_element(datasets, two):
                raw.append((ELEMENT, i, i + 2))
                i += 2
            elif _is_element(datasets, ch):
                raw.append((ELEMENT, i, i + 1))
                i += 1
            else:
                n = 2 if len(two) == 2 and two[1].islower() else 1
                raw.append((INVALID, i, i + n))
                i += n
            continue
        if _digit(ch) or (ch == "." and i + 1 < len(s) and _digit(s[i + 1])):
            m = (_NUM_FULL if depth_brace else _NUM_SIMPLE).match(s, i)
            raw.append((NUMBER, i, m.end()))
            i = m.end()
            continue
        if _lower(ch):
            m = _IDENT.match(s, i)
            raw.append((VARIABLE, i, m.end()))
            i = m.end()
            continue
        if ch in "+-*/^":
            raw.append((OPERATOR, i, i + 1))
        elif ch in "()[]_":
            raw.append((PUNCTUATION, i, i + 1))
        elif ch == "{":
            depth_brace += 1
            raw.append((PUNCTUATION, i, i + 1))
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)
            raw.append((PUNCTUATION, i, i + 1))
        else:
            raw.append((INVALID, i, i + 1))
        i += 1
    out: list[Token] = []
    for kind, a, b in raw:
        start, end = cols[a], cols[b - 1] + 1
        out.append(Token(kind, start, end, line[start:end]))
    return _with_spaces(line, out)


def lex_declaration(line: str) -> list[Token]:
    """Tokens of a range declaration line (``0 <= x <= 1, step=0.1``, ``0 < y < 0.5, points=11``)."""
    out: list[Token] = []
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch in " \t":
            i += 1
            continue
        if line.startswith("<=", i):
            out.append(Token(COMPARISON, i, i + 2, "<="))
            i += 2
            continue
        if ch in "<≤":
            out.append(Token(COMPARISON, i, i + 1, ch))
            i += 1
            continue
        if _digit(ch) or (ch == "." and i + 1 < n and _digit(line[i + 1])):
            m = _NUM_FULL.match(line, i)
            out.append(Token(NUMBER, i, m.end(), m.group()))
            i = m.end()
            continue
        if _ident_start(ch):
            m = _DECL_IDENT.match(line, i)
            word = m.group()
            j = m.end()
            while j < n and line[j] in " \t":
                j += 1
            kind = KEYWORD if (j < n and line[j] == "=") else VARIABLE
            out.append(Token(kind, i, m.end(), word))
            i = m.end()
            continue
        if ch in "=+-":
            out.append(Token(OPERATOR, i, i + 1, ch))
        elif ch == ",":
            out.append(Token(PUNCTUATION, i, i + 1, ch))
        else:
            out.append(Token(INVALID, i, i + 1, ch))
        i += 1
    return _with_spaces(line, out)


def _with_spaces(line: str, tokens: list[Token]) -> list[Token]:
    """Insert ``space`` tokens for the gaps, so the tokens cover the line."""
    out: list[Token] = []
    pos = 0
    for tok in sorted(tokens, key=lambda t: t.start):
        if tok.start > pos:
            out.append(Token(SPACE, pos, tok.start, line[pos:tok.start]))
        out.append(tok)
        pos = max(pos, tok.end)
    if pos < len(line):
        out.append(Token(SPACE, pos, len(line), line[pos:]))
    return out


def line_roles(lines: list[str]) -> list[str]:
    """Role of every line: the first non-blank line after a blank line (or the start) is an expression, the
    following non-blank lines of the block are declarations (:func:`.expression_doc.split_document`)."""
    roles, prev_blank = [], True
    for line in lines:
        if not line.strip():
            roles.append(ROLE_BLANK)
            prev_blank = True
        else:
            roles.append(ROLE_EXPRESSION if prev_blank else ROLE_DECLARATION)
            prev_blank = False
    return roles


def lex_line(line: str, role: str, datasets) -> list[Token]:
    if role == ROLE_EXPRESSION:
        return lex_formula(line, datasets)
    if role == ROLE_DECLARATION:
        return lex_declaration(line)
    return _with_spaces(line, [])


def lex_document(text: str, datasets) -> list[list[Token]]:
    lines = (text or "").split("\n")
    return [lex_line(line, role, datasets) for line, role in zip(lines, line_roles(lines))]


def formula_variables(line: str, datasets) -> list[str]:
    """Variables of an expression line in order of first appearance (also for a line that does not parse)."""
    out: list[str] = []
    for tok in lex_formula(line, datasets):
        if tok.kind == VARIABLE and tok.text.replace(" ", "") not in out:
            out.append(tok.text.replace(" ", ""))
    return out


def declared_variable(line: str) -> tuple[str, int, int] | None:
    """(name, start, end) of the variable a declaration line declares - the first identifier that is not an
    option keyword - or ``None``."""
    for tok in lex_declaration(line):
        if tok.kind == VARIABLE:
            return tok.text, tok.start, tok.end
    return None


__all__ = ["Token", "lex_formula", "lex_declaration", "lex_line", "lex_document", "line_roles",
           "formula_variables", "declared_variable", "ELEMENT", "NUMBER", "VARIABLE", "KEYWORD", "OPERATOR",
           "COMPARISON", "PUNCTUATION", "SPACE", "INVALID", "KEYWORDS", "ROLE_BLANK", "ROLE_EXPRESSION",
           "ROLE_DECLARATION"]
