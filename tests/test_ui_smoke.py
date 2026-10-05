"""UI workflow smoke tests (offscreen). They drive the real widgets end-to-end."""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


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


def test_set_equal_and_normalize(win):
    click_elements(win, "Fe", "Co", "Ni", "Cr")
    s = win.composition.single
    s.radio_group.button(2).click()  # at.%
    win.composition.equal_btn.click()
    assert all(v == pytest.approx(25.0) for v in s.values.values())
    s.rows["Fe"].fields["at"].setText("50")
    s._edited("Fe", "at")
    assert win.composition.normalize_btn.isEnabled()
    win.composition.normalize_btn.click()
    assert sum(s.values.values()) == pytest.approx(100.0)
    assert s.values["Fe"] == pytest.approx(50 / 125 * 100)
    s.radio_group.button(1).click()  # ratio: normalize disabled
    assert not win.composition.normalize_btn.isEnabled()
    s.radio_group.button(0).click()  # element column: set equal disabled
    assert not win.composition.equal_btn.isEnabled()


def test_invalid_input_blocks_calculation(win):
    click_elements(win, "Fe", "Ni")
    s = win.composition.single
    s.rows["Fe"].fields["ratio"].setText("abc")
    s._edited("Fe", "ratio")
    assert s.rows["Fe"].fields["ratio"].property("invalid")
    n = len(win.table.model.rows)
    win.composition.calc_btn.click()
    assert len(win.table.model.rows) == n
    assert win.notification.isVisible()


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
    assert win.details.row is row
    assert row.result.descriptors["dhmix"] == pytest.approx(-3.75)


def test_sweep_and_pagination(win, app):
    click_elements(win, "Al", "Ti", "V")
    win.composition.set_mode(1)
    sw = win.composition.sweep
    win.composition.unit_box.setCurrentIndex(1)  # at.%
    for row in sw.rows.values():
        row.min.setText("0")
        row.max.setText("100")
        row.step.setText("10")
    sw.all_lock.click()  # unlock all -> optional elements: binaries and the ternary
    assert not any(r.lock.isChecked() for r in sw.rows.values())
    sw._update_summary()
    assert sw.summary_data.systems == 4 and sw.summary_data.compositions == 63  # 3 x 9 binaries + 36 ternaries
    win.composition.calc_btn.click()
    wait_worker(win, app)
    m = win.table.model
    assert len(m.rows) == 63 and all(r.result.ok for r in m.rows)
    win.table.pagination.size_box.setCurrentIndex(0)  # 10 per page
    assert m.page_size == 10 and m.page_count() == 7
    win.table.pagination.next_btn.click()
    assert m.page == 1 and len(m.page_rows()) == 10
    win.table.pagination.page_box.activated.emit(m.page_count() - 1)
    assert len(m.page_rows()) == 3


def test_sweep_ratio_space_figma_example(win):
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
    s = sw.summary_data
    assert (s.selected, s.required, s.optional, s.systems, s.compositions) == (5, 5, 0, 1, 6655)
    assert "6,655 valid compositions" in sw.summary.text()
    sw.all_max.setText("1.0")
    sw.all_max.editingFinished.emit()
    assert all(r.max.text() == "1.0" for r in sw.rows.values())


def test_expression_mode(win, app):
    win.composition.set_mode(2)
    e = win.composition.expr
    assert not win.composition.calc_btn.isEnabled()
    e.edit.setPlainText("(FeCoNi)1-xAlx")
    assert e.parse()
    assert set(win.elements.table.selected()) == {"Fe", "Co", "Ni", "Al"}
    row = e.var_rows["x"]
    row.min.setText("0")
    row.max.setText("0.5")
    row.step.setText("0.1")
    assert win.composition.calc_btn.isEnabled()
    win.composition.calc_btn.click()
    wait_worker(win, app)
    names = [r.name for r in win.table.model.rows]
    assert names[0] == "FeCoNi" and "(FeCoNi)0.9Al0.1" in names and len(names) == 6
    assert win.table.model.rows[1].variables == {"x": 0.1}
    win.composition.copy_btn.click()
    text = QApplication.clipboard().text()
    assert text.startswith("Alloy\tFe (at.%)") and len(text.strip().split("\r\n")) == 7


def test_expression_blocks_in_ui(win, app):
    win.composition.set_mode(2)
    e = win.composition.expr
    e.edit.setPlainText("CoCrFeNi\n\nAl{x}CoCrFeNi")
    assert e.parse()
    e.var_rows["x"].min.setText("0.5")
    e.var_rows["x"].max.setText("1")
    e.var_rows["x"].step.setText("0.5")
    win.composition.calc_btn.click()
    wait_worker(win, app)
    assert [r.name for r in win.table.model.rows] == ["CoCrFeNi", "Al0.5CoCrFeNi", "AlCoCrFeNi"]
    e.edit.setPlainText("FeCo\n\nXq")
    assert not e.parse() and e.edit.property("invalid")


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
    win.table.view.selectRow(0)
    win.delete_rows()
    assert [r.name for r in m.rows] == ["CoCrFeNiAl"]  # selection order
    assert win.details.row is None


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
    assert THEME.name == "light" and "#f4f4f4" in app.styleSheet()
    win.set_theme("dark")
    assert THEME.name == "dark"


def test_element_order_survives_signals_and_overview(win):
    click_elements(win, "Cr", "Mn", "Fe", "Co", "Ni")
    win.composition.calc_btn.click()
    row = win.table.model.rows[-1]
    assert list(row.input_amounts) == ["Cr", "Mn", "Fe", "Co", "Ni"]
    assert list(row.result.composition) == ["Cr", "Mn", "Fe", "Co", "Ni"]
    from PySide6.QtWidgets import QLabel
    page = win.details.pages[0].widget()
    texts = [lab.text() for lab in page.findChildren(QLabel)]
    assert "20.0000" in texts and "1.0000" in texts and "0.2000" not in texts  # at.% and ratio columns


def test_overview_ratio_column(win):
    click_elements(win, "Al", "Co", "Cr", "Fe", "Ni")
    s = win.composition.single
    s.rows["Al"].fields["ratio"].setText("0.5")
    s._edited("Al", "ratio")
    win.composition.calc_btn.click()
    row = win.table.model.rows[-1]
    assert list(row.result.composition) == ["Al", "Co", "Cr", "Fe", "Ni"]
