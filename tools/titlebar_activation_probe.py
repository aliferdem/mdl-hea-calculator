"""Native title-bar activation probe: the bar's foreground colours while the main window is active, after the
taskbar / Help / the Analysis window / a dialog take activation, and after returning; the number of activation
changes while a title-bar menu opens (flicker check).  Prints one JSON line; captures go to <outdir>.

    .venv/Scripts/python.exe tools/titlebar_activation_probe.py <light|dark> <scale multiplier, 1 = native> <outdir>

A multiplier other than 1 sets QT_SCALE_FACTOR for this diagnostic process only (100 / 150 % emulation on a 125 %
display), as tools/dpi_harness.py does; production never sets it.
"""
import ctypes, json, os, sys, tempfile, time
from pathlib import Path

APP = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, APP)


def main():
    theme, mult, out = sys.argv[1], float(sys.argv[2]), Path(sys.argv[3])
    if mult != 1.0:
        os.environ["QT_SCALE_FACTOR"] = f"{mult:g}"
    out.mkdir(parents=True, exist_ok=True)
    from PySide6.QtCore import QPoint, QSettings, QTimer
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from hea_calc.ui.theme import THEME, load_fonts, t
    load_fonts()
    THEME.set_theme(theme)
    from hea_calc.ui.main_window import MainWindow
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1400, 860); w.move(60, 60); w.show(); w.raise_(); w.activateWindow()
    u = ctypes.windll.user32
    bar = w.header
    changes = []
    orig = bar.set_window_active

    def spy(on):
        if bool(on) != bar.window_active:
            changes.append(bool(on))
        orig(on)
    bar.set_window_active = spy

    def pump(sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            app.processEvents(); time.sleep(0.005)

    def foreground_self():
        hwnd = int(w.winId())
        u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)      # Alt tap: lets SetForegroundWindow pass
        u.SetForegroundWindow(hwnd)
        pump(0.6)

    def sample(tag):
        img = bar.grab().toImage()
        dpr = img.devicePixelRatio()

        def darkest(x0, x1, y0=6, y1=26):
            """the foreground of a region: the pixel furthest from the bar background"""
            bg = QColor(t("shell"))
            best, bd = None, -1
            for x in range(int(x0 * dpr), int(x1 * dpr)):
                for y in range(int(y0 * dpr), int(y1 * dpr)):
                    c = img.pixelColor(x, y)
                    d = abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue())
                    if d > bd:
                        bd, best = d, c
            return best.name()
        g = lambda wd: (wd.mapTo(bar, QPoint(0, 0)).x(), wd.mapTo(bar, QPoint(wd.width(), 0)).x())  # noqa: E731
        rec = {"tag": tag, "active_flag": bar.window_active,
               "site": darkest(*g(bar.name)), "file": darkest(*g(bar.file_item)),
               "panels_icon": darkest(*g(bar.panels_btn)), "close_glyph": darkest(*g(bar.close_btn)),
               "min_glyph": darkest(*g(bar.min_btn))}
        img.save(str(out / f"{theme}_{w.devicePixelRatioF():g}_{tag.replace(' ', '_')}.png"))
        return rec

    pump(1.2)
    foreground_self()
    res = {"theme": theme, "dpr": w.devicePixelRatioF(), "states": []}
    res["states"].append(sample("active"))
    # another application takes the foreground (the taskbar)
    tray = u.FindWindowW("Shell_TrayWnd", None)
    u.SetForegroundWindow(tray)
    pump(0.6)
    res["states"].append(sample("inactive taskbar"))
    foreground_self()
    res["states"].append(sample("reactivated"))
    # a title-bar menu opens and closes: no activation change at all
    n0 = len(changes)
    QTimer.singleShot(400, lambda: (res.__setitem__("active_while_menu", bar.window_active), w.file_menu.close()))
    bar.file_item.click()
    pump(0.4)
    res["menu_changes"] = changes[n0:]
    # Help, the Analysis window, a dialog: the main window becomes inactive; back to it: active
    hw = w.show_help("home"); pump(0.8)
    res["states"].append(sample("help active"))
    foreground_self(); res["states"].append(sample("back from help"))
    aw = w.open_analysis_window(); pump(0.8)
    res["states"].append(sample("analysis window active"))
    aw.close(); pump(0.8)
    res["after_analysis_close"] = bar.window_active
    foreground_self()
    from hea_calc.ui.widgets.dialogs import ChoiceDialog
    try:
        dlg = ChoiceDialog("Test", "Probe", "Body", [("ok", "OK")], w)
    except TypeError:
        dlg = None
    if dlg is not None:
        QTimer.singleShot(700, lambda: (res["states"].append(sample("dialog open")), dlg.reject()))
        dlg.exec()
        pump(0.6)
        res["after_dialog"] = bar.window_active
    # minimise / restore
    w.showMinimized(); pump(0.6)
    w.showNormal(); foreground_self()
    res["states"].append(sample("restored"))
    res["changes_total"] = len(changes)
    hw.close()
    print(json.dumps(res))
    w.close(); pump(0.3)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
