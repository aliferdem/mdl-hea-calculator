"""MateBook native DPI pass (2026-10-18): responsive breakpoint at Analysis' MINIMUM width, and native-window
lifetime (no "External WM_DESTROY received for ... AppBodyWindow" at exit).

design/implementation/MATEBOOK_NATIVE_DPI_AUDIT.md records the native evidence.  The native shutdown test opens real
Windows windows, so it runs only with ``HEA_NATIVE_TESTS=1`` on Windows; everything else runs offscreen.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


def pump(app, n=4):
    for _ in range(n):
        app.processEvents()


@pytest.fixture()
def win(app):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1095, 670)
    w.show()
    pump(app)
    yield w
    w.close()
    w.deleteLater()
    pump(app)


def threshold() -> int:
    """The client width at which the wide row first fits - derived from the layout constants, not a screen size."""
    from hea_calc.ui.theme import (CONTENT_MARGIN_X, COMPOSITION_PANEL_WIDTH, DETAILS_PANEL_MIN, ELEMENT_PANEL_WIDTH,
                                   PANEL_GAP)
    return CONTENT_MARGIN_X + ELEMENT_PANEL_WIDTH + PANEL_GAP + COMPOSITION_PANEL_WIDTH + PANEL_GAP \
        + DETAILS_PANEL_MIN + CONTENT_MARGIN_X


def native_children():
    return [w.objectName() or type(w).__name__ for w in QApplication.allWidgets()
            if not w.isWindow() and w.internalWinId()]


# ====================================================================== responsive breakpoint
def test_breakpoint_uses_the_analysis_minimum_not_its_preferred_width():
    from hea_calc.ui import theme
    assert theme.ANALYSIS_WIDE_MIN == theme.DETAILS_PANEL_MIN == 454
    assert theme.ANALYSIS_PANEL_WIDTH == 829, "829 (Figma) stays the preferred (reference) width"
    assert theme.ANALYSIS_WIDE_MIN < theme.ANALYSIS_PANEL_WIDTH
    assert threshold() == 1545


def test_upper_row_alone_switches_exactly_at_the_minimum(app):
    from hea_calc.ui.widgets.layouts import UpperPanels
    a, b, c = QWidget(), QWidget(), QWidget()
    row = UpperPanels([(a, 570, 570, 570), (b, 457, 457, 457), (c, 829, 454, None)], 490, 16, stacked_height=720)
    assert row.wide_minimum() == 1513
    assert row.mode_for(1512) and not row.mode_for(1513) and not row.mode_for(1514)
    row.stacked = True                          # no hysteresis: a stacked row returns to wide at the same width
    assert not row.mode_for(1513)


def test_window_width_sweep_across_the_breakpoint(win, app):
    t = threshold()
    tlw, tlwin = len(QApplication.topLevelWidgets()), len(QGuiApplication.topLevelWindows())
    seen = {}
    for w in (t + 2, t + 1, t, t - 1, t - 2, t - 1, t, t + 1, t + 2):   # narrowing, then widening back
        win.resize(w, 800)
        pump(app, 3)
        rep = win.layout_report()
        assert rep["contentWidth"] == win.width() == w, "logical px only: no DPR scaling of the comparison"
        e, c, a = rep["upperPanels"]
        assert (e, c) == (570, 457), "Elements and Composition never resize"
        seen.setdefault(w, set()).add(rep["detailsStacked"])
        if w >= t:
            assert not rep["detailsStacked"], w
            assert a == w - t + 454 >= 454, (w, a)
        else:
            assert rep["detailsStacked"], w
            assert a == w - 32, "stacked Analysis spans the full content width"
        assert len(QApplication.topLevelWidgets()) == tlw and len(QGuiApplication.topLevelWindows()) == tlwin, \
            "no transient top-level window while crossing the breakpoint"
        assert not native_children()
    assert all(len(v) == 1 for v in seen.values()), "same width, same mode in both directions"


@pytest.mark.parametrize("client, wide, analysis", [
    (1095, False, None),        # first-run default: stacking allowed
    (1440, False, None),        # maximized at 150 % on a 2160 px display
    (1728, True, 637),          # maximized at 125 % on a 2160 px display (MateBook 14, native)
    (1920, True, 829),          # the design frame: Analysis at its preferred width
    (2160, True, 1069),         # 100 %: the surplus goes to Analysis only
])
def test_logical_client_widths(win, app, client, wide, analysis):
    win.resize(client, 900)
    pump(app, 3)
    rep = win.layout_report()
    assert rep["detailsStacked"] is (not wide)
    assert rep["upperPanels"][:2] == [570, 457]
    if wide:
        assert rep["upperPanels"][2] == analysis


# ====================================================================== point inspector popover
@pytest.mark.parametrize("client", [1728, 1920])
def test_point_inspector_popover_shows_every_model_above_its_buttons(win, app, client):
    """MateBook 125 % visual QA: the popover took its height from the content's sizeHint, for which the model-tag
    FlowBox assumes 4 columns (2 rows); at the popover's 288 px content width only 3 fit, so the third row (M7, M8)
    was painted under "Analyse composition".  The height now follows heightForWidth at the content width."""
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis.widgets import FlowBox
    from hea_calc.ui.widgets.dropdown import Popover
    win.resize(client, 1000)
    pump(app)
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    win.table.model.refresh_committed()
    win.analysis_ctl.run_finished(run)
    win._check_details()
    c = win.analysis_ctl

    def settle():
        for _ in range(8):
            c.wait_idle(30)
            pump(app, 2)
    c.apply(S.switch_context, S.COLLECTION)
    settle()
    c.scope_for(run, "full")
    settle()
    c.apply(S.set_tab, "plots")
    settle()
    coll = win.analysis.collection
    assert coll.size_class != "W" and coll.plot is not None
    coll._point_clicked(coll.plot.spec.data["ids"][0])
    pump(app)
    pops = [w for w in QApplication.topLevelWidgets() if isinstance(w, Popover) and w.isVisible()]
    assert len(pops) == 1
    pop = pops[0]
    try:
        flow = pop.findChild(FlowBox)
        content = flow.parentWidget()
        rows = -(-len(flow.cells) // flow.columns(flow.width()))
        assert flow.height() == flow.heightForWidth(flow.width()) and rows == 3, (flow.width(), flow.height())
        cells_bottom = max(cl.geometry().bottom() for cl in flow.cells)
        assert cells_bottom < flow.height(), "every model tag lies inside the tag grid"
        buttons = [b for b in content.findChildren(QWidget) if hasattr(b, "text") and callable(b.text)
                   and b.text() in ("Analyse composition", "Show in results table")]
        assert len(buttons) == 2
        flow_bottom = flow.mapTo(content, flow.rect().bottomLeft()).y()
        assert flow_bottom < min(b.mapTo(content, b.rect().topLeft()).y() for b in buttons), \
            "the M7 / M8 row is not hidden under the action buttons"
        assert content.rect().contains(content.childrenRect()), "nothing painted past the content box"
        assert pop.rect().contains(content.geometry()), "the content fits the popover body"
    finally:
        pop.close()
        pump(app)


# ====================================================================== native window lifetime
def test_titlebar_theming_never_creates_a_native_handle(app):
    from hea_calc.ui import win_titlebar
    from hea_calc.ui.theme import THEME
    top = QWidget(None, Qt.WindowType.Window)                 # never shown: no handle
    assert not win_titlebar.apply(top, THEME.name, THEME.tokens)
    assert not top.testAttribute(Qt.WidgetAttribute.WA_WState_Created) and not top.internalWinId()
    parent = QWidget()
    child = QWidget(parent)                                   # an ordinary child is never themed
    assert not win_titlebar.apply(child, THEME.name, THEME.tokens)
    assert not child.internalWinId() and not parent.internalWinId()


def test_closing_owned_windows_leaves_no_native_child(win, app):
    """Closing Help / About destroys their native handles (WinIdChange to 0); the title-bar themer used to
    re-create the handle from that event, and the main window's central AppBody became a native child window."""
    win.show_help("home")
    pump(app)
    win._help.close()
    pump(app)
    win.show_about()
    pump(app)
    win._about.close()
    pump(app)
    assert not native_children()
    assert not win.centralWidget().testAttribute(Qt.WidgetAttribute.WA_NativeWindow)


NATIVE_SCRIPT = textwrap.dedent("""
    import ctypes, multiprocessing, os, sys
    if __name__ == "__main__":
        multiprocessing.freeze_support()
        sys.path.insert(0, os.getcwd())
        from PySide6.QtCore import QSettings, QTimer
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        from hea_calc.ui.theme import load_fonts
        load_fonts()
        from hea_calc.ui.main_window import MainWindow
        win = MainWindow(settings=QSettings(sys.argv[1], QSettings.Format.IniFormat))
        win.show_initial()
        post = lambda w: ctypes.windll.user32.PostMessageW(int(w.winId()), 0x0010, 0, 0)   # WM_CLOSE
        steps = [lambda: win.show_help("home"), lambda: post(win._help), win.show_about, lambda: post(win._about),
                 lambda: win.show_help("home"), lambda: post(win)]
        def nxt():
            if steps:
                steps.pop(0)()
                QTimer.singleShot(400, nxt)
        QTimer.singleShot(600, nxt)
        sys.exit(app.exec())
""")


@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("HEA_NATIVE_TESTS") != "1",
                    reason="opens real windows; set HEA_NATIVE_TESTS=1 on a Windows desktop")
def test_native_shutdown_stderr_is_clean(tmp_path):
    script = tmp_path / "native_close.py"
    script.write_text(NATIVE_SCRIPT, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    env["QT_FORCE_STDERR_LOGGING"] = "1"         # without a console Qt logs to OutputDebugString, not stderr
    p = subprocess.run([sys.executable, str(script), str(tmp_path / "s.ini")], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    assert "WM_DESTROY" not in p.stderr and not p.stderr.strip(), p.stderr
