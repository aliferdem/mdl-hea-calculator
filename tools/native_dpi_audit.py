"""Native DPI / responsive audit on the REAL Windows display (MateBook native DPI pass, 2026-10-18).

Runs the application on the native ``windows`` platform at the display's own scale and records:

* the screen (geometry, available geometry, DPR, logical / physical DPI);
* a main-window width sweep through the responsive breakpoint (both directions, top-level window counts);
* real screen captures (``QScreen.grabWindow`` - native title bar and popups included) of the states listed in
  ``SHOTS`` into ``design/screens/matebook-native/<scale>/``;
* a Results column-separator drag, the Expression text-area grip drag and popup geometry checks.

Input is synthesised through Qt (QTest) on the native window; ``--real-input`` additionally drags with the real OS
pointer (``SetCursorPos`` / ``mouse_event``, primary screen at the origin) and reads the OS cursor (``GetCursorInfo``).  The report goes to
``design/implementation/native_dpi_<scale>.json``.  ``--emulate 1.0|1.5`` runs a CONTROLLED emulation through
``QT_SCALE_FACTOR`` relative to the native factor (the output is labelled EMULATED, never native).

Usage:  .venv/Scripts/python.exe tools/native_dpi_audit.py [--emulate 1.5] [--theme dark]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def native_factor() -> float:
    """The display's own scale (Windows setting), measured in a throw-away process without any emulation."""
    import subprocess
    code = ("from PySide6.QtGui import QGuiApplication;import sys;a=QGuiApplication(sys.argv[:1]);"
            "print(a.primaryScreen().devicePixelRatio())")
    env = {k: v for k, v in os.environ.items() if k not in ("QT_SCALE_FACTOR", "QT_QPA_PLATFORM")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    return float(out.stdout.strip().splitlines()[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emulate", type=float, help="target scale (1.0 / 1.5) emulated with QT_SCALE_FACTOR")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--real-input", action="store_true",
                    help="also drag the column separator and the Expression grip with the REAL OS pointer "
                         "(moves the mouse; only while HEA is the foreground window; the pointer is put back)")
    args = ap.parse_args()
    os.environ.pop("QT_QPA_PLATFORM", None)
    emulated = args.emulate is not None
    if emulated:
        os.environ["QT_SCALE_FACTOR"] = f"{args.emulate / native_factor():.6f}"
    elif "QT_SCALE_FACTOR" in os.environ:
        raise SystemExit("QT_SCALE_FACTOR is set: a native audit must run at the display's own scale")
    sys.path.insert(0, str(ROOT))

    from PySide6.QtCore import QPoint, QSettings, Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("HEA Calculator")
    app.setOrganizationName("MDL")
    from hea_calc.ui.theme import THEME, load_fonts
    load_fonts()
    THEME.set_theme(args.theme)
    from hea_calc.ui.widgets.common import install_tooltips
    install_tooltips(app)
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    from hea_calc.core.composition import alloy_name
    from hea_calc.ui.main_window import MainWindow

    settings = QSettings(str(Path(tempfile.mkdtemp()) / "audit.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings)
    win.show_initial()
    screen = win.screen()
    dpr = screen.devicePixelRatio()
    scale = int(round(dpr * 100))
    label = f"{scale}" + ("-emulated" if emulated else "")
    shots_dir = ROOT / "design" / "screens" / "matebook-native" / label
    shots_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"evidence": "EMULATED / CONTROLLED (QT_SCALE_FACTOR)" if emulated else "REAL NATIVE",
                    "qtScaleFactor": os.environ.get("QT_SCALE_FACTOR"),
                    "screen": {"name": screen.name(), "geometry": list(screen.geometry().getRect()),
                               "available": list(screen.availableGeometry().getRect()), "dpr": dpr,
                               "logicalDpi": screen.logicalDotsPerInch(), "physicalDpi": screen.physicalDotsPerInch()},
                    "shots": {}, "checks": {}}
    errors: list[str] = []
    checks = report["checks"]

    def pump(n=8):
        for _ in range(n):
            app.processEvents()

    def check(name, ok, detail=None):
        checks[name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            errors.append(name)

    def state():
        r = win.layout_report()
        return {"client": [win.width(), win.height()], "maximized": win.isMaximized(),
                "expanded": win.pages.currentIndex() == 1, "stacked": r["detailsStacked"],
                "panels": r["upperPanels"], "contentWidth": r["contentWidth"]}

    def grab(name, widget=None, extra=None):
        pump()
        w = widget or win
        fr = w.frameGeometry()
        scr = w.screen() or QGuiApplication.primaryScreen()     # never a cached QScreen wrapper
        pm = scr.grabWindow(0, fr.x(), fr.y(), fr.width(), fr.height())
        path = shots_dir / f"{name}.png"
        pm.save(str(path))
        report["shots"][name] = {"file": str(path.relative_to(ROOT)).replace("\\", "/"),
                                 "image": [pm.width(), pm.height()], "logical": [fr.width(), fr.height()],
                                 "dpr": dpr, **state(), **(extra or {})}

    def popup_geometry(name, popup):
        from hea_calc.ui.widgets.menu import SHADOW
        avail = popup.screen().availableGeometry()
        g = popup.frameGeometry()
        if hasattr(popup, "opens_up"):          # Carbon menu: the visible surface, not its transparent shadow margin
            g = g.adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        owner = popup.parentWidget().window() if popup.parentWidget() else None
        check(f"{name}: inside the available screen (taskbar / edge)", avail.contains(g),
              [g.getRect(), avail.getRect()])
        check(f"{name}: owned by the main window", owner is win, type(owner).__name__ if owner else None)

    def after(ms, fn):
        QTimer.singleShot(ms, fn)

    steps = []

    def step(fn):
        steps.append(fn)
        return fn

    # ------------------------------------------------------------------ 1-4: geometry states
    @step
    def restored_default():
        check("first-run size 1095 x 670", (win.width(), win.height()) == (1095, 670), [win.width(), win.height()])
        grab("01_restored_default")

    @step
    def data():
        for comp in ({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}, {"Al": 0.5, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1},
                     {"Al": 1, "Ni": 1}):
            win.calculate("single", [alloy_name(comp)], [comp], [{}])
        pump()
        run = samples.store_recipe(win.repo, win.engine, samples.c1_recipe())
        win.table.model.refresh_committed()
        win.analysis_ctl.run_finished(run)
        win._check_details()
        report["collectionRun"] = run

    @step
    def maximized():
        win.showMaximized()

    @step
    def maximized_shot():
        st = state()
        check("maximized: wide when the minimum fits", not st["stacked"] or
              st["contentWidth"] < win.top_row.wide_minimum() + 40, st)
        grab("02_maximized")

    @step
    def sweep():
        win.showNormal()
        pump(20)
        win.move(screen.availableGeometry().topLeft())
        t = win.top_row.wide_minimum() + 2 * win.content.layout().contentsMargins().left()
        report["threshold"] = t
        frame_x = win.frameGeometry().width() - win.width()
        if screen.availableGeometry().width() < t + 2 + frame_x:
            # the breakpoint cannot be crossed on this screen (Windows clamps a window wider than the screen):
            # recorded, not faked
            report["sweep"] = f"not reachable: available {screen.availableGeometry().width()} < {t + 2 + frame_x}"
            report["sweepReachable"] = False
            return
        tlw, tlwin = len(QApplication.topLevelWidgets()), len(QGuiApplication.topLevelWindows())
        rows = []
        for w in (t + 2, t + 1, t, t - 1, t - 2, t - 1, t, t + 1, t + 2):
            win.resize(w, 900)
            pump(4)
            r = win.layout_report()
            rows.append({"client": win.width(), "stacked": r["detailsStacked"], "panels": r["upperPanels"],
                         "topLevelWidgets": len(QApplication.topLevelWidgets()),
                         "topLevelWindows": len(QGuiApplication.topLevelWindows())})
            check(f"sweep {w}: {'wide' if w >= t else 'stacked'}", r["detailsStacked"] is (w < t), rows[-1])
            check(f"sweep {w}: fixed panels", r["upperPanels"][:2] == [578, 457], r["upperPanels"])
            check(f"sweep {w}: no transient windows", rows[-1]["topLevelWidgets"] == tlw
                  and rows[-1]["topLevelWindows"] == tlwin)
        report["sweep"] = rows
        win.resize(t + 1, 900)

    @step
    def above():
        if report.get("sweepReachable", True):
            grab("03_just_above_breakpoint")
            win.resize(report["threshold"] - 1, 900)

    @step
    def below():
        if report.get("sweepReachable", True):
            grab("04_just_below_breakpoint")
        win.showMaximized()

    # ------------------------------------------------------------------ 5-9: content states
    @step
    def expanded():
        c = win.analysis_ctl
        c.apply(S.switch_context, S.COLLECTION)
        pump()
        c.scope_for(report["collectionRun"], "full")
        win.set_expanded(True)

    @step
    def expanded_shot():
        grab("05_analysis_expanded")
        win.analysis_ctl.apply(S.set_tab, "plots")

    @step
    def expanded_plots():
        grab("05b_analysis_expanded_plots")
        win.set_expanded(False)
        win.analysis_ctl.apply(S.set_tab, "statistics")

    @step
    def statistics():
        grab("06_statistics")
        win.analysis_ctl.apply(S.set_tab, "plots")

    @step
    def plots():
        grab("07_plots")
        comp = win.composition
        comp.set_mode(2)
        comp.expr.edit.setPlainText("(FeCoNi)1-xAlx\n0 <= x <= 1, step=0.25")
        comp.expr.parse()

    @step
    def expression():
        grab("08_expression")
        # grip drag (vertical only, Composition keeps its outer geometry, footer reachable)
        e = win.composition.expr.edit
        g = e.grip
        comp = win.composition
        panel = comp.geometry()
        h0, w0 = e.height(), e.width()
        QTest.mouseMove(g, QPoint(4, 4))
        cur = g.cursor().shape()
        QTest.mousePress(g, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(4, 4))
        QTest.mouseMove(g, QPoint(4, 44))
        QTest.mouseRelease(g, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(4, 44))
        pump()
        footer = comp.footer if hasattr(comp, "footer") else None
        fvis = footer is None or comp.rect().contains(footer.geometry())
        check("expression grip: size-ver cursor", cur == Qt.CursorShape.SizeVerCursor, str(cur))
        check("expression grip: vertical-only resize", e.height() == h0 + 40 and e.width() == w0,
              [h0, e.height(), w0, e.width()])
        check("expression grip: Composition outer geometry fixed", comp.geometry() == panel,
              [panel.getRect(), comp.geometry().getRect()])
        check("expression grip: footer inside the panel", fvis)
        report["grip"] = {"size_px_logical": [g.width(), g.height()], "dpr": g.devicePixelRatioF()}
        grab("08b_expression_grip_dragged")
        comp.set_mode(0)

    @step
    def results():
        win.scroll.ensureWidgetVisible(win.table, 0, 0)
        pump()
        v = win.table.view
        h = v.header
        i = v.m.keys.index("density") if "density" in v.m.keys else 1
        x = h.sectionViewportPosition(i) + h.sectionSize(i) - 1
        y = h.height() // 2
        w0 = h.sectionSize(i)
        QTest.mouseMove(h.viewport(), QPoint(x, y))
        pump(2)
        # the header the user actually points at: the table's own, or the sticky copy pinned over it
        under = QApplication.widgetAt(h.viewport().mapToGlobal(QPoint(x, y)))
        hdr_under = under.parentWidget() if under is not None and under.parentWidget() in (h, win.sticky) else h
        cur = hdr_under.cursor().shape()       # QHeaderView sets the split cursor on itself
        report["columnDragHeader"] = "sticky" if hdr_under is win.sticky else "table"
        QTest.mousePress(h.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
        for dx in (10, 25, 40, 60):
            QTest.mouseMove(h.viewport(), QPoint(x + dx, y))
        QTest.mouseRelease(h.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(x + 60, y))
        pump()
        win.sticky.sync()
        # QTest hover on a native window races the real pointer's enter/leave: recorded, not judged (the REAL
        # pointer check below judges the cursor)
        report["syntheticHoverCursor"] = str(cur)
        check("results drag: width follows the pointer (logical px)", h.sectionSize(i) == w0 + 60,
              [w0, h.sectionSize(i)])
        check("results drag: sticky header in sync", win.sticky.matches_source())
        check("results drag: persisted by key", v.m.keys[i] in str(settings.value("column_widths")))
        check("results drag: no table vertical scroll", not win.table.internal_vertical_scrollbar_visible())
        report["columnDrag"] = {"column": v.m.keys[i], "before": w0, "after": h.sectionSize(i)}
        grab("09_results")

    # ------------------------------------------------------------------ real OS pointer (opt-in)
    def real_input():
        import ctypes
        import time
        from ctypes import wintypes
        u32 = ctypes.windll.user32

        class CURSORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hCursor", wintypes.HANDLE),
                        ("pt", wintypes.POINT)]

        def os_cursor():
            ci = CURSORINFO(); ci.cbSize = ctypes.sizeof(CURSORINFO)
            u32.GetCursorInfo(ctypes.byref(ci))
            kinds = {u32.LoadCursorW(None, 32644): "SizeWE", u32.LoadCursorW(None, 32645): "SizeNS",
                     u32.LoadCursorW(None, 32512): "Arrow", u32.LoadCursorW(None, 32513): "IBeam",
                     u32.LoadCursorW(None, 32649): "Hand"}
            return kinds.get(ci.hCursor, hex(ci.hCursor or 0))

        def wait(ms):
            t = time.perf_counter() + ms / 1000
            while time.perf_counter() < t:
                app.processEvents(); time.sleep(0.01)

        def phys(widget, p):
            g = widget.mapToGlobal(p)
            return int(g.x() * dpr + dpr / 2), int(g.y() * dpr + dpr / 2)

        def safe(widget, p) -> bool:
            """Only press where the pointer really hits ``widget`` inside the main window's client area (never the
            caption, a border or another window: a press there starts Windows' modal move loop)."""
            g = widget.mapToGlobal(p)
            body = win.centralWidget()
            client = body.rect().translated(body.mapToGlobal(QPoint(0, 0)))
            hit = QApplication.widgetAt(g)
            return client.adjusted(4, 4, -4, -4).contains(g) and hit is widget

        def drag(widget, p, dx, dy, approach=QPoint(-12, 0)):
            if not safe(widget, p):
                return None
            x, y = phys(widget, p)
            for k in range(4, -1, -1):              # approach like a hand does: Enter, then real moves
                u32.SetCursorPos(x + round(approach.x() * dpr * k / 4), y + round(approach.y() * dpr * k / 4))
                wait(60)
            wait(200)
            hover = os_cursor()
            if hover not in ("Arrow", "IBeam", "Hand", "SizeWE", "SizeNS"):
                hover = f"qt:{QApplication.widgetAt(widget.mapToGlobal(p)).parentWidget().cursor().shape().name}"                     if QApplication.widgetAt(widget.mapToGlobal(p)) is not None else hover
            u32.mouse_event(0x0002, 0, 0, 0, 0); wait(60)                    # LEFTDOWN
            for k in range(1, 11):
                u32.SetCursorPos(x + round(dx * dpr * k / 10), y + round(dy * dpr * k / 10)); wait(25)
            u32.mouse_event(0x0004, 0, 0, 0, 0); wait(250)                    # LEFTUP
            return hover

        win.raise_(); win.activateWindow(); wait(400)
        if u32.GetForegroundWindow() != int(win.winId()):
            check("real input: HEA is the foreground window (else skipped)", False, "not foreground: skipped")
            return
        old = wintypes.POINT(); u32.GetCursorPos(ctypes.byref(old))
        import threading
        guard = threading.Timer(20.0, lambda: u32.mouse_event(0x0004, 0, 0, 0, 0))   # never leave the button down
        guard.daemon = True
        guard.start()
        try:
            v = win.table.view; h = v.header
            bar = win.scroll.verticalScrollBar()           # the table's own header on screen, below the app header
            bar.setValue(max(0, h.mapTo(win.content, QPoint(0, 0)).y() - 160)); wait(300)
            i = v.m.keys.index("density")
            w0 = h.sectionSize(i)
            p = QPoint(h.sectionViewportPosition(i) + h.sectionSize(i) - 1, h.height() // 2)
            under = QApplication.widgetAt(h.viewport().mapToGlobal(p))
            hover = drag(h.viewport(), p, 50, 0)
            if hover is None:
                check("REAL pointer: separator on screen (else skipped, no click)", False, "not hit-testable")
                return
            check("REAL pointer: split cursor over the Results separator",
                  hover in ("SizeWE", "qt:SplitHCursor"), hover)
            check("REAL pointer: separator drag follows the pointer (±1 px at 125 %)",
                  abs(h.sectionSize(i) - (w0 + 50)) <= 1, [w0, h.sectionSize(i)])
            check("REAL pointer: no accidental vertical scroll in the table",
                  not win.table.internal_vertical_scrollbar_visible())
            win.sticky.sync()
            check("REAL pointer: sticky header in sync", win.sticky.matches_source())
            report["realColumnDrag"] = {"before": w0, "after": h.sectionSize(i), "hover": hover,
                                        "under": type(under).__name__ if under else None}
            win.scroll.verticalScrollBar().setValue(0)
            comp = win.composition
            comp.set_mode(2); wait(300)
            e = comp.expr.edit; g = e.grip
            panel, h0, w0e = comp.geometry(), e.height(), e.width()
            hover = drag(g, QPoint(g.width() // 2, g.height() // 2), 0, 36, approach=QPoint(-10, -10))
            if hover is None:
                check("REAL pointer: grip on screen (else skipped, no click)", False, "not hit-testable")
                return
            check("REAL pointer: size-ver cursor on the Expression grip", hover == "SizeNS", hover)
            check("REAL pointer: grip resizes vertically only (±1 px)",
                  abs(e.height() - (h0 + 36)) <= 1 and e.width() == w0e, [h0, e.height(), w0e, e.width()])
            check("REAL pointer: Composition outer geometry fixed", comp.geometry() == panel)
            check("REAL pointer: footer inside the panel", comp.rect().contains(comp.footer.geometry()))
            report["realGripDrag"] = {"before": h0, "after": e.height(), "hover": hover}
            grab("08c_expression_grip_real_pointer")
            comp.set_mode(0)
        finally:
            guard.cancel()
            if u32.GetAsyncKeyState(0x01) & 0x8000:
                u32.mouse_event(0x0004, 0, 0, 0, 0)
            u32.SetCursorPos(old.x, old.y)

    if args.real_input:
        steps.append(real_input)

    # ------------------------------------------------------------------ 10-15: popups and windows
    def menu_shot(name, opener, menu):
        def go():
            after(0, opener)
            after(700, lambda: (popup_geometry(name, menu), grab(name), menu.close()))
        return go

    hdr = win.header
    steps.append(lambda: win.scroll.verticalScrollBar().setValue(0))
    steps.append(menu_shot("10_file_menu", hdr.file_item._open, win.file_menu))
    steps.append(lambda: None)
    steps.append(menu_shot("11_edit_menu", hdr.edit_item._open, win.edit_menu))
    steps.append(lambda: None)
    steps.append(menu_shot("12_theme_menu", hdr._open_theme, win.theme_menu))
    steps.append(lambda: None)

    @step
    def inspector():
        win.analysis_ctl.apply(S.set_tab, "plots")
        pump()
        coll = win.analysis.collection
        if coll.plot is not None and coll.plot.spec is not None:
            coll._point_clicked(coll.plot.spec.data["ids"][0])

    @step
    def inspector_shot():
        from hea_calc.ui.widgets.dropdown import Popover
        pops = [w for w in QApplication.topLevelWidgets() if isinstance(w, Popover) and w.isVisible()]
        check("point inspector opens", len(pops) == 1, len(pops))
        if pops:
            popup_geometry("13_point_inspector", pops[0])
        grab("13_point_inspector")
        for p in pops:
            p.close()
        win.show_help("home")

    @step
    def help_shot():
        grab("14_help", win._help)
        win._help.close()
        win.show_about()

    @step
    def about_shot():
        grab("15_about", win._about)
        win._about.close()

    @step
    def native_children():
        nat = [w.objectName() or type(w).__name__ for w in QApplication.allWidgets()
               if not w.isWindow() and w.internalWinId()]
        check("no native child windows (AppBodyWindow)", not nat, nat)

    it = iter(steps)

    def nxt():
        fn = next(it, None)
        if fn is None:
            report["errors"] = errors
            out = ROOT / "design" / "implementation" / f"native_dpi_{label}.json"
            out.write_text(json.dumps(report, indent=1), encoding="utf-8")
            print(json.dumps({"label": label, "errors": errors, "checks": len(checks), "out": str(out)}))
            win.close()
            return
        try:
            fn()
        except Exception as exc:                      # noqa: BLE001 - recorded, the audit continues
            errors.append(f"{getattr(fn, '__name__', 'step')}: {exc!r}")
        after(700, nxt)

    after(1200, nxt)
    rc = app.exec()
    return rc if not errors else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
