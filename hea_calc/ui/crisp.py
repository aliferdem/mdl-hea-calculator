"""Device-pixel-snapped painting for crisp borders under fractional device pixel ratios.

At Windows 125 % / 150 % scaling Qt paints with a fractional devicePixelRatio (1.25 / 1.5) and
every child widget sits at a fractional *physical* offset (a tile at logical x = 31 starts at
physical x = 38.75).  A 2 px logical stroke is then 2.5 physical pixels wide and the rasteriser
rounds each edge independently, so a frame drawn with ``QPen(2)`` or a QSS ``border: 2px``
comes out 2 px on some sides and 3 px on others depending on where the widget happens to sit -
measured on the periodic-table tiles: top 2 / bottom 3 at DPR 1.25.

The helpers here paint in **device pixels** instead:

1. the logical rectangle is mapped through the painter's full device transform (so the widget's
   fractional offset is included);
2. each edge is snapped to the nearest device-pixel boundary - the same rule for every widget, so
   neighbouring widgets still meet without gaps or overlaps;
3. stroke widths are converted once, ``floor(width × dpr)`` with a minimum of one device pixel
   (the convention browsers use for borders: 2 px → 2 / 2 / 3 device px at DPR 1 / 1.25 / 1.5);
4. square frames are filled as four integer rectangles (no antialiasing, nothing to round);
   rounded frames are filled as the difference of two rounded paths built on the snapped
   rectangle, so all four sides and all four corners are identical.

Every function takes logical coordinates; callers never deal with the device pixel ratio.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QTransform


def _snap(v: float) -> int:
    # floor(v + 0.5) - not Python's banker's round(), so x.5 always goes the same way
    return math.floor(v + 0.5)


def device_px(painter: QPainter, logical: float) -> int:
    """A logical stroke width in whole device pixels (floor, minimum 1)."""
    scale = painter.deviceTransform().m11() or 1.0
    return max(1, math.floor(logical * abs(scale) + 1e-6))


def device_inset(painter: QPainter, logical: float) -> float:
    """Logical distance equal to ``device_px(logical)`` - insets a nested frame flush inside an
    outer one without a gap or overlap at any device pixel ratio."""
    scale = abs(painter.deviceTransform().m11() or 1.0)
    return device_px(painter, logical) / scale


def device_rect(painter: QPainter, rect: QRectF | QRect) -> QRect:
    """``rect`` (logical) as a snapped rectangle in device pixels."""
    r = QRectF(rect)
    m = painter.deviceTransform()
    p0 = m.map(QPointF(r.left(), r.top()))
    p1 = m.map(QPointF(r.right(), r.bottom()))  # QRectF.right() is left + width (exclusive edge)
    x0, x1 = sorted((_snap(p0.x()), _snap(p1.x())))
    y0, y1 = sorted((_snap(p0.y()), _snap(p1.y())))
    return QRect(x0, y0, x1 - x0, y1 - y0)


class _DeviceSpace:
    """Context manager: paint in device pixels (identity device transform, no antialiasing)."""

    def __init__(self, painter: QPainter, antialias: bool = False):
        self.p = painter
        self.aa = antialias

    def __enter__(self) -> QPainter:
        p = self.p
        p.save()
        inv, ok = p.deviceTransform().inverted()
        # world' = device⁻¹ · world makes the combined transform the identity (see module doc)
        p.setWorldTransform((inv * p.worldTransform()) if ok else QTransform())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, self.aa)
        p.setPen(QColor(0, 0, 0, 0))
        return p

    def __exit__(self, *_):
        self.p.restore()


def fill_rect(painter: QPainter, rect: QRectF | QRect, color) -> None:
    """Fill ``rect`` with edges snapped to device pixels."""
    d = device_rect(painter, rect)
    with _DeviceSpace(painter) as p:
        p.fillRect(d, QColor(color))


def frame(painter: QPainter, rect: QRectF | QRect, width: float, color, radius: float = 0.0) -> None:
    """Inside frame of ``width`` logical px drawn within ``rect`` - identical on all four sides.

    ``radius`` (logical) rounds the outer corners; the inner corners follow at ``radius - width``.
    """
    d = device_rect(painter, rect)
    t = device_px(painter, width)
    col = QColor(color)
    if d.width() <= 0 or d.height() <= 0:
        return
    t = min(t, d.width() // 2, d.height() // 2) or 1
    if radius <= 0:
        with _DeviceSpace(painter) as p:
            x, y, w, h = d.x(), d.y(), d.width(), d.height()
            p.fillRect(QRect(x, y, w, t), col)                    # top
            p.fillRect(QRect(x, y + h - t, w, t), col)            # bottom
            p.fillRect(QRect(x, y + t, t, h - 2 * t), col)        # left
            p.fillRect(QRect(x + w - t, y + t, t, h - 2 * t), col)  # right
        return
    r = radius * abs(painter.deviceTransform().m11() or 1.0)
    outer = QPainterPath()
    outer.addRoundedRect(QRectF(d), r, r)
    inner = QPainterPath()
    inner.addRoundedRect(QRectF(d).adjusted(t, t, -t, -t), max(r - t, 0.0), max(r - t, 0.0))
    with _DeviceSpace(painter, antialias=True) as p:
        p.fillPath(outer.subtracted(inner), col)


def fill_rounded(painter: QPainter, rect: QRectF | QRect, radius: float, color) -> None:
    """Rounded fill on the snapped rectangle (antialiased corners, straight edges on pixel rows)."""
    d = device_rect(painter, rect)
    r = radius * abs(painter.deviceTransform().m11() or 1.0)
    path = QPainterPath()
    path.addRoundedRect(QRectF(d), r, r)
    with _DeviceSpace(painter, antialias=True) as p:
        p.fillPath(path, QColor(color))


def hline(painter: QPainter, x0: float, x1: float, y: float, color, width: float = 1.0) -> None:
    """Horizontal rule whose *top* edge is at logical ``y``, ``width`` logical px thick."""
    m = painter.deviceTransform()
    a = m.map(QPointF(x0, y))
    b = m.map(QPointF(x1, y))
    t = device_px(painter, width)
    xa, xb = sorted((_snap(a.x()), _snap(b.x())))
    with _DeviceSpace(painter) as p:
        p.fillRect(QRect(xa, _snap(a.y()), xb - xa, t), QColor(color))


def hline_bottom(painter: QPainter, rect: QRectF | QRect, color, width: float = 1.0) -> None:
    """Rule along the inside bottom edge of ``rect`` (row separators, field underlines)."""
    d = device_rect(painter, rect)
    t = device_px(painter, width)
    with _DeviceSpace(painter) as p:
        p.fillRect(QRect(d.x(), d.y() + d.height() - t, d.width(), t), QColor(color))


def vline(painter: QPainter, x: float, y0: float, y1: float, color, width: float = 1.0) -> None:
    """Vertical rule whose *left* edge is at logical ``x``."""
    m = painter.deviceTransform()
    a = m.map(QPointF(x, y0))
    b = m.map(QPointF(x, y1))
    t = device_px(painter, width)
    ya, yb = sorted((_snap(a.y()), _snap(b.y())))
    with _DeviceSpace(painter) as p:
        p.fillRect(QRect(_snap(a.x()), ya, t, yb - ya), QColor(color))
