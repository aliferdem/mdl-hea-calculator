"""Scientific plot widget (custom QPainter, ``ANALYSIS_IMPLEMENTATION_PLAN.md`` section 6).

One widget draws every v1 plot type from compact arrays delivered by the query layer: scatter (RAW /
SAMPLED), binned 2-D, ordered line (+ model strip), histogram, box plot, two-parameter heatmap, stacked
and grouped categorical bars.  There is no QObject per point: points are painted into a cached image and
hit-tested through a uniform screen grid.  Missing values never reach the widget (the query layer omits
and counts them).  Every plot shows its representation tag; the same painter renders exports (SVG / PNG)
and report images, so what is exported is what is shown.

Interaction (plotting spec section 5): hover shows the Carbon chart tooltip (``ChartTooltip``: the point's
name, its values on both axes and its colour group); click selects (visual, inspector); double-click asks for
"Analyse composition"; wheel zoom (Ctrl+wheel when ``ctrl_zoom``); middle- or right-button drag pans (no pan
mode, no box / lasso selection - brief 2026-10-16 §27, §28); Reset axes; ←/→ move between points in data
order, Enter inspects, Esc clears the selection.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.analysis import models as MD
from ...core.analysis.metrics import format_value
from ...core.analysis.queries import dim_label as dim_label_text, dim_value_text
from ...core.engine import MODEL_KEYS, NA
from ...core.results import format_number
from .. import crisp
from ..theme import BODY_COMPACT_01, HEADING_COMPACT_01, LABEL_01, THEME, font, t
from .widgets import paint_html, plain_text

# ---------------------------------------------------------------------- colours
CLASS_MARK_DARK = {"SS": "#a7f0ba", "MP": "#ffd6e8", "IM": "#ffd7d9", "SS+IM": "#d0e2ff", "MG": "#e8daff",
                   NA: "#8d8d8d", "FCC": "#dde1e6", "BCC": "#a8a8a8", "BCC + FCC": "#c6c6c6"}
CLASS_MARK_LIGHT = {"SS": "#0e6027", "MP": "#9f1853", "IM": "#a2191f", "SS+IM": "#0043ce", "MG": "#6929c4",
                    NA: "#8d8d8d", "FCC": "#343a3f", "BCC": "#697077", "BCC + FCC": "#4d5358"}
CATEGORICAL_DARK = ["#8a3ffc", "#33b1ff", "#007d79", "#ff7eb6", "#fa4d56", "#fff1f1", "#6fdc8c", "#4589ff",
                    "#d12771", "#d2a106", "#08bdba", "#bae6ff", "#ba4e00", "#d4bbff"]
CATEGORICAL_LIGHT = ["#6929c4", "#1192e8", "#005d5d", "#9f1853", "#fa4d56", "#570408", "#198038", "#002d9c",
                     "#ee538b", "#b28600", "#009d9a", "#012749", "#8a3800", "#a56eff"]
SEQUENTIAL = ["#edf5ff", "#d0e2ff", "#a6c8ff", "#78a9ff", "#4589ff", "#0f62fe", "#0043ce", "#002d9c", "#001d6c",
              "#001141"]
STATUS_COLORS = {"In domain": "#8d8d8d", "Extrapolated": "#c6c6c6", "Flagged data": "#f1c21b",
                 "Not available": "#525252"}
MAX_CATEGORIES = 10           # > 10 families: top 9 + "Other families"

# Published thresholds drawn as reference lines when the coloured model uses that metric (display only;
# each is the number printed by the model's publication).  Each label states the side the model accepts and
# whether the boundary is inclusive, exactly as ``models.threshold_text`` / the engine rule (brief §26):
# "SS: δ ≤ 6.6 %" reads "solid solution where δ ≤ 6.6 %".
REFERENCE_LINES = {
    "M1": {"omega": [(1.1, "SS: Ω ≥ 1.1")], "delta_cn12": [(6.6, "SS: δCN12 ≤ 6.6 %")]},
    "M2": {"delta": [(6.6, "SS: δ ≤ 6.6 %")], "dhmix": [(-11.6, "SS: ΔHmix ≥ −11.6"), (3.2, "SS: ΔHmix ≤ 3.2")]},
    "M3": {"gamma": [(1.175, "SS: γ < 1.175")]},
    "M4": {"lambda": [(0.96, "SS: Λ > 0.96"), (0.24, "IM: Λ < 0.24")]},
    "M5": {"phi_ye": [(20.0, "SS: φ ≥ 20")]},
    "M8": {"phi_king": [(1.0, "SS: Φ ≥ 1")]},
}
VEC_RULE = [(8.0, "FCC ≥ 8.0"), (6.87, "BCC < 6.87")]
# Carbon Charts thresholds (CORRECT_TRESHOLD): a dashed line in the threshold colour with a label filled in the
# same colour.  Colours from the Carbon palette, kept apart from the model-class marks (green / magenta / red /
# blue / purple); assigned in drawing order.
THRESHOLD_COLORS = ["#1192e8", "#ff832b", "#f1c21b", "#009d9a"]


def on_color(fill: str) -> str:
    """Text colour on a filled label: Carbon $text-on-color or Gray 100, whichever reads (WCAG luminance)."""
    c = QColor(fill)

    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())
    return "#161616" if lum > 0.179 else "#ffffff"


def class_color(label: str) -> str:
    return (CLASS_MARK_DARK if THEME.name == "dark" else CLASS_MARK_LIGHT).get(label, "#8d8d8d")


def categorical(i: int) -> str:
    pal = CATEGORICAL_DARK if THEME.name == "dark" else CATEGORICAL_LIGHT
    return pal[i % len(pal)]


def sequential(f: float) -> str:
    """Colour for f in 0..1 (high values light in the dark theme)."""
    pal = SEQUENTIAL if THEME.name == "light" else list(reversed(SEQUENTIAL))
    f = 0.0 if f != f else max(0.0, min(1.0, f))
    return pal[min(len(pal) - 1, int(f * len(pal)))]


# ---------------------------------------------------------------------- ticks
def nice_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return [lo]
    raw = (hi - lo) / max(1, target)
    k = math.floor(math.log10(raw))
    step = next((m * 10 ** k for m in (1, 2, 2.5, 5, 10) if m * 10 ** k >= raw), 10 ** (k + 1))
    first = math.ceil(lo / step - 1e-9) * step
    out, v = [], first
    while v <= hi + step * 1e-9:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


def tick_text(v: float, ticks: list[float]) -> str:
    if len(ticks) > 1:
        step = abs(ticks[1] - ticks[0])
        dec = max(0, -int(math.floor(math.log10(step))) if step < 1 else 0)
        if step < 1 and abs(step * 10 ** dec - round(step * 10 ** dec)) > 1e-6:
            dec += 1
    else:
        dec = 2
    return format_number(v, dec)


class PlotSpec:
    """Everything a plot needs to draw itself (built by the collection view from query results)."""

    def __init__(self, kind: str, data: dict, *, x=None, y=None, color: str = "none", color_metric=None,
                 title: str = "", tag: str = "", caption: str = "", legend_title: str = "", model: str | None = None,
                 thresholds: bool = True, log_x: bool = False, log_y: bool = False, hollow: bool = False,
                 extra: dict | None = None):
        self.kind, self.data = kind, data
        self.x, self.y = x, y
        self.color, self.color_metric = color, color_metric
        self.title, self.tag, self.caption, self.legend_title = title, tag, caption, legend_title
        self.model = model
        self.thresholds = thresholds
        self.log_x, self.log_y = log_x, log_y
        self.hollow = hollow
        self.extra = extra or {}


class PlotWidget(QWidget):
    """See module docstring."""

    point_clicked = Signal(object)          # result id or None
    point_activated = Signal(object)        # result id (double-click / Enter): "Analyse composition"
    view_changed = Signal(object)           # (x0, x1, y0, y1) zoom window
    category_toggled = Signal(object)

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.spec: PlotSpec | None = None
        self.compact = compact
        self.legend_mode = "overlay"        # overlay | column | row
        self.ctrl_zoom = False
        self.window: tuple | None = None    # zoom window (data coords) or None = data limits
        self.hidden: set = set()            # categories hidden from the drawing (legend toggle)
        self.selection: set = set()
        self.active_id: int | None = None     # the active composition, ringed when it is in the plot
        self.focus_index = -1
        self.dim = False                    # previous plot shown dimmed while a query runs
        self.message = ""
        self._cache: QImage | None = None
        self._grid: dict = {}
        self._screen: list = []             # (sx, sy, index) of drawn points
        self._press: QPointF | None = None
        self._pan_start = None              # (press position, window) while a middle / right drag pans
        self._hover = -1
        self.tip = ChartTooltip(self)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(180)
        self.setAccessibleName("Plot")
        THEME.changed.connect(self._invalidate)

    # ================================================================== data
    def set_spec(self, spec: PlotSpec | None, keep_view: bool = False) -> None:
        self.spec = spec
        self._place_tag_info()
        if not keep_view:
            self.window = None
        self.hidden = set()
        self.focus_index = -1
        self._invalidate()
        if spec is not None:
            self.setAccessibleName(plain_text(spec.title or "Plot") + (f" · {spec.tag}" if spec.tag else ""))

    def set_selection(self, ids) -> None:
        self.selection = set(ids or ())
        self.update()

    def reset_view(self) -> None:
        self.window = None
        self._invalidate()
        self.view_changed.emit(None)

    def zoom(self, factor: float, center: QPointF | None = None) -> None:
        lim = self._limits()
        if lim is None:
            return
        x0, x1, y0, y1 = self.window or lim
        cx = (x0 + x1) / 2 if center is None else center.x()
        cy = (y0 + y1) / 2 if center is None else center.y()
        self.window = (cx - (cx - x0) * factor, cx + (x1 - cx) * factor, cy - (cy - y0) * factor,
                       cy + (y1 - cy) * factor)
        self._invalidate()
        self.view_changed.emit(self.window)

    def _invalidate(self, *_):
        self._cache = None
        self._jobs = None
        self.update()

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(640, 320)

    # ================================================================== geometry
    def _frame_rect(self, w: float, h: float) -> QRectF:
        """Data area inside a widget of w x h (room for axes, titles, tag and legend)."""
        left = 72 if not self.compact else 64
        top = 40
        bottom = 52
        right = 16
        if self.spec is not None and self.legend_mode == "column" and self._legend_items():
            right = 176
        return QRectF(left, top, max(10.0, w - left - right), max(10.0, h - top - bottom))

    def _limits(self):
        s = self.spec
        if s is None:
            return None
        d = s.data
        if s.kind in ("scatter",):
            xs, ys = d.get("x", ()), d.get("y", ())
            if not len(xs):
                return None
            return _pad(min(xs), max(xs), s.log_x) + _pad(min(ys), max(ys), s.log_y)
        if s.kind == "binned":
            (x0, x1), (y0, y1) = d["x"], d["y"]
            if x0 is None:
                return None
            return (x0, x1, y0, y1)
        if s.kind == "line":
            xs = [v for v in d.get("x", []) if v is not None]
            ys = [v for v in d["y"].get(s.y.id, []) if v is not None] if s.y else []
            if not xs or not ys:
                return None
            lo, hi = min(ys), max(ys)
            if s.extra.get("vec_rule"):
                lo, hi = min(lo, 6.5), max(hi, 8.5)
            return _pad(min(xs), max(xs), False, 0.02) + _pad(lo, hi, False)
        if s.kind == "histogram":
            edges, counts = d.get("edges", []), d.get("counts", [])
            if not edges:
                return None
            return (edges[0], edges[-1], 0.0, max(counts) * 1.08 if counts else 1.0)
        return None

    def _to_screen(self, rect: QRectF, win) -> tuple:
        x0, x1, y0, y1 = win
        s = self.spec
        lx, ly = s.log_x, s.log_y
        fx0, fx1 = (_log(x0), _log(x1)) if lx else (x0, x1)
        fy0, fy1 = (_log(y0), _log(y1)) if ly else (y0, y1)
        sx = rect.width() / ((fx1 - fx0) or 1.0)
        sy = rect.height() / ((fy1 - fy0) or 1.0)

        def fx(v):
            return rect.left() + ((_log(v) if lx else v) - fx0) * sx

        def fy(v):
            return rect.bottom() - ((_log(v) if ly else v) - fy0) * sy

        def inv(px, py):
            vx = fx0 + (px - rect.left()) / sx
            vy = fy0 + (rect.bottom() - py) / sy
            return (10 ** vx if lx else vx), (10 ** vy if ly else vy)
        return fx, fy, inv

    # ================================================================== painting
    def paintEvent(self, _e):
        p = QPainter(self)
        self.render_to(p, self.width(), self.height(), interactive=True)
        p.end()

    def render_to(self, p: QPainter, w: float, h: float, interactive: bool = False) -> None:
        """Draw the whole plot (also used for SVG / PNG export and report images)."""
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.spec
        if s is None:
            return
        if self.dim and interactive:
            p.setOpacity(0.4)
        kind = s.kind
        if kind in ("scatter", "binned", "line", "histogram"):
            self._paint_xy(p, w, h, interactive)
        elif kind == "box":
            self._paint_box(p, w, h)
        elif kind == "heatmap":
            self._paint_heatmap(p, w, h)
        elif kind in ("bars_stacked", "bars_grouped"):
            self._paint_bars(p, w, h)
        p.setOpacity(1.0)
        if s.tag:
            self._paint_tag(p, s.tag)
        if s.caption and not (self.legend_mode == "row" and s.caption.startswith("0 omitted")):
            p.setFont(font(LABEL_01))
            p.setPen(QColor(t("text-secondary")))
            p.drawText(QRectF(0, h - 18, w - 4, 18), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       s.caption)

    def tag_width(self) -> float:
        from PySide6.QtGui import QFontMetricsF
        return QFontMetricsF(font(LABEL_01)).horizontalAdvance(self.spec.tag) + 16 if self.spec and self.spec.tag else 0

    def _place_tag_info(self) -> None:
        """SAMPLED / BINNED tags carry a 16 px Toggletip trigger 4 px after the tag (design guide 5.7)."""
        from .widgets import rich
        info = getattr(self, "_tag_info", None)
        s = self.spec
        text = s.extra.get("tag_info", "") if s is not None else ""
        if not text:
            if info is not None:
                info.hide()
            return
        if info is None:
            from ..widgets.tooltip import InfoButton
            info = self._tag_info = InfoButton("", self, title="Plot representation")
        info.tip_text = rich(text)
        info.move(int(12 + self.tag_width() + 4), 9)
        info.show()
        info.raise_()

    def _paint_tag(self, p: QPainter, text: str) -> None:
        f = font(LABEL_01)
        p.setFont(f)
        from PySide6.QtGui import QFontMetricsF
        tw = QFontMetricsF(f).horizontalAdvance(text) + 16
        r = QRectF(12, 8, tw, 18)
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(QPen(QColor(t("border-strong-01")), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(QColor(t("text-secondary")))
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), text)

    # ------------------------------------------------------------------ x/y plots
    def _paint_axes(self, p, rect: QRectF, win, fx, fy, x_title: str, y_title: str):
        x0, x1, y0, y1 = win
        p.setFont(font(LABEL_01))
        grid = QColor(t("border-subtle-01"))
        txt = QColor(t("text-secondary"))
        xt = nice_ticks(x0, x1, max(4, int(rect.width() / 70))) if not self.spec.log_x else _log_ticks(x0, x1)
        yt = nice_ticks(y0, y1, max(3, int(rect.height() / 36))) if not self.spec.log_y else _log_ticks(y0, y1)
        for v in xt:
            x = fx(v)
            if rect.left() - 0.5 <= x <= rect.right() + 0.5:
                crisp.vline(p, x, rect.top(), rect.bottom(), grid)
                p.setPen(txt)
                p.drawText(QRectF(x - 40, rect.bottom() + 4, 80, 16), int(Qt.AlignmentFlag.AlignHCenter),
                           tick_text(v, xt))
        for v in yt:
            y = fy(v)
            if rect.top() - 0.5 <= y <= rect.bottom() + 0.5:
                crisp.hline(p, rect.left(), rect.right(), y, grid)
                p.setPen(txt)
                p.drawText(QRectF(0, y - 8, rect.left() - 6, 16),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), tick_text(v, yt))
        axis = t("border-strong-01")
        crisp.hline(p, rect.left(), rect.right(), rect.bottom(), axis)
        crisp.vline(p, rect.left(), rect.top(), rect.bottom(), axis)
        paint_html(p, QRectF(rect.left(), rect.bottom() + 22, rect.width(), 20), x_title, LABEL_01, "text-secondary",
                   Qt.AlignmentFlag.AlignHCenter)
        p.save()
        p.translate(14, rect.center().y())
        p.rotate(-90)
        paint_html(p, QRectF(-rect.height() / 2, -10, rect.height(), 20), y_title, LABEL_01, "text-secondary",
                   Qt.AlignmentFlag.AlignHCenter)
        p.restore()

    def _paint_refs(self, p, rect, fx, fy, win):
        s = self.spec
        lines = []
        if s.thresholds and s.model and s.model in REFERENCE_LINES:
            refs = REFERENCE_LINES[s.model]
            if s.x is not None:
                lines += [("x", v, lab) for v, lab in refs.get(s.x.id, [])]
            if s.y is not None:
                lines += [("y", v, lab) for v, lab in refs.get(s.y.id, [])]
        if s.extra.get("vec_rule") and s.y is not None and s.y.id == "vec":
            lines += [("y", v, lab) for v, lab in VEC_RULE]
        x0, x1, y0, y1 = win
        p.setFont(font(LABEL_01))
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(p.font())
        self._threshold_labels = []
        for k, (axis, v, lab) in enumerate(lines):
            col = THRESHOLD_COLORS[k % len(THRESHOLD_COLORS)]
            pen = QPen(QColor(col), 1.5, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([3, 2])
            tw = fm.horizontalAdvance(lab) + 12
            if axis == "x" and x0 <= v <= x1:
                x = fx(v)
                p.setPen(pen)
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                box = QRectF(x - tw / 2, rect.top() + 4, tw, 18)
            elif axis == "y" and y0 <= v <= y1:
                y = fy(v)
                p.setPen(pen)
                p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                box = QRectF(rect.right() - tw - 8, y - 9, tw, 18)
            else:
                continue
            box.moveLeft(max(rect.left() + 1, min(rect.right() - tw - 1, box.left())))
            p.fillRect(box, QColor(col))
            p.setPen(QColor(on_color(col)))
            p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), lab)
            self._threshold_labels.append((box, lab, col))
        return lines

    def _paint_xy(self, p, w, h, interactive):
        s = self.spec
        lim = self._limits()
        rect = self._frame_rect(w, h)
        if lim is None:
            return
        win = self.window or lim
        fx, fy, _inv = self._to_screen(rect, win)
        xt = s.x.axis_title() if s.x is not None else ""
        yt = s.y.axis_title() if s.y is not None else "Results"
        if s.kind == "histogram":
            yt = "Number of results"
        self._paint_axes(p, rect, win, fx, fy, xt, yt)
        p.save()
        p.setClipRect(rect.adjusted(-6, -6, 6, 6))
        if s.kind == "scatter":
            self._paint_points(p, rect, win, fx, fy, interactive, w, h)
        elif s.kind == "binned":
            self._paint_bins(p, rect, fx, fy)
        elif s.kind == "line":
            self._paint_line(p, rect, fx, fy)
        elif s.kind == "histogram":
            self._paint_hist(p, rect, fx, fy)
        p.restore()
        self._paint_refs(p, rect, fx, fy, win)
        self._paint_legend(p, w, h, rect)
        if interactive:
            self._paint_overlays(p, rect, fx, fy)

    # ---- scatter
    def _categories(self) -> list:
        s = self.spec
        if s is None or s.color in ("none", "") or s.color_metric is not None:
            return []
        counts = s.data.get("category_counts")
        if counts is None:
            counts = {}
            for c in s.data.get("c", []):
                counts[c] = counts.get(c, 0) + 1
            from ...core.analysis.queries import dim_order
            counts = {k: counts[k] for k in dim_order(s.color, counts.keys())}
        return list(counts.items())

    def _color_map(self) -> dict:
        s = self.spec
        cats = self._categories()
        if s.color.startswith("model:") or s.color == "cstr":
            return {k: class_color(k if k is not None else NA) for k, _n in cats}
        if s.color.startswith("status:"):
            return {k: STATUS_COLORS.get(k, "#8d8d8d") for k, _n in cats}
        out = {}
        ordered = sorted(cats, key=lambda kv: -kv[1]) if s.color == "family" else cats
        for i, (k, _n) in enumerate(ordered):
            out[k] = categorical(i if i < MAX_CATEGORIES - 1 or len(ordered) <= MAX_CATEGORIES else MAX_CATEGORIES - 1)
        return out

    def _paint_points(self, p, rect, win, fx, fy, interactive, w, h):
        s = self.spec
        d = s.data
        if self._cache is None or not interactive or self._cache.size() != QSize(int(w * self.devicePixelRatioF()),
                                                                                 int(h * self.devicePixelRatioF())):
            img = None
            if interactive:
                dpr = self.devicePixelRatioF()
                img = QImage(int(w * dpr), int(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
                img.setDevicePixelRatio(dpr)
                img.fill(Qt.GlobalColor.transparent)
                q = QPainter(img)
                q.setRenderHint(QPainter.RenderHint.Antialiasing)
                q.setClipRect(rect.adjusted(-6, -6, 6, 6))
            else:
                q = p
            cmap = self._color_map()
            cont = s.color_metric is not None
            cvals = [v for v in d.get("c", []) if isinstance(v, (int, float))] if cont else []
            c0, c1 = (min(cvals), max(cvals)) if cvals else (0.0, 1.0)
            outline = QColor(t("layer-01"))
            r = 2.5 if len(d["x"]) > 5000 else 3.0
            xs, ys, cs = d["x"], d["y"], d.get("c", [])
            x0, x1, y0, y1 = win
            # Points are batched per colour and drawn with QPainter.drawPoints (round pen = filled disc):
            # one call per colour instead of one ellipse per point; screen coordinates come from one
            # comprehension per axis, and the hit-test grid is built only when the pointer first needs it.
            n = len(xs)
            cs = list(cs) + [None] * (n - len(cs)) if len(cs) < n else cs
            keep = [i for i in range(n) if x0 <= xs[i] <= x1 and y0 <= ys[i] <= y1 and cs[i] not in self.hidden]                 if (self.window is not None or self.hidden) else range(n)
            sxs = [fx(xs[i]) for i in keep]
            sys_ = [fy(ys[i]) for i in keep]
            default = t("border-interactive")
            groups: dict[str, list] = {}
            for k, i in enumerate(keep):
                c = cs[i]
                if cont:
                    col = sequential((c - c0) / ((c1 - c0) or 1)) if isinstance(c, (int, float)) else "#525252"
                elif cmap:
                    col = cmap.get(c) or categorical(MAX_CATEGORIES - 1)
                else:
                    col = default
                groups.setdefault(col, []).append(k)
            groups = {col: [QPointF(sxs[k], sys_[k]) for k in ks] for col, ks in groups.items()}
            if interactive:
                self._screen = list(zip(sxs, sys_, keep))
                self._grid = None                   # built lazily by _nearest
            jobs = []
            for col, pts in groups.items():
                for k in range(0, len(pts), self.CHUNK):
                    jobs.append((col, pts[k:k + self.CHUNK]))
            if interactive and sum(len(pts) for _c, pts in jobs) > self.CHUNK:
                # progressive: one chunk per event-loop turn, starting right after this paint (no long paint)
                self._jobs = (jobs, s.hollow, r, outline)
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self._next_chunk)
            else:
                for job in jobs:
                    self._draw_chunk(q, job, s.hollow, r, outline)
            if interactive:
                q.end()
                self._cache = img
        if interactive and self._cache is not None:
            p.drawImage(0, 0, self._cache)

    CHUNK = 2500

    @staticmethod
    def _draw_chunk(q: QPainter, job, hollow: bool, r: float, outline: QColor) -> None:
        col, pts = job
        poly = QPolygonF(pts)
        if hollow:                      # sampled: rings (colour disc, panel-coloured centre)
            q.setPen(QPen(QColor(col), 2 * r + 0.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            q.drawPoints(poly)
            q.setPen(QPen(outline, 2 * r - 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            q.drawPoints(poly)
        else:                           # raw: filled discs with a 1 px panel-coloured outline
            q.setPen(QPen(outline, 2 * r + 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            q.drawPoints(poly)
            q.setPen(QPen(QColor(col), 2 * r, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            q.drawPoints(poly)

    def _next_chunk(self) -> None:
        state = getattr(self, "_jobs", None)
        img = self._cache
        if not state or img is None:
            return
        jobs, hollow, r, outline = state
        if not jobs:
            self._jobs = None
            return
        q = QPainter(img)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setClipRect(self._frame_rect(self.width(), self.height()).adjusted(-6, -6, 6, 6))
        self._draw_chunk(q, jobs.pop(0), hollow, r, outline)
        q.end()
        self.update()
        if jobs:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._next_chunk)
        else:
            self._jobs = None

    def _paint_bins(self, p, rect, fx, fy):
        s = self.spec
        d = s.data
        (x0, x1), (y0, y1) = d["x"], d["y"]
        nx, ny = d["bins"]
        dx, dy = (x1 - x0) / nx or 1.0, (y1 - y0) / ny or 1.0
        cells = d["cells"]
        mx = max((c[2] for c in cells), default=1)
        cat = d.get("value") not in ("none", "", None) and s.color_metric is None
        vals = [c[3] for c in cells if isinstance(c[3], (int, float))] if s.color_metric is not None else []
        v0, v1 = (min(vals), max(vals)) if vals else (0, 1)
        p.setPen(Qt.PenStyle.NoPen)
        for bx, by, n, v in cells:
            if cat and isinstance(v, tuple):
                col = class_color(v[0]) if str(d.get("value", "")).startswith("model:") else categorical(hash(v[0]) % 9)
            elif s.color_metric is not None and isinstance(v, (int, float)):
                col = sequential((v - v0) / ((v1 - v0) or 1))
            else:
                col = sequential(math.log10(n + 1) / math.log10(mx + 1) if mx > 0 else 0)
            xa, xb = fx(x0 + bx * dx), fx(x0 + (bx + 1) * dx)
            ya, yb = fy(y0 + (by + 1) * dy), fy(y0 + by * dy)
            p.fillRect(QRectF(xa, ya, max(1.0, xb - xa), max(1.0, yb - ya)), QColor(col))

    def _paint_line(self, p, rect, fx, fy):
        s = self.spec
        d = s.data
        xs = d["x"]
        ys = d["y"][s.y.id]
        if s.extra.get("vec_rule") and s.y.id == "vec":
            self._paint_vec_bands(p, rect, fx, xs, ys)
        pen = QPen(QColor(t("border-interactive")), 1.5)
        p.setPen(pen)
        path = QPainterPath()
        started = False
        for xv, yv in zip(xs, ys):
            if yv is None:
                started = False
                continue
            pt = QPointF(fx(xv), fy(yv))
            if not started:
                path.moveTo(pt)
                started = True
            else:
                path.lineTo(pt)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setBrush(QColor(t("border-interactive")))
        p.setPen(QPen(QColor(t("layer-01")), 1))
        self._screen = []
        self._grid = {}
        for i, (xv, yv) in enumerate(zip(xs, ys)):
            if yv is None:
                continue
            sx, sy = fx(xv), fy(yv)
            p.drawEllipse(QPointF(sx, sy), 3, 3)
            self._screen.append((sx, sy, i))
            self._grid.setdefault((int(sx // 8), int(sy // 8)), []).append(len(self._screen) - 1)

    def _paint_vec_bands(self, p, rect, fx, xs, ys):
        """FCC / BCC + FCC / BCC bands along x from the VEC values (VEC rule regions)."""
        if not xs:
            return
        p.setFont(font(LABEL_01))
        regions = []
        for xv, yv in zip(xs, ys):
            if yv is None:
                continue
            cls = "FCC" if yv >= 8.0 else ("BCC" if yv < 6.87 else "BCC + FCC")
            if regions and regions[-1][0] == cls:
                regions[-1][2] = xv
            else:
                regions.append([cls, xv, xv])
        shade = {"FCC": t("layer-hover-01"), "BCC + FCC": t("layer-01"), "BCC": t("layer-hover-01")}
        for i, (cls, a, b) in enumerate(regions):
            nxt = regions[i + 1][1] if i + 1 < len(regions) else b
            xa, xb = fx(a), fx(nxt)
            if i % 2 == 0:
                p.fillRect(QRectF(xa, rect.top(), max(1.0, xb - xa), rect.height()), QColor(shade[cls]))
            p.setPen(QColor(t("text-helper")))
            p.drawText(QRectF(xa + 4, rect.bottom() - 18, max(40.0, xb - xa), 14), int(Qt.AlignmentFlag.AlignLeft), cls)

    def _paint_hist(self, p, rect, fx, fy):
        d = self.spec.data
        edges, counts = d["edges"], d["counts"]
        p.setPen(QPen(QColor(t("layer-01")), 1))
        p.setBrush(QColor(t("border-interactive")))
        for i, c in enumerate(counts):
            if not c:
                continue
            xa, xb = fx(edges[i]), fx(edges[i + 1])
            ya, yb = fy(c), fy(0)
            p.drawRect(QRectF(xa, ya, max(1.0, xb - xa), yb - ya))
        self._screen = []

    # ---- legend
    def _legend_items(self) -> list:
        s = self.spec
        if s is None:
            return []
        key = (id(s), frozenset(self.hidden) if self.hidden else None, THEME.name)
        cached = getattr(self, "_legend_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        items = self._legend_items_uncached()
        self._legend_cache = (key, items)
        return items

    def _legend_items_uncached(self) -> list:
        s = self.spec
        if s.kind in ("scatter", "binned") and s.color_metric is None and s.color not in ("none", ""):
            cmap = self._color_map()
            cats = self._categories()
            sampled = s.data.get("representation") == "SAMPLED"
            shown = {}
            if sampled:
                for c in s.data.get("c", []):
                    shown[c] = shown.get(c, 0) + 1
            items = []
            for k, n in cats:
                text = f"{dim_value_text(s.color, k) if not s.color.startswith('model:') else (k or NA)}  {n:,}"
                if sampled:
                    text += f" ({shown.get(k, 0):,})"
                items.append((cmap.get(k, "#8d8d8d"), text, k))
            return items
        return []

    def _paint_legend(self, p, w, h, rect):
        items = self._legend_items()
        s = self.spec
        if not items and not (s.color_metric is not None and s.kind == "scatter"):
            return
        p.setFont(font(LABEL_01))
        if s.color_metric is not None:
            lx = rect.right() - 140 if self.legend_mode != "column" else rect.right() + 16
            paint_html(p, QRectF(lx, rect.top(), 140, 16), s.color_metric.axis_title(), LABEL_01, "text-primary")
            for i in range(10):
                p.fillRect(QRectF(lx + i * 12, rect.top() + 20, 12, 10), QColor(sequential(i / 9)))
            vals = [v for v in s.data.get("c", []) if isinstance(v, (int, float))]
            if vals:
                p.setPen(QColor(t("text-secondary")))
                p.drawText(QRectF(lx, rect.top() + 32, 60, 14), int(Qt.AlignmentFlag.AlignLeft),
                           format_value(s.color_metric.id, min(vals)))
                p.drawText(QRectF(lx + 60, rect.top() + 32, 60, 14), int(Qt.AlignmentFlag.AlignRight),
                           format_value(s.color_metric.id, max(vals)))
            return
        title = s.legend_title
        if self.legend_mode == "row":
            x = 0.0
            y = h - 18
            if title:
                from PySide6.QtGui import QFontMetricsF
                x += paint_html(p, QRectF(0, y, 220, 16), f"<b>{title}:</b>", LABEL_01, "text-primary") + 10
            for col, text, key in items:
                p.fillRect(QRectF(x, y + 3, 10, 10), QColor(col))
                p.setPen(QColor(t("text-disabled" if key in self.hidden else "text-primary")))
                from PySide6.QtGui import QFontMetricsF
                tw = QFontMetricsF(p.font()).horizontalAdvance(text)
                p.drawText(QRectF(x + 14, y, tw + 4, 16), int(Qt.AlignmentFlag.AlignVCenter), text)
                x += tw + 32
            return
        lw = 150
        lx = rect.right() + 16 if self.legend_mode == "column" else rect.right() - lw - 4
        ly = rect.top() + 4
        if self.legend_mode != "column":
            bg = QColor(t("layer-01"))
            bg.setAlpha(220)
            p.fillRect(QRectF(lx - 6, ly - 4, lw + 8, 22 + 18 * len(items)), bg)
        if title:
            paint_html(p, QRectF(lx, ly, lw, 18), title, HEADING_COMPACT_01 if False else LABEL_01, "text-primary")
            ly += 20
        self._legend_hits = []
        for col, text, key in items:
            p.fillRect(QRectF(lx, ly + 3, 10, 10), QColor(col))
            p.setPen(QColor(t("text-disabled" if key in self.hidden else "text-primary")))
            p.drawText(QRectF(lx + 16, ly, lw - 16, 16), int(Qt.AlignmentFlag.AlignVCenter), text)
            self._legend_hits.append((QRectF(lx, ly, lw, 16), key))
            ly += 18

    # ---- overlays
    def _paint_overlays(self, p, rect, fx, fy):
        s = self.spec
        d = s.data
        if s.kind in ("scatter", "line"):
            ids = d.get("ids", [])
            xs = d.get("x", [])
            ys = d.get("y", []) if s.kind == "scatter" else d["y"][s.y.id]
            if self.active_id is not None:
                for i, rid in enumerate(ids):
                    if rid == self.active_id and ys[i] is not None:
                        p.setPen(QPen(QColor(t("support-info")), 2))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.drawEllipse(QPointF(fx(xs[i]), fy(ys[i])), 8, 8)
                        break
            for idx in self._selected_indices():
                if idx < len(xs) and ys[idx] is not None:
                    sx, sy = fx(xs[idx]), fy(ys[idx])
                    p.setPen(QPen(QColor(t("focus")), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QPointF(sx, sy), 6, 6)
                    if len(self.selection) == 1:
                        pen = QPen(QColor(t("border-strong-01")), 1, Qt.PenStyle.DotLine)
                        p.setPen(pen)
                        p.drawLine(QPointF(rect.left(), sy), QPointF(sx - 6, sy))
                        p.drawLine(QPointF(sx, sy + 6), QPointF(sx, rect.bottom()))
            if 0 <= self.focus_index < len(ids) and self.hasFocus():
                sx, sy = fx(xs[self.focus_index]), fy(ys[self.focus_index])
                crisp.frame(p, QRectF(sx - 8, sy - 8, 16, 16), 2, t("focus"))
            if 0 <= self._hover < len(xs) and ys[self._hover] is not None:
                p.setPen(QPen(QColor(t("text-primary")), 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(fx(xs[self._hover]), fy(ys[self._hover])), 5, 5)

    def _selected_indices(self) -> list[int]:
        if not self.selection or self.spec is None:
            return []
        ids = self.spec.data.get("ids", [])
        return [i for i, rid in enumerate(ids) if rid in self.selection]

    # ------------------------------------------------------------------ box plot
    def _paint_box(self, p, w, h):
        s = self.spec
        groups = s.data.get("groups", {})
        if not groups:
            return
        rect = self._frame_rect(w, h)
        rect.setBottom(rect.bottom() - 16)
        vals = [g.get(k) for g in groups.values() for k in ("min", "max") if g.get(k) is not None]
        if not vals:
            return
        lo, hi = _pad(min(vals), max(vals), False)
        fx, fy, _inv = self._to_screen(rect, (0, 1, lo, hi))
        self._paint_axes(p, rect, (0, 1, lo, hi), lambda v: -1000, fy, "", s.x.axis_title() if s.x else "")
        n = len(groups)
        slot = rect.width() / n
        p.setFont(font(LABEL_01))
        for i, (g, st) in enumerate(groups.items()):
            cx = rect.left() + slot * (i + 0.5)
            bw = min(48.0, slot * 0.5)
            col = QColor(categorical(i))
            name = dim_value_text(s.extra.get("group", "family"), g) if g is not None else "Not evaluable"
            p.setPen(QColor(t("text-secondary")))
            p.drawText(QRectF(cx - slot / 2, rect.bottom() + 4, slot, 14), int(Qt.AlignmentFlag.AlignHCenter),
                       _elide(name, slot))
            p.drawText(QRectF(cx - slot / 2, rect.bottom() + 18, slot, 14), int(Qt.AlignmentFlag.AlignHCenter),
                       f"N = {st.get('n_valid', 0):,}")
            if st.get("n_valid", 0) < 5:
                p.setPen(QPen(col, 1.5))
                p.setBrush(col)
                for v in {st.get("min"), st.get("median"), st.get("max")} - {None}:
                    p.drawEllipse(QPointF(cx, fy(v)), 3, 3)
                continue
            p.setPen(QPen(col, 1.5))
            p.drawLine(QPointF(cx, fy(st["min"])), QPointF(cx, fy(st["q1"])))
            p.drawLine(QPointF(cx, fy(st["q3"])), QPointF(cx, fy(st["max"])))
            for v in (st["min"], st["max"]):
                p.drawLine(QPointF(cx - bw / 4, fy(v)), QPointF(cx + bw / 4, fy(v)))
            box = QRectF(cx - bw / 2, fy(st["q3"]), bw, fy(st["q1"]) - fy(st["q3"]))
            fill = QColor(col)
            fill.setAlpha(70)
            p.setBrush(fill)
            p.drawRect(box)
            p.setPen(QPen(QColor(t("text-primary")), 2))
            p.drawLine(QPointF(box.left(), fy(st["median"])), QPointF(box.right(), fy(st["median"])))

    # ------------------------------------------------------------------ heatmap
    def _paint_heatmap(self, p, w, h):
        s = self.spec
        d = s.data
        xs, ys = d["xs"], d["ys"]
        if not xs or not ys:
            return
        rect = self._frame_rect(w, h)
        if not d["categorical"]:
            rect.setRight(rect.right() - 64)
        cw, ch = rect.width() / len(xs), rect.height() / len(ys)
        vals = [v[0] for v in d["cells"].values() if isinstance(v[0], (int, float))]
        v0, v1 = (min(vals), max(vals)) if vals else (0, 1)
        p.setFont(font(LABEL_01))
        self._cells = []
        for (xv, yv), (v, rid, name) in d["cells"].items():
            i, j = xs.index(xv), ys.index(yv)
            r = QRectF(rect.left() + i * cw, rect.bottom() - (j + 1) * ch, cw, ch)
            if d["categorical"]:
                col = class_color(v if v is not None else NA) if str(d["value"]).startswith("model:") else \
                    categorical(hash(v) % 9)
            else:
                col = sequential((v - v0) / ((v1 - v0) or 1)) if isinstance(v, (int, float)) else "#525252"
            qc = QColor(col)
            p.fillRect(r.adjusted(0.5, 0.5, -0.5, -0.5), qc)
            self._cells.append((r, rid, name, v, xv, yv))
            if cw >= 40 and ch >= 18:
                p.setPen(QColor("#161616" if qc.lightness() > 140 else "#f4f4f4"))
                text = str(v) if d["categorical"] else (format_value(s.extra.get("value_id", ""), v)
                                                        if isinstance(v, (int, float)) else "N/A")
                p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), text)
        p.setPen(QColor(t("text-secondary")))
        step_x = max(1, int(len(xs) / max(1, rect.width() / 60)))
        for i, xv in enumerate(xs):
            if i % step_x == 0:
                p.drawText(QRectF(rect.left() + i * cw, rect.bottom() + 4, cw, 14), int(Qt.AlignmentFlag.AlignHCenter),
                           format_number(xv, 2))
        step_y = max(1, int(len(ys) / max(1, rect.height() / 22)))
        for j, yv in enumerate(ys):
            if j % step_y == 0:
                p.drawText(QRectF(0, rect.bottom() - (j + 1) * ch, rect.left() - 6, ch),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), format_number(yv, 2))
        paint_html(p, QRectF(rect.left(), rect.bottom() + 22, rect.width(), 20), s.x.axis_title(), LABEL_01,
                   "text-secondary", Qt.AlignmentFlag.AlignHCenter)
        p.save()
        p.translate(14, rect.center().y())
        p.rotate(-90)
        paint_html(p, QRectF(-rect.height() / 2, -10, rect.height(), 20), s.y.axis_title(), LABEL_01,
                   "text-secondary", Qt.AlignmentFlag.AlignHCenter)
        p.restore()
        if not d["categorical"] and vals:
            bx = rect.right() + 24
            for k in range(20):
                p.fillRect(QRectF(bx, rect.bottom() - (k + 1) * rect.height() / 20, 16, rect.height() / 20 + 0.5),
                           QColor(sequential(k / 19)))
            p.setPen(QColor(t("text-secondary")))
            vid = s.extra.get("value_id", "")
            p.drawText(QRectF(bx - 10, rect.top() - 18, 80, 14), int(Qt.AlignmentFlag.AlignLeft),
                       format_value(vid, v1))
            p.drawText(QRectF(bx - 10, rect.bottom() + 4, 80, 14), int(Qt.AlignmentFlag.AlignLeft),
                       format_value(vid, v0))
        elif d["categorical"]:
            counts: dict = {}
            for v, _rid, _n in d["cells"].values():
                counts[v] = counts.get(v, 0) + 1
            x = rect.left()
            from PySide6.QtGui import QFontMetricsF
            for v in MD.ALL_CLASSES + (NA,):
                if v not in counts:
                    continue
                p.setBrush(QColor(class_color(v)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(QRectF(x, 12, 10, 10))
                p.setPen(QColor(t("text-primary")))
                text = f"{v} {counts[v]}"
                p.drawText(QRectF(x + 14, 9, 80, 16), int(Qt.AlignmentFlag.AlignLeft), text)
                x += QFontMetricsF(p.font()).horizontalAdvance(text) + 30

    # ------------------------------------------------------------------ bars
    def _paint_bars(self, p, w, h):
        """Stacked: one 100 % bar per model (classes of that model only, N/A separate per denominator).
        Grouped: one model's classes per group."""
        s = self.spec
        d = s.data
        rows = d.get("rows", [])
        if not rows:
            return
        label_w = d.get("label_w", 160)
        right_w = d.get("right_w", 120)
        row_h = d.get("row_h", 32)
        top = d.get("top", 36 if d.get("legend") else 4)
        p.setFont(font(LABEL_01))
        # legend row
        x = 0.0
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(p.font())
        for name, col in d.get("legend", []):
            p.fillRect(QRectF(x, 12, 10, 10), QColor(col))
            p.setPen(QColor(t("text-secondary")))
            p.drawText(QRectF(x + 14, 9, 160, 16), int(Qt.AlignmentFlag.AlignLeft), name)
            x += fm.horizontalAdvance(name) + 30
        bar_w = max(40.0, w - label_w - right_w - 16)
        self._segments = []
        for i, row in enumerate(rows):
            y = top + i * row_h
            p.setPen(QColor(t("text-primary")))
            p.setFont(font(BODY_COMPACT_01))
            p.drawText(QRectF(0, y, label_w - 8, row_h), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       _elide(row["label"], label_w - 8))
            p.setFont(font(LABEL_01))
            bx = label_w
            denom = row["denominator"] or 1
            p.fillRect(QRectF(bx, y + 8, bar_w, row_h - 16), QColor(t("layer-hover-01")))
            for name, count, col, extra in row["segments"]:
                if not count:
                    continue
                sw = bar_w * count / denom
                seg = QRectF(bx, y + 8, sw, row_h - 16)
                p.fillRect(seg, QColor(col))
                if extra:
                    p.save()
                    p.setClipRect(QRectF(bx, y + 8, bar_w * extra / denom, row_h - 16))
                    pen = QPen(QColor(t("background")), 1)
                    p.setPen(pen)
                    for k in range(-int(row_h), int(sw) + int(row_h), 6):
                        p.drawLine(QPointF(bx + k, y + row_h - 8), QPointF(bx + k + row_h - 16, y + 8))
                    p.restore()
                if sw >= 48:
                    qc = QColor(col)
                    p.setPen(QColor("#161616" if qc.lightness() > 140 else "#f4f4f4"))
                    p.drawText(seg, int(Qt.AlignmentFlag.AlignCenter), f"{100 * count / denom:.1f} %")
                self._segments.append((seg, row, name, count, col))
                bx += sw
            p.setPen(QColor(t("text-secondary")))
            p.drawText(QRectF(label_w + bar_w + 8, y, right_w, row_h),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), row["right"])

    # ================================================================== interaction
    def _nearest(self, pos: QPointF, radius: float = 7.0) -> int:
        if not self._screen:
            return -1
        if self._grid is None:
            grid: dict = {}
            for k, (sx, sy, _idx) in enumerate(self._screen):
                grid.setdefault((int(sx // 8), int(sy // 8)), []).append(k)
            self._grid = grid
        gx, gy = int(pos.x() // 8), int(pos.y() // 8)
        best, bd = -1, radius * radius
        for ix in (gx - 1, gx, gx + 1):
            for iy in (gy - 1, gy, gy + 1):
                for k in self._grid.get((ix, iy), ()):
                    sx, sy, idx = self._screen[k]
                    dd = (sx - pos.x()) ** 2 + (sy - pos.y()) ** 2
                    if dd <= bd:
                        best, bd = idx, dd
        return best

    def hover_rows(self, idx: int) -> tuple[str, list]:
        """Tooltip content for a point: (title, [(label, value, colour or None)]) - Carbon chart anatomy: the
        values on both axes and the colour group (its legend colour as the row indicator)."""
        s = self.spec
        d = s.data
        names = d.get("names")
        name = names[idx] if names and idx < len(names) else f"Result {d['ids'][idx]}"
        xv = d["x"][idx]
        yv = d["y"][idx] if s.kind == "scatter" else d["y"][s.y.id][idx]
        rows = [(s.x.symbol or s.x.plain, f"{format_value(s.x.id, xv)} {s.x.unit}".strip(), None),
                (s.y.symbol or s.y.plain, f"{format_value(s.y.id, yv)} {s.y.unit}".strip(), None)]
        cs = d.get("c")
        if cs and idx < len(cs) and s.color not in ("none", ""):
            c = cs[idx]
            if s.color.startswith("model:"):
                rows.append((s.color[6:], c or NA, class_color(c or NA)))
            elif s.color_metric is not None:
                rows.append((s.color_metric.symbol or s.color_metric.plain, format_value(s.color_metric.id, c), None))
            else:
                rows.append((dim_label_text(s.color), dim_value_text(s.color, c), self._color_map().get(c)))
        return name, rows

    def hover_text(self, idx: int) -> str:
        """The tooltip as one line (accessible description, keyboard navigation)."""
        title, rows = self.hover_rows(idx)
        return " · ".join([title] + [f"{plain_text(lab)} {plain_text(val)}" for lab, val, _c in rows])

    def mouseMoveEvent(self, e):
        pos = e.position()
        s = self.spec
        if s is None:
            return
        if self._pan_start is not None:
            self._pan(pos)
            return
        tip = None
        if s.kind in ("scatter", "line"):
            i = self._nearest(pos)
            if i != self._hover:
                self._hover = i
                self.update()
            if i >= 0:
                from ...core.composition import name_html
                name, rows = self.hover_rows(i)
                tip = (name_html(name) if s.data.get("names") else name, rows)
        elif s.kind == "heatmap":
            for r, rid, name, v, xv, yv in getattr(self, "_cells", []):
                if r.contains(pos):
                    val = v if isinstance(v, str) else format_value(s.extra.get("value_id", ""), v)
                    model = str(s.data.get("value", "")).startswith("model:")
                    tip = (name, [(s.x.plain, format_number(xv, 2), None), (s.y.plain, format_number(yv, 2), None),
                                  (s.extra.get("value_label", "Value"), val if v is not None else NA,
                                   class_color(v if v is not None else NA) if model else None)])
                    break
        elif s.kind in ("bars_stacked", "bars_grouped"):
            for seg, row, name, count, col in getattr(self, "_segments", []):
                if seg.contains(pos):
                    denom = max(1, row["denominator"])
                    rows = [(name, f"{count:,} of {row['denominator']:,} ({100 * count / denom:.1f} %)", col)]
                    if row.get("status_text", {}).get(name):
                        rows.append(("Status", row["status_text"][name], None))
                    tip = (row["label"], rows)
                    break
        elif s.kind == "binned":
            tip = self._bin_tip(pos)
        if tip is None:
            self.tip.hide()
        else:
            self.tip.show_at(pos, *tip)

    def _bin_tip(self, pos):
        s = self.spec
        d = s.data
        lim = self._limits()
        if lim is None:
            return None
        rect = self._frame_rect(self.width(), self.height())
        _fx, _fy, inv = self._to_screen(rect, self.window or lim)
        xv, yv = inv(pos.x(), pos.y())
        (x0, x1), (y0, y1) = d["x"], d["y"]
        nx, ny = d["bins"]
        dx, dy = (x1 - x0) / nx or 1.0, (y1 - y0) / ny or 1.0
        bx, by = int((xv - x0) / dx), int((yv - y0) / dy)
        for cx, cy, n, v in d["cells"]:
            if cx == bx and cy == by:
                rows = [(s.x.plain, f"{format_value(s.x.id, x0 + bx * dx)} – {format_value(s.x.id, x0 + (bx + 1) * dx)} "
                         f"{s.x.unit}".strip(), None),
                        (s.y.plain, f"{format_value(s.y.id, y0 + by * dy)} – {format_value(s.y.id, y0 + (by + 1) * dy)} "
                         f"{s.y.unit}".strip(), None)]
                if isinstance(v, tuple):
                    rows.append(("Majority", f"{v[0]} ({100 * v[1] / max(1, n):.0f} %)",
                                 class_color(v[0]) if str(d.get("value", "")).startswith("model:") else None))
                elif isinstance(v, (int, float)) and s.color_metric is not None:
                    rows.append((f"Mean {s.color_metric.plain}", format_value(s.color_metric.id, v), None))
                return f"{n:,} result{'s' if n != 1 else ''}", rows
        return None

    def leaveEvent(self, e):
        self.tip.hide()
        if self._hover >= 0:
            self._hover = -1
            self.update()

    PAN_BUTTONS = (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton)

    def mousePressEvent(self, e):
        if self.spec is None:
            return
        if e.button() in self.PAN_BUTTONS:
            # direct pan (no pan mode): middle- or right-button drag moves the axes window
            if self.spec.kind in ("scatter", "binned", "line", "histogram") and self._limits() is not None:
                self._pan_start = (e.position(), self.window or self._limits())
                self.tip.hide()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._press = e.position()
        for r, key in getattr(self, "_legend_hits", []):
            if r.contains(e.position()):
                (self.hidden.discard if key in self.hidden else self.hidden.add)(key)
                self._invalidate()
                self.category_toggled.emit(set(self.hidden))
                self._press = None
                return

    def mouseReleaseEvent(self, e):
        if e.button() in self.PAN_BUTTONS:
            if self._pan_start is not None:
                self._pan_start = None
                self.unsetCursor()
            return
        if self._press is None or self.spec is None:
            return
        press, self._press = self._press, None
        s = self.spec
        if (e.position() - press).manhattanLength() > 4:
            return
        if s.kind in ("scatter", "line"):
            i = self._nearest(e.position())
            self.focus_index = i
            self.point_clicked.emit(s.data["ids"][i] if i >= 0 else None)
        elif s.kind == "heatmap":
            for r, rid, *_rest in getattr(self, "_cells", []):
                if r.contains(e.position()):
                    self.point_clicked.emit(rid)
                    break

    def mouseDoubleClickEvent(self, e):
        s = self.spec
        if s is None:
            return
        if s.kind in ("scatter", "line"):
            i = self._nearest(e.position())
            if i >= 0:
                self.point_activated.emit(s.data["ids"][i])
        elif s.kind == "heatmap":
            for r, rid, *_rest in getattr(self, "_cells", []):
                if r.contains(e.position()):
                    self.point_activated.emit(rid)
                    break

    def _pan(self, pos):
        start, win = self._pan_start
        if win is None:
            return
        rect = self._frame_rect(self.width(), self.height())
        x0, x1, y0, y1 = win
        dx = (pos.x() - start.x()) / rect.width() * (x1 - x0)
        dy = (pos.y() - start.y()) / rect.height() * (y1 - y0)
        self.window = (x0 - dx, x1 - dx, y0 + dy, y1 + dy)
        self._invalidate()
        self.view_changed.emit(self.window)

    def wheelEvent(self, e):
        s = self.spec
        if s is None or s.kind not in ("scatter", "binned", "line", "histogram"):
            e.ignore()
            return
        if self.ctrl_zoom and not e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            e.ignore()
            return
        lim = self._limits()
        if lim is None:
            return
        rect = self._frame_rect(self.width(), self.height())
        _fx, _fy, inv = self._to_screen(rect, self.window or lim)
        cx, cy = inv(e.position().x(), e.position().y())
        self.zoom(0.8 if e.angleDelta().y() > 0 else 1.25, QPointF(cx, cy))
        e.accept()

    def keyPressEvent(self, e):
        s = self.spec
        if s is None or s.kind not in ("scatter", "line"):
            return super().keyPressEvent(e)
        ids = s.data.get("ids", [])
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right) and len(ids):
            self.focus_index = max(0, min(len(ids) - 1, self.focus_index + (1 if k == Qt.Key.Key_Right else -1)))
            self.setToolTip(self.hover_text(self.focus_index))
            self.setAccessibleDescription(self.hover_text(self.focus_index))
            self.update()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and 0 <= self.focus_index < len(ids):
            self.point_clicked.emit(ids[self.focus_index])
            return
        if k == Qt.Key.Key_Escape:
            self.point_clicked.emit(None)
            return
        super().keyPressEvent(e)

    # ================================================================== export
    def render_image(self, w: int, h: int, scale: float = 2.0) -> QImage:
        img = QImage(int(w * scale), int(h * scale), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(scale)
        img.fill(QColor(t("layer-01")))
        p = QPainter(img)
        self.render_to(p, w, h)
        p.end()
        return img

    def export_svg(self, path: str, w: int, h: int, title: str = "", description: str = "") -> None:
        from PySide6.QtSvg import QSvgGenerator
        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setSize(QSize(w, h))
        gen.setViewBox(QRectF(0, 0, w, h))
        gen.setTitle(title)
        gen.setDescription(description)
        p = QPainter(gen)
        p.fillRect(QRectF(0, 0, w, h), QColor(t("layer-01")))
        self.render_to(p, w, h)
        p.end()



# ---------------------------------------------------------------------- chart tooltip
class ChartTooltip(QWidget):
    """Carbon Charts tooltip (CORRECT_DATA_VISUALIZATION item 9): a header (the hovered item) over label /
    value rows; a row that encodes a colour group carries that colour as a 4 px indicator at its left edge.
    Painted on the menu surface ($layer-02 + elevation shadow); never the application's text tooltip.
    A child of the plot, transparent for the mouse, kept inside the plot beside the pointer."""

    ROW_H = 24
    PAD = 8

    def __init__(self, plot: QWidget):
        super().__init__(plot)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title = ""
        self.rows: list = []
        self.hide()

    def show_at(self, pos: QPointF, title: str, rows: list) -> None:
        from ..widgets.dropdown import html_width
        from ..widgets.listbox import SHADOW
        if (title, rows) != (self.title, self.rows):
            self.title, self.rows = title, rows
            lw = max((html_width(lab, LABEL_01) for lab, _v, _c in rows), default=0)
            vw = max((html_width(val, LABEL_01) for _l, val, _c in rows), default=0)
            w = max(html_width(f"<b>{title}</b>", LABEL_01), lw + 24 + vw) + 2 * self.PAD + 4
            w = int(min(360, max(160, w)))
            h = int((len(rows) + (1 if title else 0)) * self.ROW_H + 2 * 4)
            self.resize(w + 2 * SHADOW, h + 2 * SHADOW)
        par = self.parentWidget()
        x = pos.x() + 16 - SHADOW
        if x + self.width() > par.width():
            x = pos.x() - 16 - self.width() + SHADOW
        y = pos.y() - self.height() / 2
        self.move(int(max(0, x)), int(max(0, min(par.height() - self.height(), y))))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _e):
        from ..widgets.listbox import SHADOW, paint_shadow
        p = QPainter(self)
        surface = self.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        paint_shadow(p, surface)
        p.fillRect(surface, QColor(t("layer-02")))
        x0, x1 = surface.left() + self.PAD + 4, surface.right() + 1 - self.PAD
        y = surface.top() + 4
        if self.title:
            paint_html(p, QRectF(x0, y, x1 - x0, self.ROW_H), f"<b>{self.title}</b>", LABEL_01, "text-primary")
            y += self.ROW_H
            crisp.hline(p, surface.left() + self.PAD, surface.right() + 1 - self.PAD, y, t("border-subtle-02"))
        for k, (lab, val, col) in enumerate(self.rows):
            if col:
                p.fillRect(QRectF(surface.left() + self.PAD - 4, y + 4, 4, self.ROW_H - 8), QColor(col))
            paint_html(p, QRectF(x0, y, x1 - x0, self.ROW_H), lab, LABEL_01, "text-secondary")
            paint_html(p, QRectF(x0, y, x1 - x0, self.ROW_H), val, LABEL_01, "text-primary",
                       Qt.AlignmentFlag.AlignRight)
            y += self.ROW_H
        p.end()

# ---------------------------------------------------------------------- helpers
def _log(v: float) -> float:
    return math.log10(v) if v > 0 else -12.0


def _log_ticks(lo: float, hi: float) -> list[float]:
    lo, hi = max(lo, 1e-12), max(hi, 1e-12)
    return [10.0 ** k for k in range(int(math.floor(math.log10(lo))), int(math.ceil(math.log10(hi))) + 1)]


def _pad(lo: float, hi: float, log: bool, frac: float = 0.05) -> tuple[float, float]:
    if log:
        lo, hi = max(lo, 1e-12), max(hi, 1e-12)
        return lo / 1.2, hi * 1.2
    if hi == lo:
        d = abs(lo) * 0.1 or 1.0
        return lo - d, hi + d
    d = (hi - lo) * frac
    return lo - d, hi + d


def _elide(text: str, width: float) -> str:
    from PySide6.QtGui import QFontMetricsF
    return QFontMetricsF(font(LABEL_01)).elidedText(text, Qt.TextElideMode.ElideRight, width)


_ = (QFont, QPoint, MODEL_KEYS)
