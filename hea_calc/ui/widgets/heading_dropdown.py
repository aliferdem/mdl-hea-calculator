"""Composition setup heading dropdown - the panel title *is* the mode selector (Figma "Composition setup",
Mode=Single / Space / Expression, nodes 392:69182 / 392:69349 / 392:69514; open state in 392:69349 and the main
window Empty state 501:39130).

Trigger (40 px, Carbon dropdown "ghost" heading): body-compact-01 ``text-primary`` label at x = 16, a 16 px
chevron 8 px after the label, 16 px right padding (the width hugs the label: "Single composition" = 187 px).
Rest: transparent on the panel; hover ``layer-hover-01``; open: 2 px ``focus`` frame inside, chevron up; keyboard
focus: the same 2 px frame.

List (one popup window painting both levels, so hover and keyboard never leave one widget): 40 px Carbon dropdown
rows on ``layer-02`` with the menu elevation, ``text-secondary`` labels (``text-primary`` when highlighted), 1 px
``border-subtle-02`` dividers inset 16 px, hidden next to a highlighted row.  A row with children (Composition
space) shows a caret and opens its sub-list to the right, 1 px apart, top-aligned with the row + 1 px (Figma
x = 252, y = 81): At. ratio / at.% / wt.% / Mass with a checkmark on the current basis.

Keyboard: Enter / Space / Down open; Up / Down / Home / End move; Right or Enter on a parent enters its sub-list;
Left or Esc in the sub-list returns to the parent; Enter chooses; Esc closes and refocuses the trigger.

``chosen(path)`` fires with the chosen value path - ``("single",)``, ``("sweep",)`` (keep the basis) or
``("sweep", "at")``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget

from .. import crisp, icons
from ..theme import BODY_COMPACT_01, FOCUS_WIDTH, HAIRLINE, font, t
from .listbox import SHADOW, paint_shadow

TRIGGER_H = 40
ROW_H = 40
PAD_X = 16
ICON = 16
ICON_GAP = 8
SUB_GAP = 1


def snap(p: QPainter, rect: QRectF) -> QRectF:
    """``rect`` moved to whole device pixels (an icon's strokes then fall on the same pixels as the text's)."""
    dpr = p.device().devicePixelRatioF() or 1.0
    return QRectF(round(rect.x() * dpr) / dpr, round(rect.y() * dpr) / dpr, rect.width(), rect.height())


def paint_like_text(p: QPainter, name: str, rect: QRectF, text_token: str) -> None:
    """A chevron / caret / checkmark in the colour of the label it belongs to (``text_token``, state-aware), drawn
    twice: a 1 px diagonal stroke anti-aliases to ~70 % coverage, so a single pass looked lighter than the label
    beside it (light theme, 100 %: #3b3b3b against #161616).  The token is the label's own - never a parallel icon
    token - so the two can never drift apart."""
    for _ in range(2):
        icons.paint(p, name, rect, color=t(text_token))


@dataclass
class Node:
    value: object
    label: str
    children: list["Node"] = field(default_factory=list)


class HeadingDropdown(QAbstractButton):
    """See module docstring.  ``tree`` is a list of :class:`Node`; ``path`` the current value path."""

    chosen = Signal(tuple)

    def __init__(self, tree: list[Node], path: tuple, label: str = "", parent=None, accessible: str = ""):
        super().__init__(parent)
        self.tree = tree
        self.path = tuple(path)
        self.label = label
        self.popup: CascadePopup | None = None
        self._open = False
        self.closed_at = 0.0
        self.setFixedHeight(TRIGGER_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(accessible or "Mode")
        self.setFont(font(BODY_COMPACT_01))
        self.clicked.connect(self.open_menu)
        self._fit()

    # -------------------------------------------------------------- value
    def set_state(self, path: tuple, label: str) -> None:
        self.path = tuple(path)
        self.label = label
        self.setAccessibleDescription(label)
        self._fit()
        self.update()

    def _fit(self) -> None:
        w = PAD_X + QFontMetrics(font(BODY_COMPACT_01)).horizontalAdvance(self.label) + ICON_GAP + ICON + PAD_X
        self.setFixedWidth(int(w))

    # QLabel-like subset: the shell aligns its status text with the title text (AppHeader.align_status_to)
    def text(self) -> str:
        return self.label

    def indent(self) -> int:
        return PAD_X

    def text_width(self) -> int:
        return QFontMetrics(font(BODY_COMPACT_01)).horizontalAdvance(self.label)

    def is_open(self) -> bool:
        return self._open

    # -------------------------------------------------------------- popup
    def open_menu(self) -> None:
        if self._open or time.monotonic() - self.closed_at < 0.3:
            return
        self._open = True
        self.update()
        self.popup = CascadePopup(self, self.tree, self.path)
        self.popup.chosen.connect(self._chosen)
        self.popup.closed.connect(self._closed)
        self.popup.show()
        self.popup.setFocus(Qt.FocusReason.PopupFocusReason)

    def _chosen(self, path: tuple) -> None:
        self.chosen.emit(tuple(path))

    def _closed(self) -> None:
        self._open = False
        self.popup = None
        self.closed_at = time.monotonic()
        self.update()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.closed_at = 0.0
            self.open_menu()
            return
        super().keyPressEvent(e)

    # -------------------------------------------------------------- paint
    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(self.width(), TRIGGER_H)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        enabled = self.isEnabled()
        if enabled and self.underMouse() and not self._open:
            crisp.fill_rect(p, r, t("layer-hover-01"))
        p.setFont(font(BODY_COMPACT_01))
        from PySide6.QtGui import QColor
        text_token = "text-primary" if enabled else "text-disabled"
        p.setPen(QColor(t(text_token)))
        tw = self.text_width()
        p.drawText(QRectF(PAD_X, 0, tw + 1, r.height()), int(Qt.AlignmentFlag.AlignVCenter), self.label)
        ic = QRectF(PAD_X + tw + ICON_GAP, (r.height() - ICON) / 2, ICON, ICON)
        ic = snap(p, ic)
        if self._open:
            p.save()
            p.translate(ic.center())
            p.rotate(180)
            p.translate(-ic.center())
        paint_like_text(p, "chevron_down", ic, text_token)        # the label's own state token (primary / disabled)
        if self._open:
            p.restore()
        if self._open or (self.hasFocus() and enabled):
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()


class CascadePopup(QWidget):
    """The open list of a :class:`HeadingDropdown` (main level + one sub-level), see the module docstring."""

    chosen = Signal(tuple)
    closed = Signal()

    def __init__(self, trigger: HeadingDropdown, tree: list[Node], path: tuple):
        super().__init__(trigger.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("CascadePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setAccessibleName(trigger.accessibleName())
        self.trigger = trigger
        self.tree = tree
        self.path = tuple(path)
        fm = QFontMetrics(font(BODY_COMPACT_01))
        caret = ICON + ICON_GAP
        natural = max((PAD_X + fm.horizontalAdvance(n.label) + ICON_GAP + caret + PAD_X for n in tree), default=0)
        self.main_w = max(trigger.width(), natural)
        self.sub_w = 0
        for n in tree:
            if n.children:
                self.sub_w = max(self.sub_w, max(PAD_X + fm.horizontalAdvance(c.label) + 16 + ICON + PAD_X
                                                 for c in n.children))
        # active row per level; the open parent (sub-list shown) follows the hover / keyboard
        cur = self._index(tree, path[0] if path else None)
        self.active = [cur if cur >= 0 else 0, -1]
        self.level = 0
        self.keyboard = False
        self.hover: tuple[int, int] | None = None
        self.open_parent = -1
        self._set_parent(self.active[0])        # the current mode's sub-list is open at once (Figma 392:69349)
        self._place()

    # -------------------------------------------------------------- model
    @staticmethod
    def _index(nodes, value) -> int:
        for i, n in enumerate(nodes):
            if n.value == value:
                return i
        return -1

    def sub_nodes(self) -> list[Node]:
        return self.tree[self.open_parent].children if 0 <= self.open_parent < len(self.tree) else []

    def is_current(self, level: int, i: int) -> bool:
        if level == 0:
            return bool(self.path) and self.tree[i].value == self.path[0] and not self.tree[i].children
        sub = self.sub_nodes()
        return len(self.path) > 1 and self.tree[self.open_parent].value == self.path[0] \
            and sub[i].value == self.path[1]

    # -------------------------------------------------------------- geometry (local coordinates)
    def _place(self) -> None:
        g = self.trigger.mapToGlobal(QPoint(0, self.trigger.height()))
        h = max(len(self.tree), 1 + max((len(n.children) for n in self.tree), default=0)) * ROW_H + ROW_H
        w = self.main_w + SUB_GAP + self.sub_w
        self.setFixedSize(w + 2 * SHADOW, h + 2 * SHADOW)
        screen = (QApplication.screenAt(g) or QApplication.primaryScreen()).availableGeometry()
        x = min(max(screen.left(), g.x() - SHADOW), screen.right() - self.width())
        self.move(x, g.y() - SHADOW)

    def main_rect(self) -> QRect:
        return QRect(SHADOW, SHADOW, self.main_w, len(self.tree) * ROW_H)

    def row_rect(self, level: int, i: int) -> QRect:
        if level == 0:
            return QRect(SHADOW, SHADOW + i * ROW_H, self.main_w, ROW_H)
        top = SHADOW + self.open_parent * ROW_H + 1
        return QRect(SHADOW + self.main_w + SUB_GAP, top + i * ROW_H, self.sub_w, ROW_H)

    def sub_rect(self) -> QRect | None:
        sub = self.sub_nodes()
        if not sub:
            return None
        r0 = self.row_rect(1, 0)
        return QRect(r0.x(), r0.y(), self.sub_w, len(sub) * ROW_H)

    def hit(self, pos: QPoint) -> tuple[int, int] | None:
        for i in range(len(self.tree)):
            if self.row_rect(0, i).contains(pos):
                return (0, i)
        for i in range(len(self.sub_nodes())):
            if self.row_rect(1, i).contains(pos):
                return (1, i)
        return None

    # -------------------------------------------------------------- choosing
    def _set_parent(self, i: int) -> None:
        i = i if 0 <= i < len(self.tree) and self.tree[i].children else -1
        if i != self.open_parent:
            self.open_parent = i
            sub = self.sub_nodes()
            cur = self._index(sub, self.path[1]) if len(self.path) > 1 and i >= 0 \
                and self.tree[i].value == self.path[0] else -1
            self.active[1] = cur if cur >= 0 else (0 if sub else -1)

    def choose(self, level: int, i: int) -> None:
        if level == 0:
            path = (self.tree[i].value,)
        else:
            path = (self.tree[self.open_parent].value, self.sub_nodes()[i].value)
        self.chosen.emit(path)
        self.close()

    # -------------------------------------------------------------- input
    def mouseMoveEvent(self, e):
        h = self.hit(e.position().toPoint())
        if h != self.hover:
            self.hover = h
            self.keyboard = False
            if h is not None:
                lv, i = h
                self.level = lv
                self.active[lv] = i
                if lv == 0:
                    self._set_parent(i)
            self.update()

    def leaveEvent(self, _e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        if not self.rect().contains(e.position().toPoint()) or self.hit(e.position().toPoint()) is None:
            self.close()                    # a press outside both lists (incl. the transparent margin)
            return
        e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        h = self.hit(e.position().toPoint())
        if h is not None:
            self.choose(*h)

    def _step(self, d: int) -> None:
        n = len(self.tree) if self.level == 0 else len(self.sub_nodes())
        if n == 0:
            return
        i = self.active[self.level]
        i = (i + d) % n if i >= 0 else (0 if d > 0 else n - 1)
        self.active[self.level] = i
        if self.level == 0:
            self._set_parent(i)
        self.keyboard = True
        self.update()

    def keyPressEvent(self, e):
        k = e.key()
        lv = self.level
        if k == Qt.Key.Key_Down:
            self._step(1)
        elif k == Qt.Key.Key_Up:
            self._step(-1)
        elif k == Qt.Key.Key_Home:
            self.active[lv] = -1
            self._step(1)
        elif k == Qt.Key.Key_End:
            self.active[lv] = -1
            self._step(-1)
        elif k == Qt.Key.Key_Right and lv == 0 and self.sub_nodes():
            self.level = 1
            self.keyboard = True
            self.update()
        elif k in (Qt.Key.Key_Left,) and lv == 1:
            self.level = 0
            self.keyboard = True
            self.update()
        elif k == Qt.Key.Key_Escape:
            if lv == 1:
                self.level = 0
                self.keyboard = True
                self.update()
            else:
                self.close()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            i = self.active[lv]
            if i < 0:
                return
            if lv == 0 and self.tree[i].children and k != Qt.Key.Key_Space:
                self._set_parent(i)
                self.level = 1
                self.keyboard = True
                self.update()
                return
            self.choose(lv, i)
        elif k == Qt.Key.Key_Tab:
            self.close()
        else:
            super().keyPressEvent(e)

    # -------------------------------------------------------------- paint
    def _paint_rows(self, p: QPainter, level: int, nodes: list[Node]) -> None:
        from PySide6.QtGui import QColor
        hl = []
        for i in range(len(nodes)):
            hot = (self.hover == (level, i)) or (self.keyboard and self.level == level and self.active[level] == i)
            parent_open = level == 0 and i == self.open_parent
            hl.append(hot or parent_open or self.is_current(level, i))
        for i, n in enumerate(nodes):
            r = self.row_rect(level, i)
            hot = (self.hover == (level, i)) or (self.keyboard and self.level == level and self.active[level] == i)
            current = self.is_current(level, i)
            parent_open = level == 0 and i == self.open_parent
            if current:
                crisp.fill_rect(p, r, t("layer-selected-hover-02" if hot else "layer-selected-02"))
            elif hot or parent_open:
                crisp.fill_rect(p, r, t("layer-hover-02"))
            if i > 0 and not (hl[i] or hl[i - 1]):
                crisp.hline(p, r.left() + PAD_X, r.right() + 1 - PAD_X, r.top(), t("border-subtle-02"), HAIRLINE)
            on = hot or current or parent_open
            text_token = "text-primary" if on else "text-secondary"
            p.setPen(QColor(t(text_token)))
            p.setFont(font(BODY_COMPACT_01))
            p.drawText(QRectF(r.left() + PAD_X, r.top(), r.width() - 2 * PAD_X - ICON, r.height()),
                       int(Qt.AlignmentFlag.AlignVCenter), n.label)
            ic = snap(p, QRectF(r.right() + 1 - PAD_X - ICON, r.top() + (r.height() - ICON) / 2, ICON, ICON))
            # the submenu caret and the checkmark follow their label's state (unselected text-secondary, selected /
            # hovered / highlighted text-primary); they used icon-primary in every state
            if n.children:
                paint_like_text(p, "caret_right", ic, text_token)
            elif current and level == 1:
                paint_like_text(p, "checkmark", ic, text_token)
            if self.keyboard and self.level == level and self.active[level] == i:
                crisp.frame(p, r, FOCUS_WIDTH, t("focus"))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        main = self.main_rect()
        sub = self.sub_rect()
        paint_shadow(p, main)
        if sub is not None:
            paint_shadow(p, sub)
        crisp.fill_rect(p, main, t("layer-02"))
        if sub is not None:
            crisp.fill_rect(p, sub, t("layer-02"))
        self._paint_rows(p, 0, self.tree)
        if sub is not None:
            self._paint_rows(p, 1, self.sub_nodes())
        p.end()

    def closeEvent(self, e):
        super().closeEvent(e)
        self.closed.emit()
        try:
            self.trigger.setFocus(Qt.FocusReason.PopupFocusReason)
        except RuntimeError:
            pass
