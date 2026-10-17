"""Analysis UI (offscreen): embedded shell and size classes, Composition / Collection state, checked results,
stale collections, plot types, the in-window workspace and focus restoration, report export."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from hea_calc.core.analysis import samples
from hea_calc.core.analysis import state as S
from hea_calc.core.analysis.plotting import (BAR_GROUPED, BAR_STACKED, BINNED, BOX, HEATMAP, HISTOGRAM, LINE,
                                             SAMPLED, SCATTER)
from hea_calc.core.composition import alloy_name
from hea_calc.core.results import ModelFilter


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


@pytest.fixture()
def win(app):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
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


def calc_single(win, app, comp):
    win.calculate("single", [alloy_name(comp)], [comp], [{}])
    pump(app)


def add_run(win, app, recipe):
    run = samples.store_recipe(win.repo, win.engine, recipe)
    win.table.model.refresh_committed()
    win.analysis_ctl.run_finished(run)
    win._check_details()
    pump(app)
    return run


def collection(win, app, run, tab="overview"):
    c = win.analysis_ctl
    c.apply(S.switch_context, S.COLLECTION)
    settle(win, app)
    c.scope_for(run, "full")
    settle(win, app)
    c.apply(S.set_tab, tab)
    settle(win, app)


# ====================================================================== embedded shell
def test_embedded_geometry_and_regions(win, app):
    p = win.analysis
    assert (p.width(), p.height()) == (805, 465) and p.size_class == "M"
    assert p.switcher.width() == 224 and p.switcher.height() == 32
    assert p.context_stack.height() == 40 and p.tab_stack.height() == 32
    head_bottom = p.switcher.mapTo(p, QPoint(0, 0)).y() + 32
    assert head_bottom <= 56
    assert p.tab_stack.mapTo(p, QPoint(0, 0)).y() == 96, "header 56 + context bar 40"
    assert p.content_stack.mapTo(p, QPoint(0, 0)).y() == 128


def test_empty_states_and_disabled_controls(win, app):
    p = win.analysis
    assert not p.expand_btn.isEnabled() and not p.overflow_btn.isEnabled()
    assert "available after a calculation" in p.expand_btn.toolTip()
    calc_single(win, app, samples.S1)
    assert p.expand_btn.isEnabled() and p.row is not None
    win.show_details(None)
    pump(app)
    assert p.row is None and p.expand_btn.isEnabled()


@pytest.mark.parametrize("width, cls", [(454, "S"), (719, "S"), (720, "M"), (805, "M"), (1039, "M"), (1040, "L")])
def test_size_classes_reflow_without_scaling(app, width, cls):
    from hea_calc.ui.analysis.controller import AnalysisController
    from hea_calc.ui.analysis.panel import AnalysisPanel, size_class_for
    assert size_class_for(width) == cls
    from hea_calc.core.engine import default_engine
    from hea_calc.core.repository import ResultRepository
    repo = ResultRepository(default_engine(), root=Path(tempfile.mkdtemp()))
    try:
        c = AnalysisController(repo)
        p = AnalysisPanel(c)
        p.resize(width, 465)
        p.show()
        pump(app)
        assert p.size_class == cls
        assert p.composition.size_class == cls and p.collection.size_class == cls
        for tabs in (p.comp_tabs, p.coll_tabs):
            last = tabs.buttons[-1]
            assert last.x() + last.width() <= tabs.width(), "tab labels never truncated"
        f = p.title.font()
        assert f.pixelSize() in (-1, 16) or f.pointSizeF() > 0          # typography is not scaled
        p.close()
        c.close()
    finally:
        repo.close()


def test_composition_tabs_and_model_drill_in(win, app):
    calc_single(win, app, samples.S3)
    c = win.analysis_ctl
    assert c.state.context == S.COMPOSITION and c.state.active is not None
    for tab in S.COMP_TABS:
        c.apply(S.set_tab, tab)
        pump(app)
        assert win.analysis.composition.currentIndex() == S.COMP_TABS.index(tab)
    c.apply(S.set_tab, "models")
    pump(app)
    from hea_calc.ui.analysis.widgets import DataTable
    table = win.analysis.composition.pages[2].findChildren(DataTable)[0]
    assert len(table.rows) == 8
    # 805 px merges prediction and status into one column; read the status from whichever cell carries it
    statuses = [next((getattr(c, "status", None) for c in r if getattr(c, "status", None)), None) for r in table.rows]
    assert statuses[5] == statuses[6] == "data_suspect"           # M6, M7 flagged binary data
    assert table.rows[5][1].tag == "IM", "verdict tag keeps its class colour"
    table.activated.emit(5)
    pump(app)
    assert c.state.comp_tab == "model_details" and c.state.model == "M6"


def test_partial_coverage_and_extrapolated_states(win, app):
    calc_single(win, app, samples.S2)
    res = win.analysis.row.result
    assert res.models["M6"].label == "N/A" and res.models["M6"].na_kind == "missing_data"
    calc_single(win, app, samples.S4)
    assert win.analysis.row.result.models["M7"].status == "extrapolated"
    win.analysis_ctl.apply(S.set_tab, "model_details")
    win.analysis_ctl.apply(S.select_model, "M7")
    pump(app)
    from hea_calc.ui.analysis.widgets import ActionableNotification
    notes = [n for n in win.analysis.composition.pages[3].findChildren(ActionableNotification) if n.isVisibleTo(win)]
    assert notes and "Extrapolated" in notes[0].title.text()


# ====================================================================== context state
def test_context_switch_preserves_both_states(win, app):
    calc_single(win, app, samples.S1)
    run = add_run(win, app, samples.c1_recipe())
    c = win.analysis_ctl
    c.apply(S.set_tab, "model_details")
    c.apply(S.select_model, "M8")
    collection(win, app, run, "plots")
    from hea_calc.core.analysis.plotting import PlotConfiguration
    cfg = PlotConfiguration(SCATTER, "vec", "omega", "model:M5")
    c.apply(S.set_plot, cfg)
    settle(win, app)
    c.apply(S.switch_context, S.COMPOSITION)
    pump(app)
    assert (c.state.comp_tab, c.state.model) == ("model_details", "M8")
    c.apply(S.switch_context, S.COLLECTION)
    pump(app)
    assert c.state.coll_tab == "plots" and c.state.plot == cfg and c.state.scope.run_id == run


def test_single_click_never_activates_double_click_does(win, app):
    add_run(win, app, samples.e1_recipe())
    v, m = win.table.view, win.table.model
    pos = v.visualRect(m.index(1, 1)).center()

    def send(kind):
        vp = v.viewport()
        QApplication.sendEvent(vp, QMouseEvent(kind, QPointF(pos), QPointF(vp.mapToGlobal(pos)),
                                               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                               Qt.KeyboardModifier.NoModifier))
    send(QEvent.Type.MouseButtonPress)
    send(QEvent.Type.MouseButtonRelease)
    pump(app)
    assert win.analysis_ctl.state.active is None
    assert not v.selectionModel().hasSelection()
    send(QEvent.Type.MouseButtonDblClick)
    pump(app)
    assert win.analysis_ctl.state.active == m.id_at(1)


# ====================================================================== table (no checkbox column) + scopes
def test_results_table_has_no_checkbox_column_and_full_or_filtered_scopes(win, app):
    """Release reconciliation: the checkbox column is gone - no vertical header, the first column starts at the
    table's left edge, the row menu has no check action - and Collection offers Full / Filtered only."""
    run = add_run(win, app, samples.c1_recipe())
    v, m = win.table.view, win.table.model
    assert not v.verticalHeader().isVisible() and v.verticalHeader().width() == 0
    assert v.viewport().mapTo(v, QPoint(0, 0)).x() == 0
    assert not hasattr(m, "checked") and not hasattr(v, "check_header")
    menu = v.row_menu(m.row_at(0), m.keys[0])
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert not any("heck" in t for t in texts), texts
    assert "Analyse composition" in texts and "Remove result" in texts
    from hea_calc.ui.analysis.collection_view import pop_items
    c = win.analysis_ctl
    assert [p[0] for p in pop_items(c)] == ["full", "filtered"]
    c.apply(S.switch_context, S.COLLECTION)
    settle(win, app)
    c.scope_for(run, "full")
    settle(win, app)
    assert c.state.scope.base == "full" and c.state.resolved.n == 341


def test_filtered_scope_goes_stale_and_updates(win, app):
    run = add_run(win, app, samples.c1_recipe())
    m = win.table.model
    m.set_filters([ModelFilter("M8", {"SS"})])
    m.wait()
    c = win.analysis_ctl
    c.apply(S.switch_context, S.COLLECTION)
    settle(win, app)
    c.scope_for(run, "filtered")
    settle(win, app)
    assert c.state.resolved.n == 12
    m.set_filters([])
    m.wait()
    win.analysis_ctl.table_filter_changed()
    pump(app)
    assert c.state.stale == S.STALE_FILTER and c.state.resolved.n == 12
    m.sort_by("delta")                                            # table interactions never re-resolve
    m.set_page(0)
    assert c.state.resolved.n == 12
    c.update_collection()
    settle(win, app)
    assert c.state.stale is None and c.state.resolved.n == 341


def test_removing_the_active_result_shows_the_removed_state(win, app):
    calc_single(win, app, samples.S1)
    m = win.table.model
    rec = m.row_at(0)
    win.table.view._remove(rec)
    pump(app)
    assert win.analysis.row is None and win.analysis_ctl.state.active_gone == S.REMOVED


# ====================================================================== collection pages and plots
def test_collection_pages_show_query_results(win, app):
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "overview")
    c = win.analysis_ctl
    pop = c.data["population"]
    assert pop["n"] == 341 and len(pop["families"]) == 4
    c.apply(S.set_tab, "statistics")
    settle(win, app)
    st = c.data["stats"]
    assert round(st["metrics"]["dhmix"]["median"], 2) == -10.76 and st["exact"]
    c.apply(S.set_tab, "models")
    settle(win, app)
    assert c.data["dist"]["models"]["M2"]["classes"] == {"SS": 203, "MP": 138}


@pytest.mark.parametrize("ptype", [SCATTER, HISTOGRAM, BOX, BAR_STACKED, BAR_GROUPED])
def test_plot_types_render_for_a_composition_space(win, app, ptype):
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    c = win.analysis_ctl
    c.apply(S.set_plot, c.state.plot.with_(type=ptype, group="family"))
    settle(win, app)
    plot = win.analysis.collection.plot
    assert plot is not None and plot.spec is not None, ptype
    img = plot.render_image(640, 320, 1.0)
    assert not img.isNull()
    assert plot.spec.tag, "every plot discloses its representation"


def test_line_and_heatmap_for_expressions(win, app):
    e1 = add_run(win, app, samples.e1_recipe())
    collection(win, app, e1, "plots")
    c = win.analysis_ctl
    assert c.state.plot.type == LINE
    plot = win.analysis.collection.plot
    assert plot.spec.kind == "line" and plot.spec.tag == "All 41 points · ordered by x"
    xs = plot.spec.data["x"]
    assert xs == sorted(xs) and len(xs) == 41
    e2 = add_run(win, app, samples.e2_recipe())
    c.scope_for(e2, "full")
    settle(win, app)
    assert c.state.plot.type == HEATMAP
    plot = win.analysis.collection.plot
    assert plot.spec.kind == "heatmap" and plot.spec.data["complete"]
    assert plot.spec.tag == "All 121 cells calculated"


def test_invalid_line_plot_is_blocked_with_a_fix(win, app):
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    c = win.analysis_ctl
    c.apply(S.set_plot, c.state.plot.with_(type=LINE, x="grid:Al"))
    settle(win, app)
    note = win.analysis.collection.plot_note
    assert note.isVisibleTo(win) and note.title.text() == "A line plot needs an ordered axis"
    assert note.button.text() == "Use scatter plot"
    note.action.emit()
    settle(win, app)
    assert c.state.plot.type == SCATTER


def test_sampled_and_binned_disclosure(win, app, monkeypatch):
    from hea_calc.core.analysis import queries
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    c = win.analysis_ctl
    c.apply(S.set_plot, c.state.plot.with_(representation=SAMPLED))
    settle(win, app)
    spec = win.analysis.collection.plot.spec
    assert spec.data["representation"] == SAMPLED and spec.hollow
    assert spec.tag.startswith("Sample · ") and spec.tag.endswith("of 341 points")
    c.apply(S.set_plot, c.state.plot.with_(representation=BINNED, bins=50))
    settle(win, app)
    spec = win.analysis.collection.plot.spec
    assert spec.kind == "binned" and spec.tag == "Binned · 50 × 50 cells · 341 results"
    assert sum(cell[2] for cell in spec.data["cells"]) == 341
    _ = queries


def test_plot_selection_is_visual_only(win, app):
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    c = win.analysis_ctl
    scope = c.state.scope
    plot = win.analysis.collection.plot
    ids = list(plot.spec.data["ids"])[:5]
    # a click selects one point (no box / lasso tools); the selection is visual only
    plot.point_clicked.emit(ids[0])
    pump(app)
    assert c.state.selection == frozenset(ids[:1]) and c.state.scope == scope and c.state.active is None
    assert not hasattr(plot, "selection_made") and not hasattr(plot, "mode")
    c.apply(S.select_points, ids)           # several points (controller API): still never the scope / active
    pump(app)
    assert c.state.selection == frozenset(ids) and c.state.scope == scope and c.state.active is None
    # the selection reaches the table only through the explicit id filter (no hidden checked state)
    win.analysis.collection._show_selection()
    win.table.model.wait()
    pump(app)
    from hea_calc.core.results import IdSetFilter
    assert any(isinstance(f, IdSetFilter) for f in win.table.model.filters)
    assert win.table.model.view_count() == 5


def _mouse(app, w, kind, pos, button, buttons):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    e = QMouseEvent(kind, QPointF(*pos), w.mapToGlobal(QPointF(*pos)), button, buttons,
                    Qt.KeyboardModifier.NoModifier)
    app.sendEvent(w, e)


def test_chart_tooltip_follows_carbon_chart_anatomy(win, app):
    """Hovering a point shows the Carbon chart tooltip (CORRECT_DATA_VISUALIZATION): the point as header, its
    values on both axes and its colour group with the legend colour - painted, inside the plot."""
    from hea_calc.ui.analysis.plot import ChartTooltip, class_color
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    c = win.analysis_ctl
    c.apply(S.set_plot, c.state.plot.with_(type=SCATTER, x="dhmix", y="delta", color="model:M2"))
    settle(win, app)
    plot = win.analysis.collection.plot
    plot.grab()                                  # paints: the hit-test positions exist
    sx, sy, idx = plot._screen[len(plot._screen) // 2]
    _mouse(app, plot, QEvent.Type.MouseMove, (sx, sy), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton)
    tip = plot.tip
    assert isinstance(tip, ChartTooltip) and tip.isVisible()
    assert plot.toolTip() == "", "the chart never uses the application text tooltip"
    labels = [lab for lab, _v, _c in tip.rows]
    assert labels[:2] == [plot.spec.x.symbol, plot.spec.y.symbol] and labels[2] == "M2"
    cls = plot.spec.data["c"][idx]
    assert tip.rows[2][1] == cls and tip.rows[2][2] == class_color(cls), "group row carries the legend colour"
    assert tip.title and plot.rect().contains(tip.geometry()), "the tooltip stays inside the plot"
    _mouse(app, plot, QEvent.Type.MouseMove, (2, 2), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton)
    assert not tip.isVisible()


@pytest.mark.parametrize("button", ["middle", "right"])
def test_plot_pans_by_middle_or_right_drag(win, app, button):
    """No Pan tool, no Box / Lasso tools: dragging with the middle or right button pans the axes window
    (brief §27, §28); the selection is untouched."""
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    c = win.analysis_ctl
    c.apply(S.set_plot, c.state.plot.with_(type=SCATTER, x="dhmix", y="delta", color="model:M2"))
    settle(win, app)
    plot = win.analysis.collection.plot
    plot.grab()
    b = Qt.MouseButton.MiddleButton if button == "middle" else Qt.MouseButton.RightButton
    lim = plot._limits()
    start = (plot.width() / 2, plot.height() / 2)
    _mouse(app, plot, QEvent.Type.MouseButtonPress, start, b, b)
    _mouse(app, plot, QEvent.Type.MouseMove, (start[0] + 60, start[1] - 30), Qt.MouseButton.NoButton, b)
    _mouse(app, plot, QEvent.Type.MouseButtonRelease, (start[0] + 60, start[1] - 30), b, Qt.MouseButton.NoButton)
    assert plot.window is not None
    x0, x1, y0, y1 = plot.window
    assert x0 < lim[0] and x1 < lim[1], "dragging right moves the window to lower x"
    assert y0 < lim[2] and y1 < lim[3], "dragging up moves the window to lower y"
    assert abs((x1 - x0) - (lim[1] - lim[0])) < 1e-9, "pan keeps the zoom"
    assert c.state.selection == frozenset() and plot._pan_start is None
    win.analysis.expand_btn.click()          # the workspace toolbar had the Box / Lasso / Pan tools
    settle(win, app)
    ws = win.workspace.collection
    tools = {w.toolTip() or getattr(w, "tip_text", "") for w in ws.findChildren(QWidget)}
    assert {"Zoom in", "Zoom out", "Reset axes", "Export"} <= tools
    assert not tools & {"Box select", "Lasso select", "Pan"}
    # point inspector: Carbon md buttons, everything inside the region (2.png clipped the model tags)
    c.apply(S.select_points, [ws.plot.spec.data["ids"][0]])
    settle(win, app)
    from PySide6.QtWidgets import QPushButton
    reg = win.workspace.collection.inspector_region
    btns = [b for b in reg.findChildren(QPushButton) if b.text() in ("Analyse composition", "Show in results table")]
    assert len(btns) == 2 and all(b.height() == 40 for b in btns)
    from hea_calc.ui.analysis.composition_view import _ModelCell
    cells = reg.findChildren(_ModelCell)
    assert len(cells) == 8
    for w in cells + btns:
        r = w.rect().translated(w.mapTo(reg, QPoint(0, 0)))
        assert r.right() <= reg.width() - 20, (w, r, reg.width())


# ====================================================================== expanded workspace
def test_expand_and_back_preserve_state_and_focus(win, app):
    calc_single(win, app, samples.S1)
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    c = win.analysis_ctl
    before = c.state
    win.activateWindow()
    win.analysis.expand_btn.setFocus()
    win.analysis.expand_btn.click()
    settle(win, app)
    assert win.pages.currentIndex() == 1 and c.state.expanded
    assert win.header.isVisible(), "the app header stays"
    assert win.workspace.collection.plot is not None and win.workspace.collection.plot.spec is not None
    for f in ("context", "coll_tab", "resolved", "plot", "selection", "active", "comp_tab", "model"):
        assert getattr(c.state, f) == getattr(before, f), f
    win.workspace.back.click()
    pump(app)
    assert win.pages.currentIndex() == 0 and not c.state.expanded
    # (offscreen windows are never active, so ask the window rather than the application)
    assert win.focusWidget() is win.analysis.expand_btn, "focus returns to Expand analysis"
    win._expand_shortcut.activated.emit()
    pump(app)
    assert win.pages.currentIndex() == 1
    win._expand_shortcut.activated.emit()
    pump(app)
    assert win.pages.currentIndex() == 0


def test_workspace_pages_build(win, app):
    calc_single(win, app, samples.S1)
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run)
    win.set_expanded(True)
    c = win.analysis_ctl
    for tab in S.COLL_TABS:
        c.apply(S.set_tab, tab)
        settle(win, app)
        if tab == "statistics":
            # no descriptor is the default: nothing is plotted until a metric is chosen
            assert c.state.stats_focus == "" and c.data.get("hist") is None and c.data.get("box") is None
            for metric in ("delta_cn12", "dhmix"):
                c.apply(S.update, stats_focus=metric)
                settle(win, app)
                assert metric in str(c.data_keys["hist"]) and c.data.get("box") is None, \
                    "one visualization (histogram) - the group comparison is not queried until chosen"
            coll = win.workspace.collection
            from hea_calc.ui.analysis.plot import PlotWidget
            assert len([p for p in coll.ws_viz.findChildren(PlotWidget)]) == 1, "4.png: one chart, not two"
            c.apply(S.update, stats_view="groups")
            settle(win, app)
            assert "dhmix" in c.data["box"]["metrics"]
            coll = win.workspace.collection
            plots = coll.ws_viz.findChildren(PlotWidget)
            assert len(plots) == 1 and plots[0].spec.kind == "box"
            assert coll.stats_view_sw.index() == 1
    assert c.data.get("box") is not None and c.data.get("hist") is not None
    c.apply(S.switch_context, S.COMPOSITION)
    for tab in S.COMP_TABS:
        c.apply(S.set_tab, tab)
        pump(app)
    assert win.workspace.comp_body.currentIndex() == 1


def test_model_details_list_and_mse_a_reference(win, app):
    """6.png / brief §36-37: a compact selection list (no chevron, no ring after a click) and every model's
    citation in the one MSE-A form of ``core/references.py`` - the same text About and Help use."""
    from PySide6.QtGui import QTextDocumentFragment
    from PySide6.QtWidgets import QLabel
    from hea_calc.core import references as R
    from hea_calc.core.engine import MODEL_KEYS
    calc_single(win, app, samples.S1)
    win.table.model.wait()
    c = win.analysis_ctl
    c.set_active(win.table.model.page_rows()[0].id, by="table")
    c.apply(S.switch_context, S.COMPOSITION)
    c.apply(S.set_tab, "model_details")
    win.set_expanded(True)
    settle(win, app)
    lst = win.workspace.model_list
    assert lst.row_height == 40 and not lst.chevron and not lst.show_header
    parent = lst.parentWidget()
    assert lst.geometry().right() <= parent.width() - 20, "the list keeps the region padding"
    for k in MODEL_KEYS:
        c.apply(S.select_model, k)
        settle(win, app)
        assert lst.selected == MODEL_KEYS.index(k)
        refs = [lab for lab in win.workspace.composition_details.findChildren(QLabel)
                if lab.objectName() == "ModelReference"]
        assert len(refs) == 1
        text = QTextDocumentFragment.fromHtml(refs[0].text()).toPlainText()
        assert text == R.model_citation(k) and "https://doi.org/" in text, (k, text)
    md = R.markdown(R.MODEL_REFERENCES)
    assert all(R.MODEL_REFERENCES[i].text() in md for i in range(8)), "Help uses the same citations"


def test_statistics_outlier_indication(win, app):
    """Brief §35 / §72: "N statistical outliers" (Tukey fences) beside the chart with the method in a toggletip;
    a neutral statistical note, not a warning; absent where nothing lies outside the fences."""
    from hea_calc.core.analysis.queries import ScopeQuery
    from hea_calc.ui.analysis.collection_view import OUTLIER_TIP
    from hea_calc.ui.widgets.tooltip import InfoButton
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "statistics")
    win.set_expanded(True)
    c = win.analysis_ctl
    con = win.repo.reader_connection()
    try:
        for metric in ("omega", "dhmix", "vec", "delta"):
            c.apply(S.update, stats_focus=metric)
            settle(win, app)
            ref = ScopeQuery(con, c.state.scope, win.repo.get_run(run)).outliers(metric)
            n = ref["n_low"] + ref["n_high"]
            note = win.workspace.collection.outlier_note
            if n:
                assert note is not None and note.text() == f"{n:,} statistical outlier{'s' if n != 1 else ''}"
                tips = [b for b in win.workspace.collection.ws_viz.findChildren(InfoButton)
                        if b.tip_text == OUTLIER_TIP]
                assert len(tips) == 1
            else:
                assert note is None, metric
    finally:
        con.close()
    assert OUTLIER_TIP.startswith("Values outside Q1 − 1.5 × IQR to Q3 + 1.5 × IQR are marked as statistical outliers.")


# ====================================================================== reports
def _pdf_text(path) -> tuple[int, str]:
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    doc.load(str(path))
    t0 = time.perf_counter()
    while doc.status() != QPdfDocument.Status.Ready and time.perf_counter() - t0 < 10:
        QApplication.processEvents()
    text = "\n".join(doc.getAllText(i).text() for i in range(doc.pageCount()))
    n = doc.pageCount()
    doc.close()
    return n, text


def test_composition_report_pdf(win, app, tmp_path):
    from hea_calc.ui.analysis.report_ui import _composition_job, render_pdf
    from hea_calc.core.analysis.report import composition_report_html
    calc_single(win, app, samples.S2)
    c = win.analysis_ctl
    info = c.run_info(c.record.run_id)
    html = composition_report_html(c.row, info)
    assert "Not available" in html and "Troparevsky" in html
    path = tmp_path / "comp.pdf"
    pages = render_pdf(html, str(path))
    assert path.stat().st_size > 2000 and pages >= 3
    n, text = _pdf_text(path)
    assert n == pages
    for needle in ("Composition report", "CoCrFeNiSi", "Mixing enthalpy", "kJ mol", "M6", "N/A",
                   "Not available", "Takeuchi", "Yang", "Scientific limitations"):
        assert needle in text, needle
    _ = _composition_job


def test_collection_report_pdf_and_partial_run_warning(win, app, tmp_path):
    from hea_calc.ui.analysis.report_ui import ReportTask, _collection_job
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    c = win.analysis_ctl
    from hea_calc.ui.analysis.report_ui import plot_context
    plot = plot_context(win)
    assert plot is not None and plot["qimage"].pixelColor(5, 5).lightness() > 200, "printable light plot"
    info = c.run_info(run)
    info.status = "cancelled"                                 # as a cancelled run would report it
    path = tmp_path / "coll.pdf"
    task = ReportTask()
    done = []
    task.finished.connect(lambda st, v: done.append((st, v)))
    task.start(_collection_job, c.repo, c.state.scope, info, c.workspace_lo, ["dhmix", "delta"], plot, None,
               341, "", str(path))
    t0 = time.perf_counter()
    while not done and time.perf_counter() - t0 < 60:
        pump(app)
        time.sleep(0.01)
    assert done and done[0][0] == "ok", done
    n, text = _pdf_text(path)
    for needle in ("Collection analysis report", "Run ", "Full result set", "341", "Descriptive statistics",
                   "Median", "Evaluated", "% of evaluated", "Partial run", "All 341 points", "Plot"):
        assert needle in text, needle


def test_report_cancellation(win, app, tmp_path):
    from hea_calc.ui.analysis.report_ui import ReportCancelled, ReportTask
    task = ReportTask()
    done = []
    task.finished.connect(lambda st, v: done.append(st))

    def slow(t):
        for _ in range(200):
            t.check()
            time.sleep(0.01)
        return {"path": "", "pages": 0}
    task.start(slow)
    task.cancel()
    t0 = time.perf_counter()
    while not done and time.perf_counter() - t0 < 10:
        pump(app)
        time.sleep(0.01)
    assert done == ["cancelled"]
    _ = ReportCancelled


def test_report_filenames_are_sanitised():
    from hea_calc.core.analysis.report import safe_filename
    assert safe_filename("CoCrFeMnNi") == "HEA_Analysis_CoCrFeMnNi.pdf"
    assert safe_filename("Run_3") == "HEA_Analysis_Run_3.pdf"
    assert safe_filename("Al0.5(CoCrFeNi)/x:y*?") == "HEA_Analysis_Al0.5_CoCrFeNi_x_y.pdf"
    assert safe_filename("") == "HEA_Analysis_report.pdf"
    assert len(safe_filename("A" * 500)) <= 120


def test_report_theme_is_light_whatever_the_app_theme(win, app):
    from hea_calc.core.analysis.report import composition_report_html
    from hea_calc.ui.theme import THEME
    calc_single(win, app, samples.S1)
    THEME.set_theme("dark")
    html = composition_report_html(win.analysis_ctl.row)
    assert "background: #ffffff" in html and "color: #161616" in html
    for token in ("#161616;", "#262626", "#393939"):                     # no dark-theme surface leaks in
        assert f"background: {token}" not in html.replace("background: #161616; ", "")
    # the report follows the Total mass preference (release brief section 37)
    five = composition_report_html(win.analysis_ctl.row, batch_mass=5.0)
    assert "Mass (5 g batch)" in five and "Mass (2 g batch)" in html


def test_long_report_paginates(win, app, tmp_path):
    from hea_calc.ui.analysis.report_ui import render_pdf
    from hea_calc.core.analysis.report import table
    rows = [[f"row {i}", f"{i}"] for i in range(400)]
    html = "<html><body>" + table(["Name", "Value"], rows) + "</body></html>"
    pages = render_pdf(html, str(tmp_path / "long.pdf"))
    assert pages >= 5
    n, text = _pdf_text(tmp_path / "long.pdf")
    import re
    # semibold header glyphs are extracted one per line: compare without whitespace
    assert re.sub(r"\s+", "", text).count("NameValue") >= n, "the header row repeats on every page"


def test_show_in_results_table_applies_a_visible_id_filter(win, app, tmp_path):
    from hea_calc.core.results import IdSetFilter
    run = add_run(win, app, samples.c1_recipe())
    collection(win, app, run, "plots")
    plot = win.analysis.collection.plot
    ids = sorted(list(plot.spec.data["ids"])[10:17])
    win.show_in_table(ids)
    m = win.table.model
    m.wait()
    pump(app)
    assert any(isinstance(f, IdSetFilter) for f in m.filters)
    assert m.view_count() == 7 and sorted(r.id for r in m.page_rows()) == ids
    assert win.analysis_ctl.state.scope.base == "full" and win.analysis_ctl.state.stale is None, \
        "a full-result-set collection is not affected by the table filter"
    from hea_calc.core.export import export_process_main
    import multiprocessing as mp
    spec = m.view.export_spec(filtered=True)
    assert spec["count"] == 7
    q, val, ev = mp.Queue(), mp.Value("q", 0), mp.Event()
    out = tmp_path / "sel.csv"
    export_process_main(spec, str(out), "file", {"elements": ["Co", "Cr", "Fe", "Ni", "Al", "Mn"], "notes": {}},
                        val, ev, q)
    status, n = q.get(timeout=10)
    assert (status, n) == ("ok", 7)


def test_expression_run_records_block_duplicates_for_analysis(win, app):
    recipe = samples.expression_recipe("AlxCoCrFeNi\n\nAlyCoCrFeNi", {"x": (0.0, 1.0, 0.25), "y": (0.0, 1.0, 0.25)})
    win.calculate("expression", None, recipe)
    t0 = time.perf_counter()
    while win.worker is not None and time.perf_counter() - t0 < 120:
        pump(app)
        time.sleep(0.01)
    pump(app)
    info = win.repo.get_run(win.runner.run_id)
    assert info.calculated == 5
    assert info.source.get("duplicates_by_block") == {"1": 5}
