"""UI refinement pass (2026-10-27): lock underline, floating Analysis layout, Collection toolbar, Elements
properties, Add element.  Real widgets and layouts (offscreen); expected values from tokens, geometry and the
existing periodic-table path - never from the changed code's own output."""

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


def make_window(app, theme="dark"):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1728, 1000)
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


def pump(app, n=10):
    for _ in range(n):
        app.processEvents()


def grect(w):
    from PySide6.QtCore import QPoint, QRect
    return QRect(w.mapToGlobal(QPoint(0, 0)), w.size())


# ============================================================================================ A1 lock underline
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("state", ["default", "hover", "focus", "unlocked", "hover-unlocked"])
def test_lock_cell_keeps_its_bottom_border_in_every_state(app, theme, state):
    """The 1 px bottom border belongs to the LockCell; the toggle above it paints hover and focus without
    covering it (it used to fill the whole 32 x 32 cell and erase the line on hover / focus)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QHBoxLayout
    from hea_calc.ui.theme import THEME, t
    from hea_calc.ui.widgets.composition_panel import LockCell, LockToggle
    THEME.set_theme(theme)
    try:
        cell = LockCell()
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        tog = LockToggle("unlocked" not in state)
        lay.addWidget(tog, 0, Qt.AlignmentFlag.AlignCenter)
        cell.show()
        pump(app)
        assert tog.geometry() == cell.rect(), "the toggle covers the whole cell (the reason the line was erased)"
        tog.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, "hover" in state)
        if state == "focus":
            tog.setFocus(Qt.FocusReason.TabFocusReason)
        else:
            tog.clearFocus()
        pump(app)
        img = cell.grab().toImage()
        line = t("border-strong-01")
        bottom = {img.pixelColor(x, img.height() - 1).name() for x in range(img.width())}
        assert bottom == {line}, (state, bottom)
        if "hover" in state:                      # hover is still visible above the line
            assert img.pixelColor(2, img.height() - 3).name() == t("layer-hover-01")
        cell.close()
    finally:
        THEME.set_theme("dark")


def test_composition_space_locks_keep_their_line_on_hover(win, app):
    from PySide6.QtCore import Qt
    from hea_calc.ui.theme import t
    comp = win.composition
    comp.set_mode(1)                               # Composition space
    for el in ("Fe", "Ni"):
        win.elements.table.tiles[el].click()
    pump(app)
    for lock in [comp.sweep.rows["Fe"].lock, comp.sweep.all_lock]:
        lock.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        img = lock.parentWidget().grab().toImage()
        assert {img.pixelColor(x, img.height() - 1).name() for x in range(img.width())} == {t("border-strong-01")}
        lock.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)


# ============================================================================================ A2 floating layout
def test_floating_analysis_layout_follows_its_width(win, app):
    """Compact panel below the workspace's minimum width, the expanded workspace's layout from it on - both ways
    across the breakpoint, without reopening, with the shared state and the active result."""
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis.workspace import WORKSPACE_MIN_WIDTH, wide_layout_min
    win.calculate("single", ["CoCrFeNi"], [{"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}], [{}])
    win.calculate("single", ["AlCoCrFeNi"], [{"Al": 1, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}], [{}])
    pump(app)
    rid = win.table.model.id_at(1)
    aw = win.open_analysis_window(win.table.model.row_at(1))
    assert win.workspace.minimumWidth() == WORKSPACE_MIN_WIDTH        # the main window's page is unchanged
    bp = wide_layout_min()
    # the breakpoint is the workspace Overview's readable width: fixed regions + one Descriptors column + gaps
    assert bp == 440 + 520 + 2 * 20 + (120 + 80 + 8 + 90 + 24) + 2 * 20 + 2 * 20
    seen = []
    for width in (bp - 1, bp, 800, bp + 300, bp - 1):
        aw.resize(width, 760)
        pump(app, 15)
        wide = aw.content_width() >= bp
        assert aw.wide is wide, width
        assert aw.pages.currentWidget() is (aw.workspace_scroll if wide else aw.panel)
        assert aw.panel.suspended is wide                                # only the layout on screen renders
        seen.append(wide)
        assert win.analysis_ctl.state.active == rid
    assert seen == [False, True, False, True, False]
    # wide: the workspace layout - no Back to calculation (not a page of the main window), no horizontal overflow
    aw.resize(bp + 300, 760)
    pump(app, 15)
    ws = aw.workspace
    assert not ws.back.isVisible() and ws.external
    assert ws.width() <= aw.content_width()
    # the shared state crosses the switch: a tab chosen in the wide layout is the compact panel's tab
    win.analysis_ctl.apply(S.set_tab, "models")
    pump(app)
    assert ws.composition.currentIndex() == S.COMP_TABS.index("models")
    aw.resize(800, 760)
    pump(app, 15)
    assert aw.panel.comp_tabs.index() == S.COMP_TABS.index("models")
    assert aw.panel.row.row_id == rid
    # reuse: another activation updates the same window and its current layout
    aw.resize(bp + 300, 760)
    pump(app, 15)
    win.open_analysis_window(win.table.model.row_at(0))
    pump(app)
    assert win.analysis_window(create=False) is aw and win.analysis_ctl.state.active == win.table.model.id_at(0)
    # the main window's own expanded workspace is untouched (it keeps Back to calculation)
    assert not win.workspace.external


def test_floating_wide_layout_is_not_a_stretched_panel(win, app):
    """The wide layout is a different organisation (the workspace's three regions side by side), not the panel."""
    from hea_calc.ui.analysis.panel import AnalysisPanel
    from hea_calc.ui.analysis.workspace import AnalysisWorkspace
    win.calculate("single", ["CoCrFeNi"], [{"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}], [{}])
    from hea_calc.ui.analysis.workspace import wide_layout_min
    aw = win.open_analysis_window(win.table.model.row_at(0))
    aw.resize(1120, 760)                                             # the default size: compact (L) panel
    pump(app, 15)
    assert isinstance(aw.current_view(), AnalysisPanel) and aw.panel.size_class == "L"
    aw.resize(wide_layout_min() + 200, 800)
    pump(app, 15)
    assert isinstance(aw.current_view(), AnalysisWorkspace)
    aw.resize(900, 700)
    pump(app, 15)
    assert isinstance(aw.current_view(), AnalysisPanel)


# ============================================================================================ A3 Collection toolbar
def test_restrict_and_content_switcher_never_overlap(win, app):
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    run = samples.store_recipe(win.repo, win.engine, samples.e1_recipe())
    win.table.model.refresh_committed()
    win.analysis_ctl.run_finished(run)
    win._check_details()
    win.analysis_ctl.apply(S.switch_context, S.COLLECTION)
    pump(app, 20)

    def check(panel, label):
        sw = grect(panel.switcher)
        sb = panel.scope_bar
        visible = [w for w in (sb.run_dd, sb.pop_dd, sb.restrict_btn, sb.count, sb.info, sb.summary_btn)
                   if w.isVisible()]
        assert visible, label
        for w in visible:
            assert not grect(w).intersects(sw), (label, w.accessibleName() or type(w).__name__, grect(w), sw)
        return sb.restrict_btn.isVisible()

    restrict_seen = 0
    for width in (1728, 1440, 1280):                     # docked: S at 1728 (wide table row), L below
        win.resize(width, 1000)
        pump(app, 15)
        if win.analysis_dock.wide:                       # C4: the workspace layout is shown, not the panel
            continue
        restrict_seen += check(win.analysis, f"docked@{width}")
    aw = win.open_analysis_window()
    for width in (600, 720, 800, 900, 990):              # floating compact panel: S and M
        aw.resize(width, 760)
        pump(app, 15)
        restrict_seen += check(aw.panel, f"floating@{width}")
    assert restrict_seen >= 4                            # the Restrict button itself was checked, not only S


# ============================================================================================ A4 Elements properties
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_element_properties_layout(app, theme):
    from PySide6.QtCore import QPoint
    from hea_calc.ui.theme import PANEL_PADDING_X
    w = make_window(app, theme)
    try:
        ep = w.elements
        info = ep.info
        for el in ("Fe", "Pu", "He", None):              # a metal, a supplementary radius, missing values, none
            info.show_element(el)
            pump(app)
            # 16 px under the last property row, to the panel's bottom edge
            rows = [v for v, _f, _s in info.values.values()]
            bottom = max(v.mapTo(ep, QPoint(0, v.height())).y() for v in rows)
            assert ep.height() - bottom == info.BOTTOM_PAD == 16, (el, ep.height() - bottom)
            # 2026-10-27 (B2): the rule under the identity line was removed; the grid keeps the 16 px insets
            assert not hasattr(info, "rule")
            assert min(v.mapTo(info, QPoint(0, 0)).x() for v in rows) >= PANEL_PADDING_X
            # the group dividers span every property row
            top = min(v.mapTo(info, QPoint(0, 0)).y() for v in rows)
            for d in info.group_dividers:
                g = d.geometry()
                assert g.top() <= top and g.bottom() >= bottom - info.mapTo(ep, QPoint(0, 0)).y() - 1, (el, g)
            # rows are at least the 18 px text height and align across groups
            assert min(v.height() for v in rows) >= info.ROW_MIN
            if el is None:
                assert all(v.text() == "—" for v in rows)
        info.show_element("He")
        assert info.values["bulk_modulus"][0].text() in ("—",) or info.values["bulk_modulus"][0].text()
        missing = [p for p, (v, _f, _s) in info.values.items() if w.engine.data.prop("He", p) is None]
        assert all(info.values[p][0].text() == "—" for p in missing)
        # the group widths are computed for the real content width (16 px margins, 1 px dividers)
        avail = info.width() - 2 * PANEL_PADDING_X - len(info.group_dividers)
        used = sum(g.width() for g in info.group_wraps) + sum(gap.sizeHint().width() for gap in info.group_gaps)
        assert used <= avail
    finally:
        close_window(app, w)


# ============================================================================================ A5 Add element
# The searchable Add element picker was replaced on 2026-10-27 by the blank draft row (composition workflow
# redesign, A1): its tests are in tests/test_composition_workflow_redesign.py.


def _kv_overlaps(root):
    """Key-value rows of the workspace Overview whose value runs into its label, or that overlap another row."""
    from PySide6.QtCore import QPoint, QRect
    from hea_calc.ui.analysis.widgets import _KVRow
    rows = [r for r in root.findChildren(_KVRow) if r.isVisible()]
    bad = []
    for r in rows:
        v = getattr(r, "v", None)
        if v is not None and r.k.geometry().right() >= v.geometry().left():
            bad.append(("label/value", r.k.text()[:30]))
    rects = [QRect(r.mapTo(root, QPoint(0, 0)), r.size()) for r in rows]
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if a.intersects(b):
                bad.append(("rows", a.getRect(), b.getRect()))
    return rows, bad


def test_workspace_overview_descriptors_are_readable_at_the_wide_breakpoint(win, app):
    """The Descriptors region stacks its two columns when it is narrower than two key-value columns (side by side
    they overlapped, e.g. in the main window's expanded workspace at 1 440 px)."""
    from hea_calc.ui.analysis.workspace import wide_layout_min
    win.calculate("single", ["CoCrFeNi"], [{"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}], [{}])
    pump(app)
    aw = win.open_analysis_window(win.table.model.row_at(0))
    for width in (wide_layout_min(), wide_layout_min() + 250, 1900):
        aw.resize(width, 900)
        pump(app, 20)
        assert aw.wide
        rows, bad = _kv_overlaps(aw.workspace)
        assert len(rows) > 20 and not bad, (width, bad[:3])
    aw.close()
    win.resize(1440, 900)                                  # the main window's own expanded workspace (150 % width)
    win.set_expanded(True)
    pump(app, 20)
    rows, bad = _kv_overlaps(win.workspace)
    assert len(rows) > 20 and not bad, bad[:3]
    win.set_expanded(False)
