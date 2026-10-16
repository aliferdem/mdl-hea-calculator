"""Continuous main-window resize probe: records every top-level widget that is shown while the window is
resized wide -> breakpoint -> narrow -> breakpoint -> wide (regression for transient Analysis windows).

Run:  .venv/Scripts/python.exe tools/resize_probe.py [--platform windows] [--expanded]
Prints one line per transient top-level show event and a JSON summary; exits non-zero when any appeared.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="offscreen")
    ap.add_argument("--tab", default="collection")
    args = ap.parse_args()
    if args.platform != "windows":
        os.environ["QT_QPA_PLATFORM"] = args.platform
    from PySide6.QtCore import QEvent, QObject, QSettings
    from PySide6.QtWidgets import QApplication, QWidget
    import tempfile

    app = QApplication(sys.argv)
    from hea_calc.ui.theme import THEME, load_fonts
    load_fonts()
    THEME.set_theme("dark")
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.core.analysis import state as AS

    settings = QSettings(str(Path(tempfile.gettempdir()) / "hea_resize_probe.ini"), QSettings.Format.IniFormat)
    settings.clear()
    win = MainWindow(settings=settings)
    win.resize(1920, 1000)
    win.show()
    app.processEvents()
    sys.path.insert(0, str(ROOT / "tools"))
    from screenshot import demo
    demo(win, "single")
    for _ in range(10):
        app.processEvents()

    shown: list[dict] = []

    orphaned: dict[int, str] = {}

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.ParentChange and isinstance(obj, QWidget) and obj.parentWidget() is None:
                orphaned[id(obj)] = "".join(__import__("traceback").format_stack(limit=6)[:-1])
            if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() and obj is not win \
                    and id(obj) in orphaned:
                shown.append({"class": type(obj).__name__ + " (orphaned)", "name": obj.objectName(), "flags": 0,
                              "size": [obj.width(), obj.height()], "stack": orphaned[id(obj)]})
                return False
            if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() and obj is not win:
                shown.append({"class": type(obj).__name__, "name": obj.objectName(),
                              "flags": int(obj.windowFlags().value) if hasattr(obj.windowFlags(), "value")
                              else int(obj.windowFlags()),
                              "size": [obj.width(), obj.height()], "stack": "".join(__import__("traceback").format_stack(limit=8)[:-1])})
            return False

    spy = Spy()
    app.installEventFilter(spy)

    def top_count():
        return len([w for w in app.topLevelWidgets() if w.isVisible()])

    results = {}
    for ctx in ("composition", "collection"):
        win.analysis_ctl.apply(AS.switch_context, AS.COMPOSITION if ctx == "composition" else AS.COLLECTION)
        for _ in range(10):
            app.processEvents()
        before = top_count()
        counts = []
        widths = list(range(1920, 1100, -12)) + list(range(1100, 1921, 12))
        for wd in widths:
            win.resize(wd, 1000)
            app.processEvents()
            counts.append(top_count())
        results[ctx] = {"visibleTopLevelsBefore": before, "maxDuring": max(counts), "after": top_count()}
    app.removeEventFilter(spy)
    summary = {"transientShows": len(shown), "examples": shown[:10], "contexts": results,
               "compositionWidthStable": None}
    print(json.dumps(summary, indent=1))
    win.close()
    return 1 if shown else 0


if __name__ == "__main__":
    sys.exit(main())

