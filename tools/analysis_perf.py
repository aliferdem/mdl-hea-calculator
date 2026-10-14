"""Analysis performance harness: repository-backed Collection queries at 100 k / 1 M / 10 M results.

    .venv/Scripts/python.exe tools/analysis_perf.py [--sizes 100k,1m] [--offscreen] [--json out.json]

For each size a run of *synthetic* rows (``tools/synthetic.py``: replicated engine results, labelled SYN…,
for storage / query measurements only) is stored through the normal single writer, then the real
application window resolves a full-result-set collection and requests, through the Analysis controller and
its background query thread, exactly what the views request: scope count, population (families / sizes),
statistics of six metrics (exact quartiles up to ``EXACT_QUANTILE_MAX``, binned above), a histogram, a
200 × 200 binned scatter, a sampled scatter, and the M1-M8 distributions.  A 10 ms ``QTimer`` heartbeat runs
on the GUI thread throughout: the maximum event-loop gap shows whether a query ever blocked the UI.
Results go to stdout (and ``--json``); the measured table is kept in ``design/implementation/performance.md``.
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


def parse_size(s: str) -> int:
    s = s.strip().lower()
    mult = 1_000_000 if s.endswith("m") else 1_000 if s.endswith("k") else 1
    return int(float(s.rstrip("mk")) * mult)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="100k,1m")
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.stdout.reconfigure(encoding="utf-8")
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    from perf_harness import Heartbeat, make_window, wait_until
    from synthetic import fill
    from hea_calc.core.analysis import state as S
    from hea_calc.core.analysis.queries import DIM_FAMILY
    hb = Heartbeat()
    results = []
    for label in args.sizes.split(","):
        n = parse_size(label)
        win = make_window(app)
        try:
            t0 = time.perf_counter()
            run = fill(win.repo, n, win.engine, chunk=20_000)
            insert_s = time.perf_counter() - t0
            win.table.model.refresh_committed()
            c = win.analysis_ctl
            c.run_finished(run)
            win._check_details()
            app.processEvents()
            out = {"size": n, "insertS": round(insert_s, 1)}
            hb.start()
            c.apply(S.switch_context, S.COLLECTION)

            def timed_slot(name, request, slot):
                print(f"  {name}…", flush=True)
                c.data.pop(slot, None)
                c.data_keys.pop(slot, None)
                t = time.perf_counter()
                request()
                ok = wait_until(app, lambda: slot in c.data or not c.busy(slot), 1800)
                out[name] = round(time.perf_counter() - t, 3) if ok else None
                return c.data.get(slot)

            print(f"{n:,} rows stored in {insert_s:.1f} s", flush=True)
            t = time.perf_counter()
            c.scope_for(run, "full")
            wait_until(app, lambda: c.state.resolved is not None and c.state.scope.run_id == run, 1800)
            out["resolveScopeS"] = round(time.perf_counter() - t, 3)
            timed_slot("populationS", lambda: c.run_query("population", lambda sq: sq.population(), use_cache=False),
                       "population")
            metrics = ["dhmix", "dsmix", "delta", "vec", "omega", "phi_king"]
            st = timed_slot("statistics6S", lambda: c.run_query("stats", lambda sq: sq.statistics(metrics),
                                                                   use_cache=False), "stats")
            out["statisticsExact"] = bool(st and st["exact"])
            timed_slot("histogramS", lambda: c.run_query("hist", lambda sq: sq.histogram("delta"), use_cache=False),
                       "hist")
            b = timed_slot("binned200S", lambda: c.run_query("perf_binned", lambda sq: sq.binned("delta", "dhmix", (200, 200),
                                                                                         "model:M2"),
                                                               use_cache=False), "perf_binned")
            out["binnedCells"] = len(b["cells"]) if b else None
            p = timed_slot("sampledScatterS", lambda: c.run_query("plot2", lambda sq: sq.points("delta", "dhmix",
                                                                                               "model:M2"),
                                                                  use_cache=False), "plot2")
            if p:
                out["scatterRepresentation"] = p["representation"]
                out["scatterPointsDrawn"] = p["n_shown"]
            timed_slot("distributionS", lambda: c.run_query("dist", lambda sq: sq.distribution(), use_cache=False),
                       "dist")
            timed_slot("boxByFamilyS", lambda: c.run_query("box", lambda sq: sq.statistics(["delta"], group=DIM_FAMILY),
                                                           use_cache=False), "box")
            # the plot as the user sees it: Plots tab, default scatter (automatic representation)
            t = time.perf_counter()
            c.apply(S.set_tab, "plots")
            wait_until(app, lambda: win.analysis.collection.plot is not None and
                       win.analysis.collection.plot.spec is not None, 1800)
            out["plotsTabS"] = round(time.perf_counter() - t, 3)
            out["heartbeat"] = {k: v for k, v in hb.stop().items() if k in ("maxGapMs", "p99GapMs", "gapsOver100ms",
                                                                            "gapsOver250ms", "bigGaps")}
            out["dbMiB"] = round(sum(win.repo.size_bytes().values()) / 2**20, 1)
            print(json.dumps(out))
            results.append(out)
        finally:
            win.close()
            app.processEvents()
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
