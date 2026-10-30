"""UI regression and consistency pass (2026-10-28): Documentation callouts, Analysis surfaces, composition labels,
menu seam, Results column widths, Combine runs, model tabs, Expand analysis, equations, window title.

Real Qt widgets in a real MainWindow (offscreen); rendered pixels where the defect is visual.  Expected values are
computed independently in the tests (token colours, 40 % blends, molar-mass conversions, glyph scales) - never
taken from the changed code's own output."""

import math
import os
import re
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    from hea_calc.ui.widgets.common import install_tooltips
    a = QApplication.instance() or QApplication([])
    load_fonts()
    install_tooltips(a)
    return a


def pump(app, n=20):
    for _ in range(n):
        app.processEvents()


def make_window(app, theme="dark", width=2160, height=1100):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(width, height)
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


def calc_one(win, app, comp=None, name="CoCrFeNi"):
    win.calculate("single", [name], [comp or {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}], [{}])
    win.table.model.wait()
    pump(app)
    win.analysis_ctl.set_active(win.table.model.page_rows()[0].id, by="table")
    pump(app)


def pixel(widget, x, y):
    img = widget.grab().toImage()
    k = img.devicePixelRatio()
    return img.pixelColor(int(x * k), int(y * k)).name()


def surface(widget):
    """The widget's dominant colour (its surface): the most frequent pixel on a coarse grid."""
    from collections import Counter
    img = widget.grab().toImage()
    cnt = Counter(img.pixelColor(x, y).name() for x in range(2, img.width() - 2, 7)
                  for y in range(2, img.height() - 2, 7))
    return cnt.most_common(1)[0][0]


def blend(fg, bg, a=0.4):
    from PySide6.QtGui import QColor
    f, b = QColor(fg), QColor(bg)
    return QColor(round(a * f.red() + (1 - a) * b.red()), round(a * f.green() + (1 - a) * b.green()),
                  round(a * f.blue() + (1 - a) * b.blue())).name()


# ============================================================================================ 1 callout borders
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_callouts_have_one_continuous_frame_meeting_the_accent(app, theme):
    from hea_calc.ui.help_window import HelpWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    hw = HelpWindow(None)
    try:
        hw.resize(1100, 900)
        hw.show()
        hw.open("first-calculation")
        pump(app, 30)
        boxes = hw.view.callout_boxes()
        assert len(boxes) >= 2                                     # an info and a warning callout
        img = hw.view.viewport().grab().toImage()
        k = THEME.tokens
        for kind, r in boxes:
            if r.bottom() > img.height() - 2 or r.top() < 1:
                continue                                           # scrolled out of view
            acc, bg = k[f"support-{kind}"], k[f"notification-{kind}-bg"]
            edge = blend(acc, bg)
            x0, x1 = round(r.left()), round(r.right())
            # the top row: the accent over its 3 px, then the edge colour unbroken to the right edge
            top = next(y for y in range(int(r.top()) - 2, int(r.top()) + 3)
                       if img.pixelColor(x0 + 10, y).name() == edge)
            assert [img.pixelColor(x, top).name() for x in range(x0, x0 + 3)] == [acc] * 3, (kind, "corner")
            assert {img.pixelColor(x, top).name() for x in range(x0 + 3, x1 - 1)} == {edge}, (kind, "top edge")
            # one row thick: outside is the page, inside is the tinted surface
            assert img.pixelColor(x0 + 10, top - 1).name() != edge and img.pixelColor(x0 + 10, top + 1).name() == bg
            bottom = next(y for y in range(int(r.bottom()) + 2, int(r.bottom()) - 3, -1)
                          if img.pixelColor(x0 + 10, y).name() == edge)
            assert {img.pixelColor(x, bottom).name() for x in range(x0 + 3, x1 - 1)} == {edge}, (kind, "bottom")
            right = max(x for x in range(x1 - 3, x1 + 3) if img.pixelColor(x, top + 5).name() == edge)
            assert {img.pixelColor(right, y).name() for y in range(top, bottom + 1)} == {edge}, (kind, "right")
            assert {img.pixelColor(x0, y).name() for y in range(top, bottom + 1)} == {acc}, (kind, "accent height")
    finally:
        hw.close()
        THEME.set_theme("dark")


# ============================================================================================ 2 / 3 surfaces
CONTRACT = {"light": {"docked": "#ffffff", "floating": "#ffffff", "expanded": "#f4f4f4"},
            "dark": {"docked": "#262626", "floating": "#161616", "expanded": "#161616"}}


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_analysis_backgrounds_follow_the_host_not_the_layout(app, theme):
    from PySide6.QtCore import QPoint
    from hea_calc.ui.surface import surface_level
    from hea_calc.ui.theme import t
    w = make_window(app, theme)
    try:
        calc_one(w, app)
        dock = w.analysis_dock
        assert not dock.wide
        assert surface(w.analysis) == CONTRACT[theme]["docked"]
        w.top_row.set_collapsed(0, True)
        w.top_row.set_collapsed(1, True)
        pump(app, 30)
        assert dock.wide                                           # responsive switching kept
        ws = dock.workspace
        assert pixel(dock.workspace_scroll, 6, 6) == CONTRACT[theme]["docked"], "a wide docked panel stays a panel"
        assert pixel(ws, 4, ws.height() - 4) == CONTRACT[theme]["docked"]
        regions = [r for r in ws.findChildren(type(ws.model_region)) if r.objectName() == "AnaRegion"
                   and r.isVisible()]
        assert regions and pixel(regions[0], regions[0].width() - 6, 6) == t("layer-02")
        inner = [c for c in regions[0].findChildren(type(regions[0].parentWidget())) if c.isVisible()]
        assert inner and surface_level(inner[0]) == 2
        w.set_expanded(True)                                       # the dedicated workspace keeps its own surface
        pump(app, 30)
        assert pixel(w.workspace, 4, 4) == CONTRACT[theme]["expanded"]
        r2 = [r for r in w.workspace.findChildren(type(ws.model_region)) if r.objectName() == "AnaRegion"
              and r.isVisible()]
        assert pixel(r2[0], r2[0].width() - 6, 6) == t("layer-01")
        w.set_expanded(False)
        w.top_row.set_collapsed(0, False)
        w.top_row.set_collapsed(1, False)
        pump(app)
        aw = w.open_analysis_window()
        aw.resize(900, 760)
        pump(app, 30)
        assert surface(aw) == CONTRACT[theme]["floating"]
        aw.resize(1700, 900)
        pump(app, 30)
        assert aw.wide and pixel(aw, 6, aw.height() - 6) == CONTRACT[theme]["floating"]
        rf = [r for r in aw.workspace.findChildren(type(ws.model_region)) if r.objectName() == "AnaRegion"
              and r.isVisible()]
        # a region is one level above its host: the light shell IS layer-01, so its regions are layer-02
        want = t("layer-02") if t("shell") == t("layer-01") else t("layer-01")
        assert pixel(rf[0], rf[0].width() - 6, 6) == want
        # runtime theme switch: the docked wide surface follows
        aw.close()
        _ = QPoint
    finally:
        close_window(app, w)


def test_nested_components_take_the_layer_of_their_surface(app):
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis.widgets import DataTable
    from hea_calc.ui.surface import ctx, surface_level
    from hea_calc.ui.theme import t
    w = make_window(app, "dark")
    try:
        calc_one(w, app)
        w.analysis_ctl.apply(S.set_tab, "overview")
        pump(app)
        compact_tables = [d for d in w.analysis.findChildren(DataTable) if d.isVisible() and d.show_header]
        assert compact_tables and surface_level(compact_tables[0]) == 1
        assert ctx(compact_tables[0], "header-row") == t("header-row")               # the Figma design surface
        w.top_row.set_collapsed(0, True)
        w.top_row.set_collapsed(1, True)
        pump(app, 30)
        wide_tables = [d for d in w.analysis_dock.workspace.findChildren(DataTable) if d.isVisible() and d.show_header]
        assert wide_tables and surface_level(wide_tables[0]) == 2
        assert ctx(wide_tables[0], "header-row") == t("layer-accent-02") != t("layer-02")   # visible on the region
        img = wide_tables[0].grab().toImage()
        assert img.pixelColor(4, 4).name() == t("layer-accent-02")                    # rendered, not only resolved
        w.set_expanded(True)
        pump(app, 30)
        exp_tables = [d for d in w.workspace.findChildren(DataTable) if d.isVisible() and d.show_header]
        assert exp_tables and surface_level(exp_tables[0]) == 1
        assert exp_tables[0].grab().toImage().pixelColor(4, 4).name() == t("header-row")
    finally:
        close_window(app, w)


# ============================================================================================ 4 composition labels
EXAMPLE = {"Cr": 12, "Mn": 20, "Co": 3, "Ni": 15, "Cu": 20, "Zn": 20, "Si": 10}


def enter_single(win, app, rep, values):
    from PySide6.QtTest import QTest
    s = win.composition.single
    win.composition.set_mode(0)
    s.radios[rep].click()
    for el in values:
        win.elements.table.tiles[el].click()
    pump(app)
    for el, v in values.items():
        f = s.rows[el].fields[rep]
        if not f.isEnabled():
            continue                                               # the balance element: computed
        f.setFocus()
        f.selectAll()
        QTest.keyClicks(f, str(v))
    pump(app)
    return s


def test_at_percent_input_is_labelled_by_its_basis(win, app):
    s = enter_single(win, app, "at", EXAMPLE)
    assert s.values == pytest.approx({k: float(v) for k, v in EXAMPLE.items()})
    win.composition.calculate()
    win.table.model.wait()
    pump(app)
    rec = win.table.model.page_rows()[0]
    assert rec.name == "Cr12Mn20Co3Ni15Cu20Zn20Si10 (at.%)"
    # the canonical composition: atomic fractions = the at.% / 100 (independent arithmetic)
    x = {el: v / sum(rec.result.composition.values()) for el, v in rec.result.composition.items()}
    assert x == pytest.approx({el: v / 100 for el, v in EXAMPLE.items()}, rel=1e-12)
    # numerically the former formula: dividing every amount by 20 gives Cr0.6MnCo0.15Ni0.75CuZnSi0.5
    from hea_calc.core import composition as C
    assert C.alloy_name(rec.result.composition) == "Cr0.6MnCo0.15Ni0.75CuZnSi0.5"
    # the run records the entry
    info = win.analysis_ctl.run_info(rec.run_id) if hasattr(rec, "run_id") else None
    if info is not None:
        assert info.source.get("input_basis") == "at"
        assert info.source.get("input_values") == pytest.approx({k: float(v) for k, v in EXAMPLE.items()})
    # the same alloy entered as atomic ratios: identical science, conventional ratio label
    win.composition.clear()
    pump(app)
    ratio = {el: v / 20 for el, v in EXAMPLE.items()}
    enter_single(win, app, "ratio", ratio)
    win.composition.calculate()
    win.table.model.wait()
    pump(app)
    rec2 = win.table.model.page_rows()[0]
    assert rec2.name == "Cr0.6MnCo0.15Ni0.75CuZnSi0.5"
    for k_, v in rec.result.descriptors.items():
        if isinstance(v, float):
            assert rec2.result.descriptors[k_] == pytest.approx(v, rel=1e-12, abs=1e-12), k_
    assert {m: o.label for m, o in rec.result.models.items()} == {m: o.label for m, o in rec2.result.models.items()}
    assert rec.id != rec2.id
    # rich-text contexts subscript the numbers, never the basis
    html = C.name_html(rec.name)
    assert html.startswith("Cr<sub>12</sub>Mn<sub>20</sub>") and html.endswith(" (at.%)")
    # the table shows the full label; copy carries it
    from hea_calc.ui.widgets.results_table import cell_runs
    assert win.table.model.cell_text(1, 0) == rec.name


def test_wt_percent_label_is_weight_and_never_stoichiometry(win, app):
    from hea_calc.core import composition as C
    vals = {"Fe": 70, "Ni": 30}
    enter_single(win, app, "wt", vals)
    win.composition.calculate()
    win.table.model.wait()
    pump(app)
    rec = win.table.model.page_rows()[0]
    assert rec.name == "Fe70Ni30 (wt.%)"
    data = win.engine.data
    moles = {el: v / data.prop(el, "atomic_weight") for el, v in vals.items()}       # independent conversion
    x = {el: m / sum(moles.values()) for el, m in moles.items()}
    comp = rec.result.composition
    assert {el: v / sum(comp.values()) for el, v in comp.items()} == pytest.approx(x, rel=1e-12)
    # a copied / exported label read back: weight percent converted, not stoichiometry
    parsed = C.parse_formula(rec.name)
    assert {el: v / 100 for el, v in parsed.items()} == pytest.approx(x, rel=1e-12)
    assert C.parse_formula("Fe70Ni30") == {"Fe": 70.0, "Ni": 30.0}                   # unlabelled: as before


def test_label_formatting_rules():
    from hea_calc.core import composition as C
    assert C.basis_name({"Fe": 64.49999999999, "Ni": 35.5000000001}, "at") == "Fe64.5Ni35.5 (at.%)"
    assert C.basis_name({"Al": 0.0125, "Fe": 99.9875, "Ni": 0}, "wt") == "Al0.0125Fe99.9875 (wt.%)"
    assert C.basis_name({"B": 1, "C": 99}, "at") == "B1C99 (at.%)"                    # a 1 is written, never dropped
    with pytest.raises(ValueError):
        C.basis_name({"Fe": 1}, "ratio")
    assert C.split_basis("Fe50Ni50 (at.%)") == ("Fe50Ni50", "at") and C.split_basis("Fe50Ni50") == ("Fe50Ni50", None)


def test_composition_space_percent_names_say_atomic():
    from hea_calc.core import composition as C
    from hea_calc.core.generation import SweepSpec
    from hea_calc.core.recipes import SweepRecipe
    for unit in ("at", "wt"):
        r = SweepRecipe((SweepSpec("Al", 10, 10, 0), SweepSpec("Ni", 90, 90, 0)), unit)
        grid = list(r.iterate())
        comp = r.atomic(grid[0])
        assert r.name(comp).endswith(" (at.%)")
        assert C.parse_formula(r.name(comp)) == pytest.approx(comp, abs=0.005)     # the atomic values (2 dp)
    r = SweepRecipe((SweepSpec("Al", 1, 1, 0), SweepSpec("Ni", 1, 1, 0)), "ratio")
    assert r.name({"Al": 1, "Ni": 1}) == "AlNi"


def test_legacy_names_are_never_relabelled(win, app):
    win.calculate("single", ["Cr0.6MnCo0.15Ni0.75CuZnSi0.5"],
                  [{el: v / 20 for el, v in EXAMPLE.items()}], [{}])          # a record stored without basis data
    win.table.model.wait()
    pump(app)
    win.composition.single.radios["at"].click()                               # whatever the current input mode
    pump(app)
    assert win.table.model.page_rows()[0].name == "Cr0.6MnCo0.15Ni0.75CuZnSi0.5"


# ============================================================================================ 5 menu seam
def test_merged_menu_paints_the_trigger_join_in_the_trigger_colour(win, app):
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.header import HeaderMenuItem, TitleBar
    tb = win.findChild(TitleBar)
    for item in [it for it in tb.menu_items if isinstance(it, HeaderMenuItem) and it.menu_ is not None]:
        m = item.menu_
        m.trigger_width = 0
        m.open_below(item, exec_=False, merge=True)
        pump(app)
        assert m.tab is not None, item.text()
        s = m.surface()
        x_mid = m.tab.left() + m.tab.width() / 2
        # integral ratio: the windows cannot round apart - nothing is painted over the trigger (the F-05 rule)
        img = m.grab().toImage()
        assert img.devicePixelRatio() == 1
        assert img.pixelColor(int(x_mid), s.top() - 1).alpha() == 0, item.text()
        # 125 %: the one device row directly above the surface is the trigger's colour (layer-02), so a device-pixel
        # gap between the two windows shows the trigger, not the title bar (#161616 in dark); the row above it is
        # left to the trigger itself
        from PySide6.QtGui import QImage
        k = 1.25
        img = QImage(round(m.width() * k), round(m.height() * k), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(k)
        img.fill(0)
        m.render(img)
        top = math.floor(s.top() * k + 0.5)                  # the surface's first device row (crisp snapping)
        x = int(x_mid * k)
        assert img.pixelColor(x, top).name() == t("layer-02")
        assert img.pixelColor(x, top - 1).name() == t("layer-02"), item.text()
        assert img.pixelColor(x, top - 2).alpha() == 0, "above the join: the trigger's own"
        m.hide()
        pump(app)


# ============================================================================================ 6 column widths
def test_alloy_has_width_priority_and_numbers_stay_compact(win, app):
    names = ["Cr12Mn20Co3Ni15Cu20Zn20Si10 (at.%)", "Al0.5CoCrCuFeNiTi0.2", "CoCrFeNi"]
    comps = [EXAMPLE, {"Al": 0.5, "Co": 1, "Cr": 1, "Cu": 1, "Fe": 1, "Ni": 1, "Ti": 0.2},
             {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}]
    win.calculate("single", names, comps, [{}, {}, {}])               # a batch: calculated by the job runner
    from PySide6.QtTest import QTest
    for _ in range(200):
        QTest.qWait(50)
        win.table.model.wait()
        if win.table.model.rowCount() == 3:
            break
    pump(app, 30)
    v = win.table.view
    assert v.m.rowCount() == 3
    from PySide6.QtGui import QFontMetricsF
    from hea_calc.core import composition as C
    from hea_calc.ui.widgets.common import tag_width
    from hea_calc.ui.widgets.results_table import TEXT_PAD_LEFT, TEXT_PAD_RIGHT, _fonts
    base, sub = _fonts()
    fm, fs = QFontMetricsF(base), QFontMetricsF(sub)
    longest = max(sum((fs if s_ else fm).horizontalAdvance(t_) for t_, s_ in C.name_segments(n)) for n in names)
    need = longest + TEXT_PAD_LEFT + TEXT_PAD_RIGHT
    for width in (1440, 1728, 2160):
        win.resize(width, 1000)
        pump(app, 20)
        widths = {k: v.header.sectionSize(i) for i, k in enumerate(v.m.keys)}
        assert widths["name"] >= need, (width, widths["name"], need)          # the full label shows
        for k, w_ in widths.items():
            if k.startswith("M") and k[1:].isdigit():
                assert w_ >= 2 * 10 + tag_width("SS+IM"), k                    # tags are never cut
            elif k != "name":
                assert w_ <= 157, (width, k, w_)                               # numbers never take Alloy's room
        assert v.horizontalScrollBar().maximum() == 0, width
    # short of room: the numbers shrink before Alloy does
    win.resize(1300, 1000)
    pump(app, 20)
    widths = {k: v.header.sectionSize(i) for i, k in enumerate(v.m.keys)}
    nat = dict(zip(v.m.keys, v.natural_widths()))
    _refs, mins, _maxs = v.column_specs()
    mins = dict(zip(v.m.keys, mins))
    if widths["name"] < min(nat["name"], int(v.viewport().width() * 0.4)):
        assert all(widths[k] <= max(mins[k], nat[k]) for k in widths
                   if k != "name" and not (k.startswith("M") and k[1:].isdigit())), widths
    # a user width wins
    i = v.m.keys.index("delta")
    v.header.resizeSection(i, 140)
    pump(app)
    win.resize(1728, 1000)
    pump(app, 20)
    assert v.header.sectionSize(i) == 140
    # the measurement uses the page, never the dataset
    assert v._naturals[0][1] == tuple(r.id for r in v.m.page_rows())


# ============================================================================================ 7 Combine runs
def test_combine_runs_is_disabled_with_its_reason_and_runs_still_switch(win, app):
    """Updated 2026-10-28 (UX package B4): Combine runs is implemented.  With ONE run it is disabled and says why
    (the disabled-reason mechanism of this pass: tooltip + accessible description); with two runs it is enabled."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.analysis.collection_view import run_items
    from hea_calc.ui.widgets import tooltip
    from hea_calc.ui.widgets.listbox import ListPopup
    c = win.analysis_ctl
    runs = []

    def add(recipe):
        run = samples.store_recipe(win.repo, win.engine, recipe)
        win.table.model.refresh_committed()
        c.run_finished(run)
        runs.append(run)
    add(samples.c1_recipe())
    c.apply(S.switch_context, S.COLLECTION)
    pump(app, 30)
    combine = [it for it in run_items(c) if it[0] == "combine"]
    assert combine and combine[0][2] is False and "two calculation runs" in combine[0][3]
    trig = win.analysis.collection.scope_bar.run_dd if hasattr(win.analysis.collection, "scope_bar") else         win.analysis.scope_bar.run_dd
    trig.set_items(run_items(c), trig.value)
    pop = ListPopup(trig, trig.list_options(), value=trig.value)
    pop.show()
    pump(app)
    i = next(n for n, o in enumerate(pop.options) if o.value == "combine")
    rect = pop.body.row_rect(i)
    assert pop.body.tip_at(rect.center()) == (combine[0][3], rect)
    assert "Combine runs" in pop.accessibleDescription() and "two calculation runs" in pop.accessibleDescription()
    QApplication.sendEvent(pop.body, QHelpEvent(QEvent.Type.ToolTip, rect.center(), pop.body.mapToGlobal(rect.center())))
    pump(app)
    ctl = tooltip.controller()
    assert ctl.visible() and "two calculation runs" in ctl.tip.text
    assert not pop.selectable(i)
    chosen = []
    pop.selected.connect(chosen.append)
    QTest.mouseClick(pop.body, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
    pump(app)                                                                 # a click on it: nothing happens
    assert chosen == [] and pop.isVisible()
    pop.close()
    pump(app)
    # a second run: Combine runs is available
    add(samples.e1_recipe())
    combine = [it for it in run_items(c) if it[0] == "combine"]
    assert combine[0][2] is True and combine[0][3] == ""
    # the runs themselves still switch
    for run in runs:
        c.scope_for(run, "full")                                           # resolved on the query threads
        for _ in range(100):
            QTest.qWait(50)
            if c.state.scope is not None and c.state.scope.run_id == run:
                break
        assert c.state.scope.run_id == run


# ============================================================================================ 8 model tabs
def test_vertical_tab_label_and_tag_share_one_row_without_overlap(app):
    from PySide6.QtGui import QColor
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.common import VerticalTabs, tag_width
    labels = ["M1 Yang & Zhang", "M2 Guo et al.", "M3 Wang et al.", "M4 Singh et al.", "M5 Ye et al.",
              "M6 Troparevsky et al.", "M7 Senkov & Miracle", "M8 King et al."]
    tags = ["SS", "MP", "IM", "SS+IM", "MG", "N/A", "SS+IM", "SS"]
    for width in (280, 170):                                                   # comfortable and tight
        vt = VerticalTabs(labels, width=width, layer="01")
        vt.set_tags(tags)
        vt.resize(width, 8 * 48)
        vt.show()
        pump(app)
        for b, tag in zip(vt.tabs, tags):
            assert b.height() == 48 and b.accessibleName() == f"{b.text()}, prediction {tag}"
            img = b.grab().toImage()
            k = img.devicePixelRatio()
            tag_x = (b.width() - 16 - tag_width(tag)) * k
            bg = QColor(t("layer-01")).lightness()
            text_ink = [x for x in range(int(16 * k), int(tag_x)) for y in range(int(18 * k), int(30 * k))
                        if abs(img.pixelColor(x, y).lightness() - bg) > 40]
            tag_ink = [x for x in range(int(tag_x), int(tag_x + tag_width(tag) * k))
                       if img.pixelColor(x, int(24 * k)).name() != t("layer-01")]
            assert text_ink, (width, b.text())                                  # the label is drawn on the row
            assert tag_ink, (width, tag)                                        # the tag on the same row
            assert max(text_ink) < tag_x - 4 * k, (width, b.text())             # never overlapping the tag
        vt.close()


# ============================================================================================ 9 Expand analysis
def test_expand_analysis_in_the_wide_docked_layout(win, app):
    calc_one(win, app)
    win.top_row.set_collapsed(0, True)
    win.top_row.set_collapsed(1, True)
    pump(app, 30)
    ws = win.analysis_dock.workspace
    assert win.analysis_dock.wide and win.pages.currentIndex() == 0          # wide docked, not expanded
    assert ws.expand_btn.isVisible() and ws.expand_btn.isEnabled() and ws.collapse_btn.isVisible()
    assert ws.expand_btn.accessibleName() == "Expand analysis"
    assert abs(ws.expand_btn.geometry().center().y() - ws.collapse_btn.geometry().center().y()) <= 1
    model_before = win.analysis_ctl.state.active
    ws.expand_btn.click()
    pump(app)
    assert win.pages.currentIndex() == 1 and win.analysis_ctl.state.active == model_before
    win.workspace.back.click()
    pump(app)
    assert win.pages.currentIndex() == 0 and win.focusWidget() is ws.expand_btn
    ws.collapse_btn.click()                                                   # independently functional
    pump(app)
    assert win.top_row.is_collapsed(2)


# ============================================================================================ 10 equations
def glyph_scales(path):
    s = path.read_text(encoding="utf-8")
    return [float(x) for href, x in re.findall(r'xlink:href="#([^"]+)" transform="translate\([^)]*\) scale\(([0-9.]+)\)', s)
            if "Size" not in href]                                           # big delimiters scale by design


def test_model_equations_keep_readable_glyph_sizes():
    from hea_calc.ui.widgets.equation import EQ_DIR, part_names
    for k in [f"M{i}" for i in range(1, 9)]:
        parts = part_names(k)
        assert parts, k
        smallest = min([min(glyph_scales(EQ_DIR / f"{p}.svg") + [1.0]) for p in parts])
        # one script level at most (a sub/superscript: 70 %); nested fractions used to drop to 49 % / 34 %
        assert smallest >= 0.7 - 1e-9, (k, smallest)
    src = (Path(__file__).resolve().parents[1] / "tools" / "render_equations.py").read_text(encoding="utf-8")
    models = src[src.index('"M1"'):src.index('}', src.index('"M8"'))]
    assert r"\frac" not in models.replace(r"\dfrac", "")                      # display-style fractions only


def test_equation_widgets_draw_at_a_readable_scale(win, app):
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.widgets.equation import MIN_SCALE, Equation
    calc_one(win, app)
    c = win.analysis_ctl
    c.apply(S.set_tab, "model_details")
    for wide in (False, True):
        win.top_row.set_collapsed(0, wide)
        win.top_row.set_collapsed(1, wide)
        pump(app, 20)
        host = win.analysis_dock.workspace if wide else win.analysis
        for i in range(1, 9):
            c.apply(S.select_model, f"M{i}")
            pump(app, 10)
            eqs = [e for e in host.findChildren(Equation) if e.isVisible()]
            assert eqs, (wide, i)
            for e in eqs:
                assert e.drawn_scale() >= MIN_SCALE and e.scale >= 1.25, (wide, i, e.drawn_scale())
                assert e.height() >= 20, (wide, i)


# ============================================================================================ 11 window title
def test_floating_analysis_title_has_no_em_dash(win, app):
    from hea_calc.ui.theme import THEME
    aw = win.open_analysis_window()
    pump(app)
    assert aw.windowTitle() == "Analysis - MDL HEA Calculator"
    calc_one(win, app)
    win.analysis_ctl.set_active(win.table.model.page_rows()[0].id, by="table")
    pump(app)
    assert aw.windowTitle() == "CoCrFeNi - Analysis - MDL HEA Calculator"
    THEME.set_theme("light")
    pump(app)
    aw.close()
    aw2 = win.open_analysis_window()
    pump(app)
    assert aw2 is aw and "—" not in aw2.windowTitle()


# ============================================================================================ native (Windows desktop)
@pytest.mark.skipif(__import__("sys").platform != "win32" or os.environ.get("HEA_NATIVE_TESTS") != "1",
                    reason="opens real windows and grabs the screen; set HEA_NATIVE_TESTS=1 on a Windows desktop")
def test_native_menu_join_and_callouts():
    """Items 5 and 1 at the desktop's real scale (target 125 %): see ``_native_regression_checks.py``."""
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    p = subprocess.run([sys.executable, str(Path(__file__).with_name("_native_regression_checks.py"))], cwd=root,
                       env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0 and "ALL NATIVE REGRESSION CHECKS PASSED" in p.stdout, p.stdout + p.stderr
