"""Audit of the materialised table views: deletion inside large sorted and filtered views,
progressive results while a sort/filter is active, stale builds, and export order."""

import csv
import os
import random
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hea_calc.core.repository import ResultRepository, ResultView, filter_sql, order_sql  # noqa: E402
from hea_calc.core.results import ModelFilter, RangeFilter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from synthetic import fill  # noqa: E402

N = 20_000
FLT = [RangeFilter("dhmix", None, -2.0), ModelFilter("M1", {"SS", "N/A"})]


@pytest.fixture()
def repo(engine, tmp_path):
    r = ResultRepository(engine, root=tmp_path / "s")
    yield r
    r.close()


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


@pytest.fixture()
def win(app):
    from hea_calc.ui.main_window import MainWindow
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1600, 900)
    w.show()
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def expected_ids(view, filters=(), sort=None, desc=False):
    """The order computed independently, straight from the dataset (the results table shows the newest result
    first when no column is sorted)."""
    where, params = filter_sql(filters)
    ids = [r[0] for r in view.repo.con.execute(
        f"SELECT result_id FROM results WHERE result_id BETWEEN ? AND ?{where} ORDER BY {order_sql(sort, desc)}",
        (view.lo, view.hi, *params))]
    if sort is None and view.reversed_order:
        ids.reverse()
    return ids


def assert_pages(view, expected, size=100):
    """Every page equals the expected slice: no gap, duplicate, skipped or misplaced record."""
    assert view.count() == len(expected)
    got = []
    for start in range(0, len(expected) + size, size):
        page = [r.id for r in view.page(start, size)]
        assert page == expected[start:start + size], start
        got += page
    assert got == expected and len(set(got)) == len(got)
    if expected:
        picks = {0, len(expected) // 2, len(expected) - 1} | {random.randrange(len(expected)) for _ in range(5)}
        for i in sorted(picks):
            assert view.position_of(expected[i]) == i


def double_click(win, app, r):
    vp = win.table.view.viewport()
    pos = win.table.view.visualRect(win.table.model.index(r, 2)).center()
    QApplication.sendEvent(vp, QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(pos), QPointF(vp.mapToGlobal(pos)),
                                           Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                           Qt.KeyboardModifier.NoModifier))
    app.processEvents()


# ------------------------------------------------------------------ deletion (audit item 3)
@pytest.mark.parametrize("filters, sort", [((), ("dhmix", True)), (FLT, (None, False)), (FLT, ("omega", False))])
def test_deleting_rows_in_a_large_view_keeps_every_page_exact(repo, engine, filters, sort):
    view = ResultView(repo)
    fill(repo, N, engine)
    view.refresh()
    view.request(filters=list(filters), sort=sort, wait=60)
    exp = expected_ids(view, filters, *sort)
    assert view.mat is not None and len(exp) > 1000
    assert_pages(view, exp)
    # first row, middle of a page, last row of a page, final row of the final page, first row of
    # the final page, then a run of three at the same position
    for where in (0, 150, 199, "last", "last page first", 300, 300, 301):
        logical = {"last": len(exp) - 1, "last page first": (len(exp) - 1) // 100 * 100}.get(where, where)
        rec = view.page(logical, 1)[0]
        assert rec.id == exp[logical]
        assert view.remove([rec]) == 1
        exp.pop(logical)
        assert repo.get_result(rec.id) is None
        assert_pages(view, exp)
    rec = view.page(10, 1)[0]
    assert view.remove([rec, rec]) == 1 and view.remove([rec]) == 0, "a record is removed once"
    exp.pop(10)
    assert_pages(view, exp)
    victims = view.page(500, 3)                          # several at once, from one page
    view.remove(victims)
    gone = {v.id for v in victims}
    exp = [i for i in exp if i not in gone]
    assert_pages(view, exp)
    view.request(sort=(None, False), filters=[], wait=60)
    assert_pages(view, expected_ids(view))
    assert view.total() == N - 12


def test_deleting_while_a_new_order_is_being_built(repo, engine):
    view = ResultView(repo)
    fill(repo, N, engine)
    view.refresh()
    first = view.page(0, 5)                              # natural page on screen
    assert not view.request(sort=("phi_king", True), wait=0)
    view.remove(first[1:3])                              # removed before the new order is applied
    view.wait()
    exp = expected_ids(view, (), "phi_king", True)
    assert first[1].id not in exp and len(exp) == N - 2
    assert_pages(view, exp)


def test_ui_deletions_keep_pages_and_details_ids_exact(win, app, engine):
    m = win.table.model
    fill(win.repo, N, engine)
    m.refresh_committed()
    m.set_filters([RangeFilter("dhmix", None, -2.0)])
    m.sort_by("omega")
    m.wait()
    exp = expected_ids(m.view, m.filters, "omega", False)
    for page, row in ((0, 0), (3, 50), (3, 99), (m.page_count() - 1, None)):
        m.set_page(page)
        app.processEvents()
        r = m.rowCount() - 1 if row is None else row
        victim = m.row_at(r)
        assert victim.id == exp[page * 100 + r]
        win.table.view._remove(victim)
        exp.remove(victim.id)
        app.processEvents()
        assert m.view_count() == len(exp)
        assert [x.id for x in m.page_rows()] == exp[m.page * 100:m.page * 100 + 100]
        double_click(win, app, 0)
        assert win.details.row.row_id == exp[m.page * 100]
    assert m.page == m.page_count() - 1


# ------------------------------------------------------------------ progressive results (audit item 4)
def test_a_late_build_never_overwrites_a_newer_view(repo, engine):
    view = ResultView(repo)
    fill(repo, N, engine)
    view.refresh()
    view.request(sort=("dhmix", False), wait=0)
    old = view.pending
    view.request(sort=("omega", True), wait=0)
    new = view.pending
    old.done.wait(30)
    new.done.wait(30)
    assert view.apply_task(new) and view.mat.table == new.table
    assert not view.apply_task(old), "a superseded build is ignored when it arrives late"
    assert view.mat.table == new.table and view.sort_key == "omega"
    assert_pages(view, expected_ids(view, (), "omega", True))


def test_a_filtered_view_rebuilt_while_extending_still_catches_up(repo, engine):
    view = ResultView(repo)
    fill(repo, 5_000, engine)
    view.refresh()
    view.request(filters=[RangeFilter("dhmix", None, -2.0)], wait=60)
    fill(repo, 3_000, engine)
    view.refresh()                                       # extend of the first filtered view in flight
    assert view._extending is not None
    view.request(filters=FLT, wait=0)                    # a new filter before that extend is delivered
    fill(repo, 2_000, engine)
    view.refresh()
    for _ in range(4):
        view.wait()
    assert view.hi == repo.committed_last
    assert_pages(view, expected_ids(view, FLT))


def test_a_sort_still_building_when_the_rows_stop_is_completed(app, repo, engine):
    from hea_calc.ui.widgets.results_table import ResultsModel
    m = ResultsModel(repo=repo)
    try:
        fill(repo, N, engine)
        m.refresh_committed()
        m.view.request(sort=("dhmix", True), wait=0)     # a background build of the current rows ...
        fill(repo, 4_000, engine)                         # ... while more rows are committed
        m.view.streaming = True
        m.refresh_committed(resort=False)                 # as the job runner does during a calculation
        m.finish_streaming()                              # the job ended
        t0 = time.perf_counter()
        while (m.view.pending is not None or m.view.stale) and time.perf_counter() - t0 < 30:
            app.processEvents()
            time.sleep(0.01)
        assert m.view.count() == m.view.total() == N + 4_000
        assert_pages(m.view, expected_ids(m.view, (), "dhmix", True))
    finally:
        m.close()


def run_sweep(win, app):
    for el in ("Fe", "Co", "Ni", "Cr", "Mn"):
        win.elements.table.tiles[el].click()
    win.composition.set_mode(1)
    win.composition.set_basis("at")
    for r in win.composition.sweep.rows.values():
        r.min.setText("2"), r.max.setText("32"), r.step.setText("2")       # 31 076 alloys
    from conftest import settle_composition
    settle_composition(win, app)
    t0 = time.perf_counter()
    win.composition.calc_btn.click()
    while win.worker is not None and time.perf_counter() - t0 < 120:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return time.perf_counter() - t0


@pytest.mark.parametrize("filters, sort", [((), ("dhmix", True)), (FLT[:1], (None, False)),
                                           (FLT[:1], ("omega", False))])
def test_progressive_results_under_a_sort_or_filter(win, app, engine, monkeypatch, filters, sort):
    m = win.table.model
    fill(win.repo, 2_000, engine)
    m.refresh_committed()
    if filters:
        m.set_filters(list(filters))
    if sort[0]:
        m.sort_by(sort[0])
        if sort[1]:
            m.sort_by(sort[0])
    m.wait()
    builds = []
    orig = ResultView.rebuild

    def counting(self, *a, **k):
        builds.append(time.perf_counter())
        return orig(self, *a, **k)
    monkeypatch.setattr(ResultView, "rebuild", counting)
    seconds = run_sweep(win, app)
    t0 = time.perf_counter()
    while (m.view.pending is not None or m.view._extending is not None) and time.perf_counter() - t0 < 30:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    if sort[0]:
        # back-off: at most one rebuild per 1.5 s of calculation, plus the final one
        assert len(builds) <= seconds / 1.5 + 2, (len(builds), seconds)
        gaps = [b - a for a, b in zip(builds, builds[1:-1])]
        assert all(g >= 1.4 for g in gaps), gaps
    else:
        assert builds == [], "a filtered view is extended with new rows, never rebuilt"
    exp = expected_ids(m.view, filters, *sort)
    assert m.view.count() == len(exp) and m.view.total() == 2_000 + 31_076
    assert_pages(m.view, exp)
    page = min(3, m.page_count() - 1)
    m.set_page(page)
    app.processEvents()
    double_click(win, app, 7)
    assert win.details.row.row_id == exp[page * m.page_size + 7]


# ------------------------------------------------------------------ export order (audit item 2)
def test_export_scopes_follow_the_current_sort_and_ignore_or_apply_filters(win, app, engine, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    m = win.table.model
    fill(win.repo, 3_000, engine)
    m.refresh_committed()
    m.set_filters([RangeFilter("dhmix", None, -2.0)])
    m.sort_by("omega")
    m.sort_by("omega")                                   # descending
    m.wait()
    fill(win.repo, 500, engine)                          # rows the sorted view does not hold yet
    names = {r[0]: r[1] for r in win.repo.con.execute("SELECT result_id, name FROM results")}
    for scope, filters in (("all", ()), ("filtered", list(m.filters))):
        for limit in (10**9, 10):                        # in-process and export-process paths
            monkeypatch.setattr(type(win), "INLINE_ROWS", limit)
            out = tmp_path / f"{scope}{limit}.csv"
            monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, o=out, **k: (str(o), ""))
            win.export("csv", scope)
            t0 = time.perf_counter()
            while win.exporter.running and time.perf_counter() - t0 < 60:
                app.processEvents()
                time.sleep(0.01)
            app.processEvents()
            with out.open(encoding="utf-8-sig") as fh:
                got = [r[0] for r in list(csv.reader(fh))[1:]]
            where, params = filter_sql(filters)
            exp = [names[r[0]] for r in win.repo.con.execute(
                f"SELECT result_id FROM results WHERE result_id >= ?{where} ORDER BY {order_sql('omega', True)}",
                (m.view.lo, *params))]
            assert got == exp, (scope, limit, len(got), len(exp))
            assert len(exp) == (3_500 if scope == "all" else len(exp))
