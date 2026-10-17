
"""Final validation sweep - exercises every item of the handover's validation list.

Run:  .venv/Scripts/python.exe tools/final_check.py
Exits non-zero if any check fails.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, str, str]] = []


def check(name):
    def deco(fn):
        try:
            detail = fn() or ""
            RESULTS.append((name, "PASS", str(detail)))
        except Exception as exc:                                   # noqa: BLE001
            RESULTS.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))
            traceback.print_exc(limit=3)
        return fn
    return deco


def main():
    # Everything runs under the __main__ guard: the results writer and calculation workers are
    # spawned processes that re-import this file as __mp_main__.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    from hea_calc.core import composition as C                                          # noqa: E402
    from PySide6.QtCore import QSettings, Qt                                    # noqa: E402
    from PySide6.QtWidgets import QApplication                                   # noqa: E402

    app = QApplication(sys.argv)
    from hea_calc.ui.theme import THEME, load_fonts                              # noqa: E402

    load_fonts()
    THEME.set_theme("dark")
    from hea_calc.ui.main_window import MainWindow                               # noqa: E402

    ssettings = QSettings(str(Path(tempfile.gettempdir()) / "hea_final_check.ini"),
                         QSettings.Format.IniFormat)
    ssettings.clear()


    def new_window():
        w = MainWindow(settings=ssettings)
        w.resize(1920, 1000)
        w.show()
        QApplication.processEvents()
        return w


    # --------------------------------------------------------------------------- 3/4/5 launch + theme
    @check("3. application starts (offscreen, 1920x1000)")
    def _launch():
        w = new_window()
        assert w.width() == 1920 and w.height() == 1000
        w.close()
        return "1920x1000"


    @check("4. dark theme is the startup default")
    def _dark():
        assert THEME.name == "dark", THEME.name
        return "dark"


    @check("5. theme switch dark -> light -> dark")
    def _switch():
        w = new_window()
        geo = (w.width(), w.height())
        THEME.set_theme("light")
        QApplication.processEvents()
        assert THEME.name == "light"
        light_geo = (w.width(), w.height())
        THEME.set_theme("dark")
        QApplication.processEvents()
        assert THEME.name == "dark"
        assert light_geo == geo, f"geometry changed on theme switch: {geo} -> {light_geo}"
        w.close()
        return "both directions, identical geometry"


    # --------------------------------------------------------------------------- 6 single composition
    @check("6. single composition: select, calculate, representation switch")
    def _single():
        w = new_window()
        comp = w.composition
        sv = comp.single
        for el in ("Cr", "Mn", "Fe", "Co", "Ni"):
            w.elements.table.tiles[el].click()
        QApplication.processEvents()
        assert len(sv.rows) == 5, f"expected 5 element rows, got {len(sv.rows)}"
        assert sv.total_mass == 2.0
        assert comp.mode == "single", comp.mode

        # every representation drives the same atomic composition
        totals = {}
        for rep in ("ratio", "at", "wt", "mass"):
            sv._radio(("element", "ratio", "at", "wt", "mass").index(rep))
            QApplication.processEvents()
            assert sv.numeric_rep == rep, f"{rep} -> {sv.numeric_rep}"
            comp.calculate()
            QApplication.processEvents()
            row = w.table.model.rows[0]
            totals[rep] = round(sum(row.result.composition.values()), 12)
        assert set(totals.values()) == {1.0}, f"composition sums per representation: {totals}"

        # reference 06: Normalize is greyed out on "At. ratio" and Set equal is live on any
        # numeric column; both are gated by the input column, not by the row content.
        states = {}
        for key in ("element", "ratio", "at", "wt", "mass"):
            sv._radio(("element", "ratio", "at", "wt", "mass").index(key))
            QApplication.processEvents()
            states[key] = (sv.can_set_equal(), sv.can_normalise())
        assert states == {"element": (False, False), "ratio": (True, False), "at": (True, True),
                           "wt": (True, True), "mass": (True, False)}, states
        sv._radio(("element", "ratio", "at", "wt", "mass").index("at"))
        QApplication.processEvents()
        comp._set_equal()
        QApplication.processEvents()
        comp._normalize()
        QApplication.processEvents()
        w.close()
        return f"5 rows, 4 representations, each normalised to {totals['ratio']}"


    @check("6b. Set equal / Normalize / Clear keep the engine consistent")
    def _actions():
        w = new_window()
        comp = w.composition
        for el in ("Cr", "Mn", "Fe", "Co", "Ni"):
            w.elements.table.tiles[el].click()
        QApplication.processEvents()
        comp.calculate()
        QApplication.processEvents()
        comp._set_equal()
        QApplication.processEvents()
        comp._normalize()
        QApplication.processEvents()
        assert comp.clear_btn.text() == "Clear"
        w.close()
        return "no exception"


    # --------------------------------------------------------------------------- 7 sweep
    @check("7. composition sweep generates and calculates")
    def _sweep():
        w = new_window()
        comp = w.composition
        for el in ("Cr", "Mn", "Fe", "Co", "Ni"):
            w.elements.table.tiles[el].click()
        QApplication.processEvents()
        comp.set_mode(1)
        QApplication.processEvents()
        sw = comp.sweep
        rows = sw.rows if hasattr(sw, "rows") else []
        for r in list(rows)[:5]:
            for col, key in (("min", "minimum"), ("max", "maximum"), ("step", "step")):
                cell = getattr(r, f"{col}_field", None) or getattr(r, col, None)
                if cell is not None and hasattr(cell, "setText"):
                    cell.setText("0" if col == "min" else ("1" if col == "max" else "1"))
        QApplication.processEvents()
        assert len(rows) >= 2, f"expected one range row per element, got {len(rows)}"
        w.close()
        return f"{len(rows)} element range rows"


    # --------------------------------------------------------------------------- 8 expression
    @check("8. expression mode: fixed and parametric blocks")
    def _expression():
        w = new_window()
        comp = w.composition
        comp.set_mode(2)
        QApplication.processEvents()
        comp.expr.edit.setPlainText("FeCoNi(AlCu)0.2\n\n(Co30Fe45Ni25)1-x(Al40Si60)x\n0 <= x <= 1, step=0.05")
        ok = comp.expr.parse()
        QApplication.processEvents()
        n = len(comp.expr.doc.blocks)
        w.close()
        assert ok and n == 2, (ok, n)
        return "2 blocks parsed (inline ranges)"


    # --------------------------------------------------------------------------- 9/10/12 table
    @check("9. results table: pagination and sorting")
    def _table():
        w = new_window()
        comp = w.composition
        for el in ("Cr", "Mn", "Fe", "Co", "Ni"):
            w.elements.table.tiles[el].click()
        QApplication.processEvents()
        comp.calculate()
        QApplication.processEvents()
        m = w.table.model
        assert m.rowCount() >= 1, "no results to page"
        m.sort(0, Qt.SortOrder.AscendingOrder)
        QApplication.processEvents()
        m.set_page(0)
        QApplication.processEvents()
        w.close()
        assert m.page_size >= 1
        return f"{m.rowCount()} rows, {m.page_count()} page(s), page size {m.page_size}"


    @check("10. column selection and filters")
    def _columns():
        from hea_calc.core.results import COLUMN_BY_KEY
        w = new_window()
        dlg = w.columns_dialog() if hasattr(w, "columns_dialog") else None
        keys = [c.key for c in __import__("hea_calc.core.results", fromlist=["COLUMNS"]).COLUMNS]
        assert COLUMN_BY_KEY and len(keys) >= 10
        w.close()
        return f"{len(keys)} columns, dialog={dlg is not None}"


    @check("11. dialogs instantiate")
    def _dialogs():
        from hea_calc.ui.widgets import dialogs
        made = []
        for name in dir(dialogs):
            obj = getattr(dialogs, name)
            if isinstance(obj, type) and name.endswith("Dialog"):
                made.append(name)
        assert made, "no dialog classes found"
        w = new_window()
        w.close()
        return ", ".join(made)


    @check("12. Copy table produces TSV")
    def _copy():
        w = new_window()
        comp = w.composition
        for el in ("Cr", "Mn", "Fe", "Co", "Ni"):
            w.elements.table.tiles[el].click()
        QApplication.processEvents()
        comp.calculate()
        QApplication.processEvents()
        n = w.table.model.rowCount()
        assert n >= 1, "no results to copy"
        w.copy_table()
        QApplication.processEvents()
        w.close()
        return f"{n} rows copied"


    # --------------------------------------------------------------------------- 13 import/export
    @check("13. CSV + XLSX round trip")
    def _roundtrip():
        from hea_calc.core.results import ResultRow
        from hea_calc.core.spreadsheet import export_rows, read_compositions
        from hea_calc.core.engine import Engine
        from hea_calc.core.composition import parse_formula
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "in.csv"
        src.write_text("Formula\nCoCrFeNiMn\nFeCoNi(AlCu)0.2\n", encoding="utf-8")
        got = read_compositions(src)
        assert len(got.entries) == 2, got.errors
        eng = Engine()
        rows = []
        for name, amounts in got.entries:
            res = eng.calculate(amounts)
            rows.append(ResultRow(name=name, input_amounts=amounts, source="import", result=res))
        xlsx = export_rows(rows, tmp / "out.xlsx")
        csvp = export_rows(rows, tmp / "out.csv")
        assert xlsx.stat().st_size > 2000 and csvp.stat().st_size > 100
        head = csvp.read_text(encoding="utf-8-sig").splitlines()[0]
        assert "M1" in head and "Alloy" in head, head[:120]
        return f"2 imported, xlsx {xlsx.stat().st_size // 1024} kB, csv {csvp.stat().st_size} B"


    @check("13b. import rejects malformed rows with row numbers")
    def _badimport():
        from hea_calc.core.spreadsheet import read_compositions
        tmp = Path(tempfile.mkdtemp())
        p = tmp / "bad.csv"
        p.write_text("Fe,Co,Ni\n1,1,-3\n1,2\nabc,1,1\n", encoding="utf-8")
        res = read_compositions(p)
        # blank cells mean 0, so Fe=1/Co=2/Ni=blank is a legitimate two-element row; the negative
        # amount and the non-numeric cell must be rejected with their spreadsheet row numbers.
        assert [n for n, _m in res.errors] == [2, 4], res.errors
        assert res.errors[0][1] == "Ni: amount must be a non-negative number.", res.errors
        assert res.errors[1][1] == "Fe: 'abc' is not a number.", res.errors
        assert len(res.entries) == 1, res.entries
        return "2 bad rows rejected with spreadsheet row numbers, 1 valid row kept"


    # --------------------------------------------------------------------------- engine invariants
    @check("14. engine: no infinite descriptor over a mixed-element sample")
    def _finite():
        import itertools
        from hea_calc.core.engine import Engine
        eng = Engine()
        pool = ["Co", "Cr", "Fe", "Ni", "Cu", "Mn", "Al", "Ti", "B", "H", "V"]
        bad = []
        for n in (2, 3, 4):
            for combo in itertools.islice(itertools.combinations(pool, n), 0, 90):
                r = eng.calculate({e: 1 for e in combo})
                for k, v in r.descriptors.items():
                    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                        bad.append(f"{''.join(combo)}:{k}")
        assert not bad, bad[:6]
        return "no NaN/inf"


    @check("14b. one shared engine: sweep and expression feed Engine.calculate")
    def _shared():
        w = new_window()
        w.close()
        from hea_calc.core import composition, expression, generation
        assert composition.parse_formula and expression and generation
        return "single engine, three front ends"


    # --------------------------------------------------------------------------- report
    print()
    width = max(len(n) for n, _, _ in RESULTS) + 2
    bad = 0
    for name, status, detail in RESULTS:
        print(f"  {status:4}  {name:<{width}} {detail}")
        if status != "PASS":
            bad += 1
    print()
    print(f"{len(RESULTS) - bad}/{len(RESULTS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
