"""Analysis benchmark: Collection queries on large result sets (no window).

    uv run tools/bench_analysis.py [--sizes 100k,1m] [--quick] [--allow-large] [--out bench_analysis.json]

For each size a run of synthetic rows (``tests/_support.py``: engine results of 50 alloys replicated, labelled
``SYN...``, for storage and query measurements only) is stored through the repository, then the queries the
Collection views make are timed directly on :class:`~hea_calc.core.analysis.queries.ScopeQuery`, the same objects the
Analysis controller runs on its background thread:

* retrieval and aggregation - row count and population (families and system sizes);
* statistics - the Statistics table for the default metrics with exact quartiles, and the binned (approximate)
  quartiles used above ``EXACT_QUANTILE_MAX``; statistics grouped by element family (box plots);
* quantiles - for every default metric, exact quartiles by one sort of all values and by two-pass selection, with
  the number of distinct values (ties decide the path); both methods must return identical quartiles;
* distributions - the M1-M8 class distribution, overall and by family;
* plot data - a histogram, a 200 x 200 binned scatter and a sampled scatter coloured by an M2 class.

Sizes above 1,000,000 need ``--allow-large``.  Results: one JSON line per size on stdout, and ``--out``.
"""

from __future__ import annotations

import argparse
import gc
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import Report, add_common_arguments, check_sizes, parse_sizes, process_peaks  # noqa: E402


def timed(out: dict, name: str, fn):
    t0 = time.perf_counter()
    value = fn()
    out[name] = round(time.perf_counter() - t0, 4)
    return value


def quantile_methods(q, metrics: list[str]) -> list[dict]:
    """Per metric: exact quartiles by sorting every value and by two-pass selection (forced), and whether they agree."""
    from hea_calc.core.analysis import queries as Q
    rows = []
    for key in metrics:
        m = q.metric(key)
        frm = q._from(m.needs_design)
        nv, mn, mx, distinct = q._exec(
            f"SELECT COUNT({m.sql}), MIN({m.sql}), MAX({m.sql}), COUNT(DISTINCT {m.sql}) FROM {frm} WHERE {q.where}",
            q.params).fetchone()
        if not nv:
            continue
        need = {p: Q.type7_positions(nv, p) for p in Q.QUARTILES}
        t0 = time.perf_counter()
        by_sort = q._quantiles_sorted(m, nv, frm, need)
        t_sort = time.perf_counter() - t0
        saved, Q.QUANTILE_SELECT_MIN = Q.QUANTILE_SELECT_MIN, 0        # force the selection path at every size
        try:
            t0 = time.perf_counter()
            by_select = q._quantiles_exact(m, nv, frm, mn, mx)
            t_select = time.perf_counter() - t0
        finally:
            Q.QUANTILE_SELECT_MIN = saved
        rows.append({"metric": key, "values": nv, "distinct": distinct, "sort_s": round(t_sort, 4),
                     "select_s": round(t_select, 4), "identical": tuple(by_sort) == tuple(by_select)})
    return rows


def measure(n: int) -> dict:
    from _support import fill
    from hea_calc.core.analysis.metrics import STATS_DEFAULT
    from hea_calc.core.analysis.queries import DIM_FAMILY, ScopeQuery
    from hea_calc.core.analysis.scope import CollectionScope
    from hea_calc.core.engine import default_engine
    from hea_calc.core.repository import ResultRepository
    engine = default_engine()
    repo = ResultRepository(engine, root=Path(tempfile.mkdtemp()) / "sessions")
    try:
        out = {"size": n, "data": "synthetic (engine results of 50 alloys replicated)"}
        run = timed(out, "insert_s", lambda: fill(repo, n, engine, chunk=20_000))
        out["db_mib"] = round(sum(repo.size_bytes().values()) / 2**20, 1)
        gc.collect()
        q = ScopeQuery(repo.reader_connection(), CollectionScope(run), repo.get_run(run))
        metrics = list(STATS_DEFAULT)
        out["rows"] = timed(out, "count_s", q.count)
        timed(out, "population_s", q.population)
        st = timed(out, "statistics_exact_s", lambda: q.statistics(metrics))
        out["statistics_exact"] = st["exact"]
        timed(out, "statistics_binned_s", lambda: q.statistics(metrics, exact_limit=0))
        timed(out, "statistics_by_family_s", lambda: q.statistics(["delta"], group=DIM_FAMILY))
        timed(out, "distribution_s", q.distribution)
        timed(out, "distribution_by_family_s", lambda: q.distribution(group=DIM_FAMILY))
        timed(out, "histogram_s", lambda: q.histogram("delta"))
        b = timed(out, "binned_200x200_s", lambda: q.binned("delta", "dhmix", (200, 200), "model:M2"))
        out["binned_cells"] = len(b["cells"])
        p = timed(out, "scatter_s", lambda: q.points("delta", "dhmix", "model:M2"))
        out["scatter_representation"], out["scatter_points"] = p["representation"], p["n_shown"]
        out["quantiles"] = quantile_methods(q, metrics)
        out["peak"] = process_peaks(None, repo)
        return out
    finally:
        repo.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sizes", default="100k")
    add_common_arguments(ap)
    args = ap.parse_args()
    if args.quick:
        args.sizes = "5k"
    sizes = parse_sizes(args.sizes)
    check_sizes(sizes, args.allow_large)
    rep = Report("bench_analysis", args)
    try:
        for n in sizes:
            rec = rep.emit(measure(n))
            if not all(r["identical"] for r in rec["quantiles"]):
                print("ERROR: sorted and selected quartiles differ", file=sys.stderr)
                sys.exit(1)
    finally:
        rep.close()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
