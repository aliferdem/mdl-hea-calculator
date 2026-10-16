"""Release reconciliation UI regressions (offscreen): resize without transient windows, shared interactions,
preferences and the redesigned shell.  See design/implementation/release_validation.md."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QObject, QSettings, Qt
from PySide6.QtWidgets import QApplication, QWidget

from hea_calc.core.analysis import samples
from hea_calc.core.analysis import state as S
from hea_calc.core.composition import alloy_name

CANTOR = {"Co": 0.2, "Cr": 0.2, "Fe": 0.2, "Mn": 0.2, "Ni": 0.2}


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    from hea_calc.ui.widgets.tooltip import install_tooltips
    load_fonts()
    install_tooltips(a)
    return a


def pump(app, n: int = 3):
    for _ in range(n):
        app.processEvents()


def settle(win, app):
    for _ in range(6):
        win.analysis_ctl.wait_idle(20)
        pump(app)


def new_settings() -> QSettings:
    return QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)


@pytest.fixture()
def settings():
    return new_settings()


@pytest.fixture()
def win(app, settings):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
    w = MainWindow(settings=settings)
    w.resize(1920, 1000)
    w.show()
    pump(app)
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


def calc_single(win, app, comp):
    win.calculate("single", [alloy_name(comp)], [comp], [{}])
    pump(app)


class _WindowSpy(QObject):
    """Counts widgets shown as top-level windows (other than ``exclude``)."""

    def __init__(self, exclude):
        super().__init__()
        self.exclude = exclude
        self.shown: list[str] = []

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() and obj is not self.exclude:
            self.shown.append(type(obj).__name__)
        return False


def test_resize_across_breakpoint_creates_no_top_level_windows(win, app):
    calc_single(win, app, CANTOR)
    run = samples.store_recipe(win.repo, win.engine, samples.cantor_family_recipe()) \
        if hasattr(samples, "cantor_family_recipe") else None
    win.table.model.refresh_committed()
    if run is not None:
        win.analysis_ctl.run_finished(run)
    settle(win, app)
    comp_width = win.composition.width()
    for ctx in (S.COMPOSITION, S.COLLECTION):
        win.analysis_ctl.apply(S.switch_context, ctx)
        settle(win, app)
        visible_before = len([w for w in app.topLevelWidgets() if w.isVisible()])
        spy = _WindowSpy(win)
        app.installEventFilter(spy)
        try:
            stacked_seen = wide_seen = False
            for wd in list(range(1920, 1100, -20)) + list(range(1100, 1921, 20)):
                win.resize(wd, 1000)
                pump(app, 1)
                stacked_seen |= win.top_row.stacked
                wide_seen |= not win.top_row.stacked
                assert len([w for w in app.topLevelWidgets() if w.isVisible()]) <= visible_before
            settle(win, app)
        finally:
            app.removeEventFilter(spy)
        assert stacked_seen and wide_seen
        assert spy.shown == [], f"transient windows: {spy.shown}"
    assert win.composition.width() == comp_width                 # Composition setup never compresses


# ====================================================================== Composition setup
def click_elements(win, *els):
    for el in els:
        win.elements.table.tiles[el].click()
    QApplication.processEvents()


def test_composition_setup_titles_follow_the_mode_and_geometry_is_fixed(win, app):
    comp = win.composition
    geo = comp.geometry()
    titles = []
    for i in range(3):
        comp.set_mode(i)
        app.processEvents()
        titles.append(comp.title.text())
        assert comp.geometry() == geo, "the title never moves the panel"
    assert titles == ["Single composition", "Composition space", "Composition expression"]
    assert comp.width() == 457 and comp.footer.height() == 32


def test_errors_are_explained_in_the_footer(win, app):
    comp = win.composition
    click_elements(win, "Fe", "Ni")
    s = comp.single
    s.rows["Fe"].fields["ratio"].setText("x")
    s._edited("Fe", "ratio")
    st = comp.footer.status.status
    assert st.kind == "error" and s.rows["Fe"].fields["ratio"].property("invalid")
    assert not s.rows["Fe"].fields["ratio"].toolTip(), "the explanation is in the footer, not a field tooltip"
    footer_geo = comp.footer.geometry()
    s.rows["Fe"].fields["ratio"].setText("1")
    s._edited("Fe", "ratio")
    assert comp.footer.status.status is None and comp.footer.geometry() == footer_geo


def test_space_supports_wt_and_mass_bases_and_editable_symbols(win, app):
    from conftest import settle_composition
    comp = win.composition
    click_elements(win, "Fe", "Ni", "Cr")
    comp.set_mode(1)
    assert [v for v, _t in comp.unit_box.items] == ["ratio", "at", "wt", "mass"]
    sw = comp.sweep
    for unit in ("wt", "mass"):
        comp.unit_box.set_value(unit, emit=True)
        assert sw.unit == unit
        settle_composition(win, app)
        assert sw.summary_data is not None and sw.summary_data.compositions > 0, unit
        recipe = sw.recipe()
        assert recipe.unit == unit
    # editable element symbol: same rule as Single composition
    row = sw.rows["Ni"]
    row.el.setText("co")
    row.el.editingFinished.emit()
    app.processEvents()
    assert list(sw.rows) == ["Fe", "Co", "Cr"] and set(win.elements.table.selected()) == {"Fe", "Co", "Cr"}
    assert list(comp.single.rows) == ["Fe", "Co", "Cr"]
    row = sw.rows["Co"]
    row.el.setText("Fe")                                   # duplicate
    row.el.editingFinished.emit()
    st = comp.footer.status.status
    assert st.kind == "error" and "already" in st.text and not comp.calc_btn.isEnabled()
    row.el.setText("Xq")                                   # invalid symbol
    row.el.editingFinished.emit()
    assert "not an element" in comp.footer.status.status.text


def test_partial_model_coverage_is_a_footer_warning(win, app):
    click_elements(win, "Al", "Co", "Cr", "Fe", "Ni", "Si")
    st = win.composition.footer.status.status
    assert st.kind == "warning" and st.text == "Partial model coverage"
    assert "M6" in st.info[0] and "M7" in st.info[0] and "Si" in st.info[0]


# ====================================================================== total mass / Mass column
def test_total_mass_persists_and_drives_the_mass_column_only(app, settings):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.analysis.widgets import DataTable
    w = MainWindow(settings=settings)
    w.resize(1920, 1000)
    w.show()
    pump(app)
    try:
        assert w.prefs.total_mass == 2.0
        f = w.composition.single.totals["mass"]
        click_elements(w, "Co", "Cr", "Fe", "Mn", "Ni")
        f.setText("5")
        f.editingFinished.emit()
        assert w.prefs.total_mass == 5.0
        w.calculate("single", [alloy_name(CANTOR)], [CANTOR], [{}])
        settle(w, app)
        before = dict(w.analysis_ctl.row.result.descriptors)
        table = w.analysis.composition.pages[0].findChildren(DataTable)[0]
        assert table.columns[-1][0] == "Mass (5 g batch)"
        masses = [float(r[-1].html) for r in table.rows]
        assert sum(masses) == pytest.approx(5.0, abs=5e-4)
        w.prefs.set_total_mass(2)
        pump(app)
        table = w.analysis.composition.pages[0].findChildren(DataTable)[0]
        assert table.columns[-1][0] == "Mass (2 g batch)"
        assert sum(float(r[-1].html) for r in table.rows) == pytest.approx(2.0, abs=5e-4)
        assert w.analysis_ctl.row.result.descriptors == before, "no recalculation, no changed value"
    finally:
        w.close()
    # restart: the preference is restored
    w2 = MainWindow(settings=settings)
    try:
        assert w2.prefs.total_mass == 2.0 and w2.composition.single.total_mass == 2.0
    finally:
        w2.close()


def test_mass_column_for_space_and_expression_results(win, app):
    from hea_calc.ui.analysis.widgets import DataTable
    win.prefs.set_total_mass(3)
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    win.table.model.refresh_committed()
    win.analysis_ctl.run_finished(run)
    win._check_details()
    win.show_details(win.repo.get_result(win.table.model.id_at(0)))
    settle(win, app)
    table = win.analysis.composition.pages[0].findChildren(DataTable)[0]
    assert table.columns[-1][0] == "Mass (3 g batch)"
    assert sum(float(r[-1].html) for r in table.rows) == pytest.approx(3.0, abs=5e-4)
    run2 = samples.store_recipe(win.repo, win.engine, samples.e1_recipe())
    win.table.model.refresh_committed()
    win.analysis_ctl.run_finished(run2)
    rec = win.repo.get_run(run2)
    win.show_details(win.repo.get_result(rec.first_id))
    settle(win, app)
    table = win.analysis.composition.pages[0].findChildren(DataTable)[0]
    assert table.columns[-1][0] == "Mass (3 g batch)"


# ====================================================================== Analysis tabs / statistics
def test_last_analysis_tabs_are_remembered(app, settings):
    from hea_calc.ui.main_window import MainWindow
    w = MainWindow(settings=settings)
    try:
        c = w.analysis_ctl
        c.apply(S.set_tab, "models")
        c.apply(S.select_model, "M6")
        c.apply(S.switch_context, S.COLLECTION)
        c.apply(S.set_tab, "statistics")
        c.apply(S.switch_context, S.COMPOSITION)
        w.calculate("single", [alloy_name(CANTOR)], [CANTOR], [{}])
        pump(app)
        assert c.state.comp_tab == "models", "a new active composition keeps the user's tab"
    finally:
        w.close()
    w2 = MainWindow(settings=settings)
    try:
        st = w2.analysis_ctl.state
        assert (st.comp_tab, st.coll_tab, st.model) == ("models", "statistics", "M6")
    finally:
        w2.close()


def test_statistics_are_descriptor_generic_and_delta_is_not_privileged(win, app):
    from hea_calc.core.analysis.metrics import DESCRIPTORS, METRIC_KEYS, STATS_DEFAULT
    assert S.AnalysisState().stats_focus == ""
    assert {"dhmix", "delta", "delta_cn12", "vec", "density", "phi_king", "mean_mass"} <= set(METRIC_KEYS)
    assert "delta" in STATS_DEFAULT and "delta_cn12" in STATS_DEFAULT
    assert DESCRIPTORS["delta"].name == "Size mismatch — Guo & Liu radii"
    assert DESCRIPTORS["delta_cn12"].name == "Size mismatch — Kittel CN12 radii"
    run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
    win.table.model.refresh_committed()
    win.analysis_ctl.run_finished(run)
    win._check_details()
    c = win.analysis_ctl
    c.apply(S.switch_context, S.COLLECTION)
    settle(win, app)
    c.scope_for(run, "full")
    c.apply(S.update, stats_metrics=("dhmix", "delta", "delta_cn12", "vec", "density", "phi_king"))
    c.apply(S.set_tab, "statistics")
    settle(win, app)
    stats = c.data["stats"]["metrics"]
    for k in ("dhmix", "delta", "delta_cn12", "vec", "density", "phi_king"):
        assert stats[k]["n_valid"] + stats[k]["n_missing"] == c.state.resolved.n, k
    assert stats["delta"]["median"] != stats["delta_cn12"]["median"], "two different quantities"
    win.set_expanded(True)
    settle(win, app)
    for metric in ("density", "delta_cn12"):
        c.apply(S.update, stats_focus=metric)
        settle(win, app)
        assert metric in c.data["box"]["metrics"] and c.data["hist"]["n_valid"] > 0
    win.set_expanded(False)


# ====================================================================== shared controls
def test_closed_dropdowns_ignore_the_wheel_and_keep_their_text_origin(win, app):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from hea_calc.ui.widgets.dropdown import Dropdown
    dds = [d for d in win.findChildren(Dropdown) if d.isVisible()]
    assert dds, "the table's items-per-page select is a shared Dropdown"
    for d in dds:
        before = d.value
        ev = QWheelEvent(QPointF(5, 5), QPointF(d.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(d, ev)
        assert d.value == before and not ev.isAccepted(), "the page scrolls, the value stays"
    # text origin: identical pixels left of the chevron in rest / hover / focus / open-styled states
    d = dds[0]

    def grab():
        from PySide6.QtGui import QColor, QImage, QPainter, QRegion
        from PySide6.QtCore import QPoint
        img = QImage(d.width() - 40, d.height(), QImage.Format.Format_ARGB32)
        img.fill(QColor("#262626"))                     # the panel surface under the transparent (inline) field
        p = QPainter(img)
        d.render(p, QPoint(0, 0), QRegion(0, 0, d.width() - 40, d.height()), QWidget.RenderFlag.DrawChildren)
        p.end()
        return img
    rest = grab()
    d._hover = True
    hover = grab()
    d._hover = False
    d._open = True
    opened = grab()
    d._open = False
    def text_cols(img):
        cols = []
        for x in range(img.width()):
            if any(img.pixelColor(x, y).lightness() > 150 for y in range(4, img.height() - 4)):
                cols.append(x)
        return cols[:3]
    assert text_cols(rest) == text_cols(hover) == text_cols(opened)


def test_results_pagination_has_an_editable_page_field(win, app):
    from hea_calc.ui.widgets.results_table import PageField
    pag = win.table.pagination
    assert isinstance(pag.page_field, PageField)
    assert not pag.page_field.isEnabled() and pag.page_field.text() == "1", "empty table: page 1, disabled"
    for i in range(25):
        win.calculate("single", [f"A{i}"], [{"Fe": 1 + i, "Ni": 1}], [{}])
    pag.size_box.set_value(10, emit=True)
    pump(app)
    assert win.table.model.page_count() == 3 and pag.page_field.isEnabled()
    pag.page_field.setText("3")
    pag.page_field.returnPressed.emit()
    assert win.table.model.page == 2
    pag.page_field.setText("0")
    pag.page_field.returnPressed.emit()
    assert win.table.model.page == 0 and pag.page_field.text() == "1"


def test_theme_preference_system_light_dark(app, settings):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui import system_theme
    from hea_calc.ui.theme import THEME
    assert system_theme.resolve("system", "light") == "light"
    assert system_theme.resolve("system", "dark") == "dark"
    assert system_theme.resolve("light", "dark") == "light" and system_theme.resolve("dark", "light") == "dark"
    w = MainWindow(settings=settings)
    try:
        labels = [a.text() for a in w.theme_menu.actions() if not a.isSeparator()]
        assert labels == ["System default", "Light", "Dark"]
        w.set_theme("system")
        assert w.prefs.theme == "system"
        w._os_scheme_changed("light")
        assert THEME.name == "light" and w.prefs.theme == "system", "the preference is not overwritten"
        w._os_scheme_changed("dark")
        assert THEME.name == "dark"
        w.set_theme("light")
        w._os_scheme_changed("dark")
        assert THEME.name == "light", "an explicit choice ignores the OS"
        assert [a.data() for a in w.theme_actions.actions() if a.isChecked()] == ["light"]
        assert not any("heme" in a.text() for a in w.file_menu.actions()), "no duplicate theme command in File"
    finally:
        THEME.set_theme("dark")
        w.close()


def test_native_titlebar_attributes_follow_the_tokens():
    from hea_calc.ui import win_titlebar as WT
    from hea_calc.ui.theme import DARK, LIGHT
    assert WT.colorref("#161616") == 0x161616 and WT.colorref("#f4f4f4") == 0xF4F4F4
    assert WT.colorref("#0f62fe") == 0xFE620F
    dark = dict(WT.caption_attributes("dark", DARK, 22631))
    assert dark[WT.DWMWA_USE_IMMERSIVE_DARK_MODE] == 1
    assert dark[WT.DWMWA_CAPTION_COLOR] == WT.colorref(DARK["background"])
    assert dark[WT.DWMWA_TEXT_COLOR] == WT.colorref(DARK["text-primary"])
    light = dict(WT.caption_attributes("light", LIGHT, 22631))
    assert light[WT.DWMWA_USE_IMMERSIVE_DARK_MODE] == 0 and light[WT.DWMWA_CAPTION_COLOR] == 0xF4F4F4
    win10 = dict(WT.caption_attributes("dark", DARK, 19045))
    assert WT.DWMWA_CAPTION_COLOR not in win10 and win10[WT.DWMWA_USE_IMMERSIVE_DARK_MODE] == 1
    assert dict(WT.caption_attributes("dark", DARK, 17763)) == {WT.DWMWA_USE_IMMERSIVE_DARK_MODE_OLD: 1}


def test_header_progress_keeps_the_header_geometry(win, app):
    hdr = win.header
    geo = (hdr.height(), hdr.progress.geometry(), hdr.help_btn.geometry(), hdr.theme_btn.geometry())
    hdr.progress.set_progress("Calculating", 0, 0, None)
    hdr.progress.show()
    pump(app)
    hdr.progress.set_progress("Calculating", 24_990, 99_961, 120.0)
    pump(app)
    assert hdr.progress.label.text() == "Calculating…25%"
    assert hdr.progress.detail.text() == "(24,990/99,961) 2 minutes remaining"
    assert (hdr.height(), hdr.progress.geometry(), hdr.help_btn.geometry(), hdr.theme_btn.geometry()) == geo
    hdr.progress.hide()
    pump(app)
    assert (hdr.height(), hdr.progress.geometry()) == geo[:2]
    assert hdr.help_btn.toolTip() and hdr.theme_btn.toolTip() and not hdr.help_btn.text()
    assert hdr.help_btn.x() > hdr.width() - 2 * 48 - 1, "Help and Theme are the far-right header actions"


def test_scrollbar_thumbs_are_pills():
    from PySide6.QtGui import QColor, QImage, QPainter
    from hea_calc.ui import crisp
    img = QImage(12, 40, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    from PySide6.QtCore import QRectF
    crisp.fill_pill(p, QRectF(4, 0, 4, 40), "#ffffff")
    p.end()
    assert img.pixelColor(5, 20).alpha() == 255
    assert img.pixelColor(4, 0).alpha() < 200, "the end of the thumb is rounded, not square"
