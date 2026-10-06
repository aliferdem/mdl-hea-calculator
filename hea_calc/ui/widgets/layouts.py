"""Responsive layouts."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QLayout, QWidgetItem

from ..responsive import distribute


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
