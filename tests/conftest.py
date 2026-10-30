import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REF = Path(__file__).resolve().parent / "reference"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REF) not in sys.path:
    sys.path.insert(0, str(REF))

from hea_calc.core.engine import Engine  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    return Engine()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Destroy the main/analysis windows a test body created and left open.  close() only hides a top-level widget;
    a leaked MainWindow stays connected to THEME.changed and is re-polished on every later theme switch, so the
    suite slowed down the longer it ran.  Windows that existed before the body (fixtures, application singletons
    such as the tooltip and Help) are left to their owners."""
    app = _qapp()
    before = set(app.topLevelWidgets()) if app is not None else set()
    yield
    app = _qapp()
    if app is None:
        return
    from PySide6.QtCore import QEvent
    from hea_calc.ui.analysis.panel import AnalysisPanel
    from hea_calc.ui.main_window import MainWindow
    leaked = [w for w in app.topLevelWidgets()
              if w not in before and isinstance(w, (MainWindow, AnalysisPanel))]
    for w in leaked:
        w.close()
        w.deleteLater()
    if leaked:
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def _qapp():
    """The running QApplication, without importing Qt for the suites that never start one."""
    if "PySide6.QtWidgets" not in sys.modules:
        return None
    return sys.modules["PySide6.QtWidgets"].QApplication.instance()


def settle_composition(win, app, timeout: float = 60.0) -> None:
    """Composition setup recounts after a pause (debounced, in the background) and its footer says "Updating…"
    meanwhile, with Calculate disabled (Figma State=Recalculating).  Run the pending pre-flight now and wait for
    it, as a user would wait for the footer to say Ready."""
    import time
    comp = win.composition
    if comp.mode == "sweep":
        sw = comp.sweep
        sw._timer.stop()
        sw._update_summary()
        task = sw._counter
    elif comp.mode == "expression":
        e = comp.expr                      # explicit Parse (inline syntax), then the background count
        e.parse()
        task = e._counter
    else:
        app.processEvents()
        return
    t0 = time.perf_counter()
    while task.busy and time.perf_counter() - t0 < timeout:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
