"""Element family: the canonical identity of an alloy system (data contract section 3; no Qt).

The family of a result is the set of element symbols whose **normalised atomic fraction** exceeds
``FAMILY_EPS``, in alphabetical order of the symbol, joined by "-": CrMnFeNi and NiFeMnCr are both
``Cr-Fe-Mn-Ni``.  It is computed from the engine's normalised fractions - never from the input
amounts, the displayed (rounded) at.% or the formula text - so input order, unit and rounding cannot
change it.  ``FAMILY_EPS`` absorbs floating-point residue only; a 0.001 at.% addition is a member.
"""

from __future__ import annotations

from collections.abc import Mapping

FAMILY_EPS = 1e-9
SEPARATOR = "-"


def family_members(fractions: Mapping[str, float], eps: float = FAMILY_EPS) -> tuple[str, ...]:
    """Alphabetically ordered symbols with a normalised fraction above ``eps``."""
    return tuple(sorted(str(el) for el, x in fractions.items() if x is not None and x > eps))


def family_key(fractions: Mapping[str, float], eps: float = FAMILY_EPS) -> str | None:
    """Canonical family key (``"Co-Cr-Fe-Mn-Ni"``), or None for an empty composition (an error row)."""
    members = family_members(fractions, eps)
    return SEPARATOR.join(members) if members else None


def family_size(key: str | None) -> int | None:
    return None if not key else key.count(SEPARATOR) + 1
