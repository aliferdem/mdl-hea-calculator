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
    """One element's grid: Min to Max inclusive, either in steps of ``step`` (Step size) or as ``points`` evenly
    spaced values including both ends (Points; ``step`` is then not used)."""

    element: str
    minimum: float
    maximum: float
    step: float
    points: int | None = None

    def validate(self) -> None:
        for name, v in (("Min", self.minimum), ("Max", self.maximum)):
            if v is None or not math.isfinite(v):
                raise RangeError(f"{self.element}: {name} is missing or invalid.")
        if self.minimum < 0:
            raise RangeError(f"{self.element}: Min must be ≥ 0.")
        if self.maximum < self.minimum:
            raise RangeError(f"{self.element}: Max must be ≥ Min.")
        if self.points is not None:
            if isinstance(self.points, bool) or not isinstance(self.points, int):
                raise RangeError(f"{self.element}: Points must be a whole number.")
            if self.maximum > self.minimum and self.points < 2:
                raise RangeError(f"{self.element}: Points must be ≥ 2 when Max > Min.")
            if self.points < 1:
                raise RangeError(f"{self.element}: Points must be ≥ 1.")
            return
        if self.step is None or not math.isfinite(self.step):
            raise RangeError(f"{self.element}: Step is missing or invalid.")
        if self.step <= 0 and self.maximum > self.minimum:
            raise RangeError(f"{self.element}: Step must be > 0.")


def _decimals(*values: float) -> int:
    d = 0
    for v in values:
        exp = Decimal(repr(float(v))).normalize().as_tuple().exponent
        d = max(d, -exp if isinstance(exp, int) and exp < 0 else 0)
    return min(d, 6)


def grid_scale(ranges, total: float | None = None) -> int:
    """The one integer scale every grid of a space is expressed in (value × scale is an integer for every grid
    value): 10^decimals of the entered numbers, times the lcm of (Points − 1) of the Points rows - so an N-point
    grid (step (Max − Min)/(N − 1), e.g. thirds) is exact too, and sums, counts and duplicate removal stay integer
    arithmetic."""
    vals = [v for r in ranges for v in (r.minimum, r.maximum)]
    vals += [r.step for r in ranges if getattr(r, "points", None) is None]
    if total is not None:
        vals.append(total)
    scale = 10 ** _decimals(*vals)
    for r in ranges:
        n = getattr(r, "points", None)
        if n is not None and n >= 2 and r.maximum > r.minimum:
            scale = scale * (n - 1) // math.gcd(scale, n - 1)
    return scale


def grid(r: ElementRange, scale: int) -> list[int]:
    """Integer grid (value × scale) from Min to Max inclusive: in steps of Step, or ``points`` values."""
    lo, hi = round(r.minimum * scale), round(r.maximum * scale)
    if r.points is not None:
        if hi == lo or r.points < 2:
            return [lo]
        span = hi - lo
        if span % (r.points - 1):
            raise RangeError(f"{r.element}: internal grid scale error.")     # grid_scale guarantees this
        st = span // (r.points - 1)
        return [lo + k * st for k in range(r.points)]
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
    scale = grid_scale(ranges, total)
    target = round(total * scale)
    grids = [grid(r, scale) for r in ranges]
    last = ranges[-1]
    last_lo, last_hi = round(last.minimum * scale), round(last.maximum * scale)
    lg = grids[-1]
    last_step = (lg[1] - lg[0]) if len(lg) > 1 else 0
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
    points: int | None = None          # Points mode: this many values from Min to Max (``step`` not used)

    def as_range(self) -> ElementRange:
        return ElementRange(self.element, self.minimum, self.maximum, self.step, self.points)

    @property
    def effective_step(self) -> float:
        """The grid spacing in the entered basis (Points: (Max − Min) / (Points − 1))."""
        if self.points is not None:
            return (self.maximum - self.minimum) / (self.points - 1) if self.points > 1 else 0.0
        return self.step


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


def _space_grids(specs: list[SweepSpec], total: float) -> tuple[int, int]:
    for s in specs:
        s.as_range().validate()
    scale = grid_scale(specs, total)
    return scale, round(total * scale)


def _sum_combos(grids: list[list[int]], target: int, prefix: tuple = ()):
    """Combinations of one value per grid summing to ``target``, in lexicographic grid order
    (the order of ``itertools.product`` filtered by the sum) without visiting the rest of the product."""
    n = len(grids)
    suffix_min = [sum(g[0] for g in grids[i:]) for i in range(n + 1)]
    suffix_max = [sum(g[-1] for g in grids[i:]) for i in range(n + 1)]

    def rec(i: int, rest: int, values: tuple):
        if i == n - 1:
            g = grids[i]
            if g[0] <= rest <= g[-1] and _on_grid(g, rest):
                yield values + (rest,)
            return
        for v in grids[i]:
            r = rest - v
            if r < suffix_min[i + 1]:
                break
            if r > suffix_max[i + 1]:
                continue
            yield from rec(i + 1, r, values + (v,))

    if n and suffix_min[0] <= target <= suffix_max[0]:
        yield from rec(0, target, prefix)


def _on_grid(g: list[int], v: int) -> bool:
    if len(g) == 1:
        return v == g[0]
    return (v - g[0]) % (g[1] - g[0]) == 0


def _ray_first(combo: tuple[int, ...], grids: list[list[int]]) -> bool:
    """True when ``combo`` is the first tuple of its ray (its proportional class) in product order.

    The tuples proportional to ``combo`` are ``k·p`` with ``p = combo / gcd(combo)``; product order
    is lexicographic with a strictly positive first component, so the class members appear in
    increasing ``k``.  ``combo = g·p`` is therefore the first iff no ``k < g`` puts every ``k·pᵢ`` on
    its grid - decided without remembering any earlier tuple (constant memory for any space size;
    the former ``seen`` set held every distinct direction)."""
    from math import gcd
    g = gcd(*combo)
    if g <= 1:
        return True
    p = [v // g for v in combo]
    k0 = max(1, max(-(-gr[0] // pi) for gr, pi in zip(grids, p)))
    for k in range(k0, g):
        if all(_on_grid_range(gr, k * pi) for gr, pi in zip(grids, p)):
            return False
    return True


def _on_grid_range(g: list[int], v: int) -> bool:
    return g[0] <= v <= g[-1] and _on_grid(g, v)


# Range bases of a composition space (the Composition setup "Range basis" menu).  The values a space yields are
# in the entered basis; recipes.SweepRecipe.atomic converts wt.% and mass to atomic amounts with the shared
# composition.to_fractions (the Single-composition conversion) before anything is calculated.
#   * sum-constrained bases - at.% and wt.%: a composition is one grid value per element summing to 100;
#   * free (proportional) bases - at. ratio and mass (g): any positive grid values; a mass vector, like Single
#     composition's Mass column, describes a batch whose total is the sum of its masses, so proportional mass
#     vectors are the same alloy and only the first of each ray is kept (as for ratios).
SPACE_UNITS = ("ratio", "at", "wt", "mass")
SUM_UNITS = ("at", "wt")


def check_unit(unit: str) -> str:
    if unit not in SPACE_UNITS:
        raise RangeError(f"Unknown range basis {unit!r}.")
    return unit


def iter_space(specs: list[SweepSpec], unit: str = "ratio", sizes: set[int] | None = None,
               total: float = 100.0):
    """Yield compositions of the space (values in the entered basis ``unit``).

    ``unit="ratio"`` / ``"mass"``: every element of a system takes each positive value of its grid
    independently (cartesian product); proportional duplicates are removed (the first of each ray is kept,
    :func:`_ray_first`). ``unit="at"`` / ``"wt"``: as above but only combinations summing to ``total``
    (100 %) are valid.

    Duplicates can only occur inside one system: every value is positive, so two systems never
    share an element set.  In at.% every combination of a system has the same sum, so two
    proportional combinations are equal - at.% therefore has no duplicates at all and its valid
    combinations are enumerated directly (``_sum_combos``) instead of filtering the product.
    The generator holds no per-composition state: it can enumerate millions in constant memory.
    """
    check_unit(unit)
    scale, target = _space_grids(specs, total)
    from itertools import product
    for system in systems(specs, sizes):
        grids = [_positive_grid(s, scale) for s in system]
        if any(not g for g in grids):
            continue
        names = [s.element for s in system]
        if unit in SUM_UNITS:
            for combo in _sum_combos(grids, target):
                yield {el: v / scale for el, v in zip(names, combo)}
            continue
        for combo in product(*grids):
            if _ray_first(combo, grids):
                yield {el: v / scale for el, v in zip(names, combo)}


# ---------------------------------------------------------------------- pre-flight counting
@dataclass(frozen=True)
class SpaceCount:
    """Result of :func:`count_space`: ``count`` is exact unless ``exceeds`` (then ``count > stop_after``)."""
    count: int
    exceeds: bool
    systems: int


def _count_sum(grids: list[list[int]], target: int, cap: int) -> int:
    """Number of one-value-per-grid combinations summing to ``target`` (bounded knapsack DP).

    Each grid is an arithmetic progression ``a + k·s`` (k = 0..K), so the question is the number of
    ``Σ kᵢ·sᵢ = target − Σaᵢ`` solutions; the DP runs over that remainder divided by the common gcd of
    the steps, with sliding-window sums, and saturates at ``cap`` (all terms are non-negative)."""
    rem = target - sum(g[0] for g in grids)
    if rem < 0:
        return 0
    steps = [(g[1] - g[0]) if len(g) > 1 else 0 for g in grids]
    from math import gcd
    sg = 0
    for s in steps:
        sg = gcd(sg, s)
    if sg == 0:
        return 1 if rem == 0 else 0
    if rem % sg:
        return 0
    R = rem // sg
    if R > 4_000_000:                       # pathological grids: count by enumeration instead
        n = 0
        for _ in _sum_combos(grids, target):
            n += 1
            if n >= cap:
                break
        return n
    dp = [0] * (R + 1)
    dp[0] = 1
    for g, s in zip(grids, steps):
        if s == 0:
            continue
        s //= sg
        K = len(g) - 1
        new = [0] * (R + 1)
        for r0 in range(min(s, R + 1)):
            window = 0
            idx = list(range(r0, R + 1, s))
            for j, x in enumerate(idx):
                window += dp[x]
                if j > K:
                    window -= dp[idx[j - K - 1]]
                new[x] = window if window < cap else cap
        dp = new
    return min(dp[R], cap)


def count_space(specs: list[SweepSpec], unit: str = "ratio", sizes: set[int] | None = None,
                stop_after: int = DEFAULT_LIMIT, total: float = 100.0, cancelled=None) -> SpaceCount:
    """Number of compositions :func:`iter_space` yields, without materialising them.

    at.% / wt.%: exact, per system, by :func:`_count_sum` (no duplicates exist, see :func:`iter_space`).
    Ratio / mass: a system's product of ``P`` tuples holds at least ``P / min |gridᵢ|`` distinct directions
    (a ray meets each grid at most ``|gridᵢ|`` times), so a system that alone proves the count
    exceeds ``stop_after`` stops immediately; otherwise the product is walked with the same duplicate
    rule as ``iter_space`` and stopped once ``stop_after`` is exceeded.
    ``cancelled()`` (optional) is polled while walking a product; a cancelled count returns early.
    """
    check_unit(unit)
    scale, target = _space_grids(specs, total)
    syst = systems(specs, sizes)
    cap = stop_after + 1
    n = 0
    from math import prod
    from itertools import product
    for system in syst:
        grids = [_positive_grid(s, scale) for s in system]
        if any(not g for g in grids):
            continue
        if unit in SUM_UNITS:
            n += _count_sum(grids, target, cap - n)
        else:
            sizes_ = [len(g) for g in grids]
            if prod(sizes_) // min(sizes_) >= cap - n:
                return SpaceCount(cap, True, len(syst))
            for i, combo in enumerate(product(*grids)):
                if cancelled is not None and not i & 0xFFF and cancelled():
                    return SpaceCount(n, False, len(syst))
                if not _ray_first(combo, grids):
                    continue
                n += 1
                if n >= cap:
                    break
        if n >= cap:
            return SpaceCount(cap, True, len(syst))
    return SpaceCount(n, False, len(syst))


def summarize_space(specs: list[SweepSpec], unit: str = "ratio", sizes: set[int] | None = None,
                    limit: int = DEFAULT_LIMIT, cancelled=None) -> SpaceSummary:
    c = count_space(specs, unit, sizes, stop_after=limit, cancelled=cancelled)
    req = sum(1 for s in specs if s.required)
    return SpaceSummary(len(specs), req, len(specs) - req, c.systems, c.count, c.exceeds)


def generate_space(specs: list[SweepSpec], unit: str = "ratio", sizes: set[int] | None = None,
                   limit: int = DEFAULT_LIMIT) -> list[dict[str, float]]:
    out = []
    for comp in iter_space(specs, unit, sizes):
        out.append(comp)
        if len(out) > limit:
            raise RangeError(f"More than {limit:,} compositions; increase the steps or narrow the ranges.")
    return out
