"""UX, workflow, Analysis Collection, reporting and visualization package (2026-10-28).

Real widgets in a real MainWindow (offscreen) where the behaviour is interactive; core logic without Qt where it can
be.  Expected values are computed independently in the tests - never taken from the changed code's own output."""

import os
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


def pump(app, n=20):
    for _ in range(n):
        app.processEvents()


def make_window(app, theme="dark", width=2160, height=1100):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(width, height)
    w.show()
    pump(app)
    return w


def close_window(app, w):
    from PySide6.QtCore import QEvent
    from hea_calc.ui.theme import THEME
    aw = w.analysis_window(create=False)
    if aw is not None:
        aw.close()
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


# ============================================================================================ A1 documentation history
@pytest.fixture()
def help_win(app):
    from hea_calc.ui.help_window import HelpWindow
    hw = HelpWindow(None)
    hw.resize(1100, 700)
    hw.show()
    pump(app, 30)
    yield hw
    hw.close()
    hw.deleteLater()
    pump(app)


def test_documentation_history_back_forward_and_branching(help_win, app):
    hw = help_win
    assert hw.page == "home"
    assert not hw.back_btn.isEnabled() and not hw.forward_btn.isEnabled(), "nothing to go back or forward to"
    hw.open("first-calculation")
    pump(app)
    hw.open("results-table")
    pump(app)
    hw.open("results-table")                                  # the same location again: no new entry
    pump(app)
    assert [e["page"] for e in hw.history] == ["home", "first-calculation", "results-table"]
    assert hw.back_btn.isEnabled() and not hw.forward_btn.isEnabled()
    hw.back()
    pump(app)
    assert hw.page == "first-calculation" and hw.nav.currentItem().data(0, 256) == "first-calculation"
    assert hw.back_btn.isEnabled() and hw.forward_btn.isEnabled()
    hw.forward()
    pump(app)
    assert hw.page == "results-table"
    hw.back()
    hw.back()
    pump(app)
    assert hw.page == "home" and not hw.back_btn.isEnabled()
    hw.back()                                                 # at the start: nothing happens
    assert hw.page == "home"
    # a new page after going back drops the forward branch
    hw.open("composition-space")
    pump(app)
    assert [e["page"] for e in hw.history] == ["home", "composition-space"]
    assert not hw.forward_btn.isEnabled()


def test_documentation_history_follows_links_and_search_hits_not_external_urls(help_win, app, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    hw = help_win
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    hw.follow("help://results-table")                        # an internal link
    pump(app)
    hw.follow("https://example.org/paper")                   # external: the browser, not a history entry
    hw.follow("mailto:someone@example.org")
    pump(app)
    assert opened == ["https://example.org/paper", "mailto:someone@example.org"]
    assert [e["page"] for e in hw.history] == ["home", "results-table"]
    hw.search.setText("system size")                          # a search listing is not an entry ...
    hw._run_search()
    pump(app)
    assert [e["page"] for e in hw.history] == ["home", "results-table"]
    hw._open_first_hit()                                      # ... the hit that is opened is
    pump(app)
    assert len(hw.history) == 3 and hw.history[-1]["page"] == hw.page != "results-table"
    hw.back()
    pump(app)
    assert hw.page == "results-table" and hw.search.text() == ""


def test_documentation_history_restores_scroll_positions(help_win, app):
    hw = help_win
    hw.open("composition-space")
    pump(app, 30)
    bar = hw.view.verticalScrollBar()
    assert bar.maximum() > 300, "a long article"
    bar.setValue(300)
    pump(app)
    hw.open("results-table")
    pump(app, 30)
    assert bar.value() == 0, "a new page opens at its top"
    hw.back()
    pump(app, 30)
    assert hw.page == "composition-space" and bar.value() == 300
    hw.forward()
    pump(app, 30)
    assert hw.page == "results-table" and bar.value() == 0


def test_documentation_history_shortcuts_are_scoped_to_the_window(help_win, win, app):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut
    hw = help_win
    keys = {s.key().toString(): s for s in hw.findChildren(QShortcut)}
    assert "Alt+Left" in keys and "Alt+Right" in keys
    for k in ("Alt+Left", "Alt+Right"):
        assert keys[k].context() == Qt.ShortcutContext.WindowShortcut and keys[k].parent() is hw
    # the main window (Composition text editing) has no Alt+Left / Alt+Right shortcut
    main_keys = {s.key().toString() for s in win.findChildren(QShortcut)}
    assert not main_keys & {"Alt+Left", "Alt+Right"}
    assert hw.back_btn.accessibleName() == "Back" and hw.forward_btn.accessibleName() == "Forward"
    hw.open("first-calculation")
    pump(app)
    keys["Alt+Left"].activated.emit()
    pump(app)
    assert hw.page == "home"
    keys["Alt+Right"].activated.emit()
    pump(app)
    assert hw.page == "first-calculation"
    assert QKeySequence("Alt+Left") != QKeySequence("Ctrl+Left")


def calc_rows(win, app, n=1):
    """``n`` single-composition results (a batch: calculated by the job runner)."""
    from PySide6.QtTest import QTest
    base = win.table.model.rowCount()
    els = ["Co", "Cr", "Fe", "Ni", "Mn", "Cu", "Al", "Ti"]
    comps = [{e: 1 + (i % 3) * (j == 0) for j, e in enumerate(els[:4 + i % 4])} for i in range(n)]
    names = [f"R{i}" for i in range(n)]
    win.calculate("single", names, comps, [{}] * n)
    for _ in range(400):
        QTest.qWait(25)
        win.table.model.wait()
        if win.table.model.total_count() >= base + n and win.worker is None:
            break
    pump(app)
    assert win.worker is None


# ============================================================================================ A2 pagination footer
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_pagination_focus_frames_are_whole_and_selects_meet_their_dividers(app, theme):
    from PySide6.QtCore import Qt
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.common import Divider
    w = make_window(app, theme, 1400, 900)
    try:
        calc_rows(w, app, 1)
        pb = w.table.pagination
        divs = [d for d in pb.findChildren(Divider)]
        # the items-per-page select: 8 px after its label, flush against the divider on its right
        assert pb.size_box.x() - (pb.size_lbl.geometry().right() + 1) == 8
        assert any(d.x() == pb.size_box.geometry().right() + 1 for d in divs)
        # the page select: flush against the divider on its left
        assert any(d.geometry().right() + 1 == pb.page_field.x() for d in divs)
        for c in (pb.size_box, pb.page_field, pb.prev_btn, pb.next_btn):
            g = c.geometry()
            assert g.top() >= 1 and g.bottom() <= pb.height() - 1, (c, g)   # under the border, inside the bar
        focus = t("focus")
        for c in (pb.size_box, pb.page_field):
            c.setFocus(Qt.FocusReason.TabFocusReason)
            pump(app)
            img = pb.grab().toImage()
            g = c.geometry()
            mid_x, mid_y = g.center().x(), g.center().y()
            # all four sides of the 2 px frame are drawn inside the bar
            assert img.pixelColor(mid_x, g.top()).name() == focus, ("top", c)
            assert img.pixelColor(mid_x, g.bottom()).name() == focus, ("bottom", c)
            assert img.pixelColor(g.left(), mid_y).name() == focus, ("left", c)
            assert img.pixelColor(g.right(), mid_y).name() == focus, ("right", c)
            w.setFocus()
            pump(app)
    finally:
        close_window(app, w)


# ============================================================================================ A3 empty states
def _free_above_below(group_top, group_bottom, region_top, region_bottom):
    return group_top - region_top, region_bottom - group_bottom


@pytest.mark.parametrize("size", [(1920, 1032), (1440, 900), (2160, 1300)])
def test_empty_states_are_centred_optically_in_their_regions(app, size):
    from PySide6.QtWidgets import QLabel
    from hea_calc.ui.widgets.common import EmptyState, Illustration
    from hea_calc.ui.analysis.widgets import EmptyBlock
    w = make_window(app, "dark", *size)
    try:
        pump(app, 30)
        checked = 0
        blocks = [b for b in w.findChildren(EmptyState) + w.findChildren(EmptyBlock) if b.isVisible()]
        assert blocks, "the empty session shows empty states"
        for b in blocks:
            art = [i for i in b.findChildren(Illustration) if i.isVisible()]
            labels = [lab for lab in b.findChildren(QLabel) if lab.isVisible() and lab.text()]
            if not art or not labels:
                continue
            top = art[0].mapTo(b, art[0].rect().topLeft()).y()
            bottom = max(lab.mapTo(b, lab.rect().bottomLeft()).y() for lab in labels)
            above, below = _free_above_below(top, bottom, 0, b.height() - 1)
            assert bottom <= b.height() - 1, "the text is never pushed out of its region"
            if above + below > 60:                                  # room to centre in
                assert 0.6 * below <= above <= below + 8, (type(b).__name__, above, below)
            checked += 1
        assert checked >= 2                                           # Composition setup and Analysis
        es = w.table.empty
        assert es.isVisible()
        top = es.group_top()
        above, below = top, es.height() - (top + es.group_height())
        assert below >= 0 and above >= es.TOP
        if es.height() - es.group_height() > 2 * es.TOP + 40:
            assert 0.6 * below <= above <= below + 8, (above, below)
    finally:
        close_window(app, w)


def test_empty_state_keeps_its_minimum_top_when_there_is_no_room(app):
    from hea_calc.ui.widgets.common import EMPTY_MIN_TOP, empty_top
    assert empty_top(0) == EMPTY_MIN_TOP and empty_top(-50) == EMPTY_MIN_TOP
    assert empty_top(200) == 90                                       # 45 % of the free height
    assert empty_top(10, 32) == 32 and empty_top(64, 32) == 32        # the table at its natural height: Figma's 32


# ============================================================================================ A8 model support
@pytest.mark.parametrize("width", [1440, 1920, 2160])
def test_model_support_is_centred_between_be_and_b(app, width):
    w = make_window(app, "dark", width, 1000)
    try:
        el = w.elements
        t = el.table
        be, b = t.tiles["Be"], t.tiles["B"]
        gap_l = be.mapTo(el, be.rect().topLeft()).x() + be.width()
        gap_r = b.mapTo(el, b.rect().topLeft()).x()
        ws = el.support.model_labels + list(el.support.icons.values())
        g_l = min(x.mapTo(el, x.rect().topLeft()).x() for x in ws)
        g_r = max(x.mapTo(el, x.rect().topLeft()).x() + x.width() for x in ws)
        assert abs((g_l - gap_l) - (gap_r - g_r)) <= 1, (gap_l, g_l, g_r, gap_r)   # equal space on both sides
        assert g_l > gap_l and g_r < gap_r
        # the tiles themselves never moved (fixed periodic-table geometry, 28 px tiles on a 30 px pitch)
        assert (be.width(), t.pitch) == (28, 30) and gap_r - gap_l == 10 * t.pitch + 2   # columns 3-12 + 2 gaps
    finally:
        close_window(app, w)


# ============================================================================================ A9 exit full screen
def test_exit_full_screen_action_sits_beside_the_top_panels_action(win, app):
    from hea_calc.ui.widgets.header import HeaderAction
    h = win.header
    btn = h.exit_fs_btn
    assert isinstance(btn, HeaderAction) and btn.icon_name == "minimize"
    assert btn.accessibleName() == "Exit full screen" and "F11" in btn.toolTip()
    assert not btn.isVisible(), "only in full screen"
    win.showNormal()
    pump(app)
    before = win.geometry()
    win.set_fullscreen(True)
    pump(app, 40)
    assert win.isFullScreen()
    assert btn.isVisible() and not h.min_btn.isVisible() and not h.close_btn.isVisible()
    # immediately to the right of Hide / Show top panels, which is unchanged
    assert btn.x() == h.panels_btn.geometry().right() + 1 and btn.y() == h.panels_btn.y()
    assert h.panels_btn.icon_name in ("open_panel_filled_top", "open_panel_top") and h.panels_btn.isVisible()
    # a control for the native chrome (not caption: no drag / Snap Layouts from it)
    centre = btn.mapTo(h, btn.rect().center())
    assert h.hit_test(centre) == "client"
    btn.click()
    pump(app, 40)
    assert not win.isFullScreen() and not btn.isVisible() and h.max_btn.isVisible()
    assert win.geometry() == before, "the window returns to its geometry"
    assert not win.fullscreen_action.isChecked()
    # F11 still toggles (View > Full screen)
    win.fullscreen_action.trigger()
    pump(app, 40)
    assert win.isFullScreen() and btn.isVisible()
    win.fullscreen_action.trigger()
    pump(app, 40)
    assert not win.isFullScreen() and not btn.isVisible()


# ============================================================================================ A15 main scroll bar
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_main_scrollbar_is_centred_in_the_outer_gutter(app, theme):
    from collections import Counter
    from hea_calc.ui.theme import CONTENT_MARGIN_X, t
    w = make_window(app, theme, 1440, 760)
    try:
        calc_rows(w, app, 30)
        pump(app, 30)
        ov = w.scroll.overlay
        assert ov.isVisible()
        vp = w.scroll.viewport()
        content_right = max(p.mapTo(vp, p.rect().topRight()).x() for p in (w.table, w.top_row)) + 1
        assert vp.width() - content_right == CONTENT_MARGIN_X
        # measure the drawn thumb: the columns of the gutter that carry the thumb colour
        img = w.scroll.grab().toImage()
        thumb = t("scrollbar-thumb")
        cols = Counter(x for x in range(content_right, vp.width()) for y in range(0, img.height(), 3)
                       if img.pixelColor(x, y).name() == thumb)
        xs = sorted(x for x, n in cols.items() if n > 3)
        assert len(xs) == 4, xs                                          # the 4 px bar
        left_gap, right_gap = xs[0] - content_right, vp.width() - 1 - xs[-1]
        assert left_gap == right_gap == 6, (left_gap, right_gap)         # centred: 6 | 4 | 6
        # still an overlay: no width is taken from the content
        assert w.table.width() == vp.width() - 2 * CONTENT_MARGIN_X
    finally:
        close_window(app, w)


# ============================================================================================ A7 page after a run
def click_elements(win, *els):
    from PySide6.QtWidgets import QApplication
    for el in els:
        win.elements.table.tiles[el].click()
    QApplication.processEvents()


def wait_worker(win, app, timeout=120.0):
    import time
    t0 = time.time()
    while win.worker is not None and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert win.worker is None


def wait_task(task, app, timeout=30.0):
    import time
    t0 = time.time()
    while task.busy and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def settle_counts(win, app):
    comp = win.composition
    if comp.mode == "sweep":
        comp.sweep._timer.stop()
        comp.sweep._update_summary()
        wait_task(comp.sweep._counter, app)
    elif comp.mode == "expression":
        comp.expr.parse()
        wait_task(comp.expr._counter, app)
    app.processEvents()


def run_space(win, app, els=("Al", "Ti", "V"), step="10"):
    """An at.% composition space with every element optional: 63 results for 3 elements at 10 % steps."""
    click_elements(win, *els)
    win.composition.set_mode(1)
    sw = win.composition.sweep
    win.composition.set_basis("at")
    for row in sw.rows.values():
        row.min.setText("0")
        row.max.setText("100")
        row.step.setText(step)
    sw.all_lock.click()
    settle_counts(win, app)
    n = sw.summary_data.compositions
    win.composition.calc_btn.click()
    wait_worker(win, app)
    return n


def test_a_multi_page_run_opens_on_page_one_with_its_newest_results(win, app):
    m = win.table.model
    calc_rows(win, app, 3)                                       # earlier results
    old_ids = {r.id for r in m.page_rows()}
    win.table.pagination.size_box.setCurrentIndex(0)             # 10 per page
    pump(app)
    n = run_space(win, app)
    assert n == 63 and m.total_count() == 66 and m.page_count() == 7
    assert m.page == 0, "page 1 after the run - not the page of its oldest result"
    ids = [r.id for r in m.page_rows()]
    assert ids == sorted(ids, reverse=True) and not set(ids) & old_ids, "the newest results at the top"
    run_last = win.repo.get_run(win.runner.run_id).last_id
    assert ids[0] == run_last
    assert win.analysis_ctl.state.active == run_last, "Analysis shows the run's newest result"


def test_paging_during_a_run_is_kept_when_it_completes(win, app):
    m = win.table.model
    calc_rows(win, app, 25)
    win.table.pagination.size_box.setCurrentIndex(0)
    pump(app)
    # the user pages while the run is active (set as the controls do, between start and completion)
    orig_start = win.runner.start

    def start_and_page(*a, **k):
        orig_start(*a, **k)
        win.table.pagination.next_btn.click()                   # what a click on Next does
    win.runner.start = start_and_page
    try:
        run_space(win, app)
    finally:
        win.runner.start = orig_start
    assert m.user_paged and m.page == 1, "the user's page is not taken away"
    # the next run starts fresh: page 1 again
    calc_rows(win, app, 12)
    assert m.page == 0


def test_a_single_composition_lands_on_page_one(win, app):
    m = win.table.model
    calc_rows(win, app, 30)
    win.table.pagination.size_box.setCurrentIndex(0)
    win.table.pagination.next_btn.click()
    pump(app)
    assert m.page == 1
    win.calculate("single", ["CoCrFeNiMn"], [{"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "Mn": 1}], [{}])
    pump(app)
    assert m.page == 0 and m.page_rows()[0].name == "CoCrFeNiMn"
    assert win.analysis_ctl.state.active == m.page_rows()[0].id


def test_an_expression_run_in_a_sorted_view_opens_on_page_one(win, app):
    m = win.table.model
    calc_rows(win, app, 4)
    win.table.pagination.size_box.setCurrentIndex(0)
    m.sort_by("vec")                                            # a column sort is kept; still page 1
    pump(app)
    m.wait()
    win.composition.set_mode(2)
    e = win.composition.expr
    e.set_text("AlxCoCrFeNi\n0 <= x <= 2, step=0.1")
    assert e.parse()
    settle_counts(win, app)
    win.composition.calc_btn.click()
    wait_worker(win, app)
    m.wait()
    pump(app)
    assert m.total_count() == 25 and m.page_count() == 3
    assert m.page == 0 and m.sort_key == "vec"


# ============================================================================================ A12 empty is zero
def _weights():
    import json
    d = json.loads((Path(__file__).resolve().parents[1] / "data" / "periodic_table.json").read_text(encoding="utf-8"))
    return {el: v["properties"]["atomic_weight"] for el, v in d.items() if not el.startswith("_")}


def single_with(win, app, els, basis):
    click_elements(win, *els)
    sv = win.composition.single
    sv.radios[basis].click()
    pump(app)
    return sv


def type_into(app, f, text):
    """What typing does: the text, then textEdited (setText alone does not emit it)."""
    f.setFocus()
    f.selectAll()
    f.del_()
    if text:
        f.insert(text)
    else:
        f.textEdited.emit("")
    pump(app)


def num(f):
    return float(f.text().replace(",", "")) if f.text() else None


@pytest.mark.parametrize("basis", ["ratio", "at", "wt", "mass"])
def test_an_emptied_amount_is_zero_for_the_other_columns(win, app, basis):
    W = _weights()
    els = ("Co", "Fe", "Ni")
    sv = single_with(win, app, els, basis)
    # the edited element is not the balance element (the first one in at.% / wt.%)
    target = "Fe"
    type_into(app, sv.rows[target].fields[basis], "")
    f = sv.rows[target].fields[basis]
    assert f.text() == "" and f.placeholderText() == "0", "the cleared input stays visibly empty"
    assert not f.property("invalid")
    # the other columns still show every element; the emptied one converts as 0
    entered = {el: (0.0 if el == target else None) for el in els}
    for el in els:
        if el != target:
            entered[el] = num(sv.rows[el].fields[basis])
    assert all(v is not None for v in entered.values())
    if basis in ("ratio", "at"):
        moles = dict(entered)
    else:
        moles = {el: v / W[el] for el, v in entered.items()}
    tot = sum(moles.values())
    expect_at = {el: 100 * v / tot for el, v in moles.items()}
    for el in els:
        if basis != "at":
            assert num(sv.rows[el].fields["at"]) == pytest.approx(expect_at[el], abs=1e-3), (basis, el)
        if not (basis == "wt" and el == target):              # the entered, emptied field stays empty
            assert sv.rows[el].fields["wt"].text() != "", (basis, el)
    assert num(sv.rows[target].fields["at" if basis != "at" else "wt"]) == 0
    if basis == "at":                                            # the balance element follows: 100 - the others
        others = sum(num(sv.rows[el].fields["at"]) or 0.0 for el in els[1:])
        assert num(sv.rows[els[0]].fields["at"]) == pytest.approx(100 - others, abs=1e-3)
    # the calculation uses a well-defined composition: the empty element is 0, i.e. not in the alloy
    name, ratios = sv.composition()
    assert ratios[target] == 0 and target not in name.split(" (")[0]
    assert sv.can_calculate()


@pytest.mark.parametrize("basis", ["ratio", "at", "wt", "mass"])
def test_text_negative_and_non_finite_amounts_stay_invalid_never_zero(win, app, basis):
    sv = single_with(win, app, ("Co", "Fe", "Ni"), basis)
    f = sv.rows["Fe"].fields[basis]
    for bad in ("abc", "-1", "inf", "nan"):
        type_into(app, f, bad)
        assert f.property("invalid"), bad
        assert sv.values["Fe"] is None, bad
        assert not sv.can_calculate(), bad
    type_into(app, f, "")                                        # blank -> zero: valid again
    assert not f.property("invalid") and sv.values["Fe"] == 0
    type_into(app, f, "0")                                       # zero -> a typed zero shows "0"
    assert f.text() == "0" and sv.values["Fe"] == 0
    type_into(app, f, "1")                                       # -> valid amount
    assert sv.values["Fe"] == 1 and "Fe" not in sv.blank


def test_all_zero_amounts_block_the_calculation(win, app):
    sv = single_with(win, app, ("Co", "Fe", "Ni"), "ratio")
    for el in ("Co", "Fe", "Ni"):
        type_into(app, sv.rows[el].fields["ratio"], "")
    st = sv.status()
    assert st is not None and st.blocking and "zero" in st.text.lower()
    assert not sv.can_calculate()
    with pytest.raises(ValueError):
        sv.composition()
    for el in ("Co", "Fe", "Ni"):                                # no division by zero: derived columns are blank
        assert sv.rows[el].fields["at"].text() == ""


# ============================================================================================ A13 long values
def test_long_values_show_their_beginning_unless_being_edited(win, app):
    sv = single_with(win, app, ("Co", "Fe", "Ni"), "mass")
    sv.set_total_mass(123456789.123456)                       # a large batch: long Mass values
    pump(app)
    for el, row in sv.rows.items():
        for rep, f in row.fields.items():
            if f.fontMetrics().horizontalAdvance(f.text()) > f.width() - 8:
                assert f.cursorPosition() == 0, (el, rep, f.text())          # the first digits in view
                assert f.cursorRect().left() < f.width() // 3
    # a field being edited keeps the user's caret: typing at the end stays at the end
    f = sv.rows["Fe"].fields["mass"]
    f.setFocus()
    f.end(False)
    f.insert("1")
    f.textEdited.emit(f.text())
    pump(app)
    assert f.hasFocus() and f.cursorPosition() == len(f.text())
    # leaving it shows the beginning again
    sv.rows["Ni"].fields["mass"].setFocus()
    pump(app)
    assert f.cursorPosition() == 0 and not f.hasSelectedText()
    # Composition space fields too
    click_elements(win, "Cr")
    win.composition.set_mode(1)
    sw = win.composition.sweep
    r = next(iter(sw.rows.values()))
    r.min.setText("12345678901234567890.5")
    assert r.min.cursorPosition() == 0


def test_a_negative_balance_shows_its_sign(win, app):
    sv = single_with(win, app, ("Co", "Fe", "Ni"), "at")
    type_into(app, sv.rows["Fe"].fields["at"], "99.123456789")
    type_into(app, sv.rows["Ni"].fields["at"], "20.98765432")
    win.setFocus()
    pump(app)
    bal = sv.rows["Co"].fields["at"]
    assert bal.text().startswith("-") and bal.cursorPosition() == 0


# ============================================================================================ A6 ratio / mass defaults
def _distinct_directions(n_el, lo=10, hi=20):
    """Independent count: integer grid lo..hi per element (0.1 steps of 1.0..2.0 times 10), proportional
    combinations counted once (divide each tuple by its gcd)."""
    from itertools import product
    from math import gcd
    from functools import reduce
    seen = set()
    for t in product(range(lo, hi + 1), repeat=n_el):
        g = reduce(gcd, t)
        seen.add(tuple(v // g for v in t))
    return len(seen)


@pytest.mark.parametrize("unit", ["ratio", "mass"])
def test_new_ratio_and_mass_rows_default_to_one_to_two(win, app, unit):
    click_elements(win, "Co", "Fe")
    win.composition.set_mode(1)
    win.composition.set_basis(unit)
    sw = win.composition.sweep
    for r in sw.rows.values():
        assert (r.min.text(), r.max.text(), r.step.text()) == ("1.0", "2.0", "0.1")
    # an existing row keeps what the user entered when another element is added
    sw.rows["Co"].max.setText("3.0")
    sw._edited()
    click_elements(win, "Ni")
    assert (sw.rows["Co"].min.text(), sw.rows["Co"].max.text()) == ("1.0", "3.0")
    assert (sw.rows["Ni"].min.text(), sw.rows["Ni"].max.text(), sw.rows["Ni"].step.text()) == ("1.0", "2.0", "0.1")
    # switching to Single composition and back keeps the ranges
    win.composition.set_mode(0)
    win.composition.set_mode(1)
    assert sw.rows["Co"].max.text() == "3.0" and sw.rows["Ni"].max.text() == "2.0"
    # a valid grid with the right count (all required): independent enumeration of 1.0-2.0 x 3
    sw.rows["Co"].max.setText("2.0")
    sw._edited()
    settle_counts(win, app)
    assert sw.summary_data.compositions == _distinct_directions(3)
    # clear -> defaults again
    win.composition.clear()
    pump(app)
    for r in sw.rows.values():
        assert (r.min.text(), r.max.text(), r.step.text()) == ("1.0", "2.0", "0.1")


def test_percent_defaults_are_unchanged():
    from hea_calc.ui.widgets.composition_panel import RANGE_DEFAULTS
    assert RANGE_DEFAULTS["at"] == RANGE_DEFAULTS["wt"] == ("0", "100", "10")


# ============================================================================================ A5 1 px cell gaps
def _cell_gaps(row):
    from PySide6.QtWidgets import QWidget
    cells = sorted([c for c in row.children() if isinstance(c, QWidget) and c.isVisible()], key=lambda w: w.x())
    return [b.x() - (a.geometry().right() + 1) for a, b in zip(cells, cells[1:])], [c.height() for c in cells]


def test_composition_cells_are_one_pixel_apart_in_every_row(win, app):
    click_elements(win, "Co", "Fe")
    comp = win.composition
    for mode in (0, 1):
        comp.set_mode(mode)
        pump(app)
        view = comp.single if mode == 0 else comp.sweep
        gaps, heights = _cell_gaps(view.rows["Co"])
        assert gaps and set(gaps) == {1}, (mode, gaps)                 # element -> values -> lock: 1 px each
        assert len(set(heights)) == 1
        comp.add_draft()
        pump(app)
        d_gaps, d_heights = _cell_gaps(view.draft)
        assert d_gaps == gaps and d_heights == heights, "a draft row has the committed row's geometry"
        comp.discard_drafts()
        pump(app)


# ============================================================================================ A4 keyboard navigation
def key(app, w, k, mods=None):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClick(w, k, mods if mods is not None else Qt.KeyboardModifier.NoModifier)
    pump(app)


def focused(app):
    from PySide6.QtWidgets import QApplication
    return QApplication.focusWidget()


def test_single_enter_and_up_down_move_within_the_column(win, app):
    from PySide6.QtCore import Qt
    sv = single_with(win, app, ("Co", "Fe", "Ni"), "ratio")
    col = lambda el: sv.rows[el].fields["ratio"]                       # noqa: E731
    col("Co").setFocus()
    pump(app)
    col("Co").selectAll()
    col("Co").insert("2")
    col("Co").textEdited.emit("2")
    key(app, col("Co"), Qt.Key.Key_Return)                             # commits, moves down
    assert focused(app) is col("Fe") and sv.values["Co"] == 2
    assert col("Fe").selectedText() == col("Fe").text(), "the next value is selected, ready to overwrite"
    key(app, col("Fe"), Qt.Key.Key_Down)
    assert focused(app) is col("Ni")
    key(app, col("Ni"), Qt.Key.Key_Down)                               # the last row: nowhere to go
    assert focused(app) is col("Ni")
    key(app, col("Ni"), Qt.Key.Key_Up)
    key(app, col("Fe"), Qt.Key.Key_Up)
    assert focused(app) is col("Co")
    # Left / Right stay text keys
    col("Co").setCursorPosition(1)
    key(app, col("Co"), Qt.Key.Key_Left)
    assert focused(app) is col("Co") and col("Co").cursorPosition() == 0


def test_single_navigation_skips_the_balance_and_the_draft(win, app):
    from PySide6.QtCore import Qt
    sv = single_with(win, app, ("Co", "Fe", "Ni"), "at")             # Co: the balance (not editable)
    col = lambda el: sv.rows[el].fields["at"]                          # noqa: E731
    assert not GridKeys_editable(col("Co"))
    col("Fe").setFocus()
    pump(app)
    key(app, col("Fe"), Qt.Key.Key_Up)                                 # only the balance above: stays
    assert focused(app) is col("Fe")
    key(app, col("Fe"), Qt.Key.Key_Down)
    assert focused(app) is col("Ni")
    # a draft row (it exists while its symbol is being typed): its cells are never navigation targets
    sv.open_draft(after="Fe")
    pump(app)
    d = sv.draft
    assert d is not None
    assert all(not GridKeys_editable(f) for f in d.fields.values())
    assert all(f not in [c for cells in sv.nav_grid() for c in cells] for f in d.fields.values())
    win.composition.discard_drafts()


def GridKeys_editable(f):  # noqa: N802
    from hea_calc.ui.widgets.composition_panel import GridKeys
    return GridKeys.editable(f)


def test_space_enter_ctrl_arrows_and_up_down(win, app):
    from PySide6.QtCore import Qt
    click_elements(win, "Co", "Fe", "Ni")
    win.composition.set_mode(1)
    pump(app)
    sw = win.composition.sweep
    rows = [sw.rows[e] for e in ("Co", "Fe", "Ni")]
    locks = [r.lock.isChecked() for r in rows]
    values = [(r.min.text(), r.max.text(), r.step.text()) for r in rows]
    rows[0].min.setFocus()
    pump(app)
    order = []
    for _ in range(4):
        w = focused(app)
        key(app, w, Qt.Key.Key_Return)
        order.append(focused(app))
    assert order == [rows[0].max, rows[0].step, rows[1].min, rows[1].max], "Min, Max, Step, then the next row"
    key(app, rows[1].max, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    assert focused(app) is rows[1].step
    key(app, rows[1].step, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)   # last column: no move
    assert focused(app) is rows[1].step
    key(app, rows[1].step, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    key(app, rows[1].max, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
    assert focused(app) is rows[1].min
    key(app, rows[1].min, Qt.Key.Key_Down)
    assert focused(app) is rows[2].min
    key(app, rows[2].min, Qt.Key.Key_Up)
    key(app, rows[1].min, Qt.Key.Key_Up)
    assert focused(app) is rows[0].min
    # nothing was toggled or changed by moving around
    assert [r.lock.isChecked() for r in rows] == locks
    assert [(r.min.text(), r.max.text(), r.step.text()) for r in rows] == values
    # an invalid value stays flagged after leaving it
    rows[0].min.selectAll()
    rows[0].min.insert("abc")
    rows[0].min.textEdited.emit("abc")
    key(app, rows[0].min, Qt.Key.Key_Down)
    assert focused(app) is rows[1].min
    sw._timer.stop()
    sw._update_summary()
    pump(app)
    st = sw.status()
    assert st is not None and st.blocking


def test_navigation_scrolls_the_new_field_into_view(app):
    from PySide6.QtCore import Qt
    w = make_window(app, "dark", 1920, 1032)
    try:
        els = ("Co", "Fe", "Ni", "Cr", "Mn", "Cu", "Al", "Ti", "V", "Nb")
        click_elements(w, *els)
        sv = w.composition.single
        pump(app, 30)
        vp = sv.scroll.viewport()
        f0 = sv.rows["Co"].fields["ratio"]
        f0.setFocus()
        pump(app)
        for el in els[1:]:
            key(app, focused(app), Qt.Key.Key_Down)
        last = sv.rows[els[-1]].fields["ratio"]
        assert focused(app) is last
        top = last.mapTo(vp, last.rect().topLeft()).y()
        assert 0 <= top and top + last.height() <= vp.height(), "the focused field is in view"
    finally:
        close_window(app, w)


# ============================================================================================ A10 indentation guide
@pytest.mark.parametrize("text, runs", [
    ("AlxCoCrFeNiTiy\n0 <= x <= 2, step=0.1\n0 <= y <= 1, points=5", 1),
    ("AlxCoCrFeNi\n0 <= x <= 2, step=0.1\n\n(FeCoNi)1-zAlz\n  0 <= z <= 0.5, step=0.1", 2),
    ("CoCrFeNi", 0),
])
def test_expression_guide_keeps_eight_pixels_of_space_before_the_code(win, app, text, runs):
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.code_editor import GUIDE_GAP, LINE_H
    win.composition.set_mode(2)
    e = win.composition.expr
    e.set_text(text)
    pump(app, 30)
    ed = e.edit
    assert len(ed.guide_runs()) == runs
    gut = ed.gutter
    guide = t("syntax-indent-guide")
    img = gut.grab().toImage()
    code_x = ed.viewport().mapTo(gut.parentWidget(), ed.viewport().rect().topLeft()).x() - gut.x()
    assert code_x == gut.width(), "the code column starts where the gutter ends"
    for top, bottom in ed.guide_runs():
        y = int((top + bottom) / 2)
        xs = [x for x in range(img.width()) if img.pixelColor(x, y).name() == guide]
        assert xs == [gut.width() - GUIDE_GAP - 1], xs               # 1 px wide, 8 px clear before the code
        assert bottom - top >= LINE_H
    # nothing of the guide inside the code column (it never touches or crosses the text)
    vimg = ed.viewport().grab().toImage()
    for top, bottom in ed.guide_runs():
        y = int((top + bottom) / 2)
        assert all(vimg.pixelColor(x, y).name() != guide for x in range(0, 12))


def test_expression_guide_stays_while_scrolling_long_lines_in_a_narrow_editor(app):
    from hea_calc.ui.theme import t
    w = make_window(app, "dark", 1440, 900)
    try:
        w.composition.set_mode(2)
        e = w.composition.expr
        e.set_text("AlxCoCrFeNiTiMoNbTaWVZrHfCuMnSiCy\n0 <= x <= 2, step=0.1\n0 <= y <= 1, points=5")
        pump(app, 30)
        ed = e.edit
        ed.horizontalScrollBar().setValue(ed.horizontalScrollBar().maximum())
        pump(app)
        img = ed.gutter.grab().toImage()
        top, bottom = ed.guide_runs()[0]
        assert img.pixelColor(ed.guide_x(ed.gutter), int((top + bottom) / 2)).name() == t("syntax-indent-guide")
    finally:
        close_window(app, w)


# ============================================================================================ A14 mass tooltips
def test_overview_mass_values_have_no_redundant_tooltip(win, app):
    from PySide6.QtCore import QPoint
    from hea_calc.ui.analysis.widgets import DataTable
    from hea_calc.ui.widgets.tooltip import InfoButton
    calc_rows(win, app, 1)
    rid = win.table.model.page_rows()[0].id
    win.analysis_ctl.set_active(rid, by="table")
    pump(app, 30)
    tables = [t_ for t_ in win.findChildren(DataTable) if t_.isVisible()
              and any("g batch" in str(c[0]) for c in t_.columns)]
    assert tables, "the Overview composition table"
    tbl = tables[0]
    mass_ci = next(i for i, c in enumerate(tbl.columns) if "g batch" in str(c[0]))
    rects = tbl.column_rects()
    x0, w = rects[mass_ci]
    n = 0
    for i in range(len(tbl.rows)):
        y = tbl.row_y[i] + tbl.row_height // 2
        tip = tbl.tip_at(QPoint(int(x0 + w / 2), int(y)))
        if not tbl.cell_elided(i, mass_ci):
            assert tip is None, tip                                     # no redundant Tooltip
        n += 1
    assert n >= 2
    # explanatory controls of Analysis keep theirs
    assert any(b.isVisible() for b in win.analysis.findChildren(InfoButton))


# ============================================================================================ A11 completion
def _comp(text, explicit=False):
    from hea_calc.core.data import default_datasets
    from hea_calc.core.expression_complete import complete
    pos = text.index("|")
    return complete(text.replace("|", ""), pos, default_datasets(), explicit)


def _texts(c):
    return [x.text for x in c.candidates] if c else []


def test_completion_follows_the_grammar_po_gives_points():
    c = _comp("AlxCoCrFeNi\n0 <= x <= 1, po|")
    assert c.context == "option" and _texts(c) == ["points="] and (c.start, c.end) == (13, 15)
    # every option the parser accepts, nothing else; a given option is not offered again; step and points exclude
    from hea_calc.core import expression_lexer as L
    assert set(_texts(_comp("AlxCoCrFeNi\n0 <= x <= 1, |", True))) == {"step=", "points=", "p="}
    assert {t.rstrip("=") for t in _texts(_comp("AlxCoCrFeNi\n0 <= x <= 1, |", True))} <= set(L.KEYWORDS)
    assert _comp("AlxCoCrFeNi\n0 <= x <= 1, step=0.1, po|") is None
    assert _texts(_comp("AlxCoCrFeNi\n0 <= x <= 1, step=0.1, |", True)) == ["p="]
    assert _texts(_comp("AlxCoCrFeNi\n0 <= x <= 1, pre|")) == ["preview="]          # a documented alias
    assert _comp("AlxCoCrFeNi\n0 <= x <= 1, step=0.|") is None                       # inside a value
    assert _comp("AlxCoCrFeNi\n0 <= x <= 1, zz|") is None                            # no such option


def test_completion_variables_templates_and_elements():
    assert _texts(_comp("Al{frac}CoCr\n0 <= f|")) == ["frac"]                           # undeclared variable
    assert _comp("Al{frac}CoCr\n0 <= frac <= 1, step=0.1\n0 <= f|") is None             # already declared
    assert _texts(_comp("AlxCoCrFeNiTiy\n0 <= x <= 1, step=0.1\ny|")) == ["0 <= y <= 1, step=0.1"]
    els = _texts(_comp("AlxC|", True))
    assert "Co" in els and "Cr" in els and all(e.startswith("C") for e in els)
    assert _comp("AlxC|") is None, "element symbols only on request"
    assert _comp("AlxCo|", True) is None or _texts(_comp("AlxCo|", True)) in ([], ["Co"])
    # a lower-case letter after an element's capital is its symbol, not a variable
    assert _comp("Al_fracCo|") is None


def test_completion_replaces_only_the_typed_word():
    from hea_calc.core.expression_complete import apply
    text = "AlxCoCrFeNi\n0 <= x <= 1, po"
    c = _comp(text + "|")
    new, caret = apply(text, c, c.candidates[0])
    assert new == "AlxCoCrFeNi\n0 <= x <= 1, points=" and caret == len(new)
    # the rest of the document is untouched, whatever it holds
    text2 = "AlxCoCrFeNi\n0 <= x <= 1, po\n\n(FeCoNi)1-zAlz\n0 <= z <= 0.5, step=0.1"
    c2 = _comp(text2[:text2.index("po") + 2] + "|" + text2[text2.index("po") + 2:])
    new2, _ = apply(text2, c2, c2.candidates[0])
    assert new2 == text2.replace(", po\n", ", points=\n")


def _type(app, ed, text):
    from PySide6.QtTest import QTest
    for ch in text:
        QTest.keyClicks(ed, ch)
    pump(app)


def test_completion_popup_keys(win, app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win.composition.set_mode(2)
    e = win.composition.expr
    e.set_text("AlxCoCrFeNi\n")
    ed = e.edit
    ed.setFocus()
    c = ed.textCursor()
    c.movePosition(c.MoveOperation.End)
    ed.setTextCursor(c)
    pump(app)
    _type(app, ed, "0 <= x <= 1, po")
    assert ed.completion_visible() and [x.text for x in ed.popup.items] == ["points="]
    # Enter without having navigated the list: an ordinary new line (never a surprise insertion)
    QTest.keyClick(ed, Qt.Key.Key_Return)
    pump(app)
    assert ed.toPlainText() == "AlxCoCrFeNi\n0 <= x <= 1, po\n" and not ed.completion_visible()
    QTest.keyClick(ed, Qt.Key.Key_Backspace)
    _type(app, ed, "i")                                             # "poi"
    assert ed.completion_visible()
    QTest.keyClick(ed, Qt.Key.Key_Tab)                              # Tab accepts
    pump(app)
    assert ed.toPlainText() == "AlxCoCrFeNi\n0 <= x <= 1, points=" and ed.hasFocus()
    ed.undo()                                                       # one undo step: back to what was typed
    assert ed.toPlainText() == "AlxCoCrFeNi\n0 <= x <= 1, poi"
    # Escape dismisses and keeps the text; typing continues normally
    c = ed.textCursor()
    c.movePosition(c.MoveOperation.End)
    ed.setTextCursor(c)
    for _ in range(3):
        QTest.keyClick(ed, Qt.Key.Key_Backspace)                    # "poi" removed
    pump(app)
    _type(app, ed, "s")
    assert ed.completion_visible() and [x.text for x in ed.popup.items] == ["step="]
    QTest.keyClick(ed, Qt.Key.Key_Escape)
    pump(app)
    assert not ed.completion_visible() and ed.toPlainText().endswith(", s")
    # Ctrl+Space: every option; Down + Enter (navigated) accepts the second
    QTest.keyClick(ed, Qt.Key.Key_Backspace)
    QTest.keyClick(ed, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    assert [x.text for x in ed.popup.items] == ["step=", "points=", "p="]
    QTest.keyClick(ed, Qt.Key.Key_Down)
    QTest.keyClick(ed, Qt.Key.Key_Return)
    pump(app)
    assert ed.toPlainText() == "AlxCoCrFeNi\n0 <= x <= 1, points="
    # the popup sits under the caret line and never takes the focus
    _type(app, ed, "5, ")
    QTest.keyClick(ed, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    pump(app)
    assert ed.completion_visible() and ed.hasFocus()
    caret = ed.viewport().mapToGlobal(ed.cursorRect().bottomLeft())
    assert ed.popup.geometry().top() >= caret.y() - 1
    QTest.keyClick(ed, Qt.Key.Key_Escape)


def test_completion_never_rewrites_on_its_own(win, app):
    win.composition.set_mode(2)
    e = win.composition.expr
    valid = "AlxCoCrFeNi\n0 <= x <= 1, step=0.1"
    e.set_text(valid)
    ed = e.edit
    ed.setFocus()
    pump(app)
    ed.show_completion(explicit=False)
    pump(app)
    assert ed.toPlainText() == valid
    ed.hide_completion()


# ============================================================================================ B1 setup undo / redo
def undo_texts(win):
    st = win.undo_mgr.stack
    return [st.text(i) for i in range(st.count())]


def tiles_selected(win):
    return [el for el, t_ in win.elements.table.tiles.items() if t_.isChecked()]


def test_setup_edits_undo_and_redo_one_step_each(win, app):
    sv = win.composition.single
    base = win.undo_mgr.stack.count()
    click_elements(win, "Co", "Fe", "Ni")
    assert undo_texts(win)[base:] == ["Add element Co", "Add element Fe", "Add element Ni"]
    # several characters typed into one field, committed on leaving it: ONE step
    f = sv.rows["Fe"].fields["ratio"]
    f.setFocus()
    pump(app)
    for txt in ("2", "2.", "2.5"):
        f.setText(txt)
        f.textEdited.emit(txt)
    sv.rows["Ni"].fields["ratio"].setFocus()                    # leaving it commits
    pump(app)
    assert undo_texts(win)[-1] == "Edit Fe amount" and win.undo_mgr.stack.count() == base + 4
    assert sv.values["Fe"] == 2.5
    # remove one (context-menu path)
    win.composition.remove_element("Co")
    pump(app)
    assert undo_texts(win)[-1] == "Remove element Co" and "Co" not in tiles_selected(win)
    states = []
    # Undo repeatedly: every step restores order, values and the periodic table
    win.undo()
    pump(app)
    assert list(sv.rows) == ["Co", "Fe", "Ni"] and sv.values["Fe"] == 2.5 and sv.values["Co"] == 1
    assert set(tiles_selected(win)) == {"Co", "Fe", "Ni"}
    win.undo()
    pump(app)
    assert sv.values["Fe"] == 1
    win.undo()
    pump(app)
    assert list(sv.rows) == ["Co", "Fe"] and set(tiles_selected(win)) == {"Co", "Fe"}
    # Redo repeatedly
    win.redo()
    win.redo()
    pump(app)
    assert list(sv.rows) == ["Co", "Fe", "Ni"] and sv.values["Fe"] == 2.5
    win.redo()
    pump(app)
    assert list(sv.rows) == ["Fe", "Ni"] and set(tiles_selected(win)) == {"Fe", "Ni"}
    assert not win.undo_mgr.can_redo()
    # a new edit after undo drops the redo branch
    win.undo()
    pump(app)
    assert win.undo_mgr.can_redo()
    click_elements(win, "Cr")
    assert not win.undo_mgr.can_redo() and undo_texts(win)[-1] == "Add element Cr"
    assert win.undo_action.isEnabled() and "add element cr" in win.undo_action.text().lower()


def test_no_step_for_derived_updates_drafts_or_unchanged_commits(win, app):
    sv = single_with(win, app, ("Co", "Fe", "Ni"), "at")             # Co: the balance (derived)
    n = win.undo_mgr.stack.count()
    # leaving a field without changing it
    sv.rows["Fe"].fields["at"].setFocus()
    pump(app)
    sv.rows["Ni"].fields["at"].setFocus()
    pump(app)
    assert win.undo_mgr.stack.count() == n
    # an empty draft row opened and discarded
    win.composition.add_draft()
    pump(app)
    win.composition.discard_drafts()
    pump(app)
    assert win.undo_mgr.stack.count() == n
    sv.radios["at"].click()                                       # the draft left the El. column active
    pump(app)
    assert win.undo_mgr.stack.count() == n, "back to the same basis: not an edit"
    # an edit: one step, although the balance and three other columns changed with it
    f = sv.rows["Fe"].fields["at"]
    f.setFocus()
    f.setText("40")
    f.textEdited.emit("40")
    sv.rows["Ni"].fields["at"].setFocus()
    pump(app)
    assert win.undo_mgr.stack.count() == n + 1
    bal = sv.values["Co"]
    win.undo()
    pump(app)
    assert sv.values["Fe"] == pytest.approx(100 / 3) and sv.values["Co"] != bal     # the balance follows


def test_rename_and_lock_undo(win, app):
    from PySide6.QtCore import Qt
    click_elements(win, "Co", "Fe", "Ni")
    win.composition.set_mode(1)
    pump(app)
    sw = win.composition.sweep
    sw.rows["Fe"].max.setFocus()
    sw.rows["Fe"].max.setText("1.8")
    sw.rows["Fe"].max.textEdited.emit("1.8")
    sw.rows["Ni"].max.setFocus()
    pump(app)
    assert undo_texts(win)[-1] == "Edit Fe range"
    # rename Fe -> Cr (symbol field + Enter)
    el = sw.rows["Fe"].el
    el.setFocus()
    el.setText("Cr")
    from PySide6.QtTest import QTest
    QTest.keyClick(el, Qt.Key.Key_Return)
    pump(app, 30)
    assert "Cr" in sw.rows and "Fe" not in sw.rows and undo_texts(win)[-1] == "Rename Fe to Cr"
    assert sw.rows["Cr"].max.text() == "1.8", "values follow the renamed row"
    win.composition.discard_drafts()
    sw.rows["Ni"].lock.click()
    pump(app)
    assert undo_texts(win)[-1] == "Unlock Ni" and not sw.rows["Ni"].lock.isChecked()
    win.undo()
    pump(app)
    assert sw.rows["Ni"].lock.isChecked()
    win.undo()
    pump(app)
    assert "Fe" in sw.rows and "Cr" not in sw.rows and sw.rows["Fe"].max.text() == "1.8"
    assert set(tiles_selected(win)) == {"Co", "Fe", "Ni"}
    win.redo()
    pump(app)
    assert "Cr" in sw.rows and set(tiles_selected(win)) == {"Co", "Cr", "Ni"}
    win.undo()
    win.undo()
    pump(app)
    assert sw.rows["Fe"].max.text() == "2.0"


def test_undo_returns_to_the_mode_of_the_edit_and_mode_switches_are_not_steps(win, app):
    sv = single_with(win, app, ("Co", "Fe"), "ratio")
    n = win.undo_mgr.stack.count()
    win.composition.set_mode(1)
    win.composition.set_mode(0)
    win.composition.set_mode(1)
    pump(app)
    assert win.undo_mgr.stack.count() == n, "switching the mode records nothing"
    win.undo()                                                      # undo the Single edit (input column)
    pump(app)
    assert win.composition.mode == "single"


# ============================================================================================ B2 result removal undo
def _record_data(win, rid):
    rec = win.repo.get_result(rid)
    return None if rec is None else (rec.id, rec.run_id, rec.seq, rec.name, tuple(rec.v))


def test_removed_results_come_back_exactly_and_go_again(win, app):
    m = win.table.model
    calc_rows(win, app, 4)                                       # run 1
    calc_rows(win, app, 3)                                       # run 2
    ids = [r.id for r in m.page_rows()]
    order = list(ids)
    runs = {win.repo.get_result(i).run_id for i in ids}
    assert len(runs) == 2
    victims = [ids[1], ids[4]]                                   # one row of each run
    before = {i: _record_data(win, i) for i in victims}
    win.analysis_ctl.set_active(ids[0], by="table")
    pump(app)
    win.remove_results([m.view_record(i) if hasattr(m, "view_record") else win.repo.get_result(i) for i in victims])
    pump(app)
    assert [r.id for r in m.page_rows()] == [i for i in order if i not in victims]
    assert all(not m.view.is_alive(i) for i in victims)
    assert win.undo_mgr.stack.undoText().startswith("Remove 2")
    win.undo()
    pump(app)
    assert [r.id for r in m.page_rows()] == order, "the same ids, in their original order"
    assert {i: _record_data(win, i) for i in victims} == before, "the same data and run identity"
    assert win.repo.count() == len(order), "no duplicate restored records"
    assert win.analysis_ctl.state.active == ids[0], "Analysis keeps its composition"
    win.redo()
    pump(app)
    assert [r.id for r in m.page_rows()] == [i for i in order if i not in victims]
    assert win.repo.count() == len(order) - 2
    win.undo()
    pump(app)
    assert [r.id for r in m.page_rows()] == order


def test_removing_the_active_result_and_undoing(win, app):
    m = win.table.model
    calc_rows(win, app, 3)
    ids = [r.id for r in m.page_rows()]
    win.analysis_ctl.set_active(ids[1], by="table")
    pump(app)
    win.remove_results([win.repo.get_result(ids[1])])
    pump(app)
    st = win.analysis_ctl.state
    assert st.active_gone == "removed", "Analysis says its composition was removed (existing rule)"
    win.undo()
    pump(app)
    assert ids[1] in [r.id for r in m.page_rows()]
    assert not win.analysis_ctl.state.active_gone
    assert win.repo.get_result(ids[1]) is not None


# ============================================================================================ B3 / B4 collections
def _sql(win, query, params=()):
    import sqlite3
    con = sqlite3.connect(f"file:{win.repo.db_path}?mode=ro", uri=True)
    try:
        return con.execute(query, params).fetchall()
    finally:
        con.close()


def _two_runs(win, app):
    calc_rows(win, app, 4)                                         # run A: R0..R3
    calc_rows(win, app, 3)                                         # run B: R0..R2 (the same three compositions)
    runs = sorted(r.run_id for r in win.analysis_ctl.runs())
    assert len(runs) == 2
    return runs


def _wait(c, app):
    c.wait_idle()
    pump(app)


def test_collection_keeps_its_snapshot_while_results_stream_in(win, app):
    c = win.analysis_ctl
    a, b = _two_runs(win, app)
    c.scope_for(b, "full")
    _wait(c, app)
    assert c.state.resolved.n == 3
    version = c.state.data_version
    slots = []
    orig = c.run_query
    c.run_query = lambda slot, *a_, **k: (slots.append(slot), orig(slot, *a_, **k))[1]
    try:
        for _ in range(5):                                         # commits of the collection's run
            c.rows_committed(b)
        c.run_finished(b)
        pump(app, 40)
        # only the runs list recounts; the collection itself is never re-queried while results stream in
        assert set(slots) <= {"run_counts"}, slots
        assert c.state.newer_results and c.state.data_version == version and c.state.resolved.n == 3
        c.rows_committed(a)                                        # another run: nothing for this collection
        assert c.state.newer_results
    finally:
        c.run_query = orig
    c.refresh_collection()
    _wait(c, app)
    assert not c.state.newer_results and c.state.data_version == version + 1 and c.state.resolved.n == 3
    c.refresh_collection()                                         # idempotent
    _wait(c, app)
    assert c.state.resolved.n == 3


def S_switch_context():  # noqa: N802
    from hea_calc.core.analysis import state as S
    return S.switch_context


def test_combined_collection_counts_statistics_and_provenance(win, app):
    import statistics as st_
    c = win.analysis_ctl
    a, b = _two_runs(win, app)
    before = _sql(win, "SELECT result_id, run_id, name, vec FROM results ORDER BY result_id")
    assert c.combine([a, b]) is None
    _wait(c, app)
    sc = c.state.scope
    assert sc.combined and sc.run_ids == (a, b) and c.state.resolved.n == 7
    info = c.run_info(sc.run_id)
    assert info.mode == "combined" and info.source["combined"] == [a, b] and info.axes == []
    # every result keeps its id and run (nothing copied or merged): the population is exactly the two runs
    ids = [r[0] for r in _sql(win, "SELECT result_id FROM results WHERE run_id IN (?, ?)", (a, b))]
    c.run_query("t_ids", lambda sq: [r[0] for r in sq._exec(f"SELECT r.result_id FROM {sq.frm} WHERE {sq.where}",
                                                            sq.params).fetchall()])
    c.run_query("t_stats", lambda sq: sq.statistics(["vec"]))
    c.run_query("t_dist", lambda sq: sq.distribution())
    _wait(c, app)
    assert sorted(c.data["t_ids"]) == sorted(ids) and len(ids) == 7
    # statistics over both runs: independent mean / SD of the stored values
    vals = [r[0] for r in _sql(win, "SELECT vec FROM results WHERE run_id IN (?, ?)", (a, b)) if r[0] is not None]
    m = c.data["t_stats"]["metrics"]["vec"]
    assert m["n_valid"] == len(vals) == 7
    assert m["mean"] == pytest.approx(st_.mean(vals)) and m["sd"] == pytest.approx(st_.stdev(vals))
    # model distribution: the class counts of both runs together
    exp = dict(_sql(win, 'SELECT "M1", COUNT(*) FROM results WHERE run_id IN (?, ?) GROUP BY 1', (a, b)))
    got = c.data["t_dist"]["models"]["M1"]
    assert got["population"] == 7
    assert got["classes"] == {k: v for k, v in exp.items() if k not in (None, "N/A")}
    # duplicates: the three shared compositions are reported, and each result still counts once
    assert c.data.get("dups") == 3
    # filtered combined population: the table filter applies across both runs
    from hea_calc.core.results import RangeFilter
    cut = sorted(vals)[3]
    win.table.model.set_filters([RangeFilter("vec", cut, None)])
    pump(app)
    c.scope_for(sc.run_id, "filtered")
    _wait(c, app)
    assert c.state.scope.combined and c.state.resolved.n == sum(1 for v in vals if v >= cut)
    win.table.model.set_filters([])
    # back to an individual run: its own population; the stored data never changed
    c.scope_for(a, "full")
    _wait(c, app)
    assert not c.state.scope.combined and c.state.resolved.n == 4
    assert _sql(win, "SELECT result_id, run_id, name, vec FROM results ORDER BY result_id") == before
    assert _sql(win, "PRAGMA integrity_check") == [("ok",)]
    # streaming into one of its runs marks the combined collection, it does not rebuild it
    assert c.combine([a, b]) is None
    _wait(c, app)
    c.rows_committed(b)
    assert c.state.newer_results


def test_combining_requires_two_compatible_runs(win, app, monkeypatch):
    from hea_calc.core.analysis.combine import combine_problem
    c = win.analysis_ctl
    a, b = _two_runs(win, app)
    assert c.combine([a]) is not None, "one run is not a combination"
    ia, ib = c.run_info(a), c.run_info(b)
    assert combine_problem([ia, ib]) is None
    from dataclasses import replace
    other = replace(ib, engine_version="0000")
    assert "engine version" in combine_problem([ia, other])
    other = replace(ib, dataset_ids={**ib.dataset_ids, "periodic_table.json": "x"})
    assert "datasets" in combine_problem([ia, other])
    other = replace(ib, settings={**ib.settings, "something": 1})
    assert "settings" in combine_problem([ia, other])


def test_combine_runs_dialog_selection(win, app):
    from hea_calc.ui.analysis.collection_view import run_items
    from hea_calc.ui.analysis.combine_dialog import CombineRunsDialog
    c = win.analysis_ctl
    a, b = _two_runs(win, app)
    items = run_items(c)
    combine = next(i for i in items if i[0] == "combine")
    assert combine[2] is True, "Combine runs… is available with two runs"
    dlg = CombineRunsDialog(c, win)
    try:
        assert not dlg.combine_btn.isEnabled()
        dlg.checks[a].setChecked(True)
        assert not dlg.combine_btn.isEnabled() and "two" in dlg.problem.text()
        dlg.checks[b].setChecked(True)
        assert dlg.combine_btn.isEnabled() and "7 results" in dlg.problem.text()
        dlg.combine_btn.click()
        assert dlg.chosen == (a, b)
    finally:
        dlg.deleteLater()
    assert c.combine(dlg.chosen) is None
    _wait(c, app)
    items = run_items(c)
    assert any(i[0] == -1 and "Combined: Runs" in i[1] for i in items)


# ============================================================================================ B5 system size All
def test_unlocking_after_all_locked_selects_all_sizes(win, app):
    click_elements(win, "Co", "Cr", "Fe", "Mn", "Ni")
    win.composition.set_mode(1)
    pump(app)
    sw = win.composition.sweep
    box = sw.size_box
    rows = list(sw.rows.values())
    assert all(r.lock.isChecked() for r in rows)
    assert box.read_only and [o[0] for o in box.options] == [5]     # all locked: only N, read-only
    rows[0].lock.click()                                            # unlock 1
    pump(app)
    assert [o[0] for o in box.options] == [4, 5] and not box.read_only
    assert box.current_html() == "All" and sw.sizes() is None       # All = every possible size (4 and 5)
    for r in rows[1:3]:                                             # unlock 3 in all
        r.lock.click()
    pump(app)
    assert [o[0] for o in box.options] == [2, 3, 4, 5] and box.current_html() == "All"
    box.set_options(box.options, (5,))                              # an earlier explicit choice: the maximum
    sw._size_chosen((5,))
    sw.all_lock.setChecked(True)                                    # re-lock all
    sw._apply_all_lock()
    pump(app)
    assert [o[0] for o in box.options] == [5] and box.read_only
    rows[4].lock.click()                                            # unlock again: All, never the old maximum
    pump(app)
    assert box.current_html() == "All" and [o[0] for o in box.options] == [4, 5]
    # an explicit narrower choice is kept through compatible edits
    rows[3].lock.click()                                            # 3..5 possible
    pump(app)
    box.set_options(box.options, (4,))                              # the user chooses 4
    sw._size_chosen((4,))
    rows[0].max.setText("2.0")
    sw._edited()
    rows[2].lock.click()                                            # another unlock: 2..5 possible, 4 still is
    pump(app)
    assert box.current_html() == "4" and set(sw.sizes()) == {4}


# ============================================================================================ C1-C4 columns / filters
# model -> the descriptors only it uses: the engine's own outcome values (model-local names mapped to columns)
_ENGINE_NAMES = {"M1": {"omega": "omega", "delta_cn12": "delta_cn12"}, "M3": {"gamma": "gamma"},
                 "M4": {"lambda": "lambda"}, "M5": {"phi": "phi_ye", "s_e": "s_e"},
                 "M6": {"hf_min": "hf_min", "hf_max": "hf_max", "lower": "hf_lower"},
                 "M7": {"k1": "k1", "k1cr": "k1cr"}, "M8": {"phi": "phi_king", "dg_ss": "dg_ss", "dg_max": "dg_max"}}


def _model_short(k):
    from hea_calc.core.engine import MODELS
    return MODELS[k].short


def test_descriptors_are_grouped_under_the_model_that_owns_them():
    import re
    from hea_calc.core.engine import Engine
    from hea_calc.core.results import COLUMNS, chooser_groups
    res = Engine().calculate({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "Mn": 1})
    used = {k: set(o.values) for k, o in res.models.items()}
    for model, names in _ENGINE_NAMES.items():
        assert set(names) <= used[model], (model, used[model])          # the engine really uses them
    owned = {c.key: c.model for c in COLUMNS if c.model and c.kind != "model"}
    expected = {col: m for m, names in _ENGINE_NAMES.items() for col in names.values()}
    expected["dhim"] = "M7"                                             # ΔH_IM: the intermetallic term of M7
    assert owned == expected
    # shared descriptors stay in General; nothing appears twice; Composition (at.%) is not offered
    groups = chooser_groups()
    keys = [c.key for _g, cols in groups for c in cols]
    assert len(keys) == len(set(keys)) and "composition" not in keys
    general = dict(groups)["General"]
    assert {c.key for c in general} >= {"dhmix", "delta", "vec", "tm", "dsmix", "t_assess"}
    assert all(c.model is None for c in general)
    # chooser tooltips: no bibliographic reference, no repeated model name for owned descriptors
    for c in COLUMNS:
        if c.chooser and c.chooser_tip:
            assert not re.search(r"\(\d{4}\)|et al\.|\b(19|20)\d{2}\b", c.chooser_tip), (c.key, c.chooser_tip)
            if c.model and c.kind != "model":
                assert c.model not in c.chooser_tip and _model_short(c.model) not in c.chooser_tip


def test_columns_dialog_groups_and_saved_layouts(win, app):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.widgets.dialogs import ColumnsDialog
    dlg = ColumnsDialog(win.table.model.keys, win)
    try:
        assert "composition" not in dlg.checks and "run" in dlg.checks and "variables" in dlg.checks
        assert dlg.checks["phi_king"].toolTip() and "King" not in dlg.checks["phi_king"].toolTip()
        dlg.show()
        pump(app)
        avail = win.screen().availableGeometry().height()
        assert 420 <= dlg.height() <= int(avail * 0.9) + 1
    finally:
        dlg.close()
        dlg.deleteLater()
    # a stored layout that still holds Composition (at.%) loads without it, and nothing breaks
    s = win.settings
    s.setValue("columns", ["name", "composition", "vec", "M1", "no_such_column"])
    w2 = MainWindow(settings=s)
    try:
        assert w2.table.model.keys == ["name", "vec", "M1"]
    finally:
        w2.close()
        w2.deleteLater()
        pump(app)


def test_run_and_variables_columns_show_sort_and_export(win, app):
    m = win.table.model
    calc_rows(win, app, 2)
    win.composition.set_mode(2)
    e = win.composition.expr
    e.set_text("AlxCoCrFeNi\n0 <= x <= 1, step=0.5")
    assert e.parse()
    settle_counts(win, app)
    win.composition.calc_btn.click()
    wait_worker(win, app)
    m.set_keys(["name", "run", "variables", "vec"])
    m.wait()
    pump(app)
    rows = m.page_rows()
    runs = {r.run_id for r in rows}
    assert len(runs) == 2
    texts = {r.id: (m.cell_text(i, 1), m.cell_text(i, 2)) for i, r in enumerate(rows)}
    expr_rows = [r for r in rows if r.run_id == max(runs)]
    assert sorted(texts[r.id][1] for r in expr_rows) == ["x = 0", "x = 0.5", "x = 1"]
    assert all(texts[r.id][1] == "" for r in rows if r.run_id == min(runs)), "no variables: empty, never invented"
    assert all(texts[r.id][0] == str(r.run_id) for r in rows)
    m.sort_by("run")
    m.wait()
    pump(app)
    assert [r.run_id for r in m.page_rows()] == sorted(r.run_id for r in rows)
    m.sort_by("variables")                                         # not sortable: nothing changes
    assert m.sort_key == "run"
    # clipboard / export text carries both
    from hea_calc.core.results import table_tsv
    tsv = table_tsv([win.repo.get_result(r.id) for r in expr_rows], ["name", "run", "variables"])
    assert "Run\tVariables" in tsv and "x = 0.5" in tsv
    # the schema did not change (derived columns)
    cols = [c[1] for c in _sql(win, "PRAGMA table_info(results)")]
    assert "run" not in cols and "variables" not in cols


def test_filter_builder_adds_edits_removes_and_keeps_semantics(win, app):
    from hea_calc.core.chunks import NUM_KEYS
    from hea_calc.core.results import ModelFilter, RangeFilter
    from hea_calc.ui.widgets.dialogs import FilterDialog
    existing = [RangeFilter("vec", 7.0, None), ModelFilter("M4", {"SS", "SS+IM"})]
    dlg = FilterDialog(existing, win)
    try:
        assert [r.key for r in dlg.rules] == ["vec", "M4"], "current filters open as rules"
        vec = dlg.rules[0]
        assert vec.op.value == "ge" and vec.lo.text() == "7" and vec.hi.isHidden()
        m4 = dlg.rules[1]
        assert [o[0] for o in m4.classes.options] == ["SS", "SS+IM", "IM", "N/A"], "only the classes M4 produces"
        assert set(m4.classes.selected) == {"SS", "SS+IM"}
        assert m4.lo is None and m4.op is None, "no numeric inputs for a categorical rule"
        dlg._apply()                                               # unchanged rules: exactly the same filters
        assert dlg.result_filters == existing
        r = dlg.add_rule("delta")                                  # a parameter cannot be added twice
        assert dlg.add_rule("delta") is r and len(dlg.rules) == 3
        assert r.op.value == "between"
        r.lo.setText("1")
        r.hi.setText("0.5")
        dlg.setResult(0)
        dlg._apply()
        assert dlg.result() == 0 and "minimum exceeds" in dlg.error.text()
        r.hi.setText("6")
        dlg.remove_rule(dlg.rules[1])                              # remove M4
        dlg._apply()
        assert dlg.result_filters == [RangeFilter("vec", 7.0, None), RangeFilter("delta", 1.0, 6.0)]
    finally:
        dlg.deleteLater()
    dlg = FilterDialog([], win)
    try:
        assert not dlg.empty.isHidden()
        groups = [g for g, _c in dlg.parameters()]
        assert groups[0] == "General" and "M8 King et al." in groups
        assert all(c.key in NUM_KEYS or c.kind == "model" for _g, cols in dlg.parameters() for c in cols)
        rule = dlg.add_rule("M2")
        rule.classes.set_options(rule.classes.options, ())
        dlg.setResult(0)
        dlg._apply()
        assert dlg.result() == 0 and "at least one class" in dlg.error.text()
        dlg.clear()
        dlg._apply()
        assert dlg.result_filters == []
    finally:
        dlg.deleteLater()


def test_filter_builder_results_match_the_table(win, app):
    from hea_calc.core.results import RangeFilter
    calc_rows(win, app, 6)
    vals = [v for (v,) in _sql(win, "SELECT vec FROM results") if v is not None]
    cut = sorted(vals)[2]
    win.table.model.set_filters([RangeFilter("vec", cut, None)])
    win.table.model.wait()
    pump(app)
    assert win.table.model.view_count() == sum(1 for v in vals if v >= cut)


def test_variables_column_shows_composition_space_grid_values(win, app):
    m = win.table.model
    run_space(win, app, els=("Al", "Ti", "V"), step="50")
    m.set_keys(["name", "variables"])
    m.wait()
    pump(app)
    texts = [m.cell_text(i, 1) for i in range(m.rowCount())]
    assert texts and all(t_.startswith("Al = ") and "Ti = " in t_ and "V = " in t_ for t_ in texts), texts[:3]
    assert "at.%" not in " ".join(texts), "grid values, never the derived fractions"


# ============================================================================================ D1 report plots
def _pdf_text(path):
    import time
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtWidgets import QApplication
    doc = QPdfDocument()
    doc.load(str(path))
    t0 = time.perf_counter()
    while doc.status() != QPdfDocument.Status.Ready and time.perf_counter() - t0 < 10:
        QApplication.processEvents()
    text = "\n".join(doc.getAllText(i).text() for i in range(doc.pageCount()))
    n = doc.pageCount()
    doc.close()
    return n, text


def _open_tab(win, app, tab):
    from hea_calc.core.analysis import state as S
    c = win.analysis_ctl
    c.apply(S.switch_context, S.COLLECTION)
    c.apply(S.set_tab, tab)
    for _ in range(6):
        c.wait_idle()
        pump(app, 20)


def _run_report(win, app, chosen, path):
    """export_report with the contents dialog and the file dialog answered."""
    import time
    from unittest import mock
    from PySide6.QtWidgets import QFileDialog
    from hea_calc.ui.analysis import report_dialog, report_ui

    class Fake:
        def __init__(self, candidates, parent=None):
            self.candidates = candidates

        def exec(self):
            return 1

        def chosen(self):
            avail = [c for c in self.candidates if c["available"]]
            return [avail[i] for i in chosen(avail)]

        def deleteLater(self):
            pass
    with mock.patch.object(report_dialog, "ReportPlotsDialog", Fake), \
            mock.patch.object(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), "")):
        report_ui.export_report(win, "collection")
        t0 = time.perf_counter()
        while (win._report_task is not None and win._report_task.running) and time.perf_counter() - t0 < 60:
            pump(app)
            time.sleep(0.01)
    pump(app, 20)
    return _pdf_text(path)


def test_report_candidates_and_zero_one_many_plots(win, app, tmp_path):
    from hea_calc.ui.analysis.report_ui import report_plot_candidates
    calc_rows(win, app, 6)
    run = win.analysis_ctl.runs()[0].run_id
    win.analysis_ctl.scope_for(run, "full")
    _open_tab(win, app, "plots")
    cands = report_plot_candidates(win)
    avail = [c for c in cands if c["available"]]
    assert avail and avail[0]["tab"] == "plots"
    assert any(not c["available"] and c["tab"] == "models" and "Open the Models tab" in c["reason"] for c in cands)
    _open_tab(win, app, "models")
    _open_tab(win, app, "statistics")
    avail = [c for c in report_plot_candidates(win) if c["available"]]
    tabs = [c["tab"] for c in avail]
    assert {"plots", "models"} <= set(tabs) and tabs == sorted(tabs, key=["overview", "plots",
                                                                          "statistics", "models"].index)
    if "statistics" not in tabs:                                   # no focus metric: listed, with the reason
        assert any(c["tab"] == "statistics" and "no chart" in c["reason"] for c in report_plot_candidates(win)
                   if not c["available"])
    # zero charts: summary and provenance only
    n0, text0 = _run_report(win, app, lambda a: [], tmp_path / "r0.pdf")
    assert "MDL HEA Calculator" in text0 and "Descriptive statistics" in text0 and "Plot 1" not in text0
    assert "\nPlot\n" not in text0
    # one chart
    n1, text1 = _run_report(win, app, lambda a: [0], tmp_path / "r1.pdf")
    assert n1 in (n0 + 1, n0 + 2) and "Source" in text1 and "Plots tab" in text1   # its own page (+ text flow)
    # several, in the chosen order, each with its scope
    order = lambda a: [len(a) - 1, 0, 1]                                       # noqa: E731
    n3, text3 = _run_report(win, app, order, tmp_path / "r3.pdf")
    assert n0 + 3 <= n3 <= n0 + 4 and "Plot 1 of 3" in text3 and "Plot 3 of 3" in text3
    assert text3.count(f"Run {run} (") >= 3, "every chart states its scope"
    first = text3.index("Plot 1 of 3")
    assert "Models tab" in text3[first:text3.index("Plot 2 of 3")]
    assert text3.count("MDL HEA Calculator") >= n3, "the identity is on every page (footer)"


def test_combined_report_names_its_runs(win, app, tmp_path):
    c = win.analysis_ctl
    a, b = _two_runs(win, app)
    _open_tab(win, app, "models")                                   # Combine runs is a Collection action
    assert c.combine([a, b]) is None
    _open_tab(win, app, "models")
    assert c.state.scope.combined
    n, text = _run_report(win, app, lambda av: [0], tmp_path / "comb.pdf")
    assert f"Combined: Runs {a}, {b}" in text and "Contributing runs" in text
    assert f"Run {a} (" in text and f"Run {b} (" in text and "nothing is merged" in text


def test_report_dialog_selection_and_order(win, app):
    from hea_calc.ui.analysis.report_dialog import ReportPlotsDialog
    cands = [{"key": "a", "tab": "plots", "tab_label": "Plots", "title": "Scatter", "available": True, "pw": None},
             {"key": "b", "tab": "models", "tab_label": "Models", "title": "M1 classes", "available": True, "pw": None},
             {"key": "c", "tab": "statistics", "tab_label": "Statistics", "title": "Statistics charts",
              "available": False, "reason": "Open the Statistics tab once to include its charts.", "pw": None}]
    dlg = ReportPlotsDialog(cands, win)
    try:
        assert [c["key"] for c in dlg.chosen()] == ["a"], "the Plots tab's chart is preselected"
        dlg.rows[1][2].setChecked(True)
        dlg.move(dlg.rows[1][1], -1)
        assert [c["key"] for c in dlg.chosen()] == ["b", "a"]
        for _c, _r, cb in dlg.rows:
            cb.setChecked(False)
        assert dlg.chosen() == []
    finally:
        dlg.deleteLater()


# ============================================================================================ D2 model figures
def _reference_cases():
    import json
    ref = Path(__file__).resolve().parent / "reference" / "published_benchmarks.json"
    return json.loads(ref.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("model", ["M1", "M2", "M3", "M4", "M5", "M7", "M8"])
def test_model_figure_points_are_the_published_tabulated_values(model):
    from hea_calc.core.analysis.model_figures import figure
    fig = figure(model)
    xk, yk = fig.x_key, fig.y_key
    # independent: every published case of the model that prints the figure's quantities (reference file)
    expected = [(c["formula"], c["published"][xk], c["published"].get(yk) if yk else None,
                 c.get("published_class") or c.get("observed"))
                for c in _reference_cases() if c["model"] == model and xk in c["published"]
                and (yk is None or yk in c["published"])]
    got = [(p["label"], p["x"], p["y"], p["cls"] or None) for p in fig.points]
    assert got == expected and got, model
    assert fig.source.startswith(fig.source.split(",")[0]) and "doi" in fig.source


def test_model_figures_state_their_provenance_and_thresholds():
    from hea_calc.core.analysis.model_figures import THRESHOLDS, evidence_table, figure
    from hea_calc.core.engine import MODELS
    prov = {k: p for k, p, _s, _n in evidence_table()}
    assert prov == {"M1": "publication", "M2": "publication", "M3": "publication", "M4": "publication",
                    "M5": "illustrative", "M6": "illustrative", "M7": "publication", "M8": "illustrative"}
    for k, values in THRESHOLDS.items():
        crit = MODELS[k].criterion.replace("−", "-")
        for v in values:
            assert f"{v:g}" in crit, (k, v, crit)                   # the criterion text states every threshold
        fig = figure(k)
        drawn = {ln.value for ln in fig.lines if ln.kind in ("v", "h")}
        if k != "M7":                                                # M7: the k1 = k1cr diagonal (k2 in the caption)
            assert set(values) <= drawn | {v for v in values if fig.kind == "curves"}, (k, values, drawn)
        assert ("not a reproduction" in fig.caption) == (fig.provenance == "publication")
        assert fig.provenance != "illustrative" or "Illustrative" in fig.caption


def test_m6_window_curves_follow_the_entropy_bound():
    import math
    from hea_calc.core.analysis.model_figures import figure
    kb = 1.380649e-23 / 1.602176634e-22                          # J/K over J per meV: CODATA, independently
    fig = figure("M6")
    curves = [ln for ln in fig.lines if ln.kind == "curve"]
    assert [ln.label.split(", ")[1] for ln in curves] == ["3 elements", "4 elements", "5 elements", "6 elements"]
    for n, ln in zip((3, 4, 5, 6), curves):
        for t_, y in zip(ln.xs[::17], ln.ys[::17]):
            assert y == pytest.approx(-kb * t_ * math.log(n), rel=1e-6)
    assert not fig.points, "no published values invented"


def test_model_figure_m7_discloses_points_outside_the_range():
    from hea_calc.core.analysis.model_figures import M7_RANGE, figure
    fig = figure("M7")
    (xa, xb), (ya, yb) = M7_RANGE
    out = sum(1 for p in fig.points if not (xa <= p["x"] <= xb and ya <= p["y"] <= yb))
    assert out > 0 and f"{out} of the {len(fig.points)} alloys lie outside" in fig.caption


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_model_figures_render_and_export(app, tmp_path, theme):
    from hea_calc.core.analysis.model_figures import figure
    from hea_calc.ui.analysis.model_figure import ModelFigureWidget
    from hea_calc.ui.analysis.plot import class_color
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    try:
        for k in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"):
            fig = figure(k)
            w = ModelFigureWidget(fig, {"x": 3.0, "y": 2.0})
            w.resize(560, 300)
            img = w.grab().toImage()
            colours = {img.pixelColor(x, y).name() for x in range(0, img.width(), 3) for y in range(0, img.height(), 3)}
            classes = {p["cls"] for p in fig.points if p["cls"]}
            for c in classes:                                       # the class colours are drawn
                assert class_color(c) in colours or any(_close(class_color(c), x) for x in colours), (k, c)
            png, svg = tmp_path / f"{k}.png", tmp_path / f"{k}.svg"
            w.export(str(png))
            w.export(str(svg))
            assert png.stat().st_size > 2000 and "<svg" in svg.read_text(encoding="utf-8")[:400]
    finally:
        THEME.set_theme("dark")


def _close(a, b, tol=12):
    from PySide6.QtGui import QColor
    x, y = QColor(a), QColor(b)
    return abs(x.red() - y.red()) + abs(x.green() - y.green()) + abs(x.blue() - y.blue()) <= tol


def test_model_details_show_the_figure_with_this_composition(win, app):
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis.model_figure import ModelFigureWidget
    calc_rows(win, app, 1)
    c = win.analysis_ctl
    c.set_active(win.table.model.page_rows()[0].id, by="table")
    c.apply(S.switch_context, S.COMPOSITION)
    c.apply(S.set_tab, "model_details")
    pump(app, 30)
    for k in ("M1", "M4", "M8"):
        c.apply(S.select_model, k)
        pump(app, 30)
        figs = [f for f in win.findChildren(ModelFigureWidget) if f.isVisible()]
        assert figs and figs[0].fig.model == k
        assert isinstance(figs[0].current.get("x"), float), "the analysed composition is marked"


# ============================================================================================ E2 About
def test_about_shows_the_contact_address_and_no_guessed_repository(win, app, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    from hea_calc.core import references as R
    win.show_about()
    pump(app)
    ab = win._about
    sec = ab.sections["Contact"]
    assert "erdem.alifethi@gmail.com" in sec.text() and "mailto:erdem.alifethi@gmail.com" in sec.text()
    assert R.REPOSITORY_URL is None and "Source code" not in sec.text()      # not verifiable: no guessed link
    assert {"Development", "Original software", "References", "Built with", "Licence"} <= set(ab.sections)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    sec.linkActivated.emit("mailto:erdem.alifethi@gmail.com")
    assert opened == ["mailto:erdem.alifethi@gmail.com"]
    ab.close()


# ============================================================================================ native (Windows desktop)
@pytest.mark.skipif(__import__("sys").platform != "win32" or os.environ.get("HEA_NATIVE_TESTS") != "1",
                    reason="opens real windows; set HEA_NATIVE_TESTS=1 on a Windows desktop")
def test_native_ux_checks():
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    p = subprocess.run([sys.executable, str(Path(__file__).with_name("_native_ux_checks.py"))], cwd=root, env=env,
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0 and "ALL NATIVE UX CHECKS PASSED" in p.stdout, p.stdout + p.stderr


def test_combined_notice_states_the_duplicates_once_known(win, app):
    from PySide6.QtWidgets import QLabel
    from hea_calc.core.analysis import state as S
    c = win.analysis_ctl
    a, b = _two_runs(win, app)
    c.apply(S.switch_context, S.COLLECTION)
    _wait(c, app)
    assert c.combine([a, b]) is None
    for _ in range(4):
        _wait(c, app)
    texts = " ".join(lab.text() for lab in win.analysis.findChildren(QLabel) if lab.isVisible())
    assert "Combined collection" in texts and "3 compositions occur in more than one run" in texts
