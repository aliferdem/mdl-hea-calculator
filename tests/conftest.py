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


# ---------------------------------------------------------------------------------------------- test groups
# Every test belongs to exactly one group, so a change can be checked without the whole suite:
#   uv run pytest -m ui      Qt interface tests (widgets, windows, layout, theme)
#   uv run pytest -m core    calculations, datasets, models, export and storage, without a window
#   uv run pytest -m perf    timing budgets and large workloads (benchmarks, million-row tables, cancellation)
#   uv run pytest -m "not perf"   everything except the slow performance group
# A performance test that opens a window is in ``perf``, not ``ui``.
GROUPS = {"ui": "Qt interface tests", "core": "calculation, data and export tests without a window",
          "perf": "timing budgets and large workloads"}
PERF_MODULES = {"test_benchmarks.py", "test_large_workflows.py"}
PERF_TESTS = {
    "test_final_interaction.py::test_large_clear_undo_copies_no_rows_into_python",
    "test_repository.py::test_large_build_runs_in_the_background_and_keeps_the_old_page",
    "test_repository.py::test_cancel_with_a_full_writer_queue_is_fast_and_keeps_a_contiguous_prefix",
    "test_repository.py::test_sweep_summary_reports_large_sets_instead_of_refusing_them",
    "test_repository.py::test_beyond_the_largest_tested_batch_is_refused_plainly",
    "test_space_units.py::test_large_wt_space_counts_in_bounded_time",
    "test_variables_export.py::test_variables_export_performance",
    "test_view_consistency.py::test_deleting_rows_in_a_large_view_keeps_every_page_exact",
}
_UI_MARKS = ("QApplication", "_ui_support", "MainWindow", "QWidget")
_UI_MODULES: dict[str, bool] = {}


def pytest_configure(config):
    for name, text in GROUPS.items():
        config.addinivalue_line("markers", f"{name}: {text}")


def group_of(item) -> str:
    """The group of a collected test: ``perf`` (listed above), else ``ui`` (its module builds Qt widgets), else
    ``core``."""
    path = Path(str(item.fspath))
    if path.name in PERF_MODULES or f"{path.name}::{item.originalname or item.name}" in PERF_TESTS:
        return "perf"
    if path.name not in _UI_MODULES:
        text = path.read_text(encoding="utf-8", errors="replace")
        _UI_MODULES[path.name] = any(m in text for m in _UI_MARKS)
    return "ui" if _UI_MODULES[path.name] else "core"


def pytest_collection_modifyitems(config, items):
    for item in items:
        item.add_marker(getattr(pytest.mark, group_of(item)))


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
