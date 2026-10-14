"""Statistical conventions of Collection analysis (normative; ``ANALYSIS_FIGMA_SAMPLE_DATA.md``, data contract 9).

* N valid = finite values; missing values (N/A) are excluded and counted, never treated as zero;
* sample standard deviation with n − 1 (not reported for N valid < 2);
* quartiles by linear interpolation between order statistics - Hyndman & Fan (1996) type 7, the
  default of R and NumPy: h = (n − 1)·p, Q(p) = x[⌊h⌋] + (h − ⌊h⌋)(x[⌊h⌋+1] − x[⌊h⌋]) (0-based);
* no imputation; categorical fields have no mean.

The SQL implementations (``queries.py``) follow exactly these definitions; this module is the reference
used for small populations and by the tests.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

QUARTILES = (0.25, 0.5, 0.75)


def type7_positions(n: int, p: float) -> tuple[int, int, float]:
    """0-based order-statistic indices (lo, hi) and the interpolation weight for quantile ``p`` of ``n``."""
    if n <= 0:
        raise ValueError("no values")
    h = (n - 1) * p
    lo = int(math.floor(h))
    hi = min(lo + 1, n - 1)
    return lo, hi, h - lo


def quantile_type7(sorted_values: Sequence[float], p: float) -> float | None:
    n = len(sorted_values)
    if n == 0:
        return None
    lo, hi, w = type7_positions(n, p)
    a, b = sorted_values[lo], sorted_values[hi]
    return a + w * (b - a)


def finite(values: Iterable) -> list[float]:
    return [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)]


def describe(values: Iterable) -> dict:
    """Every measure of the Statistics table for one metric (reference implementation)."""
    raw = list(values)
    xs = sorted(finite(raw))
    n = len(xs)
    out = {"n_valid": n, "n_missing": len(raw) - n, "mean": None, "sd": None, "min": None, "q1": None,
           "median": None, "q3": None, "max": None}
    if not n:
        return out
    mean = math.fsum(xs) / n
    out["mean"] = mean
    if n >= 2:
        out["sd"] = math.sqrt(math.fsum((x - mean) ** 2 for x in xs) / (n - 1))
    out["min"], out["max"] = xs[0], xs[-1]
    out["q1"], out["median"], out["q3"] = (quantile_type7(xs, p) for p in QUARTILES)
    return out
