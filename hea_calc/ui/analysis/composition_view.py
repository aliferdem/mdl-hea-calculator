"""Composition analysis pages: Overview, Descriptors, Models, Model details (design guide frames 2-5, 13-15,
18-19).  Everything shown is read from one engine result (``ResultRow``: the stored inputs reproduced by
the engine with the run's settings); nothing is calculated here.

Layout follows the panel's size class (``ANALYSIS_RESPONSIVE_LAYOUT.md`` 3.1): ``S`` one column, ``M`` two
columns (reference 805 px), ``L`` three columns, ``W`` the expanded workspace (panels on the background).
Fonts never shrink; content reflows.  Pages are built lazily (only the visible one) and rebuilt when the
result or the size class changes.
"""

from __future__ import annotations

import html as _html

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLineEdit, QSizePolicy, QStackedWidget, QVBoxLayout,
                               QWidget)

from ...core import composition as CMP
from ...core.analysis import models as MD
from ...core.analysis.metrics import (DESCRIPTORS, DESCRIPTORS_LIST, GROUPS, KEY_DESCRIPTORS, KEY_LABELS,
                                      format_sig, format_value, full_precision)
from ...core.engine import MODEL_KEYS, MODELS, NA, STATUS_DATA_SUSPECT, STATUS_EXTRAPOLATED, TROPAREVSKY_UPPER_MEV
from ...core.family import family_key
from .. import crisp, icons
from ..theme import BODY_COMPACT_01, HAIRLINE, LABEL_01, font, t
from ..widgets.common import IconButton, TagLabel
from ..widgets.tooltip import InfoButton, Toggletip
from .widgets import (ROW_SM, ROW_XS, ActionableNotification, Cell, DataTable, Divider, Dropdown, EmptyBlock,
                      KVRows, SectionHeading, StatusIcon, label, paint_html, plain_text, rich, scroll_page)

PAGES = ("overview", "descriptors", "models", "model_details")
MODE_NAMES = {"single": "Single composition", "sweep": "Composition space", "expression": "Composition expression",
              "import": "Imported compositions", "recalc": "Recalculation"}


def mode_name(mode: str | None) -> str:
    return MODE_NAMES.get(mode or "", (mode or "").capitalize())


# ====================================================================== result helpers (formatting only)
def verdict_status(o) -> str | None:
    """Status icon kind of a model outcome: extrapolated / data_suspect / caution / na / None."""
    if o is None:
        return None
    if o.label == NA:
        return "na"
    if o.status == STATUS_DATA_SUSPECT:
        return "data_suspect"
    if o.status == STATUS_EXTRAPOLATED:
        return "extrapolated"
    if o.caution:
        return "caution"
    return None


def status_tip(key: str, o) -> str:
    """Toggletip text for a model's status (engine reason / caution text, catalog IDs ANA-*)."""
    if o is None:
        return ""
    if o.label == NA:
        kind = "Not available — undefined" if o.na_kind == "undefined" else "Not available — missing data"
        return f"<b>{kind}.</b> {_html.escape(o.reason or '')} Missing data are not replaced by zero."
    return _html.escape(o.caution or "")


def descriptor_values(row) -> dict:
    return dict(row.result.descriptors) if row is not None else {}


def kv_value(d: dict, key: str, full: bool = False) -> tuple[str, str]:
    """(value text, Tooltip) of a descriptor, with "Not available"/"undefined" handled."""
    v = d.get(key)
    if v is None:
        und = d.get(f"{key}_undefined")
        return ("Undefined" if und else "N/A"), (und or "Not available (missing data)")
    text = format_value(key, v, full)
    return text, f"{text} ({full_precision(v)} exactly as calculated)" if isinstance(v, float) else text


class _Anchor(QWidget):
    """Transparent anchor for a Toggletip opened from a painted table cell."""

    def __init__(self, parent, rect: QRect):
        super().__init__(parent)
        self.setGeometry(rect)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.show()


def open_cell_tip(table: QWidget, rect: QRect, html: str, title: str) -> None:
    anchor = _Anchor(table, rect)
    tip = Toggletip(anchor, rich(html), title)
    tip.destroyed.connect(anchor.deleteLater)
    tip.show()


def descriptor_tip(key: str) -> str:
    d = DESCRIPTORS[key]
    parts = [f"<b>Definition</b><br>{d.definition}"]
    if d.equation:
        parts.append(f"<b>Equation</b><br>{d.equation}")
    if d.data:
        parts.append(f"<b>Data</b><br>{_html.escape(d.data)}")
    if d.undefined:
        parts.append(d.undefined)
    return "<br><br>".join(parts)


# ====================================================================== threshold line (design guide 5.11)
class PairWindow(QWidget):
    """M6 pair window: an axis over the relevant ΔH_f range, the band (−TΔS_mix … 37 meV/atom) and one
    labelled marker per binary pair; values beyond the axis are drawn at the clipped end with an arrow."""

    def __init__(self, pairs, lower: float, upper: float = TROPAREVSKY_UPPER_MEV, parent=None):
        super().__init__(parent)
        self.pairs = [(a, b, v, flag) for a, b, v, flag in pairs if v is not None]
        self.lower, self.upper = lower, upper
        lo = min([lower, *[v for *_x, v, _f in self.pairs]]) if self.pairs else lower
        hi = max([upper, *[v for *_x, v, _f in self.pairs]]) if self.pairs else upper
        span = hi - lo
        self.x0 = max(lo - 0.08 * span, lower - 0.5 * (upper - lower) - 10)
        self.x1 = min(hi + 0.08 * span, upper + 0.5 * (upper - lower) + 10)
        self.setFixedHeight(84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inside = sum(1 for *_x, v, _f in self.pairs if lower < v < upper)
        self.setAccessibleName(f"{inside} of {len(self.pairs)} pairs inside the window")

    def _x(self, v: float) -> float:
        w = self.width() - 24
        return 12 + (min(max(v, self.x0), self.x1) - self.x0) / (self.x1 - self.x0) * w

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        axis_y = 44
        a, b = self._x(self.lower), self._x(self.upper)
        crisp.fill_rect(p, QRectF(a, axis_y - 8, b - a, 16), t("layer-hover-01"))
        crisp.hline(p, 12, self.width() - 12, axis_y, t("border-strong-01"), HAIRLINE)
        p.setFont(font(LABEL_01))
        for v, txt in ((self.lower, f"{format_value('hf_lower', self.lower)} <"), (self.upper, f"< {self.upper:g}")):
            x = self._x(v)
            crisp.fill_rect(p, QRectF(x - 1, axis_y - 6, 2, 12), t("text-primary"))
            p.setPen(QColor(t("text-secondary")))
            p.drawText(QRectF(x - 60, 0, 120, 16), int(Qt.AlignmentFlag.AlignCenter), txt.replace("-", "−"))
        placed: list[float] = []
        for i, (ea, eb, v, flag) in enumerate(sorted(self.pairs, key=lambda q_: q_[2])):
            x = self._x(v)
            clipped = v < self.x0 or v > self.x1
            color = t("support-warning") if flag else t("text-secondary")
            p.setBrush(QColor(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(x - 4, axis_y - 4, 8, 8))
            row = 0
            while any(abs(x - px) < 52 and r == row for px, r in placed) and row < 2:
                row += 1
            placed.append((x, row))
            text = f"{ea}–{eb} {format_value('hf_min', v)}" + (" →" if clipped and v > 0 else "")
            if clipped and v < 0:
                text = "← " + text
            p.setPen(QColor(color))
            p.drawText(QRectF(x - 50, axis_y + 8 + 12 * row, 100, 14), int(Qt.AlignmentFlag.AlignCenter), text)
        p.end()


class ModelStrip(QWidget):
    """Overview "Model predictions" strip: M1-M8 cells (key + tag), clickable (-> Model details)."""

    activated = Signal(str)

    def __init__(self, outcomes: dict, per_row: int = 8, cell_w: int = 88, parent=None):
        super().__init__(parent)
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(8)
        for i, k in enumerate(MODEL_KEYS):
            o = outcomes.get(k)
            cell = _ModelCell(k, o, cell_w)
            cell.clicked.connect(self.activated.emit)
            lay.addWidget(cell, i // per_row, i % per_row)
        lay.setColumnStretch(per_row, 1)


class _ModelCell(QWidget):
    clicked = Signal(str)

    def __init__(self, key, o, width):
        super().__init__()
        self.key, self.o = key, o
        self.setFixedSize(width, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        lab = o.label if o else NA
        self.setToolTip(f"{MD.title(key)}: {MD.CLASS_NAMES.get(lab, lab)} ({lab})")
        self.setAccessibleName(f"{key} {lab}")
        self.hover = False

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        self.clicked.emit(self.key)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.key)
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e):
        from ..widgets.common import paint_tag
        from .widgets import paint_status
        p = QPainter(self)
        p.setFont(font(LABEL_01))
        p.setPen(QColor(t("text-primary" if self.hover else "text-secondary")))
        p.drawText(QRectF(0, 0, 24, 24), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.key)
        lab = self.o.label if self.o else NA
        w = paint_tag(p, QRectF(26, 0, 0, 24), lab, align_left=True)
        st = verdict_status(self.o)
        if st and st != "na":
            paint_status(p, QRectF(26 + w + 4, 0, 16, 24), st)
        if self.hasFocus():
            from ..theme import FOCUS_WIDTH
            crisp.frame(p, self.rect(), FOCUS_WIDTH, t("focus"))
        p.end()


class StatusLine(QWidget):
    """One "Data quality" line: 16 px status icon + text."""

    def __init__(self, icon: str, token: str | None, text: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        ic = QWidget()
        ic.setFixedSize(16, 16)
        ic.paintEvent = lambda _e, w=ic: _paint_icon(w, icon, token)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        lab = label(text, "body", wrap=True)
        lay.addWidget(lab, 1)


def _paint_icon(w, name, token):
    p = QPainter(w)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if token is None:
        icons.paint(p, name, QRectF(0, 0, 16, 16))
    else:
        icons.paint(p, name, QRectF(0, 0, 16, 16), token)
    p.end()


# ====================================================================== the pages
class CompositionContent(QStackedWidget):
    """The four Composition pages for one result (embedded panel, workspace or a details window)."""

    open_tab = Signal(str)            # request a tab switch (e.g. "All descriptors")
    model_selected = Signal(str)      # Model details selection changed (state holder keeps it)

    def __init__(self, size_class: str = "M", parent=None):
        super().__init__(parent)
        self.size_class = size_class
        self.row = None
        self.info = None              # RunInfo of the result's run
        self.record = None            # ResultRecord (provenance), may be None (snapshot window)
        self.model = "M1"
        self.search = ""
        self.full_precision = False
        self.pages: list[QWidget] = []
        for _ in PAGES:
            holder = QWidget()
            QVBoxLayout(holder).setContentsMargins(0, 0, 0, 0)
            self.pages.append(holder)
            self.addWidget(holder)
        self._built: set[int] = set()
        self.empty: tuple[str, str] | None = ("No results to analyse yet",
                                              "Calculate a composition or a composition set. Its descriptors, model "
                                              "predictions and collection statistics appear here.")
        self.currentChanged.connect(self.ensure)
        self.rebuild()

    # -------------------------------------------------------------- inputs
    def set_result(self, row, info=None, record=None) -> None:
        self.row, self.info, self.record = row, info, record
        self.empty = None
        self.rebuild()

    def set_empty(self, title: str, body: str) -> None:
        self.row = None
        self.empty = (title, body)
        self.rebuild()

    def set_size_class(self, cls: str) -> None:
        if cls != self.size_class:
            self.size_class = cls
            self.rebuild()

    def set_model(self, key: str, rebuild: bool = True) -> None:
        if key != self.model:
            self.model = key
            if rebuild:
                self._built.discard(3)
                self.ensure(self.currentIndex())

    def set_search(self, text: str, full: bool) -> None:
        if (text, full) != (self.search, self.full_precision):
            self.search, self.full_precision = text, full
            if 1 in self._built:
                self._rebuild_descriptor_table()

    def rebuild(self) -> None:
        self._built = set()
        self.ensure(self.currentIndex())

    def ensure(self, i: int) -> None:
        if i < 0 or i in self._built:
            return
        self._built.add(i)
        holder = self.pages[i]
        lay = holder.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                _w = it.widget()
                _w.setParent(None)
                _w.deleteLater()
        if self.row is None or self.empty is not None:
            title, body = self.empty or ("No composition selected",
                                         "Double-click a row in the results table to analyse that composition here.")
            lay.addWidget(EmptyBlock(title, body, "document", centred=self.size_class == "W"))
            return
        if not self.row.result.ok:
            w = EmptyBlock("This composition could not be evaluated", _html.escape(self.row.result.error or ""),
                           "document", centred=self.size_class == "W")
            lay.addWidget(w)
            return
        builder = (self._overview, self._descriptors, self._models, self._model_details)[i]
        lay.addWidget(builder())

    # -------------------------------------------------------------- shared bits
    @property
    def wide(self) -> bool:
        return self.size_class in ("M", "L", "W")

    def _scroll(self, margins=(20, 16, 20, 16)):
        content = QWidget()
        sa, lay = scroll_page(content, margins)
        return sa, lay

    def _region(self, title: str = "") -> tuple[QWidget, QVBoxLayout]:
        """A workspace panel (layer-01, padding 20) with an optional heading."""
        w = QWidget()
        w.setObjectName("AnaRegion")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)
        if title:
            lay.addWidget(label(title, "heading02"))
        return w, lay

    def composition_table(self, ws: bool = False) -> DataTable:
        res = self.row.result
        reps = {rep: CMP.from_fractions(dict(res.composition), rep) for rep in ("ratio", "at", "wt")}
        widths = {"S": (80, 104, 104, None), "M": (80, 96, 96, None)}.get(self.size_class, (80, None, None, None))
        cols = [("Element", widths[0]), ("at.%", widths[1], "right"), ("At. ratio", widths[2], "right"),
                ("wt.%", widths[3], "right")]
        rows = [[el, Cell(f"{reps['at'][el]:.2f}", align="right"), Cell(f"{reps['ratio'][el]:.3f}", align="right"),
                 Cell(f"{reps['wt'][el]:.2f}", align="right")] for el in res.composition]
        return DataTable(cols, rows, ROW_SM if ws else ROW_XS)

    def key_descriptor_rows(self, d: dict, extra=()) -> list:
        rows = []
        for key in (*KEY_DESCRIPTORS, *extra):
            desc = DESCRIPTORS[key]
            val, tip = kv_value(d, key)
            name = KEY_LABELS.get(key, desc.name)
            text = f"{desc.symbol} {name}" if self.size_class == "S" else f"{name} {desc.symbol}"   # frame 13 / 2
            rows.append((text, val, desc.unit, None, None, tip))
        cstr = d.get("cstr")
        rows.append(("Crystal structure (VEC rule)", "", "", DESCRIPTORS["cstr"].definition, cstr or NA))
        return rows

    def quality_lines(self) -> list[tuple[str, str | None, str]]:
        """Data-quality lines from the engine's warnings and the models' reasons / cautions."""
        res = self.row.result
        out = []
        na = [k for k in MODEL_KEYS if res.models[k].label == NA]
        if na:
            reasons: dict[str, list[str]] = {}
            for k in na:
                reasons.setdefault(res.models[k].reason or "", []).append(k)
            for reason, keys in reasons.items():
                out.append(("information", "icon-secondary", f"{', '.join(keys)} not available — {_html.escape(reason)}"))
        flagged = [k for k in MODEL_KEYS if res.models[k].status == STATUS_DATA_SUSPECT and res.models[k].label != NA]
        if flagged:
            out.append(("warning_filled", "support-warning",
                        f"{', '.join(flagged)}: verdict uses flagged binary data."))
        extra = [k for k in MODEL_KEYS if res.models[k].status == STATUS_EXTRAPOLATED and res.models[k].label != NA]
        if extra:
            out.append(("warning_alt", "icon-secondary", f"{', '.join(extra)}: extrapolated beyond the published domain."))
        for w in res.warnings:
            out.append(("information", "icon-secondary", _html.escape(w)))
        if not out:
            out.append(("status_ok", None, "All required data available. No cautions."))
        return out

    def provenance_text(self) -> str:
        info = self.info
        parts = []
        if info is not None:
            parts.append(mode_name(info.mode))
            if info.created:
                parts.append("calculated " + info.created.replace("T", " ")[:16])
            if info.engine_version:
                parts.append(f"engine {info.engine_version}")
        return " · ".join(parts)

    def identity_text(self) -> str:
        res = self.row.result
        fam = family_key(res.composition) or ""
        n = len([x for x in res.composition.values() if x > 0])
        parts = [fam, f"{n} elements"]
        if self.info is not None:
            parts += [f"Run {self.info.run_id}", mode_name(self.info.mode)]
        return " · ".join(parts)

    # -------------------------------------------------------------- Overview
    def _overview(self) -> QWidget:
        cls = self.size_class
        res = self.row.result
        d = descriptor_values(self.row)
        if cls == "W":
            return self._overview_workspace(d)
        sa, lay = self._scroll()
        comp_block = QWidget()
        cl = QVBoxLayout(comp_block)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cl.addWidget(SectionHeading("Composition (normalised)"))
        cl.addWidget(self.composition_table())
        if self.row.variables:
            cl.addWidget(label("Expression variables: " + ", ".join(
                f"<i>{_html.escape(str(k))}</i> = {v:g}" for k, v in self.row.variables.items()), "label", wrap=True))
        cl.addStretch(1)
        key_block = QWidget()
        kl = QVBoxLayout(key_block)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setSpacing(8)
        kh = SectionHeading("Key descriptors", link="All descriptors")
        kh.link_clicked.connect(lambda: self.open_tab.emit("descriptors"))
        kl.addWidget(kh)
        label_w = 196 if cls == "S" else 180
        kl.addWidget(KVRows(self.key_descriptor_rows(d), label_w=label_w, value_w=80, unit_w=106 if cls == "S" else 72))
        kl.addStretch(1)
        models_block = QWidget()
        ml = QVBoxLayout(models_block)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(8)
        n_eval, summary = MD.summary_line({k: res.models[k].label for k in MODEL_KEYS})
        ml.addWidget(SectionHeading("Model predictions", f"{n_eval} of 8 evaluated" + (f" · {summary}" if summary else "")))
        per_row = 4 if cls in ("S",) else 8
        strip = ModelStrip(res.models, per_row=per_row, cell_w=96 if cls == "S" else 88)
        strip.activated.connect(self._model_from_strip)
        ml.addWidget(strip)
        quality = QWidget()
        ql = QVBoxLayout(quality)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(8)
        ql.addWidget(SectionHeading("Data quality"))
        for icon, token, text in self.quality_lines():
            ql.addWidget(StatusLine(icon, token, text))
        prov = label(self.provenance_text(), "helper", wrap=True)
        if cls == "L":
            top = QHBoxLayout()
            top.setSpacing(24)
            top.addWidget(comp_block, 1)
            top.addWidget(key_block, 1)
            right = QWidget()
            rl = QVBoxLayout(right)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(16)
            strip_l = ModelStrip(res.models, per_row=4, cell_w=88)
            strip_l.activated.connect(self._model_from_strip)
            rl.addWidget(SectionHeading("Model predictions", f"{n_eval} of 8 · {summary}" if summary else f"{n_eval} of 8"))
            rl.addWidget(strip_l)
            rl.addWidget(quality)
            rl.addStretch(1)
            top.addWidget(right, 1)
            lay.addLayout(top)
            lay.addWidget(prov)
        elif cls == "M":
            top = QHBoxLayout()
            top.setSpacing(24)
            top.addWidget(comp_block, 370)
            top.addWidget(key_block, 371)
            lay.addLayout(top)
            lay.addWidget(models_block)
            lay.addWidget(Divider())
            lay.addWidget(quality)
            lay.addWidget(prov)
        else:
            lay.addWidget(comp_block)
            lay.addWidget(key_block)
            lay.addWidget(models_block)
            lay.addWidget(quality)
            lay.addWidget(prov)
        lay.addStretch(1)
        return sa

    def _model_from_strip(self, key: str) -> None:
        self.model_selected.emit(key)
        self.open_tab.emit("model_details")

    def _overview_workspace(self, d: dict) -> QWidget:
        res = self.row.result
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)
        # Composition panel (440)
        comp, cl = self._region("Composition (normalised)")
        cl.addWidget(self.composition_table(ws=True))
        cl.addWidget(label("Identity", "heading"))
        n = len(res.composition)
        cl.addWidget(KVRows([("Family", family_key(res.composition) or "—", ""), ("Elements", str(n), ""),
                             ("Mean atomic mass", kv_value(d, "mean_mass")[0], "g mol⁻¹"),
                             ("Density", kv_value(d, "density")[0], "g cm⁻³")], label_w=150, value_w=170, unit_w=60))
        cl.addWidget(label("Crystal structure (VEC rule)", "heading"))
        cs = QHBoxLayout()
        cs.addWidget(TagLabel(d.get("cstr") or NA, long_text=False))
        cs.addWidget(label(f"VEC {kv_value(d, 'vec')[0]}", "secondary"))
        cs.addStretch(1)
        cl.addLayout(cs)
        cl.addStretch(1)
        comp.setFixedWidth(440)
        row.addWidget(comp)
        # Descriptors panel (two columns of groups)
        desc, dl = self._region("Descriptors")
        cols = QHBoxLayout()
        cols.setSpacing(24)
        for groups in (GROUPS[:3], GROUPS[3:6]):
            col = QVBoxLayout()
            col.setSpacing(4)
            for g in groups:
                col.addWidget(label(g, "heading"))
                rows = []
                for dd in DESCRIPTORS_LIST:
                    if dd.group != g:
                        continue
                    if dd.key == "cstr":
                        rows.append((dd.name, "", "", descriptor_tip("cstr"), d.get("cstr") or NA))
                        continue
                    val, tip = kv_value(d, dd.key)
                    name = self._descriptor_name(dd, d)
                    rows.append((f"{name} {dd.symbol}", val, dd.unit, descriptor_tip(dd.key), None, tip))
                col.addWidget(KVRows(rows, label_w=200, value_w=80, unit_w=90))
                col.addSpacing(12)
            col.addStretch(1)
            cols.addLayout(col, 1)
        dl.addLayout(cols)
        dl.addStretch(1)
        sa_d = scroll_wrap(desc)
        row.addWidget(sa_d, 1)
        # Models & provenance (520)
        mp, ml = self._region()
        n_eval, summary = MD.summary_line({k: res.models[k].label for k in MODEL_KEYS})
        ml.addWidget(SectionHeading("Model predictions", f"{n_eval} of 8 evaluated · {summary}"))
        table = self._models_table(("model", "pred", "status", "value"))
        ml.addWidget(table)
        ml.addWidget(label("Data quality", "heading"))
        for icon, token, text in self.quality_lines():
            ml.addWidget(StatusLine(icon, token, text))
        ml.addWidget(label("Provenance", "heading"))
        for line in self.provenance_lines():
            ml.addWidget(label(line, "label", wrap=True))
        ml.addStretch(1)
        sa_m = scroll_wrap(mp)
        sa_m.setFixedWidth(520)
        row.addWidget(sa_m)
        return host

    def provenance_lines(self) -> list[str]:
        info = self.info
        res = self.row.result
        out = []
        if info is not None:
            out.append(f"Run {info.run_id} · {mode_name(info.mode)} · calculated "
                       f"{(info.created or '').replace('T', ' ')[:16]}")
            out.append(f"Engine {info.engine_version or '—'} · app {info.app_version or '—'}")
        if res.temperature is not None:
            out.append(f"M6/M7 temperature {res.temperature:.1f} K ({_html.escape(res.temperature_source or '')})")
        if info is not None and info.dataset_ids:
            from ...core.provenance import DATASET_LABELS
            for name, ident in info.dataset_ids.items():
                out.append(f"{_html.escape(DATASET_LABELS.get(name, name))}: {ident}")
        return out

    @staticmethod
    def _descriptor_name(dd, d: dict) -> str:
        if dd.pair_key and d.get(dd.pair_key):
            return f"{dd.name} ({d[dd.pair_key]})"
        return dd.name

    # -------------------------------------------------------------- Descriptors
    def _descriptors(self) -> QWidget:
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(20 if self.size_class != "W" else 0, 16 if self.size_class != "W" else 0,
                               20 if self.size_class != "W" else 0, 0)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search_field = QLineEdit(self.search)
        self.search_field.setPlaceholderText("Find a descriptor")
        self.search_field.setAccessibleName("Find a descriptor")
        self.search_field.setFixedHeight(32)
        if self.size_class == "S":
            bar.addWidget(self.search_field, 1)
        else:
            self.search_field.setFixedWidth(240)
            bar.addWidget(self.search_field)
            bar.addStretch(1)
            from ..widgets.composition_panel import Toggle
            self.precision_toggle = Toggle(self.full_precision)
            self.precision_toggle.setAccessibleName("Full precision")
            bar.addWidget(label("Full precision", "secondary"))
            bar.addWidget(self.precision_toggle)
            self.precision_toggle.toggled.connect(lambda on: self.set_search(self.search, on))
        self.search_field.textChanged.connect(lambda txt: self.set_search(txt, self.full_precision))
        lay.addLayout(bar)
        cols = self._descriptor_columns()
        header = DataTable(cols, [], ROW_XS)
        lay.addWidget(header)                         # the header stays put while the rows scroll
        content = QWidget()
        sa, cl = scroll_page(content, (0, 0, 0, 16))
        cl.setSpacing(0)
        self.desc_table = DataTable(cols, [], ROW_XS, header=False)
        self.desc_table.activatable = False
        self.desc_table.setMouseTracking(True)
        self.desc_table.mouseReleaseEvent = self._descriptor_click
        cl.addWidget(self.desc_table)
        cl.addStretch(1)
        lay.addWidget(sa, 1)
        self._rebuild_descriptor_table()
        return host

    def _descriptor_columns(self):
        if self.size_class == "S":
            return [("Descriptor", None), ("Value", 88, "right"), ("Unit", 72), ("", 32)]
        if self.size_class in ("L", "W"):
            return [("Descriptor", 300), ("Symbol", 96), ("Value", 120, "right"), ("Unit", 120), ("Source", None),
                    ("", 40)]
        return [("Descriptor", None), ("Symbol", 96), ("Value", 110, "right"), ("Unit", 120), ("", 40)]

    def _rebuild_descriptor_table(self) -> None:
        d = descriptor_values(self.row)
        needle = self.search.strip().lower()
        rows, groups, keys = [], {}, []
        for g in GROUPS:
            first = True
            for dd in DESCRIPTORS_LIST:
                if dd.group != g:
                    continue
                name = self._descriptor_name(dd, d)
                hay = f"{name} {plain_text(dd.symbol)} {dd.plain} {dd.unit}".lower()
                if needle and needle not in hay:
                    continue
                if first:
                    groups[len(rows)] = g
                    first = False
                if dd.key == "cstr":
                    val = Cell(tag=d.get("cstr") or NA)
                else:
                    text, tip = kv_value(d, dd.key, self.full_precision)
                    val = Cell(text, align="right", tip=tip)
                unit = dd.unit or "–"
                if self.size_class == "S":
                    rows.append([Cell(f"{dd.symbol} <span style='color:{t('text-secondary')}'>{name}</span>"
                                      if dd.symbol else name), val, unit, Cell(status="caution")])
                elif self.size_class in ("L", "W"):
                    rows.append([name, dd.symbol or "–", val, unit, Cell(_html.escape(dd.data), color="text-secondary"),
                                 Cell(status="caution")])
                else:
                    rows.append([name, dd.symbol or "–", val, unit, Cell(status="caution")])
                keys.append(dd.key)
        self._desc_keys = keys
        self.desc_table.set_rows(rows, groups)

    def _descriptor_click(self, e):
        tbl = self.desc_table
        i = tbl.row_at(int(e.position().y()))
        if i < 0:
            return
        x0, w = tbl.column_rects()[-1]
        if x0 <= e.position().x() <= x0 + w:
            key = self._desc_keys[i]
            open_cell_tip(tbl, QRect(int(x0 + 4), tbl.row_y[i], 24, ROW_XS), descriptor_tip(key),
                          DESCRIPTORS[key].name)

    # -------------------------------------------------------------- Models
    def _models_table(self, columns=None) -> DataTable:
        res = self.row.result
        d = descriptor_values(self.row)
        cls = self.size_class
        if columns is None:
            columns = ("model", "value", "pred", "status") if cls == "S" else \
                ("model", "pred", "status", "value", "threshold", *(("ref",) if cls == "L" else ()))
        spec = {"model": ("Model", 148 if cls == "S" else 196), "pred": ("Prediction", 80),
                "status": ("Status", 52 if cls != "S" else 40), "value": ("Criterion value", 200 if cls != "S" else None),
                "threshold": ("Threshold", None), "ref": ("Reference", 260)}
        if cls == "W" and "threshold" not in columns:
            spec["value"] = ("Key value", None)
        cols = [spec[c] for c in columns]
        rows, tips = [], []
        for k in MODEL_KEYS:
            o = res.models[k]
            st = verdict_status(o)
            cells = []
            for c in columns:
                if c == "model":
                    cells.append(MD.title(k, short=cls == "S"))
                elif c == "pred":
                    cells.append(Cell(tag=o.label))
                elif c == "status":
                    cells.append(Cell(status=st, tip=MD.STATUS_LABELS.get(o.status) if st else ""))
                elif c == "value":
                    cells.append(Cell(MD.criterion_value_text(k, d, o.label),
                                      color="text-secondary" if o.label == NA else ""))
                elif c == "threshold":
                    cells.append(MD.threshold_text(k, d))
                elif c == "ref":
                    cells.append(Cell(_html.escape(MODELS[k].short) + f" ({MD.YEARS[k]})", color="text-secondary"))
            rows.append(cells)
            tips.append(f"Threshold: {plain_text(MD.threshold_text(k, d))}" if cls == "S"
                        else f"Open details for {MD.title(k)}")
        table = DataTable(cols, rows, ROW_SM, activatable=True, row_tips=tips)
        status_col = list(columns).index("status") if "status" in columns else -1

        def click(e, tbl=table):
            i = tbl.row_at(int(e.position().y()))
            if i < 0:
                return
            if status_col >= 0:
                x0, w = tbl.column_rects()[status_col]
                o = res.models[MODEL_KEYS[i]]
                if x0 <= e.position().x() <= x0 + w and verdict_status(o):
                    open_cell_tip(tbl, QRect(int(x0 + 12), tbl.row_y[i] + 4, 24, 24), status_tip(MODEL_KEYS[i], o),
                                  MD.title(MODEL_KEYS[i]))
                    return
            tbl.focus_row = i
            tbl.activated.emit(i)
        table.mouseReleaseEvent = click
        table.activated.connect(lambda i: self._model_from_strip(MODEL_KEYS[i]))
        return table

    def _models(self) -> QWidget:
        res = self.row.result
        cls = self.size_class
        sa, lay = self._scroll((0, 0, 0, 16) if cls == "W" else (20, 16, 20, 16))
        lay.setSpacing(8)
        head = QHBoxLayout()
        n_eval, summary = MD.summary_line({k: res.models[k].label for k in MODEL_KEYS})
        n_na = 8 - n_eval
        text = f"<b>{n_eval} of 8</b> models evaluated" + (f" · {summary}" if summary and not n_na else "") + \
            (f" · {n_na} not available" if n_na else "")
        head.addWidget(label(text, "body"))
        head.addStretch(1)
        if cls != "S":
            for icon, token, name in (("warning_alt", "icon-secondary", "Extrapolated"),
                                      ("warning_filled", "support-warning", "Flagged binary data")):
                ic = QWidget()
                ic.setFixedSize(16, 16)
                ic.paintEvent = lambda _e, w=ic, n=icon, tk=token: _paint_icon(w, n, tk)
                head.addWidget(ic)
                head.addWidget(label(name, "label"))
                head.addSpacing(8)
        lay.addLayout(head)
        lay.addWidget(self._models_table())
        if cls == "S":
            lay.addWidget(label("Thresholds are shown in Model details and in each row's Tooltip.", "helper", wrap=True))
        lay.addStretch(1)
        return sa

    # -------------------------------------------------------------- Model details
    def _model_details(self) -> QWidget:
        k = self.model
        res = self.row.result
        o = res.models[k]
        d = descriptor_values(self.row)
        cls = self.size_class
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(0)
        if cls != "W":
            sel = QHBoxLayout()
            sel.setContentsMargins(20, 16, 20, 8)
            sel.setSpacing(0)
            dd = Dropdown([(m, MD.title(m)) for m in MODEL_KEYS], k, prefix="Model", inline=True,
                          accessible="Model")
            dd.setFixedWidth(340 if cls != "S" else 300)
            dd.changed.connect(lambda m: (self.model_selected.emit(m), self.set_model(m)))
            sel.addWidget(dd)
            sel.addSpacing(8)
            prev = IconButton("caret_left", "Previous model")
            nxt = IconButton("caret_right", "Next model")
            i = MODEL_KEYS.index(k)
            prev.clicked.connect(lambda: self._step_model(-1))
            nxt.clicked.connect(lambda: self._step_model(1))
            prev.setEnabled(i > 0)
            nxt.setEnabled(i < 7)
            sel.addWidget(prev)
            sel.addWidget(nxt)
            sel.addStretch(1)
            ol.addLayout(sel)
        content = QWidget()
        sa, lay = scroll_page(content, (20, 8, 20, 16) if cls != "W" else (0, 0, 0, 0))
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        verdict = QHBoxLayout()
        verdict.setSpacing(8)
        if cls == "W":
            verdict.addWidget(label(MD.title(k), "title"))
        tag = TagLabel(o.label, long_text=False)
        verdict.addWidget(tag)
        st = verdict_status(o)
        if st:
            verdict.addWidget(StatusIcon(st, status_tip(k, o)))
        verdict.addWidget(label(MD.NA_LABELS.get(o.na_kind, "Not available") if o.label == NA
                                else MD.STATUS_SHORT.get(o.status, ""), "secondary"))
        verdict.addStretch(1)
        ll.addLayout(verdict)
        if o.label != NA and o.status == STATUS_EXTRAPOLATED and o.caution:
            note = ActionableNotification()
            note.show_message("warning", "Extrapolated", _html.escape(o.caution))
            ll.addWidget(note)
        if o.label == NA:
            note = ActionableNotification()
            note.show_message("info", "Not available", _html.escape(o.reason or "") +
                              " Missing data are not replaced by zero.")
            ll.addWidget(note)
        ll.addSpacing(8)
        ll.addWidget(label("Criterion", "heading"))
        from ..widgets.equation import Equation
        ll.addWidget(Equation(k, 1.4 if cls == "W" else 1.0))
        ll.addWidget(label(_html.escape(MODELS[k].criterion), "label", wrap=True))
        ll.addSpacing(8)
        ll.addWidget(label("Evaluated values", "heading"))
        vals = []
        for key in MD.CRITERION_KEYS[k]:
            dd_ = DESCRIPTORS[key]
            v = d.get(key)
            text = format_sig(v, 5 if key == "gamma" else 4) if isinstance(v, float) else \
                ("Not available" if v is None else str(v))
            if key in ("t_assess",) and isinstance(v, float):
                text = format_value("hf_lower", v)
            name = self._descriptor_name(dd_, d)
            vals.append((f"{name} {dd_.symbol}", text, dd_.unit, None, None,
                         full_precision(v) if isinstance(v, float) else ""))
        if k == "M6" and d.get("hf_min") is not None:
            n_pairs = len(self.row.result.composition) * (len(self.row.result.composition) - 1) // 2
            vals.append(("Pairs evaluated", f"{n_pairs} of {n_pairs}", ""))
        ll.addWidget(KVRows(vals, label_w=220, value_w=100, unit_w=90))
        if k == "M6" and d.get("hf_lower") is not None and o.label != NA:
            from ...core.engine import default_engine
            pairs = default_engine().formation_pairs(self.row.result.composition)
            ll.addSpacing(8)
            ll.addWidget(label("Pair window", "heading"))
            ll.addWidget(PairWindow(pairs, d["hf_lower"]))
            inside = sum(1 for *_x, v, _f in pairs if v is not None and d["hf_lower"] < v < TROPAREVSKY_UPPER_MEV)
            lo = format_value("hf_lower", d["hf_lower"])
            ll.addWidget(label(f"{'All ' if inside == len(pairs) else ''}{inside} of {len(pairs)} pairs inside "
                               f"{lo} &lt; ΔH<sub>f</sub> &lt; {TROPAREVSKY_UPPER_MEV:g} meV atom⁻¹.", "label", wrap=True))
            if cls == "W":
                ll.addWidget(label("All binary pairs", "heading"))
                rows = [[f"{a}–{b}", Cell(format_value("hf_min", v) if v is not None else "N/A", align="right"),
                         Cell("Yes" if v is not None and d["hf_lower"] < v < TROPAREVSKY_UPPER_MEV else "No"),
                         Cell("Flagged" if flag else "", color="support-warning" if flag else "")]
                        for a, b, v, flag in pairs]
                ll.addWidget(DataTable([("Pair", 140), ("ΔH<sub>f</sub> (meV atom⁻¹)", 200, "right"),
                                        ("Inside window", 160), ("Data", None)], rows, ROW_XS))
        ll.addStretch(1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        h = MD.HELP[k]
        rl.addWidget(label("Interpretation", "heading"))
        rl.addWidget(label(h.interpretation or MODELS[k].note, "body", wrap=True))
        rl.addSpacing(8)
        data_head = QHBoxLayout()
        data_head.addWidget(label("Data", "heading"))
        if k in ("M6", "M7"):
            asym = d.get("formation_asymmetric_pairs") or []
            txt = ("DFT formation enthalpies of the lowest-energy binary compounds, 30 elements. Seven pairs are "
                   "printed with two values; the value of the first element's row in the published order is used.")
            txt += (" Used for this composition: " + ", ".join(asym) + ".") if asym else ""
            data_head.addWidget(InfoButton(txt, title="Troparevsky data"))
        data_head.addStretch(1)
        rl.addLayout(data_head)
        rl.addWidget(label(h.data, "body", wrap=True))
        if st == "data_suspect":
            rl.addWidget(label(_html.escape(o.caution or ""), "secondary", wrap=True))
        rl.addSpacing(8)
        rl.addWidget(label("Limitations", "heading"))
        rl.addWidget(label(h.limitations, "body", wrap=True))
        rl.addSpacing(8)
        rl.addWidget(label("Not available when", "heading"))
        rl.addWidget(label(h.not_available, "body", wrap=True))
        rl.addSpacing(8)
        rl.addWidget(label(_html.escape(MODELS[k].reference), "label", wrap=True))
        rl.addStretch(1)
        if cls == "S":
            lay.addWidget(left)
            lay.addWidget(right)
        else:
            row = QHBoxLayout()
            row.setSpacing(24)
            row.addWidget(left, 450 if cls != "W" else 980)
            row.addWidget(right, 291 if cls != "W" else 580)
            lay.addLayout(row)
        lay.addStretch(1)
        ol.addWidget(sa, 1)
        return outer

    def _step_model(self, step: int) -> None:
        i = MODEL_KEYS.index(self.model)
        j = max(0, min(7, i + step))
        if j != i:
            self.model_selected.emit(MODEL_KEYS[j])
            self.set_model(MODEL_KEYS[j])


def scroll_wrap(w: QWidget):
    from ..widgets.scroll import inner_scroll_area
    sa = inner_scroll_area(w)
    return sa


_ = (BODY_COMPACT_01, paint_html, QGridLayout)
