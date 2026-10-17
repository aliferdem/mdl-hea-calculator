"""Carbon v11 list box popup - the one list surface behind every Dropdown and MultiSelect.

Carbon MCP evidence (components/dropdown, components/menu, specifications): the open list is a ``$layer``
surface one step above the field it opens from (here ``layer-02`` over ``layer-01`` panels), elevated with
``box-shadow: 0 2px 6px rgba(0,0,0,.2)``; options are 32 / 40 / 48 px rows with 16 px inline padding,
``$text-secondary`` text, ``$border-subtle`` dividers inset 16 px between options; hover ``$layer-hover`` with
``$text-primary``; the selected option sits on ``$layer-selected`` with a checkmark; disabled ``$text-disabled``;
keyboard focus a 2 px ``$focus`` frame inside the option.  MultiSelect options carry a Carbon checkbox.

Behaviour (release brief sections 5-6, references ``CORRECT_RANGE_BASIS`` / ``CORRECT_SYSTEM_SIZE_DROPDOWN``):

* the list never leaves the screen: it opens below the trigger (above when there is more room there), its
  height is clamped to ``max_rows`` and to the available screen space, and it scrolls (pill scrollbar with hover);
* the mouse wheel scrolls the open list - it never changes the selection;
* Up / Down / Home / End move the active option (sections and disabled options are skipped) and scroll it into
  view; Enter / Space select (MultiSelect: toggle); Esc closes and returns focus to the trigger;
* a single-select list closes on selection; a MultiSelect applies every toggle immediately and stays open.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea, QVBoxLayout, QWidget

from .. import crisp, icons
from ..theme import BODY_COMPACT_01, FOCUS_WIDTH, HAIRLINE, LABEL_01, font, t

SHADOW = 6                      # px of painted shadow around the surface (0 2px 6px)
PAD_X = 16
CHECK = 16
CHECK_GAP = 16
SECTION_H = 32


@dataclass
class Option:
    value: object
    html: str
    enabled: bool = True
    tip: str = ""
    section: bool = False


def paint_shadow(p: QPainter, rect: QRect) -> None:
    """Carbon menu elevation ``0 2px 6px 0 rgba(0,0,0,.2)``, approximated with stacked translucent rects."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(SHADOW, 0, -1):
        a = int(0.2 * 255 * (1 - i / (SHADOW + 1)) / 3)
        p.setBrush(QColor(0, 0, 0, a))
        p.drawRoundedRect(QRectF(rect.adjusted(-i, -i + 2, i, i + 2)), i, i)
    p.restore()


def paint_checkbox(p: QPainter, rect: QRectF, checked: bool, enabled: bool = True) -> None:
    """Carbon checkbox (16 px): 1 px ``$icon-primary`` frame, checked = filled with a checkmark."""
    r = QRectF(rect.x() + 1, rect.y() + 1, 14, 14)
    if checked:
        crisp.fill_rounded(p, r, 2, t("icon-primary" if enabled else "icon-disabled"))
        p.save()
        pen_color = QColor(t("layer-02"))
        from PySide6.QtGui import QPen
        pen = QPen(pen_color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        p.setPen(pen)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPolyline([QPoint(int(r.x() + 3.5), int(r.y() + 7.5)), QPoint(int(r.x() + 6), int(r.y() + 10)),
                        QPoint(int(r.x() + 10.5), int(r.y() + 4.5))])
        p.restore()
    else:
        crisp.frame(p, r, 1, t("icon-primary" if enabled else "icon-disabled"), 2)


class _Body(QWidget):
    """The painted option rows (inside the scroll area)."""

    def __init__(self, popup: "ListPopup"):
        super().__init__()
        self.popup = popup
        self.setMouseTracking(True)
        self.hover = -1

    def sizeHint(self) -> QSize:
        return QSize(self.popup.list_width, self.popup.content_height())

    def row_rect(self, i: int) -> QRect:
        y = self.popup.row_y[i]
        return QRect(0, y, self.width(), self.popup.row_h(i))

    def row_at(self, y: int) -> int:
        for i in range(len(self.popup.options)):
            r = self.row_rect(i)
            if r.top() <= y < r.bottom() + 1:
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self.row_at(int(e.position().y()))
        if i != self.hover:
            self.hover = i
            if i >= 0 and self.popup.selectable(i):
                self.popup.active = i
                self.popup.keyboard = False
            self.update()

    def leaveEvent(self, _e):
        self.hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        i = self.row_at(int(e.position().y()))
        if i >= 0 and self.popup.selectable(i):
            self.popup.choose(i)

    def paintEvent(self, _e):
        from .dropdown import paint_html
        pop = self.popup
        p = QPainter(self)
        crisp.fill_rect(p, self.rect(), t("layer-02"))
        for i, o in enumerate(pop.options):
            r = self.row_rect(i)
            if o.section:
                p.setFont(font(LABEL_01))
                p.setPen(QColor(t("text-helper")))
                p.drawText(QRectF(PAD_X, r.top(), r.width() - 2 * PAD_X, r.height()),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), o.html)
                continue
            selected = pop.is_selected(i) and not pop.multi
            hot = o.enabled and (i == self.hover or (pop.keyboard and i == pop.active))
            if selected:
                crisp.fill_rect(p, r, t("layer-selected-hover-02" if hot else "layer-selected-02"))
            elif hot:
                crisp.fill_rect(p, r, t("layer-hover-02"))
            # divider above every option except the first, hidden next to a highlighted option
            if i > 0 and not pop.options[i - 1].section:
                prev_hl = (pop.is_selected(i - 1) and not pop.multi) or i - 1 == self.hover
                if not (selected or hot or prev_hl):
                    crisp.hline(p, PAD_X, r.width() - PAD_X, r.top(), t("border-subtle-02"), HAIRLINE)
            color = "text-disabled" if not o.enabled else ("text-primary" if (hot or selected) else "text-secondary")
            x = float(PAD_X)
            if pop.multi:
                paint_checkbox(p, QRectF(x, r.top() + (r.height() - CHECK) / 2, CHECK, CHECK), pop.is_selected(i),
                               o.enabled)
                x += CHECK + 8
            w = paint_html(p, QRectF(x, r.top(), r.width() - x - PAD_X - (0 if pop.multi else CHECK + 8),
                                     r.height()), o.html, BODY_COMPACT_01, color)
            if selected:
                cx = min(x + w + CHECK_GAP, r.width() - PAD_X - CHECK)
                icons.paint(p, "checkmark", QRectF(cx, r.top() + (r.height() - CHECK) / 2, CHECK, CHECK),
                            "icon-primary")
            if pop.keyboard and i == pop.active and o.enabled:
                crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()


class ListPopup(QWidget):
    """See module docstring.  ``selected(value)`` fires on a single-select choice, ``toggled(values)`` after
    every MultiSelect change; ``closed`` when the popup goes away."""

    selected = Signal(object)
    toggled = Signal(object)
    closed = Signal()

    def __init__(self, trigger: QWidget, options: list[Option], value=None, values=(), multi: bool = False,
                 row_height: int = 32, max_rows: int = 10, width: int | None = None):
        super().__init__(trigger.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName("ListPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAccessibleName(trigger.accessibleName() or "List")
        self.trigger = trigger
        self.options = options
        self.value = value
        self.values = list(values)
        self.multi = multi
        self.row_height = row_height
        self.keyboard = False
        self.row_y: list[int] = []
        y = 0
        for o in options:
            self.row_y.append(y)
            y += SECTION_H if o.section else row_height
        self._content_h = y
        from .dropdown import html_width
        widest = max((html_width(o.html) for o in options if not o.section), default=0)
        natural = int(PAD_X + (CHECK + 8 if multi else 0) + widest + CHECK_GAP + CHECK + PAD_X)
        self.list_width = max(trigger.width(), width or 0, min(natural, 480))
        # the active option starts on the selection (or the first selectable one)
        sel = [i for i in range(len(options)) if self.is_selected(i)]
        first = next((i for i in range(len(options)) if self.selectable(i)), -1)
        self.active = sel[0] if sel else first
        self.body = _Body(self)
        self.body.setMinimumHeight(self._content_h)          # a resizable scroll area honours the minimum
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(True)
        from .scroll import thin_scrollbars
        thin_scrollbars(self.scroll)
        self.scroll.setWidget(self.body)
        self.scroll.viewport().setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        lay.addWidget(self.scroll)
        self._place(max_rows)
        self.ensure_visible(self.active)

    # -------------------------------------------------------------- model
    def row_h(self, i: int) -> int:
        return SECTION_H if self.options[i].section else self.row_height

    def content_height(self) -> int:
        return self._content_h

    def selectable(self, i: int) -> bool:
        return 0 <= i < len(self.options) and not self.options[i].section and self.options[i].enabled

    def is_selected(self, i: int) -> bool:
        o = self.options[i]
        if o.section:
            return False
        return o.value in self.values if self.multi else o.value == self.value

    # -------------------------------------------------------------- geometry
    def _place(self, max_rows: int) -> None:
        g = self.trigger.mapToGlobal(QPoint(0, 0))
        screen = (QApplication.screenAt(g) or QApplication.primaryScreen()).availableGeometry()
        below = screen.bottom() - (g.y() + self.trigger.height())
        above = g.y() - screen.top()
        cap = min(self._content_h, max_rows * self.row_height)
        down = below >= min(cap, 4 * self.row_height) or below >= above
        room = below if down else above
        h = max(min(cap, room - 2 * SHADOW), self.row_height)
        self.setFixedSize(self.list_width + 2 * SHADOW, h + 2 * SHADOW)
        x = min(max(screen.left(), g.x() - SHADOW), screen.right() - self.width())
        if down:
            y = g.y() + self.trigger.height() - SHADOW
        else:
            y = g.y() - self.height() + SHADOW
        self.move(x, y)
        self.opens_up = not down

    def ensure_visible(self, i: int) -> None:
        if i < 0:
            return
        self.scroll.ensureVisible(0, self.row_y[i] + self.row_h(i) // 2, 0, self.row_h(i))

    def scroll_scrollable(self) -> bool:
        return self.scroll.verticalScrollBar().maximum() > 0

    # -------------------------------------------------------------- choosing
    def choose(self, i: int) -> None:
        o = self.options[i]
        if self.multi:
            if o.value in self.values:
                self.values.remove(o.value)
            else:
                self.values.append(o.value)
            self.body.update()
            self.toggled.emit(list(self.values))
            return
        self.value = o.value
        self.selected.emit(o.value)
        self.close()

    def _step(self, d: int) -> None:
        i = self.active
        n = len(self.options)
        for _ in range(n):
            i = (i + d) % n if i >= 0 else (0 if d > 0 else n - 1)
            if self.selectable(i):
                break
        self.active = i
        self.keyboard = True
        self.ensure_visible(i)
        self.body.update()

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Down:
            self._step(1)
        elif k == Qt.Key.Key_Up:
            self._step(-1)
        elif k == Qt.Key.Key_Home:
            self.active = -1
            self._step(1)
        elif k == Qt.Key.Key_End:
            self.active = -1
            self._step(-1)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self.selectable(self.active):
                self.choose(self.active)
        elif k in (Qt.Key.Key_Escape, Qt.Key.Key_Tab):
            self.close()
        else:
            super().keyPressEvent(e)

    # -------------------------------------------------------------- lifecycle / paint
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        inner = self.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        paint_shadow(p, inner)
        crisp.fill_rect(p, inner, t("layer-02"))
        p.end()

    def closeEvent(self, e):
        super().closeEvent(e)
        self.closed.emit()
        tr = self.trigger
        try:
            tr.closed_at = time.monotonic()
            tr.setFocus(Qt.FocusReason.PopupFocusReason)
        except RuntimeError:
            pass


def open_list(trigger: QWidget, options: list[Option], **kw) -> ListPopup | None:
    """Show a list popup unless the trigger has just closed one (the outside click that closed it is replayed
    on the trigger)."""
    if time.monotonic() - getattr(trigger, "closed_at", 0.0) < 0.3:
        return None
    pop = ListPopup(trigger, options, **kw)
    pop.show()
    pop.setFocus(Qt.FocusReason.PopupFocusReason)
    return pop
