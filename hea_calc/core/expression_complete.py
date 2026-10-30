"""Context-aware completion for expression documents (no Qt) - 2026-10-28.

Suggestions come from the grammar the parser itself reads (:mod:`.expression_lexer`, :mod:`.expression_doc`), never
from a separately maintained command list:

* **declaration lines** (the range lines of a block, ``lo <= x <= hi, option=value``):
  - after the range, a range *option* - the parser's keywords ``step=``, ``points=``, ``p=`` (and the documented
    aliases when only they match what was typed); an option already given is not offered again, and ``step`` /
    ``points`` exclude each other (the parser rejects both);
  - in the variable position (between the comparisons), a variable of the block's expression line that the block
    does not declare yet;
  - at the start of the line, on request, a range *template* for each undeclared variable
    (``0 <= x <= 1, step=0.1``: the parser's own example);
* **expression lines**: on request, the element symbols of the loaded dataset that start with the typed letters,
  and the block's variables that start with a typed lower-case prefix.

:func:`complete` returns the candidates and the exact column span of the line they replace (the identifier being
typed) - a syntax-aware prefix replacement; nothing outside that span is ever touched.  ``explicit`` is a request
(Ctrl+Space); without it only multi-character completions (option keywords, long variable names) are offered, and
only when they extend what was typed."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import expression_lexer as L

OPTIONS = ("step", "points", "p")                                # canonical option keys (expression_doc)
ALIASES = {"preview": "p", "point": "points", "n": "points"}      # documented aliases -> canonical key
OPTION_DETAIL = {"step": "step size", "points": "number of values (both ends included)", "p": "preview value"}
TEMPLATE = "0 <= {v} <= 1, step=0.1"

_IDENT_TAIL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_LOWER_TAIL = re.compile(r"[a-z][a-z0-9_]*$")
_UPPER_TAIL = re.compile(r"[A-Z][a-z]?$")


@dataclass(frozen=True)
class Candidate:
    text: str            # what replaces the prefix
    label: str           # what the list shows
    kind: str            # "option", "variable", "element", "template"
    detail: str = ""


@dataclass
class Completion:
    line: int                                   # 0-based line of the document
    start: int                                  # column span of the line that the candidate replaces
    end: int
    prefix: str
    context: str                                # "option", "variable", "template", "element", "formula-variable"
    candidates: list[Candidate] = field(default_factory=list)


def _block_of(lines: list[str], roles: list[str], ln: int) -> tuple[int, int]:
    """(first, last) line of the block holding ``ln`` (blocks are separated by blank lines)."""
    a = ln
    while a > 0 and roles[a - 1] != L.ROLE_BLANK and roles[a] != L.ROLE_EXPRESSION:
        a -= 1
    b = ln
    while b + 1 < len(lines) and roles[b + 1] == L.ROLE_DECLARATION:
        b += 1
    return a, b


def _block_variables(lines, roles, ln, datasets) -> tuple[list[str], set[str]]:
    """The variables of the block's expression line, and those its declaration lines already declare."""
    a, b = _block_of(lines, roles, ln)
    used = L.formula_variables(lines[a], datasets) if roles[a] == L.ROLE_EXPRESSION else []
    declared = set()
    for i in range(a + 1, b + 1):
        if i == ln:
            continue
        d = L.declared_variable(lines[i])
        if d:
            declared.add(d[0])
    return used, declared


def _option_candidates(prefix: str, given: set[str]) -> list[Candidate]:
    blocked = set(given)
    if "step" in given:
        blocked.add("points")
    if "points" in given:
        blocked.add("step")
    out = [Candidate(k + "=", k + "=", "option", OPTION_DETAIL[k]) for k in OPTIONS
           if k not in blocked and k.startswith(prefix.lower())]
    if not out and prefix:
        out = [Candidate(a + "=", a + "=", "option", f"alias of {c}=") for a, c in ALIASES.items()
               if c not in blocked and a.startswith(prefix.lower())]
    return out


def complete(text: str, pos: int, datasets=None, explicit: bool = False) -> Completion | None:
    """Completion at document position ``pos`` of ``text`` (see the module docstring), or ``None``."""
    text = text or ""
    pos = max(0, min(pos, len(text)))
    lines = text.split("\n")
    ln = text.count("\n", 0, pos)
    col = pos - (text.rfind("\n", 0, pos) + 1)
    line = lines[ln]
    before = line[:col]
    roles = L.line_roles(lines)
    role = roles[ln]

    if role == L.ROLE_DECLARATION or (role == L.ROLE_BLANK and False):
        m = _IDENT_TAIL.search(before)
        prefix = m.group() if m else ""
        start = col - len(prefix)
        if prefix and start > 0 and (before[start - 1].isdigit() or before[start - 1] == "."):
            return None                                          # inside a number (1e5): nothing to complete
        toks = [t for t in L.lex_declaration(line[:start]) if t.kind != L.SPACE]
        comparisons = [t for t in toks if t.kind == L.COMPARISON]
        used, declared = _block_variables(lines, roles, ln, datasets)
        open_vars = [v for v in used if v not in declared]
        # options: after a comma that follows the second comparison and its bound
        if len(comparisons) >= 2 and any(t.text == "," for t in toks):
            last = toks[-1] if toks else None
            if last is not None and last.text not in (",",):
                return None                                      # mid-option value (step=0.|): no keyword here
            given = set()
            for t in L.lex_declaration(line):
                if t.kind == L.KEYWORD:
                    k = ALIASES.get(t.text.lower(), t.text.lower())
                    if not (t.start == start and t.end >= col):  # the option being typed is not "given"
                        given.add(k)
            cands = _option_candidates(prefix, given)
            if not explicit:
                cands = [c for c in cands if len(c.text) > len(prefix) and c.text.rstrip("=") != prefix]
            return Completion(ln, start, col + _tail(line, col), prefix, "option", cands) if cands else None
        # the variable between the comparisons
        if len(comparisons) == 1 and toks and toks[-1].kind == L.COMPARISON:
            cands = [Candidate(v, v, "variable", "variable of this block") for v in open_vars
                     if v.startswith(prefix) and (explicit or len(v) > len(prefix))]
            return Completion(ln, start, col + _tail(line, col), prefix, "variable", cands) if cands else None
        # the start of a declaration line: a range template, on request (or typing an undeclared variable name)
        if not toks and line[:start].strip() == "":
            cands = [Candidate(TEMPLATE.format(v=v), TEMPLATE.format(v=v), "template", "range of " + v)
                     for v in open_vars if v.startswith(prefix)]
            if not explicit:
                cands = [c for c in cands if prefix and len(prefix) >= 1]
            end = len(line.rstrip()) if line[col:].strip() == "" else col
            return Completion(ln, start, max(end, col), prefix, "template", cands) if cands else None
        return None

    if role == L.ROLE_EXPRESSION:
        mu = _UPPER_TAIL.search(before)
        ml = _LOWER_TAIL.search(before)
        if ml and (not mu or ml.start() > mu.start()) and not (mu and mu.end() == col and mu.group()[-1:].islower()
                                                             and len(mu.group()) == 2 and ml.start() == col - 1):
            prefix = ml.group()
            start = col - len(prefix)
            # a lower-case letter right after an element's capital is part of its symbol (Co), not a variable
            if start > 0 and before[start - 1].isupper() and datasets is not None \
                    and datasets.is_element(before[start - 1] + prefix[:1]):
                return None
            used, _declared = _block_variables(lines, roles, ln, datasets)
            others = sorted({v for v in _document_variables(lines, roles, datasets) if v != prefix} | set())
            pool = [v for v in dict.fromkeys(used + others) if v.startswith(prefix) and v != prefix]
            if not explicit:
                pool = [v for v in pool if len(v) > len(prefix) and len(v) > 2]
            cands = [Candidate(v, v, "variable", "variable") for v in pool]
            return Completion(ln, start, col + _tail(line, col), prefix, "formula-variable", cands) if cands else None
        if mu and explicit and datasets is not None:
            prefix = mu.group()
            start = col - len(prefix)
            syms = [s for s in _symbols(datasets) if s.startswith(prefix[:1]) and s.startswith(prefix)]
            cands = [Candidate(s, s, "element", "element") for s in syms]
            return Completion(ln, start, col, prefix, "element", cands) if cands else None
        return None
    return None


def _tail(line: str, col: int) -> int:
    """Identifier characters right of the caret that belong to the word being completed (replaced too)."""
    m = re.match(r"[A-Za-z0-9_]*", line[col:])
    return len(m.group()) if m else 0


def _document_variables(lines, roles, datasets) -> list[str]:
    out: list[str] = []
    for line, role in zip(lines, roles):
        if role == L.ROLE_EXPRESSION:
            out += L.formula_variables(line, datasets)
    return out


def _symbols(datasets) -> list[str]:
    for name in ("elements", "symbols"):
        v = getattr(datasets, name, None)
        if callable(v):
            v = v()
        if v:
            return sorted(v)
    return []


def apply(text: str, comp: Completion, cand: Candidate) -> tuple[str, int]:
    """``text`` with ``cand`` replacing the completion's span, and the caret position after it."""
    lines = (text or "").split("\n")
    line = lines[comp.line]
    lines[comp.line] = line[:comp.start] + cand.text + line[comp.end:]
    caret = sum(len(x) + 1 for x in lines[:comp.line]) + comp.start + len(cand.text)
    return "\n".join(lines), caret


__all__ = ["Candidate", "Completion", "complete", "apply", "OPTIONS", "ALIASES", "TEMPLATE"]
