"""Capture the real application screenshots used by the Help pages (``hea_calc/docs/images/``).

    .venv/Scripts/python.exe tools/help_screenshots.py [--theme dark|light]

Every image is a grab of the running application (offscreen platform, DPR 1, the authoritative dark theme by
default) after driving it through its own controls and calculation path - no mock-ups.  Re-run after a UI change;
the Help text references the images by file name only, so they can be replaced independently.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "hea_calc" / "docs" / "images"


def main():
    sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from hea_calc.ui.theme import THEME, load_fonts
    load_fonts()
    THEME.set_theme(args.theme)
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.main_window import MainWindow

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(Path(tempfile.mkdtemp()) / "help_shots.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings)
    win.resize(1920, 1032)
    win.show()

    def pump(n=4):
        for _ in range(n):
            app.processEvents()

    def settle():
        for _ in range(8):
            win.analysis_ctl.wait_idle(50)
            pump()

    def wait_run(timeout=120.0):
        t0 = time.perf_counter()
        while (win.runner.running or win.table.model.total_count() == 0) and time.perf_counter() - t0 < timeout:
            app.processEvents()
            time.sleep(0.01)
        settle()

    def save(widget, name, width=None):
        pm = widget.grab()
        if width and pm.width() > width:
            pm = pm.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        pm.save(str(out / name))
        print(name, pm.width(), pm.height())

    def click(*els):
        for el in els:
            win.elements.table.tiles[el].click()
        pump()

    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import settle_composition

    comp = win.composition
    # --- Single composition: CoCrFeMnNi -------------------------------------------------------------
    click("Co", "Cr", "Fe", "Mn", "Ni")
    win.elements._preview("Fe")
    pump()
    save(win.elements, "element-selection.png")
    save(comp, "single-composition.png")
    comp.calculate()
    wait_run()
    win.analysis_ctl.apply(S.set_tab, "overview")
    settle()
    save(win.details, "analysis-composition.png")
    save(win, "main-window.png", width=1520)

    # a few more rows so the results table shows disagreeing models
    for name, c in (("AlCoCrFeNi", {"Al": 1, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}),
                    ("CoCrFeNiSi0.5", {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "Si": 0.5}),
                    ("Al0.5CoCrFeNi", {"Al": 0.5, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1})):
        win.calculate("single", [name], [c], [{}])
        pump()
    settle()
    table = win.table
    save(table, "results-table.png", width=1520)

    # --- Composition space: Al optional in CoCrFeNi -------------------------------------------------
    comp.clear()
    pump()
    comp.set_mode(1)
    pump()
    click("Co", "Cr", "Fe", "Ni", "Al")
    sw = comp.sweep
    row = sw.rows["Al"]
    if row.lock.isChecked():
        row.lock.click()                                   # Lock off: Al is optional
    row.set_values(("0.1", "0.5", "0.1"))
    for f in (row.min, row.max, row.step):
        f.editingFinished.emit()
    pump()
    settle_composition(win, app)
    pump()
    save(comp, "composition-space.png")
    before = win.table.model.total_count()
    comp.calculate()
    t0 = time.perf_counter()
    while (win.runner.running or win.table.model.total_count() < before + 6) and time.perf_counter() - t0 < 120:
        app.processEvents()
        time.sleep(0.01)
    settle()
    run = win.repo.runs()[-1].run_id
    c = win.analysis_ctl
    c.apply(S.switch_context, S.COLLECTION)
    settle()
    c.scope_for(run, "full")
    settle()
    c.apply(S.set_tab, "plots")
    settle()
    save(win.details, "analysis-collection.png")
    c.apply(S.set_tab, "statistics")
    settle()
    save(win.details, "analysis-statistics.png")
    c.apply(S.switch_context, S.COMPOSITION)
    settle()

    # --- Composition expression: AlxCoCrFeNi --------------------------------------------------------
    comp.clear()
    pump()
    comp.set_mode(2)
    pump()
    comp.expr.edit.setPlainText("AlxCoCrFeNi")
    settle_composition(win, app)
    pump()
    save(comp, "composition-expression.png")

    win.close()


if __name__ == "__main__":
    main()
