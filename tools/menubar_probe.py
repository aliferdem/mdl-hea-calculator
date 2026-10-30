"""Native title-bar menu-bar probe (real mouse and keyboard input, sent from a worker thread).

    .venv/Scripts/python.exe tools/menubar_probe.py [scale multiplier, 1 = native]

Click File; move the pointer over Edit, View, Help (each opens, exactly one menu at a time); Right / Left arrows;
Esc; then plain hover over the menus (nothing may open).  Prints one JSON line.  A multiplier other than 1 sets
QT_SCALE_FACTOR for this diagnostic process only (100 / 150 % emulation on a 125 % display).
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x02, 0x04
VK = {"left": 0x25, "right": 0x27, "esc": 0x1B}


def main():
    mult = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    if mult != 1.0:
        os.environ["QT_SCALE_FACTOR"] = f"{mult:g}"
    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.widgets.menu import CarbonMenu
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1300, 800)
    w.move(80, 60)
    w.show()
    w.raise_()
    w.activateWindow()
    u = ctypes.windll.user32
    bar = w.header
    dpr = w.devicePixelRatioF()

    state = {"open": [], "popups": 0, "max_popups": 0}

    def sample():                                   # GUI thread, every 15 ms (also inside a menu's modal loop)
        state["open"] = [it.text() for it in bar.menu_items if it.menu_ is not None and it.menu_.isVisible()]
        state["popups"] = sum(1 for x in QApplication.topLevelWidgets() if isinstance(x, CarbonMenu) and x.isVisible())
        state["max_popups"] = max(state["max_popups"], state["popups"])
    from PySide6.QtCore import QTimer
    timer = QTimer()
    timer.setInterval(15)
    timer.timeout.connect(sample)
    timer.start()
    file_, edit, view, help_ = bar.menu_items
    centers = {it.text(): it.mapToGlobal(QPoint(it.width() // 2, it.height() // 2)) for it in bar.menu_items}
    mid = w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2))
    out = {"dpr": dpr, "steps": []}

    def drive():                                    # worker thread: real OS input
        def to(name):
            c = centers[name]
            u.SetCursorPos(int(c.x() * dpr), int(c.y() * dpr))

        def click():
            u.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            u.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

        def key(name):
            u.keybd_event(VK[name], 0, 0, 0)
            u.keybd_event(VK[name], 0, 2, 0)

        def step(label):
            time.sleep(0.4)
            out["steps"].append((label, list(state["open"]), state["popups"]))
        time.sleep(1.2)
        to("File"); time.sleep(0.1); click(); step("click File")
        for name in ("Edit", "View", "Help", "File"):
            to(name); step(f"hover {name}")
        key("right"); step("Right")
        key("left"); step("Left")
        key("esc"); step("Esc")
        if state["open"]:
            key("esc"); time.sleep(0.3)
        for name in ("Edit", "View"):
            to(name); step(f"plain hover {name}")
        to("File"); time.sleep(0.1); click(); time.sleep(0.3)
        u.SetCursorPos(int(mid.x() * dpr), int(mid.y() * dpr)); time.sleep(0.1); click(); step("click outside")
        u.SetCursorPos(5, 5)
        out["max_popups"] = state["max_popups"]
        QTimer.singleShot(0, app.quit)
    th = threading.Thread(target=drive, daemon=True)
    th.start()
    QTimer.singleShot(60000, app.quit)
    app.exec()
    print(json.dumps(out))
    w.close()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
