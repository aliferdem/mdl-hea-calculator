"""Native Windows checks of the UI regression and consistency pass (2026-10-28), run by
``test_ui_regression_consistency.test_native_menu_join_and_callouts`` (HEA_NATIVE_TESTS=1), at the desktop's real
scale (the target: 125 %).

* item 5 - a header menu opened from the title bar: the device-pixel column under the trigger, from the trigger's
  lower part across the join into the menu, is the menu surface (``layer-02``) on every row - no dark seam -
  for File / Edit / View / Help, both themes, and again after the window has been moved;
* item 1 - the documentation notifications drawn at the native ratio: one continuous top edge that meets the 3 px
  accent, a one-row frame, and balanced vertical padding.

Prints ``ALL NATIVE REGRESSION CHECKS PASSED`` (exit code 0) or the failures (exit code 1)."""

import sys
import tempfile
import time
from pathlib import Path

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PySide6.QtCore import QPoint, QRect, QSettings
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from hea_calc.ui.theme import THEME, load_fonts, t
    load_fonts()
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.widgets.header import HeaderMenuItem, TitleBar
    from hea_calc.ui.help_window import HelpWindow

    failures = []
    report = {}

    def pump(s=0.3):
        end = time.monotonic() + s
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    scr = QGuiApplication.primaryScreen()
    dpr = scr.devicePixelRatio()
    report["dpr"] = dpr
    win = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    win.resize(1300, 860)
    win.move(80, 60)
    win.show()
    pump(1.0)
    tb = win.findChild(TitleBar)

    # ------------------------------------------------------------------ item 5: menu trigger / popup join
    for theme in ("dark", "light"):
        THEME.set_theme(theme)
        win.apply_theme()
        for moved in (False, True):
            if moved:
                win.move(win.x() + 37, win.y() + 23)          # a non-integral device offset at 125 %
            pump(0.6)
            for item in [it for it in tb.menu_items if isinstance(it, HeaderMenuItem) and it.menu_ is not None]:
                m = item.menu_
                item._set_open(True)
                m.trigger_width = 0
                m.menubar = tb
                tb.open_item = item
                m.open_below(item, exec_=False, merge=True)
                pump(0.6)
                g = item.mapToGlobal(QPoint(0, 0))
                # from 6 px above the trigger's bottom (below its label) to 10 px into the menu
                box = QRect(g.x(), g.y() + item.height() - 6, item.width(), 16)
                img = scr.grabWindow(0, box.x(), box.y(), box.width(), box.height()).toImage()
                surf = t("layer-02")
                cx = img.width() // 2
                odd = [(y, img.pixelColor(cx, y).name()) for y in range(img.height())
                       if img.pixelColor(cx, y).name() != surf]
                report[f"menu {theme}{' moved' if moved else ''} {item.text()}"] = odd or "seamless"
                if odd:
                    failures.append((f"5 menu join {theme} moved={moved} {item.text()}", odd[:8]))
                m.hide()
                item._set_open(False)
                tb.open_item = None
                pump(0.3)
    win.close()
    pump(0.3)

    # ------------------------------------------------------------------ item 1: documentation notifications
    def blend(fg, bg, a=0.4):
        f, b = QColor(fg), QColor(bg)
        return QColor(round(a * f.red() + (1 - a) * b.red()), round(a * f.green() + (1 - a) * b.green()),
                      round(a * f.blue() + (1 - a) * b.blue())).name()

    for theme in ("light", "dark"):
        THEME.set_theme(theme)
        hw = HelpWindow(None)
        hw.resize(1100, 900)
        hw.move(100, 60)
        hw.show()
        hw.open("first-calculation")
        pump(0.8)
        img = hw.view.viewport().grab().toImage()
        k = img.devicePixelRatio()
        tok = THEME.tokens
        checked = 0
        for kind, r in hw.view.callout_boxes():
            if r.top() < 1 or r.bottom() * k > img.height() - 3:
                continue
            acc, bg = tok[f"support-{kind}"], tok[f"notification-{kind}-bg"]
            edge = blend(acc, bg)
            x0, x1 = round(r.left() * k), round(r.right() * k)
            mid = x0 + int(40 * k)
            rows = [y for y in range(int(r.top() * k) - 3, int(r.bottom() * k) + 4)
                    if img.pixelColor(mid, y).name() == edge]
            if len(rows) != 2:
                failures.append((f"1 callout {theme} {kind}: edge rows", rows))
                continue
            top, bottom = rows
            corner = [img.pixelColor(x, top).name() for x in range(x0, x0 + 3)]
            line = {img.pixelColor(x, top).name() for x in range(x0 + 4, x1 - 2)}
            accent_w = sum(1 for x in range(x0, x0 + 8) if img.pixelColor(x, top + 5).name() == acc)
            # balanced padding: the text ink of the note cell between the edges
            ink = [y for y in range(top + 1, bottom)
                   if any(abs(img.pixelColor(x, y).lightness() - QColor(bg).lightness()) > 60
                          for x in range(x0 + int(60 * k), x1 - int(16 * k), 2))]
            pads = (min(ink) - top, bottom - max(ink)) if ink else None
            report[f"callout {theme} {kind}"] = {"top_row": top, "accent_px": accent_w, "pads_device": pads}
            if set(corner) != {acc} or line != {edge}:
                failures.append((f"1 callout {theme} {kind}: top edge", corner, sorted(line)[:6]))
            if accent_w != round(3 * k):
                failures.append((f"1 callout {theme} {kind}: accent width", accent_w))
            if pads is None or abs(pads[0] - pads[1]) > 4 * k:
                failures.append((f"1 callout {theme} {kind}: padding", pads))
            checked += 1
        if checked < 1:
            failures.append((f"1 callout {theme}", "no callout in view"))
        hw.close()
        pump(0.3)
    THEME.set_theme("dark")

    for key, v in report.items():
        print(key, v)
    if failures:
        for f in failures:
            print("FAIL", f)
        sys.exit(1)
    print("ALL NATIVE REGRESSION CHECKS PASSED", {"dpr": dpr})
