"""Expression code editor - the text surface of Expression mode (Figma "Expression bases" 584:51933: Empty,
Draft, Error, Stale, Fixed / Parametric / Batch parsed).

Geometry (457 px panel): the editor's 1 px ``layer-accent-01`` top rule; 19 px rows of IBM Plex Mono 14 (a system
monospace stands in when Plex Mono is not installed - the row height stays 19 px: the document uses a fixed line
height); a gutter with the line number at x = 16 (``syntax-line-number``, the caret's line
``syntax-line-number-active``) and the code at the gutter's end (x = 50 for one-digit line numbers); the caret's
line is a full-width ``syntax-line-active`` band; the caret is 2 px wide in ``syntax-caret``; a 9 px overview strip
on the right edge marks every line with a diagnostic (``syntax-overview-error``, 9 × 19), framed left and bottom in
``layer-accent-01`` while there are diagnostics.

Colours come from :class:`ExpressionHighlighter`, which colours the tokens of :mod:`hea_calc.core.expression_lexer`
(the parser's own reading of the text): elements ``syntax-element``, numbers ``syntax-number``, variables
``syntax-variable``, option keywords ``syntax-keyword``, operators / comparisons / ``=`` ``syntax-operator``,
brackets and commas ``syntax-punctuation``.  Diagnostics never recolour tokens: they are wavy ``syntax-error``
underlines painted under their column span (a span past the end of a line marks something missing there).

Declaration lines (the range lines of a block) carry a painted 1 px ``syntax-indent-guide`` in the gutter,
``GUIDE_GAP`` (8 px, Carbon spacing-03) before the code column, from the block's first declaration to its last - the
guide is not text (2026-10-28: formerly 4 px *into* the code column, where it touched or crossed the first
character).

The editor is plain text only (pasted rich text arrives as text), keeps Qt's undo / redo, selection and clipboard,
``Tab`` moves the focus (Carbon text area), ``Enter`` on a declaration line keeps its indentation, ``Ctrl+Enter``
asks for a parse.

Completion (2026-10-28, :mod:`hea_calc.core.expression_complete`): typing an option keyword or a long variable name
shows a suggestion list under the caret; ``Ctrl+Space`` asks for every suggestion of the context (element symbols,
range templates).  Up / Down move through the list, ``Tab`` accepts, ``Enter`` accepts once the list has been
navigated (otherwise it is a new line, as always), ``Escape`` dismisses; anything else keeps typing.  Only the word
being typed is replaced (one undo step); text composed by an input method never opens the list.  It never scrolls vertically itself: its owner gives it its content height (or more) inside the
panel's scroll area; it scrolls horizontally for long lines (following the caret; no bar).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QKeySequence, QPainter, QPainterPath, QPen,
                           QShortcut, QSyntaxHighlighter, QTextBlockFormat, QTextCharFormat, QTextCursor,
                           QTextOption)
from PySide6.QtWidgets import QFrame, QTextEdit, QWidget

from ...core import expression_lexer as L
from .. import crisp
from ..theme import HAIRLINE, THEME, t

LINE_H = 19
FONT_PX = 14
GUTTER_PAD = 16          # line number x
GUTTER_FILL = 26         # the two filler glyphs between the number and the code (Figma "ㅤㅤ")
RULER_W = 9
GUIDE_GAP = 8            # the indentation guide: 8 px (spacing-03) of clear space before the code column
MONO_FAMILIES = ("IBM Plex Mono", "Cascadia Mono", "Consolas", "Courier New")

TOKEN_COLOURS = {L.ELEMENT: "syntax-element", L.NUMBER: "syntax-number", L.VARIABLE: "syntax-variable",
                 L.KEYWORD: "syntax-keyword", L.OPERATOR: "syntax-operator", L.COMPARISON: "syntax-operator",
                 L.PUNCTUATION: "syntax-punctuation", L.INVALID: "syntax-text", L.SPACE: "syntax-text"}

_MONO: str | None = None


def mono_family() -> str:
    global _MONO
    if _MONO is None:
        fams = set(QFontDatabase.families())
        _MONO = next((f for f in MONO_FAMILIES if f in fams), "monospace")
    return _MONO


def mono_font() -> QFont:
    f = QFont(mono_family())
    f.setPixelSize(FONT_PX)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


# block states: 0 = blank line (or before the first line), 1 = a non-blank line
class ExpressionHighlighter(QSyntaxHighlighter):
    """Token colours of an expression document (see the module docstring); one lexer for all lines."""

    def __init__(self, document, datasets):
        super().__init__(document)
        self.datasets = datasets
        self._formats: dict[str, QTextCharFormat] = {}

    def _fmt(self, token: str) -> QTextCharFormat:
        f = self._formats.get(token)
        if f is None:
            f = QTextCharFormat()
            f.setForeground(QColor(t(token)))
            self._formats[token] = f
        return f

    def theme_changed(self) -> None:
        self._formats.clear()
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        blank = not text.strip()
        prev = self.previousBlockState()
        self.setCurrentBlockState(0 if blank else 1)
        if blank:
            return
        role = L.ROLE_DECLARATION if prev == 1 else L.ROLE_EXPRESSION
        for tok in L.lex_line(text, role, self.datasets):
            if tok.kind == L.SPACE:
                continue
            self.setFormat(tok.start, tok.end - tok.start, self._fmt(TOKEN_COLOURS.get(tok.kind, "syntax-text")))


def line_role(block) -> str:
    """Role of a QTextBlock from the highlighter state of the block above (see ExpressionHighlighter)."""
    if not block.text().strip():
        return L.ROLE_BLANK
    prev = block.previous()
    return L.ROLE_DECLARATION if prev.isValid() and prev.text().strip() else L.ROLE_EXPRESSION


class _Side(QWidget):
    """Gutter (line numbers) or overview strip - painted by the editor."""

    def __init__(self, editor: "CodeEditor", kind: str):
        super().__init__(editor)
        self.editor = editor
        self.kind = kind
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, kind == "ruler")

    def paintEvent(self, _e):
        p = QPainter(self)
        if self.kind == "gutter":
            self.editor.paint_gutter(p, self)
        else:
            self.editor.paint_ruler(p, self)
        p.end()

    def mousePressEvent(self, e):
        # a click in the gutter puts the caret at the start of that line (as code editors do)
        if self.kind == "gutter":
            blk = self.editor.block_at_y(int(e.position().y()))
            if blk is not None:
                c = self.editor.textCursor()
                c.setPosition(blk.position())
                self.editor.setTextCursor(c)
                self.editor.setFocus(Qt.FocusReason.MouseFocusReason)


class CodeEditor(QTextEdit):
    """See module docstring.  ``diagnostics`` are :class:`~hea_calc.core.expression_doc.Diagnostic` objects;
    :meth:`set_diagnostics` shows them (the owner decides which ones are shown)."""

    parse_requested = Signal()

    def __init__(self, datasets, parent=None):
        super().__init__(parent)
        self.setObjectName("CodeEditor")
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setWordWrapMode(QTextOption.WrapMode.NoWrap)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTabChangesFocus(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # long lines scroll with the caret (and Shift+wheel); a bar would take a row's height from the editor
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        from .scroll import thin_scrollbars
        thin_scrollbars(self)
        self.setCursorWidth(2)
        self.setFont(mono_font())
        self.document().setDefaultFont(mono_font())
        self.document().setDocumentMargin(0)
        self.viewport().setAutoFillBackground(False)
        self.setAccessibleName("Expression")
        self.setPlaceholderText("e.g. (FeCoNi)1-x(AlTi)x")
        self.diagnostics: list = []
        self.datasets = datasets
        self.highlighter = ExpressionHighlighter(self.document(), datasets)
        from .completion import CompletionPopup
        self.completion = None
        self.popup = CompletionPopup(self)
        self.popup.accepted.connect(self._accept_index)
        self.gutter = _Side(self, "gutter")
        self.ruler = _Side(self, "ruler")
        self._apply_line_height()
        self._sync_margins()
        self._sync_palette()
        self.document().blockCountChanged.connect(lambda _n: self._sync_margins())
        self.cursorPositionChanged.connect(self._refresh_lines)
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self.gutter.update())
        THEME.changed.connect(self._theme_changed)
        from .menu import carbon_context_menu
        carbon_context_menu(self)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.parse_requested.emit)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.parse_requested.emit)

    # -------------------------------------------------------------- text / layout
    def setPlainText(self, text: str) -> None:            # noqa: N802 - Qt API
        super().setPlainText(text)
        self._apply_line_height()

    def _apply_line_height(self) -> None:
        """Every block gets the fixed 19 px line height.  ``setPlainText`` resets the undo stack, so the format
        change made here is not an undo step; typed / pasted lines inherit it from the block they split."""
        doc = self.document()
        undo = doc.isUndoRedoEnabled()
        doc.setUndoRedoEnabled(False)
        c = QTextCursor(doc)
        c.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(LINE_H, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        c.mergeBlockFormat(fmt)
        doc.setUndoRedoEnabled(undo)

    def insertFromMimeData(self, source):                  # noqa: N802 - Qt API: plain text, fixed rows
        if source.hasText():
            c = self.textCursor()
            c.insertText(source.text().replace("\r\n", "\n").replace("\r", "\n"))
            self.setTextCursor(c)
            return
        super().insertFromMimeData(source)

    def char_width(self) -> float:
        return QFontMetricsF(mono_font()).horizontalAdvance("0")

    def gutter_width(self) -> int:
        digits = max(1, len(str(max(1, self.document().blockCount()))))
        return int(round(GUTTER_PAD + digits * self.char_width() + GUTTER_FILL))

    def _sync_margins(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, RULER_W, 0)
        self._place_sides()

    def _place_sides(self) -> None:
        cr = self.contentsRect()
        self.gutter.setGeometry(cr.left(), cr.top(), self.gutter_width(), cr.height())
        self.ruler.setGeometry(cr.right() + 1 - RULER_W, cr.top(), RULER_W, cr.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_sides()

    def content_height(self) -> int:
        return max(1, self.document().blockCount()) * LINE_H

    def sizeHint(self) -> QSize:
        return QSize(400, self.content_height())

    def _sync_palette(self) -> None:
        pal = self.palette()
        pal.setColor(pal.ColorRole.Base, QColor(0, 0, 0, 0))
        pal.setColor(pal.ColorRole.Text, QColor(t("syntax-text")))
        pal.setColor(pal.ColorRole.PlaceholderText, QColor(t("text-placeholder")))
        pal.setColor(pal.ColorRole.Highlight, QColor(t("highlight")))
        pal.setColor(pal.ColorRole.HighlightedText, QColor(t("text-primary")))
        self.setPalette(pal)
        self.viewport().setPalette(pal)

    def _theme_changed(self, *_):
        self._sync_palette()
        self.highlighter.theme_changed()
        self.viewport().update()
        self.gutter.update()
        self.ruler.update()

    # -------------------------------------------------------------- completion
    def show_completion(self, explicit: bool = False) -> bool:
        """Open (or refresh) the suggestion list for the caret; hide it when the context has none."""
        from ...core.expression_complete import complete
        c = self.textCursor()
        if c.hasSelection() or self.isReadOnly():
            self.hide_completion()
            return False
        comp = complete(self.toPlainText(), c.position(), self.datasets, explicit=explicit)
        if comp is None or not comp.candidates:
            self.hide_completion()
            return False
        self.completion = comp
        self.popup.set_items(comp.candidates, mono_font())
        r = self.cursorRect(c)
        top_left = self.viewport().mapToGlobal(r.topLeft())
        self.popup.place_under(QRect(top_left.x(), top_left.y(), max(1, r.width()), LINE_H))
        self.popup.show()
        return True

    def hide_completion(self) -> None:
        self.completion = None
        if self.popup.isVisible():
            self.popup.hide()

    def completion_visible(self) -> bool:
        return self.popup.isVisible() and self.completion is not None

    def _accept_index(self, i: int) -> None:
        self.popup.index = i
        self.accept_completion()

    def accept_completion(self) -> bool:
        """Replace the word being typed by the current suggestion (one undo step)."""
        comp, cand = self.completion, self.popup.current()
        self.hide_completion()
        if comp is None or cand is None:
            return False
        blk = self.document().findBlockByNumber(comp.line)
        if not blk.isValid():
            return False
        c = QTextCursor(blk)
        c.setPosition(blk.position() + comp.start)
        c.setPosition(blk.position() + min(comp.end, len(blk.text())), QTextCursor.MoveMode.KeepAnchor)
        c.insertText(cand.text)
        self.setTextCursor(c)
        self.ensureCursorVisible()
        return True

    def event(self, e):
        # Tab normally moves the focus (setTabChangesFocus) before keyPressEvent sees it: with the list open it
        # accepts the suggestion instead
        if e.type() == e.Type.KeyPress and e.key() == Qt.Key.Key_Tab and self.completion_visible()                 and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.accept_completion()
            return True
        return super().event(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.hide_completion()

    def inputMethodEvent(self, e):                       # noqa: N802 - Qt API
        if e.preeditString():
            self.hide_completion()                       # composing: never interrupted by suggestions
        super().inputMethodEvent(e)

    # -------------------------------------------------------------- keyboard
    def keyPressEvent(self, e):
        mods = e.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        k = e.key()
        if self.completion_visible():
            if k in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not ctrl:
                self.popup.move_selection(-1 if k == Qt.Key.Key_Up else 1)
                return
            if (k == Qt.Key.Key_Tab and not ctrl) or (k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ctrl
                                                      and self.popup.engaged):
                self.accept_completion()
                return
            if k == Qt.Key.Key_Escape:
                self.hide_completion()
                return
        if ctrl and k == Qt.Key.Key_Space:
            self.show_completion(explicit=True)
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.hide_completion()
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            c = self.textCursor()
            blk = c.block()
            indent = ""
            if line_role(blk) == L.ROLE_DECLARATION and c.positionInBlock() > 0:
                text = blk.text()
                indent = text[:len(text) - len(text.lstrip())]
            c.insertText("\n" + indent)
            self.setTextCursor(c)
            self.ensureCursorVisible()
            return
        super().keyPressEvent(e)
        typed = e.text()
        if typed and typed.isprintable() and not ctrl and not (mods & Qt.KeyboardModifier.AltModifier):
            self.show_completion(explicit=False)          # typing: suggest when the context has a completion
        elif k == Qt.Key.Key_Backspace and self.completion_visible():
            self.show_completion(explicit=False)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp,
                   Qt.Key.Key_PageDown):
            self.hide_completion()

    # -------------------------------------------------------------- diagnostics
    def set_diagnostics(self, diags: list) -> None:
        self.diagnostics = list(diags)
        self.viewport().update()
        self.ruler.update()

    # -------------------------------------------------------------- geometry helpers
    def block_top(self, block) -> float:
        """Top of ``block`` in viewport coordinates."""
        r = self.document().documentLayout().blockBoundingRect(block)
        return r.top() - self.verticalScrollBar().value()

    def block_at_y(self, y: int):
        blk = self.document().begin()
        while blk.isValid():
            top = self.block_top(blk)
            if top <= y < top + LINE_H:
                return blk
            blk = blk.next()
        return None

    def column_x(self, block, col: int) -> float:
        """Viewport x of the left edge of column ``col`` of ``block`` (columns past the end extend in whole
        character widths)."""
        n = len(block.text())
        c = QTextCursor(block)
        c.setPosition(block.position() + min(col, n))
        x = self.cursorRect(c).left()
        if col > n:
            x += (col - n) * self.char_width()
        return float(x)

    def current_block(self):
        return self.textCursor().block()

    def _refresh_lines(self) -> None:
        self.viewport().update()
        self.gutter.update()
        self.ruler.update()

    # -------------------------------------------------------------- painting
    def paintEvent(self, e):
        p = QPainter(self.viewport())
        w = self.viewport().width()
        cur = self.current_block()
        if self.hasFocus() or not self.isReadOnly():
            crisp.fill_rect(p, QRectF(0, self.block_top(cur), w, LINE_H), t("syntax-line-active"))
        p.end()
        super().paintEvent(e)
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_squiggles(p)
        crisp.hline(p, 0, w, 0, t("layer-accent-01"), HAIRLINE)
        p.end()

    def guide_runs(self) -> list[tuple[float, float]]:
        """(top, bottom) in viewport coordinates of every run of declaration lines."""
        out = []
        blk = self.document().begin()
        run_top = None
        last = None
        while blk.isValid():
            if line_role(blk) == L.ROLE_DECLARATION:
                if run_top is None:
                    run_top = self.block_top(blk)
                last = blk
            elif run_top is not None:
                out.append((run_top, self.block_top(last) + LINE_H))
                run_top = None
            blk = blk.next()
        if run_top is not None:
            out.append((run_top, self.block_top(last) + LINE_H))
        return out

    def _paint_guides(self, p: QPainter, x: float) -> None:
        """The guides at ``x`` of the gutter (they do not scroll horizontally with the code)."""
        for top, bottom in self.guide_runs():
            crisp.fill_rect(p, QRectF(x, top, 1, bottom - top), t("syntax-indent-guide"))

    def _paint_squiggles(self, p: QPainter) -> None:
        if not self.diagnostics:
            return
        pen = QPen(QColor(t("syntax-error")), 1)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        doc = self.document()
        for d in self.diagnostics:
            blk = doc.findBlockByNumber(d.line)
            if not blk.isValid():
                continue
            x0 = self.column_x(blk, d.start)
            x1 = self.column_x(blk, max(d.end, d.start + 1))
            y = self.block_top(blk) + LINE_H - 3
            p.drawPath(wave(x0, x1, y))

    def paint_gutter(self, p: QPainter, w: QWidget) -> None:
        cur = self.current_block()
        crisp.fill_rect(p, QRectF(0, 0, w.width(), 1), t("layer-accent-01"))
        p.setFont(mono_font())
        blk = self.document().begin()
        h = w.height()
        while blk.isValid():
            top = self.block_top(blk)
            if top > h:
                break
            if top + LINE_H >= 0:
                active = blk == cur
                if active and (self.hasFocus() or not self.isReadOnly()):
                    crisp.fill_rect(p, QRectF(0, top, w.width(), LINE_H), t("syntax-line-active"))
                p.setPen(QColor(t("syntax-line-number-active" if active else "syntax-line-number")))
                p.drawText(QRectF(GUTTER_PAD, top, w.width() - GUTTER_PAD, LINE_H),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), str(blk.blockNumber() + 1))
            blk = blk.next()
        self._paint_guides(p, self.guide_x(w))
        crisp.hline(p, 0, w.width(), 0, t("layer-accent-01"), HAIRLINE)

    @staticmethod
    def guide_x(gutter: QWidget) -> int:
        """The guide's x in the gutter: ``GUIDE_GAP`` px of clear space between it and the code column."""
        return gutter.width() - GUIDE_GAP - 1

    def paint_ruler(self, p: QPainter, w: QWidget) -> None:
        cur = self.current_block()
        if self.hasFocus() or not self.isReadOnly():
            crisp.fill_rect(p, QRectF(0, self.block_top(cur), w.width(), LINE_H), t("syntax-line-active"))
        lines = sorted({d.line for d in self.diagnostics})
        doc = self.document()
        for ln in lines:
            blk = doc.findBlockByNumber(ln)
            if blk.isValid():
                crisp.fill_rect(p, QRectF(0, self.block_top(blk), w.width(), LINE_H), t("syntax-overview-error"))
        if lines:
            crisp.vline(p, 0, 0, w.height(), t("layer-accent-01"), HAIRLINE)
            crisp.hline(p, 0, w.width(), w.height() - 1, t("layer-accent-01"), HAIRLINE)
        crisp.hline(p, 0, w.width(), 0, t("layer-accent-01"), HAIRLINE)


def wave(x0: float, x1: float, y: float, amp: float = 1.5, period: float = 4.0) -> QPainterPath:
    """A wavy underline from ``x0`` to ``x1`` centred on ``y`` (Figma: 3 px tall)."""
    path = QPainterPath(QPointF(x0, y))
    n = max(1, int(math.ceil((x1 - x0) / (period / 2))))
    step = (x1 - x0) / n
    for i in range(n):
        xa = x0 + i * step
        up = -amp if i % 2 == 0 else amp
        path.quadTo(QPointF(xa + step / 2, y + 2 * up), QPointF(xa + step, y))
    return path


__all__ = ["CodeEditor", "ExpressionHighlighter", "mono_font", "line_role", "LINE_H", "RULER_W"]
