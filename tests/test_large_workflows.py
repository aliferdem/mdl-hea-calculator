"""Large-composition workflows: pre-flight counting, process-based jobs, the page-backed results
table and its interaction model, responsive reflow, Pending status, tooltip/toggletip geometry and
the shared Carbon menu.  (Timings of the real 30k / 100k runs: tools/perf_harness.py.)"""

import os
import sys
import tempfile
import time
from array import array
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSettings, QSize, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication  # noqa: E402

from hea_calc.core import generation  # noqa: E402
from hea_calc.core.generation import SweepSpec, count_space  # noqa: E402
from hea_calc.core.jobs import CalculationJob, CalculationService, JobInput  # noqa: E402
from hea_calc.core.recipes import SweepRecipe  # noqa: E402
from hea_calc.core.chunks import pack_results  # noqa: E402
from hea_calc.core.repository import ResultRepository, ResultView  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from synthetic import fill  # noqa: E402

FIVE = ["Fe", "Co", "Ni", "Cr", "Mn"]


# =========================================================================== pre-flight count (core)
def test_preflight_count_never_materialises_compositions(monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("a composition was materialised")
    monkeypatch.setattr(generation, "iter_space", forbidden)
    monkeypatch.setattr(generation, "_sum_combos", forbidden)
    specs = [SweepSpec(e, 0, 100, 2) for e in FIVE]
    t = time.perf_counter()
    capped = count_space(specs, "at", stop_after=200_000)
    exact = count_space(specs, "at", stop_after=10**12)
    assert time.perf_counter() - t < 0.5
    assert capped.exceeds and capped.count == 200_001
    assert exact.count == 211_876 and not exact.exceeds      # C(49, 4): 50 parts of 2 at.% into 5 elements


def test_preflight_cap_is_immediate_for_huge_ratio_spaces():
    t = time.perf_counter()
    c = count_space([SweepSpec(e, 0, 100, 2) for e in FIVE], "ratio", stop_after=200_000)
    assert c.exceeds and time.perf_counter() - t < 0.1       # 50^5 product: bound proves it, no walk


def test_preflight_count_matches_generation_with_optional_elements_and_sizes():
    specs = [SweepSpec("Al", 0, 40, 10, False), SweepSpec("Ti", 10, 60, 10), SweepSpec("V", 0, 50, 5, False),
             SweepSpec("Nb", 20, 30, 5)]
    for unit in ("at", "ratio"):
        for sizes in (None, {3}, {2, 4}):
            n = len(list(generation.iter_space(specs, unit, sizes)))
            assert count_space(specs, unit, sizes, stop_after=10**9).count == n, (unit, sizes)


# =========================================================================== jobs (core, real processes)
@pytest.fixture(scope="module")
def service():
    svc = CalculationService(workers=2, inprocess_max=50)
    yield svc
    svc.shutdown()
    assert svc.worker_pids() == []


def drain(job, timeout=120):
    chunks = []
    t0 = time.perf_counter()
    while not (job.finished and not job.inbox):
        while job.inbox:
            chunks.append(job.inbox.popleft())
        time.sleep(0.01)
        assert time.perf_counter() - t0 < timeout
    return chunks


def test_recipe_job_generates_and_calculates_in_worker_processes(service, engine):
    recipe = SweepRecipe(tuple(SweepSpec(e, 5, 50, 5) for e in FIVE[:4]), "at")
    job = service.start(CalculationJob(JobInput("sweep", (), recipe, (), {}), engine))
    chunks = drain(job)
    assert job.state == "done" and job.mode == "process"
    assert job.names == [] and not hasattr(job, "_comps"), "the GUI process never held the composition list"
    assert sum(c["n"] for _s, c in chunks) == job.total == recipe.estimate()
    assert [s for s, _c in chunks] == sorted(s for s, _c in chunks), "chunks arrive in order"
    assert all(pid != os.getpid() for pid in service.worker_pids())
    # same results as the in-process engine
    _src, names, comps, _env = recipe()
    first = chunks[0][1]
    assert first["names"][0] == names[0]
    ref = pack_results(comps[:1], [engine.calculate(comps[0])])
    assert first["num"]["dhmix"][0] == ref["num"]["dhmix"][0]


def test_cancellation_is_fast_and_keeps_a_contiguous_prefix(service, engine):
    recipe = SweepRecipe(tuple(SweepSpec(e, 2, 40, 2) for e in FIVE), "at")      # 94 381 alloys
    job = service.start(CalculationJob(JobInput("sweep", (), recipe, (), {}), engine))
    t0 = time.perf_counter()
    while job.done_count < 400 and time.perf_counter() - t0 < 60:
        time.sleep(0.02)
    t = time.perf_counter()
    job.cancel()
    job.wait(10)
    assert job.state == "cancelled"
    assert time.perf_counter() - t < 1.0, "cancel effective well below one second"
    chunks = drain(job)
    expect = 0
    for s, c in chunks:
        assert s == expect
        expect += c["n"]
    assert 0 < expect < 94_381
    assert not service.cancel_event.is_set(), "the shared cancel flag is reset for the next job"


def test_small_jobs_stay_in_process_when_no_pool_runs(engine):
    svc = CalculationService(workers=2, inprocess_max=300)
    job = svc.start(CalculationJob(JobInput("single", ["a", "b"], [{"Fe": 1, "Ni": 1}, {"Co": 1, "Cr": 1}],
                                            [{}, {}], {}), engine))
    drain(job)
    assert job.state == "done" and job.mode == "inprocess" and not svc.warm


# =========================================================================== repository / model
def test_repository_of_100k_rows_lives_on_disk(engine):
    repo = ResultRepository(engine)
    try:
        view = ResultView(repo)
        fill(repo, 100_000, engine)
        view.refresh()
        assert view.total() == 100_000
        size = sum(repo.size_bytes().values())
        assert size < 100_000 * 600, size                       # ~0.45 KiB/row on disk, nothing in RAM
        assert view.at(99_999).name == "SYN99999"
        view.request(sort=("dhmix", True), wait=60)
        assert view.count() == 100_000
    finally:
        repo.close()


# =========================================================================== UI
@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


def make_window(app, size=(1920, 1000)):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
    settings = QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=settings)
    w.resize(*size)
    w.show()
    for _ in range(3):
        app.processEvents()
    return w


@pytest.fixture()
def win(app):
    w = make_window(app)
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def add_rows(win, n):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from screenshot import demo_rows
    demo_rows(win, n)
    QApplication.processEvents()


def mouse(view, kind, pos, button=Qt.MouseButton.LeftButton, buttons=None):
    vp = view.viewport()
    ev = QMouseEvent(kind, QPointF(pos), QPointF(vp.mapToGlobal(pos)), button,
                     button if buttons is None else buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(vp, ev)


def wait_job(win, app, timeout=120):
    t0 = time.perf_counter()
    while win.worker is not None:
        app.processEvents()
        time.sleep(0.005)
        assert time.perf_counter() - t0 < timeout
    app.processEvents()


def test_model_exposes_only_the_page_and_no_qt_items(win, app, engine):
    m = win.table.model
    before = len(m.findChildren(QObject)) + len(win.table.view.viewport().findChildren(QObject))
    fill(m.repo, 100_000, engine)
    m.refresh_committed()
    app.processEvents()
    assert m.view_count() == 100_000
    assert m.rowCount() == 100 and m.columnCount() == len(m.keys)
    win.table.pagination.size_box.setCurrentIndex(0)
    assert m.rowCount() == 10
    after = len(m.findChildren(QObject)) + len(win.table.view.viewport().findChildren(QObject))
    assert after == before, "no QObject per row or cell"
    assert win.table.pagination.of_lbl.text() == "of 10,000 pages"
    assert win.table.view.indexWidget(m.index(0, 0)) is None
    t = time.perf_counter()
    m.set_page(5000)
    app.processEvents()
    assert time.perf_counter() - t < 0.5 and m.id_at(0) == m.view.lo + 50_000
    field = win.table.pagination.page_field
    assert field.text() == "5001"
    field.setText("5004")
    field.returnPressed.emit()                             # Enter commits a typed page number
    assert m.page == 5003
    field.setText("99999")
    field.returnPressed.emit()                             # out of range: corrected to the last page, visibly
    assert m.page == 9999 and field.text() == "10000" and field._invalid


def test_table_has_no_selection_and_no_body_tooltips(win):
    add_rows(win, 3)
    v, m = win.table.view, win.table.model
    assert v.selectionMode() == QAbstractItemView.SelectionMode.NoSelection
    assert v.focusPolicy() == Qt.FocusPolicy.NoFocus
    idx = m.index(0, 0)
    assert not (m.flags(idx) & Qt.ItemFlag.ItemIsSelectable)
    assert m.data(idx, Qt.ItemDataRole.ToolTipRole) is None
    assert m.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)


def test_single_click_does_nothing_double_click_loads_details(win, app):
    add_rows(win, 5)
    win.show_details(None)
    v, m = win.table.view, win.table.model
    pos = v.visualRect(m.index(2, 3)).center()
    mouse(v, QEvent.Type.MouseButtonPress, pos)
    mouse(v, QEvent.Type.MouseButtonRelease, pos)
    app.processEvents()
    assert win.details.row is None, "a single click neither selects nor opens details"
    assert not v.selectionModel().hasSelection()
    mouse(v, QEvent.Type.MouseButtonDblClick, pos)
    app.processEvents()
    assert win.details.row is not None and win.details.row.row_id == m.id_at(2)
    assert win.details.row.name == m.row_at(2).name


def test_double_click_after_sorting_opens_the_right_alloy(win, app):
    add_rows(win, 12)
    v, m = win.table.view, win.table.model
    m.sort_by("name")
    m.sort_by("name")                                    # descending
    app.processEvents()
    expected = sorted((r.name for r in m.rows), reverse=True)[0]
    pos = v.visualRect(m.index(0, 2)).center()
    mouse(v, QEvent.Type.MouseButtonDblClick, pos)
    app.processEvents()
    assert win.details.row.name == expected
    assert m.repo.get_result(win.details.row.row_id).name == expected


def test_row_menu_opens_details_in_a_new_window(win, app, monkeypatch):
    add_rows(win, 4)
    v, m = win.table.view, win.table.model
    opened = []
    from hea_calc.ui.widgets import dialogs
    monkeypatch.setattr(dialogs.AlloyDetailsDialog, "exec", lambda self: opened.append(self.windowTitle()) or 0)
    menu = v.row_menu(m.row_at(1), m.keys[0])
    from hea_calc.ui.widgets.menu import CarbonMenu
    assert isinstance(menu, CarbonMenu)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert "Open details in new window" in texts
    assert [a for a in menu.actions() if a.text() == "Remove result"][0].property("danger")
    win.show_details(None)
    next(a for a in menu.actions() if a.text() == "Open details in new window").trigger()
    app.processEvents()
    assert len(opened) == 1
    assert win.details.row is None, "the menu opens a window, not the embedded panel"


def test_drag_selects_cell_text_and_ctrl_c_copies_it(win, app):
    add_rows(win, 3)
    v, m = win.table.view, win.table.model
    col = m.keys.index("dhmix")
    rect = v.visualRect(m.index(1, col))
    text = m.cell_text(1, col)
    start = QPoint(rect.left() + 14, rect.center().y())
    end = QPoint(rect.left() + 16 + 200, rect.center().y())
    mouse(v, QEvent.Type.MouseButtonPress, start)
    mouse(v, QEvent.Type.MouseMove, QPoint(start.x() + 10, start.y()), Qt.MouseButton.NoButton,
          Qt.MouseButton.LeftButton)
    mouse(v, QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    mouse(v, QEvent.Type.MouseButtonRelease, end)
    app.processEvents()
    sel = v.selection
    assert sel.isVisible() and sel.selected_text() == text
    assert not v.selectionModel().hasSelection(), "text selection, not item selection"
    QApplication.clipboard().setText("")
    from PySide6.QtGui import QKeyEvent, QKeySequence
    QApplication.sendEvent(sel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier))
    assert QApplication.clipboard().text() == text.replace("−", "-")
    # a plain click ends it; nothing stays highlighted
    mouse(v, QEvent.Type.MouseButtonPress, rect.center())
    mouse(v, QEvent.Type.MouseButtonRelease, rect.center())
    assert not sel.isVisible()


def test_sweep_calculation_runs_as_a_process_job_with_throttled_progress(win, app):
    for el in FIVE[:4]:
        win.elements.table.tiles[el].click()
    win.composition.set_mode(1)
    win.composition.unit_box.setCurrentIndex(1)
    for r in win.composition.sweep.rows.values():
        r.min.setText("5"), r.max.setText("50"), r.step.setText("5")
    # Calculate is enabled once the (debounced, background) pre-flight count has run ("Updating…" -> "Ready")
    sw = win.composition.sweep
    sw._timer.stop()
    sw._update_summary()
    t_count = time.perf_counter()
    while sw._counter.busy and time.perf_counter() - t_count < 30:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert win.composition.calc_btn.isEnabled()
    progress = []
    win.runner.progress.connect(lambda d, t, e: progress.append(d))
    t0 = time.perf_counter()
    win.composition.calc_btn.click()
    assert win.worker is not None and not win.composition.calc_btn.isEnabled()
    job = win.worker
    wait_job(win, app)
    elapsed = time.perf_counter() - t0
    n = win.table.model.total_count()
    assert n == job.total > 300 and job.mode == "process"
    assert len(progress) <= elapsed / 0.1 + 3, "progress at the 10 Hz tick, not per alloy"
    assert len(progress) < n / 20
    assert win.table.model.rowCount() <= 100
    assert win.composition.calc_btn.isEnabled() and win.composition.calc_btn.text() == "Calculate"


def test_details_move_below_when_the_three_panels_do_not_fit(app):
    from hea_calc.ui.theme import (ANALYSIS_WIDE_MIN, COMPOSITION_PANEL_WIDTH, CONTENT_MARGIN_X, ELEMENT_PANEL_MIN,
                                   PANEL_GAP)
    need = ELEMENT_PANEL_MIN + COMPOSITION_PANEL_WIDTH + ANALYSIS_WIDE_MIN + 2 * PANEL_GAP
    boundary = need + 2 * CONTENT_MARGIN_X                    # window width at the breakpoint
    w = make_window(app, (1920, 900))
    try:
        top = w.top_row
        assert top.wide_minimum() == need
        ids = (id(w.elements), id(w.composition), id(w.details))
        assert not top.stacked and top.width() >= need          # 100 % on a 1920 px client: one row
        w.resize(1440, 900)                                     # 150 % on the target display: stacked
        app.processEvents()
        assert top.stacked
        e, c, d = w.elements.geometry(), w.composition.geometry(), w.details.geometry()
        assert e.top() == c.top() == 0 and d.top() == e.bottom() + 1 + PANEL_GAP
        assert d.width() == top.width() and d.left() == 0, "Analysis spans the full width"
        assert c.right() == top.width() - 1, "Element + Composition fill the first row"
        assert c.width() == COMPOSITION_PANEL_WIDTH, "Composition setup keeps its design width"
        assert w.table.mapTo(w.content, QPoint(0, 0)).y() > w.details.mapTo(w.content, QPoint(0, 0)).y()
        assert not w.layout_report()["horizontalOverflow"]
        # hysteresis: just past the boundary it stays stacked, a little wider it returns
        w.resize(boundary + 10, 900)
        app.processEvents()
        assert top.stacked
        w.resize(boundary + 40, 900)
        app.processEvents()
        assert not top.stacked
        assert w.composition.width() == COMPOSITION_PANEL_WIDTH and w.details.width() >= ANALYSIS_WIDE_MIN
        assert ids == (id(w.elements), id(w.composition), id(w.details)), "panels repositioned, not rebuilt"
    finally:
        w.close()


def test_model_support_shows_pending_in_the_empty_state(win, app):
    sup = win.elements.support
    assert all(ic.status == "pending" for ic in sup.icons.values())
    assert all("Pending" in ic.accessibleName() and ic.toolTip() for ic in sup.icons.values())
    win.elements.table.tiles["Fe"].click()
    app.processEvents()
    sup.show_element("Fe")
    assert all(ic.status in ("ok", "warn", "pair", "none") for ic in sup.icons.values())
    sup.show_element(None)
    assert all(ic.status == "pending" for ic in sup.icons.values())
    img = sup.icons["M1"].grab().toImage().convertToFormat(QImage.Format.Format_ARGB32)
    from hea_calc.ui.theme import t
    assert img.pixelColor(img.width() // 2, 3).name() == t("status-gray"), "the grey pending disc is painted"


def test_toggletip_caret_points_at_the_trigger_not_the_body_centre(win, app):
    from hea_calc.ui.theme import TOOLTIP_RADIUS
    from hea_calc.ui.widgets.tooltip import START_CARET_INSET, InfoButton
    trig = win.elements.support.findChild(InfoButton)
    trig.click()
    app.processEvents()
    tip = trig.popup
    try:
        assert tip.isVisible() and TOOLTIP_RADIUS == 2
        assert tip.width() == 308
        trig_c = trig.mapToGlobal(QPoint(0, 0)).x() + trig.width() / 2
        caret_global = tip.x() + tip.placement.caret
        assert abs(caret_global - trig_c) <= 1, (caret_global, trig_c)
        assert tip.placement.caret == pytest.approx(START_CARET_INSET, abs=1), "start-aligned like the reference"
        assert abs(tip.placement.caret - tip.width() / 2) > 100, "not centred on the body"
    finally:
        tip.close()


def test_popover_shifts_on_screen_edges_but_keeps_the_caret_on_the_trigger():
    from hea_calc.ui.widgets.tooltip import CARET_GAP, place_popover
    screen = QRect(0, 0, 1440, 900)
    body = QSize(308, 120)
    pl = place_popover(body, QRect(1400, 300, 16, 16), screen, "bottom", "start")    # right edge
    assert pl.pos.x() + 308 - 1 <= 1439
    assert abs(pl.pos.x() + pl.caret - 1408) <= 1
    pl = place_popover(body, QRect(4, 300, 16, 16), screen, "bottom", "center")        # left edge
    assert pl.pos.x() >= 0 and abs(pl.pos.x() + pl.caret - 12) <= 1
    pl = place_popover(body, QRect(700, 880, 16, 16), screen, "bottom", "start")       # no room below
    assert pl.side == "top" and pl.pos.y() + 120 + 6 + CARET_GAP == 880
    pl = place_popover(QSize(308, 860), QRect(400, 400, 16, 16), screen, "bottom")     # no room above/below
    assert pl.side in ("right", "left") and abs(pl.pos.y() + pl.caret - 408) <= 1


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_carbon_menu_paints_from_theme_tokens(win, app, theme):
    from hea_calc.ui.theme import THEME, t
    from hea_calc.ui.widgets.menu import CarbonMenu
    win.set_theme(theme)
    menu = CarbonMenu(parent=win)
    menu.add_action("Open details in new window")
    menu.addSeparator()
    danger = menu.add_action("Remove result", danger=True)
    menu.popup(QPoint(100, 100))
    app.processEvents()
    try:
        assert menu.width() >= 160
        img = menu.grab().toImage()
        assert img.pixelColor(4, 2).name() == t("layer-01")
        menu.setActiveAction(danger)
        app.processEvents()
        r = menu.actionGeometry(danger)
        img = menu.grab().toImage()
        assert img.pixelColor(r.left() + 4, r.center().y()).name() == t("button-danger-primary")
        assert THEME.name == theme
    finally:
        menu.close()
        win.set_theme("dark")


def test_every_application_menu_is_a_carbon_menu(win):
    from hea_calc.ui.widgets.menu import CarbonMenu
    assert isinstance(win.file_menu, CarbonMenu) and isinstance(win.theme_menu, CarbonMenu)
    assert isinstance(win.table.export_btn.menu(), CarbonMenu)
    subs = [a.menu() for a in win.file_menu.actions() if a.menu() is not None]
    assert subs and all(isinstance(s, CarbonMenu) for s in subs)


_ = (array, QSize)


def test_carbon_menu_keyboard_navigation(win, app):
    from PySide6.QtGui import QKeyEvent
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.menu import CarbonMenu
    hit = []
    menu = CarbonMenu(parent=win)
    a = menu.add_action("First", lambda: hit.append("first"))
    menu.add_action("Disabled", lambda: hit.append("disabled"), enabled=False)
    c = menu.add_action("Third", lambda: hit.append("third"))
    menu.popup(QPoint(200, 200))
    app.processEvents()

    def key(k):
        QApplication.sendEvent(menu, QKeyEvent(QEvent.Type.KeyPress, k, Qt.KeyboardModifier.NoModifier))
        app.processEvents()
    key(Qt.Key.Key_Down)
    assert menu.activeAction() is a
    key(Qt.Key.Key_Down)
    assert menu.activeAction() is c, "disabled items are skipped"
    img = menu.grab().toImage()
    r = menu.actionGeometry(c)
    assert img.pixelColor(1, r.center().y()).name() == t("focus"), "keyboard focus ring on the item"
    key(Qt.Key.Key_Return)
    assert hit == ["third"] and not menu.isVisible()
    menu.popup(QPoint(200, 200))
    app.processEvents()
    key(Qt.Key.Key_Escape)
    assert not menu.isVisible()
