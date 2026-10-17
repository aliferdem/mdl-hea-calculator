"""Statistical conventions of Collection analysis (normative; ``ANALYSIS_FIGMA_SAMPLE_DATA.md``, data contract 9).

* N valid = finite values; missing values (N/A) are excluded and counted, never treated as zero;
* sample standard deviation with n − 1 (not reported for N valid < 2);
* quartiles by linear interpolation between order statistics - Hyndman & Fan (1996) type 7, the
  default of R and NumPy: h = (n − 1)·p, Q(p) = x[⌊h⌋] + (h − ⌊h⌋)(x[⌊h⌋+1] − x[⌊h⌋]) (0-based);
* no imputation; categorical fields have no mean;
* statistical outliers (Statistics page, brief 2026-10-16 §35): Tukey fences Q1 − 1.5 × IQR and Q3 + 1.5 × IQR;
  values strictly outside are counted, never removed, never treated as erroneous data.  Not applied when
  IQR = 0 or fewer than ``TUKEY_MIN_N`` values are valid (the quartiles are not a meaningful spread there).

The SQL implementations (``queries.py``) follow exactly these definitions; this module is the reference
used for small populations and by the tests.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

QUARTILES = (0.25, 0.5, 0.75)
TUKEY_K = 1.5
TUKEY_MIN_N = 10                 # below this the quartiles of a descriptor are too coarse for fences


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


def tukey_fences(q1, q3, n_valid: int) -> tuple[float, float] | None:
    """(lower, upper) Tukey fences, or None where the method is not meaningful (IQR = 0, too few values)."""
    if q1 is None or q3 is None or n_valid < TUKEY_MIN_N:
        return None
    iqr = q3 - q1
    if not (math.isfinite(iqr) and iqr > 0):
        return None
    return q1 - TUKEY_K * iqr, q3 + TUKEY_K * iqr


def tukey_outliers(values: Iterable) -> tuple[int, int] | None:
    """(below, above) counts of values outside the Tukey fences (reference implementation)."""
    xs = sorted(finite(values))
    if not xs:
        return None
    f = tukey_fences(quantile_type7(xs, 0.25), quantile_type7(xs, 0.75), len(xs))
    if f is None:
        return None
    return sum(x < f[0] for x in xs), sum(x > f[1] for x in xs)


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
