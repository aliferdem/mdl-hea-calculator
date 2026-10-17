"""Composition expression - one text area for expressions *and* their variable ranges (references
``design/fix needed/COMPOSITION_EXPRESSION_{DRAFT,FIXED_PARSED,PARAMETRIC_PARSED,BATCH_PARSED,STALE,ERROR}.png``).

The document syntax is :mod:`hea_calc.core.expression_doc`: blocks separated by blank lines, the first line of a
block is the expression, the following lines declare its variables (``0 <= x <= 2, step=0.05`` / ``points=31``,
optional ``p=`` preview value).  There are no Min / Max / Step fields outside the text area.

Parsing is explicit (the Parse icon in the field, or Ctrl+Enter) - never on every keystroke:

* **Draft**     helper text; Calculate unavailable;
* **Parsed**    green field + check, "Parsed successfully: …", the parsed block summary (one block: its composition
  preview table at the preview values; several blocks: one compact line per block); Calculate available once the
  background count has finished;
* **Stale**     any edit after a parse: warning icon, "Expression changed. Parse again to update the result.", the
  previous parse stays visible but Calculate is unavailable until Parse runs again;
* **Error**     red field + error icon; every failing block listed with its number, first line and reason;
  Calculate unavailable (valid blocks are never calculated on their own).

Counting (valid / skipped / duplicates per block) runs off the GUI thread - in a worker process for large documents.
"""

from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget

from ...core import composition as C
from ...core.data import Datasets
from ...core.expression import MAX_COMBINATIONS, ExpressionError, GenerationCancelled, evaluate_positive
from ...core.expression_doc import Document, parse_document, summary
from ...core.generation import RangeError
from ...core.limits import LARGE
from ...core.recipes import ExpressionRecipe
from .. import icons
from ..theme import t
from ..worker import BackgroundTask
from .common import IconButton, InfoButton, refresh_style
from .composition_footer import Status
from .menu import carbon_context_menu
from .scroll import inner_scroll_area, own_wheel, thin_scrollbars

HELPER_TEXT = "Enter one expression per block. Separate blocks with a blank line."
STALE_TEXT = "Expression changed. Parse again to update the result."
HEAVY_THRESHOLD = 5_000

EXPRESSION_HELP = (
    "<b>Composition expression</b><br>"
    "First line of a block: the expression - elements, amounts, groups, lower-case variables "
    "(<i>Al0.5CoCrFeNi</i>, <i>AlxCoCrFeNi</i>, <i>(FeCoNi)1-xAlx</i>, <i>B{a}</i>).<br>"
    "Following lines: one range per variable - <i>0 &lt;= x &lt;= 2, step=0.05</i> or "
    "<i>0 &lt;= x &lt;= 0.3, points=31</i> (both endpoints included).<br>"
    "Separate blocks with a blank line. Select Parse (Ctrl+Enter) to check the document.<br>"
    "<a href='help://expression-syntax'>Expression syntax reference</a>"
)

EDIT_MIN_H = 142
EDIT_MAX_H = 420
EDIT_COMPACT_H = 48                 # one line after a parse: the Carbon lg field height


def formula_html(source: str) -> str:
    """An expression with its amounts as subscripts: (FeCoNi)<sub>1-x</sub>Al<sub>x</sub>."""
    out = []
    i, s = 0, source.replace(" ", "")
    while i < len(s):
        ch = s[i]
        if ch.isupper():
            j = i + 1
            if j < len(s) and s[j].islower() and not (j + 1 < len(s) and s[j + 1] in "{_"):
                # a two-letter symbol unless the lower-case letter starts an amount (Alx: Al + x)
                j += 1
            out.append(html.escape(s[i:j]))
            i = j
        elif ch in "([":
            out.append(ch)
            i += 1
        elif ch in ")]":
            out.append(ch)
            i += 1
        else:
            j = i
            if s[j] == "{":
                k = s.find("}", j)
                k = len(s) - 1 if k < 0 else k
                out.append(f"<sub>{html.escape(s[j + 1:k])}</sub>")
                i = k + 1
                continue
            if s.startswith("_(", j):
                k = s.find(")", j)
                k = len(s) - 1 if k < 0 else k
                out.append(f"<sub>{html.escape(s[j + 2:k])}</sub>")
                i = k + 1
                continue
            while j < len(s) and not s[j].isupper() and s[j] not in "([)]{":
                j += 1
            out.append(f"<sub>{html.escape(s[i:j])}</sub>")
            i = j
    return "".join(out)


def _fmt(v: float) -> str:
    return f"{v:g}"


class _Editor(QPlainTextEdit):
    """The expression text area: grows with its content (the panel scrolls), Parse + state icons inside."""

    parse_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("ExpressionEdit")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setPlaceholderText("e.g. (Fe1.6CoCr0.4Mn)0.9Al0.1")
        self.setAccessibleName("Composition expression")
        thin_scrollbars(self)
        carbon_context_menu(self)
        self.parse_btn = IconButton("search_locate", "Parse expression", self)
        self.parse_btn.setFixedSize(32, 32)
        self.parse_btn.clicked.connect(self.parse_requested.emit)
        self.state_icon = QLabel(self)
        self.state_icon.setFixedSize(16, 16)
        self.state_icon.hide()
        self.compact = False            # after a parse the field hugs its lines (COMPOSITION_EXPRESSION_*)
        self.document().contentsChanged.connect(self.fit)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.parse_requested.emit)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.parse_requested.emit)
        self.fit()

    def fit(self):
        lines = max(1, self.document().blockCount())
        if self.compact:
            h = max(EDIT_COMPACT_H, int(lines * self.fontMetrics().lineSpacing() + 2 * 14))
        else:
            h = max(EDIT_MIN_H, int(lines * self.fontMetrics().lineSpacing() + 2 * 16 + 8))
        self.setFixedHeight(min(EDIT_MAX_H, h))

    def set_compact(self, on: bool):
        if on != self.compact:
            self.compact = on
            self.fit()

    def set_state_icon(self, name: str | None):
        if name is None:
            self.state_icon.hide()
            return
        self.state_icon.setPixmap(icons.pixmap(name, size=16))
        self.state_icon.show()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.parse_btn.move(self.width() - 72, 8)
        self.state_icon.move(self.width() - 32, 16)


class ExpressionView(QWidget):
    """See module docstring.  Public API used by the panel: ``text()``, ``parse()``, ``status()``,
    ``can_calculate()``, ``recipe()``, ``compositions()``, ``preview_tsv()``, ``add_element()`` /
    ``remove_element()``, ``clear()``, ``set_total_mass()``; ``expressions`` / ``detected`` describe the
    current parse."""

    changed = Signal()
    elements_parsed = Signal(list)
    message = Signal(str, str)

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        self.doc: Document | None = None          # the last parse (the calculation source while not stale)
        self.parsed_text = ""
        self.stale = False
        self.counting = False
        self.count_detail: dict | None = None
        self.count_error: str | None = None
        self.total_mass = 2.0
        self.expressions: list = []
        self.detected = (0, [], [])
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setObjectName("ExpressionContent")
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 14, 20, 16)
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
        self.edit = _Editor()
        self.edit.textChanged.connect(self._edited)
        self.edit.parse_requested.connect(self.parse)
        root.addWidget(self.edit)
        root.addSpacing(6)
        self.feedback = QLabel(HELPER_TEXT)
        self.feedback.setObjectName("Helper")
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.TextFormat.RichText)
        self.feedback.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.feedback.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        root.addWidget(self.feedback)
        root.addSpacing(16)
        self.section = QWidget()
        self.section_lay = QVBoxLayout(self.section)
        self.section_lay.setContentsMargins(0, 0, 0, 0)
        self.section_lay.setSpacing(0)
        self.section.hide()
        root.addWidget(self.section)
        root.addStretch(1)
        self.scroll = inner_scroll_area(content)
        own_wheel(self.scroll)
        outer.addWidget(self.scroll)
        self._counter = BackgroundTask(self)
        self._counter.done.connect(self._counted)
        self._counter.failed.connect(self._count_failed)

    # ------------------------------------------------------------------ state
    def text(self) -> str:
        return self.edit.toPlainText()

    def set_total_mass(self, grams: float) -> None:
        self.total_mass = grams
        if self.doc is not None and len(self.doc.blocks) == 1:
            self._render_section()

    def _edited(self):
        if self.doc is not None and self.doc.ok and self.text() != self.parsed_text:
            self.stale = True
        elif self.doc is not None and self.doc.ok and self.text() == self.parsed_text:
            self.stale = False
        elif self.doc is not None and not self.doc.ok:
            self.doc = None                     # an edit after an error goes back to the draft
            self.section.hide()
        self._render_feedback()
        self.changed.emit()

    def state(self) -> str:
        if not self.text().strip():
            return "empty"
        if self.doc is None:
            return "draft"
        if not self.doc.ok:
            return "error"
        if self.stale:
            return "stale"
        if self.count_error or self._zero_blocks():
            return "error"
        return "parsed"

    def _zero_blocks(self) -> list[int]:
        d = self.count_detail
        if d is None:
            return []
        return [i for i, (valid, _s, _d) in enumerate(d["blocks"]) if valid == 0]

    # ------------------------------------------------------------------ parse
    def parse(self) -> bool:
        """Parse the document now (Parse icon / Ctrl+Enter).  True when every block is valid."""
        text = self.text()
        self._counter.cancel()
        self.count_detail = None
        self.count_error = None
        if not text.strip():
            self.doc = None
            self.stale = False
            self.expressions = []
            self.detected = (0, [], [])
            self.section.hide()
            self._render_feedback()
            self.changed.emit()
            return False
        doc = parse_document(text, self.data)
        self.doc = doc
        self.parsed_text = text
        self.stale = False
        if doc.ok:
            self.expressions = doc.expressions
            els = doc.elements()
            self.detected = (len(doc.blocks), els, doc.variables)
            self.elements_parsed.emit(els)
            self._start_count()
        else:
            self.expressions = []
            self.detected = (0, [], [])
            self.section.hide()
        self._render_feedback()
        self._render_section()
        self.changed.emit()
        return doc.ok

    def _start_count(self):
        doc = self.doc
        n = doc.combinations
        if n > MAX_COMBINATIONS:
            self.count_error = (f"{n:,} combinations exceed the limit of {MAX_COMBINATIONS:,}.\n"
                                "Increase the steps or reduce the points.")
            return
        self.counting = True
        exprs, ranges = doc.expressions, doc.block_ranges
        from ...core.expression import count_blocks_detail
        if n <= HEAVY_THRESHOLD:
            self._counter.run(lambda cancelled=None: count_blocks_detail(exprs, ranges, cancelled=cancelled))
        else:
            from ...core.recipes import expression_count_detail
            self._counter.run_heavy(expression_count_detail, tuple(exprs), ranges)

    def _counted(self, detail):
        self.counting = False
        self.count_detail = detail
        self._render_feedback()
        self._render_section()
        self.changed.emit()

    def _count_failed(self, exc):
        if isinstance(exc, GenerationCancelled):
            return
        self.counting = False
        self.count_error = str(exc)
        self._render_feedback()
        self.changed.emit()

    # ------------------------------------------------------------------ rendering
    def _set_field(self, state: str | None):
        for prop, on in (("invalid", state == "invalid"), ("valid", state == "valid")):
            if bool(self.edit.property(prop)) != on:
                self.edit.setProperty(prop, on)
                refresh_style(self.edit)

    def _render_feedback(self):
        st = self.state()
        self.edit.set_compact(st not in ("empty", "draft"))
        if st in ("empty", "draft"):
            self._set_field(None)
            self.edit.set_state_icon(None)
            self.feedback.setText(f"<span style='color:{t('text-helper')}'>{HELPER_TEXT}</span>")
            return
        if st == "stale":
            self._set_field(None)
            self.edit.set_state_icon("status_warn")
            self.feedback.setText(f"<span style='color:{t('text-primary')}'>{STALE_TEXT}</span>")
            return
        if st == "error":
            self._set_field("invalid")
            self.edit.set_state_icon("field_invalid")
            self.feedback.setText(self._errors_html())
            return
        self._set_field("valid")
        self.edit.set_state_icon("notify_success")
        d = self.count_detail
        if d is None:
            text = summary(self.doc) if self.doc.blocks[0].kind == "fixed" and len(self.doc.blocks) == 1 else \
                summary(self.doc) + " Counting compositions…"
        else:
            text = summary(self.doc, d["valid"], d["duplicates"])
        self.feedback.setText(f"<span style='color:{t('support-success')}'>{html.escape(text)}</span>")

    def _errors_html(self) -> str:
        err = t("text-error")
        rows = []
        if self.doc is not None and not self.doc.ok:
            items = self.doc.errors
        else:
            items = [(i + 1, self.doc.blocks[i].first_line, "No valid compositions: every combination is skipped "
                                                            "(negative amounts or fewer than two elements).")
                     for i in self._zero_blocks()]
            if self.count_error:
                items.append((0, "", self.count_error))
        for n, first, msg in items:
            lines = [html.escape(x) for x in msg.split("\n")]
            head = f"{n}&nbsp;&nbsp;{html.escape(first)}" if n else ""
            body = "<br>".join("&nbsp;&nbsp;&nbsp;&nbsp;" + x if n else x for x in lines)
            rows.append(f"<p style='margin:0 0 10px 0; color:{err}'>{head}{'<br>' if head else ''}{body}</p>")
        return "".join(rows)

    def _render_section(self):
        from .common import retire
        lay = self.section_lay
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                retire(w)
        doc = self.doc
        if doc is None or not doc.ok:
            self.section.hide()
            return
        n = len(doc.blocks)
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 8)
        title = QLabel("Parsed expression" if n == 1 else "Parsed expressions")
        title.setObjectName("Heading")
        hl.addWidget(title)
        hl.addStretch(1)
        hl.addWidget(_CountTag(n))
        lay.addWidget(head)
        lay.addWidget(_Rule())
        per = self.count_detail["blocks"] if self.count_detail else [None] * n
        for b, counts in zip(doc.blocks, per):
            lay.addWidget(self._block_item(b, counts))
            lay.addWidget(_Rule())
        if n == 1:
            tbl = self._preview_table(doc.blocks[0])
            if tbl is not None:
                lay.addSpacing(16)
                lay.addWidget(tbl)
        self.section.show()

    def _block_item(self, b, counts) -> QLabel:
        ex = b.expression
        sec = t("text-secondary")
        n_el = len(_elements(ex))
        valid = counts[0] if counts else None
        comps = "…" if valid is None else f"{valid:,} composition{'s' if valid != 1 else ''}"
        parts = [f"<div style='font-size:16px; color:{t('text-primary')}'>{formula_html(ex.source)}</div>"]
        if b.kind == "fixed":
            parts.append(f"<div style='color:{sec}'>Fixed | {n_el} elements | {comps}</div>")
        else:
            rows = []
            for v in ex.variables:
                r = b.ranges[v]
                vals = r.values()
                sampling = f"Step {_fmt(r.step)}" if r.step is not None else f"{len(vals)} points"
                prev = r.preview if r.preview is not None else r.minimum
                rows.append(f"<tr><td style='padding-right:16px'>{html.escape(v)}</td>"
                            f"<td style='padding-right:16px'>{_fmt(r.minimum)} → {_fmt(r.maximum)}</td>"
                            f"<td style='padding-right:16px'>{sampling}</td>"
                            f"<td style='padding-right:16px'>Preview {_fmt(prev)}</td>"
                            f"<td>{len(vals)} point{'s' if len(vals) != 1 else ''}</td></tr>")
            parts.append(f"<table style='color:{sec}' cellspacing='0' cellpadding='0'>{''.join(rows)}</table>")
            parts.append(f"<div style='color:{sec}'>{comps}</div>")
        lab = QLabel("".join(parts))
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        lab.setContentsMargins(16, 8, 16, 8)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return lab

    def preview_composition(self, b=None) -> dict | None:
        b = b or (self.doc.blocks[0] if self.doc and self.doc.ok and len(self.doc.blocks) == 1 else None)
        if b is None:
            return None
        try:
            return evaluate_positive(b.expression, b.preview_env())
        except ExpressionError:
            return None

    def preview_rows(self) -> list[tuple[str, dict]]:
        comp = self.preview_composition()
        if not comp:
            return []
        reps = C.all_representations(dict(comp), "ratio", total_mass=self.total_mass, datasets=self.data)
        return [(el, {k: reps[k][el] for k in ("ratio", "at", "wt", "mass")}) for el in comp]

    def _preview_table(self, b):
        rows = self.preview_rows()
        if not rows:
            return None
        from ..analysis.widgets import Cell, DataTable, ROW_SM
        cols = [("Element", None), ("At. ratio", None, "right"), ("at.%", None, "right"), ("wt.%", None, "right"),
                (f"Mass ({self.total_mass:g} g)", None, "right")]
        data = [[el, Cell(f"{v['ratio']:.4f}", align="right"), Cell(f"{v['at']:.4f}", align="right"),
                 Cell(f"{v['wt']:.4f}", align="right"), Cell(f"{v['mass']:.4f}", align="right")] for el, v in rows]
        return DataTable(cols, data, ROW_SM)

    def preview_tsv(self) -> str:
        lines = ["Element\tAt. ratio\tat.%\twt.%\tMass (g)"]
        for el, v in self.preview_rows():
            lines.append(f"{el}\t{v['ratio']:.4f}\t{v['at']:.4f}\t{v['wt']:.4f}\t{v['mass']:.5f}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ footer contract
    def status(self) -> Status | None:
        st = self.state()
        if st in ("empty", "draft", "stale", "error"):
            return None                          # the field and its message say it (references show no footer)
        if self.counting:
            return Status("loading", "Updating…")
        d = self.count_detail
        if d is not None:
            if d["valid"] >= LARGE:
                from .composition_panel import size_note
                svc = getattr(self.window(), "jobs", None)
                _tier, tip = size_note(d["valid"], getattr(svc, "workers", 1))
                return Status("info", "Large workload", [tip, "<a href='help://workload'>About workload "
                                                              "estimates</a>"], "Large workload")
            if d["skipped"]:
                k = d["skipped"]
                return Status("info", f"{k:,} combination{'s' if k != 1 else ''} skipped",
                              "Skipped: variable values giving negative amounts or fewer than two elements.")
        return None

    def can_calculate(self) -> bool:
        return self.state() == "parsed" and not self.counting and self.count_detail is not None \
            and self.count_detail["valid"] > 0

    def recipe(self) -> ExpressionRecipe:
        """The parsed document as a calculation recipe (generation happens in the calculation job)."""
        if self.state() != "parsed":
            raise ExpressionError("Parse the expression first." if self.state() in ("draft", "stale")
                                  else "The expression has errors.")
        doc = self.doc
        n = doc.combinations
        if n > MAX_COMBINATIONS:
            raise RangeError(f"{n:,} combinations exceed the limit of {MAX_COMBINATIONS:,}; increase the steps.")
        merged: dict = {}
        for r in doc.block_ranges:
            for k, v in r.items():
                merged.setdefault(k, v)
        return ExpressionRecipe(tuple(doc.expressions), tuple(merged.items()), doc.text,
                                tuple(tuple(r.items()) for r in doc.block_ranges))

    def compositions(self):
        return self.recipe()()[1:]

    # ------------------------------------------------------------------ periodic table
    def _expression_lines(self) -> list[int]:
        """Line numbers of the expression (first) line of every block."""
        out, prev_blank = [], True
        for i, line in enumerate(self.text().split("\n")):
            if line.strip() and prev_blank:
                out.append(i)
            prev_blank = not line.strip()
        return out

    def add_element(self, el: str):
        """Append an element to the expression line of the last block (never to a range line)."""
        lines = self.text().split("\n")
        exprs = self._expression_lines()
        if not exprs:
            self.edit.setPlainText(el)
            return
        i = exprs[-1]
        if re.search(rf"{el}(?![a-z])", lines[i]):
            return
        lines[i] = lines[i].rstrip() + el
        self.edit.setPlainText("\n".join(lines))

    def remove_element(self, el: str):
        lines = self.text().split("\n")
        for i in self._expression_lines():
            new = re.sub(rf"{el}(?![a-z])(\{{[^}}]*\}}|_\([^)]*\)|_\{{[^}}]*\}}|[0-9.]*[a-z0-9_+\-*/.]*)?", "",
                         lines[i])
            lines[i] = new.replace("()", "")
        self.edit.setPlainText("\n".join(lines))

    def clear(self):
        self.edit.clear()
        self.parse()


class _CountTag(QWidget):
    """Carbon gray tag (sm, 20 px pill) holding the number of parsed blocks."""

    def __init__(self, n: int):
        super().__init__()
        self.text = str(n)
        from ..theme import LABEL_01, font
        self.setFont(font(LABEL_01))
        self.setFixedSize(max(24, self.fontMetrics().horizontalAdvance(self.text) + 16), 20)

    def paintEvent(self, _e):
        from PySide6.QtGui import QColor, QPainter
        from .. import crisp
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        crisp.fill_pill(p, self.rect(), t("layer-selected-01"))
        p.setPen(QColor(t("text-primary")))
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.text)
        p.end()


class _Rule(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(1)
        self.setObjectName("ParsedRule")


def _elements(ex) -> list[str]:
    out: list[str] = []

    def walk(items):
        for it in items:
            if hasattr(it, "symbol"):
                if it.symbol not in out:
                    out.append(it.symbol)
            else:
                walk(it.items)
    walk(ex.items)
    return out

