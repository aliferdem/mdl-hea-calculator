"""Native Windows check of the main window frame in every state (2026-11-04): run by
``test_ui_layout_interaction_consistency.test_native_window_frame`` with ``HEA_NATIVE_TESTS=1`` on a Windows desktop.

Restored: rounded corners (DWM corner preference ROUND).  Maximised: the client area is the monitor's work area
(taskbar respected) with square corners.  Full screen: the window covers the monitor, square corners, no DWM border -
the screen's corner pixels are the window's own colours, not the desktop.  The native window is never recreated by
these transitions (one HWND).  Prints one line per check and exits non-zero on the first failure."""

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


def main(settings_path: str) -> int:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from hea_calc.ui.theme import THEME, load_fonts
    load_fonts()
    THEME.set_theme("dark")
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import t
    win = MainWindow(settings=QSettings(settings_path, QSettings.Format.IniFormat))
    win.resize(1100, 720)
    win.show()

    def pump(s):
        end = time.perf_counter() + s
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)

    pump(1.0)
    u, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    hwnd = int(win.winId())
    h = wintypes.HWND(hwnd)
    failures = []

    def check(name, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
        if not ok:
            failures.append(name)

    def corner_pref():
        c = ctypes.c_int(-1)
        dwm.DwmGetWindowAttribute(h, 33, ctypes.byref(c), 4)
        return c.value

    def monitor():
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        u.GetMonitorInfoW(u.MonitorFromWindow(h, 2), ctypes.byref(mi))
        return mi

    def client_screen_rect():
        cr = wintypes.RECT()
        u.GetClientRect(h, ctypes.byref(cr))
        pt = wintypes.POINT(0, 0)
        u.ClientToScreen(h, ctypes.byref(pt))
        return (pt.x, pt.y, pt.x + cr.right, pt.y + cr.bottom)

    def screen_corners():
        scr = win.screen()
        g = scr.geometry()
        out = []
        for x, y in ((0, 0), (g.width() - 1, 0), (0, g.height() - 1), (g.width() - 1, g.height() - 1)):
            out.append(scr.grabWindow(0, x, y, 1, 1).toImage().pixelColor(0, 0).name())
        return out

    check("restored: rounded corners", corner_pref() == 2, f"pref {corner_pref()}")
    win.showMaximized()
    pump(1.2)
    mi = monitor()
    work = (mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom)
    check("maximized: client area = work area", client_screen_rect() == work, f"{client_screen_rect()} vs {work}")
    check("maximized: square corners", corner_pref() == 1, f"pref {corner_pref()}")
    win.set_fullscreen(True)
    pump(1.2)
    mi = monitor()
    mon = (mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right, mi.rcMonitor.bottom)
    check("full screen: covers the monitor", client_screen_rect() == mon, f"{client_screen_rect()} vs {mon}")
    check("full screen: square corners", corner_pref() == 1, f"pref {corner_pref()}")
    own = {t("shell"), t("titlebar-inactive"), t("background")}
    # the maximised -> full-screen transition is animated by DWM; sample once it has settled (at most 4 s)
    end = time.perf_counter() + 4.0
    corners = screen_corners()
    while not all(c in own for c in corners) and time.perf_counter() < end:
        pump(0.2)
        corners = screen_corners()
    check("full screen: corner pixels are the window's colours", all(c in own for c in corners), str(corners))
    win.set_fullscreen(False)
    pump(1.2)
    check("after full screen: maximized again", win.isMaximized() and corner_pref() == 1, f"pref {corner_pref()}")
    win.showNormal()
    pump(1.2)
    check("restored again: rounded corners", corner_pref() == 2, f"pref {corner_pref()}")
    check("one native window throughout", int(win.winId()) == hwnd)
    win.close()
    pump(0.3)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
