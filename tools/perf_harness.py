"""Large-workflow performance harness: drives the real UI and measures GUI responsiveness.

Run (native window, the meaningful case):
    .venv/Scripts/python.exe tools/perf_harness.py                      # preflight, small, 30k, 100k, cancel
    .venv/Scripts/python.exe tools/perf_harness.py --scenario storage --sizes 100k,200k,500k,1m,2m,5m
    .venv/Scripts/python.exe tools/perf_harness.py --scenario real --real 430k,1m
    .venv/Scripts/python.exe tools/perf_harness.py --offscreen          # CI-style, no window

Every UI scenario goes through the path a user takes (periodic-table clicks, Composition sweep
fields, the Calculate button, the table's own model calls).  A 10 ms ``QTimer`` heartbeat runs
throughout; its largest gap is the longest time the Qt event loop could not run ("max gap").  A
sustained gap of hundreds of ms is what Windows reports as "Not Responding" after 5 s; the
acceptance limit used here is 250 ms.

Three kinds of measurement, reported separately:

* real-engine calculation (``30k``, ``100k``, ``real``, ``cancel``, ``shutdown``): compositions are
  generated and calculated by the worker processes and stored by the single database writer;
* repository/storage (``storage``): **synthetic** rows - engine outputs of 50 alloys replicated -
  inserted through the same writer path as a calculation, to reach 5 M rows in minutes instead of
  hours; labelled ``synthetic`` in the output;
* query (inside both): page change, first and repeated full-dataset sort, filter, details, row
  removal, clear, streamed export - each timed until the result is on screen, with the heartbeat
  running.
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

JITTER_LIMIT_MS = 250.0
FIVE = ["Fe", "Co", "Ni", "Cr", "Mn"]


# ---------------------------------------------------------------------------- process memory (Windows)
class _PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def _pmc(handle) -> _PMC | None:
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    k32 = ctypes.windll.kernel32
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    return pmc if k32.K32GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb) else None


def memory_mib(pid: int | None = None) -> dict:
    """Private bytes / working set of this process (or ``pid``) in MiB."""
    if os.name != "nt":
        return {}
    k32 = ctypes.windll.kernel32
    if pid is None:
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        pmc = _pmc(k32.GetCurrentProcess())
    else:
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000 | 0x0010, False, pid)          # QUERY_LIMITED_INFORMATION | VM_READ
        if not h:
            return {}
        try:
            pmc = _pmc(h)
        finally:
            k32.CloseHandle(h)
    if pmc is None:
        return {}
    return {"privateMiB": round(pmc.PrivateUsage / 2**20, 1), "workingSetMiB": round(pmc.WorkingSetSize / 2**20, 1)}


def process_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(0x1000 | 0x00100000, False, pid)            # QUERY_LIMITED_INFORMATION | SYNCHRONIZE
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == 0x102               # WAIT_TIMEOUT: still running
    finally:
        k32.CloseHandle(h)


class MemorySampler:
    """Peak private bytes of the GUI process and of GUI + worker processes."""

    def __init__(self, win):
        self.win = win
        self.peak_main = 0.0
        self.peak_total = 0.0

    def sample(self):
        main = memory_mib().get("privateMiB", 0.0)
        workers = sum(memory_mib(p).get("privateMiB", 0.0) for p in self.win.jobs.worker_pids())
        self.peak_main = max(self.peak_main, main)
        self.peak_total = max(self.peak_total, main + workers)

    def result(self) -> dict:
        return {"peakMainPrivateMiB": round(self.peak_main, 1), "peakTotalPrivateMiB": round(self.peak_total, 1)}


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
                "gapsOver250ms": sum(1 for x in g if x > 0.25), "bigGaps": self.big[:20], "events": self.events}


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
    poll.setInterval(10)
    poll.timeout.connect(check)
    poll.start()
    if cond():
        state["ok"] = True
    else:
        loop.exec()
    poll.stop()
    return state["ok"]


def timed(fn) -> float:
    t = time.perf_counter()
    fn()
    return round(1000 * (time.perf_counter() - t), 2)


def until_shown(app, m, fn, timeout: float = 600) -> float:
    """ms from the request until the result is applied (a background build included)."""
    t = time.perf_counter()
    fn()
    wait_until(app, lambda: m.view.pending is None and m.view._extending is None, timeout)
    app.processEvents()
    return round(1000 * (time.perf_counter() - t), 2)


def db_mib(repo) -> float:
    return round(sum(repo.size_bytes().values()) / 2**20, 1)


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
    m = win.table.model
    if m.sort_key or m.filters:
        m.view.request(filters=[], sort=(None, False))
    m.clear()
    win.composition.clear()
    win.repo.writer.flush(timeout=600)
    pump(app, 0.1)


def qobject_count(win) -> int:
    from PySide6.QtCore import QObject
    return len(win.findChildren(QObject))


# ---------------------------------------------------------------------------- scenarios
def scenario_preflight(app, win, hb) -> dict:
    sw = set_sweep(win, app, FIVE, 0, 100, 2)
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
    from hea_calc.core.generation import SweepSpec, count_space
    t = time.perf_counter()
    c = count_space(sw.specs(), "at", None, stop_after=10**15)
    out["countSpaceMs"] = round(1000 * (time.perf_counter() - t), 3)
    out["exactCount"] = c.count
    counts = {}
    for label, els, lo, hi in (("5M", 5, 1, 60), ("42M", 6, 1, 40), ("806M", 7, 1, 40)):
        specs = [SweepSpec(e, lo, hi, 1) for e in (FIVE + ["Al", "Ti"])[:els]]
        t = time.perf_counter()
        n = count_space(specs, "at", None, stop_after=10**15).count
        counts[label] = {"count": n, "ms": round(1000 * (time.perf_counter() - t), 3)}
    out["largeCounts"] = counts
    clear(win, app)
    return out


def interact_during(win, app, hb=None, sampler: MemorySampler | None = None):
    """Use the UI while the job runs: open/close a menu, resize, page; sample memory."""
    from PySide6.QtCore import QPoint, QTimer
    state = {"menu": False, "resize": False, "page": False, "last_mem": 0.0}

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
        if t > 2.0 and not state["page"] and win.table.model.page_count() > 2:
            state["page"] = True
            if hb:
                hb.mark("page change during job")
            win.table.model.set_page(1)
        if sampler is not None and t - state["last_mem"] > 0.5:
            state["last_mem"] = t
            sampler.sample()
    return during, state


def after_metrics(app, win, export: bool = True) -> dict:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    from hea_calc.core.results import ModelFilter, RangeFilter
    m = win.table.model
    view = win.table.view
    n = m.total_count()
    out = {"qtModelRows": m.rowCount(), "qtModelColumns": m.columnCount(), "viewCount": m.view_count(),
           "datasetRows": n, "dbMiB": db_mib(win.repo)}
    out["pageChangeMs"] = timed(lambda: (m.set_page(m.page + 1), app.processEvents()))
    out["lastPageMs"] = timed(lambda: (m.set_page(m.page_count() - 1), app.processEvents()))
    out["pageSize10Ms"] = timed(lambda: (win.table.pagination.size_box.setCurrentIndex(0), app.processEvents()))
    out["pageSize100Ms"] = timed(lambda: (win.table.pagination.size_box.setCurrentIndex(3), app.processEvents()))
    out["firstSortMs"] = until_shown(app, m, lambda: m.sort_by("dhmix"))
    out["repeatSortDescMs"] = until_shown(app, m, lambda: m.sort_by("dhmix"))
    out["sortedPageChangeMs"] = timed(lambda: (m.set_page(m.page_count() // 2), app.processEvents()))
    out["sortOffMs"] = until_shown(app, m, lambda: m.sort_by("dhmix"))
    out["labelSortMs"] = until_shown(app, m, lambda: m.sort_by("M1"))
    m.sort_by("M1")
    m.sort_by("M1")
    m.wait()
    flt = [RangeFilter("delta", None, 6.6), RangeFilter("omega", 1.1, None), ModelFilter("M1", {"SS"})]
    out["filterMs"] = until_shown(app, m, lambda: m.set_filters(flt))
    out["filteredRows"] = m.view_count()
    out["clearFilterMs"] = until_shown(app, m, lambda: m.set_filters([]))
    # hover: move over ten rows, each move repaints two row strips
    vp = view.viewport()

    def hover():
        for r in range(10):
            y = view.rowViewportPosition(r) + 16
            ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(200, y), QPointF(vp.mapToGlobal(QPoint(200, y))),
                             Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(vp, ev)
            app.processEvents()           # paints only the two dirty row strips, as a real hover does
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
    victim = m.row_at(3)
    out["removeRowMs"] = timed(lambda: (view._remove(victim), app.processEvents()))
    out["removedGone"] = win.repo.get_result(victim.id) is None and m.total_count() == n - 1
    if export and n:
        out.update(export_metrics(app, win))
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
    out["memoryAfterQueries"] = memory_mib()
    return out


def export_metrics(app, win, fmt: str = "csv") -> dict:
    """Export all results through the UI path (a background process above 2 000 rows)."""
    from PySide6.QtWidgets import QFileDialog
    out_path = Path(tempfile.mkdtemp()) / f"export.{fmt}"
    orig = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_path), ""))
    try:
        t = time.perf_counter()
        win.export(fmt, "all")
        wait_until(app, lambda: not win.exporter.running, 3600)
        dt = time.perf_counter() - t
    finally:
        QFileDialog.getSaveFileName = orig
    size = out_path.stat().st_size if out_path.exists() else 0
    n = win.table.model.total_count()
    res = {"exportCsvSeconds": round(dt, 2), "exportCsvRowsPerS": round(n / dt) if dt else None,
           "exportCsvMiB": round(size / 2**20, 1)}
    out_path.unlink(missing_ok=True)
    return res


EDIT_PAUSE_S = 2.0       # a user edits Min/Max/Step for seconds after choosing the mode (the pool warms meanwhile)


def run_calc(app, win, hb, label, elements, lo, hi, step, after: bool = True, pause: float = EDIT_PAUSE_S) -> dict:
    sw = set_sweep(win, app, elements, lo, hi, step)
    pump(app, pause)
    sw._timer.stop()
    sw.summary_data = None
    sw._update_summary()
    wait_until(app, lambda: sw.summary_data is not None, 30)
    expected = sw.summary_data.compositions
    gc.collect()
    mem0 = memory_mib()
    obj0 = qobject_count(win)
    sampler = MemorySampler(win)
    during, state = interact_during(win, app, hb, sampler)
    first = {"t": None}
    hb.start()
    t0 = time.perf_counter()
    win.composition.calc_btn.click()
    hb.mark("calculate clicked")

    def watch(t):
        during(t)
        if first["t"] is None and win.table.model.total_count() > 0:
            first["t"] = time.perf_counter() - t0
    ok = wait_until(app, lambda: win.worker is None, 7200, watch)
    hb.mark("job finished")
    total = time.perf_counter() - t0
    jit = hb.stop()
    sampler.sample()
    r = win.runner
    n = win.table.model.total_count()
    out = {"scenario": label, "kind": "real engine", "ok": ok, "expected": expected, "calculated": n,
           "totalSeconds": round(total, 2), "alloysPerSecond": round(n / total) if total else None,
           "timeToFirstResultS": round(first["t"], 2) if first["t"] else None, "heartbeat": jit,
           "guiSecondsInTicks": round(r.ingest_seconds, 3), "maxTickMs": round(1000 * r.max_tick_seconds, 1),
           "ticks": r.ticks, "workers": win.jobs.workers, "writerInsertSeconds": round(win.repo.writer.insert_seconds, 2),
           "writerCommits": win.repo.writer.commits, "menuOpenedDuringJob": state["menu"],
           "resizedDuringJob": state["resize"], "pagedDuringJob": state["page"], "memoryBefore": mem0,
           "qobjectsBefore": obj0, "dbMiB": db_mib(win.repo), **sampler.result()}
    pump(app, 0.3)
    gc.collect()
    out["memoryAfter"] = memory_mib()
    if after:
        hb.start()
        out["after"] = after_metrics(app, win)
        out["heartbeatAfter"] = hb.stop()
    clear(win, app)
    return out


def scenario_small(app, win, hb) -> dict:
    """The same after-calculation interactions on 100 rows: the baseline the large runs must match."""
    from screenshot import demo_rows
    demo_rows(win, 100)
    pump(app, 0.3)
    hb.start()
    out = {"after": after_metrics(app, win, export=False)}
    out["heartbeat"] = hb.stop()
    clear(win, app)
    return out


def scenario_cancel(app, win, hb, elements=FIVE, lo=2, hi=40, step=2, after_s: float = 1.5) -> dict:
    sw = set_sweep(win, app, elements, lo, hi, step)
    pump(app, EDIT_PAUSE_S)
    sw._timer.stop()
    hb.start()
    win.composition.calc_btn.click()
    wait_until(app, lambda: False, after_s)
    job = win.worker
    queued = (job.chunks_emitted - win.repo.writer.stored_chunks(win.runner.run_id)) if job else 0
    t0 = time.perf_counter()
    hb.mark("cancel clicked")
    win.progress.cancel.click()
    ok = wait_until(app, lambda: win.worker is None, 60)
    latency = time.perf_counter() - t0
    jit = hb.stop()
    m = win.table.model
    info = win.repo.get_run(win.runner.run_id)
    seqs_ok = win.repo.con.execute("SELECT COUNT(*), MIN(seq), MAX(seq) FROM results WHERE run_id=?",
                                   (info.run_id,)).fetchone()
    out = {"ok": ok, "cancelLatencyMs": round(1000 * latency, 1), "writerBacklogChunksAtCancel": queued,
           "rowsKept": m.total_count(), "runStatus": info.status,
           "contiguousPrefix": seqs_ok[0] == 0 or (seqs_ok[1] == 0 and seqs_ok[2] == seqs_ok[0] - 1),
           "heartbeat": jit, "workerPidsAlive": len(win.jobs.worker_pids())}
    clear(win, app)
    return out


def scenario_storage(app, win, hb, sizes: list[int], export_max: int) -> dict:
    """Synthetic rows inserted through the single writer (as a calculation does), then queries."""
    from synthetic import synthetic_chunk
    m, repo = win.table.model, win.repo
    variants = [synthetic_chunk(win.engine, 500, i * 500) for i in range(20)]
    run = repo.create_run("sweep", settings={}, elements=FIVE, source={"synthetic": True})
    out = {"kind": "SYNTHETIC rows (engine outputs of 50 alloys replicated) - repository/query benchmark",
           "checkpoints": []}
    have = 0
    gc.collect()
    out["memoryStart"] = memory_mib()
    for target in sizes:
        add = target - have
        hb.start()
        hb.mark(f"insert {add:,}")
        done = {"ok": False}
        chunks = max(0, round(add / 500))
        add = chunks * 500

        def feed():
            for i in range(chunks):
                repo.submit_chunk(run, dict(variants[i % 20]))
            repo.writer.flush(timeout=3600)
            done["ok"] = True
        th = threading.Thread(target=feed, daemon=True)
        t0 = time.perf_counter()
        th.start()
        from PySide6.QtCore import QTimer
        tick = QTimer()
        tick.setInterval(100)
        tick.timeout.connect(m.refresh_committed)        # what JobRunner does at 10 Hz
        tick.start()
        wait_until(app, lambda: done["ok"], 7200)
        tick.stop()
        th.join()
        m.refresh_committed()
        ins = time.perf_counter() - t0
        jit = hb.stop()
        gc.collect()
        cp = {"rows": m.total_count(), "insertSeconds": round(ins, 2), "insertRowsPerS": round(add / ins) if ins else 0,
              "heartbeatDuringInsert": {k: jit[k] for k in ("maxGapMs", "p99GapMs", "gapsOver100ms")},
              "dbMiB": db_mib(repo), "bytesPerRow": round(sum(repo.size_bytes().values()) / target),
              "memory": memory_mib()}
        hb.start()
        cp["pageFirstMs"] = timed(lambda: (m.set_page(0), app.processEvents()))
        cp["pageMidMs"] = timed(lambda: (m.set_page(m.page_count() // 2), app.processEvents()))
        cp["pageLastMs"] = timed(lambda: (m.set_page(m.page_count() - 1), app.processEvents()))
        cp["firstSortMs"] = until_shown(app, m, lambda: m.sort_by("dhmix"))
        cp["sortedPageMidMs"] = timed(lambda: (m.set_page(m.page_count() // 2), app.processEvents()))
        cp["repeatSortDescMs"] = until_shown(app, m, lambda: m.sort_by("dhmix"))
        cp["sortOffMs"] = until_shown(app, m, lambda: m.sort_by("dhmix"))
        cp["labelSortMs"] = until_shown(app, m, lambda: m.sort_by("M1"))
        cp["nameSortMs"] = until_shown(app, m, lambda: m.sort_by("name"))
        from hea_calc.core.results import ModelFilter, RangeFilter
        cp["filterMs"] = until_shown(app, m, lambda: m.set_filters(
            [RangeFilter("delta", None, 4.0), RangeFilter("omega", 1.1, None), ModelFilter("M1", {"SS"})]))
        cp["filteredRows"] = m.view_count()
        cp["filteredPageLastMs"] = timed(lambda: (m.set_page(m.page_count() - 1), app.processEvents()))
        cp["clearFilterAndSortMs"] = until_shown(app, m, lambda: (m.set_filters([]), m.sort_by("name")))
        cp["detailsMs"] = timed(lambda: (win.show_details(m.row_at(0)), app.processEvents()))
        cp["removeRowMs"] = timed(lambda: (win.table.view._remove(m.row_at(1)), app.processEvents()))
        cp["heartbeatQueries"] = {k: v for k, v in hb.stop().items() if k in ("maxGapMs", "p99GapMs", "bigGaps")}
        if target <= export_max:
            cp.update(export_metrics(app, win))
        gc.collect()
        cp["memoryAfterQueries"] = memory_mib()
        cp["qtModelRows"] = m.rowCount()
        cp["qobjects"] = qobject_count(win)
        out["checkpoints"].append(cp)
        print("storage", json.dumps(cp), flush=True)
        have = m.total_count()                  # one row was removed per checkpoint
    hb.start()
    t = time.perf_counter()
    m.clear()
    app.processEvents()
    out["clearUiMs"] = round(1000 * (time.perf_counter() - t), 2)
    t = time.perf_counter()
    repo.writer.flush(timeout=3600)
    out["clearBackgroundDeleteS"] = round(time.perf_counter() - t, 2)
    out["heartbeatClear"] = {k: v for k, v in hb.stop().items() if k in ("maxGapMs", "p99GapMs")}
    out["dbMiBAfterClear"] = db_mib(repo)
    return out


def scenario_cold(app, win_factory, hb) -> dict:
    """Worst case: a fresh window, Composition sweep chosen and Calculate pressed at once (cold pool)."""
    win = win_factory()
    try:
        return run_calc(app, win, hb, "cold 30k", FIVE, 2, 32, 2, after=False, pause=0.0)
    finally:
        win.close()


def scenario_shutdown(app, win_factory, hb) -> dict:
    """Close the window while a large calculation runs: time to closed, no orphan, files gone."""
    win = win_factory()
    set_sweep(win, app, FIVE, 2, 40, 2)
    pump(app, EDIT_PAUSE_S)
    win.composition.sweep._timer.stop()
    win.composition.calc_btn.click()
    wait_until(app, lambda: win.table.model.total_count() > 2000, 60)
    pids = list(win.jobs.worker_pids())
    session = win.repo.session_dir
    t = time.perf_counter()
    win.close()
    close_ms = round(1000 * (time.perf_counter() - t), 1)
    pump(app, 0.5)
    alive = [p for p in pids if process_alive(p)]
    threads = [th.name for th in threading.enumerate() if th.name.startswith("hea-") and th.is_alive()]
    return {"closeDuringRunMs": close_ms, "workersBefore": len(pids), "orphanWorkers": len(alive),
            "sessionDirRemoved": not session.exists(), "heaThreadsAlive": threads}


SIZE = {"k": 1_000, "m": 1_000_000}


def parse_size(s: str) -> int:
    s = s.strip().lower()
    return int(float(s[:-1]) * SIZE[s[-1]]) if s[-1] in SIZE else int(s)


REAL = {430_776: (FIVE, 2, 32, 1), 1_039_776: (FIVE, 4, 40, 1), 1_527_506: (FIVE, 1, 40, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="all",
                    choices=["all", "preflight", "small", "30k", "100k", "cancel", "storage", "real", "shutdown", "cold"])
    ap.add_argument("--sizes", default="100k,200k,500k,1m,2m,5m", help="storage checkpoints (synthetic rows)")
    ap.add_argument("--export-max", default="1m", help="largest storage checkpoint that also exports CSV")
    ap.add_argument("--real", default="430k,1m", help="real-engine runs: 430k (430 776) and/or 1m (1 039 776)")
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--unlock-limit", action="store_true", help="lift the composition guard for the real runs")
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
    if a.unlock_limit:
        from hea_calc.ui.widgets import composition_panel
        composition_panel.SWEEP_LIMIT = 10**12
    win = make_window(app)
    hb = Heartbeat()
    results: dict = {"platform": app.platformName(), "jitterLimitMs": JITTER_LIMIT_MS, "cpus": os.cpu_count(),
                     "workers": win.jobs.workers}
    sc = a.scenario
    try:
        if sc in ("all", "preflight"):
            results["preflight"] = scenario_preflight(app, win, hb)
            print("preflight", json.dumps(results["preflight"]), flush=True)
        if sc in ("all", "small"):
            results["small"] = scenario_small(app, win, hb)
            print("small", json.dumps(results["small"]), flush=True)
        if sc in ("all", "30k"):
            results["30k"] = run_calc(app, win, hb, "30k", FIVE, 2, 32, 2)
            print("30k", json.dumps(results["30k"]), flush=True)
        if sc in ("all", "100k"):
            results["100k"] = run_calc(app, win, hb, "100k", FIVE, 2, 40, 2)
            print("100k", json.dumps(results["100k"]), flush=True)
        if sc in ("all", "cancel"):
            results["cancel"] = scenario_cancel(app, win, hb)
            print("cancel", json.dumps(results["cancel"]), flush=True)
        if sc == "real":
            for s in a.real.split(","):
                n = parse_size(s)
                key = min(REAL, key=lambda k: abs(k - n))
                els, lo, hi, step = REAL[key]
                results[f"real{key}"] = run_calc(app, win, hb, f"real {key:,}", els, lo, hi, step)
                print(f"real{key}", json.dumps(results[f"real{key}"]), flush=True)
            results["cancelLarge"] = scenario_cancel(app, win, hb, FIVE, 4, 40, 1, after_s=5.0)
            print("cancelLarge", json.dumps(results["cancelLarge"]), flush=True)
        if sc == "storage":
            sizes = [parse_size(s) for s in a.sizes.split(",")]
            results["storage"] = scenario_storage(app, win, hb, sizes, parse_size(a.export_max))
        if sc in ("all", "cold"):
            results["cold"] = scenario_cold(app, lambda: make_window(app), hb)
            print("cold", json.dumps(results["cold"]), flush=True)
        if sc in ("all", "shutdown"):
            results["shutdown"] = scenario_shutdown(app, lambda: make_window(app), hb)
            print("shutdown", json.dumps(results["shutdown"]), flush=True)
    finally:
        t = time.perf_counter()
        win.close()
        app.processEvents()
        results["finalCloseMs"] = round(1000 * (time.perf_counter() - t), 1)
    failures = []
    for k, r in results.items():
        if not isinstance(r, dict):
            continue
        hbr = r.get("heartbeat")
        if k != "small" and hbr and hbr["maxGapMs"] > JITTER_LIMIT_MS:
            failures.append(f"{k}: max event-loop gap {hbr['maxGapMs']} ms")
        if "ok" in r and not r["ok"]:
            failures.append(f"{k}: did not complete")
        for cp in r.get("checkpoints", []):
            for hk in ("heartbeatDuringInsert", "heartbeatQueries"):
                if cp[hk]["maxGapMs"] > JITTER_LIMIT_MS:
                    failures.append(f"storage {cp['rows']:,}: {hk} max gap {cp[hk]['maxGapMs']} ms")
        if k == "shutdown" and (r["orphanWorkers"] or not r["sessionDirRemoved"]):
            failures.append("shutdown: orphan workers or session files left")
    results["failures"] = failures
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("FAILURES:" if failures else "PASS", *failures, sep="\n  ")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
