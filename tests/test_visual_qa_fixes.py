"""Regressions for the release-candidate visual QA (``design/implementation/FRONTEND_VISUAL_QA_REPORT.md``):
F-01 per-tab height of the expanded Analysis workspace, F-02 Elements frozen while calculating, F-03 one menu
elevation (no windows11 drop-shadow effect), F-04 open File trigger on the menu surface, F-05 trigger and menu
as one elevated surface, F-08 a screen-edge menu flush with its trigger, F-06 the workload estimate ellipsis.

Offscreen (Fusion) cannot show the windows11 effect itself; the F-03 tests therefore install it the way the
style does, or load the windows11 style explicitly when it is available.  The native (windows platform)
capture check is recorded in the report's re-verification section.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QGraphicsDropShadowEffect, QLabel, QPushButton, QStyleFactory,
                               QVBoxLayout, QWidget)


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


def pump(app, n: int = 4):
    for _ in range(n):
        app.processEvents()


def _wait(app, cond, limit=60):
    t0 = time.perf_counter()
    while not cond() and time.perf_counter() - t0 < limit:
        app.processEvents()
        time.sleep(0.01)
    pump(app)


@pytest.fixture()
def win(app):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("light")
    st = QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=st)
    w.resize(1920, 1000)
    w.show()
    pump(app)
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


# ====================================================================== F-01
def test_current_stack_measures_only_its_current_page(app):
    """QStackedLayout reports the largest height-for-width of all pages, and QWidgetItem asks the layout
    directly - a tall hidden page must not size the stack or its parent."""
    from hea_calc.ui.analysis.widgets import CurrentStack
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    stack = CurrentStack()
    lay.addWidget(stack)
    short = QLabel("short")
    short.setWordWrap(True)
    tall = QLabel(" ".join(["word"] * 2000))
    tall.setWordWrap(True)
    stack.addWidget(short)
    stack.addWidget(tall)
    host.resize(400, 100)
    host.show()
    pump(app)
    stack.setCurrentIndex(1)
    pump(app)
    tall_h = host.heightForWidth(400)
    assert tall_h > 500
    seen: list[int] = []
    stack.currentChanged.connect(seen.append)
    stack.setCurrentIndex(0)
    pump(app)
    assert seen == [0] and stack.currentIndex() == 0 and stack.currentWidget() is short
    assert stack.heightForWidth(400) == short.heightForWidth(400)
    assert host.heightForWidth(400) < 100, "the parent layout no longer inherits the tall page"
    assert stack.sizeHint() == short.sizeHint() and stack.count() == 2 and stack.indexOf(tall) == 1
    host.close()


def test_expanded_tabs_do_not_inherit_the_statistics_height(win, app):
    """F-01: after Statistics, Overview has no empty scroll range and the plot keeps its pre-Statistics height."""
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    win.table.model.refresh_committed()
    c = win.analysis_ctl

    def settle():
        for _ in range(10):
            c.wait_idle(30)
            pump(app, 2)

    c.run_finished(run)
    c.apply(S.switch_context, S.COLLECTION)
    c.scope_for(run, "full")
    c.apply(S.update, plot="line")
    c.apply(S.set_tab, "overview")
    win.set_expanded(True)
    settle()
    bar = win.workspace_scroll.verticalScrollBar()
    coll = win.workspace.collection
    overview_before = bar.maximum()
    c.apply(S.set_tab, "plots")
    settle()
    plots_before, plot_h = bar.maximum(), coll.plot.height()
    c.apply(S.set_tab, "statistics")
    settle()
    assert bar.maximum() > plots_before, "Statistics is the tall page (precondition)"
    c.apply(S.set_tab, "overview")
    settle()
    assert bar.maximum() == overview_before
    c.apply(S.set_tab, "plots")
    settle()
    assert (bar.maximum(), coll.plot.height()) == (plots_before, plot_h)
    stack = coll.stack
    assert stack.height() == stack.currentWidget().heightForWidth(stack.width()) or not \
        stack.currentWidget().hasHeightForWidth()
    win.set_expanded(False)


# ====================================================================== F-02
def _start_sweep(win, app, lo, hi, step):
    for el in ("Cr", "Mn", "Fe", "Co", "Ni"):
        if not win.elements.table.tiles[el].isChecked():
            win.elements.table.tiles[el].click()
    comp = win.composition
    comp.set_mode(1)
    comp.set_basis("at")
    for r in comp.sweep.rows.values():
        r.min.setText(str(lo)), r.max.setText(str(hi)), r.step.setText(str(step))
    sw = comp.sweep
    sw._timer.stop()
    sw._update_summary()
    _wait(app, lambda: not sw._counter.busy, 30)
    comp.calc_btn.click()


def test_elements_are_frozen_while_calculating(win, app):
    """F-02: while State = Calculating no click, Space or Enter on a tile changes the running setup; hover still
    inspects the element; the tiles accept input again afterwards."""
    _start_sweep(win, app, 2, 40, 2)                          # 94 381 compositions: long enough to observe
    _wait(app, lambda: win.worker is not None)
    table = win.elements.table
    ti = table.tiles["Ti"]
    before = list(win.composition.current_elements())
    assert ti.read_only and not ti.isChecked()
    QTest.mouseClick(ti, Qt.MouseButton.LeftButton)
    ti.click()
    ti.setFocus()
    QTest.keyClick(ti, Qt.Key.Key_Space)
    QTest.keyClick(table, Qt.Key.Key_Return)
    pump(app)
    assert not ti.isChecked() and "Ti" not in table.selected()
    assert win.composition.current_elements() == before, "the running setup is unchanged"
    QTest.mouseClick(table.tiles["Fe"], Qt.MouseButton.LeftButton)
    assert table.tiles["Fe"].isChecked(), "a selected tile cannot be cleared either"
    table.tiles["Ti"].hovered.emit("Ti")
    assert "Titanium" in win.elements.info.name.text(), "hover inspection still works"
    win.cancel_calculation()
    _wait(app, lambda: win.worker is None)
    assert not ti.read_only
    QTest.mouseClick(ti, Qt.MouseButton.LeftButton)
    pump(app)
    assert ti.isChecked() and "Ti" in win.composition.current_elements()


# ====================================================================== F-03
def _menu(app, parent=None, size="lg"):
    from hea_calc.ui.widgets.menu import CarbonMenu
    m = CarbonMenu(parent=parent, size=size)
    for text in ("Import compositions", "Export results", "Exit"):
        m.add_action(text, lambda: None)
    return m


def test_menu_strips_a_style_drop_shadow_effect(app):
    """F-03: the windows11 style sets a QGraphicsDropShadowEffect in polish(); every (re-)polish removes it."""
    m = _menu(app)
    m.ensurePolished()
    assert m.graphicsEffect() is None
    m.setGraphicsEffect(QGraphicsDropShadowEffect(m))     # what QWindows11Style::polish does
    QApplication.sendEvent(m, QEvent(QEvent.Type.StyleChange))
    assert m.graphicsEffect() is None
    m.setGraphicsEffect(QGraphicsDropShadowEffect(m))
    m.popup(QPoint(100, 100))
    pump(app)
    assert m.graphicsEffect() is None, "stripped again before the menu is shown"
    m.close()


def test_menu_has_no_effect_under_the_windows11_style(app):
    style = QStyleFactory.create("windows11")
    if style is None:
        pytest.skip("windows11 style not available on this platform")
    m = _menu(app)
    m.setStyle(style)                                      # polish(): the style installs its drop shadow here
    m.ensurePolished()
    assert m.graphicsEffect() is None
    m._apply_style()                                       # a stylesheet change re-polishes the menu
    assert m.graphicsEffect() is None
    m.popup(QPoint(100, 100))
    pump(app)
    assert m.graphicsEffect() is None
    img = m.grab().toImage()
    s = m.surface()
    # Carbon's own elevation is symmetric: the right and left shadow columns match (no 3 px right band)
    y = s.center().y()
    left = img.pixelColor(s.left() - 2, y).alpha()
    right = img.pixelColor(s.right() + 2, y).alpha()
    assert abs(left - right) <= 2, (left, right)
    m.close()


# ====================================================================== F-04 / F-05
def test_open_file_trigger_is_on_the_menu_surface_under_the_mouse(win, app):
    """F-04: opened with the mouse the trigger stays under the pointer; [open] outranks :hover."""
    from hea_calc.ui.theme import t
    item = win.header.file_item
    QTest.mouseMove(item, QPoint(10, 10))
    pump(app)
    assert item.underMouse()
    from PySide6.QtCore import QRect
    bar = win.header
    img = bar.grab(QRect(item.mapTo(bar, QPoint(0, 0)), item.size())).toImage()     # over the bar's surface
    hover = QColor(t("titlebar-hover"))                                   # Figma background-hover over the bar
    shell = QColor(t("shell"))
    a = hover.alphaF()
    expect = [round(c1 * a + c2 * (1 - a)) for c1, c2 in zip(hover.getRgb()[:3], shell.getRgb()[:3])]
    got = img.pixelColor(4, item.height() // 2).getRgb()[:3]
    assert max(abs(x - y) for x, y in zip(got, expect)) <= 2, ("hover (precondition)", got, expect)
    item._set_open(True)
    img = item.grab().toImage()
    assert img.pixelColor(4, item.height() // 2).name() == QColor(t("layer-02")).name(), "open wins over hover"
    item._set_open(False)
    QTest.mouseMove(win.header, QPoint(win.header.width() // 2, 24))
    pump(app)


@pytest.mark.parametrize("which", ["file", "view"])
def test_header_menu_and_trigger_are_one_elevated_surface(win, app, which):
    """F-05: one union outline for trigger + menu.  The menu window stays an ordinary QMenu (offsetting its items
    under the trigger broke QMenu's hit area for the last item); the trigger's share of the shadow is a separate,
    input-transparent window that ends where the menu window begins.  The join has no seam."""
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.menu import SHADOW
    hdr = win.header
    # the title bar menus (File, and View - which holds the Theme choices) open merged with their trigger
    trigger, m = (hdr.file_item, win.file_menu) if which == "file" else (hdr.view_item, win.view_menu)
    trigger._set_open(True)
    m.trigger_width = 0
    m.open_below(trigger, exec_=False, merge=True)
    pump(app)
    try:
        assert m.tab is not None and m.tab.size() == trigger.size()
        tl = trigger.mapToGlobal(QPoint(0, 0))
        assert m.mapToGlobal(m.tab.topLeft()) == tl, "the tab is exactly the trigger"
        s = m.surface()
        assert s == m.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW), "an ordinary menu window"
        assert m.mapToGlobal(s.topLeft()).y() == tl.y() + trigger.height(), "surface flush under the trigger"
        img = m.grab().toImage()
        surf = QColor(t("layer-02")).name()
        tab_x = (m.tab.left() + 1, m.tab.center().x(), m.tab.right() - 1)
        for x in tab_x:
            assert img.pixelColor(x, s.top()).name() == surf, "no seam across the join"
            assert img.pixelColor(x, s.top() - 1).alpha() == 0, "nothing painted over the trigger's bottom edge"
        ov = m._overlay
        assert ov is not None and ov.isVisible() and ov.windowFlags() & Qt.WindowType.WindowTransparentForInput
        oimg = ov.grab().toImage()
        mid = ov.mapFromGlobal(trigger.mapToGlobal(trigger.rect().center()))
        assert oimg.pixelColor(mid).alpha() == 0, "the real trigger shows through"
        assert oimg.pixelColor(SHADOW - 2, mid.y()).alpha() > 0, "the trigger's outer edge is elevated"
        assert m.mapToGlobal(s.topLeft()).x() == tl.x()
    finally:
        m.close()
        pump(app)
    assert not trigger.property("open")


def test_press_on_the_merged_trigger_closes_the_menu(win, app):
    item, m = win.header.file_item, win.file_menu
    item._set_open(True)
    m.trigger_width = 0
    m.open_below(item, exec_=False, merge=True)
    pump(app)
    assert m.isVisible()
    QTest.mousePress(m, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, m.tab.center())
    pump(app)
    assert not m.isVisible() and not item.property("open")


def test_unmerged_opening_resets_the_tab(win, app):
    """A menu opened without ``merge`` (toolbar MenuButtons, context menus) has no tab and no overlay."""
    from hea_calc.ui.widgets.menu import SHADOW
    m = _menu(app, parent=win)
    m.open_below(win.header.file_item, exec_=False, merge=True)
    pump(app)
    merged_h = m.height()
    assert m.tab is not None and m._overlay.isVisible()
    m.close()
    m.open_below(win.header.file_item, exec_=False)
    pump(app)
    assert m.tab is None and m.surface().top() == SHADOW and m.height() == merged_h
    assert not m._overlay.isVisible()
    m.close()


# ====================================================================== F-08
def test_menu_at_the_screen_edge_stays_flush_with_its_trigger(app):
    """F-08: Qt clamps the popup - shadow margin included - to the screen; the margin hangs off-screen instead."""
    scr = QGuiApplication.primaryScreen().geometry()
    host = QWidget(None, Qt.WindowType.FramelessWindowHint)
    host.setGeometry(scr.right() + 1 - 200, scr.top() + 40, 200, 48)
    btn = QPushButton("T", host)
    btn.setGeometry(200 - 48, 0, 48, 48)
    host.show()
    pump(app)
    m = _menu(app, parent=host)
    m.trigger_width = 0
    m.open_below(btn, exec_=False, align_right=True, merge=True)
    pump(app)
    s = m.surface()
    assert m.mapToGlobal(s.topRight()).x() == btn.mapToGlobal(QPoint(btn.width() - 1, 0)).x() == scr.right()
    assert m.geometry().right() == scr.right() + 6, "the transparent margin hangs off-screen"
    m.close()
    host.close()


# ====================================================================== F-06
def test_workload_estimate_ends_in_an_ellipsis_with_a_tooltip(app):
    from hea_calc.ui.widgets.composition_footer import _EstimateRow
    row = _EstimateRow()
    row.resize(400, 18)
    row.set_values("~3 min", "~853.2 MB")
    row.show()
    pump(app)
    assert not row.is_elided() and row.toolTip() == ""
    row.resize(int(row.natural_width()) - 30, 18)
    pump(app)
    assert row.is_elided() and row.toolTip() == "~3 min runtime, ~853.2 MB temp. storage"
    img = row.grab().toImage()
    assert img.width() == row.width()
    row.resize(int(row.natural_width()) + 1, 18)
    pump(app)
    assert row.toolTip() == ""
    row.close()


def test_workload_estimate_in_the_panel_is_never_cut(win, app):
    """The real Composition-space footer with a five-character storage value: it fits, or it is elided with a
    Tooltip - never a silently cut glyph."""
    est = win.composition.sweep.summary.est if hasattr(win.composition.sweep, "summary") else None
    if est is None:
        from hea_calc.ui.widgets.composition_footer import _EstimateRow
        est = next(w for w in win.composition.findChildren(_EstimateRow))
    est.set_values("~3 min", "~853.2 MB")
    pump(app)
    assert est.natural_width() <= est.width() or est.toolTip() == "~3 min runtime, ~853.2 MB temp. storage"
