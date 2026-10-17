"""Picklable generation recipes: a batch described by its parameters, generated where it is calculated.

Generating a sweep is pure Python; doing it on any thread of the GUI process starves the Qt event
loop through the GIL (measured: a 509 ms event-loop gap right after Calculate).  A recipe is sent
to the calculation worker processes instead, and no process ever holds the whole batch:

* :class:`SweepRecipe` - each worker walks the (deterministic, constant-memory) composition-space
  generator with a cursor and calculates only its slices; slices arrive in increasing order per
  worker, so each worker generates the sequence at most once (~1 µs per composition against
  ~500 µs of engine work).
* :class:`ExpressionRecipe` - duplicate removal needs the whole history, so one worker writes a
  *plan*: one bit per variable combination (kept / skipped-or-duplicate), streamed to a file in
  fixed ranges.  Calculation workers evaluate any range directly (:class:`ExpressionSpace`
  random access) using the plan bits; they keep no duplicate set.
* :class:`RecalcRecipe` - recalculation reads the stored inputs of a run from the database
  (read-only) in id ranges.

Every recipe also describes the run it produces (``run_meta``): mode, elements, design axes and
source parameters, and builds the design-coordinate rows (``design``) stored for future plots.

``estimate()`` is the cheap pre-flight size used to decide between in-process and worker
calculation; ``__call__`` materialises a *small* batch (in-process path, previews):
``(sources, names, compositions, variables)``.
"""

from __future__ import annotations

import math
import os
import sqlite3
from array import array
from dataclasses import dataclass
from functools import cached_property
from itertools import islice

from . import composition as C
from .expression import (Expression, ExpressionSpace, VariableRange, block_variables, composition_key,
                         count_blocks, count_combinations, expression_elements, generate_blocks)
from .generation import (DEFAULT_LIMIT, SUM_UNITS, RangeError, SweepSpec, check_unit, count_space, generate_space,
                         iter_space)

NAN = float("nan")
UNIT_LABELS = {"ratio": "at. ratio", "at": "at.%", "wt": "wt.%", "mass": "g"}
COPY_GENERATED_MAX = 1_048_575          # one Excel worksheet below its header row


# ====================================================================== composition space
@dataclass(frozen=True)
class SweepRecipe:
    specs: tuple[SweepSpec, ...]
    unit: str = "ratio"
    sizes: frozenset[int] | None = None
    limit: int = DEFAULT_LIMIT
    kind = "sweep"

    def __post_init__(self):
        check_unit(self.unit)

    def estimate(self) -> int:
        """Cheap upper bound of the batch size: exact for at.% / wt.% (DP, < 1 ms even for 10⁸ alloys), the
        grid product for ratios and masses."""
        sizes = set(self.sizes) if self.sizes else None
        if self.unit in SUM_UNITS:
            return count_space(list(self.specs), self.unit, sizes, stop_after=10 ** 15).count
        from math import prod
        from .generation import _positive_grid, _space_grids, systems
        scale, _ = _space_grids(list(self.specs), 100.0)
        return sum(prod(len(_positive_grid(s, scale)) for s in system) for system in systems(list(self.specs), sizes))

    def count(self) -> int:
        """Exact size (at.%: DP; ratio: a constant-memory walk) - run in a worker for large spaces."""
        sizes = set(self.sizes) if self.sizes else None
        return count_space(list(self.specs), self.unit, sizes, stop_after=10 ** 15).count

    def iterate(self):
        """Grid compositions in the entered basis (see :meth:`atomic` for what is calculated)."""
        sizes = set(self.sizes) if self.sizes else None
        return iter_space(list(self.specs), self.unit, sizes)

    def atomic(self, grid: dict) -> dict:
        """The composition calculated for one grid point: atomic amounts.  at. ratio / at.% are atomic
        already; wt.% and mass are converted with the shared Single-composition conversion
        (``composition.to_fractions``, standard atomic weights) and expressed in at.%."""
        if self.unit in ("ratio", "at"):
            return grid
        x = C.to_fractions(grid, self.unit)
        return {el: 100.0 * v for el, v in x.items()}

    def name(self, comp: dict) -> str:
        """Alloy name from the *atomic* composition (``atomic(grid)``)."""
        return C.percent_name(comp) if self.unit in SUM_UNITS else C.alloy_name(comp)

    @property
    def elements(self) -> list[str]:
        return [s.element for s in self.specs]

    def run_meta(self) -> dict:
        unit = UNIT_LABELS[self.unit]
        return {"mode": "sweep", "elements": self.elements,
                "axes": [{"name": el, "col": f"c{i}", "kind": "element", "unit": unit}
                         for i, el in enumerate(self.elements)],
                "source": {"unit": self.unit, "sizes": sorted(self.sizes) if self.sizes else None,
                           "specs": [{"element": s.element, "min": s.minimum, "max": s.maximum, "step": s.step,
                                      "required": s.required} for s in self.specs]}}

    def design(self, grid, envs=None, results=None) -> array:
        """Sweep coordinates: the generating grid values in the entered basis (0 for an absent optional
        element) - for wt.% / mass these are the entered wt.% / grams, not the converted at.%."""
        els = self.elements
        return array("d", (float(c.get(el, 0.0)) for c in grid for el in els))

    def _generate(self) -> tuple[list[dict], list[dict]]:
        sizes = set(self.sizes) if self.sizes else None
        grid = generate_space(list(self.specs), self.unit, sizes, limit=self.limit)
        if not grid:
            raise RangeError("No valid compositions for these ranges"
                             + (f" ({UNIT_LABELS[self.unit]} values must sum to 100 %)." if self.unit in SUM_UNITS
                                else "."))
        return grid, [self.atomic(g) for g in grid]

    def __call__(self):
        _grid, comps = self._generate()
        names = [self.name(c) for c in comps]
        return "sweep", names, comps, [{} for _ in comps]

    def materialise(self) -> dict:
        grid, comps = self._generate()
        return {"sources": "sweep", "names": [self.name(c) for c in comps], "comps": comps, "grid": grid,
                "variables": None, "blocks": None}


class SweepCursor:
    """Sequential slices of a sweep (one per worker and job): never re-generates what it passed.  Slices are
    grid compositions in the entered basis; the chunk calculation converts them (``SweepRecipe.atomic``)."""

    def __init__(self, recipe: SweepRecipe):
        self.recipe = recipe
        self.it = recipe.iterate()
        self.pos = 0

    def take(self, start: int, stop: int) -> list[dict]:
        if start < self.pos:
            self.it, self.pos = self.recipe.iterate(), 0
        if start > self.pos:
            next(islice(self.it, start - self.pos, start - self.pos), None)
            self.pos = start
        out = list(islice(self.it, stop - start))
        self.pos += len(out)
        return out


# ====================================================================== expressions
@dataclass(frozen=True)
class ExpressionRecipe:
    expressions: tuple[Expression, ...]
    ranges: tuple[tuple[str, VariableRange], ...]
    text: str = ""
    block_ranges: tuple = ()          # one tuple of (name, VariableRange) per block (inline syntax)
    kind = "expression"

    @property
    def spec(self):
        """The range spec: per-block dicts (inline syntax) or one shared dict."""
        if self.block_ranges:
            return [dict(r) for r in self.block_ranges]
        return dict(self.ranges)

    def estimate(self) -> int:
        return count_combinations(list(self.expressions), self.spec)

    @cached_property
    def space(self) -> ExpressionSpace:
        return ExpressionSpace(list(self.expressions), self.spec)

    @property
    def variables(self) -> list[str]:
        return block_variables(list(self.expressions))

    @property
    def elements(self) -> list[str]:
        return expression_elements(list(self.expressions))

    def run_meta(self) -> dict:
        axes = [{"name": v, "col": f"x{i}", "kind": "variable"} for i, v in enumerate(self.variables)]
        axes += [{"name": f"{el} at.%", "col": f"f{j}", "kind": "fraction", "unit": "at.%", "element": el}
                 for j, el in enumerate(self.elements)]
        spec = self.spec

        def rng(v):
            return [v.minimum, v.maximum, v.step] + ([v.points] if v.points else [])
        blocks = []
        merged: dict = {}
        for i, ex in enumerate(self.expressions):
            r = spec[i] if isinstance(spec, list) else spec
            mine = {k: rng(r[k]) for k in ex.variables if k in r}
            for k, v in mine.items():
                merged.setdefault(k, v)
            blocks.append({"index": i, "name": None, "expression": ex.source, "variables": list(ex.variables),
                           "ranges": mine})
        return {"mode": "expression", "elements": self.elements, "axes": axes,
                "source": {"text": self.text, "blocks": blocks, "ranges": merged}}

    def design(self, comps, envs, results) -> array:
        """Variable values (NaN = not used by the block) then the engine's at.% of every element."""
        vs, els = self.variables, self.elements
        out = array("d")
        for env, res in zip(envs, results):
            out.extend(float(env[v]) if v in env else NAN for v in vs)
            frac = res.composition if res is not None and res.ok else None
            out.extend((100.0 * frac.get(el, 0.0)) if frac else NAN for el in els)
        return out

    # -------------------------------------------------------------- plan (one worker)
    def plan(self, path: str, block: int, cancelled=lambda: False) -> tuple[int, int, int, int, dict]:
        """Write one bit per combination (1 = calculated) to ``path`` in ranges of ``block``
        combinations, flushed range by range so calculation can follow; returns
        ``(valid, skipped, duplicates, combinations, duplicates per expression block)`` - a duplicate is
        counted in the block that generated it again (it is kept in the first one).  The only process
        holding a duplicate set."""
        import hashlib
        space = self.space
        seen: set[bytes] = set()
        valid = skipped = dups = 0
        by_block: dict[int, int] = {}
        nbytes = block // 8
        with open(path, "wb") as fh:
            bits = bytearray(nbytes)
            for g in range(space.total):
                if not g & 0x3FF and cancelled():
                    break
                b, _env, positive = space.evaluate(g)
                if positive is None:
                    skipped += 1
                else:
                    key = hashlib.blake2b(repr(composition_key(positive)).encode(), digest_size=16).digest()
                    if key in seen:
                        dups += 1
                        by_block[b] = by_block.get(b, 0) + 1
                    else:
                        seen.add(key)
                        valid += 1
                        r = g % block
                        bits[r >> 3] |= 1 << (r & 7)
                if g % block == block - 1 or g == space.total - 1:
                    fh.write(bits)
                    fh.flush()
                    bits = bytearray(nbytes)
        return valid, skipped, dups, space.total, by_block

    def take(self, bits: bytes, k: int, block: int) -> tuple[list, list, list, list]:
        """Compositions of combination range ``k`` (kept by the plan bits)."""
        space = self.space
        comps, names, envs, blocks = [], [], [], []
        bits = bytes(bits).ljust(block // 8, bytes(1))
        start = k * block
        for r in range(min(block, space.total - start)):
            if bits[r >> 3] >> (r & 7) & 1:
                b, env, positive = space.evaluate(start + r)
                comps.append(positive)
                names.append(space.name(b, env))
                envs.append(env)
                blocks.append(b)
        return comps, names, envs, blocks

    def __call__(self):
        b = generate_blocks(list(self.expressions), self.spec)
        if not b.compositions:
            raise RangeError("No valid compositions for these ranges.")
        return "expression", b.names, b.compositions, b.variables

    def materialise(self) -> dict:
        b = generate_blocks(list(self.expressions), self.spec)
        if not b.compositions:
            raise RangeError("No valid compositions for these ranges.")
        return {"sources": "expression", "names": b.names, "comps": b.compositions, "variables": b.variables,
                "blocks": b.blocks, "counts": (len(b.compositions), b.skipped, b.duplicates,
                                               len(b.compositions) + b.skipped + b.duplicates, b.duplicates_by_block)}


# ====================================================================== recalculation
@dataclass(frozen=True)
class RecalcRecipe:
    """Recalculate one stored run (new settings, same inputs, same provenance)."""
    db_path: str
    run_id: int
    first_id: int
    last_id: int
    design_cols: tuple[str, ...] = ()
    count_hint: int = 0
    kind = "recalc"

    def estimate(self) -> int:
        return self.count_hint or (self.last_id - self.first_id + 1)

    def connect(self) -> sqlite3.Connection:
        from pathlib import Path
        con = sqlite3.connect(f"file:{Path(self.db_path).as_posix()}?mode=ro", uri=True, timeout=10)
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def read(self, con: sqlite3.Connection, lo: int, hi: int) -> dict:
        """Stored inputs and provenance of ids ``lo..hi`` of the run (id order)."""
        from .chunks import decode_amounts
        rows = con.execute("SELECT r.result_id, r.name, s.s, r.block, e.els, r.amounts FROM results r "
                           "LEFT JOIN strings s ON s.code = r.src LEFT JOIN elsets e ON e.id = r.elset "
                           "WHERE r.run_id = ? AND r.result_id BETWEEN ? AND ? ORDER BY r.result_id",
                           (self.run_id, lo, hi)).fetchall()
        design = None
        if self.design_cols:
            cols = ", ".join('"' + c + '"' for c in self.design_cols)
            got = {r[0]: r[1:] for r in con.execute(
                f'SELECT result_id, {cols} FROM "design_{self.run_id}" WHERE result_id BETWEEN ? AND ?', (lo, hi))}
            design = array("d")
            k = len(self.design_cols)
            for r in rows:
                design.extend(NAN if v is None else float(v) for v in got.get(r[0], (None,) * k))
        comps = [decode_amounts(tuple(r[4].split(",")) if r[4] else (), r[5])[0] for r in rows]
        return {"ids": [r[0] for r in rows], "names": [r[1] or "" for r in rows], "sources": [r[2] or "" for r in rows],
                "blocks": [r[3] for r in rows], "comps": comps, "design": design}

    def __call__(self):
        d = self.materialise()
        return d["sources"], d["names"], d["comps"], [{} for _ in d["comps"]]

    def materialise(self) -> dict:
        con = self.connect()
        try:
            d = self.read(con, self.first_id, self.last_id)
        finally:
            con.close()
        return {"sources": d["sources"], "names": d["names"], "comps": d["comps"], "variables": None,
                "blocks": d["blocks"], "design": d["design"]}


# ---------------------------------------------------------------------- small results for the GUI
# These run where the batch is generated (a worker process for large batches) and return only what
# the GUI shows, never the composition list itself.
@dataclass(frozen=True)
class BatchCount:
    count: int
    skipped: int = 0
    duplicates: int = 0


def expression_count(expressions, ranges) -> BatchCount:
    """Valid / skipped / duplicate counts of expression blocks (the live pre-flight summary).  ``ranges`` is a
    tuple of (name, range) pairs (shared) or a list of per-block dicts (inline syntax)."""
    spec = ranges if (isinstance(ranges, list) and (not ranges or isinstance(ranges[0], dict))) else dict(ranges)
    valid, skipped, dups = count_blocks(list(expressions), spec)
    return BatchCount(valid, skipped, dups)


def expression_count_detail(expressions, ranges) -> dict:
    """Per-block counts for the inline expression editor (runs in a worker process for large documents)."""
    from .expression import count_blocks_detail
    return count_blocks_detail(list(expressions), ranges)


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


def _check_copy_size(recipe) -> None:
    n = recipe.estimate()
    if n > COPY_GENERATED_MAX:
        raise RangeError(f"{n:,} combinations are too many to copy (at most {COPY_GENERATED_MAX:,} rows, one Excel "
                         "worksheet). Calculate them and export the results instead.")


def recipe_tsv(recipe) -> str:
    _check_copy_size(recipe)
    _src, names, comps, _envs = recipe()
    return compositions_tsv(names, comps)


def recipe_preview(recipe, limit: int = 2000) -> tuple[int, list[str], str]:
    """(total, first ``limit`` display lines, full TSV) for the generated-compositions dialog."""
    _check_copy_size(recipe)
    _src, names, comps, _envs = recipe()
    lines = []
    for n, c in list(zip(names, comps))[:limit]:
        tot = sum(c.values())
        lines.append(f"{n}    ({', '.join(f'{el} {100 * v / tot:.2f}' for el, v in c.items())})")
    return len(comps), lines, compositions_tsv(names, comps)


_ = (math, os)
