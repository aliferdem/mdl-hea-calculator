"""Work done by each Analysis view while the separate Analysis window is the one in use.

    .venv/Scripts/python.exe tools/analysis_dedupe_probe.py [rows=30000] [--offscreen] [--no-suspend] [--json out.json]

``--no-suspend`` disables AnalysisPanel.set_suspended in this process (the behaviour before it existed).

A synthetic run (``tools/synthetic.py``: replicated engine results, labelled SYN..., for measurements only) is stored,
the Analysis window is opened and activated (the main window becomes inactive, as when the user works in the
separate window), and a fixed sequence of Analysis interactions is applied through the shared controller: Collection
Plots with three colourings, the Overview / Statistics / Models / Plots tabs, then Composition for five different
results with two tab changes.  For each view - the embedded panel and the window's panel - the probe counts tab
builds, data fills, composition renders and plot image renders (cache misses, with the points drawn), plus the
controller's query requests and the background queries actually run; the GUI time of the sequence is the sum of
the per-step wall times until every slot has settled.  Then the main window is activated again and the same
counters show what the embedded panel does to catch up.  Prints one JSON object.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rows = int(args[0]) if args else 30_000
    if "--offscreen" in sys.argv:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    out_json = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--json"), "")
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    from perf_harness import make_window
    from synthetic import fill
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis import collection_view as CV, composition_view as CPV, panel as PN, plot as PL
    from hea_calc.ui.analysis import controller as CT

    counts: dict = {}

    def owner(widget):
        w = widget
        while w is not None and not isinstance(w, PN.AnalysisPanel):
            w = w.parentWidget()
        if w is None:
            return "other"
        return "window" if getattr(w, "external", False) else "embedded"

    def count(name, who):
        d = counts.setdefault(who, {})
        d[name] = d.get(name, 0) + 1

    def wrap(cls, meth, name, who_of=owner):
        real = getattr(cls, meth)

        def f(self, *a, **k):
            count(name, who_of(self))
            return real(self, *a, **k)
        setattr(cls, meth, f)
    wrap(CV.CollectionContent, "_build", "collection tab builds")
    for m in ("_fill_overview", "_fill_plot", "_fill_statistics", "_fill_models"):
        wrap(CV.CollectionContent, m, "collection fills")
    wrap(CPV.CompositionContent, "set_result", "composition renders")
    wrap(CPV.CompositionContent, "ensure", "composition tab ensures")
    if "--no-suspend" in sys.argv:              # the behaviour before suspension, for comparison
        PN.AnalysisPanel.set_suspended = lambda self, on: None
    real_pp = PL.PlotWidget._paint_points

    def paint_points(self, p, rect, win, fx, fy, interactive, w, h):
        miss = self._cache is None
        if miss:
            count("plot image renders", owner(self))
            n = len(self.spec.data.get("x", [])) if self.spec is not None else 0
            d = counts.setdefault(owner(self), {})
            d["points drawn"] = d.get("points drawn", 0) + n
        return real_pp(self, p, rect, win, fx, fy, interactive, w, h)
    PL.PlotWidget._paint_points = paint_points
    real_rq = CT.AnalysisController.run_query

    def run_query(self, slot, fn, **k):
        count("query requests", "controller")
        return real_rq(self, slot, fn, **k)
    CT.AnalysisController.run_query = run_query
    real_submit = CT.QueryRunner.submit

    def submit(self, *a, **k):
        count("queries run", "controller")
        return real_submit(self, *a, **k)
    CT.QueryRunner.submit = submit

    win = make_window(app)
    run = fill(win.repo, rows, win.engine, chunk=20_000)
    win.table.model.refresh_committed()
    c = win.analysis_ctl
    c.run_finished(run)
    win._check_details()
    app.processEvents()

    def settle(limit=60.0):
        t0 = time.perf_counter()
        quiet = 0
        while time.perf_counter() - t0 < limit:
            app.processEvents()
            busy = any(c.busy(s) for s in list(c._slots))
            quiet = quiet + 1 if not busy else 0
            if quiet > 25:
                break
            time.sleep(0.004)
        return time.perf_counter() - t0

    aw = win.open_analysis_window(win.table.model.row_at(0))
    aw.raise_()
    aw.activateWindow()
    settle()
    res = {"rows": rows, "suspension": "--no-suspend" not in sys.argv, "platform": app.platformName(), "main_active": win.isActiveWindow(),
           "window_active": aw.isActiveWindow()}
    counts.clear()
    gui = 0.0
    steps = []
    from hea_calc.core.analysis.plotting import SCATTER
    c.apply(S.switch_context, S.COLLECTION)
    gui += settle()
    c.scope_for(run, "full")
    gui += settle()
    c.apply(S.set_tab, "plots")
    gui += settle()
    for colour in ("model:M2", "model:M4", "family"):
        c.apply(S.set_plot, c.state.plot.with_(type=SCATTER, x="delta", y="dhmix", color=colour))
        dt = settle()
        steps.append(("plot " + colour, round(dt, 3)))
        gui += dt
    for tab in ("overview", "statistics", "models", "plots"):
        c.apply(S.set_tab, tab)
        dt = settle()
        steps.append(("tab " + tab, round(dt, 3)))
        gui += dt
    c.apply(S.switch_context, S.COMPOSITION)
    gui += settle()
    for i in range(1, 6):
        win.open_analysis_window(win.table.model.row_at(i))
        dt = settle()
        steps.append((f"composition {i}", round(dt, 3)))
        gui += dt
    for tab in ("models", "descriptors"):
        c.apply(S.set_tab, tab)
        gui += settle()
    res["while_window_active"] = {k: dict(v) for k, v in counts.items()}
    res["gui_seconds"] = round(gui, 3)
    res["steps"] = steps
    res["main_active_during"] = win.isActiveWindow()
    counts.clear()
    win.raise_()
    win.activateWindow()
    res["catch_up_seconds"] = round(settle(), 3)
    res["on_main_activation"] = {k: dict(v) for k, v in counts.items()}
    res["embedded_shows"] = {"name": win.analysis.row.name if win.analysis.row is not None else None,
                             "controller": c.row.name if c.row is not None else None}
    print(json.dumps(res))
    if out_json:
        Path(out_json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    aw.close()
    win.close()
    app.processEvents()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
