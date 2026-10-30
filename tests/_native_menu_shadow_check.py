"""Native check run by ``test_analysis_surfaces_routing_menus.py`` (HEA_NATIVE_TESTS=1, Windows platform).

Moves the main window, then opens every header menu through its real path (HeaderMenuItem._open -> exec) and, inside
the menu's modal loop, compares the trigger-shadow overlay with the trigger: Qt geometry, the native window rectangle
(GetWindowRect, device px), and the composed screen (shadow present on both sides of the trigger).
Prints "ALL ALIGNED" on success; exits 1 with the failing records otherwise.
"""
import ctypes
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def native(w):
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(wintypes.HWND(int(w.winId())), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    from PySide6.QtCore import QPoint, QRect, QSettings, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import THEME, load_fonts
    from hea_calc.ui.widgets.menu import SHADOW

    app = QApplication([])
    load_fonts()
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.widgets.header import HeaderMenuItem, TitleBar
    THEME.set_theme("light")
    win = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    win.resize(1300, 860)
    win.move(80, 60)
    win.show()
    for _ in range(30):
        app.processEvents()
    tb = win.findChild(TitleBar)
    items = [it for it in tb.menu_items if isinstance(it, HeaderMenuItem) and it.menu_ is not None]
    failures, checked = [], 0

    def check(item, label):
        global checked
        m = item.menu_
        ov = m._overlay
        trig = QRect(item.mapToGlobal(QPoint(0, 0)), item.size())
        want = QRect(trig.left() - SHADOW, trig.top() - SHADOW, trig.width() + 2 * SHADOW, 0)
        got = ov.geometry() if ov is not None else None
        rec = {"case": label, "menu": item.text(), "trigger": trig.getRect(), "overlay": got.getRect() if got else None}
        ok = got is not None and ov.isVisible() and (got.left(), got.top(), got.width()) == \
            (want.left(), want.top(), want.width())
        dpr = QGuiApplication.primaryScreen().devicePixelRatio()
        if ok:
            nl, nt, nr, nb = native(ov)
            ml, mt, _mr, _mb = native(m)
            # the native overlay starts at the native menu's left edge + the tab's offset (device px, +-1 rounding)
            exp_left = ml + round((m.tab.left() - SHADOW) * dpr)
            rec["native"] = (nl, nt, nr, nb)
            ok = abs(nl - exp_left) <= 1 and abs(nb - mt) <= 1
            scr = QGuiApplication.primaryScreen()
            box = QRect(trig.left() - 10, trig.top(), trig.width() + 20, max(1, m.geometry().top() - trig.top()))
            img = scr.grabWindow(0, box.x(), box.y(), box.width(), box.height()).toImage()
            k = img.width() / box.width()
            y = img.height() // 2
            dark = lambda a, b: min(img.pixelColor(x, y).lightness() for x in range(int(a * k), int(b * k)))
            left, right = dark(5, 9), dark(10 + trig.width() + 1, 10 + trig.width() + 5)
            rec["shadow_lightness"] = (left, right)
            # a shadow on both sides of the trigger (the light title bar is 255; the failure left one or both at 255).
            # Not equality: at 125 % the two sample bands fall on different device-pixel boundaries (10-20 apart).
            ok = ok and left < 245 and right < 245
        checked += 1
        if not ok:
            failures.append(rec)

    for label, pos in (("initial", None), ("moved right", (230, 60)), ("moved down", (230, 170)),
                       ("moved back", (80, 60))):
        if pos:
            win.move(*pos)
            for _ in range(30):
                app.processEvents()
        for it in items:                       # the first opening at the new position is the failing one
            QTimer.singleShot(150, lambda it=it, label=label: (check(it, label), it.menu_.close()))
            it._open()
            for _ in range(10):
                app.processEvents()
    win.close()
    if failures or not checked:
        print("FAILURES", failures, "checked", checked)
        sys.exit(1)
    print("ALL ALIGNED", checked)
