"""Results table rows and header rule across the whole viewport, and the main panels' spacing (2026-11-04)."""

import os

import pytest

import _ui_support as U
from _ui_support import calc, close, make_window, pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402


@pytest.mark.parametrize("size", [(1920, 1040), (1366, 768)])
def test_panels_start_16px_below_the_title_bar(app, size):
    from hea_calc.ui.theme import TITLEBAR_PANEL_GAP
    w = make_window(app, size=size)
    try:
        bar_bottom = 32
        top = w.top_row.mapTo(w, QPoint(0, 0)).y()
        assert TITLEBAR_PANEL_GAP == 16 and top - bar_bottom == 16
        assert w.header.height() == 36                                 # the bar and its 4 px state line
    finally:
        close(app, w)


def test_result_rows_extend_to_the_viewport_edge(win, app):
    from hea_calc.ui.theme import t
    calc(win, app)
    view = win.table.view
    keys = list(view.m.keys)
    # user-resized columns keep their widths (``user_widths``), so they can end before the viewport's right edge -
    # the case of the reported screenshot
    view.user_widths = {k: 70 for k in keys}
    view._distribute()
    pump(app, 20)
    widths = [view.header.sectionSize(i) for i in range(len(keys))]
    assert widths == [70] * len(keys), "the user's widths are kept, nothing is stretched"
    assert view.header.length() < view.viewport().width(), "the columns leave room on the right"
    assert view.m.columnCount() == len(keys), "no filler column"
    tail = view.row_tail_rect(0)
    assert tail.width() > 0 and tail.right() == view.viewport().width() - 1
    view._set_hover(0)
    pump(app)
    img = view.viewport().grab().toImage()
    x = view.viewport().width() - 4
    y = view.rowViewportPosition(0) + 8
    assert img.pixelColor(x, y).name() == t("row-hover"), "the hover band reaches the right edge"
    assert img.pixelColor(x, view.rowViewportPosition(0) + 31).name() == t("row-border"), "the row rule too"
    view._set_hover(-1)
    pump(app)
    img = view.viewport().grab().toImage()
    assert img.pixelColor(x, y).name() != t("row-hover")
    # columns that overflow the viewport leave no strip (horizontal scrolling is unchanged)
    view.user_widths = {k: 400 for k in keys}
    view._distribute()
    pump(app, 20)
    assert view.header.length() > view.viewport().width() and view.row_tail_rect(0).width() == 0
    assert view.horizontalScrollBar().maximum() > 0, "horizontal scrolling still reaches the last column"
    view.user_widths = {}
    view._distribute()


def test_row_tails_with_an_empty_table(win, app):
    view = win.table.view
    assert view.m.rowCount() == 0
    view.viewport().grab()                                             # paints without rows (no error)


def test_the_rule_above_the_first_row_reaches_the_viewport_edge(win, app):
    """Screenshot 1 (2026-11-04): with user-narrowed columns the 1 px rule under the header - the top border of the
    first row - stopped where the last column ended.  It belongs to the header and now spans its whole width."""
    from hea_calc.ui.theme import t
    calc(win, app)
    view = win.table.view
    view.user_widths = {k: 70 for k in view.m.keys}
    view._distribute()
    pump(app, 20)
    hdr = view.header
    assert hdr.length() < hdr.viewport().width() and hdr.tail_rect().width() > 0
    img = hdr.viewport().grab().toImage()
    y = img.height() - 1
    xs_tail = range(hdr.length() + 2, img.width() - 1, 7)
    assert {img.pixelColor(x, y).name() for x in xs_tail} == {t("row-border")}, "the rule continues to the edge"
    assert {img.pixelColor(x, y - 4).name() for x in xs_tail} == {t("header-row")}, "header surface, no text"
    # the same y, colour and thickness as under the sections: no step or double line at the last column's edge
    last = hdr.length() - 3
    assert img.pixelColor(last, y).name() == t("row-border") and img.pixelColor(last, y - 1).name() != t("row-border")
    assert img.pixelColor(hdr.length() + 2, y - 1).name() != t("row-border"), "one hairline, not two"
    # columns filling the viewport again: no tail, nothing drawn beyond the sections
    view.user_widths = {}
    view._distribute()
    pump(app, 20)
    assert hdr.tail_rect().width() == 0


_FORMULA_OR_REFERENCE = r"[=≤≥<>Σ∑√±^_|]|[A-Za-z]ᵢ|\bet al\b|\(\d{4}\)|\b(19|20)\d{2}\b|doi|https?:|www\.|&|<sub>|<sup>|\$"


def test_column_tooltips_are_short_plain_descriptions():
    """Results-table heading and Table columns / Filter results tooltips: what the value is (and its unit) in plain
    language - no equation, citation, DOI or URL; the definitions and sources stay in Documentation."""
    import re
    from hea_calc.core.results import COLUMNS
    for c in COLUMNS:
        if c.key in ("name", "composition"):
            continue
        assert c.tooltip and c.chooser_tip == c.tooltip, c.key
        assert len(c.tooltip) <= 140 and c.tooltip.count(". ") <= 2, (c.key, c.tooltip)
        assert not re.search(_FORMULA_OR_REFERENCE, c.tooltip, re.IGNORECASE), (c.key, c.tooltip)
    from hea_calc.core.docs import source                                    # the full material stays in Documentation
    assert "Guo & Liu" in source("results-table") and "Δχ" in source("results-table")
    assert "Takeuchi" in source("references")


def test_table_heading_and_chooser_show_the_plain_descriptions(win, app):
    from PySide6.QtCore import Qt
    from hea_calc.core.results import COLUMN_BY_KEY
    from hea_calc.ui.widgets.dialogs import ColumnsDialog, FilterRule
    m = win.table.view.m
    for i, key in enumerate(m.keys):
        tip = m.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
        col = COLUMN_BY_KEY[key]
        assert tip == (col.tooltip or col.header), key
    d = ColumnsDialog(list(m.keys), win)
    try:
        for key, cb in d.checks.items():
            assert cb.toolTip() == COLUMN_BY_KEY[key].tooltip, key
    finally:
        d.close()
    rule = FilterRule("dhmix")
    name = rule.layout().itemAt(0).widget()
    assert name.toolTip() == COLUMN_BY_KEY["dhmix"].tooltip
    rule.deleteLater()
