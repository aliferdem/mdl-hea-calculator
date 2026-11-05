"""The Composition setup footer's More actions menu in Composition space (2026-11-05).

* **Copy table** copies the range table as shown (Element, Min, Max, Step or Points, Lock), like Single
  composition's Copy table;
* **Copy compositions** copies every generated composition, at most SWEEP_COPY_LIMIT.  The At. ratio and Mass
  defaults (1.0 to 2.0, step 0.1) give 160,921 compositions for five elements: the item is then unavailable and
  says why - the chevron used to be disabled with it, without a reason."""

import os
import sys

import pytest

import _ui_support as U
from _ui_support import ROOT, pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(ROOT / "tests"))

from conftest import settle_composition  # noqa: E402


def _menu(win, monkeypatch):
    """Open More actions and return its items as (label, enabled), without running the popup's event loop."""
    from hea_calc.ui.widgets import composition_footer as F
    seen = []
    monkeypatch.setattr(F.CarbonMenu, "open_below", lambda self, *a, **k: seen.extend(
        (act.text(), act.isEnabled()) for act in self.actions() if not act.isSeparator()))
    win.composition.footer.calc.chevron.click()
    return seen


def _space(win, app, basis, elements):
    comp = win.composition
    comp.set_mode(1)
    pump(app)
    for el in elements:
        win.elements.table.tiles[el].click()
    comp.set_basis(basis)
    settle_composition(win, app)
    pump(app, 10)
    return comp


def _copied(win, app, monkeypatch, label):
    """Trigger the menu item ``label`` and return what reached the clipboard handler."""
    from hea_calc.ui.widgets import composition_footer as F
    got = []
    win.composition.copy_text.connect(lambda tsv, what: got.append((tsv, what)))

    def pick(menu, *a, **k):
        next(act for act in menu.actions() if act.text() == label).trigger()
    monkeypatch.setattr(F.CarbonMenu, "open_below", pick)
    win.composition.footer.calc.chevron.click()
    pump(app)
    return got


@pytest.mark.parametrize("basis", ["ratio", "mass"])
def test_more_actions_opens_and_explains_the_copy_limit(win, app, monkeypatch, basis):
    from hea_calc.ui.widgets.composition_panel import SWEEP_COPY_LIMIT
    comp = _space(win, app, basis, ("Co", "Cr", "Fe", "Ni", "Al"))
    assert comp.sweep.valid_count() > SWEEP_COPY_LIMIT and comp.sweep.can_calculate()
    chevron = comp.footer.calc.chevron
    assert chevron.isVisible() and chevron.isEnabled(), "the menu is reachable"
    items = _menu(win, monkeypatch)
    assert items == [("Copy table", True), (f"Copy compositions (over {SWEEP_COPY_LIMIT:,})", False)]
    from PySide6.QtGui import QFontMetricsF
    from hea_calc.ui.theme import BODY_COMPACT_01, MENU_MAX_WIDTH, MENU_PADDING_X, font
    from hea_calc.ui.widgets.menu import ICON, ICON_GAP
    room = MENU_MAX_WIDTH - 2 * MENU_PADDING_X - ICON - ICON_GAP
    for label, _on in items:
        assert QFontMetricsF(font(BODY_COMPACT_01)).horizontalAdvance(label) <= room, ("shown in full", label)
    assert comp.calc_btn.isEnabled(), "Calculate itself is unaffected"


@pytest.mark.parametrize("basis", ["ratio", "at", "wt", "mass"])
def test_both_copies_are_available_under_the_limit(win, app, monkeypatch, basis):
    comp = _space(win, app, basis, ("Co", "Cr", "Fe"))
    assert comp.footer.calc.chevron.isEnabled()
    assert _menu(win, monkeypatch) == [("Copy table", True), ("Copy compositions", True)]


@pytest.mark.parametrize("basis, unit", [("ratio", "at. ratio"), ("at", "at.%"), ("wt", "wt.%"), ("mass", "g")])
def test_copy_table_copies_the_range_table_as_shown(win, app, monkeypatch, basis, unit):
    comp = _space(win, app, basis, ("Co", "Cr", "Fe", "Ni", "Al"))      # also over the composition limit
    row = comp.sweep.rows["Al"]
    row.lock.click()                                                   # Al optional
    pump(app)
    got = _copied(win, app, monkeypatch, "Copy table")
    assert len(got) == 1 and got[0][1] == "range table"
    lines = got[0][0].split("\r\n")
    assert lines[0].split("\t") == ["Element", f"Min ({unit})", f"Max ({unit})", f"Step ({unit})", "Lock"]
    assert lines[-1] == "" and len(lines) == 1 + 5 + 1
    body = [ln.split("\t") for ln in lines[1:-1]]
    assert [r[0] for r in body] == ["Co", "Cr", "Fe", "Ni", "Al"], "the table's order"
    for r in body:
        el = comp.sweep.rows[r[0]]
        assert r[1:4] == [el.min.text(), el.max.text(), el.step.text()], "the fields' values as shown"
    assert [r[4] for r in body] == ["On", "On", "On", "On", "Off"]


def test_copy_table_follows_the_points_column(win, app, monkeypatch):
    comp = _space(win, app, "at", ("Co", "Cr", "Fe"))
    comp.sweep.set_discretization("points")
    pump(app)
    lines = _copied(win, app, monkeypatch, "Copy table")[0][0].split("\r\n")
    assert lines[0].split("\t") == ["Element", "Min (at.%)", "Max (at.%)", "Points", "Lock"]
    assert lines[1].split("\t")[3] == comp.sweep.rows["Co"].step.text()


def test_copy_compositions_still_copies_every_generated_composition(win, app, monkeypatch):
    comp = _space(win, app, "ratio", ("Co", "Cr"))
    got = []
    monkeypatch.setattr(comp, "_generate_recipe_then", lambda recipe, fn, done: got.append(fn(recipe)))
    _copied(win, app, monkeypatch, "Copy compositions")
    assert len(got) == 1
    lines = [ln for ln in got[0].split("\r\n") if ln]
    assert len(lines) - 1 == comp.sweep.valid_count(), "one row per generated composition"


def test_nothing_to_offer_keeps_the_chevron_disabled(win, app):
    comp = win.composition
    comp.set_mode(1)
    pump(app)
    assert not comp.sweep.can_calculate()
    assert not comp.footer.calc.chevron.isEnabled(), "an empty space has no action and nothing to explain"
    comp.set_mode(0)
    pump(app)
    assert not comp.footer.calc.chevron.isEnabled(), "Single composition without elements: unchanged"
