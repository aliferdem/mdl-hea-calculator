"""P0 (2026-10-27): every Results row shows the result it stands for, and a double click analyses that same result.

Root cause fixed: ``ResultsModel`` cached formatted cells by *row index*; newest-first insertion moves every row down
without a reset, so the top row painted the previous top row's cached cells (name, descriptors and model tags) while
``id_at`` / double click resolved the new result.  The cache is now keyed by ``result_id``.

Expected values never come from the table: single-calculation names come from the input formula, every other cell
from ``format_cell`` of the record fetched again from SQLite by the row's result id, batch names from the recipe.
"""

import os
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hea_calc.core.composition import alloy_name, parse_formula  # noqa: E402
from hea_calc.core.results import format_cell  # noqa: E402

FORMULAS = ("Mo0.3CoCrFeNi", "AlCoCrFeNi", "HfNbTaTiZr")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    a = QApplication.instance() or QApplication([])
    load_fonts()
    return a


@pytest.fixture()
def win(app):
    from PySide6.QtCore import QEvent, QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1440, 1000)
    w.show()
    pump(app)
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


def pump(app, n=6):
    for _ in range(n):
        app.processEvents()


def calc_single(win, app, formula):
    comp = parse_formula(formula)
    win.calculate("single", [alloy_name(comp)], [comp], [{}])
    pump(app)


def wait_batch(win, app, timeout=180):
    t0 = time.perf_counter()
    while win.worker is not None and time.perf_counter() - t0 < timeout:
        pump(app, 2)
        time.sleep(0.01)
    assert win.worker is None, "batch did not finish"
    pump(app)
    win.table.model.refresh_committed()
    pump(app)


def double_click(win, app, r):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    m, view = win.table.model, win.table.view
    got = []

    def collect(rec):
        got.append(rec)

    view.details_requested.connect(collect)
    try:
        rect = view.visualRect(m.index(r, m.keys.index("name")))
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
        pump(app, 2)
    finally:
        view.details_requested.disconnect(collect)
    return got


def assert_rows_are_their_results(win, app, expected_names: dict[int, str] | None = None, click: bool = True):
    """Invariants A and B for every visible row: displayed cells == the stored result of the row's id; a double
    click analyses that id."""
    from PySide6.QtCore import Qt
    m = win.table.model
    reader = m.repo.reader
    assert m.rowCount() == len(m.page_rows())
    for r in range(m.rowCount()):
        rid = m.id_at(r)
        stored = reader.get(rid)                                  # fresh from SQLite, by id
        assert stored is not None, rid
        shown = [m.data(m.index(r, c), Qt.ItemDataRole.DisplayRole) for c in range(m.columnCount())]
        assert shown == [format_cell(stored, k) for k in m.keys], (r, rid, shown[:2], stored.name)
        if expected_names is not None:
            assert shown[m.keys.index("name")] == expected_names[rid], (r, rid)
        if click:
            got = double_click(win, app, r)
            assert [g.id for g in got] == [rid], (r, rid, got)
            assert win.analysis_ctl.state.active == rid


def ids_on_page(win):
    return [r.id for r in win.table.model.page_rows()]


# ---------------------------------------------------------------------------------------------- A, B, C
def test_consecutive_single_calculations_show_their_own_composition(win, app):
    """Test A + B + C: after each calculation every row (new and moved) shows its own result; newest first."""
    expected: dict[int, str] = {}
    for f in FORMULAS:
        before = {rid: n for rid, n in expected.items()}
        calc_single(win, app, f)
        ids = ids_on_page(win)
        new = max(ids)
        expected[new] = alloy_name(parse_formula(f))          # from the input, not from the table
        assert ids == sorted(ids, reverse=True), "Invariant C: newest result first without a column sort"
        assert ids[0] == new
        assert_rows_are_their_results(win, app, expected)
        for rid, name in before.items():                        # moved rows keep their result -> name mapping
            r = ids.index(rid)
            assert win.table.model.cell_text(r, win.table.model.keys.index("name")) == name


def test_top_row_never_repeats_the_previous_composition(win, app):
    """The reported symptom, literally: the second calculation's row must not read Mo0.3CoCrFeNi.  The table is
    painted after each calculation, as on screen (the delegate reads the cells through the model's cache)."""
    view = win.table.view
    calc_single(win, app, "Mo0.3CoCrFeNi")
    view.viewport().grab()
    calc_single(win, app, "AlCoCrFeNi")
    view.viewport().grab()
    m = win.table.model
    names = [m.cell_text(r, m.keys.index("name")) for r in range(m.rowCount())]
    assert names == ["AlCoCrFeNi", "Mo0.3CoCrFeNi"]


# ---------------------------------------------------------------------------------------------- D
def test_sorting_then_new_result_then_original_order(win, app):
    expected = {}
    for f in FORMULAS[:2]:
        calc_single(win, app, f)
        expected[max(ids_on_page(win))] = alloy_name(parse_formula(f))
    m = win.table.model
    m.sort_by("name")                                           # ascending
    m.wait()
    pump(app)
    assert_rows_are_their_results(win, app, expected, click=False)
    calc_single(win, app, FORMULAS[2])
    m.wait()
    pump(app)
    expected[max(ids_on_page(win))] = alloy_name(parse_formula(FORMULAS[2]))
    names = [m.cell_text(r, m.keys.index("name")) for r in range(m.rowCount())]
    assert names == sorted(names)
    assert_rows_are_their_results(win, app, expected)
    m.sort_by("name")                                           # descending
    m.wait()
    m.sort_by("name")                                           # third click: original order (newest first)
    m.wait()
    pump(app)
    assert m.sort_key is None
    ids = ids_on_page(win)
    assert ids == sorted(ids, reverse=True)
    assert_rows_are_their_results(win, app, expected)
    calc_single(win, app, "CoNi")                                # and a further result enters at the top
    expected[max(ids_on_page(win))] = "CoNi"
    assert ids_on_page(win)[0] == max(expected)
    assert_rows_are_their_results(win, app, expected)


# ---------------------------------------------------------------------------------------------- E
def test_undo_of_a_removal_and_paging_keep_row_identity(win, app):
    """Restoring removed rows re-enters them at the top (the same insertion path); paging re-reads the view."""
    expected = {}
    for f in FORMULAS:
        calc_single(win, app, f)
        expected[max(ids_on_page(win))] = alloy_name(parse_formula(f))
    m = win.table.model
    newest = max(expected)
    win.remove_results([m.row_at(0)])                           # row menu "Remove result" (undoable)
    pump(app)
    assert newest not in ids_on_page(win)
    assert_rows_are_their_results(win, app, expected)
    win.undo()
    pump(app)
    assert ids_on_page(win)[0] == newest
    assert_rows_are_their_results(win, app, expected)
    m.set_page_size(2)
    m.set_page(1)
    pump(app)
    assert_rows_are_their_results(win, app, expected)
    m.set_page(0)
    pump(app)
    assert_rows_are_their_results(win, app, expected)
    m.set_page_size(100)
    pump(app)
    assert_rows_are_their_results(win, app, expected)


def test_stored_results_are_unchanged_by_display(win, app):
    """Invariant D/E: the persisted record of each id carries the composition it was calculated from."""
    ids = []
    for f in FORMULAS:
        calc_single(win, app, f)
        ids.append(max(ids_on_page(win)))
    reader = win.table.model.repo.reader
    for rid, f in zip(ids, FORMULAS):
        rec = reader.get(rid)
        comp = parse_formula(f)
        tot = sum(comp.values())
        assert rec.name == alloy_name(comp)
        assert set(rec.composition) == set(comp)
        for el, x in comp.items():
            assert rec.composition[el] == pytest.approx(x / tot, abs=1e-12)


# ---------------------------------------------------------------------------------------------- F
def test_batch_workflows_after_singles_keep_row_identity(win, app, tmp_path):
    """Composition space, Expression and multi-row spreadsheet import stream rows into the same model (worker
    processes -> writer -> refresh_committed -> top insertion)."""
    from hea_calc.core.analysis import samples
    from hea_calc.core.spreadsheet import read_compositions
    calc_single(win, app, "Mo0.3CoCrFeNi")
    expected = {max(ids_on_page(win)): "Mo0.3CoCrFeNi"}
    m = win.table.model

    sweep = samples.SweepRecipe(tuple([samples.SweepSpec(el, 1.0, 1.0, 0.1, True) for el in ("Co", "Cr", "Fe", "Ni")]
                                      + [samples.SweepSpec("Al", 0.25, 0.75, 0.25, True)]), "ratio")
    win.calculate("sweep", None, sweep)
    wait_batch(win, app)
    names = sweep.materialise()["names"]
    new = sorted(set(ids_on_page(win)) - set(expected))
    assert len(new) == len(names)
    assert sorted(m.repo.reader.get(i).name for i in new) == sorted(names)
    expected.update({i: m.repo.reader.get(i).name for i in new})
    assert_rows_are_their_results(win, app, expected)

    expr = samples.expression_recipe("AlxCoCrFeNi", {"x": (0.0, 1.0, 0.5)})
    win.calculate("expression", None, expr)
    wait_batch(win, app)
    new = sorted(set(ids_on_page(win)) - set(expected))
    assert len(new) == len(expr.materialise()["names"])
    expected.update({i: m.repo.reader.get(i).name for i in new})
    assert_rows_are_their_results(win, app, expected)

    csv = tmp_path / "import.csv"
    csv.write_text("Name,Hf,Nb,Ta,Ti,Zr,Co,Ni,Fe\nimpA,1,1,1,1,1,0,0,0\nimpB,0,0,0,0,0,1,1,0\nimpC,0,0,0,0,0,0,1,1\n",
                   encoding="utf-8")
    res = read_compositions(csv, win.engine.data)
    assert not res.errors and len(res.entries) == 3
    win.calculate("import", [n for n, _ in res.entries], [c for _, c in res.entries], [{}] * 3)
    wait_batch(win, app)
    new = sorted(set(ids_on_page(win)) - set(expected))
    assert sorted(m.repo.reader.get(i).name for i in new) == ["impA", "impB", "impC"]
    expected.update({i: m.repo.reader.get(i).name for i in new})
    ids = ids_on_page(win)
    assert ids == sorted(ids, reverse=True)
    assert_rows_are_their_results(win, app, expected)


def test_keyboard_row_follows_its_result_when_rows_enter_above(win, app):
    """View state indexed by row (keyboard focus row) stays on the same result after a top insertion."""
    calc_single(win, app, "Mo0.3CoCrFeNi")
    calc_single(win, app, "AlCoCrFeNi")
    view, m = win.table.view, win.table.model
    view.kb_row = 1
    target = m.id_at(1)
    calc_single(win, app, "HfNbTaTiZr")
    assert m.id_at(view.kb_row) == target
