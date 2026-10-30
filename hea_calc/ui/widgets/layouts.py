"""Responsive layouts."""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..responsive import distribute

STRIP = 40          # Figma Mode=Collapsed (Composition setup 533:56747, Analysis 534:66018): 40 px wide
COLLAPSED_GAP = 8   # the gap on either side of a vertical collapsed strip in a row (the page gap stays 16 elsewhere)


class CollapsedStrip(QWidget):
    """A collapsed panel (Figma Mode=Collapsed / Collapsed Horizontal / Collapsed Vertical): the panel surface,
    40 px across, with the expand button (40 × 40) and the title - rotated in a vertical strip (reading top to
    bottom, from y = 56), horizontal in a 40 px tall bar (stacked Analysis)."""

    expand_requested = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        from .status_tag import HeaderIconButton
        self.title = title
        self.horizontal = False
        self.setObjectName("Panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.button = HeaderIconButton("panel_expand", f"Expand {title}", self)
        self.button.clicked.connect(self.expand_requested.emit)
        self.setAccessibleName(f"{title} (collapsed)")
        self.hide()

    def set_horizontal(self, on: bool) -> None:
        self.horizontal = on
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.button.move(self.width() - STRIP if self.horizontal else 0, 0)

    def paintEvent(self, _e):
        from ..theme import BODY_COMPACT_01, font, t
        p = QPainter(self)
        p.setFont(font(BODY_COMPACT_01))
        p.setPen(QColor(t("text-primary")))
        if self.horizontal:
            p.drawText(QRectF(16, 0, self.width() - 16 - STRIP, STRIP), int(Qt.AlignmentFlag.AlignVCenter), self.title)
        else:
            p.translate(STRIP / 2 + 7, 56)
            p.rotate(90)
            p.drawText(QRectF(0, 0, self.height() - 72, 20), int(Qt.AlignmentFlag.AlignLeft), self.title)
        p.end()


class UpperPanels(QWidget):
    """The upper content area: Elements, Composition setup, Analysis.

    * **wide** - one row: Elements and Composition at their fixed design widths, Analysis takes the rest
      (at least its wide minimum);
    * **stacked** - when the three panels no longer fit, Analysis moves to a second row spanning the full
      width with the taller ``stacked_height`` (brief §19); Elements and Composition keep their fixed sizes,
      left-aligned (they are never stretched to fill the row - 8.png, brief §18).

    ``panels`` are ``(widget, reference, wide_minimum, maximum)``; a widget's own minimum width is its own
    business (Analysis may be narrower when stacked than it is allowed to be in the wide row).

    Collapsing (each panel header's collapse button, Figma Mode=Collapsed): a collapsed panel is replaced by its
    40 px :class:`CollapsedStrip` in the same slot (the panel keeps its state; it is only hidden), and the space
    goes to Analysis, the flexible panel.  A collapsed Analysis is a 40 px strip at the right end of the row, or -
    stacked - a 40 px bar under the first row.

    The breakpoint is not a screen size: it is the width the wide row needs, ``Σ wide minimums + gaps``
    (``wide_minimum``; the fixed Elements and Composition widths plus Analysis' MINIMUM).  No hysteresis: the main
    scroll bar is an overlay, so switching modes never changes the available width and cannot oscillate.  The
    panels are only repositioned - never re-created or re-parented - so their state survives every switch.
    """

    HYSTERESIS = 0
    collapse_changed = Signal(int, bool)

    def __init__(self, panels: list[tuple[QWidget, int, int, int | None]], row_height: int, gap: int,
                 parent=None, stacked_height: int | None = None, titles: list[str] | None = None):
        super().__init__(parent)
        self.panels = panels                        # (widget, reference, wide minimum, maximum)
        self.row_height = row_height
        self.stacked_height = stacked_height or row_height
        self.gap = gap
        self.stacked = False
        self.collapsed: set[int] = set()
        self.strips: list[CollapsedStrip] = []
        titles = titles or [""] * len(panels)
        for i, (w, _ref, _mn, _mx) in enumerate(panels):
            w.setParent(self)
            strip = CollapsedStrip(titles[i], self)
            strip.expand_requested.connect(lambda i=i: self.set_collapsed(i, False))
            self.strips.append(strip)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(row_height)

    # -------------------------------------------------------------- collapse
    def _sync_directions(self) -> None:
        """Collapse / expand icons that show where the panel goes: left / right in the row (Carbon panel icons),
        up / down for the stacked Analysis, which collapses vertically (Carbon row--collapse / row--expand)."""
        last = len(self.panels) - 1
        vertical = self.stacked
        w = self.panels[last][0]
        btns = getattr(w, "collapse_btns", None) or [getattr(w, "collapse_btn", None)]   # the Analysis dock: both
        for btn in btns:
            if btn is not None and hasattr(btn, "set_icon"):
                btn.set_icon("row_collapse" if vertical else "panel_collapse")
        self.strips[last].button.set_icon("row_expand" if vertical else "panel_expand")

    def set_collapsed(self, i: int, on: bool) -> None:
        if (i in self.collapsed) == on:
            return
        if on:
            self.collapsed.add(i)
        else:
            self.collapsed.discard(i)
        self.panels[i][0].setVisible(not on)
        self.strips[i].setVisible(on)
        self.relayout(force=True)
        self.collapse_changed.emit(i, on)

    def is_collapsed(self, i: int) -> bool:
        return i in self.collapsed

    def _spec(self, i: int) -> tuple[int, int, int | None]:
        _w, ref, mn, mx = self.panels[i]
        return (STRIP, STRIP, STRIP) if i in self.collapsed else (ref, mn, mx)

    # -------------------------------------------------------------- sizes
    def row_gaps(self, indices) -> list[int]:
        """Gaps between consecutive panels of one row: 8 px where either neighbour is a (vertical) collapsed strip,
        the 16 px page gap otherwise - decided per boundary, so expanded neighbours keep their 16 px."""
        idx = list(indices)
        return [COLLAPSED_GAP if (a in self.collapsed or b in self.collapsed) else self.gap
                for a, b in zip(idx, idx[1:])]

    def wide_minimum(self) -> int:
        n = len(self.panels)
        return sum(self._spec(i)[1] for i in range(n)) + sum(self.row_gaps(range(n)))

    def stacked_minimum(self) -> int:
        first = range(len(self.panels) - 1)
        return max(sum(self._spec(i)[1] for i in first) + sum(self.row_gaps(first)),
                   self._spec(len(self.panels) - 1)[1])

    def mode_for(self, width: int) -> bool:
        """True = stacked, for ``width`` given the current mode (hysteresis)."""
        need = self.wide_minimum() + (self.HYSTERESIS if self.stacked else 0)
        return width < need

    def minimumSizeHint(self) -> QSize:
        return QSize(self.stacked_minimum(), self.height())

    def sizeHint(self) -> QSize:
        n = len(self.panels)
        return QSize(sum(self._spec(i)[0] for i in range(n)) + sum(self.row_gaps(range(n))), self.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def _place(self, i: int, rect: QRect) -> None:
        w = self.strips[i] if i in self.collapsed else self.panels[i][0]
        w.setGeometry(rect)

    def relayout(self, force: bool = False):
        width = self.width()
        stacked = self.mode_for(width)
        last = len(self.panels) - 1
        analysis_bar = last in self.collapsed
        if stacked != self.stacked or force:
            self.stacked = stacked
            if stacked:
                h = self.row_height + self.gap + (STRIP if analysis_bar else self.stacked_height)
            else:
                h = self.row_height
            self.setFixedHeight(h)
        self.strips[last].set_horizontal(self.stacked and analysis_bar)
        self._sync_directions()
        h = self.row_height
        if self.stacked:
            x = 0
            gaps = self.row_gaps(range(last)) + [0]
            for i in range(last):                       # fixed design widths, left-aligned
                ref = self._spec(i)[0]
                self._place(i, QRect(x, 0, ref, h))
                x += ref + gaps[i]
            self._place(last, QRect(0, h + self.gap, width, STRIP if analysis_bar else self.stacked_height))
        else:
            gaps = self.row_gaps(range(len(self.panels)))
            avail = width - sum(gaps)
            specs = [self._spec(i) for i in range(len(self.panels))]
            widths = distribute(avail, [s[0] for s in specs], [s[1] for s in specs], [s[2] for s in specs])
            gaps.append(0)
            x = 0
            for i, wd in enumerate(widths):
                # every panel collapses towards the left - a collapsed Analysis is the strip right after
                # Composition setup, like the other two (it used to jump to the right end of the row)
                self._place(i, QRect(x, 0, wd, h))
                x += wd + gaps[i]
