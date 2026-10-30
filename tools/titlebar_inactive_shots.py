"""Side-by-side title bar captures: active vs inactive (real OS activation), White and Gray 100, 100 / 125 / 150 %.

    .venv/Scripts/python.exe tools/titlebar_inactive_shots.py [outdir]

Each (theme, scale) runs in its own process (a multiplier other than 1 sets QT_SCALE_FACTOR for that diagnostic
process only, as tools/dpi_harness.py does - on a 125 % display 0.8 / 1 / 1.2 give 100 / 125 / 150 %).  The bar shows
a cancelled run (warning state line) so the subdued state line is visible.  The window is made active with
SetForegroundWindow, inactive by giving the foreground to the taskbar; the bar is captured from its own rendering
(``grab``) in both states.  Output: one PNG per theme (rows: scale; left: active, right: inactive; the left part of the
bar and its right end) and ``titlebar_inactive.json`` (sampled colours and WCAG contrast ratios).
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MULTS = (0.8, 1.0, 1.2)


def contrast(a: str, b: str) -> float:
    def lum(h):
        h = h.lstrip("#")[-6:]
        r, g, bl = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        f = lambda v: v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl)
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def one(theme: str, mult: float, out: Path) -> dict:
    if mult != 1.0:
        os.environ["QT_SCALE_FACTOR"] = f"{mult:g}"
    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from hea_calc.ui.theme import THEME, load_fonts, t
    load_fonts()
    THEME.set_theme(theme)
    from hea_calc.ui.main_window import MainWindow
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1500, 860)
    w.move(40, 40)
    w.show()
    u = ctypes.windll.user32
    bar = w.header

    def pump(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)
    pump(1.0)
    w.progress.show()
    w.progress.set_result("warning", "Calculation cancelled", "Results calculated so far are kept")
    pump(0.3)

    def foreground_self():
        u.keybd_event(0x12, 0, 0, 0)
        u.keybd_event(0x12, 0, 2, 0)
        u.SetForegroundWindow(int(w.winId()))
        pump(0.7)

    def capture(tag):
        img = bar.grab().toImage()
        dpr = img.devicePixelRatio()
        path = out / f"_{theme}_{mult:g}_{tag}.png"
        img.save(str(path))

        def region_fg(wd):
            bg = QColor(bar.surface())
            x0, x1 = wd.mapTo(bar, QPoint(0, 0)).x(), wd.mapTo(bar, QPoint(wd.width(), 0)).x()
            best, bd = None, -1
            for x in range(int(x0 * dpr), int(x1 * dpr)):
                for y in range(int(6 * dpr), int(26 * dpr)):
                    c = img.pixelColor(x, y)
                    d = abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue())
                    if d > bd:
                        bd, best = d, c
            return best.name()
        sx = bar.panels_btn.mapTo(bar, QPoint(-24, 0)).x()
        return {"active_flag": bar.window_active, "file": str(path),
                "surface": img.pixelColor(int(sx * dpr), int(3 * dpr)).name(),
                "site": region_fg(bar.name), "menu_file": region_fg(bar.file_item),
                "panels_icon": region_fg(bar.panels_btn), "close_glyph": region_fg(bar.close_btn),
                "line": img.pixelColor(int(bar.width() / 2 * dpr), int(34 * dpr)).name()}
    foreground_self()
    act = capture("active")
    u.SetForegroundWindow(u.FindWindowW("Shell_TrayWnd", None))
    pump(0.7)
    ina = capture("inactive")
    foreground_self()
    back = capture("reactivated")
    res = {"theme": theme, "mult": mult, "dpr": w.devicePixelRatioF(), "active": act, "inactive": ina,
           "reactivated": back,
           "contrast": {"surface_vs_active": contrast(ina["surface"], act["surface"]),
                        "site_inactive": contrast(ina["site"], ina["surface"]),
                        "site_active": contrast(act["site"], act["surface"]),
                        "menu_inactive": contrast(ina["menu_file"], ina["surface"]),
                        "menu_active": contrast(act["menu_file"], act["surface"]),
                        "line_inactive": contrast(ina["line"], t("background")),
                        "line_active": contrast(act["line"], t("background"))}}
    w.close()
    pump(0.2)
    return res


def compose(results: list[dict], out: Path) -> None:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    for theme in ("light", "dark"):
        rows = [r for r in results if r["theme"] == theme]
        crops = []
        for r in rows:
            pair = []
            for state in ("active", "inactive"):
                img = QImage(r[state]["file"])
                d = r["dpr"]
                left = img.copy(QRect(0, 0, int(980 * d), img.height()))
                right = img.copy(QRect(img.width() - int(200 * d), 0, int(200 * d), img.height()))
                pair.append((left, right))
            crops.append(pair)
        gap = 12
        width = max(2 * (pl.width() + pr.width() + gap) + gap * 3 for (pl, pr), _ in crops)
        height = sum(pl.height() + gap for (pl, _), _ in crops) + gap
        canvas = QImage(width, height, QImage.Format.Format_RGB32)
        canvas.fill(QColor("#8d8d8d"))
        p = QPainter(canvas)
        y = gap
        for pair in crops:
            x = gap
            for left, right in pair:
                p.drawImage(x, y, left)
                p.drawImage(x + left.width() + 2, y, right)
                x += left.width() + right.width() + gap * 3
            y += pair[0][0].height() + gap
        p.end()
        canvas.save(str(out / f"titlebar_inactive_{theme}.png"))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--one":
        print(json.dumps(one(sys.argv[2], float(sys.argv[3]), Path(sys.argv[4]))))
        return
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "design" / "screens" / "titlebar_inactive"
    out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("QT_QPA_PLATFORM", "QT_SCALE_FACTOR")}
    results = []
    for theme in ("light", "dark"):
        for m in MULTS:
            r = subprocess.run([sys.executable, __file__, "--one", theme, str(m), str(out)], capture_output=True,
                               text=True, cwd=str(ROOT), env=env, timeout=180)
            line = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
            if not line:
                print(r.stdout[-1500:], r.stderr[-1500:])
                raise SystemExit(1)
            results.append(json.loads(line[-1]))
    compose(results, out)
    (out / "titlebar_inactive.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    for r in results:
        print(r["theme"], r["dpr"], r["contrast"], "surface", r["active"]["surface"], "->", r["inactive"]["surface"],
              "flags", r["active"]["active_flag"], r["inactive"]["active_flag"], r["reactivated"]["active_flag"])


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
