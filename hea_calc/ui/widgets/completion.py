"""Completion list of the expression editor (2026-10-28): a compact Carbon list (``layer-02`` surface, 32 px rows,
``layer-selected-02`` current row, the candidate in the code font and its kind in ``text-secondary``) shown under
the caret.  It never takes the keyboard focus - the editor keeps typing and forwards Up / Down / Tab / Enter /
Escape (``CodeEditor.keyPressEvent``); a click on a row accepts it.  What it lists comes from
:func:`hea_calc.core.expression_complete.complete`."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from .. import crisp
from ..theme import BODY_COMPACT_01, HAIRLINE, font, t

ROW_H = 32
PAD_X = 16
GAP = 24
MAX_ROWS = 8


class CompletionPopup(QWidget):
    accepted = Signal(int)                 # index of the chosen candidate

    def __init__(self, owner: QWidget):
        super().__init__(owner, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("CompletionPopup")
        self.setAccessibleName("Suggestions")
        self.items: list = []
        self.index = 0
        self.top = 0
        self.engaged = False               # the user moved through the list (Enter then accepts)
        self.code_font = None

    def set_items(self, items: list, code_font) -> None:
        self.items = list(items)
        self.index = 0
        self.top = 0
        self.engaged = False
        self.code_font = code_font
        fm, fd = QFontMetrics(code_font), QFontMetrics(font(BODY_COMPACT_01))
        w = max((fm.horizontalAdvance(c.label) + GAP + fd.horizontalAdvance(c.detail) for c in self.items), default=0)
        self.resize(min(max(160, w + 2 * PAD_X), 520), ROW_H * min(MAX_ROWS, len(self.items)))
        self.setAccessibleDescription(", ".join(c.label for c in self.items[:MAX_ROWS]))
        self.update()

    def current(self):
        return self.items[self.index] if self.items else None

    def move_selection(self, step: int) -> None:
        if not self.items:
            return
        self.index = (self.index + step) % len(self.items)
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + MAX_ROWS:
            self.top = self.index - MAX_ROWS + 1
        self.engaged = True
        self.update()

    def place_under(self, global_caret: QRect) -> None:
        """Under the caret's line; above it when there is no room below on the screen."""
        scr = QGuiApplication.screenAt(global_caret.center()) or QGuiApplication.primaryScreen()
        avail = scr.availableGeometry()
        x = min(max(avail.left(), global_caret.left()), avail.right() + 1 - self.width())
        y = global_caret.bottom() + 1
        if y + self.height() > avail.bottom() + 1:
            y = global_caret.top() - self.height()
        self.move(QPoint(x, y))

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        crisp.fill_rect(p, r, t("layer-02"))
        fd = font(BODY_COMPACT_01)
        for row, i in enumerate(range(self.top, min(len(self.items), self.top + MAX_ROWS))):
            c = self.items[i]
            rr = QRectF(0, row * ROW_H, r.width(), ROW_H)
            if i == self.index:
                crisp.fill_rect(p, rr, t("layer-selected-02"))
            p.setFont(self.code_font)
            p.setPen(QColor(t("text-primary")))
            p.drawText(rr.adjusted(PAD_X, 0, -PAD_X, 0), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       c.label)
            p.setFont(fd)
            p.setPen(QColor(t("text-secondary")))
            p.drawText(rr.adjusted(PAD_X, 0, -PAD_X, 0), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       c.detail)
        crisp.frame(p, r, HAIRLINE, t("border-subtle-02"))
        p.end()

    def mousePressEvent(self, e):
        i = self.top + int(e.position().y()) // ROW_H
        if 0 <= i < len(self.items):
            self.index = i
            self.accepted.emit(i)
        e.accept()
