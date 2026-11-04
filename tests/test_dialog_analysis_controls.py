"""Window captions (titles shown, no icon on secondary windows), dialog content without repeated headings, the Add
filter icon, the Analysis content switcher and the Options trigger's open state (2026-11-04)."""

import os

import pytest

import _ui_support as U
from _ui_support import calc, close, pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


def test_analysis_switcher_is_4px_from_the_top_with_8px_below_docked_and_detached(win, app):
    """The switcher's outer frame is 4 px below the panel's top edge (y = 4 .. 36, centred on the 40 px header row with
    the title and the icon buttons) in both contexts and both hosts, and the Collection scope controls start
    SWITCHER_GAP_BELOW (8 px) under it - they no longer touch it."""
    from hea_calc.ui.analysis.widgets import ContentSwitcher
    from hea_calc.ui.widgets.dropdown import Dropdown
    calc(win, app)
    aw = win.open_analysis_window()
    try:
        aw.resize(564, 554)
        pump(app, 15)
        checked = []
        for host, panel in (("docked", win.analysis), ("detached", aw.panel)):
            assert panel.SWITCHER_TOP == 4 and panel.SWITCHER_GAP_BELOW == 8
            for ctx in (0, 1):                                         # Composition, Collection
                panel.switcher.set_index(ctx, emit=True)
                pump(app, 15)
                sw = panel.switcher
                assert isinstance(sw, ContentSwitcher) and sw.isVisible()
                top = sw.mapTo(panel, QPoint(0, 0)).y()
                assert top == 4, (host, ctx, top)
                assert top + sw.height() / 2 == 20, "centred on the 40 px header row"
                buttons = [b for b in (panel.overflow_btn, panel.expand_btn) if b.isVisible()]
                assert all(b.mapTo(panel, QPoint(0, 0)).y() + b.height() / 2 == 20 for b in buttons), host
                if ctx == 1:
                    drops = [d for d in panel.scope_bar.findChildren(Dropdown) if d.isVisible()]
                    checked.append((host, bool(drops)))
                    if drops:
                        gap = drops[0].mapTo(panel, QPoint(0, 0)).y() - (top + sw.height())
                        assert gap == panel.SWITCHER_GAP_BELOW, (host, gap)
        assert ("detached", True) in checked, "the scope controls were measured"
    finally:
        close(app, aw)


def _corner_geometry(img, y_top, xs):
    row = lambda y, x: img.pixelColor(x, y).lightness()                # noqa: E731
    x_edge = next(x for x in xs if all(row(y_top, x + i) > 200 for i in range(20)))
    x_col = next(x for x in range(x_edge - 12, x_edge + 2) if row(y_top + 16, x) > 200)
    depth = next(dy for dy in range(16) if all(row(y_top + dy + k, x_col) > 200 for k in range(3)))
    return x_edge - x_col, depth


def test_content_switcher_corner_radius_matches_the_reference(app):
    """The approved reference measures (2, 3): straight top edge 2 px right of the side, side straight from 3 px down,
    which is the 4 px corner (the panels' 7 px corner measures (5, 5))."""
    from hea_calc.ui.analysis.widgets import ContentSwitcher
    from hea_calc.ui.theme import SWITCHER_RADIUS, THEME
    THEME.set_theme("dark")
    assert SWITCHER_RADIUS == 4
    sw = ContentSwitcher(["Composition", "Collection"], segment=116)
    sw.set_index(1)
    assert _corner_geometry(sw.grab().toImage(), 0, range(110, 130)) == (2, 3)


def test_dialogs_show_their_title_in_the_caption_and_no_heading(win, app):
    """Table columns, Filter results and Calculation settings: the caption shows the title (no icon) and the content
    has no repeated heading block - the first control starts 16 px under the caption."""
    from PySide6.QtWidgets import QLabel
    from hea_calc.ui import win_titlebar as W
    from hea_calc.ui.widgets.dialogs import ColumnsDialog, FilterDialog, SettingsDialog
    calc(win, app)
    dialogs = {"Table columns": ColumnsDialog(list(win.table.view.m.keys), win),
               "Filter results": FilterDialog([], win),
               "Calculation settings": SettingsDialog(None, 0.55, win)}
    for title, d in dialogs.items():
        d.show()
        pump(app, 6)
        assert d.windowTitle() == title
        assert W.caption_content(d) == W.CAPTION_TITLE and W.caption_flags(W.caption_content(d)) == W.WTNCA_NODRAWICON
        texts = [lb.text() for lb in d.findChildren(QLabel)]
        assert not [lb for lb in d.findChildren(QLabel) if lb.objectName() in ("ModalTitle", "ModalLabel")], title
        assert title not in texts and "Results table" not in texts and "Models M6 and M7" not in texts, title
        first = d.layout().itemAt(0)
        assert first.layout() is d.body, "the body is the first item: no heading container"
        assert d.body.contentsMargins().top() == 16 and d.body.geometry().top() == 0, title
        content = [d.body.itemAt(i) for i in range(d.body.count())]
        top = min((it.geometry().top() for it in content if not it.isEmpty()), default=None)
        assert top == 16, (title, top)
        d.close()


def test_other_secondary_windows_hide_the_caption_icon_and_the_main_window_keeps_it(win, app):
    from hea_calc.ui import win_titlebar as W
    from hea_calc.ui.widgets.dialogs import ChoiceDialog, ImportReportDialog
    assert W.caption_content(win) == W.CAPTION_FULL and W.caption_flags(W.CAPTION_FULL) == 0
    assert not win.windowIcon().isNull(), "the main window keeps the application icon"
    hw = win.show_help("home")
    win.show_about()
    aw = win.open_analysis_window()
    pump(app)
    try:
        about = win._about
        assert hw.windowTitle() == "Documentation"
        assert about.windowTitle() == "About MDL HEA Calculator"
        assert aw.windowTitle().endswith("Analysis - MDL HEA Calculator"), "its meaningful title is kept"
        others = [hw, about, aw, ImportReportDialog("x.csv", "rows", 1, [], win),
                  ChoiceDialog("Choose", "", "Message", [("a", "A")], win)]
        for w in others:
            assert W.caption_content(w) == W.CAPTION_TITLE, w.windowTitle()
            assert W.caption_flags(W.caption_content(w)) == W.WTNCA_NODRAWICON, "title drawn, icon hidden"
    finally:
        close(app, hw, aw, win._about)


def test_add_filter_button_has_the_add_icon_after_its_label(win, app):
    from PySide6.QtCore import Qt
    from hea_calc.ui import icons
    from hea_calc.ui.widgets.dialogs import FilterDialog
    d = FilterDialog([], win)
    d.show()
    pump(app, 6)
    try:
        b = d.add_btn
        assert b.text() == "Add filter" and b.accessibleName() == "Add filter"
        assert not b.icon().isNull() and b.iconSize().width() == 16
        want = icons.icon("add", "link-primary").pixmap(16, 16).toImage()
        assert b.icon().pixmap(16, 16).toImage() == want, "the application's add icon in the link colour"
        assert b.icon().pixmap(16, 16).toImage() != icons.icon("close", "link-primary").pixmap(16, 16).toImage()
        assert b.layoutDirection() == Qt.LayoutDirection.RightToLeft, "icon after the label, like Restrict"
        assert b.property("kind") == "ghost" and b.height() == 32 and b.focusPolicy() == Qt.FocusPolicy.TabFocus
    finally:
        d.close()


def _open_and_inspect(app, trigger, opener, closer):
    """Open the trigger's menu (a blocking exec), inspect the trigger while it is open, then close it with
    ``closer(menu)``; returns (state while open, colour while open, state after)."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.widgets.menu import CarbonMenu, is_menu_open
    seen = {}

    def inspect():
        menu = QApplication.activePopupWidget()
        seen["open"] = is_menu_open(trigger)
        seen["menu"] = isinstance(menu, CarbonMenu) and menu.isVisible()
        img = trigger.grab().toImage()
        seen["fill"] = img.pixelColor(3, 3).name()
        closer(menu)
    QTimer.singleShot(150, inspect)
    opener()
    pump(app, 5)
    return seen, is_menu_open(trigger)


@pytest.mark.parametrize("how", ["escape", "select", "close"])
def test_options_trigger_shows_its_open_state_while_the_menu_is_open(win, app, how):
    from PySide6.QtCore import Qt as _Qt
    from hea_calc.ui.theme import t
    calc(win, app)
    panel = win.analysis
    btn = panel.overflow_btn
    assert not btn.property("menu_open")

    def closer(menu):
        if how == "escape":
            QTest.keyClick(menu, _Qt.Key.Key_Escape)
        elif how == "select":
            act = next(a for a in menu.actions() if a.text() == "Show full precision")
            act.trigger()
            menu.close()
        else:
            menu.close()                                             # programmatic dismissal
    seen, after = _open_and_inspect(app, btn, panel.open_overflow, closer)
    assert seen["menu"] and seen["open"], "the menu is open and the trigger knows it"
    assert seen["fill"] == t("layer-02"), "the trigger shows the menu surface while open (approved reference)"
    assert after is False, "back to its normal state once the menu has closed"
    assert btn.grab().toImage().pixelColor(3, 3).name() != t("layer-02")


def test_wide_workspace_options_trigger_shares_the_open_state(win, app):
    from hea_calc.ui.theme import t
    calc(win, app)
    win.set_expanded(True)
    pump(app, 20)
    ws = win.workspace
    seen, after = _open_and_inspect(app, ws.overflow_btn, ws.open_overflow, lambda m: m.close())
    assert seen["open"] and seen["fill"] == t("layer-02") and after is False
    win.set_expanded(False)
    pump(app)


def test_caption_content_flags():
    from PySide6.QtWidgets import QWidget
    from hea_calc.ui import win_titlebar as W
    assert W.caption_flags(W.CAPTION_TITLE) == W.WTNCA_NODRAWICON, "title kept, icon hidden"
    assert W.caption_flags(W.CAPTION_FULL) == 0
    assert not W.caption_flags(W.CAPTION_TITLE) & W.WTNCA_NODRAWCAPTION, "no window hides its title text"
    assert W.caption_content(QWidget()) == W.CAPTION_TITLE, "secondary windows default to no icon"
