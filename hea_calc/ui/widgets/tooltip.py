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
* corner radius ``TOOLTIP_RADIUS`` = 2 px - an intentional exception to the 7 px HEA radius,
  measured on the HEA toggletip reference (``design/components/Group 241.png``);
* placement (:func:`place_popover`, Carbon popover guidelines "Placement" / "Alignment"): the
  preferred side (tooltips above, toggletips below), flipped to the opposite side and then to the
  right / left when it would leave the screen; the body is aligned *center* (tooltips) or *start*
  (toggletips: the HEA reference puts the caret 22 px from the body's left edge), then shifted
  to stay on screen; the caret is computed from the trigger's screen position, independently of
  the body, so it keeps pointing at the trigger after any shift (Carbon: "align the caret tip
  center with the trigger button"), limited only by the rounded corners;
* timing: enter 100 ms (Carbon React default), immediate on keyboard focus.  Closing is immediate (HEA
  product decision, release reconciliation): a tooltip is visible only while its trigger is hovered or keeps
  keyboard focus - no post-hover grace period, no fade.  Toggletips are unaffected (explicitly dismissed).
"""

from __future__ import annotations

import time

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPolygonF, QTextDocumentFragment
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel,
                               QVBoxLayout, QWidget)

from .. import icons
from ..theme import BODY_COMPACT_01, FOCUS_WIDTH, THEME, TOOLTIP_RADIUS, font, t

CARET_W, CARET_H = 12, 6
CARET_GAP = 4
START_CARET_INSET = 22      # start-aligned body: caret centre 22 px from its edge (Group 241.png, 66/3)
# Hover tooltips wait 400 ms (cancelled when the pointer leaves first), so sweeping the pointer across a column of
# controls - the Composition space locks - does not open a tooltip on every one.  Keyboard focus shows at once;
# toggletips (click) are not delayed.
ENTER_DELAY_MS = 400
LEAVE_DELAY_MS = 0          # no linger: hide as soon as the pointer leaves the trigger


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


@dataclass
class Placement:
    """Where a popover sits: ``pos`` (top-left of the widget, body + caret), ``side`` of the trigger
    it is on (``top`` = above it), and ``caret`` - the caret centre along the edge facing the
    trigger, in widget coordinates (x for top/bottom, y for left/right; None if unreachable)."""
    pos: QPoint
    side: str
    caret: float | None

    @property
    def below(self) -> bool:
        return self.side == "bottom"


def popover_size(body: QSize, side: str) -> QSize:
    if side in ("top", "bottom"):
        return QSize(body.width(), body.height() + CARET_H)
    return QSize(body.width() + CARET_H, body.height())


def place_popover(body: QSize, anchor: QRect, screen: QRect, prefer: str = "top", align: str = "center",
                  radius: float = TOOLTIP_RADIUS) -> Placement:
    """Anchor-aware placement (see module docstring).  ``anchor`` and ``screen`` are global rects."""
    opposite = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}[prefer]
    order = [prefer, opposite] + [s for s in ("right", "left", "bottom", "top") if s not in (prefer, opposite)]
    cx = anchor.left() + anchor.width() / 2
    cy = anchor.top() + anchor.height() / 2
    margin = radius + CARET_W / 2            # the caret stays on the straight part of the edge

    def fit(side: str) -> tuple[bool, Placement]:
        size = popover_size(body, side)
        w, h = size.width(), size.height()
        if side in ("top", "bottom"):
            y = anchor.top() - CARET_GAP - h if side == "top" else anchor.bottom() + 1 + CARET_GAP
            ok = screen.top() <= y and y + h - 1 <= screen.bottom()
            if align == "start":
                x = round(cx - START_CARET_INSET)
            elif align == "end":
                x = round(cx - (w - START_CARET_INSET))
            else:
                x = round(cx - w / 2)
            x = max(screen.left(), min(x, screen.right() - w + 1))
            y = max(screen.top(), min(y, screen.bottom() - h + 1))
            c = cx - x
            caret = min(max(c, margin), w - margin) if -CARET_W / 2 <= c <= w + CARET_W / 2 else None
            return ok, Placement(QPoint(x, y), side, None if caret is None else round(caret))
        x = anchor.right() + 1 + CARET_GAP if side == "right" else anchor.left() - CARET_GAP - w
        ok = screen.left() <= x and x + w - 1 <= screen.right()
        y = round(cy - h / 2)
        y = max(screen.top(), min(y, screen.bottom() - h + 1))
        x = max(screen.left(), min(x, screen.right() - w + 1))
        c = cy - y
        caret = min(max(c, margin), h - margin) if -CARET_W / 2 <= c <= h + CARET_W / 2 else None
        return ok, Placement(QPoint(x, y), side, None if caret is None else round(caret))

    for side in order:
        ok, placement = fit(side)
        if ok:
            return placement
    return fit(prefer)[1]


def place_bubble(size: QSize, anchor: QRect, screen: QRect, prefer_below: bool) -> tuple[QPoint, bool, int | None]:
    """Compatibility wrapper: centre-aligned, vertical placement of a bubble of ``size`` (with caret)."""
    pl = place_popover(QSize(size.width(), size.height() - CARET_H), anchor, screen,
                       "bottom" if prefer_below else "top")
    return pl.pos, pl.below, pl.caret


def body_rect(size: QSize, side: str) -> QRectF:
    w, h = size.width(), size.height()
    return {"top": QRectF(0, 0, w, h - CARET_H), "bottom": QRectF(0, CARET_H, w, h - CARET_H),
            "right": QRectF(CARET_H, 0, w - CARET_H, h), "left": QRectF(0, 0, w - CARET_H, h)}[side]


def bubble_path(body: QRectF, radius: float, caret: float | None, side: str) -> QPainterPath:
    """Rounded body plus caret pointing at the trigger, as one path (no seam)."""
    path = QPainterPath()
    path.addRoundedRect(body, radius, radius)
    if caret is not None:
        half = CARET_W / 2
        if side == "bottom":       # bubble below the trigger: caret on the top edge, pointing up
            pts = [QPointF(caret - half, body.top() + 0.5), QPointF(caret + half, body.top() + 0.5),
                   QPointF(caret, body.top() - CARET_H)]
        elif side == "top":        # bubble above: caret on the bottom edge, pointing down
            pts = [QPointF(caret - half, body.bottom() - 0.5), QPointF(caret + half, body.bottom() - 0.5),
                   QPointF(caret, body.bottom() + CARET_H)]
        elif side == "right":      # bubble right of the trigger: caret on the left edge, pointing left
            pts = [QPointF(body.left() + 0.5, caret - half), QPointF(body.left() + 0.5, caret + half),
                   QPointF(body.left() - CARET_H, caret)]
        else:
            pts = [QPointF(body.right() - 0.5, caret - half), QPointF(body.right() - 0.5, caret + half),
                   QPointF(body.right() + CARET_H, caret)]
        tri = QPainterPath()
        tri.addPolygon(QPolygonF(pts))
        tri.closeSubpath()
        path = path.united(tri)
    return path


class CarbonToolTip(QWidget):
    """The tooltip bubble (see module docstring for the specification)."""

    PAD_X = 16
    PAD_Y = 3                 # single-line: 18 px line in a 24 px body (reference 21)
    PAD_MULTI = 16
    MAX_SINGLE = 208          # Carbon single-line container max-width
    MAX_MULTI = 288           # Carbon multi-line container max-width
    LINE_MULTI = 20           # body-01 line height for multi-line tooltips
    CARET_W, CARET_H, GAP, RADIUS = CARET_W, CARET_H, CARET_GAP, TOOLTIP_RADIUS

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFont(font(BODY_COMPACT_01))
        self._lines: list[str] = [""]
        self._multi = False
        self.placement = Placement(QPoint(), "top", None)
        self.anchor = QRect()
        self.text = ""

    @property
    def _caret(self) -> bool:
        return self.placement.caret is not None

    @property
    def _below(self) -> bool:
        return self.placement.below

    @property
    def _caret_x(self) -> int | None:
        return self.placement.caret if self.placement.side in ("top", "bottom") else None

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
        self.placement = place_popover(body, anchor, screen, "bottom" if below else "top", "center")
        self.resize(popover_size(body, self.placement.side))
        self.move(self.placement.pos)
        self.setAccessibleName(text)
        self.show()
        self.update()

    def body_rect(self) -> QRectF:
        return body_rect(self.size(), self.placement.side)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = self.body_rect()
        p.fillPath(bubble_path(body, TOOLTIP_RADIUS, self.placement.caret, self.placement.side),
                   QColor(t("background-inverse")))
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
            p.drawText(QPointF(body.left() + pad_x, base), line)
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


def _has_cell_tips(obj) -> bool:
    return isinstance(obj, QWidget) and callable(getattr(obj, "tip_at", None))


class ToolTipController(QObject):
    """Application-wide event filter that shows :class:`CarbonToolTip` instead of Qt's tooltip.

    * plain widgets with ``toolTip()``: Enter starts the 400 ms enter delay, Leave cancels it or hides at once (no
      linger); a click or wheel on the trigger cancels a pending tooltip and hides a shown one;
      keyboard focus (Tab / Backtab / Shortcut) shows it at once, focus-out hides it;
    * item views and headers: the per-cell / per-section tooltip, anchored to that cell, refreshed
      as the pointer moves to another cell; painted widgets with cells answer the same way through
      ``tip_at(pos) -> (text, local rect) | None`` (the Analysis ``DataTable``);
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
        self._focus_shown = False         # the visible tip was opened by keyboard focus

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
        self._focus_shown = False
        self._source = widget
        self._bubble().show_for(anchor, text, screen.availableGeometry(), below)

    def hide(self):
        self._enter.stop()
        self._leave.stop()
        self._pending = None
        self._source = None
        self._focus_shown = False
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
            if obj is self._source and not (self._focus_shown and obj.hasFocus()):
                self.hide()             # no linger after hover (a keyboard-focus tip stays with the focus)
        elif et == QEvent.Type.MouseMove and self._source is obj and self.tip is not None \
                and (isinstance(obj.parent(), (QAbstractItemView, QHeaderView)) or _has_cell_tips(obj)):
            # left the cell the tip belongs to
            local = obj.mapFromGlobal(self.tip.anchor.topLeft())
            if not QRect(local, self.tip.anchor.size()).contains(ev.position().toPoint()):
                self.hide()
        elif et == QEvent.Type.FocusIn:
            reason = ev.reason()
            if obj.toolTip() and reason in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                            Qt.FocusReason.ShortcutFocusReason):
                self.show_tip(obj, obj.toolTip())
                self._focus_shown = True
        elif et == QEvent.Type.FocusOut:
            if obj is self._source:
                self.hide()
        elif et == QEvent.Type.KeyPress:
            if ev.key() == Qt.Key.Key_Escape and self.visible():
                self.hide()
        elif et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel):
            if self._pending is not None:
                self._enter.stop()              # clicked / scrolled before the delay ran out: no tooltip
                self._pending = None
            if self.visible() and not self._focus_shown:
                self.hide()                     # the pointer acted: the hover tip (now possibly outdated) goes
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
        elif _has_cell_tips(obj):
            hit = obj.tip_at(ev.pos())
            if hit:
                text, rect = hit
                self.show_tip(obj, text, rect)
        elif isinstance(obj, QWidget) and obj.toolTip() and not self.visible():
            self.show_tip(obj, obj.toolTip())
        if hit is None and (isinstance(parent, (QAbstractItemView, QHeaderView)) or _has_cell_tips(obj)) \
                and self._source is obj:
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
class _ToggletipIconRow(QWidget):
    """One toggletip row: a 16 px vector icon (inverse tokens, painted at the device pixel ratio) + text."""

    def __init__(self, icon_name: str, text: QLabel):
        super().__init__()
        self.icon_name = icon_name
        self.label = text
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(text, 0, Qt.AlignmentFlag.AlignTop)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fm = QFontMetrics(self.label.font())
        y = max(0.0, (min(18, fm.height()) - 16) / 2 + 1)          # centred on the first text line
        icons.paint(p, self.icon_name, QRectF(0, y, 16, 16), inverse=True)
        p.end()


class Toggletip(QWidget):
    """Carbon toggletip popover: inverse surface, 16 px padding, 2 px corners, caret on the trigger.

    Start-aligned below the trigger (HEA reference: caret 22 px from the body's left edge), with the
    general collision handling of :func:`place_popover`.

    A ``Qt.Popup`` window, so a click anywhere outside closes it (Carbon), and ``Esc`` closes it;
    on close, focus returns to the trigger.  Content is rich text (status icons inline, as in the
    design's model-support legend, ``design/components/Group 241.png``).
    """

    PAD = 16
    MAX_W = 288
    ROW_GAP = 4

    def __init__(self, anchor: QWidget, html, title: str = "", width: int | None = None, on_link=None):
        """``html``: rich text, or a list of blocks - a paragraph string, or ``("icon", name, html)`` for a
        row led by a 16 px status / Carbon icon.  Icons are vector-painted in device pixels from the *inverse*
        tokens (crisp at every DPR; never a raster ``<img>``).  ``on_link(href)`` handles link activation."""
        super().__init__(anchor.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.anchor = anchor
        self.on_link = on_link
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAccessibleName(title or "More information")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.max_w = width or self.MAX_W
        lay = QVBoxLayout(self)
        lay.setSpacing(self.ROW_GAP)
        blocks = [html] if isinstance(html, str) else list(html)
        inner = self.max_w - 2 * self.PAD
        self.labels: list[QLabel] = []
        body_h = 0
        plain = []
        for i, b in enumerate(blocks):
            if isinstance(b, tuple) and b and b[0] == "icon":
                row = _ToggletipIconRow(b[1], self._text(b[2], inner - 24))
                lay.addWidget(row)
                self.labels.append(row.label)
                h = row.label.heightForWidth(inner - 24)
                row.setFixedHeight(max(16, h))
                body_h += max(16, h)
                plain.append(QTextDocumentFragment.fromHtml(b[2]).toPlainText())
            else:
                lab = self._text(str(b), inner)
                lay.addWidget(lab)
                self.labels.append(lab)
                body_h += lab.heightForWidth(inner)
                plain.append(QTextDocumentFragment.fromHtml(str(b)).toPlainText())
            if i:
                body_h += self.ROW_GAP
        self.label = self.labels[0] if self.labels else QLabel()
        self.setAccessibleDescription(" ".join(plain))
        body = QSize(self.max_w, body_h + 2 * self.PAD)
        g = anchor.mapToGlobal(QPoint(0, 0))
        screen = (QApplication.screenAt(g) or QApplication.primaryScreen()).availableGeometry()
        self.placement = place_popover(body, QRect(g, anchor.size()), screen, "bottom", "start")
        side = self.placement.side
        lay.setContentsMargins(self.PAD + (CARET_H if side == "right" else 0),
                               self.PAD + (CARET_H if side == "bottom" else 0),
                               self.PAD + (CARET_H if side == "left" else 0),
                               self.PAD + (CARET_H if side == "top" else 0))
        self.setFixedSize(popover_size(body, side))
        self.move(self.placement.pos)

    def _text(self, html: str, width: int) -> QLabel:
        from ..theme import style_links
        # Carbon link on the inverse surface: link-inverse at rest; hover link-inverse-hover + underline; no
        # visited colour (inline anchor colours: the windows11 accent never leaks in - theme.style_links)
        lab = QLabel(style_links(html, t("link-inverse")))
        lab.setObjectName("ToggletipText")
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        lab.setFont(font(BODY_COMPACT_01))
        # inverse surface: text-inverse, link-inverse (Carbon), never the main surface's tokens
        lab.setStyleSheet(f"color: {t('text-inverse')}; background: transparent; font-size: 14px;")
        pal = lab.palette()
        pal.setColor(pal.ColorRole.Link, QColor(t("link-inverse")))
        pal.setColor(pal.ColorRole.LinkVisited, QColor(t("link-inverse")))
        lab.setPalette(pal)
        lab.setOpenExternalLinks(False)
        lab.linkActivated.connect(self._link)
        lab.setProperty("source_html", html)
        lab.linkHovered.connect(self._hover_link)
        lab.setFixedWidth(width)
        return lab

    def _hover_link(self, href: str) -> None:
        """Carbon link hover: link-inverse-hover + underline.  QLabel also reports the end of a hover while it is
        hidden or torn down (the toggletip closes on a click) - re-rendering then would touch a dying widget."""
        import shiboken6
        from ..theme import style_links
        lab = self.sender()
        if lab is None or not shiboken6.isValid(lab) or not lab.isVisible() or not self.isVisible():
            return
        html = lab.property("source_html") or ""
        lab.setText(style_links(html, t("link-inverse-hover"), True) if href else style_links(html, t("link-inverse")))

    def _link(self, href: str) -> None:
        cb = self.on_link
        self.close()
        if cb is not None:
            cb(href)
        elif href.startswith(("http://", "https://")):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(href))
        else:
            from .. import help_router
            help_router.open(href, self.anchor)

    @property
    def _below(self) -> bool:
        return self.placement.below

    @property
    def _caret_x(self) -> int | None:
        return self.placement.caret if self.placement.side in ("top", "bottom") else None

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = body_rect(self.size(), self.placement.side)
        p.fillPath(bubble_path(body, TOOLTIP_RADIUS, self.placement.caret, self.placement.side),
                   QColor(t("background-inverse")))
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
        THEME.changed.connect(self._theme_changed)   # bound: auto-disconnected on deletion

    def _theme_changed(self, *_):
        self.update()

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
