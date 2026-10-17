"""Render the main window at the Figma client size (1920 × 1000 below the native title bar) to a PNG.

Usage:
    .venv/Scripts/python.exe tools/screenshot.py [out.png] [--theme light] [--mode single|sweep|expression]
           [--tab 0-3] [--size 1920x1000] [--empty] [--platform windows]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(ROOT / "design" / "screens" / "app_dark.png"))
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--mode", default="single")
    ap.add_argument("--tab", type=int, default=2)
    ap.add_argument("--size", default="1920x1000")
    ap.add_argument("--empty", action="store_true")
    ap.add_argument("--platform", default="offscreen")
    args = ap.parse_args()
    if args.platform != "windows":
        os.environ["QT_QPA_PLATFORM"] = args.platform
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    import tempfile
    settings = QSettings(str(Path(tempfile.gettempdir()) / "hea_screenshot_settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    from hea_calc.ui.theme import THEME, load_fonts
    load_fonts()
    THEME.set_theme(args.theme)
    from hea_calc.ui.main_window import MainWindow

    w, h = (int(x) for x in args.size.split("x"))
    win = MainWindow(settings=settings)
    win.resize(w, h)
    win.show()
    app.processEvents()
    if not args.empty:
        demo(win, args.mode)
    from hea_calc.core.analysis import state as AS
    win.analysis_ctl.apply(AS.set_tab, AS.COMP_TABS[min(args.tab, len(AS.COMP_TABS) - 1)])
    for _ in range(5):
        app.processEvents()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pm = win.grab()
    pm.save(str(out))
    print(out, pm.width(), pm.height())
    win.close()


def demo(win, mode: str):
    from PySide6.QtWidgets import QApplication

    comp = win.composition
    for el in ("Cr", "Mn", "Fe", "Co", "Ni", "Mo", "Ti"):
        win.elements.table.tiles[el].click()
    QApplication.processEvents()
    comp.calculate()
    rows = [
        ("(Fe1.6CoCr0.4Mn)0.9Al0.1", {"Fe": 1.6 * 0.9 / 4, "Co": 0.9 / 4, "Cr": 0.4 * 0.9 / 4, "Mn": 0.9 / 4, "Al": 0.1}),
        ("FeCoNi(AlCu)0.2", {"Fe": 1, "Co": 1, "Ni": 1, "Al": 0.1, "Cu": 0.1}),
        ("AlCoCuFeNiSi", {"Al": 1, "Co": 1, "Cu": 1, "Fe": 1, "Ni": 1, "Si": 1}),
    ]
    for name, c in rows:
        win.calculate("single", [name], [c], [{}])
    win._jump_to(win.table.model.view.lo)          # the first result of the table
    if mode == "sweep":
        comp.set_mode(1)
    elif mode == "expression":
        comp.set_mode(2)
        comp.expr.edit.setPlainText("(FeCoNi)1-xAlx\n0 <= x <= 1, step=0.25")
        comp.expr.parse()
    QApplication.processEvents()


def demo_rows(win, n: int):
    """Append ``n`` calculated rows (an Al_x CoCrFeNi series) so the table overflows the viewport."""
    from PySide6.QtWidgets import QApplication

    names, comps = [], []
    for i in range(n):
        x = round(0.05 * (i + 1), 2)
        names.append(f"Al{x:g}CoCrFeNi")
        comps.append({"Al": x, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1})
    rows = []
    from hea_calc.core.results import ResultRow
    for name, c in zip(names, comps):
        rows.append(ResultRow(name, c, win.engine.calculate(c, **win.options()), "single", {}))
    win._add_rows(rows, select_first=False)
    QApplication.processEvents()


if __name__ == "__main__":
    main()
