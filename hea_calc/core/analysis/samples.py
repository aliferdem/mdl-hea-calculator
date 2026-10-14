"""Canonical Analysis sample collections (``ANALYSIS_FIGMA_SAMPLE_DATA.md``), stored through the normal
engine + repository path.  Used by tests, visual validation and benchmarks - never by the UI itself.

* S1-S5: single compositions (CoCrFeMnNi, CoCrFeNiSi0.5, CoCrFeNiW0.5, CoCrCuFeNi, CoNi);
* C1: composition space Co, Cr, Fe, Ni at 1.0 (required), Al 0.05-1.5 step 0.05 and Mn 0.1-1.0 step 0.1
  (optional), atomic ratio -> 341 compositions;
* E1: expression ``AlxCoCrFeNi``, x 0-2 step 0.05 -> 41 compositions;
* E2: expression ``AlxTiyCoCrFeNi``, x, y 0-1 step 0.1 -> 121 compositions.
"""

from __future__ import annotations

from ..composition import alloy_name
from ..expression import VariableRange, parse_blocks
from ..generation import SweepSpec
from ..recipes import ExpressionRecipe, SweepRecipe
from ..results import ResultRow

S1 = {"Co": 1, "Cr": 1, "Fe": 1, "Mn": 1, "Ni": 1}
S2 = {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "Si": 0.5}
S3 = {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "W": 0.5}
S4 = {"Co": 1, "Cr": 1, "Cu": 1, "Fe": 1, "Ni": 1}
S5 = {"Co": 1, "Ni": 1}
SINGLES = {"S1": S1, "S2": S2, "S3": S3, "S4": S4, "S5": S5}


def c1_recipe() -> SweepRecipe:
    specs = tuple([SweepSpec(el, 1.0, 1.0, 0.1, True) for el in ("Co", "Cr", "Fe", "Ni")]
                  + [SweepSpec("Al", 0.05, 1.5, 0.05, False), SweepSpec("Mn", 0.1, 1.0, 0.1, False)])
    return SweepRecipe(specs, "ratio")


def expression_recipe(text: str, ranges: dict[str, tuple[float, float, float]]) -> ExpressionRecipe:
    exprs = parse_blocks(text)
    return ExpressionRecipe(tuple(exprs), tuple((k, VariableRange(k, *v)) for k, v in ranges.items()), text)


def e1_recipe() -> ExpressionRecipe:
    return expression_recipe("AlxCoCrFeNi", {"x": (0.0, 2.0, 0.05)})


def e2_recipe() -> ExpressionRecipe:
    return expression_recipe("AlxTiyCoCrFeNi", {"x": (0.0, 1.0, 0.1), "y": (0.0, 1.0, 0.1)})


def store_recipe(repo, engine, recipe, options: dict | None = None) -> int:
    """Calculate a (small) recipe in this process and store it as one run with its design table."""
    from ..jobs import calculate_recipe_chunk
    options = options or {}
    d = recipe.materialise()
    meta = recipe.run_meta()
    run = repo.create_run(meta["mode"], settings=options, source=meta.get("source"), axes=meta.get("axes"),
                          elements=meta.get("elements"), expected=len(d["comps"]))
    chunk = calculate_recipe_chunk(engine, recipe, d["comps"], d["names"], d["variables"], d["blocks"],
                                   d["sources"] if isinstance(d["sources"], str) else recipe.kind, options)
    repo.append_chunk(run, chunk)
    repo.finalize_run(run, "complete")
    return run


def store_singles(repo, engine, comps, options: dict | None = None, mode: str = "single") -> tuple[int, range]:
    rows = [ResultRow(alloy_name(c), c, engine.calculate(c, **(options or {})), mode) for c in comps]
    run = repo.create_run(mode, settings=options or {}, elements=[], expected=len(rows))
    rng = repo.append_results(run, rows)
    repo.finalize_run(run, "complete")
    return run, rng
