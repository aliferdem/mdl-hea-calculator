"""Responsive layouts."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..responsive import distribute


class UpperPanels(QWidget):
    """The upper content area: Elements, Composition setup, Analysis.

    * **wide** - one row: Elements and Composition at their fixed design widths, Analysis takes the rest
      (at least its wide minimum);
    * **stacked** - when the three panels no longer fit, Analysis moves to a second row spanning the full
      width with the taller ``stacked_height`` (brief §19); Elements and Composition keep their fixed sizes,
      left-aligned (they are never stretched to fill the row - 8.png, brief §18).

    ``panels`` are ``(widget, reference, wide_minimum, maximum)``; a widget's own minimum width is its own
    business (Analysis may be narrower when stacked than it is allowed to be in the wide row).

    The breakpoint is not a screen size: it is the width the wide row needs, ``Σ wide minimums + gaps``
    (``wide_minimum``; 1880 px - exactly the 1920 px design window).  No hysteresis: the main scroll bar is an
    overlay, so switching modes never changes the available width and cannot oscillate, and a window returned
    to its design width must be wide again.  The panels are only repositioned - never re-created or re-parented - so
    their state survives every switch and no panel ever becomes a top-level window; the main scroll area
    simply receives the taller content.
    """

    HYSTERESIS = 0

    def __init__(self, panels: list[tuple[QWidget, int, int, int | None]], row_height: int, gap: int,
                 parent=None, stacked_height: int | None = None):
        super().__init__(parent)
        self.panels = panels                        # (widget, reference, wide minimum, maximum)
        self.row_height = row_height
        self.stacked_height = stacked_height or row_height
        self.gap = gap
        self.stacked = False
        for w, _ref, _mn, _mx in panels:
            w.setParent(self)
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
            h = self.row_height + self.gap + self.stacked_height if stacked else self.row_height
            self.setFixedHeight(h)
        h = self.row_height
        if self.stacked:
            x = 0
            for w, ref, _mn, _mx in self.panels[:-1]:          # fixed design widths, left-aligned
                w.setGeometry(QRect(x, 0, ref, h))
                x += ref + self.gap
            self.panels[-1][0].setGeometry(QRect(0, h + self.gap, width, self.stacked_height))
        else:
            avail = width - self.gap * (len(self.panels) - 1)
            widths = distribute(avail, [r for _w, r, _m, _x in self.panels], [m for _w, _r, m, _x in self.panels],
                                [x for _w, _r, _m, x in self.panels])
            x = 0
            for (w, *_), wd in zip(self.panels, widths):
                w.setGeometry(QRect(x, 0, wd, h))
                x += wd + self.gap
