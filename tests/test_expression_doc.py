"""Composition expression documents - the inline syntax (brief sections 40-51; references
``design/fix needed/COMPOSITION_EXPRESSION_*.png``).  Core grammar without Qt, then the editor's states."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from hea_calc.core.engine import default_engine
from hea_calc.core.expression import VariableRange, count_blocks_detail, generate_blocks
from hea_calc.core.expression_doc import parse_declaration, parse_document, split_document, summary
from hea_calc.core.recipes import ExpressionRecipe

E = default_engine()


def doc(text):
    return parse_document(text, E.data)


def counts(d):
    return count_blocks_detail(d.expressions, d.block_ranges)


# ====================================================================== grammar
def test_fixed_expressions():
    for text, n_el in (("CoCrFeMnNi", 5), ("Al0.5CoCrFeNi", 5), ("FeCoNi(AlCu)0.2", 5)):
        d = doc(text)
        assert d.ok and len(d.blocks) == 1 and d.blocks[0].kind == "fixed", text
        assert len(d.elements()) == n_el
        c = counts(d)
        assert c["valid"] == 1 and c["blocks"] == [(1, 0, 0)]
        assert summary(d) == f"Parsed successfully: Single composition, {n_el} elements."


def test_fixed_group_keeps_the_verified_group_convention():
    """(FeCoNi)90Al10 = 30/30/30/10 at.% - the inline syntax does not touch the formula semantics."""
    d = doc("(FeCoNi)90Al10")
    b = generate_blocks(d.expressions, d.block_ranges)
    frac = b.compositions[0]
    tot = sum(frac.values())
    assert {k: round(100 * v / tot, 6) for k, v in frac.items()} == {"Fe": 30, "Co": 30, "Ni": 30, "Al": 10}


def test_one_variable_step():
    d = doc("AlxCoCrFeNi\n0 <= x <= 2, step=0.05")
    assert d.ok and d.blocks[0].kind == "parametric"
    r = d.blocks[0].ranges["x"]
    assert (r.minimum, r.maximum, r.step, r.points) == (0, 2, 0.05, None)
    assert counts(d)["valid"] == 41


def test_one_variable_points_includes_both_endpoints():
    d = doc("(FeCoNi)1-xAlx\n0 <= x <= 0.3, points=31")
    vals = d.blocks[0].ranges["x"].values()
    assert len(vals) == 31 and vals[0] == 0 and vals[-1] == 0.3 and vals[1] == 0.01
    assert counts(d)["valid"] == 31


def test_two_variables():
    d = doc("AlxCoyCrFeNi\n0 <= x <= 2, step=0.1\n0 <= y <= 1, points=11")
    assert d.ok and sorted(d.blocks[0].ranges) == ["x", "y"]
    assert d.combinations == 21 * 11
    c = counts(d)
    assert c["valid"] + c["skipped"] + c["duplicates"] == 231


def test_batch_of_fixed_and_parametric_blocks_with_duplicates():
    text = ("FeCoNi(AlCu)0.2\n\n(Fe1.6CoCr0.4Mn)0.9Al0.1\n\n"
            "(Co30Fe45Ni25)1-x(Al40Si60)x\n0 <= x <= 1, step=0.05\n\n"
            "(Co30Fe45Ni25)1-x(Al40Si60)x\n0 <= x <= 1, points=101")
    d = doc(text)
    assert d.ok and [b.kind for b in d.blocks] == ["fixed", "fixed", "parametric", "parametric"]
    c = counts(d)
    # the 21 step values are also among the 101 points: they stay in block 3 and are duplicates in block 4
    assert c["blocks"] == [(1, 0, 0), (1, 0, 0), (21, 0, 0), (80, 0, 21)]
    assert summary(d, c["valid"], c["duplicates"]) == \
        "Parsed successfully: 4 expressions, 2 fixed, 2 parametric, 103 compositions (21 duplicates)."


def test_mixed_batch_including_multi_variable_block():
    text = "CoCrFeMnNi\n\nAl0.5CoCrFeNi\n\nAlxCoCrFeNi\n0 <= x <= 2, step=0.1\n\n(FeCoNi)1-yAly\n0 <= y <= 0.3, points=31"
    d = doc(text)
    assert d.ok and len(d.blocks) == 4 and counts(d)["valid"] > 50


def test_blocks_split_on_one_or_more_blank_lines_and_trim_whitespace():
    blocks = split_document("  CoCrFeNi  \n\n\n\n Al{x}CoCrFeNi \n  0.5 <= x <= 1, step=0.5\n")
    assert [lines for _s, lines in blocks] == [["CoCrFeNi"], ["Al{x}CoCrFeNi", "0.5 <= x <= 1, step=0.5"]]


def test_braces_keep_a_variable_apart_from_an_element():
    d = doc("B{a}Fe\n0.5 <= a <= 1, step=0.5")
    assert d.ok and d.blocks[0].expression.variables == ["a"]
    assert d.elements() == ["B", "Fe"]
    assert doc("BaFe").ok and doc("BaFe").elements() == ["Ba", "Fe"], "Ba is barium"


def test_same_variable_may_have_different_ranges_in_different_blocks():
    d = doc("AlxCoCrFeNi\n0 <= x <= 1, step=0.5\n\n(FeCoNi)1-xAlx\n0 <= x <= 0.2, points=3")
    assert d.block_ranges[0]["x"].values() == [0, 0.5, 1.0]
    assert d.block_ranges[1]["x"].values() == [0, 0.1, 0.2]
    assert counts(d)["valid"] == 6


def test_preview_value_and_unicode_inequalities():
    d = doc("(FeCoNi)1-x-y(AlTi)xCry\n0 ≤ x ≤ 0.2, step=0.1, p=0.10\n0 <= y <= 0.2, step=0.1, preview=0.2")
    assert d.ok
    assert d.blocks[0].preview_env() == {"x": 0.1, "y": 0.2}


@pytest.mark.parametrize("text, block, needle", [
    ("FeCoXxNi", 1, 'Unknown element "Xx"'),
    ("(FeCoNi", 1, "Unmatched parenthesis"),
    ("AlxCoCrFeNi\n0 <= x <= 1, step=0.05, points=21", 1, "Specify either step or points, not both"),
    ("AlxCoCrFeNi", 1, 'The variable "x" has no range'),
    ("AlxCoCrFeNi\n0 <= x <= 1", 1, "Specify step or points"),
    ("AlxCoCrFeNi\n1 <= x <= 0, step=0.1", 1, "lower bound of x exceeds"),
    ("AlxCoCrFeNi\n0 <= x <= 1, step=0", 1, "step of x must be greater than 0"),
    ("AlxCoCrFeNi\n0 <= x <= 1, points=1.5", 1, "whole number"),
    ("AlxCoCrFeNi\n0 <= x <= 1, points=1", 1, "at least 2"),
    ("AlxCoCrFeNi\n0 <= x <= 1, step=0.1\n0 <= x <= 2, step=0.1", 1, "declared twice"),
    ("AlxCoCrFeNi\n0 <= x <= 1, step=0.1\n0 <= y <= 1, step=0.1", 1, '"y" is not used'),
    ("AlxCoCrFeNi\nx from 0 to 1", 1, "is not a range"),
    ("AlxCoCrFeNi\n0 <= x <= 1, stride=0.1", 1, "Unknown range option"),
    ("AlxCoCrFeNi\n0 <= x <= 1, step=0.1, p=2", 1, "preview value of x lies outside"),
    ("CoCrFeNi\n\nAlxCoCrFeNi", 2, 'The variable "x" has no range'),
])
def test_errors_name_the_block_and_the_reason(text, block, needle):
    d = doc(text)
    assert not d.ok
    errs = d.errors
    assert any(n == block and needle in msg for n, _first, msg in errs), errs
    assert all(first for _n, first, _m in errs)


def test_reference_error_document_reports_all_three_blocks_once():
    d = doc("FeCoXxNi\n\n(FeCoNi\n\n(Co30Fe45Ni25)1-x(Al40Si60)x\n0 <= x <= 1, step=0.05, points=21")
    assert [(n, first) for n, first, _m in d.errors] == [(1, "FeCoXxNi"), (2, "(FeCoNi"),
                                                        (3, "(Co30Fe45Ni25)1-x(Al40Si60)x")]


def test_zero_valid_compositions_are_detected_per_block():
    d = doc("CoCrFeNi\n\n(FeCoNi)1-xAlx\n1 <= x <= 1, points=1")
    assert d.ok
    assert counts(d)["blocks"][1][0] == 0, "x = 1 leaves only Al: skipped"


def test_declaration_parser_unit():
    rng, err = parse_declaration("0.1 <= x <= 0.5, step=0.1")
    assert err is None and rng == VariableRange("x", 0.1, 0.5, 0.1, None, None)
    rng, err = parse_declaration("0.5 <= y <= 0.5")
    assert err is None and rng.values() == [0.5]


def test_recipe_with_per_block_ranges_counts_and_names():
    d = doc("AlxCoCrFeNi\n0 <= x <= 1, step=0.5\n\n(FeCoNi)1-xAlx\n0 <= x <= 0.2, points=3")
    r = ExpressionRecipe(tuple(d.expressions), (), d.text, tuple(tuple(br.items()) for br in d.block_ranges))
    assert r.estimate() == 6
    meta = r.run_meta()
    assert meta["source"]["blocks"][1]["ranges"]["x"] == {"min": 0, "max": 0.2, "step": None, "points": 3,
                                                          "min_inclusive": True, "max_inclusive": True}
    kind, names, comps, envs = r()
    assert kind == "expression" and len(names) == len(comps) == 6 and envs[3] == {"x": 0.0}


# ====================================================================== editor states (offscreen)
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    a = QApplication.instance() or QApplication([])
    load_fonts()
    return a


@pytest.fixture()
def win(app):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("light")
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1920, 1032)
    w.show()
    w.composition.set_mode(2)
    app.processEvents()
    yield w
    w.close()
    THEME.set_theme("dark")
    app.processEvents()


def settle(e, app):
    t0 = time.perf_counter()
    while e._counter.busy and time.perf_counter() - t0 < 30:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def test_editor_states_draft_parsed_stale_reparse_error(win, app):
    comp = win.composition
    e = comp.expr
    e.set_text("(Fe1.6CoCr0.4Mn)0.9Al0.1")
    app.processEvents()
    assert e.state() == "ready" and comp.calc_btn.text() == "Parse expression", "parsing is explicit"
    assert comp.header_status.status is None                 # Figma Draft: no tag
    assert e.parse()
    settle(e, app)
    assert e.state() == "parsed" and comp.calc_btn.isEnabled() and comp.calc_btn.text() == "Calculate"
    assert comp.header_status.status.text == "Parsed successfully"
    assert e.section.isVisible() and e.preview_rows() and len(e.preview_rows()) == 5
    # stale: any edit after a parse
    e.set_text("(Fe1.6CoCr0.4Mn)0.9Al0.2")
    app.processEvents()
    assert e.state() == "stale" and comp.calc_btn.text() == "Parse expression"
    assert comp.header_status.status.text == "Expression changed"
    assert e.section.isVisible(), "the previous parse stays visible"
    with pytest.raises(Exception):
        e.recipe()
    assert e.parse()
    settle(e, app)
    assert e.state() == "parsed" and comp.calc_btn.isEnabled()
    # error: every problem underlined; Parse stays unavailable
    e.set_text("FeCoXxNi\n\n(FeCoNi\n\n(Co30Fe45Ni25)1-x(Al40Si60)x\n0 <= x <= 1, step=0.05, points=21")
    assert not e.parse()
    assert e.state() == "error" and not comp.calc_btn.isEnabled()
    st = comp.header_status.status
    assert st.kind == "error" and st.text == "Multiple errors"
    msgs = " ".join(d.message for d in e.edit.diagnostics)
    assert 'Unknown element "Xx"' in msgs and "Unmatched parenthesis" in msgs and "not both" in msgs
    assert sorted({d.line for d in e.edit.diagnostics}) == [0, 2, 5]
    assert not e.section.isVisible()


def test_editor_has_no_external_range_fields_and_calculates_a_batch(win, app):
    from PySide6.QtWidgets import QLineEdit
    comp = win.composition
    e = comp.expr
    assert not [f for f in e.findChildren(QLineEdit) if f.isVisible()], "ranges live in the text area only"
    e.set_text("CoCrFeNi\n\nAlxCoCrFeNi\n0.5 <= x <= 1, step=0.5\n\n(FeCoNi)1-yAly\n0 <= y <= 0.2, points=3")
    assert e.parse()
    settle(e, app)
    assert e.count_detail["blocks"] == [(1, 0, 0), (2, 0, 0), (3, 0, 0)], e.count_detail
    assert comp.header_status.status.text == "Parsed successfully"
    assert summary(e.doc, 6) == "Parsed successfully: 3 expressions, 1 fixed, 2 parametric, 6 compositions."
    comp.calc_btn.click()
    t0 = time.perf_counter()
    while (win.runner.running or win.table.model.total_count() < 6) and time.perf_counter() - t0 < 60:
        app.processEvents()
        time.sleep(0.01)
    names = sorted(r.name for r in win.table.model.rows)
    assert len(names) == 6 and "CoCrFeNi" in names and "FeCoNi" in names
    # Calculation completed is the header's state, never a table notification
    assert win.progress.message is None


def test_periodic_table_edits_the_expression_line_not_the_ranges(win, app):
    e = win.composition.expr
    e.set_text("CoCrFe\n\nAlxCoCrFeNi\n0 <= x <= 1, step=0.5")
    e.add_element("Mo")
    lines = e.text().split("\n")
    assert lines[2] == "AlxCoCrFeNiMo" and lines[3] == "0 <= x <= 1, step=0.5"
    e.remove_element("Mo")
    assert e.text().split("\n")[2] == "AlxCoCrFeNi"


def test_zero_valid_block_is_an_error_after_counting(win, app):
    e = win.composition.expr
    e.set_text("CoCrFeNi\n\n(FeCoNi)1-xAlx\n1 <= x <= 1, points=1")
    assert e.parse()
    settle(e, app)
    assert e.state() == "error" and not win.composition.calc_btn.isEnabled()
    assert win.composition.header_status.status.text == "No valid compositions"
