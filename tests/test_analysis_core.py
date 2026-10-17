"""Qt-free Analysis core: statistics conventions, collection scopes, repository queries, plot rules and
the Analysis state machine - checked against the canonical sample data (ANALYSIS_FIGMA_SAMPLE_DATA.md)."""

from __future__ import annotations

import math

import pytest

from hea_calc.core.analysis import samples
from hea_calc.core.analysis import state as S
from hea_calc.core.analysis.plotting import (BINNED, HEATMAP, LINE, RAW, SAMPLED, SCATTER, PlotConfiguration,
                                             available_types, default_config, representation_text, validate)
from hea_calc.core.analysis.queries import QueryCancelled, ScopeQuery, nice_bin_width, run_metrics
from hea_calc.core.analysis.scope import (FILTERED, CollectionScope, ResolvedScope, filter_text,
                                          freeze_filters)
from hea_calc.core.analysis.stats import describe, quantile_type7
from hea_calc.core.engine import NA_ERROR, NA_MISSING_DATA, NA_UNDEFINED
from hea_calc.core.repository import ResultRepository, ViewTask
from hea_calc.core.results import ModelFilter, RangeFilter


# ====================================================================== statistics conventions
def test_type7_quantiles_known_values():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert quantile_type7(xs, 0.25) == pytest.approx(1.75)
    assert quantile_type7(xs, 0.5) == pytest.approx(2.5)
    assert quantile_type7(xs, 0.75) == pytest.approx(3.25)
    assert quantile_type7([5.0], 0.25) == 5.0
    assert quantile_type7([], 0.5) is None


def test_type7_matches_numpy_when_available():
    np = pytest.importorskip("numpy")
    import random
    rnd = random.Random(7)
    for n in (2, 3, 5, 10, 101):
        xs = sorted(rnd.uniform(-5, 5) for _ in range(n))
        for p in (0.25, 0.5, 0.75):
            assert quantile_type7(xs, p) == pytest.approx(float(np.quantile(xs, p)))


def test_describe_excludes_missing_and_uses_n_minus_1():
    d = describe([1.0, None, 3.0, float("nan")])
    assert d["n_valid"] == 2 and d["n_missing"] == 2
    assert d["mean"] == 2.0 and d["sd"] == pytest.approx(math.sqrt(2.0))
    one = describe([4.0])
    assert one["sd"] is None and one["median"] == 4.0
    empty = describe([None])
    assert empty["n_valid"] == 0 and empty["mean"] is None


# ====================================================================== fixtures
@pytest.fixture(scope="module")
def world(tmp_path_factory, engine):
    repo = ResultRepository(engine, root=tmp_path_factory.mktemp("analysis"))
    c1 = samples.store_recipe(repo, engine, samples.c1_recipe())
    e1 = samples.store_recipe(repo, engine, samples.e1_recipe())
    e2 = samples.store_recipe(repo, engine, samples.e2_recipe())
    singles, rng = samples.store_singles(repo, engine, [samples.S1, samples.S2, samples.S5, {"Fe": 1}])
    multi = samples.store_recipe(repo, engine, samples.expression_recipe(
        "AlxCoCrFeNi\n\nAlxCoCrFeNiTi0.1", {"x": (0.0, 1.0, 0.25)}))
    con = repo.reader_connection()
    yield {"repo": repo, "con": con, "c1": c1, "e1": e1, "e2": e2, "singles": singles, "single_ids": rng,
           "multi": multi}
    con.close()
    repo.close()


def sq(world, scope):
    return ScopeQuery(world["con"], scope, world["repo"].get_run(scope.run_id))


# ====================================================================== C1 canonical numbers
def test_c1_population_families_and_sizes(world):
    pop = sq(world, CollectionScope(world["c1"])).population()
    assert pop["n"] == 341 and pop["n_error"] == 0
    assert [(k, n) for k, _s, n in pop["families"]] == [("Al-Co-Cr-Fe-Mn-Ni", 300), ("Al-Co-Cr-Fe-Ni", 30),
                                                         ("Co-Cr-Fe-Mn-Ni", 10), ("Co-Cr-Fe-Ni", 1)]
    assert pop["sizes"] == {4: 1, 5: 40, 6: 300}


def test_c1_statistics_match_sample_data(world):
    st = sq(world, CollectionScope(world["c1"])).statistics(["dhmix", "delta", "vec", "omega", "phi_king"])
    m = st["metrics"]
    assert st["n"] == 341 and st["exact"]
    h = m["dhmix"]
    assert (round(h["mean"], 2), round(h["sd"], 2), round(h["min"], 2), round(h["q1"], 2), round(h["median"], 2),
            round(h["q3"], 2), round(h["max"], 2)) == (-10.16, 3.00, -14.28, -12.78, -10.76, -7.77, -3.75)
    d = m["delta"]
    assert (round(d["median"], 2), round(d["q1"], 2), round(d["q3"], 2)) == (5.28, 4.34, 5.82)
    assert (round(m["phi_king"]["median"], 2), round(m["omega"]["q3"], 2)) == (0.26, 3.18)
    assert all(v["n_valid"] == 341 and v["n_missing"] == 0 for v in m.values())


def test_sql_statistics_equal_reference_implementation(world):
    scope = CollectionScope(world["c1"])
    q = sq(world, scope)
    frm, where, params = scope.sql()
    for key in ("dhmix", "lambda", "gamma", "dg_max"):
        values = [r[0] for r in world["con"].execute(f'SELECT r."{key}" FROM {frm} WHERE {where}', params)]
        ref = describe(values)
        got = q.statistics([key])["metrics"][key]
        for k in ("mean", "sd", "min", "q1", "median", "q3", "max"):
            assert got[k] == pytest.approx(ref[k], rel=1e-12, abs=1e-12), (key, k)


def test_tukey_fences_convention():
    """Brief §35: Q1 − 1.5 IQR / Q3 + 1.5 IQR; no fences (no warning) for IQR = 0 or too few values."""
    from hea_calc.core.analysis.stats import TUKEY_MIN_N, tukey_fences, tukey_outliers
    assert tukey_fences(2.0, 4.0, 20) == (-1.0, 7.0)
    assert tukey_fences(3.0, 3.0, 100) is None, "IQR = 0: the method is not meaningful"
    assert tukey_fences(2.0, 4.0, TUKEY_MIN_N - 1) is None, "too few valid values"
    assert tukey_fences(None, 4.0, 20) is None
    # 22 finite values: Q1 5.25, Q3 15.75, fences −10.5 … 31.5
    xs = list(range(1, 21)) + [100.0, -50.0, None, float("nan")]
    assert tukey_outliers(xs) == (1, 1), "values strictly outside the fences; missing values are not counted"
    assert tukey_outliers([5.0] * 30 + [9.0]) is None


def test_sql_outlier_count_equals_reference_implementation(world):
    """``ScopeQuery.outliers`` counts in SQL exactly what the reference implementation counts; values are
    counted, never removed (the statistics of the metric are unchanged)."""
    from hea_calc.core.analysis.stats import tukey_outliers
    scope = CollectionScope(world["c1"])
    q = sq(world, scope)
    frm, where, params = scope.sql()
    for key in ("omega", "dhmix", "delta", "vec"):
        values = [r[0] for r in world["con"].execute(f'SELECT r."{key}" FROM {frm} WHERE {where}', params)]
        ref = tukey_outliers(values)
        got = q.outliers(key)
        assert got["metric"] == key and got["n_valid"] == 341
        if ref is None:
            assert got["fences"] is None and got["n_low"] == got["n_high"] == 0
        else:
            assert (got["n_low"], got["n_high"]) == ref, key
    assert q.statistics(["omega"])["metrics"]["omega"]["n_valid"] == 341, "outliers stay in the analysis"


def test_two_pass_exact_quartiles_equal_the_full_sort(world, monkeypatch):
    """The bin-selection path (used from QUANTILE_SELECT_MIN values) returns exactly the quartiles of one sort of
    every value - continuous descriptors through the selection, discrete ones (VEC) through the fallback."""
    from hea_calc.core.analysis import queries as Q
    monkeypatch.setattr(Q, "QUANTILE_SELECT_MIN", 0)
    from hea_calc.core.analysis.metrics import STATISTICS_ELIGIBLE
    from hea_calc.core.analysis.stats import QUARTILES, type7_positions
    for scope in (CollectionScope(world["c1"]), CollectionScope(world["e1"])):
        q = sq(world, scope)
        for key in STATISTICS_ELIGIBLE:
            st = q.statistics([key])["metrics"][key]
            n = st["n_valid"]
            if not n:
                continue
            m = q.metric(key)
            need = {p: type7_positions(n, p) for p in QUARTILES}
            ref = q._quantiles_sorted(m, n, q._from(m.needs_design), need)
            assert (st["q1"], st["median"], st["q3"]) == ref, key


def test_approximate_quartiles_are_disclosed_and_within_one_bin(world):
    q = sq(world, CollectionScope(world["c1"]))
    exact = q.statistics(["dhmix"])
    approx = q.statistics(["dhmix"], exact_limit=10)
    assert exact["exact"] and not approx["exact"]
    a, e = approx["metrics"]["dhmix"], exact["metrics"]["dhmix"]
    for k in ("q1", "median", "q3"):
        assert abs(a[k] - e[k]) <= a["bin_width"] + 1e-12
    assert a["mean"] == e["mean"] and a["min"] == e["min"]          # exact measures stay exact


def test_c1_model_distributions_and_denominators(world):
    d = sq(world, CollectionScope(world["c1"])).distribution()["models"]
    expect = {"M1": {"SS": 341}, "M2": {"SS": 203, "MP": 138}, "M3": {"SS": 341}, "M4": {"SS": 54, "SS+IM": 287},
              "M5": {"SS": 69, "MP": 272}, "M6": {"SS": 11, "IM": 330}, "M7": {"SS": 43, "IM": 298},
              "M8": {"SS": 12, "MP": 329}}
    for k, classes in expect.items():
        assert d[k]["classes"] == classes, k
        assert d[k]["population"] == d[k]["evaluated"] == 341 and d[k]["na"] == 0
        assert d[k]["status"] == {"in_domain": 341}
    assert "SS+IM" not in d["M1"]["classes"] and "MG" not in d["M2"]["classes"]    # absent, never zero


def test_c1_histogram_and_box_plot(world):
    q = sq(world, CollectionScope(world["c1"]))
    h = q.histogram("delta")
    assert h["width"] == 0.5 and h["edges"][0] == 0.0
    assert h["counts"] == [1, 0, 1, 2, 5, 11, 19, 25, 33, 46, 59, 94, 45] and sum(h["counts"]) == 341
    box = q.statistics(["delta"], group="family")["metrics"]["delta"]
    a = box["Al-Co-Cr-Fe-Ni"]
    assert a["n_valid"] == 30
    assert (round(a["min"], 2), round(a["q1"], 2), round(a["median"], 2), round(a["q3"], 2), round(a["max"], 2)) \
        == (1.66, 4.27, 5.35, 5.97, 6.35)
    assert box["Co-Cr-Fe-Ni"]["median"] == pytest.approx(0.2977, abs=1e-4)


def test_nice_bin_width():
    assert nice_bin_width(0.3, 6.35, 20) == 0.5
    assert nice_bin_width(0, 1, 10) == 0.1


# ====================================================================== scopes
def test_run_isolation(world):
    """A collection never mixes runs (rule R1)."""
    assert sq(world, CollectionScope(world["c1"])).count() == 341
    assert sq(world, CollectionScope(world["e1"])).count() == 41
    assert sq(world, CollectionScope(world["e2"])).count() == 121


def test_filtered_scope_uses_table_semantics(world):
    flt = freeze_filters([ModelFilter("M8", {"SS"})])
    scope = CollectionScope(world["c1"], FILTERED, filters=flt)
    assert sq(world, scope).count() == 12
    rng = freeze_filters([RangeFilter("delta", 6.0, None)])
    n = sq(world, CollectionScope(world["c1"], FILTERED, filters=rng)).count()
    assert n == sum(1 for v in world["con"].execute(
        "SELECT delta FROM results WHERE run_id=?", (world["c1"],)) if v[0] >= 6.0)
    assert filter_text(flt) == "M8 = SS"


def test_family_size_and_block_restrictions(world):
    base = CollectionScope(world["c1"])
    assert sq(world, base.with_restrictions(families=["Co-Cr-Fe-Mn-Ni"])).count() == 10
    assert sq(world, base.with_restrictions(sizes=[5])).count() == 40
    both = base.with_restrictions(families=["Al-Co-Cr-Fe-Ni", "Co-Cr-Fe-Mn-Ni"], sizes=[5])
    assert sq(world, both).count() == 40 and both.restricted == 2
    multi = CollectionScope(world["multi"])
    pop = sq(world, multi).population()
    assert set(pop["blocks"]) == {0, 1}
    assert sq(world, multi.with_restrictions(blocks=[1])).count() == pop["blocks"][1]


def test_collection_populations_are_full_and_filtered_only(world):
    """Release reconciliation: the Results checkbox column and the "Checked results" population are gone;
    a collection is the full or the filtered result set of one run (plus restrictions)."""
    from hea_calc.core.analysis import scope as SC
    assert SC.BASES == (SC.FULL, SC.FILTERED)
    assert set(SC.BASE_LABELS.values()) == {"Full result set", "Filtered result set"}
    with pytest.raises(ValueError):
        CollectionScope(world["c1"], "checked")


def test_show_in_results_table_id_set_is_explicit(world):
    """The one id-set mechanism left: an explicit id table for the table's id filter (Show in results table)."""
    from hea_calc.core.analysis.idsets import drop_id_table, id_table
    from hea_calc.core.results import IdSetFilter
    repo = world["repo"]
    ids = [r[0] for r in world["con"].execute("SELECT result_id FROM results WHERE run_id=? LIMIT 7", (world["c1"],))]
    name = id_table(repo, ids)
    flt = freeze_filters([IdSetFilter(name, frozenset(ids))])
    scope = CollectionScope(world["c1"], FILTERED, filters=flt)
    assert sq(world, scope).count() == 7
    drop_id_table(repo, name)


def test_scope_identity_ignores_scope_id(world):
    a, b = CollectionScope(world["c1"]), CollectionScope(world["c1"])
    assert a == b and a.key() == b.key() and a.scope_id != b.scope_id
    assert a.key() != a.with_restrictions(sizes=[5]).key()


def test_removal_and_cleared_rows_leave_the_population(engine, tmp_path):
    repo = ResultRepository(engine, root=tmp_path)
    try:
        run = samples.store_recipe(repo, engine, samples.e1_recipe())
        con = repo.reader_connection()
        scope = CollectionScope(run)
        info = repo.get_run(run)
        assert ScopeQuery(con, scope, info).count() == 41
        first = info.first_id
        repo.delete_results([first, first + 1])
        assert ScopeQuery(con, scope, info).count() == 39
        assert ScopeQuery(con, scope, info, workspace_lo=info.last_id + 1).count() == 0   # table cleared
        con.close()
    finally:
        repo.close()


# ====================================================================== missing values
def test_missing_values_are_excluded_and_classified(world):
    q = sq(world, CollectionScope(world["singles"]))
    st = q.statistics(["dhim", "omega", "dhmix"])["metrics"]
    # S1, S2 (Si: no Troparevsky data), S5 (CoNi: omega undefined), Fe (not evaluable)
    assert st["dhim"]["n_valid"] == 2 and st["dhim"]["missing_data"] == 1 and st["dhim"]["error"] == 1
    assert st["omega"]["undefined"] == 1 and st["omega"]["error"] == 1 and st["omega"]["n_valid"] == 2
    d = q.distribution()["models"]
    assert d["M6"]["na_by_kind"] == {NA_MISSING_DATA: 1, NA_ERROR: 1}
    assert d["M1"]["na_by_kind"] == {NA_UNDEFINED: 1, NA_ERROR: 1}
    assert d["M6"]["evaluated"] + d["M6"]["na"] == d["M6"]["population"] == 4
    pts = q.points("delta", "dhim")
    assert pts["n_missing"] == 2 and pts["n_shown"] == 2      # never drawn at zero


# ====================================================================== plot data
def test_scatter_raw_and_sampled_disclosure(world):
    q = sq(world, CollectionScope(world["c1"]))
    raw = q.points("delta", "dhmix", "model:M2")
    assert raw["representation"] == RAW and raw["n_shown"] == 341
    assert sorted(set(raw["c"])) == ["MP", "SS"]
    smp = q.points("delta", "dhmix", "model:M2", budget=100, sample_target=100)
    assert smp["representation"] == SAMPLED and 0 < smp["n_shown"] < 341 and smp["n_valid"] == 341
    assert smp["category_counts"] == {"SS": 203, "MP": 138}        # legend counts refer to the population
    again = q.points("delta", "dhmix", "model:M2", budget=100, sample_target=100)
    assert list(again["ids"]) == list(smp["ids"])                  # fixed seed: reproducible
    assert representation_text(SAMPLED, shown=20000, population=1039776) == "Sample · 20,000 of 1,039,776 points"
    assert representation_text(RAW, shown=341) == "All 341 points"
    assert representation_text(BINNED, bins=(200, 200), population=1039776) == \
        "Binned · 200 × 200 cells · 1,039,776 results"


def test_binned_counts_are_complete(world):
    b = sq(world, CollectionScope(world["c1"])).binned("delta", "dhmix", (20, 20), "model:M2")
    assert sum(c[2] for c in b["cells"]) == 341
    assert all(c[3][0] in ("SS", "MP") for c in b["cells"])


def test_line_series_is_ordered_and_heatmap_complete(world):
    s = sq(world, CollectionScope(world["e1"])).series("var:x", ["vec"])
    assert len(s["x"]) == 41 and s["x"] == sorted(s["x"]) and s["duplicates"] == 0
    assert s["y"]["vec"][0] == pytest.approx(8.25) and s["y"]["vec"][-1] == pytest.approx(6.5)
    g = sq(world, CollectionScope(world["e2"])).grid("var:x", "var:y", "delta")
    assert g["complete"] and len(g["xs"]) == len(g["ys"]) == 11 and g["missing_cells"] == 0
    assert g["cells"][(0.0, 0.0)][0] == pytest.approx(0.2977, abs=1e-4)
    assert round(g["cells"][(0.5, 0.3)][0], 2) == 5.74
    gm = sq(world, CollectionScope(world["e2"])).grid("var:x", "var:y", "model:M2")
    counts = {}
    for v, _rid, _name in gm["cells"].values():
        counts[v] = counts.get(v, 0) + 1
    assert counts == {"SS": 27, "MP": 42, "MG": 52}


def test_line_rejects_unordered_axis(world):
    with pytest.raises(ValueError):
        sq(world, CollectionScope(world["c1"])).series("delta", ["vec"])


def test_query_cancellation(world):
    q = sq(world, CollectionScope(world["c1"]))
    q.cancel()
    with pytest.raises(QueryCancelled):
        q.population()


# ====================================================================== plot configuration rules
def test_defaults_by_run_type(world):
    repo = world["repo"]
    assert default_config(repo.get_run(world["c1"])).type == SCATTER
    assert default_config(repo.get_run(world["c1"])).color == "model:M2"
    e1 = default_config(repo.get_run(world["e1"]))
    assert (e1.type, e1.x, e1.y) == (LINE, "var:x", "vec")
    e2 = default_config(repo.get_run(world["e2"]))
    assert (e2.type, e2.x, e2.y, e2.value) == (HEATMAP, "var:x", "var:y", "delta")
    assert default_config(repo.get_run(world["multi"])).color == "block"
    assert default_config(repo.get_run(world["singles"])).color == "family"


def test_invalid_configurations_are_blocked(world):
    repo = world["repo"]
    c1 = repo.get_run(world["c1"])
    v = validate(PlotConfiguration(LINE, "grid:Al", "vec"), c1)
    assert not v.ok and v.title == "A line plot needs an ordered axis" and v.fix == "Use scatter plot"
    assert not validate(PlotConfiguration(SCATTER, "delta", "delta"), c1).ok
    assert validate(PlotConfiguration(SCATTER, "delta", "dhmix", "model:M2"), c1).ok
    e2 = repo.get_run(world["e2"])
    v = validate(PlotConfiguration(LINE, "var:x", "vec"), e2)
    assert not v.ok and "Fix y" in v.title
    assert validate(PlotConfiguration(LINE, "var:x", "vec", fixed=(("var:y", 0.0),)), e2).ok
    assert validate(PlotConfiguration(HEATMAP, "var:x", "var:y", value="model:M2"), e2).ok
    assert HEATMAP in available_types(e2) and HEATMAP not in available_types(c1)


def test_metric_registry_has_units_and_symbols(world):
    for m in run_metrics(world["repo"].get_run(world["e2"])):
        assert m.symbol and m.name
        assert "(" in m.axis_title()
    ids = {m.id for m in run_metrics(world["repo"].get_run(world["e2"]))}
    assert {"var:x", "var:y", "at:Al", "at:Ti", "dhmix", "n_elements"} <= ids


# ====================================================================== state machine
def _resolved(base="full", filters=(), version=0):
    _ = version
    scope = CollectionScope(3, base, filters=filters)
    return ResolvedScope(scope, 10, "now", filter_snapshot=filters)


def test_double_click_changes_only_the_active_composition():
    s = S.AnalysisState(context=S.COLLECTION, coll_tab="plots", resolved=_resolved())
    t = S.double_click(s, 42)
    assert t.active == 42 and t.composition_badge
    assert (t.context, t.coll_tab, t.resolved, t.plot) == (s.context, s.coll_tab, s.resolved, s.plot)


def test_filter_changes_only_flag_the_scope():
    flt = freeze_filters([ModelFilter("M8", {"SS"})])
    s = S.AnalysisState(resolved=_resolved(FILTERED, flt))
    t = S.table_filter_changed(s, ())
    assert t.stale == S.STALE_FILTER and t.resolved is s.resolved
    assert S.table_filter_changed(t, flt).stale is None               # filter restored
    full = S.AnalysisState(resolved=_resolved())
    assert S.table_filter_changed(full, ()).stale is None             # full set: unaffected
    assert not hasattr(S, "checked_changed") and not hasattr(S, "STALE_CHECKED")


def test_removal_rules():
    s = S.AnalysisState(active=5, selection=frozenset({5, 6, 7}), inspector=6, resolved=_resolved())
    t = S.results_removed(s, [5, 6])
    assert t.active_gone == S.REMOVED and t.selection == frozenset({7}) and t.inspector is None
    assert t.data_version == s.data_version + 1 and t.resolved is s.resolved
    c = S.table_cleared(s)
    assert c.scope_gone and c.active_gone == S.REMOVED
    r = S.table_cleared(s, recalculated=True)
    assert r.active_gone == S.RECALCULATED


def test_view_changes_preserve_state():
    s = S.AnalysisState(active=9, model="M6", comp_tab="model_details", resolved=_resolved(),
                        selection=frozenset({1, 2}), plot=PlotConfiguration(SCATTER, "vec", "omega"))
    t = S.set_expanded(S.switch_context(S.switch_context(s, S.COLLECTION), S.COMPOSITION), True)
    t = S.set_expanded(t, False)
    for f in ("active", "model", "comp_tab", "resolved", "selection", "plot", "coll_tab"):
        assert getattr(t, f) == getattr(s, f), f


def test_update_collection_keeps_plot_and_surviving_selection():
    s = S.AnalysisState(resolved=_resolved(), stale=S.STALE_FILTER, selection=frozenset({1, 2, 3}),
                        plot=PlotConfiguration(SCATTER, "vec", "omega"))
    r = _resolved(FILTERED)
    t = S.update_collection(s, r, surviving=[2, 3, 99])
    assert t.resolved is r and t.stale is None and t.selection == frozenset({2, 3}) and t.plot == s.plot


def test_point_activation_only_from_explicit_action():
    s = S.AnalysisState(context=S.COLLECTION, coll_tab="plots")
    t = S.select_points(s, [11])
    assert t.context == S.COLLECTION and t.active is None and t.inspector == 11
    u = S.analyse_point(t, 11)
    assert u.active == 11 and u.context == S.COMPOSITION and u.coll_tab == "plots"


def test_expression_plan_counts_duplicates_per_block(tmp_path):
    recipe = samples.expression_recipe("AlxCoCrFeNi\n\nAlyCoCrFeNi", {"x": (0.0, 1.0, 0.25), "y": (0.0, 1.0, 0.25)})
    valid, skipped, dups, total, by_block = recipe.plan(str(tmp_path / "plan.bin"), 64)
    assert (valid, skipped, dups, total) == (5, 0, 5, 10)
    assert by_block == {1: 5}, "every composition of block 2 was generated first by block 1"


def test_run_source_update_is_merged(engine, tmp_path):
    repo = ResultRepository(engine, root=tmp_path)
    try:
        run = repo.create_run("expression", source={"text": "AlxCoCrFeNi"})
        repo.update_run_source(run, {"duplicates": 3, "duplicates_by_block": {"1": 3}})
        src = repo.get_run(run).source
        assert src == {"text": "AlxCoCrFeNi", "duplicates": 3, "duplicates_by_block": {"1": 3}}
    finally:
        repo.close()
