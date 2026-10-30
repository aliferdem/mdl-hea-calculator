"""Native Windows checks of the UX / workflow package (2026-10-28), at the desktop's real scale (target 125 %); run by
``test_ux_workflow_package.test_native_ux_checks`` (HEA_NATIVE_TESTS=1).  Prints the measurements and
``ALL NATIVE UX CHECKS PASSED`` (exit 0), or the failures (exit 1).

* A2 - pagination: the focus frame of both selects has device rows on all four sides inside the bar;
* A15 - main scroll bar: the drawn 4 px thumb leaves equal device gaps to the content and to the window edge;
* A9 - full screen: Exit full screen shows beside the top-panels action, is a client area for the native chrome,
  and restores the window;
* A11 - completion: the list opens under the caret, on the screen, without taking the focus;
* A1 - Documentation: Back / Forward buttons, their states;
* A5 - the device-pixel gaps between composition cells (reported; see the report for the fractional-scale note).
"""

import sys
import tempfile
import time
from pathlib import Path

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PySide6.QtCore import QPoint, QSettings, Qt
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from hea_calc.ui.theme import THEME, load_fonts, t
    load_fonts()
    from hea_calc.ui.main_window import MainWindow

    failures, report = [], {}

    def pump(s=0.3):
        end = time.monotonic() + s
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    dpr = QGuiApplication.primaryScreen().devicePixelRatio()
    report["dpr"] = dpr
    win = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    win.resize(1440, 860)
    win.move(60, 40)
    win.show()
    pump(1.0)
    names = [f"R{i}" for i in range(40)]
    comps = [{"Co": 1 + (i % 4) * 0.25, "Cr": 1, "Fe": 1, "Ni": 1} for i in range(40)]
    win.calculate("single", names, comps, [{}] * 40)
    for _ in range(200):
        pump(0.05)
        if win.worker is None and win.table.model.total_count() >= 40:
            break

    for theme in ("dark", "light"):
        THEME.set_theme(theme)
        win.apply_theme()
        pump(0.4)
        # ---------------------------------------------------------- A2 pagination focus frames
        pb = win.table.pagination
        for name, w in (("size", pb.size_box), ("page", pb.page_field)):
            w.setFocus(Qt.FocusReason.TabFocusReason)
            pump(0.3)
            img = pb.grab().toImage()
            k = img.devicePixelRatio()
            g = w.geometry()
            focus = QColor(t("focus")).name()
            mx, my = int(g.center().x() * k), int(g.center().y() * k)
            top = [y for y in range(int(g.top() * k) - 1, int(g.top() * k) + 4) if img.pixelColor(mx, y).name() == focus]
            bot = [y for y in range(int((g.bottom() - 3) * k), min(img.height(), int((g.bottom() + 2) * k)))
                   if img.pixelColor(mx, y).name() == focus]
            left = [x for x in range(int(g.left() * k) - 1, int(g.left() * k) + 4) if img.pixelColor(x, my).name() == focus]
            right = [x for x in range(int((g.right() - 3) * k), int((g.right() + 2) * k)) if img.pixelColor(x, my).name() == focus]
            report[f"A2 {theme} {name} focus rows/cols (top,bottom,left,right)"] = (len(top), len(bot), len(left), len(right))
            if not (top and bot and left and right):
                failures.append((f"A2 {theme} {name} focus frame", (top, bot, left, right)))
        win.setFocus()
        pump(0.2)
        # ---------------------------------------------------------- A15 scroll bar gutter (device pixels)
        sa = win.scroll
        if sa.overlay.isVisible():
            img = sa.grab().toImage()
            k = img.devicePixelRatio()
            vp = sa.viewport()
            content_right = max(p.mapTo(vp, p.rect().topRight()).x() for p in (win.table, win.top_row)) + 1
            thumb = QColor(t("scrollbar-thumb")).name()
            cols = {}
            for x in range(int(content_right * k), int(vp.width() * k)):
                n = sum(1 for y in range(0, img.height(), 4) if img.pixelColor(x, y).name() == thumb)
                if n > 3:
                    cols[x] = n
            xs = sorted(cols)
            if xs:
                lg, rg = xs[0] - int(content_right * k), int(vp.width() * k) - 1 - xs[-1]
                report[f"A15 {theme} thumb device cols / gaps (content, edge)"] = (len(xs), lg, rg)
                if abs(lg - rg) > 1:
                    failures.append((f"A15 {theme} not centred", (lg, rg)))
            else:
                failures.append((f"A15 {theme}", "thumb not found"))
        else:
            failures.append((f"A15 {theme}", "no main scroll bar"))

    # -------------------------------------------------------------- A9 exit full screen
    THEME.set_theme("dark")
    win.apply_theme()
    win.showNormal()
    pump(0.4)
    before = win.geometry()
    win.set_fullscreen(True)
    pump(1.0)
    h = win.header
    b = h.exit_fs_btn
    ok = win.isFullScreen() and b.isVisible() and b.x() == h.panels_btn.geometry().right() + 1
    report["A9 exit button visible beside top panels"] = ok
    report["A9 hit test"] = h.hit_test(b.mapTo(h, b.rect().center()))
    if not ok or report["A9 hit test"] != "client":
        failures.append(("A9 exit full screen", report["A9 hit test"]))
    b.click()
    pump(1.0)
    report["A9 restored geometry"] = (win.geometry() == before, not win.isFullScreen())
    if win.isFullScreen() or win.geometry() != before:
        failures.append(("A9 restore", win.geometry(), before))

    # -------------------------------------------------------------- A11 completion popup
    win.composition.set_mode(2)
    pump(0.3)
    e = win.composition.expr
    e.set_text("AlxCoCrFeNi\n0 <= x <= 1, po")
    ed = e.edit
    win.activateWindow()
    ed.setFocus()
    c = ed.textCursor()
    c.movePosition(c.MoveOperation.End)
    ed.setTextCursor(c)
    pump(0.3)
    ed.show_completion(explicit=False)
    pump(0.4)
    pop = ed.popup
    caret = ed.viewport().mapToGlobal(ed.cursorRect().bottomLeft())
    scr = QGuiApplication.screenAt(caret).availableGeometry()
    report["A11 popup / caret bottom"] = (pop.geometry().getRect(), caret.y())
    if not (pop.isVisible() and pop.geometry().top() >= caret.y() - 1 and scr.contains(pop.geometry())):
        failures.append(("A11 popup placement", pop.geometry(), caret))
    if QApplication.focusWidget() is not ed:
        failures.append(("A11 focus", QApplication.focusWidget()))
    ed.hide_completion()

    # -------------------------------------------------------------- A5 device gaps (reported)
    win.composition.set_mode(1)
    for el in ("Co", "Fe"):
        win.elements.table.tiles[el].click()
    pump(0.4)
    sw = win.composition.sweep
    row = sw.rows["Co"]
    img = sw.grab().toImage()
    k = img.devicePixelRatio()
    y = int((row.mapTo(sw, QPoint(0, 3)).y()) * k)
    cols = [img.pixelColor(x, y).name() for x in range(img.width())]
    runs, s0 = [], 0
    for x in range(1, len(cols) + 1):
        if x == len(cols) or cols[x] != cols[s0]:
            runs.append((s0, x - s0))
            s0 = x
    report["A5 space row device runs (start, width) first 9"] = runs[:9]

    # -------------------------------------------------------------- A1 help history
    win.show_help("home")
    pump(0.6)
    hw = win._help
    hw.open("results-table")
    pump(0.3)
    report["A1 back/forward enabled"] = (hw.back_btn.isEnabled(), hw.forward_btn.isEnabled())
    if not hw.back_btn.isEnabled() or hw.forward_btn.isEnabled():
        failures.append(("A1 states", report["A1 back/forward enabled"]))
    hw.close()
    win.close()
    pump(0.3)
    for key, v in report.items():
        print(key, v)
    if failures:
        for f in failures:
            print("FAIL", f)
        sys.exit(1)
    print("ALL NATIVE UX CHECKS PASSED", {"dpr": dpr})
