"""High-DPI rendering, responsive layout, scroll ownership and Carbon tooltip/toggletip behaviour.

Fractional device pixel ratios are exercised by rendering into QImages with
``setDevicePixelRatio(1.25 / 1.5)`` at several logical offsets (so the widget lands on different
fractional physical positions - the situation that made a 2 px QPen frame 2 px on one side and
3 px on the other at Windows 125 %).  Layout is exercised at the logical client sizes of the
target 2160 x 1440 display at Windows 100 / 125 / 150 % (see tools/dpi_harness.py).
"""

import math
import os
import re
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFocusEvent, QImage, QKeyEvent, QPainter, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hea_calc.ui.responsive import distribute, tab_padding, tile_size_for  # noqa: E402

DPRS = (1.0, 1.25, 1.5)
OFFSETS = ((0, 0), (1, 1), (2, 3), (3, 2), (5, 7))
MATEBOOK_CLIENTS = {1.0: (2160, 1361), 1.25: (1728, 1073), 1.5: (1440, 881)}


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


def add_rows(win, n):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from screenshot import demo_rows
    demo_rows(win, n)
    for _ in range(5):
        QApplication.processEvents()


def render(widget, dpr, offset=(0, 0), bg="#000000"):
    """``widget`` painted at ``dpr`` with its origin at the logical ``offset``."""
    w = widget.width() + offset[0] + 4
    h = widget.height() + offset[1] + 4
    img = QImage(math.ceil(w * dpr), math.ceil(h * dpr), QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(bg))
    widget.render(img, QPoint(*offset))
    return img


def runs_from_edges(img, color, rect=None):
    """Frame thickness (device px) on each side, along the middle row / column, away from corners."""
    color = QColor(color).name()
    x0, y0, w, h = rect or (0, 0, img.width(), img.height())
    cx, cy = x0 + w // 2, y0 + h // 2

    def first_run(points):
        n, started = 0, False
        for x, y in points:
            hit = img.pixelColor(x, y).name() == color
            if hit:
                started = True
                n += 1
            elif started:
                break
        return n
    return {
        "top": first_run((cx, y) for y in range(y0, y0 + h)),
        "bottom": first_run((cx, y) for y in range(y0 + h - 1, y0 - 1, -1)),
        "left": first_run((x, cy) for x in range(x0, x0 + w)),
        "right": first_run((x, cy) for x in range(x0 + w - 1, x0 - 1, -1)),
    }


# =========================================================================== pure layout rules
def test_distribute_reproduces_the_design_and_compresses_proportionally():
    refs, mins, maxs = (596, 457, 787), (506, 400, 454), (596, 457, None)
    assert distribute(1840, refs, mins, maxs) == [596, 457, 787]          # 1920 px window
    assert distribute(2080, refs, mins, maxs) == [596, 457, 1027]         # 2160: only Details grows
    w125 = distribute(1648, refs, mins, maxs)                              # 1728 px window
    assert sum(w125) == 1648 and all(abs(w / r - 1648 / 1840) < 0.01 for w, r in zip(w125, refs))
    assert distribute(1360, refs, mins, maxs) == [506, 400, 454]          # 1440 px window
    assert distribute(1000, refs, mins, maxs) == [506, 400, 454]          # below: minimums (scroll)
    for avail in range(1360, 2400, 7):
        out = distribute(avail, refs, mins, maxs)
        assert sum(out) == avail and all(o >= m for o, m in zip(out, mins))


def test_tile_and_tab_sizing_rules():
    assert tile_size_for(556) == 29                       # design: 18 x 31 - 2
    assert tile_size_for(466) == 24                       # 150 %: TILE_SIZE_MIN
    assert tile_size_for(300) == 24                       # never below the minimum
    texts = [62, 77, 48, 89, 67]                          # semibold tab labels
    assert tab_padding(10_000, texts) == 16
    assert tab_padding(414, texts) == 6                   # 454 px Details panel at 150 %


# =========================================================================== crisp strokes
@pytest.mark.parametrize("dpr", DPRS)
def test_crisp_frame_is_identical_on_all_sides(app, dpr):
    from hea_calc.ui import crisp
    expected = max(1, math.floor(2 * dpr))
    for ox, oy in ((0, 0), (0.4, 0.8), (1.0, 1.0), (2.6, 3.2), (31.0, 62.0)):
        img = QImage(math.ceil(200 * dpr), math.ceil(200 * dpr), QImage.Format.Format_ARGB32)
        img.setDevicePixelRatio(dpr)
        img.fill(QColor("#000000"))
        p = QPainter(img)
        p.translate(ox, oy)
        crisp.frame(p, QRectF(3, 3, 29, 29), 2, "#ffffff")
        crisp.frame(p, QRectF(40, 3, 60, 32), 2, "#ff0000", radius=7)
        p.end()
        sq = runs_from_edges(img, "#ffffff", (math.floor(ox * dpr), math.floor(oy * dpr),
                                              math.ceil(36 * dpr), math.ceil(36 * dpr)))
        assert set(sq.values()) == {expected}, (dpr, ox, oy, sq)
        rx0 = math.floor((40 + ox) * dpr) - 2
        rd = runs_from_edges(img, "#ff0000", (rx0, math.floor(oy * dpr), math.ceil(64 * dpr), math.ceil(40 * dpr)))
        assert set(rd.values()) == {expected}, (dpr, ox, oy, rd)


@pytest.mark.parametrize("dpr", DPRS)
def test_selected_periodic_tile_border_is_symmetric(app, dpr):
    """P0: a selected tile's 2 px frame must have the same device thickness on all four sides."""
    from hea_calc.ui.theme import THEME, t
    from hea_calc.ui.widgets.element_panel import ElementTile
    for theme in ("dark", "light"):
        THEME.set_theme(theme)
        for size in (29, 25, 24):
            tile = ElementTile("Fe")
            tile.setFixedSize(size, size)
            tile.setChecked(True)
            for off in OFFSETS:
                img = render(tile, dpr, off)
                sides = runs_from_edges(img, t("tile-selected-border"))
                assert set(sides.values()) == {math.floor(2 * dpr)}, (theme, size, dpr, off, sides)
    THEME.set_theme("dark")


@pytest.mark.parametrize("dpr", DPRS)
def test_tiles_on_the_real_grid_have_symmetric_borders(app, win, dpr):
    """Every tile of the laid-out table (each at its own fractional physical offset)."""
    from hea_calc.ui.theme import t
    table = win.elements.table
    for el in ("H", "Cr", "Mn", "Fe", "Og", "Lu", "Lr"):
        table.tiles[el].setChecked(True)
    img = render(table, dpr, (20, 0))
    for el in ("H", "Cr", "Mn", "Fe", "Og", "Lu", "Lr"):
        tile = table.tiles[el]
        x0 = math.floor((20 + tile.x()) * dpr) - 2
        y0 = math.floor(tile.y() * dpr) - 2
        rect = (max(0, x0), max(0, y0), math.ceil(tile.width() * dpr) + 4, math.ceil(tile.height() * dpr) + 4)
        sides = runs_from_edges(img, t("tile-selected-border"), rect)
        assert set(sides.values()) == {math.floor(2 * dpr)}, (el, dpr, sides)


@pytest.mark.parametrize("dpr", DPRS)
def test_input_border_and_invalid_frame_are_crisp(app, dpr):
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.composition_panel import Field
    f_frame = True  # noqa: F841
    f = Field(88)
    f.setFrame(False)
    f.setText("1.0000")
    for off in OFFSETS:
        img = render(f, dpr, off, bg="#262626")
        # bottom rule: exactly one device row of border-strong-02 under the field, at any offset
        rule = runs_from_edges(img, t("border-strong-02"))
        assert rule["bottom"] == 1, (dpr, off, rule)
    f.set_invalid(True, "Enter a number")
    for off in OFFSETS:
        img = render(f, dpr, off, bg="#262626")
        sides = runs_from_edges(img, t("support-error"))
        assert set(sides.values()) == {math.floor(2 * dpr)}, (dpr, off, sides)


@pytest.mark.parametrize("dpr", DPRS)
def test_tab_underline_is_the_same_under_every_tab(app, dpr):
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.common import LineTabs
    tabs = LineTabs(["Overview", "Descriptors", "Models", "Model details", "All results"])
    tabs.resize(600, 32)
    tabs.show()
    QApplication.processEvents()
    for i in range(5):
        tabs.set_index(i)
        for b in tabs.buttons:          # the 2 px focus ring would cover the underline
            b.clearFocus()
        QApplication.processEvents()
        for off in ((0, 0), (1, 1), (3, 2)):
            img = render(tabs, dpr, off)
            b = tabs.buttons[i]
            cx = math.floor((off[0] + b.x() + b.width() / 2) * dpr)
            col = [img.pixelColor(cx, y).name() for y in range(img.height())]
            assert col.count(QColor(t("border-interactive")).name()) == math.floor(2 * dpr), (i, dpr, off)
    tabs.close()


@pytest.mark.parametrize("dpr", DPRS)
def test_table_row_separators_are_one_device_pixel(app, win, dpr):
    from hea_calc.ui.theme import t
    add_rows(win, 12)
    view = win.table.view
    img = render(view.viewport(), dpr, (0, 1))
    col = [img.pixelColor(math.floor(400 * dpr), y).name() for y in range(img.height())]
    border = QColor(t("row-border")).name()
    runs, n = [], 0
    for c in col:
        if c == border:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    assert len(runs) >= 12 and set(runs) == {1}, (dpr, runs)


def test_focus_ring_of_icon_button_is_crisp(app):
    from hea_calc.ui import crisp  # noqa: F401
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.common import IconButton
    b = IconButton("filter", "Filter results")
    b.resize(32, 32)
    b.show()
    b.setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    if not b.hasFocus():
        pytest.skip("no focus on the offscreen platform")
    for dpr in DPRS:
        img = render(b, dpr, (1, 1))
        sides = runs_from_edges(img, t("focus"))
        assert set(sides.values()) == {math.floor(2 * dpr)}, (dpr, sides)
    b.close()


# =========================================================================== responsive layout
@pytest.mark.parametrize("scale", sorted(MATEBOOK_CLIENTS))
def test_upper_panels_fit_and_table_fills_width_at_each_scale(app, scale):
    w = make_window(app, MATEBOOK_CLIENTS[scale])
    try:
        add_rows(w, 6)
        rep = w.layout_report()
        assert not rep["horizontalOverflow"], rep
        e, c, d = rep["upperPanels"]
        width = MATEBOOK_CLIENTS[scale][0]
        if rep["detailsStacked"]:     # Analysis below Element + Composition (the row cannot hold 805 px)
            assert e + c + 3 * 20 == width and d == width - 40, rep
        else:
            assert e + c + d + 4 * 20 == width, rep
        assert e >= 506 and c == 457 and d >= 454, rep        # Composition setup is not responsive
        # results table spans the content width; default columns fill it exactly, no scroll bars
        assert rep["tableWidth"] == MATEBOOK_CLIENTS[scale][0] - 40, rep
        assert rep["tableColumnsSum"] == rep["tableViewportWidth"], rep
        assert not rep["tableHorizontalScrollbarVisible"], rep
        assert not rep["tableVerticalScrollbarVisible"] and rep["tableVerticalScrollRange"] == 0, rep
        # periodic table and Analysis tabs fit inside their panels
        el = w.elements
        assert el.table.x() + el.table.width() <= el.width() - 20
        for tabs in (w.analysis.comp_tabs, w.analysis.coll_tabs):
            last = tabs.buttons[-1]
            assert last.x() + last.width() <= tabs.width(), "all four tabs visible"
        info = el.info
        right = max(g.x() + g.width() for g in info.group_wraps)
        assert right <= info.width() - 20, (right, info.width())
    finally:
        w.close()


def test_design_viewport_reproduces_reference_geometry(app):
    """1920 px: panels at the current Figma positions (20 / 618 / 1095: Elements 578, Composition setup 457,
    Analysis 805 px, right edge 1900)."""
    w = make_window(app, (1920, 1000))
    try:
        xs = [p.mapTo(w, QPoint(0, 0)).x() for p in (w.elements, w.composition, w.details)]
        assert xs == [20, 618, 1095]
        assert w.elements.width() == 578 and w.composition.width() == 457
        assert w.details.width() == 805
        assert w.details.mapTo(w, QPoint(0, 0)).x() + w.details.width() == 1900
        assert w.elements.table.tile_size == 28        # 578 px panel: 18 × 28 px tiles + 2 px gaps (Figma)
        assert not w.layout_report()["mainScrollbarVisible"], "no unnecessary main scroll bar"
    finally:
        w.close()


# =========================================================================== scroll ownership
def test_main_area_owns_vertical_scroll_and_header_sticks(app):
    w = make_window(app, MATEBOOK_CLIENTS[1.5])
    try:
        add_rows(w, 40)
        rep = w.layout_report()
        assert rep["mainScrollbarVisible"], "40 rows overflow the 150 % viewport"
        assert rep["tableVerticalScrollRange"] == 0, "the table never scrolls by itself"
        assert w.table.view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        # the table is as tall as its page: header + 44 rows (4 demo rows from _add_rows? count them)
        rows = w.table.model.rowCount()
        assert w.table.view.height() >= 32 + rows * 32
        assert not w.sticky.isVisible()
        sb = w.scroll.verticalScrollBar()
        # scroll so the table header is just above the viewport
        hdr_top = w.table.view.header.mapTo(w.content, QPoint(0, 0)).y()
        sb.setValue(hdr_top + 100)
        w._place_sticky()
        QApplication.processEvents()
        assert w.sticky.isVisible(), "sticky header pinned once the real header scrolled away"
        assert w.sticky.y() == 0 and w.sticky.height() == 32
        src = w.table.view.header
        assert w.sticky.x() == src.mapTo(w.scroll.viewport(), QPoint(0, 0)).x()
        assert w.sticky.width() == src.width()
        assert w.sticky.matches_source()
        # column set changes propagate to the pinned header
        keys = list(w.table.model.keys)
        w.table.model.set_keys([k for k in keys if k != "vec"])
        QApplication.processEvents()
        w._place_sticky()
        assert w.sticky.count() == len(keys) - 1 and w.sticky.matches_source()
        # sorting through the pinned header sorts the table and shows the indicator in both
        w.sticky.sectionClicked.emit(1)
        assert w.table.model.sort_key == w.table.model.keys[1]
        # scrolled back up: the natural header is visible again, the pinned one goes away
        sb.setValue(0)
        w._place_sticky()
        assert not w.sticky.isVisible()
    finally:
        w.close()


def test_wheel_over_table_scrolls_the_main_area(app):
    w = make_window(app, MATEBOOK_CLIENTS[1.5])
    try:
        add_rows(w, 40)
        sb = w.scroll.verticalScrollBar()
        sb.setValue(0)
        vp = w.table.view.viewport()
        pos = QPointF(200, 40)
        ev = QWheelEvent(pos, QPointF(vp.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, -120),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(vp, ev)
        # the table declines the vertical gesture (Qt then propagates a real, spontaneous wheel
        # event to the parents; a synthesized one is not propagated, so deliver it onwards here)
        assert not ev.isAccepted(), "the table must not consume a vertical wheel gesture"
        assert w.table.view.verticalScrollBar().value() == 0
        outer = w.scroll.viewport()
        p2 = QPointF(vp.mapTo(outer, pos.toPoint()))
        ev2 = QWheelEvent(p2, QPointF(outer.mapToGlobal(p2.toPoint())), QPoint(0, 0), QPoint(0, -120),
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(outer, ev2)
        QApplication.processEvents()
        assert sb.value() > 0, "the main content area scrolls"
    finally:
        w.close()


def test_scrollbars_are_four_pixels_visible(app):
    from hea_calc.ui.theme import SCROLLBAR_HIT, SCROLLBAR_VISIBLE, t
    from hea_calc.ui.widgets.scroll import ThinScrollBar
    assert SCROLLBAR_VISIBLE == 4
    bar = ThinScrollBar(Qt.Orientation.Vertical)
    bar.setRange(0, 500)
    bar.setPageStep(100)
    bar.resize(SCROLLBAR_HIT, 300)
    assert bar.sizeHint().width() == SCROLLBAR_HIT
    assert bar.thumb_rect().width() == 4
    for dpr in DPRS:
        img = render(bar, dpr, (1, 0))
        y = math.floor(20 * dpr)
        row = [img.pixelColor(x, y).name() for x in range(img.width())]
        assert row.count(QColor(t("scrollbar-thumb")).name()) == math.floor(4 * dpr), dpr


def test_main_scrollbar_is_an_overlay_in_the_right_margin(app):
    w = make_window(app, MATEBOOK_CLIENTS[1.5])
    try:
        before = w.table.width()
        add_rows(w, 40)
        ov = w.scroll.overlay
        assert ov.isVisible()
        assert w.table.width() == before, "the main scroll bar takes no width from the content"
        vp = w.scroll.viewport()
        # visible 4 px thumb centred 10 px from the right edge: inside the 20 px content margin
        centre = ov.x() + ov.thumb_rect().center().x()
        assert vp.width() - centre == pytest.approx(10, abs=1)
    finally:
        w.close()


# =========================================================================== tooltip / toggletip
def test_tooltip_hover_focus_and_escape(app, win):
    from hea_calc.ui.widgets.tooltip import ENTER_DELAY_MS, LEAVE_DELAY_MS, install_tooltips
    ctl = install_tooltips(app)
    btn = win.table.delete_btn
    QApplication.sendEvent(btn, QEvent(QEvent.Type.Enter))
    assert not ctl.visible(), "Carbon enter delay"
    QTest.qWait(ENTER_DELAY_MS + 60)
    assert ctl.visible() and ctl.tip.text == "Clear table"
    QApplication.sendEvent(btn, QEvent(QEvent.Type.Leave))
    assert LEAVE_DELAY_MS == 0 and not ctl.visible(), "no post-hover linger: hidden the moment the pointer leaves"
    # keyboard focus shows it immediately and keeps it while the trigger has focus; Esc dismisses
    QApplication.sendEvent(btn, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    assert ctl.visible()
    QApplication.sendEvent(btn, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not ctl.visible()
    # focus loss hides a keyboard tooltip at once
    QApplication.sendEvent(btn, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    assert ctl.visible()
    QApplication.sendEvent(btn, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason))
    assert not ctl.visible()
    # Qt's own tooltip request is swallowed (no native QToolTip)
    from PySide6.QtGui import QHelpEvent
    help_ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), btn.mapToGlobal(QPoint(5, 5)))
    assert ctl.eventFilter(btn, help_ev) is True
    ctl.hide()


def test_result_cells_have_no_tooltip_but_headers_use_the_carbon_bubble(app, win):
    """Product decision: no body-cell tooltips (full data lives in Calculation details); column
    headers explain name / unit / meaning through the Carbon tooltip, anchored to the section."""
    from PySide6.QtGui import QHelpEvent
    from hea_calc.ui.widgets.tooltip import install_tooltips
    ctl = install_tooltips(app)
    add_rows(win, 3)
    view = win.table.view
    m = win.table.model
    for c in range(m.columnCount()):
        assert m.data(m.index(0, c), Qt.ItemDataRole.ToolTipRole) is None
    col = m.keys.index("M1")
    rect = view.visualRect(m.index(0, col))
    ev = QHelpEvent(QEvent.Type.ToolTip, rect.center(), view.viewport().mapToGlobal(rect.center()))
    assert ctl.eventFilter(view.viewport(), ev) is True     # swallowed: no native tooltip either
    assert not ctl.visible()
    hdr = view.header
    x = hdr.sectionViewportPosition(col) + 5
    ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(x, 10), hdr.viewport().mapToGlobal(QPoint(x, 10)))
    assert ctl.eventFilter(hdr.viewport(), ev) is True
    assert ctl.visible() and "M1" in ctl.tip.text
    g = hdr.viewport().mapToGlobal(QPoint(hdr.sectionViewportPosition(col), 0))
    assert ctl.tip.anchor.topLeft() == g, "anchored to the header section"
    ctl.hide()


def test_tooltip_respects_screen_edges(app):
    from hea_calc.ui.widgets.tooltip import CarbonToolTip
    tip = CarbonToolTip()
    screen = QRect(0, 0, 1440, 900)
    tip.show_for(QRect(1420, 10, 16, 16), "Filter results (active)", screen)
    assert tip.x() + tip.width() - 1 <= screen.right()
    assert tip._below, "no room above the anchor: flipped below"
    assert tip.y() >= 10 + 16
    tip.show_for(QRect(2, 400, 16, 16), "Previous page", screen)
    assert tip.x() >= 0
    tip.hide()


def test_model_support_is_a_keyboard_accessible_toggletip(app, win):
    from hea_calc.ui.widgets.tooltip import InfoButton
    trig = next(b for b in win.elements.findChildren(InfoButton))
    assert trig.accessibleName() == "Model support legend"
    assert not trig.toolTip(), "a toggletip trigger is not also a hover tooltip"
    trig.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(trig, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert trig.is_open()
    pop = trig.popup
    assert "Model support for the highlighted element" in pop.label.text()
    from hea_calc.ui.widgets.tooltip import _ToggletipIconRow
    rows = pop.findChildren(_ToggletipIconRow)
    # the four status icons are vector-painted rows (crisp at any DPR), never raster <img> or unicode symbols
    assert [r.icon_name for r in rows] == ["status_ok", "status_warn", "status_pair", "status_none"]
    assert not any("<img" in lab.text() for lab in pop.labels)
    assert pop.width() == 308
    QTest.keyClick(pop, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert not trig.is_open()


# =========================================================================== tokens / themes
def test_corner_radius_token_is_the_only_numeric_radius():
    from hea_calc.ui.theme import CORNER_RADIUS
    assert CORNER_RADIUS == 7
    ui = Path(__file__).resolve().parents[1] / "hea_calc" / "ui"
    literal = re.compile(r"RoundedRect\([^)]*,\s*\d+(\.\d+)?\s*,\s*\d+(\.\d+)?\s*\)")
    offenders = [f"{p.name}: {m.group(0)}" for p in ui.rglob("*.py") for m in literal.finditer(p.read_text("utf-8"))]
    assert not offenders, offenders
    qss = (ui / "theme.py").read_text("utf-8")
    assert not re.search(r"border-radius:\s*[1-9]", qss), "no stray QSS radii"


def test_theme_switch_with_sticky_header_active(app):
    from hea_calc.ui.theme import THEME
    w = make_window(app, MATEBOOK_CLIENTS[1.25])
    try:
        add_rows(w, 40)
        sb = w.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        w._place_sticky()
        assert w.sticky.isVisible()
        THEME.set_theme("light")
        QApplication.processEvents()
        w._place_sticky()
        assert w.sticky.isVisible() and w.sticky.matches_source()
        rep = w.layout_report()
        assert not rep["horizontalOverflow"] and rep["tableVerticalScrollRange"] == 0
    finally:
        THEME.set_theme("dark")
        w.close()


def test_composition_panel_states_fit_at_150_percent(app):
    """At Windows 150 % (Composition setup keeps its 457 px design width): no clipped title, no overlapping radio labels, no overlapped
    helper in expression mode, and value fields wide enough for five-digit values."""
    from PySide6.QtGui import QFontMetrics
    from hea_calc.ui.theme import BODY_COMPACT_01, font
    w = make_window(app, MATEBOOK_CLIENTS[1.5])
    try:
        comp = w.composition
        assert comp.width() == 457
        for el in ("Cr", "Mn", "Fe", "Co", "Ni"):
            w.elements.table.tiles[el].click()
        QApplication.processEvents()
        # single: radios fit their columns, values unclipped
        fm = QFontMetrics(font(BODY_COMPACT_01))
        for key, rb in comp.single.radios.items():
            spacing = 4 if rb.property("compact") else 8
            assert 20 + spacing + fm.horizontalAdvance(rb.text()) <= rb.width() + 1, key
        f = next(iter(comp.single.rows.values())).fields["at"]
        m = f.textMargins()
        assert f.width() - m.left() - m.right() >= fm.horizontalAdvance("14.2857"), "value clipped"
        # sweep: the title keeps its full width next to the unit select and the switcher
        comp.set_mode(1)
        QApplication.processEvents()
        assert comp.title.width() >= comp.title.sizeHint().width(), "panel title clipped"
        # expression: the wrapped helper sits below the field, not over it
        comp.set_mode(2)
        comp.expr.edit.setPlainText("(FeCoNi)1-xAlx\n0 <= x <= 1, step=0.1")
        comp.expr.parse()
        QApplication.processEvents()
        e = comp.expr
        assert e.feedback.y() >= e.edit.y() + e.edit.height(), (e.feedback.geometry(), e.edit.geometry())
        assert e.minimumSizeHint().height() <= e.height()
    finally:
        w.close()
