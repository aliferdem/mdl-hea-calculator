"""Native checks run by ``test_ui_corrections_b_c.py`` (HEA_NATIVE_TESTS=1, Windows platform, a real desktop).

B4 - the Help window is an independent top-level window:
  * no owner window (GetWindow GW_OWNER == 0), so it has its own taskbar button and Alt+Tab entry;
  * not a tool window (WS_EX_TOOLWINDOW) and not topmost (WS_EX_TOPMOST); it has a minimise box;
  * it minimises on its own (the main window stays restored);
  * it can go behind the main window (z-order after activating the main window).
B1 - the caption buttons show no tooltip under the real pointer (SetCursorPos from a worker thread while the GUI
  thread pumps events; the native maximise button is HTMAXBUTTON, so Windows owns that pointer).
B5 - the mode caret is as dark as its label at the native device pixel ratio.

Prints "ALL NATIVE B CHECKS PASSED"; exits 1 with the failing records otherwise.
"""
import ctypes
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

GW_OWNER, GW_HWNDNEXT = 4, 2
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_MINIMIZEBOX, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_APPWINDOW = 0x00020000, 0x80, 0x8, 0x40000


def hwnd(w) -> int:
    return int(w.winId())


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import THEME, load_fonts, t
    from hea_calc.ui.widgets.common import install_tooltips

    u = ctypes.windll.user32
    u.GetWindow.restype = wintypes.HWND
    u.GetWindowLongW.restype = ctypes.c_long
    app = QApplication([])
    load_fonts()
    install_tooltips(app)
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.widgets import tooltip
    THEME.set_theme("light")
    win = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    win.resize(1400, 900)
    win.move(60, 40)
    win.show()
    failures = []

    def pump(seconds=0.3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    pump(1.0)

    # ---------------------------------------------------------------- B4
    hw = win.show_help("home")
    pump(0.8)
    h = hwnd(hw)
    owner = u.GetWindow(wintypes.HWND(h), GW_OWNER)
    ex = u.GetWindowLongW(wintypes.HWND(h), GWL_EXSTYLE)
    st = u.GetWindowLongW(wintypes.HWND(h), GWL_STYLE)
    rec = {"owner": owner, "exstyle": hex(ex & 0xFFFFFFFF), "style": hex(st & 0xFFFFFFFF)}
    if owner or ex & WS_EX_TOOLWINDOW or ex & WS_EX_TOPMOST or not st & WS_MINIMIZEBOX:
        failures.append(("B4 window kind", rec))
    win.raise_()
    win.activateWindow()
    u.SetForegroundWindow(wintypes.HWND(hwnd(win)))
    pump(0.8)
    order, w = [], u.GetTopWindow(None)
    while w and len(order) < 2000:
        if w in (hwnd(win), h):
            order.append("main" if w == hwnd(win) else "help")
        w = u.GetWindow(wintypes.HWND(w), GW_HWNDNEXT)
    if order[:1] != ["main"]:
        failures.append(("B4 help can go behind the main window", order))
    hw.showMinimized()
    pump(0.8)
    if not u.IsIconic(wintypes.HWND(h)) or u.IsIconic(wintypes.HWND(hwnd(win))):
        failures.append(("B4 minimise independently", (u.IsIconic(wintypes.HWND(h)),
                                                       u.IsIconic(wintypes.HWND(hwnd(win))))))
    if win.show_help("faq") is not hw or hw.isMinimized():
        failures.append(("B4 reused and restored", None))
    hw.close()
    pump(0.3)

    # ---------------------------------------------------------------- B1
    win.raise_()
    win.activateWindow()
    u.SetForegroundWindow(wintypes.HWND(hwnd(win)))
    pump(0.5)
    bar = win.header
    dpr = win.devicePixelRatioF()
    seen = {}
    for name, btn in (("min", bar.min_btn), ("max", bar.max_btn), ("close", bar.close_btn)):
        g = btn.mapToGlobal(QPoint(btn.width() // 2, btn.height() // 2))
        x, y = round(g.x() * dpr), round(g.y() * dpr)
        threading.Thread(target=lambda: u.SetCursorPos(x, y), daemon=True).start()
        pump(1.0)                                                    # > the 400 ms enter delay
        ctl = tooltip.controller()
        seen[name] = bool(ctl and ctl.visible())
        threading.Thread(target=lambda: u.SetCursorPos(x, y + round(300 * dpr)), daemon=True).start()
        pump(0.3)
    if any(seen.values()):
        failures.append(("B1 caption tooltip shown", seen))
    # negative control: the controller does show a tooltip on the top-panels action
    g = bar.panels_btn.mapToGlobal(QPoint(bar.panels_btn.width() // 2, bar.panels_btn.height() // 2))
    threading.Thread(target=lambda: u.SetCursorPos(round(g.x() * dpr), round(g.y() * dpr)), daemon=True).start()
    pump(1.0)
    ctl = tooltip.controller()
    if not (ctl and ctl.visible()):
        failures.append(("B1 negative control: no tooltip on the top-panels action", None))
    threading.Thread(target=lambda: u.SetCursorPos(round(g.x() * dpr), round((g.y() + 400) * dpr)), daemon=True).start()
    pump(0.3)

    # ---------------------------------------------------------------- B5
    from hea_calc.ui.widgets import heading_dropdown as HD
    head = win.composition.heading
    img = head.grab().toImage()
    k = img.devicePixelRatio()
    bg = QColor(t("layer-01"))
    tw = head.text_width()

    def strongest(x0, x1):
        best = 0
        for x in range(int(x0 * k), int(x1 * k)):
            for yy in range(img.height()):
                best = max(best, abs(img.pixelColor(x, yy).lightness() - bg.lightness()))
        return best
    text_s = strongest(HD.PAD_X, HD.PAD_X + tw)
    caret_s = strongest(HD.PAD_X + tw + HD.ICON_GAP, HD.PAD_X + tw + HD.ICON_GAP + HD.ICON)
    if caret_s < 0.85 * text_s:
        failures.append(("B5 caret lighter than its label", {"dpr": k, "text": text_s, "caret": caret_s}))

    # ---------------------------------------------------------------- 2026-10-28 pass (native DPR)
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtTest import QTest
    comp = win.composition
    s = comp.single
    s.radios["at"].click()
    for el in ("Fe", "Ni", "Cr"):
        win.elements.table.tiles[el].click()
    pump(0.3)
    # B2 / B3: the bottom rule of a disabled and a read-only field, whole device pixels in the product colour
    for f in (s.rows["Fe"].fields["at"], s.rows["Fe"].fields["wt"]):
        img = f.grab().toImage()
        row = {img.pixelColor(x, img.height() - 1).name() for x in range(3, img.width() - 3)}
        if row != {t("field-border-quiet")}:
            failures.append(("B2/B3 bottom rule", {"field": f.accessibleName(), "dpr": img.devicePixelRatio(),
                                                   "row": sorted(row)}))
    # A2: Enter in a committed row (added by the periodic table) opens the draft under it, real key events
    s.radios["element"].click()
    pump(0.2)
    f = s.rows["Ni"].el
    f.setFocus()
    QTest.keyClick(f, _Qt.Key.Key_Return)
    pump(0.3)
    QTest.keyClicks(s.draft.el, "co") if s.draft else None
    QTest.keyClick(s.draft.el, _Qt.Key.Key_Return) if s.draft else None
    pump(0.3)
    if list(s.rows) != ["Fe", "Ni", "Co", "Cr"]:
        failures.append(("A2 Enter from a periodic-table row", list(s.rows)))
    if s.draft is not None:
        QTest.keyClick(s.draft.el, _Qt.Key.Key_Escape)
    # C1: the Composition space caret and its label at the native device pixel ratio (unselected)
    from hea_calc.ui.widgets.heading_dropdown import CascadePopup
    pop = CascadePopup(comp.heading, comp.heading.tree, comp.heading.path)
    pimg = pop.grab().toImage()
    kk = pimg.devicePixelRatio()
    r = pop.row_rect(0, 1)
    bgc = QColor(t("layer-02")).lightness()

    def extreme(x0, x1):
        best = (0, None)
        for x in range(int(x0 * kk), int(x1 * kk)):
            for yy in range(int((r.top() + 2) * kk), int((r.bottom() - 2) * kk)):
                c = pimg.pixelColor(x, yy)
                if abs(c.lightness() - bgc) > best[0]:
                    best = (abs(c.lightness() - bgc), c.name())
        return best
    txt = extreme(r.left() + HD.PAD_X, r.left() + HD.PAD_X + 60)
    car = extreme(r.right() + 1 - HD.PAD_X - HD.ICON, r.right() + 1 - HD.PAD_X)
    if car[0] < 0.85 * txt[0] or abs(QColor(car[1]).lightness() - QColor(t("text-secondary")).lightness()) > 30:
        failures.append(("C1 menu caret", {"dpr": kk, "text": txt, "caret": car}))
    pop.deleteLater()

    win.close()
    pump(0.3)
    if failures:
        for f in failures:
            print("FAIL", f)
        sys.exit(1)
    print("ALL NATIVE B CHECKS PASSED", {"dpr": dpr, "z-order": order, "caption_tooltips": seen})
