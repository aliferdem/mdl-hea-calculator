"""UI workflow smoke tests (offscreen). They drive the real widgets end-to-end."""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSettings  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from hea_calc.ui.widgets.common import IconButton  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


@pytest.fixture()
def win(app):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
    settings = QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=settings)
    w.resize(1920, 1000)
    w.show()
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    from PySide6.QtCore import QEvent
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def click_elements(win, *els):
    for el in els:
        win.elements.table.tiles[el].click()
    QApplication.processEvents()


def wait_worker(win, app, timeout=60.0):
    import time
    t0 = time.time()
    while win.worker is not None and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert win.worker is None


def wait_task(task, app, timeout=30.0):
    """Wait for a BackgroundTask (pre-flight count / generation) to deliver."""
    import time
    t0 = time.time()
    while task.busy and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not task.busy


def settle_counts(win, app):
    """Composition setup recounts after a pause (debounced, background): Calculate is disabled while the
    footer says "Updating…" (Figma State=Recalculating).  Run the pending count now and wait for it."""
    comp = win.composition
    if comp.mode == "sweep":
        comp.sweep._timer.stop()
        comp.sweep._update_summary()
        wait_task(comp.sweep._counter, app)
    elif comp.mode == "expression":
        e = comp.expr
        e.parse()
        wait_task(e._counter, app)
    app.processEvents()


def menu_action(win, text):
    return next(i for i in win.composition.footer.calc.menu_items if i[0] == text)


def test_selection_order_and_rows(win):
    click_elements(win, "Cr", "Mn", "Fe")
    single = win.composition.single
    assert list(single.rows) == ["Cr", "Mn", "Fe"]
    assert win.elements.table.selected() and set(win.elements.table.selected()) == {"Cr", "Mn", "Fe"}
    click_elements(win, "Mn")  # deselect
    assert list(single.rows) == ["Cr", "Fe"]


def test_representation_switch_preserves_composition(win):
    click_elements(win, "Al", "Co", "Cr", "Fe", "Ni")
    s = win.composition.single
    s.rows["Al"].fields["ratio"].setText("0.5")
    s._edited("Al", "ratio")
    before = s.composition()[1]
    for idx in (2, 3, 4, 1):  # at.%, wt.%, mass, ratio
        s.radio_group.button(idx).click()
        QApplication.processEvents()
        after = s.composition()[1]
        for el in before:
            assert after[el] == pytest.approx(before[el], rel=1e-9)
    assert s.composition()[0] == "Al0.5CoCrFeNi"


def test_set_equal_and_balance_element(win):
    """2026-10-27: Normalize was removed from the UI (the balance element replaces it in at.% / wt.%)."""
    click_elements(win, "Fe", "Co", "Ni", "Cr")
    s = win.composition.single
    s.radio_group.button(2).click()  # at.%
    menu_action(win, "Set equal")[1]()                 # Calculate menu (Figma split button)
    assert all(v == pytest.approx(25.0) for v in s.values.values())
    # Fe (first committed) is the balance: 100 - the others, live
    s.rows["Co"].fields["at"].setText("40")
    s._edited("Co", "at")
    assert s.values["Fe"] == pytest.approx(10.0) and win.composition.calc_btn.isEnabled()
    # the others above 100 %: invalid, nothing clamped or rescaled, Calculate blocked
    s.rows["Ni"].fields["at"].setText("50")
    s._edited("Ni", "at")
    st = win.composition.footer.status.status
    assert st.kind == "error" and "100%" in st.text and not win.composition.calc_btn.isEnabled()
    assert s.values["Co"] == 40.0 and s.values["Ni"] == 50.0 and s.values["Cr"] == pytest.approx(25.0)
    assert s.values["Fe"] is None and s.rows["Fe"].fields["at"].text() == "-15.0000"
    assert not any(label == "Normalize" for label, *_ in win.composition.footer.calc.menu_items)
    s.radio_group.button(0).click()  # element column: set equal disabled
    assert not menu_action(win, "Set equal")[2]


def test_invalid_input_blocks_calculation(win):
    click_elements(win, "Fe", "Ni")
    s = win.composition.single
    s.rows["Fe"].fields["ratio"].setText("abc")
    s._edited("Fe", "ratio")
    assert s.rows["Fe"].fields["ratio"].property("invalid")
    n = len(win.table.model.rows)
    # the explanation is in the Composition setup footer and Calculate is disabled (no calculation)
    st = win.composition.footer.status.status
    assert st.kind == "error" and "number" in st.text
    assert not win.composition.calc_btn.isEnabled()
    win.composition.calc_btn.click()
    win.composition.calculate()                        # even a direct request is refused
    assert len(win.table.model.rows) == n
    assert win.progress.message is not None and win.progress.message[0] == "error"


def test_element_column_rename(win):
    click_elements(win, "Fe", "Ni")
    s = win.composition.single
    s.radio_group.button(0).click()
    row = s.rows["Ni"]
    row.el.setText("co")
    row.el.editingFinished.emit()
    QApplication.processEvents()
    assert list(s.rows) == ["Fe", "Co"]
    assert set(win.elements.table.selected()) == {"Fe", "Co"}
    row = s.rows["Co"]
    row.el.setText("Xx")
    row.el.editingFinished.emit()
    assert row.el.property("invalid")


def test_single_calculation_and_details(win):
    click_elements(win, "Co", "Cr", "Fe", "Ni")
    win.composition.calc_btn.click()
    m = win.table.model
    assert len(m.rows) == 1
    row = m.rows[0]
    assert row.name == "CoCrFeNi"
    assert win.details.row.row_id == row.id        # stable store identity, reproduced result
    assert row.result.descriptors["dhmix"] == pytest.approx(-3.75)


def test_sweep_and_pagination(win, app):
    click_elements(win, "Al", "Ti", "V")
    win.composition.set_mode(1)
    sw = win.composition.sweep
    win.composition.set_basis("at")  # at.%
    for row in sw.rows.values():
        row.min.setText("0")
        row.max.setText("100")
        row.step.setText("10")
    sw.all_lock.click()  # unlock all -> optional elements: binaries and the ternary
    assert not any(r.lock.isChecked() for r in sw.rows.values())
    settle_counts(win, app)
    assert sw.summary_data.systems == 4 and sw.summary_data.compositions == 63  # 3 x 9 binaries + 36 ternaries
    assert win.composition.calc_btn.isEnabled()
    win.composition.calc_btn.click()
    wait_worker(win, app)
    m = win.table.model
    assert len(m.rows) == 63 and all(r.result.ok for r in m.rows)
    win.table.pagination.size_box.setCurrentIndex(0)  # 10 per page
    assert m.page_size == 10 and m.page_count() == 7
    win.table.pagination.next_btn.click()
    assert m.page == 1 and len(m.page_rows()) == 10
    win.table.pagination.page_field.setText(str(m.page_count()))
    win.table.pagination.page_field.returnPressed.emit()
    assert len(m.page_rows()) == 3


def test_sweep_ratio_space_figma_example(win, app):
    click_elements(win, "Cr", "Mn", "Fe", "Co", "Ni")
    win.composition.set_mode(1)
    sw = win.composition.sweep
    vals = {"Cr": ("0.5", "1.5", "0.1"), "Mn": ("0.5", "1.5", "0.1"), "Fe": ("0.8", "1.2", "0.1"),
            "Co": ("1.0", "1.0", "0.1"), "Ni": ("0.5", "1.5", "0.1")}
    for el, (a, b, c) in vals.items():
        r = sw.rows[el]
        r.min.setText(a), r.max.setText(b), r.step.setText(c)
    sw._edited()
    assert sw.all_min.placeholderText() == "Mixed" and sw.all_step.placeholderText() == "0.1"
    assert sw.all_step.text() == ""  # common value shown as placeholder; typing applies to all rows
    sw._update_summary()
    wait_task(sw._counter, app)
    s = sw.summary_data
    assert (s.selected, s.required, s.optional, s.systems, s.compositions) == (5, 5, 0, 1, 6655)
    assert "6,655</span><span style='font-size:12px'> valid compositions" in sw.workload.count.text()
    sw.all_max.setText("1.0")
    sw.all_max.editingFinished.emit()
    assert all(r.max.text() == "1.0" for r in sw.rows.values())


def test_expression_mode(win, app):
    win.composition.set_mode(2)
    e = win.composition.expr
    assert not win.composition.calc_btn.isEnabled()
    # inline syntax: the range is a line of the same block - no Min / Max / Step fields
    e.set_text("(FeCoNi)1-xAlx\n0 <= x <= 0.5, step=0.1")
    assert win.composition.calc_btn.text() == "Parse expression", "draft: Calculate waits for Parse"
    assert e.parse()
    assert not hasattr(e, "var_rows")
    assert set(win.elements.table.selected()) == {"Fe", "Co", "Ni", "Al"}
    settle_counts(win, app)
    assert win.composition.calc_btn.isEnabled()
    win.composition.calc_btn.click()
    wait_worker(win, app)
    names = [r.name for r in win.table.model.rows]
    assert names[0] == "FeCoNi" and "(FeCoNi)0.9Al0.1" in names and len(names) == 6
    assert win.table.model.rows[1].variables == {"x": 0.1}
    QApplication.clipboard().setText("")
    win.composition._copy_compositions()             # Calculate menu: Copy table
    wait_task(win.composition._gen_task, app)
    text = QApplication.clipboard().text()
    assert text.startswith("Alloy\tFe (at.%)") and len(text.strip().split("\r\n")) == 7


def test_expression_blocks_in_ui(win, app):
    win.composition.set_mode(2)
    e = win.composition.expr
    e.set_text("CoCrFeNi\n\nAl{x}CoCrFeNi\n0.5 <= x <= 1, step=0.5")
    assert e.parse()
    settle_counts(win, app)
    win.composition.calc_btn.click()
    wait_worker(win, app)
    assert [r.name for r in win.table.model.rows] == ["CoCrFeNi", "Al0.5CoCrFeNi", "AlCoCrFeNi"]
    e.set_text("FeCo\n\nXq")
    assert not e.parse() and e.state() == "error" and e.edit.diagnostics


def test_copy_filter_columns_delete(win, app):
    click_elements(win, "Co", "Cr", "Fe", "Ni")
    win.composition.calc_btn.click()
    click_elements(win, "Al")
    win.composition.calc_btn.click()
    m = win.table.model
    assert len(m.rows) == 2
    win.copy_table()
    text = QApplication.clipboard().text()
    lines = text.strip("\r\n").split("\r\n")
    assert lines[0].split("\t")[0] == "Alloy" and len(lines) == 3
    from hea_calc.core.results import ModelFilter
    m.set_filters([ModelFilter("M6", {"SS"})])
    assert [r.name for r in m.view_rows] == ["CoCrFeNi"]
    m.set_filters([])
    m.set_keys(["name", "dhmix", "M1"])
    assert m.columnCount() == 3
    # the toolbar trash button is "Clear table": it empties the table whatever is selected,
    # resets the pagination, and leaves the composition alone
    win.table.view.selectRow(0)
    win.table.delete_btn.click()
    assert m.rows == []
    assert m.view_rows == [] and m.page == 0
    assert win.table.pagination.prev_btn.isEnabled() is False
    assert win.table.pagination.next_btn.isEnabled() is False
    assert win.details.row is None
    assert set(win.composition.single.rows) == {"Co", "Cr", "Fe", "Ni", "Al"}, \
        "the composition must not be cleared"
    assert win.table.empty.isVisible()


def test_import_and_export_through_ui(win, app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    src = tmp_path / "in.csv"
    src.write_text("Formula\nCoCrFeNi\nAl0.5CoCrFeNi\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(src), ""))
    win.import_compositions()
    wait_worker(win, app)
    assert [r.name for r in win.table.model.rows] == ["CoCrFeNi", "Al0.5CoCrFeNi"]
    out = tmp_path / "out.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    win.export("xlsx")
    assert out.exists() and out.stat().st_size > 0


def test_recalculate_all_uses_new_temperature(win, app):
    click_elements(win, "Co", "Cr", "Fe", "Ni")
    win.composition.calc_btn.click()
    click_elements(win, "Mn")
    win.composition.calc_btn.click()
    before = [r.result.temperature for r in win.table.model.rows]
    win.annealing = 1000.0
    win.recalculate_all()
    wait_worker(win, app)
    rows = win.table.model.rows
    assert [r.name for r in rows] == ["CoCrFeNi", "CoCrFeNiMn"]
    assert all(r.result.temperature == 1000.0 for r in rows) and before[0] != 1000.0
    assert all(r.source == "single" for r in rows)


def test_theme_switch(win, app):
    from hea_calc.ui.theme import THEME
    win.set_theme("light")
    # the sheet is scoped to the main window (see MainWindow.apply_theme), not to QApplication
    assert THEME.name == "light" and "#f4f4f4" in win.styleSheet()
    assert app.styleSheet() == "", "no application-wide sheet may be kept alive"
    win.set_theme("dark")
    assert THEME.name == "dark"


def test_element_order_survives_signals_and_overview(win):
    click_elements(win, "Cr", "Mn", "Fe", "Co", "Ni")
    win.composition.calc_btn.click()
    row = win.table.model.rows[-1]
    assert list(row.input_amounts) == ["Cr", "Mn", "Fe", "Co", "Ni"]
    assert list(row.result.composition) == ["Cr", "Mn", "Fe", "Co", "Ni"]
    from hea_calc.ui.analysis.widgets import DataTable
    page = win.analysis.composition.pages[0]
    table = page.findChildren(DataTable)[0]                      # Composition (normalised)
    assert [r[0].html for r in table.rows] == ["Cr", "Mn", "Fe", "Co", "Ni"]
    assert {r[1].html for r in table.rows} == {"20.00"} and {r[2].html for r in table.rows} == {"1.000"}


def test_overview_ratio_column(win):
    click_elements(win, "Al", "Co", "Cr", "Fe", "Ni")
    s = win.composition.single
    s.rows["Al"].fields["ratio"].setText("0.5")
    s._edited("Al", "ratio")
    win.composition.calc_btn.click()
    row = win.table.model.rows[-1]
    assert list(row.result.composition) == ["Al", "Co", "Cr", "Fe", "Ni"]


def test_button_sizes_follow_the_carbon_size_property(win, app):
    """md buttons are 40 px and sm buttons 32 px, per theme.BUTTON_HEIGHT / CONTROL_HEIGHT.

    Regression: the selector used to be the Qt property ``size``, which QWidget already declares
    as a read-only QSize, so ``setProperty("size", "md")`` failed silently and every md button
    rendered at the 32 px sm height.  The final Figma Composition setup footer is 40 px with md buttons
    (Calculate 141 × 40 + a 40 px chevron, flush with the panel edge), so this is measurable against the design.
    """
    from hea_calc.ui.theme import BUTTON_HEIGHT, CONTROL_HEIGHT
    from hea_calc.ui.widgets.common import button

    probe = button("Probe", "primary", "md", win)
    probe.show()
    app.processEvents()
    assert (probe.minimumHeight(), probe.maximumHeight()) == (BUTTON_HEIGHT, BUTTON_HEIGHT)
    for b in (win.composition.clear_btn, win.composition.calc_btn):
        assert b.property("btnsize") == "md", b
        assert (b.minimumHeight(), b.maximumHeight()) == (BUTTON_HEIGHT, BUTTON_HEIGHT), b
    b = win.table.export_btn
    # the Results toolbar is 40 px in the final Figma Data table (447:65142): Export is md, 123 x 40
    assert b.property("btnsize") == "md" and (b.minimumHeight(), b.maximumHeight()) == (BUTTON_HEIGHT, BUTTON_HEIGHT)
    assert CONTROL_HEIGHT == 32
    # the rendered footer matches the component: 40 px under a 1 px rule, Calculate 141 px wide
    app.processEvents()
    comp = win.composition
    assert comp.footer.height() == BUTTON_HEIGHT + 1 and comp.calc_btn.height() == BUTTON_HEIGHT
    assert comp.width() == 457 and comp.calc_btn.width() == 141
    right = comp.footer.calc.mapTo(comp, comp.footer.calc.rect().topRight()).x()
    assert right == comp.width() - 1
    assert comp.footer.mapTo(comp, comp.footer.rect().topLeft()).y() == 490 - 41      # Figma: rule at y 449


def test_empty_states_use_the_exported_illustrations(win, app):
    """The three empty states render the Figma artwork, at its exported size."""
    from hea_calc.ui.widgets.common import Illustration

    from PySide6.QtWidgets import QLabel

    for view, art in ((win.composition.single, "magnifier"), (win.composition.sweep, "magnifier")):
        found = view.empty.findChildren(Illustration)
        assert [i.name for i in found] == [art], view
    # Analysis: two variants of one artwork, driven by whether results exist (design guide frame 1 / 1b)
    page = win.analysis.composition.pages[0]
    names = [i.name for i in page.findChildren(Illustration)]
    assert names == ["document"], names
    texts = [lab.text() for lab in page.findChildren(QLabel)]
    assert "No results to analyse yet" in texts, texts
    click_elements(win, "Co", "Cr", "Fe", "Ni")
    win.composition.calc_btn.click()
    app.processEvents()
    assert win.table.model.rows
    # a row is shown, then it goes away while other results remain (Figma 289:44646)
    win._jump_to(0)
    app.processEvents()
    assert win.details.row is not None
    win.show_details(None)
    app.processEvents()
    page = win.analysis.composition.pages[0]
    texts = [lab.text() for lab in page.findChildren(QLabel) if lab.isVisibleTo(page)]
    assert "No composition selected" in texts, texts
    assert [i.name for i in page.findChildren(Illustration) if i.isVisibleTo(page)] == ["document"]


def test_data_table_row_and_header_colours(win, app):
    """Header, selected row and the 1 px row rules, per theme.

    Regression: `row-selected` was the same value as `header-row` in both themes, so the selected
    row was indistinguishable from the header, and the rules were drawn in `border-subtle-01`
    (#393939 on #262626), i.e. invisible.  Values are the ones measured in
    `19_data_table_populated.png` and specified for the light theme.
    """
    from hea_calc.ui.theme import DARK, LIGHT, THEME

    for theme, header, selected, rule in (("dark", "#393939", "#333333", "#525252"),
                                          ("light", "#e0e0e0", "#e8e8e8", "#e0e0e0")):
        THEME.set_theme(theme)
        app.processEvents()
        k = DARK if theme == "dark" else LIGHT
        assert k["header-row"] == header, (theme, k["header-row"])
        assert k["row-selected"] == selected, (theme, k["row-selected"])
        assert k["row-border"] == rule, (theme, k["row-border"])
        assert k["row-selected"] != k["header-row"], theme
    THEME.set_theme("dark")
    app.processEvents()


def test_text_input_box_includes_its_own_bottom_stroke(win, app):
    """A field is 32 px tall *including* the 1 px bottom stroke, and focus does not move the text.

    Regression: QSS min/max-height applies to the content box, so 32 px plus a 1 px
    `border-bottom` produced a 33 px field with the stroke hanging outside it.  Measured against
    `06_single_populated.png`: 31 px of field, then a 1 px #8d8d8d stroke = 32 px, then a 1 px gap.
    """
    from hea_calc.ui.theme import CONTROL_HEIGHT, FIELD_CONTENT_HEIGHT

    assert FIELD_CONTENT_HEIGHT == CONTROL_HEIGHT - 1
    click_elements(win, "Cr", "Mn", "Fe", "Co", "Ni")
    app.processEvents()
    row = win.composition.single.rows["Cr"]
    for key in ("ratio", "at", "wt", "mass"):
        edit = row.fields[key]
        assert edit.height() == CONTROL_HEIGHT, (key, edit.height())
        # the last row of the widget is the stroke, i.e. it is inside the box
        img = edit.grab().toImage()
        last = img.pixelColor(img.width() // 2, img.height() - 1)
        assert last.lightness() > 40, (key, last.name(), "no bottom stroke")

    edit = row.fields["ratio"]
    edit.clearFocus()
    app.processEvents()
    before = edit.cursorRect()
    edit.setFocus()
    app.processEvents()
    after = edit.cursorRect()
    assert (after.x(), after.y()) == (before.x(), before.y()), "the text must not move on focus"
    edit.clearFocus()


def test_focus_border_is_two_px_on_all_four_sides(win, app):
    """The focus ring is 2 px on every side - a bare `border: 2px` left the bottom at 1 px."""
    from hea_calc.ui.theme import LIGHT, THEME, t

    click_elements(win, "Cr", "Mn", "Fe", "Co", "Ni")
    app.processEvents()
    edit = win.composition.single.rows["Cr"].fields["ratio"]
    THEME.set_theme("light")
    app.processEvents()
    edit.setFocus()
    app.processEvents()
    img = edit.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    mid_x, mid_y = img.width() // 2, img.height() // 2
    blue = t("focus")
    # the ring is two pixels on every side; the interior starts at 2
    for y, side in ((0, "top"), (1, "top"), (img.height() - 2, "bottom"), (img.height() - 1, "bottom")):
        assert img.pixelColor(mid_x, y).name() == blue, (side, y, img.pixelColor(mid_x, y).name())
    for x, side in ((0, "left"), (1, "left"), (img.width() - 2, "right"), (img.width() - 1, "right")):
        assert img.pixelColor(x, mid_y).name() == blue, (side, x, img.pixelColor(x, mid_y).name())
    assert img.pixelColor(mid_x, 2).name() != blue, "the ring must be 2 px, not more"
    assert LIGHT["focus"] == "#0f62fe"
    THEME.set_theme("dark")
    app.processEvents()


def test_element_tiles_have_no_tooltip_and_the_right_selected_border(win, app):
    """No tile tooltip (the inspector reports the name on hover), and a theme-correct frame."""
    from hea_calc.ui.theme import DARK, LIGHT, THEME, t

    tiles = win.elements.table.tiles
    assert len(tiles) > 100
    assert all(t.toolTip() == "" for t in tiles.values()), "the tile tooltip duplicated the inspector"
    # the inspector still reports the element on hover - only the tooltip was removed
    win.elements.table.tiles["Cr"].enterEvent(None)
    app.processEvents()
    texts = [lab.text() for lab in win.elements.info.findChildren(QLabel)]
    assert any("Chromium" in t for t in texts), texts

    tile = tiles["Cr"]
    assert t("tile-selected-border") == DARK["tile-selected-border"] == "#f4f4f4"
    assert LIGHT["tile-selected-border"] == "#0f62fe"
    tile.setChecked(True)
    img = tile.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    assert img.pixelColor(0, 14).name() == "#" + DARK["tile-selected-border"].lstrip("#"), \
        "the selected frame is 2 px of tile-selected-border on the tile's left edge"
    THEME.set_theme("light")
    app.processEvents()
    img = tile.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    assert img.pixelColor(0, 14).name() == "#0f62fe", img.pixelColor(0, 14).name()
    THEME.set_theme("dark")
    app.processEvents()


def _one_result(win, app):
    """Toolbar actions are disabled on an empty table (Carbon disabled state); give it a result."""
    comp = {"Co": 1, "Ni": 1}
    win.calculate("single", ["CoNi"], [comp], [{}])
    app.processEvents()


def test_icon_only_buttons_centre_their_icon(win, app):
    """Every icon-only button centres its icon horizontally and vertically.

    Regression: the sheet's base `QPushButton` rule sets `text-align: left`, which Qt applies to a
    text-less button's icon too, so every IconButton drew its icon 8 px left of centre in a 32 x 32
    button (12.5 px in the 40 x 40 pagination buttons) - most obvious on hover.  IconButton now
    paints the icon itself.
    """
    from hea_calc.ui.widgets.common import IconButton  # noqa: E402

    _one_result(win, app)

    def hx(c):
        return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"

    def offset(btn):
        img = btn.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
        bg = hx(img.pixelColor(1, 1))
        pts = [(x, y) for y in range(img.height()) for x in range(img.width())
               if hx(img.pixelColor(x, y)) != bg]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return ((min(xs) + max(xs) + 1) / 2 - btn.width() / 2,
                (min(ys) + max(ys) + 1) / 2 - btn.height() / 2)

    buttons = [win.table.delete_btn, win.table.filter_btn, win.table.columns_btn,
               win.table.pagination.prev_btn, win.table.pagination.next_btn]
    buttons += win.findChildren(IconButton)
    assert len(buttons) >= 8, "the audit must cover every icon-only button"
    for b in buttons:
        dx, dy = offset(b)
        # a 1:1 bitmap of an odd-width glyph can only land on a half pixel
        assert abs(dx) <= 1.0 and abs(dy) <= 0.5, (b.toolTip(), dx, dy)

    # and on hover, which is when the misalignment was most visible
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent

    b = win.table.delete_btn
    app.sendEvent(b, QEnterEvent(QPointF(16, 16), QPointF(1, 1), QPointF(1, 1)))
    app.processEvents()
    img = b.grab().toImage().convertToFormat(QImage.Format_RGB32)
    assert hx(img.pixelColor(1, 1)) == "#333333", "hover surface"
    dx, dy = offset(b)
    assert abs(dx) <= 0.5 and abs(dy) <= 0.5, (dx, dy)


def test_composition_mode_is_the_heading_dropdown_not_a_switcher(win, app):
    """The final Figma Composition setup has no mode content switcher: the panel title is the mode dropdown."""
    comp = win.composition
    assert not hasattr(comp, "switcher")
    assert comp.heading.height() == 40 and comp.heading.x() == 0
    assert comp.heading.width() == 16 + comp.heading.text_width() + 8 + 16 + 16


def test_mode_single_icon_follows_the_icon_token(win):
    """The Single-composition icon carried `style="fill:#000000"`, which beat `currentColor`.

    Regression: it rendered black on the selected segment's #404040 surface, in both themes,
    because an inline `style` fill overrides the root's `fill="currentColor"`.
    """
    from hea_calc.ui import icons

    src = icons.svg_text("mode_single", "#f4f4f4")
    assert "style=" not in src, src[:120]
    assert 'fill="#f4f4f4"' in src
    for name in ("mode_single", "mode_sweep", "mode_expression"):
        assert "style=" not in icons.svg_text(name, "#f4f4f4"), name


def test_results_toolbar_has_no_copy_button(win):
    """Export's menu keeps the copy action; the redundant toolbar button is gone."""
    tb = win.table
    assert not hasattr(tb, "copy_btn"), "the icon-only Copy table button was removed"
    tips = [b.toolTip() for b in tb.findChildren(IconButton)]
    assert not any("copy" in t.lower() for t in tips), tips
    menu = tb.export_btn.menu()
    assert menu is not None
    labels = [a.text() for a in menu.actions() if a.text() and a.isVisible()]
    assert "Copy table to clipboard" in labels, labels
    # and the Edit menu offers it (Copy belongs to Edit - the window-chrome branch's grouping)
    edit_actions = [a.text() for a in win.edit_menu.actions()]
    assert "Copy table" in edit_actions, edit_actions


def test_export_button_label_and_chevron(win, app):
    """Label on the padding grid *and* the design's chevron, both measured in reference 21."""
    _one_result(win, app)
    b = win.table.export_btn
    assert (b.width(), b.height()) == (123, 40)                 # Figma Data table toolbar: 40 px
    img = b.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    bg = img.pixelColor(1, 16).name().lstrip("#").upper()
    pts = [(x, y) for y in range(img.height()) for x in range(img.width())
           if img.pixelColor(x, y).name().lstrip("#").upper() != bg
           and 0.299 * img.pixelColor(x, y).red() + 0.587 * img.pixelColor(x, y).green()
           + 0.114 * img.pixelColor(x, y).blue() > 150]
    cols = sorted({p[0] for p in pts})
    groups, start, prev = [], None, None
    for x in cols:
        if start is None:
            start = prev = x
        elif x - prev <= 4:
            prev = x
        else:
            groups.append((start, prev))
            start = prev = x
    groups.append((start, prev))
    assert len(groups) == 2, groups
    label, chevron = groups
    assert label[0] == 17, f"label starts at {label[0]}, reference 17"
    assert chevron == (94, 103), f"chevron ink {chevron}, reference (94, 103)"
    assert img.width() - 1 - chevron[1] == 19, "chevron right gap, reference 19"


def test_carbon_tooltip_matches_the_component_reference(win, app):
    """Background, text, size, caret and placement, against reference 21 and the Carbon spec.

    Reference 21 ("Composition space"): body 155 x 24, caret 12 px wide at the base and 6 px tall
    (Carbon popover-caret), tip 4 px above the trigger ($spacing-02).
    """
    from hea_calc.ui.theme import TOOLTIP_RADIUS
    from hea_calc.ui.widgets.common import CarbonToolTip

    tip = CarbonToolTip()
    screen = QRect(0, 0, 1920, 1032)      # the desktop the reference was exported from
    anchor = QRect(1680, 600, 32, 32)    # the reference's trash button sits at x 1681
    tip.show_for(anchor, "Clear table", screen)
    app.processEvents()
    assert (tip.width(), tip.height()) == (102, 24 + 6), (tip.width(), tip.height())
    assert tip.RADIUS == TOOLTIP_RADIUS == 2      # tooltip/toggletip exception to the 7 px radius
    img = tip.grab().toImage().convertToFormat(QImage.Format_RGB32)
    assert img.pixelColor(20, 12).name().lstrip("#").upper() == "F4F4F4"
    ink = [img.pixelColor(x, y).red() for y in range(3, 20) for x in range(3, 90)]
    assert min(ink) < 60, "dark text on the inverse surface"
    # the caret: 12 px at its base, narrowing over 6 rows
    def bright(y):
        return sum(1 for x in range(tip.width()) if img.pixelColor(x, y).red() > 200)
    assert 10 <= bright(24) <= 13, bright(24)
    assert bright(24) > bright(27) > bright(29) >= 0
    # placement: caret on the anchor's centre, tip 4 px above the anchor, body hanging left
    assert tip._caret, "the caret is drawn when the tip can reach the anchor"
    assert tip.x() + tip._caret_x == anchor.center().x() + 1 or tip.x() + tip._caret_x == anchor.center().x()
    assert anchor.top() - (tip.y() + tip.height()) == tip.GAP == 4
    assert tip.x() + tip.width() - 1 <= screen.right(), "stays on the screen"

    tip.show_for(QRect(940, 600, 32, 32), "Composition space", screen)
    app.processEvents()
    assert (tip.width(), tip.height()) == (154, 30), (tip.width(), tip.height())
    tip.hide()


def test_no_button_in_the_toolbars_carries_its_own_stylesheet(win):
    """A widget-level sheet stops it inheriting the theme rules - the Export padding bug."""
    for other in (win.table.delete_btn, win.table.filter_btn,
                  win.table.columns_btn, win.table.pagination.prev_btn,
                  win.table.pagination.next_btn):
        assert other.styleSheet() == "", other


def test_install_tooltips_is_idempotent(win, app):
    from hea_calc.ui.widgets.common import install_tooltips

    install_tooltips(app)
    install_tooltips(app)
    assert win.table.delete_btn.toolTip() == "Clear table"


def test_illustrations_are_cached_and_sized_from_the_svg(win):
    """The artwork renders once, at its exported size, and a theme switch must not recolour it."""
    from hea_calc.ui.theme import THEME
    from hea_calc.ui.widgets.common import illustration

    for name, w, h in (("magnifier", 80, 80), ("document", 55, 81), ("box", 80, 97)):
        size, pm = illustration(name)
        assert (size.width(), size.height()) == (w, h), (name, size)
        assert (pm.width(), pm.height()) == (w, h), name
    # the artwork's colours are exported for both themes: switching must not change a single pixel
    before = illustration("magnifier")[1].toImage()
    THEME.set_theme("light")
    after = illustration("magnifier")[1].toImage()
    assert before == after, "the illustration must be identical in both themes"
    assert illustration("box")[1] is illustration("box")[1], "cached, not re-rendered"
    THEME.set_theme("dark")
