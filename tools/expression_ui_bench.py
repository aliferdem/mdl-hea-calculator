"""Interactive Expression vs Composition space timing through the real window (pre-flight, Calculate → completed,
table on screen) with a 10 ms event-loop heartbeat.

Usage:
    .venv/Scripts/python.exe tools/expression_ui_bench.py [--cases 1v1k,1v10k,2v10k,3v10k,2v40k] [--offscreen]
           [--out design/implementation/expression_ui_bench.json]

Per case and mode: pre-flight (Composition space: the debounced count; Expression: Parse expression = parse + count),
Calculate → "Calculation completed", the stored rows, rows/s, the largest event-loop gap (ms) during each phase.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from expression_bench import CASES, VARIED, VARS, grid  # noqa: E402


class Heartbeat:
    def __init__(self, app):
        from PySide6.QtCore import QTimer
        self.timer = QTimer()
        self.timer.setInterval(10)
        self.last = time.perf_counter()
        self.gap = 0.0
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self):
        now = time.perf_counter()
        self.gap = max(self.gap, now - self.last)
        self.last = now

    def reset(self):
        self.last = time.perf_counter()
        self.gap = 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="1v1k,1v10k,2v10k,3v10k,2v40k")
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "design" / "implementation" / "expression_ui_bench.json"))
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    from hea_calc.ui.main_window import MainWindow
    win = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    win.resize(1600, 1000)
    win.show()
    hb = Heartbeat(app)

    def pump(sec=0.0):
        end = time.monotonic() + sec
        while True:
            app.processEvents()
            if time.monotonic() >= end:
                return
            time.sleep(0.002)

    def until(cond, limit=300.0):
        t0 = time.perf_counter()
        while not cond() and time.perf_counter() - t0 < limit:
            app.processEvents()
            time.sleep(0.001)
        return time.perf_counter() - t0

    pump(1.0)
    win.jobs.warm_up().join()
    comp = win.composition
    out = {"label": args.label, "platform": app.platformName(), "cases": []}

    def calc_and_wait():
        before = win.table.model.total_count()
        hb.reset()
        t0 = time.perf_counter()
        comp.calculate()
        until(lambda: not win.runner.running and win.progress.result is not None)
        wall = time.perf_counter() - t0
        pump(0.05)
        rows = win.table.model.total_count() - before
        win.progress.clear_result()
        return {"calculate_s": round(wall, 3), "rows": rows, "rows_per_s": round(rows / wall) if wall else 0,
                "max_gap_ms": round(hb.gap * 1000, 1)}

    for name in args.cases.split(","):
        nv, n = CASES[name]
        lo, hi, step = grid(n)
        rec = {"case": name}
        # ---- Composition space: Fe, Co, Ni locked at 1, the varied elements on the grid
        comp.set_mode(0)
        win.composition.clear()
        pump(0.1)
        els = ["Fe", "Co", "Ni"] + list(VARIED[:nv])
        for el in els:
            win.elements.table.tiles[el].click()
        comp.set_mode(1)
        sw = comp.sweep
        for el, row in sw.rows.items():
            v = (lo, hi, step) if el in VARIED else (1.0, 1.0, 0.1)
            row.set_values(tuple(f"{x:g}" for x in v))
        hb.reset()
        t0 = time.perf_counter()
        sw._edited()
        sw._timer.stop()
        sw._update_summary()
        until(lambda: not sw._counter.busy and sw.summary_data is not None)
        pump(0.02)
        rec["space"] = {"preflight_s": round(time.perf_counter() - t0, 3), "preflight_gap_ms": round(hb.gap * 1000, 1)}
        rec["space"].update(calc_and_wait())
        # ---- Expression with the same grid
        comp.set_mode(2)
        ex = comp.expr
        formula = "FeCoNi" + "".join(f"{VARIED[i]}{{{VARS[i]}}}" for i in range(nv))
        text = formula + "".join(f"\n  {lo:g} <= {VARS[i]} <= {hi:g}, step={step:g}" for i in range(nv))
        ex.set_text(text)
        pump(0.05)
        hb.reset()
        t0 = time.perf_counter()
        ex.parse()
        until(lambda: not ex.counting)
        pump(0.02)
        rec["expression"] = {"preflight_s": round(time.perf_counter() - t0, 3),
                             "preflight_gap_ms": round(hb.gap * 1000, 1)}
        rec["expression"].update(calc_and_wait())
        rec["ratio_calculate"] = round(rec["expression"]["calculate_s"] / rec["space"]["calculate_s"], 2)
        out["cases"].append(rec)
        print(json.dumps(rec), flush=True)
        win.table.model.clear()
        pump(0.5)
    win.close()
    pump(0.5)
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("wrote", args.out)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
