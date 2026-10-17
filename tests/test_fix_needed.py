"""Acceptance tests for the fix-needed pass (``design/implementation/FIX_NEEDED_AUDIT.md``).

Shared Carbon popups (long lists, text origin), scrollbar states, the notification anatomy, the header theme icon
and the Export MenuButton.  Offscreen; the references are ``design/fix needed/CORRECT_*.png``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


def pump(app, n: int = 4):
    for _ in range(n):
        app.processEvents()


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


def _host(app, child: QWidget, w: int = 300, h: int = 120) -> QWidget:
    host = QWidget()
    host.resize(w, h)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.addWidget(child)
    lay.addStretch(1)
    host.show()
    pump(app)
    return host


def _wheel(widget: QWidget, dy: int) -> None:
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    e = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, e)


# ====================================================================== shared list popup (brief §4-6, 3.png)
def test_long_dropdown_list_is_screen_clamped_and_scrolls_with_the_wheel(app):
    from hea_calc.ui.widgets.dropdown import Dropdown
    items = [(f"v{i}", f"Option {i}") for i in range(60)]
    d = Dropdown(items, "v0", accessible="Long list")
    d.setFixedWidth(220)
    host = _host(app, d)
    d.open_menu()
    pump(app)
    pop = d.popup
    screen = QApplication.primaryScreen().availableGeometry()
    assert pop is not None and pop.isVisible()
    assert pop.height() <= screen.height() and pop.height() <= 10 * 32 + 2 * 8, "at most ten rows, never the screen"
    assert pop.geometry().top() >= screen.top() and pop.geometry().bottom() <= screen.bottom() + 1
    assert pop.scroll_scrollable(), "the rest of a long list scrolls inside the popup"
    sb = pop.scroll.verticalScrollBar()
    before = sb.value()
    _wheel(pop.scroll.viewport(), -120)
    pump(app)
    assert sb.value() > before, "the wheel scrolls the open list"
    assert d.value == "v0", "scrolling the list never changes the value"
    pop.close()
    pump(app)
    assert d.popup is None
    host.close()


def test_closed_dropdown_ignores_the_wheel(app):
    from hea_calc.ui.widgets.dropdown import Dropdown
    d = Dropdown([("a", "A"), ("b", "B")], "a", accessible="Two")
    host = _host(app, d)
    _wheel(d, -120)
    pump(app)
    assert d.value == "a"
    host.close()


def _text_columns(img, bg: QColor) -> list[int]:
    cols = []
    for x in range(6, img.width() - 44):                 # skip the focus frame and the chevron
        for y in range(6, img.height() - 6):
            c = img.pixelColor(x, y)
            if abs(c.lightness() - bg.lightness()) > 60:
                cols.append(x)
                break
    return cols


def test_dropdown_text_keeps_its_origin_when_opened(app):
    """Brief §6: the value text never moves between the closed and the open state."""
    from hea_calc.ui.widgets.dropdown import Dropdown
    d = Dropdown([("ratio", "At. ratio"), ("at", "at.%")], "ratio", accessible="Basis")
    d.setFixedSize(200, 40)
    host = _host(app, d)
    closed = d.grab().toImage()
    bg = closed.pixelColor(8, 4)
    d.open_menu()
    pump(app)
    opened = d.grab().toImage()
    a, b = _text_columns(closed, bg), _text_columns(opened, bg)
    assert a and b and a[0] == b[0] and a[-1] == b[-1], (a[:3], b[:3])
    d.popup.close()
    pump(app)
    host.close()


def test_open_list_marks_the_selected_row_and_closes_on_choice(app):
    from hea_calc.ui.widgets.dropdown import Dropdown
    d = Dropdown([("ratio", "At. ratio"), ("at", "at.%"), ("wt", "wt.%")], "at", accessible="Basis")
    host = _host(app, d)
    d.open_menu()
    pump(app)
    pop = d.popup
    assert pop.active == 1 and pop.is_selected(1)
    pop.choose(2)
    pump(app)
    assert d.value == "wt" and d.popup is None
    host.close()


# ====================================================================== scrollbars (brief §22)
def test_scrollbar_thumb_changes_colour_not_geometry_on_hover_and_drag(app):
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.scroll import ThinScrollBar
    sb = ThinScrollBar(Qt.Orientation.Vertical)
    sb.setRange(0, 1000)
    sb.setPageStep(100)
    sb.resize(12, 300)
    sb.show()
    pump(app)
    rest_rect = sb.thumb_rect()
    sb._hover, sb._drag = False, None           # the offscreen pointer may start over the bar

    def thumb_colour():
        img = sb.grab().toImage()
        r = sb.thumb_rect()
        return img.pixelColor(int(r.center().x()), int(r.center().y())).name()
    rest = thumb_colour()
    sb._hover = True
    hover = thumb_colour()
    sb._drag = (0, 0)
    active = thumb_colour()
    assert {rest, hover, active} == {t("scrollbar-thumb").lower(), t("scrollbar-thumb-hover").lower(),
                                     t("scrollbar-thumb-active").lower()}
    assert len({rest, hover, active}) == 3, "rest, hover and active are distinguishable"
    assert sb.thumb_rect() == rest_rect, "only the colour changes"
    sb.close()


# ====================================================================== notification (CORRECT_NOTIFICATION)
@pytest.mark.parametrize("kind", ["info", "success", "warning", "error"])
def test_inline_notification_anatomy(app, kind):
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.common import InlineNotification
    n = InlineNotification(closable=False)
    host = _host(app, n, 600, 140)
    n.show_message(kind, "Title", "Message")
    pump(app)
    assert n.height() >= 48
    img = n.grab().toImage()
    y = n.height() // 2
    accent = img.pixelColor(1, y).name()
    surface = img.pixelColor(n.width() // 2, y).name()
    assert accent == t(f"support-{kind}").lower(), "3 px status accent on the left edge"
    assert surface == t(f"notification-{kind}-bg").lower(), "tinted low-contrast surface"
    assert img.pixelColor(2, y).name() == accent and img.pixelColor(4, y).name() != accent, "accent is 3 px"
    assert n.title.text() == "Title" and n.body.text() == "Message"
    assert n.title.geometry().bottom() <= n.body.geometry().top(), "title above message"
    host.close()


# ====================================================================== header (CORRECT_THEME_BUTTON, §9)
@pytest.mark.parametrize("pref, icon", [("light", "brightness_contrast"), ("dark", "asleep"),
                                        ("system", "contrast")])
def test_theme_button_shows_the_selected_preference(win, app, pref, icon):
    win.prefs.set_theme(pref)
    win._sync_theme_actions()
    pump(app)
    assert win.header.theme_btn.icon_name == icon
    checked = [a.text() for a in win.theme_menu.actions() if a.isCheckable() and a.isChecked()]
    assert checked == [{"light": "Light", "dark": "Dark", "system": "System default"}[pref]]


# ====================================================================== Export MenuButton (§8, 11.png)
def test_export_menu_button_chevron_flips_and_filtered_items_follow_the_filter(win, app):
    b = win.table.export_btn
    m = b.menu()
    labels = [a.text() for a in m.actions() if a.isVisible() and not a.isSeparator()]
    assert labels[:2] == ["Excel workbook (.xlsx)", "CSV (.csv)"] and "Copy table to clipboard" in labels
    assert not any("filtered" in x.lower() for x in labels), "filtered variants only with an active filter"
    for name, comp in (("CoCrFeNi", {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}), ("CoFeNi", {"Co": 1, "Fe": 1, "Ni": 1})):
        win.calculate("single", [name], [comp], [{}])
        pump(app)
    win.table.model.wait()
    pump(app)
    win.show_in_table([r.id for r in win.table.model.page_rows()][:2])      # an explicit id filter
    win.table.model.wait()
    pump(app)
    m.aboutToShow.emit()
    labels = [a.text() for a in m.actions() if a.isVisible() and not a.isSeparator()]
    assert sum("filtered" in x.lower() for x in labels) == 2, labels
    closed = b.grab().toImage()
    b.open = True
    opened = b.grab().toImage()
    b.open = False
    x0 = b.width() - b.INDICATOR_PAD - b.CHEVRON
    region = [(x, y) for x in range(x0, x0 + b.CHEVRON) for y in range(b.height())]
    assert any(closed.pixelColor(x, y) != opened.pixelColor(x, y) for x, y in region), "chevron points up when open"


# ====================================================================== Elements / Composition (§17, §18, 8.png, 16.png)
@pytest.mark.parametrize("width", [1920, 1728, 1440, 1280])
def test_elements_and_composition_keep_fixed_geometry(app, width):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import ANALYSIS_STACKED_HEIGHT, PANEL_GAP, TILE_GAP, TILE_SIZE, t
    st = QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=st)
    w.resize(width, 1000)
    w.show()
    pump(app)
    try:
        assert w.elements.title.text() == "Elements"
        assert (w.elements.width(), w.composition.width()) == (578, 457)
        tiles = w.elements.table.tiles
        assert {(t_.width(), t_.height()) for t_ in tiles.values()} == {(28, 28)} and TILE_SIZE == 28
        assert tiles["He"].x() - tiles["H"].x() == 17 * (28 + TILE_GAP), "30 px pitch"
        img = tiles["Fe"].grab().toImage()
        assert img.pixelColor(0, 14).name() == t("border-subtle-02").lower(), "bordered tile"
        top = w.top_row
        if top.stacked:
            assert w.composition.geometry().left() == 578 + PANEL_GAP
            assert w.details.height() == ANALYSIS_STACKED_HEIGHT and w.details.width() == top.width()
        else:
            assert width >= 1920 and w.details.width() >= 805
    finally:
        w.close()


# ====================================================================== scrollbar safe area (§23, 5.png)
def _bar_overlaps(root):
    """(scroll area, control) pairs where an interactive control lies under a visible vertical scroll bar."""
    from PySide6.QtWidgets import QAbstractButton, QLineEdit, QScrollArea
    from hea_calc.ui.analysis.widgets import DataTable
    from hea_calc.ui.widgets.scroll import ThinScrollBar
    kinds = (QAbstractButton, QLineEdit, DataTable)       # controls and painted rows with icon / value columns
    out = []
    bars = [b for b in root.findChildren(ThinScrollBar)
            if b.isVisible() and b.orientation() == Qt.Orientation.Vertical and b.maximum() > b.minimum()]
    for bar in bars:
        tl = bar.mapToGlobal(QPoint(0, 0))
        r = bar.thumb_rect().toRect().translated(tl)
        lane = r.adjusted(0, -10_000, 0, 10_000)          # the whole lane the thumb travels
        area = bar.parentWidget()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parentWidget()
        if area is None or area.widget() is None:
            continue
        for w in [x for k in kinds for x in area.widget().findChildren(k)]:
            if not w.isVisible():
                continue
            g = w.rect().translated(w.mapToGlobal(QPoint(0, 0)))
            vis = area.viewport().rect().translated(area.viewport().mapToGlobal(QPoint(0, 0)))
            if g.intersected(vis).intersects(lane):          # only what is visible in the viewport counts
                out.append((type(area).__name__, type(w).__name__, w.accessibleName() or w.toolTip()))
    return out


@pytest.mark.parametrize("expanded", [False, True])
def test_scrollbars_never_cover_interactive_content(win, app, expanded):
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    win.calculate("single", ["CrMnFeCoCuAl"], [{"Cr": 1, "Mn": 1, "Fe": 1, "Co": 1, "Cu": 1, "Al": 1}], [{}])
    pump(app)
    win.table.model.wait()
    c = win.analysis_ctl
    c.set_active(win.table.model.page_rows()[0].id, by="table")
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    win.table.model.refresh_committed()
    c.run_finished(run)
    if expanded:
        win.resize(1214, 700)
        win.set_expanded(True)
    pump(app, 8)
    pages = [(S.COMPOSITION, t_) for t_ in S.COMP_TABS] + [(S.COLLECTION, t_) for t_ in S.COLL_TABS]
    for ctx, tab in pages:
        c.apply(S.switch_context, ctx)
        if ctx == S.COLLECTION:
            c.scope_for(run, "full")
        c.apply(S.set_tab, tab)
        for _ in range(6):
            c.wait_idle(30)
            pump(app)
        bad = _bar_overlaps(win)
        assert not bad, (ctx, tab, bad[:5])


# ====================================================================== scrollable tabs (§21)
def test_line_tabs_scroll_instead_of_shrinking(app):
    from hea_calc.ui.widgets.common import LineTabs
    tabs = LineTabs(["Overview", "Descriptors", "Models", "Model details"])
    host = _host(app, tabs, 600, 80)
    assert not tabs.overflowing() and not tabs.left_arrow.isVisible() and not tabs.right_arrow.isVisible()
    tabs.setFixedWidth(240)                                  # tighter than the four tabs
    pump(app)
    assert tabs.overflowing() and tabs.right_arrow.isVisible() and not tabs.left_arrow.isVisible()
    assert {b.pad for b in tabs.buttons} == {16}, "labels and padding are never compressed"
    tabs.set_index(3)                                        # the selected tab scrolls into view
    pump(app)
    b = tabs.buttons[3]
    left, right = b.x() - tabs.offset, b.x() + b.width() - tabs.offset
    assert left >= 0 and right <= tabs.width() and tabs.left_arrow.isVisible()
    tabs.left_arrow.click()                                  # the overflow button brings hidden tabs back
    pump(app)
    assert tabs.offset < b.x()
    tabs.set_index(0)
    pump(app)
    assert tabs.offset == 0 and not tabs.left_arrow.isVisible()
    host.close()


# ====================================================================== expanded Analysis in a small window (§20, 7.png)
def test_tight_expanded_workspace_reflows_and_scrolls_once(win, app):
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.widgets.scroll import ThinScrollBar
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    win.table.model.refresh_committed()
    c = win.analysis_ctl
    c.run_finished(run)
    c.apply(S.switch_context, S.COLLECTION)
    c.scope_for(run, "full")
    c.apply(S.set_tab, "statistics")
    win.resize(1214, 700)
    win.set_expanded(True)
    c.apply(S.update, stats_focus="delta")
    for _ in range(8):
        c.wait_idle(30)
        pump(app)
    ws = win.workspace
    assert ws.identity_wrapped and ws.identity_row.isVisible(), "the scope text moves under the header"
    tabs = ws.tab_stack.currentWidget()
    t_right = tabs.mapTo(ws, QPoint(0, 0)).x() + tabs.width()
    assert t_right <= ws.overflow_btn.mapTo(ws, QPoint(0, 0)).x(), "tabs never overlap the header actions"
    vbars = [b for b in ws.findChildren(ThinScrollBar)
             if b.isVisible() and b.orientation() == Qt.Orientation.Vertical and b.maximum() > b.minimum()]
    assert vbars == [], "no region scrolls by itself"
    outer = win.workspace_scroll.verticalScrollBar()
    assert outer.maximum() > 0, "the page is taller than the window: the one outer scroll owns it"
    assert ws.collection.ws_viz.height() >= 420
    c.apply(S.set_tab, "plots")
    for _ in range(8):
        c.wait_idle(30)
        pump(app)
    coll = ws.collection
    assert coll.plot.width() >= 640, "the inspector moves below instead of squeezing the plot"
    assert coll.inspector_region.mapTo(ws, QPoint(0, 0)).y() > coll.plot.mapTo(ws, QPoint(0, 0)).y()
    win.resize(1920, 1000)
    pump(app, 8)
    assert not ws.identity_wrapped and coll.inspector_region.width() == 340


# ====================================================================== shell calculation states (§14, §15, §52, §53)
def _start_sweep(win, app, lo, hi, step):
    import time
    for el in ("Cr", "Mn", "Fe", "Co", "Ni"):
        if not win.elements.table.tiles[el].isChecked():
            win.elements.table.tiles[el].click()
    comp = win.composition
    comp.set_mode(1)
    comp.unit_box.setCurrentIndex(1)
    for r in comp.sweep.rows.values():
        r.min.setText(str(lo)), r.max.setText(str(hi)), r.step.setText(str(step))
    sw = comp.sweep
    sw._timer.stop()
    sw._update_summary()
    t0 = time.perf_counter()
    while sw._counter.busy and time.perf_counter() - t0 < 30:
        app.processEvents()
        time.sleep(0.005)
    pump(app)
    comp.calc_btn.click()


def _wait(app, cond, limit=60):
    import time
    t0 = time.perf_counter()
    while not cond() and time.perf_counter() - t0 < limit:
        app.processEvents()
        time.sleep(0.01)
    pump(app)


def test_header_calculating_then_success_without_notification(win, app):
    from hea_calc.ui.theme import t
    head_h = win.header.height()
    _start_sweep(win, app, 2, 40, 2)                        # 94 381 compositions: long enough to observe
    _wait(app, lambda: win.worker is not None and win.worker.done_count > 500)
    import time
    time.sleep(0.15)
    pump(app)
    p, line = win.progress, win.progress_line
    assert p.isVisible() and p.label.text().startswith("Calculating…") and p.label.text().endswith("%")
    assert p.detail.text().startswith("(") and "/94,381)" in p.detail.text()
    assert line.isVisible() and line.kind == "progress" and line.height() == 4
    g = win.header.geometry()
    assert (line.geometry().top(), line.width()) == (g.bottom() + 1, line.parentWidget().width()), \
        "the line sits on the header's bottom edge, across the window"
    assert win.header.height() == head_h, "header geometry stays stable"
    comp = win.composition
    assert not comp.calc_btn.isVisible() or not comp.calc_btn.isEnabled()
    assert not comp.unit_box.isEnabled(), "inputs are read-only while calculating (§52)"
    assert comp.status() is None or comp.status().kind != "ready", "never 'Ready' while a run is going"
    win.cancel_calculation()
    _wait(app, lambda: win.worker is None)
    assert p.label.text() == "Calculation cancelled" and line.kind == "warning"
    assert "calculated before cancellation" in p.detail.text()
    _start_sweep(win, app, 10, 30, 10)                      # 51 compositions: to completion
    _wait(app, lambda: win.worker is None and win.progress.result is not None)
    assert p.label.text() == "Calculation succeeded" and p.detail.text() == "51 compositions calculated successfully"
    assert line.kind == "success" and line.isVisible()
    img = line.grab().toImage()
    assert img.pixelColor(line.width() // 2, 1).name() == t("support-success").lower()
    assert not win.notification.isVisible(), "§14: no success notification above the results"
    assert comp.calc_btn.isEnabled() and comp.unit_box.isEnabled()


def test_header_failure_state(win, app):
    from types import SimpleNamespace
    win.progress.show()
    win.runner.run_id = None
    win._done(SimpleNamespace(state="error", error="boom", plan_counts=None))
    pump(app)
    assert win.progress.label.text() == "Calculation failed" and win.progress_line.kind == "error"
    assert win.progress.detail.text() == "An error interrupted the calculation before completion."


# ====================================================================== double-click acknowledgement (§38)
def test_row_double_click_is_acknowledged_transiently(win, app):
    import time
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    for name, comp in (("CoCrFeNi", {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}), ("CoFeNi", {"Co": 1, "Fe": 1, "Ni": 1})):
        win.calculate("single", [name], [comp], [{}])
        pump(app)
    win.table.model.wait()
    pump(app)
    view = win.table.view
    target = win.table.model.row_at(1)
    y = view.rowViewportPosition(1) + 10
    pos = QPointF(200, y)
    ev = QMouseEvent(QEvent.Type.MouseButtonDblClick, pos, view.viewport().mapToGlobal(pos), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    view.mouseDoubleClickEvent(ev)
    pump(app)
    assert win.analysis_ctl.state.active == target.id, "double click still sets the active composition"
    assert view.flash_row == 1 and view.flash_level > 0, "the row flashes"
    acc = win.analysis.accent
    assert acc.isVisible() and acc.level > 0 and acc.height() == 3, "the Analysis panel is accented"
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 1.2:
        app.processEvents()
        time.sleep(0.01)
    assert view.flash_row == -1 and view.flash_level == 0, "feedback, not state: the row returns to hover-only"
    assert not acc.isVisible()
    assert view.selectionMode() == view.SelectionMode.NoSelection and not win.notification.isVisible()
