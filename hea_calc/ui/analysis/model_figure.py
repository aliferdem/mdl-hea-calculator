"""Model figure of Model details (2026-10-28): draws a :class:`hea_calc.core.analysis.model_figures.Figure` in the
Carbon Charts visual language - plain axes with tick labels in ``text-secondary``, light grid lines, class regions as
10 % tints of the scientific class colours, dashed threshold lines with their values, points in the class colours
(``plot.class_color``: SS, MP, IM, SS+IM, MG - never UI status colours), a legend, and the analysed composition as a
star.  Light and dark follow the theme; ``render_to`` also writes PNG / SVG exports."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.analysis.model_figures import Figure
from ..theme import BODY_COMPACT_01, THEME, font, t
from .plot import categorical, class_color

PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 12, 44
LEGEND_H = 24


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10)), key=lambda s: abs(s - raw))
    first = math.ceil(lo / step) * step
    out, v = [], first
    while v <= hi + 1e-9 * step:
        out.append(round(v, 10))
        v += step
    return out


def _fmt(v: float) -> str:
    return f"{v:g}".replace("-", "−")


class ModelFigureWidget(QWidget):
    def __init__(self, fig: Figure, current: dict | None = None, parent=None):
        super().__init__(parent)
        self.fig = fig
        self.current = current or {}
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{fig.model} figure: {fig.title}")
        self.setAccessibleDescription(fig.caption)
        THEME.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(520, 300)

    # -------------------------------------------------------------- geometry
    def ranges(self) -> tuple[tuple[float, float], tuple[float, float]]:
        f = self.fig
        xs = [p["x"] for p in f.points]
        ys = [p["y"] for p in f.points if p["y"] is not None]
        cx, cy = self.current.get("x"), self.current.get("y")
        xs += [cx] if isinstance(cx, (int, float)) else []
        ys += [cy] if isinstance(cy, (int, float)) else []
        for ln in f.lines:
            if ln.kind == "v":
                xs.append(ln.value)
            elif ln.kind == "h":
                ys.append(ln.value)
            elif ln.kind == "curve":
                xs += ln.xs
                ys += ln.ys
        if f.x_range:
            xr = f.x_range
        elif f.log_x:
            pos = [x for x in xs if x > 0] or [1.0]
            xr = (10 ** math.floor(math.log10(min(pos))), 10 ** math.ceil(math.log10(max(pos))))
        else:
            lo, hi = (min(xs), max(xs)) if xs else (0.0, 1.0)
            m = (hi - lo) * 0.06 or 0.5
            xr = (lo - m, hi + m)
        if f.kind == "strip":
            yr = (0.0, 1.0)
        elif f.y_range:
            yr = f.y_range
        else:
            lo, hi = (min(ys), max(ys)) if ys else (0.0, 1.0)
            if f.log_y:
                lo, hi = max(min(y for y in ys if y > 0), 1e-3), max(hi, 1e-3)
                yr = (10 ** math.floor(math.log10(lo)), 10 ** math.ceil(math.log10(hi)))
            else:
                m = (hi - lo) * 0.08 or 0.5
                yr = (lo - m, hi + m)
        if f.kind == "scatter" and any(ln.kind == "diag" for ln in f.lines) and not (f.x_range or f.y_range):
            lo, hi = min(xr[0], yr[0]), max(xr[1], yr[1])
            xr = yr = (lo, hi)
        return xr, yr

    def render_to(self, p: QPainter, w: float, h: float) -> None:
        f = self.fig
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fnt = font(BODY_COMPACT_01)
        fnt.setPixelSize(11)
        p.setFont(fnt)
        fm = QFontMetricsF(fnt)
        (x0, x1), (y0, y1) = self.ranges()
        plot = QRectF(PAD_L, PAD_T, max(10.0, w - PAD_L - PAD_R), max(10.0, h - PAD_T - PAD_B - LEGEND_H))
        log = f.log_y and f.kind != "strip"

        def X(v):                                                    # noqa: N802
            if f.log_x:
                v, a, b = math.log10(max(v, 1e-12)), math.log10(x0), math.log10(x1)
                return plot.left() + (v - a) / (b - a) * plot.width()
            return plot.left() + (v - x0) / (x1 - x0) * plot.width()

        def Y(v):                                                    # noqa: N802
            if log:
                v = math.log10(max(v, 1e-12))
                a, b = math.log10(y0), math.log10(y1)
            else:
                a, b = y0, y1
            return plot.bottom() - (v - a) / (b - a) * plot.height()
        # class regions (10 % tints)
        for r in f.regions:
            c = QColor(class_color(r.cls))
            c.setAlphaF(0.10)
            xa = X(r.x0) if r.x0 is not None else plot.left()
            xb = X(r.x1) if r.x1 is not None else plot.right()
            if f.kind == "strip":
                ya, yb = plot.top(), plot.bottom()
            else:
                ya = Y(r.y1) if r.y1 is not None else plot.top()
                yb = Y(r.y0) if r.y0 is not None else plot.bottom()
            p.fillRect(QRectF(QPointF(min(xa, xb), min(ya, yb)), QPointF(max(xa, xb), max(ya, yb))).intersected(plot), c)
        # grid and ticks
        grid = QColor(t("border-subtle-01"))
        sec = QColor(t("text-secondary"))
        xticks = ([10 ** e for e in range(int(math.log10(x0)), int(math.log10(x1)) + 1)] if f.log_x
                  else _nice_ticks(x0, x1))
        for v in xticks:
            x = X(v)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(sec)
            p.drawText(QRectF(x - 30, plot.bottom() + 4, 60, 14), int(Qt.AlignmentFlag.AlignHCenter), _fmt(v))
        if f.kind != "strip":
            yticks = ([10 ** e for e in range(int(math.log10(y0)), int(math.log10(y1)) + 1)] if log
                      else _nice_ticks(y0, y1))
            for v in yticks:
                y = Y(v)
                p.setPen(QPen(grid, 1))
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
                p.setPen(sec)
                p.drawText(QRectF(0, y - 7, PAD_L - 6, 14), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                           _fmt(v))
        p.setPen(QPen(QColor(t("border-strong-01")), 1))
        p.drawLine(plot.bottomLeft(), plot.bottomRight())
        p.drawLine(plot.bottomLeft(), plot.topLeft())
        p.setPen(sec)
        p.drawText(QRectF(plot.left(), plot.bottom() + 18, plot.width(), 16), int(Qt.AlignmentFlag.AlignHCenter),
                   f.x_label)
        if f.y_label:
            p.save()
            p.translate(12, plot.center().y())
            p.rotate(-90)
            p.drawText(QRectF(-plot.height() / 2, -8, plot.height(), 16), int(Qt.AlignmentFlag.AlignHCenter), f.y_label)
            p.restore()
        # thresholds (dashed) and curves
        p.save()
        p.setClipRect(plot)
        thr = QPen(QColor(t("text-secondary")), 1.2, Qt.PenStyle.DashLine)
        ci = vi = hi = 0
        for ln in f.lines:
            if ln.kind == "curve":
                pen = QPen(QColor(categorical(ci)), 2)
                ci += 1
                path = QPainterPath(QPointF(X(ln.xs[0]), Y(ln.ys[0])))
                for xv, yv in zip(ln.xs[1:], ln.ys[1:]):
                    path.lineTo(X(xv), Y(yv))
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
                continue
            p.setPen(thr)
            # labels alternate ends (top / bottom, right / left) so close thresholds never overlap
            if ln.kind == "v":
                p.drawLine(QPointF(X(ln.value), plot.top()), QPointF(X(ln.value), plot.bottom()))
                p.drawText(QPointF(X(ln.value) + 3, plot.top() + 11 if vi % 2 == 0 else plot.bottom() - 4), ln.label)
                vi += 1
            elif ln.kind == "h":
                p.drawLine(QPointF(plot.left(), Y(ln.value)), QPointF(plot.right(), Y(ln.value)))
                lx = plot.right() - fm.horizontalAdvance(ln.label) - 3 if hi % 2 == 0 else plot.left() + 3
                p.drawText(QPointF(lx, Y(ln.value) - 3 if hi % 2 == 0 else Y(ln.value) + 12), ln.label)
                hi += 1
            elif ln.kind == "diag":
                p.drawLine(QPointF(X(x0), Y(x0)), QPointF(X(x1), Y(x1)))
                p.drawText(QPointF(X(x1) - fm.horizontalAdvance(ln.label) - 4, Y(x1) + 14), ln.label)
        # points
        n = max(1, len(f.points))
        for i, pt in enumerate(f.points):
            if f.kind == "strip":
                y = plot.top() + plot.height() * (0.15 + 0.7 * ((i * 0.618) % 1.0))    # deterministic spread
            else:
                if pt["y"] is None:
                    continue
                y = Y(pt["y"])
            c = QColor(class_color(pt["cls"])) if pt["cls"] else QColor(t("text-secondary"))
            p.setPen(QPen(QColor(t("layer-01")), 0.8))
            p.setBrush(c)
            p.drawEllipse(QPointF(X(pt["x"]), y), 3.5, 3.5)
            if f.kind == "strip" and n <= 12:
                p.setPen(sec)
                p.drawText(QPointF(X(pt["x"]) + 6, y + 4), pt["label"])
        # the analysed composition
        cx, cy = self.current.get("x"), self.current.get("y")
        if isinstance(cx, (int, float)) and (f.kind == "strip" or isinstance(cy, (int, float))):
            y = plot.center().y() if f.kind == "strip" else Y(cy)
            star = QPolygonF([QPointF(X(cx) + 7 * math.cos(math.pi / 2 + k * math.pi / 5) * (1 if k % 2 == 0 else 0.45),
                                      y - 7 * math.sin(math.pi / 2 + k * math.pi / 5) * (1 if k % 2 == 0 else 0.45))
                              for k in range(10)])
            p.setPen(QPen(QColor(t("layer-01")), 1))
            p.setBrush(QColor(t("text-primary")))
            p.drawPolygon(star)
        p.restore()
        # legend
        items = []
        for c in dict.fromkeys(pt["cls"] for pt in f.points):
            items.append((c or "Not classified", QColor(class_color(c)) if c else QColor(t("text-secondary")), "dot"))
        if isinstance(cx, (int, float)):
            items.append(("This composition", QColor(t("text-primary")), "star"))
        ci = 0
        for ln in f.lines:
            if ln.kind == "curve":
                items.append((ln.label, QColor(categorical(ci)), "line"))
                ci += 1
        x = plot.left()
        ly = h - LEGEND_H / 2
        for text, col, kind in items:
            if kind == "line":
                p.setPen(QPen(col, 2))
                p.drawLine(QPointF(x, ly), QPointF(x + 12, ly))
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                p.drawEllipse(QPointF(x + 5, ly), 4, 4)
            p.setPen(QColor(t("text-primary")))
            p.drawText(QPointF(x + 16, ly + 4), text)
            x += 16 + fm.horizontalAdvance(text) + 16

    def paintEvent(self, _e):
        p = QPainter(self)
        self.render_to(p, self.width(), self.height())
        p.end()

    def export(self, path: str, w: int = 900, h: int = 520) -> None:
        """PNG (2x) or SVG (vector) of the figure, in the current theme."""
        if path.lower().endswith(".svg"):
            from PySide6.QtSvg import QSvgGenerator
            gen = QSvgGenerator()
            gen.setFileName(path)
            gen.setSize(QSize(w, h))
            gen.setViewBox(QRectF(0, 0, w, h))
            gen.setTitle(f"{self.fig.model} - {self.fig.title}")
            gen.setDescription(self.fig.caption + " Source: " + self.fig.source)
            p = QPainter(gen)
            p.fillRect(QRectF(0, 0, w, h), QColor(t("layer-01")))
            self.render_to(p, w, h)
            p.end()
            return
        from PySide6.QtGui import QImage
        img = QImage(w * 2, h * 2, QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(2)
        img.fill(QColor(t("layer-01")))
        p = QPainter(img)
        self.render_to(p, w, h)
        p.end()
        img.save(path)
