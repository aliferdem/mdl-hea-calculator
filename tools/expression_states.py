"""Capture the Composition setup panel in the Figma "Expression bases" states (584:51933) for visual comparison.

Usage:
    .venv/Scripts/python.exe tools/expression_states.py [--theme light|dark|both] [--out design/screens/expression]

Writes one PNG per state (``<theme>_<state>.png``, the 457 × 490 panel at DPR 1) - Empty, Draft, Error, Stale, Fixed
parsed, Parametric parsed, Batch parsed - using the Figma documents of those variants.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DOCS = {
    "draft": "(Co30Fe45Ni25)1-x(Al40Si60)x\n  0 <= x <= 1, step=0.05",
    "error": "FeCoXxNi\n\n(FeCoNi\n\n(Co30Fe45Ni25)1-x(Al40Si60)x\n  0 <= x <= 1, step=0.05, points=21",
    "fixed": "(Fe1.6CoCr0.4Mn)0.9Al0.1",
    "parametric": ("(FeCoNi)1-x-y-z(AlTi)xCryCuz\n  0 <= x <= 0.2, step=0.1, p=0.10\n  0 <= y <= 0.2, step=0.1, p=0.10\n"
                   "  0 <= z <= 0.10, step=0.05, p=0.05"),
    "batch": ("FeCoNi(AlCu)0.2\n\n(Fe1.6CoCr0.4Mn)0.9Al0.1\n\n(Co30Fe45Ni25)1-x(Al40Si60)x\n  0 <= x <= 1, step=0.05\n\n"
              "(Co30Fe45Ni25)1-x(Al40Si60)x\n  0 <= x <= 1, points=101"),
}


def pump(app, seconds: float = 0.0):
    end = time.monotonic() + seconds
    while True:
        app.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.02)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="both")
    ap.add_argument("--out", default=str(ROOT / "design" / "screens" / "expression"))
    ap.add_argument("--platform", default="offscreen")
    args = ap.parse_args()
    if args.platform != "windows":
        os.environ["QT_QPA_PLATFORM"] = args.platform
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    import tempfile
    settings = QSettings(str(Path(tempfile.gettempdir()) / "hea_expr_states.ini"), QSettings.Format.IniFormat)
    settings.clear()
    from hea_calc.ui.theme import THEME, load_fonts
    load_fonts()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    themes = ("light", "dark") if args.theme == "both" else (args.theme,)
    from hea_calc.ui.main_window import MainWindow
    for theme in themes:
        THEME.set_theme(theme)
        win = MainWindow(settings=settings)
        win.resize(1920, 1000)
        win.show()
        pump(app, 0.2)
        comp = win.composition
        comp.set_mode(2)
        ex = comp.expr

        def shot(name):
            pump(app, 0.15)
            comp.grab().save(str(out / f"{theme}_{name}.png"))

        ex.set_text("")
        shot("empty")
        for name in ("draft", "error"):
            ex.set_text(DOCS[name])
            ex.edit.setFocus()
            c = ex.edit.textCursor()
            c.movePosition(c.MoveOperation.End)
            ex.edit.setTextCursor(c)
            pump(app, 0.6)
            shot(name)
        for name in ("fixed", "parametric", "batch"):
            ex.set_text(DOCS[name])
            ex.parse()
            pump(app, 1.0)
            shot(f"{name}_parsed")
        ex.set_text(DOCS["fixed"])
        ex.parse()
        pump(app, 0.5)
        c = ex.edit.textCursor()
        c.movePosition(c.MoveOperation.End)
        c.movePosition(c.MoveOperation.Left)
        c.insertText("2")
        c.deleteChar()
        ex.edit.setTextCursor(c)
        pump(app, 0.6)
        shot("stale")
        win.close()
        win.deleteLater()
        pump(app, 0.2)
    print(out)


if __name__ == "__main__":
    main()
