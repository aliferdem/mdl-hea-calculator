"""Carbon Tooltip and Toggletip for PySide6.

Carbon v11 distinguishes the two (Carbon MCP, components/tooltip + components/toggletip guidelines):

* **Tooltip** - brief, non-interactive supplemental text, exposed on *hover or keyboard focus*,
  dismissed by moving away, tabbing away or ``Esc``.  Every ``setToolTip`` in the application -
  icon buttons, table cells, header sections - is shown through :class:`CarbonToolTip` by the
  application-wide :class:`ToolTipController`; Qt's native ``QToolTip`` never appears.
* **Toggletip** - opened explicitly by a trigger (click, ``Enter`` or ``Space``), may hold richer
  content, closes on ``Esc``, on a click outside or on the trigger again, and returns focus to the
  trigger.  :class:`Toggletip` / :class:`InfoButton`; used for the model-support legend and the
  expression syntax help.

Visual specification (Carbon tooltip specs, HEA design where it customises them):

* container ``$background-inverse``, text ``$text-inverse``; body-compact-01 (14 / 18 px);
* single-line tooltips: 16 px side padding, max width 208 px; body 24 px tall for one line
  (``21_dark_mode_fullscreen_tooltips``: "Composition space" 155 × 24);
* multi-line tooltips (more than two wrapped lines): 16 px padding on all sides, max width 288 px,
  body-01 line height 20 px;
* caret 12 × 6 px (Carbon ``popover-caret``; measured 12 × 6 in reference 21), tip 4 px from the
  trigger (``$spacing-02``);
* corner radius: the HEA ``CORNER_RADIUS`` token (7 px) - the HEA design's one radius for rounded
  components;
* placement: above the trigger by default (``tip_align`` property ``"bottom"`` places it below),
  flipped when it would leave the screen, clamped horizontally, caret kept on the trigger's
  centre - and dropped when the clamped body can no longer reach it;
* timing: Carbon React defaults, enter 100 ms, leave 300 ms; immediate on keyboard focus.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPolygonF, QTextDocumentFragment
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QHeaderView, QLabel, QVBoxLayout,
                               QWidget)

from .. import icons
from ..theme import BODY_COMPACT_01, CORNER_RADIUS, FOCUS_WIDTH, THEME, font, t

CARET_W, CARET_H = 12, 6
CARET_GAP = 4
ENTER_DELAY_MS = 100
LEAVE_DELAY_MS = 300


def _wrap(line: str, fm: QFontMetrics, width: int) -> list[str]:
    out, cur = [], ""
    for word in line.split(" "):
        trial = f"{cur} {word}".strip()
        if cur and fm.horizontalAdvance(trial) > width:
            out.append(cur)
            cur = word
        else:
            cur = trial
    out.append(cur)
    return out


def _bubble_path(body: QRectF, radius: float, caret_x: float | None, below: bool) -> QPainterPath:
    """Rounded body plus caret, as one path (no seam between caret and body)."""
    path = QPainterPath()
    path.addRoundedRect(body, radius, radius)
    if caret_x is not None:
        half = CARET_W / 2
        if below:          # bubble below the anchor: caret on the top edge, pointing up
            tri = QPolygonF([QPointF(caret_x - half, body.top() + 0.5), QPointF(caret_x + half, body.top() + 0.5),
                             QPointF(caret_x, body.top() - CARET_H)])
        else:              # bubble above the anchor: caret on the bottom edge, pointing down
            tri = QPolygonF([QPointF(caret_x - half, body.bottom() - 0.5), QPointF(caret_x + half, body.bottom() - 0.5),
                             QPointF(caret_x, body.bottom() + CARET_H)])
        caret = QPainterPath()
        caret.addPolygon(tri)
        caret.closeSubpath()
        path = path.united(caret)
    return path


def place_bubble(size: QSize, anchor: QRect, screen: QRect, prefer_below: bool) -> tuple[QPoint, bool, int | None]:
    """Top-left of a bubble (body + caret) of ``size``, whether it sits below the anchor, and the
    caret's x inside the bubble (None when the clamped body cannot reach the anchor's centre)."""
    w, h = size.width(), size.height()
    above_y = anchor.top() - CARET_GAP - h
    below_y = anchor.bottom() + 1 + CARET_GAP
    below = prefer_below
    if below and below_y + h - 1 > screen.bottom() and above_y >= screen.top():
        below = False
    elif not below and above_y < screen.top() and below_y + h - 1 <= screen.bottom():
        below = True
    y = below_y if below else above_y
    y = max(screen.top(), min(y, screen.bottom() - h + 1))
    centre = anchor.left() + anchor.width() / 2
    x = round(centre - w / 2)
    x = max(screen.left(), min(x, screen.right() - w + 1))
    cx = centre - x
    margin = CORNER_RADIUS + CARET_W / 2       # keep the caret on the straight part of the edge
    caret = int(round(cx)) if margin <= cx <= w - margin else None
    return QPoint(x, y), below, caret


class CarbonToolTip(QWidget):
    """The tooltip bubble (see module docstring for the specification)."""

    PAD_X = 16
    PAD_Y = 3                 # single-line: 18 px line in a 24 px body (reference 21)
    PAD_MULTI = 16
    MAX_SINGLE = 208          # Carbon single-line container max-width
    MAX_MULTI = 288           # Carbon multi-line container max-width
    LINE_MULTI = 20           # body-01 line height for multi-line tooltips
    CARET_W, CARET_H, GAP, RADIUS = CARET_W, CARET_H, CARET_GAP, CORNER_RADIUS

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFont(font(BODY_COMPACT_01))
        self._lines: list[str] = [""]
        self._multi = False
        self._below = False
        self._caret_x: int | None = None
        self.anchor = QRect()
        self.text = ""

    @property
    def _caret(self) -> bool:
        return self._caret_x is not None

    def layout_text(self, text: str) -> QSize:
        """Wrap ``text`` and return the body size (without caret)."""
        fm = QFontMetrics(self.font())
        paras = text.split("\n")
        lines: list[str] = []
        for para in paras:
            lines.extend(_wrap(para, fm, self.MAX_SINGLE - 2 * self.PAD_X))
        self._multi = len(lines) > 2
        if self._multi:
            lines = []
            for para in paras:
                lines.extend(_wrap(para, fm, self.MAX_MULTI - 2 * self.PAD_MULTI))
        self._lines = lines
        width = max((fm.horizontalAdvance(ln) for ln in lines), default=0)
        if self._multi:
            return QSize(width + 2 * self.PAD_MULTI, len(lines) * self.LINE_MULTI + 2 * self.PAD_MULTI)
        return QSize(width + 2 * self.PAD_X, len(lines) * 18 + 2 * self.PAD_Y)

    def show_for(self, anchor: QRect, text: str, screen: QRect, below: bool = False) -> None:
        self.text = text
        self.anchor = QRect(anchor)
        body = self.layout_text(text)
        size = QSize(body.width(), body.height() + CARET_H)
        self.resize(size)
        pos, self._below, self._caret_x = place_bubble(size, anchor, screen, below)
        self.move(pos)
        self.setAccessibleName(text)
        self.show()
        self.update()

    def body_rect(self) -> QRectF:
        if self._below:
            return QRectF(0, CARET_H, self.width(), self.height() - CARET_H)
        return QRectF(0, 0, self.width(), self.height() - CARET_H)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = self.body_rect()
        p.fillPath(_bubble_path(body, CORNER_RADIUS, self._caret_x, self._below), QColor(t("background-inverse")))
        p.setPen(QColor(t("text-inverse")))
        p.setFont(self.font())
        fm = QFontMetrics(self.font())
        pad_x = self.PAD_MULTI if self._multi else self.PAD_X
        pad_y = self.PAD_MULTI if self._multi else self.PAD_Y
        line_h = self.LINE_MULTI if self._multi else 18
        y = body.top() + pad_y
        for line in self._lines:
            # centre the 14 px font's ascent+descent inside the line box
            base = y + (line_h - fm.height()) / 2 + fm.ascent()
            p.drawText(QPointF(pad_x, base), line)
            y += line_h
        p.end()


def _item_tip(view: QAbstractItemView, pos: QPoint) -> tuple[str, QRect] | None:
    idx = view.indexAt(pos)
    if not idx.isValid():
        return None
    text = idx.data(Qt.ItemDataRole.ToolTipRole)
    if not text:
        return None
    return str(text), view.visualRect(idx)


def _header_tip(header: QHeaderView, pos: QPoint) -> tuple[str, QRect] | None:
    section = header.logicalIndexAt(pos)
    model = header.model()
    if section < 0 or model is None:
        return None
    text = model.headerData(section, header.orientation(), Qt.ItemDataRole.ToolTipRole)
    if not text:
        return None
    x = header.sectionViewportPosition(section)
    return str(text), QRect(x, 0, header.sectionSize(section), header.height())


class ToolTipController(QObject):
    """Application-wide event filter that shows :class:`CarbonToolTip` instead of Qt's tooltip.

    * plain widgets with ``toolTip()``: Enter starts the 100 ms enter delay, Leave the 300 ms leave
      delay; keyboard focus (Tab / Backtab / Shortcut) shows it at once, focus-out hides it;
    * item views and headers: the per-cell / per-section tooltip, anchored to that cell, refreshed
      as the pointer moves to another cell;
    * ``Esc`` and any mouse press elsewhere dismiss it; Qt's own ``QEvent.ToolTip`` is swallowed.
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.tip: CarbonToolTip | None = None
        self._pending: QWidget | None = None
        self._source: QWidget | None = None
        self._enter = QTimer(self)
        self._enter.setSingleShot(True)
        self._enter.setInterval(ENTER_DELAY_MS)
        self._enter.timeout.connect(self._show_pending)
        self._leave = QTimer(self)
        self._leave.setSingleShot(True)
        self._leave.setInterval(LEAVE_DELAY_MS)
        self._leave.timeout.connect(self.hide)

    # ---------------------------------------------------------------- showing / hiding
    def _bubble(self) -> CarbonToolTip:
        if self.tip is None:
            self.tip = CarbonToolTip()
        return self.tip

    def show_tip(self, widget: QWidget, text: str, local_rect: QRect | None = None):
        rect = local_rect or widget.rect()
        g = widget.mapToGlobal(rect.topLeft())
        anchor = QRect(g, rect.size())
        screen = QApplication.screenAt(anchor.center()) or self.app.primaryScreen()
        below = str(widget.property("tip_align") or "") == "bottom"
        self._leave.stop()
        self._source = widget
        self._bubble().show_for(anchor, text, screen.availableGeometry(), below)

    def hide(self):
        self._enter.stop()
        self._leave.stop()
        self._pending = None
        self._source = None
        if self.tip is not None:
            self.tip.hide()

    def _show_pending(self):
        w = self._pending
        self._pending = None
        if w is not None and w.isVisible() and w.toolTip():
            self.show_tip(w, w.toolTip())

    def visible(self) -> bool:
        return self.tip is not None and self.tip.isVisible()

    # ---------------------------------------------------------------- events
    def eventFilter(self, obj, ev):
        et = ev.type()
        if et == QEvent.Type.ToolTip:
            return self._item_tooltip(obj, ev)
        if not isinstance(obj, QWidget):
            return False
        if et == QEvent.Type.Enter:
            if obj.toolTip() and not isinstance(obj, CarbonToolTip):
                self._leave.stop()
                if self.visible() and self._source is not obj:
                    self.show_tip(obj, obj.toolTip())     # moving between triggers: no re-delay
                else:
                    self._pending = obj
                    self._enter.start()
        elif et == QEvent.Type.Leave:
            if obj is self._pending:
                self._enter.stop()
                self._pending = None
            if obj is self._source:
                self._leave.start()
        elif et == QEvent.Type.MouseMove and self._source is obj and self.tip is not None \
                and isinstance(obj.parent(), (QAbstractItemView, QHeaderView)):
            # left the cell the tip belongs to
            local = obj.mapFromGlobal(self.tip.anchor.topLeft())
            if not QRect(local, self.tip.anchor.size()).contains(ev.position().toPoint()):
                self.hide()
        elif et == QEvent.Type.FocusIn:
            reason = ev.reason()
            if obj.toolTip() and reason in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                            Qt.FocusReason.ShortcutFocusReason):
                self.show_tip(obj, obj.toolTip())
        elif et == QEvent.Type.FocusOut:
            if obj is self._source:
                self.hide()
        elif et == QEvent.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape and self.visible():
                self.hide()
        elif et in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel) and self.visible() and obj is not self._source:
            self.hide()
        elif et == QEvent.Type.Hide and obj is self._source:
            self.hide()
        return False

    def _item_tooltip(self, obj, ev) -> bool:
        """Qt asks for a tooltip (pointer resting): answer for item views / headers, swallow the rest."""
        parent = obj.parent() if isinstance(obj, QWidget) else None
        hit = None
        if isinstance(parent, QHeaderView) and obj is parent.viewport():
            hit = _header_tip(parent, ev.pos())
            if hit:
                text, rect = hit
                self.show_tip(obj, text, rect)
        elif isinstance(parent, QAbstractItemView) and obj is parent.viewport():
            hit = _item_tip(parent, ev.pos())
            if hit:
                text, rect = hit
                self.show_tip(obj, text, rect)
        elif isinstance(obj, QWidget) and obj.toolTip() and not self.visible():
            self.show_tip(obj, obj.toolTip())
        if hit is None and isinstance(parent, (QAbstractItemView, QHeaderView)) and self._source is obj:
            self.hide()
        return True             # never let Qt show its native tooltip


_CONTROLLER: ToolTipController | None = None


def install_tooltips(app) -> ToolTipController:
    """Route every tooltip through :class:`CarbonToolTip` (idempotent)."""
    global _CONTROLLER
    if _CONTROLLER is None:
        _CONTROLLER = ToolTipController(app)
        app.installEventFilter(_CONTROLLER)
    return _CONTROLLER


def controller() -> ToolTipController | None:
    return _CONTROLLER


# ==================================================================================== toggletip
class Toggletip(QWidget):
    """Carbon toggletip popover: inverse surface, 16 px padding, caret on the trigger, max 288 px.

    A ``Qt.Popup`` window, so a click anywhere outside closes it (Carbon), and ``Esc`` closes it;
    on close, focus returns to the trigger.  Content is rich text (status icons inline, as in the
    design's model-support legend, ``design/components/Group 241.png``).
    """

    PAD = 16
    MAX_W = 288

    def __init__(self, anchor: QWidget, html: str, title: str = "", width: int | None = None):
        super().__init__(anchor.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.anchor = anchor
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAccessibleName(title or "More information")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._below = True
        self._caret_x: int | None = None
        self.max_w = width or self.MAX_W
        lay = QVBoxLayout(self)
        self.label = QLabel(html)
        self.label.setObjectName("ToggletipText")
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setWordWrap(True)
        self.label.setFont(font(BODY_COMPACT_01))
        self.label.setStyleSheet(f"color: {t('text-inverse')}; background: transparent; font-size: 14px;")
        self.label.setAccessibleDescription(QTextDocumentFragment.fromHtml(html).toPlainText())
        self.label.setFixedWidth(self.max_w - 2 * self.PAD)
        lay.addWidget(self.label)
        body_h = self.label.heightForWidth(self.label.width())
        size = QSize(self.max_w, body_h + 2 * self.PAD + CARET_H)
        g = anchor.mapToGlobal(QPoint(0, 0))
        screen = (QApplication.screenAt(g) or QApplication.primaryScreen()).availableGeometry()
        pos, self._below, self._caret_x = place_bubble(size, QRect(g, anchor.size()), screen, True)
        top = CARET_H if self._below else 0
        lay.setContentsMargins(self.PAD, self.PAD + top, self.PAD, self.PAD + (CARET_H - top))
        self.setFixedSize(size)
        self.move(pos)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(0, CARET_H, self.width(), self.height() - CARET_H) if self._below else \
            QRectF(0, 0, self.width(), self.height() - CARET_H)
        p.fillPath(_bubble_path(body, CORNER_RADIUS, self._caret_x, self._below), QColor(t("background-inverse")))
        p.end()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        super().closeEvent(e)
        anchor = self.anchor
        if anchor is not None:
            anchor.closed_at = time.monotonic()
            anchor.setProperty("expanded", False)
            anchor.setFocus(Qt.FocusReason.PopupFocusReason)
            anchor.update()


class InfoButton(QAbstractButton):
    """Toggletip trigger: the 16 px ``information`` icon (Carbon toggletip button).

    Click / ``Enter`` / ``Space`` opens the toggletip; activating it again (or ``Esc``, or a click
    outside) closes it.  It carries an accessible name and an accessible description of the
    disclosure, and a 2 px focus ring.
    """

    def __init__(self, html, parent=None, title: str = "More information", width: int | None = None):
        super().__init__(parent)
        self.tip_text = html
        self.popup_width = width
        self.title = title
        self.popup: Toggletip | None = None
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription("Opens an explanation; press Escape to close it.")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.clicked.connect(self.toggle)
        THEME.changed.connect(lambda *_: self.update())

    def is_open(self) -> bool:
        try:
            return self.popup is not None and self.popup.isVisible()
        except RuntimeError:          # deleted on close
            return False

    def toggle(self):
        if self.is_open():
            self.popup.close()
            return
        # a click on the trigger while open first closes the popup (outside click) and is then
        # replayed to the trigger - that click means "close", not "open again"
        if time.monotonic() - getattr(self, "closed_at", 0.0) < 0.3:
            return
        html = self.tip_text() if callable(self.tip_text) else self.tip_text
        self.popup = Toggletip(self, html, self.title, self.popup_width)
        self.setProperty("expanded", True)
        self.popup.show()
        self.popup.setFocus(Qt.FocusReason.PopupFocusReason)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e):
        from .. import crisp
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        token = "icon-primary" if (self.underMouse() or self.is_open()) else "icon-secondary"
        icons.paint(p, "information", QRectF(0, 0, 16, 16), token)
        if self.hasFocus():
            crisp.frame(p, self.rect(), FOCUS_WIDTH, t("focus"))
        p.end()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()
