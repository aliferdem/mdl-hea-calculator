"""DPI validation harness: render the main window at Windows 100 / 125 / 150 % geometry and measure it.

The target laptop (Huawei MateBook 14) has a 2160 × 1440 panel.  Windows scaling divides that
into a logical workspace; maximised, the client area is the work area minus the native title bar:

    scale  DPI  logical screen   client (taskbar 48, title bar 31 logical px)
    100 %   96  2160 × 1440      2160 × 1361
    125 %  120  1728 × 1152      1728 × 1073
    150 %  144  1440 ×  960      1440 ×  881

Each scale runs in its own process with ``QT_SCALE_FACTOR`` = scale on the offscreen platform, so
Qt really paints at the fractional device pixel ratio (QSS, fonts, crisp strokes, layout rounding)
and the capture has the true physical size (e.g. 1440 × 881 logical → 2160 × 1322 px at 150 %).
This emulates the DPR, not Windows: ``GetDpiForWindow`` is recorded only by ``--native`` runs,
which use the real windows platform on the current display (see tools/dpi_diagnostics.py).

Usage:
    .venv/Scripts/python.exe tools/dpi_harness.py            # all three scales, writes the JSON
    .venv/Scripts/python.exe tools/dpi_harness.py --native   # adds a native run on this display
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "design" / "screens" / "dpi"
JSON_OUT = ROOT / "design" / "implementation" / "dpi_validation.json"

PANEL = (2160, 1440)
TASKBAR, TITLEBAR = 48, 31
SCALES = (1.0, 1.25, 1.5)


def client_size(scale: float) -> tuple[int, int]:
    w, h = round(PANEL[0] / scale), round(PANEL[1] / scale)
    return w, h - TASKBAR - TITLEBAR


# ---------------------------------------------------------------------------------------------- child
def measure_frame(img, rect, color: str) -> dict:
    """Thickness (device px) of a frame of ``color`` on each side of ``rect`` (device px), measured
    on the middle row / column, away from the corners."""
    x0, y0, w, h = rect
    cx, cy = x0 + w // 2, y0 + h // 2

    def run(points):
        # skip up to 4 px of background outside the frame, then count the frame's pixels
        n, started, skipped = 0, False, 0
        for x, y in points:
            hit = img.pixelColor(x, y).name() == color
            if hit:
                started = True
                n += 1
            elif started or skipped >= 4:
                break
            else:
                skipped += 1
        return n
    return {
        "top": run((cx, y) for y in range(y0, y0 + h)),
        "bottom": run((cx, y) for y in range(y0 + h - 1, y0 - 1, -1)),
        "left": run((x, cy) for x in range(x0, x0 + w)),
        "right": run((x, cy) for x in range(x0 + w - 1, x0 - 1, -1)),
    }


def child(scale: float, theme: str, rows: int, tag: str) -> dict:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    import tempfile

    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    from hea_calc.ui.theme import THEME, load_fonts, t
    load_fonts()
    THEME.set_theme(theme)
    from hea_calc.ui.main_window import MainWindow
    from screenshot import demo, demo_rows

    settings = QSettings(str(Path(tempfile.gettempdir()) / f"hea_dpi_{tag}.ini"), QSettings.Format.IniFormat)
    settings.clear()
    win = MainWindow(settings=settings)
    w, h = client_size(scale)
    win.resize(w, h)
    win.show()
    for _ in range(5):
        app.processEvents()
    demo(win, "single")
    if rows:
        demo_rows(win, rows)
    for _ in range(10):
        app.processEvents()
    dpr = win.devicePixelRatioF()
    info = {"tag": tag, "theme": theme, "windowsScale": f"{round(scale * 100)}%",
            "expectedWindowsDpi": round(96 * scale), "GetDpiForWindow": None,
            "method": "emulated: offscreen platform, QT_SCALE_FACTOR (fractional DPR painting, not Windows)",
            "qtDevicePixelRatio": dpr, "logicalClient": [win.width(), win.height()]}

    def capture(name):
        for _ in range(5):
            app.processEvents()
        pm = win.grab()
        path = OUT_DIR / f"{tag}_{name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        pm.save(str(path))
        return pm, path

    pm, path = capture("top")
    info["physicalScreenshot"] = [pm.width(), pm.height()]
    info["screenshotTop"] = str(path.relative_to(ROOT))
    info["layoutTop"] = win.layout_report()
    # selected periodic tile (Cr) - border thickness on all four sides, measured in the capture
    img = pm.toImage()
    tile = win.elements.table.tiles["Cr"]
    p0 = tile.mapTo(win, QPoint(0, 0))
    rect = (round(p0.x() * dpr), round(p0.y() * dpr), round(tile.width() * dpr), round(tile.height() * dpr))
    sides = measure_frame(img, (rect[0] - 2, rect[1] - 2, rect[2] + 4, rect[3] + 4), t("tile-selected-border"))
    info["tileBorderDevicePx"] = sides
    info["tileBorderSymmetric"] = len(set(sides.values())) == 1
    # scroll to the bottom: main scroll owns overflow, sticky header pins
    sb = win.scroll.verticalScrollBar()
    sb.setValue(sb.maximum())
    win._place_sticky()
    pm2, path2 = capture("scrolled")
    info["screenshotScrolled"] = str(path2.relative_to(ROOT))
    info["layoutScrolled"] = win.layout_report()
    lt, ls = info["layoutTop"], info["layoutScrolled"]
    info["mainScrollbarVisible"] = lt["mainScrollbarVisible"]
    info["tableVerticalScrollbarVisible"] = lt["tableVerticalScrollbarVisible"] or ls["tableVerticalScrollbarVisible"]
    info["tableHorizontalScrollbarVisible"] = lt["tableHorizontalScrollbarVisible"]
    info["horizontalOverflow"] = lt["horizontalOverflow"]
    info["stickyHeaderActiveWhenScrolled"] = ls["stickyHeaderActive"]
    info["stickyHeaderAligned"] = win.sticky.matches_source() if ls["stickyHeaderActive"] else None
    # the sticky header has a job only once the table's own header has scrolled above the viewport (a short
    # scroll range - e.g. the stacked layout with a few rows - leaves the real header on screen)
    hdr = win.table.view.header
    header_top = hdr.mapTo(win.scroll.viewport(), QPoint(0, 0)).y()
    info["tableHeaderTopWhenScrolled"] = header_top
    ok = (info["tileBorderSymmetric"] and not info["horizontalOverflow"]
          and not info["tableVerticalScrollbarVisible"] and not info["tableHorizontalScrollbarVisible"]
          and (not lt["mainScrollbarVisible"] or ls["stickyHeaderActive"] or header_top >= 0))
    info["visualStatus"] = "pass" if ok else "fail"
    win.close()
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", type=float)
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--rows", type=int, default=40)
    ap.add_argument("--tag")
    ap.add_argument("--native", action="store_true")
    args = ap.parse_args()
    if args.child:
        print("JSON:" + json.dumps(child(args.child, args.theme, args.rows, args.tag)))
        return
    results = []
    for scale in SCALES:
        for theme, rows in (("dark", 0), ("dark", args.rows), ("light", args.rows)):
            tag = f"{round(scale * 100)}_{theme}_{rows}rows"
            out = subprocess.run([sys.executable, __file__, "--child", str(scale), "--theme", theme,
                                  "--rows", str(rows), "--tag", tag], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
            line = next((ln for ln in out.stdout.splitlines() if ln.startswith("JSON:")), None)
            if line is None:
                print(out.stdout, out.stderr)
                raise SystemExit(f"harness child failed for {tag}")
            res = json.loads(line[5:])
            results.append(res)
            print(f"{tag:22s} dpr={res['qtDevicePixelRatio']:<5} client={res['logicalClient']} "
                  f"phys={res['physicalScreenshot']} panels={res['layoutTop']['upperPanels']} "
                  f"tile={res['layoutTop']['tileSize']} border={res['tileBorderDevicePx']} "
                  f"mainSB={res['mainScrollbarVisible']} tableVSB={res['tableVerticalScrollbarVisible']} "
                  f"tableHSB={res['tableHorizontalScrollbarVisible']} sticky={res['stickyHeaderActiveWhenScrolled']}"
                  f" -> {res['visualStatus']}")
    native = []
    if args.native:
        out = subprocess.run([sys.executable, str(ROOT / "tools" / "dpi_diagnostics.py"), "--rows", "40",
                              "--scroll-to-table"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        try:
            native.append(json.loads(out.stdout))
        except json.JSONDecodeError:
            print(out.stdout, out.stderr)
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps({
        "display": {"model": "Huawei MateBook 14 (target)", "physical": list(PANEL)},
        "assumptions": {"taskbarLogical": TASKBAR, "titleBarLogical": TITLEBAR},
        "captures": results, "nativeRuns": native,
        "manualNativeProcedure": [
            "On the MateBook set Settings > System > Display > Scale to 100 %, 125 % or 150 % and sign out/in if asked.",
            ".venv/Scripts/python.exe tools/dpi_diagnostics.py --rows 40 --json design/implementation/native_<scale>.json "
            "--screenshot design/screens/dpi/native_<scale>.png",
            "Check: GetDpiForWindow = 96/120/144, devicePixelRatio = 1/1.25/1.5, layout.horizontalOverflow = false, "
            "layout.tableVerticalScrollbarVisible = false, layout.stickyHeaderActive = true after --scroll-to-table.",
        ],
    }, indent=2), encoding="utf-8")
    print("wrote", JSON_OUT)


if __name__ == "__main__":
    main()
