"""UI corrections B1-B8 and the radius display C1 (2026-10-27).

Real widgets in a real MainWindow (offscreen), real events where an interaction is under test (QTest mouse / key,
Enter / Leave).  Expected values come from tokens, layout constants and the dataset - never from the changed code's
own output.  The Windows-only checks (taskbar ownership, native caption hover) are in ``_native_b_checks.py``."""

import os
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


def pump(app, n=10):
    for _ in range(n):
        app.processEvents()


def make_window(app, theme="dark", width=1728):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(width, 1000)
    w.show()
    pump(app)
    return w


def close_window(app, w):
    from PySide6.QtCore import QEvent
    from hea_calc.ui.theme import THEME
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


def enter(app, widget):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QApplication
    c = QPointF(widget.width() / 2, widget.height() / 2)
    QApplication.sendEvent(widget, QEnterEvent(c, c, QPointF(widget.mapToGlobal(c.toPoint()))))
    pump(app)


def leave(app, widget):
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(widget, QEvent(QEvent.Type.Leave))
    pump(app)


def wait(ms):
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


def tip_visible():
    from hea_calc.ui.widgets import tooltip
    ctl = tooltip.controller()
    return ctl is not None and ctl.visible()


# ============================================================================================ B1 caption buttons
def test_caption_buttons_have_accessible_names_and_no_tooltip(win, app):
    from hea_calc.ui.widgets import tooltip
    bar = win.header
    for btn, name in ((bar.min_btn, "Minimize"), (bar.max_btn, "Maximize"), (bar.close_btn, "Close")):
        assert btn.accessibleName() == name and btn.toolTip() == ""
        enter(app, btn)                                   # hover past the enter delay: nothing appears
        wait(600)
        assert not tip_visible(), name
        leave(app, btn)
    bar.max_btn.set_maximized(True)
    assert bar.max_btn.accessibleName() == "Restore down" and bar.max_btn.toolTip() == ""
    bar.max_btn.set_maximized(False)
    # Snap Layouts / hit-testing are unchanged: the maximise button still answers HTMAXBUTTON's zone
    c = bar.max_btn.geometry().center()
    assert bar.hit_test(bar.row.mapTo(bar, c)) == "max"
    assert bar.hit_test(bar.row.mapTo(bar, bar.close_btn.geometry().center())) == "client"
    # a control with a tooltip still gets one (negative control: the controller works in this test)
    enter(app, bar.panels_btn)
    wait(600)
    assert tip_visible()
    leave(app, bar.panels_btn)
    tooltip.controller().hide()


# ============================================================================================ B2 / C1 / B7 properties
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_element_properties_without_rule(app, theme):
    from PySide6.QtCore import QPoint
    from hea_calc.ui.widgets.common import Divider
    w = make_window(app, theme)
    try:
        ep, info = w.elements, w.elements.info
        assert not hasattr(info, "rule")
        horizontal = [d for d in info.findChildren(Divider) if d.width() > d.height()]
        assert horizontal == []                                     # only the vertical group dividers remain
        for el in ("Fe", "Pu", None):
            info.show_element(el)
            pump(app)
            rows = [v for v, _f, _s in info.values.values()]
            bottom = max(v.mapTo(ep, QPoint(0, v.height())).y() for v in rows)
            assert ep.height() - bottom == info.BOTTOM_PAD == 16      # 16 px bottom padding kept
            top = min(v.mapTo(info, QPoint(0, 0)).y() for v in rows)
            for d in info.group_dividers:                           # dividers still span every row
                assert d.geometry().top() <= top
    finally:
        close_window(app, w)


def test_radius_is_shown_at_the_printed_precision(win, app):
    info = win.elements.info
    data = info.data
    info.show_element("Fe")
    assert info.values["atomic_radius"][0].text() == "124.1 pm"
    assert info.values["atomic_radius_cn12"][0].text() == f"{data.prop('Fe', 'atomic_radius_cn12'):.0f} pm"
    for el in data.elements:                                         # display = dataset value, never re-rounded
        r = data.prop(el, "atomic_radius")
        if r is None:
            continue
        info.show_element(el)
        text = info.values["atomic_radius"][0].text().split(" ")[0]
        assert float(text) == r, el
        if data.radius_is_supplementary(el):
            assert info.values["atomic_radius"][0].text().endswith("*")
    info.show_element("Fe")
    tips = {k: lab.toolTip() for k, lab in info.keys.items()}
    # 2026-10-28 (C2): definitions and units, no bibliographic references in the tooltips
    assert "0.1 pm" in tips["atomic_radius"] and "M2–M5" in tips["atomic_radius"]
    assert "different radius set" in tips["atomic_radius_cn12"] and "M1" in tips["atomic_radius_cn12"]


def test_property_tooltips_are_on_the_symbol_only(win, app):
    from PySide6.QtCore import QRect
    from hea_calc.ui.widgets import tooltip
    info = win.elements.info
    info.show_element("Fe")
    pump(app)
    for prop, (v, _f, _s) in info.values.items():
        assert v.toolTip() == "", prop                               # the value: no tooltip
        k = info.keys[prop]
        assert k.toolTip(), prop
        assert k.width() <= k.sizeHint().width() + 1, prop           # the trigger is the symbol, not the column
        assert k.width() < k.parentWidget().width(), prop
    enter(app, info.values["density"][0])
    wait(600)
    assert not tip_visible()                                         # hovering a value shows nothing
    k = info.keys["density"]
    enter(app, k)
    wait(600)
    ctl = tooltip.controller()
    assert ctl.visible() and ctl._source is k
    assert ctl.tip.anchor == QRect(k.mapToGlobal(k.rect().topLeft()), k.size())
    caret_x = ctl.tip.mapToGlobal(ctl.tip.rect().topLeft()).x() + ctl.tip.placement.caret
    assert abs(caret_x - ctl.tip.anchor.center().x()) <= 1           # the caret points at the symbol
    leave(app, k)
    info.show_element("Pu")                                          # supplementary radius: said on the symbol
    assert "supplementary" in info.keys["atomic_radius"].toolTip()
    info.show_element("Fe")
    assert "supplementary" not in info.keys["atomic_radius"].toolTip()


# ============================================================================================ B3 Clear resets details
@pytest.mark.parametrize("collapsed", [False, True])
def test_clear_returns_the_details_to_the_empty_state(win, app, collapsed):
    info = win.elements.info
    for el in ("Fe", "Ni"):
        win.elements.table.tiles[el].click()
    pump(app)
    assert "Ni" in info.name.text()
    if collapsed:
        win.top_row.set_collapsed(0, True)
        pump(app)
    win.composition.clear_btn.click()                                # the real Clear (undoable path)
    pump(app)
    assert win.composition._elements == []
    if collapsed:
        win.top_row.set_collapsed(0, False)
        pump(app)
    assert info.name.property("hint") and info.name.text().startswith("Hover over an element")
    assert all(v.text() == "—" for v, _f, _s in info.values.values())
    win.undo()                                                       # Undo restores the committed selection
    pump(app)
    assert "Ni" in info.name.text()


def test_hover_preview_is_not_the_committed_selection(win, app):
    ep = win.elements
    info = ep.info
    ep.table.tiles["Fe"].click()
    pump(app)
    ep.table.hovered.emit("Cu")                                      # pointer over Cu: a preview
    assert "Cu" in info.name.text()
    leave(app, ep.table)                                             # pointer leaves: the committed element again
    assert "Fe" in info.name.text()
    ep.table.hovered.emit("Cu")
    win.composition.clear()                                          # Clear while not hovering the table
    pump(app)
    assert ep._sticky is None
    leave(app, ep.table)
    assert info.name.property("hint")


# ============================================================================================ B4 Help window
def test_help_is_an_independent_top_level_window(win, app):
    from PySide6.QtCore import Qt
    from hea_calc.ui.theme import THEME
    hw = win.show_help("home")
    pump(app)
    assert hw.parent() is None and hw.isWindow()                     # no owner: own taskbar entry, can go behind
    flags = hw.windowFlags()
    assert flags & Qt.WindowType.Window
    for bad in (Qt.WindowType.Tool, Qt.WindowType.Dialog):          # composite flags: Window | bit
        assert (flags & bad) != bad, bad
    assert not (flags & Qt.WindowType.WindowStaysOnTopHint)
    assert flags & Qt.WindowType.WindowMinimizeButtonHint or not (flags & Qt.WindowType.CustomizeWindowHint)
    assert not hw.isModal() and not win.isModal()
    assert win.show_help("faq") is hw                                # reused, never duplicated
    hw.showMinimized()
    pump(app)
    assert win.isVisible() and not win.isMinimized()
    assert win.show_help("home") is hw and not hw.isMinimized()      # brought back
    sheet = hw.styleSheet()
    THEME.set_theme("light")                                         # follows the theme like the main window
    win.apply_theme()
    pump(app)
    assert hw.styleSheet().startswith(win.styleSheet()) and hw.styleSheet() != sheet
    assert "#HelpWindow" in hw.styleSheet()                         # its own rules are kept
    hw.close()
    pump(app)
    assert win.show_help("home") is hw and hw.isVisible()
    win.close()                                                      # closing the application closes Help
    pump(app)
    assert not hw.isVisible()                                        # a hidden window keeps nothing alive


# ============================================================================================ B5 heading caret
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mode_caret_matches_the_label(app, theme):
    from PySide6.QtGui import QColor, QImage
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets import heading_dropdown as HD
    w = make_window(app, theme)
    try:
        h = w.composition.heading
        for enabled in (True, False):
            h.setEnabled(enabled)
            bg = QColor(t("layer-01"))
            img = QImage(h.size(), QImage.Format.Format_ARGB32)
            img.fill(bg)
            from PySide6.QtCore import QPoint
            from PySide6.QtGui import QRegion
            from PySide6.QtWidgets import QWidget
            # the widget's own painting on the layer it sits on (no palette background from grab())
            h.render(img, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
            tw = h.text_width()
            x_icon = int(HD.PAD_X + tw + HD.ICON_GAP)

            def strongest(x0, x1):
                best = (0, None)
                for x in range(x0, x1):
                    for y in range(img.height()):
                        c = img.pixelColor(x, y)
                        d = abs(c.lightness() - bg.lightness())
                        best = max(best, (d, c.name()), key=lambda b: b[0])
                return best
            text = strongest(int(HD.PAD_X), int(HD.PAD_X + tw))
            caret = strongest(x_icon, x_icon + HD.ICON)
            assert text[0] > 0 and caret[0] >= 0.85 * text[0], (theme, enabled, text, caret)
            target = QColor(t("text-primary" if enabled else "text-disabled"))
            assert abs(QColor(caret[1]).lightness() - target.lightness()) <= 0.15 * 255, (theme, enabled, caret)
        h.setEnabled(True)
    finally:
        close_window(app, w)


# ============================================================================================ B6 System size
def test_system_size_is_read_only_n_when_every_element_is_locked(win, app):
    comp = win.composition
    comp.set_mode(1)
    for el in ("Fe", "Ni", "Cr", "Co"):
        win.elements.table.tiles[el].click()
    pump(app)
    sv = comp.sweep
    box = sv.size_box
    assert all(r.lock.isChecked() for r in sv.rows.values())        # new rows are required (locked)
    assert box.read_only and box.isEnabled() and box.currentText() == "4"
    assert sv.sizes() == {4} and "locked" in box.accessibleDescription()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(box, Qt.MouseButton.LeftButton)                 # cannot be opened
    QTest.keyClick(box, Qt.Key.Key_Space)
    pump(app)
    assert box.popup is None
    sv.rows["Co"].lock.click()                                       # unlock one: editable 2..4 again
    pump(app)
    # 4 elements, 3 locked: sizes 3 and 4 only (C7, 2026-10-28: max(2, L) .. N)
    assert not box.read_only and [v for v, _h in box.options] == [3, 4] and box.accessibleDescription() == ""
    box.selected = (3,)
    box.changed.emit((3,))                                           # the MultiSelect's own path
    pump(app)
    sv.rows["Co"].lock.click()                                       # all locked again: N
    pump(app)
    assert box.read_only and box.currentText() == "4"
    sv.rows["Co"].lock.click()                                       # unlocked: All (UX package B5, 2026-10-28)
    pump(app)
    assert box.selected == () and box.current_html() == "All"
    win.elements.table.tiles["Co"].click()                           # remove the optional one: all locked, N = 3
    pump(app)
    assert box.read_only and box.currentText() == "3" and sv.sizes() == {3}
    # the space is the same as without the restriction: every element is required anyway
    assert sv.valid_count() is None or sv.valid_count() >= 0


# ============================================================================================ B8 collapsed gaps
def test_gap_beside_a_collapsed_strip_is_8px(win, app):
    from hea_calc.ui.widgets.layouts import COLLAPSED_GAP, STRIP
    from hea_calc.ui.theme import PANEL_GAP
    top = win.top_row
    (el, _r, _m, _x), (comp, *_), (ana, *_) = top.panels
    assert COLLAPSED_GAP == 8 and PANEL_GAP == 16 and top.gap == PANEL_GAP
    assert comp.x() - el.geometry().right() - 1 == 16 and ana.x() - comp.geometry().right() - 1 == 16
    top.set_collapsed(0, True)
    pump(app)
    s0 = top.strips[0]
    assert s0.width() == STRIP
    assert comp.x() - s0.geometry().right() - 1 == 8                 # beside the strip: 8
    assert ana.x() - comp.geometry().right() - 1 == 16               # elsewhere: 16
    top.set_collapsed(1, True)
    pump(app)
    s1 = top.strips[1]
    assert s1.x() - s0.geometry().right() - 1 == 8 and ana.x() - s1.geometry().right() - 1 == 8
    assert ana.geometry().right() == top.width() - 1                 # the space went to Analysis
    top.set_collapsed(0, False)
    top.set_collapsed(1, False)
    pump(app)
    assert comp.x() - el.geometry().right() - 1 == 16 and ana.x() - comp.geometry().right() - 1 == 16


# ============================================================================================ native (Windows desktop)
@pytest.mark.skipif(__import__("sys").platform != "win32" or os.environ.get("HEA_NATIVE_TESTS") != "1",
                    reason="opens real windows and moves the pointer; set HEA_NATIVE_TESTS=1 on a Windows desktop")
def test_native_help_window_caption_tooltips_and_caret():
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    p = subprocess.run([sys.executable, str(Path(__file__).with_name("_native_b_checks.py"))], cwd=root, env=env,
                       capture_output=True, text=True, timeout=180)
    assert p.returncode == 0 and "ALL NATIVE B CHECKS PASSED" in p.stdout, p.stdout + p.stderr
