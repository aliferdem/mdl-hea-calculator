"""Keyboard navigation of the composition editors: symbols and Ctrl+Left / Ctrl+Right (2026-11-04)."""

import os


import _ui_support as U
from _ui_support import pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


def _focus(app):
    pump(app)
    return app.focusWidget()


def _key(app, key, mods=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(app.focusWidget(), key, mods)
    pump(app)
    return app.focusWidget()


def test_composition_space_symbol_keys_and_ctrl_left(win, app):
    comp = win.composition
    comp.set_mode(1)
    comp.set_elements(["Co", "Cr", "Fe"])
    pump(app)
    view = comp.sweep
    co, cr, fe = (view.rows[e] for e in ("Co", "Cr", "Fe"))
    co.el.setFocus()
    assert _focus(app) is co.el
    assert _key(app, Qt.Key.Key_Up) is co.el, "first row: Up stays"
    assert _key(app, Qt.Key.Key_Down) is cr.el
    assert _key(app, Qt.Key.Key_Down) is fe.el
    assert _key(app, Qt.Key.Key_Down) is fe.el, "last row: Down stays"
    assert _key(app, Qt.Key.Key_Up) is cr.el
    assert _key(app, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier) is cr.min
    assert _key(app, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier) is cr.max
    assert _key(app, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier) is cr.min
    assert _key(app, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier) is cr.el, "Ctrl+Left reaches the symbol"
    assert _key(app, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier) is cr.el, "nothing left of the symbol"
    # Shift+Up / Shift+Down keep their text meaning (selection) in the symbol field
    assert _key(app, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier) is cr.el
    # Up / Down in the values keep moving within the column
    cr.min.setFocus()
    _focus(app)
    assert _key(app, Qt.Key.Key_Down) is fe.min


def test_single_composition_symbol_keys(win, app):
    comp = win.composition
    comp.set_mode(0)
    comp.set_elements(["Co", "Cr", "Fe"])
    pump(app)
    view = comp.single
    co, cr, fe = (view.rows[e] for e in ("Co", "Cr", "Fe"))
    # in an amount column the symbols are not editable: Ctrl+Left from the amount stays (normal editing)
    first = next(f for f in view.value_cells(cr) if f.isEnabled() and not f.isReadOnly())
    first.setFocus()
    assert _focus(app) is first
    assert _key(app, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier) is first
    # El. input column: the symbols are editable and Up / Down move between them, bounded at both ends
    view._radio(0)
    pump(app)
    co.el.setFocus()
    assert _focus(app) is co.el
    assert _key(app, Qt.Key.Key_Down) is cr.el
    assert _key(app, Qt.Key.Key_Down) is fe.el
    assert _key(app, Qt.Key.Key_Down) is fe.el
    assert _key(app, Qt.Key.Key_Up) is cr.el
    assert _key(app, Qt.Key.Key_Up) is co.el
    assert _key(app, Qt.Key.Key_Up) is co.el
    assert cr.el.text() == "Cr", "moving never edits a symbol"


def test_up_from_the_add_element_draft_reaches_the_last_symbol(win, app):
    """The draft takes part in Up / Down; leaving an empty draft removes it, as any focus loss does (RowEditing)."""
    comp = win.composition
    comp.set_mode(1)
    comp.set_elements(["Co", "Cr"])
    pump(app)
    view = comp.sweep
    view.open_draft(after="Cr")
    pump(app)
    assert _focus(app) is view.draft.el
    assert _key(app, Qt.Key.Key_Up) is view.rows["Cr"].el
    pump(app, 5)
    assert view.draft is None, "an empty draft that loses the focus is discarded (unchanged rule)"
    assert list(view.rows) == ["Co", "Cr"]
