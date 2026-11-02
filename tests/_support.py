"""Shared test helpers: synthetic result sets, demo rows, process memory and an unexpected-window watcher.

* :func:`synthetic_chunk` / :func:`fill` - chunks of ``base`` real engine results replicated (column arrays repeated)
  to any size, with distinct names (``SYN...``) and a deterministic per-row perturbation of a few numeric columns so
  sorts and filters see realistic value spreads.  Values are engine outputs of a small set of alloys: use for
  repository and query tests only, never as new calculations;
* :func:`demo_rows` - calculated rows of an Al_x CoCrFeNi series appended to a main window;
* :func:`memory_mib` / :func:`process_alive` - process memory and liveness (Windows API, POSIX fallback);
* :class:`WindowWatch` - an application-wide event filter that records every top-level window shown and lists any
  that is not one of the application's intended windows (a widget shown while it has no parent becomes a native
  top-level window, which reads as a small window flashing open and shut).
"""

from __future__ import annotations

import ctypes
import os
from array import array
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QDialog, QMenu, QWidget

from hea_calc.core.chunks import pack_results, with_metadata


# ---------------------------------------------------------------------- synthetic result sets
def _base(engine, base: int):
    comps = [{"Fe": 1 + i % 7, "Co": 1 + (i // 7) % 3, "Ni": 1 + i % 3, "Cr": 0.5 + i % 5, "Mn": 0.2 + (i % 4) * 0.4}
             for i in range(base)]
    comps[-1] = {"Fe": 1.0}                         # one engine error row (N/A everywhere)
    return comps, pack_results(comps, [engine.calculate(c) for c in comps])


_CACHE: dict = {}


def synthetic_chunk(engine, n: int, start: int = 0, base: int = 50, source: str = "sweep") -> dict:
    """``n`` rows (names ``SYN<start+i>``) replicated from ``base`` real results."""
    key = (id(engine), base)
    if key not in _CACHE:
        _CACHE[key] = _base(engine, base)
    comps, ch = _CACHE[key]
    reps = -(-n // base)
    big = {"n": n, "strings": ch["strings"], "elements": ch["elements"], "families": ch["families"],
           "cancelled": False}
    for k in ("el_idx", "warnings", "errors", "temps", "fam_idx", "n_els"):
        big[k] = (ch[k] * reps)[:n]
    for k in ("comp", "amounts"):
        big[k] = (ch[k] * reps)[:n]
    for group in ("num", "text", "labels", "notes", "status", "na_kind"):
        big[group] = {k: (v * reps)[:n] for k, v in ch[group].items()}
    # spread a few columns so a sort is not mostly ties (deterministic, small)
    for k, scale in (("dhmix", 1e-7), ("delta", 1e-8), ("omega", 1e-7), ("phi_king", 1e-8)):
        col = big["num"][k]
        big["num"][k] = array("d", (v + scale * ((i + start) % 100_003) if v == v else v for i, v in enumerate(col)))
    return with_metadata(big, [f"SYN{start + i}" for i in range(n)], source)


def fill(repo, n: int, engine, chunk: int = 5000, mode: str = "sweep", run_id: int | None = None) -> int:
    """Insert ``n`` synthetic rows as one run through the single writer (synchronous commits)."""
    if run_id is None:
        run_id = repo.create_run(mode, settings={}, elements=["Fe", "Co", "Ni", "Cr", "Mn"], expected=n,
                                 source={"synthetic": True})
    done = 0
    while done < n:
        k = min(chunk, n - done)
        repo.append_chunk(run_id, synthetic_chunk(engine, k, done))
        done += k
    repo.finalize_run(run_id, "complete")
    return run_id


# ---------------------------------------------------------------------- demo rows
def demo_rows(win, n: int):
    """Append ``n`` calculated rows (an Al_x CoCrFeNi series) so the table overflows the viewport."""
    from PySide6.QtWidgets import QApplication

    names, comps = [], []
    for i in range(n):
        x = round(0.05 * (i + 1), 2)
        names.append(f"Al{x:g}CoCrFeNi")
        comps.append({"Al": x, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1})
    rows = []
    from hea_calc.core.results import ResultRow
    for name, c in zip(names, comps):
        rows.append(ResultRow(name, c, win.engine.calculate(c, **win.options()), "single", {}))
    win._add_rows(rows, select_first=False)
    QApplication.processEvents()


# ---------------------------------------------------------------------- process memory (Windows)
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


# ---------------------------------------------------------------------- unexpected top-level windows
INTENDED = ("MainWindow", "HelpWindow", "AboutWindow", "AnalysisWindow", "CarbonToolTip", "Toggletip",
            "_TriggerShadow", "QFileDialog", "QColorDialog", "QPrintDialog")


class WindowWatch(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.shown: list[tuple[str, str]] = []
        self.unexpected: list[tuple[str, str, str]] = []

    def __enter__(self):
        self.app.installEventFilter(self)
        return self

    def __exit__(self, *exc):
        self.app.removeEventFilter(self)
        return False

    @staticmethod
    def intended(w: QWidget) -> bool:
        if isinstance(w, (QDialog, QMenu)):
            return True
        if w.windowFlags() & Qt.WindowType.Popup == Qt.WindowType.Popup:          # dropdown lists, popovers
            return True
        if w.windowFlags() & Qt.WindowType.ToolTip == Qt.WindowType.ToolTip:
            return True
        return any(c.__name__ in INTENDED for c in type(w).__mro__)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            name = type(obj).__name__
            self.shown.append((name, obj.objectName()))
            if not self.intended(obj):
                text = ""
                for attr in ("text", "windowTitle"):
                    try:
                        text = text or str(getattr(obj, attr)())[:60]
                    except Exception:                   # noqa: BLE001 - diagnostics only
                        pass
                self.unexpected.append((name, obj.objectName(), text))
        return False
