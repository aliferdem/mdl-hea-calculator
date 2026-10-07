"""Picklable generation recipes: a batch described by its parameters, generated where it is calculated.

Generating a 100 000-composition sweep is ~0.3 s of pure Python; doing it on any thread of the GUI
process starves the Qt event loop through the GIL (measured: a 509 ms event-loop gap right after
Calculate).  A recipe is sent to the calculation worker processes instead; each worker generates
the batch once per job (deterministically - every worker obtains the same list) and calculates
its slices, returning names / variables alongside the results.  The GUI process never holds the
composition list.

``estimate()`` is the cheap pre-flight size used to decide between in-process and worker
calculation; ``__call__`` returns ``(sources, names, compositions, variables)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import composition as C
from .expression import Expression, VariableRange, count_combinations, generate_blocks
from .generation import DEFAULT_LIMIT, RangeError, SweepSpec, count_space, generate_space


@dataclass(frozen=True)
class SweepRecipe:
    specs: tuple[SweepSpec, ...]
    unit: str = "ratio"
    sizes: frozenset[int] | None = None
    limit: int = DEFAULT_LIMIT

    def estimate(self) -> int:
        """Cheap upper bound of the batch size: exact for at.% (DP), the grid product for ratios."""
        sizes = set(self.sizes) if self.sizes else None
        if self.unit == "at":
            return count_space(list(self.specs), self.unit, sizes, stop_after=self.limit).count
        from math import prod
        from .generation import _positive_grid, _space_grids, systems
        scale, _ = _space_grids(list(self.specs), 100.0)
        return sum(prod(len(_positive_grid(s, scale)) for s in system) for system in systems(list(self.specs), sizes))

    def __call__(self):
        sizes = set(self.sizes) if self.sizes else None
        comps = generate_space(list(self.specs), self.unit, sizes, limit=self.limit)
        if not comps:
            raise RangeError("No valid compositions for these ranges"
                             + (" (at.% values must sum to 100 %)." if self.unit == "at" else "."))
        names = [C.percent_name(c) if self.unit == "at" else C.alloy_name(c) for c in comps]
        return "sweep", names, comps, [{} for _ in comps]


@dataclass(frozen=True)
class ExpressionRecipe:
    expressions: tuple[Expression, ...]
    ranges: tuple[tuple[str, VariableRange], ...]

    def estimate(self) -> int:
        return count_combinations(list(self.expressions), dict(self.ranges))

    def __call__(self):
        b = generate_blocks(list(self.expressions), dict(self.ranges))
        if not b.compositions:
            raise RangeError("No valid compositions for these ranges.")
        return "expression", b.names, b.compositions, b.variables


# ---------------------------------------------------------------------- small results for the GUI
# These run where the batch is generated (a worker process for large batches) and return only what
# the GUI shows, never the composition list itself.
@dataclass(frozen=True)
class BatchCount:
    count: int
    skipped: int = 0
    duplicates: int = 0


def expression_count(expressions, ranges) -> BatchCount:
    """Valid / skipped / duplicate counts of expression blocks (the live pre-flight summary)."""
    b = generate_blocks(list(expressions), dict(ranges))
    return BatchCount(len(b.compositions), b.skipped, b.duplicates)


def compositions_tsv(names, comps) -> str:
    """Generated compositions as Excel-pastable text: alloy name, then at.% per element."""
    elements: list[str] = []
    for c in comps:
        for el in c:
            if el not in elements:
                elements.append(el)
    lines = ["Alloy\t" + "\t".join(f"{el} (at.%)" for el in elements)]
    for n, c in zip(names, comps):
        tot = sum(c.values())
        lines.append(n + "\t" + "\t".join(f"{100 * c.get(el, 0.0) / tot:.4f}" for el in elements))
    return "\r\n".join(lines) + "\r\n"


def recipe_tsv(recipe) -> str:
    _src, names, comps, _envs = recipe()
    return compositions_tsv(names, comps)


def recipe_preview(recipe, limit: int = 2000) -> tuple[int, list[str], str]:
    """(total, first ``limit`` display lines, full TSV) for the generated-compositions dialog."""
    _src, names, comps, _envs = recipe()
    lines = []
    for n, c in list(zip(names, comps))[:limit]:
        tot = sum(c.values())
        lines.append(f"{n}    ({', '.join(f'{el} {100 * v / tot:.2f}' for el, v in c.items())})")
    return len(comps), lines, compositions_tsv(names, comps)
