"""After-fix captures for the fix-needed acceptance matrix (``design/fix needed`` → ``design/screens/fix-needed-after``).

    .venv/Scripts/python.exe tools/fix_needed_captures.py [--theme light|dark] [--only name,...] [--scale 1.25]

Every capture is a render of the running application (offscreen platform; real widgets, real engine results).
Popups are composited onto the window grab at their real screen position, so an open menu is seen with its
trigger, as in the reference screenshots.  Captures are review artefacts, git-ignored.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "design" / "screens" / "fix-needed-after"


def main():
    sys.path.insert(0, str(ROOT))
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="light")
    ap.add_argument("--only", default="")
    ap.add_argument("--scale", default="1")
    args = ap.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if args.scale != "1":
        os.environ["QT_SCALE_FACTOR"] = args.scale
    from PySide6.QtCore import QPoint, QRect, QSettings
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from hea_calc.ui.theme import THEME, load_fonts
    from hea_calc.ui.widgets.tooltip import install_tooltips
    load_fonts()
    install_tooltips(app)
    THEME.set_theme(args.theme)
    from hea_calc.core.analysis import state as S
    from hea_calc.ui.main_window import MainWindow

    out = OUT / f"{args.theme}{'' if args.scale == '1' else '@' + args.scale}"
    out.mkdir(parents=True, exist_ok=True)
    only = {x for x in args.only.split(",") if x}
    settings = QSettings(str(Path(tempfile.mkdtemp()) / "fix.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings)
    win.resize(1920, 1032)
    win.show()

    def pump(n=6):
        for _ in range(n):
            app.processEvents()

    def settle():
        for _ in range(8):
            win.analysis_ctl.wait_idle(50)
            pump()

    def want(name):
        return not only or name in only

    def composite(popups, rect: QRect | None = None, name: str = ""):
        """Window grab with popups painted at their real positions, cropped to ``rect`` (window coords)."""
        pm = win.grab()
        p = QPainter(pm)
        origin = win.mapToGlobal(QPoint(0, 0))
        for pop in popups:
            p.drawPixmap(pop.pos() - origin, pop.grab())
        p.end()
        if rect is not None:
            pm = pm.copy(rect)
        pm.save(str(out / f"{name}.png"))
        print(name, pm.width(), pm.height())

    def place_list(pop, trigger):
        """Undo the offscreen (800 x 600) screen clamping: the list opens under its trigger."""
        from hea_calc.ui.widgets.listbox import SHADOW as LS
        pop.move(trigger.mapToGlobal(QPoint(-LS, trigger.height() - LS)))
        pump()

    def click(*els):
        for el in els:
            win.elements.table.tiles[el].click()
        pump()

    sys.path.insert(0, str(ROOT / "tests"))
    from conftest import settle_composition

    # results so the table, Export and the context menu have content
    for name, c in (("CrMnFeCoNiMoTi", {"Cr": 1, "Mn": 1, "Fe": 1, "Co": 1, "Ni": 1, "Mo": 1, "Ti": 1}),
                    ("(Fe1.6CoCr0.4Mn)0.9Al0.1", {"Fe": 0.36, "Co": 0.225, "Cr": 0.09, "Mn": 0.225, "Al": 0.1}),
                    ("FeCoNi(AlCu)0.2", {"Fe": 1, "Co": 1, "Ni": 1, "Al": 0.1, "Cu": 0.1}),
                    ("AlCoCuFeNiSi", {"Al": 1, "Co": 1, "Cu": 1, "Fe": 1, "Ni": 1, "Si": 1})):
        win.calculate("single", [name], [c], [{}])
        pump()
    settle()

    # ---------------------------------------------------------------- 12 File menu
    if want("file_menu"):
        item = win.header.file_item
        item._set_open(True)
        m = win.file_menu
        m.trigger_width = 0
        m.open_below(item, exec_=False)
        m.move(m.target_below(item))          # offscreen screens are 800 x 600: undo Qt's screen clamping
        pump()
        composite([m], QRect(0, 0, 640, 420), "file_menu_open")
        m.close()
        item._set_open(False)
        pump()
        composite([], QRect(0, 0, 640, 60), "file_menu_closed")

    # ---------------------------------------------------------------- 13 Theme menu (three preferences)
    if want("theme_menu"):
        for pref in ("light", "dark", "system"):
            win.prefs.set_theme(pref)
            win._sync_theme_actions()
            b = win.header.theme_btn
            b.active = True
            m = win.theme_menu
            m.trigger_width = 0
            m.open_below(b, exec_=False, align_right=True)
            m.move(m.target_below(b, True))
            pump()
            composite([m], QRect(win.width() - 420, 0, 420, 260), f"theme_menu_{pref}_open")
            m.close()
            b.active = False
            pump()
        win.prefs.set_theme(args.theme)
        win._sync_theme_actions()

    # ---------------------------------------------------------------- 11 Export MenuButton
    if want("export"):
        b = win.table.export_btn
        b.open = True
        m = b.menu()
        m.trigger_width = b.width()
        m.open_below(b, exec_=False, align_right=True)
        m.move(m.target_below(b, True))
        pump()
        g = b.mapTo(win, QPoint(0, 0))
        composite([m], QRect(g.x() - 300, g.y() - 60, 440, 260), "export_open")
        m.close()
        b.open = False
        pump()
        composite([], QRect(g.x() - 300, g.y() - 20, 440, 80), "export_closed")

    # ---------------------------------------------------------------- 20 results context menu
    if want("context"):
        tbl = win.table.view
        row = win.table.model.row_at(0)
        menu = tbl.row_menu(row, win.table.model.keys[1])
        vp = tbl.viewport()
        at = vp.mapToGlobal(QPoint(380, tbl.rowViewportPosition(0) + 20))
        menu._fit_width()
        from hea_calc.ui.widgets.menu import SHADOW
        menu.popup(at - QPoint(SHADOW, SHADOW))
        pump()
        g = vp.mapTo(win, QPoint(0, 0))
        composite([menu], QRect(g.x(), g.y() - 48, 900, 360), "context_menu")
        menu.close()

    # ---------------------------------------------------------------- notifications
    if want("notification"):
        n = win.notification
        for kind, title, body in (("info", "Title", "Message"), ("success", "Title", "Message"),
                                  ("warning", "Title", "Message"), ("error", "Title", "Message")):
            n.show_message(kind, title, body)
            pump()
            n.grab().save(str(out / f"notification_{kind}.png"))
        n.dismiss()
        pump()

    # ---------------------------------------------------------------- 15 Range basis, 14 System size
    comp = win.composition
    if want("range_basis") or want("system_size"):
        comp.set_mode(1)
        pump()
        click("Cr", "Mn", "Fe", "Co", "Ni")
        settle_composition(win, app)
        pump()
        g = comp.mapTo(win, QPoint(0, 0))
        if want("range_basis"):
            comp.unit_box.open_menu()
            place_list(comp.unit_box.popup, comp.unit_box)
            composite([comp.unit_box.popup], QRect(g.x(), g.y(), comp.width(), 260), "range_basis_open")
            comp.unit_box.popup.close()
            pump()
            composite([], QRect(g.x(), g.y(), comp.width(), 120), "range_basis_closed")
        if want("system_size"):
            ss = comp.sweep.size_select if hasattr(comp.sweep, "size_select") else None
            from hea_calc.ui.widgets.composition_panel import SystemSizeSelect
            ss = ss or comp.sweep.findChildren(SystemSizeSelect)[0]
            ss.open_menu()
            place_list(ss.popup, ss)
            composite([ss.popup], QRect(g.x(), g.y() + 260, comp.width(), 360), "system_size_open")
            ss.popup.close()
            pump()

    # ---------------------------------------------------------------- 3 long axis dropdown
    if want("long_dropdown"):
        from hea_calc.ui.widgets.dropdown import Dropdown
        win.analysis_ctl.apply(S.switch_context, S.COLLECTION)
        settle()
        win.analysis_ctl.apply(S.set_tab, "plots")
        settle()
        dds = [d for d in win.analysis.findChildren(Dropdown) if d.isVisible() and d.count() > 20]
        if dds:
            d = dds[0]
            d.open_menu()
            pump()
            composite([d.popup], None, "long_dropdown_open")
            d.popup.close()
        win.analysis_ctl.apply(S.switch_context, S.COMPOSITION)
        settle()

    sample_run = []

    def collection(tab):
        """The canonical C1 composition space (341 results) as the collection, on ``tab``."""
        from hea_calc.core.analysis import samples
        c = win.analysis_ctl
        if not sample_run:
            sample_run.append(samples.store_recipe(win.repo, win.engine, samples.c1_recipe()))
            win.table.model.refresh_committed()
            c.run_finished(sample_run[0])
            pump()
        c.apply(S.switch_context, S.COLLECTION)
        settle()
        c.scope_for(sample_run[0], "full")
        settle()
        c.apply(S.set_tab, tab)
        settle()
        return c

    # ---------------------------------------------------------------- 1 expanded Overview (no filler, top-aligned)
    if want("overview"):
        c = collection("overview")
        win.set_expanded(True)
        settle()
        composite([], None, "overview_workspace")
        win.set_expanded(False)
        c.apply(S.switch_context, S.COMPOSITION)
        settle()

    # ---------------------------------------------------------------- 6 expanded Model details: list + MSE-A citation
    if want("model_details"):
        c = win.analysis_ctl
        rid = win.table.model.page_rows()[0].id
        c.set_active(rid, by="table")
        c.apply(S.switch_context, S.COMPOSITION)
        c.apply(S.set_tab, "model_details")
        c.apply(S.select_model, "M1")
        win.set_expanded(True)
        settle()
        composite([], None, "model_details_workspace")
        win.set_expanded(False)
        settle()

    # ---------------------------------------------------------------- 4 expanded Statistics: one chart + outliers
    if want("statistics"):
        c = collection("statistics")
        win.set_expanded(True)
        c.apply(S.update, stats_focus="omega", stats_view="histogram")
        settle()
        composite([], None, "statistics_histogram")
        c.apply(S.update, stats_view="groups")
        settle()
        composite([], None, "statistics_groups")
        c.apply(S.update, stats_view="histogram")
        win.set_expanded(False)
        c.apply(S.switch_context, S.COMPOSITION)
        settle()

    # ---------------------------------------------------------------- 2 expanded Plots: thresholds, tooltip, inspector
    if want("plots"):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        c = collection("plots")
        settle()
        c.apply(S.set_plot, c.state.plot.with_(type="scatter", x="dhmix", y="delta", color="model:M2"))
        settle()
        win.analysis.expand_btn.click()
        settle()
        plot = win.workspace.collection.plot
        plot.grab()
        sx, sy, idx = sorted(plot._screen, key=lambda s: s[0])[len(plot._screen) * 2 // 3]
        c.apply(S.select_points, [plot.spec.data["ids"][idx]])
        settle()
        plot = win.workspace.collection.plot
        plot.grab()
        # hover a different point than the selected one, from the settled geometry
        sx, sy, _i = sorted(plot._screen, key=lambda s: s[0])[len(plot._screen) // 3]
        e = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(sx, sy), plot.mapToGlobal(QPointF(sx, sy)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(plot, e)
        pump()
        composite([], None, "plots_workspace")
        win.set_expanded(False)
        c.apply(S.switch_context, S.COMPOSITION)
        settle()

    # ---------------------------------------------------------------- 17 Composition expression states
    if want("expression"):
        from hea_calc.ui.widgets.composition_panel import CompositionPanel  # noqa: F401
        comp.set_mode(2)
        pump()
        e = comp.expr

        def wait_count():
            t0 = time.perf_counter()
            while e._counter.busy and time.perf_counter() - t0 < 30:
                app.processEvents()
                time.sleep(0.005)
            pump()

        g = comp.mapTo(win, QPoint(0, 0))
        crop = QRect(g.x(), g.y(), comp.width(), comp.height())
        nl = "\n"
        states = (
            ("expression_draft", nl.join(["(Co30Fe45Ni25)1-x(Al40Si60)x", "0 <= x <= 1, step=0.05"]), False, None),
            ("expression_fixed_parsed", "(Fe1.6CoCr0.4Mn)0.9Al0.1", True, None),
            ("expression_parametric_parsed", nl.join(["(FeCoNi)1-x-y-z(AlTi)xCryCuz",
                                                      "0 <= x <= 0.2, step=0.1, p=0.10",
                                                      "0 <= y <= 0.2, step=0.1, p=0.10",
                                                      "0 <= z <= 0.10, step=0.05, p=0.05"]), True, None),
            ("expression_batch_parsed", nl.join(["FeCoNi(AlCu)0.2", "", "(Fe1.6CoCr0.4Mn)0.9Al0.1", "",
                                                 "(Co30Fe45Ni25)1-x(Al40Si60)x", "0 <= x <= 1, step=0.05", "",
                                                 "(Co30Fe45Ni25)1-x(Al40Si60)x", "0 <= x <= 1, points=101"]),
             True, None),
            ("expression_stale", "(Fe1.6CoCr0.4Mn)0.9Al0.1", True, "(Fe1.6CoCr0.4Mn)0.9Al0.2"),
            ("expression_error", nl.join(["FeCoXxNi", "", "(FeCoNi", "", "(Co30Fe45Ni25)1-x(Al40Si60)x",
                                          "0 <= x <= 1, step=0.05, points=21"]), True, None),
        )
        for name, text, do_parse, edit_after in states:
            e.edit.setPlainText(text)
            pump()
            if do_parse:
                e.parse()
                wait_count()
            if edit_after:
                e.edit.setPlainText(edit_after)
                pump()
            e.scroll.verticalScrollBar().setValue(0)
            pump()
            composite([], crop, name)

    win.close()


if __name__ == "__main__":
    main()
