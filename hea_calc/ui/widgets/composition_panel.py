"""Composition Setup panel (Figma 278:30198) with three workflows sharing one engine:

* Single composition — editable representation columns (El., At. ratio, at.%, wt.%, Mass)
* Composition sweep — composition space: per-element Min / Max / Step (at. ratio or at.%), Lock
  (required/optional), system-size filter (Figma 278:17008)
* Expression mode — one or more expression blocks with variables, Min / Max / Step per variable
  (Figma 256:38340)

The panel only builds compositions; calculations are requested through ``calculate_requested``.
"""

from __future__ import annotations

import math
import re

from PySide6.QtCore import QPointF, QTimer, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QRadioButton, QScrollArea, QSizePolicy, QSpacerItem, QStackedWidget,
                               QVBoxLayout, QWidget)

from ...core import composition as C
from ...core.data import Datasets
from ...core.expression import (ExpressionError, VariableRange, block_variables, generate_blocks,
                                 parse_blocks)
from ...core.generation import RangeError, SweepSpec, generate_space, summarize_space
from .. import crisp
from ..theme import COMPOSITION_PANEL_MIN, FOCUS_WIDTH, HAIRLINE, t
from .scroll import own_wheel, thin_scrollbars
from .common import (Divider, EmptyState, IconButton, IconContentSwitcher, InfoButton, Panel, button,
                     install_wheel_guard, refresh_style)

COL_ELEMENT = 64
COL_VALUE = 88
COL_GAP = 1
COL_LOCK = 64
ROW_H = 32
ROW_GAP = 1
REP_KEYS = ("ratio", "at", "wt", "mass")
DECIMALS = {"ratio": 4, "at": 4, "wt": 4, "mass": 5}
SWEEP_LIMIT = 200_000


class ColumnGrid:
    """Column widths shared by the three composition tables (single, sweep, expression).

    The design columns (element 64, value 88, lock 64 px, 1 px gaps) fit the 457 px panel.  On a
    narrower panel (Windows 125 % / 150 %) the columns compress with the panel and the value
    fields' horizontal text padding shrinks from 16 px towards 8 px, so a five-digit value such as
    ``14.2857`` still fits unclipped.  Widgets opt in with a ``col_role`` property (element / value
    / lock); :meth:`apply` re-sizes every tagged descendant of a widget.
    """

    DESIGN_PANEL = 457
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
                # "At. ratio" = 20 px indicator + 8 px spacing + 51 px label; below an 80 px column
                # the spacing tightens to 4 px so the label never runs into the next radio
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

    Its strokes - the 1 px bottom rule, the 2 px focus frame and the 2 px invalid frame - are
    painted in device pixels (``crisp``) rather than by QSS borders: at DPR 1.25 a QSS 1 px rule
    rendered 1 or 2 device px depending on the field's position, and a 2 px frame 2 px on some sides
    and 3 px on others.  The QSS only provides background, text and the hover state.
    """

    def __init__(self, width: int, parent=None, cell: str = "value"):
        super().__init__(parent)
        self.setFixedSize(width, ROW_H)
        self.setProperty("cell", cell)
        self.setProperty("crisp", True)
        col_role(self, "element" if width == COL_ELEMENT else "value")
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
        if bool(self.property("invalid")) != invalid:
            self.setProperty("invalid", invalid)
            refresh_style(self)
        self.setToolTip(message if invalid else "")

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
        from PySide6.QtGui import QColor, QLinearGradient, QPainter
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


# ======================================================================== single composition
class SingleRow(QWidget):
    def __init__(self, element: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(COL_GAP)
        self.element = element
        self.el = Field(COL_ELEMENT, cell="element")
        self.el.setText(element)
        self.el.setMaxLength(2)
        self.el.setAccessibleName("Element")
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
    message = Signal(str, str)          # kind, text

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        self.input_rep = "ratio"         # active input column (or "element")
        self.values: dict[str, float | None] = {}  # values of the active numeric column, full precision
        self.total_mass = 2.0
        self.rows: dict[str, SingleRow] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Input column radio group (Figma 278:30254 at y 68, 44 px)
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

        # Totals (Figma: band from y 332, divider, total row at y 373)
        totals = QWidget()
        totals.setFixedHeight(67)
        tl = QVBoxLayout(totals)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.addWidget(Divider())
        trow = QHBoxLayout()
        trow.setContentsMargins(19, 16, 0, 18)
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
                f.setText(f"{self.total_mass:g}")
                f.setToolTip("Total mass (g)")
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
                row.setParent(None)
                row.deleteLater()
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
        for i, el in enumerate(elements):
            self.rows_widget.lay.removeWidget(self.rows[el])
            self.rows_widget.lay.insertWidget(i, self.rows[el])
        self.rows = {el: self.rows[el] for el in elements}
        self.values = {el: self.values.get(el) for el in elements}
        self.rows_stack.setCurrentIndex(1 if elements else 0)
        self._apply_editability()
        self.refresh()

    def _wire(self, row: SingleRow):
        for rep, f in row.fields.items():
            f.textEdited.connect(lambda _txt, el=row.element, r=rep: self._edited(el, r))
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
        if reps is not None:
            self.values = dict(reps[new_numeric])
        elif new_numeric != self.numeric_rep:
            self.values = {el: None for el in self.rows}
            self.message.emit("warning", "The previous column contained invalid values; enter values in the "
                                         "new input column.")
        self.input_rep = key
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
        if rep != self.numeric_rep or self.input_rep == "element":
            return
        f = self.rows[el].fields[rep]
        v = f.number()
        if f.text().strip() == "":
            self.values[el] = None
            f.set_invalid(True, "Value required")
        elif v is None:
            self.values[el] = None
            f.set_invalid(True, "Enter a number")
        elif v < 0:
            self.values[el] = None
            f.set_invalid(True, "Value must be ≥ 0")
        else:
            self.values[el] = v
            f.set_invalid(False)
        self.refresh(skip=(el, rep))
        self.changed.emit()

    def _element_edited(self, row: SingleRow):
        new = row.el.text().strip()
        new = new[:1].upper() + new[1:].lower() if new else new
        old = row.element
        if new == old:
            row.el.set_invalid(False)
            return
        if not self.data.is_element(new):
            row.el.set_invalid(True, f"'{new}' is not an element symbol")
            self.message.emit("error", f"'{new}' is not an element symbol.")
            return
        if new in self.rows:
            row.el.set_invalid(True, f"{new} is already in the composition")
            self.message.emit("error", f"{new} is already in the composition.")
            return
        row.el.set_invalid(False)
        self.element_renamed.emit(old, new)

    def rename(self, old: str, new: str, order: list[str]):
        """Replace ``old`` by ``new`` keeping its value (called by the window after selection sync)."""
        row = self.rows.pop(old)
        row.element = new
        row.el.setText(new)
        for rep, f in row.fields.items():
            try:
                f.textEdited.disconnect()
            except (TypeError, RuntimeError):
                pass
            f.textEdited.connect(lambda _txt, el=new, r=rep: self._edited(el, r))
        self.rows[new] = row
        self.values[new] = self.values.pop(old, None)
        self.set_elements(order)

    def _total_mass_edited(self):
        f = self.totals["mass"]
        if not f.text().strip() and not self.rows:
            return
        v = f.number()
        if v is None or v <= 0:
            f.set_invalid(True, "Total mass must be > 0")
            return
        f.set_invalid(False)
        self.total_mass = v
        self.refresh()

    def _representations(self):
        vals = self.values
        if not vals or any(v is None for v in vals.values()) or sum(vals.values()) <= 0:
            return None
        try:
            return C.all_representations(dict(vals), self.numeric_rep, total_mass=self.total_mass, datasets=self.data)
        except ValueError:
            return None

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
            raw = [v for v in self.values.values() if v is not None]
            s = sum(raw) if raw else None
            for rep in ("ratio", "at", "wt"):
                lab = self.totals[rep]
                if rep == active and s is not None:
                    lab.setText(f"{s:.2f}" if rep == "ratio" else f"{s:.4g}%")
                else:
                    lab.setText("—")
        else:
            self.totals["ratio"].setText(f"{sum(reps['ratio'].values()):.2f}")
            self.totals["at"].setText(f"{sum(reps['at'].values()):.4g}%")
            self.totals["wt"].setText(f"{sum(reps['wt'].values()):.4g}%")
            if active == "mass":
                self.total_mass = sum(reps["mass"].values())
        mt = self.totals["mass"]
        mt.setPlaceholderText("Total mass")
        if not self.rows:
            for rep in ("ratio", "at", "wt"):
                self.totals[rep].setText("0.00")
            if not mt.hasFocus():
                mt.clear()
        elif not mt.hasFocus():
            mt.setText(f"{self.total_mass:.5g}")
        for rep in ("at", "wt"):
            lab = self.totals[rep]
            off = rep == active and reps is None and self.values and all(v is not None for v in self.values.values())
            lab.setStyleSheet(f"color: {t('text-error')};" if off else "")

    # ---------------------------------------------------------------- actions
    def can_normalise(self) -> bool:
        return self.input_rep in ("at", "wt") and bool(self.rows)

    def can_set_equal(self) -> bool:
        return self.input_rep != "element" and bool(self.rows)

    def set_equal(self):
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
            self.message.emit("error", f"Cannot normalize: {exc}")
            return
        self.refresh()
        self.changed.emit()

    def composition(self):
        """Return (name, amounts as atomic ratios) or raise ValueError with a user message."""
        if len(self.rows) < 2:
            raise ValueError("Select at least two elements.")
        bad = [el for el, v in self.values.items() if v is None]
        if bad:
            raise ValueError("Missing or invalid value for " + ", ".join(bad) + ".")
        if sum(self.values.values()) <= 0:
            raise ValueError("Total is zero.")
        x = C.to_fractions(dict(self.values), self.numeric_rep, self.data)
        if sum(1 for v in x.values() if v > 0) < 2:
            raise ValueError("At least two elements need non-zero amounts.")
        ratios = C.from_fractions(x, "ratio")
        return C.alloy_name(ratios), ratios

    def clear(self):
        self.values = {el: (1.0 if self.input_rep in ("ratio", "element") else 0.0) for el in self.rows}
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
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
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


# ======================================================================== composition space (sweep)
SWEEP_MARGIN = 31  # Figma 278:17008: table starts at x = 31



class SweepRow(QWidget):
    def __init__(self, element: str, parent=None):
        super().__init__(parent)
        self.element = element
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(COL_GAP)
        self.el = Field(COL_ELEMENT, cell="element-filled")
        self.el.setText(element)
        self.el.setReadOnly(True)
        self.el.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        self.lock.setToolTip("Lock on: element always present (required). Off: optional — systems with and "
                             "without it are generated.")
        self.lock.setAccessibleName(f"{element} required")
        ll.addWidget(self.lock, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lock_cell)
        lay.addStretch(1)
        self.setFixedHeight(ROW_H)


class SweepView(QWidget):
    grid = ColumnGrid()
    """Composition space (Figma 278:17008): per-element ranges, Lock (required/optional), All row,
    system-size filter and live counts."""

    changed = Signal()
    message = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: dict[str, SweepRow] = {}
        self.unit = "ratio"
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
        self.page = QWidget()
        pl = QVBoxLayout(self.page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        pl.addWidget(hw)
        self.rows_widget = _Rows(margin=SWEEP_MARGIN)
        self.scroll = scroll_wrap(self.rows_widget)
        pl.addWidget(self.scroll, 1)
        # All row
        all_w = QWidget()
        all_w.setFixedHeight(57)
        al = QVBoxLayout(all_w)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)
        al.addWidget(Divider())
        ar = QHBoxLayout()
        ar.setContentsMargins(SWEEP_MARGIN, 12, 0, 12)
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
        pl.addWidget(all_w)
        # summary + system size (Figma: two text lines left, dropdown right)
        sum_w = QWidget()
        sum_w.setFixedHeight(68)
        sl = QVBoxLayout(sum_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.addWidget(Divider())
        srow = QHBoxLayout()
        srow.setContentsMargins(SWEEP_MARGIN, 8, 20, 8)
        self.summary = QLabel("")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        srow.addWidget(self.summary, 1)
        self.size_box = QComboBox()
        self.size_box.setAccessibleName("System size")
        self.size_box.setToolTip("Restrict the number of elements per system (optional elements)")
        self.size_box.setMinimumWidth(120)
        self.size_box.currentIndexChanged.connect(lambda _i: self._edited())
        srow.addWidget(self.size_box, 0, Qt.AlignmentFlag.AlignVCenter)
        sl.addLayout(srow)
        pl.addWidget(sum_w)
        self.empty = EmptyState("Start by selecting elements",
                                "Click elements in the periodic table to set their ranges.",
                                art="magnifier")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.page)
        root.addWidget(self.stack, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_summary)
        self.summary_data = None
        self._refresh_sizes()

    # -- elements
    def set_elements(self, elements: list[str]):
        for el in list(self.rows):
            if el not in elements:
                row = self.rows.pop(el)
                row.setParent(None)
                row.deleteLater()
        for el in elements:
            if el not in self.rows:
                row = SweepRow(el)
                self.grid.apply(row)
                if self.unit == "ratio":
                    row.min.setText("1.0")
                    row.max.setText("1.0")
                    row.step.setText("0.1")
                else:
                    row.min.setText("0")
                    row.max.setText("100")
                    row.step.setText("10")
                for f in (row.min, row.max, row.step):
                    f.textEdited.connect(lambda _t: self._edited())
                row.lock.toggled.connect(lambda _c: self._edited())
                self.rows[el] = row
                self.rows_widget.insert(row)
        for i, el in enumerate(elements):
            self.rows_widget.lay.removeWidget(self.rows[el])
            self.rows_widget.lay.insertWidget(i, self.rows[el])
        self.rows = {el: self.rows[el] for el in elements}
        self.stack.setCurrentIndex(1 if elements else 0)
        self._refresh_sizes()
        self._edited()

    def set_unit(self, unit: str):
        if unit == self.unit:
            return
        self.unit = unit
        for row in self.rows.values():
            if unit == "ratio":
                row.min.setText("1.0"), row.max.setText("1.0"), row.step.setText("0.1")
            else:
                row.min.setText("0"), row.max.setText("100"), row.step.setText("10")
        self._edited()

    def _refresh_sizes(self):
        n = len(self.rows)
        cur = self.size_box.currentData()
        self.size_box.blockSignals(True)
        self.size_box.clear()
        self.size_box.addItem("System size", None)
        for k in range(2, n + 1):
            self.size_box.addItem(f"{k} elements", k)
        idx = self.size_box.findData(cur) if cur is not None else 0
        self.size_box.setCurrentIndex(max(idx, 0))
        self.size_box.blockSignals(False)

    def _edited(self):
        self._sync_all_row()
        self.changed.emit()
        self._timer.start()

    def _sync_all_row(self):
        rows = list(self.rows.values())
        for fld, attr in ((self.all_min, "min"), (self.all_max, "max"), (self.all_step, "step")):
            vals = {getattr(r, attr).text().strip() for r in rows}
            if not fld.hasFocus():
                fld.clear()
                fld.setPlaceholderText((vals.pop() if len(vals) == 1 else "Mixed") if rows else "")
        locks = {r.lock.isChecked() for r in rows}
        self.all_lock.mixed = len(locks) > 1
        self.all_lock.blockSignals(True)
        self.all_lock.setChecked(all(locks) if locks else True)
        self.all_lock.blockSignals(False)
        self.all_lock.update()

    def _apply_all(self, attr: str, fld: Field):
        text = fld.text().strip()
        if not text:
            return
        if C.parse_number(text) is None:
            fld.set_invalid(True, "Enter a number")
            return
        fld.set_invalid(False)
        for r in self.rows.values():
            getattr(r, attr).setText(text)
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
            for f in (row.min, row.max, row.step):
                v = f.number()
                f.set_invalid(v is None, "Enter a number")
                vals.append(v)
            if None in vals:
                raise RangeError(f"{el}: enter Min, Max and Step.")
            out.append(SweepSpec(el, vals[0], vals[1], vals[2], row.lock.isChecked()))
        return out

    def sizes(self):
        k = self.size_box.currentData()
        return {k} if k else None

    def _update_summary(self):
        n = len(self.rows)
        if n == 0:
            self.summary.setText("")
            return
        sep = f"<span style='color:{t('text-helper')}'> | </span>"
        try:
            s = summarize_space(self.specs(), self.unit, self.sizes(), limit=SWEEP_LIMIT)
        except RangeError as exc:
            self.summary.setText(f"<span style='color:{t('text-error')}'>{exc}</span>")
            self.summary_data = None
            return
        self.summary_data = s
        line1 = f"{s.selected} selected{sep}{s.required} required{sep}{s.optional} optional"
        comp = f"more than {SWEEP_LIMIT:,}" if s.truncated else f"{s.compositions:,}"
        color = t("text-error") if s.truncated or s.compositions == 0 else t("text-primary")
        line2 = (f"{s.systems} combination{'s' if s.systems != 1 else ''}{sep}"
                 f"<span style='color:{color}'>{comp} valid composition{'s' if s.compositions != 1 else ''}</span>")
        self.summary.setText(f"{line1}<br>{line2}")

    def can_calculate(self) -> bool:
        return len(self.rows) >= 2

    def compositions(self):
        comps = generate_space(self.specs(), self.unit, self.sizes(), limit=SWEEP_LIMIT)
        if not comps:
            raise RangeError("No valid compositions for these ranges"
                             + (" (at.% values must sum to 100 %)." if self.unit == "at" else "."))
        names = [C.percent_name(c) if self.unit == "at" else C.alloy_name(c) for c in comps]
        return names, comps

    def clear(self):
        for row in self.rows.values():
            if self.unit == "ratio":
                row.min.setText("1.0"), row.max.setText("1.0"), row.step.setText("0.1")
            else:
                row.min.setText("0"), row.max.setText("100"), row.step.setText("10")
            row.lock.setChecked(True)
        self._edited()


# ======================================================================== expression
class VariableRow(QWidget):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(COL_GAP)
        self.var = Field(COL_ELEMENT, cell="element-filled")
        self.var.setText(name)
        self.var.setReadOnly(True)
        self.var.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.var.setStyleSheet("font-style: italic;")
        lay.addWidget(self.var)
        self.min, self.max, self.step = Field(COL_VALUE), Field(COL_VALUE), Field(COL_VALUE)
        for f, label in ((self.min, "Min"), (self.max, "Max"), (self.step, "Step")):
            f.setAccessibleName(f"{name} {label}")
            lay.addWidget(f)
        lay.addStretch(1)
        self.setFixedHeight(ROW_H)


HELPER_TEXT = "Enter one expression per block. Separate blocks with a blank line."

EXPRESSION_HELP = (
    "<b>Composition expression</b><br>"
    "Elements: Fe, Co, Al … · Variables: lowercase names (x, y1).<br>"
    "Amounts follow an element or a group: <i>Al0.5</i>, <i>Alx</i>, <i>(FeCoNi)1-x</i>, "
    "<i>Ti{0.1*k}</i>, <i>Mo_(1-y)</i>.<br>"
    "Groups (…) are normalised: (FeCoNi)90Al10 = 30/30/30/10 at.%.<br>"
    "Use braces when a variable would merge with a symbol: B{a}.<br>"
    "Enter one expression per block; separate blocks with a blank line."
)


class ExpressionView(QWidget):
    grid = ColumnGrid()
    """Expression mode (Figma 256:38340): multi-block expression text area, detected variables with
    Min / Max / Step, live count of valid compositions."""

    changed = Signal()
    elements_parsed = Signal(list)
    message = Signal(str, str)
    preview_requested = Signal()

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        self.expressions: list = []
        self.var_rows: dict[str, VariableRow] = {}
        self._remembered: dict[str, tuple[str, str, str]] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 0)
        root.setSpacing(0)
        lab_row = QHBoxLayout()
        lab_row.setSpacing(8)
        lab = QLabel("Composition expression")
        lab.setObjectName("Label01")
        lab_row.addWidget(lab)
        lab_row.addWidget(InfoButton(EXPRESSION_HELP, title="Expression syntax"))
        lab_row.addStretch(1)
        root.addLayout(lab_row)
        root.addSpacing(8)
        self.edit = QPlainTextEdit()
        thin_scrollbars(self.edit)
        own_wheel(self.edit)
        self.edit.setPlaceholderText("e.g. (Fe1.6CoCr0.4Mn)0.9Al0.1")
        self.edit.setFixedHeight(142)
        self.edit.setAccessibleName("Composition expression")
        self.edit.textChanged.connect(self._dirty)
        self.preview_btn = IconButton("data_table", "Preview generated compositions", self.edit)
        self.preview_btn.clicked.connect(self.preview_requested.emit)
        self.edit.installEventFilter(self)
        root.addWidget(self.edit)
        root.addSpacing(6)
        self.detected = (0, [], [])
        self.helper = QLabel(HELPER_TEXT)
        self.helper.setObjectName("Helper")
        self.helper.setWordWrap(True)
        self.helper.setTextFormat(Qt.TextFormat.RichText)
        self.helper.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        root.addWidget(self.helper)
        root.addSpacing(10)
        cols = QHBoxLayout()
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(COL_GAP)
        cols.addWidget(header_label("Var.", COL_ELEMENT, True))
        for text in ("Min", "Max", "Step"):
            cols.addWidget(header_label(text, COL_VALUE))
        cols.addStretch(1)
        self.var_header = QWidget()
        self.var_header.setLayout(cols)
        self.var_header.setFixedHeight(ROW_H)
        root.addWidget(self.var_header)
        self.rows_widget = _Rows(margin=0)
        self.scroll = scroll_wrap(self.rows_widget)
        # One variable row is the least it needs; QScrollArea's own minimum hint (76 px) made the
        # view taller than the panel once the helper wrapped (Windows 150 %), and the layout then
        # overlapped the helper with the expression field.
        self.scroll.setMinimumHeight(ROW_H)
        root.addWidget(self.scroll, 1)
        self.summary = QLabel("")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setFixedHeight(48)
        root.addWidget(self.summary)
        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(350)
        self._parse_timer.timeout.connect(self.parse)
        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.setInterval(250)
        self._count_timer.timeout.connect(self._preview)
        self._set_variables([])

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == ev.Type.Resize:
            self.preview_btn.move(self.edit.width() - 40, 8)
            self._fit_helper()
        return False

    def _fit_helper(self):
        # On a narrow panel (Windows 150 %) the helper wraps to two lines; reserve that height, or the
        # layout keeps a one-line box and the second line is drawn over the field above it.
        w = self.edit.width()
        if w > 0:
            self.helper.setMinimumHeight(self.helper.heightForWidth(w))

    def _dirty(self):
        self._parse_timer.start()
        self.changed.emit()

    def text(self) -> str:
        return self.edit.toPlainText()

    def parse(self) -> bool:
        if not self.text().strip():
            self.expressions = []
            self._set_invalid(False)
            self.helper.setText(HELPER_TEXT)
            self._fit_helper()
            self._set_variables([])
            self.summary.setText("")
            self.changed.emit()
            return False
        try:
            exprs = parse_blocks(self.text(), self.data)
        except ExpressionError as exc:
            self.expressions = []
            self._set_invalid(True)
            self.helper.setText(f"<span style='color:{t('text-error')}'>{exc}</span>")
            self._fit_helper()
            self._set_variables([])
            self.summary.setText("")
            self.changed.emit()
            return False
        self.expressions = exprs
        self._set_invalid(False)
        els: list[str] = []
        for ex in exprs:
            _collect_elements(ex.items, els)
        names = block_variables(exprs)
        self.helper.setText(HELPER_TEXT)
        self._fit_helper()
        self.detected = (len(exprs), els, names)
        self._set_variables(names)
        self.elements_parsed.emit(els)
        self.changed.emit()
        self._preview()
        return True

    def _set_invalid(self, bad: bool):
        if bool(self.edit.property("invalid")) != bad:
            self.edit.setProperty("invalid", bad)
            refresh_style(self.edit)

    def _set_variables(self, names: list[str]):
        if list(self.var_rows) == names:
            return
        for name, row in list(self.var_rows.items()):
            self._remembered[name] = (row.min.text(), row.max.text(), row.step.text())
            row.setParent(None)
            row.deleteLater()
        self.var_rows = {}
        for name in names:
            row = VariableRow(name)
            self.grid.apply(row)
            mn, mx, st = self._remembered.get(name, ("0", "1", "0.1"))
            row.min.setText(mn)
            row.max.setText(mx)
            row.step.setText(st)
            for f in (row.min, row.max, row.step):
                f.textEdited.connect(lambda _t: (self.changed.emit(), self._count_timer.start()))
            self.var_rows[name] = row
            self.rows_widget.insert(row)
        has = bool(names)
        self.var_header.setVisible(has)
        self.scroll.setVisible(has)

    def ranges(self) -> dict[str, VariableRange]:
        out = {}
        for name, row in self.var_rows.items():
            vals = []
            for f in (row.min, row.max, row.step):
                v = f.number()
                f.set_invalid(v is None, "Enter a number")
                vals.append(v)
            if None in vals:
                raise RangeError(f"{name}: enter Min, Max and Step.")
            out[name] = VariableRange(name, *vals)
        return out

    def batch(self):
        if not self.expressions:
            if not self.parse():
                raise ExpressionError("Enter a valid expression first.")
        return generate_blocks(self.expressions, self.ranges())

    def _preview(self):
        if not self.expressions:
            self.summary.setText("")
            return
        try:
            b = self.batch()
        except (RangeError, ExpressionError) as exc:
            self.summary.setText(f"<span style='color:{t('text-error')}'>{exc}</span>")
            return
        n = len(b.compositions)
        extra = []
        if b.skipped:
            extra.append(f"{b.skipped:,} skipped")
        if b.duplicates:
            extra.append(f"{b.duplicates:,} duplicate{'s' if b.duplicates != 1 else ''}")
        blocks, els, names = self.detected
        sep = f"<span style='color:{t('text-helper')}'> | </span>"
        self.summary.setText(f"{blocks} block{'s' if blocks != 1 else ''}{sep}{len(els)} elements{sep}"
                             f"{len(names)} variable{'s' if len(names) != 1 else ''}<br>"
                             f"<b>{n:,}</b> valid composition{'s' if n != 1 else ''}"
                             + (sep + ", ".join(extra) if extra else ""))
        self.summary.setToolTip("Skipped: variable values giving negative amounts or fewer than two elements."
                                if b.skipped else "")

    def can_calculate(self) -> bool:
        return bool(self.text().strip())

    def compositions(self):
        self.parse()
        b = self.batch()
        if not b.compositions:
            raise RangeError("No valid compositions for these ranges.")
        return b.names, b.compositions, b.variables

    # periodic-table interaction: append / remove element tokens in the last block
    def add_element(self, el: str):
        text = self.text().rstrip()
        if re.search(rf"{el}(?![a-z])", text):
            return
        self.edit.setPlainText(text + el)
        self.parse()

    def remove_element(self, el: str):
        new = re.sub(rf"{el}(?![a-z])(\{{[^}}]*\}}|_\([^)]*\)|_\{{[^}}]*\}}|[0-9.]*[a-z0-9_+\-*/.]*)?", "",
                     self.text())
        self.edit.setPlainText(new.replace("()", ""))
        self.parse()

    def clear(self):
        self.edit.clear()
        self.parse()


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

    MODES = ("single", "sweep", "expression")

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__("Composition setup", parent)
        self.data = datasets
        self.title_holder.setFixedHeight(55)
        self.unit_box = QComboBox()
        self.unit_box.addItem("At. ratio", "ratio")
        self.unit_box.addItem("at.%", "at")
        self.unit_box.setAccessibleName("Range unit")
        self.unit_box.setToolTip("Unit of the Min / Max / Step values")
        self.unit_box.setFixedWidth(104)
        self.unit_box.hide()
        self.title_row.addWidget(self.unit_box)
        self.unit_gap = QSpacerItem(16, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.title_row.addSpacerItem(self.unit_gap)
        self.switcher = IconContentSwitcher([("mode_single", "Single composition"),
                                             ("mode_sweep", "Composition sweep"),
                                             ("mode_expression", "Expression mode")])
        self.title_row.addWidget(self.switcher)
        self.title_row.setContentsMargins(20, 0, 18, 0)
        self.root.addWidget(Divider())
        self.stack = QStackedWidget()
        self.single = SingleView(datasets)
        self.sweep = SweepView()
        self.expr = ExpressionView(datasets)
        for v in (self.single, self.sweep, self.expr):
            self.stack.addWidget(v)
            v.changed.connect(self._update_actions)
            v.message.connect(self.message.emit)
        self.root.addWidget(self.stack, 1)
        self.expr.elements_parsed.connect(self.elements_changed.emit)
        self.expr.preview_requested.connect(self.preview_expression)
        self.single.element_renamed.connect(self._renamed)
        self.unit_box.currentIndexChanged.connect(lambda _i: self.sweep.set_unit(self.unit_box.currentData()))

        # footer toolbar (Figma 278:30201, 40 px, top border); visible actions depend on the mode
        bar = QWidget()
        bar.setFixedHeight(40)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.clear_btn = button("Clear", "danger-ghost", "md")
        self.normalize_btn = button("Normalize", "ghost", "md")
        self.equal_btn = button("Set equal", "ghost", "md")
        self.copy_btn = button("Copy table", "ghost", "md")
        self.calc_btn = button("Calculate", "primary", "md")
        self.calc_btn.setFixedWidth(141)
        bl.addWidget(self.clear_btn)
        bl.addStretch(1)
        for b in (self.normalize_btn, self.equal_btn, self.copy_btn, self.calc_btn):
            bl.addWidget(b)
        self.root.addWidget(Divider())
        self.root.addWidget(bar)
        self.clear_btn.clicked.connect(self.clear)
        self.normalize_btn.clicked.connect(self._normalize)
        self.equal_btn.clicked.connect(self._set_equal)
        self.copy_btn.clicked.connect(self._copy_compositions)
        self.calc_btn.clicked.connect(self.calculate)
        self.switcher.changed.connect(self.set_mode)
        for b in (self.clear_btn, self.normalize_btn, self.equal_btn, self.copy_btn, self.calc_btn):
            b.setProperty("tip_align", "bottom")
        self.normalize_btn.setToolTip("Scale at.% or wt.% values to sum to 100 %")
        self.equal_btn.setToolTip("Equal values in the active input column")
        self.copy_btn.setToolTip("Copy the generated compositions (tab-separated)")
        self.setMinimumWidth(COMPOSITION_PANEL_MIN)
        self.grid = ColumnGrid()
        for v in (self.single, self.sweep, self.expr):
            v.grid = self.grid
        self._elements: list[str] = []
        self.set_mode(0)

    CALC_WIDTH = 141
    UNIT_WIDTH = 104
    CALC_WIDTH_MIN = 112

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.grid.set_panel_width(self.width()):
            self.grid.apply(self)
        self.calc_btn.setFixedWidth(max(self.CALC_WIDTH_MIN,
                                        self.CALC_WIDTH - max(0, ColumnGrid.DESIGN_PANEL - self.width())))
        # sweep header: the 104 px unit select gives up to 8 px so the title is never clipped
        self.unit_box.setFixedWidth(self.UNIT_WIDTH - min(8, max(0, ColumnGrid.DESIGN_PANEL - self.width())))
        gap = 16 - min(8, max(0, ColumnGrid.DESIGN_PANEL - self.width()) // 4)
        if self.unit_gap.sizeHint().width() != gap:
            self.unit_gap.changeSize(gap, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            self.title_row.invalidate()

    @property
    def mode(self) -> str:
        return self.MODES[self.stack.currentIndex()]

    def set_mode(self, i: int):
        self.stack.setCurrentIndex(i)
        self.switcher.set_index(i)
        self.unit_box.setVisible(self.mode == "sweep")
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
        order = [new if e == old else e for e in self._elements]
        self._elements = order
        self.single.rename(old, new, order)
        self.sweep.set_elements(order)
        self.elements_changed.emit(order)

    def _update_actions(self):
        m = self.mode
        self.normalize_btn.setVisible(m == "single")
        self.equal_btn.setVisible(m == "single")
        self.copy_btn.setVisible(m == "expression")
        if m == "single":
            has = bool(self._elements)
            self.normalize_btn.setEnabled(self.single.can_normalise())
            self.equal_btn.setEnabled(self.single.can_set_equal())
            self.clear_btn.setEnabled(has)
            self.calc_btn.setEnabled(len(self._elements) >= 2)
        elif m == "sweep":
            self.clear_btn.setEnabled(bool(self._elements))
            self.calc_btn.setEnabled(self.sweep.can_calculate())
        else:
            has = self.expr.can_calculate()
            self.clear_btn.setEnabled(has)
            self.copy_btn.setEnabled(has)
            self.calc_btn.setEnabled(has)

    def _normalize(self):
        if self.mode == "single":
            self.single.normalise()

    def _set_equal(self):
        if self.mode == "single":
            self.single.set_equal()

    def _generated_tsv(self) -> str:
        names, comps, _envs = self.expr.compositions()
        elements: list[str] = []
        for c in comps:
            for el in c:
                if el not in elements:
                    elements.append(el)
        lines = ["Alloy\t" + "\t".join(f"{el} (at.%)" for el in elements)]
        for n, c in zip(names, comps):
            tot = sum(c.values())
            lines.append(n + "\t" + "\t".join(f"{100 * c.get(el, 0.0) / tot:.4f}" for el in elements))
        return "\r\n".join(lines) + "\r\n"

    def _copy_compositions(self):
        try:
            self.copy_compositions.emit(self._generated_tsv())
        except (ValueError, RangeError, ExpressionError) as exc:
            self.message.emit("error", str(exc))

    def preview_expression(self):
        try:
            names, comps, _ = self.expr.compositions()
        except (ValueError, RangeError, ExpressionError) as exc:
            self.message.emit("error", str(exc))
            return
        from PySide6.QtWidgets import QListWidget
        from .dialogs import Modal
        dlg = Modal("Generated compositions", f"{len(comps):,} valid", self, width=560)
        lst = QListWidget()
        for n, c in list(zip(names, comps))[:2000]:
            tot = sum(c.values())
            lst.addItem(f"{n}    ({', '.join(f'{el} {100 * v / tot:.2f}' for el, v in c.items())})")
        dlg.body.addWidget(lst, 1)
        dlg.add_footer_button("Copy table", "secondary", self._copy_compositions)
        dlg.add_footer_button("Close", "primary", dlg.accept)
        dlg.exec()
        dlg.deleteLater()

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
                names, comps = self.sweep.compositions()
                self.calculate_requested.emit("sweep", names, comps, [{} for _ in comps])
            else:
                names, comps, envs = self.expr.compositions()
                self.calculate_requested.emit("expression", names, comps, envs)
        except (ValueError, RangeError, ExpressionError) as exc:
            self.message.emit("error", str(exc))
