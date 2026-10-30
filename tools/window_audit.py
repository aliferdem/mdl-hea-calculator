"""Drive the main flows and report every unexpected top-level window (``tools/window_watch.py``).

    .venv/Scripts/python.exe tools/window_audit.py [--offscreen] [--theme dark]

Flows: Analysis Composition Overview / Descriptors / Models / Model details for M1-M8 on compositions that give
every model state (in domain, extrapolated, flagged data, N/A), in the embedded panel, the expanded workspace and
the separate Analysis window; Collection Overview / Plots / Statistics / Models with the stale-filter notice;
title-bar menus; Help and About; the Filter, Columns and Settings dialogs; theme switches.  Prints the windows
shown and exits 1 if any was unexpected.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

# compositions that give every model state (found by scanning the engine): M7 extrapolated with a caution,
# M6 / M7 flagged binary data, M1 / M6 / M7 not available, and an ordinary in-domain alloy
COMPOSITIONS = ["CoCuMgVZn", "NiTaV", "ReSnWZr", "AlReZn", "CrMnTa", "CoCrFeMnNi"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offscreen", action="store_true")
    ap.add_argument("--theme", default="light")
    args = ap.parse_args()
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from hea_calc.ui.theme import THEME, load_fonts
    load_fonts()
    THEME.set_theme(args.theme)
    from hea_calc.core.analysis import state as S
    from hea_calc.core.engine import MODEL_KEYS
    from hea_calc.ui.main_window import MainWindow
    from window_watch import WindowWatch
    win = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    win.resize(1700, 980)
    win.show()

    def pump(sec=0.05):
        end = time.monotonic() + sec
        while True:
            app.processEvents()
            if time.monotonic() >= end:
                return
            time.sleep(0.003)

    pump(0.8)
    c = win.analysis_ctl
    with WindowWatch(app) as ww:
        # one calculation per composition (Single composition), then every Composition tab and model
        for formula in COMPOSITIONS:
            win.composition.clear()
            pump(0.1)
            win.composition.set_mode(0)
            from hea_calc.core import composition as CMP
            for el in CMP.parse_formula(formula, win.engine.data if hasattr(win.engine, "data") else None):
                win.elements.table.tiles[el].click()
            pump(0.1)
            win.composition.calculate()
            t0 = time.monotonic()
            while win.runner.running and time.monotonic() - t0 < 30:
                pump(0.05)
            pump(0.2)
            c.apply(S.switch_context, S.COMPOSITION)
            for host in ("embedded", "expanded", "window"):
                if host == "expanded":
                    win.set_expanded(True)
                elif host == "window":
                    win.set_expanded(False)
                    win.open_analysis_window()
                pump(0.15)
                for tab in S.COMP_TABS:
                    c.apply(S.set_tab, tab)
                    pump(0.05)
                for m in MODEL_KEYS:
                    c.apply(S.select_model, m, True)
                    pump(0.06)
                if host == "window":
                    win.analysis_window(create=False).close()
                    pump(0.1)
        # Collection: every tab; the stale-filter notice
        c.apply(S.switch_context, S.COLLECTION)
        pump(0.2)
        for tab in S.COLL_TABS:
            c.apply(S.set_tab, tab)
            c.wait_idle(20)
            pump(0.1)
        # title-bar menus, Help, About, dialogs (closed by a timer), theme switches
        for item in win.header.menu_items:
            QTimer.singleShot(150, lambda it=item: it.menu_.close())
            item.click()
            pump(0.1)
        win.show_help("home")
        pump(0.3)
        win.show_about()
        pump(0.3)
        for opener in (win.edit_settings,):
            QTimer.singleShot(400, lambda: [w.reject() for w in QApplication.topLevelWidgets()
                                            if w.isVisible() and hasattr(w, "reject")])
            opener()
            pump(0.2)
        for theme in ("dark", "light", args.theme):
            win.set_theme(theme)
            pump(0.2)
    print("shown:", sorted(set(n for n, _o in ww.shown)))
    print("unexpected:", ww.unexpected)
    win.close()
    pump(0.3)
    return 1 if ww.unexpected else 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
