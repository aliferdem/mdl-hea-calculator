"""Final Figma implementation (2026-10-25): expression lexer / grammar / automatic declarations, the Composition
setup heading dropdown, the custom title bar, panel collapse, Analysis identity, newest-first results and the
Figma theme variables.

Core tests need no Qt.  UI tests run offscreen.  The native title-bar test opens a real Windows window and runs only
with ``HEA_NATIVE_TESTS=1`` on Windows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]

from hea_calc.core.data import default_datasets  # noqa: E402
from hea_calc.core import expression_lexer as L  # noqa: E402
from hea_calc.core.expression import (VariableRange, count_combinations, parse_expression,  # noqa: E402
                                      range_from_meta)
from hea_calc.core.expression_doc import (DEFAULT_RANGE, LEXICAL, SEMANTIC, SYNTAX,  # noqa: E402
                                          apply_declaration_edits, parse_document, plan_declarations)
from hea_calc.core.recipes import ExpressionRecipe  # noqa: E402

D = default_datasets()


def kinds(text):
    return [(t.kind, t.text) for t in L.lex_formula(text, D) if t.kind != L.SPACE]


# ====================================================================== lexer
@pytest.mark.parametrize("text, expected", [
    ("CrMnFeCoNiyCux", [("element", "Cr"), ("element", "Mn"), ("element", "Fe"), ("element", "Co"),
                        ("element", "Ni"), ("variable", "y"), ("element", "Cu"), ("variable", "x")]),
    ("FeCoNi", [("element", "Fe"), ("element", "Co"), ("element", "Ni")]),
    ("(Fe1.6CoCr0.4Mn)0.9Al0.1", [("punctuation", "("), ("element", "Fe"), ("number", "1.6"), ("element", "Co"),
                                  ("element", "Cr"), ("number", "0.4"), ("element", "Mn"), ("punctuation", ")"),
                                  ("number", "0.9"), ("element", "Al"), ("number", "0.1")]),
    ("(Co30Fe45Ni25)1-x(Al40Si60)x", [("punctuation", "("), ("element", "Co"), ("number", "30"), ("element", "Fe"),
                                      ("number", "45"), ("element", "Ni"), ("number", "25"), ("punctuation", ")"),
                                      ("number", "1"), ("operator", "-"), ("variable", "x"), ("punctuation", "("),
                                      ("element", "Al"), ("number", "40"), ("element", "Si"), ("number", "60"),
                                      ("punctuation", ")"), ("variable", "x")]),
    ("(FeCoNi)1-x-y-z(AlTi)xCryCuz", [("punctuation", "("), ("element", "Fe"), ("element", "Co"),
                                      ("element", "Ni"), ("punctuation", ")"), ("number", "1"), ("operator", "-"),
                                      ("variable", "x"), ("operator", "-"), ("variable", "y"), ("operator", "-"),
                                      ("variable", "z"), ("punctuation", "("), ("element", "Al"), ("element", "Ti"),
                                      ("punctuation", ")"), ("variable", "x"), ("element", "Cr"), ("variable", "y"),
                                      ("element", "Cu"), ("variable", "z")]),
])
def test_lexer_reads_chemical_formulas_like_the_parser(text, expected):
    assert kinds(text) == expected
    # the parser agrees: the same elements and variables, in the same order
    ex = parse_expression(text, D)
    els = [k[1] for k in expected if k[0] == "element"]
    assert list(dict.fromkeys(els)) == list(dict.fromkeys(_elements(ex)))
    assert L.formula_variables(text, D) == ex.variables


def _elements(ex):
    out = []

    def walk(items):
        for it in items:
            if hasattr(it, "symbol"):
                out.append(it.symbol)
            else:
                walk(it.items)
    walk(ex.items)
    return out


def test_capitalisation_distinguishes_cobalt_from_carbon_oxygen():
    assert kinds("Co") == [("element", "Co")]
    assert kinds("CO") == [("element", "C"), ("element", "O")]
    assert kinds("Cx") == [("element", "C"), ("variable", "x")]
    assert kinds("FeXx")[-1] == ("invalid", "Xx")


def test_lexer_columns_cover_the_original_text_with_spaces():
    toks = L.lex_formula("Fe Co  Ni", D)
    assert "".join(t.text for t in toks) == "Fe Co  Ni"
    assert [(t.start, t.end) for t in toks if t.kind == L.ELEMENT] == [(0, 2), (3, 5), (7, 9)]


def test_declaration_tokens():
    toks = [(t.kind, t.text) for t in L.lex_declaration("  0 < x <= 1, step=0.1, p=0.5") if t.kind != L.SPACE]
    assert toks == [("number", "0"), ("comparison", "<"), ("variable", "x"), ("comparison", "<="), ("number", "1"),
                    ("punctuation", ","), ("keyword", "step"), ("operator", "="), ("number", "0.1"),
                    ("punctuation", ","), ("keyword", "p"), ("operator", "="), ("number", "0.5")]


def test_line_roles_follow_blocks():
    assert L.line_roles(["A", "  0<=x<=1", "", "B", "c"]) == ["expression", "declaration", "blank", "expression",
                                                               "declaration"]


# ====================================================================== < and <=
@pytest.mark.parametrize("decl, values", [
    ("0 <= x <= 1, step=0.25", [0.0, 0.25, 0.5, 0.75, 1.0]),
    ("0 < x < 1, step=0.25", [0.25, 0.5, 0.75]),
    ("0 < x <= 1, step=0.25", [0.25, 0.5, 0.75, 1.0]),
    ("0 <= x < 1, step=0.25", [0.0, 0.25, 0.5, 0.75]),
    ("0 < x < 1, points=5", [0.25, 0.5, 0.75]),
    ("0.1 < x < 0.3, step=0.1", [0.2]),                 # floating point: 0.1 + 0.1 + 0.1 is not 0.3 in binary
    ("0 < x < 0.95, step=0.3", [0.3, 0.6, 0.9]),         # the upper bound is not on the grid: nothing removed
    ("0 ≤ x ≤ 1, step=0.5", [0.0, 0.5, 1.0]),
])
def test_strict_and_inclusive_bounds(decl, values):
    doc = parse_document(f"(FeCoNi)1-xAlx\n  {decl}", D)
    assert doc.ok, doc.errors
    r = doc.blocks[0].ranges["x"]
    assert r.values() == pytest.approx(values)
    # counting and generation use the same grid
    assert count_combinations(doc.expressions, doc.block_ranges) == len(values)
    rec = ExpressionRecipe(tuple(doc.expressions), (), doc.text, tuple(tuple(b.items()) for b in doc.block_ranges))
    assert rec.estimate() == len(values)


def test_strict_bounds_are_never_normalised_to_inclusive():
    r = parse_document("AlxCoCrFeNi\n0 < x < 1, step=0.5", D).blocks[0].ranges["x"]
    assert (r.min_inclusive, r.max_inclusive) == (False, False)
    assert r.bounds_text() == "0 < x < 1" and r.values() == [0.5]
    assert not r.contains(0) and not r.contains(1) and r.contains(0.5)


def test_empty_strict_range_is_an_error_not_an_empty_batch():
    doc = parse_document("AlxCoCrFeNi\n0 < x < 1, points=2", D)
    assert not doc.ok and "contains no values" in doc.errors[0][2]
    assert doc.diagnostics[0].category == SEMANTIC


def test_step_and_points_conflict_and_positive_step():
    doc = parse_document("AlxCoCrFeNi\n  0 <= x <= 1, step=0.05, points=21", D)
    d = doc.diagnostics[0]
    assert "Choose one sampling method" in d.message and (d.line, d.start, d.end) == (1, 15, 35)
    assert "greater than 0" in parse_document("AlxCoCrFeNi\n0 <= x <= 1, step=0", D).errors[0][2]
    assert "at least 2" in parse_document("AlxCoCrFeNi\n0 <= x <= 1, points=1", D).errors[0][2]


def test_preview_value_respects_strict_bounds():
    doc = parse_document("AlxCoCrFeNi\n0 < x < 1, step=0.5, p=0", D)
    assert not doc.ok and "lies outside 0 < x < 1" in doc.errors[0][2]
    doc = parse_document("AlxCoCrFeNi\n0 < x < 1, step=0.25", D)
    assert doc.blocks[0].preview_env() == {"x": 0.25}          # the first grid value, not the excluded bound


def test_run_metadata_keeps_strict_bounds_and_reads_legacy_lists():
    doc = parse_document("AlxCoCrFeNi\n0 < x <= 1, step=0.5", D)
    rec = ExpressionRecipe(tuple(doc.expressions), (), doc.text, tuple(tuple(b.items()) for b in doc.block_ranges))
    meta = rec.run_meta()["source"]["ranges"]["x"]
    assert meta["min_inclusive"] is False and meta["max_inclusive"] is True
    assert range_from_meta("x", meta).values() == [0.5, 1.0]
    assert range_from_meta("x", [0, 1, 0.5]).values() == [0.0, 0.5, 1.0]          # runs stored before
    assert range_from_meta("x", [0, 0.2, None, 3]).values() == pytest.approx([0, 0.1, 0.2])


# ====================================================================== diagnostics
def test_diagnostics_have_spans_categories_and_unfinished_flags():
    text = "FeCoXxNi\n\n(FeCoNi\n\n(FeCoNi)1-xAlx\n  0 <= y <= 1, step=0.1"
    ds = parse_document(text, D).diagnostics
    by_line = {d.line: d for d in ds}
    assert (by_line[0].start, by_line[0].end, by_line[0].category) == (4, 6, LEXICAL)
    assert by_line[2].incomplete and by_line[2].category == SYNTAX and by_line[2].start == 7
    assert any(d.line == 4 and "has no range" in d.message and (d.start, d.end) == (10, 11) for d in ds)
    assert any(d.line == 5 and "not used" in d.message and (d.start, d.end) == (7, 8) for d in ds)


def test_trailing_operator_is_unfinished_input():
    d = parse_document("FeCoNi1-", D).diagnostics[0]
    assert d.incomplete


# ====================================================================== automatic declarations
def test_new_variables_get_default_ranges_in_order_of_appearance():
    edits, mem = plan_declarations("CrMnFeCoNiyCux", D)
    assert apply_declaration_edits("CrMnFeCoNiyCux", edits) == \
        "CrMnFeCoNiyCux\n  0 <= y <= 1, step=0.1\n  0 <= x <= 1, step=0.1"
    assert mem == [{"x", "y"}]
    text = apply_declaration_edits("CrMnFeCoNiyCux", edits)
    assert plan_declarations(text, D, mem)[0] == []                # no duplicates
    assert parse_document(text, D).ok


def test_rename_keeps_the_edited_values():
    text = "AlxCoCrFeNi\n  0 <= x <= 0.6, step=0.2"
    edits, _ = plan_declarations(text.replace("Alx", "Alt"), D, [{"x"}])
    assert apply_declaration_edits(text.replace("Alx", "Alt"), edits) == "AltCoCrFeNi\n  0 <= t <= 0.6, step=0.2"


def test_removed_variable_default_is_dropped_but_edited_range_is_kept_and_flagged():
    default = "CrMnFeCoNiy\n  0 <= y <= 1, step=0.1\n  " + DEFAULT_RANGE.format(v="x")
    edits, mem = plan_declarations(default, D, [{"x", "y"}])
    assert apply_declaration_edits(default, edits) == "CrMnFeCoNiy\n  0 <= y <= 1, step=0.1" and mem == [{"y"}]
    edited = "CrMnFeCoNiy\n  0 <= y <= 1, step=0.1\n  0 <= x <= 0.5, step=0.1"
    assert plan_declarations(edited, D, [{"x", "y"}])[0] == []
    assert "not used" in parse_document(edited, D).errors[0][2]


def test_a_deleted_declaration_is_not_added_again():
    assert plan_declarations("AlxCoCrFeNi", D, [{"x"}])[0] == []


def test_declarations_per_block():
    text = "(FeCoNi)1-xAlx\n\nAlyCoCrFeNi"
    out = apply_declaration_edits(text, plan_declarations(text, D)[0])
    assert out == "(FeCoNi)1-xAlx\n  0 <= x <= 1, step=0.1\n\nAlyCoCrFeNi\n  0 <= y <= 1, step=0.1"


# ====================================================================== native chrome (pure parts)
def test_hit_zones():
    from hea_calc.ui import win_chrome as W
    z = lambda x, y, bar="client", m=False: W.hit_zone(x, y, 1000, 800, 8, 8, m, bar)  # noqa: E731
    assert z(500, 2, "caption") == W.HTTOP and z(2, 2) == W.HTTOPLEFT and z(998, 798) == W.HTBOTTOMRIGHT
    assert z(500, 20, "caption") == W.HTCAPTION and z(500, 20, "max") == W.HTMAXBUTTON
    assert z(500, 2, "max") == W.HTMAXBUTTON                       # the maximise button reaches the top edge
    assert z(500, 2, "caption", m=True) == W.HTCAPTION              # maximised: no resize borders
    assert z(500, 400) == W.HTCLIENT


def test_maximised_client_rect_is_inset_by_the_frame_and_autohide_taskbar():
    from hea_calc.ui.win_chrome import maximized_client
    assert maximized_client((-8, -8, 1928, 1088), 8, 8) == (0, 0, 1920, 1080)
    assert maximized_client((-8, -8, 1928, 1088), 8, 8, (False, False, False, True)) == (0, 0, 1920, 1078)


# ====================================================================== theme variables
def test_theme_tokens_reproduce_the_figma_variables_in_both_themes():
    from hea_calc.ui.theme import DARK, FIGMA_VARIABLES, LIGHT, SEMANTIC_ALIASES
    for name, tokens in (("light", LIGHT), ("dark", DARK)):
        for alias, var in SEMANTIC_ALIASES.items():
            assert tokens[alias] == FIGMA_VARIABLES[name][var], (name, alias)
    # spot values read from the Figma file (White / Gray 100)
    assert (LIGHT["syntax-number"], DARK["syntax-number"]) == ("#0072c3", "#82cfff")
    assert (LIGHT["syntax-variable"], DARK["syntax-variable"]) == ("#d02670", "#ff7eb6")
    assert (LIGHT["syntax-line-number"], DARK["syntax-line-number"]) == ("#237893", "#858585")
    assert (LIGHT["tag-red-bg"], DARK["tag-red-bg"]) == ("#ffd7d9", "#a2191f")
    assert LIGHT["shell"] == "#ffffff" and DARK["shell"] == "#161616"
    assert LIGHT["layer-01"] == "#ffffff" and DARK["layer-01"] == "#262626"


# ====================================================================== newest-first view (core)
def _rows(engine, names):
    from hea_calc.core.results import ResultRow
    comp = {"Fe": 1, "Co": 1, "Ni": 1}
    return [ResultRow(n, dict(comp), engine.calculate(comp), "single", {}) for n in names]


def _store(repo, engine, names):
    run = repo.create_run("single", settings={}, elements=["Fe", "Co", "Ni"])
    repo.append_results(run, _rows(engine, names))
    repo.finalize_run(run, "complete")


def test_result_view_newest_first_without_a_sort(engine, tmp_path):
    from hea_calc.core.repository import ResultRepository, ResultView
    repo = ResultRepository(engine, root=tmp_path / "sessions")
    try:
        view = ResultView(repo)
        _store(repo, engine, [f"R{i}" for i in range(5)])
        view.refresh()
        assert [r.name for r in view.page(0, 10)] == ["R0", "R1", "R2", "R3", "R4"]      # dataset order
        view.newest_first = True
        assert [r.name for r in view.page(0, 10)] == ["R4", "R3", "R2", "R1", "R0"]
        assert [r.name for r in view.page(1, 2)] == ["R3", "R2"]
        ids = {r.name: r.id for r in view.page(0, 10)}
        assert view.position_of(ids["R4"]) == 0 and view.position_of(ids["R0"]) == 4
        assert [r.name for r in view.iterate_table()] == ["R4", "R3", "R2", "R1", "R0"]
        assert [r.name for r in view.iterate()] == ["R0", "R1", "R2", "R3", "R4"]   # exports: calculation order
        # new rows enter at index 0
        _store(repo, engine, ["R5"])
        view.refresh()
        assert view.page(0, 1)[0].name == "R5" and view.position_of(ids["R4"]) == 1
        # a removed row keeps the order consistent
        view.remove_ids([ids["R2"]])
        assert [r.name for r in view.page(0, 10)] == ["R5", "R4", "R3", "R1", "R0"]
        # an explicit sort is not reversed
        view.request(sort=("name", True))
        view.wait()
        assert [r.name for r in view.page(0, 3)] == ["R5", "R4", "R3"]
        view.request(sort=("name", False))
        view.wait()
        assert [r.name for r in view.page(0, 3)] == ["R0", "R1", "R3"]
    finally:
        repo.close()


# ====================================================================== UI (offscreen)
@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


def pump(app, seconds=0.0, n=4):
    end = time.monotonic() + seconds
    while True:
        for _ in range(n):
            app.processEvents()
        if time.monotonic() >= end:
            return
        time.sleep(0.01)


@pytest.fixture()
def win(app):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("light")
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1920, 1000)
    w.show()
    pump(app)
    yield w
    w.close()
    w.deleteLater()
    pump(app)


def test_heading_dropdown_switches_modes_and_basis(win, app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    comp = win.composition
    assert not hasattr(comp, "switcher") and not hasattr(comp, "unit_box")
    assert comp.heading.label == "Single composition" and comp.heading.height() == 40
    for el in ("Fe", "Co", "Ni"):
        win.elements.table.tiles[el].click()
    comp.single.rows["Fe"].fields["ratio"].setText("2")
    # keyboard: open, Down to Composition space (its basis list is open), Right, Down to at.%, Enter
    comp.heading.setFocus()
    QTest.keyClick(comp.heading, Qt.Key.Key_Down)
    pump(app)
    pop = comp.heading.popup
    assert pop is not None and pop.open_parent == -1
    QTest.keyClick(pop, Qt.Key.Key_Down)
    assert pop.open_parent == 1 and [n.label for n in pop.sub_nodes()] == ["At. ratio", "at.%", "wt.%", "Mass"]
    QTest.keyClick(pop, Qt.Key.Key_Right)
    QTest.keyClick(pop, Qt.Key.Key_Down)
    QTest.keyClick(pop, Qt.Key.Key_Return)
    pump(app)
    assert comp.mode == "sweep" and comp.basis == "at" and comp.heading.label == "Composition space (at.%)"
    # back to Single: its input is preserved
    comp._heading_chosen(("single",))
    assert comp.mode == "single" and comp.single.rows["Fe"].fields["ratio"].text() == "2"
    comp.set_basis("mass")
    comp._heading_chosen(("sweep",))
    assert comp.heading.label == "Composition space (Mass)"
    comp._heading_chosen(("expression",))
    assert comp.heading.label == "Expression" and comp.help_btn.isVisible()


def _type(editor, text):
    from PySide6.QtTest import QTest
    QTest.keyClicks(editor, text)


def test_typing_a_variable_adds_its_range_keeps_the_caret_and_undo(win, app):
    comp = win.composition
    comp.set_mode(2)
    ex = comp.expr
    ed = ex.edit
    ed.setFocus()
    _type(ed, "CrMnFeCoNiyCux")
    caret = ed.textCursor().position()
    ex._validate()                                   # the debounce pause
    assert ex.text() == "CrMnFeCoNiyCux\n  0 <= y <= 1, step=0.1\n  0 <= x <= 1, step=0.1"
    assert ed.textCursor().position() == caret and ed.textCursor().blockNumber() == 0
    # one Undo removes the automatic declarations, which are not added back
    ed.undo()
    pump(app)
    ex._validate()
    assert ex.text() == "CrMnFeCoNiyCux"
    ed.redo()
    pump(app)
    assert ex.text().count("step=0.1") == 2


def test_highlighter_colours_follow_the_figma_syntax_tokens(win, app):
    from hea_calc.ui.theme import t
    comp = win.composition
    comp.set_mode(2)
    ex = comp.expr
    ex.set_text("(Fe1.6CoCr0.4Mn)0.9Al0.1")
    pump(app)
    blk = ex.edit.document().firstBlock()
    fmts = {(r.start, r.length): r.format.foreground().color().name() for r in blk.layout().formats()}
    assert fmts[(0, 1)] == t("syntax-punctuation")
    assert fmts[(1, 2)] == t("syntax-element")          # Fe
    assert fmts[(3, 3)] == t("syntax-number")           # 1.6
    ex.set_text("(FeCoNi)1-xAlx\n  0 < x <= 1, step=0.5")
    pump(app)
    second = ex.edit.document().findBlockByNumber(1)
    f2 = {second.text()[r.start:r.start + r.length]: r.format.foreground().color().name()
          for r in second.layout().formats()}
    assert f2["<"] == t("syntax-operator") and f2["x"] == t("syntax-variable") and f2["step"] == t("syntax-keyword")


def test_parse_then_calculate_and_stale_input_is_never_calculated(win, app):
    from hea_calc.core.expression import ExpressionError
    comp = win.composition
    comp.set_mode(2)
    ex = comp.expr
    ex.set_text("(FeCoNi)1-xAlx\n  0 <= x <= 0.5, step=0.25")
    pump(app)
    assert ex.state() == "ready" and ex.primary_action()[:2] == ("parse", True)
    assert comp.calc_btn.text() == "Parse expression"
    comp.calculate()                                  # the primary button parses first
    t0 = time.monotonic()
    while ex.counting and time.monotonic() - t0 < 20:
        pump(app, 0.02)
    assert ex.state() == "parsed" and comp.calc_btn.text() == "Calculate"
    assert comp.header_status.status.text == "Parsed successfully"
    c = ex.edit.textCursor()
    c.movePosition(c.MoveOperation.End)
    c.insertText("1")                                 # 0.251 - changed after the parse
    pump(app)
    assert ex.state() == "stale" and comp.header_status.status.text == "Expression changed"
    with pytest.raises(ExpressionError):
        ex.recipe()
    assert not comp.calc_btn.isEnabled() or comp.calc_btn.text() == "Parse expression"


def test_unfinished_input_on_the_caret_line_is_held_back(win, app):
    comp = win.composition
    comp.set_mode(2)
    ex = comp.expr
    ex.edit.setFocus()
    _type(ex.edit, "(FeCoNi")
    ex._validate()
    assert ex.live and ex.live[0].incomplete and not ex.shown and ex.state() != "error"
    ex.parse()                                        # an explicit parse shows it
    assert ex.shown and ex.state() == "error" and comp.header_status.status.text == "Unmatched parenthesis"


def test_title_bar_layout_hit_test_and_top_panels(win, app):
    from PySide6.QtCore import QPoint
    bar = win.header
    assert bar.height() == 36 and bar.row.height() == 32
    assert [w.text() for w in bar.menu_items] == ["File", "Edit", "View", "Help"]
    assert bar.file_item.x() == 24 + 173 + 17
    for b in (bar.min_btn, bar.max_btn, bar.close_btn):
        assert (b.width(), b.height()) == (46, 32)
    assert bar.close_btn.geometry().right() == bar.width() - 1
    assert bar.hit_test(QPoint(bar.file_item.geometry().center())) == "client"
    assert bar.hit_test(QPoint(bar.max_btn.geometry().center())) == "max"
    assert bar.hit_test(QPoint(bar.width() // 2, 16)) == "caption"
    assert bar.hit_test(QPoint(bar.width() // 2, 34)) == "client"          # the state line is not the caption
    win.set_top_panels_visible(False)
    pump(app)
    assert not win.top_row.isVisible() and bar.panels_btn.icon_name == "open_panel_top"
    assert win.settings.value("top_panels_visible", True, bool) is False
    bar.panels_btn.click()
    assert win.top_row.isVisible() and win.top_panels_action.isChecked()


def test_f10_enters_the_title_bar_menus(win, app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    win.activateWindow()
    win._menu_mode()
    pump(app)
    assert win.header.file_item.hasFocus()
    QTest.keyClick(win.header.file_item, Qt.Key.Key_Right)
    assert win.header.edit_item.hasFocus()
    QTest.keyClick(win.header.edit_item, Qt.Key.Key_Escape)
    assert not win.header.in_menu_mode()


def test_view_menu_holds_the_theme_choices(win, app):
    labels = [a.text() for a in win.view_menu.actions() if not a.isSeparator()]
    # Top panels (Ctrl+B) and Full screen (F11) restored from the window-chrome branch, then the Figma Theme section;
    # 2026-10-28 (C6): Expand analysis and the Panels section with Reset workspace restored before the Theme section
    assert labels == ["Top panels", "Full screen", "Expand analysis", "Panels", "Elements", "Composition setup",
                      "Analysis", "Reset workspace", "Theme", "Light", "Dark", "System default"]
    dark = next(a for a in win.theme_actions.actions() if a.data() == "dark")
    dark.trigger()
    from hea_calc.ui.theme import THEME
    assert THEME.name == "dark" and dark.isChecked()


def test_progress_line_reserves_its_height(win, app):
    y0 = win.top_row.mapTo(win, win.top_row.rect().topLeft()).y()
    win.progress.show()
    win.progress.set_progress("Calculating", 25, 100, 60)
    pump(app)
    assert win.progress_line.fraction() == 0.25
    assert win.top_row.mapTo(win, win.top_row.rect().topLeft()).y() == y0        # no layout shift
    assert y0 == 36 + 16
    win.progress.hide()


def test_panels_collapse_to_strips_and_analysis_takes_the_space(win, app):
    row = win.top_row
    w0 = win.details.width()
    win.elements.collapse_btn.click()
    pump(app)
    assert not win.elements.isVisible() and row.strips[0].isVisible() and row.strips[0].width() == 40
    # 2026-10-27 (B8): the gap beside a collapsed strip is 8 px, so Analysis also gains 16 - 8 px
    from hea_calc.ui.widgets.layouts import COLLAPSED_GAP
    assert win.details.width() == w0 + 570 - 40 + (row.gap - COLLAPSED_GAP)
    assert win.settings.value("collapsed_panels") == "0"
    row.strips[0].button.click()
    pump(app)
    assert win.elements.isVisible() and win.details.width() == w0


def test_calculation_failure_is_a_panel_state_not_an_input_error(win, app):
    comp = win.composition
    comp.set_run_failed("The engine stopped: disk full.")
    st = comp.header_status.status
    assert st.kind == "error" and st.text == "Calculation failed" and "disk full" in st.info
    for el in ("Fe", "Co", "Ni"):
        win.elements.table.tiles[el].click()            # the next edit clears it
    pump(app)
    assert comp.header_status.status is None or comp.header_status.status.text != "Calculation failed"


def test_analysis_identity_names_the_run_not_the_elements(win, app):
    win.calculate("single", ["CoCrFeMnNi"], [{"Co": 1, "Cr": 1, "Fe": 1, "Mn": 1, "Ni": 1}], [{}])
    pump(app, 0.3)
    ident = win.analysis.composition.identity_text()
    assert ident == "Single composition · Run 1"
    assert "elements" not in ident and "Co-Cr" not in ident


def test_results_table_is_newest_first_until_a_column_is_sorted(win, app):
    for n in ("AlCoCrFeNi", "CoCrFeNi", "CoCrFeMnNi"):
        els = {"Al": "Al", "Co": "Co"}
        comp = {e: 1 for e in ("Co", "Cr", "Fe", "Ni")}
        if n.startswith("Al"):
            comp["Al"] = 1
        if "Mn" in n:
            comp["Mn"] = 1
        win.calculate("single", [n], [comp], [{}])
        pump(app, 0.2)
    m = win.table.model
    assert [r.name for r in m.page_rows()] == ["CoCrFeMnNi", "CoCrFeNi", "AlCoCrFeNi"]
    m.sort_by("name")
    m.wait()
    assert [r.name for r in m.page_rows()] == ["AlCoCrFeNi", "CoCrFeMnNi", "CoCrFeNi"]
    m.sort_by("name")
    m.sort_by("name")                                 # third click: no sort -> newest first again
    m.wait()
    assert [r.name for r in m.page_rows()] == ["CoCrFeMnNi", "CoCrFeNi", "AlCoCrFeNi"]
    assert [r.name for r in m.view_rows] == ["CoCrFeMnNi", "CoCrFeNi", "AlCoCrFeNi"]


# ====================================================================== native (real Windows window)
NATIVE = sys.platform == "win32" and os.environ.get("HEA_NATIVE_TESTS") == "1"


@pytest.mark.skipif(not NATIVE, reason="opens a real Windows window (HEA_NATIVE_TESTS=1)")
def test_native_title_bar_hit_testing_and_maximise():
    script = textwrap.dedent(f"""
        import json, sys, time, tempfile
        sys.path.insert(0, {str(ROOT)!r})
        from pathlib import Path
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        app = QApplication(sys.argv)
        from hea_calc.ui.theme import load_fonts
        load_fonts()
        from hea_calc.ui.main_window import MainWindow
        from hea_calc.ui import win_chrome as W
        w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
        w.resize(1300, 800); w.move(60, 60); w.show()
        end = time.monotonic() + 1.0
        while time.monotonic() < end: app.processEvents()
        b = w.header
        def c(x): p = x.mapTo(w, x.rect().center()); return p.x(), p.y()
        hit = {{k: w.chrome.send_hit_test(*v) for k, v in {{
            "caption": (700, 16), "file": c(b.file_item), "max": c(b.max_btn), "close": c(b.close_btn),
            "top": (700, 2), "left": (2, 400), "corner": (w.width() - 2, w.height() - 2), "client": (300, 300)}}.items()}}
        style = (w.chrome.native_style() & W.NATIVE_STYLE) == W.NATIVE_STYLE
        b.maximize_requested.emit()
        end = time.monotonic() + 1.0
        while time.monotonic() < end: app.processEvents()
        out = {{"hit": hit, "style": style, "max": w.isMaximized(), "glyph": b.max_btn.glyph()}}
        w.close()
        print("RESULT" + json.dumps(out))
    """)
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, env=env)
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT"))
    out = json.loads(line[6:])
    from hea_calc.ui import win_chrome as W
    assert out["style"] and out["max"] and out["glyph"] == "restore"
    assert out["hit"] == {"caption": W.HTCAPTION, "file": W.HTCLIENT, "max": W.HTMAXBUTTON, "close": W.HTCLIENT,
                          "top": W.HTTOP, "left": W.HTLEFT, "corner": W.HTBOTTOMRIGHT, "client": W.HTCLIENT}
