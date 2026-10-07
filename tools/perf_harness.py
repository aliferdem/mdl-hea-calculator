"""Large-workflow performance harness: drives the real UI and measures GUI responsiveness.

Run (native window, the meaningful case):
    .venv/Scripts/python.exe tools/perf_harness.py                     # preflight + 30k + 100k + cancel
    .venv/Scripts/python.exe tools/perf_harness.py --scenario 30k --json design/implementation/perf.json
    .venv/Scripts/python.exe tools/perf_harness.py --offscreen         # CI-style, no window

Every scenario goes through the same path a user takes: periodic-table clicks, Composition sweep
fields, the Calculate button.  A 10 ms ``QTimer`` heartbeat runs throughout; its largest gap is the
longest time the Qt event loop could not run ("max jitter").  A sustained gap of hundreds of ms is
what Windows reports as "Not Responding" after 5 s; the acceptance limit used here is 250 ms.

Scenarios:
  preflight  5 elements, at.% 0-100 step 2 (211 876 compositions): time until the panel shows
             "more than 200,000", heartbeat during it.  No composition is generated.
  30k        5 elements, at.% 2-32 step 2       (31 076 compositions) calculated
  100k       5 elements, at.% 2-40   step 2     (94 381 compositions) calculated
  small      100 rows: the after-calculation interactions on a small table (reference for 30k/100k)
  cancel     the 100k space, Cancel pressed after 1.5 s: latency until the job reports cancelled

After each calculation: page change, sort, filter, hover repaint, theme switch, embedded details
(double click), separate details window, menu open; memory (private bytes), QObject count, Qt
model row count and ResultStore size.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

JITTER_LIMIT_MS = 250.0


# ---------------------------------------------------------------------------- process memory (Windows)
class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def memory_mib() -> dict:
    if os.name != "nt":
        return {}
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    ok = k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    if not ok:
        return {}
    return {"privateMiB": round(pmc.PrivateUsage / 2**20, 1), "workingSetMiB": round(pmc.WorkingSetSize / 2**20, 1)}


# ---------------------------------------------------------------------------- heartbeat
class Heartbeat:
    def __init__(self, interval_ms: int = 10):
        from PySide6.QtCore import QTimer
        self.interval = interval_ms / 1000
        self.timer = QTimer()
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._beat)
        self.reset()

    def reset(self):
        self.t0 = self.last = time.perf_counter()
        self.gaps: list[float] = []
        self.big: list[tuple[float, float]] = []      # (start s, gap ms) of gaps over 100 ms
        self.events: list[tuple[float, str]] = []

    def mark(self, what: str):
        self.events.append((round(time.perf_counter() - self.t0, 3), what))

    def _beat(self):
        now = time.perf_counter()
        gap = now - self.last
        self.gaps.append(gap)
        if gap > 0.1:
            self.big.append((round(self.last - self.t0, 3), round(1000 * gap, 1)))
        self.last = now

    def start(self):
        self.reset()
        self.timer.start()

    def stop(self) -> dict:
        self.timer.stop()
        g = sorted(self.gaps) or [0.0]
        return {"maxGapMs": round(1000 * g[-1], 1), "p99GapMs": round(1000 * g[int(0.99 * (len(g) - 1))], 1),
                "beats": len(self.gaps), "gapsOver100ms": sum(1 for x in g if x > 0.1),
                "gapsOver250ms": sum(1 for x in g if x > 0.25), "bigGaps": self.big, "events": self.events}


def pump(app, seconds: float):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.002)


def wait_until(app, cond, timeout: float, during=None) -> bool:
    """Run the event loop (as the app would) until ``cond()``; ``during(t)`` is called every ~50 ms."""
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    t0 = time.perf_counter()
    state = {"ok": False}

    def check():
        if cond():
            state["ok"] = True
            loop.quit()
        elif time.perf_counter() - t0 > timeout:
            loop.quit()
        elif during is not None:
            during(time.perf_counter() - t0)
    poll = QTimer()
    poll.setInterval(50)
    poll.timeout.connect(check)
    poll.start()
    loop.exec()
    poll.stop()
    return state["ok"]


def timed(fn) -> float:
    t = time.perf_counter()
    fn()
    return round(1000 * (time.perf_counter() - t), 2)


# ---------------------------------------------------------------------------- window / UI driving
def make_window(app):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
    settings = QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=settings)
    w.resize(1600, 900)
    w.show()
    pump(app, 0.3)
    return w


def set_sweep(win, app, elements, lo, hi, step):
    for el in elements:
        win.elements.table.tiles[el].click()
    win.composition.set_mode(1)
    win.composition.unit_box.setCurrentIndex(1)       # at.%
    sw = win.composition.sweep
    for row in sw.rows.values():
        row.min.setText(str(lo))
        row.max.setText(str(hi))
        row.step.setText(str(step))
    sw._edited()
    return sw


def clear(win, app):
    win.table.model.clear()
    win.composition.clear()
    pump(app, 0.1)


def qobject_count(win) -> int:
    from PySide6.QtCore import QObject
    return len(win.findChildren(QObject))


# ---------------------------------------------------------------------------- scenarios
def scenario_preflight(app, win, hb) -> dict:
    sw = set_sweep(win, app, ["Fe", "Co", "Ni", "Cr", "Mn"], 0, 100, 2)
    sw.summary_data = None
    hb.start()
    t0 = time.perf_counter()
    sw._timer.stop()
    sw._update_summary()
    ok = wait_until(app, lambda: sw.summary_data is not None, 30)
    dt = time.perf_counter() - t0
    jit = hb.stop()
    s = sw.summary_data
    out = {"ok": ok, "timeToDisplayMs": round(1000 * dt, 1), "truncated": bool(s and s.truncated),
           "summaryText": sw.summary.text().split("<br>")[-1], "heartbeat": jit,
           "rowsInTable": win.table.model.view_count()}
    from hea_calc.core.generation import count_space
    t = time.perf_counter()
    c = count_space(sw.specs(), "at", None, stop_after=200_000)
    out["countSpaceMs"] = round(1000 * (time.perf_counter() - t), 3)
    out["exactCount"] = count_space(sw.specs(), "at", None, stop_after=10**12).count
    out["countResult"] = f"{'>' if c.exceeds else ''}{min(c.count, 200_000):,}"
    clear(win, app)
    return out


def interact_during(win, app, hb=None):
    """Use the UI while the job runs: open/close a menu, resize, page."""
    from PySide6.QtCore import QPoint, QTimer
    state = {"menu": False, "resize": False}

    def during(t):
        if t > 0.6 and not state["menu"]:
            state["menu"] = True
            if hb:
                hb.mark("menu popup")
            m = win.file_menu
            QTimer.singleShot(150, m.close)
            m.popup(win.mapToGlobal(QPoint(40, 48)))
        if t > 1.0 and not state["resize"]:
            state["resize"] = True
            if hb:
                hb.mark("resize")
            win.resize(win.width() - 120, win.height())
            QTimer.singleShot(200, lambda: win.resize(win.width() + 120, win.height()))
    return during, state


def after_metrics(app, win) -> dict:
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    from hea_calc.core.results import RangeFilter
    from hea_calc.ui.theme import THEME
    m = win.table.model
    view = win.table.view
    out = {"qtModelRows": m.rowCount(), "qtModelColumns": m.columnCount(), "viewCount": m.view_count(),
           "storeRows": len(m.store), "storeMiB": round(m.store.nbytes() / 2**20, 1)}
    out["pageChangeMs"] = timed(lambda: (m.set_page(m.page + 1), app.processEvents()))
    out["pageSize10Ms"] = timed(lambda: (win.table.pagination.size_box.setCurrentIndex(0), app.processEvents()))
    out["pageSize100Ms"] = timed(lambda: (win.table.pagination.size_box.setCurrentIndex(3), app.processEvents()))
    out["sortMs"] = timed(lambda: (m.sort_by("dhmix"), app.processEvents()))
    out["sortDescMs"] = timed(lambda: (m.sort_by("dhmix"), app.processEvents()))
    out["sortOffMs"] = timed(lambda: (m.sort_by("dhmix"), app.processEvents()))
    out["filterMs"] = timed(lambda: (m.set_filters([RangeFilter("dhmix", -10.0, None)]), app.processEvents()))
    out["filteredRows"] = m.view_count()
    out["clearFilterMs"] = timed(lambda: (m.set_filters([]), app.processEvents()))
    # hover: move over ten rows, each move repaints two row strips
    vp = view.viewport()

    def hover():
        for r in range(10):
            y = view.rowViewportPosition(r) + 16
            ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(200, y), QPointF(vp.mapToGlobal(QPoint(200, y))),
                             Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(vp, ev)
            app.processEvents()           # paints only the two dirty row strips, as a real hover does
    from PySide6.QtWidgets import QApplication
    out["hover10RowsMs"] = timed(hover)
    out["fullTableRepaintMs"] = timed(vp.repaint)
    rect = view.visualRect(m.index(0, 0))
    pos = QPointF(rect.center())

    def dbl():
        ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, pos, QPointF(vp.mapToGlobal(rect.center())),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(vp, ev)
        app.processEvents()
    out["doubleClickDetailsMs"] = timed(dbl)
    out["detailsShowsRow"] = win.details.row is not None and win.details.row.row_id == m.id_at(0)

    def window():
        from hea_calc.ui.widgets.dialogs import AlloyDetailsDialog
        d = AlloyDetailsDialog(m.row_at(0).materialize(), win)
        d.show()
        app.processEvents()
        d.close()
        d.deleteLater()
    out["detailsWindowMs"] = timed(window)

    def menu():
        mm = view.row_menu(m.row_at(0), m.keys[0])
        mm.popup(vp.mapToGlobal(rect.center()))
        app.processEvents()
        mm.close()
        mm.deleteLater()
    out["rowMenuMs"] = timed(menu)
    out["themeLightMs"] = timed(lambda: (win.set_theme("light"), app.processEvents()))
    out["themeDarkMs"] = timed(lambda: (win.set_theme("dark"), app.processEvents()))
    out["resizeMs"] = timed(lambda: (win.resize(win.width() - 300, win.height()), app.processEvents(),
                                     win.resize(win.width() + 300, win.height()), app.processEvents()))
    out["scrollMs"] = timed(lambda: (win.scroll.verticalScrollBar().setValue(600), app.processEvents(),
                                     win.scroll.verticalScrollBar().setValue(0), app.processEvents()))
    out["qobjects"] = qobject_count(win)
    # no QTableWidgetItem / QStandardItem / index widget per cell: the model is a QAbstractTableModel
    out["perCellQtItems"] = sum(1 for r in range(m.rowCount()) for c in range(m.columnCount())
                                if view.indexWidget(m.index(r, c)) is not None)
    return out


def scenario_calc(app, win, hb, label, elements, lo, hi, step) -> dict:
    sw = set_sweep(win, app, elements, lo, hi, step)
    sw._timer.stop()
    sw.summary_data = None
    sw._update_summary()
    wait_until(app, lambda: sw.summary_data is not None, 30)
    expected = sw.summary_data.compositions
    gc.collect()
    mem0 = memory_mib()
    obj0 = qobject_count(win)
    during, state = interact_during(win, app, hb)
    hb.start()
    t0 = time.perf_counter()
    win.composition.calc_btn.click()
    hb.mark("calculate clicked")
    ok = wait_until(app, lambda: win.worker is None, 600, during)
    hb.mark("job finished")
    total = time.perf_counter() - t0
    jit = hb.stop()
    r = win.runner
    out = {"scenario": label, "ok": ok, "expected": expected, "calculated": len(win.table.model.store),
           "totalSeconds": round(total, 2), "heartbeat": jit, "ingestSecondsGuiThread": round(r.ingest_seconds, 3),
           "maxIngestTickMs": round(1000 * r.max_tick_seconds, 1), "ticks": r.ticks,
           "workers": win.jobs.workers, "menuOpenedDuringJob": state["menu"], "resizedDuringJob": state["resize"],
           "memoryBefore": mem0, "qobjectsBefore": obj0}
    pump(app, 0.3)
    gc.collect()
    out["memoryAfter"] = memory_mib()
    hb.start()
    out["after"] = after_metrics(app, win)
    out["heartbeatAfter"] = hb.stop()
    clear(win, app)
    return out


def scenario_small(app, win, hb) -> dict:
    """The same after-calculation interactions on 100 rows: the baseline the large runs must match."""
    sys.path.insert(0, str(ROOT / "tools"))
    from screenshot import demo_rows
    demo_rows(win, 100)
    pump(app, 0.3)
    hb.start()
    out = {"after": after_metrics(app, win)}
    out["heartbeat"] = hb.stop()
    clear(win, app)
    return out


def scenario_cancel(app, win, hb) -> dict:
    sw = set_sweep(win, app, ["Fe", "Co", "Ni", "Cr", "Mn"], 2, 40, 2)
    sw._timer.stop()
    hb.start()
    win.composition.calc_btn.click()
    wait_until(app, lambda: False, 1.5)
    t0 = time.perf_counter()
    hb.mark("cancel clicked")
    win.progress.cancel.click()
    ok = wait_until(app, lambda: win.worker is None, 30)
    latency = time.perf_counter() - t0
    jit = hb.stop()
    out = {"ok": ok, "cancelLatencyMs": round(1000 * latency, 1), "rowsKept": len(win.table.model.store),
           "heartbeat": jit, "workerPidsAlive": len(win.jobs.worker_pids())}
    clear(win, app)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="all", choices=["all", "preflight", "small", "30k", "100k", "cancel"])
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    if a.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from hea_calc.ui.theme import load_fonts
    from hea_calc.ui.widgets.common import install_tooltips
    load_fonts()
    install_tooltips(app)
    win = make_window(app)
    hb = Heartbeat()
    results: dict = {"platform": app.platformName(), "jitterLimitMs": JITTER_LIMIT_MS}
    try:
        if a.scenario in ("all", "preflight"):
            results["preflight"] = scenario_preflight(app, win, hb)
            print("preflight", json.dumps(results["preflight"]))
        if a.scenario in ("all", "small"):
            results["small"] = scenario_small(app, win, hb)
            print("small", json.dumps(results["small"]))
        if a.scenario in ("all", "30k"):
            results["30k"] = scenario_calc(app, win, hb, "30k", ["Fe", "Co", "Ni", "Cr", "Mn"], 2, 32, 2)
            print("30k", json.dumps(results["30k"]))
        if a.scenario in ("all", "100k"):
            results["100k"] = scenario_calc(app, win, hb, "100k", ["Fe", "Co", "Ni", "Cr", "Mn"], 2, 40, 2)
            print("100k", json.dumps(results["100k"]))
        if a.scenario in ("all", "cancel"):
            results["cancel"] = scenario_cancel(app, win, hb)
            print("cancel", json.dumps(results["cancel"]))
    finally:
        win.close()
        app.processEvents()
    failures = []
    for k in ("preflight", "30k", "100k", "cancel"):     # "small"'s after-metrics are a reference only
        r = results.get(k)
        if r and r["heartbeat"]["maxGapMs"] > JITTER_LIMIT_MS:
            failures.append(f"{k}: max event-loop gap {r['heartbeat']['maxGapMs']} ms")
        if r and not r.get("ok", True):
            failures.append(f"{k}: did not complete")
    results["failures"] = failures
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("FAILURES:" if failures else "PASS", *failures, sep="\n  ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
