"""Before / after measurement of the exact-quartile query (Collection statistics), on the real repository.

    .venv/Scripts/python.exe tools/quantile_bench.py [--size 1m] [--json out.json]

Stores ``size`` synthetic results (``tools/synthetic.py``: replicated real engine results, for measurements only)
through the normal writer, then times ``ScopeQuery.statistics`` for the seven default Statistics metrics of a
full-result-set collection twice per method: the full sort of every value (``ROW_NUMBER`` window, the method before
the optimisation) and the two-pass bin selection.  Both must return identical quartiles; the timings are written to
stdout / ``--json`` and recorded in ``design/implementation/performance.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1m")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from analysis_perf import parse_size
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    from perf_harness import make_window
    from synthetic import fill
    from hea_calc.core.analysis import queries as Q
    from hea_calc.core.analysis.metrics import STATS_DEFAULT
    from hea_calc.core.analysis.queries import ScopeQuery
    from hea_calc.core.analysis.scope import CollectionScope

    n = parse_size(args.size)
    win = make_window(app)
    try:
        run = fill(win.repo, n, win.engine, chunk=20_000)
        con = win.repo.reader_connection()
        scope = CollectionScope(run)
        metrics = list(STATS_DEFAULT)
        out = {"size": n, "metrics": metrics, "runs": []}
        answers = {}
        for method, limit in (("sort", 10 ** 12), ("select", Q.QUANTILE_SELECT_MIN),
                              ("sort", 10 ** 12), ("select", Q.QUANTILE_SELECT_MIN)):
            Q.QUANTILE_SELECT_MIN = limit
            q = ScopeQuery(con, scope, win.repo.get_run(run))
            t0 = time.perf_counter()
            st = q.statistics(metrics)
            dt = time.perf_counter() - t0
            ans = {k: (v["q1"], v["median"], v["q3"]) for k, v in st["metrics"].items()}
            answers.setdefault(method, ans)
            out["runs"].append({"method": method, "seconds": round(dt, 3), "exact": st["exact"]})
            print(f"{method:6s} {dt:7.2f} s  exact={st['exact']}", flush=True)
        # per metric: quartile time of each method and the distinct-value count (ties decide the path)
        q = ScopeQuery(con, scope, win.repo.get_run(run))
        frm_cache = {}
        out["per_metric"] = []
        for key in metrics:
            m = q.metric(key)
            frm = frm_cache.setdefault(m.needs_design, q._from(m.needs_design))
            row = con.execute(f"SELECT COUNT({m.sql}), MIN({m.sql}), MAX({m.sql}), COUNT(DISTINCT {m.sql}) "
                              f"FROM {frm} WHERE {q.where}", q.params).fetchone()
            nv, mn, mx, distinct = row
            need = {p: Q.type7_positions(nv, p) for p in Q.QUARTILES}
            t0 = time.perf_counter()
            q._quantiles_sorted(m, nv, frm, need)
            t_sort = time.perf_counter() - t0
            Q.QUANTILE_SELECT_MIN = 20_000
            t0 = time.perf_counter()
            q._quantiles_exact(m, nv, frm, mn, mx)
            t_sel = time.perf_counter() - t0
            out["per_metric"].append({"metric": key, "distinct": distinct, "sortS": round(t_sort, 3),
                                      "selectS": round(t_sel, 3)})
            print(f"  {key:11s} distinct={distinct:>8,}  sort {t_sort:6.2f} s  select {t_sel:6.2f} s", flush=True)
        out["identical"] = answers["sort"] == answers["select"]
        print("identical quartiles:", out["identical"])
        if args.json:
            Path(args.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    finally:
        win.close()


if __name__ == "__main__":
    main()
