"""Collapsed Elements / Composition setup strips and the upper row's height (2026-11-05).

* a vertical strip's title reads bottom to top (rotated 90° counterclockwise), centred across the strip, under its
  expand button; only the title is rotated;
* with both left panels collapsed the upper row grows until Analysis needs no scroll bar of its own, bounded so the
  results table keeps a usable minimum; every other state keeps the design height."""

import os

import pytest

import _ui_support as U
from _ui_support import calc, close, make_window, pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402


def _ink(img, x0, y0, x1, y1, bg):
    """Pixels in [x0, x1) x [y0, y1) that differ clearly from the background colour ``bg``."""
    n = 0
    for y in range(max(0, y0), min(img.height(), y1)):
        for x in range(max(0, x0), min(img.width(), x1)):
            c = img.pixelColor(x, y)
            if abs(c.lightness() - bg.lightness()) > 60:
                n += 1
    return n


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_vertical_title_reads_bottom_to_top_and_is_centred(app, theme, scale):
    from PySide6.QtGui import QColor, QImage, QPainter
    from hea_calc.ui.theme import THEME, t
    from hea_calc.ui.widgets.layouts import STRIP, CollapsedStrip
    THEME.set_theme(theme)
    strip = CollapsedStrip("L")
    strip.setStyleSheet(f"#Panel {{ background: {t('layer-01')}; }}")     # the panel surface of the theme
    strip.resize(STRIP, 300)
    strip.show()
    pump(app, 3)
    r = strip.vertical_title_rect()
    assert r.top() == CollapsedStrip.TITLE_TOP and abs(r.center().x() - STRIP / 2) <= 0.5, "centred across"
    img = QImage(round(STRIP * scale), round(300 * scale), QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(scale)
    img.fill(QColor(t("layer-01")))
    p = QPainter(img)
    strip.render(p, QPoint(0, 0))
    p.end()
    img = img.scaled(STRIP, 300)                                          # back to logical pixels for the check
    bg = img.pixelColor(2, 290)                                           # the strip's own surface
    x0, x1, y0, y1 = int(r.left()), int(r.right()) + 1, int(r.top()), int(r.bottom()) + 1
    assert _ink(img, x0, y0, x1, y1, bg) > 4, "the title is drawn inside its rectangle"
    assert _ink(img, 0, y1 + 1, STRIP, 300, bg) == 0, "nothing below the title"
    # the ink's bounding box, then "L" turned 90° counterclockwise: the stem lies along the bottom of the glyph,
    # the foot runs up its right side (clockwise - the former top-to-bottom reading - puts them top and left)
    pts = [(x, y) for y in range(y0, y1) for x in range(x0, x1)
           if abs(img.pixelColor(x, y).lightness() - bg.lightness()) > 60]
    gx0, gx1 = min(p[0] for p in pts), max(p[0] for p in pts) + 1
    gy0, gy1 = min(p[1] for p in pts), max(p[1] for p in pts) + 1
    third_h, third_w = max(1, (gy1 - gy0) // 3), max(1, (gx1 - gx0) // 3)
    assert _ink(img, gx0, gy1 - third_h, gx1, gy1, bg) > _ink(img, gx0, gy0, gx1, gy0 + third_h, bg), "reads upward"
    assert _ink(img, gx1 - third_w, gy0, gx1, gy1, bg) > _ink(img, gx0, gy0, gx0 + third_w, gy1, bg), "foot right"
    # the expand button is not rotated: it stays the 40 px square at the top
    assert strip.button.geometry().topLeft() == QPoint(0, 0) and strip.button.width() == STRIP
    strip.close()


def test_both_strips_share_the_title_geometry(win, app):
    tr = win.top_row
    tr.set_collapsed(0, True)
    tr.set_collapsed(1, True)
    pump(app, 10)
    a, b = tr.strips[0], tr.strips[1]
    from PySide6.QtGui import QFontMetricsF
    from hea_calc.ui.theme import BODY_COMPACT_01, font
    for s in (a, b):                                       # a tall strip shows the whole title: no ellipsis
        assert s.vertical_title_rect().height() >= QFontMetricsF(font(BODY_COMPACT_01), s).horizontalAdvance(s.title)
    assert a.vertical_title_rect().left() == b.vertical_title_rect().left()
    assert a.vertical_title_rect().top() == b.vertical_title_rect().top() == a.TITLE_TOP
    short = a.height() - a.TITLE_TOP - a.TITLE_BOTTOM_MIN
    a.resize(a.width(), a.TITLE_TOP + 30)
    assert a.vertical_title_rect().height() <= 30 - a.TITLE_BOTTOM_MIN, "a short strip elides, never clips"
    assert short > 0


def _state(w, app):
    pump(app, 40)
    tr = w.top_row
    from PySide6.QtWidgets import QScrollArea
    bars = [sa.verticalScrollBar().maximum() for sa in w.analysis_dock.findChildren(QScrollArea)
            if sa.isVisible() and sa.widget() is not None]
    geos = [(s.y(), s.height()) for s in tr.strips if s.isVisible()]
    geos += [(p.y(), p.height()) for p, *_ in tr.panels if p.isVisible()]
    return tr.height(), max(bars, default=0), geos


def _table_min(w):
    from hea_calc.ui.widgets.results_table import HEADER_HEIGHT, ROW_HEIGHT
    return w.table.TOOLBAR_HEIGHT + HEADER_HEIGHT + w.FIT_TABLE_ROWS * ROW_HEIGHT + w.table.PAGINATION_HEIGHT


def test_upper_row_height_for_each_collapse_state(app):
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.theme import TOP_ROW_HEIGHT
    w = make_window(app, "light", size=(1920, 1040))
    try:
        calc(w, app)
        tr, c = w.top_row, w.analysis.c
        h, _, _ = _state(w, app)
        assert h == TOP_ROW_HEIGHT, "both expanded: the design layout"
        for i in (0, 1):                                                 # only one collapsed: unchanged
            tr.set_collapsed(i, True)
            h, _, geos = _state(w, app)
            assert h == TOP_ROW_HEIGHT and tr.fitted_height is None, i
            assert {g for g in geos} == {(0, TOP_ROW_HEIGHT)}, "strip and panels share top and bottom"
            tr.set_collapsed(i, False)
        tr.set_collapsed(0, True)
        tr.set_collapsed(1, True)
        h, overflow, geos = _state(w, app)
        limit = w.upper_row_limit()
        assert TOP_ROW_HEIGHT < h <= limit, (h, limit)
        assert overflow == 0 or h == limit, "grown until Analysis needs no scroll bar, or up to the limit"
        assert {g for g in geos} == {(0, h)}, "the strips stretch with Analysis: one top, one bottom"
        assert w.table.height() >= _table_min(w), "the results table stays usable"
        assert w.scroll.verticalScrollBar().maximum() == 0, "no page scroll bar with a single result"
        # content-driven: a short view lets the row go back down, a long one grows it again
        c.apply(S.set_tab, "models")
        h_models, overflow, _ = _state(w, app)
        assert overflow == 0 and h_models <= h
        c.apply(S.set_tab, "descriptors")
        h_desc, overflow, _ = _state(w, app)
        assert overflow == 0 or h_desc == w.upper_row_limit()
        # stable: nothing changes without a cause
        again = _state(w, app)[0]
        assert again == h_desc
        # reopening either panel restores the design height; nothing is stored for the fitted height
        tr.set_collapsed(0, False)
        h, _, geos = _state(w, app)
        assert h == TOP_ROW_HEIGHT and tr.fitted_height is None and {g for g in geos} == {(0, TOP_ROW_HEIGHT)}
        assert "fitted" not in " ".join(w.settings.allKeys())
        tr.set_collapsed(0, True)
        assert _state(w, app)[0] > TOP_ROW_HEIGHT
        tr.set_collapsed(1, False)
        assert _state(w, app)[0] == TOP_ROW_HEIGHT
    finally:
        close(app, w)


def test_short_window_keeps_the_analysis_scroll_bar(app):
    from hea_calc.ui.theme import TOP_ROW_HEIGHT
    w = make_window(app, "dark", size=(1366, 768))
    try:
        calc(w, app)
        w.top_row.set_collapsed(0, True)
        w.top_row.set_collapsed(1, True)
        h, _, geos = _state(w, app)
        assert w.upper_row_limit() < TOP_ROW_HEIGHT
        assert h == TOP_ROW_HEIGHT, "never below the design height, never above the window's room"
        assert {g for g in geos} == {(0, TOP_ROW_HEIGHT)}
    finally:
        close(app, w)


def test_resize_theme_and_collection_keep_the_fit_bounded_and_stable(app):
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.theme import THEME, TOP_ROW_HEIGHT
    w = make_window(app, "light", size=(1920, 1040))
    try:
        calc(w, app)
        tr = w.top_row
        tr.set_collapsed(0, True)
        tr.set_collapsed(1, True)
        first = _state(w, app)[0]
        for size in ((1920, 900), (1920, 1200), (1920, 1040)):
            w.resize(*size)
            h, overflow, geos = _state(w, app)
            assert TOP_ROW_HEIGHT <= h <= max(TOP_ROW_HEIGHT, w.upper_row_limit()), size
            assert overflow == 0 or h in (TOP_ROW_HEIGHT, w.upper_row_limit()), size
            assert w.table.height() >= _table_min(w) or h == TOP_ROW_HEIGHT, size
        assert _state(w, app)[0] == first, "back to the same size: the same height"
        THEME.set_theme("dark")
        assert _state(w, app)[0] == first
        THEME.set_theme("light")
        w.analysis.c.apply(S.switch_context, S.COLLECTION)
        h, overflow, _ = _state(w, app)
        assert TOP_ROW_HEIGHT <= h <= w.upper_row_limit() and (overflow == 0 or h == w.upper_row_limit())
        # the separate Analysis window is not affected
        aw = w.open_analysis_window()
        pump(app, 10)
        assert _state(w, app)[0] == h
        close(app, aw)
    finally:
        close(app, w)
