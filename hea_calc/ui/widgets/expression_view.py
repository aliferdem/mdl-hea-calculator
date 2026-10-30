"""Expression mode of Composition setup (Figma "Expression bases" 584:51933 - Empty, Draft, Error, Stale, Fixed /
Parametric / Batch parsed - and Composition setup Mode=Expression 392:69514).

One code editor (:class:`~.code_editor.CodeEditor`) holds the whole document - expressions *and* their range
lines (syntax: :mod:`hea_calc.core.expression_doc`).  Below it, after a parse, the "Parsed expressions" list and,
for one block, the composition preview (Element / At. ratio / at.% / wt.% / Mass).

Editor states (the header tag is the panel's :class:`~.status_tag.PanelStatus`, from :meth:`status`):

* **empty**      no text; Parse expression unavailable;
* **editing**    text that has not been parsed; problems that only mean "unfinished" on the caret's line are held
  back while the user types there;
* **ready**      no problem found (Figma Draft): Parse expression available;
* **error**      lexical / syntax / semantic problems - wavy underlines + overview marks; the tag names the problem
  ("Unknown element "Xx"") or says "Multiple errors"; its toggletip lists every problem by line; Parse unavailable;
* **parsing**    Parse was chosen: the document is parsed and its compositions counted off the GUI thread
  ("Parsing…" inline loading);
* **parsed**     green "Parsed successfully"; Calculate (with Copy table) replaces Parse expression;
* **warnings**   parsed, but combinations were skipped or duplicates removed: blue "Parsed with warnings" (toggletip);
* **workload**   parsed, but the batch exceeds the combination limit (red "Workload too large") or is large (blue
  "Large workload") - a workload is never reported as an invalid expression;
* **stale**      text edited after a parse: blue "Expression changed"; the previous parse stays visible, Calculate is
  unavailable until Parse runs again (the calculation never uses an outdated parse: :meth:`recipe` refuses it).

Problems are found by one debounced validation pass (``VALIDATE_MS`` after the last keystroke) that also adds the
automatic range declarations (:func:`hea_calc.core.expression_doc.plan_declarations`): a new variable gets
``0 <= v <= 1, step=0.1`` as one undo step of its own; the caret, the selection and the user's undo history are
kept.  Model support (which models cannot be evaluated for these elements) is the panel's coverage status, never a
syntax error.
"""

from __future__ import annotations

import html
import re

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QTextCursor, QTextBlockUserData
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...core import composition as C
from ...core.data import Datasets
from ...core.expression import MAX_COMBINATIONS, ExpressionError, GenerationCancelled, evaluate_positive
from ...core.expression_doc import (Diagnostic, Document, LEXICAL, SEMANTIC, SYNTAX, parse_document,
                                    plan_declarations)
from ...core.expression_lexer import ROLE_EXPRESSION, line_roles
from ...core.generation import RangeError
from ...core.limits import LARGE
from ...core.recipes import ExpressionRecipe
from .. import crisp
from ..theme import BODY_COMPACT_01, HEADING_COMPACT_01, LABEL_01, font, t
from ..worker import BackgroundTask
from .code_editor import CodeEditor, LINE_H
from .composition_footer import Status
from .scroll import inner_scroll_area

HEAVY_THRESHOLD = 5_000
VALIDATE_MS = 450                   # validation / automatic declarations wait for a pause in typing
EDITOR_TOP = 8                      # Figma: the editor starts 8 px under the 40 px header

EXPRESSION_HELP = (
    "<b>Expression syntax</b><br>"
    "First line of a block: the expression - elements, amounts, groups, lower-case variables "
    "(<i>Al0.5CoCrFeNi</i>, <i>CrMnFeCoNiyCux</i>, <i>(FeCoNi)1-x(AlTi)x</i>, <i>B{a}</i>).<br>"
    "Following lines: one range per variable - <i>0 &lt;= x &lt;= 1, step=0.1</i>, <i>0 &lt;= x &lt;= 1, "
    "points=11</i>; <i>&lt;</i> excludes an endpoint (<i>0 &lt; x &lt; 1, step=0.1</i>).  A new variable gets a "
    "default range automatically.<br>"
    "Separate blocks with a blank line. Parse expression (Ctrl+Enter) checks the document.<br>"
    "<a href='help://expression-syntax'>Expression syntax reference</a>"
)

STATE_TAGS = {
    "parsed": ("Parsed successfully", "green"),
    "warnings": ("Parsed with warnings", "blue"),
    "stale": ("Expression changed", "blue"),
}
CATEGORY_NAMES = {LEXICAL: "Lexical", SYNTAX: "Syntax", SEMANTIC: "Range"}


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


class _Memory(QTextBlockUserData):
    """Variables already declared or offered for the block whose expression line carries this (see
    :func:`plan_declarations`).  Lives on the QTextBlock, so it follows the line through edits."""

    def __init__(self, names=()):
        super().__init__()
        self.names = set(names)


class ExpressionView(QWidget):
    """See module docstring.  Public API used by the panel: ``text()``, ``parse()``, ``state()``, ``status()``,
    ``primary_action()``, ``can_calculate()``, ``recipe()``, ``compositions()``, ``preview_tsv()``,
    ``add_element()`` / ``remove_element()``, ``clear()``, ``set_total_mass()``; ``expressions`` / ``detected``
    describe the current parse."""

    changed = Signal()
    elements_parsed = Signal(list)
    message = Signal(str, str)

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        self.doc: Document | None = None          # the last *parse* (the calculation source while not stale)
        self.parsed_text = ""
        self.stale = False
        self.counting = False
        self.count_detail: dict | None = None
        self.count_error: str | None = None
        self.total_mass = 2.0
        self.expressions: list = []
        self.detected = (0, [], [])
        self.live: list[Diagnostic] = []          # every problem of the current text (last validation)
        self.shown: list[Diagnostic] = []         # the ones underlined now (unfinished caret-line ones held back)
        self.validated_text: str | None = None
        self.typing = False                       # an edit is waiting for the validation pause
        self._auto_editing = False
        self._undo_steps = 0
        self._ready = False                       # the event filter waits for the widgets below
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget()
        self.content.setObjectName("ExpressionContent")
        root = QVBoxLayout(self.content)
        root.setContentsMargins(0, EDITOR_TOP, 0, 0)
        root.setSpacing(0)
        self.edit = CodeEditor(datasets)
        self.edit.textChanged.connect(self._edited)
        self.edit.parse_requested.connect(self.parse)
        self.edit.cursorPositionChanged.connect(self._caret_moved)
        self.edit.installEventFilter(self)
        root.addWidget(self.edit)
        self.section = QWidget()
        self.section_lay = QVBoxLayout(self.section)
        self.section_lay.setContentsMargins(16, 16, 16, 16)
        self.section_lay.setSpacing(0)
        self.section.hide()
        root.addWidget(self.section)
        root.addStretch(1)
        self.scroll = inner_scroll_area(self.content)
        self.scroll.viewport().installEventFilter(self)
        outer.addWidget(self.scroll)
        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(VALIDATE_MS)
        self._validate_timer.timeout.connect(self._validate)
        self._counter = BackgroundTask(self)
        self._counter.done.connect(self._counted)
        self._counter.failed.connect(self._count_failed)
        self._ready = True
        self._fit_editor()

    # ------------------------------------------------------------------ text
    def text(self) -> str:
        return self.edit.toPlainText()

    def set_text(self, text: str) -> None:
        """Programmatic text (restore, import): no automatic declarations for what is already there."""
        self.edit.setPlainText(text)
        self._seed_memory()
        self._validate()

    def set_total_mass(self, grams: float) -> None:
        self.total_mass = grams
        if self.doc is not None and self.doc.ok and len(self.doc.blocks) == 1:
            self._render_section()

    def eventFilter(self, obj, ev):
        if not self._ready:
            return False
        if obj is self.scroll.viewport() and ev.type() == ev.Type.Resize:
            self._fit_editor()
        elif obj is self.edit and ev.type() == ev.Type.FocusOut:
            if self.typing:
                self._validate_timer.stop()
                self._validate()
            else:
                self._refresh_shown()
        return False

    # ------------------------------------------------------------------ editing
    def _edited(self):
        if self._auto_editing:
            return
        doc = self.edit.document()
        steps = doc.availableUndoSteps()
        undoing = steps < self._undo_steps            # an undo (any path: keys, menu, Edit > Undo)
        self._undo_steps = steps
        text = self.text()
        if self.doc is not None and self.doc.ok:
            self.stale = text != self.parsed_text
        elif self.doc is not None and not self.doc.ok:
            self.doc = None                           # an edit after a failed parse goes back to editing
            self.section.hide()
        self.typing = True
        self.validated_text = None
        if undoing:
            self._seed_memory()                       # an undone automatic declaration is not added back
        self._validate_timer.start()
        self._fit_editor()
        self._refresh_shown()
        self.changed.emit()

    def _caret_moved(self):
        self._refresh_shown()
        self._ensure_caret_visible()

    def _ensure_caret_visible(self):
        r = self.edit.cursorRect()
        top = self.edit.mapTo(self.content, r.topLeft())
        self.scroll.ensureVisible(top.x(), top.y() + LINE_H // 2, 0, LINE_H)

    def _expression_blocks(self):
        """QTextBlocks of the expression line of every document block (in order)."""
        doc = self.edit.document()
        lines = self.text().split("\n")
        roles = line_roles(lines)
        return [doc.findBlockByNumber(i) for i, r in enumerate(roles) if r == ROLE_EXPRESSION]

    def _memory(self) -> list[set[str]]:
        out = []
        for blk in self._expression_blocks():
            m = blk.userData()
            out.append(set(m.names) if isinstance(m, _Memory) else set())
        return out

    def _store_memory(self, memory: list[set[str]]) -> None:
        for blk, names in zip(self._expression_blocks(), memory):
            m = blk.userData()
            if isinstance(m, _Memory):
                m.names = set(names)
            else:
                blk.setUserData(_Memory(names))

    def _seed_memory(self) -> None:
        """Remember every current variable and declaration as known (nothing is generated for them)."""
        from ...core.expression_doc import document_blocks
        from ...core.expression_lexer import declared_variable, formula_variables
        mem = []
        for _first, lines in document_blocks(self.text()):
            names = set(formula_variables(lines[0][1], self.data))
            for _n, ln in lines[1:]:
                dv = declared_variable(ln)
                if dv:
                    names.add(dv[0])
            mem.append(names)
        self._store_memory(mem)

    def _declare(self) -> bool:
        """Apply the automatic range declarations as one undo step; True when the text changed."""
        edits, memory = plan_declarations(self.text(), self.data, self._memory())
        if not edits:
            self._store_memory(memory)
            return False
        ed = self.edit
        doc = ed.document()
        caret = ed.textCursor()
        pos, anchor = caret.position(), caret.anchor()
        self._auto_editing = True
        c = QTextCursor(doc)
        c.beginEditBlock()
        try:
            inserts: dict[int, list[str]] = {}
            for e in edits:
                if e.kind == "insert":
                    inserts.setdefault(e.line, []).append(e.text)
            # bottom-up: earlier line numbers stay valid
            for line in sorted({e.line for e in edits}, reverse=True):
                blk = doc.findBlockByNumber(line)
                if line in inserts:
                    c.setPosition(blk.position() + len(blk.text()))
                    c.insertText("".join("\n" + x for x in inserts[line]))
                for e in edits:
                    if e.line != line or e.kind == "insert":
                        continue
                    if e.kind == "rename":
                        c.setPosition(blk.position() + e.start)
                        c.setPosition(blk.position() + e.end, QTextCursor.MoveMode.KeepAnchor)
                        c.insertText(e.text)
                    elif e.kind == "delete":
                        c.setPosition(blk.position())
                        nxt = blk.next()
                        if nxt.isValid():
                            c.setPosition(nxt.position(), QTextCursor.MoveMode.KeepAnchor)
                        else:
                            c.setPosition(max(0, blk.position() - 1))
                            c.setPosition(blk.position() + len(blk.text()), QTextCursor.MoveMode.KeepAnchor)
                        c.removeSelectedText()
        finally:
            c.endEditBlock()
            self._auto_editing = False
        # the user's caret and selection stay where they were (an insertion at the caret must not carry it along)
        n = doc.characterCount() - 1
        if caret.position() != pos or caret.anchor() != anchor:
            keep = ed.textCursor()
            keep.setPosition(min(anchor, n))
            keep.setPosition(min(pos, n), QTextCursor.MoveMode.KeepAnchor)
            ed.setTextCursor(keep)
        self._undo_steps = doc.availableUndoSteps()
        self._store_memory(memory)
        return True

    def _validate(self):
        """The debounced pass: automatic declarations, then every problem of the text."""
        self._validate_timer.stop()
        self.typing = False
        if self.text().strip():
            changed = self._declare()
            if changed and self.doc is not None and self.doc.ok:
                self.stale = self.text() != self.parsed_text
        text = self.text()
        self.live = parse_document(text, self.data).diagnostics if text.strip() else []
        self.validated_text = text
        self._fit_editor()
        self._refresh_shown()
        self.changed.emit()

    def _refresh_shown(self):
        """Underline the problems, holding back the "unfinished" ones on the caret's line while the user types
        there (and everything on that line during the typing pause)."""
        if self.validated_text != self.text():
            line = self.edit.textCursor().blockNumber()
            shown = [d for d in self.live if d.line != line]
        elif self.edit.hasFocus():
            line = self.edit.textCursor().blockNumber()
            shown = [d for d in self.live if not (d.incomplete and d.line == line)]
        else:
            shown = list(self.live)
        if shown != self.shown:
            self.shown = shown
            self.edit.set_diagnostics(shown)
            self.changed.emit()

    # ------------------------------------------------------------------ state
    def state(self) -> str:
        if not self.text().strip():
            return "empty"
        if self.shown:
            return "error"
        if self.doc is not None and not self.doc.ok:
            return "error"
        if self.doc is None:
            return "editing" if (self.typing or self.validated_text != self.text() or self.live) else "ready"
        if self.stale:
            return "stale"
        if self.counting:
            return "parsing"
        if self.count_error or self._zero_blocks():
            return "workload" if self.count_error else "error"
        d = self.count_detail
        if d is not None and d["valid"] >= LARGE:
            return "workload"
        if d is not None and (d["skipped"] or d["duplicates"]):
            return "warnings"
        return "parsed"

    def _zero_blocks(self) -> list[int]:
        d = self.count_detail
        if d is None:
            return []
        return [i for i, (valid, _s, _d) in enumerate(d["blocks"]) if valid == 0]

    def problems(self) -> list[Diagnostic]:
        """Problems of the state: the shown underlines, or those of a failed parse."""
        if self.shown:
            return list(self.shown)
        if self.doc is not None and not self.doc.ok:
            return self.doc.diagnostics
        return []

    # ------------------------------------------------------------------ parse
    def parse(self) -> bool:
        """Parse the document now (Parse expression / Ctrl+Enter).  True when every block is valid."""
        if self.typing:
            self._validate()
        text = self.text()
        self._counter.cancel()
        self.count_detail = None
        self.count_error = None
        self.counting = False
        if not text.strip():
            self.doc = None
            self.stale = False
            self.expressions = []
            self.detected = (0, [], [])
            self.live, self.shown = [], []
            self.edit.set_diagnostics([])
            self.section.hide()
            self._fit_editor()
            self.changed.emit()
            return False
        doc = parse_document(text, self.data)
        self.doc = doc
        self.parsed_text = text
        self.stale = False
        self.live = doc.diagnostics
        self.validated_text = text
        self.shown = list(self.live)                  # an explicit parse shows every problem, unfinished included
        self.edit.set_diagnostics(self.shown)
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
        self._render_section()
        self._fit_editor()
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
        self._render_section()
        self.changed.emit()

    def _count_failed(self, exc):
        if isinstance(exc, GenerationCancelled):
            return
        self.counting = False
        self.count_error = str(exc)
        self.changed.emit()

    # ------------------------------------------------------------------ layout
    def _fit_editor(self):
        """Empty / editing / error: the editor fills the panel; parsed / stale: it hugs its lines and the parse
        result follows (Figma Draft / Error vs Fixed parsed / Stale)."""
        need = self.edit.content_height()
        compact = self.doc is not None and self.doc.ok and not self.shown
        avail = self.scroll.viewport().height() - EDITOR_TOP
        h = need if compact else max(need, avail)
        if self.edit.height() != h:
            self.edit.setFixedHeight(max(LINE_H, h))

    # ------------------------------------------------------------------ rendering
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
        per = self.count_detail["blocks"] if self.count_detail else [None] * n
        valid = self.count_detail["valid"] if self.count_detail else None
        if n == 1:
            count = "1" if doc.blocks[0].kind == "fixed" else \
                (f"1 expression, {valid:,} composition{'s' if valid != 1 else ''}" if valid is not None else "1")
        else:
            count = f"{n} expressions" + (f", {valid:,} compositions" if valid is not None else "")
        lay.addWidget(_ListTitle("Parsed expressions", count))
        for b, counts in zip(doc.blocks, per):
            lay.addWidget(self._block_item(b, counts, n > 1))
            lay.addWidget(_Rule())
        if n == 1:
            rows = self.preview_rows()
            if rows:
                lay.addSpacing(12)
                lay.addWidget(_PreviewTable(rows))
        self.section.show()

    def _block_item(self, b, counts, batch: bool) -> QLabel:
        ex = b.expression
        helper = t("text-helper")
        n_el = len(_elements(ex))
        valid = counts[0] if counts else None
        comps = "…" if valid is None else f"{valid:,} composition{'s' if valid != 1 else ''}"
        size = 16 if (b.kind == "parametric" and not batch) else 14
        parts = [f"<div style='font-size:{size}px; color:{t('text-primary')}'>{formula_html(ex.source)}</div>"]
        if b.kind == "fixed":
            parts.append(f"<div style='color:{helper}'>Fixed | {n_el} elements | {comps}</div>")
        elif batch:
            ranges = []
            for v in ex.variables:
                r = b.ranges[v]
                ranges.append(f"{html.escape(_range_span(r))} | "
                              + (f"step {_fmt(r.step)}" if r.step is not None else f"{len(r.values())} points"))
            parts.append(f"<div style='color:{helper}'>{' ; '.join(ranges)} | {comps}</div>")
        else:
            rows = []
            for v in ex.variables:
                r = b.ranges[v]
                vals = r.values()
                sampling = f"Step {_fmt(r.step)}" if r.step is not None else f"{len(vals)} points"
                prev = r.preview if r.preview is not None else vals[0]
                rows.append(f"<tr><td style='padding-right:20px'>{html.escape(v)}</td>"
                            f"<td style='padding-right:20px'>{html.escape(_range_span(r, short=True))}</td>"
                            f"<td style='padding-right:20px'>{sampling}</td>"
                            f"<td style='padding-right:20px'>Preview {_fmt(prev)}</td>"
                            f"<td>{len(vals)} point{'s' if len(vals) != 1 else ''}</td></tr>")
            parts.append(f"<table style='color:{helper}' cellspacing='0' cellpadding='0'>{''.join(rows)}</table>")
            parts.append(f"<div style='color:{helper}'>{comps}</div>")
        lab = QLabel("".join(parts))
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        lab.setFont(font(BODY_COMPACT_01))
        lab.setContentsMargins(16, 6, 16, 6)
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

    def preview_tsv(self) -> str:
        lines = ["Element\tAt. ratio\tat.%\twt.%\tMass (g)"]
        for el, v in self.preview_rows():
            lines.append(f"{el}\t{v['ratio']:.4f}\t{v['at']:.4f}\t{v['wt']:.4f}\t{v['mass']:.5f}")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ header status / footer contract
    def _problems_html(self, items: list[Diagnostic]) -> str:
        rows = []
        for d in items:
            msg = "<br>".join(html.escape(x) for x in d.message.split("\n"))
            rows.append(f"<p style='margin:0 0 8px 0'><b>Line {d.line + 1}</b> ({CATEGORY_NAMES.get(d.category, '')})"
                        f"<br>{msg}</p>")
        return "".join(rows)

    def status(self) -> Status | None:
        st = self.state()
        if st in ("empty", "editing", "ready"):
            return None
        if st == "error":
            items = self.problems()
            if items:
                title = "Multiple errors" if len(items) > 1 else items[0].title.rstrip(".")
                return Status("error", title, self._problems_html(items), "Expression problems")
            zero = self._zero_blocks()
            return Status("error", "No valid compositions",
                          "Every combination of block " + ", ".join(str(i + 1) for i in zero) +
                          " is skipped (negative amounts or fewer than two elements).", "No valid compositions")
        if st == "parsing":
            return Status("loading", "Parsing…")
        if st == "workload":
            if self.count_error:
                return Status("error", "Workload too large", self.count_error, "Workload too large")
            from .composition_panel import size_note
            svc = getattr(self.window(), "jobs", None)
            _tier, tip = size_note(self.count_detail["valid"], getattr(svc, "workers", 1))
            return Status("info", "Large workload", [tip, "<a href='help://workload'>About workload estimates</a>"],
                          "Large workload")
        if st == "warnings":
            d = self.count_detail
            notes = []
            if d["skipped"]:
                k = d["skipped"]
                notes.append(f"{k:,} combination{'s' if k != 1 else ''} skipped: variable values giving negative "
                             "amounts or fewer than two elements.")
            if d["duplicates"]:
                k = d["duplicates"]
                notes.append(f"{k:,} duplicate composition{'s' if k != 1 else ''} removed (kept once, in the first "
                             "block that produces it).")
            return Status("info", "Parsed with warnings", "<br>".join(html.escape(x) for x in notes),
                          "Parsed with warnings", "blue")
        text, colour = STATE_TAGS[st]
        info = None
        if st == "stale":
            info = "The expression changed after the last parse. Parse expression again to update the result."
        return Status("success" if st == "parsed" else "info", text, info, text, colour)

    def primary_action(self) -> tuple[str, bool, bool]:
        """(``"parse"`` or ``"calculate"``, enabled, split) of the footer's primary button (Figma: Parse expression
        until the document is parsed; Stale adds the chevron)."""
        st = self.state()
        if st in ("parsed", "warnings", "workload") or (st == "error" and self.doc is not None and self.doc.ok
                                                       and not self.shown):
            return "calculate", self.can_calculate(), True
        if st == "parsing":
            return "parse", False, False
        if st == "stale":
            return "parse", True, True
        return "parse", st in ("ready", "editing"), False

    def can_calculate(self) -> bool:
        return self.state() in ("parsed", "warnings", "workload") and not self.counting \
            and self.count_detail is not None and self.count_detail["valid"] > 0 and not self.count_error

    def recipe(self) -> ExpressionRecipe:
        """The parsed document as a calculation recipe (generation happens in the calculation job).  Refuses a
        document that changed after its parse: the calculation never uses an outdated parse."""
        st = self.state()
        if st not in ("parsed", "warnings", "workload") or self.text() != self.parsed_text:
            raise ExpressionError("Parse the expression first." if st in ("editing", "ready", "stale")
                                  else "The expression has errors.")
        doc = self.doc
        n = doc.combinations
        if n > MAX_COMBINATIONS:
            raise RangeError(f"{n:,} combinations exceed the limit of {MAX_COMBINATIONS:,}; increase the steps.")
        merged: dict = {}
        for r in doc.block_ranges:
            for k, v in r.items():
                merged.setdefault(k, v)
        d = self.count_detail
        counts = None
        if d is not None and self.text() == self.parsed_text:
            # the Parse count of this very document: lets the calculation skip its duplicate plan when there are
            # none (core.jobs.CalculationJob._run_expression_direct)
            counts = (d["valid"], d["skipped"], d["duplicates"], d["combinations"],
                      tuple((i, b[2]) for i, b in enumerate(d["blocks"]) if b[2]))
        return ExpressionRecipe(tuple(doc.expressions), tuple(merged.items()), doc.text,
                                tuple(tuple(r.items()) for r in doc.block_ranges), counts)

    def compositions(self):
        return self.recipe()()[1:]

    # ------------------------------------------------------------------ periodic table
    def _expression_lines(self) -> list[int]:
        """Line numbers of the expression (first) line of every block."""
        return [i for i, r in enumerate(line_roles(self.text().split("\n"))) if r == ROLE_EXPRESSION]

    def _replace_line(self, i: int, new: str) -> None:
        """Replace document line ``i`` as one undo step, keeping the rest of the text (and the memory)."""
        blk = self.edit.document().findBlockByNumber(i)
        c = QTextCursor(blk)
        c.beginEditBlock()
        c.setPosition(blk.position())
        c.setPosition(blk.position() + len(blk.text()), QTextCursor.MoveMode.KeepAnchor)
        c.insertText(new)
        c.endEditBlock()

    def add_element(self, el: str):
        """Append an element to the expression line of the last block (never to a range line)."""
        exprs = self._expression_lines()
        if not exprs:
            self.edit.setPlainText(el)
            self._seed_memory()
            return
        i = exprs[-1]
        line = self.text().split("\n")[i]
        if re.search(rf"{el}(?![a-z])", line):
            return
        self._replace_line(i, line.rstrip() + el)

    def remove_element(self, el: str):
        lines = self.text().split("\n")
        for i in self._expression_lines():
            new = re.sub(rf"{el}(?![a-z])(\{{[^}}]*\}}|_\([^)]*\)|_\{{[^}}]*\}}|[0-9.]*[a-z0-9_+\-*/.]*)?", "",
                         lines[i])
            new = new.replace("()", "")
            if new != lines[i]:
                self._replace_line(i, new)

    def clear(self):
        self.edit.clear()
        self.parse()


class _ListTitle(QWidget):
    """Carbon contained-list title row (32 px): "Parsed expressions" (heading-compact-01) and a gray 18 px count
    tag on the right; a 1 px ``list-divider`` under it."""

    def __init__(self, title: str, count: str):
        super().__init__()
        self.title, self.count = title, count
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{title}: {count}")

    def paintEvent(self, _e):
        from PySide6.QtGui import QFontMetrics
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font(HEADING_COMPACT_01))
        p.setPen(QColor(t("text-primary")))
        p.drawText(QRectF(16, 0, self.width() - 32, 32), int(Qt.AlignmentFlag.AlignVCenter), self.title)
        f = font(LABEL_01)
        w = QFontMetrics(f).horizontalAdvance(self.count) + 16
        r = QRectF(self.width() - 16 - w, 7, w, 18)
        crisp.fill_pill(p, r, t("tag-gray-bg"))
        p.setFont(f)
        p.setPen(QColor(t("tag-gray-fg")))
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self.count)
        crisp.hline(p, 0, self.width(), self.height() - 1, t("list-divider"), 1)
        p.end()


class _Rule(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(1)

    def paintEvent(self, _e):
        p = QPainter(self)
        crisp.hline(p, 0, self.width(), 0, t("list-divider"), 1)
        p.end()


class _PreviewTable(QWidget):
    """Carbon structured list (Figma Parametric parsed: 34 px header row, 36 px rows, five equal columns, text at
    14 px into each column, 1 px ``list-row-border`` under every row)."""

    HEADERS = ("Element", "At. ratio", "at.%", "wt.%", "Mass")
    HEAD_H, ROW_H = 34, 36

    def __init__(self, rows: list[tuple[str, dict]]):
        super().__init__()
        self.rows = [(el, f"{v['ratio']:.4f}", f"{v['at']:.4f}", f"{v['wt']:.4f}", f"{v['mass']:.4f}")
                     for el, v in rows]
        self.setFixedHeight(self.HEAD_H + self.ROW_H * len(self.rows))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Composition preview")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        n = len(self.HEADERS)
        cw = self.width() / n
        p.setFont(font(HEADING_COMPACT_01))
        p.setPen(QColor(t("text-primary")))
        for i, h in enumerate(self.HEADERS):
            p.drawText(QRectF(i * cw + 14, 0, cw - 14, self.HEAD_H), int(Qt.AlignmentFlag.AlignVCenter), h)
        crisp.hline(p, 0, self.width(), self.HEAD_H - 1, t("list-row-border"), 1)
        p.setFont(font(BODY_COMPACT_01))
        for r, row in enumerate(self.rows):
            y = self.HEAD_H + r * self.ROW_H
            p.setPen(QColor(t("text-secondary")))
            for i, v in enumerate(row):
                p.drawText(QRectF(i * cw + 14, y, cw - 14, self.ROW_H), int(Qt.AlignmentFlag.AlignVCenter), v)
            crisp.hline(p, 0, self.width(), y + self.ROW_H - 1, t("list-row-border"), 1)
        p.end()


def _range_span(r, short: bool = False) -> str:
    """``0 → 0.2`` for an inclusive range (Figma), the declaration's comparisons for a strict one."""
    if r.min_inclusive and r.max_inclusive:
        return f"{_fmt(r.minimum)} → {_fmt(r.maximum)}"
    return r.bounds_text()


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
