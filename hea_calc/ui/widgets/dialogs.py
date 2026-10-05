"""Carbon-style modal dialogs: table columns, filters, calculation settings, alloy details, about, import report."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QScrollArea, QVBoxLayout, QWidget)

from ... import __version__
from ...core.composition import parse_number
from ...core.engine import DEFAULT_TCRIT_FRACTION, MODEL_KEYS, MODELS
from ...core.results import COLUMNS, COLUMN_BY_KEY, DEFAULT_COLUMNS, ModelFilter, RangeFilter
from .common import IconButton, button, refresh_style
from .details_panel import DetailsPanel


class Modal(QDialog):
    """Carbon modal: 20 px title, label, scrollable body, footer of 64 px buttons."""

    def __init__(self, title: str, label: str = "", parent=None, width: int = 640):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(width, 560)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 16, 0, 0)
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
        close = IconButton("close", "Close")
        close.setFixedSize(48, 48)
        close.setStyleSheet("min-width: 48px; max-width: 48px; min-height: 48px; max-height: 48px;")
        close.clicked.connect(self.reject)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
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

    def showEvent(self, e):
        super().showEvent(e)
        # initial focus: first text field, otherwise the dialog itself (no stray focus ring on Close)
        from PySide6.QtWidgets import QLineEdit
        fields = [w for w in self.findChildren(QLineEdit) if w.isVisible() and w.isEnabled()]
        if fields:
            fields[0].setFocus()
        else:
            self.setFocus()

    def add_footer_button(self, text: str, kind: str, slot, stretch: int = 1):
        b = button(text, kind, "md")
        b.setMinimumHeight(64)
        b.setMaximumHeight(64)
        b.setStyleSheet("min-height: 64px; max-height: 64px; padding-bottom: 24px; padding-top: 0px;")
        b.clicked.connect(slot)
        self.footer.addWidget(b, stretch)
        return b


def scroll(inner: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    sa.setWidget(inner)
    return sa


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
        groups: dict[str, list] = {}
        for c in COLUMNS:
            groups.setdefault(c.group, []).append(c)
        r = 0
        for gi, (group, cols) in enumerate(groups.items()):
            h = QLabel(group)
            h.setStyleSheet("font-weight: 600;")
            grid.addWidget(h, r, 0, 1, 2)
            r += 1
            for i, c in enumerate(cols):
                cb = QCheckBox(c.header)
                cb.setToolTip(c.tooltip)
                cb.setChecked(c.key in visible)
                if c.key == "name":
                    cb.setEnabled(False)
                    cb.setChecked(True)
                self.checks[c.key] = cb
                grid.addWidget(cb, r + i // 2, i % 2)
            r += (len(cols) + 1) // 2
        self.body.addWidget(scroll(inner), 1)
        self.order = [c.key for c in COLUMNS]
        self.add_footer_button("Reset to default", "ghost", self.reset)
        self.add_footer_button("Cancel", "secondary", self.reject)
        self.add_footer_button("Apply", "primary", self.accept)

    def reset(self):
        for k, cb in self.checks.items():
            cb.setChecked(k in DEFAULT_COLUMNS)

    def selected(self) -> list[str]:
        return [k for k in self.order if self.checks[k].isChecked()]


FILTER_KEYS = ["dhmix", "dsmix", "delta", "delta_cn12", "vec", "tm", "density", "omega", "gamma", "lambda",
               "phi_ye", "k1", "k1cr", "phi_king"]


class FilterDialog(Modal):
    """Filter results by descriptor ranges and model predictions (empty = no limit)."""

    def __init__(self, filters: list, parent=None):
        super().__init__("Filter results", "Results table", parent, width=640)
        current_r = {f.key: f for f in filters if isinstance(f, RangeFilter)}
        current_m = {f.key: f for f in filters if isinstance(f, ModelFilter)}
        inner = QWidget()
        g = QGridLayout(inner)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(4)
        for j, h in enumerate(("Descriptor", "Min", "Max")):
            lab = QLabel(h)
            lab.setStyleSheet("font-weight: 600;")
            g.addWidget(lab, 0, j)
        self.ranges: dict[str, tuple[QLineEdit, QLineEdit]] = {}
        for i, k in enumerate(FILTER_KEYS, start=1):
            c = COLUMN_BY_KEY[k]
            g.addWidget(QLabel(c.header), i, 0)
            mn, mx = QLineEdit(), QLineEdit()
            mn.setPlaceholderText("no limit")
            mx.setPlaceholderText("no limit")
            f = current_r.get(k)
            if f:
                mn.setText("" if f.minimum is None else f"{f.minimum:g}")
                mx.setText("" if f.maximum is None else f"{f.maximum:g}")
            g.addWidget(mn, i, 1)
            g.addWidget(mx, i, 2)
            self.ranges[k] = (mn, mx)
        r = len(FILTER_KEYS) + 1
        lab = QLabel("Model predictions")
        lab.setStyleSheet("font-weight: 600; padding-top: 12px;")
        g.addWidget(lab, r, 0, 1, 3)
        self.models: dict[str, QComboBox] = {}
        for i, k in enumerate(MODEL_KEYS):
            g.addWidget(QLabel(f"{k} — {MODELS[k].short}"), r + 1 + i, 0)
            cb = QComboBox()
            cb.setProperty("field", True)
            cb.addItems(["Any", "SS", "MP", "IM", "SS+IM", "MG", "N/A", "SS (any SS)"])
            f = current_m.get(k)
            if f:
                labels = f.labels
                if labels == {"SS", "SS+IM"}:
                    cb.setCurrentText("SS (any SS)")
                elif len(labels) == 1:
                    cb.setCurrentText(next(iter(labels)))
            g.addWidget(cb, r + 1 + i, 1, 1, 2)
            self.models[k] = cb
        g.setColumnStretch(0, 1)
        self.body.addWidget(scroll(inner), 1)
        self.error = QLabel("")
        self.error.setObjectName("ErrorText")
        self.body.addWidget(self.error)
        self.add_footer_button("Clear filters", "ghost", self.clear)
        self.add_footer_button("Cancel", "secondary", self.reject)
        self.add_footer_button("Apply", "primary", self._apply)
        self.result_filters: list = []

    def clear(self):
        for mn, mx in self.ranges.values():
            mn.clear()
            mx.clear()
        for cb in self.models.values():
            cb.setCurrentIndex(0)

    def _apply(self):
        out = []
        ok = True
        for k, (mn, mx) in self.ranges.items():
            vals = []
            for f in (mn, mx):
                txt = f.text().strip()
                v = parse_number(txt) if txt else None
                bad = bool(txt) and v is None
                f.setProperty("invalid", bad)
                refresh_style(f)
                ok &= not bad
                vals.append(v)
            if vals[0] is not None and vals[1] is not None and vals[0] > vals[1]:
                mn.setProperty("invalid", True)
                refresh_style(mn)
                ok = False
            if vals[0] is not None or vals[1] is not None:
                out.append(RangeFilter(k, vals[0], vals[1]))
        if not ok:
            self.error.setText("Fix the highlighted fields (numbers only; Min ≤ Max).")
            return
        for k, cb in self.models.items():
            txt = cb.currentText()
            if txt == "Any":
                continue
            out.append(ModelFilter(k, {"SS", "SS+IM"} if txt.startswith("SS (") else {txt}))
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


class AlloyDetailsDialog(Modal):
    def __init__(self, row, parent=None):
        super().__init__("Alloy details", "Calculation details", parent, width=900)
        self.resize(900, 760)
        self.panel = DetailsPanel()
        self.panel.setMinimumWidth(0)
        self.panel.tabs.set_index(0)
        self.panel.stack.setCurrentIndex(0)
        self.panel.show_row(row)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.panel, 1)
        self.add_footer_button("Print", "secondary", self.panel.print_results)
        self.add_footer_button("Close", "primary", self.accept)


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
        self.body.addWidget(scroll(inner), 1)
        self.add_footer_button("Close", "primary", self.accept)


class AboutDialog(Modal):
    def __init__(self, parent=None):
        super().__init__("MDL HEA Calculator", f"Version {__version__}", parent, width=720)
        self.resize(720, 640)
        from pathlib import Path

        from PySide6.QtCore import QByteArray
        from PySide6.QtSvgWidgets import QSvgWidget

        from ..theme import t as _tok
        logo_path = Path(__file__).resolve().parents[1] / "icons" / "about_logo.svg"
        if logo_path.exists():
            svg = logo_path.read_text(encoding="utf-8").replace("rgb(141,141,141)", _tok("text-primary"))
            logo = QSvgWidget()
            logo.load(QByteArray(svg.encode("utf-8")))
            logo.setFixedSize(346, 44)
            self.body.addWidget(logo)
        parts = [
            "<p>Phase-formation descriptors and models for high-entropy alloys.<br>"
            "Metals Development Laboratory, Department of Metallurgical and Materials Engineering, "
            "Middle East Technical University (METU), Ankara, Türkiye.</p>",
            "<p><b>Models</b></p><ul>",
        ]
        for k in MODEL_KEYS:
            parts.append(f"<li><b>{k}</b> {html.escape(MODELS[k].title)} — {html.escape(MODELS[k].reference)}</li>")
        parts.append("</ul><p><b>Data</b></p><ul>"
                     "<li>Binary liquid mixing enthalpies: A. Takeuchi, A. Inoue, Mater. Trans. 46 (2005) 2817.</li>"
                     "<li>Binary formation enthalpies: Troparevsky et al., Phys. Rev. X 5 (2015) 011041, Suppl. A.</li>"
                     "<li>Miedema parameters and moduli: H. Bakker, Enthalpies in Alloys (1998), Tables A1, A5.</li>"
                     "<li>Atomic radii: S. Guo, C.T. Liu, Prog. Nat. Sci. 21 (2011) 433; "
                     "C. Kittel, Introduction to Solid State Physics, 8th ed., Table 9 (CN12).</li></ul>"
                     "<p>Licensed under the GNU General Public License v3. IBM Plex Sans: SIL Open Font License.</p>")
        lab = QLabel("".join(parts))
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(lab)
        v.addStretch(1)
        self.body.addWidget(scroll(inner), 1)
        self.add_footer_button("Close", "primary", self.accept)
