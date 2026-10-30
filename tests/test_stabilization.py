"""Stabilization pass (2026-10-25, second round): Qt thread hygiene, Expression throughput, Analysis loading, plot
colours, title-bar menus, Composition-space table, input hovers, tooltips, Elements properties, Documentation
header, and the external Analysis window.  Offscreen unless stated."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings, Qt, QThread, qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


def pump(app, seconds=0.0, n=4):
    end = time.monotonic() + seconds
    while True:
        for _ in range(n):
            app.processEvents()
        if time.monotonic() >= end:
            return
        time.sleep(0.01)


@pytest.fixture()
def win(app):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("light")
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1920, 1000)
    w.show()
    pump(app)
    yield w
    w.close()
    w.deleteLater()
    pump(app)


class QtMessages:
    """Collects Qt warnings (with the emitting thread) while active."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []

    def __enter__(self):
        def handler(_mode, _ctx, msg):
            self.messages.append((threading.current_thread().name, msg))
        self._old = qInstallMessageHandler(handler)
        return self

    def __exit__(self, *exc):
        qInstallMessageHandler(self._old)
        return False


# ====================================================================== 2. QBasicTimer
def test_reports_render_on_a_qthread_without_timer_warnings(app, engine, tmp_path):
    """Root cause: QTextDocument's layout starts a QBasicTimer; in a Python thread Qt printed "QBasicTimer can only be
    used with threads started with QThread" (9 times per composition report).  The job now runs on a QThread."""
    from hea_calc.core.results import ResultRow
    from hea_calc.ui.analysis.report_ui import ReportTask, _composition_job
    comp = {"Co": 1, "Cr": 1, "Fe": 1, "Mn": 1, "Ni": 1}
    row = ResultRow("CoCrFeMnNi", comp, engine.calculate(comp), "single", {})
    seen = {}

    def job(task, *args):
        seen["qthread"] = QThread.currentThread() is not QApplication.instance().thread()
        return _composition_job(task, *args)

    task = ReportTask()
    out = []
    task.finished.connect(lambda status, value: out.append((status, value)))
    path = str(tmp_path / "r.pdf")
    with QtMessages() as qt:
        task.start(job, row, None, path, 2.0)
        t0 = time.monotonic()
        while not out and time.monotonic() - t0 < 30:
            pump(app, 0.02)
    assert out and out[0][0] == "ok", out
    assert seen["qthread"], "the report job runs on a worker QThread"
    assert Path(path).stat().st_size > 1000 and out[0][1]["pages"] >= 1
    assert not [m for _t, m in qt.messages if "QBasicTimer" in m or "QThread" in m], qt.messages
    assert not task.running


# ====================================================================== 3. Expression throughput
EXPRESSIONS = [
    "(FeCoNi)1-x-y-z(AlTi)xCryCuz", "Al{x}CoCrFeNi", "(Fe1.6CoCr0.4Mn)0.9Al0.1", "((FeNi)1Co1)0.8Al0.2",
    "Ti{0.1*k}Fe{2-k}Co", "Fe{x^2}Co{1/x}Ni", "Mo_(1-y)Nb{y}Ta{y/2}W", "(FeCoNi)100-cAlc", "Fe{-x}Co", "Fe{x-1}CoNi",
    "(AlTi){x}(FeCo)1-x", "Fe{0*x}Co{x}Ni{x}",
]


@pytest.mark.parametrize("formula", EXPRESSIONS)
def test_compiled_evaluator_is_bit_identical_to_the_tree_evaluator(formula):
    import random
    from hea_calc.core.expression import evaluate_positive, parse_expression
    from hea_calc.core.expression_compile import compile_positive
    ex = parse_expression(formula)
    fn = compile_positive(ex)
    rnd = random.Random(7)
    values = [0.0, 1.0, 0.5, 1e-13, -1e-13, 2.0, 1e-9, 0.1, 0.3, 0.7]
    for _ in range(400):
        env = {v: rnd.choice(values) if rnd.random() < 0.3 else rnd.uniform(-0.2, 2.5) for v in ex.variables}
        try:
            ref = evaluate_positive(ex, env)
        except (TypeError, OverflowError, ZeroDivisionError) as exc:      # not an ExpressionError: both raise
            with pytest.raises(type(exc)):
                fn(env)
            continue
        got = fn(env)
        assert got == ref, (formula, env, got, ref)          # == on every float: same IEEE operations
        if ref is not None:
            assert list(got) == list(ref), "same element order"


def test_compiled_function_is_not_pickled_with_the_expression():
    import pickle
    from hea_calc.core.expression import ExpressionSpace, parse_expression
    from hea_calc.core.expression_doc import parse_document
    doc = parse_document("Al{x}CoCrFeNi\n0 <= x <= 1, step=0.5")
    space = ExpressionSpace(doc.expressions, doc.block_ranges)
    assert space.evaluate(1)[2] is not None                    # compiles and caches
    clone = pickle.loads(pickle.dumps(doc.expressions[0]))
    assert "_positive_fn" not in clone.__dict__ and clone.evaluate({"x": 0.5})


def test_sequential_iteration_matches_random_access():
    from hea_calc.core.expression import ExpressionSpace
    from hea_calc.core.expression_doc import parse_document
    doc = parse_document("CoCrFeNi\n\n(FeCoNi)1-x-y(AlTi)xCry\n0 <= x <= 1, step=0.25\n0 < y < 1, step=0.25\n\n"
                         "Al{z}CoCrFeNi\n0 <= z <= 1, points=3")
    space = ExpressionSpace(doc.expressions, doc.block_ranges)
    seq = list(space.iterate())
    assert len(seq) == space.total
    for g, b, env, pos in seq:
        assert (b, env, pos) == space.evaluate(g)
    assert list(space.iterate(5, 9)) == seq[5:9]
    assert list(space.iterate(space.total - 2, space.total + 5)) == seq[-2:]


def _recipe(text, with_counts):
    from hea_calc.core.expression import count_blocks_detail
    from hea_calc.core.expression_doc import parse_document
    from hea_calc.core.recipes import ExpressionRecipe
    doc = parse_document(text)
    d = count_blocks_detail(doc.expressions, doc.block_ranges)
    counts = (d["valid"], d["skipped"], d["duplicates"], d["combinations"],
              tuple((i, b[2]) for i, b in enumerate(d["blocks"]) if b[2])) if with_counts else None
    return ExpressionRecipe(tuple(doc.expressions), (), doc.text, tuple(tuple(b.items()) for b in doc.block_ranges),
                            counts)


@pytest.mark.parametrize("text, direct", [
    ("(FeCoNi)1-x-y-z(AlTi)xCryCuz\n0 <= x <= 1, step=0.1\n0 <= y <= 1, step=0.1\n0 <= z <= 1, step=0.1", True),
    ("Al{x}Co{x}CrFeNi\n0 <= x <= 2, step=0.5\n\nAlCoCrFeNi", False),       # duplicates: the plan stays
])
def test_direct_expression_jobs_store_exactly_what_the_plan_stores(engine, tmp_path, text, direct):
    from hea_calc.core.jobs import CalculationJob, CalculationService, Delivery, JobInput
    from hea_calc.core.repository import ResultRepository
    repo = ResultRepository(engine, root=tmp_path / "s")
    svc = CalculationService(workers=2, inprocess_max=5, channel=repo.writer.inbox)
    out = {}
    try:
        for label, with_counts in (("plan", False), ("counts", True)):
            recipe = _recipe(text, with_counts)
            assert recipe.dedupe is (not (with_counts and direct))
            meta = recipe.run_meta()
            run = repo.create_run(meta["mode"], source=meta["source"], axes=meta["axes"], elements=meta["elements"])
            w = repo.writer
            job = CalculationJob(JobInput("expression", (), recipe, (), {}), engine,
                                 Delivery(run, lambda i, ch, r=run: w.put_chunk(r, i, ch),
                                          lambda r=run: w.stored_chunks(r), lambda: bool(w.error), w.inbox))
            svc.start(job)
            job.wait(120)
            assert job.state == "done", job.error
            repo.finalize_run(run, "complete", upto=job.chunks_emitted)
            info = repo.get_run(run)
            t0 = time.monotonic()
            while repo.committed_last < info.last_id and time.monotonic() - t0 < 30:
                time.sleep(0.01)
            out[label] = ([(r.name, r.variables, r.block, r.raw("delta"), r.raw("dhmix"))
                           for r in repo.reader.iter_range(info.first_id, info.last_id)], job.plan_counts)
        assert out["plan"][0] == out["counts"][0] and out["plan"][0]
        assert out["plan"][1][:4] == out["counts"][1][:4]
    finally:
        svc.shutdown()
        repo.close()


# ====================================================================== 4. Analysis loading
@pytest.fixture()
def synth_repo(engine, tmp_path):
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    from synthetic import fill
    from hea_calc.core.repository import ResultRepository
    repo = ResultRepository(engine, root=tmp_path / "s")
    run = fill(repo, 6000, engine, chunk=2000)
    yield repo, run
    repo.close()


STATS_METRICS = ["dhmix", "dsmix", "delta", "vec", "omega", "phi_king", "gamma", "lambda"]


def test_per_metric_statistics_merge_equals_the_multi_metric_query(synth_repo):
    """Statistics now run one query per metric (in parallel, cached per metric); every number must equal what
    the multi-metric query returns - exactly, not approximately."""
    from hea_calc.core.analysis.queries import ScopeQuery, merge_statistics
    from hea_calc.core.analysis.scope import CollectionScope
    repo, run = synth_repo
    con = repo.reader_connection()
    try:
        sq = ScopeQuery(con, CollectionScope(run), repo.get_run(run), 0)
        whole = sq.statistics(STATS_METRICS)
        merged = merge_statistics([sq.statistics([m]) for m in STATS_METRICS])
        for exact_limit in (10, ):                   # the binned (approximate) path merges identically too
            binned = sq.statistics(STATS_METRICS, exact_limit=exact_limit)
            parts = merge_statistics([sq.statistics([m], exact_limit=exact_limit) for m in STATS_METRICS])
            assert binned["metrics"] == parts["metrics"] and binned["exact"] is parts["exact"] is False
        out = sq.outliers("delta", sq.statistics(["delta"]))
        assert out == sq.outliers("delta"), "outliers from known statistics = outliers recalculated"
    finally:
        con.close()
    assert merged.pop("pending") == ()
    assert merged == whole                           # dict equality: every float compared with ==


def test_query_runner_prioritises_waiting_views_and_never_delivers_cancelled_jobs(app, synth_repo):
    from hea_calc.ui.analysis.controller import QueryRunner
    from hea_calc.core.analysis.scope import CollectionScope
    repo, run = synth_repo
    info = repo.get_run(run)
    runner = QueryRunner(repo, threads=1)
    got, order = {}, []
    runner.finished.connect(lambda tok, res, err: got.__setitem__(tok, (res, err)))
    gate = threading.Event()
    try:
        blocker = runner.submit(CollectionScope(run), info, 0, lambda sq: gate.wait(10) and sq.count())
        low = runner.submit(CollectionScope(run), info, 0, lambda sq: order.append("prefetch") or 1, priority=1)
        high = runner.submit(CollectionScope(run), info, 0, lambda sq: order.append("view") or 2, priority=0)
        dropped = runner.submit(CollectionScope(run), info, 0, lambda sq: order.append("dropped") or 3)
        runner.cancel(dropped)
        gate.set()
        t0 = time.monotonic()
        while len(got) < 3 and time.monotonic() - t0 < 20:
            pump(app, 0.01)
        pump(app, 0.1)
        assert order == ["view", "prefetch"], "a waiting view runs before prefetch; a cancelled job never runs"
        assert got[blocker] == (6000, None) and got[high] == (2, None) and got[low] == (1, None)
        assert dropped not in got and runner.idle
    finally:
        gate.set()
        runner.close()


def test_controller_shares_one_query_between_slots_and_fills_statistics_progressively(app, synth_repo):
    from hea_calc.ui.analysis.controller import AnalysisController
    from hea_calc.core.analysis import state as S
    from hea_calc.core.analysis.scope import CollectionScope
    repo, run = synth_repo
    c = AnalysisController(repo)
    c.prefetch_enabled = False
    calls = []
    try:
        c.resolve(CollectionScope(run))
        assert c.wait_idle(30)
        c.cache.clear()

        def pop(sq):
            calls.append(1)
            return sq.population()
        c.run_query("options", pop, share="population")
        c.run_query("population", pop)
        assert len(c._by_token) == 1, "the same answer for two slots is one background job"
        assert c.wait_idle(30) and len(calls) == 1
        assert c.data["options"] == c.data["population"] and c.data["population"]["n"] == 6000
        published = []
        c.data_ready.connect(lambda slot: published.append(dict(c.data["stats"])) if slot == "stats" else None)
        c.apply(S.update, stats_metrics=("dhmix", "delta", "vec"))
        c.request_statistics(("dhmix", "delta", "vec"))
        assert c.busy("stats")
        assert c.wait_idle(30) and not c.busy("stats")
        assert published and published[-1]["pending"] == ()
        assert all(set(p["metrics"]) | set(p["pending"]) == {"dhmix", "delta", "vec"} for p in published)
        # adding one metric calculates only that metric (the others come from the per-metric cache)
        before = len(c.cache)
        c.request_statistics(("dhmix", "delta", "vec", "omega"))
        assert len(c._by_token) == 1
        assert c.wait_idle(30) and len(c.cache) == before + 1
        assert set(c.data["stats"]["metrics"]) == {"dhmix", "delta", "vec", "omega"}
        # a cancelled statistics request is never published
        c.cache.clear()
        n_pub = len(published)
        c.request_statistics(("gamma", "lambda"))
        c.cancel("stats")
        assert c.wait_idle(30) and len(published) == n_pub and not c.busy("stats")
    finally:
        c.close()


# ====================================================================== 5. Plot colours
def _contrast(a: str, b: str) -> float:
    def lum(h):
        h = h.lstrip("#")[-6:]
        r, g, bl = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl)
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_plot_marks_are_visible_on_the_panel_in_both_themes(app, theme):
    """Points coloured by a numeric metric used the full Carbon blue ramp, whose end step is the panel colour
    (Blue 10 on White, Blue 100 on Gray 90-100): the lowest / highest values vanished.  Marks now keep >= 3:1."""
    from hea_calc.ui.analysis import plot as P
    from hea_calc.ui.theme import THEME, t
    THEME.set_theme(theme)
    try:
        bg = t("layer-01")
        for i in range(21):
            assert _contrast(P.sequential_mark(i / 20), bg) >= 3.0, (theme, i / 20, P.sequential_mark(i / 20))
        for i in range(10):                                   # cells: never the panel colour itself
            assert _contrast(P.sequential(i / 9), bg) >= 1.5, (theme, i, P.sequential(i / 9))
        for col in (P.CATEGORICAL_DARK if theme == "dark" else P.CATEGORICAL_LIGHT):
            assert _contrast(col, bg) >= 3.0, col
    finally:
        THEME.set_theme("light")


def test_category_colours_are_deterministic_and_shared_by_every_plot_type(app):
    """Binned and heatmap cells were coloured with ``hash(value) % 9`` - a per-process random string hash, so the
    same expression block changed colour between sessions and never matched the scatter legend."""
    import subprocess
    import sys as _sys
    from hea_calc.ui.analysis.plot import PlotSpec, PlotWidget, category_colors
    code = ("import os;os.environ['QT_QPA_PLATFORM']='offscreen';from PySide6.QtWidgets import QApplication;"
            "a=QApplication([]);from hea_calc.ui.analysis.plot import category_colors as c;"
            "print(c('family', ['FeCoNi','AlCoCrFeNi','CoCr']))")
    runs = {subprocess.run([_sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT),
                           env={**os.environ, "PYTHONHASHSEED": seed}).stdout.strip() for seed in ("1", "2", "3")}
    assert len(runs) == 1 and runs != {""}, runs
    blocks = category_colors("block", [2, 0, 1])
    assert list(blocks) == [0, 1, 2] and len(set(blocks.values())) == 3
    w = PlotWidget()
    w.set_spec(PlotSpec("scatter", {"x": [1, 2, 3], "y": [1, 2, 3], "c": [0, 1, 2]}, color="block"))
    assert w._color_map() == blocks, "scatter legend = binned / heatmap cells"


def test_binned_plots_report_their_category_counts_for_the_legend(synth_repo):
    from hea_calc.core.analysis.queries import ScopeQuery
    from hea_calc.core.analysis.scope import CollectionScope
    repo, run = synth_repo
    con = repo.reader_connection()
    try:
        sq = ScopeQuery(con, CollectionScope(run), repo.get_run(run), 0)
        b = sq.binned("delta", "dhmix", (40, 40), "model:M2")
        assert b["category_counts"] and sum(b["category_counts"].values()) == b["n_valid"]
        assert "category_counts" not in sq.binned("delta", "dhmix", (40, 40), "vec")
    finally:
        con.close()


# ====================================================================== 6. Title-bar menu seam (native)
@pytest.mark.skipif(os.environ.get("HEA_NATIVE_TESTS") != "1", reason="native Windows check (HEA_NATIVE_TESTS=1)")
@pytest.mark.parametrize("maximized", [False, True])
def test_open_header_menu_leaves_no_unpainted_device_row(maximized):
    """At 125 % the trigger's shadow window and the menu window were rounded to device pixels separately; one
    device row between them was never painted (a white line beside the open trigger in the light theme)."""
    import subprocess
    import sys as _sys
    code = r'''
import sys, tempfile, time
from pathlib import Path
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
from hea_calc.ui.theme import THEME, load_fonts
load_fonts(); THEME.set_theme("light")
from hea_calc.ui.main_window import MainWindow
from hea_calc.ui.widgets.header import HeaderMenuItem
from hea_calc.ui.widgets.menu import _native_gap
w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
w.resize(1300, 800); w.move(37, 41)
w.showMaximized() if MAX else w.show()
end = time.monotonic() + 1.0
while time.monotonic() < end: app.processEvents()
gaps = []
for it in [i for i in w.findChildren(HeaderMenuItem) if i.menu_ is not None and i.isVisible()]:
    def check(it=it):
        ov = it.menu_._overlay
        gaps.append(None if ov is None else _native_gap(ov, it.menu_))
        it.menu_.close()
    QTimer.singleShot(250, check)
    it.click()
print("GAPS", gaps)
w.close()
'''.replace("MAX", str(maximized))
    r = subprocess.run([_sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), timeout=120,
                       env={k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"})
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("GAPS")]
    assert line, r.stdout + r.stderr
    gaps = eval(line[0][5:])
    assert gaps and all(g is not None and g <= 0 for g in gaps), gaps


# ====================================================================== 7. Restored menu contents
def test_title_bar_menus_are_complete_and_every_action_works(win, app, monkeypatch):
    from PySide6.QtGui import QKeySequence
    labels = {name: [a.text() for a in m.actions() if a.isVisible()]
              for name, m in (("file", win.file_menu), ("edit", win.edit_menu), ("help", win.help_menu))}
    assert labels["file"] == ["Import compositions…", "Export results…", "", "Calculation settings…", "", "Exit"]
    assert labels["edit"][:2] and labels["edit"][-1] == "Copy table"
    assert labels["help"] == ["Getting started", "Documentation", "", "Expression syntax", "Model support",
                              "Keyboard shortcuts", "", "About MDL HEA Calculator"]
    # shortcut labels are shown and are real window shortcuts
    sc = {a.text(): a.shortcut().toString() for m in (win.file_menu, win.edit_menu, win.view_menu, win.help_menu)
          for a in m.actions() if not a.shortcut().isEmpty()}
    assert sc["Import compositions…"] == "Ctrl+O" and sc["Exit"] == "Ctrl+Q" and sc["Top panels"] == "Ctrl+B"
    assert sc["Full screen"] == "F11" and sc["Documentation"] == "F1" and sc["Copy table"] == "Ctrl+Shift+C"
    assert all(m.property("show_shortcuts") is not False for m in (win.file_menu, win.view_menu))
    window_keys = {a.shortcut().toString() for a in win.actions()}
    assert {"Ctrl+O", "Ctrl+Q", "Ctrl+B", "F11", "F1", "Ctrl+Shift+C"} <= window_keys
    # Help items open their pages (no dead action)
    pages = []
    monkeypatch.setattr(win, "show_help", lambda page="home", anchor="": pages.append(page))
    for a in win.help_menu.actions():
        if a.text() and not a.text().startswith("About"):
            a.trigger()
    from hea_calc.core import docs
    assert pages == ["first-calculation", "home", "expression-syntax", "model-coverage", "shortcuts"]
    assert all(p in docs.ORDER for p in pages)
    # Ctrl+B toggles the top panels; the action's check follows
    win.top_panels_action.trigger()
    pump(app)
    assert not win.top_panels_visible() and not win.top_panels_action.isChecked()
    win.top_panels_action.trigger()
    pump(app)
    assert win.top_panels_visible() and win.top_panels_action.isChecked()
    # Alt+F / Alt+E / Alt+V / Alt+H shortcuts exist for the four menus
    keys = sorted(s.key().toString() for s in win._menu_keys)
    assert keys == ["Alt+E", "Alt+F", "Alt+H", "Alt+V"]
    _ = QKeySequence


# ====================================================================== 9. Composition space table (Figma 393:66042)
def test_composition_space_header_and_locks_follow_the_figma_geometry(win, app):
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QLabel
    comp = win.composition
    comp.set_mode(1)
    for el in ("Fe", "Co", "Ni"):
        win.elements.table.tiles[el].click()
    pump(app, 0.1)
    sw = comp.sweep
    panel = comp
    heads = [w for w in sw.findChildren(QLabel) if w.objectName() == "ColHeader" and w.isVisible()]
    texts = [h.text() for h in heads]
    assert texts[:3] == ["Elem.", "Min", "Max"] and "Lock" not in texts, texts
    # the Step heading is the Figma inline Small dropdown (Step size | Points), 88 x 32, text at +16
    assert sw.h_step.current_html() == "Step" and (sw.h_step.width(), sw.h_step.height()) == (88, 32)
    for h in heads[:3]:
        assert h.font().weight() == QFont.Weight.Normal, (h.text(), h.font().weight())
        assert h.font().pixelSize() == 14 or h.font().pointSizeF() > 0
    x = lambda w: w.mapTo(panel, w.rect().topLeft()).x()  # noqa: E731
    assert x(heads[0]) == 47, "the table starts at x = 47"
    assert [x(h) for h in heads[1:3]] + [x(sw.h_step)] == [112, 201, 290], "64 / 88 / 88 / 88 px, 1 px gaps"
    assert all(h.contentsMargins().left() == 16 for h in heads[:3]), "text on the 16 px cell inset"
    assert sw.h_step.width() - sw.h_step.chevron_inset - 16 == 62, "Figma: the chevron at x + 62"
    row = sw.rows["Fe"]
    icon_left = row.lock.mapTo(panel, row.lock.rect().topLeft()).x() + (row.lock.width() - 16) // 2
    assert row.lock.size().width() == 32 and icon_left == 387, icon_left
    assert panel.width() == 457
    # Figma (re-inspected 2026-10-26): the lock Button has a 1 px bottom border, border-strong (contextual)
    from hea_calc.ui.theme import t
    cell = row.lock.parentWidget()
    assert cell.objectName() == "LockCell"
    img = cell.grab().toImage()
    bottom = {img.pixelColor(xx, img.height() - 1).name() for xx in range(4, img.width() - 4, 4)}
    assert bottom == {t("border-strong-01")}, bottom


# ====================================================================== 10. Input hover states
def _hovered(app, f, on=True):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent
    if on:
        app.sendEvent(f, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    f.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, on)
    if not on:
        app.sendEvent(f, QEvent(QEvent.Type.Leave))
    f.update()
    pump(app)
    return f.grab().toImage()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_enabled_composition_inputs_have_a_hover_that_never_replaces_focus_or_error(win, app, theme):
    from hea_calc.ui.theme import THEME, t
    THEME.set_theme(theme)
    pump(app)
    comp = win.composition
    for el in ("Fe", "Co"):
        win.elements.table.tiles[el].click()
    comp.set_mode(1)
    pump(app, 0.1)
    row = comp.sweep.rows["Fe"]
    for f in (row.el, row.min, row.step, comp.sweep.all_max):
        mid = (f.width() - 6, f.height() // 2)
        base = _hovered(app, f, False).pixelColor(*mid).name()
        hot = _hovered(app, f, True).pixelColor(*mid).name()
        assert (base, hot) == (t("field-02"), t("field-hover-02")), (f.accessibleName(), base, hot)
        _hovered(app, f, False)
    # error has priority: the 2 px error frame stays while hovered; text never moves (same margins)
    f = row.max
    m0 = f.textMargins()
    f.set_invalid(True, "x")
    img = _hovered(app, f, True)
    assert img.pixelColor(0, f.height() // 2).name() == t("support-error")
    assert f.textMargins() == m0
    f.set_invalid(False)
    _hovered(app, f, False)
    # disabled: no hover
    f.setEnabled(False)
    a = _hovered(app, f, False).pixelColor(f.width() - 6, f.height() // 2).name()
    b = _hovered(app, f, True).pixelColor(f.width() - 6, f.height() // 2).name()
    assert a == b
    f.setEnabled(True)


# ====================================================================== 12. Tooltip delay
def test_hover_tooltips_wait_400_ms_and_a_quick_sweep_over_the_locks_shows_none(win, app):
    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent
    from hea_calc.ui.widgets.tooltip import ENTER_DELAY_MS, install_tooltips

    def _enter():
        return QEnterEvent(QPointF(4, 4), QPointF(4, 4), QPointF(4, 4))
    assert ENTER_DELAY_MS == 400
    ctl = install_tooltips(app)
    # earlier tests leave the synthetic cursor over the window, where Qt's own "pointer resting" tooltip event
    # would open some other widget's tooltip mid-sweep: park it off-window, then start from no tooltip
    from PySide6.QtCore import QPoint as _QP
    from PySide6.QtGui import QCursor
    QCursor.setPos(_QP(-5000, -5000))
    pump(app, 0.05)
    ctl.hide()
    comp = win.composition
    for el in ("Fe", "Co", "Ni", "Cr", "Mn"):
        win.elements.table.tiles[el].click()
    comp.set_mode(1)
    pump(app, 0.1)
    locks = [r.lock for r in comp.sweep.rows.values()]
    assert all(lk.toolTip() for lk in locks)
    # the pointer sweeps down the lock column (150 ms per lock): no tooltip at all
    # (timing is asserted from the measured wait: under full-suite load a 150 ms wait can overrun the delay)
    for lk in locks:
        QApplication.sendEvent(lk, _enter())
        assert ctl._enter.isActive() and ctl._enter.interval() == ENTER_DELAY_MS and not ctl.visible()
        t0 = time.monotonic()
        QTest.qWait(150)
        if time.monotonic() - t0 < (ENTER_DELAY_MS - 20) / 1000:
            assert not ctl.visible(), ("no tooltip while sweeping", ctl._source)
        QApplication.sendEvent(lk, QEvent(QEvent.Type.Leave))
        assert not ctl._enter.isActive() and ctl._pending is None and not ctl.visible(), "leaving cancels the delay"
    QTest.qWait(ENTER_DELAY_MS + 100)
    assert not ctl.visible(), "a cancelled delay never fires later"
    # resting on one lock shows it after the delay, not before
    lk = locks[2]
    QApplication.sendEvent(lk, _enter())
    t0 = time.monotonic()
    QTest.qWait(250)
    if time.monotonic() - t0 < (ENTER_DELAY_MS - 20) / 1000:
        assert not ctl.visible()
    end = time.monotonic() + 3.0
    while not ctl.visible() and time.monotonic() < end:
        QTest.qWait(20)
    assert ctl.visible() and ctl._source is lk
    # a click hides it (its text may now be outdated) and a pending tooltip is cancelled by a click
    QTest.mouseClick(lk, Qt.MouseButton.LeftButton)
    pump(app)
    assert not ctl.visible()
    QApplication.sendEvent(lk, QEvent(QEvent.Type.Leave))
    QApplication.sendEvent(lk, _enter())
    QTest.qWait(100)
    QTest.mousePress(lk, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(lk, Qt.MouseButton.LeftButton)
    QTest.qWait(ENTER_DELAY_MS + 100)
    assert not ctl.visible()
    QApplication.sendEvent(lk, QEvent(QEvent.Type.Leave))
    ctl.hide()


# ====================================================================== 11. Elements properties
def test_element_properties_are_grouped_by_category_labelled_with_sources_and_never_clipped(win, app):
    from hea_calc.ui.widgets.dropdown import html_width
    from hea_calc.ui.theme import LABEL_01, t
    info = win.elements.info
    props = [[prop for _k, prop, *_r in g] for g in info.GROUPS]
    assert props == [["density", "melting_point", "molar_volume"],
                     ["atomic_weight", "atomic_radius", "atomic_radius_cn12"],
                     ["nvalence", "work_function_phi", "n_ws"],
                     ["bulk_modulus", "shear_modulus"]]
    tips = {prop: tip for g in info.GROUPS for _k, prop, _f, _s, tip in g}
    # 2026-10-28 (C2): the tooltips define the property and its use; the sources are in Documentation
    assert "M2–M5" in tips["atomic_radius"] and "different radius set" in tips["atomic_radius_cn12"]
    # no value of any element is clipped by its group (keys and values measured from the dataset)
    for el in info.data.elements:
        info.show_element(el)
        for gi, g in enumerate(info.GROUPS):
            for _k, prop, fmt, sc, _t in g:
                v, *_ = info.values[prop]
                need = html_width(v.text(), LABEL_01)
                assert info.KEY_WIDTHS[gi] + need <= info.group_wraps[gi].width(), (el, prop, v.text())
    info.show_element("Fe")
    pump(app)
    v, *_ = info.values["density"]
    assert v.palette().windowText().color().name() == t("text-primary")
    # formatting only: the shown value is the dataset value (moduli 1e10 Pa -> GPa)
    assert info.values["bulk_modulus"][0].text() == f"{info.data.prop('Fe', 'bulk_modulus') * 10:.1f} GPa"


# ====================================================================== 14-17. The separate Analysis window
def _rows(win, n=30):
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    from screenshot import demo_rows
    demo_rows(win, n)
    pump(app=QApplication.instance())


def _mouse(view, kind, r, c=2):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    vp = view.viewport()
    pos = view.visualRect(view.model().index(r, c)).center()
    QApplication.sendEvent(vp, QMouseEvent(kind, QPointF(pos), QPointF(vp.mapToGlobal(pos)), Qt.MouseButton.LeftButton,
                                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def test_double_click_with_hidden_top_panels_opens_and_reuses_the_analysis_window(win, app):
    from PySide6.QtCore import QEvent
    from hea_calc.core.analysis import state as S
    _rows(win)
    v, m = win.table.view, win.table.model
    win.set_top_panels_visible(False)
    pump(app)
    # single click, press/release, sorting and hover never open it
    _mouse(v, QEvent.Type.MouseButtonPress, 1)
    _mouse(v, QEvent.Type.MouseButtonRelease, 1)
    _mouse(v, QEvent.Type.MouseMove, 2)
    m.sort_by("omega")
    m.wait()
    pump(app)
    assert win.analysis_window(create=False) is None or not win.analysis_window(create=False).isVisible()
    # double click: the window opens with that composition (Composition context)
    _mouse(v, QEvent.Type.MouseButtonDblClick, 3)
    pump(app)
    aw = win.analysis_window(create=False)
    assert aw is not None and aw.isVisible()
    assert aw.panel.row.row_id == m.row_at(3).id and win.analysis_ctl.state.context == S.COMPOSITION
    # a second double click reuses the same window (never a duplicate) and updates it
    _mouse(v, QEvent.Type.MouseButtonDblClick, 5)
    pump(app)
    tops = [w for w in QApplication.topLevelWidgets() if w.objectName() == "AnalysisWindow" and w.isVisible()]
    assert tops == [aw] and aw.panel.row.row_id == m.row_at(5).id
    # with the top panels visible a double click goes to the embedded panel - and the open window follows
    win.set_top_panels_visible(True)
    pump(app)
    _mouse(v, QEvent.Type.MouseButtonDblClick, 7)
    pump(app)
    assert win.analysis.row.row_id == m.row_at(7).id == aw.panel.row.row_id
    aw.close()
    pump(app)
    assert not aw.isVisible() and win.isVisible(), "closing the Analysis window does not close the application"


def test_keyboard_enter_on_a_results_row_is_the_double_click(win, app):
    from PySide6.QtTest import QTest
    _rows(win)
    v, m = win.table.view, win.table.model
    win.set_top_panels_visible(False)
    pump(app)
    assert v.focusPolicy() == Qt.FocusPolicy.TabFocus
    v.setFocus(Qt.FocusReason.TabFocusReason)
    pump(app)
    assert v.kb_row == 0
    QTest.keyClick(v, Qt.Key.Key_Down)
    QTest.keyClick(v, Qt.Key.Key_Down)
    assert v.kb_row == 2
    QTest.keyClick(v, Qt.Key.Key_Return)
    pump(app)
    aw = win.analysis_window(create=False)
    assert aw is not None and aw.isVisible() and aw.panel.row.row_id == m.row_at(2).id
    aw.close()


def test_the_analysis_window_is_a_normal_window_with_the_full_shared_analysis(win, app, monkeypatch):
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis.panel import overflow_menu
    _rows(win)
    aw = win.open_analysis_window(win.table.model.row_at(0))
    pump(app)
    # the compact layout is checked here: from workspace.wide_layout_min() on the window shows the workspace layout
    # instead (2026-10-27, test_ui_refinement_pass.py::test_floating_analysis_layout_follows_its_width)
    aw.resize(900, 700)
    pump(app)
    assert not aw.wide
    flags = aw.windowFlags()
    assert aw.parentWidget() is None, "unowned: its own taskbar button and Alt+Tab entry"
    assert flags & Qt.WindowType.Window and not aw.isModal()
    for hint in (Qt.WindowType.WindowMinimizeButtonHint, Qt.WindowType.WindowMaximizeButtonHint,
                 Qt.WindowType.WindowCloseButtonHint):
        assert flags & hint or not (flags & Qt.WindowType.CustomizeWindowHint), hint
    # the same panel as the embedded one: Composition and Collection with every tab, no collapse / expand
    p = aw.panel
    assert p.external and not p.collapse_btn.isVisible() and not p.expand_btn.isVisible()
    assert [b.text() for b in p.coll_tabs.buttons] == list(S.COLL_TAB_LABELS)
    # no footer Export button; export lives in the Options menu (the shared overflow actions)
    from PySide6.QtWidgets import QPushButton
    assert not [b for b in aw.findChildren(QPushButton) if "Export" in b.text() and b.isVisible()]
    labels = [a.text() for a in overflow_menu(p, win.analysis_ctl).actions()]
    assert "Export composition report…" in labels and "Open in new window" not in labels
    main_labels = [a.text() for a in overflow_menu(win.analysis, win.analysis_ctl).actions()]
    assert "Open in new window" in main_labels, "the former dead item now opens this window"
    # state sync both ways: switching context / tab in the window changes the embedded panel too
    p.switcher.changed.emit(1)
    p.coll_tabs.changed.emit(S.COLL_TABS.index("statistics"))
    pump(app)
    assert win.analysis_ctl.state.context == S.COLLECTION and p.coll_tabs.index() == S.COLL_TABS.index("statistics")
    # the embedded panel shows the same state as soon as the main window is the one in use (while the window is
    # in use the embedded panel is suspended and catches up once - test_only_the_analysis_view_in_use_renders_...)
    monkeypatch.setattr(win, "_owns_active_window", lambda: True)
    win.sync_analysis_suspension()
    pump(app)
    assert not win.analysis.suspended
    assert win.analysis.content_stack.currentIndex() == 1 and \
        win.analysis.coll_tabs.index() == S.COLL_TABS.index("statistics")
    # responsive: its own size class from its own width
    aw.resize(600, 600)
    pump(app)
    assert p.size_class == "S"
    aw.resize(1300, 800)
    pump(app)
    assert p.size_class == "L"
    # wide enough for the expanded workspace's readable layout: the window shows that layout instead
    from hea_calc.ui.analysis.workspace import wide_layout_min
    aw.resize(wide_layout_min() + 100, 800)
    pump(app)
    assert aw.wide and aw.current_view() is aw.workspace and aw.panel.suspended
    # the theme reaches the unowned window too
    from hea_calc.ui.theme import THEME
    win.set_theme("dark")
    pump(app)
    assert aw.styleSheet() == win.styleSheet() and THEME.name == "dark"
    win.set_theme("light")
    aw.close()


def test_closing_the_main_window_destroys_the_analysis_window(app):
    from hea_calc.ui.main_window import MainWindow
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.show()
    pump(app)
    aw = w.open_analysis_window()
    pump(app)
    assert aw.isVisible()
    w.close()
    pump(app, 0.2)
    assert not [x for x in QApplication.topLevelWidgets() if x.objectName() == "AnalysisWindow" and x.isVisible()]


# ====================================================================== Title bar inactive state
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_whole_title_bar_steps_down_when_the_window_is_inactive(win, app, theme):
    from PySide6.QtGui import QColor
    from hea_calc.ui.theme import THEME, t
    from hea_calc.ui.widgets.header import CAPTION
    THEME.set_theme(theme)
    win.apply_theme()
    pump(app)
    bar = win.header

    def fg(widget):
        """the foreground colour of a title-bar part: its pixel furthest from the bar background (grabbed from the
        bar, which paints that background)"""
        from PySide6.QtCore import QRect
        img = bar.grab(QRect(widget.mapTo(bar, QPoint(0, 0)), widget.size())).toImage()
        bg = QColor(bar.surface())
        best, bd = None, -1
        for x in range(0, img.width()):
            for y in range(img.height() // 4, 3 * img.height() // 4):
                c = img.pixelColor(x, y)
                d = abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue())
                if d > bd:
                    bd, best = d, c
        return best.name()

    def mix(fgc, alpha):
        a, b = QColor(fgc), QColor(bar.surface())
        return QColor(round(a.red() * alpha + b.red() * (1 - alpha)), round(a.green() * alpha + b.green() * (1 - alpha)),
                      round(a.blue() * alpha + b.blue() * (1 - alpha))).name()

    def label(item):          # a stylesheet-drawn label: its resolved text colour (pixels are checked natively)
        item.ensurePolished()
        return item.palette().buttonText().color().name()

    bar.set_window_active(True)
    pump(app)
    active = {"site": fg(bar.name), "file": label(bar.file_item), "icon": fg(bar.panels_btn)}
    assert active == {"site": t("text-primary"), "file": t("text-secondary"), "icon": t("icon-primary")}, active
    bar.set_window_active(False)
    pump(app)
    inactive = {"site": fg(bar.name), "file": label(bar.file_item), "icon": fg(bar.panels_btn)}
    assert inactive == {"site": t("titlebar-inactive-title"), "file": t("titlebar-inactive-text"),
                        "icon": t("titlebar-inactive-text")}, inactive
    # the inactive surface: subtle but distinct from the active one, and painted by the bar itself
    img = bar.grab().toImage()
    assert img.pixelColor(bar.width() // 2 + 40, 2).name() in (t("titlebar-inactive"),), "the inactive surface"
    assert t("titlebar-inactive") != t("shell")
    assert 1.03 <= _contrast(t("titlebar-inactive"), t("shell")) <= 1.35, "subtle, not a different component"
    # contrast: title >= 4.5:1, menus / icons >= 3:1 on the inactive surface; never the disabled colour
    assert _contrast(t("titlebar-inactive-title"), t("titlebar-inactive")) >= 4.5
    assert _contrast(t("titlebar-inactive-text"), t("titlebar-inactive")) >= 3.0
    assert t("titlebar-inactive-text") != t("text-disabled") and t("titlebar-inactive-title") != t("text-disabled")
    # more muted than active: lower contrast than the active colour on the active surface
    assert _contrast(t("titlebar-inactive-title"), t("titlebar-inactive")) < _contrast(t("text-primary"), t("shell"))
    assert _contrast(t("titlebar-inactive-text"), t("titlebar-inactive")) < _contrast(t("text-secondary"), t("shell"))
    assert all(it.property("inactive") for it in bar.menu_items)
    # the caption glyphs take the Windows 11 kit's Inactive=True value (36 % of the foreground)
    g = QColor(fg(bar.close_btn))
    want = QColor(mix(t("text-primary"), CAPTION["inactive_alpha"]))
    assert abs(g.lightness() - want.lightness()) <= 12, (g.name(), want.name())
    # inactive is not disabled: every control still works
    assert all(w.isEnabled() for w in (*bar.menu_items, bar.panels_btn, bar.min_btn, bar.max_btn, bar.close_btn))
    # back: the exact active colours
    bar.set_window_active(True)
    pump(app)
    assert {"site": fg(bar.name), "file": label(bar.file_item), "icon": fg(bar.panels_btn)} == active
    THEME.set_theme("light")
    win.apply_theme()


def test_inactive_title_bar_drops_stale_hover_and_keeps_the_run_status(win, app):
    from PySide6.QtGui import QCursor
    bar = win.header
    bar.set_window_active(True)
    QCursor.setPos(QPoint(-4000, -4000))
    b = bar.panels_btn
    b.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)      # the pointer left for another app without Leave
    bar.file_item.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    win.progress.show()
    win.progress.set_progress("Calculating", 25, 100, 60)
    kind = win.progress_line.kind
    bar.set_window_active(False)
    pump(app)
    assert not b.underMouse() and not bar.file_item.underMouse(), "no stale hover after deactivation"
    assert win.progress_line.kind == kind and win.progress_line.fraction() == 0.25, "the run keeps its real status"
    assert win.progress.label.property("inactive")
    from hea_calc.ui.widgets import header as H
    restyled = []
    real = H.refresh_style
    H.refresh_style = lambda w: restyled.append(w) or real(w)
    try:
        bar.set_window_active(False)                             # unchanged: no restyle, no repaint
        assert bar.window_active is False and not restyled
        bar.set_window_active(True)
        assert len(restyled) == len(bar.menu_items) + 2          # the menu labels and the status texts only
    finally:
        H.refresh_style = real
    bar.set_window_active(True)
    win.progress.hide()


def test_a_popup_of_the_window_keeps_the_title_bar_active(win, app, monkeypatch):
    """Opening a title-bar menu must not flicker the bar to inactive: a popup of this window counts as active."""
    bar = win.header
    bar.set_window_active(True)
    monkeypatch.setattr(type(win), "isActiveWindow", lambda self: False)
    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: win.file_menu))
    bar._evaluate_activation()
    assert bar.window_active is True
    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: None))
    bar._evaluate_activation()
    assert bar.window_active is False
    bar.set_window_active(True)


@pytest.mark.skipif(os.environ.get("HEA_NATIVE_TESTS") != "1", reason="native Windows check (HEA_NATIVE_TESTS=1)")
def test_native_activation_moves_the_whole_title_bar_without_menu_flicker():
    import json
    import subprocess
    import sys as _sys
    probe = ROOT / "tools" / "titlebar_activation_probe.py"
    r = subprocess.run([_sys.executable, str(probe), "light", "1", str(Path(tempfile.mkdtemp()))],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=180,
                       env={k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"})
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    assert line, r.stdout[-2000:] + r.stderr[-2000:]
    d = json.loads(line[-1])
    st = {s["tag"]: s for s in d["states"]}
    assert st["active"]["active_flag"] and not st["inactive taskbar"]["active_flag"] and st["reactivated"]["active_flag"]
    assert not st["help active"]["active_flag"] and not st["analysis window active"]["active_flag"]
    assert d["menu_changes"] == [] and d["active_while_menu"], "a title-bar menu never deactivates the bar"
    for k in ("site", "file", "panels_icon", "close_glyph"):
        assert st["active"][k] == st["reactivated"][k] == st["restored"][k], k
        assert st["active"][k] != st["inactive taskbar"][k], k


def test_lock_tooltips_state_what_the_lock_does_now(win, app):
    comp = win.composition
    for el in ("Fe", "Co", "Ni"):
        win.elements.table.tiles[el].click()
    comp.set_mode(1)
    pump(app, 0.1)
    sw = comp.sweep
    lk = sw.rows["Fe"].lock
    assert lk.toolTip().startswith("Required") and lk.accessibleName() == "Fe required"
    lk.click()
    pump(app)
    assert lk.toolTip().startswith("Optional")
    sw._sync_all_row()
    pump(app)
    assert sw.all_lock.mixed                                    # Fe optional, Co / Ni required
    assert sw.all_lock.toolTip().startswith("Some elements are required")
    lk.click()


def test_opening_and_closing_the_analysis_window_repeatedly_leaks_nothing(win, app):
    from PySide6.QtCore import SIGNAL
    from PySide6.QtWidgets import QWidget
    _rows(win, 10)
    c = win.analysis_ctl
    aw = win.open_analysis_window(win.table.model.row_at(0))
    pump(app)
    aw.close()
    pump(app)
    base = (c.receivers(SIGNAL("state_changed(PyObject,PyObject)")), len(aw.findChildren(QWidget)),
            len(QApplication.topLevelWidgets()))
    for i in range(15):
        w2 = win.open_analysis_window(win.table.model.row_at(i % 10))
        pump(app)
        assert w2 is aw, "reused, never a second window"
        aw.close()
        pump(app)
    now = (c.receivers(SIGNAL("state_changed(PyObject,PyObject)")), len(aw.findChildren(QWidget)),
           len(QApplication.topLevelWidgets()))
    assert now[0] == base[0], "no extra controller connections"
    assert now[2] == base[2], "no new top-level windows"
    assert now[1] <= base[1] * 1.1 + 20, ("the window's widgets do not accumulate", base, now)
    assert sum(1 for w in QApplication.topLevelWidgets() if w.objectName() == "AnalysisWindow") == 1


# ====================================================================== Follow-up: expression editor runtime errors
NON_ASCII = "ıİşŞğĞüÜöÖçÇßéµΩ²³٣−–　"


def test_lexers_never_raise_on_any_character_and_mark_foreign_ones_invalid():
    """Root cause of both reported errors: ``str.isalpha`` / ``isdigit`` / ``islower`` accept any Unicode letter or
    digit, the token regexes only ASCII - ``match()`` returned None and ``.group()`` raised (a Turkish-keyboard
    ``ı`` in a range line was enough)."""
    import random
    from hea_calc.core.data import default_datasets
    from hea_calc.core import expression_doc as D
    from hea_calc.core import expression_lexer as L
    data = default_datasets()
    for ch in NON_ASCII:
        for line in (f"0 <= x <= 1, st{ch}ep=0.1", f"{ch} <= 1", f"Cr{ch}MnFe", f"Al{{x{ch}}}Co", f"x{ch}"):
            toks = L.lex_declaration(line) + L.lex_formula(line, data)
            assert any(t.kind == L.INVALID and ch in t.text for t in toks), (line, toks)
            assert L.declared_variable(line) is None or L.declared_variable(line)[0].isascii()
    alphabet = list("CrMnFeCoNiAlTixyz0123456789.,=<>≤ +-*/^(){}_stepoints") + list(NON_ASCII)
    rnd = random.Random(3)
    base = ["CrMnFeCoNiyCux", "0 <= x <= 1, step=0.1", "0 < y < 1, points=9", "Al{x}CoCrFeNi"]
    for _ in range(4000):
        s = list(rnd.choice(base))
        for _k in range(rnd.randint(1, 3)):
            pos = rnd.randint(0, len(s))
            if rnd.random() < 0.6:
                s.insert(pos, rnd.choice(alphabet))
            elif s:
                s.pop(min(pos, len(s) - 1))
        line = "".join(s)
        text = f"CrMnFeCoNiyCux\n{line}\n\n{line}"
        L.lex_document(text, data)
        D.plan_declarations(text, data, {})
        D.parse_document(text, data)                 # structured diagnostics only, never an exception


def test_malformed_declarations_get_structured_diagnostics_and_the_example_parses():
    from hea_calc.core.data import default_datasets
    from hea_calc.core.expression_doc import parse_document
    data = default_datasets()
    ok = parse_document("CrMnFeCoNiyCux\n0 <= x <= 1, step=0.1\n0 < y < 1, points=9", data)
    assert ok.ok and not ok.errors
    cases = {"0 <= x <= 1, stıep=0.1": "not a range option", "0 <= x <=": "not a range", "0 < y < 1, poi": "range option"}
    for line, msg in cases.items():
        d = parse_document(f"CrMnFeCoNiyCux\n{line}", data)
        assert not d.ok and any(msg in e[2] for e in d.errors), (line, d.errors)
    d = parse_document("CrMnFeCoNüyCux\n0 <= x <= 1, step=0.1", data)
    assert not d.ok and any("ü" in e[2] for e in d.errors)


def _type(app, ed, text):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    for ch in text:
        if ch == "\n":
            keys = [(QEvent.Type.KeyPress, Qt.Key.Key_Return, "\r"), (QEvent.Type.KeyRelease, Qt.Key.Key_Return, "\r")]
        elif ch == "\b":
            keys = [(QEvent.Type.KeyPress, Qt.Key.Key_Backspace, ""), (QEvent.Type.KeyRelease, Qt.Key.Key_Backspace, "")]
        else:
            keys = [(QEvent.Type.KeyPress, 0, ch), (QEvent.Type.KeyRelease, 0, ch)]
        for t, k, txt in keys:
            QApplication.sendEvent(ed, QKeyEvent(t, k, Qt.KeyboardModifier.NoModifier, txt))
        app.processEvents()


def test_real_editing_sequences_print_no_traceback_and_no_missing_slot(win, app, capfd):
    """Typing character by character (incl. a Turkish ``ı``), Backspace, paste, undo / redo, a second block, mode
    switches and repeated Parse: nothing on stderr - no traceback, no "Slot ... not found" (the misreport of an
    exception left pending by the highlighter)."""
    from PySide6.QtGui import QGuiApplication
    comp = win.composition
    comp.set_mode(2)
    ex = comp.expr
    ed = ex.edit
    ed.setFocus()
    capfd.readouterr()
    _type(app, ed, "CrMnFeCoNiyCux\n0 <= x <= 1, stıep=0.1")
    _type(app, ed, "\b" * 9 + "step=0.1\n0 < y < 1, points=9")
    pump(app, 0.4)
    assert "x" in ex.text() and "points=9" in ex.text()
    ed.undo(); ed.undo(); ed.redo()
    QGuiApplication.clipboard().setText("\n\nAl{z}CoCrFeNi\n0 <= z <= 0.5, step=0.25")
    c = ed.textCursor(); c.movePosition(c.MoveOperation.End); ed.setTextCursor(c)
    ed.paste()
    pump(app, 0.4)
    for _ in range(3):
        ex.parse()
        pump(app, 0.2)
    comp.set_mode(0); pump(app, 0.1); comp.set_mode(1); pump(app, 0.1); comp.set_mode(2); pump(app, 0.2)
    _type(app, ed, "ş²ü\b\b\b")
    pump(app, 0.5)
    err = capfd.readouterr().err
    assert "Traceback" not in err and "not found" not in err, err[-3000:]


def test_automatic_declarations_still_appear_while_typing(win, app):
    comp = win.composition
    comp.set_mode(2)
    ex = comp.expr
    ex.set_text("")
    ed = ex.edit
    ed.setFocus()
    _type(app, ed, "CrMnFeCoNiyCux")
    pump(app, 1.2)
    ex._validate()
    pump(app, 0.2)
    lines = ex.text().split("\n")
    assert lines[0] == "CrMnFeCoNiyCux"
    declared = {ln.split("<=")[1].strip() for ln in lines[1:] if "<=" in ln}
    assert {"x", "y"} <= declared, lines


# ====================================================================== Follow-up: transient windows
def test_a_notification_filled_before_it_is_placed_never_becomes_a_window(app):
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from hea_calc.ui.analysis.widgets import ActionableNotification
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    from window_watch import WindowWatch
    host = QWidget()
    lay = QVBoxLayout(host)
    host.show()
    with WindowWatch(app) as ww:
        note = ActionableNotification()
        note.show_message("warning", "Extrapolated", "Outside the published domain.")
        pump(app)
        assert not note.isVisible(), "not shown while it has no parent (it would be a window)"
        lay.addWidget(note)
        pump(app)
    assert not ww.unexpected, ww.unexpected
    assert note.isVisible() and note.parentWidget() is host, "shown once placed"
    host.close()


def test_model_details_with_warnings_open_no_transient_window(win, app):
    """M7 extrapolated (CoCuMgVZn), M6 / M7 flagged data (NiTaV), N/A models (ReSnWZr): every Model details view in
    the embedded panel and the separate window shows its notices inside the page - no top-level window flashes."""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "tools"))
    from window_watch import WindowWatch
    from hea_calc.core.analysis import state as S
    from hea_calc.core.engine import MODEL_KEYS
    c = win.analysis_ctl
    with WindowWatch(app) as ww:
        for formula, els in (("CoCuMgVZn", ("Co", "Cu", "Mg", "V", "Zn")), ("NiTaV", ("Ni", "Ta", "V")),
                             ("ReSnWZr", ("Re", "Sn", "W", "Zr"))):
            win.composition.clear()
            win.composition.set_mode(0)
            for el in els:
                win.elements.table.tiles[el].click()
            win.composition.calculate()
            t0 = time.monotonic()
            while win.runner.running and time.monotonic() - t0 < 30:
                pump(app, 0.05)
            pump(app, 0.1)
            for host in ("embedded", "window"):
                if host == "window":
                    win.open_analysis_window()
                c.apply(S.switch_context, S.COMPOSITION)
                for m in MODEL_KEYS:
                    c.apply(S.select_model, m, True)
                    pump(app, 0.02)
                if host == "window":
                    win.analysis_window(create=False).close()
    assert not ww.unexpected, ww.unexpected


# ====================================================================== Follow-up: Composition space Step size | Points
def test_points_grids_equal_the_equivalent_step_grids_and_counts_agree():
    from hea_calc.core.generation import SweepSpec, count_space, iter_space
    from hea_calc.core.recipes import SweepRecipe
    cases = [("ratio", [(0, 1, 0.25), (0.5, 1.5, 0.5), (1, 1, 0.1)]), ("at", [(10, 50, 10), (10, 50, 10), (10, 80, 10)]),
             ("wt", [(0, 100, 20), (0, 100, 20), (0, 100, 20)]), ("mass", [(0.5, 2, 0.5), (1, 2, 0.25)])]
    for unit, rows in cases:
        els = ["Fe", "Co", "Ni"][:len(rows)]
        step = [SweepSpec(el, a, b, st, True) for el, (a, b, st) in zip(els, rows)]
        pts = [SweepSpec(el, a, b, 0.0, True, points=round((b - a) / st) + 1) for el, (a, b, st) in zip(els, rows)]
        A, B = list(iter_space(step, unit)), list(iter_space(pts, unit))
        assert A == B and A, unit                               # same compositions, same order, same floats
        assert count_space(step, unit).count == count_space(pts, unit).count == len(A)
        assert SweepRecipe(tuple(pts), unit).estimate() == SweepRecipe(tuple(step), unit).estimate()
        meta = SweepRecipe(tuple(pts), unit).run_meta()["source"]["specs"]
        assert all("points" in m and m["step"] > 0 or m["min"] == m["max"] for m in meta)


def test_points_mode_is_exact_for_non_decimal_steps_and_validates_counts():
    from hea_calc.core.generation import RangeError, SweepSpec, count_space, iter_space
    thirds = [SweepSpec(el, 0, 100, 0.0, True, points=4) for el in ("Fe", "Co", "Ni")]
    comps = list(iter_space(thirds, "at"))
    assert count_space(thirds, "at").count == len(comps) == 1          # 0, 33.3, 66.7, 100 -> only 1/3 each
    assert abs(sum(comps[0].values()) - 100) < 1e-9
    endpoints = list(iter_space([SweepSpec("Fe", 0.2, 1.0, 0.0, True, points=3), SweepSpec("Co", 1, 1, 0.0, True,
                                                                                         points=1)], "ratio"))
    assert [c["Fe"] for c in endpoints] == [0.2, 0.6, 1.0], "both ends included, evenly spaced"
    for bad in (1, 0, -3):
        with pytest.raises(RangeError):
            SweepSpec("Fe", 0, 1, 0.0, True, points=bad).as_range().validate()
    with pytest.raises(RangeError):
        SweepSpec("Fe", 0, 1, 0.0, True, points=2.5).as_range().validate()     # not a whole number
    SweepSpec("Fe", 1, 1, 0.0, True, points=1).as_range().validate()          # a fixed value: 1 point


def test_switching_step_and_points_converts_only_exact_equivalents(win, app):
    from hea_calc.ui.widgets.composition_panel import points_to_step, step_to_points
    assert step_to_points("0", "1", "0.25") == "5" and points_to_step("0", "1", "5") == "0.25"
    assert step_to_points("0", "1", "0.3") is None and points_to_step("0", "100", "4") is None
    comp = win.composition
    for el in ("Fe", "Co", "Ni"):
        win.elements.table.tiles[el].click()
    comp.set_mode(1)
    pump(app, 0.1)
    sw = comp.sweep
    sw.rows["Fe"].set_values(("0", "1", "0.25"))
    sw.rows["Co"].set_values(("0", "1", "0.3"))                 # no exact point count
    sw.rows["Ni"].set_values(("1", "1", "0.1"))
    sw._edited()
    before = sw.specs()
    sw.h_step.set_value("points", emit=True)
    pump(app)
    assert sw.mode == "points" and sw.h_step.current_html() == "Points"
    assert sw.rows["Fe"].step.text() == "5" and sw.rows["Ni"].step.text() == "1"
    assert sw.rows["Co"].step.text() == "" and sw.rows["Co"].step.property("invalid"), "never reinterpreted"
    sw.rows["Co"].step.setText("4")
    specs = sw.specs()
    assert [s.points for s in specs] == [5, 4, 1]
    sw.set_discretization("step")
    assert [r.step.text() for r in sw.rows.values()] == ["0.25", "0.3", "0.1"], "your step values come back"
    assert sw.specs() == before
    # the window keeps the choice as a preference
    sw.set_discretization("points")
    assert win.prefs.get("composition/space_discretization") == "points"
    sw.set_discretization("step")
    assert win.prefs.get("composition/space_discretization") == "step"


def test_points_mode_count_and_calculation_match_the_step_mode(win, app):
    comp = win.composition
    for el in ("Fe", "Co", "Ni"):
        win.elements.table.tiles[el].click()
    comp.set_mode(1)
    pump(app, 0.1)
    sw = comp.sweep
    for el in ("Fe", "Co", "Ni"):
        sw.rows[el].set_values(("0.5", "1.5", "0.5"))
    sw._edited()
    sw._timer.stop()
    sw._update_summary()
    t0 = time.monotonic()
    while sw._counter.busy and time.monotonic() - t0 < 20:
        pump(app, 0.05)
    n_step = sw.summary_data.compositions
    sw.set_discretization("points")
    assert [r.step.text() for r in sw.rows.values()] == ["3", "3", "3"]
    sw._timer.stop()
    sw._update_summary()
    t0 = time.monotonic()
    while sw._counter.busy and time.monotonic() - t0 < 20:
        pump(app, 0.05)
    assert sw.summary_data.compositions == n_step
    rec = sw.recipe()
    assert rec.count() == n_step
    sw.set_discretization("step")


# ====================================================================== Follow-up: menu bar navigation
@pytest.mark.skipif(os.environ.get("HEA_NATIVE_TESTS") != "1", reason="native Windows check (HEA_NATIVE_TESTS=1)")
def test_native_open_menu_follows_the_pointer_and_arrows_one_at_a_time():
    import json
    import subprocess
    import sys as _sys
    r = subprocess.run([_sys.executable, str(ROOT / "tools" / "menubar_probe.py"), "1"], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=120, env={k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"})
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    assert line, r.stdout[-2000:] + r.stderr[-2000:]
    d = json.loads(line[-1])
    got = {label: menus for label, menus, _n in d["steps"]}
    assert got["click File"] == ["File"] and got["hover Edit"] == ["Edit"] and got["hover View"] == ["View"]
    assert got["hover Help"] == ["Help"] and got["hover File"] == ["File"]
    assert got["Right"] == ["Edit"] and got["Left"] == ["File"] and got["Esc"] == []
    assert got["plain hover Edit"] == [] and got["plain hover View"] == [] and got["click outside"] == []
    assert d["max_popups"] == 1, "never two menus at once"


# ====================================================================== Follow-up: window state
def _settings():
    return QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)


def test_window_state_first_run_maximized_then_as_left(app):
    from PySide6.QtCore import QRect
    from hea_calc.ui.main_window import MainWindow
    st = _settings()
    w = MainWindow(settings=st)
    w.show_initial()
    pump(app, 0.2)
    assert w.isMaximized(), "a fresh installation opens maximized"
    w.close(); pump(app)
    assert st.value("window/state") == "maximized"
    normal = st.value("window/normal")
    assert isinstance(normal, QRect) and (normal.width(), normal.height()) == MainWindow.DEFAULT_SIZE, \
        "the maximized size never overwrites the normal one"
    w2 = MainWindow(settings=st)
    w2.show_initial()
    pump(app, 0.2)
    assert w2.isMaximized()
    w2.showNormal(); pump(app)
    from PySide6.QtGui import QGuiApplication
    avail = QGuiApplication.primaryScreen().availableGeometry()
    want = QRect(avail.left() + 30, avail.top() + 40, w2.minimumWidth(), w2.minimumHeight())
    w2.setGeometry(want); pump(app)
    saved = w2.geometry()
    w2.close(); pump(app)
    w3 = MainWindow(settings=st)
    w3.show_initial()
    pump(app, 0.2)
    assert not w3.isMaximized() and st.value("window/state") == "normal"
    if avail.width() >= want.right() and avail.height() >= want.bottom():   # (offscreen: an 800 x 800 screen)
        assert w3.geometry() == saved
    assert w3.geometry().left() >= avail.left() and w3.geometry().top() >= avail.top()
    # minimized after being maximized: reopens maximized, not minimized
    w3.showMaximized(); pump(app); w3.showMinimized(); pump(app)
    w3.close(); pump(app)
    assert st.value("window/state") == "maximized"
    # full screen from normal: reopens normal
    w4 = MainWindow(settings=st)
    w4.show_initial(); pump(app); w4.showNormal(); pump(app)
    w4.set_fullscreen(True); pump(app)
    w4.close(); pump(app)
    assert st.value("window/state") == "normal"


def test_a_window_saved_on_a_missing_monitor_opens_on_the_primary_screen(app):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication
    from hea_calc.ui.main_window import MainWindow
    st = _settings()
    st.setValue("window/state", "normal")
    st.setValue("window/normal", QRect(9000, 9000, 1000, 700))     # a monitor that is not connected
    w = MainWindow(settings=st)
    w.show_initial()
    pump(app, 0.2)
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert avail.intersects(w.geometry()) and avail.contains(w.geometry().center())
    w.close(); pump(app)


@pytest.mark.skipif(os.environ.get("HEA_NATIVE_TESTS") != "1", reason="native Windows check (HEA_NATIVE_TESTS=1)")
def test_native_window_state_round_trip_keeps_size_and_snap():
    import subprocess
    import sys as _sys
    code = r"""
import ctypes, sys, tempfile, time
from pathlib import Path
from PySide6.QtCore import QRect, QSettings
from PySide6.QtWidgets import QApplication
app = QApplication([])
from hea_calc.ui.main_window import MainWindow
def pump(s):
    end = time.monotonic() + s
    while time.monotonic() < end: app.processEvents(); time.sleep(0.005)
st = QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)
st.setValue("window/state", "normal"); st.setValue("window/normal", QRect(120, 90, 1180, 760))
w = MainWindow(settings=st); w.show_initial(); pump(0.8)
g = w.geometry(); maxed = w.isMaximized()
w.showMaximized(); pump(0.6); zoomed = bool(ctypes.windll.user32.IsZoomed(int(w.winId())))
w.close(); pump(0.3); saved = st.value("window/state")
w2 = MainWindow(settings=st); w2.show_initial(); pump(0.8)
again = w2.isMaximized(); w2.showNormal(); pump(0.6); g2 = w2.geometry()
w2.close(); pump(0.3)
print("RESULT", g.x(), g.y(), g.width(), g.height(), maxed, zoomed, saved, again,
      g2.x(), g2.y(), g2.width(), g2.height())
"""
    r = subprocess.run([_sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), timeout=120,
                       env={k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"})
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT")]
    assert line, r.stdout[-2000:] + r.stderr[-2000:]
    f = line[0].split()[1:]
    assert f[:4] == ["120", "90", "1180", "760"] and f[4] == "False", f
    assert f[5] == "True" and f[6] == "maximized" and f[7] == "True", "maximized again, Snap-capable (IsZoomed)"
    assert f[8:] == ["120", "90", "1180", "760"], "Restore returns to the saved normal geometry"

# ====================================================================== Follow-up: panel collapse
def test_every_panel_collapses_left_and_the_strip_follows_its_neighbour(win, app):
    from hea_calc.ui.widgets.layouts import STRIP
    win.resize(1920, 1000)
    pump(app, 0.1)
    row = win.top_row
    assert not row.stacked
    row.set_collapsed(2, True)
    pump(app)
    comp_right = win.composition.geometry().right()
    strip = row.strips[2]
    from hea_calc.ui.widgets.layouts import COLLAPSED_GAP          # 8 px beside a collapsed strip (B8, 2026-10-27)
    assert strip.geometry().left() == comp_right + 1 + COLLAPSED_GAP, "Analysis' strip sits right after Composition"
    assert strip.width() == STRIP
    row.set_collapsed(2, False)
    pump(app)


def test_collapsing_all_three_hides_the_region_and_showing_restores_the_last_one(win, app):
    row = win.top_row
    for i in (0, 2, 1):
        row.set_collapsed(i, True)
        pump(app)
    assert not win.top_panels_visible(), "all collapsed: the region hides like Hide top panels"
    assert win.header.panels_btn.toolTip() == "Show top panels" and not win.top_panels_action.isChecked()
    win.set_top_panels_visible(True)
    pump(app)
    assert win.top_panels_visible() and row.collapsed == {0, 2}, "the panel collapsed last comes back"
    assert win.header.panels_btn.toolTip() == "Hide top panels"
    for i in (0, 2):
        row.set_collapsed(i, False)
    pump(app)
    assert win.top_panels_visible() and not row.collapsed


def test_stacked_analysis_uses_vertical_collapse_icons(win, app):
    row = win.top_row
    win.resize(1920, 1000)
    pump(app, 0.1)
    assert win.analysis.collapse_btn.icon_name == "panel_collapse"
    win.resize(1200, 900)
    pump(app, 0.2)
    if row.stacked:
        assert win.analysis.collapse_btn.icon_name == "row_collapse"
        assert row.strips[2].button.icon_name == "row_expand"
    win.resize(1920, 1000)
    pump(app, 0.2)
    assert win.analysis.collapse_btn.icon_name == "panel_collapse" and row.strips[2].button.icon_name == "panel_expand"


def test_system_default_theme_uses_the_carbon_screen_icon(win):
    from hea_calc.ui import icons
    acts = {a.text(): a for a in win.view_menu.actions()}
    assert acts["System default"].property("trailing_icon") == "screen"
    assert "M28,4H4A2,2,0,0,0,2,6V22" in icons._INLINE["screen"]          # Carbon screen.svg path


def test_danger_dialog_cancel_ring_appears_only_with_the_keyboard(win, app):
    from PySide6.QtTest import QTest
    from hea_calc.ui.widgets.dialogs import DangerDialog
    from hea_calc.ui.theme import t
    d = DangerDialog("Clear results", "Clear all 1,000 results?", "detail", "Clear results", win)
    d.show()
    pump(app)
    b = d.cancel_button

    def ring():
        img = b.grab().toImage()
        return img.pixelColor(1, b.height() // 2).name() == t("focus")
    assert b.hasFocus() and not ring(), "program focus: no ring"
    QTest.keyClick(b, Qt.Key.Key_Tab)                     # keyboard use: the ring follows the focus
    pump(app)
    QTest.keyClick(d.action_button, Qt.Key.Key_Backtab)
    pump(app)
    assert b.hasFocus() and ring(), "keyboard focus: the ring shows"
    d.reject()


def test_dialog_surfaces_are_the_dialog_background_in_gray_100(app):
    from hea_calc.ui.theme import THEME, t
    from hea_calc.ui.main_window import MainWindow
    THEME.set_theme("dark")
    w = MainWindow(settings=_settings())
    w.show()
    pump(app)
    try:
        from hea_calc.ui.widgets.dialogs import FilterDialog
        d = FilterDialog(w.table.model.filters, w)
        d.add_rule("vec")                         # 2026-10-28: the builder shows fields once a filter is added
        d.show()
        pump(app, 0.1)
        img = d.footer_widget.grab().toImage()
        assert img.pixelColor(8, 8).name() == t("shell") == "#161616", "footer: the dialog's Gray 100"
        from PySide6.QtWidgets import QLineEdit
        f = [x for x in d.findChildren(QLineEdit) if x.isVisible()][0]
        assert f.grab().toImage().pixelColor(f.width() - 4, f.height() // 2).name() == t("dialog-field") == "#262626"
        d.reject()
    finally:
        w.close()
        THEME.set_theme("light")


def test_analysis_window_opens_without_a_focus_ring_on_a_gray_100_surface(win, app):
    from hea_calc.ui.theme import THEME, t
    THEME.set_theme("dark")
    win.apply_theme()
    _rows(win, 5)
    aw = win.open_analysis_window(win.table.model.row_at(0))
    pump(app, 0.2)
    try:
        assert not aw.panel.switcher.hasFocus(), "the window opens with no control focused"
        img = aw.grab().toImage()
        assert img.pixelColor(4, aw.height() - 4).name() == t("background") == "#161616"
    finally:
        aw.close()
        THEME.set_theme("light")
        win.apply_theme()


# ---------------------------------------------------------------- Documentation: notifications and links
def test_documentation_callouts_have_balanced_carbon_padding(win, app):
    from hea_calc.core import docs
    html = docs.article_html("first-calculation", 640)
    assert 'class="nlast"' in html, "the last paragraph of a callout carries no trailing margin"
    hw = win.show_help("first-calculation")
    pump(app, 0.2)
    try:
        from hea_calc.ui.theme import t
        doc = hw.view.document()
        cur = doc.find("Before you start.")
        tbl = cur.currentTable()
        assert tbl is not None
        box = doc.documentLayout().frameBoundingRect(tbl)
        img = hw.view.viewport().grab().toImage()
        fill = t("notification-info-bg")
        x0 = int(box.left()) + 60                   # inside the note cell (text starts 48 px in)
        rows = [y for y in range(int(box.top()), int(box.bottom()) + 1)
                if img.pixelColor(int(box.left()) + 30, y).name() == fill]
        top, bottom = min(rows), max(rows)
        ink = [y for y in range(top, bottom + 1)
               if any(img.pixelColor(x, y).lightness() < 120 for x in range(x0, int(box.right()) - 16))]
        top_pad, bottom_pad = min(ink) - top, bottom - max(ink)
        # Carbon inline notification: 15 px text padding top and bottom (glyph ink sits a little inside)
        assert abs(top_pad - bottom_pad) <= 4, (top_pad, bottom_pad)
        assert 12 <= top_pad <= 20 and 12 <= bottom_pad <= 20, (top_pad, bottom_pad)
    finally:
        hw.close()


def test_documentation_links_have_hover_active_and_focus_states_without_layout_shift(win, app):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from hea_calc.ui.theme import t
    hw = win.show_help("first-calculation")
    pump(app, 0.2)
    v = hw.view
    try:
        doc = v.document()
        cur = doc.find("Documentation Home")          # breadcrumb link
        assert cur.charFormat().isAnchor()
        rng = v._anchor_range(cur.selectionStart())
        assert rng is not None and rng[1] - rng[0] >= len("Documentation Home")
        size_before = doc.size()
        r = v.cursorRect(cur)
        pt = QPointF(r.center().x() - 20, r.center().y())

        def send(kind, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.NoButton):
            ev = QMouseEvent(kind, pt, v.viewport().mapToGlobal(pt.toPoint()).toPointF(), button, buttons,
                             Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(v.viewport(), ev)
            pump(app)
        send(QEvent.Type.MouseMove)
        assert v.hover_range == rng
        sels = v.extraSelections()
        hov = [s for s in sels if s.format.fontUnderline()]
        assert hov and hov[-1].format.foreground().color().name() == t("link-primary-hover")
        links = []
        v.link.connect(links.append)
        send(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        assert v.active_range == rng
        act = [s for s in v.extraSelections() if s.format.fontUnderline()]
        assert act[-1].format.foreground().color().name() == t("text-primary"), "Carbon active link"
        assert doc.size() == size_before, "states are paint-only: no layout shift"
        send(QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton)
        assert v.active_range is None
        assert links and links[-1].startswith("help://"), "the click follows the link"
        hw.show_page("first-calculation") if hasattr(hw, "show_page") else win.show_help("first-calculation")
        pump(app, 0.1)
        doc = v.document()
        QApplication.sendEvent(v.viewport(), QEvent(QEvent.Type.Leave))
        pump(app)
        assert v.hover_range is None and not [s for s in v.extraSelections() if s.format.fontUnderline()]
        # keyboard: a Tab-selected link is shown with the focus outline, not as selected text
        c = v.textCursor()
        c.setPosition(rng[0])
        c.setPosition(rng[1], c.MoveMode.KeepAnchor)
        v.setTextCursor(c)
        pump(app)
        assert v.focus_range == rng
        assert v.palette().color(v.palette().ColorRole.Highlight).alpha() == 0
        assert v.link_rects(rng), "the focus outline has a rectangle"
        c.clearSelection()
        v.setTextCursor(c)
        pump(app)
        assert v.focus_range is None and v.palette().color(v.palette().ColorRole.Highlight).alpha() > 0
    finally:
        hw.close()


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_inactive_state_line_keeps_its_meaning_subdued(win, app, theme):
    from PySide6.QtGui import QColor
    from hea_calc.ui.theme import THEME, t
    THEME.set_theme(theme)
    win.apply_theme()
    line = win.header.line
    try:
        for kind in ("success", "warning", "error"):
            line.set_kind(kind)
            win.header.set_window_active(True)
            pump(app)
            on = line.grab().toImage().pixelColor(line.width() // 2, 2)
            assert on.name() == t(f"support-{kind}"), "active: the exact status colour"
            win.header.set_window_active(False)
            pump(app)
            off = line.grab().toImage().pixelColor(line.width() // 2, 2)
            assert off.name() != on.name(), "inactive: subdued"
            assert abs(off.hslHue() - on.hslHue()) <= 6, (kind, on.name(), off.name())   # same meaning (hue)
            bg = t("background")
            # still visible: 3:1 (WCAG 1.4.11) where the active colour has it, else at least half its contrast
            assert _contrast(off.name(), bg) >= min(3.0, 1 + 0.5 * (_contrast(on.name(), bg) - 1)), (kind, off.name())
            assert line.kind == kind
    finally:
        line.set_kind(None)
        win.header.set_window_active(True)
        THEME.set_theme("light")
        win.apply_theme()


# ---------------------------------------------------------------- messages: the title bar, never above the table
def test_copy_confirmation_is_in_the_title_bar_and_nothing_sits_above_the_table(win, app):
    from hea_calc.ui.widgets.common import InlineNotification
    _rows(win, 5)
    top = win.table.mapTo(win, QPoint(0, 0)).y()
    win.copy_table()
    pump(app)
    p = win.progress
    assert p.message is not None and p.message[0] == "success"
    assert p.label.text() == "Table copied to clipboard" and p.label.isVisible() and p.icon.isVisible()
    assert "5 row(s)" in p.message_text()
    assert win.table.mapTo(win, QPoint(0, 0)).y() == top, "the table never moves for a message"
    above = [n for n in win.findChildren(InlineNotification) if n.isVisible()
             and n.mapTo(win, QPoint(0, n.height())).y() <= top + 1
             and not win.top_row.isAncestorOf(n)]
    assert not above, "no notification above the results table"
    assert win.progress_line.kind is None, "a message never changes the state line"
    p._msg_timer.timeout.emit()                     # the timeout: back to idle
    pump(app)
    assert p.message is None and not p.label.isVisible()


def test_warnings_stay_until_the_next_press_and_a_running_job_keeps_its_text(win, app):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    p = win.progress
    win.notify("warning", "Wait for the running calculation or export to finish.")
    pump(app, 0.05)
    assert p.message[0] == "warning" and not p._msg_timer.isActive(), "a warning has no timeout"
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(win.table, ev)
    pump(app, 0.05)
    assert p.message is None
    # a job is running: the message takes the text for its time, then the progress text returns
    p.show()
    p.set_progress("Calculating", 25, 100, 60)
    win.notify("info", "A report is already being prepared.", 4000)
    p.set_progress("Calculating", 50, 100, 30)      # progress continues underneath
    assert p.label.text() == "Info" and p.bar.fraction() == 0.5
    p._msg_timer.timeout.emit()
    pump(app)
    assert p.label.text() == "Calculating…50%" and "(50/100)" in p.detail.text() and not p.icon.isVisible()
    p.hide()
    # a long sentence is elided and given in full in the tooltip / accessible description
    long = "The calculation was stopped because the disk is full; " * 8
    win.notify("error", long, title="Calculation failed")
    pump(app, 0.05)
    assert p.detail.text().endswith("…") and p.detail.toolTip() == long and p.detail.accessibleDescription() == long
    p.dismiss_message()


# ---------------------------------------------------------------- one Analysis view at work
def test_only_the_analysis_view_in_use_renders_and_the_other_catches_up_once(win, app, monkeypatch):
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis import panel as PN
    _rows(win, 6)
    aw = win.open_analysis_window(win.table.model.row_at(0))
    aw.resize(900, 700)                   # the window's compact layout (its panel); wide, the workspace renders
    pump(app, 0.1)
    renders = {"embedded": 0, "window": 0}
    from hea_calc.ui.analysis import composition_view as CPV
    real = CPV.CompositionContent.set_result

    def spy(self, *a, **k):
        w = self
        while w is not None and not isinstance(w, PN.AnalysisPanel):
            w = w.parentWidget()
        renders["window" if w is not None and w.external else "embedded"] += 1
        return real(self, *a, **k)
    monkeypatch.setattr(CPV.CompositionContent, "set_result", spy)
    try:
        # the separate window is in use (the main window is not active)
        monkeypatch.setattr(win, "_owns_active_window", lambda: False)
        win.sync_analysis_suspension()
        assert win.analysis.suspended and not aw.panel.suspended
        for i in range(1, 4):
            win.open_analysis_window(win.table.model.row_at(i))
            pump(app, 0.05)
        assert renders == {"embedded": 0, "window": 3}, renders
        name = win.table.model.row_at(3).name
        assert aw.panel.row.name == name
        win.analysis_ctl.apply(S.set_tab, "models")
        pump(app, 0.05)
        # back to the main window: the embedded panel catches up once, with the current state
        monkeypatch.setattr(win, "_owns_active_window", lambda: True)
        win.sync_analysis_suspension()
        pump(app, 0.05)
        assert not win.analysis.suspended and renders["embedded"] == 1
        assert win.analysis.row.name == name and win.analysis.comp_tabs.index() == S.COMP_TABS.index("models")
        # the window hidden (closed): its panel is suspended and catches up when presented again
        aw.close()
        pump(app, 0.05)
        win.sync_analysis_suspension()
        assert aw.panel.suspended
        win.analysis_ctl.set_active(win.table.model.row_at(5).id)
        pump(app, 0.05)
        assert renders["window"] == 3
        win.open_analysis_window()
        pump(app, 0.05)
        assert not aw.panel.suspended and aw.panel.row.name == win.table.model.row_at(5).name
    finally:
        aw.close()


# ---------------------------------------------------------------- Elements: property definitions
def test_element_properties_toggletip_opens_the_definitions_page(win, app, monkeypatch):
    from hea_calc.ui import help_router
    from hea_calc.ui.widgets.tooltip import Toggletip
    info = win.elements.info
    btn = info.info_btn
    assert btn.isVisible() and btn.accessibleName() == "Element properties"
    # inside the identity row, right-aligned within the panel padding, never over a value
    assert btn.mapTo(info, QPoint(btn.width(), 0)).x() <= info.width() - 16
    opened = []
    monkeypatch.setattr(help_router, "open", lambda href, anchor=None: opened.append(href))
    btn.click()
    pump(app, 0.05)
    tip = btn.popup
    assert isinstance(tip, Toggletip) and tip.isVisible()
    tip._link("help://element-properties")
    assert opened == ["help://element-properties"]


def test_element_property_definitions_page_documents_every_displayed_value(win, app):
    import re
    from hea_calc.core import docs
    from hea_calc.ui.widgets.element_panel import ElementInfo
    assert docs.resolve("element-properties") is not None and "elemental-data" in docs.related("element-properties")
    text = (docs.PAGES_DIR / "element-properties.md").read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if ln.startswith("| ")]
    shown = [k for g in ElementInfo.GROUPS for k, *_r in g]
    for key in shown:                               # every symbol of the panel has its own row
        assert any(ln.startswith(f"| {key} |") for ln in rows), key
    for word in ("Z", "Category"):
        assert any(ln.startswith(f"| {word} |") for ln in rows), word
    # the units and sources in the page are those of the panel's tooltips (one definition, two places)
    tips = {k: tip for g in ElementInfo.GROUPS for k, _p, _f, _s, tip in g}
    # 2026-10-28 (C2): sources only in the page, never in the tooltips (definitions and units stay in both)
    assert "Guo & Liu (2011), Table 1" in text and "Ch. 3, Table 9" in text and "Table A5" in text
    assert "(pm)" in tips["r"] and "(pm)" in tips["r<sub>CN12</sub>"] and "(GPa)" in tips["K"]
    assert not any(s in t_ for t_ in tips.values() for s in ("Guo & Liu", "Kittel", "Bakker", "Table"))
    # coverage numbers come from the dataset (nothing invented)
    d = win.engine.data
    els = list(d.elements)

    def n(prop):
        return sum(1 for e in els if d.prop(e, prop) is not None)
    flat = " ".join(text.split())
    cov = re.search(r"VEC for all (\d+); ρ for (\d+); r for (\d+) \((\d+) of them supplementary values; "
                    r"At, Rn and Cm–Lr have none\); r<sub>CN12</sub> for (\d+); φ\*, n<sub>ws</sub>, K and G for "
                    r"(\d+)", flat)
    assert cov, "coverage sentence"
    assert int(cov.group(1)) == len(els)
    for prop in ("melting_point", "molar_volume", "atomic_weight", "nvalence"):
        assert n(prop) == len(els), prop
    assert int(cov.group(2)) == n("density") and int(cov.group(3)) == n("atomic_radius")
    assert int(cov.group(4)) == sum(1 for e in els if d.radius_is_supplementary(e) and d.prop(e, "atomic_radius"))
    no_r = sorted(e for e in els if d.prop(e, "atomic_radius") is None)
    assert no_r == sorted(["At", "Rn", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr"])
    assert int(cov.group(5)) == n("atomic_radius_cn12")
    assert all(n(p) == int(cov.group(6)) for p in ("work_function_phi", "n_ws", "bulk_modulus", "shear_modulus"))
    # the gas-density statement matches the dataset values it quotes
    assert d.prop("N", "density") == 1.251 and d.prop("O", "density") == 1.429
    # the page renders and is reachable from Help
    hw = win.show_help("element-properties")
    pump(app, 0.1)
    try:
        assert "Element Property Definitions" in hw.article_text()
        assert "Metallic radius, coordination number 12" in hw.article_text()
    finally:
        hw.close()
