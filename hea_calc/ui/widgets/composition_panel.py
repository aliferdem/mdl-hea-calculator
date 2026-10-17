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

from PySide6.QtCore import QTimer, Qt, Signal
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
from .common import (Divider, EmptyState, IconContentSwitcher, InfoButton, Panel, install_wheel_guard,
                     refresh_style, retire)
from .composition_footer import CompositionFooter, Status, WorkloadSummary
from .dropdown import Dropdown, MultiSelect
from .expression_view import ExpressionView
from .menu import carbon_context_menu
from .scroll import own_wheel, thin_scrollbars

COL_ELEMENT = 64
COL_VALUE = 88
COL_GAP = 1
COL_LOCK = 64
ROW_H = 32
ROW_GAP = 1
REP_KEYS = ("ratio", "at", "wt", "mass")
DECIMALS = {"ratio": 4, "at": 4, "wt": 4, "mass": 5}
SWEEP_LIMIT = HARD_LIMIT     # largest measured batch (core/limits.py); was 200 000 (in-memory result store)
COUNT_DEBOUNCE_MS = 200      # pre-flight counts wait for a pause in typing
HEAVY_THRESHOLD = 5_000      # combinations above which a pre-flight runs in a worker process
SUM_TOLERANCE = 1e-3         # at.% / wt.% columns must sum to 100 within 0.001 % (4-decimal input)

MODE_TITLES = {"single": "Single composition", "sweep": "Composition space", "expression": "Composition expression"}
RANGE_BASES = (("ratio", "At. ratio"), ("at", "at.%"), ("wt", "wt.%"), ("mass", "Mass"))
# defaults of a new row / after a basis change: (min, max, step)
RANGE_DEFAULTS = {"ratio": ("1.0", "1.0", "0.1"), "at": ("0", "100", "10"), "wt": ("0", "100", "10"),
                  "mass": ("1.0", "1.0", "0.1")}

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

    The design columns (element 64, value 88, lock 64 px, 1 px gaps) fit the 457 px panel, which is fixed by
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
        lock = element
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
            elif isinstance(w, QLabel) and role == "value" and w.property("col_header"):
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
        elif self.isEnabled():
            quiet = self.isReadOnly() or cell == "element-filled"
            crisp.hline_bottom(p, r, t("border-strong-01" if quiet else "border-strong-02"), HAIRLINE)
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


class SingleView(QWidget):
    grid = ColumnGrid()          # replaced by the panel's shared grid
    changed = Signal()
    element_renamed = Signal(str, str)  # old, new
    message = Signal(str, str)          # kind, text (action results for the window notification)
    total_mass_committed = Signal(float)

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        self.input_rep = "ratio"         # active input column (or "element")
        self.values: dict[str, float | None] = {}  # values of the active numeric column, full precision
        self.total_mass = DEFAULT_TOTAL_MASS
        self.rows: dict[str, SingleRow] = {}
        self.notice: Status | None = None     # a one-off explanation (input column switch, normalise)
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
        for el in elements:
            if el not in self.rows:
                row = SingleRow(el)
                self.grid.apply(row)
                self._wire(row)
                self.rows[el] = row
                self.rows_widget.insert(row)
                self.values[el] = 1.0 if self.input_rep in ("ratio", "element") else 0.0
        # keep visual order equal to selection order
        self.rows_widget.order([self.rows[el] for el in elements])
        self.rows = {el: self.rows[el] for el in elements}
        self.values = {el: self.values.get(el) for el in elements}
        self.rows_stack.setCurrentIndex(1 if elements else 0)
        self._apply_editability()
        self.refresh()

    def _wire(self, row: SingleRow):
        for rep, f in row.fields.items():
            f.textEdited.connect(lambda _txt, r=row, rp=rep: self._edited(r.element, rp))
            f.editingFinished.connect(lambda r=row: self._value_committed(r))
        row.el.editingFinished.connect(lambda r=row: self._element_edited(r))

    # ---------------------------------------------------------------- state
    @property
    def numeric_rep(self) -> str:
        return "ratio" if self.input_rep == "element" else self.input_rep

    def _radio(self, idx: int):
        key = ("element", "ratio", "at", "wt", "mass")[idx]
        if key == self.input_rep:
            return
        # switch the input column without changing the composition: adopt the computed values
        reps = self._representations()
        new_numeric = "ratio" if key == "element" else key
        self.notice = None
        if reps is not None:
            self.values = dict(reps[new_numeric])
        elif new_numeric != self.numeric_rep:
            self.values = {el: None for el in self.rows}
            self.notice = Status("warning", "Enter values in the new input column",
                                 "The previous column contained invalid values, so they could not be converted.")
        self.input_rep = key
        for row in self.rows.values():
            for f in row.fields.values():
                f.set_invalid(False)
        self._apply_editability()
        self.refresh()
        self.changed.emit()

    def _apply_editability(self):
        rep = self.input_rep
        for row in self.rows.values():
            row.el.setReadOnly(rep != "element")
            row.el.setFocusPolicy(Qt.FocusPolicy.StrongFocus if rep == "element" else Qt.FocusPolicy.NoFocus)
            for r, f in row.fields.items():
                f.setReadOnly(r != rep)
                f.setFocusPolicy(Qt.FocusPolicy.StrongFocus if r == rep else Qt.FocusPolicy.ClickFocus)
            refresh_style(row.el)
        mass_total = self.totals["mass"]
        mass_total.setReadOnly(rep == "mass")

    def _edited(self, el: str, rep: str):
        if rep != self.numeric_rep or self.input_rep == "element" or el not in self.rows:
            return
        self.notice = None
        f = self.rows[el].fields[rep]
        v = f.number()
        if f.text().strip() == "":
            self.values[el] = None
            f.set_invalid(True, f"{el}: value required")
        elif v is None:
            self.values[el] = None
            f.set_invalid(True, f"{el}: enter a number")
        elif v < 0:
            self.values[el] = None
            f.set_invalid(True, f"{el}: value must be ≥ 0")
        else:
            self.values[el] = v
            f.set_invalid(False)
        self.refresh(skip=(el, rep))
        self.changed.emit()

    def _value_committed(self, _row: SingleRow):
        if self.input_rep == "mass" and self._representations() is not None:
            self.total_mass_committed.emit(self.total_mass)

    def _element_edited(self, row: SingleRow):
        others = {e for e in self.rows if e != row.element}
        new, error = check_symbol(row.el.text(), self.data, others, row.element)
        if error:
            row.el.set_invalid(True, error)
            self.element_error = (row, error)
            self.changed.emit()
            return
        row.el.set_invalid(False)
        self.element_error = None
        if new != row.element:
            self.element_renamed.emit(row.element, new)
        self.changed.emit()

    def rename(self, old: str, new: str, order: list[str]):
        """Replace ``old`` by ``new`` keeping its value (called by the panel after selection sync)."""
        row = self.rows.pop(old)
        row.element = new
        row.el.setText(new)
        for rep, f in row.fields.items():
            f.setAccessibleName(f"{new} {C.REPRESENTATION_LABELS[rep]}")
        self.rows[new] = row
        self.values[new] = self.values.pop(old, None)
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
        """at.% / wt.% input whose column does not sum to 100 % (Figma State: "Composition sum ≠ 100%")."""
        s = self.column_sum()
        return self.numeric_rep in ("at", "wt") and s is not None and abs(s - 100.0) > SUM_TOLERANCE

    def refresh(self, skip: tuple | None = None):
        reps = self._representations()
        active = self.numeric_rep
        for el, row in self.rows.items():
            for rep, f in row.fields.items():
                if skip == (el, rep):
                    continue
                if rep == active:
                    if not f.hasFocus():
                        v = self.values.get(el)
                        f.setText(fmt(v, DECIMALS[rep]) if v is not None else f.text())
                    continue
                f.setText(fmt(reps[rep][el], DECIMALS[rep]) if reps else "")
        # totals
        if reps is None:
            s = self.column_sum()
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
        if not self.rows:
            return None
        if self.element_error:
            return Status("error", self.element_error[1])
        bad = [row.fields[self.numeric_rep] for row in self.rows.values()
               if self.input_rep != "element" and row.fields[self.numeric_rep].error]
        if bad or any(v is None for v in self.values.values()):
            msg = bad[0].error if len(bad) == 1 else "Missing or invalid values"
            return Status("error", msg[:1].upper() + msg[1:])
        if self.totals["mass"].error:
            return Status("error", self.totals["mass"].error)
        if self.sum_off():
            return Status("error", "Composition sum ≠ 100%",
                          "at.% and wt.% values must sum to 100 %. Use Normalize (Calculate menu) to scale them.")
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
    def can_normalise(self) -> bool:
        return self.input_rep in ("at", "wt") and bool(self.rows)

    def can_set_equal(self) -> bool:
        return self.input_rep != "element" and bool(self.rows)

    def set_equal(self):
        self.notice = None
        self.values = C.set_equal(list(self.rows), self.numeric_rep, total_mass=self.total_mass)
        for row in self.rows.values():
            for f in row.fields.values():
                f.set_invalid(False)
        self.refresh()
        self.changed.emit()

    def normalise(self):
        try:
            self.values = C.normalise(dict(self.values), self.numeric_rep)
        except ValueError as exc:
            self.notice = Status("error", "Cannot normalize", str(exc))
            self.changed.emit()
            return
        self.notice = None
        for row in self.rows.values():
            for f in row.fields.values():
                f.set_invalid(False)
        self.refresh()
        self.changed.emit()

    def composition(self):
        """Return (name, amounts as atomic ratios) or raise ValueError with a user message."""
        st = self.status()
        if len(self.rows) < 2:
            raise ValueError("Select at least two elements.")
        if st is not None and st.blocking:
            raise ValueError(st.text + ".")
        x = C.to_fractions(dict(self.values), self.numeric_rep, self.data)
        ratios = C.from_fractions(x, "ratio")
        return C.alloy_name(ratios), ratios

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
        self.values = {el: (1.0 if self.input_rep in ("ratio", "element") else 0.0) for el in self.rows}
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


def header_label(text: str, width: int, center: bool = False, role: str | None = None) -> QLabel:
    c = QLabel(text)
    c.setFixedSize(width, ROW_H)
    col_role(c, role or ("element" if width == COL_ELEMENT else "value"))
    c.setProperty("col_header", not center)
    c.setStyleSheet("font-weight: 600;")
    if center:
        c.setAlignment(Qt.AlignmentFlag.AlignCenter)
    else:
        c.setContentsMargins(16, 0, 0, 0)
    return c


# ======================================================================== composition space
SWEEP_MARGIN = 31  # Figma: table starts at x = 31


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
        lock_cell = col_role(QFrame(), "lock")
        lock_cell.setObjectName("LockCell")
        lock_cell.setFixedSize(COL_LOCK, ROW_H)
        ll = QHBoxLayout(lock_cell)
        ll.setContentsMargins(0, 0, 0, 0)
        self.lock = Toggle(True)
        # the column header says "Lock"; the toggle explains what locking means (not just its name)
        self.lock.setToolTip("On: always present (required). Off: optional - systems with and without it")
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


class SweepView(QWidget):
    """Composition space (Figma "_Composition setup Composition space bases" 392:60079): per-element ranges in
    the range basis, Lock (required / optional), All row, System size and the workload summary."""

    grid = ColumnGrid()
    changed = Signal()
    message = Signal(str, str)
    element_renamed = Signal(str, str)

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
        head.addWidget(header_label("Elem.", COL_ELEMENT, True))
        self.h_min = header_label("Min", COL_VALUE)
        self.h_max = header_label("Max", COL_VALUE)
        self.h_step = header_label("Step", COL_VALUE)
        for w in (self.h_min, self.h_max, self.h_step):
            head.addWidget(w)
        head.addWidget(header_label("Lock", COL_LOCK, True, role="lock"))
        head.addStretch(1)
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
        lab.setFixedSize(COL_ELEMENT, ROW_H)
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setStyleSheet("font-weight: 600;")
        ar.addWidget(lab)
        self.all_min, self.all_max, self.all_step = Field(COL_VALUE), Field(COL_VALUE), Field(COL_VALUE)
        for f, attr in ((self.all_min, "min"), (self.all_max, "max"), (self.all_step, "step")):
            f.setAccessibleName(f"All {attr}")
            f.editingFinished.connect(lambda a=attr, fld=f: self._apply_all(a, fld))
            ar.addWidget(f)
        lc = col_role(QWidget(), "lock")
        lc.setFixedSize(COL_LOCK, ROW_H)
        lcl = QHBoxLayout(lc)
        lcl.setContentsMargins(0, 0, 0, 0)
        self.all_lock = Toggle(True)
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
        self.size_box.changed.connect(lambda _sel: self._edited())
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
                row.set_values(RANGE_DEFAULTS[self.unit])
                for f in (row.min, row.max, row.step):
                    f.textEdited.connect(lambda _t, fld=f: (fld.set_invalid(False), self._edited()))
                row.lock.toggled.connect(lambda _c: self._edited())
                row.el.editingFinished.connect(lambda r=row: self._element_edited(r))
                self.rows[el] = row
                self.rows_widget.insert(row)
        self.rows_widget.order([self.rows[el] for el in elements])
        self.rows = {el: self.rows[el] for el in elements}
        self.rows_stack.setCurrentIndex(1 if elements else 0)
        self._refresh_sizes()
        self._sync_enabled()
        self._edited()

    def _element_edited(self, row: SweepRow):
        others = {e for e in self.rows if e != row.element}
        new, error = check_symbol(row.el.text(), self.data, others, row.element)
        if error:
            row.el.set_invalid(True, error)
            self.element_error = (row, error)
            self.changed.emit()
            return
        row.el.set_invalid(False)
        self.element_error = None
        if new != row.element:
            self.element_renamed.emit(row.element, new)
        self.changed.emit()

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

    def set_unit(self, unit: str):
        """Range basis (at. ratio / at.% / wt.% / mass): new defaults for every row, recounted."""
        if unit == self.unit:
            return
        self.unit = unit
        for row in self.rows.values():
            row.set_values(RANGE_DEFAULTS[unit])
        self._edited()

    def _refresh_sizes(self):
        n = len(self.rows)
        sel = tuple(k for k in self.size_box.selected if k <= n)
        self.size_box.set_options([(k, str(k)) for k in range(2, n + 1)], sel)

    def _sync_enabled(self):
        has = bool(self.rows)
        for w in (self.all_min, self.all_max, self.all_step, self.all_lock, self.size_box):
            w.setEnabled(has)

    def _edited(self):
        self._sync_all_row()
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
                                       {"min": "Min", "max": "Max", "step": "Step"}[attr])
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
        if C.parse_number(text) is None:
            fld.set_invalid(True, f"All {attr}: enter a number")
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

    # -- data
    def specs(self) -> list[SweepSpec]:
        out = []
        for el, row in self.rows.items():
            vals = []
            for f, name in ((row.min, "Min"), (row.max, "Max"), (row.step, "Step")):
                v = f.number()
                f.set_invalid(v is None, f"{el}: {name} is missing or invalid")
                vals.append(v)
            if None in vals:
                raise RangeError("Missing range values")
            spec = SweepSpec(el, vals[0], vals[1], vals[2], row.lock.isChecked())
            try:
                spec.as_range().validate()
            except RangeError as exc:
                bad = row.max if "Max" in str(exc) else row.step if "Step" in str(exc) else row.min
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
        if not self.rows:
            return None
        if self.element_error:
            return Status("error", self.element_error[1])
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
    calculate_requested = Signal(object, object, object, object)  # source, names, compositions, variables
    elements_changed = Signal(list)                       # elements chosen inside the panel
    message = Signal(str, str)
    copy_compositions = Signal(str)                       # TSV of generated compositions
    copy_text = Signal(str, str)                          # TSV, description (Single: Copy table)
    mode_changed = Signal(str)                            # "single" | "sweep" | "expression"
    cancel_requested = Signal()
    total_mass_committed = Signal(float)

    MODES = ("single", "sweep", "expression")

    def __init__(self, datasets: Datasets, parent=None, engine=None):
        super().__init__(MODE_TITLES["single"], parent)
        self.data = datasets
        self.engine = engine
        self._coverage_cache: dict[frozenset, dict] = {}
        self.title_holder.setFixedHeight(55)
        # Range basis (Figma: an inline dropdown at x 229, 12 px before the mode switcher; Composition space only)
        # CORRECT_RANGE_BASIS / Figma 392:60079: 140 px inline trigger showing the basis; while open it reads
        # "Range basis" inside the focus frame above the divided list (no tooltip - the label is the explanation)
        self.unit_box = Dropdown(RANGE_BASES, "ratio", inline=True, accessible="Range basis",
                                 open_label="Range basis", width=140)
        self.unit_box.hide()
        self.title_row.addWidget(self.unit_box)
        self.title_row.addSpacing(12)
        self.switcher = IconContentSwitcher([("mode_single", MODE_TITLES["single"]),
                                             ("mode_sweep", MODE_TITLES["sweep"]),
                                             ("mode_expression", MODE_TITLES["expression"])])
        self.title_row.addWidget(self.switcher)
        self.title_row.setContentsMargins(20, 0, 18, 0)
        self.root.addWidget(Divider())
        self.stack = QStackedWidget()
        self.single = SingleView(datasets)
        self.sweep = SweepView(datasets)
        self.expr = ExpressionView(datasets)
        for v in (self.single, self.sweep, self.expr):
            self.stack.addWidget(v)
            v.changed.connect(self._update_actions)
            v.message.connect(self.message.emit)
        self.root.addWidget(self.stack, 1)
        self.expr.elements_parsed.connect(self.elements_changed.emit)
        self.single.element_renamed.connect(self._renamed)
        self.sweep.element_renamed.connect(self._renamed)
        self.single.total_mass_committed.connect(self.total_mass_committed.emit)
        self.unit_box.changed.connect(lambda v: self.sweep.set_unit(v))

        # footer (Figma: 32 px, status | Clear | Calculate [▾])
        self.footer = CompositionFooter()
        self.root.addWidget(self.footer)
        self.clear_btn = self.footer.clear_btn
        self.calc_btn = self.footer.calc_btn
        self.clear_btn.clicked.connect(self._clear_or_cancel)
        self.calc_btn.clicked.connect(self.calculate)
        self.switcher.changed.connect(self.set_mode)
        self.setFixedWidth(COMPOSITION_PANEL_WIDTH)      # not responsive: the Figma component's width
        self.grid = ColumnGrid()
        for v in (self.single, self.sweep, self.expr):
            v.grid = self.grid
        self._elements: list[str] = []
        self.service = None
        self._calculating = False
        self.set_mode(0)

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
        self.stack.setCurrentIndex(i)
        self.switcher.set_index(i)
        self.title.setText(MODE_TITLES[self.mode])          # the panel title names the mode
        self.unit_box.setVisible(self.mode == "sweep")
        self.footer.set_split(self.mode != "sweep")
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

    def element_toggled(self, el: str, selected: bool):
        if self.mode == "expression":
            if selected:
                self.expr.add_element(el)
            else:
                self.expr.remove_element(el)
            return
        if selected and el not in self._elements:
            self._elements.append(el)
        elif not selected and el in self._elements:
            self._elements.remove(el)
        self.set_elements(self._elements)

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
        self.footer.set_running(running)
        # CORRECT_CALCULATING_STATE: the inputs of the running recipe are read-only (disabled tokens), the
        # basis / mode controls too; the footer keeps its status (never "Ready" while a run is going)
        self.stack.setEnabled(not running)
        self.unit_box.setEnabled(not running)
        self.switcher.setEnabled(not running)
        self._update_actions()

    # ---------------------------------------------------------------- status / actions
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
        st = self.view().status()
        if st is None:
            cov = coverage_status(self.coverage(self.current_elements()))
            if cov is not None:
                return cov
            # the expression editor reports its own state in place (COMPOSITION_EXPRESSION_* show no footer status)
            if self.mode == "sweep" and self.view().can_calculate() and not self._calculating:
                return Status("ready", "Ready")
        return st

    def _update_actions(self):
        m = self.mode
        v = self.view()
        self.footer.status.set_status(self.status())
        if m == "single":
            has = bool(self._elements)
            self.footer.calc.set_actions([("Normalize", self._normalize, self.single.can_normalise(), None),
                                          ("Set equal", self._set_equal, self.single.can_set_equal(), None),
                                          ("-", None, False, None),
                                          ("Copy table", self._copy_single, has, "copy")])
            self.clear_btn.setEnabled(has or self._calculating)
        elif m == "sweep":
            self.clear_btn.setEnabled(bool(self._elements) or self._calculating)
        else:
            has = bool(self.expr.text().strip())
            self.footer.calc.set_actions([("Copy table", self._copy_expression, self.expr.can_calculate(),
                                           "copy")])
            self.clear_btn.setEnabled(has or self._calculating)
        self.calc_btn.setEnabled(v.can_calculate() and not self._calculating)

    def _clear_or_cancel(self):
        if self._calculating:
            self.cancel_requested.emit()
            return
        self.clear()

    def _normalize(self):
        if self.mode == "single":
            self.single.normalise()

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

    def _copy_expression(self):
        """One block: its composition preview table; several blocks: every generated composition."""
        doc = self.expr.doc
        if doc is not None and doc.ok and len(doc.blocks) == 1 and doc.blocks[0].kind == "fixed":
            self.copy_text.emit(self.expr.preview_tsv(), "composition table")
        else:
            self._copy_compositions()

    def clear(self):
        if self.mode == "expression":
            self.expr.clear()
            self.elements_changed.emit([])
            self._update_actions()
            return
        self._elements = []
        self.set_elements([])
        self.elements_changed.emit([])

    def calculate(self):
        m = self.mode
        try:
            if m == "single":
                name, ratios = self.single.composition()
                self.calculate_requested.emit("single", [name], [ratios], [{}])
            elif m == "sweep":
                # generation happens in the calculation job, not here (it can be millions of rows)
                self.calculate_requested.emit("sweep", None, self.sweep.recipe(), None)
            else:
                self.calculate_requested.emit("expression", None, self.expr.recipe(), None)
        except (ValueError, RangeError, ExpressionError) as exc:
            self.message.emit("error", str(exc))
