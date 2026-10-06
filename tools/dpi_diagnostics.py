"""Development-only DPI diagnostics for the HEA Calculator main window.

Launches the real main window (native Windows platform unless ``--platform`` says otherwise),
waits for it to be shown maximised and prints - or writes as JSON - everything that decides how
the UI is scaled:

* Qt scale environment variables and the application's high-DPI policy
* every QScreen: geometry, availableGeometry, logical/physical DPI, devicePixelRatio
* the main window: logical frame and client size, devicePixelRatio, native ``GetDpiForWindow``
* layout ownership: main scroll bar visible?  table vertical scroll bar visible?  sticky header?
  horizontal overflow of the three upper panels?

Usage:
    .venv/Scripts/python.exe tools/dpi_diagnostics.py [--json out.json] [--rows 30] [--scroll-to-table]
                                                      [--screenshot out.png] [--size 1440x900]

To exercise a different Windows scale without changing the system setting, the scale can be
emulated for this process only with ``--emulate 1.25`` (sets QT_SCALE_FACTOR relative to the
current system scale).  The authoritative check is a native run at each Windows scale (Settings >
System > Display > Scale); see ``design/implementation/dpi_validation.json``.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCALE_VARS = ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_FONT_DPI", "QT_ENABLE_HIGHDPI_SCALING",
              "QT_AUTO_SCREEN_SCALE_FACTOR", "QT_SCALE_FACTOR_ROUNDING_POLICY", "QT_USE_PHYSICAL_DPI",
              "QT_QPA_PLATFORM")


def system_dpi() -> int | None:
    """System DPI as Windows reports it to a per-monitor-aware process (None off Windows)."""
    if sys.platform != "win32":
        return None
    try:
        return int(ctypes.windll.user32.GetDpiForSystem())
    except (AttributeError, OSError):
        return None


def window_dpi(hwnd: int) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        return int(ctypes.windll.user32.GetDpiForWindow(ctypes.c_void_p(hwnd)))
    except (AttributeError, OSError):
        return None


def dpi_awareness() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        ctx = user32.GetThreadDpiAwarenessContext()
        aw = user32.GetAwarenessFromDpiAwarenessContext(ctypes.c_void_p(ctx))
        return {0: "unaware", 1: "system-aware", 2: "per-monitor-aware"}.get(aw, str(aw))
    except (AttributeError, OSError):
        return None


def collect(win, app) -> dict:
    from PySide6.QtGui import QGuiApplication

    screens = []
    for s in app.screens():
        g, a = s.geometry(), s.availableGeometry()
        screens.append({
            "name": s.name(), "primary": s is app.primaryScreen(),
            "geometry": [g.x(), g.y(), g.width(), g.height()],
            "availableGeometry": [a.x(), a.y(), a.width(), a.height()],
            "logicalDpi": round(s.logicalDotsPerInch(), 2), "physicalDpi": round(s.physicalDotsPerInch(), 2),
            "devicePixelRatio": s.devicePixelRatio(),
            "physicalPixels": [round(g.width() * s.devicePixelRatio()), round(g.height() * s.devicePixelRatio())],
        })
    cw = win.centralWidget()
    info = {
        "env": {k: os.environ.get(k) for k in SCALE_VARS},
        "platform": QGuiApplication.platformName(),
        "roundingPolicy": QGuiApplication.highDpiScaleFactorRoundingPolicy().name,
        "processDpiAwareness": dpi_awareness(),
        "GetDpiForSystem": system_dpi(),
        "primaryScreenDpr": app.primaryScreen().devicePixelRatio(),
        "screens": screens,
        "window": {
            "frameLogical": [win.frameGeometry().width(), win.frameGeometry().height()],
            "clientLogical": [win.width(), win.height()],
            "centralLogical": [cw.width(), cw.height()],
            "devicePixelRatio": win.devicePixelRatioF(),
            "GetDpiForWindow": window_dpi(int(win.winId())),
            "maximized": win.isMaximized(),
        },
    }
    if hasattr(win, "layout_report"):
        info["layout"] = win.layout_report()
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--rows", type=int, default=0, help="add N demo rows to the results table")
    ap.add_argument("--scroll-to-table", action="store_true", help="scroll the main area to the bottom")
    ap.add_argument("--screenshot")
    ap.add_argument("--size", help="WxH logical; default: maximised")
    ap.add_argument("--emulate", type=float, help="extra QT_SCALE_FACTOR for this process only")
    ap.add_argument("--platform", default="windows")
    ap.add_argument("--theme", default="dark")
    args = ap.parse_args()
    if args.platform != "windows":
        os.environ["QT_QPA_PLATFORM"] = args.platform
    if args.emulate:
        os.environ["QT_SCALE_FACTOR"] = f"{args.emulate:g}"

    import tempfile

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from hea_calc.ui.theme import THEME, load_fonts
    from hea_calc.ui.widgets.common import install_tooltips

    load_fonts()
    THEME.set_theme(args.theme)
    install_tooltips(app)
    from hea_calc.ui.main_window import MainWindow

    settings = QSettings(str(Path(tempfile.gettempdir()) / "hea_dpi_diag.ini"), QSettings.Format.IniFormat)
    settings.clear()
    win = MainWindow(settings=settings)
    if args.size:
        w, h = (int(x) for x in args.size.split("x"))
        win.resize(w, h)
        win.show()
    else:
        win.showMaximized()
    for _ in range(10):
        app.processEvents()
    if args.rows:
        sys.path.insert(0, str(ROOT / "tools"))
        from screenshot import demo, demo_rows
        demo(win, "single")
        demo_rows(win, args.rows)
        for _ in range(10):
            app.processEvents()
    if args.scroll_to_table and hasattr(win, "scroll"):
        sb = win.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        for _ in range(10):
            app.processEvents()
    info = collect(win, app)
    if args.screenshot:
        out = Path(args.screenshot)
        out.parent.mkdir(parents=True, exist_ok=True)
        # native capture of the window's client area (physical pixels, includes popups' absence)
        scr = win.screen()
        pm = scr.grabWindow(int(win.winId())) if args.platform == "windows" else win.grab()
        pm.save(str(out))
        info["screenshot"] = {"path": str(out), "physical": [pm.width(), pm.height()],
                              "dpr": pm.devicePixelRatio()}
    text = json.dumps(info, indent=2)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)
    win.close()


if __name__ == "__main__":
    main()
