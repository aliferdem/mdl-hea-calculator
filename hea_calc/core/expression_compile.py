"""Compiled evaluation of parsed expressions (no Qt) - a faster, bit-identical stand-in for
:func:`.expression.evaluate_positive`.

The tree evaluator (:meth:`.expression.Expression.evaluate`) walks AST objects and dispatches a Python method per
node for every combination; for a three-variable batch that is ~4.7 µs of 5 µs per combination, paid at Parse (the
count) and again in the duplicate plan during Calculate.  :func:`compile_positive` turns one expression into one
generated Python function that performs **the same floating-point operations in the same order**:

* every arithmetic node keeps its parenthesisation (``BinOp`` left/right, ``Neg``, ``^`` as ``**``), so the IEEE
  results are identical;
* element amounts accumulate in the same dictionary insertion order (``out.get(el, 0.0) + factor * amt``) with
  ``factor = 1.0``, and a group adds ``factor * amt * v / total`` in its own first-appearance order - so
  ``sum(inner.values())`` adds the same numbers in the same order;
* the same checks reject a combination: a non-finite amount, an amount below ``-1e-12``, a group with a zero total
  and a non-zero amount, division by zero - each of which the tree evaluator raises as ``ExpressionError`` and
  :func:`evaluate_positive` turns into ``None``; any other exception (a complex power of a negative number) still
  propagates, as before;
* the result filter is the same: amounts above ``1e-12``, at least two elements.

``tests/test_stabilization.py`` compares the two evaluators for equality (``==`` on every float) over random and
edge-case variable values.  The tree evaluator stays the reference implementation.
"""

from __future__ import annotations

import math

from .expression import BinOp, ElementItem, ExpressionError, GroupItem, Neg, Num, Var

_OPS = {"+": "+", "-": "-", "*": "*", "^": "**"}


class _Skip(Exception):
    pass


def _div(a, b):
    if b == 0:
        raise _Skip()
    return a / b


def _arith(node) -> str:
    if isinstance(node, Num):
        return repr(float(node.value))
    if isinstance(node, Var):
        return f"env[{node.name!r}]"
    if isinstance(node, Neg):
        return f"(-{_arith(node.operand)})"
    if isinstance(node, BinOp):
        left, right = _arith(node.left), _arith(node.right)
        if node.op == "/":
            return f"_div({left}, {right})"
        if node.op not in _OPS:
            raise ValueError(node.op)
        return f"({left} {_OPS[node.op]} {right})"
    raise TypeError(type(node))


def _items(lines: list[str], items, out: str, indent: str, counter: list[int]) -> None:
    """Code accumulating ``items`` into the dict named ``out`` (the tree evaluator's ``walk`` with factor 1.0)."""
    for it in items:
        counter[0] += 1
        a = f"a{counter[0]}"
        lines.append(f"{indent}{a} = float({_arith(it.amount)})")
        lines.append(f"{indent}if not _isfinite({a}) or {a} < -1e-12: raise _Skip()")
        lines.append(f"{indent}{a} = max({a}, 0.0)")
        if isinstance(it, ElementItem):
            lines.append(f"{indent}{out}[{it.symbol!r}] = {out}.get({it.symbol!r}, 0.0) + 1.0 * {a}")
        elif isinstance(it, GroupItem):
            inner = f"g{counter[0]}"
            total = f"t{counter[0]}"
            lines.append(f"{indent}{inner} = {{}}")
            _items(lines, it.items, inner, indent, counter)
            lines.append(f"{indent}{total} = sum({inner}.values())")
            lines.append(f"{indent}if {total} <= 0:")
            lines.append(f"{indent}    if {a} != 0: raise _Skip()")
            lines.append(f"{indent}else:")
            lines.append(f"{indent}    for _el, _v in {inner}.items():")
            lines.append(f"{indent}        {out}[_el] = {out}.get(_el, 0.0) + 1.0 * {a} * _v / {total}")
        else:
            raise TypeError(type(it))


def compile_positive(expression):
    """``f(env) -> {element: amount} | None`` equivalent to ``evaluate_positive(expression, env)``."""
    lines = ["def _positive(env):", "    try:"]
    body: list[str] = ["out = {}"]
    _items(body, expression.items, "out", "", [0])
    lines += ["        " + ln for ln in body]
    lines += ["    except (_Skip, KeyError):",
              "        return None",
              "    positive = {el: v for el, v in out.items() if v > 1e-12}",
              "    return positive if len(positive) >= 2 else None"]
    ns = {"_Skip": _Skip, "_div": _div, "_isfinite": math.isfinite}
    exec("\n".join(lines), ns)                                  # noqa: S102 - code generated from the parse tree
    fn = ns["_positive"]
    fn.source = "\n".join(lines)
    return fn


def positive_function(expression):
    """The compiled function of ``expression``, cached on the instance (never pickled - see Expression)."""
    fn = expression.__dict__.get("_positive_fn")
    if fn is None:
        fn = compile_positive(expression)
        expression.__dict__["_positive_fn"] = fn
    return fn


__all__ = ["compile_positive", "positive_function", "ExpressionError"]
