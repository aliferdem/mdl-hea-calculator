"""Side-by-side crop of the Figma frame and an app screenshot for visual validation.

The Figma frame includes the 32 px native title bar; the app screenshot does not, so Figma is shifted.

Usage:
    .venv/Scripts/python.exe tools/compare.py x y w h [--app design/screens/app_dark.png]
           [--figma design/figma/main_170-11154.png] [--zoom 2] [--out design/screens/compare.png]
Coordinates are app (client) coordinates.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("x", type=int)
    ap.add_argument("y", type=int)
    ap.add_argument("w", type=int)
    ap.add_argument("h", type=int)
    ap.add_argument("--app", default=str(ROOT / "design" / "screens" / "app_dark.png"))
    ap.add_argument("--figma", default=str(ROOT / "design" / "figma" / "main_170-11154.png"))
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--out", default=str(ROOT / "design" / "screens" / "compare.png"))
    a = ap.parse_args()
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

    _app = QGuiApplication([])
    fig = QImage(a.figma).copy(QRect(a.x, a.y + 32, a.w, a.h))
    app = QImage(a.app).copy(QRect(a.x, a.y, a.w, a.h))
    z = a.zoom
    W, H = int(a.w * z), int(a.h * z)
    out = QImage(W, H * 2 + 4, QImage.Format.Format_RGB32)
    out.fill(QColor("#ff00ff"))
    p = QPainter(out)
    p.drawImage(QRect(0, 0, W, H), fig.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
                                               Qt.TransformationMode.FastTransformation))
    p.drawImage(QRect(0, H + 4, W, H), app.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                   Qt.TransformationMode.FastTransformation))
    p.end()
    out.save(a.out)
    print(a.out)


if __name__ == "__main__":
    main()
