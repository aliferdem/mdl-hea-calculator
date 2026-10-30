"""Expression Mode: composition formulas with variable amounts.

Examples::

    (FeCoNi)1-xAlx          Al_x(CoCrFeNi)          Fe{2-x}Co{x}Ni
    (Fe1.6CoCr0.4Mn)1-yAly  CoCrFeNiTi{0.1*k}       (FeCoNi)100-cAlc

Grammar
-------
* Element symbols are matched greedily against the periodic table (``Ba`` is barium). A variable
  that would merge with the preceding symbol must be braced: ``B{a}``.
* Variables: lowercase identifiers (``x``, ``y1``, ``al_frac``).
* An amount follows an element or a group: a plain number, a variable, a simple chain such as
  ``1-x`` or ``100-2x``, or any arithmetic expression in ``{…}`` / ``_(…)``. Operators: ``+ - * / ^``.
* A parenthesised group is normalised to unit total and multiplied by its amount (HEA convention:
  ``(FeCoNi)90Al10`` = 30/30/30/10 at.%).

The parser only builds compositions.  No scientific calculation happens here — generated
compositions are passed to :class:`hea_calc.core.engine.Engine`.
"""

from __future__ import annotations

import bisect
import itertools
import math
import re
from dataclasses import dataclass, field

from .data import Datasets, default_datasets
from .generation import RangeError, _decimals

# Variable combinations per batch.  Duplicate removal keeps ~98 bytes per kept composition in one
# worker and walks ~70 000 combinations/s (measured): 5 M stays under ~0.5 GB / ~75 s, faster than
# the calculation it feeds (~19 000 alloys/s).  Formerly 200 000 (the in-memory result store).
MAX_COMBINATIONS = 5_000_000


class ExpressionError(ValueError):
    """A formula the parser cannot read.  ``pos`` is the 0-based index of the problem in the expression with its
    spaces removed (the parser reads it that way) and ``length`` the number of characters concerned (0 = the
    problem is *after* the text, e.g. a missing ``)``); both are ``None`` for errors raised elsewhere."""

    def __init__(self, msg: str = "", pos: int | None = None, length: int | None = None):
        super().__init__(msg)
        self.pos = pos
        self.length = length


# ---------------------------------------------------------------------- arithmetic AST
@dataclass
class Num:
    value: float

    def eval(self, env):
        return self.value

    def vars(self):
        return set()

    def text(self):
        return f"{self.value:g}"


@dataclass
class Var:
    name: str

    def eval(self, env):
        if self.name not in env:
            raise ExpressionError(f"No value for variable '{self.name}'.")
        return env[self.name]

    def vars(self):
        return {self.name}

    def text(self):
        return self.name


@dataclass
class BinOp:
    op: str
    left: object
    right: object

    def eval(self, env):
        a, b = self.left.eval(env), self.right.eval(env)
        if self.op == "+":
            return a + b
        if self.op == "-":
            return a - b
        if self.op == "*":
            return a * b
        if self.op == "/":
            if b == 0:
                raise ExpressionError("Division by zero.")
            return a / b
        if self.op == "^":
            return a ** b
        raise ExpressionError(f"Unknown operator {self.op}.")

    def vars(self):
        return self.left.vars() | self.right.vars()

    def text(self):
        return f"({self.left.text()}{self.op}{self.right.text()})"


@dataclass
class Neg:
    operand: object

    def eval(self, env):
        return -self.operand.eval(env)

    def vars(self):
        return self.operand.vars()

    def text(self):
        return f"-{self.operand.text()}"


# ---------------------------------------------------------------------- formula AST
@dataclass
class ElementItem:
    symbol: str
    amount: object  # arithmetic node


@dataclass
class GroupItem:
    items: list
    amount: object


@dataclass
class Expression:
    source: str
    items: list
    variables: list[str] = field(default_factory=list)

    def __getstate__(self):
        # the compiled evaluator (expression_compile.positive_function) is a cache: rebuilt where it is used
        state = dict(self.__dict__)
        state.pop("_positive_fn", None)
        return state

    def evaluate(self, env: dict[str, float]) -> dict[str, float]:
        """Return element amounts for the given variable values (zero amounts kept)."""
        out: dict[str, float] = {}

        def walk(items, factor):
            for it in items:
                amt = float(it.amount.eval(env))
                if not math.isfinite(amt):
                    raise ExpressionError("Non-finite amount.")
                if amt < -1e-12:
                    raise ExpressionError("Negative amount.")
                amt = max(amt, 0.0)
                if isinstance(it, ElementItem):
                    out[it.symbol] = out.get(it.symbol, 0.0) + factor * amt
                else:
                    inner = Expression(self.source, it.items).evaluate(env)
                    total = sum(inner.values())
                    if total <= 0:
                        if amt == 0:
                            continue
                        raise ExpressionError("Group with zero total amount.")
                    for el, v in inner.items():
                        out[el] = out.get(el, 0.0) + factor * amt * v / total
            return out

        return walk(self.items, 1.0)

    def name(self, env: dict[str, float], digits: int = 3) -> str:
        """Alloy name with the variable values substituted, preserving groups."""

        def fmt(v: float) -> str:
            if abs(v - 1.0) < 0.5 * 10 ** (-digits):
                return ""
            s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
            return s

        def render(items) -> str:
            parts = []
            for it in items:
                amt = float(it.amount.eval(env))
                if amt <= 1e-12:
                    continue
                if isinstance(it, ElementItem):
                    parts.append(f"{it.symbol}{fmt(amt)}")
                else:
                    inner = render(it.items)
                    if inner:
                        parts.append(f"({inner}){fmt(amt)}")
            return "".join(parts)

        # A lone unit-amount group is shown without redundant parentheses: (FeCoNi) -> FeCoNi
        visible = [it for it in self.items if float(it.amount.eval(env)) > 1e-12]
        if len(visible) == 1 and isinstance(visible[0], GroupItem) and fmt(float(visible[0].amount.eval(env))) == "":
            return render(visible[0].items)
        return render(self.items)


class _Parser:
    def __init__(self, text: str, datasets: Datasets):
        self.s = text.replace(" ", "")
        self.i = 0
        self.data = datasets

    # -- helpers
    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def error(self, msg: str, pos: int | None = None, length: int = 1):
        i = self.i if pos is None else pos
        if i >= len(self.s):
            length = 0                      # the problem is past the end: something is missing
        raise ExpressionError(f"{msg} (at position {i + 1})", i, length)

    def element(self) -> str | None:
        s, i = self.s, self.i
        if i < len(s) and s[i].isupper():
            two = s[i:i + 2]
            if len(two) == 2 and two[1].islower() and self.data.is_element(two):
                self.i += 2
                return two
            if self.data.is_element(s[i]):
                self.i += 1
                return s[i]
            cand = two if len(two) == 2 and two[1].islower() else s[i]
            self.error(f"Unknown element '{cand}'", i, len(cand))
        return None

    # -- formula level
    def formula(self, depth=0) -> list:
        items = []
        while self.i < len(self.s):
            ch = self.peek()
            if ch == "(" or ch == "[":
                self.i += 1
                inner = self.formula(depth + 1)
                if self.peek() not in (")", "]"):
                    self.error("Missing ')'")
                self.i += 1
                if not inner:
                    self.error("Empty group", self.i - 2, 2)
                items.append(GroupItem(inner, self.amount()))
            elif ch in (")", "]"):
                if depth == 0:
                    self.error("Unbalanced ')'")
                return items
            elif ch.isupper():
                sym = self.element()
                items.append(ElementItem(sym, self.amount()))
            else:
                self.error(f"Unexpected '{ch}'")
        if depth > 0:
            self.error("Missing ')'")
        return items

    def amount(self):
        ch = self.peek()
        if ch == "{":
            self.i += 1
            node = self.expr()
            if self.peek() != "}":
                self.error("Missing '}'")
            self.i += 1
            return node
        if ch == "_":
            self.i += 1
            if self.peek() == "{" or self.peek() == "(":
                close = "}" if self.peek() == "{" else ")"
                self.i += 1
                node = self.expr()
                if self.peek() != close:
                    self.error(f"Missing '{close}'")
                self.i += 1
                return node
            node = self.simple_term()
            if node is None:
                self.error("Expected amount after '_'")
            return node
        node = self.simple_chain()
        return node if node is not None else Num(1.0)

    # simple (unbraced) amounts: term ((+|-|*|/) term)* ; implicit multiplication "2x"
    def simple_term(self):
        m = re.compile(r"\d+(?:\.\d*)?|\.\d+").match(self.s, self.i)
        node = None
        if m:
            self.i = m.end()
            node = Num(float(m.group()))
        m2 = re.compile(r"[a-z][a-z0-9_]*").match(self.s, self.i)
        if m2:
            self.i = m2.end()
            var = Var(m2.group())
            node = var if node is None else BinOp("*", node, var)
        return node

    def simple_chain(self):
        node = self.simple_term()
        if node is None:
            return None
        while self.peek() in ("+", "-", "*", "/"):
            op = self.s[self.i]
            save = self.i
            self.i += 1
            rhs = self.simple_term()
            if rhs is None:
                self.i = save
                break
            node = BinOp(op, node, rhs)
        return _precedence_fix(node)

    # full arithmetic inside braces
    def expr(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.s[self.i]
            self.i += 1
            node = BinOp(op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while True:
            ch = self.peek()
            if ch in ("*", "/"):
                self.i += 1
                node = BinOp(ch, node, self.factor())
            elif ch and (ch.isalpha() and ch.islower() or ch == "("):
                node = BinOp("*", node, self.factor())  # implicit multiplication
            else:
                return node

    def factor(self):
        node = self.unary()
        if self.peek() == "^":
            self.i += 1
            node = BinOp("^", node, self.factor())
        return node

    def unary(self):
        if self.peek() == "-":
            self.i += 1
            return Neg(self.unary())
        if self.peek() == "+":
            self.i += 1
            return self.unary()
        if self.peek() == "(":
            self.i += 1
            node = self.expr()
            if self.peek() != ")":
                self.error("Missing ')'")
            self.i += 1
            return node
        m = re.compile(r"\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|\.\d+").match(self.s, self.i)
        if m:
            self.i = m.end()
            return Num(float(m.group()))
        m = re.compile(r"[a-z][a-z0-9_]*").match(self.s, self.i)
        if m:
            self.i = m.end()
            return Var(m.group())
        self.error("Expected a number or variable")


def _precedence_fix(node):
    """Re-associate a left-to-right simple chain so that * and / bind tighter than + and -."""
    flat = []

    def collect(n):
        if isinstance(n, BinOp) and n.op in "+-*/" and not getattr(n, "_grouped", False):
            collect(n.left)
            flat.append(n.op)
            flat.append(n.right)
        else:
            flat.append(n)

    collect(node)
    # flat = [t0, op, t1, op, t2 ...]
    terms = [flat[0]]
    ops = []
    for k in range(1, len(flat), 2):
        op, t = flat[k], flat[k + 1]
        if op in "*/":
            terms[-1] = BinOp(op, terms[-1], t)
        else:
            ops.append(op)
            terms.append(t)
    out = terms[0]
    for op, t in zip(ops, terms[1:]):
        out = BinOp(op, out, t)
    return out


def parse_expression(text: str, datasets: Datasets | None = None) -> Expression:
    data = datasets or default_datasets()
    if not text or not text.strip():
        raise ExpressionError("Enter an expression, e.g. (FeCoNi)1-xAlx.")
    p = _Parser(text.strip(), data)
    items = p.formula()
    if not items:
        raise ExpressionError("No elements found.")
    names: list[str] = []

    def collect(its):
        for it in its:
            for v in sorted(it.amount.vars()):
                if v not in names:
                    names.append(v)
            if isinstance(it, GroupItem):
                collect(it.items)

    collect(items)
    return Expression(text.strip(), items, names)


@dataclass(frozen=True)
class VariableRange:
    """Values of one variable: ``minimum`` to ``maximum`` either in steps of ``step`` or as ``points`` evenly
    spaced values that include both endpoints (the inline syntax ``0 <= x <= 1, step=0.1`` / ``points=11``).
    ``preview`` is the value used for a single-block composition preview (default: ``minimum``).

    Bounds: ``min_inclusive`` / ``max_inclusive`` are ``False`` for a strict comparison (``0 < x < 1``).  The
    discretisation is always defined on the closed interval - ``step`` from ``minimum``, or ``points`` evenly
    spaced values including both ends - and a strict bound then removes that endpoint from the grid, so
    ``0 < x < 1, step=0.1`` is 0.1 … 0.9 (9 values) and ``0 < x <= 1, points=11`` is 0.1 … 1 (10 values).  An
    endpoint is removed when the grid value equals the bound within 1e-12 (the grid itself is exact decimal)."""
    name: str
    minimum: float
    maximum: float
    step: float | None = None
    points: int | None = None
    preview: float | None = None
    min_inclusive: bool = True
    max_inclusive: bool = True

    def grid(self) -> list[float]:
        """The closed-interval grid (both endpoints as discretised), before the strict bounds apply."""
        for label, v in (("Min", self.minimum), ("Max", self.maximum)):
            if v is None or not math.isfinite(v):
                raise RangeError(f"{self.name}: {label} is missing or invalid.")
        if self.maximum < self.minimum:
            raise RangeError(f"{self.name}: Max must be ≥ Min.")
        if self.points is not None:
            n = int(self.points)
            if n < 1 or (n < 2 and self.maximum > self.minimum):
                raise RangeError(f"{self.name}: points must be at least 2.")
            if n == 1 or self.maximum == self.minimum:
                return [self.minimum]
            d = _decimals(self.minimum, self.maximum) + len(str(n - 1)) + 2
            span = self.maximum - self.minimum
            return [round(self.minimum + span * i / (n - 1), d) for i in range(n)]
        if self.step is None or not math.isfinite(self.step):
            if self.maximum == self.minimum:
                return [self.minimum]
            raise RangeError(f"{self.name}: Step is missing or invalid.")
        if self.maximum == self.minimum:
            return [self.minimum]
        if self.step <= 0:
            raise RangeError(f"{self.name}: Step must be > 0.")
        scale = 10 ** _decimals(self.minimum, self.maximum, self.step)
        lo, hi, st = round(self.minimum * scale), round(self.maximum * scale), round(self.step * scale)
        if st <= 0:
            raise RangeError(f"{self.name}: Step is too small.")
        return [v / scale for v in range(lo, hi + 1, st)]

    def values(self) -> list[float]:
        vals = self.grid()
        if self.min_inclusive and self.max_inclusive:
            return vals

        def at(v: float, bound: float) -> bool:
            return abs(v - bound) <= 1e-12 * max(1.0, abs(bound))
        return [v for v in vals if not ((not self.min_inclusive and at(v, self.minimum))
                                        or (not self.max_inclusive and at(v, self.maximum)))]

    def contains(self, v: float) -> bool:
        """``v`` satisfies both comparisons of the declaration."""
        lo_ok = v >= self.minimum if self.min_inclusive else v > self.minimum
        hi_ok = v <= self.maximum if self.max_inclusive else v < self.maximum
        return lo_ok and hi_ok

    def bounds_text(self) -> str:
        """``0 ≤ x < 1`` - the declaration's comparisons as written (inclusive ≤, strict <)."""
        lo = "≤" if self.min_inclusive else "<"
        hi = "≤" if self.max_inclusive else "<"
        return f"{self.minimum:g} {lo} {self.name} {hi} {self.maximum:g}"

    def to_meta(self) -> dict:
        """JSON-safe description kept with a run (``range_from_meta`` reads it back)."""
        return {"min": self.minimum, "max": self.maximum, "step": self.step, "points": self.points,
                "min_inclusive": self.min_inclusive, "max_inclusive": self.max_inclusive}


def range_from_meta(name: str, meta) -> VariableRange:
    """A :class:`VariableRange` from run metadata: the current dict form, or the earlier list form
    ``[min, max, step]`` / ``[min, max, step, points]`` of stored runs (always inclusive)."""
    if isinstance(meta, dict):
        return VariableRange(name, float(meta["min"]), float(meta["max"]), meta.get("step"), meta.get("points"),
                             None, bool(meta.get("min_inclusive", True)), bool(meta.get("max_inclusive", True)))
    lo, hi, step = meta[0], meta[1], meta[2] if len(meta) > 2 else None
    points = meta[3] if len(meta) > 3 else None
    return VariableRange(name, float(lo), float(hi), step, points)


@dataclass
class ExpressionBatch:
    compositions: list[dict[str, float]]
    names: list[str]
    variables: list[dict[str, float]]
    skipped: int  # combinations rejected (negative amounts, fewer than two elements, …)
    duplicates: int
    blocks: list[int] = field(default_factory=list)   # index of the expression block of each composition
    duplicates_by_block: dict = field(default_factory=dict)   # block -> duplicates it generated (kept earlier)


def composition_key(positive: dict[str, float]) -> tuple:
    """Identity of a composition for duplicate removal: normalised fractions rounded to 1e-10."""
    tot = sum(positive.values())
    return tuple(sorted((el, round(v / tot, 10)) for el, v in positive.items()))


def evaluate_positive(expression: "Expression", env: dict[str, float]) -> dict[str, float] | None:
    """Amounts > 1e-12 for ``env``; ``None`` when the combination is skipped (invalid amounts or
    fewer than two elements) - the rule of :func:`generate`."""
    try:
        amounts = expression.evaluate(env)
    except ExpressionError:
        return None
    positive = {el: v for el, v in amounts.items() if v > 1e-12}
    return positive if len(positive) >= 2 else None


def generate(expression: Expression, ranges: dict[str, VariableRange], limit: int = MAX_COMBINATIONS,
             cancelled=None) -> ExpressionBatch:
    missing = [v for v in expression.variables if v not in ranges]
    if missing:
        raise RangeError("Set Min / Max / Step for: " + ", ".join(missing))
    names = expression.variables
    value_lists = [ranges[n].values() for n in names]
    total = math.prod(len(v) for v in value_lists) if value_lists else 1
    if total > limit:
        raise RangeError(f"{total:,} combinations exceed the limit of {limit:,}; increase the steps.")
    comps, labels, envs = [], [], []
    seen = set()
    skipped = dups = 0
    for i, combo in enumerate(itertools.product(*value_lists) if value_lists else [()]):
        if cancelled is not None and not i & 0x3FF and cancelled():
            raise GenerationCancelled()
        env = dict(zip(names, combo))
        positive = evaluate_positive(expression, env)
        if positive is None:
            skipped += 1
            continue
        key = composition_key(positive)
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        comps.append(positive)
        labels.append(expression.name(env))
        envs.append(env)
    return ExpressionBatch(comps, labels, envs, skipped, dups)


# ---------------------------------------------------------------------- multiple expression blocks
def split_blocks(text: str) -> list[str]:
    """Blocks are separated by one or more blank lines; line breaks inside a block are ignored."""
    blocks, cur = [], []
    for line in (text or "").splitlines():
        if line.strip():
            cur.append(line.strip())
        elif cur:
            blocks.append("".join(cur))
            cur = []
    if cur:
        blocks.append("".join(cur))
    return blocks


def parse_blocks(text: str, datasets: Datasets | None = None) -> list[Expression]:
    blocks = split_blocks(text)
    if not blocks:
        raise ExpressionError("Enter an expression, e.g. (FeCoNi)1-xAlx.")
    out = []
    for i, b in enumerate(blocks, start=1):
        try:
            out.append(parse_expression(b, datasets))
        except ExpressionError as exc:
            raise ExpressionError(f"Block {i}: {exc}" if len(blocks) > 1 else str(exc)) from None
    return out


def block_variables(expressions: list[Expression]) -> list[str]:
    names: list[str] = []
    for ex in expressions:
        for v in ex.variables:
            if v not in names:
                names.append(v)
    return names


class GenerationCancelled(Exception):
    """A superseded background generation (pre-flight count) stopped early."""


def ranges_of_block(ranges, b: int) -> dict[str, VariableRange]:
    """A range spec is one dict shared by every block, or a list with one dict per block (the inline syntax
    declares ranges per block, so ``x`` may have different ranges in different blocks)."""
    if isinstance(ranges, (list, tuple)):
        return ranges[b] if b < len(ranges) else {}
    return ranges


def count_combinations(expressions: list[Expression], ranges) -> int:
    """Variable combinations the blocks evaluate (before skips and duplicates) - a cheap upper bound."""
    total = 0
    for b, ex in enumerate(expressions):
        r = ranges_of_block(ranges, b)
        missing = [v for v in ex.variables if v not in r]
        if missing:
            raise RangeError("Set Min / Max / Step for: " + ", ".join(missing))
        total += math.prod(len(r[v].values()) for v in ex.variables) if ex.variables else 1
    return total


def generate_blocks(expressions: list[Expression], ranges,
                    limit: int = MAX_COMBINATIONS, cancelled=None) -> ExpressionBatch:
    """Generate every block with the shared variable ranges; duplicates across blocks are removed."""
    comps, names, envs, blocks = [], [], [], []
    skipped = dups = 0
    by_block: dict[int, int] = {}
    seen = set()
    for b, ex in enumerate(expressions):
        r = ranges_of_block(ranges, b)
        sub = {k: v for k, v in r.items() if k in ex.variables}
        batch = generate(ex, sub, limit, cancelled)
        skipped += batch.skipped
        dups += batch.duplicates
        if batch.duplicates:
            by_block[b] = by_block.get(b, 0) + batch.duplicates
        for c, n, e in zip(batch.compositions, batch.names, batch.variables):
            key = composition_key(c)
            if key in seen:
                dups += 1
                by_block[b] = by_block.get(b, 0) + 1
                continue
            seen.add(key)
            comps.append(c)
            names.append(n)
            envs.append(e)
            blocks.append(b)
            if len(comps) > limit:
                raise RangeError(f"More than {limit:,} compositions; increase the steps.")
    return ExpressionBatch(comps, names, envs, skipped, dups, blocks, by_block)


def expression_elements(expressions: list[Expression]) -> list[str]:
    """Element symbols of the blocks in order of first appearance."""
    out: list[str] = []

    def walk(items):
        for it in items:
            if isinstance(it, ElementItem):
                if it.symbol not in out:
                    out.append(it.symbol)
            else:
                walk(it.items)
    for ex in expressions:
        walk(ex.items)
    return out


class ExpressionSpace:
    """Random access to the combinations of expression blocks.

    Global combination index ``g``: blocks in order, inside a block the ``itertools.product`` order
    of the block's variables (the order :func:`generate_blocks` walks).  Used by calculation workers
    to evaluate any slice without generating what precedes it, and by the duplicate plan.
    """

    def __init__(self, expressions: list[Expression], ranges):
        self.expressions = list(expressions)
        self.value_lists: list[list[list[float]]] = []
        self.sizes: list[int] = []
        for b, ex in enumerate(self.expressions):
            r = ranges_of_block(ranges, b)
            missing = [v for v in ex.variables if v not in r]
            if missing:
                raise RangeError("Set Min / Max / Step for: " + ", ".join(missing))
            vl = [r[v].values() for v in ex.variables]
            self.value_lists.append(vl)
            self.sizes.append(math.prod(len(v) for v in vl) if vl else 1)
        self.offsets = list(itertools.accumulate([0] + self.sizes[:-1]))
        self.total = sum(self.sizes)

    def locate(self, g: int) -> tuple[int, dict[str, float]]:
        """(block index, variable values) of combination ``g``."""
        import bisect
        b = bisect.bisect_right(self.offsets, g) - 1
        i = g - self.offsets[b]
        vl = self.value_lists[b]
        vals = [0.0] * len(vl)
        for j in range(len(vl) - 1, -1, -1):      # product order: the last variable varies fastest
            i, d = divmod(i, len(vl[j]))
            vals[j] = vl[j][d]
        return b, dict(zip(self.expressions[b].variables, vals))

    def evaluate(self, g: int) -> tuple[int, dict[str, float], dict[str, float] | None]:
        b, env = self.locate(g)
        return b, env, self.positive[b](env)

    @property
    def positive(self):
        """The compiled evaluator of every block (bit-identical to :func:`evaluate_positive`)."""
        fns = self.__dict__.get("_positive")
        if fns is None:
            from .expression_compile import positive_function
            fns = self.__dict__["_positive"] = [positive_function(ex) for ex in self.expressions]
        return fns

    def iterate(self, start: int = 0, stop: int | None = None):
        """``(g, block, env, positive)`` for combinations ``start .. stop-1`` in index order - the order
        :meth:`locate` defines, walked with ``itertools.product`` instead of one ``divmod`` chain per index."""
        stop = self.total if stop is None else min(stop, self.total)
        if start >= stop:
            return
        b = bisect.bisect_right(self.offsets, start) - 1
        g = start
        while g < stop and b < len(self.expressions):
            vl = self.value_lists[b]
            names = self.expressions[b].variables
            fn = self.positive[b]
            first = g - self.offsets[b]
            n = min(self.sizes[b], stop - self.offsets[b])
            combos = itertools.product(*vl) if vl else iter([()])
            if first:
                combos = itertools.islice(combos, first, None)
            for _i in range(first, n):
                env = dict(zip(names, next(combos)))
                yield g, b, env, fn(env)
                g += 1
            b += 1

    def name(self, block: int, env: dict[str, float]) -> str:
        return self.expressions[block].name(env)


def count_blocks(expressions: list[Expression], ranges,
                 cancelled=None) -> tuple[int, int, int]:
    """(valid, skipped, duplicates) of :func:`generate_blocks` without building its lists.

    Duplicate detection keeps a 16-byte digest per distinct composition (~0.1 KiB each instead of a
    tuple of tuples), so a multi-million-combination count stays within a few hundred MiB."""
    import hashlib
    space = ExpressionSpace(expressions, ranges)
    seen: set[bytes] = set()
    valid = skipped = dups = 0
    for g, _b, _env, positive in space.iterate():
        if cancelled is not None and not g & 0x3FF and cancelled():
            raise GenerationCancelled()
        if positive is None:
            skipped += 1
            continue
        key = hashlib.blake2b(repr(composition_key(positive)).encode(), digest_size=16).digest()
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        valid += 1
    return valid, skipped, dups


def count_blocks_detail(expressions: list[Expression], ranges, cancelled=None) -> dict:
    """Per-block (valid, skipped, duplicates) plus the totals - :func:`count_blocks` with the block breakdown the
    inline expression editor needs ("Block 3: no valid compositions").  A duplicate is counted in the block that
    produced it again (it is kept in the first one)."""
    import hashlib
    space = ExpressionSpace(expressions, ranges)
    seen: set[bytes] = set()
    per = [[0, 0, 0] for _ in space.expressions]
    for g, b, _env, positive in space.iterate():
        if cancelled is not None and not g & 0x3FF and cancelled():
            raise GenerationCancelled()
        if positive is None:
            per[b][1] += 1
            continue
        key = hashlib.blake2b(repr(composition_key(positive)).encode(), digest_size=16).digest()
        if key in seen:
            per[b][2] += 1
            continue
        seen.add(key)
        per[b][0] += 1
    return {"blocks": [tuple(x) for x in per], "valid": sum(x[0] for x in per),
            "skipped": sum(x[1] for x in per), "duplicates": sum(x[2] for x in per), "combinations": space.total}
