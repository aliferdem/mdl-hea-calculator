"""Composition workflow redesign (2026-10-27): A1 Add element draft row + Remove element, A2 balance element.

Real widgets in a real MainWindow (offscreen), driven by QTest key / mouse events and real context-menu events.
Expected states come from the periodic-table path (tile clicks) and from independent arithmetic (100 - sum,
moles = w / M) - never from the changed code's own output."""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    a = QApplication.instance() or QApplication([])
    load_fonts()
    return a


def pump(app, n=10):
    for _ in range(n):
        app.processEvents()


def make_window(app):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1728, 1000)
    w.show()
    w.activateWindow()
    pump(app)
    return w


def close_window(app, w):
    from PySide6.QtCore import QEvent
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


@pytest.fixture()
def win(app):
    w = make_window(app)
    yield w
    close_window(app, w)


def click(app, widget):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    pump(app)


def key(app, widget, name):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClick(widget, getattr(Qt.Key, f"Key_{name}"))
    pump(app)


def type_into(app, widget, text):
    from PySide6.QtTest import QTest
    QTest.keyClicks(widget, text)
    pump(app)


def focused(app):
    from PySide6.QtWidgets import QApplication
    return QApplication.focusWidget()


def state(win):
    """Everything an insertion or removal may touch: composition snapshot + periodic-table selection."""
    return win.composition.snapshot(), sorted(win.elements.table.selected()), list(win.composition._elements)


def layout_index(view, row):
    lay = view.rows_widget.lay
    return next(i for i in range(lay.count()) if lay.itemAt(i).widget() is row)


# ============================================================================================ A1 draft row
@pytest.mark.parametrize("mode", [0, 1])
def test_add_element_opens_one_focused_draft(win, app, mode):
    comp = win.composition
    comp.set_mode(mode)
    pump(app)
    view = comp.view()
    assert comp.add_btn.isVisible() and comp.add_btn.accessibleName() == "Add element"
    click(app, comp.add_btn)
    draft = view.draft
    assert draft is not None and draft.isVisible() and draft not in view.rows.values()
    assert focused(app) is draft.el and not draft.el.isReadOnly()
    assert view.rows_stack.currentWidget() is view.scroll           # shown although nothing is committed yet
    if mode == 0:
        assert view.radios["element"].isChecked() and view.input_rep == "element"
        cells = list(draft.fields.values())
    else:
        cells = [draft.min, draft.max, draft.step]
        assert not draft.lock.isEnabled()                           # a toggle, not a text input
    # 2026-10-28: every column present, blank and read-only (not disabled)
    assert all(f.isVisible() and f.isEnabled() and f.isReadOnly() and f.text() == "" for f in cells)
    click(app, comp.add_btn)                                        # again: the same draft, focused
    assert view.draft is draft and focused(app) is draft.el
    assert sum(1 for r in view.rows_widget.findChildren(type(draft)) if r.isVisible()) == 1


@pytest.mark.parametrize("mode,rep", [(0, None), (0, "at"), (0, "wt"), (1, None)])
def test_keyboard_only_entry_equals_the_periodic_table_path(app, mode, rep):
    by_table = make_window(app)
    by_keys = make_window(app)
    try:
        for w in (by_table, by_keys):
            w.composition.set_mode(mode)
            if rep is not None:
                w.composition.single.radios[rep].click()
            pump(app)
        for el in ("Fe", "Ni", "Cr"):
            by_table.elements.table.tiles[el].click()
            pump(app)
        if mode == 0:
            by_table.composition.single.radios["element"].click()      # the draft activates El.
            pump(app)
        comp = by_keys.composition
        click(app, comp.add_btn)
        view = comp.view()
        draft = view.draft
        for typed in ("fe", "NI", "Cr"):                                # any case, Enter commits
            type_into(app, draft.el, typed)
            key(app, draft.el, "Return")
            assert view.draft is draft and draft.el.text() == "" and focused(app) is draft.el
            assert layout_index(view, draft) == len(view.rows)           # the next blank row is under the last
        assert state(by_keys) == state(by_table)
        if mode == 0 and rep is not None:
            assert comp.single.value_rep == rep                          # El. did not change the basis
        key(app, draft.el, "Escape")                                     # finish: the draft is discarded
        assert view.draft is None and focused(app) is comp.add_btn
        assert state(by_keys) == state(by_table)
    finally:
        close_window(app, by_table)
        close_window(app, by_keys)


@pytest.mark.parametrize("mode", [0, 1])
def test_invalid_and_duplicate_symbols_use_the_existing_validation(win, app, mode):
    comp = win.composition
    comp.set_mode(mode)
    win.elements.table.tiles["Fe"].click()
    pump(app)
    click(app, comp.add_btn)
    view = comp.view()
    draft = view.draft
    before = state(win)
    type_into(app, draft.el, "xx")
    key(app, draft.el, "Return")
    assert draft.el.property("invalid") and comp.footer.status.status.text == "'Xx' is not an element symbol"
    assert state(win) == before and not comp.calc_btn.isEnabled()
    type_into(app, draft.el, "\b\b")                                    # typing clears the error
    assert not draft.el.property("invalid")
    draft.el.clear()
    type_into(app, draft.el, "fe")
    key(app, draft.el, "Enter")                                          # keypad Enter too
    assert comp.footer.status.status.text == "Fe is already in the composition"
    assert state(win) == before and view.draft is draft
    key(app, draft.el, "Return")                                         # still the same message, still no change
    assert state(win) == before
    key(app, draft.el, "Escape")
    assert view.draft is None and view.element_error is None and state(win) == before


def test_blur_discards_an_empty_draft_and_commits_a_typed_one(win, app):
    comp = win.composition
    comp.single.radios["at"].click()
    pump(app)
    click(app, comp.add_btn)
    assert comp.single.draft is not None
    comp.single.radios["at"].setFocus()                                   # focus leaves the empty draft
    pump(app)
    assert comp.single.draft is None and comp._elements == []
    assert comp.single.rows_stack.currentWidget() is comp.single.empty
    click(app, comp.add_btn)
    type_into(app, comp.single.draft.el, "co")
    comp.single.radios["at"].setFocus()                                   # blur with a symbol: committed, no new draft
    pump(app)
    assert comp._elements == ["Co"] and comp.single.draft is None
    assert win.elements.table.selected() == ["Co"]


def test_a_draft_never_enters_a_calculation(win, app):
    comp = win.composition
    for el in ("Fe", "Ni"):
        win.elements.table.tiles[el].click()
    pump(app)
    click(app, comp.add_btn)
    type_into(app, comp.single.draft.el, "co")                            # typed, not committed
    name, ratios = comp.single.composition()
    assert set(ratios) == {"Fe", "Ni"} and "Co" not in name
    assert comp.calc_btn.isEnabled() and comp.single.can_calculate()
    got = []
    comp.calculate_requested.connect(lambda *a: got.append(a))
    comp.calculate()
    assert len(got) == 1 and set(got[0][2][0]) == {"Fe", "Ni"}
    type_into(app, comp.single.draft.el, "\b\bqq")                       # an invalid draft blocks Calculate
    key(app, comp.single.draft.el, "Return")
    assert not comp.calc_btn.isEnabled()
    comp.calculate()
    assert len(got) == 1


def test_add_element_is_hidden_in_expression_and_disabled_while_calculating(win, app):
    comp = win.composition
    for mode, shown in ((0, True), (1, True), (2, False)):
        comp.set_mode(mode)
        pump(app)
        assert comp.add_btn.isVisible() is shown, mode
    comp.add_draft()                                                      # Expression: nothing
    assert comp.single.draft is None and comp.sweep.draft is None and not comp.add_element("Fe")
    comp.set_mode(0)
    comp.set_calculating(True)
    pump(app)
    assert not comp.add_btn.isEnabled()
    comp.add_draft()
    assert comp.single.draft is None
    comp.set_calculating(False)
    pump(app)
    assert comp.add_btn.isEnabled()
    f = comp.footer
    assert f.add_btn.x() == 0 and f.add_btn.height() == f.clear_btn.height()


def test_mode_switch_and_clear_discard_the_draft(win, app):
    comp = win.composition
    click(app, comp.add_btn)
    assert comp.single.draft is not None
    comp.set_mode(1)
    pump(app)
    assert comp.single.draft is None
    click(app, comp.add_btn)
    type_into(app, comp.sweep.draft.el, "ni")
    key(app, comp.sweep.draft.el, "Return")
    assert comp.sweep.draft is not None and comp._elements == ["Ni"]
    comp.clear()
    pump(app)
    assert comp.sweep.draft is None and comp._elements == []


def test_el_activation_keeps_the_basis_and_values(win, app):
    comp = win.composition
    s = comp.single
    s.radios["wt"].click()
    for el in ("Fe", "Ni", "Cr"):
        win.elements.table.tiles[el].click()
    pump(app)
    f = s.rows["Ni"].fields["wt"]
    f.setFocus()
    f.selectAll()
    type_into(app, f, "30")
    shown = {el: float(s.rows[el].fields["wt"].text()) for el in s.rows}
    values = dict(s.values)
    click(app, comp.add_btn)
    assert s.input_rep == "element" and s.value_rep == "wt"
    assert s.values == values and {el: float(s.rows[el].fields["wt"].text()) for el in s.rows} == shown
    assert s.totals["wt"].text() == "100%"
    s.radios["wt"].click()                                               # back: no conversion
    pump(app)
    assert s.values == values


# ============================================================================================ A1 Remove element
def context_menu_choose(app, field, text):
    """Open the field's real context menu (QContextMenuEvent) and choose ``text``; returns the menu's labels."""
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication
    seen = []

    def pick():
        menu = QApplication.activePopupWidget()
        if menu is None:
            QTimer.singleShot(20, pick)
            return
        seen.extend(a.text() for a in menu.actions())
        act = next((a for a in menu.actions() if a.text() == text), None)
        if act is not None:
            act.trigger()
        menu.close()
    QTimer.singleShot(20, pick)
    pos = QPoint(10, 10)
    QApplication.sendEvent(field, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, field.mapToGlobal(pos)))
    pump(app, 20)
    return seen


@pytest.mark.parametrize("mode", [0, 1])
def test_remove_element_equals_a_periodic_table_deselection(app, mode):
    by_table = make_window(app)
    by_menu = make_window(app)
    try:
        for w in (by_table, by_menu):
            w.composition.set_mode(mode)
            for el in ("Fe", "Ni", "Cr"):
                w.elements.table.tiles[el].click()
            pump(app)
        by_table.elements.table.tiles["Ni"].click()
        pump(app)
        view = by_menu.composition.view()
        field = view.rows["Ni"].el
        labels = context_menu_choose(app, field, "Remove element")
        assert "Remove element" in labels and any("Copy" in t for t in labels)    # standard text actions kept
        assert state(by_menu) == state(by_table)
        # from a value field as well, and by row identity after a rename
        row = view.rows["Cr"]
        row.el.setText("co")
        row.el.editingFinished.emit()
        pump(app)
        assert "Co" in view.rows and view.rows["Co"] is row
        value_field = row.fields["ratio"] if mode == 0 else row.min
        context_menu_choose(app, value_field, "Remove element")
        assert by_menu.composition._elements == ["Fe"] and by_menu.elements.table.selected() == ["Fe"]
    finally:
        close_window(app, by_table)
        close_window(app, by_menu)


def test_the_draft_has_no_remove_action(win, app):
    comp = win.composition
    click(app, comp.add_btn)
    labels = context_menu_choose(app, comp.single.draft.el, "Remove element")
    assert labels and "Remove element" not in labels and comp.single.draft is not None


# ============================================================================================ A2 balance element
@pytest.mark.parametrize("rep", ["at", "wt"])
def test_first_committed_element_is_the_live_balance(win, app, rep):
    comp = win.composition
    s = comp.single
    s.radios[rep].click()
    for el in ("Fe", "Ni", "Cr"):
        win.elements.table.tiles[el].click()
    pump(app)
    fe = s.rows["Fe"].fields[rep]
    assert not fe.isEnabled() and s.rows["Ni"].fields[rep].isEnabled() and s.rows["Cr"].fields[rep].isEnabled()
    assert fe.focusPolicy() is not None and not fe.isEnabled()                  # no focus, no Tab stop
    ni = s.rows["Ni"].fields[rep]
    ni.setFocus()
    ni.selectAll()
    type_into(app, ni, "20")
    cr = s.rows["Cr"].fields[rep]
    cr.setFocus()
    cr.selectAll()
    type_into(app, cr, "15.5")
    assert s.values["Ni"] == 20.0 and s.values["Cr"] == 15.5
    assert s.values["Fe"] == pytest.approx(100 - 20 - 15.5, abs=1e-12)
    assert fe.text() == "64.5000" and s.totals[rep].text() == "100%"
    assert comp.calc_btn.isEnabled()
    # typing into the disabled balance field is impossible
    type_into(app, fe, "99")
    assert fe.text() == "64.5000"


@pytest.mark.parametrize("rep", ["at", "wt"])
def test_over_100_is_invalid_never_clamped(win, app, rep):
    comp = win.composition
    s = comp.single
    s.radios[rep].click()
    for el in ("Fe", "Ni", "Cr"):
        win.elements.table.tiles[el].click()
    pump(app)
    for el, v in (("Ni", "70"), ("Cr", "40")):
        f = s.rows[el].fields[rep]
        f.setFocus()
        f.selectAll()
        type_into(app, f, v)
    st = comp.footer.status.status
    assert st.kind == "error" and st.text == "Composition exceeds 100%" and st.blocking
    assert not comp.calc_btn.isEnabled()
    assert s.values["Ni"] == 70.0 and s.values["Cr"] == 40.0 and s.values["Fe"] is None
    assert s.rows["Fe"].fields[rep].text() == "-10.0000" and s.rows["Fe"].fields[rep].property("invalid")
    # the minus sign is in view: wider than the field, the text is scrolled to its start, not its end
    assert s.rows["Fe"].fields[rep].cursorPosition() == 0
    assert s.totals[rep].text() == "110%"
    with pytest.raises(ValueError):
        s.composition()
    f = s.rows["Cr"].fields[rep]                                                # corrected: valid again
    f.setFocus()
    f.selectAll()
    type_into(app, f, "30")
    assert s.values["Fe"] == pytest.approx(0.0, abs=1e-12) and not s.rows["Fe"].fields[rep].property("invalid")
    assert comp.calc_btn.isEnabled()


def test_balance_role_transfers_on_removal_and_clear_removes_it(win, app):
    comp = win.composition
    s = comp.single
    s.radios["at"].click()
    for el in ("Fe", "Ni", "Cr"):
        win.elements.table.tiles[el].click()
    pump(app)
    f = s.rows["Cr"].fields["at"]
    f.setFocus()
    f.selectAll()
    type_into(app, f, "10")
    assert s.balance_element() == "Fe"
    win.elements.table.tiles["Fe"].click()                                     # the balance is removed
    pump(app)
    assert s.balance_element() == "Ni" and not s.rows["Ni"].fields["at"].isEnabled()
    assert s.rows["Cr"].fields["at"].isEnabled() and s.values["Cr"] == 10.0
    assert s.values["Ni"] == pytest.approx(90.0, abs=1e-12)
    comp.clear()
    pump(app)
    assert s.balance_element() is None and not s.rows
    for el in ("Co", "Mn"):
        win.elements.table.tiles[el].click()
    pump(app)
    assert s.balance_element() == "Co" and s.rows["Mn"].fields["at"].isEnabled()


def test_converting_into_percent_preserves_the_physical_composition(win, app):
    comp = win.composition
    s = comp.single
    data = comp.data
    for el in ("Al", "Co", "Cr", "Fe", "Ni"):
        win.elements.table.tiles[el].click()
    pump(app)
    f = s.rows["Al"].fields["ratio"]
    f.setFocus()
    f.selectAll()
    type_into(app, f, "0.5")
    x_ratio = {"Al": 0.5 / 4.5, **{el: 1 / 4.5 for el in ("Co", "Cr", "Fe", "Ni")}}
    s.radios["at"].click()                                                      # Al (balance) = 100 - others
    pump(app)
    for el, x in x_ratio.items():
        assert s.values[el] == pytest.approx(100 * x, rel=1e-12)
    s.radios["wt"].click()
    pump(app)
    m = {el: data.prop(el, "atomic_weight") for el in x_ratio}
    mass = {el: x_ratio[el] * m[el] for el in x_ratio}
    for el in x_ratio:                                                           # independent: w = x M / sum(x M)
        assert s.values[el] == pytest.approx(100 * mass[el] / sum(mass.values()), rel=1e-12)
    s.radios["at"].click()                                                      # wt.% -> at.% via molar masses
    pump(app)
    for el, x in x_ratio.items():
        assert s.values[el] == pytest.approx(100 * x, rel=1e-12)
    assert comp.calc_btn.isEnabled()


def test_normalize_is_gone_from_the_ui_and_help(win, app):
    comp = win.composition
    comp.single.radios["at"].click()
    win.elements.table.tiles["Fe"].click()
    pump(app)
    assert not any(i[0] == "Normalize" for i in comp.footer.calc.menu_items)
    assert not hasattr(comp.single, "normalise") and not hasattr(comp, "_normalize")
    docs_dir = Path(__file__).resolve().parents[1] / "hea_calc" / "docs" / "pages"
    hits = [p.name for p in docs_dir.glob("*.md") if "Normalize" in p.read_text(encoding="utf-8")]
    assert not hits, hits


def test_composition_space_percent_bases_have_no_balance(win, app):
    """at.% / wt.% composition spaces keep enumerating grid points that sum to 100 (no balance: see report A2)."""
    comp = win.composition
    comp.set_mode(1)
    comp.set_basis("at")
    for el in ("Fe", "Ni"):
        win.elements.table.tiles[el].click()
    pump(app)
    assert all(r.min.isEnabled() and r.max.isEnabled() and r.step.isEnabled() for r in comp.sweep.rows.values())
