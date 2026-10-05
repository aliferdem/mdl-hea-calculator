"""Composition parsing, representation conversion and naming (no Qt, no scientific models).

Representations
---------------
``ratio``  atomic ratio (any positive proportional amounts)
``at``     atomic percent
``wt``     weight percent
``mass``   mass in grams (with a total mass)

All conversions go through atomic fractions so that switching representation never changes the
underlying composition.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .data import Datasets, default_datasets

REPRESENTATIONS = ("ratio", "at", "wt", "mass")
REPRESENTATION_LABELS = {"element": "El.", "ratio": "At. ratio", "at": "at.%", "wt": "wt.%", "mass": "Mass"}


class FormulaError(ValueError):
    """Raised when a formula string cannot be parsed."""


# ---------------------------------------------------------------------- formula parsing
_TOKEN = re.compile(r"\s*(?:(?P<el>[A-Z][a-z]?)|(?P<num>\d+(?:\.\d*)?|\.\d+)|(?P<open>[(\[])|(?P<close>[)\]]))")


def parse_formula(text: str, datasets: Datasets | None = None) -> dict[str, float]:
    """Parse ``Al0.5CoCrFeNi``, ``(FeCoNi)90Al10``, ``Al20(TiCoCrFeNi)80`` into amounts.

    Amounts are returned as given (proportional), merged per element, in first-appearance order.
    Groups multiply their normalised contents: ``(FeCo)2Ni`` = Fe1 Co1 Ni1.
    """
    data = datasets or default_datasets()
    s = text.strip().replace(" ", "")
    if not s:
        raise FormulaError("Empty formula.")
    pos = 0

    def parse_seq(depth: int) -> list[tuple[str, float]]:
        nonlocal pos
        items: list[tuple[str, float]] = []
        while pos < len(s):
            m = _TOKEN.match(s, pos)
            if not m:
                raise FormulaError(f"Unexpected character '{s[pos]}' at position {pos + 1}.")
            if m.group("el"):
                sym = m.group("el")
                if not data.is_element(sym):
                    # maybe a one-letter element followed by a lowercase letter that is not part of it
                    if len(sym) == 2 and data.is_element(sym[0]):
                        raise FormulaError(f"Unknown element '{sym}'.")
                    raise FormulaError(f"Unknown element '{sym}'.")
                pos = m.end()
                amount = _read_number()
                items.append((sym, amount))
            elif m.group("open"):
                pos = m.end()
                inner = parse_seq(depth + 1)
                amount = _read_number()
                total = sum(v for _, v in inner)
                if total <= 0:
                    raise FormulaError("Group with zero total amount.")
                items.extend((el, v / total * amount) for el, v in inner)
            elif m.group("close"):
                if depth == 0:
                    raise FormulaError("Unbalanced ')'.")
                pos = m.end()
                return items
            else:
                raise FormulaError(f"Unexpected number at position {pos + 1}.")
        if depth > 0:
            raise FormulaError("Unbalanced '('.")
        return items

    def _read_number() -> float:
        nonlocal pos
        m = re.compile(r"\d+(?:\.\d*)?|\.\d+").match(s, pos)
        if not m:
            return 1.0
        pos = m.end()
        return float(m.group())

    items = parse_seq(0)
    out: dict[str, float] = {}
    for el, v in items:
        out[el] = out.get(el, 0.0) + v
    if not out:
        raise FormulaError("No elements found.")
    return out


# ---------------------------------------------------------------------- conversions
def fractions(amounts: dict[str, float]) -> dict[str, float]:
    total = sum(amounts.values())
    if total <= 0:
        raise ValueError("Total must be greater than zero.")
    return {el: v / total for el, v in amounts.items()}


def to_fractions(values: dict[str, float], representation: str, datasets: Datasets | None = None
                 ) -> dict[str, float]:
    """Convert values in ``representation`` to atomic fractions."""
    data = datasets or default_datasets()
    if any(v is None or not math.isfinite(v) or v < 0 for v in values.values()):
        raise ValueError("Values must be finite and non-negative.")
    if representation in ("ratio", "at"):
        return fractions(values)
    if representation in ("wt", "mass"):
        moles = {el: v / data.prop(el, "atomic_weight") for el, v in values.items()}
        return fractions(moles)
    raise ValueError(f"Unknown representation {representation!r}.")


def from_fractions(x: dict[str, float], representation: str, *, total_mass: float = 1.0,
                   datasets: Datasets | None = None) -> dict[str, float]:
    """Express atomic fractions in ``representation``.

    ``ratio`` is scaled so that the largest component equals 1. ``mass`` uses ``total_mass`` (g).
    """
    data = datasets or default_datasets()
    if representation == "ratio":
        top = max(x.values()) if x else 0.0
        return {el: (v / top if top > 0 else 0.0) for el, v in x.items()}
    if representation == "at":
        return {el: 100.0 * v for el, v in x.items()}
    if representation in ("wt", "mass"):
        masses = {el: v * data.prop(el, "atomic_weight") for el, v in x.items()}
        tot = sum(masses.values())
        scale = 100.0 if representation == "wt" else total_mass
        return {el: (m / tot * scale if tot > 0 else 0.0) for el, m in masses.items()}
    raise ValueError(f"Unknown representation {representation!r}.")


def convert(values: dict[str, float], src: str, dst: str, *, total_mass: float = 1.0,
            datasets: Datasets | None = None) -> dict[str, float]:
    return from_fractions(to_fractions(values, src, datasets), dst, total_mass=total_mass, datasets=datasets)


def all_representations(values: dict[str, float], src: str, *, total_mass: float = 1.0,
                        datasets: Datasets | None = None) -> dict[str, dict[str, float]]:
    """Return every representation of a composition entered in ``src``.

    The entered column is returned unchanged (no rounding drift). When ``src`` is ``mass`` the total
    mass is the sum of the entered masses.
    """
    x = to_fractions(values, src, datasets)
    if src == "mass":
        total_mass = sum(values.values())
    out = {}
    for rep in REPRESENTATIONS:
        out[rep] = dict(values) if rep == src else from_fractions(x, rep, total_mass=total_mass, datasets=datasets)
    return out


def set_equal(elements: list[str], representation: str, *, total_mass: float = 1.0) -> dict[str, float]:
    """Equal values in the active representation (ratio 1 each, percentages 100/n, mass total/n)."""
    n = len(elements)
    if n == 0:
        return {}
    if representation == "ratio":
        value = 1.0
    elif representation in ("at", "wt"):
        value = 100.0 / n
    elif representation == "mass":
        value = total_mass / n
    else:
        raise ValueError(f"Set equal does not apply to {representation!r}.")
    return {el: value for el in elements}


def can_normalise(representation: str) -> bool:
    return representation in ("at", "wt")


def normalise(values: dict[str, float | None], representation: str) -> dict[str, float]:
    """Scale percentage values to sum to 100. Blank/invalid/negative entries raise ``ValueError``."""
    if not can_normalise(representation):
        raise ValueError("Normalize applies to at.% and wt.% only.")
    clean = {}
    for el, v in values.items():
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{el}: value is missing or invalid.")
        if v < 0:
            raise ValueError(f"{el}: value must be non-negative.")
        clean[el] = float(v)
    total = sum(clean.values())
    if total <= 0:
        raise ValueError("Cannot normalize: total is zero.")
    return {el: v * 100.0 / total for el, v in clean.items()}


def parse_number(text: str) -> float | None:
    """Parse a user-entered number (accepts ',' as decimal separator). Returns None if invalid."""
    t = (text or "").strip().replace(",", ".")
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------------- naming
def _fmt_amount(v: float, digits: int = 3) -> str:
    if abs(v - 1.0) < 10 ** (-digits) / 2:
        return ""
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return s if s not in ("0", "") else f"{v:.{digits}g}"


def alloy_name(amounts: dict[str, float], digits: int = 3) -> str:
    """Conventional alloy name with plain-text subscripts, e.g. ``Al0.5CoCrFeNi``.

    Amounts are divided by the most frequent value (ties → largest) so that the majority of elements
    carry no subscript.
    """
    vals = {el: float(v) for el, v in amounts.items() if v and v > 0}
    if not vals:
        return ""
    rounded = Counter(round(v, 9) for v in vals.values())
    top_count = max(rounded.values())
    base = max(v for v, n in rounded.items() if n == top_count)
    if top_count == 1:
        base = max(vals.values())
    return "".join(f"{el}{_fmt_amount(v / base, digits)}" for el, v in vals.items())


def percent_name(at_percent: dict[str, float], decimals: int = 2) -> str:
    """Name from at.% values, e.g. ``Al10Ti30V60`` (zero entries omitted)."""
    parts = []
    for el, v in at_percent.items():
        if v <= 0:
            continue
        s = f"{v:.{decimals}f}".rstrip("0").rstrip(".")
        parts.append(f"{el}{s}")
    return "".join(parts)


_SUB = str.maketrans("0123456789.", "₀₁₂₃₄₅₆₇₈₉.")


def name_segments(name: str) -> list[tuple[str, bool]]:
    """Split an alloy name into (text, is_subscript) runs for rich rendering."""
    out: list[tuple[str, bool]] = []
    for m in re.finditer(r"([A-Z][a-z]?|[()\[\]])|(\d+(?:\.\d+)?)|(.)", name):
        if m.group(2):
            out.append((m.group(2), True))
        else:
            out.append((m.group(0), False))
    return out


def name_html(name: str) -> str:
    return "".join(f"<sub>{t}</sub>" if sub else t for t, sub in name_segments(name))
