"""Responsive layouts."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidget, QWidgetItem

from ..responsive import distribute


class UpperPanels(QWidget):
    """The upper content area: Element selection, Composition setup, Calculation details.

    * **wide** - one row, the design's 596 / 457 / 787 px reference widths distributed by
      ``responsive.distribute`` (only Details grows), exactly as before;
    * **stacked** - when the three panels no longer fit at their minimum widths, Details moves to a
      second row spanning the full width; Element + Composition share the first row (Composition
      grows).

    The breakpoint is not a screen size: it is the width the wide row needs, ``Σ minimums + gaps``
    (``wide_minimum``), with ``HYSTERESIS`` px extra before returning to wide so a resize near the
    boundary cannot oscillate.  The panels are only repositioned - never re-created - so their state
    survives every switch; the main scroll area simply receives the taller content.
    """

    HYSTERESIS = 24

    def __init__(self, panels: list[tuple[QWidget, int, int, int | None]], row_height: int, gap: int,
                 parent=None):
        super().__init__(parent)
        self.panels = panels                        # (widget, reference, minimum, maximum)
        self.row_height = row_height
        self.gap = gap
        self.stacked = False
        for w, _ref, mn, _mx in panels:
            w.setParent(self)
            w.setMinimumWidth(mn)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(row_height)

    def wide_minimum(self) -> int:
        return sum(mn for _w, _r, mn, _x in self.panels) + self.gap * (len(self.panels) - 1)

    def stacked_minimum(self) -> int:
        first = self.panels[:-1]
        return max(sum(mn for _w, _r, mn, _x in first) + self.gap * (len(first) - 1), self.panels[-1][2])

    def mode_for(self, width: int) -> bool:
        """True = stacked, for ``width`` given the current mode (hysteresis)."""
        need = self.wide_minimum() + (self.HYSTERESIS if self.stacked else 0)
        return width < need

    def minimumSizeHint(self) -> QSize:
        return QSize(self.stacked_minimum(), self.height())

    def sizeHint(self) -> QSize:
        return QSize(sum(r for _w, r, _m, _x in self.panels) + self.gap * (len(self.panels) - 1), self.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def relayout(self):
        width = self.width()
        stacked = self.mode_for(width)
        if stacked != self.stacked:
            self.stacked = stacked
            h = 2 * self.row_height + self.gap if stacked else self.row_height
            self.setFixedHeight(h)
        h = self.row_height
        if self.stacked:
            first = self.panels[:-1]
            avail = width - self.gap * (len(first) - 1)
            widths = distribute(avail, [r for _w, r, _m, _x in first], [m for _w, _r, m, _x in first],
                                [x for _w, _r, _m, x in first[:-1]] + [None])
            x = 0
            for (w, *_), wd in zip(first, widths):
                w.setGeometry(QRect(x, 0, wd, h))
                x += wd + self.gap
            self.panels[-1][0].setGeometry(QRect(0, h + self.gap, width, h))
        else:
            avail = width - self.gap * (len(self.panels) - 1)
            widths = distribute(avail, [r for _w, r, _m, _x in self.panels], [m for _w, _r, m, _x in self.panels],
                                [x for _w, _r, _m, x in self.panels])
            x = 0
            for (w, *_), wd in zip(self.panels, widths):
                w.setGeometry(QRect(x, 0, wd, h))
                x += wd + self.gap


class ProportionalRowLayout(QLayout):
    """Horizontal row whose items keep the design's width proportions (see ``responsive.distribute``).

    Each item has a reference width (its width in the 1920 px design frame), a minimum and an
    optional maximum (``None`` = may grow).  The layout's minimum width is the sum of the minimums,
    so a window narrower than that makes the enclosing scroll area show its fallback horizontal bar
    instead of clipping a panel.
    """

    def __init__(self, parent=None, spacing: int = 20):
        super().__init__(parent)
        self._items: list[tuple[QWidgetItem, int, int, int | None]] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def add(self, widget, ref: int, minimum: int, maximum: int | None = None):
        self.addChildWidget(widget)
        self._items.append((QWidgetItem(widget), ref, minimum, maximum))
        widget.setMinimumWidth(minimum)
        self.invalidate()

    # -- QLayout interface
    def addItem(self, item):                       # pragma: no cover - use add()
        self._items.append((item, item.sizeHint().width(), item.minimumSize().width(), None))

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i][0] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        if 0 <= i < len(self._items):
            return self._items.pop(i)[0]
        return None

    def _gaps(self) -> int:
        return self.spacing() * max(0, len(self._items) - 1)

    def _height(self) -> int:
        return max((it.sizeHint().height() for it, *_ in self._items), default=0)

    def sizeHint(self) -> QSize:
        m = self.contentsMargins()
        return QSize(sum(r for _i, r, _mn, _mx in self._items) + self._gaps() + m.left() + m.right(),
                     self._height() + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        m = self.contentsMargins()
        h = max((it.minimumSize().height() for it, *_ in self._items), default=0)
        return QSize(sum(mn for _i, _r, mn, _mx in self._items) + self._gaps() + m.left() + m.right(),
                     h + m.top() + m.bottom())

    def widths_for(self, width: int) -> list[int]:
        m = self.contentsMargins()
        avail = width - m.left() - m.right() - self._gaps()
        return distribute(avail, [r for _i, r, _mn, _mx in self._items],
                          [mn for _i, _r, mn, _mx in self._items],
                          [mx for _i, _r, _mn, mx in self._items])

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        m = self.contentsMargins()
        x = rect.x() + m.left()
        h = rect.height() - m.top() - m.bottom()
        for (item, *_), w in zip(self._items, self.widths_for(rect.width())):
            item.setGeometry(QRect(x, rect.y() + m.top(), w, h))
            x += w + self.spacing()
