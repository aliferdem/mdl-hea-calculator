"""Analysis tab-loading benchmark: what the user waits for when opening Overview / Plots / Statistics / Models.

    .venv/Scripts/python.exe tools/analysis_loading_bench.py [--sizes 10k,100k,1m] [--expanded] [--offscreen]
           [--out design/implementation/analysis_loading_<label>.json] [--label before]

For each size a synthetic run (``tools/synthetic.py``, replicated engine results, storage/query measurement only)
is stored, the real window switches the Analysis panel to Collection and visits every tab twice (first visit =
cold, second = cached).  Per visit: wall time from the tab switch until the tab's content is filled, the GUI time
spent synchronously building / filling / painting (instrumented methods), and the largest event-loop gap of a
10 ms heartbeat.  A separate pass changes the Statistics metric set and the plot axes (the "update" cost).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def parse_size(s: str) -> int:
    s = s.strip().lower()
    mult = 1_000_000 if s.endswith("m") else 1_000 if s.endswith("k") else 1
    return int(float(s.rstrip("mk")) * mult)


class Probe:
    """Wraps methods and accumulates their synchronous wall time (GUI thread)."""

    def __init__(self):
        self.t = defaultdict(float)
        self.n = defaultdict(int)
        self.filled = defaultdict(int)

    def wrap(self, cls, name, key=None, fill=None):
        orig = getattr(cls, name)
        probe = self

        def w(self_, *a, **k):
            t0 = time.perf_counter()
            try:
                return orig(self_, *a, **k)
            finally:
                probe.t[key or name] += time.perf_counter() - t0
                probe.n[key or name] += 1
                if fill:
                    probe.filled[fill] += 1
        setattr(cls, name, w)

    def reset(self):
        self.t.clear()
        self.n.clear()

    def snapshot(self):
        return {k: round(v * 1000, 1) for k, v in sorted(self.t.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="10k,100k,1m")
    ap.add_argument("--expanded", action="store_true")
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-prefetch", action="store_true", help="disable background prefetch (after code only)")
    args = ap.parse_args()
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.stdout.reconfigure(encoding="utf-8")
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    from perf_harness import Heartbeat, make_window, wait_until, pump
    from synthetic import fill
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis import collection_view as CV
    from hea_calc.ui.analysis import plot as P

    probe = Probe()
    for name, fill_key in (("_rebuild_now", None), ("_build", None), ("_fill_overview", "overview"),
                           ("_fill_plot", "plots"), ("_fill_statistics", "statistics"), ("_fill_models", "models")):
        if hasattr(CV.CollectionContent, name):
            probe.wrap(CV.CollectionContent, name, fill=fill_key)
    probe.wrap(P.PlotWidget, "paintEvent", "plot.paint")
    probe.wrap(P.PlotWidget, "set_spec", "plot.set_spec")

    hb = Heartbeat()
    results = {"label": args.label, "expanded": args.expanded, "platform": os.environ.get("QT_QPA_PLATFORM", "windows"),
               "sizes": []}
    for label in args.sizes.split(","):
        n = parse_size(label)
        win = make_window(app)
        try:
            run = fill(win.repo, n, win.engine, chunk=20_000)
            win.table.model.refresh_committed()
            c = win.analysis_ctl
            if args.no_prefetch:
                c.prefetch_enabled = False
            c.run_finished(run)
            pump(app, 0.2)
            if args.expanded:
                win.set_expanded(True)
                pump(app, 0.3)
            out = {"size": n, "visits": []}

            def visit(tab, phase):
                probe.reset()
                before = probe.filled[tab]
                first = {}
                t_req = time.perf_counter()

                def on_data(slot):
                    first.setdefault(slot, time.perf_counter() - t_req)
                c.data_ready.connect(on_data)
                hb.start()
                t0 = time.perf_counter()
                if tab == "overview" and c.state.context != S.COLLECTION:
                    c.apply(S.switch_context, S.COLLECTION)
                else:
                    c.apply(S.set_tab, tab)
                ok = wait_until(app, lambda: (probe.filled[tab] > before or (phase == "cached" and probe.n["_rebuild_now"])) and not getattr(c, '_slots', getattr(c, '_jobs', {})), 120)
                wall = time.perf_counter() - t0
                pump(app, 0.15)                              # let the paint happen
                g = hb.stop()
                rec = {"tab": tab, "phase": phase, "ok": ok, "wall_ms": round(wall * 1000, 1),
                       "max_gap_ms": g.get("maxGapMs"), "gui_ms": probe.snapshot()}
                if "stats" in first:
                    rec["first_stats_ms"] = round(first["stats"] * 1000, 1)
                try:
                    c.data_ready.disconnect(on_data)              # only the probe, never the views
                except (RuntimeError, TypeError):
                    pass
                print(json.dumps({"size": n, **rec}), flush=True)
                out["visits"].append(rec)

            c.apply(S.set_tab, "overview")
            for phase in ("cold", "cached"):
                for tab in ("overview", "plots", "statistics", "models"):
                    visit(tab, phase)
            results["sizes"].append(out)
        finally:
            win.close()
            app.processEvents()
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
        print("wrote", args.out)


if __name__ == "__main__":
    main()
