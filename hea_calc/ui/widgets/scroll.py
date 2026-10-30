"""Scrolling primitives: the thin scroll bar, the main content scroll area and wheel ownership.

Scroll ownership (product decision): below the fixed HEA header there is **one** primary vertical
scrolling context, :class:`MainScrollArea`, holding the upper panels and the results table.  The
results table never scrolls vertically itself - it grows with the rows of its current page.
Internal scroll areas exist only where a component needs one (Details pages, composition rows,
expanded expression content); :func:`own_wheel` makes them consume the wheel *only while they can
scroll*, so two stacked scroll bars never fight over one gesture.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QFrame, QScrollArea, QScrollBar

from .. import crisp
from ..theme import CONTENT_MARGIN_X, SCROLLBAR_HIT, SCROLLBAR_MIN_THUMB, SCROLLBAR_VISIBLE, THEME, t


class ThinScrollBar(QScrollBar):
    """Scroll bar with a 4 px visible pill thumb (radius = half its thickness) centred in a 12 px invisible
    hit target.

    Painted and hit-tested here (not through the style), so the visible geometry and the
    interactive geometry are the same rectangle at every device pixel ratio; the thumb is filled
    through ``crisp`` so it is exactly ``floor(4 × dpr)`` device pixels wide.  Nothing is drawn
    when there is nothing to scroll.
    """

    def __init__(self, orientation=Qt.Orientation.Vertical, parent=None):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._hover = False
        self._drag: tuple[int, int] | None = None   # (press position along the bar, value at press)
        THEME.changed.connect(self._theme_changed)   # bound: auto-disconnected on deletion

    def _theme_changed(self, *_):
        self.update()

    # ---------------------------------------------------------------- geometry
    def _vertical(self) -> bool:
        return self.orientation() == Qt.Orientation.Vertical

    def sizeHint(self) -> QSize:
        return QSize(SCROLLBAR_HIT, 64) if self._vertical() else QSize(64, SCROLLBAR_HIT)

    def minimumSizeHint(self) -> QSize:
        return QSize(SCROLLBAR_HIT, SCROLLBAR_MIN_THUMB) if self._vertical() else \
            QSize(SCROLLBAR_MIN_THUMB, SCROLLBAR_HIT)

    def _track_len(self) -> int:
        return self.height() if self._vertical() else self.width()

    def thumb_span(self) -> tuple[float, float]:
        """(start, length) of the thumb along the bar, in logical px."""
        track = self._track_len()
        rng = self.maximum() - self.minimum()
        if rng <= 0:
            return 0.0, float(track)
        length = max(float(SCROLLBAR_MIN_THUMB), track * self.pageStep() / (rng + self.pageStep()))
        length = min(length, float(track))
        start = (self.value() - self.minimum()) / rng * (track - length)
        return start, length

    def thumb_rect(self) -> QRectF:
        start, length = self.thumb_span()
        if self._vertical():
            x = (self.width() - SCROLLBAR_VISIBLE) / 2
            return QRectF(x, start, SCROLLBAR_VISIBLE, length)
        y = (self.height() - SCROLLBAR_VISIBLE) / 2
        return QRectF(start, y, length, SCROLLBAR_VISIBLE)

    def _thumb_hit(self) -> QRect:
        start, length = self.thumb_span()
        if self._vertical():
            return QRect(0, int(start), self.width(), int(length) + 1)
        return QRect(int(start), 0, int(length) + 1, self.height())

    # ---------------------------------------------------------------- painting
    def paintEvent(self, _e):
        if self.maximum() <= self.minimum():
            return
        p = QPainter(self)
        # rest / hover / drag: the thumb only changes colour - its 4 px pill geometry never moves (brief 22)
        token = ("scrollbar-thumb-active" if self._drag else
                 "scrollbar-thumb-hover" if self._hover else "scrollbar-thumb")
        crisp.fill_pill(p, self.thumb_rect(), t(token))        # maximum roundness: a 4 px pill
        p.end()

    # ---------------------------------------------------------------- interaction
    def _pos(self, e) -> int:
        pt = e.position().toPoint()
        return pt.y() if self._vertical() else pt.x()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.maximum() <= self.minimum():
            return super().mousePressEvent(e)
        if self._thumb_hit().contains(e.position().toPoint()):
            self._drag = (self._pos(e), self.value())
            self.setSliderDown(True)
        else:
            start, _length = self.thumb_span()
            step = self.pageStep() if self._pos(e) > start else -self.pageStep()
            self.setValue(self.value() + step)
        self.update()
        e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            hover = self.maximum() > self.minimum()
            if hover != self._hover:
                self._hover = hover
                self.update()
            return
        start, length = self.thumb_span()
        free = self._track_len() - length
        if free <= 0:
            return
        delta = self._pos(e) - self._drag[0]
        rng = self.maximum() - self.minimum()
        self.setValue(round(self._drag[1] + delta * rng / free))
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.setSliderDown(False)
            self.update()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self._hover = self.maximum() > self.minimum()
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)


def thin_scrollbars(area: QAbstractScrollArea) -> QAbstractScrollArea:
    """Give ``area`` thin vertical and horizontal scroll bars (keeps its scroll-bar policies)."""
    area.setVerticalScrollBar(ThinScrollBar(Qt.Orientation.Vertical))
    area.setHorizontalScrollBar(ThinScrollBar(Qt.Orientation.Horizontal))
    return area


class _WheelOwner(QObject):
    """Inner scroll areas consume a vertical wheel gesture only while they can scroll.

    * nothing to scroll -> the event passes to the parent (the main content scroll area);
    * scrollable -> the inner area scrolls and the event is *accepted even at its ends*, so a
      gesture that reaches the bottom of a Details page does not suddenly start moving the page
      behind it (no scroll chaining in the middle of a gesture).
    """

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.Wheel:
            return False
        area = obj.parent()
        if not isinstance(area, QAbstractScrollArea):
            return False
        horizontal = abs(ev.angleDelta().x()) > abs(ev.angleDelta().y())
        bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
        if bar.maximum() <= bar.minimum():
            ev.ignore()
            return False          # let the parent scroll
        QApplication.sendEvent(bar, ev)
        ev.accept()
        return True


_WHEEL_OWNER: _WheelOwner | None = None


def own_wheel(area: QAbstractScrollArea) -> QAbstractScrollArea:
    """Apply the inner-scroll wheel rule (see :class:`_WheelOwner`) to ``area``."""
    global _WHEEL_OWNER
    if _WHEEL_OWNER is None:
        _WHEEL_OWNER = _WheelOwner()
    area.viewport().installEventFilter(_WHEEL_OWNER)
    return area


class OverlayScrollArea(QScrollArea):
    """An inner scroll area whose vertical bar floats over the content's right padding (as
    :class:`MainScrollArea` does for the window): the bar never takes width from the content, so a page that
    fits its panel never needs a horizontal bar just because it is tall."""

    OVERLAY_RIGHT = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBar(ThinScrollBar(Qt.Orientation.Horizontal))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = self.verticalScrollBar()
        self.overlay = ThinScrollBar(Qt.Orientation.Vertical, self)
        inner.rangeChanged.connect(self._sync_range)
        inner.valueChanged.connect(self.overlay.setValue)
        self.overlay.valueChanged.connect(inner.setValue)
        self._sync_range(inner.minimum(), inner.maximum())

    def _sync_range(self, lo: int, hi: int):
        inner = self.verticalScrollBar()
        self.overlay.setRange(lo, hi)
        self.overlay.setPageStep(inner.pageStep())
        self.overlay.setSingleStep(inner.singleStep())
        self.overlay.setValue(inner.value())
        self.overlay.setVisible(hi > lo)
        self._place()

    def _place(self):
        vp = self.viewport().geometry()
        self.overlay.setGeometry(vp.right() + 1 - SCROLLBAR_HIT - self.OVERLAY_RIGHT, vp.top(), SCROLLBAR_HIT,
                                 vp.height())
        self.overlay.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()


def inner_scroll_area(widget=None, horizontal: bool = False) -> QScrollArea:
    """A frameless, resizable internal scroll area with thin bars and the wheel rule."""
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    thin_scrollbars(sa)
    if not horizontal:
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    own_wheel(sa)
    if widget is not None:
        sa.setWidget(widget)
    return sa


class MainScrollArea(QScrollArea):
    """The application's single primary vertical scrolling context (below the HEA header).

    The vertical scroll bar is an **overlay**: a :class:`ThinScrollBar` floating in the 20 px right
    content margin (where the design draws it), mirrored to the area's own - hidden - bar.  It
    therefore never takes width from the content, so its appearing or disappearing never re-flows
    the panels or the table columns.  A horizontal bar appears only as a last-resort fallback when
    the window is narrower than the content's minimum width.
    """

    # the visible 4 px bar is centred in the 16 px outer gutter (CONTENT_MARGIN_X): its 12 px hit target sits
    # 2 px from the edge, leaving 6 px between the bar and the content and 6 px between it and the window edge
    # (2026-10-28; formerly 4 px from the content, 8 px from the edge)
    OVERLAY_RIGHT = (CONTENT_MARGIN_X - SCROLLBAR_HIT) // 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBar(ThinScrollBar(Qt.Orientation.Horizontal))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = self.verticalScrollBar()
        self.overlay = ThinScrollBar(Qt.Orientation.Vertical, self)
        self.overlay.setAccessibleName("Scroll main content")
        inner.rangeChanged.connect(self._sync_range)
        inner.valueChanged.connect(self.overlay.setValue)
        self.overlay.valueChanged.connect(inner.setValue)
        self._sync_range(inner.minimum(), inner.maximum())

    def _sync_range(self, lo: int, hi: int):
        inner = self.verticalScrollBar()
        self.overlay.setRange(lo, hi)
        self.overlay.setPageStep(inner.pageStep())
        self.overlay.setSingleStep(inner.singleStep())
        self.overlay.setValue(inner.value())
        self.overlay.setVisible(hi > lo)
        self._place_overlay()

    def _place_overlay(self):
        vp = self.viewport().geometry()
        self.overlay.setGeometry(vp.right() + 1 - SCROLLBAR_HIT - self.OVERLAY_RIGHT, vp.top(),
                                 SCROLLBAR_HIT, vp.height())
        self.overlay.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_overlay()

    def main_scrollbar_visible(self) -> bool:
        return self.overlay.isVisible()

    def scroll_to_widget_top(self, w, margin: int = 0):
        y = w.mapTo(self.widget(), QPoint(0, 0)).y()
        self.verticalScrollBar().setValue(max(0, y - margin))
