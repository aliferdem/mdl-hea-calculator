"""Composition-sweep (composition space) generation. Produces plain compositions only."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

DEFAULT_LIMIT = 200_000


class RangeError(ValueError):
    pass


@dataclass(frozen=True)
class ElementRange:
    element: str
    minimum: float
    maximum: float
    step: float

    def validate(self) -> None:
        for name, v in (("Min", self.minimum), ("Max", self.maximum), ("Step", self.step)):
            if v is None or not math.isfinite(v):
                raise RangeError(f"{self.element}: {name} is missing or invalid.")
        if self.minimum < 0:
            raise RangeError(f"{self.element}: Min must be ≥ 0.")
        if self.maximum < self.minimum:
            raise RangeError(f"{self.element}: Max must be ≥ Min.")
        if self.step <= 0 and self.maximum > self.minimum:
            raise RangeError(f"{self.element}: Step must be > 0.")


def _decimals(*values: float) -> int:
    d = 0
    for v in values:
        exp = Decimal(repr(float(v))).normalize().as_tuple().exponent
        d = max(d, -exp if isinstance(exp, int) and exp < 0 else 0)
    return min(d, 6)


def grid(r: ElementRange, scale: int) -> list[int]:
    """Integer grid (value × scale) from Min to Max inclusive in steps of Step."""
    lo, hi = round(r.minimum * scale), round(r.maximum * scale)
    if hi == lo or r.step <= 0:
        return [lo]
    st = round(r.step * scale)
    if st <= 0:
        raise RangeError(f"{r.element}: Step is too small.")
    return list(range(lo, hi + 1, st))


def count_sweep(ranges: list[ElementRange], total: float = 100.0, limit: int | None = None) -> int:
    return sum(1 for _ in iter_sweep(ranges, total, limit))


def iter_sweep(ranges: list[ElementRange], total: float = 100.0, limit: int | None = None):
    """Yield every composition (at.% by default) whose values lie on each element's grid and sum to ``total``.

    The last element acts as the balance: its value is ``total`` minus the others and must lie on its
    own grid. Integer arithmetic avoids floating-point drift.
    """
    if len(ranges) < 2:
        raise RangeError("Select at least two elements.")
    for r in ranges:
        r.validate()
    scale = 10 ** _decimals(total, *[v for r in ranges for v in (r.minimum, r.maximum, r.step)])
    target = round(total * scale)
    grids = [grid(r, scale) for r in ranges]
    last = ranges[-1]
    last_lo, last_hi = round(last.minimum * scale), round(last.maximum * scale)
    last_step = round(last.step * scale) if last.step > 0 else 0
    mins = [g[0] for g in grids]
    maxs = [g[-1] for g in grids]
    suffix_min = [sum(mins[i:]) for i in range(len(grids) + 1)]
    suffix_max = [sum(maxs[i:]) for i in range(len(grids) + 1)]
    elements = [r.element for r in ranges]
    produced = 0

    def rec(i: int, acc: int, values: list[int]):
        nonlocal produced
        if limit is not None and produced >= limit:
            return
        if i == len(grids) - 1:
            rest = target - acc
            if rest < last_lo or rest > last_hi:
                return
            if last_step and (rest - last_lo) % last_step:
                return
            if not last_step and rest != last_lo:
                return
            produced += 1
            yield {el: v / scale for el, v in zip(elements, values + [rest])}
            return
        for v in grids[i]:
            remaining = target - acc - v
            if remaining < suffix_min[i + 1]:
                break
            if remaining > suffix_max[i + 1]:
                continue
            yield from rec(i + 1, acc + v, values + [v])

    yield from rec(0, 0, [])


def generate_sweep(ranges: list[ElementRange], total: float = 100.0, limit: int = DEFAULT_LIMIT,
                   min_elements: int = 1) -> list[dict[str, float]]:
    """List of compositions; zero-valued elements are kept (the engine drops them).

    ``min_elements`` skips grid points with fewer non-zero elements (the UI uses 2: a pure element is
    not an alloy).
    """
    out = []
    for comp in iter_sweep(ranges, total, None):
        if sum(1 for v in comp.values() if v > 0) < min_elements:
            continue
        out.append(comp)
        if len(out) > limit:
            raise RangeError(f"More than {limit:,} compositions; increase the step or narrow the ranges.")
    return out


def count_alloys(ranges: list[ElementRange], total: float = 100.0, limit: int | None = None,
                 min_elements: int = 2) -> int:
    n = 0
    for comp in iter_sweep(ranges, total, None):
        if sum(1 for v in comp.values() if v > 0) >= min_elements:
            n += 1
            if limit is not None and n >= limit:
                break
    return n


# ---------------------------------------------------------------------- composition space (Figma sweep design)
@dataclass(frozen=True)
class SweepSpec:
    """One element of a composition space. ``required`` (Lock on) elements are always present;
    optional ones generate systems with and without the element."""

    element: str
    minimum: float
    maximum: float
    step: float
    required: bool = True

    def as_range(self) -> ElementRange:
        return ElementRange(self.element, self.minimum, self.maximum, self.step)


@dataclass
class SpaceSummary:
    selected: int
    required: int
    optional: int
    systems: int
    compositions: int
    truncated: bool = False


def systems(specs: list[SweepSpec], sizes: set[int] | None = None) -> list[tuple[SweepSpec, ...]]:
    """Element systems: all required elements plus every subset of the optional ones (≥ 2 elements),
    filtered by the allowed system sizes."""
    from itertools import combinations
    req = [s for s in specs if s.required]
    opt = [s for s in specs if not s.required]
    out = []
    for k in range(len(opt) + 1):
        for subset in combinations(opt, k):
            chosen = set(id(s) for s in req) | set(id(s) for s in subset)
            system = tuple(s for s in specs if id(s) in chosen)  # keep the user's element order
            if len(system) < 2 or (sizes and len(system) not in sizes):
                continue
            out.append(system)
    return out


def _positive_grid(spec: SweepSpec, scale: int) -> list[int]:
    return [v for v in grid(spec.as_range(), scale) if v > 0]


def iter_space(specs: list[SweepSpec], unit: str = "ratio", sizes: set[int] | None = None,
               total: float = 100.0):
    """Yield compositions of the space.

    ``unit="ratio"``: every element of a system takes each positive value of its grid independently
    (cartesian product); proportional duplicates are removed. ``unit="at"``: as above but only
    combinations summing to ``total`` at.% are valid.
    """
    for s in specs:
        s.as_range().validate()
    vals = [v for s in specs for v in (s.minimum, s.maximum, s.step)] + [total]
    scale = 10 ** _decimals(*vals)
    target = round(total * scale)
    seen: set[tuple] = set()
    from itertools import product
    from math import gcd
    for system in systems(specs, sizes):
        grids = [_positive_grid(s, scale) for s in system]
        if any(not g for g in grids):
            continue
        names = [s.element for s in system]
        for combo in product(*grids):
            if unit == "at" and sum(combo) != target:
                continue
            g = 0
            for v in combo:
                g = gcd(g, v)
            key = tuple(sorted(zip(names, (v // g for v in combo))))
            if key in seen:
                continue
            seen.add(key)
            yield {el: v / scale for el, v in zip(names, combo)}


def summarize_space(specs: list[SweepSpec], unit: str = "ratio", sizes: set[int] | None = None,
                    limit: int = DEFAULT_LIMIT) -> SpaceSummary:
    n = 0
    truncated = False
    for _ in iter_space(specs, unit, sizes):
        n += 1
        if n > limit:
            truncated = True
            break
    req = sum(1 for s in specs if s.required)
    return SpaceSummary(len(specs), req, len(specs) - req, len(systems(specs, sizes)), n, truncated)


def generate_space(specs: list[SweepSpec], unit: str = "ratio", sizes: set[int] | None = None,
                   limit: int = DEFAULT_LIMIT) -> list[dict[str, float]]:
    out = []
    for comp in iter_space(specs, unit, sizes):
        out.append(comp)
        if len(out) > limit:
            raise RangeError(f"More than {limit:,} compositions; increase the steps or narrow the ranges.")
    return out
