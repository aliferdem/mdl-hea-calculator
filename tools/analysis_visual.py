"""Analysis visual regression against the approved mock-ups, at device pixel ratio 1.0 / 1.25 / 1.5.

    .venv/Scripts/python.exe tools/analysis_visual.py            # all scales -> JSON + comparison images

Each scale runs in its own process (offscreen platform, ``QT_SCALE_FACTOR`` = scale, as tools/dpi_harness.py),
builds the canonical states of ``docs/analysis-redesign/images`` from real engine results (S1-S4, C1, E1, E2),
captures the Analysis panel (805 x 465, and pinned to 454 x 465 logical for the S size class) or the window (expanded workspace) and checks
what a design review checks - not font rasters:

* geometry: panel size, header / context bar / tab row / content boundaries, size class;
* hierarchy and state: the selected context segment and tab, empty / stale / representation states;
* major colours: panel ``layer-01``, header-row, selected-tab underline ``border-interactive``, scientific tag
  colours present where the mock-up shows them;
* crisp strokes: the selected switcher frame is ``floor(dpr)`` device pixels on every side.

Side-by-side images (mock-up | application) are written to ``design/screens/analysis/<scale>/`` and the
check results to ``design/implementation/analysis_visual.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MOCKS = ROOT / "docs" / "analysis-redesign" / "images"
OUT = ROOT / "design" / "screens" / "analysis"
JSON_OUT = ROOT / "design" / "implementation" / "analysis_visual.json"
SCALES = (1.0, 1.25, 1.5)


# ====================================================================== child
def child(scale: float, theme: str) -> dict:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = str(scale)
    from PySide6.QtCore import QPoint, QSettings
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from hea_calc.ui.theme import DARK, LIGHT, THEME, load_fonts
    from hea_calc.ui.widgets.tooltip import install_tooltips
    load_fonts()
    install_tooltips(app)
    THEME.set_theme(theme)
    tok = DARK if theme == "dark" else LIGHT
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    from hea_calc.core.composition import alloy_name
    from hea_calc.core.results import ModelFilter
    from hea_calc.ui.main_window import MainWindow
    out_dir = OUT / f"{theme}_{scale:g}"
    out_dir.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = []

    def pump(n=4):
        for _ in range(n):
            app.processEvents()

    def make(size):
        st = QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)
        w = MainWindow(settings=st)
        w.resize(*size)
        w.show()
        pump()
        return w

    def settle(w):
        for _ in range(6):
            w.analysis_ctl.wait_idle(20)
            pump()

    def check(frame, name, ok, detail=""):
        checks.append({"frame": frame, "check": name, "ok": bool(ok), "detail": str(detail)})

    def color_at(img: QImage, x: float, y: float, dpr: float) -> str:
        return img.pixelColor(int(x * dpr), int(y * dpr)).name()

    def count_color(img: QImage, color: str, rect=None) -> int:
        target = QColor(color).rgb()
        x0, y0, x1, y1 = rect or (0, 0, img.width(), img.height())
        n = 0
        for y in range(y0, min(y1, img.height()), 2):
            for x in range(x0, min(x1, img.width()), 2):
                if img.pixel(x, y) == target:
                    n += 1
        return n

    def side_by_side(frame, app_img: QImage, mock_name: str | None):
        dpr = app_img.devicePixelRatio()
        logical = (app_img.width() / dpr, app_img.height() / dpr)
        canvas_w = int(logical[0] * 2 + 24)
        canvas = QImage(canvas_w, int(logical[1]), QImage.Format.Format_RGB32)
        canvas.fill(QColor("#000000"))
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if mock_name and (MOCKS / mock_name).exists():
            mock = QImage(str(MOCKS / mock_name))
            if mock.width() >= 1900 and mock.height() > logical[1]:      # workspace mock: drop the 32 px title bar
                mock = mock.copy(0, 32, mock.width(), mock.height() - 32)
            from PySide6.QtCore import QRectF
            p.drawImage(QRectF(0, 0, logical[0], logical[1]), mock)
        from PySide6.QtCore import QRectF
        p.drawImage(QRectF(logical[0] + 24, 0, logical[0], logical[1]), app_img)
        p.end()
        canvas.save(str(out_dir / f"{frame}.png"))

    def grab_panel(w):
        pm = w.analysis.grab()
        return pm.toImage()

    def panel_checks(frame, w, size_cls, ctx_h=40):
        p = w.analysis
        img = grab_panel(w)
        dpr = img.devicePixelRatio()
        check(frame, "panel size", (p.width(), p.height()) in ((805, 465), (454, 465)), (p.width(), p.height()))
        check(frame, "size class", p.size_class == size_cls, p.size_class)
        y_tabs = p.tab_stack.mapTo(p, QPoint(0, 0)).y()
        check(frame, "tab row at 56 + context bar", y_tabs == 56 + ctx_h, y_tabs)
        check(frame, "content below tabs", p.content_stack.mapTo(p, QPoint(0, 0)).y() == y_tabs + 32,
              p.content_stack.mapTo(p, QPoint(0, 0)).y())
        bg = color_at(img, 6, 6, dpr)
        check(frame, "panel background layer-01", bg == tok["layer-01"], bg)
        # selected tab underline (border-interactive) under the selected tab
        tabs = p.comp_tabs if w.analysis_ctl.state.context == "composition" else p.coll_tabs
        sel = tabs.buttons[tabs.index()]
        sx = sel.mapTo(p, QPoint(0, 0)).x() + sel.width() / 2
        under = color_at(img, sx, y_tabs + 31, dpr)
        want = tok["border-interactive"] if sel.isEnabled() else tok["border-disabled"]     # frame 1: tabs disabled
        check(frame, "selected tab underline", under == want, under)
        # crisp: selected switcher segment frame thickness on its left edge, in device px
        sw = p.switcher
        o = sw.mapTo(p, QPoint(0, 0))
        seg_x = o.x() + (0 if sw.index() == 0 else sw.segment)
        y_mid = int((o.y() + 16) * dpr)
        x = int(seg_x * dpr)
        n = 0
        expect = max(1, math.floor(dpr))
        target = QColor(tok["border-inverse"]).rgb()
        for dx in range(0, 6):
            if img.pixel(x + dx, y_mid) == target:
                n += 1
        check(frame, "switcher frame crisp (device px)", n == expect, f"{n} vs {expect}")
        return img

    results = {}
    # ---------------------------------------------------------------- embedded 805 (1920 x 1000)
    w = make((1920, 1000))
    try:
        c = w.analysis_ctl
        img = panel_checks("01_empty", w, "M")
        check("01_empty", "expand disabled", not w.analysis.expand_btn.isEnabled())
        side_by_side("01_empty", img, "01_analysis_empty_805.png")
        w.calculate("single", [alloy_name(samples.S1)], [samples.S1], [{}])
        pump()
        for tab, frame, mock in (("overview", "02_overview", "02_composition_overview_805.png"),
                                 ("descriptors", "03_descriptors", "03_composition_descriptors_805.png"),
                                 ("models", "04_models", "04_composition_models_805.png")):
            c.apply(S.set_tab, tab)
            pump()
            img = panel_checks(frame, w, "M")
            if tab == "models":
                n = count_color(img, "#0e6027" if theme == "dark" else "#a7f0ba")
                check(frame, "SS tags drawn (8)", n > 100, n)
            side_by_side(frame, img, mock)
        c.apply(S.set_tab, "model_details")
        c.apply(S.select_model, "M6")
        pump()
        side_by_side("05_model_details", panel_checks("05_model_details", w, "M"), "05_composition_model_details_805.png")
        for comp, frame, mock in ((samples.S2, "04b_partial", "04b_composition_models_partial_805.png"),
                                  (samples.S3, "04c_flagged", "04c_composition_models_flagged_805.png"),
                                  (samples.S4, "04d_extrapolated", "04d_composition_models_extrapolated_805.png")):
            w.calculate("single", [alloy_name(comp)], [comp], [{}])
            c.apply(S.set_tab, "models")
            pump()
            img = panel_checks(frame, w, "M")
            if frame == "04c_flagged":
                n = count_color(img, tok["support-warning"])
                check(frame, "flagged-data icons drawn", n > 10, n)
            side_by_side(frame, img, mock)
        run = samples.store_recipe(w.repo, w.engine, samples.c1_recipe())
        w.table.model.refresh_committed()
        c.run_finished(run)
        w._check_details()
        c.apply(S.switch_context, S.COLLECTION)
        settle(w)
        c.scope_for(run, "full")
        settle(w)
        for tab, frame, mock in (("overview", "06_coll_overview", "06_collection_overview_805.png"),
                                 ("plots", "07_scatter", "07_collection_scatter_805.png"),
                                 ("statistics", "08_statistics", "08_collection_statistics_805.png"),
                                 ("models", "09_coll_models", "09_collection_models_805.png")):
            c.apply(S.set_tab, tab)
            settle(w)
            img = panel_checks(frame, w, "M")
            if tab == "plots":
                spec = w.analysis.collection.plot.spec
                check(frame, "representation tag", spec is not None and spec.tag == "All 341 points",
                      spec.tag if spec else None)
                n_ss = count_color(img, "#a7f0ba" if theme == "dark" else "#0e6027")
                check(frame, "SS points drawn", n_ss > 50, n_ss)
            side_by_side(frame, img, mock)
        m = w.table.model
        m.set_filters([ModelFilter("M8", {"SS"})])
        m.wait()
        c.apply(S.set_tab, "overview")
        c.scope_for(run, "filtered")
        settle(w)
        m.set_filters([])
        m.wait()
        c.table_filter_changed()
        settle(w)
        img = panel_checks("10_stale", w, "M")
        check("10_stale", "stale state", c.state.stale == "filter" and c.state.resolved.n == 12)
        side_by_side("10_stale", img, "10_collection_stale_scope_805.png")
        # ------------------------------------------------------------ workspace
        c.scope_for(run, "full")
        settle(w)
        w.set_expanded(True)
        settle(w)
        for ctx, tab, frame, mock in ((S.COLLECTION, "plots", "21_ws_scatter", "21_ws_collection_scatter_inspector.png"),
                                      (S.COLLECTION, "statistics", "22_ws_statistics", "22_ws_collection_statistics.png"),
                                      (S.COLLECTION, "models", "23_ws_models", "23_ws_collection_model_distribution.png"),
                                      (S.COMPOSITION, "overview", "18_ws_comp_overview", "18_ws_composition_overview.png"),
                                      (S.COMPOSITION, "model_details", "19_ws_model_details",
                                       "19_ws_composition_model_details.png")):
            c.apply(S.switch_context, ctx)
            c.apply(S.set_tab, tab)
            settle(w)
            img = w.grab().toImage()
            dpr = img.devicePixelRatio()
            back = w.workspace.back
            bx = back.mapTo(w, QPoint(0, 0))
            check(frame, "Back to calculation top-right", abs((bx.x() + back.width()) - (w.width() - 20)) <= 1,
                  bx.x() + back.width())
            check(frame, "workspace background", color_at(img, w.width() - 8, w.height() - 8, dpr) == tok["background"],
                  color_at(img, w.width() - 8, w.height() - 8, dpr))
            side_by_side(frame, img, mock)
        w.set_expanded(False)
        pump()
        check("back", "focus returns to Expand analysis", w.focusWidget() is w.analysis.expand_btn)
    finally:
        w.close()
        pump()
    # ---------------------------------------------------------------- embedded 454 (S size class)
    # Composition setup keeps its Figma width (457 px), so below 1920 px the main window stacks Analysis at full
    # width and never lays it out at 454 px; the S state is still a supported width (narrow host windows), so the
    # real panel of a real window is pinned to it here.
    w = make((1440, 1000))
    w.analysis.setFixedWidth(454)
    pump()
    try:
        c = w.analysis_ctl
        w.calculate("single", [alloy_name(samples.S1)], [samples.S1], [{}])
        pump()
        check("13_overview_454", "Analysis is 454 px wide", w.analysis.width() == 454, w.analysis.width())
        img = panel_checks("13_overview_454", w, "S", ctx_h=48)
        side_by_side("13_overview_454", img, "13_composition_overview_454.png")
        c.apply(S.set_tab, "models")
        pump()
        side_by_side("15_models_454", panel_checks("15_models_454", w, "S", ctx_h=48), "15_composition_models_454.png")
        run = samples.store_recipe(w.repo, w.engine, samples.c1_recipe())
        w.table.model.refresh_committed()
        c.run_finished(run)
        w._check_details()
        c.apply(S.switch_context, S.COLLECTION)
        settle(w)
        c.scope_for(run, "full")
        settle(w)
        for tab, frame, mock in (("overview", "16_coll_overview_454", "16_collection_overview_454.png"),
                                 ("plots", "17_plot_454", "17_collection_plot_454.png")):
            c.apply(S.set_tab, tab)
            settle(w)
            side_by_side(frame, panel_checks(frame, w, "S"), mock)
    finally:
        w.close()
        pump()
    # ---------------------------------------------------------------- expressions (workspace 24, 25)
    w = make((1920, 1000))
    try:
        c = w.analysis_ctl
        for recipe, frame, mock, expect in ((samples.e1_recipe(), "24_ws_line", "24_ws_expression_line_plot.png", "line"),
                                            (samples.e2_recipe(), "25_ws_heatmap", "25_ws_expression_heatmap.png",
                                             "heatmap")):
            run = samples.store_recipe(w.repo, w.engine, recipe)
            w.table.model.refresh_committed()
            c.run_finished(run)
            w._check_details()
            c.apply(S.switch_context, S.COLLECTION)
            settle(w)
            c.scope_for(run, "full")
            settle(w)
            c.apply(S.set_tab, "plots")
            w.set_expanded(True)
            settle(w)
            spec = w.workspace.collection.plot.spec if w.workspace.collection.plot else None
            check(frame, f"{expect} plot", spec is not None and spec.kind == expect, spec.kind if spec else None)
            side_by_side(frame, w.grab().toImage(), mock)
            w.set_expanded(False)
            pump()
    finally:
        w.close()
        pump()
    results["checks"] = checks
    results["passed"] = sum(1 for x in checks if x["ok"])
    results["failed"] = [x for x in checks if not x["ok"]]
    return results


# ====================================================================== parent
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", type=float)
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--scales", default="1.0,1.25,1.5")
    ap.add_argument("--themes", default="dark,light")
    args = ap.parse_args()
    if args.child is not None:
        res = child(args.child, args.theme)
        print("@@JSON@@" + json.dumps(res))
        return
    summary = {}
    ok = True
    for theme in args.themes.split(","):
        for s in (float(x) for x in args.scales.split(",")):
            proc = subprocess.run([sys.executable, __file__, "--child", str(s), "--theme", theme], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
                                  env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("@@JSON@@")), None)
            if line is None:
                summary[f"{theme}@{s:g}"] = {"error": proc.stderr[-3000:]}
                ok = False
                print(f"{theme} @ {s:g}: ERROR\n{proc.stderr[-1500:]}")
                continue
            res = json.loads(line[8:])
            summary[f"{theme}@{s:g}"] = res
            n_fail = len(res["failed"])
            ok &= n_fail == 0
            print(f"{theme} @ {s:g}: {res['passed']} passed, {n_fail} failed")
            for f in res["failed"]:
                print(f"   FAIL {f['frame']}: {f['check']} ({f['detail']})")
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
