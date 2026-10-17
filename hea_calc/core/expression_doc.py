"""Composition expression documents - the inline syntax of Composition setup (no Qt).

A document is one or more **blocks** separated by one or more blank lines.  In every block

* the **first line** is a composition expression (the verified formula syntax of :mod:`.expression`: element
  symbols, amounts, groups, lower-case variables, braces ``B{a}``);
* every **following line** declares one variable used in that expression::

      0 <= x <= 2, step=0.05           values 0, 0.05, …, 2
      0 <= x <= 0.3, points=31         31 evenly spaced values, both endpoints included
      0 <= x <= 0.2, step=0.1, p=0.10  ``p`` (or ``preview``) - the value shown in a single-block preview

``step`` and ``points`` are mutually exclusive; ``<=`` may be written ``≤``.  A block without variables is a fixed
composition; a block with variables is parametric; any mixture of blocks is one batch.  Ranges belong to their
block, so the same variable name may have different ranges in different blocks.

:func:`parse_document` never raises: it returns every block with its expression and ranges, or its error, so the
editor can report each failing block ("2 (FeCoNi / Unmatched parenthesis").  The scientific formula parser is not
changed here - only the document structure around it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .expression import Expression, ExpressionError, RangeError, VariableRange, parse_expression

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
DECL = re.compile(rf"^\s*({NUMBER})\s*(?:<=|≤)\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:<=|≤)\s*({NUMBER})\s*(?:,(.*))?$")
OPTION = re.compile(r"^\s*([A-Za-z]+)\s*=\s*(\S+)\s*$")


@dataclass
class Block:
    index: int                                  # 0-based
    lines: list[str]                            # non-empty lines of the block, stripped
    expression: Expression | None = None
    ranges: dict[str, VariableRange] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

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
        """Variable values for the single-block preview: each declared ``p``, else the lower bound."""
        if self.expression is None:
            return {}
        return {v: (r.preview if r.preview is not None else r.minimum)
                for v, r in self.ranges.items() if v in self.expression.variables}


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
    blocks, cur, start = [], [], 0
    for i, line in enumerate((text or "").splitlines(), start=1):
        if line.strip():
            if not cur:
                start = i
            cur.append(line.strip())
        elif cur:
            blocks.append((start, cur))
            cur = []
    if cur:
        blocks.append((start, cur))
    return blocks


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
    m = DECL.match(line)
    if not m:
        return None, f'"{line}" is not a range.\nUse a line such as 0 <= x <= 1, step=0.1.'
    lo, name, hi, rest = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4) or ""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        return None, f'"{name}" is not a variable name.\nVariables are lower-case, e.g. x or y1.'
    opts: dict[str, str] = {}
    for part in [p for p in rest.split(",") if p.strip()]:
        om = OPTION.match(part)
        if not om:
            return None, f'"{part.strip()}" is not a range option.\nUse step=…, points=… or p=….'
        key = om.group(1).lower()
        key = {"preview": "p", "point": "points", "n": "points"}.get(key, key)
        if key not in ("step", "points", "p"):
            return None, f'Unknown range option "{om.group(1)}".\nUse step=…, points=… or p=….'
        if key in opts:
            return None, f'The option "{key}" is given twice.'
        opts[key] = om.group(2)
    if "step" in opts and "points" in opts:
        return None, "Choose one sampling method.\nSpecify either step or points, not both."
    if lo > hi:
        return None, f"The lower bound of {name} exceeds its upper bound."
    step = points = preview = None
    try:
        if "step" in opts:
            step = float(opts["step"])
            if not math.isfinite(step) or step <= 0:
                return None, f"The step of {name} must be greater than 0."
        if "points" in opts:
            pv = float(opts["points"])
            if pv != int(pv) or pv < 1:
                return None, f"The points of {name} must be a whole number of at least 2."
            points = int(pv)
            if points < 2 and hi > lo:
                return None, f"The points of {name} must be at least 2 (both endpoints are included)."
        if "p" in opts:
            preview = float(opts["p"])
    except ValueError:
        return None, f"A range option of {name} is not a number."
    if step is None and points is None:
        if hi > lo:
            return None, f"Choose a sampling method for {name}.\nSpecify step or points."
        points = 1
    if preview is not None and not (lo <= preview <= hi):
        return None, f"The preview value of {name} lies outside {lo:g} … {hi:g}."
    rng = VariableRange(name, lo, hi, step, points, preview)
    try:
        rng.values()
    except RangeError as exc:
        return None, str(exc)
    return rng, None


def parse_document(text: str, datasets=None) -> Document:
    """Parse every block (never raises; see the module docstring)."""
    blocks: list[Block] = []
    for i, (_start, lines) in enumerate(split_document(text)):
        b = Block(i, lines)
        try:
            b.expression = parse_expression(lines[0], datasets)
        except ExpressionError as exc:
            b.errors.append(formula_message(exc))
        attempted: set[str] = set()                 # variables whose declaration failed (reported once)
        for line in lines[1:]:
            rng, err = parse_declaration(line)
            if err:
                b.errors.append(err)
                m = DECL.match(line)
                if m:
                    attempted.add(m.group(2))
                continue
            if rng.name in b.ranges:
                b.errors.append(f'The variable "{rng.name}" is declared twice.')
                continue
            b.ranges[rng.name] = rng
        if b.expression is not None:
            used = list(b.expression.variables)
            for v in used:
                if v not in b.ranges and v not in attempted:
                    b.errors.append(f'The variable "{v}" has no range.\nAdd a line such as 0 <= {v} <= 1, step=0.1.')
            for v in b.ranges:
                if v not in used:
                    b.errors.append(f'The variable "{v}" is not used in the expression.')
        blocks.append(b)
    return Document(text, blocks)


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


__all__ = ["Block", "Document", "parse_document", "parse_declaration", "split_document", "summary",
           "formula_message"]
