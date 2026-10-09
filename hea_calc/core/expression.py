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
    pass


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

    def error(self, msg: str):
        raise ExpressionError(f"{msg} (at position {self.i + 1})")

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
            self.error(f"Unknown element '{two if len(two) == 2 and two[1].islower() else s[i]}'")
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
                    self.error("Empty group")
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
    name: str
    minimum: float
    maximum: float
    step: float

    def values(self) -> list[float]:
        for label, v in (("Min", self.minimum), ("Max", self.maximum), ("Step", self.step)):
            if v is None or not math.isfinite(v):
                raise RangeError(f"{self.name}: {label} is missing or invalid.")
        if self.maximum < self.minimum:
            raise RangeError(f"{self.name}: Max must be ≥ Min.")
        if self.maximum == self.minimum:
            return [self.minimum]
        if self.step <= 0:
            raise RangeError(f"{self.name}: Step must be > 0.")
        scale = 10 ** _decimals(self.minimum, self.maximum, self.step)
        lo, hi, st = round(self.minimum * scale), round(self.maximum * scale), round(self.step * scale)
        if st <= 0:
            raise RangeError(f"{self.name}: Step is too small.")
        return [v / scale for v in range(lo, hi + 1, st)]


@dataclass
class ExpressionBatch:
    compositions: list[dict[str, float]]
    names: list[str]
    variables: list[dict[str, float]]
    skipped: int  # combinations rejected (negative amounts, fewer than two elements, …)
    duplicates: int
    blocks: list[int] = field(default_factory=list)   # index of the expression block of each composition


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


def count_combinations(expressions: list[Expression], ranges: dict[str, VariableRange]) -> int:
    """Variable combinations the blocks evaluate (before skips and duplicates) - a cheap upper bound."""
    total = 0
    for ex in expressions:
        missing = [v for v in ex.variables if v not in ranges]
        if missing:
            raise RangeError("Set Min / Max / Step for: " + ", ".join(missing))
        total += math.prod(len(ranges[v].values()) for v in ex.variables) if ex.variables else 1
    return total


def generate_blocks(expressions: list[Expression], ranges: dict[str, VariableRange],
                    limit: int = MAX_COMBINATIONS, cancelled=None) -> ExpressionBatch:
    """Generate every block with the shared variable ranges; duplicates across blocks are removed."""
    comps, names, envs, blocks = [], [], [], []
    skipped = dups = 0
    seen = set()
    for b, ex in enumerate(expressions):
        sub = {k: v for k, v in ranges.items() if k in ex.variables}
        batch = generate(ex, sub, limit, cancelled)
        skipped += batch.skipped
        dups += batch.duplicates
        for c, n, e in zip(batch.compositions, batch.names, batch.variables):
            key = composition_key(c)
            if key in seen:
                dups += 1
                continue
            seen.add(key)
            comps.append(c)
            names.append(n)
            envs.append(e)
            blocks.append(b)
            if len(comps) > limit:
                raise RangeError(f"More than {limit:,} compositions; increase the steps.")
    return ExpressionBatch(comps, names, envs, skipped, dups, blocks)


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

    def __init__(self, expressions: list[Expression], ranges: dict[str, VariableRange]):
        self.expressions = list(expressions)
        self.value_lists: list[list[list[float]]] = []
        self.sizes: list[int] = []
        for ex in self.expressions:
            missing = [v for v in ex.variables if v not in ranges]
            if missing:
                raise RangeError("Set Min / Max / Step for: " + ", ".join(missing))
            vl = [ranges[v].values() for v in ex.variables]
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
        return b, env, evaluate_positive(self.expressions[b], env)

    def name(self, block: int, env: dict[str, float]) -> str:
        return self.expressions[block].name(env)


def count_blocks(expressions: list[Expression], ranges: dict[str, VariableRange],
                 cancelled=None) -> tuple[int, int, int]:
    """(valid, skipped, duplicates) of :func:`generate_blocks` without building its lists.

    Duplicate detection keeps a 16-byte digest per distinct composition (~0.1 KiB each instead of a
    tuple of tuples), so a multi-million-combination count stays within a few hundred MiB."""
    import hashlib
    space = ExpressionSpace(expressions, ranges)
    seen: set[bytes] = set()
    valid = skipped = dups = 0
    for g in range(space.total):
        if cancelled is not None and not g & 0x3FF and cancelled():
            raise GenerationCancelled()
        _b, _env, positive = space.evaluate(g)
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
