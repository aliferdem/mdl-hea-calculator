"""Composition interaction corrections, Carbon field styling, responsive docked Analysis, vertical model tabs,
restored View actions and structural System size options (2026-10-28).

Real widgets in a real MainWindow (offscreen); keyboard editing, focus changes and state transitions are driven by
QTest events.  Expected values come from the periodic-table path, explicit product colours, the generator's own
system construction (``generation.systems``) and independent arithmetic - never from the changed code's output."""

import os
import re
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    from hea_calc.ui.widgets.common import install_tooltips
    a = QApplication.instance() or QApplication([])
    load_fonts()
    install_tooltips(a)
    return a


def pump(app, n=10):
    for _ in range(n):
        app.processEvents()


def make_window(app, theme="dark", width=1728):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(width, 1000)
    w.show()
    w.activateWindow()
    pump(app)
    return w


def close_window(app, w):
    from PySide6.QtCore import QEvent
    from hea_calc.ui.theme import THEME
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    THEME.set_theme("dark")
    pump(app)


@pytest.fixture()
def win(app):
    w = make_window(app)
    yield w
    close_window(app, w)


def key(app, w, name, mod=None):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClick(w, getattr(Qt.Key, f"Key_{name}"), mod or Qt.KeyboardModifier.NoModifier)
    pump(app)


def type_into(app, w, text):
    from PySide6.QtTest import QTest
    QTest.keyClicks(w, text)
    pump(app)


def focused():
    from PySide6.QtWidgets import QApplication
    return QApplication.focusWidget()


def tiles(win, app, *els):
    for el in els:
        win.elements.table.tiles[el].click()
    pump(app)


def el_mode(win, app, mode=0):
    comp = win.composition
    comp.set_mode(mode)
    pump(app)
    if mode == 0:
        comp.single.radios["element"].click()
        pump(app)
    return comp.view()


def order_of(view):
    lay = view.rows_widget.lay
    return [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]


# ============================================================================================ A1 clear = remove
@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize("how", ["backspace_enter", "delete_enter", "selectall_delete_blur"])
def test_clearing_a_committed_symbol_removes_its_row(win, app, mode, how):
    from PySide6.QtCore import Qt
    view = el_mode(win, app, mode)
    tiles(win, app, "Fe", "Ni", "Cr")
    f = view.rows["Ni"].el
    f.setFocus()
    if how == "backspace_enter":
        f.end(False)
        key(app, f, "Backspace")
        key(app, f, "Backspace")
        assert "Ni" in view.rows                                   # an intermediate empty state removes nothing
        key(app, f, "Return")
    elif how == "delete_enter":
        f.home(False)
        key(app, f, "Delete")
        key(app, f, "Delete")
        key(app, f, "Return")
    else:
        key(app, f, "A", Qt.KeyboardModifier.ControlModifier)
        key(app, f, "Delete")
        assert "Ni" in view.rows
        view.rows["Fe"].el.setFocus()                              # confirmed by leaving the field
    pump(app, 20)
    assert list(view.rows) == ["Fe", "Cr"]
    assert sorted(win.elements.table.selected()) == ["Cr", "Fe"]   # the periodic-table path
    assert view.element_error is None and win.composition.footer.status.status is None or \
        "Enter an element symbol" not in (win.composition.footer.status.status.text or "")


def test_escape_cancels_a_symbol_edit(win, app):
    view = el_mode(win, app)
    tiles(win, app, "Fe", "Ni")
    f = view.rows["Ni"].el
    f.setFocus()
    f.selectAll()
    type_into(app, f, "xx")
    key(app, f, "Escape")
    assert f.text() == "Ni" and list(view.rows) == ["Fe", "Ni"] and view.element_error is None


@pytest.mark.parametrize("mode", [0, 1])
def test_select_all_and_retype_is_a_rename_not_a_removal(win, app, mode):
    from PySide6.QtCore import Qt
    view = el_mode(win, app, mode)
    tiles(win, app, "Fe", "Ni", "Cr")
    row = view.rows["Ni"]
    f = row.el
    f.setFocus()
    key(app, f, "A", Qt.KeyboardModifier.ControlModifier)
    type_into(app, f, "c")                                        # "N" replaced: never an empty decision
    type_into(app, f, "o")
    key(app, f, "Return")
    assert list(view.rows) == ["Fe", "Co", "Cr"] and view.rows["Co"] is row
    assert sorted(win.elements.table.selected()) == ["Co", "Cr", "Fe"]
    # paste replacement, confirmed by focus loss: a rename again
    f = view.rows["Cr"].el
    f.setFocus()
    f.selectAll()
    f.insert("Mn")
    view.rows["Fe"].el.setFocus()
    pump(app, 20)
    assert list(view.rows) == ["Fe", "Co", "Mn"]


# ============================================================================================ A2 Enter anywhere
@pytest.mark.parametrize("mode", [0, 1])
def test_enter_in_a_periodic_table_row_opens_a_draft_below_it(win, app, mode):
    view = el_mode(win, app, mode)
    tiles(win, app, "Fe", "Ni", "Cr")
    win.composition.calc_btn.setFocus()                           # the user was elsewhere in the window
    f = view.rows["Ni"].el
    f.setFocus()
    key(app, f, "Return")
    draft = view.draft
    assert draft is not None and focused() is draft.el
    order = order_of(view)
    assert order.index(draft) == order.index(view.rows["Ni"]) + 1     # directly below Ni, not at the end
    type_into(app, draft.el, "co")
    key(app, draft.el, "Return")
    assert list(view.rows) == ["Fe", "Ni", "Co", "Cr"]                # inserted where the draft was
    assert win.composition._elements == ["Fe", "Ni", "Co", "Cr"]
    order = order_of(view)
    assert view.draft is draft and order.index(draft) == order.index(view.rows["Co"]) + 1
    assert focused() is draft.el and draft.el.text() == ""


@pytest.mark.parametrize("which", ["Fe", "Ni"])
def test_enter_after_leaving_and_returning(win, app, which):
    comp = win.composition
    view = el_mode(win, app)
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(comp.add_btn, Qt.MouseButton.LeftButton)
    pump(app)
    for s in ("fe", "ni"):
        type_into(app, view.draft.el, s)
        key(app, view.draft.el, "Return")
    key(app, view.draft.el, "Escape")                             # leave the table
    win.table.view.setFocus()
    pump(app, 20)
    assert view.draft is None
    f = view.rows[which].el                                       # come back to a committed row
    f.setFocus()
    key(app, f, "Return")
    order = order_of(view)
    assert view.draft is not None and order.index(view.draft) == order.index(view.rows[which]) + 1
    assert focused() is view.draft.el
    win.top_row.set_collapsed(0, True)                            # Elements collapsed: the same
    pump(app)
    key(app, view.draft.el, "Escape")
    f.setFocus()
    key(app, f, "Return")
    assert view.draft is not None and focused() is view.draft.el


def test_invalid_rename_with_enter_is_not_committed(win, app):
    view = el_mode(win, app)
    tiles(win, app, "Fe", "Ni")
    f = view.rows["Ni"].el
    f.setFocus()
    f.selectAll()
    type_into(app, f, "fe")                                       # a duplicate
    key(app, f, "Return")
    assert view.draft is None and view.element_error is not None and list(view.rows) == ["Fe", "Ni"]
    assert "already in the composition" in win.composition.footer.status.status.text


# ============================================================================================ A3 full drafts
@pytest.mark.parametrize("mode", [0, 1])
def test_drafts_render_every_column_blank_and_read_only(win, app, mode):
    from hea_calc.ui.widgets.composition_panel import ROW_H
    view = el_mode(win, app, mode)
    tiles(win, app, "Fe", "Ni")
    f = view.rows["Fe"].el
    f.setFocus()
    key(app, f, "Return")
    draft, ref = view.draft, view.rows["Fe"]
    if mode == 0:
        pairs = [(draft.fields[r], ref.fields[r]) for r in draft.fields]
    else:
        pairs = [(draft.min, ref.min), (draft.max, ref.max), (draft.step, ref.step)]
        assert draft.lock.isVisible() and draft.lock.parentWidget().geometry() == ref.lock.parentWidget().geometry()
    for d, r in pairs:
        assert d.isVisible() and d.isEnabled() and d.isReadOnly() and d.text() == "" and d.placeholderText() == ""
        assert d.geometry() == r.geometry() and d.height() == ROW_H     # the committed row's geometry
    assert draft.el.geometry() == ref.el.geometry() and not draft.el.isReadOnly()
    key(app, draft.el, "Escape")
    assert view.draft is None and draft not in order_of(view)


def test_committed_draft_rows_get_their_values(win, app):
    comp = win.composition
    view = el_mode(win, app)
    tiles(win, app, "Fe", "Ni")                                    # auto-equal ratios: every row 1
    f = view.rows["Ni"].el
    f.setFocus()
    key(app, f, "Return")
    type_into(app, view.draft.el, "co")
    key(app, view.draft.el, "Return")
    assert view.values["Co"] == 1.0 and view.rows["Co"].fields["ratio"].text() == "1.0000"
    assert view.rows["Co"].fields["at"].text() == f"{100 / 3:.4f}"
    sv = el_mode(win, app, 1)
    f = sv.rows["Co"].el
    f.setFocus()
    key(app, f, "Return")
    type_into(app, sv.draft.el, "cr")
    key(app, sv.draft.el, "Return")
    r = sv.rows["Cr"]
    # at. ratio defaults 1.0 - 2.0 (UX package A6, 2026-10-28; formerly 1.0 - 1.0)
    assert (r.min.text(), r.max.text(), r.step.text()) == ("1.0", "2.0", "0.1") and r.lock.isChecked()
    assert not r.min.isReadOnly() and r.lock.isEnabled()
    assert comp._elements == ["Fe", "Ni", "Co", "Cr"]


def test_drafts_never_reach_calculation_or_enumeration(win, app):
    comp = win.composition
    sv = el_mode(win, app, 1)
    tiles(win, app, "Fe", "Ni", "Cr")
    pump(app, 30)
    sizes_before = list(sv.possible_sizes())
    specs_before = [s.element for s in sv.specs()]
    f = sv.rows["Ni"].el
    f.setFocus()
    key(app, f, "Return")
    type_into(app, sv.draft.el, "co")                              # typed, not committed
    assert list(sv.possible_sizes()) == sizes_before and [s.element for s in sv.specs()] == specs_before
    assert [s.element for s in sv.recipe().specs] == ["Fe", "Ni", "Cr"]
    s = el_mode(win, app, 0)
    assert s.draft is None                                         # a draft belongs to its table (mode switch)
    name, ratios = s.composition()
    assert set(ratios) == {"Fe", "Ni", "Cr"}


# ============================================================================================ B1 balance states
def test_balance_field_disabled_only_in_its_active_percentage_column(win, app):
    comp = win.composition
    s = comp.single
    s.radios["at"].click()
    tiles(win, app, "Fe", "Ni", "Cr")

    def check():
        bal = s.balance_element()
        for el, row in s.rows.items():
            for rep, f in row.fields.items():
                is_bal_cell = el == bal and rep == s.value_rep
                want_disabled = is_bal_cell and s.input_rep == s.value_rep
                assert f.isEnabled() is (not want_disabled), (s.input_rep, el, rep)
                assert f.isReadOnly() is (rep != s.input_rep), (s.input_rep, el, rep)
    for radio in ("element", "at", "element", "wt", "element", "ratio", "at"):
        s.radios[radio].click()
        pump(app)
        check()
    tiles(win, app, "Co")                                          # after adding
    check()
    tiles(win, app, "Fe")                                          # after removing the balance element
    assert s.balance_element() == "Ni"
    check()
    s.radios["element"].click()
    pump(app)
    check()
    assert s.values["Ni"] == pytest.approx(100 - s.values["Cr"] - s.values["Co"])   # still computed while read-only


# ============================================================================================ B2 / B3 field colours
@pytest.mark.parametrize("theme,bg,text,border", [("light", "#f4f4f4", "#bcbcbc", "#c6c6c6"),
                                                  ("dark", "#393939", "#686868", "#6f6f6f")])
def test_disabled_and_read_only_field_rendering(app, theme, bg, text, border):
    from PySide6.QtGui import QColor
    from hea_calc.ui.widgets.composition_panel import ROW_H
    w = make_window(app, theme)
    try:
        s = w.composition.single
        s.radios["at"].click()
        tiles(w, app, "Fe", "Ni")
        dis = s.rows["Fe"].fields["at"]                            # the balance in its active column: disabled
        ro = s.rows["Fe"].fields["wt"]                             # an inactive column: read-only
        assert not dis.isEnabled() and ro.isReadOnly() and ro.isEnabled()
        for f, want_bg in ((dis, bg), (ro, None)):
            img = f.grab().toImage()
            y = img.height() - 1
            row = {img.pixelColor(x, y).name() for x in range(2, img.width() - 2)}
            assert row == {border}, (theme, f.accessibleName(), row)          # a visible, uniform bottom rule
            if want_bg:
                assert img.pixelColor(3, 3).name() == want_bg
        # the disabled text: QSS colour as resolved by the widget, and the darkest glyph pixel near it
        assert dis.palette().color(dis.foregroundRole()).name() == text or \
            QColor(text).lightness() - 10 <= min(
                (dis.grab().toImage().pixelColor(x, y).lightness() for x in range(10, 70) for y in range(8, ROW_H - 8)),
                key=lambda L: abs(L - QColor(text).lightness())) <= QColor(text).lightness() + 10
        # no focus, hover or selection on the disabled field
        assert dis.focusPolicy() is not None and not dis.isEnabled()
        dis.setFocus()
        assert not dis.hasFocus()
        # Composition space read-only fields: the same rule (the draft's blank cells)
        sv = el_mode(w, app, 1)
        f = sv.rows["Fe"].el
        f.setFocus()
        key(app, f, "Return")
        img = sv.draft.min.grab().toImage()
        assert {img.pixelColor(x, img.height() - 1).name() for x in range(2, img.width() - 2)} == {border}
    finally:
        close_window(app, w)


# ============================================================================================ C1 caret colours
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_composition_space_caret_matches_its_label(app, theme):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QImage, QRegion
    from PySide6.QtWidgets import QWidget
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.heading_dropdown import ICON, PAD_X
    want = {"light": {"secondary": "#525252", "primary": "#161616"},
            "dark": {"secondary": "#c6c6c6", "primary": "#f4f4f4"}}[theme]
    w = make_window(app, theme)
    try:
        h = w.composition.heading

        def measure(pop):
            img = QImage(pop.size(), QImage.Format.Format_ARGB32)
            img.fill(QColor(t("layer-02")))
            pop.render(img, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
            r = pop.row_rect(0, 1)                                 # "Composition space"
            bg = QColor(t("layer-02")).lightness()

            def strongest(x0, x1):
                best = (0, None)
                for x in range(x0, x1):
                    for y in range(r.top() + 2, r.bottom() - 2):
                        c = img.pixelColor(x, y)
                        if abs(c.lightness() - bg) > best[0]:
                            best = (abs(c.lightness() - bg), c)
                return best
            text = strongest(r.left() + PAD_X, r.left() + PAD_X + 60)
            caret = strongest(r.right() + 1 - PAD_X - ICON, r.right() + 1 - PAD_X)
            return text, caret

        for mode, state in ((0, "secondary"), (1, "primary")):    # Single: unselected; Space: selected (open)
            w.composition.set_mode(mode)
            pump(app)
            from hea_calc.ui.widgets.heading_dropdown import CascadePopup
            pop = CascadePopup(h, h.tree, h.path)                  # the real popup, rendered off screen
            for variant in ("rest", "hover", "keyboard"):
                pop.hover = None
                pop.keyboard = False
                if variant == "hover":
                    pop.hover = (0, 1)
                elif variant == "keyboard":
                    pop.keyboard, pop.level, pop.active[0] = True, 0, 1
                expect = state if variant == "rest" else "primary"
                text, caret = measure(pop)
                assert caret[0] >= 0.85 * text[0], (mode, variant, text, caret)
                assert abs(caret[1].lightness() - QColor(want[expect]).lightness()) <= 0.12 * 255, \
                    (mode, variant, caret[1].name(), want[expect])
            pop.deleteLater()
            pump(app)
    finally:
        close_window(app, w)


# ============================================================================================ C2 tooltips
def test_property_tooltips_carry_no_bibliography(win, app):
    info = win.elements.info
    bib = re.compile(r"(18|19|20)\d\d|\bTable\b|et al|doi|DOI|Bakker|Kittel|Guo|Liu|Miedema \(|https?://")
    for el in ("Fe", "Pu", "He"):
        info.show_element(el)
        for prop, k in info.keys.items():
            assert k.toolTip() and not bib.search(k.toolTip()), (el, prop, k.toolTip())
            assert info.values[prop][0].toolTip() == ""
    info.show_element("Pu")
    tip = info.keys["atomic_radius"].toolTip()
    assert "supplementary" in tip and "flagged" in tip                  # the warning stays
    for unit in ("g cm⁻³", "(K)", "(pm)", "(V)", "(GPa)"):
        assert any(unit in k.toolTip() for k in info.keys.values()), unit
    # the sources stay in the Documentation
    page = Path(__file__).resolve().parents[1] / "hea_calc" / "docs" / "pages" / "element-properties.md"
    assert "Guo & Liu" in page.read_text(encoding="utf-8") and "Bakker" in page.read_text(encoding="utf-8")


# ============================================================================================ C3 callout borders
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_documentation_callouts_have_all_borders(app, theme):
    from PySide6.QtGui import QColor
    from hea_calc.ui.theme import THEME
    from hea_calc.ui.help_window import HelpWindow
    THEME.set_theme(theme)
    hw = HelpWindow(None)
    try:
        hw.resize(1100, 900)
        hw.show()
        hw.open("first-calculation")                               # "Common mistake." warning callouts
        pump(app, 20)
        img = hw.view.viewport().grab().toImage()
        k = THEME.tokens
        fg, bg = QColor(k["support-warning"]), QColor(k["notification-warning-bg"])
        edge = QColor(round(0.4 * fg.red() + 0.6 * bg.red()), round(0.4 * fg.green() + 0.6 * bg.green()),
                      round(0.4 * fg.blue() + 0.6 * bg.blue()))            # independent: 40 % over the surface
        bar = fg.name()
        px = [(x, y) for y in range(img.height()) for x in range(img.width())
              if img.pixelColor(x, y).name() == edge.name()]
        bars = [(x, y) for y in range(img.height()) for x in range(img.width()) if img.pixelColor(x, y).name() == bar]
        assert px and bars
        xs = sorted({x for x, _y in bars})                          # the 3 px accent bar (the icon is the same hue)
        bx = xs[0]
        while bx + 1 in xs and bx + 1 - xs[0] < 3:
            bx += 1
        ys = sorted({y for _x, y in px})
        top, bottom = ys[0], ys[-1]
        right = max(x for x, _y in px)
        horizontal_top = [x for x, y in px if y == top]
        assert min(horizontal_top) == bx + 1 and max(horizontal_top) == right    # top edge: bar to right edge
        assert {y for x, y in px if x == right} >= set(range(top, bottom + 1))   # right edge: full height
        assert len([x for x, y in px if y == bottom]) == len(horizontal_top)     # bottom edge
        assert all(img.pixelColor(bx, y).name() == bar for y in range(top + 1, bottom))   # left accent kept
        mid = (top + bottom) // 2
        assert img.pixelColor(right - 4, mid).name() == bg.name()      # the tinted surface is kept inside
    finally:
        hw.close()
        THEME.set_theme("dark")


# ============================================================================================ C4 docked Analysis
def test_docked_analysis_adopts_the_wide_layout_by_available_width(app):
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis.workspace import wide_layout_min
    w = make_window(app, width=2160)
    try:
        w.calculate("single", ["CoCrFeNi"], [{"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}], [{}])
        w.table.model.wait()
        pump(app, 20)
        c = w.analysis_ctl
        c.set_active(w.table.model.page_rows()[0].id, by="table")
        c.apply(S.set_tab, "model_details")
        c.apply(S.select_model, "M5")
        pump(app, 20)
        dock, top = w.analysis_dock, w.top_row
        before = (c.state.active, c.state.comp_tab, c.state.model, c.state.context)
        for collapsed in ((), (0,), (1,), (0, 1), (0,), ()):
            for i in range(3):
                top.set_collapsed(i, i in collapsed)
            pump(app, 20)
            assert not top.is_collapsed(2)
            want = dock.width() >= wide_layout_min()
            assert dock.wide is want, (collapsed, dock.width())
            assert dock.currentWidget() is (dock.workspace_scroll if want else w.analysis)
            assert w.analysis.suspended is want                     # only the layout on screen renders
            assert (c.state.active, c.state.comp_tab, c.state.model, c.state.context) == before
            assert w.pages.currentIndex() == 0                     # never the dedicated expanded workspace
            assert [top.is_collapsed(i) for i in range(2)] == [i in collapsed for i in range(2)]
            if want:
                assert dock.workspace.model_tabs.index == 4         # M5 kept
        top.set_collapsed(0, True)
        top.set_collapsed(1, True)
        pump(app, 20)
        assert dock.wide
        top.set_collapsed(1, False)
        top.set_collapsed(2, True)                                 # Analysis collapsed: the strip, no switch
        pump(app)
        assert not dock.isVisible() and top.is_collapsed(0) and not top.is_collapsed(1)
        top.set_collapsed(2, False)
        top.set_collapsed(1, True)
        pump(app, 20)
        assert dock.isVisible() and dock.wide
        w.set_top_panels_visible(False)                            # top panels hidden: nothing to lay out
        pump(app)
        assert not dock.isVisible()
        w.set_top_panels_visible(True)
        pump(app, 20)
        assert dock.wide
        w.resize(1300, 1000)                                       # restore down: compact again
        pump(app, 20)
        assert not dock.wide and dock.currentWidget() is w.analysis
        w.resize(2160, 1000)
        pump(app, 20)
        assert dock.wide
        dock.workspace.collapse_btn.click()                        # the wide layout keeps Collapse Analysis
        pump(app)
        assert top.is_collapsed(2)
    finally:
        close_window(app, w)


def test_docked_wide_layout_has_no_overlap(app):
    from PySide6.QtCore import QPoint, QRect
    from hea_calc.ui.analysis.widgets import _KVRow
    w = make_window(app, width=2160)
    try:
        w.calculate("single", ["CoCrFeNi"], [{"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}], [{}])
        w.table.model.wait()
        pump(app, 20)
        w.analysis_ctl.set_active(w.table.model.page_rows()[0].id, by="table")
        w.top_row.set_collapsed(0, True)
        w.top_row.set_collapsed(1, True)
        pump(app, 30)
        ws = w.analysis_dock.workspace
        assert w.analysis_dock.wide and ws.isVisible()
        rows = [r for r in ws.findChildren(_KVRow) if r.isVisible()]
        assert len(rows) > 20
        rects = [QRect(r.mapTo(ws, QPoint(0, 0)), r.size()) for r in rows]
        for r in rows:
            v = getattr(r, "v", None)
            assert v is None or r.k.geometry().right() < v.geometry().left()
        for i, a in enumerate(rects):
            assert not any(a.intersects(b) for b in rects[i + 1:])
    finally:
        close_window(app, w)


# ============================================================================================ C5 vertical tabs
def test_model_details_vertical_tabs(app):
    from PySide6.QtGui import QColor
    from hea_calc.core.analysis import state as S
    from hea_calc.core.engine import MODEL_KEYS
    from hea_calc.ui.theme import t
    w = make_window(app, width=1728)
    try:
        w.calculate("single", ["CoCrFeNi"], [{"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}], [{}])
        w.table.model.wait()
        pump(app, 20)
        c = w.analysis_ctl
        c.set_active(w.table.model.page_rows()[0].id, by="table")
        c.apply(S.switch_context, S.COMPOSITION)
        c.apply(S.set_tab, "model_details")
        w.set_expanded(True)
        pump(app, 30)
        tabs = w.workspace.model_tabs
        row = w.table.model.page_rows()[0]
        assert [b.tag for b in tabs.tabs] == [row.result.models[k].label for k in MODEL_KEYS]
        assert all(b.accessibleName().startswith(k) for b, k in zip(tabs.tabs, MODEL_KEYS))
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(tabs.tabs[2], Qt.MouseButton.LeftButton)  # click M3
        pump(app, 10)
        assert c.state.model == "M3" and tabs.index == 2
        tabs.tabs[2].setFocus()
        key(app, tabs.tabs[2], "Down")
        assert c.state.model == "M4" and focused() is tabs.tabs[3]
        key(app, focused(), "End")
        assert c.state.model == "M8"
        key(app, focused(), "Home")
        assert c.state.model == "M1"
        key(app, focused(), "Up")                                  # stays at the first tab
        assert c.state.model == "M1"
        # roving Tab stop: only the selected tab takes Tab focus
        assert [b.focusPolicy() == Qt.FocusPolicy.TabFocus for b in tabs.tabs] == [True] + [False] * 7
        c.apply(S.select_model, "M6")                              # state -> view (another surface chose M6)
        pump(app)
        assert tabs.index == 5
        # selected indicator: 3 px border-interactive at the left edge; unselected: no indicator
        img = tabs.tabs[5].grab().toImage()
        assert img.pixelColor(1, 30).name() == QColor(t("border-interactive")).name()
        img = tabs.tabs[0].grab().toImage()
        assert img.pixelColor(1, 30).name() != QColor(t("border-interactive")).name()
        # one region: tabs and details share it
        assert tabs.parentWidget() is w.workspace.model_region
        assert w.workspace.composition_details.parentWidget().parentWidget() is w.workspace.model_region
        w.resize(1100, 900)                                        # narrower: selection kept, no overlap
        pump(app, 20)
        assert tabs.index == 5 and c.state.model == "M6"
        details = w.workspace.composition_details
        assert tabs.geometry().right() < details.mapTo(w.workspace.model_region, details.rect().topLeft()).x()
    finally:
        close_window(app, w)


# ============================================================================================ C6 View menu
def test_view_menu_panels_reset_workspace_and_sync(win, app):
    texts = [a.text() for a in win.view_menu.actions() if a.text()]
    for t_ in ("Top panels", "Full screen", "Expand analysis", "Panels", "Elements", "Composition setup",
               "Analysis", "Reset workspace", "Theme", "Light", "Dark", "System default"):
        assert t_ in texts, t_
    acts = win.panel_actions
    assert [a.isChecked() for a in acts] == [True, True, True]
    win.elements.collapse_btn.click()                              # a panel button: the menu follows
    pump(app)
    assert [a.isChecked() for a in acts] == [False, True, True]
    acts[1].trigger()                                              # the menu: the panel follows
    pump(app)
    assert win.top_row.is_collapsed(1) and not acts[1].isChecked()
    win.top_row.strips[0].button.click()                           # the strip's expand button
    pump(app)
    assert acts[0].isChecked() and not win.top_row.is_collapsed(0)
    assert not win.expand_action.isEnabled()                       # no results: nothing to expand
    tiles(win, app, "Fe", "Ni")
    win.composition.calculate()
    win.table.model.wait()
    pump(app, 20)
    n = win.table.model.total_count()
    assert n == 1 and win.expand_action.isEnabled()
    win.expand_action.trigger()
    pump(app)
    assert win.pages.currentIndex() == 1 and win.expand_action.isChecked()
    win.set_top_panels_visible(False)
    pump(app)
    # Reset workspace: default layout; results and composition untouched
    win.reset_workspace_action.trigger()
    pump(app, 20)
    assert win.pages.currentIndex() == 0 and not win.expand_action.isChecked()
    assert win.top_panels_visible() and win.top_panels_action.isChecked()
    assert not any(win.top_row.is_collapsed(i) for i in range(3)) and all(a.isChecked() for a in acts)
    assert win.table.model.total_count() == n and win.composition._elements == ["Fe", "Ni"]
    assert win.settings.value("collapsed_panels") == ""
    # expanding a panel from the menu while the top panels are hidden shows them
    acts[0].trigger()
    win.set_top_panels_visible(False)
    acts[0].trigger()
    pump(app)
    assert win.top_panels_visible() and acts[0].isChecked()


# ============================================================================================ C7 System size
@pytest.mark.parametrize("n,locked,options,read_only", [
    (5, 4, [4, 5], False), (5, 5, [5], True), (5, 2, [2, 3, 4, 5], False), (5, 0, [2, 3, 4, 5], False),
    (5, 1, [2, 3, 4, 5], False), (3, 3, [3], True), (2, 0, [2], True), (2, 1, [2], True), (1, 1, [], False)])
def test_system_size_options_are_the_structurally_possible_sizes(win, app, n, locked, options, read_only):
    from hea_calc.core.generation import SweepSpec, systems
    comp = win.composition
    comp.set_mode(1)
    els = ["Fe", "Ni", "Cr", "Co", "Mn"][:n]
    tiles(win, app, *els)
    sv = comp.sweep
    for i, el in enumerate(els):                                   # rows start locked: unlock the last n - locked
        if i >= locked:
            sv.rows[el].lock.click()
    pump(app)
    box = sv.size_box
    assert [v for v, _h in box.options] == options and box.read_only is read_only
    # the generator's own construction gives exactly these sizes (independent of the dropdown)
    specs = [SweepSpec(el, 1, 1, 0.1, i < locked) for i, el in enumerate(els)]
    assert sorted({len(s) for s in systems(specs)}) == options


def test_system_size_selection_is_reconciled(win, app):
    comp = win.composition
    comp.set_mode(1)
    tiles(win, app, "Fe", "Ni", "Cr", "Co", "Mn")
    sv = comp.sweep
    for el in ("Cr", "Co", "Mn"):
        sv.rows[el].lock.click()                                   # 2 locked: 2..5
    pump(app)
    box = sv.size_box

    def choose(sel):                                               # the MultiSelect's own path: set, then emit
        box.selected = tuple(sel)
        box.changed.emit(tuple(sel))
        pump(app)
    choose((2, 3, 5))
    sv.rows["Cr"].lock.click()                                     # 3 locked: 3..5 - 2 is dropped, 3 and 5 stay
    pump(app)
    assert box.selected == (3, 5) and sv.sizes() == {3, 5}
    for el in ("Co", "Mn"):                                        # rapid lock / unlock
        sv.rows[el].lock.click()
        sv.rows[el].lock.click()
    pump(app)
    assert box.selected == (3, 5)
    sv.rows["Co"].lock.click()
    sv.rows["Mn"].lock.click()                                     # all locked: 5, read-only
    pump(app)
    assert box.read_only and box.selected == (5,)
    # 2026-10-28 (UX package B5): leaving the all-locked state starts at All (every possible size), never the fixed
    # maximum or an older choice; the user narrows it again (formerly the old choice came back)
    sv.rows["Mn"].lock.click()                                     # 4 locked: 4..5 - All
    pump(app)
    assert not box.read_only and box.selected == () and box.current_html() == "All"
    sv.rows["Co"].lock.click()                                     # 3 locked: 3..5 - still All
    pump(app)
    assert box.selected == () and sv.sizes() is None
    choose((4,))
    sv.rows["Mn"].lock.click()
    sv.rows["Mn"].lock.click()
    pump(app)
    assert box.selected == (4,)
    choose(())                                                     # All = every possible size
    assert sv.sizes() is None
