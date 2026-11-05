"""Tooltip pointers aim at the control that triggered them (2026-11-05).

A check box in a Table columns grid cell, or a fixed-width label, is much wider than what it shows; the pointer used
to aim at the middle of that empty width, over a neighbouring row.  ``tooltip.anchor_rect`` gives the visible part;
``place_popover`` keeps the pointer on it when the bubble is pushed back on screen."""

import os

import pytest

import _ui_support as U
from _ui_support import calc, pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402


def _caret_global(tip):
    """Global x (top / bottom placement) or y (left / right) of the pointer's tip."""
    pl = tip.placement
    return tip.pos().x() + pl.caret if pl.side in ("top", "bottom") else tip.pos().y() + pl.caret


def _controller(app):
    from hea_calc.ui.widgets.tooltip import controller, install_tooltips
    return controller() or install_tooltips(app)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_table_columns_pointer_targets_the_hovered_check_box(win, app, theme):
    from hea_calc.ui.theme import THEME
    from hea_calc.ui.widgets.dialogs import ColumnsDialog
    from hea_calc.ui.widgets.tooltip import anchor_rect
    THEME.set_theme(theme)
    calc(win, app)
    d = ColumnsDialog(list(win.table.view.m.keys), win)
    d.show()
    pump(app, 10)
    ctl = _controller(app)
    try:
        for key in ("M1", "dchi", "omega", "density", "mean_mass"):        # left and right grid columns
            cb = d.checks[key]
            cb.ensurePolished()
            visible = anchor_rect(cb)
            assert visible.width() < cb.width(), (key, "the cell is wider than the box and its label")
            assert visible.left() == 0 and visible.height() == cb.height()
            ctl.show_tip(cb, cb.toolTip())
            pump(app, 3)
            tip = ctl.tip
            g = cb.mapToGlobal(visible.topLeft())
            x = _caret_global(tip)
            assert tip.placement.side == "top" and tip.placement.caret is not None, key
            assert abs(x - (g.x() + visible.width() / 2)) <= 1, (key, x, g.x(), visible.width())
            # the pointer touches the check box's own row: above its top edge, not over the row above it
            assert tip.pos().y() + tip.height() + ctl.tip.GAP == cb.mapToGlobal(QPoint(0, 0)).y(), key
            ctl.hide()
    finally:
        ctl.hide()
        d.close()


def test_pointer_follows_the_check_box_after_scrolling(win, app):
    from hea_calc.ui.widgets.dialogs import ColumnsDialog
    from hea_calc.ui.widgets.tooltip import anchor_rect
    from PySide6.QtWidgets import QScrollArea
    calc(win, app)
    d = ColumnsDialog(list(win.table.view.m.keys), win)
    d.resize(560, 360)
    d.show()
    pump(app, 10)
    ctl = _controller(app)
    try:
        sa = d.findChildren(QScrollArea)[0]
        bar = sa.verticalScrollBar()
        assert bar.maximum() > 0, "the list scrolls at this height"
        bar.setValue(bar.maximum())
        pump(app, 5)
        cb = d.checks["M8"]
        ctl.show_tip(cb, cb.toolTip())
        pump(app, 3)
        g = cb.mapToGlobal(anchor_rect(cb).center())
        assert abs(_caret_global(ctl.tip) - g.x()) <= 1
    finally:
        ctl.hide()
        d.close()


def test_filter_rule_label_pointer_targets_its_text(win, app):
    from hea_calc.ui.widgets.dialogs import FilterRule
    from hea_calc.ui.widgets.tooltip import anchor_rect
    rule = FilterRule("dhmix")
    rule.resize(640, 40)
    rule.show()
    pump(app, 5)
    ctl = _controller(app)
    try:
        name = rule.layout().itemAt(0).widget()
        r = anchor_rect(name)
        assert r.width() == name.fontMetrics().horizontalAdvance(name.text()) and r.width() < name.width()
        ctl.show_tip(name, name.toolTip())
        pump(app, 3)
        assert abs(_caret_global(ctl.tip) - name.mapToGlobal(r.center()).x()) <= 1
    finally:
        ctl.hide()
        rule.close()


def test_pointer_stays_on_the_anchor_when_the_bubble_is_pushed_on_screen():
    from hea_calc.ui.widgets.tooltip import CARET_W, TOOLTIP_RADIUS, place_popover
    screen = QRect(0, 0, 1920, 1080)
    body = QSize(288, 64)
    margin = TOOLTIP_RADIUS + CARET_W / 2
    for ax in (4, 40, 960, 1880, 1912):                             # near both edges and in the middle
        anchor = QRect(ax, 500, 8, 20)
        pl = place_popover(body, anchor, screen, "top")
        assert screen.left() <= pl.pos.x() and pl.pos.x() + body.width() - 1 <= screen.right()
        want = anchor.left() + anchor.width() / 2
        if margin <= want - pl.pos.x() <= body.width() - margin:
            assert abs(pl.pos.x() + pl.caret - want) <= 1, ax
        else:
            assert pl.caret in (round(margin), round(body.width() - margin)), "clamped to the straight edge"
    # no room above: the bubble goes below and still points at the anchor
    pl = place_popover(body, QRect(900, 4, 40, 20), screen, "top")
    assert pl.side == "bottom" and abs(pl.pos.x() + pl.caret - 920) <= 1


def test_moving_the_window_hides_the_tip(win, app):
    from hea_calc.ui.widgets.dialogs import ColumnsDialog
    calc(win, app)
    d = ColumnsDialog(list(win.table.view.m.keys), win)
    d.show()
    pump(app, 5)
    ctl = _controller(app)
    try:
        cb = d.checks["M1"]
        ctl.show_tip(cb, cb.toolTip())
        pump(app, 3)
        assert ctl.visible()
        d.move(d.pos() + QPoint(40, 30))
        pump(app, 5)
        assert not ctl.visible(), "a tip never points away from its moved trigger"
    finally:
        ctl.hide()
        d.close()
