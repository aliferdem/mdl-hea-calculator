"""Regressions for the final interaction / state / undo / window-consistency pass
(``design/implementation/FINAL_INTERACTION_FIX_AUDIT.md``).  Offscreen; the native checks are in the audit."""

from __future__ import annotations

import os
import re
import tempfile
import time
import tracemalloc
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QApplication, QWidget

from hea_calc.core.analysis import samples
from hea_calc.core.analysis import state as S
from hea_calc.core.composition import alloy_name

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    from hea_calc.ui.widgets.tooltip import install_tooltips
    load_fonts()
    install_tooltips(a)
    return a


def pump(app, n: int = 4):
    for _ in range(n):
        app.processEvents()


def settle(win, app):
    for _ in range(8):
        win.analysis_ctl.wait_idle(30)
        pump(app, 2)


def new_settings() -> QSettings:
    return QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)


@pytest.fixture()
def settings():
    return new_settings()


def make_win(app, settings, theme="dark", size=(1500, 900)):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    w = MainWindow(settings=settings)
    w.resize(*size)
    w.show()
    pump(app)
    return w


def close_win(app, w):
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


@pytest.fixture()
def win(app, settings):
    w = make_win(app, settings)
    yield w
    close_win(app, w)


def calc(win, app, *comps):
    for comp in comps:
        win.calculate("single", [alloy_name(comp)], [comp], [{}])
        pump(app)


ALLOYS = ({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}, {"Co": 1, "Cr": 1, "Fe": 1}, {"Al": 1, "Ni": 1},
          {"Fe": 1, "Ni": 1})


# ====================================================================== menus: every item has a hit area
def _visible_actions(m):
    return [a for a in m.actions() if a.isVisible() and not a.isSeparator()]


@pytest.mark.parametrize("which", ["file", "edit", "theme", "export"])
def test_every_menu_item_is_hit_at_its_centre(win, app, which):
    """The merged File / Theme shadow made QMenu drop the last item's hit area ("Exit", "System default")."""
    hdr = win.header
    calc(win, app, ALLOYS[0])                                  # Export needs results
    if which == "file":
        m, trig, kw = win.file_menu, hdr.file_item, {"merge": True}
    elif which == "edit":
        m, trig, kw = win.edit_menu, hdr.edit_item, {"merge": True}
    elif which == "theme":                                     # View holds the Theme choices
        m, trig, kw = hdr.theme_menu, hdr.view_item, {"merge": True}
    else:
        m, trig, kw = win.table.export_menu, win.table.export_btn, {"align_right": True}
    m.trigger_width = 0
    m.open_below(trig, exec_=False, **kw)
    pump(app)
    try:
        acts = _visible_actions(m)
        assert acts
        for a in acts:
            r = m.actionGeometry(a)
            assert m.rect().contains(r.center()), a.text()
            assert m.actionAt(r.center()) is a, f"{a.text()!r} has no hit area"
            assert m.actionAt(QPoint(r.center().x(), r.bottom() - 1)) is a, a.text()
        names = [a.text() for a in acts]
        if which == "file":
            assert "Exit" in names
        if which == "theme":
            assert "System default" in names
    finally:
        m.close()
        pump(app)


def test_real_clicks_trigger_the_last_item_of_a_merged_menu(win, app):
    """A real mouse click on the last item of a merged title bar menu fires it (View > System default)."""
    hdr = win.header
    m = hdr.theme_menu
    win.set_theme("dark")
    for label in ("Light", "Dark", "System default"):
        m.trigger_width = 0
        m.open_below(hdr.view_item, exec_=False, merge=True)
        pump(app)
        act = next(a for a in _visible_actions(m) if a.text() == label)
        c = m.actionGeometry(act).center()
        QTest.mouseMove(m, c)
        QTest.mouseClick(m, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c)
        pump(app)
        assert not m.isVisible()
        assert win.prefs.theme == {"Light": "light", "Dark": "dark", "System default": "system"}[label]


def test_keyboard_selects_the_last_menu_item(win, app):
    hdr = win.header
    m = hdr.theme_menu
    win.set_theme("dark")
    m.trigger_width = 0
    m.open_below(hdr.view_item, exec_=False, merge=True)
    pump(app)
    for _ in range(16):                    # the View menu has more items since 2026-10-28 (C6)
        QTest.keyClick(m, Qt.Key.Key_Down)
        if m.activeAction() is not None and m.activeAction().text() == "System default":
            break
    assert m.activeAction() is not None and m.activeAction().text() == "System default"
    QTest.keyClick(m, Qt.Key.Key_Return)
    pump(app)
    assert win.prefs.theme == "system"


def test_merged_menu_geometry_is_an_ordinary_menu(win, app):
    """The trigger's elevation is a separate, input-transparent window - the menu window is not extended."""
    from hea_calc.ui.widgets.menu import SHADOW
    m, item = win.file_menu, win.header.file_item
    m.trigger_width = 0
    m.open_below(item, exec_=False, merge=True)
    pump(app)
    try:
        assert m.surface() == m.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        assert m.mapToGlobal(m.surface().topLeft()) == item.mapToGlobal(QPoint(0, item.height()))
        ov = m._overlay
        assert ov is not None and ov.isVisible()
        assert ov.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert ov.windowFlags() & Qt.WindowType.WindowTransparentForInput
        assert ov.geometry().bottom() < m.geometry().top(), "the overlay never covers the menu window"
        img = ov.grab().toImage()
        tab = QWidget.mapFromGlobal(ov, item.mapToGlobal(QPoint(item.width() // 2, item.height() // 2)))
        assert img.pixelColor(tab).alpha() == 0, "nothing is painted over the trigger"
        assert img.pixelColor(2, tab.y()).alpha() > 0, "the trigger's left edge is elevated"
    finally:
        m.close()
        pump(app)
    assert not m._overlay.isVisible()


# ====================================================================== point inspector
def test_plot_window_does_not_shadow_qwidget_window(app):
    from hea_calc.ui.analysis.plot import PlotWidget
    host = QWidget()
    pw = PlotWidget(parent=host)
    assert callable(pw.window) and pw.window() is host and pw.view_window is None


def test_point_inspector_opens_owned_by_the_window_repeatedly(win, app):
    """`anchor.window()` raised "'NoneType' object is not callable": PlotWidget.window (the zoom window)
    shadowed QWidget.window().  Opening the embedded point inspector twice works and is owned by the window."""
    from hea_calc.ui.widgets.dropdown import Popover
    # the embedded compact panel: at 1500 px the stacked Analysis slot is wide enough for the workspace layout
    # (C4, 2026-10-28), so the window is narrowed until the compact panel is the layout on screen
    win.resize(1360, 900)
    settle(win, app)
    assert not win.analysis_dock.wide
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    win.table.model.refresh_committed()
    win.analysis_ctl.run_finished(run)
    win._check_details()
    c = win.analysis_ctl
    c.apply(S.switch_context, S.COLLECTION)
    settle(win, app)
    c.scope_for(run, "full")
    settle(win, app)
    c.apply(S.set_tab, "plots")
    settle(win, app)
    coll = win.analysis.collection
    plot = coll.plot
    assert plot is not None and coll.size_class != "W"
    plot.view_window = None
    rid = plot.spec.data["ids"][0]
    for _ in range(2):
        coll._point_clicked(rid)
        pump(app)
        pops = [w for w in QApplication.topLevelWidgets() if isinstance(w, Popover) and w.isVisible()]
        assert len(pops) == 1 and pops[0].parentWidget() is win
        pops[0].close()
        pump(app)
        pops[0].anchor.closed_at = 0.0             # the replay guard is for real outside clicks
    assert not [w for w in QApplication.topLevelWidgets() if isinstance(w, Popover) and w.isVisible()]


def test_popover_refuses_a_hidden_or_deleted_anchor(app):
    from hea_calc.ui.widgets.dropdown import open_popover, popover_owner
    a = QWidget()
    assert popover_owner(a) is None and open_popover(a, QWidget()) is None
    a.show()
    pump(app)
    assert popover_owner(a) is a
    a.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert popover_owner(a) is None


# ====================================================================== header status
def test_terminal_status_waits_for_the_next_click(win, app):
    from hea_calc.ui.widgets.header import _NextPress
    p = win.progress
    for kind, title in (("success", "Calculation completed"), ("warning", "Calculation cancelled"),
                        ("error", "Calculation failed")):
        p.set_result(kind, title, "detail")
        pump(app, 6)
        assert p.result == kind and p.label.isVisible(), "not dismissed when the run ends"
        assert _NextPress.armed(p), "a filter only while a terminal status is shown"
        QTest.mouseClick(win.table.view.viewport(), Qt.MouseButton.LeftButton)
        pump(app)
        assert p.result is None and not p.label.isVisible() and not p.bar.kind
        assert not _NextPress.armed(p), "the filter is removed at once"
    # a running job is never hidden by a click, and a new job replaces a finished state
    p.set_result("success", "Calculation completed", "")
    p.show()
    assert not _NextPress.armed(p)
    p.set_progress("Calculating", 5, 10, None)
    QTest.mouseClick(win.table.view.viewport(), Qt.MouseButton.LeftButton)
    pump(app)
    assert p.active and p.label.isVisible()
    p.hide()


def test_completed_wording_everywhere():
    for f in list((ROOT / "hea_calc").rglob("*.py")) + list((ROOT / "hea_calc" / "docs").rglob("*.md")):
        assert "Calculation succeeded" not in f.read_text(encoding="utf-8"), f


def test_status_text_aligns_with_the_composition_title(win, app):
    win._place_sticky()
    pump(app)
    p, title = win.progress, win.composition.title
    x_status = p.label.mapToGlobal(QPoint(0, 0)).x()
    x_title = title.mapToGlobal(QPoint(title.contentsRect().left() + title.indent(), 0)).x()   # the heading text
    assert x_status == x_title
    win.resize(1200, 800)
    pump(app, 6)
    win._place_sticky()
    pump(app)
    assert p.label.mapToGlobal(QPoint(0, 0)).x() == title.mapToGlobal(QPoint(title.contentsRect().left()
                                                                             + title.indent(), 0)).x()


# ====================================================================== pagination
def test_page_selector_types_and_chooses(win, app):
    from hea_calc.ui.widgets.listbox import ListPopup
    calc(win, app, *ALLOYS)
    m = win.table.model
    win.table.pagination.size_box.setCurrentIndex(0)           # 10 per page
    for i in range(3):
        calc(win, app, *ALLOYS)
    pag = win.table.pagination
    f = pag.page_field
    m.set_page_size(2)
    pump(app)
    assert m.page_count() >= 5
    f.setFocus()
    f.setText("3")
    QTest.keyClick(f, Qt.Key.Key_Return)
    assert m.page == 2
    f.setText("999")
    QTest.keyClick(f, Qt.Key.Key_Return)
    assert m.page == m.page_count() - 1 and f.text() == str(m.page_count()), "out of range: corrected"
    f.open_list()
    pump(app)
    pop = f.popup
    assert isinstance(pop, ListPopup) and pop.isVisible()
    assert [o.value for o in pop.options] == list(range(m.page_count())) and pop.value == m.page
    pop.choose(0)
    pump(app)
    assert m.page == 0 and f.popup is None
    QTest.keyClick(f, Qt.Key.Key_Down)                         # keyboard opens the list
    pump(app)
    assert f.popup is not None
    f.popup.close()
    pump(app)
    # the closed field ignores the wheel
    before = m.page
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPointF
    ev = QWheelEvent(QPointF(10, 10), QPointF(f.mapToGlobal(QPoint(10, 10))), QPoint(0, 0), QPoint(0, -120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(f, ev)
    assert m.page == before


def test_page_selector_lists_a_window_for_huge_page_counts(app):
    from hea_calc.ui.widgets.results_table import PageField
    f = PageField()
    f.set_pages(25_000, 60_000)
    w = f.page_window()
    assert len(w) == PageField.LIST_WINDOW and 25_000 in w
    f.set_pages(59_999, 60_000)
    assert f.page_window()[-1] == 59_999
    f.set_pages(3, 40)
    assert f.page_window() == range(40)


# ====================================================================== toggletip links
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_toggletip_links_use_the_inverse_link_token(app, theme):
    from collections import Counter
    from hea_calc.ui.theme import THEME, t
    from hea_calc.ui.widgets.tooltip import Toggletip
    THEME.set_theme(theme)
    host = QWidget()
    host.resize(300, 200)
    host.show()
    tip = Toggletip(host, "<a href='help://models'>Prediction model coverage</a>")
    tip.show()
    pump(app)
    img = tip.labels[0].grab().toImage()
    inked = Counter(img.pixelColor(x, y).name() for x in range(img.width()) for y in range(img.height())
                    if img.pixelColor(x, y).alpha() == 255 and img.pixelColor(x, y).name() != "#000000")
    assert inked.most_common(1)[0][0] == t("link-inverse").lower()
    assert "#8c7045" not in inked, "never the Windows accent (visited / palette link colour)"
    # deterministic teardown: a popup whose owner is garbage-collected while it is open crashes Qt (pre-existing,
    # test-only lifecycle - see FINAL_INTERACTION_FIX_AUDIT.md)
    tip.close()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    host.close()
    host.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


def test_style_links_colours_every_anchor():
    from hea_calc.ui.theme import style_links
    out = style_links("<a href='x'>a</a> and <a style='color:red' href='y'>b</a>", "#0f62fe")
    assert out.count("color:#0f62fe") == 2 and "red" not in out


# ====================================================================== expression footer + resize
def test_parse_expression_is_the_footer_action(win, app):
    """Figma Expression bases: Parse expression is the 182 px primary footer button until the document is
    parsed, then Calculate (141 px) with its 40 px chevron; the editor has no field-internal buttons."""
    comp = win.composition
    comp.set_mode(2)
    ex = comp.expr
    pump(app)
    ex.set_text("FeNi")
    pump(app)
    assert comp.calc_btn.text() == "Parse expression" and comp.calc_btn.width() == 182
    assert not comp.footer.calc.chevron.isVisible()
    ex.parse()
    t0 = time.monotonic()
    while ex.counting and time.monotonic() - t0 < 10:
        pump(app)
    assert comp.calc_btn.text() == "Calculate" and comp.calc_btn.width() == 141
    assert comp.footer.calc.chevron.isVisible() and comp.footer.calc.chevron.width() == 40
    calc = comp.footer.calc
    assert calc.mapTo(comp.footer, QPoint(calc.width() - 1, 0)).x() == comp.footer.width() - 1, "flush with the panel edge"


def test_expression_editor_fills_the_panel_then_hugs_its_lines(win, app):
    from hea_calc.ui.widgets.code_editor import LINE_H
    comp = win.composition
    comp.set_mode(2)
    pump(app)
    ex = comp.expr
    e = ex.edit
    ex.set_text("(FeCoNi)1-xAlx\n  0 <= x <= 1, step=0.5")
    pump(app)
    avail = ex.scroll.viewport().height() - 8
    assert e.height() == avail and e.y() == 8, "editing: the editor takes the panel (Figma Draft)"
    ex.parse()
    t0 = time.monotonic()
    while ex.counting and time.monotonic() - t0 < 10:
        pump(app)
    pump(app)
    assert e.height() == 2 * LINE_H, "parsed: the editor hugs its two lines (Figma Parametric parsed)"
    blk = e.document().findBlockByNumber(1)
    assert e.document().documentLayout().blockBoundingRect(blk).top() == LINE_H
    assert e.width() == comp.width() and comp.height() == comp.height()


# ====================================================================== single composition: auto-equal
@pytest.mark.parametrize("rep, expect", [("ratio", 1.0), ("at", 25.0), ("wt", 25.0), ("mass", None)])
def test_pristine_single_composition_is_equal(win, app, rep, expect):
    comp = win.composition
    comp.set_mode(0)
    sv = comp.single
    sv.radios[rep].click()
    pump(app)
    for el in ("Fe", "Ni", "Co", "Cr"):
        win.elements.table.tiles[el].click()
    pump(app)
    share = expect if expect is not None else sv.total_mass / 4
    assert sv.values == pytest.approx({el: share for el in ("Fe", "Ni", "Co", "Cr")})
    win.elements.table.tiles["Cr"].click()                      # remove: equal again
    share3 = {"ratio": 1.0, "at": 100 / 3, "wt": 100 / 3, "mass": sv.total_mass / 3}[rep]
    assert sv.values == pytest.approx({el: share3 for el in ("Fe", "Ni", "Co")})
    assert sv.can_calculate()


def test_manual_values_are_never_redistributed(win, app):
    comp = win.composition
    comp.set_mode(0)
    sv = comp.single
    sv.radios["at"].click()
    for el in ("Fe", "Ni"):
        win.elements.table.tiles[el].click()
    f = sv.rows["Fe"].fields["at"]
    f.setFocus()
    f.setText("70")
    f.textEdited.emit("70")
    sv.rows["Ni"].fields["at"].setText("30")
    sv.rows["Ni"].fields["at"].textEdited.emit("30")
    assert not sv.pristine and sv.values == {"Fe": 70.0, "Ni": 30.0}
    win.elements.table.tiles["Co"].click()
    assert sv.values["Fe"] == 70.0 and sv.values["Ni"] == 30.0 and sv.values["Co"] == 0.0
    win.elements.table.tiles["Co"].click()
    assert sv.values == {"Fe": 70.0, "Ni": 30.0}
    sv.set_equal()
    assert sv.pristine
    comp.clear()
    assert sv.pristine and not sv.values


# ====================================================================== results columns
def test_columns_resize_by_key_with_minimum_and_persist(app, settings):
    w = make_win(app, settings)
    try:
        calc(w, app, *ALLOYS)
        v = w.table.view
        h = v.header
        i = v.m.keys.index("density")
        assert h.sectionResizeMode(i) == h.ResizeMode.Interactive
        h.resizeSection(i, 400)                              # a separator drag
        pump(app)
        assert v.user_widths["density"] == 400 and h.sectionSize(i) == 400
        h.resizeSection(i, 3)                                # no accidental zero-width column
        assert h.sectionSize(i) == v._min_width("density") and v.user_widths["density"] == v._min_width("density")
        h.resizeSection(i, 900)
        w.sticky.sync()
        assert w.sticky.matches_source(), "the pinned header follows"
        pump(app, 6)
        assert v.horizontalScrollBar().maximum() > 0, "wider than the table: horizontal scroll"
        assert not w.table.internal_vertical_scrollbar_visible(), "the table never scrolls vertically"
        assert '"density": 900' in str(settings.value("column_widths"))
        w.sticky.resizeSection(i, 300)                       # a drag on the pinned header resizes the table
        assert h.sectionSize(i) == 300
        v.m.sort_by("density")                               # sorting keeps the width (key, not position)
        pump(app)
        assert h.sectionSize(v.m.keys.index("density")) == 300
    finally:
        close_win(app, w)
    w2 = make_win(app, settings)                              # persisted by column key
    try:
        calc(w2, app, ALLOYS[0])
        v2 = w2.table.view
        assert v2.header.sectionSize(v2.m.keys.index("density")) == 300
        v2.reset_width(v2.m.keys.index("density"))
        assert "density" not in v2.user_widths
    finally:
        close_win(app, w2)


# ====================================================================== default window size
def test_first_run_window_size_then_saved_geometry(app, settings):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import ELEMENT_PANEL_WIDTH, TILE_SIZE
    w = MainWindow(settings=settings)
    w.show_initial()
    pump(app, 6)
    try:
        # 2026-10-26: a fresh installation opens maximized; Restore returns to the default size
        assert w.isMaximized() and MainWindow.DEFAULT_SIZE == (1095, 670)
        w.showNormal()
        pump(app)
        assert (w.width(), w.height()) == MainWindow.DEFAULT_SIZE
        assert w.elements.width() == ELEMENT_PANEL_WIDTH and w.elements.table.tile_size == TILE_SIZE == 28
        from hea_calc.ui.theme import COMPOSITION_PANEL_WIDTH
        assert w.composition.width() == COMPOSITION_PANEL_WIDTH
        bar = w.scroll.verticalScrollBar()
        assert bar.maximum() > 0, "the results remain reachable through the one outer scroll"
        w.resize(1300, 820)
        pump(app)
    finally:
        close_win(app, w)
    w2 = MainWindow(settings=settings)
    w2.show_initial()
    pump(app)
    try:
        # the saved normal state is kept inside the available screen (offscreen: 800 x 800, so the 1300 x 820
        # window is clamped there); the native run checks the exact size - here: the saved state, not the default
        assert settings.value("window/state") == "normal" and not w2.isMaximized()
        assert (w2.width(), w2.height()) != MainWindow.DEFAULT_SIZE
    finally:
        close_win(app, w2)


# ====================================================================== undo / redo + destructive policy
def test_policy_threshold():
    from hea_calc.core import destructive
    assert not destructive.needs_confirmation(5) and not destructive.needs_confirmation(99)
    assert destructive.needs_confirmation(100) and destructive.needs_confirmation(1_000_000)


def test_remove_result_undo_redo_and_edit_menu(win, app):
    calc(win, app, *ALLOYS)
    m = win.table.model
    assert win.header.edit_item is not None and win.header.edit_item.x() > win.header.file_item.x()
    assert not win.undo_action.isEnabled() and win.undo_action.text() == "Undo"
    asked = []
    win._confirm_destructive = lambda *a: asked.append(a) or True
    row = m.row_at(0)
    win.table.view._remove(row)                              # the row menu's "Remove result"
    pump(app)
    assert m.total_count() == 3 and not asked, "a handful never asks"
    assert win.undo_action.isEnabled() and win.undo_action.text() == "Undo remove result"
    win.undo()
    assert m.total_count() == 4 and win.repo.get_result(row.id) is not None
    assert win.redo_action.text() == "Redo remove result"
    win.redo()
    assert m.total_count() == 3
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    assert m.total_count() == 4
    QTest.keyClick(win, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    assert m.total_count() == 3
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    pump(app)
    assert m.total_count() == 3


def test_clear_table_confirms_when_large_and_undoes(win, app):
    m = win.table.model
    calc(win, app, *ALLOYS)
    asked = []
    win._confirm_destructive = lambda *a: asked.append(a) or True
    win.delete_rows()
    assert m.total_count() == 0 and not asked, "a small table is cleared at once (undoable)"
    assert win.undo_action.text() == "Undo clear results table"
    win.undo()
    assert m.total_count() == 4
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    m.refresh_committed()
    n = m.total_count()
    assert n >= 100
    win._confirm_destructive = lambda *a: asked.append(a) or False
    win.delete_rows()
    assert asked and m.total_count() == n, "declined: nothing happens"
    win._confirm_destructive = lambda *a: asked.append(a) or True
    win.delete_rows()
    assert m.total_count() == 0 and not win.table.export_btn.isEnabled()
    win.undo()
    assert m.total_count() == n and win.table.export_btn.isEnabled()
    assert win.repo.get_run(run).cleared is None or not win.repo.get_run(run).cleared
    win.redo()
    assert m.total_count() == 0
    win.undo()
    assert m.total_count() == n


def test_clear_composition_undo_in_every_mode(win, app):
    comp = win.composition
    for el in ("Fe", "Ni", "Co"):
        win.elements.table.tiles[el].click()
    comp.single.radios["at"].click()
    comp._clear_or_cancel()
    assert comp._elements == [] and win.undo_action.text() == "Undo clear composition"
    win.undo()
    assert comp._elements == ["Fe", "Ni", "Co"] and comp.single.input_rep == "at"
    assert sorted(win.elements.table.selected()) == ["Co", "Fe", "Ni"]
    win.redo()
    assert comp._elements == []
    win.undo()
    comp.set_mode(1)
    comp.sweep.rows["Fe"].max.setText("55")
    comp._clear_or_cancel()
    assert win.undo_action.text() == "Undo clear composition space"
    win.undo()
    assert comp.sweep.rows["Fe"].max.text() == "55"
    comp.set_mode(2)
    comp.expr.edit.setPlainText("(FeNi)1-xAlx\n0 <= x <= 1, step=0.5")
    comp.expr.parse()
    comp._clear_or_cancel()
    assert comp.expr.text() == "" and win.undo_action.text() == "Undo clear composition expression"
    win.undo()
    assert comp.expr.text().startswith("(FeNi)1-xAlx")


def test_redo_branch_and_limit_purge_the_trash(win, app):
    calc(win, app, *ALLOYS)
    m = win.table.model
    win.table.view._remove(m.row_at(0))
    assert win.repo.trash_tables()
    win.undo()                                              # rows back: no trash
    assert win.repo.trash_tables() == []
    win.table.view._remove(m.row_at(0))                     # replaces the redo branch
    first = win.undo_mgr.stack.command(0).op
    win.repo.writer.flush()
    assert win.repo.trash_tables() == [f"trash_{first}"]
    from hea_calc.ui import undo
    for _ in range(undo.UNDO_LIMIT + 1):                     # pushes the first removal off the stack
        win.composition.clear_handler()
        for el in ("Fe", "Ni"):
            win.elements.table.tiles[el].click()
        win.clear_composition()
    win.repo.writer.flush()
    assert f"trash_{first}" not in win.repo.trash_tables(), "a removal that can no longer be undone is purged"


def test_large_clear_undo_copies_no_rows_into_python(app, settings, engine):
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from synthetic import fill
    w = make_win(app, settings)
    try:
        fill(w.repo, 200_000, w.engine)
        w.repo.writer.flush()
        w.table.model.refresh_committed()
        m = w.table.model
        assert m.total_count() == 200_000
        size0 = os.path.getsize(w.repo.db_path)
        w._confirm_destructive = lambda *a: True
        tracemalloc.start()
        t0 = time.perf_counter()
        w.delete_rows()
        w.undo()
        w.redo()
        w.undo()
        dt = time.perf_counter() - t0
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        assert m.total_count() == 200_000
        assert peak < 16 * 2 ** 20, f"peak Python allocation {peak / 2 ** 20:.1f} MiB"
        assert dt < 10, dt
        assert os.path.getsize(w.repo.db_path) < 1.2 * size0 + 2 ** 20, "the database is never duplicated"
    finally:
        close_win(app, w)


def test_danger_dialog_defaults_to_cancel(app):
    from hea_calc.ui.widgets.dialogs import DangerDialog
    d = DangerDialog("Clear results", "Clear all 1,000 results?", "detail", "Clear results")
    d.show()
    pump(app)
    assert d.cancel_button.hasFocus() and d.action_button.property("kind") == "danger"
    # focus-visible: the initial (program) focus shows no ring until the keyboard is used
    assert d.cancel_button.property("quietfocus") is True
    assert d.windowTitle() == "Clear results" and "Clear all 1,000 results?" in [
        w.text() for w in d.findChildren(QLabel) if w.objectName() == "ModalTitle"]
    assert not [w for w in d.findChildren(QLabel) if w.objectName() == "ModalLabel"], "no label repeating the caption"

    def ink_rows(b):                               # rows holding label ink (the focus frame excluded)
        img = b.grab().toImage()
        bg = img.pixelColor(b.width() // 2, b.height() - 6).name()
        return [y for y in range(4, img.height() - 4)
                if any(img.pixelColor(x, y).name() != bg for x in range(8, min(img.width() - 8, 90)))]
    a, c = ink_rows(d.action_button), ink_rows(d.cancel_button)
    assert a and c and abs(a[0] - c[0]) <= 1, "a focused footer button keeps its label in place"
    QTest.keyClick(d, Qt.Key.Key_Escape)
    assert d.result() == DangerDialog.DialogCode.Rejected


# ====================================================================== empty results
def test_empty_table_disables_invalid_actions(win, app):
    t = win.table
    assert not t.delete_btn.isEnabled() and not t.filter_btn.isEnabled() and not t.export_btn.isEnabled()
    t.export_btn.click()
    pump(app)
    assert not t.export_menu.isVisible(), "a disabled MenuButton cannot open its menu"
    calc(win, app, ALLOYS[0])
    assert t.delete_btn.isEnabled() and t.filter_btn.isEnabled() and t.export_btn.isEnabled()
    win._confirm_destructive = lambda *a: True
    win.delete_rows()
    assert not t.delete_btn.isEnabled() and not t.export_btn.isEnabled()


# ====================================================================== window roots
@pytest.mark.parametrize("theme, root", [("dark", "#161616"), ("light", "#ffffff")])
def test_every_app_window_root_is_the_caption_colour(app, settings, theme, root):
    from hea_calc.ui import win_titlebar
    from hea_calc.ui.theme import THEME
    from hea_calc.ui.widgets.dialogs import ColumnsDialog, FilterDialog
    w = make_win(app, settings, theme)
    try:
        assert THEME.tokens["shell"].lower() == root
        attrs = dict(win_titlebar.caption_attributes(theme, THEME.tokens, 22631))
        assert attrs[win_titlebar.DWMWA_CAPTION_COLOR] == win_titlebar.colorref(root)
        w.show_about()
        w.show_help("home")
        pump(app, 6)
        wins = [w._about, w._help, ColumnsDialog(w.table.model.keys, w), FilterDialog(w.table.model.filters, w)]
        for dlg in wins:
            dlg.show()
            pump(app, 4)
            img = dlg.grab().toImage()
            # the window root: a pixel of its own background, below the caption-less top margin
            assert img.pixelColor(img.width() - 3, 3).name() == root, type(dlg).__name__
            dlg.close()
    finally:
        close_win(app, w)


# ====================================================================== help callouts
def test_help_callouts_are_carbon_inline_notifications():
    from hea_calc.core import docs
    assert docs.callout_kind("**Common mistake.** x") == "warning"
    assert docs.callout_kind("**Before you start.** x") == "info"
    html = docs.to_html("> **Common mistake.** Do not.", lead=False)
    assert 'class="callout c-warning"' in html and 'src="notify:warning"' in html and "bar-warning" in html


# ====================================================================== statistics / copy
def test_statistics_visualization_is_bounded(win, app):
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    win.table.model.refresh_committed()
    c = win.analysis_ctl
    c.run_finished(run)
    c.apply(S.switch_context, S.COLLECTION)
    c.scope_for(run, "full")
    c.apply(S.set_tab, "statistics")
    c.apply(S.update, stats_focus="delta", stats_view="histogram")
    win.set_expanded(True)
    settle(win, app)
    coll = win.workspace.collection
    assert coll.STATS_VIZ_MIN <= coll.ws_viz.height() <= coll.STATS_VIZ_MAX
    c.apply(S.set_tab, "plots")
    settle(win, app)
    assert coll.plot.height() > coll.STATS_VIZ_MAX, "Plots stays the chart-centric page"
    win.set_expanded(False)


def test_no_decorative_middle_dot_separators_in_ui_copy():
    """`·` stays only where it is mathematical (J/(mol·K), 0.55·Tm, −T·ΔS, k·p) - and in the one place the final
    Figma design uses it as a separator: the Analysis identity "Composition space · Run 1" (Analysis 494:69395)."""
    bad = []
    for f in (ROOT / "hea_calc").rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if "· Run" in line or "· {origin}" in line:            # the Figma identity line
                continue
            if re.search(r"[ \"'{]·[ \"'}]", line) and not re.search(r"f · T", line):
                bad.append(f"{f.name}:{i}: {line.strip()}")
    assert not bad, "\n".join(bad)
