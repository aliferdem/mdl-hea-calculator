"""Composition space range bases at. ratio / at.% / wt.% / mass (release reconciliation, Composition setup).

The wt.% and mass bases reuse the Single-composition conversion (``composition.to_fractions``): wt.% values
sum to 100 like at.% values; masses are free proportional amounts like the Single Mass column (the batch
total is the sum of the masses), so proportional mass vectors are one alloy.
"""

from __future__ import annotations

import pytest

from hea_calc.core import composition as C
from hea_calc.core.generation import RangeError, SweepSpec, count_space, iter_space, summarize_space
from hea_calc.core.recipes import SweepRecipe

TOL = 1e-9


def _fractions(comp):
    tot = sum(comp.values())
    return {el: v / tot for el, v in comp.items()}


def test_wt_space_counts_like_at_and_converts_with_the_shared_conversion():
    specs = (SweepSpec("Fe", 10, 50, 10), SweepSpec("Ni", 10, 50, 10), SweepSpec("Cr", 10, 50, 10))
    at = SweepRecipe(specs, "at")
    wt = SweepRecipe(specs, "wt")
    assert wt.estimate() == at.estimate() == wt.count() == count_space(list(specs), "wt").count
    grid = list(wt.iterate())
    assert all(abs(sum(g.values()) - 100) < TOL for g in grid)
    for g in grid:
        comp = wt.atomic(g)
        x = C.to_fractions(g, "wt")
        assert _fractions(comp) == pytest.approx(x, abs=TOL)
        # round trip: the at.% composition expressed in wt.% is the entered grid point
        assert C.from_fractions(x, "wt") == pytest.approx(g, abs=1e-9)
    # wt.% points are distinct alloys (fixed sum: no proportional duplicates)
    keys = {tuple(round(v, 12) for v in _fractions(wt.atomic(g)).values()) for g in grid}
    assert len(keys) == len(grid)


def test_mass_space_dedupes_proportional_batches_like_ratio():
    specs = (SweepSpec("Fe", 1, 2, 1), SweepSpec("Ni", 1, 2, 1))
    mass = SweepRecipe(specs, "mass")
    grid = list(mass.iterate())
    # (1,1) and (2,2) g are the same alloy; (1,2) and (2,1) differ
    assert sorted(tuple(g.values()) for g in grid) == [(1.0, 1.0), (1.0, 2.0), (2.0, 1.0)]
    assert mass.count() == summarize_space(list(specs), "mass").compositions == 3
    comps = [mass.atomic(g) for g in grid]
    for g, c in zip(grid, comps):
        assert _fractions(c) == pytest.approx(C.to_fractions(g, "mass"), abs=TOL)


def test_equivalent_compositions_agree_across_all_four_bases(engine):
    """CoCrFeMnNi entered as at. ratio, at.%, wt.% and mass gives one atomic composition and one result."""
    els = ["Co", "Cr", "Fe", "Mn", "Ni"]
    x = {el: 0.2 for el in els}
    wt = C.from_fractions(x, "wt")
    mass = C.from_fractions(x, "mass", total_mass=2.0)
    cases = {"ratio": {el: 1.0 for el in els}, "at": {el: 20.0 for el in els},
             "wt": {el: round(v, 6) for el, v in wt.items()}, "mass": {el: round(v, 6) for el, v in mass.items()}}
    results = {}
    for unit, values in cases.items():
        specs = tuple(SweepSpec(el, v, v, 0.0) for el, v in values.items())
        recipe = SweepRecipe(specs, unit)
        if unit == "wt":                      # rounding to 6 decimals: the entered sum must still be 100
            assert abs(sum(values.values()) - 100) < 1e-4
            continue
        grid = list(recipe.iterate())
        assert len(grid) == 1
        comp = recipe.atomic(grid[0])
        assert _fractions(comp) == pytest.approx(x, abs=1e-6), unit
        results[unit] = engine.calculate(comp)
    # wt.% through the conversion directly (the grid demands an exact 100 % sum)
    comp_wt = {el: 100 * v for el, v in C.to_fractions(wt, "wt").items()}
    assert _fractions(comp_wt) == pytest.approx(x, abs=1e-9)
    results["wt"] = engine.calculate(comp_wt)
    ref = results["ratio"]
    for unit, r in results.items():
        for k in ("dhmix", "dsmix", "delta", "vec", "omega"):
            assert r.descriptors[k] == pytest.approx(ref.descriptors[k], rel=1e-6, abs=1e-9), (unit, k)
        assert {m: o.label for m, o in r.models.items()} == {m: o.label for m, o in ref.models.items()}, unit


def test_design_keeps_the_entered_values_and_names_use_atomic_amounts():
    specs = (SweepSpec("Al", 10, 10, 0), SweepSpec("Ni", 90, 90, 0))
    r = SweepRecipe(specs, "wt")
    grid = list(r.iterate())
    comp = r.atomic(grid[0])
    assert list(r.design(grid)) == [10.0, 90.0]                 # wt.% coordinates, not at.%
    # names are the ATOMIC percentages, labelled as such since 2026-10-28 (a wt.% space's name is never its entered
    # weight percentages read as stoichiometry)
    assert r.name(comp) == C.percent_name(comp) + " (at.%)"
    assert abs(comp["Al"] - 100 * C.to_fractions({"Al": 10, "Ni": 90}, "wt")["Al"]) < 1e-12
    meta = r.run_meta()
    assert meta["source"]["unit"] == "wt" and meta["axes"][0]["unit"] == "wt.%"
    m = SweepRecipe(specs, "mass").run_meta()
    assert m["axes"][0]["unit"] == "g"


def test_invalid_bases_and_values_are_rejected():
    with pytest.raises(RangeError):
        SweepRecipe((SweepSpec("Fe", 1, 1, 0), SweepSpec("Ni", 1, 1, 0)), "kg")
    with pytest.raises(RangeError):
        list(iter_space([SweepSpec("Fe", -1, 1, 0.5), SweepSpec("Ni", 1, 1, 0)], "mass"))
    with pytest.raises(RangeError):
        count_space([SweepSpec("Fe", 5, 1, 1), SweepSpec("Ni", 1, 1, 0)], "wt")


def test_large_wt_space_counts_in_bounded_time():
    import time
    specs = [SweepSpec(el, 0, 100, 1, required=False) for el in ("Al", "Co", "Cr", "Fe", "Ni", "Ti", "Mn")]
    t0 = time.perf_counter()
    c = count_space(specs, "wt", stop_after=10 ** 15)
    assert c.count > 1_000_000 and time.perf_counter() - t0 < 5
    t0 = time.perf_counter()
    m = count_space(specs, "mass", stop_after=200_000)          # free basis: bounded, stops past the limit
    assert m.exceeds and time.perf_counter() - t0 < 5


def test_model_coverage_reports_missing_data_only(engine):
    cov = engine.model_coverage(["Co", "Cr", "Fe", "Mn", "Ni"])
    assert set(cov) == {f"M{i}" for i in range(1, 9)} and not any(cov.values())
    cov = engine.model_coverage(["Al", "Co", "Cr", "Fe", "Ni", "Si"])
    assert cov["M6"] and cov["M7"] and "Si" in cov["M6"]
    assert engine.model_coverage(["Fe"]) == {}
