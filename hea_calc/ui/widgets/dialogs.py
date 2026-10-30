"""Carbon-style modal dialogs: table columns, filters, calculation settings, alloy details, about, import report."""

from __future__ import annotations

import html

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QVBoxLayout, QWidget)

from ...core.composition import parse_number
from ...core.engine import DEFAULT_TCRIT_FRACTION, MODEL_KEYS, MODELS
from ...core.results import (COLUMNS, COLUMN_BY_KEY, DEFAULT_COLUMNS, IdSetFilter, ModelFilter, RangeFilter,
                               chooser_groups)
from .scroll import inner_scroll_area
from .common import button, refresh_style, set_prop


class Modal(QDialog):
    """Carbon modal: 20 px title, label, scrollable body, footer of 64 px buttons.

    The window keeps the native Windows caption (themed by ``ui/win_titlebar.py``), whose Close button closes
    it; there is no second, in-content close control (release reconciliation).  Footer buttons are workflow
    actions only (Apply, Cancel, Export …)."""

    def __init__(self, title: str, label: str = "", parent=None, width: int = 640):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        from .. import win_titlebar
        win_titlebar.watch(self)
        self.resize(width, 560)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 16, 16, 0)
        col = QVBoxLayout()
        col.setSpacing(4)
        if label:
            lab = QLabel(label)
            lab.setObjectName("ModalLabel")
            col.addWidget(lab)
        t = QLabel(title)
        t.setObjectName("ModalTitle")
        col.addWidget(t)
        head.addLayout(col, 1)
        root.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(16, 16, 16, 24)
        self.body.setSpacing(12)
        root.addLayout(self.body, 1)
        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(0, 0, 0, 0)
        self.footer.setSpacing(1)
        foot = QWidget()
        foot.setObjectName("ModalFooter")
        foot.setFixedHeight(64)
        foot.setLayout(self.footer)
        root.addWidget(foot)
        self.footer_widget = foot
        foot.hide()                  # shown by the first workflow button (informational dialogs have none)

    def showEvent(self, e):
        from .menu import carbonize_popups
        carbonize_popups(self)       # content is added after __init__: done when first shown
        super().showEvent(e)
        # initial focus: first text field, otherwise the dialog itself (no stray focus ring)
        from PySide6.QtWidgets import QLineEdit
        fields = [w for w in self.findChildren(QLineEdit) if w.isVisible() and w.isEnabled()]
        if fields:
            fields[0].setFocus()
        else:
            self.setFocus()

    def fit_height(self, content: QWidget, minimum: int = 420) -> None:
        """Responsive height (2026-10-28): tall enough for the scrolling ``content`` without scrolling when the screen
        allows, never taller than 90 % of the available screen height and never shorter than ``minimum``; the
        footer and the title always stay on screen (the content scrolls inside)."""
        from PySide6.QtGui import QGuiApplication
        par = self.parentWidget()
        scr = (par.screen() if par is not None else None) or QGuiApplication.primaryScreen()
        avail = scr.availableGeometry().height() if scr is not None else 900
        chrome = 16 + 44 + 16 + 24 + 64 + 40           # title block, body margins, footer, caption allowance
        want = content.sizeHint().height() + chrome
        h = max(minimum, min(int(avail * 0.9), want))
        self.resize(self.width(), h)

    def add_footer_button(self, text: str, kind: str, slot, stretch: int = 1):
        b = button(text, kind, "md")
        set_prop(b, "tall", "64")
        b.clicked.connect(slot)
        self.footer.addWidget(b, stretch)
        self.footer_widget.show()
        return b


class _QuietFocus(QObject):
    """Drops the ``quietfocus`` property (and so shows the normal focus ring) once the keyboard is used or the
    focus moves on."""

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.FocusOut, QEvent.Type.KeyPress) and obj.property("quietfocus"):
            obj.setProperty("quietfocus", False)
            refresh_style(obj)
            obj.removeEventFilter(self)
        return False


_QUIET = None


def quiet_focus(widget: QWidget) -> None:
    """Give ``widget`` the initial focus without the keyboard focus ring (focus-visible): the ring appears with the
    first key press or when focus moves on and comes back."""
    global _QUIET
    if _QUIET is None:
        _QUIET = _QuietFocus()
    widget.setProperty("quietfocus", True)
    refresh_style(widget)
    widget.installEventFilter(_QUIET)
    widget.setFocus(Qt.FocusReason.OtherFocusReason)


def scroll(inner: QWidget) -> QScrollArea:
    return inner_scroll_area(inner)


class ColumnsDialog(Modal):
    """Table columns: choose visible columns; Apply / Cancel / Reset to default."""

    def __init__(self, visible: list[str], parent=None):
        super().__init__("Table columns", "Results table", parent, width=560)
        self.checks: dict[str, QCheckBox] = {}
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)
        # 2026-10-28: Composition, Run, the shared descriptors, then one group per model (its prediction and the
        # descriptors only it uses - results.chooser_groups); tooltips say what a column holds, without references
        r = 0
        for gi, (group, cols) in enumerate(chooser_groups()):
            h = QLabel(group)
            h.setStyleSheet("font-weight: 600;" + (" padding-top: 8px;" if gi else ""))
            grid.addWidget(h, r, 0, 1, 2)
            r += 1
            for i, c in enumerate(cols):
                cb = QCheckBox(c.header)
                cb.setToolTip(c.chooser_tip or c.tooltip)
                cb.setProperty("tip_align", "top")
                cb.setChecked(c.key in visible)
                if c.key == "name":
                    cb.setEnabled(False)
                    cb.setChecked(True)
                self.checks[c.key] = cb
                grid.addWidget(cb, r + i // 2, i % 2)
            r += (len(cols) + 1) // 2
        self.body.addWidget(scroll(inner), 1)
        self.order = [c.key for c in COLUMNS if c.key in self.checks]
        self.fit_height(inner)
        self.add_footer_button("Reset to default", "ghost", self.reset)
        self.add_footer_button("Cancel", "secondary", self.reject)
        self.add_footer_button("Apply", "primary", self.accept)

    reset_widths = False

    def reset(self):
        """Default columns, and on Apply the default (weighted) column widths too."""
        for k, cb in self.checks.items():
            cb.setChecked(k in DEFAULT_COLUMNS)
        self.reset_widths = True

    def selected(self) -> list[str]:
        return [k for k in self.order if self.checks[k].isChecked()]


FILTER_KEYS = ["dhmix", "dsmix", "delta", "delta_cn12", "vec", "tm", "density", "omega", "gamma", "lambda",
               "phi_ye", "k1", "k1cr", "phi_king"]


class FilterRule(QWidget):
    """One rule of the filter builder: the parameter (name and unit), its operator and value(s), and Remove.

    Numeric parameter: *between* (min and max), *at least* (min) or *at most* (max) - inclusive bounds, a value that
    is N/A never passes (``repository.filter_sql``).  Model prediction: *is one of* the classes that model can
    produce (``analysis.models.CLASSES``) and N/A.  The rule yields exactly one ``RangeFilter`` / ``ModelFilter``."""

    OPS = (("between", "is between"), ("ge", "is at least"), ("le", "is at most"))

    def __init__(self, key: str, flt=None, on_remove=None, parent=None):
        super().__init__(parent)
        from ...core.analysis.models import CLASSES
        from .dropdown import Dropdown, MultiSelect
        self.key = key
        self.col = COLUMN_BY_KEY[key]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        unit = f" ({self.col.unit})" if self.col.unit else ""
        name = QLabel(self.col.header.split(" (")[0] + unit if self.col.kind != "model"
                      else f"{key} {MODELS[key].short}")
        name.setFixedWidth(180)
        name.setToolTip(self.col.chooser_tip or self.col.tooltip)
        lay.addWidget(name)
        self.op = self.lo = self.hi = self.classes = None
        if self.col.kind == "model":
            have = set(getattr(flt, "labels", ()) or ())
            opts = [c for c in CLASSES.get(key, ())] + ["N/A"]
            opts += sorted(have - set(opts))             # a stored filter keeps every class it had
            lab = QLabel("is one of")
            lab.setFixedWidth(96)
            lay.addWidget(lab)
            self.classes = MultiSelect("classes", [(c, c) for c in opts], tuple(sorted(have)),
                                       accessible=f"{key} prediction classes")
            lay.addWidget(self.classes, 1)
        else:
            lo = getattr(flt, "minimum", None)
            hi = getattr(flt, "maximum", None)
            op = "between" if (lo is not None and hi is not None) or flt is None else ("ge" if lo is not None else "le")
            self.op = Dropdown(list(self.OPS), op, accessible=f"{self.col.header} condition")
            self.op.setFixedWidth(136)
            lay.addWidget(self.op)
            self.lo, self.hi = QLineEdit(), QLineEdit()
            self.lo.setPlaceholderText("Min")
            self.hi.setPlaceholderText("Max")
            self.lo.setAccessibleName(f"{self.col.header} minimum")
            self.hi.setAccessibleName(f"{self.col.header} maximum")
            self.lo.setText("" if lo is None else f"{lo:g}")
            self.hi.setText("" if hi is None else f"{hi:g}")
            lay.addWidget(self.lo, 1)
            lay.addWidget(self.hi, 1)
            self.op.changed.connect(lambda _v: self._sync_op())
            self._sync_op()
        from .common import IconButton
        self.remove_btn = IconButton("close", f"Remove the {self.col.header.split(' (')[0]} filter")
        self.remove_btn.setFixedSize(32, 32)
        if on_remove is not None:
            self.remove_btn.clicked.connect(lambda: on_remove(self))
        lay.addWidget(self.remove_btn)

    def _sync_op(self):
        v = self.op.value
        self.lo.setVisible(v in ("between", "ge"))
        self.hi.setVisible(v in ("between", "le"))

    def result(self):
        """``(filter, error)``: the rule's filter, or why it is not valid yet."""
        name = self.col.header.split(" (")[0]
        if self.classes is not None:
            sel = set(self.classes.selected)
            if not sel:
                return None, f"{self.key}: choose at least one class."
            return ModelFilter(self.key, sel), None
        v = self.op.value
        vals = []
        for f, used in ((self.lo, v in ("between", "ge")), (self.hi, v in ("between", "le"))):
            txt = f.text().strip() if used else ""
            num = parse_number(txt) if txt else None
            bad = used and (not txt or num is None)
            f.setProperty("invalid", bad)
            refresh_style(f)
            if bad:
                return None, f"{name}: enter a number."
            vals.append(num)
        if vals[0] is not None and vals[1] is not None and vals[0] > vals[1]:
            self.lo.setProperty("invalid", True)
            refresh_style(self.lo)
            return None, f"{name}: the minimum exceeds the maximum."
        return RangeFilter(self.key, vals[0], vals[1]), None


class FilterDialog(Modal):
    """Filter results: an incremental filter builder (2026-10-28).

    Add filter -> choose a parameter (grouped like Table columns: shared descriptors, then each model with its
    prediction and the descriptors only it uses) -> set its condition; add more, edit or remove them; Apply.
    Every rule must hold (AND) - the same semantics as before: one ``RangeFilter`` per descriptor (inclusive bounds,
    N/A never passes) and one ``ModelFilter`` per model (its prediction is one of the chosen classes).  Opening the
    dialog shows the table's current filters as rules; Cancel changes nothing."""

    def __init__(self, filters: list, parent=None):
        super().__init__("Filter results", "Results table", parent, width=720)
        self.rules: list[FilterRule] = []
        top = QHBoxLayout()
        self.add_btn = button("Add filter", "ghost", "sm")
        self.add_btn.setAccessibleName("Add filter")
        self.add_btn.clicked.connect(self.open_add_menu)
        top.addWidget(self.add_btn)
        top.addStretch(1)
        self.body.addLayout(top)
        inner = QWidget()
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(8)
        self.empty = QLabel("No filters: every result is shown. Add a filter to show only the results that match "
                            "it; with several filters a result must match all of them.")
        self.empty.setWordWrap(True)
        self.empty.setObjectName("Helper")
        self.list.addWidget(self.empty)
        self.list.addStretch(1)
        self.id_filters = [f for f in filters if isinstance(f, IdSetFilter)]
        self.keep_ids = None
        if self.id_filters:
            n = sum(f.count for f in self.id_filters)
            self.keep_ids = QCheckBox(f"Only the {n:,} results selected in Analysis")
            self.keep_ids.setChecked(True)
            self.body.addWidget(self.keep_ids)
        self.body.addWidget(scroll(inner), 1)
        self.error = QLabel("")
        self.error.setObjectName("ErrorText")
        self.body.addWidget(self.error)
        self.add_footer_button("Clear all", "ghost", self.clear)
        self.add_footer_button("Cancel", "secondary", self.reject)
        self.add_footer_button("Apply", "primary", self._apply)
        self.result_filters: list = []
        for f in filters:
            if isinstance(f, (RangeFilter, ModelFilter)) and f.key in COLUMN_BY_KEY:
                self.add_rule(f.key, f)
        self._sync()
        self.fit_height(inner, minimum=360)

    # -------------------------------------------------------------- rules
    @staticmethod
    def parameters() -> list[tuple[str, list]]:
        """Filterable parameters by group: numeric stored descriptors and the model predictions."""
        from ...core.chunks import NUM_KEYS
        ok = lambda c: c.kind == "model" or (c.kind == "num" and c.key in NUM_KEYS)      # noqa: E731
        return [(g, [c for c in cols if ok(c)]) for g, cols in chooser_groups() if any(ok(c) for c in cols)]

    def used(self) -> set[str]:
        return {r.key for r in self.rules}

    def open_add_menu(self):
        from .menu import CarbonMenu
        menu = CarbonMenu(parent=self)
        used = self.used()
        for group, cols in self.parameters():
            free = [c for c in cols if c.key not in used]
            if not free:
                continue
            sub = menu.add_submenu(group)
            for c in free:
                text = f"{c.key} prediction" if c.kind == "model" else c.header
                sub.add_action(text, lambda _c=False, k=c.key: self.add_rule(k, focus=True))
        menu.open_below(self.add_btn)
        menu.deleteLater()

    def add_rule(self, key: str, flt=None, focus: bool = False) -> FilterRule:
        if key in self.used():
            return next(r for r in self.rules if r.key == key)
        rule = FilterRule(key, flt, on_remove=self.remove_rule)
        self.rules.append(rule)
        self.list.insertWidget(self.list.count() - 1, rule)
        self._sync()
        if focus:
            (rule.lo if rule.lo is not None and rule.lo.isVisible() else rule.classes or rule.op).setFocus()
        return rule

    def remove_rule(self, rule: FilterRule) -> None:
        if rule in self.rules:
            self.rules.remove(rule)
            rule.setParent(None)
            rule.deleteLater()
        self._sync()

    def _sync(self):
        self.empty.setVisible(not self.rules)
        self.error.setText("")

    def clear(self):
        for r in list(self.rules):
            self.remove_rule(r)
        if self.keep_ids is not None:
            self.keep_ids.setChecked(False)

    def _apply(self):
        out = []
        for r in self.rules:
            f, err = r.result()
            if err:
                self.error.setText(err)
                return
            out.append(f)
        if self.keep_ids is not None and self.keep_ids.isChecked():
            out += self.id_filters
        self.result_filters = out
        self.accept()


class SettingsDialog(Modal):
    """Calculation settings shared by every workflow (passed to the engine)."""

    def __init__(self, annealing: float | None, fraction: float, parent=None):
        super().__init__("Calculation settings", "Models M6 and M7", parent, width=560)
        self.resize(560, 360)
        txt = QLabel("Troparevsky (M6) and Senkov & Miracle (M7) compare phases at a temperature. "
                     "Enter the annealing temperature of interest, or leave it empty to use "
                     "T = f · T<sub>m</sub> (default f = 0.55, Troparevsky et al. 2015).")
        txt.setWordWrap(True)
        txt.setTextFormat(Qt.TextFormat.RichText)
        self.body.addWidget(txt)
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.addWidget(QLabel("Annealing temperature (K)"), 0, 0)
        self.t_edit = QLineEdit("" if annealing is None else f"{annealing:g}")
        self.t_edit.setPlaceholderText("empty = f · Tm")
        g.addWidget(self.t_edit, 0, 1)
        g.addWidget(QLabel("Fraction f of Tm (when empty)"), 1, 0)
        self.f_edit = QLineEdit(f"{fraction:g}")
        g.addWidget(self.f_edit, 1, 1)
        self.body.addLayout(g)
        self.error = QLabel("")
        self.error.setObjectName("ErrorText")
        self.body.addWidget(self.error)
        self.body.addStretch(1)
        self.add_footer_button("Reset", "ghost", self._reset)
        self.add_footer_button("Cancel", "secondary", self.reject)
        self.add_footer_button("Apply", "primary", self._apply)
        self.annealing, self.fraction = annealing, fraction

    def _reset(self):
        self.t_edit.clear()
        self.f_edit.setText(f"{DEFAULT_TCRIT_FRACTION:g}")

    def _apply(self):
        t_txt = self.t_edit.text().strip()
        t = parse_number(t_txt) if t_txt else None
        f = parse_number(self.f_edit.text())
        bad_t = bool(t_txt) and (t is None or t <= 0)
        bad_f = f is None or not (0 < f <= 1.5)
        for w, bad in ((self.t_edit, bad_t), (self.f_edit, bad_f)):
            w.setProperty("invalid", bad)
            refresh_style(w)
        if bad_t or bad_f:
            self.error.setText("Temperature must be > 0 K; the fraction must be in (0, 1.5].")
            return
        self.annealing, self.fraction = t, f
        self.accept()


class ImportReportDialog(Modal):
    def __init__(self, path: str, layout: str, imported: int, errors: list[tuple[int, str]], parent=None):
        super().__init__("Import report", path, parent, width=640)
        lab = QLabel(f"Layout: {html.escape(layout)}. Imported <b>{imported}</b> composition(s); "
                     f"<b>{len(errors)}</b> row(s) skipped.")
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        self.body.addWidget(lab)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        for n, msg in errors[:500]:
            e = QLabel(f"Row {n}: {html.escape(msg)}")
            e.setWordWrap(True)
            v.addWidget(e)
        if len(errors) > 500:
            v.addWidget(QLabel(f"… and {len(errors) - 500} more"))
        v.addStretch(1)
        self.body.addWidget(scroll(inner), 1)        # informational: the native caption closes it


class ChoiceDialog(Modal):
    """Carbon modal with a message and one footer button per choice; ``choice`` is the chosen key
    (None when closed).  The last choice is the primary button."""

    def __init__(self, title: str, label: str, message: str, choices: list[tuple[str, str]], parent=None):
        super().__init__(title, label, parent, width=560)
        self.resize(560, 280)
        lab = QLabel(message)
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        self.body.addWidget(lab)
        self.body.addStretch(1)
        self.choice: str | None = None
        for i, (key, text) in enumerate(choices):
            kind = "primary" if i == len(choices) - 1 else ("ghost" if i == 0 else "secondary")
            self.add_footer_button(text, kind, lambda _=False, k=key: self._choose(k))

    def _choose(self, key: str):
        self.choice = key
        self.accept() if key != "cancel" else self.reject()


class DangerDialog(Modal):
    """Carbon danger modal (Carbon MCP, components/modal "Danger"): the question as the title, a short
    consequence, and the footer Cancel (secondary) | <destructive action> (danger primary).  Used only through the
    one destructive-action policy (``core/destructive.py``); Esc and the caption's Close button cancel."""

    def __init__(self, title: str, question: str, detail: str, action: str, parent=None):
        # the window caption says what the dialog is (``title``); the heading asks the question once - no label
        # repeating the caption above it
        super().__init__(question, "", parent, width=560)
        self.setWindowTitle(title)
        self.resize(560, 240)
        lab = QLabel(detail)
        lab.setWordWrap(True)
        self.body.addWidget(lab)
        self.body.addStretch(1)
        self.cancel_button = self.add_footer_button("Cancel", "secondary", self.reject)
        self.action_button = self.add_footer_button(action, "danger", self.accept)
        self.cancel_button.setDefault(False)
        self.cancel_button.setAutoDefault(False)
        self.action_button.setAutoDefault(False)

    def showEvent(self, e):
        super().showEvent(e)
        # Carbon danger modal: initial focus on Cancel, so a stray Enter never confirms the destructive action -
        # without the focus ring until the keyboard is used (a ring on a button nobody moved to looked stuck)
        quiet_focus(self.cancel_button)
