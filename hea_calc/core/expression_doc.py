"""Composition expression documents - the inline syntax of Composition setup (no Qt).

A document is one or more **blocks** separated by one or more blank lines.  In every block

* the **first line** is a composition expression (the verified formula syntax of :mod:`.expression`: element
  symbols, amounts, groups, lower-case variables, braces ``B{a}``);
* every **following line** declares one variable used in that expression::

      0 <= x <= 2, step=0.05           values 0, 0.05, …, 2
      0 <= x <= 0.3, points=31         31 evenly spaced values, both endpoints included
      0 < x < 1, step=0.1              strict bounds: 0.1, …, 0.9 (the endpoints 0 and 1 are excluded)
      0 <= x <= 0.2, step=0.1, p=0.10  ``p`` (or ``preview``) - the value shown in a single-block preview

``step`` and ``points`` are mutually exclusive; ``<=`` may be written ``≤``; ``<`` is a strict bound and is never
read as ``<=``: the grid is built on the closed interval, then a strict bound removes that endpoint (see
:class:`.expression.VariableRange`).  A block without variables is a fixed composition; a block with variables is
parametric; any mixture of blocks is one batch.  Ranges belong to their block, so the same variable name may have
different ranges in different blocks.

:func:`parse_document` never raises: it returns every block with its expression and ranges, or its errors.  Every
error is also a :class:`Diagnostic` with its line, column span, category (lexical / syntax / semantic) and whether
it only says that the text is unfinished (``incomplete``: a missing ``)`` at the end of a line), so the editor can
underline it in place and hold unfinished-input errors back while the user is still typing.  The scientific formula
parser is not changed here - only the document structure around it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .expression import Expression, ExpressionError, RangeError, VariableRange, parse_expression
from .expression_lexer import VARIABLE, declared_variable, lex_formula

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
COMPARE = r"(<=|≤|<)"
DECL = re.compile(rf"^\s*({NUMBER})\s*{COMPARE}\s*([A-Za-z_][A-Za-z0-9_]*)\s*{COMPARE}\s*({NUMBER})\s*(?:,(.*))?$")
OPTION = re.compile(r"^\s*([A-Za-z]+)\s*=\s*(\S+)\s*$")

LEXICAL, SYNTAX, SEMANTIC = "lexical", "syntax", "semantic"
DEFAULT_RANGE = "0 <= {v} <= 1, step=0.1"     # the automatic declaration of a new variable
DECLARATION_INDENT = "  "                     # declarations sit two spaces in (Figma Expression bases)


@dataclass(frozen=True)
class Diagnostic:
    """One problem of a document: 0-based ``line`` and column span ``[start, end)`` of the original text (``end``
    may pass the end of the line when something is missing there), the ``message`` (first line short, following
    lines the advice), ``category`` (lexical / syntax / semantic), ``block`` (0-based) and ``incomplete`` (the
    text is only unfinished at the end of the line)."""
    line: int
    start: int
    end: int
    message: str
    category: str = SYNTAX
    block: int = 0
    incomplete: bool = False
    severity: str = "error"

    @property
    def title(self) -> str:
        return self.message.split("\n", 1)[0]


@dataclass
class Block:
    index: int                                  # 0-based
    lines: list[str]                            # non-empty lines of the block, stripped
    expression: Expression | None = None
    ranges: dict[str, VariableRange] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    line: int = 0                               # 0-based document line of the expression

    @property
    def first_line(self) -> str:
        return self.lines[0] if self.lines else ""

    @property
    def ok(self) -> bool:
        return not self.errors and self.expression is not None

    @property
    def kind(self) -> str:
        return "parametric" if self.expression is not None and self.expression.variables else "fixed"

    @property
    def combinations(self) -> int:
        if not self.ok:
            return 0
        n = 1
        for v in self.expression.variables:
            n *= len(self.ranges[v].values())
        return n

    def preview_env(self) -> dict[str, float]:
        """Variable values for the single-block preview: each declared ``p``, else the first grid value."""
        if self.expression is None:
            return {}
        out = {}
        for v, r in self.ranges.items():
            if v in self.expression.variables:
                vals = r.values()
                out[v] = r.preview if r.preview is not None else (vals[0] if vals else r.minimum)
        return out


@dataclass
class Document:
    text: str
    blocks: list[Block]

    @property
    def ok(self) -> bool:
        return bool(self.blocks) and all(b.ok for b in self.blocks)

    @property
    def errors(self) -> list[tuple[int, str, str]]:
        """(1-based block number, the block's first line, message) for every failing block."""
        return [(b.index + 1, b.first_line, m) for b in self.blocks for m in b.errors]

    @property
    def diagnostics(self) -> list[Diagnostic]:
        return [d for b in self.blocks for d in b.diagnostics]

    @property
    def expressions(self) -> list[Expression]:
        return [b.expression for b in self.blocks]

    @property
    def block_ranges(self) -> list[dict[str, VariableRange]]:
        return [dict(b.ranges) for b in self.blocks]

    @property
    def combinations(self) -> int:
        return sum(b.combinations for b in self.blocks)

    @property
    def variables(self) -> list[str]:
        out: list[str] = []
        for b in self.blocks:
            if b.expression is not None:
                for v in b.expression.variables:
                    if v not in out:
                        out.append(v)
        return out

    def elements(self) -> list[str]:
        out: list[str] = []
        for b in self.blocks:
            if b.expression is not None:
                _collect(b.expression.items, out)
        return out


def _collect(items, out):
    for it in items:
        if hasattr(it, "symbol"):
            if it.symbol not in out:
                out.append(it.symbol)
        else:
            _collect(it.items, out)


def split_document(text: str) -> list[tuple[int, list[str]]]:
    """[(first line number, stripped non-empty lines)] of every block (blank lines separate blocks)."""
    return [(first + 1, [ln.strip() for _n, ln in lines]) for first, lines in document_blocks(text)]


def document_blocks(text: str) -> list[tuple[int, list[tuple[int, str]]]]:
    """[(0-based first line, [(0-based line, original line)])] of every block."""
    blocks, cur = [], []
    for i, line in enumerate((text or "").split("\n")):
        if line.strip():
            cur.append((i, line))
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return [(b[0][0], b) for b in blocks]


def formula_message(exc: Exception) -> str:
    """The formula parser's message in the editor's wording (COMPOSITION_EXPRESSION_ERROR.png)."""
    msg = re.sub(r"\s*\(at position \d+\)$", "", str(exc))
    m = re.match(r"Unknown element '([^']+)'", msg)
    if m:
        return f'Unknown element "{m.group(1)}"'
    if msg in ("Missing ')'", "Unbalanced ')'", "Missing ']'"):
        return "Unmatched parenthesis"
    return msg


def parse_declaration(line: str) -> tuple[VariableRange | None, str | None]:
    """One range line -> (range, None) or (None, message)."""
    rng, err, _span = parse_declaration_span(line)
    return rng, err


def parse_declaration_span(line: str) -> tuple[VariableRange | None, str | None, tuple[int, int]]:
    """:func:`parse_declaration` with the column span of the problem in ``line`` (the whole line if none)."""
    whole = (len(line) - len(line.lstrip()), len(line.rstrip()))
    m = DECL.match(line)
    if not m:
        return None, f'"{line.strip()}" is not a range.\nUse a line such as 0 <= x <= 1, step=0.1.', whole
    lo, lo_op, name, hi_op, hi = float(m.group(1)), m.group(2), m.group(3), m.group(4), float(m.group(5))
    rest = m.group(6) or ""
    lo_span, name_span, hi_span = m.span(1), m.span(3), m.span(5)
    rest_at = m.start(6) if m.group(6) is not None else len(line)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        return None, f'"{name}" is not a variable name.\nVariables are lower-case, e.g. x or y1.', name_span
    opts: dict[str, tuple[str, tuple[int, int]]] = {}
    pos = rest_at
    for part in rest.split(","):
        span = (pos + len(part) - len(part.lstrip()), pos + len(part.rstrip()))
        pos += len(part) + 1
        if not part.strip():
            continue
        om = OPTION.match(part)
        if not om:
            return None, f'"{part.strip()}" is not a range option.\nUse step=…, points=… or p=….', span
        key = om.group(1).lower()
        key = {"preview": "p", "point": "points", "n": "points"}.get(key, key)
        if key not in ("step", "points", "p"):
            return None, f'Unknown range option "{om.group(1)}".\nUse step=…, points=… or p=….', span
        if key in opts:
            return None, f'The option "{key}" is given twice.', span
        opts[key] = (om.group(2), span)
    if "step" in opts and "points" in opts:
        a, b = sorted((opts["step"][1], opts["points"][1]))
        return None, "Choose one sampling method.\nSpecify either step or points, not both.", (a[0], b[1])
    if lo > hi:
        return None, f"The lower bound of {name} exceeds its upper bound.", (lo_span[0], hi_span[1])
    step = points = preview = None
    try:
        if "step" in opts:
            step = float(opts["step"][0])
            if not math.isfinite(step) or step <= 0:
                return None, f"The step of {name} must be greater than 0.", opts["step"][1]
        if "points" in opts:
            pv = float(opts["points"][0])
            if pv != int(pv) or pv < 1:
                return None, f"The points of {name} must be a whole number of at least 2.", opts["points"][1]
            points = int(pv)
            if points < 2 and hi > lo:
                return None, f"The points of {name} must be at least 2 (both endpoints are included).", \
                    opts["points"][1]
        if "p" in opts:
            preview = float(opts["p"][0])
    except ValueError:
        bad = next((sp for v, sp in opts.values() if not _is_number(v)), whole)
        return None, f"A range option of {name} is not a number.", bad
    if step is None and points is None:
        if hi > lo:
            return None, f"Choose a sampling method for {name}.\nSpecify step or points.", (name_span[0], whole[1])
        points = 1
    rng = VariableRange(name, lo, hi, step, points, preview, lo_op != "<", hi_op != "<")
    if preview is not None and not rng.contains(preview):
        return None, f"The preview value of {name} lies outside {rng.bounds_text()}.", opts["p"][1]
    try:
        vals = rng.values()
    except RangeError as exc:
        return None, str(exc), (name_span[0], whole[1])
    if not vals:
        return None, (f"The range {rng.bounds_text()} contains no values.\nWiden it, or use <= to include an "
                      "endpoint."), (lo_span[0], hi_span[1])
    return rng, None, whole


def _is_number(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


_TRAILING = tuple(f"Unexpected '{c}'" for c in "+-*/^_{")


def _formula_span(line: str, exc: ExpressionError) -> tuple[int, int, bool]:
    """Original columns of a parser error (the parser reads the line without spaces) and whether it only says
    that the line is unfinished (the problem is at its end: a missing ``)`` or a trailing operator)."""
    cols = [i for i, ch in enumerate(line) if ch != " "]
    pos = getattr(exc, "pos", None)
    length = getattr(exc, "length", None)
    end_col = len(line.rstrip())
    if pos is None or not cols:
        return (len(line) - len(line.lstrip()), max(end_col, 1), False)
    if pos >= len(cols) or not length:              # something missing at the end of the line
        return (end_col, end_col + 2, True)
    a = cols[pos]
    b = cols[min(len(cols) - 1, pos + max(1, length) - 1)] + 1
    unfinished = pos + max(1, length) >= len(cols) and str(exc).startswith(_TRAILING)
    return (a, b, unfinished)


def _formula_category(msg: str) -> str:
    return LEXICAL if msg.startswith(("Unknown element", "Unexpected")) else SYNTAX


def parse_document(text: str, datasets=None) -> Document:
    """Parse every block (never raises; see the module docstring)."""
    blocks: list[Block] = []
    for i, (first, lines) in enumerate(document_blocks(text)):
        b = Block(i, [ln.strip() for _n, ln in lines], line=first)

        def add(line_no: int, span: tuple[int, int], msg: str, category: str, incomplete: bool = False,
                block=b, index=i):
            block.errors.append(msg)
            block.diagnostics.append(Diagnostic(line_no, span[0], span[1], msg, category, index, incomplete))

        expr_line = lines[0][1]
        try:
            b.expression = parse_expression(expr_line, datasets)
        except ExpressionError as exc:
            msg = formula_message(exc)
            a, e, unfinished = _formula_span(expr_line, exc)
            add(first, (a, e), msg, _formula_category(msg), unfinished)
        attempted: set[str] = set()                 # variables whose declaration failed (reported once)
        decl_lines: dict[str, tuple[int, str]] = {}
        for line_no, line in lines[1:]:
            rng, err, span = parse_declaration_span(line)
            m = DECL.match(line)
            if err:
                add(line_no, span, err, SEMANTIC if m else SYNTAX)
                if m:
                    attempted.add(m.group(3))
                continue
            if rng.name in b.ranges:
                add(line_no, (len(line) - len(line.lstrip()), len(line.rstrip())),
                    f'The variable "{rng.name}" is declared twice.', SEMANTIC)
                continue
            b.ranges[rng.name] = rng
            decl_lines[rng.name] = (line_no, line)
        if b.expression is not None:
            used = list(b.expression.variables)
            tokens = lex_formula(expr_line, datasets)
            for v in used:
                if v not in b.ranges and v not in attempted:
                    tok = next((t for t in tokens if t.kind == VARIABLE and t.text.replace(" ", "") == v), None)
                    span = (tok.start, tok.end) if tok else (0, len(expr_line.rstrip()))
                    add(first, span, f'The variable "{v}" has no range.\nAdd a line such as '
                                     f'{DEFAULT_RANGE.format(v=v)}.', SEMANTIC)
            for v in b.ranges:
                if v not in used:
                    line_no, line = decl_lines[v]
                    dv = declared_variable(line)
                    span = (dv[1], dv[2]) if dv else (0, len(line.rstrip()))
                    add(line_no, span, f'The variable "{v}" is not used in the expression.', SEMANTIC)
        blocks.append(b)
    return Document(text, blocks)


# ---------------------------------------------------------------------- automatic range declarations
@dataclass(frozen=True)
class DeclarationEdit:
    """One edit of :func:`plan_declarations` on 0-based document lines: ``insert`` (a new line *after* ``line``),
    ``delete`` (the line) or ``rename`` (columns ``[start, end)`` of the line become ``text``)."""
    kind: str
    line: int
    text: str = ""
    start: int = 0
    end: int = 0


def plan_declarations(text: str, datasets, memory: list[set[str]] | None = None
                      ) -> tuple[list[DeclarationEdit], list[set[str]]]:
    """The range lines to add, rename or remove so that every variable of every expression has a declaration.

    Policy (per block):

    * a variable that appears in the expression and has no declaration gets ``DEFAULT_RANGE`` (indented by
      ``DECLARATION_INDENT``) after the block's last line, in order of appearance - once: ``memory`` (one set per
      block, carried by the caller) remembers the variables already declared or offered, so a declaration the user
      deleted (or undid) is not added again;
    * exactly one variable gone and one new in the same pass is a rename: the declaration keeps its values and only
      its variable name changes;
    * a declaration of a variable no longer used is removed when it is still the untouched default; an edited one
      stays and the parse reports it as unused (the user decides).

    Returns the edits (apply them bottom-up: they are sorted by descending line) and the updated memory.
    """
    from .expression_lexer import formula_variables
    memory = list(memory or [])
    blocks = document_blocks(text)
    while len(memory) < len(blocks):
        memory.append(set())
    edits: list[DeclarationEdit] = []
    new_memory: list[set[str]] = []
    for bi, (first, lines) in enumerate(blocks):
        mem = set(memory[bi])
        used = formula_variables(lines[0][1], datasets)
        declared: dict[str, tuple[int, str, int, int]] = {}
        for line_no, line in lines[1:]:
            dv = declared_variable(line)
            if dv is not None and dv[0] not in declared:
                declared[dv[0]] = (line_no, line, dv[1], dv[2])
        unused = [v for v in declared if v not in used]
        new = [v for v in used if v not in declared and v not in mem]
        if len(unused) == 1 and len(new) == 1:
            line_no, _line, a, b = declared[unused[0]]
            edits.append(DeclarationEdit("rename", line_no, new[0], a, b))
            mem.discard(unused[0])
            mem.add(new[0])
            new = []
            unused = []
        for v in unused:
            line_no, line, _a, _b = declared[v]
            if line.strip() == DEFAULT_RANGE.format(v=v):
                edits.append(DeclarationEdit("delete", line_no))
                mem.discard(v)
        last = lines[-1][0]
        for v in new:
            edits.append(DeclarationEdit("insert", last, DECLARATION_INDENT + DEFAULT_RANGE.format(v=v)))
            mem.add(v)
        mem |= set(declared) & set(used)
        mem &= set(used) | set(declared)          # a variable gone from the expression may be declared again later
        new_memory.append(mem)
    order = {"rename": 0, "delete": 1, "insert": 2}
    edits.sort(key=lambda e: (-e.line, order[e.kind]))
    return edits, new_memory


def apply_declaration_edits(text: str, edits: list[DeclarationEdit]) -> str:
    """The text after :func:`plan_declarations`' edits (the editor applies them with a text cursor instead)."""
    lines = (text or "").split("\n")
    inserts: dict[int, list[str]] = {}
    for e in edits:
        if e.kind == "insert":
            inserts.setdefault(e.line, []).append(e.text)
    for e in sorted((e for e in edits if e.kind != "insert"), key=lambda e: -e.line):
        if e.kind == "rename":
            ln = lines[e.line]
            lines[e.line] = ln[:e.start] + e.text + ln[e.end:]
    deleted = {e.line for e in edits if e.kind == "delete"}
    out = []
    for i, ln in enumerate(lines):
        if i not in deleted:
            out.append(ln)
        out.extend(inserts.get(i, []))
    return "\n".join(out)


def summary(doc: Document, valid: int | None = None, duplicates: int = 0) -> str:
    """The success line under the field (COMPOSITION_EXPRESSION_*_PARSED.png)."""
    n = len(doc.blocks)
    els = len(doc.elements())
    count = "" if valid is None else f", {valid:,} composition{'s' if valid != 1 else ''}"
    if duplicates:
        count += f" ({duplicates:,} duplicate{'s' if duplicates != 1 else ''})"
    if n == 1:
        b = doc.blocks[0]
        if b.kind == "fixed":
            return f"Parsed successfully: Single composition, {els} elements."
        nv = len(b.expression.variables)
        return (f"Parsed successfully: Parametric composition, {els} elements, {nv} variable"
                f"{'s' if nv != 1 else ''}{count}.")
    fixed = sum(1 for b in doc.blocks if b.kind == "fixed")
    para = n - fixed
    return (f"Parsed successfully: {n} expressions, {fixed} fixed, {para} parametric{count}.")


__all__ = ["Block", "Document", "Diagnostic", "DeclarationEdit", "plan_declarations", "apply_declaration_edits",
           "parse_document", "parse_declaration", "parse_declaration_span",
           "split_document", "document_blocks", "summary", "formula_message", "DEFAULT_RANGE",
           "DECLARATION_INDENT", "LEXICAL", "SYNTAX", "SEMANTIC"]
