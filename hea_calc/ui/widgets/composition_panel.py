"""Composition setup panel - the current Figma component "Composition setup" (Mode=Single / Space / Expression,
nodes 392:69182 / 392:69349 / 392:69514 and their base components), with three workflows sharing one engine:

* Single composition - editable representation columns (El., At. ratio, at.%, wt.%, Mass) and a persisted
  Total mass (``ui/preferences.py``);
* Composition space - per-element Min / Max / Step in a *range basis* (at. ratio, at.%, wt.% or mass, chosen in
  the panel header), Lock (required / optional), editable element symbols, a multi-select System size and the
  workload summary;
* Composition expression - expression blocks with variables and their Min / Max / Step.

Product decisions (release reconciliation): the panel is **not responsive** - its geometry is the component's
(457 × 465) at every window width; its title names the mode; every explanation (invalid input, counting,
readiness, workload, model coverage) is in the 32 px footer (``composition_footer.py``), fields only mark
which input is invalid; calculation progress is in the UI shell header, not here.

The panel only builds compositions; calculations are requested through ``calculate_requested``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QRadioButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from ...core import composition as C
from ...core.data import Datasets
from ...core.expression import ExpressionError
from ...core.generation import SUM_UNITS, RangeError, SweepSpec, summarize_space
from ...core.limits import HARD_LIMIT, LARGE, capacity_problem, describe, estimate, fmt_short_bytes, \
    fmt_short_duration
from ...core.recipes import SweepRecipe, compositions_tsv, recipe_tsv
from .. import crisp
from ..preferences import DEFAULT_TOTAL_MASS, format_mass, valid_mass
from ..theme import COMPOSITION_PANEL_WIDTH, FOCUS_WIDTH, HAIRLINE, t
from ..worker import BackgroundTask
from .common import Divider, EmptyState, InfoButton, Panel, install_wheel_guard, refresh_style, retire
from .composition_footer import CompositionFooter, Status, WorkloadSummary
from .status_tag import HeaderIconButton
from .dropdown import Dropdown, MultiSelect
from .expression_view import ExpressionView
from .menu import carbon_context_menu
from .scroll import own_wheel, thin_scrollbars

COL_ELEMENT = 64
COL_VALUE = 88
COL_GAP = 1
COL_LOCK = 32      # Figma (Composition space bases 393:66042): the 16 px lock icon in a 32 px ghost cell after Step
ROW_H = 32
ROW_GAP = 1
REP_KEYS = ("ratio", "at", "wt", "mass")
DECIMALS = {"ratio": 4, "at": 4, "wt": 4, "mass": 5}
SWEEP_LIMIT = HARD_LIMIT     # largest measured batch (core/limits.py); was 200 000 (in-memory result store)
COUNT_DEBOUNCE_MS = 200      # pre-flight counts wait for a pause in typing
HEAVY_THRESHOLD = 5_000      # combinations above which a pre-flight runs in a worker process

MODE_TITLES = {"single": "Single composition", "sweep": "Composition space", "expression": "Expression"}
RANGE_BASES = (("ratio", "At. ratio"), ("at", "at.%"), ("wt", "wt.%"), ("mass", "Mass"))
BASIS_LABELS = dict(RANGE_BASES)
SWEEP_COPY_LIMIT = 100_000   # Copy table of a composition space puts every generated row on the clipboard
# defaults of a new row / after a basis change: (min, max, step)
def parse_points(text: str) -> int | None:
    """A Points value: a whole number (``11``, ``11.0`` is not accepted - it would hide a typed step)."""
    t = (text or "").strip()
    return int(t) if t.isascii() and t.isdigit() else None


def step_to_points(lo: str, hi: str, step: str) -> str | None:
    """The point count with exactly the step grid of ``lo``..``hi`` (the step must reach Max), else None."""
    from decimal import Decimal, InvalidOperation
    try:
        a, b, s = Decimal(lo), Decimal(hi), Decimal(step)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if b < a:
        return None
    if b == a:
        return "1"
    if s <= 0:
        return None
    n = (b - a) / s
    return str(int(n) + 1) if n == n.to_integral_value() else None


def points_to_step(lo: str, hi: str, points: str) -> str | None:
    """The step size with exactly the ``points`` grid of ``lo``..``hi`` when it is a finite decimal, else None."""
    from decimal import Decimal, InvalidOperation
    n = parse_points(points)
    try:
        a, b = Decimal(lo), Decimal(hi)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if n is None or b < a or n < 1:
        return None
    if b == a:
        return points if n >= 1 else None
    if n < 2:
        return None
    s = (b - a) / (n - 1)
    q = s.quantize(Decimal(1).scaleb(-6))
    if q != s:                                   # thirds etc.: no finite step size gives this grid
        return None
    return format(s.normalize(), "f")


# new rows (2026-10-28): at. ratio and mass span 1.0-2.0 (formerly a fixed 1.0); at.% / wt.% keep 0-100 in steps of 10
RANGE_DEFAULTS = {"ratio": ("1.0", "2.0", "0.1"), "at": ("0", "100", "10"), "wt": ("0", "100", "10"),
                  "mass": ("1.0", "2.0", "0.1")}

SYSTEM_SIZE_HELP = ("System size (N) specifies the number of constituent elements in each generated alloy. "
                    "Multiple values of N may be selected. Only element combinations satisfying the "
                    "required-element constraints are included.")
WORKLOAD_HELP = [("Summarizes the valid composition count and estimated computational requirements. Runtime and "
                  "temporary disk usage depend on the workload and system performance. Actual resource usage "
                  "may vary."), "<a href='help://workload'>About workload estimates</a>"]


def size_note(n: int, workers: int) -> tuple[str, str]:
    """Tier label (Large set / Very large set) and the explanation: the tier message for large sets
    and the measured estimates of calculation time and temporary storage."""
    if not n:
        return "", ""
    tier, tip = describe(estimate(n, workers))
    return tier, tip


def coverage_status(coverage: dict | None) -> Status | None:
    """Footer warning when some models lack data for the chosen elements (engine.model_coverage)."""
    if not coverage:
        return None
    missing = [k for k, v in coverage.items() if v]
    if not missing:
        return None
    ok = [k for k, v in coverage.items() if not v]

    def names(keys):
        return keys[0] if len(keys) == 1 else ", ".join(keys[:-1]) + " and " + keys[-1]
    reasons = []
    for k in missing:
        r = coverage[k]
        if r not in reasons:
            reasons.append(r)
    text = (f"{names(missing)} {'is' if len(missing) == 1 else 'are'} unavailable for these elements: "
            + " ".join(reasons))
    if ok:
        text += f" {names(ok)} can still be evaluated."
    return Status("warning", "Partial model coverage",
                  [text, "<a href='help://models'>View model support</a>"], "Partial model coverage")


def check_symbol(text: str, data: Datasets, existing, current: str) -> tuple[str, str | None]:
    """Normalised element symbol and an error (or None) - the one element-entry rule of every composition table:
    a known element symbol that is not already in the composition."""
    new = text.strip()
    new = new[:1].upper() + new[1:].lower() if new else new
    if new == current:
        return new, None
    if not new:
        return new, "Enter an element symbol"
    if not data.is_element(new):
        return new, f"'{new}' is not an element symbol"
    if new in existing:
        return new, f"{new} is already in the composition"
    return new, None


class ColumnGrid:
    """Column widths shared by the three composition tables (single, sweep, expression).

    The design columns (element 64, value 88, lock 32 px, 1 px gaps) fit the 457 px panel, which is fixed by
    design; the grid is kept as the one place that sizes every tagged cell (``col_role`` property)."""

    DESIGN_PANEL = COMPOSITION_PANEL_WIDTH
    SINGLE_SPAN = COL_ELEMENT + 4 * COL_VALUE + 4 * COL_GAP     # 420 px of the 457 px panel
    PAD = 16
    PAD_MIN = 8

    def __init__(self):
        self.element, self.value, self.lock, self.pad = COL_ELEMENT, COL_VALUE, COL_LOCK, self.PAD

    def set_panel_width(self, width: int) -> bool:
        avail = min(self.SINGLE_SPAN, width - (self.DESIGN_PANEL - self.SINGLE_SPAN))
        s = avail / self.SINGLE_SPAN
        element = max(48, round(COL_ELEMENT * s))
        value = max(68, (avail - element - 4 * COL_GAP) // 4)
        lock = COL_LOCK
        pad = max(self.PAD_MIN, min(self.PAD, self.PAD - (COL_VALUE - value) // 2))
        new = (element, value, lock, pad)
        changed = new != (self.element, self.value, self.lock, self.pad)
        self.element, self.value, self.lock, self.pad = new
        return changed

    def width_of(self, role: str) -> int:
        return {"element": self.element, "value": self.value, "lock": self.lock}[role]

    def apply(self, root: QWidget) -> None:
        widgets = [root] + root.findChildren(QWidget)
        for w in widgets:
            role = w.property("col_role")
            if not role:
                continue
            w.setFixedWidth(self.width_of(role))
            if isinstance(w, Field):
                w.set_padding(self.pad if role == "value" else 4)
            elif isinstance(w, QLabel) and role in ("value", "element") and w.property("col_header"):
                w.setContentsMargins(self.pad, 0, 0, 0)
            elif isinstance(w, QRadioButton):
                compact = self.value < 80
                if bool(w.property("compact")) != compact:
                    w.setProperty("compact", compact)
                    refresh_style(w)


def col_role(w: QWidget, role: str) -> QWidget:
    w.setProperty("col_role", role)
    return w


def fmt(v: float | None, decimals: int) -> str:
    if v is None or not math.isfinite(v):
        return ""
    return f"{v:.{decimals}f}"


class Field(QLineEdit):
    """Carbon text input (sm, 32 px) with an ``invalid`` state.

    Its strokes - the 1 px bottom rule, the 2 px focus frame and the 2 px invalid frame - are painted in device
    pixels (``crisp``) over the field, never as QSS borders, so the text origin is identical in every state.
    The explanation of an invalid value is the footer's (``error`` keeps it for the footer)."""

    def __init__(self, width: int, parent=None, cell: str = "value"):
        super().__init__(parent)
        self.setFixedSize(width, ROW_H)
        self.setProperty("cell", cell)
        self.setProperty("crisp", True)
        self.error = ""
        col_role(self, "element" if width == COL_ELEMENT else "value")
        carbon_context_menu(self)        # Cut / Copy / Paste through the shared Carbon menu
        self.set_padding(4 if width == COL_ELEMENT else ColumnGrid.PAD)
        install_wheel_guard(self)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt name
        """Programmatic values (conversions, refreshes) show their beginning - the sign and the most significant
        digits - when wider than the field; a field being edited keeps the user's caret (2026-10-28)."""
        super().setText(text)
        if not self.hasFocus():
            self.setCursorPosition(0)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if e.reason() != Qt.FocusReason.PopupFocusReason:   # not for its own context menu
            self.deselect()
            self.setCursorPosition(0)

    def set_padding(self, pad: int) -> None:
        m = self.textMargins()
        if m.left() != pad or m.right() != pad:
            self.setTextMargins(pad, 0, pad, 0)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        r = self.rect()
        cell = self.property("cell")
        if self.property("invalid"):
            crisp.frame(p, r, FOCUS_WIDTH, t("support-error"))
        elif self.hasFocus() and not self.isReadOnly():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        elif not self.isEnabled() or self.isReadOnly():
            # read-only and disabled fields keep a visible bottom rule (field-border-quiet; Carbon would drop it on
            # disabled - an explicit product decision, 2026-10-28)
            crisp.hline_bottom(p, r, t("field-border-quiet"), HAIRLINE)
        else:
            crisp.hline_bottom(p, r, t("border-strong-01" if cell == "element-filled" else "border-strong-02"),
                               HAIRLINE)
        p.end()

    def set_invalid(self, invalid: bool, message: str = ""):
        self.error = message if invalid else ""
        if bool(self.property("invalid")) != invalid:
            self.setProperty("invalid", invalid)
            refresh_style(self)

    def number(self) -> float | None:
        return C.parse_number(self.text())


class _Rows(QWidget):
    """Vertical list of rows inside a scroll area that only scrolls when needed."""

    def __init__(self, parent=None, margin: int = 19):
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(margin, 0, 0, 0)
        self.lay.setSpacing(ROW_GAP)
        self.lay.addStretch(1)

    def insert(self, w: QWidget):
        self.lay.insertWidget(self.lay.count() - 1, w)

    def order(self, widgets: list[QWidget]) -> None:
        for i, w in enumerate(widgets):
            self.lay.removeWidget(w)
            self.lay.insertWidget(i, w)


class FadeOverlay(QWidget):
    """Bottom fade over a scroll viewport when rows overflow (Figma band "Rectangle 275")."""

    def __init__(self, area: QScrollArea):
        super().__init__(area)
        self.area = area
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(24)
        area.verticalScrollBar().rangeChanged.connect(lambda *_: self._sync())
        area.verticalScrollBar().valueChanged.connect(lambda *_: self._sync())
        area.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == ev.Type.Resize:
            self._sync()
        return False

    def _sync(self):
        sb = self.area.verticalScrollBar()
        vw = self.area.viewport()
        self.setGeometry(0, vw.height() - 24, vw.width(), 24)
        self.setVisible(sb.maximum() > 0 and sb.value() < sb.maximum())
        self.raise_()

    def paintEvent(self, _e):
        from PySide6.QtGui import QColor, QLinearGradient
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        c0 = QColor(t("layer-01"))
        c0.setAlpha(0)
        g.setColorAt(0, c0)
        g.setColorAt(1, QColor(t("layer-01")))
        p.fillRect(self.rect(), g)
        p.end()


def scroll_wrap(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    thin_scrollbars(sa)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    own_wheel(sa)
    sa.setWidget(inner)
    sa.fade = FadeOverlay(sa)
    return sa


def element_field(element: str) -> Field:
    """The editable element-symbol cell shared by Single composition and Composition space."""
    f = Field(COL_ELEMENT, cell="element")
    f.setText(element)
    f.setMaxLength(2)
    f.setAccessibleName("Element symbol")
    return f


def row_context_actions(view, row) -> None:
    """Right-click on a committed row's text inputs: the standard text actions, then "Remove element" (danger).
    The action resolves its row by identity when it is chosen (the symbol may have been renamed meanwhile), and
    removes it through the panel's shared removal path - exactly a periodic-table deselection."""
    def extra():
        return [("Remove element", lambda: view.remove_row(row), True)]
    fields = [row.el] + (list(row.fields.values()) if hasattr(row, "fields") else [row.min, row.max, row.step])
    for f in fields:
        f.context_extra = extra


class SymbolKeys(QObject):
    """The one keyboard / focus lifecycle of every element-symbol field - committed rows and the Add element draft
    alike (``RowEditing``):

    * Enter commits the field (rename, removal of a cleared symbol, or the draft's new element) and, when that is
      valid, opens the blank draft directly under the row, focused - from any row, however it was added;
    * Escape cancels: a committed field returns to its element, the draft is discarded;
    * leaving the field decides it (after the event, so a click on Add element can re-focus the draft first).

    Intermediate empty states (select-all + typing, paste, IME composition) are never decisions: only Enter or a real
    focus loss confirms what the field holds."""

    def __init__(self, view, row):
        super().__init__(row)
        self.view, self.row = view, row
        row.el.installEventFilter(self)
        row.el.textEdited.connect(lambda _t: view._symbol_typing(row))

    def eventFilter(self, obj, ev):
        et = ev.type()
        read_only = getattr(obj, "isReadOnly", None)      # absent while the field is being destroyed
        if read_only is None or read_only():
            return False
        if et == QEvent.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.view.symbol_enter(self.row)
                return True
            if ev.key() == Qt.Key.Key_Escape:
                self.view.symbol_escape(self.row)
                return True
        elif et == QEvent.Type.FocusOut and ev.reason() not in (Qt.FocusReason.PopupFocusReason,
                                                                Qt.FocusReason.ActiveWindowFocusReason):
            QTimer.singleShot(0, self, self._blurred)
        return False

    def _blurred(self):
        row = self.row
        if row.el.hasFocus():
            return
        if row is self.view.draft:
            if not row.el.text().strip():
                self.view.discard_draft()
            else:
                self.view._commit_draft(row, next_row=False)
        # committed rows: QLineEdit.editingFinished (emitted on a real focus loss) runs _element_edited


class GridKeys(QObject):
    """Keyboard navigation between the numeric cells of a composition table (2026-10-28).

    * Single composition - Enter commits the field and moves to the editable field below in the same column;
      Up / Down move to the editable field above / below in the same column.
    * Composition space - Enter moves to the next editable cell (Min, Max, Step, then the next row); Up / Down move
      within the column; Ctrl+Left / Ctrl+Right move between Min, Max and Step of the row.

    Read-only, disabled and draft cells are skipped.  A key with no target cell keeps its ordinary meaning (Enter
    still commits; Left / Right without Ctrl always edit the text).  Moving focus is the commit: the field's own
    ``editingFinished`` and validation run as on any focus change.  Lock toggles are never reached."""

    def __init__(self, view, row_major: bool):
        super().__init__(view)
        self.view, self.row_major = view, row_major

    def watch(self, fields) -> None:
        for f in fields:
            f.installEventFilter(self)

    @staticmethod
    def editable(f) -> bool:
        return f.isEnabled() and not f.isReadOnly() and f.isVisible() and f.focusPolicy() != Qt.FocusPolicy.NoFocus

    def _locate(self, obj):
        grid = self.view.nav_grid()
        for r, cells in enumerate(grid):
            for c, f in enumerate(cells):
                if f is obj:
                    return grid, r, c
        return grid, -1, -1

    def target(self, obj, key, mods):
        grid, r, c = self._locate(obj)
        if r < 0:
            return None
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not ctrl:
            step = -1 if key == Qt.Key.Key_Up else 1
            rr = r + step
            while 0 <= rr < len(grid):
                if c < len(grid[rr]) and self.editable(grid[rr][c]):
                    return grid[rr][c]
                rr += step
            return None
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ctrl:
            if not self.row_major:                       # the field below, same column
                return self.target(obj, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
            flat = [f for cells in grid for f in cells]
            i = flat.index(obj)
            return next((f for f in flat[i + 1:] if self.editable(f)), None)
        if self.row_major and ctrl and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -1 if key == Qt.Key.Key_Left else 1
            cc = c + step
            while 0 <= cc < len(grid[r]):
                if self.editable(grid[r][cc]):
                    return grid[r][cc]
                cc += step
            return None
        return None

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.KeyPress:
            return False
        read_only = getattr(obj, "isReadOnly", None)      # absent while the field is being destroyed
        if read_only is None or read_only():
            return False
        tgt = self.target(obj, ev.key(), ev.modifiers())
        if tgt is None:
            return False
        tgt.setFocus(Qt.FocusReason.TabFocusReason)       # selects the value, like Tab; the old field commits
        tgt.selectAll()
        sa = getattr(self.view, "scroll", None)
        if sa is not None:
            sa.ensureWidgetVisible(tgt, 0, 8)
        return True


class RowEditing:
    """Element rows of a composition table (Single composition, Composition space): symbol editing, removal and the
    Add element *draft* row.

    The draft is not a composition row: it is never in ``rows``, so it never reaches a status count, a recipe, a
    system-size enumeration or a calculation.  It has every column of a committed row (blank, read-only text inputs)
    and sits under its *anchor* (``draft_after``: the row Enter was pressed in; None = the end).  Enter commits its
    symbol through the panel's periodic-table path (``add_element``, inserted after the anchor) and leaves a new blank
    draft under the new row; an empty draft that loses the focus, or Escape, discards it; a non-empty one that loses
    the focus is committed (or keeps its validation error).  There is never more than one draft.

    Clearing a committed symbol and confirming it (Enter or leaving the field) removes the element through the
    shared removal path - the periodic-table deselection - instead of reporting an empty symbol."""

    draft = None
    draft_after: str | None = None
    add_element_cb = None          # the panel's add_element(symbol, after=None) -> bool
    remove_element_cb = None       # the panel's remove_element(symbol) -> bool
    focus_add_cb = None            # focus the Add element button (Escape)

    def _new_draft_row(self):      # pragma: no cover - provided by the view
        raise NotImplementedError

    def symbols_editable(self) -> bool:
        return True

    # ---------------------------------------------------------------- draft placement
    def _ordered_rows(self) -> list:
        rows = list(self.rows.values())
        if self.draft is not None:
            anchor = self.rows.get(self.draft_after) if self.draft_after else None
            rows.insert(rows.index(anchor) + 1 if anchor is not None else len(rows), self.draft)
        return rows

    def _place_rows(self) -> None:
        self.rows_widget.order(self._ordered_rows())

    def open_draft(self, after: str | None = None) -> None:
        """The blank row under ``after`` (None: under the last row), focused; the existing draft is moved, never
        duplicated."""
        self.draft_after = after if after in self.rows else None
        if self.draft is None:
            row = self._new_draft_row()
            row.el.setAccessibleName("New element symbol")
            row.el.setReadOnly(False)
            row.el.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.grid.apply(row)
            row.keys = SymbolKeys(self, row)
            self.rows_widget.insert(row)
            self.draft = row
            self.rows_stack.setCurrentIndex(1)
        row = self.draft
        self._place_rows()
        row.el.setFocus(Qt.FocusReason.OtherFocusReason)
        row.el.setCursorPosition(len(row.el.text()))
        QTimer.singleShot(0, row, lambda: self.scroll.ensureWidgetVisible(row, 0, 0))

    def discard_draft(self, focus_add: bool = False) -> None:
        row, self.draft = self.draft, None
        self.draft_after = None
        if row is None:
            return
        if self.element_error and self.element_error[0] is row:
            self.element_error = None
        retire(row)
        self.rows_stack.setCurrentIndex(1 if self.rows else 0)
        self.changed.emit()
        if focus_add and self.focus_add_cb is not None:
            self.focus_add_cb()

    def _symbol_typing(self, row) -> None:
        if row.el.property("invalid"):
            row.el.set_invalid(False)
            if self.element_error and self.element_error[0] is row:
                self.element_error = None
            self.changed.emit()

    def _commit_draft(self, row, next_row: bool) -> None:
        if self.draft is not row or not row.el.text().strip():
            return                                    # Enter on an empty draft does nothing
        new, error = check_symbol(row.el.text(), self.data, set(self.rows), "")
        if error:
            row.el.set_invalid(True, error)
            self.element_error = (row, error)
            self.changed.emit()
            return
        row.el.set_invalid(False)
        if self.element_error and self.element_error[0] is row:
            self.element_error = None
        if self.add_element_cb is None or not self.add_element_cb(new, after=self.draft_after):
            return
        if next_row:                                  # keyboard flow: the next blank row under the new one
            row.el.clear()
            self.open_draft(after=new)
        else:
            self.discard_draft()

    # ---------------------------------------------------------------- committed symbols
    def symbol_enter(self, row) -> None:
        if row is self.draft:
            self._commit_draft(row, next_row=True)
            return
        if self.rows.get(row.element) is not row or not self.symbols_editable():
            return
        if not row.el.text().strip():
            self._remove_cleared(row, focus_next=True)
            return
        if self._element_edited(row):                 # unchanged, or a valid rename: continue under this row
            self.open_draft(after=row.element)

    def symbol_escape(self, row) -> None:
        if row is self.draft:
            self.discard_draft(focus_add=True)
            return
        row.el.setText(row.element)                   # cancel the edit: the committed symbol again
        row.el.set_invalid(False)
        if self.element_error and self.element_error[0] is row:
            self.element_error = None
        self.changed.emit()

    def _remove_cleared(self, row, focus_next: bool = False) -> None:
        """A committed symbol cleared and confirmed: remove the element (periodic-table path), not an error."""
        row.el.set_invalid(False)
        if self.element_error and self.element_error[0] is row:
            self.element_error = None
        order = list(self.rows.values())
        nxt = None
        if focus_next and row in order:
            i = order.index(row)
            nxt = order[i + 1] if i + 1 < len(order) else (order[i - 1] if i > 0 else None)

        def remove():
            if self.remove_row(row) and nxt is not None and self.rows.get(nxt.element) is nxt:
                nxt.el.setFocus(Qt.FocusReason.OtherFocusReason)
        QTimer.singleShot(0, row, remove)         # after the field's own signal: the row is retired by the removal

    def _element_edited(self, row) -> bool:
        """A committed symbol confirmed (Enter, or leaving the field): unchanged or a valid rename -> True; a cleared
        symbol removes the element; an unknown / duplicate symbol keeps the existing validation (False)."""
        if self.rows.get(row.element) is not row:
            return False                              # retired meanwhile (removed, or the edit of a stale row)
        if not row.el.text().strip():
            self._remove_cleared(row)
            return False
        others = {e for e in self.rows if e != row.element}
        new, error = check_symbol(row.el.text(), self.data, others, row.element)
        if error:
            row.el.set_invalid(True, error)
            self.element_error = (row, error)
            self.changed.emit()
            return False
        row.el.set_invalid(False)
        if self.element_error and self.element_error[0] is row:
            self.element_error = None
        if new != row.element:
            self.element_renamed.emit(row.element, new)
        elif row.el.text() != new:
            row.el.setText(new)                       # "fe" typed over Fe: the canonical symbol again
        self.changed.emit()
        return True

    def remove_row(self, row) -> bool:
        """Context menu "Remove element" / a cleared symbol: the row, resolved by identity (never by position or a
        stale symbol)."""
        if self.rows.get(row.element) is not row or self.remove_element_cb is None:
            return False
        return self.remove_element_cb(row.element)


# ======================================================================== single composition
class SingleRow(QWidget):
    def __init__(self, element: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(COL_GAP)
        self.element = element
        self.el = element_field(element)
        lay.addWidget(self.el)
        self.fields: dict[str, Field] = {}
        for rep in REP_KEYS:
            f = Field(COL_VALUE)
            f.setAccessibleName(f"{element} {C.REPRESENTATION_LABELS[rep]}")
            lay.addWidget(f)
            self.fields[rep] = f
        lay.addStretch(1)
        self.setFixedHeight(ROW_H)


class SingleView(QWidget, RowEditing):
    committed = Signal(str)               # a finished user edit (Undo / Redo: CompositionPanel.edit_committed)

    grid = ColumnGrid()          # replaced by the panel's shared grid
    changed = Signal()
    element_renamed = Signal(str, str)  # old, new
    message = Signal(str, str)          # kind, text (action results for the window notification)
    total_mass_committed = Signal(float)

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        self.input_rep = "ratio"         # active input column (or "element")
        # quantity basis of ``values`` (ratio / at / wt / mass): the last numeric input column.  Activating El.
        # changes only which column is editable, never the basis or the values.
        self.value_rep = "ratio"
        self.values: dict[str, float | None] = {}  # values in ``value_rep``, full precision
        # at.% / wt.%: the first committed element is the balance (100 - the others), like Thermo-Calc's
        # "balance" element; ``excess`` is the amount by which the others exceed 100 % (invalid, never clamped)
        self.excess: float | None = None
        # auto-equal ("pristine") until the user edits a value: while pristine every selection change gives
        # each element the equal share of the active column (ratio 1, at.% / wt.% 100/N, mass total/N); once
        # edited, selecting or removing an element never redistributes the user's values
        self.pristine = True
        # entered fields the user left empty (2026-10-28): an empty amount is 0 - for the live conversion of every
        # other column and for the calculation (the engine drops a zero amount, the same as leaving it out) - while
        # the field itself stays visibly empty (placeholder "0").  Text that is not a number stays invalid.
        self.blank: set[str] = set()
        self.total_mass = DEFAULT_TOTAL_MASS
        self.rows: dict[str, SingleRow] = {}
        self.notice: Status | None = None     # a one-off explanation (input column switch)
        self.element_error: tuple[SingleRow, str] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Input column radio group (Figma: label-01 at y 76, radios at y 102, divider at y 130)
        radios = QWidget()
        radios.setFixedHeight(74)
        rl = QVBoxLayout(radios)
        rl.setContentsMargins(20, 12, 0, 18)
        rl.setSpacing(8)
        lab = QLabel("Input column")
        lab.setObjectName("Label01")
        lab.setFixedHeight(16)
        rl.addWidget(lab)
        rr = QHBoxLayout()
        rr.setSpacing(COL_GAP)
        rr.setContentsMargins(0, 0, 0, 0)
        self.radio_group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        for i, (key, width) in enumerate((("element", COL_ELEMENT), ("ratio", COL_VALUE), ("at", COL_VALUE),
                                           ("wt", COL_VALUE), ("mass", COL_VALUE))):
            rb = QRadioButton(C.REPRESENTATION_LABELS[key])
            rb.setFixedSize(width, 20)
            col_role(rb, "element" if key == "element" else "value")
            rb.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            rb.setCursor(Qt.CursorShape.PointingHandCursor)
            self.radio_group.addButton(rb, i)
            self.radios[key] = rb
            rr.addWidget(rb)
        rr.addStretch(1)
        rl.addLayout(rr)
        self.radios["ratio"].setChecked(True)
        self.radio_group.idClicked.connect(self._radio)
        root.addWidget(radios)
        root.addWidget(Divider())

        self.rows_widget = _Rows()
        self.scroll = scroll_wrap(self.rows_widget)
        self.empty = EmptyState("Start by selecting elements", "Click elements in the periodic table.",
                                art="magnifier")
        self.rows_stack = QStackedWidget()
        self.rows_stack.addWidget(self.empty)
        self.rows_stack.addWidget(self.scroll)
        root.addWidget(self.rows_stack, 1)

        # Totals (Figma: divider at y 356, total row 373-405, then the footer at y 433)
        totals = QWidget()
        totals.setFixedHeight(77)
        tl = QVBoxLayout(totals)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.addWidget(Divider())
        trow = QHBoxLayout()
        trow.setContentsMargins(19, 16, 0, 28)
        trow.setSpacing(COL_GAP)
        tot_lab = col_role(QLabel("Total:"), "element")
        tot_lab.setFixedSize(COL_ELEMENT, ROW_H)
        tot_lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tot_lab.setStyleSheet("font-weight: 600;")
        trow.addWidget(tot_lab)
        self.totals: dict[str, QLabel | Field] = {}
        for rep in REP_KEYS:
            if rep == "mass":
                f = Field(COL_VALUE, cell="total")
                f.setText(format_mass(self.total_mass))
                f.setAccessibleName("Total mass (g)")
                f.editingFinished.connect(self._total_mass_edited)
                self.totals[rep] = f
                trow.addWidget(f)
            else:
                lab = col_role(QLabel(""), "value")
                lab.setFixedSize(COL_VALUE, ROW_H)
                lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.totals[rep] = lab
                trow.addWidget(lab)
        trow.addStretch(1)
        tl.addLayout(trow)
        root.addWidget(totals)
        self._apply_editability()

    # ---------------------------------------------------------------- elements
    def set_elements(self, elements: list[str]):
        current = list(self.rows)
        for el in current:
            if el not in elements:
                row = self.rows.pop(el)
                if self.element_error and self.element_error[0] is row:
                    self.element_error = None
                retire(row)
                self.values.pop(el, None)
                self.blank.discard(el)
        for el in elements:
            if el not in self.rows:
                row = SingleRow(el)
                self.grid.apply(row)
                self._wire(row)
                self.rows[el] = row
                self.rows_widget.insert(row)
                self.values[el] = 1.0 if self.value_rep == "ratio" else 0.0
        # keep visual order equal to selection order (an Add element draft stays under its anchor row)
        self.rows = {el: self.rows[el] for el in elements}
        self._place_rows()
        self.values = {el: self.values.get(el) for el in elements}
        if not elements:
            self.pristine = True                 # an empty composition starts over
        elif self.pristine:
            self.values = self._equal(elements)
        self.rows_stack.setCurrentIndex(1 if elements or self.draft else 0)
        self._apply_editability()
        self.refresh()

    def nav_grid(self) -> list[list]:
        """The numeric cells, by committed row (the draft has none to edit) and column (GridKeys)."""
        return [list(row.fields.values()) for row in self.rows.values()]

    def _wire(self, row: SingleRow):
        if not hasattr(self, "grid_keys"):
            self.grid_keys = GridKeys(self, row_major=False)
        self.grid_keys.watch(row.fields.values())
        for rep, f in row.fields.items():
            f.textEdited.connect(lambda _txt, r=row, rp=rep: self._edited(r.element, rp))
            f.editingFinished.connect(lambda r=row: self._value_committed(r))
        row.el.editingFinished.connect(lambda r=row: self._element_edited(r))
        row.keys = SymbolKeys(self, row)
        row_context_actions(self, row)

    def symbols_editable(self) -> bool:
        return self.input_rep == "element"

    def _new_draft_row(self) -> SingleRow:
        row = SingleRow("")
        for rep, f in row.fields.items():
            # every column is there (the committed row's geometry); blank and read-only until the symbol is committed
            f.setReadOnly(True)
            f.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            f.setAccessibleName(f"New element {C.REPRESENTATION_LABELS[rep]}")
        return row

    def open_draft(self, after: str | None = None) -> None:
        """Add element: the blank row, typed in the El. column (activated without changing the basis)."""
        if self.input_rep != "element":
            self.radios["element"].setChecked(True)
            self._radio(0)
        RowEditing.open_draft(self, after)

    # ---------------------------------------------------------------- state
    @property
    def numeric_rep(self) -> str:
        return self.value_rep

    def balance_element(self) -> str | None:
        """The balance element of an at.% / wt.% composition: the first committed element (None otherwise)."""
        if self.value_rep in ("at", "wt") and self.rows:
            return next(iter(self.rows))
        return None

    def _rebalance(self) -> None:
        """balance = 100 - sum(others).  Others above 100 % make it invalid (``excess``): nothing is clamped or
        rescaled, and the calculation is blocked until the user corrects them.  Only floating-point residue below
        1e-9 % is read as 0."""
        self.excess = None
        b = self.balance_element()
        if b is None:
            return
        others = [v for el, v in self.values.items() if el != b]
        f = self.rows[b].fields[self.value_rep]
        if any(v is None for v in others):
            self.values[b] = None                # unknown until every other amount is valid
            f.set_invalid(False)
            return
        rest = 100.0 - math.fsum(others)
        if rest < 0 and rest > -1e-9:
            rest = 0.0
        if rest < 0:
            self.values[b] = None
            self.excess = -rest
            f.set_invalid(True, "Composition exceeds 100%")
        else:
            self.values[b] = rest
            f.set_invalid(False)

    def _equal(self, elements) -> dict[str, float]:
        return C.set_equal(list(elements), self.numeric_rep, total_mass=self.total_mass)

    def snapshot(self) -> dict:
        """The editable state (Undo of Clear composition): input column, basis, values, batch mass, auto-equal."""
        return {"input_rep": self.input_rep, "value_rep": self.value_rep, "values": dict(self.values),
                "total_mass": self.total_mass, "pristine": self.pristine, "blank": sorted(self.blank)}

    def restore(self, snap: dict) -> None:
        """Re-apply :meth:`snapshot` after the rows exist again (the panel restores the element selection)."""
        self.input_rep = snap["input_rep"]
        self.value_rep = snap.get("value_rep", "ratio" if self.input_rep == "element" else self.input_rep)
        self.radios[self.input_rep].setChecked(True)
        self.total_mass = snap["total_mass"]
        self.values = {el: snap["values"].get(el) for el in self.rows}
        self.blank = {el for el in snap.get("blank", ()) if el in self.rows}
        self.pristine = snap["pristine"]
        self.notice = None
        for row in self.rows.values():
            for f in row.fields.values():
                f.set_invalid(False)
        self._apply_editability()
        self.refresh()
        self.changed.emit()

    def _radio(self, idx: int):
        key = ("element", "ratio", "at", "wt", "mass")[idx]
        if key == self.input_rep:
            return
        self.notice = None
        if key == "element" or key == self.value_rep:
            # El. only makes the symbols editable: the basis and the values are kept as they are
            self.input_rep = key
            self._apply_editability()
            self.refresh()
            self.changed.emit()
            return
        # switch the input column without changing the composition: adopt the computed values
        reps = self._representations()
        self.blank.clear()
        if reps is not None:
            self.values = dict(reps[key])
        else:
            self.values = {el: None for el in self.rows}
            self.notice = Status("warning", "Enter values in the new input column",
                                 "The previous column contained invalid values, so they could not be converted.")
        self.input_rep = self.value_rep = key
        for row in self.rows.values():
            for f in row.fields.values():
                f.set_invalid(False)
        self._apply_editability()
        self.refresh()
        self.changed.emit()
        self.committed.emit("Change input column")

    def _apply_editability(self):
        rep = self.input_rep
        balance = self.balance_element()
        for el, row in self.rows.items():
            row.el.setReadOnly(rep != "element")
            row.el.setFocusPolicy(Qt.FocusPolicy.StrongFocus if rep == "element" else Qt.FocusPolicy.NoFocus)
            for r, f in row.fields.items():
                f.setReadOnly(r != rep)
                f.setFocusPolicy(Qt.FocusPolicy.StrongFocus if r == rep else Qt.FocusPolicy.ClickFocus)
                is_balance = el == balance and r == self.value_rep
                # the balance amount is computed, never typed.  In its own column while that column is the active
                # input (at.% / wt.%) it is truly disabled - the one field of the editable column you cannot edit;
                # in any other state (El., or another column active) it is read-only like every inactive field.
                f.setEnabled(not (is_balance and rep == self.value_rep))
                f.setAccessibleDescription(
                    "Balance element: 100 % minus the other elements" if is_balance else "")
            refresh_style(row.el)
        mass_total = self.totals["mass"]
        mass_total.setReadOnly(rep == "mass")

    def _edited(self, el: str, rep: str):
        if rep != self.numeric_rep or self.input_rep == "element" or el not in self.rows \
                or el == self.balance_element():
            return
        self.notice = None
        self.pristine = False                    # the user's values are kept from now on
        f = self.rows[el].fields[rep]
        v = f.number()
        self.blank.discard(el)
        if f.text().strip() == "":
            self.values[el] = 0.0                # empty is zero: the other columns keep converting
            self.blank.add(el)
            f.setPlaceholderText("0")
            f.set_invalid(False)
        elif v is None:
            self.values[el] = None
            f.set_invalid(True, f"{el}: enter a number")
        elif not math.isfinite(v):
            self.values[el] = None               # never read as zero
            f.set_invalid(True, f"{el}: enter a finite number")
        elif v < 0:
            self.values[el] = None
            f.set_invalid(True, f"{el}: value must be ≥ 0")
        else:
            self.values[el] = v
            f.set_invalid(False)
        self.refresh(skip=(el, rep))
        self.changed.emit()

    def _value_committed(self, row: SingleRow):
        if self.input_rep == "mass" and self._representations() is not None:
            self.total_mass_committed.emit(self.total_mass)
        self.committed.emit(f"Edit {row.element} amount")

    def rename(self, old: str, new: str, order: list[str]):
        """Replace ``old`` by ``new`` keeping its value (called by the panel after selection sync)."""
        row = self.rows.pop(old)
        row.element = new
        row.el.setText(new)
        for rep, f in row.fields.items():
            f.setAccessibleName(f"{new} {C.REPRESENTATION_LABELS[rep]}")
        self.rows[new] = row
        self.values[new] = self.values.pop(old, None)
        if old in self.blank:
            self.blank.discard(old)
            self.blank.add(new)
        self.set_elements(order)

    def set_total_mass(self, grams: float) -> None:
        """The persisted batch mass (preference); updates the Mass column, never a scientific value."""
        g = valid_mass(grams)
        if g is None:
            return
        self.total_mass = g
        f = self.totals["mass"]
        f.set_invalid(False)
        if not f.hasFocus():
            f.setText(format_mass(g))
        if self.input_rep == "mass" and self.values and all(v is not None for v in self.values.values()):
            s = sum(self.values.values())
            if s > 0:                   # mass input: rescale the batch, same composition
                self.values = {el: v * g / s for el, v in self.values.items()}
        self.refresh()
        self.changed.emit()

    def _total_mass_edited(self):
        f = self.totals["mass"]
        if f.isReadOnly() or (not f.text().strip() and not self.rows):
            return
        v = f.number()
        if v is None or v <= 0 or not math.isfinite(v):
            f.set_invalid(True, "Total mass must be > 0 g")
            self.changed.emit()
            return
        f.set_invalid(False)
        self.total_mass = v
        self.refresh()
        self.total_mass_committed.emit(v)
        self.changed.emit()
        self.committed.emit("Edit total mass")

    def _representations(self):
        vals = self.values
        if not vals or any(v is None for v in vals.values()) or sum(vals.values()) <= 0:
            return None
        try:
            return C.all_representations(dict(vals), self.numeric_rep, total_mass=self.total_mass, datasets=self.data)
        except ValueError:
            return None

    def column_sum(self) -> float | None:
        raw = [v for v in self.values.values() if v is not None]
        return sum(raw) if raw and len(raw) == len(self.values) else None

    def sum_off(self) -> bool:
        """at.% / wt.% input whose other elements exceed 100 %, leaving the balance element negative (Figma State:
        "Composition sum ≠ 100%"; with a balance element the column otherwise always sums to 100)."""
        return self.numeric_rep in ("at", "wt") and self.excess is not None

    def refresh(self, skip: tuple | None = None):
        self._rebalance()
        reps = self._representations()
        active = self.numeric_rep
        balance = self.balance_element()
        for el, row in self.rows.items():
            for rep, f in row.fields.items():
                if skip == (el, rep):
                    continue
                if rep == active:
                    if el == balance and self.excess is not None:
                        f.setText(fmt(-self.excess, DECIMALS[rep]))   # shown as computed: negative, not clamped
                        f.setCursorPosition(0)       # the sign stays in view when the text is wider than the field
                    elif el == balance and self.values.get(el) is None:
                        f.setText("")
                    elif el in self.blank and el != balance:
                        if f.text():
                            f.setText("")                # left empty by the user: it stays empty (0)
                    elif not f.hasFocus():
                        v = self.values.get(el)
                        f.setText(fmt(v, DECIMALS[rep]) if v is not None else f.text())
                    continue
                f.setText(fmt(reps[rep][el], DECIMALS[rep]) if reps else "")
        # totals
        if reps is None:
            s = self.column_sum()
            if self.excess is not None:
                s = 100.0 + self.excess                  # the column as typed: the others alone exceed 100 %
            for rep in ("ratio", "at", "wt"):
                lab = self.totals[rep]
                if rep == active and s is not None:
                    lab.setText(f"{s:.2f}" if rep == "ratio" else f"{s:.4g}%")
                else:
                    lab.setText("—")
        else:
            self.totals["ratio"].setText(f"{sum(reps['ratio'].values()):.2f}")
            self.totals["at"].setText(f"{sum(self.values.values()):.4g}%" if active == "at"
                                      else f"{sum(reps['at'].values()):.4g}%")
            self.totals["wt"].setText(f"{sum(self.values.values()):.4g}%" if active == "wt"
                                      else f"{sum(reps['wt'].values()):.4g}%")
            if active == "mass":
                self.total_mass = sum(reps["mass"].values())
        mt = self.totals["mass"]
        mt.setPlaceholderText("Total mass")
        if not self.rows:
            for rep in ("ratio", "at", "wt"):
                self.totals[rep].setText("0.00")
        if not mt.hasFocus():
            mt.setText(format_mass(self.total_mass))
        off = self.sum_off()
        for rep in ("at", "wt"):
            lab = self.totals[rep]
            bad = rep == active and off
            # the total cell is framed like an invalid field (Figma: red 2 px frame around "95%")
            lab.setStyleSheet(f"border: 2px solid {t('support-error')};" if bad else "")

    # ---------------------------------------------------------------- status (footer)
    def status(self) -> Status | None:
        if self.element_error:
            return Status("error", self.element_error[1])
        if not self.rows:
            return None
        balance = self.balance_element()
        if self.sum_off():
            unit = "at.%" if self.numeric_rep == "at" else "wt.%"
            return Status("error", "Composition exceeds 100%",
                          f"The elements other than {balance} add up to {100.0 + self.excess:.4f} {unit}. {balance} "
                          f"is the balance element (100 % minus the others), so they must not exceed 100 %. "
                          f"Nothing is rescaled: reduce the other amounts.")
        bad = [row.fields[self.numeric_rep] for el, row in self.rows.items()
               if el != balance and row.fields[self.numeric_rep].error]
        if bad or any(v is None for v in self.values.values()):
            msg = bad[0].error if len(bad) == 1 else "Missing or invalid values"
            return Status("error", msg[:1].upper() + msg[1:])
        if self.totals["mass"].error:
            return Status("error", self.totals["mass"].error)
        if len(self.rows) < 2:
            return Status("info", "Select at least two elements")
        if sum(self.values.values()) <= 0:
            return Status("error", "Total is zero")
        if sum(1 for v in self.values.values() if v > 0) < 2:
            return Status("error", "At least two elements need non-zero amounts")
        return self.notice

    def can_calculate(self) -> bool:
        st = self.status()
        return len(self.rows) >= 2 and (st is None or not st.blocking)

    # ---------------------------------------------------------------- actions
    def can_set_equal(self) -> bool:
        return self.input_rep != "element" and bool(self.rows)

    def set_equal(self):
        self.notice = None
        self.blank.clear()
        self.values = self._equal(self.rows)
        self.pristine = True                     # equal again: later selections stay equal
        for row in self.rows.values():
            for f in row.fields.values():
                f.set_invalid(False)
        self.refresh()
        self.changed.emit()
        self.committed.emit("Set equal")

    def composition(self):
        """Return (name, amounts as atomic ratios) or raise ValueError with a user message."""
        st = self.status()
        if len(self.rows) < 2:
            raise ValueError("Select at least two elements.")
        if st is not None and st.blocking:
            raise ValueError(st.text + ".")
        x = C.to_fractions(dict(self.values), self.numeric_rep, self.data)
        ratios = C.from_fractions(x, "ratio")
        return self.display_name(ratios), ratios

    def display_name(self, ratios: dict) -> str:
        """The result's label: at.% / wt.% input -> the entered percentages with their basis ("Cr12Mn20 (at.%)");
        at. ratio / mass / El. -> the conventional atomic-ratio formula.  The calculation uses ``ratios`` either way."""
        if self.value_rep in ("at", "wt"):
            return C.basis_name(self.values, self.value_rep)
        return C.alloy_name(ratios)

    def input_meta(self) -> dict:
        """What the run records about the entry (run ``source``): the basis and the entered values."""
        return {"input_basis": self.value_rep,
                "input_values": {el: v for el, v in self.values.items() if v is not None}}

    def table_tsv(self) -> str:
        """The composition table (every representation) as Excel-pastable text (Calculate menu: Copy table)."""
        reps = self._representations()
        head = ["Element"] + [C.REPRESENTATION_LABELS[r] + (" (g)" if r == "mass" else "") for r in REP_KEYS]
        lines = ["\t".join(head)]
        for el in self.rows:
            vals = [fmt(reps[r][el], DECIMALS[r]) if reps else "" for r in REP_KEYS]
            lines.append("\t".join([el] + vals))
        return "\r\n".join(lines) + "\r\n"

    def clear(self):
        self.notice = None
        self.pristine = True
        self.blank.clear()
        self.values = self._equal(self.rows)
        for row in self.rows.values():
            for f in row.fields.values():
                f.set_invalid(False)
        self.refresh()


# ======================================================================== shared bits
class Toggle(QAbstractButton):
    """Carbon toggle, small (32 × 16): checked track uses support-success, unchecked border-strong."""

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(32, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.mixed = False

    def paintEvent(self, _e):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        on = self.isChecked()
        track = QColor(t("support-success") if on else t("border-strong-02"))
        if not self.isEnabled():
            track = QColor(t("border-disabled"))
        if self.mixed:
            track = QColor(t("border-strong-01"))
        path = QPainterPath()
        pill = r.height() / 2           # toggle track is a pill, not the CORNER_RADIUS token
        path.addRoundedRect(r, pill, pill)
        p.fillPath(path, track)
        knob = QRectF(r.right() - 14, 2, 12, 12) if on else QRectF(2, 2, 12, 12)
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(knob)
        if self.hasFocus():
            crisp.frame(p, self.rect(), FOCUS_WIDTH, t("focus"), pill)
        p.end()


class LockToggle(Toggle):
    """Lock of a Composition space row (Figma Composition space bases 393:66042): a 32 × 32 ghost icon toggle -
    ``locked--filled`` = required (checked), ``unlocked`` = optional; hover ``layer-hover-01``, 2 px focus frame,
    ``icon-disabled`` while disabled; the All row's mixed state shows ``unlocked``."""

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(checked, parent)
        self.setFixedSize(32, 32)
        self.toggled.connect(self._sync_name)
        self._sync_name()

    def _sync_name(self, *_):
        self.setAccessibleDescription(self.toolTip())

    def toolTip(self) -> str:                    # noqa: N802 - Qt name; read by the tooltip controller
        """The lock's meaning in its *current* state (an icon alone does not say what locking does); computed, so
        a state set without a signal (the All row) never shows an outdated text."""
        if self.mixed:
            return "Some elements are required. Click to require all."
        if self.isChecked():
            return "Required: in every alloy. Click to make it optional."
        return "Optional: alloys with and without it. Click to require it."

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        from PySide6.QtCore import QRectF
        from .. import icons
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        # The 1 px bottom border belongs to the LockCell under this toggle (Figma: the ghost button's border-bottom,
        # like the fields beside it).  The toggle covers the whole cell and paints after it, so its hover fill and
        # focus frame stop above that line's device rows - otherwise hover / focus erased the line.
        deco = QRectF(r)
        if isinstance(self.parentWidget(), LockCell) and self.geometry().bottom() == self.parentWidget().rect().bottom():
            deco.setHeight(r.height() - crisp.device_inset(p, HAIRLINE))
        if self.isEnabled() and self.underMouse():
            crisp.fill_rect(p, deco, t("layer-hover-01"))
        name = "locked_filled" if self.isChecked() and not self.mixed else "unlocked"
        icons.paint(p, name, QRectF((r.width() - 16) / 2, (r.height() - 16) / 2, 16, 16),
                    "icon-primary" if self.isEnabled() else "icon-disabled")
        if self.hasFocus():
            crisp.frame(p, deco, FOCUS_WIDTH, t("focus"))
        p.end()


class LockCell(QFrame):
    """The 32 × 32 cell of a lock (Figma: the lock is a ghost icon Button whose 1 px bottom border is
    ``border-strong`` (contextual) - the same rule as the value fields beside it).  Painted crisp."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LockCell")
        self.setFixedSize(COL_LOCK, ROW_H)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        crisp.hline_bottom(p, self.rect(), t("border-strong-01"), HAIRLINE)
        p.end()


STEP_MODES = (("step", "Step size", True, "", "Step"), ("points", "Points", True, "", "Points"))


def header_label(text: str, width: int, center: bool = False, role: str | None = None) -> QLabel:
    """A column heading of the composition tables.  Composition space (Figma 393:66042, State=Normal): IBM Plex
    Sans Regular 14 / 18 px, 0.16 px tracking, ``text-primary``, left-aligned on the cell's 16 px text inset."""
    from ..theme import BODY_COMPACT_01, font
    c = QLabel(text)
    c.setObjectName("ColHeader")
    c.setFont(font(BODY_COMPACT_01))
    c.setFixedSize(width, ROW_H)
    col_role(c, role or ("element" if width == COL_ELEMENT else "value"))
    c.setProperty("col_header", not center)
    if center:
        c.setAlignment(Qt.AlignmentFlag.AlignCenter)
    else:
        c.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        c.setContentsMargins(16, 0, 0, 0)
    return c


# ======================================================================== composition space
SWEEP_MARGIN = 47  # Figma (393:66042, State=Normal / Error / Calculating): the table starts at x = 47


class SweepRow(QWidget):
    def __init__(self, element: str, parent=None):
        super().__init__(parent)
        self.element = element
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(COL_GAP)
        # editable symbol, exactly as in Single composition (same cell, same rule: check_symbol)
        self.el = element_field(element)
        lay.addWidget(self.el)
        self.min, self.max, self.step = Field(COL_VALUE), Field(COL_VALUE), Field(COL_VALUE)
        for f, name in ((self.min, "Min"), (self.max, "Max"), (self.step, "Step")):
            f.setAccessibleName(f"{element} {name}")
            lay.addWidget(f)
        lock_cell = col_role(LockCell(), "lock")
        lock_cell.setFixedSize(COL_LOCK, ROW_H)
        ll = QHBoxLayout(lock_cell)
        ll.setContentsMargins(0, 0, 0, 0)
        self.lock = LockToggle(True)
        # no column heading (Figma): the toggle's Tooltip explains what locking means in its current state
        self.lock.setAccessibleName(f"{element} required")
        ll.addWidget(self.lock, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lock_cell)
        lay.addStretch(1)
        self.setFixedHeight(ROW_H)

    def set_values(self, values: tuple[str, str, str]) -> None:
        for f, v in zip((self.min, self.max, self.step), values):
            f.setText(v)
            f.set_invalid(False)


class SystemSizeSelect(MultiSelect):
    """System size (Figma: 116 px field, "4, 5, 6" / "All"): the element counts N a generated alloy may have."""

    def __init__(self, parent=None):
        # CORRECT_SYSTEM_SIZE_DROPDOWN: a field-width checkbox list with an "All" option; toggles apply at once
        super().__init__("system sizes", parent=parent, accessible="System size", all_label="All")
        self.setFixedWidth(116)

    def current_html(self) -> str:
        if not self.options:
            return "System size"
        if not self.selected:
            return "All"
        return ", ".join(str(v) for v in sorted(self.selected))


class SweepView(QWidget, RowEditing):
    committed = Signal(str)               # a finished user edit (Undo / Redo: CompositionPanel.edit_committed)

    """Composition space (Figma "_Composition setup Composition space bases" 392:60079): per-element ranges in
    the range basis, Lock (required / optional), All row, System size and the workload summary."""

    grid = ColumnGrid()
    changed = Signal()
    message = Signal(str, str)
    element_renamed = Signal(str, str)
    discretization_changed = Signal(str)       # "step" | "points" (kept as a preference by the window)

    def __init__(self, datasets: Datasets | None = None, parent=None):
        super().__init__(parent)
        from ...core.data import default_datasets
        self.data = datasets or default_datasets()
        self.rows: dict[str, SweepRow] = {}
        self.unit = "ratio"
        self.element_error: tuple[SweepRow, str] | None = None
        self.range_error: str | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(SWEEP_MARGIN, 0, 0, 0)
        head.setSpacing(COL_GAP)
        head.addWidget(header_label("Elem.", COL_ELEMENT))
        self.h_min = header_label("Min", COL_VALUE)
        self.h_max = header_label("Max", COL_VALUE)
        self.mode = "step"                       # Step size | Points (the Step column heading)
        self.h_step = Dropdown(STEP_MODES, "step", inline=True, accessible="Step size or points",
                               width=COL_VALUE)
        col_role(self.h_step, "value")
        self.h_step.chevron_inset = 10           # Figma: chevron at x + 62 of the 88 px heading
        self.h_step.text_gap = 4
        self.h_step.changed.connect(lambda v: self.set_discretization(v))
        for w in (self.h_min, self.h_max, self.h_step):
            head.addWidget(w)
        head.addStretch(1)                       # the lock column has no heading (Figma)
        hw = QWidget()
        hw.setLayout(head)
        hw.setFixedHeight(32)
        root.addWidget(hw)
        root.addWidget(Divider())
        self.rows_widget = _Rows(margin=SWEEP_MARGIN)
        self.scroll = scroll_wrap(self.rows_widget)
        self.empty = EmptyState("Start by selecting elements",
                                "Click elements in the periodic table to set their ranges.", art="magnifier")
        self.rows_stack = QStackedWidget()
        self.rows_stack.addWidget(self.empty)
        self.rows_stack.addWidget(self.scroll)
        root.addWidget(self.rows_stack, 1)
        # All row (Figma: divider at y 301, row at y 313, 12 px margins)
        all_w = QWidget()
        all_w.setFixedHeight(57)
        al = QVBoxLayout(all_w)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)
        al.addWidget(Divider())
        ar = QHBoxLayout()
        ar.setContentsMargins(SWEEP_MARGIN, 11, 0, 13)
        ar.setSpacing(COL_GAP)
        lab = col_role(QLabel("All:"), "element")
        lab.setObjectName("ColHeader")
        lab.setFixedSize(COL_ELEMENT, ROW_H)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)          # Figma: Regular, centred in the element column
        ar.addWidget(lab)
        self.all_min, self.all_max, self.all_step = Field(COL_VALUE), Field(COL_VALUE), Field(COL_VALUE)
        for f, attr in ((self.all_min, "min"), (self.all_max, "max"), (self.all_step, "step")):
            f.setAccessibleName(f"All {attr}")
            f.editingFinished.connect(lambda a=attr, fld=f: self._apply_all(a, fld))
            ar.addWidget(f)
        lc = col_role(LockCell(), "lock")
        lc.setFixedSize(COL_LOCK, ROW_H)
        lcl = QHBoxLayout(lc)
        lcl.setContentsMargins(0, 0, 0, 0)
        self.all_lock = LockToggle(True)
        self.all_lock.setAccessibleName("Lock all")
        self.all_lock.clicked.connect(self._apply_all_lock)
        lcl.addWidget(self.all_lock, 0, Qt.AlignmentFlag.AlignCenter)
        ar.addWidget(lc)
        ar.addStretch(1)
        al.addLayout(ar)
        root.addWidget(all_w)
        # System size | Workload summary (Figma: divider x 20..437 at y 357; size at x 20, y 366, 116 px;
        # vertical divider x 148; workload summary at x 161)
        sum_w = QWidget()
        sum_w.setFixedHeight(76)
        sl = QVBoxLayout(sum_w)
        sl.setContentsMargins(20, 0, 20, 0)
        sl.setSpacing(0)
        sl.addWidget(Divider())
        srow = QHBoxLayout()
        srow.setContentsMargins(0, 8, 0, 8)
        srow.setSpacing(0)
        size_col = QVBoxLayout()
        size_col.setSpacing(8)
        cap_row = QHBoxLayout()
        cap_row.setSpacing(8)
        cap = QLabel("System size")
        cap.setObjectName("Label01")
        cap_row.addWidget(cap)
        cap_row.addWidget(InfoButton(SYSTEM_SIZE_HELP, title="System size"))
        cap_row.addStretch(1)
        size_col.addLayout(cap_row)
        self.size_box = SystemSizeSelect()
        # the user's own System size choice (kept apart from what is currently possible: a lock toggled for a
        # moment never loses it); the field shows choice ∩ possible sizes
        self._size_choice: tuple = ()
        self.size_box.changed.connect(self._size_chosen)
        size_col.addWidget(self.size_box)
        size_col.addStretch(1)
        srow.addLayout(size_col)
        srow.addSpacing(12)
        vdiv = Divider(vertical=True)
        vdiv.setFixedHeight(59)
        srow.addWidget(vdiv, 0, Qt.AlignmentFlag.AlignTop)
        srow.addSpacing(12)
        self.workload = WorkloadSummary(WORKLOAD_HELP)
        srow.addWidget(self.workload, 1)
        sl.addLayout(srow)
        root.addWidget(sum_w)
        # Pre-flight count: debounced, computed on a background thread (count_space never materialises a
        # composition; at.% / wt.% are an exact DP, ratio / mass a bounded walk), latest-wins.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COUNT_DEBOUNCE_MS)
        self._timer.timeout.connect(self._update_summary)
        self._counter = BackgroundTask(self)
        self._counter.done.connect(self._show_summary)
        self._counter.failed.connect(self._summary_failed)
        self.summary_data = None
        self.counting = False
        self._refresh_sizes()
        self._show_workload(None)
        self._sync_enabled()

    # -- elements
    def set_elements(self, elements: list[str]):
        for el in list(self.rows):
            if el not in elements:
                row = self.rows.pop(el)
                if self.element_error and self.element_error[0] is row:
                    self.element_error = None
                retire(row)
        for el in elements:
            if el not in self.rows:
                row = SweepRow(el)
                self.grid.apply(row)
                row.set_values(self._defaults())
                row.step.setAccessibleName(f"{el} {'Points' if self.mode == 'points' else 'Step'}")
                for f in (row.min, row.max, row.step):
                    f.textEdited.connect(lambda _t, fld=f: (fld.set_invalid(False), self._edited()))
                    f.editingFinished.connect(lambda r=row: self.committed.emit(f"Edit {r.element} range"))
                row.lock.toggled.connect(lambda _c: self._edited())
                row.lock.toggled.connect(lambda c, r=row: self.committed.emit(
                    f"{'Lock' if c else 'Unlock'} {r.element}"))
                if not hasattr(self, "grid_keys"):
                    self.grid_keys = GridKeys(self, row_major=True)
                self.grid_keys.watch((row.min, row.max, row.step))
                row.el.editingFinished.connect(lambda r=row: self._element_edited(r))
                row.keys = SymbolKeys(self, row)
                row_context_actions(self, row)
                self.rows[el] = row
                self.rows_widget.insert(row)
        self.rows = {el: self.rows[el] for el in elements}
        self._place_rows()
        self.rows_stack.setCurrentIndex(1 if elements or self.draft else 0)
        self._refresh_sizes()
        self._sync_enabled()
        self._edited()

    def nav_grid(self) -> list[list]:
        """Min, Max and Step of every committed row (GridKeys)."""
        return [[row.min, row.max, row.step] for row in self.rows.values()]

    def _new_draft_row(self) -> SweepRow:
        row = SweepRow("")
        for f, name in ((row.min, "Min"), (row.max, "Max"), (row.step, "Step")):
            # every column is there; blank and read-only until the symbol is committed (no default range shown)
            f.setText("")
            f.setReadOnly(True)
            f.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            f.setAccessibleName(f"New element {name}")
        row.lock.setEnabled(False)               # a toggle, not a text input: no lock before there is an element
        row.lock.setAccessibleName("New element required")
        return row

    def rename(self, old: str, new: str, order: list[str]) -> None:
        """Replace ``old`` by ``new`` keeping the row's range and lock (row identity follows the symbol)."""
        row = self.rows.pop(old, None)
        if row is None:
            self.set_elements(order)
            return
        row.element = new
        row.el.setText(new)
        for f, name in ((row.min, "Min"), (row.max, "Max"), (row.step, "Step")):
            f.setAccessibleName(f"{new} {name}")
        row.lock.setAccessibleName(f"{new} required")
        self.rows[new] = row
        self.set_elements(order)

    def snapshot(self) -> dict:
        """Ranges, locks and system sizes per element (Undo of Clear composition space)."""
        return {"rows": {el: (r.min.text(), r.max.text(), r.step.text(), r.lock.isChecked())
                         for el, r in self.rows.items()},
                "sizes": tuple(self.size_box.selected), "mode": self.mode}

    def restore(self, snap: dict) -> None:
        if snap.get("mode", "step") != self.mode:
            self.set_discretization(snap.get("mode", "step"), convert=False)
        for el, r in self.rows.items():
            saved = snap["rows"].get(el)
            if saved is None:
                continue
            r.set_values(saved[:3])
            r.lock.blockSignals(True)
            r.lock.setChecked(saved[3])
            r.lock.blockSignals(False)
            r.lock.update()
        self._refresh_sizes()
        self._size_choice = tuple(snap["sizes"])
        self.size_box.set_options(self.size_box.options, snap["sizes"])
        self._edited()

    def set_unit(self, unit: str):
        """Range basis (at. ratio / at.% / wt.% / mass): new defaults for every row, recounted."""
        if unit == self.unit:
            return
        self.unit = unit
        for row in self.rows.values():
            row.set_values(self._defaults())
            row.memory = {}
        self._edited()
        self.committed.emit("Change range basis")

    # -- Step size | Points
    def _defaults(self) -> tuple[str, str, str]:
        lo, hi, step = RANGE_DEFAULTS[self.unit]
        if self.mode == "points":
            return lo, hi, step_to_points(lo, hi, step) or "2"
        return lo, hi, step

    def set_discretization(self, mode: str, convert: bool = True) -> None:
        """Switch the Step column between Step size and Points.  A value is never reinterpreted as the other
        quantity: an equivalent value is converted exactly (step 0.25 on 0-1 <-> 5 points); a value with no exact
        equivalent (0-1 in steps of 0.3; 4 points = thirds, which no finite step gives) is cleared and flagged for
        the user to enter; switching back restores the value entered before, while Min and Max are unchanged."""
        if mode not in ("step", "points") or mode == self.mode:
            if self.h_step.value != self.mode:
                self.h_step.set_value(self.mode)
            return
        old, self.mode = self.mode, mode
        self.h_step.set_value(mode)
        for el, row in self.rows.items():
            lo, hi, val = row.min.text().strip(), row.max.text().strip(), row.step.text().strip()
            row.memory = getattr(row, "memory", {})
            row.memory[old] = (lo, hi, val)
            kept = row.memory.get(mode)
            if kept is not None and kept[:2] == (lo, hi):
                new = kept[2]
            elif not convert:
                new = val
            else:
                new = (step_to_points(lo, hi, val) if mode == "points" else points_to_step(lo, hi, val)) or ""
            row.step.setText(new)
            row.step.set_invalid(not new, (f"{el}: enter the number of points" if mode == "points"
                                           else f"{el}: enter a step size") if not new else "")
            row.step.setAccessibleName(f"{el} {'Points' if mode == 'points' else 'Step'}")
        self.all_step.clear()
        self.all_step.setAccessibleName("All points" if mode == "points" else "All step")
        self.discretization_changed.emit(mode)
        self._edited()

    def possible_sizes(self) -> range:
        """System sizes the generator can produce, by construction: every system holds all L required (locked)
        elements plus any subset of the optional ones, and systems of fewer than two elements are dropped
        (``generation.systems``) - so k runs over max(2, L) .. N.  Computed directly, never by enumeration; whether a
        size also yields compositions (e.g. at.% grids summing to 100) is the workload count's answer."""
        n = len(self.rows)
        locked = sum(1 for r in self.rows.values() if r.lock.isChecked())
        return range(max(2, locked), n + 1)

    def _refresh_sizes(self):
        """System size choices: the structurally possible sizes only.  When exactly one size is possible (every
        element locked, or two elements) the field is read-only and shows it; when more sizes become possible again
        the field starts at All (every possible size, 2026-10-28) and the user narrows it.  Otherwise a choice that
        is no longer possible is hidden (the user's choice is kept, ``_size_choice``); nothing left means All."""
        n = len(self.rows)
        box = self.size_box
        sizes = self.possible_sizes()
        if n >= 2 and len(sizes) == 1:
            k = sizes[0]
            box.set_options([(k, str(k))], (k,))
            locked = all(r.lock.isChecked() for r in self.rows.values())
            box.set_read_only(True, f"Every element is locked (required), so every alloy has all {k} elements."
                              if locked else f"With {k} elements every alloy contains all of them.")
            self._sizes_fixed = True
            return
        if getattr(self, "_sizes_fixed", False):
            # from one possible size to several (an element unlocked, or a third element added): All - every
            # possible size - never the fixed maximum the read-only field showed (2026-10-28); the user narrows it
            self._size_choice = ()
            self._sizes_fixed = False
        box.set_read_only(False)
        box.set_options([(k, str(k)) for k in sizes], tuple(k for k in self._size_choice if k in sizes))

    def _size_chosen(self, sel) -> None:
        self._size_choice = tuple(sel)
        self._edited()
        self.committed.emit("Change system size")

    def _sync_enabled(self):
        has = bool(self.rows)
        for w in (self.all_min, self.all_max, self.all_step, self.all_lock, self.size_box):
            w.setEnabled(has)

    def _edited(self):
        self._sync_all_row()
        self._refresh_sizes()                    # a lock may have changed: System size follows (all locked = N)
        self.range_error = None
        self.counting = bool(self.rows)
        self.changed.emit()
        self._timer.start()

    def _sync_all_row(self):
        rows = list(self.rows.values())
        for fld, attr in ((self.all_min, "min"), (self.all_max, "max"), (self.all_step, "step")):
            vals = {getattr(r, attr).text().strip() for r in rows}
            if not fld.hasFocus():
                fld.clear()
                fld.setPlaceholderText((vals.pop() if len(vals) == 1 else "Mixed") if rows else
                                       {"min": "Min", "max": "Max",
                                        "step": "Points" if self.mode == "points" else "Step"}[attr])
        locks = {r.lock.isChecked() for r in rows}
        self.all_lock.mixed = len(locks) > 1
        self.all_lock.blockSignals(True)
        self.all_lock.setChecked(all(locks) if locks else True)
        self.all_lock.blockSignals(False)
        self.all_lock.update()

    def _apply_all(self, attr: str, fld: Field):
        text = fld.text().strip()
        if not text:
            fld.set_invalid(False)
            return
        points = attr == "step" and self.mode == "points"
        if (parse_points(text) if points else C.parse_number(text)) is None:
            fld.set_invalid(True, "All points: enter a whole number" if points else f"All {attr}: enter a number")
            self.changed.emit()
            return
        fld.set_invalid(False)
        for r in self.rows.values():
            getattr(r, attr).setText(text)
            getattr(r, attr).set_invalid(False)
        self._edited()

    def _apply_all_lock(self):
        state = self.all_lock.isChecked()
        self.all_lock.mixed = False
        for r in self.rows.values():
            r.lock.blockSignals(True)
            r.lock.setChecked(state)
            r.lock.blockSignals(False)
            r.lock.update()
        self._edited()
        self.committed.emit("Lock all elements" if state else "Unlock all elements")

    # -- data
    def specs(self) -> list[SweepSpec]:
        out = []
        for el, row in self.rows.items():
            vals = []
            pts = self.mode == "points"
            for f, name in ((row.min, "Min"), (row.max, "Max"), (row.step, "Points" if pts else "Step")):
                v = parse_points(f.text()) if (pts and f is row.step) else f.number()
                f.set_invalid(v is None, f"{el}: {name} is missing or invalid" if not (pts and f is row.step)
                              else f"{el}: Points must be a whole number")
                vals.append(v)
            if None in vals:
                raise RangeError("Missing range values")
            spec = SweepSpec(el, vals[0], vals[1], 0.0 if pts else vals[2], row.lock.isChecked(),
                             points=vals[2] if pts else None)
            try:
                spec.as_range().validate()
            except RangeError as exc:
                bad = row.max if "Max" in str(exc) else row.step if ("Step" in str(exc) or "Points" in str(exc)) \
                    else row.min
                bad.set_invalid(True, str(exc))
                raise
            out.append(spec)
        return out

    def sizes(self):
        sel = self.size_box.selected
        return set(sel) if sel else None

    def _update_summary(self):
        if not self.rows:
            self._counter.cancel()
            self.summary_data = None
            self.counting = False
            self._show_workload(None)
            self.changed.emit()
            return
        try:
            specs, sizes = self.specs(), self.sizes()
        except RangeError as exc:
            self._counter.cancel()
            self._summary_failed(exc)
            return
        self.counting = True
        self.changed.emit()
        unit = self.unit
        if unit in SUM_UNITS:
            # exact bounded-knapsack DP: microseconds to milliseconds
            self._counter.run(lambda cancelled=None: summarize_space(specs, unit, sizes, limit=SWEEP_LIMIT,
                                                                     cancelled=cancelled))
        else:
            # ratio / mass spaces may need a duplicate-removing walk of up to ~10^6 tuples: worker process
            recipe = SweepRecipe(tuple(specs), unit, frozenset(sizes) if sizes else None, SWEEP_LIMIT)
            if recipe.estimate() <= HEAVY_THRESHOLD:
                self._counter.run(lambda cancelled=None: summarize_space(specs, unit, sizes, limit=SWEEP_LIMIT,
                                                                         cancelled=cancelled))
            else:
                self._counter.run_heavy(summarize_space, specs, unit, sizes, SWEEP_LIMIT)

    def _summary_failed(self, exc):
        self.summary_data = None
        self.counting = False
        self.range_error = str(exc) or "Invalid ranges"
        self._show_workload(None)
        self.changed.emit()

    def _show_summary(self, s):
        self.summary_data = s
        self.counting = False
        self.range_error = None
        self._show_workload(s)
        self.changed.emit()

    def _show_workload(self, s):
        if s is None:
            self.workload.set_values(f"<span style='color:{t('text-secondary')}'>—</span>"
                                     "<span style='font-size:12px'> valid compositions</span>", "", "")
            return
        n = SWEEP_LIMIT + 1 if s.truncated else s.compositions
        est = estimate(n, self.workers())
        count = f"&gt;{SWEEP_LIMIT:,}" if s.truncated else f"{s.compositions:,}"
        color = t("text-error") if s.truncated or not s.compositions else t("text-primary")
        self.workload.set_values(f"<span style='color:{color}; font-weight:600; font-size:14px'>{count}</span>"
                                 f"<span style='font-size:12px'> valid composition"
                                 f"{'s' if s.compositions != 1 else ''}</span>",
                                 fmt_short_duration(est.seconds), fmt_short_bytes(est.bytes))

    def workers(self) -> int:
        svc = getattr(self.window(), "jobs", None)
        return getattr(svc, "workers", 1)

    # -- status (footer)
    def status(self) -> Status | None:
        if self.element_error:
            return Status("error", self.element_error[1])
        if not self.rows:
            return None
        bad = [f for row in self.rows.values() for f in (row.min, row.max, row.step) if f.error]
        if self.range_error or bad:
            if bad and all("missing or invalid" in f.error for f in bad):
                return Status("error", "Missing range values")
            msg = bad[0].error if bad else self.range_error
            return Status("error", msg.rstrip("."))
        if len(self.rows) < 2:
            return Status("info", "Select at least two elements")
        if self.counting or self._timer.isActive():
            return Status("loading", "Updating…")
        s = self.summary_data
        if s is None:
            return None
        if s.truncated:
            return Status("error", "Workload too large",
                          capacity_problem(SWEEP_LIMIT + 1, None), "Workload too large")
        if not s.compositions:
            hint = " - values must sum to 100 %" if self.unit in SUM_UNITS else ""
            return Status("error", "No valid compositions" + hint)
        if s.compositions >= LARGE:
            _tier, tip = size_note(s.compositions, self.workers())
            return Status("info", "Large workload", [tip, "<a href='help://workload'>About workload estimates</a>"],
                          "Large workload")
        return None

    def valid_count(self) -> int | None:
        """Valid compositions of the last pre-flight count (``None`` while unknown or beyond the limit)."""
        s = self.summary_data
        return None if s is None or s.truncated else s.compositions

    def can_calculate(self) -> bool:
        st = self.status()
        return len(self.rows) >= 2 and self.summary_data is not None and (st is None or not st.blocking) \
            and not (st is not None and st.kind == "loading")

    def compositions(self):
        names, comps = self.recipe()()[1:3]
        return names, comps

    def recipe(self):
        """A callable generating ``(source, names, compositions, variables)`` - run by the calculation
        job off the GUI thread.  The pre-flight count rejects an oversized space before anything is
        generated."""
        specs, sizes, unit = self.specs(), self.sizes(), self.unit
        s = self.summary_data
        recipe = SweepRecipe(tuple(specs), unit, frozenset(sizes) if sizes else None, SWEEP_LIMIT)
        if unit in SUM_UNITS:
            n = recipe.estimate()                    # exact (DP, < 1 ms), whatever the summary shows
            if n > SWEEP_LIMIT:
                raise RangeError(capacity_problem(n, None))
        elif s is not None and s.truncated and self._counter.busy is False and not self._timer.isActive():
            raise RangeError(capacity_problem(SWEEP_LIMIT + 1, None))
        return recipe

    def clear(self):
        for row in self.rows.values():
            row.set_values(RANGE_DEFAULTS[self.unit])
            row.lock.setChecked(True)
        self._edited()


# ======================================================================== expression
def _collect_elements(items, out):
    for it in items:
        if hasattr(it, "symbol"):
            if it.symbol not in out:
                out.append(it.symbol)
        else:
            _collect_elements(it.items, out)


# ======================================================================== panel
class CompositionPanel(Panel):
    # Python payloads are passed as ``object``: a ``list``/``dict`` signature would convert compositions to
    # QVariantMap, which re-orders elements alphabetically.
    # source, names, compositions, variables, run metadata (Single composition: the input basis; else None)
    calculate_requested = Signal(object, object, object, object, object)
    elements_changed = Signal(list)                       # elements chosen inside the panel
    edit_committed = Signal(str)                          # one finished, meaningful edit (MainWindow's Undo / Redo)
    message = Signal(str, str)
    copy_compositions = Signal(str)                       # TSV of generated compositions
    copy_text = Signal(str, str)                          # TSV, description (Single: Copy table)
    mode_changed = Signal(str)                            # "single" | "sweep" | "expression"
    cancel_requested = Signal()
    total_mass_committed = Signal(float)

    MODES = ("single", "sweep", "expression")

    def __init__(self, datasets: Datasets, parent=None, engine=None):
        super().__init__("", parent)
        self.data = datasets
        self.engine = engine
        self._coverage_cache: dict[frozenset, dict] = {}
        # Header (Figma 392:69182 / 392:69349 / 392:69514, 40 px): the title *is* the mode dropdown (Single
        # composition / Composition space > basis / Expression); the status tag or inline loading sits right of it,
        # then Expression's help button and the panel's collapse button (40 x 40 each).
        self.title_holder.setFixedHeight(40)
        while self.title_row.count():
            item = self.title_row.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        self.title_row.setSpacing(0)
        from .heading_dropdown import HeadingDropdown, Node
        tree = [Node("single", MODE_TITLES["single"]),
                Node("sweep", MODE_TITLES["sweep"], [Node(v, lab) for v, lab in RANGE_BASES]),
                Node("expression", MODE_TITLES["expression"])]
        self.heading = HeadingDropdown(tree, ("single",), MODE_TITLES["single"], accessible="Composition setup mode")
        self.heading.chosen.connect(self._heading_chosen)
        self.title_row.addWidget(self.heading)
        self.title = self.heading             # the shell aligns its status with the title text (indent 16)
        self.footer = CompositionFooter()
        self.header_status = self.footer.status
        self.title_row.addSpacing(16)
        self.title_row.addWidget(self.header_status, 1)
        self.title_row.addSpacing(8)
        self.help_btn = HeaderIconButton("help", "Expression syntax", toggletip=self._expression_help)
        self.title_row.addWidget(self.help_btn)
        self.collapse_btn = HeaderIconButton("panel_collapse", "Collapse Composition setup")
        self.title_row.addWidget(self.collapse_btn)
        self.stack = QStackedWidget()
        self.single = SingleView(datasets)
        self.sweep = SweepView(datasets)
        self.expr = ExpressionView(datasets)
        self._run_failed = None
        for v in (self.single, self.sweep, self.expr):
            self.stack.addWidget(v)
            v.changed.connect(self._edited_view)
            v.message.connect(self.message.emit)
        self.root.addWidget(self.stack, 1)
        self.expr.elements_parsed.connect(self.elements_changed.emit)
        self.single.element_renamed.connect(self._renamed)
        self.sweep.element_renamed.connect(self._renamed)
        self.single.total_mass_committed.connect(self.total_mass_committed.emit)
        self._restoring = False
        self.single.committed.connect(self._commit)
        self.sweep.committed.connect(self._commit)

        # footer (Figma: 40 px, Clear | Calculate [v])
        self.root.addWidget(self.footer)
        self.clear_btn = self.footer.clear_btn
        self.calc_btn = self.footer.calc_btn
        self.clear_btn.clicked.connect(self._clear_or_cancel)
        self.calc_btn.clicked.connect(self.calculate)
        self.add_btn = self.footer.add_btn
        self.add_btn.clicked.connect(self.add_draft)
        for v in (self.single, self.sweep):
            v.add_element_cb = self.add_element
            v.remove_element_cb = self.remove_element
            v.focus_add_cb = lambda: self.add_btn.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setFixedWidth(COMPOSITION_PANEL_WIDTH)      # not responsive: the Figma component's width
        self.grid = ColumnGrid()
        for v in (self.single, self.sweep, self.expr):
            v.grid = self.grid
        self._elements: list[str] = []
        self.service = None
        self._calculating = False
        self.clear_handler = None           # set by the window: Clear goes through Edit > Undo
        self.set_mode(0)

    # ---------------------------------------------------------------- mode / basis (the heading dropdown)
    @property
    def basis(self) -> str:
        return self.sweep.unit

    def set_basis(self, unit: str) -> None:
        """Range basis of Composition space (at. ratio / at.% / wt.% / mass) - chosen in the heading dropdown's
        Composition space sub-list.  A change resets every row to that basis' defaults (as before)."""
        if unit not in BASIS_LABELS:
            return
        self.sweep.set_unit(unit)
        self._sync_heading()

    def _heading_chosen(self, path: tuple) -> None:
        mode = path[0]
        if mode == "sweep" and len(path) > 1:
            self.set_basis(path[1])
        if mode != self.mode:
            self.set_mode(self.MODES.index(mode))
        else:
            self._sync_heading()

    def heading_label(self) -> str:
        if self.mode == "sweep":
            return f"{MODE_TITLES['sweep']} ({BASIS_LABELS[self.sweep.unit]})"
        return MODE_TITLES[self.mode]

    def _sync_heading(self) -> None:
        path = ("sweep", self.sweep.unit) if self.mode == "sweep" else (self.mode,)
        self.heading.set_state(path, self.heading_label())

    def _expression_help(self) -> str:
        from .expression_view import EXPRESSION_HELP
        return EXPRESSION_HELP

    CALC_WIDTH = 141

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.grid.set_panel_width(self.width()):
            self.grid.apply(self)

    @property
    def mode(self) -> str:
        return self.MODES[self.stack.currentIndex()]

    def view(self):
        return self.stack.currentWidget()

    def set_mode(self, i: int):
        if i != self.stack.currentIndex():
            self.discard_drafts()                           # a draft belongs to the table it was opened in
        self.stack.setCurrentIndex(i)
        self._sync_heading()                                # the panel title names the mode (and the basis)
        self.help_btn.setVisible(self.mode == "expression")
        self.mode_changed.emit(self.mode)
        if self.mode != "expression":
            self.elements_changed.emit(self._elements)
        elif self.expr.expressions:
            els: list[str] = []
            for ex in self.expr.expressions:
                _collect_elements(ex.items, els)
            self.elements_changed.emit(els)
        else:
            self.elements_changed.emit([])
        self._update_actions()

    def set_elements(self, elements: list[str]):
        self._elements = list(elements)
        self.single.set_elements(self._elements)
        self.sweep.set_elements(self._elements)
        self._update_actions()

    def element_toggled(self, el: str, selected: bool, after: str | None = None):
        """Select / deselect one element (the periodic table's path).  A new element goes to the end of the order,
        or directly after ``after`` (an element typed in the Add element draft under that row)."""
        self._run_failed = None                     # a changed setup replaces the failed run's message
        if self.mode == "expression":
            if selected:
                self.expr.add_element(el)
            else:
                self.expr.remove_element(el)
            return
        if selected and el not in self._elements:
            if after in self._elements:
                self._elements.insert(self._elements.index(after) + 1, el)
            else:
                self._elements.append(el)
        elif not selected and el in self._elements:
            self._elements.remove(el)
        self.set_elements(self._elements)
        self._commit(f"{'Add' if selected else 'Remove'} element {el}")     # recorded only if it changed

    # ---------------------------------------------------------------- Undo / Redo of setup edits (2026-10-28)
    def _commit(self, text: str) -> None:
        """One finished, meaningful edit of Single composition or Composition space (an element added, removed or
        renamed, a field left after editing, a lock, the input column, the range basis, the system size, Set
        equal).  The window records it as one Undo step when the setup actually changed; edits made by Undo /
        Redo themselves (``_restoring``) and Expression mode (its editor has its own undo) are not recorded."""
        if not self._restoring and self.mode != "expression":
            self.edit_committed.emit(text)

    def undo_state(self) -> dict:
        """Everything an Undo step restores: the mode, the element order (the periodic-table selection follows
        it), Single composition's input column, basis, values (the balance is derived), batch mass and auto-equal
        state, and Composition space's range basis, ranges, locks, discretization and system sizes."""
        single = self.single.snapshot()
        single["input_rep"] = single["value_rep"]          # the El. column (symbols editable) is not data
        return {"mode": self.mode, "elements": list(self._elements), "unit": self.sweep.unit,
                "single": single, "sweep": self.sweep.snapshot()}

    def apply_undo_state(self, st: dict) -> None:
        """Re-apply :meth:`undo_state` (Undo / Redo): the mode the edit was made in, then the elements and both
        tables; validation and counts recompute from the restored values."""
        self._restoring = True
        try:
            self.discard_drafts()
            if st["mode"] != self.mode and st["mode"] in self.MODES:
                self.set_mode(self.MODES.index(st["mode"]))
            self._elements = list(st["elements"])
            self.set_elements(self._elements)
            if self.sweep.unit != st["unit"]:
                self.sweep.unit = st["unit"]               # restore() below sets every row's values
            self.single.restore(st["single"])
            self.sweep.restore(st["sweep"])
            self._sync_heading()
            self.elements_changed.emit(list(self._elements))
            self._update_actions()
        finally:
            self._restoring = False

    # ---------------------------------------------------------------- Add element (footer)
    def add_element(self, el: str, after: str | None = None) -> bool:
        """Add one element typed in the Add element draft: exactly a periodic-table selection (``element_toggled``,
        placed after ``after`` when given), then the periodic table follows (``elements_changed``).  Single
        composition and Composition space only; an element already present is refused."""
        if self.mode == "expression" or self._calculating or el in self._elements:
            return False
        self.element_toggled(el, True, after=after)
        self.elements_changed.emit(list(self._elements))
        return True

    def remove_element(self, el: str) -> bool:
        """Remove one element (row context menu "Remove element"): exactly a periodic-table deselection
        (``element_toggled``), then the periodic table follows (``elements_changed``)."""
        if self.mode == "expression" or self._calculating or el not in self._elements:
            return False
        self.element_toggled(el, False)
        self.elements_changed.emit(list(self._elements))
        return True

    def add_draft(self) -> None:
        """Add element (footer): a blank row at the end of the current table, its symbol field focused (Single
        composition activates the El. input column).  Typed symbols are committed by :meth:`add_element`."""
        if self.mode == "expression" or self._calculating:
            return
        self.view().open_draft()

    def discard_drafts(self) -> None:
        for v in (self.single, self.sweep):
            v.discard_draft()

    def _renamed(self, old: str, new: str):
        """An element symbol typed in Single or Space: one rename for both tables, the periodic table and the
        model-support state (row identity follows the symbol; values and locks are kept)."""
        order = [new if e == old else e for e in self._elements]
        self._elements = order
        if old in self.single.rows:
            self.single.rename(old, new, order)
        else:
            self.single.set_elements(order)
        self.sweep.rename(old, new, order)
        self.elements_changed.emit(order)
        self._update_actions()
        self._commit(f"Rename {old} to {new}")

    def set_total_mass(self, grams: float) -> None:
        self.single.set_total_mass(grams)
        self.expr.set_total_mass(grams)

    def set_service(self, service) -> None:
        """The calculation service whose worker processes run heavy pre-flight work."""
        self.service = service
        self.sweep._counter.service = service
        self.expr._counter.service = service

    def set_calculating(self, running: bool):
        """State=Calculating: Cancel + inline "Calculating…" in the footer; progress is in the shell header."""
        self._calculating = running
        if running:
            self._run_failed = None
        self.footer.set_running(running)
        # CORRECT_CALCULATING_STATE: the inputs of the running recipe are read-only (disabled tokens), the
        # basis / mode controls too; the footer keeps its status (never "Ready" while a run is going)
        self.stack.setEnabled(not running)
        self.heading.setEnabled(not running)
        self._update_actions()

    # ---------------------------------------------------------------- status / actions
    def set_run_failed(self, message: str | None) -> None:
        """Calculation failure (an engine or storage error ended the run): a red "Calculation failed" tag in the
        header, explained by its toggletip, until the next edit or calculation.  It is not an input error."""
        self._run_failed = message or None
        self._update_actions()

    def coverage(self, elements) -> dict:
        els = frozenset(elements)
        if self.engine is None or len(els) < 2:
            return {}
        cov = self._coverage_cache.get(els)
        if cov is None:
            if len(self._coverage_cache) > 256:
                self._coverage_cache.clear()
            cov = self._coverage_cache[els] = self.engine.model_coverage(list(elements))
        return cov

    def current_elements(self) -> list[str]:
        if self.mode == "expression":
            return list(self.expr.detected[1]) if self.expr.expressions else []
        return list(self._elements)

    def status(self) -> Status | None:
        if getattr(self, "_run_failed", None) and not self._calculating:
            return Status("error", "Calculation failed", self._run_failed, "Calculation failed")
        st = self.view().status()
        if st is None or st.kind == "success":
            # model support is information, never an input error: it replaces only "nothing to say" / success
            cov = coverage_status(self.coverage(self.current_elements()))
            if cov is not None:
                return cov
            # the expression editor reports its own state in place (COMPOSITION_EXPRESSION_* show no footer status)
            if self.mode == "sweep" and self.view().can_calculate() and not self._calculating:
                return Status("ready", "Ready")
        return st

    def _edited_view(self):
        self._run_failed = None                     # an edit replaces the failed run's message
        self._update_actions()

    def _update_actions(self):
        m = self.mode
        v = self.view()
        self.footer.status.set_status(self.status())
        # Add element: Single composition and Composition space (Expression has its own element syntax)
        self.add_btn.setVisible(m != "expression")
        self.add_btn.setEnabled(not self._calculating)
        if m == "single":
            has = bool(self._elements)
            self.footer.calc.set_actions([("Set equal", self._set_equal, self.single.can_set_equal(), None),
                                          ("-", None, False, None),
                                          ("Copy table", self._copy_single, has, "copy")])
            self.clear_btn.setEnabled(has or self._calculating)
        elif m == "sweep":
            self.footer.calc.set_actions([("Copy table", self._copy_sweep, self._sweep_copyable(), "copy")])
            self.clear_btn.setEnabled(bool(self._elements) or self._calculating)
        else:
            has = bool(self.expr.text().strip())
            self.footer.calc.set_actions([("Copy table", self._copy_expression, self.expr.can_calculate(),
                                           "copy")])
            self.clear_btn.setEnabled(has or self._calculating)
        if m == "expression":
            action, enabled, split = self.expr.primary_action()
            self.footer.set_primary("Parse expression" if action == "parse" else "Calculate", split)
            self.calc_btn.setEnabled(enabled and not self._calculating)
        else:
            self.footer.set_primary("Calculate", True)
            self.calc_btn.setEnabled(v.can_calculate() and not self._calculating)

    def _clear_or_cancel(self):
        if self._calculating:
            self.cancel_requested.emit()
            return
        if self.clear_handler is not None:          # the window: an undoable Clear composition
            self.clear_handler()
            return
        self.clear()

    def _set_equal(self):
        if self.mode == "single":
            self.single.set_equal()

    def _copy_single(self):
        self.copy_text.emit(self.single.table_tsv(), "composition table")

    def _generated_tsv(self, generated=None) -> str:
        names, comps, _envs = generated or self.expr.compositions()
        return compositions_tsv(names, comps)

    def _generate_then(self, fn, action):
        """``action(fn(recipe))`` with the expression recipe evaluated off the GUI thread (in a worker
        process for large batches - only the small result comes back)."""
        try:
            recipe = self.expr.recipe()
        except (ValueError, RangeError, ExpressionError) as exc:
            self.message.emit("error", str(exc))
            return
        self._generate_recipe_then(recipe, fn, action)

    def _generate_recipe_then(self, recipe, fn, action):
        task = getattr(self, "_gen_task", None)
        if task is None:
            task = self._gen_task = BackgroundTask(self, self.service)
            task.failed.connect(lambda exc: self.message.emit("error", str(exc)))
            task.done.connect(lambda out: self._gen_action(out))
        self._gen_action = action
        if recipe.estimate() <= HEAVY_THRESHOLD:
            task.run(lambda cancelled=None: fn(recipe))
        else:
            task.run_heavy(fn, recipe)

    def _copy_compositions(self):
        self._generate_then(recipe_tsv, self.copy_compositions.emit)

    def _sweep_copyable(self) -> bool:
        if not self.sweep.can_calculate():
            return False
        n = self.sweep.valid_count()
        return n is not None and 0 < n <= SWEEP_COPY_LIMIT

    def _copy_sweep(self):
        """Composition space > Copy table: every generated composition (at most SWEEP_COPY_LIMIT) as TSV, generated
        off the GUI thread like Expression's."""
        try:
            recipe = self.sweep.recipe()
        except (ValueError, RangeError, ExpressionError) as exc:
            self.message.emit("error", str(exc))
            return
        self._generate_recipe_then(recipe, recipe_tsv, self.copy_compositions.emit)

    def _copy_expression(self):
        """One block: its composition preview table; several blocks: every generated composition."""
        doc = self.expr.doc
        if doc is not None and doc.ok and len(doc.blocks) == 1 and doc.blocks[0].kind == "fixed":
            self.copy_text.emit(self.expr.preview_tsv(), "composition table")
        else:
            self._copy_compositions()

    def clear(self):
        """Clear composition (undoable from the window: :meth:`snapshot` before, :meth:`restore` to undo)."""
        if self.mode == "expression":
            self.expr.clear()
            self.elements_changed.emit([])
            self._update_actions()
            return
        self.discard_drafts()
        self._elements = []
        self.set_elements([])
        self.elements_changed.emit([])

    def is_empty(self) -> bool:
        if self.mode == "expression":
            return not self.expr.text().strip()
        return not self._elements

    def snapshot(self) -> dict:
        """Everything Clear composition discards in the current mode."""
        m = self.mode
        snap = {"mode": m, "elements": list(self._elements)}
        if m == "single":
            snap["single"] = self.single.snapshot()
        elif m == "sweep":
            snap["sweep"] = self.sweep.snapshot()
        else:
            snap["text"] = self.expr.text()
        return snap

    def restore(self, snap: dict) -> None:
        m = snap["mode"]
        if self.mode != m:
            self.set_mode(self.MODES.index(m))
        if m == "expression":
            self.expr.set_text(snap["text"])
            self.expr.parse()
            self.set_mode(self.MODES.index(m))           # re-sync the periodic table with the parsed elements
            return
        self._elements = list(snap["elements"])
        self.set_elements(self._elements)
        if m == "single":
            self.single.restore(snap["single"])
        else:
            self.sweep.restore(snap["sweep"])
        self.elements_changed.emit(list(self._elements))
        self._update_actions()

    def calculate(self):
        m = self.mode
        try:
            if m == "single":
                name, ratios = self.single.composition()
                self.calculate_requested.emit("single", [name], [ratios], [{}], self.single.input_meta())
            elif m == "sweep":
                # generation happens in the calculation job, not here (it can be millions of rows)
                self.calculate_requested.emit("sweep", None, self.sweep.recipe(), None, None)
            elif self.expr.primary_action()[0] == "parse":
                self.expr.parse()                    # Figma: Parse expression comes before Calculate
            else:
                self.calculate_requested.emit("expression", None, self.expr.recipe(), None, None)
        except (ValueError, RangeError, ExpressionError) as exc:
            self.message.emit("error", str(exc))
