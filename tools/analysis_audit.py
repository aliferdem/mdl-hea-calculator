"""Analysis layout audit: nothing may be clipped, overflow its container or become unreachable.

    .venv/Scripts/python.exe tools/analysis_audit.py [--scale 1.25] [--theme light] [--json out.json]

Renders every Analysis page - Composition (Overview, Descriptors, Models, Model details) and Collection
(Overview, Plots, Statistics, Models) - at the embedded preferred size (805 × 465), the embedded minimum
(454 × 465, a second AnalysisPanel on the same controller) and in the expanded workspace (whole content area
of a 1920 × 1000 window), at the given device pixel ratio (``QT_SCALE_FACTOR``, offscreen), and checks:

* **clipped text** - a visible single-line QLabel whose text needs more width than it has (word-wrapped
  labels and elided-by-design labels excepted);
* **overflow** - a visible widget extending beyond the visible area of its page that is *not* inside a scroll
  area (content inside a scroll area is reachable by scrolling and is allowed);
* **tables** - a DataTable narrower than its minimum (header + content) width.

Captures go to ``design/screens/audit/<theme>_<scale>/``; findings to stdout (and JSON with ``--json``).  The
exit code is the number of findings (0 = clean).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "design" / "screens" / "audit"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--json", default="")
    ap.add_argument("--no-capture", action="store_true")
    args = ap.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if args.scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    from PySide6.QtCore import QPoint, QRect, QSettings
    from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QLabel, QWidget
    app = QApplication(sys.argv)
    from hea_calc.ui.theme import THEME, load_fonts
    from hea_calc.ui.widgets.tooltip import install_tooltips
    load_fonts()
    install_tooltips(app)
    THEME.set_theme(args.theme)
    from hea_calc.core.analysis import samples
    from hea_calc.core.analysis import state as S
    from hea_calc.core.composition import alloy_name
    from hea_calc.ui.analysis.panel import AnalysisPanel
    from hea_calc.ui.analysis.widgets import DataTable
    from hea_calc.ui.main_window import MainWindow

    out_dir = OUT / f"{args.theme}_{args.scale:g}"
    out_dir.mkdir(parents=True, exist_ok=True)
    findings: list[dict] = []
    notes: list[dict] = []           # informational (sideways scrolling at the 454 px minimum)

    def pump(n=4):
        for _ in range(n):
            app.processEvents()

    def settle(w):
        for _ in range(8):
            w.analysis_ctl.wait_idle(20)
            pump()

    def in_scroll_area(wd: QWidget, page: QWidget) -> bool:
        p = wd.parentWidget()
        while p is not None and p is not page:
            if isinstance(p, QAbstractScrollArea) or isinstance(p.parentWidget(), QAbstractScrollArea):
                return True
            p = p.parentWidget()
        return False

    def audit(page: QWidget, frame: str) -> None:
        page_rect = QRect(QPoint(0, 0), page.size())
        # nothing should need sideways scrolling at 805 px or in the workspace; at the 454 px minimum the
        # horizontal bar is the accepted last resort (content reachable, never clipped) and is only reported
        for sa in page.findChildren(QAbstractScrollArea):
            hb = sa.horizontalScrollBar()
            if sa.isVisibleTo(page) and hb.maximum() > 0 and sa.objectName() != "ContentScroll":
                entry = {"frame": frame, "kind": "horizontal scroll", "range": hb.maximum(),
                         "viewport": sa.viewport().width()}
                (notes if frame.endswith("_454") else findings).append(entry)
        for wd in page.findChildren(QWidget):
            if not wd.isVisibleTo(page) or wd.width() <= 0 or wd.height() <= 0:
                continue
            if QWidget.window(wd) is not QWidget.window(page):
                continue
            if isinstance(wd, QLabel) and not wd.wordWrap() and wd.text() and not wd.property("elide_ok"):
                need = wd.sizeHint().width()
                if need > wd.width() + 1:
                    findings.append({"frame": frame, "kind": "clipped label", "widget": wd.objectName() or "QLabel",
                                     "text": wd.text()[:80], "need": need, "have": wd.width()})
            if isinstance(wd, DataTable) and wd.width() + 1 < wd.minimumWidth():
                findings.append({"frame": frame, "kind": "table narrower than its content",
                                 "need": wd.minimumWidth(), "have": wd.width(),
                                 "headers": [c[0] for c in wd.columns][:6]})
            # overlapping visible siblings (e.g. a header row that no longer fits)
            par = wd.parentWidget()
            if par is not None and par.layout() is not None:
                mine = wd.geometry()
                for sib in par.children():
                    if sib is wd or not isinstance(sib, QWidget) or not sib.isVisibleTo(page) \
                            or QWidget.window(sib) is not QWidget.window(page) or sib.isWindow():
                        continue
                    if id(sib) < id(wd):
                        continue                       # each pair once
                    inter = mine.intersected(sib.geometry())
                    if inter.width() > 2 and inter.height() > 2 and par.layout().indexOf(sib) >= 0 \
                            and par.layout().indexOf(wd) >= 0:
                        findings.append({"frame": frame, "kind": "overlap", "a": type(wd).__name__,
                                         "b": type(sib).__name__, "rect": [inter.x(), inter.y(), inter.width(),
                                                                          inter.height()]})
            if in_scroll_area(wd, page):
                continue
            tl = wd.mapTo(page, QPoint(0, 0))
            r = QRect(tl, wd.size())
            if not page_rect.contains(r.adjusted(1, 1, -1, -1)):
                findings.append({"frame": frame, "kind": "overflow", "widget": type(wd).__name__,
                                 "name": wd.objectName(), "rect": [r.x(), r.y(), r.width(), r.height()],
                                 "page": [page_rect.width(), page_rect.height()]})

    def capture(widget: QWidget, name: str) -> None:
        if not args.no_capture:
            widget.grab().save(str(out_dir / f"{name}.png"))

    st = QSettings(str(Path(tempfile.mkdtemp()) / "audit.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=st)
    w.resize(1920, 1000)
    w.show()
    pump()
    c = w.analysis_ctl
    # data: one single composition (active) and a composition-space run (collection)
    w.calculate("single", [alloy_name(samples.S1)], [samples.S1], [{}])
    run = samples.store_recipe(w.repo, w.engine, samples.c1_recipe())
    w.table.model.refresh_committed()
    c.run_finished(run)
    w._check_details()
    settle(w)
    small = AnalysisPanel(c)
    small.setStyleSheet(w.styleSheet())             # the window-scoped sheet (fonts, colours) as embedded
    small.set_has_results(True)
    small.resize(454, 465)
    small.show()
    pump()
    surfaces = (("805", w.analysis), ("454", small))
    for ctx, tabs in ((S.COMPOSITION, S.COMP_TABS), (S.COLLECTION, S.COLL_TABS)):
        c.apply(S.switch_context, ctx)
        settle(w)
        if ctx == S.COLLECTION:
            c.scope_for(run, "full")
            settle(w)
        for tab in tabs:
            c.apply(S.set_tab, tab)
            if ctx == S.COLLECTION and tab == "statistics":
                c.apply(S.update, stats_focus="delta_cn12")
            settle(w)
            for size, panel in surfaces:
                frame = f"{ctx}_{tab}_{size}"
                audit(panel, frame)
                capture(panel, frame)
            w.set_expanded(True)
            settle(w)
            frame = f"{ctx}_{tab}_expanded"
            audit(w.workspace, frame)
            capture(w.window(), frame)
            w.set_expanded(False)
            settle(w)
    for f in findings:
        print(json.dumps(f, ensure_ascii=False))
    for n in notes:
        print("note:", json.dumps(n, ensure_ascii=False))
    print(f"{len(findings)} finding(s), {len(notes)} note(s) at scale {args.scale:g}, theme {args.theme}")
    if args.json:
        Path(args.json).write_text(json.dumps({"findings": findings, "notes": notes}, indent=1, ensure_ascii=False),
                                   encoding="utf-8")
    small.close()
    w.close()
    return len(findings)


if __name__ == "__main__":
    sys.exit(min(main(), 255))
