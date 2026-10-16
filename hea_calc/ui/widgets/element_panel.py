"""Element Selection panel (Figma 170:13202): periodic table of selectable element tiles,
per-model data-support indicators and the element property readout."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QSpacerItem, QVBoxLayout,
                               QWidget)

from ...core.data import Datasets
from ...core.engine import MODEL_KEYS, MODELS, Engine
from .. import crisp, icons
from ..crisp import device_inset
from ..responsive import distribute, tile_size_for
from ..theme import (BODY_COMPACT_01, BORDER_SELECTED, ELEMENT_PANEL_MIN, FOCUS_WIDTH, LABEL_01, PANEL_PADDING_X, THEME,
                     TILE_GAP, TILE_SIZE, TILE_SIZE_MIN, font, t)
from .common import Divider, InfoButton, Panel

# Figma places La and Ac at the start of the f-block rows (row 8/9, column 2).
_DISPLAY_POSITION = {"La": (8, 2), "Ac": (9, 2)}
_FBLOCK_EXTRA_GAP = 10  # px between the main table and the f-block rows (Figma: 41 px pitch vs 31)


class ElementTile(QAbstractButton):
    """Selectable element tile — a customised Carbon selectable Tile (29 × 29).

    States: rest (layer-02), hover (layer-hover-02), pressed (layer-active-02), selected (2 px
    ``tile-selected-border`` frame: #f4f4f4 in the dark theme, #0f62fe in the light one, so the
    selected tile keeps the design's white frame on dark and the interactive blue on light),
    keyboard focus (Carbon focus ring with inset line).

    The tiles carry **no tooltip**: the element inspector below the table already shows the symbol
    and the full name on hover, so a tile tooltip only duplicated it.
    """

    hovered = Signal(str)

    def __init__(self, symbol: str, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.setCheckable(True)
        self.setFixedSize(TILE_SIZE, TILE_SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(symbol)
        self._hover = False
        self.setFont(font(BODY_COMPACT_01))

    def sizeHint(self):
        return QSize(self.width(), self.height())

    def enterEvent(self, e):
        self._hover = True
        self.hovered.emit(self.symbol)
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.hovered.emit(self.symbol)

    def paintEvent(self, _e):
        # Background, selected frame and focus ring are painted in device pixels (ui/crisp.py):
        # a QPen / QSS 2 px frame rasterised 2 px on some sides and 3 px on others at DPR 1.25,
        # depending on the tile's fractional physical offset.
        p = QPainter(self)
        r = self.rect()
        if self.isDown():
            bg = t("layer-active-02")
        elif self._hover:
            bg = t("layer-hover-02")
        else:
            bg = t("layer-02")
        crisp.fill_rect(p, r, bg)
        if self.isChecked():
            crisp.frame(p, r, BORDER_SELECTED, t("tile-selected-border"))
        if self.hasFocus() and self.focusPolicy() != Qt.FocusPolicy.NoFocus:
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
            inset = device_inset(p, FOCUS_WIDTH)
            crisp.frame(p, QRectF(r).adjusted(inset, inset, -inset, -inset), 1, t("focus-inset"))
        p.setPen(QColor(t("text-primary")))
        p.setFont(self.font())
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.symbol)
        p.end()


class PeriodicTable(QWidget):
    """Grid of :class:`ElementTile`. Arrow keys move focus; Space/Enter toggles."""

    toggled = Signal(str, bool)
    hovered = Signal(str)

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        self.tiles: dict[str, ElementTile] = {}
        self.grid_pos: dict[tuple[int, int], str] = {}
        for el in datasets.elements:
            row, col, _cat = datasets.position(el)
            row, col = _DISPLAY_POSITION.get(el, (row, col))
            tile = ElementTile(el, self)
            # No tile tooltip: the element inspector already reports the symbol and the full name
            # on hover (see ElementSelection.show_element), so a tooltip only repeated it.
            tile.toggled.connect(lambda checked, s=el: self.toggled.emit(s, checked))
            tile.hovered.connect(self.hovered.emit)
            self.tiles[el] = tile
            self.grid_pos[(row, col)] = el
        self.tile_size = 0
        self.set_tile_size(TILE_SIZE)
        THEME.changed.connect(self.update_all)

    @property
    def pitch(self) -> int:
        return self.tile_size + TILE_GAP

    def set_tile_size(self, size: int) -> None:
        """Lay the tiles out at ``size`` px (design 29; narrower windows use down to TILE_SIZE_MIN).

        Only the cell size changes - gap, typography and the f-block offset stay as designed.
        """
        if size == self.tile_size:
            return
        self.tile_size = size
        pitch = self.pitch
        max_x = max_y = 0
        for (row, col), el in self.grid_pos.items():
            x = col * pitch
            y = row * pitch + (_FBLOCK_EXTRA_GAP - pitch if row >= 8 else 0)
            tile = self.tiles[el]
            tile.setFixedSize(size, size)
            tile.move(x, y)
            max_x, max_y = max(max_x, x + size), max(max_y, y + size)
        self.setFixedSize(max_x, max_y)

    def update_all(self, *_):
        for tile in self.tiles.values():
            tile.update()

    def set_selected(self, element: str, selected: bool) -> None:
        tile = self.tiles.get(element)
        if tile and tile.isChecked() != selected:
            tile.blockSignals(True)
            tile.setChecked(selected)
            tile.blockSignals(False)
            tile.update()

    def selected(self) -> list[str]:
        return [el for el, tile in self.tiles.items() if tile.isChecked()]

    def keyPressEvent(self, e):
        focused = self.focusWidget()
        if not isinstance(focused, ElementTile):
            return super().keyPressEvent(e)
        pos = next(k for k, v in self.grid_pos.items() if v == focused.symbol)
        moves = {Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1), Qt.Key.Key_Up: (-1, 0),
                 Qt.Key.Key_Down: (1, 0)}
        if e.key() in moves:
            dr, dc = moves[e.key()]
            r, c = pos
            for _ in range(20):
                r, c = r + dr, c + dc
                if (r, c) in self.grid_pos:
                    self.tiles[self.grid_pos[(r, c)]].setFocus()
                    return
                if not (0 <= r <= 9 and 0 <= c <= 17):
                    break
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused.click()
            return
        super().keyPressEvent(e)


STATUS_ICONS = {"pending": "status_pending", "ok": "status_ok", "warn": "status_warn", "pair": "status_pair",
                "none": "status_none"}
STATUS_LABELS = {"pending": "Pending", "ok": "Data available", "warn": "Supplementary data used",
                 "pair": "Depends on partner elements", "none": "Data unavailable"}
PENDING_TEXT = "Pending: select or hover an element to see this model\u2019s data support."


class _StatusIcon(QWidget):
    """One model's support status - always an explicit state, never blank.

    ``pending`` (no element highlighted: 03_element_empty shows the grey Carbon pending--filled icon
    for every model) or one of the model-support results ``ok`` / ``warn`` / ``pair`` / ``none``.
    The brief description is the Carbon tooltip on hover *and* keyboard focus, and the accessible
    name / description for screen readers - no visible text is added.
    """

    def __init__(self, key: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self.setFixedSize(16, 16)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.status = "pending"
        self.set_status("pending")

    def set_status(self, status: str | None, tip: str = ""):
        status = status or "pending"
        self.status = status
        title = MODELS[self.key].title if self.key in MODELS else self.key
        if status == "pending":
            tip = f"{title}\n{PENDING_TEXT}" if title else PENDING_TEXT
        self.setToolTip(tip)
        self.setAccessibleName(f"{self.key} model support: {STATUS_LABELS[status]}")
        self.setAccessibleDescription(tip)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icons.paint(p, STATUS_ICONS[self.status], QRectF(0, 0, 16, 16))
        if self.hasFocus():
            from .. import crisp
            crisp.frame(p, self.rect(), FOCUS_WIDTH, t("focus"))
        p.end()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()


SUPPORT_LEGEND_ROWS = (
    ("status_ok", "data available from the model\u2019s source dataset"),
    ("status_warn", "computable, but a supplementary (non-source) value is used"),
    ("status_pair", "depends on the partner elements (binary data exist only for pairs within the dataset)"),
    ("status_none", "required data unavailable \u2014 the model returns N/A"),
)


def support_legend_html() -> list:
    """Model-support legend for the toggletip (design/components/Group 241.png): one row per status icon
    followed by its explanation.  The icons are vector-painted by the toggletip from the inverse tokens
    (crisp at 100 / 125 / 150 %; the former inline raster <img> was blurry at fractional scaling and took the
    main surface's colours)."""
    return (["Model support for the highlighted element:"]
            + [("icon", name, text[:1].upper() + text[1:]) for name, text in SUPPORT_LEGEND_ROWS]
            + ["<a href='help://models'>Prediction model coverage</a>"])


# Plain-text form (accessibility, tests).
SUPPORT_LEGEND = "Model support for the highlighted element: " + "; ".join(t for _n, t in SUPPORT_LEGEND_ROWS)


class ModelSupport(QWidget):
    """Figma 198:21910 — 'Model support (i)' label, M1–M8 labels and status icons (32 px pitch)."""

    def __init__(self, engine: Engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(10)
        lbl = QLabel("Model support")
        lbl.setObjectName("Label01")
        head.addWidget(lbl)
        # 308 px: the design component (design/components/Group 241.png, 924 px at 3x)
        head.addWidget(InfoButton(support_legend_html, title="Model support legend", width=308))
        head.addStretch(1)
        lay.addLayout(head)
        lay.addSpacing(10)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        grid.setContentsMargins(0, 0, 0, 0)
        self.icons: dict[str, _StatusIcon] = {}
        for i, key in enumerate(MODEL_KEYS):
            m = QLabel(key)
            m.setFixedWidth(20)
            m.setAlignment(Qt.AlignmentFlag.AlignCenter)
            m.setToolTip(MODELS[key].title)
            grid.addWidget(m, 0, i, Qt.AlignmentFlag.AlignCenter)
            ic = _StatusIcon(key)
            grid.addWidget(ic, 1, i, Qt.AlignmentFlag.AlignCenter)
            self.icons[key] = ic
        lay.addLayout(grid)
        self.setFixedWidth(8 * 32)
        THEME.changed.connect(self._theme_changed)

    def _theme_changed(self, *_):
        for ic in self.icons.values():
            ic.update()

    def show_element(self, element: str | None):
        if not element:
            for ic in self.icons.values():
                ic.set_status("pending")
            return
        support = self.engine.model_support(element)
        for key, (status, text) in support.items():
            self.icons[key].set_status(status, f"{MODELS[key].title}\n{element}: {text}")


class ElementInfo(QWidget):
    """Figma 220:28174 — element identity line and four property groups separated by dividers."""

    GROUPS = [
        [("ρ", "density", "{:.2f} g cm<sup>−3</sup>", 1.0), ("T<sub>m</sub>", "melting_point", "{:.0f} K", 1.0),
         ("VEC", "nvalence", "{:g}", 1.0)],
        [("At. mass", "atomic_weight", "{:.3f} u", 1.0), ("At. radius", "atomic_radius", "{:.2f} pm", 1.0),
         ("V<sub>m</sub>", "molar_volume", "{:.2f} cm³ mol<sup>−1</sup>", 1.0)],
        [("K", "bulk_modulus", "{:.1f} GPa", 10.0), ("G", "shear_modulus", "{:.1f} GPa", 10.0),
         ("φ", "work_function_phi", "{:.2f} V", 1.0)],
        [("n<sub>ws</sub>", "n_ws", "{:.2f}", 1.0), ("r<sub>CN12</sub>", "atomic_radius_cn12", "{:.0f} pm", 1.0)],
    ]
    KEY_WIDTHS = (35, 68, 22, 31)
    GROUP_WIDTHS = (125, 177, 107, 85)    # design (596 px panel)
    GROUP_GAP = 20                        # after each divider; compresses to GROUP_GAP_MIN
    GROUP_GAP_MIN = 10
    # widest value each group must show without clipping (12 px Plex), used as the group minimum
    WORST_VALUES = ("22.59 g cm-3", "10.00 cm3 mol-1 *", "450.0 GPa", "190 pm")

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 11, 20, 0)
        lay.setSpacing(13)
        ident = QHBoxLayout()
        ident.setSpacing(0)
        self.name = QLabel()
        self.name.setObjectName("KeyValueValue")
        self.z = QLabel()
        self.z.setObjectName("KeyValueValue")
        self.cat = QLabel()
        self.cat.setObjectName("KeyValueValue")
        # 108 px fits the identity row (symbol + name). The empty-state hint is longer, so it
        # re-measures itself while nothing is selected - see show_element().
        self.name.setFixedWidth(108)
        self.name_min_width = 108
        self.z.setFixedWidth(49)
        for w in (self.name, self.z, self.cat):
            w.setTextFormat(Qt.TextFormat.RichText)
            ident.addWidget(w)
        ident.addStretch(1)
        lay.addLayout(ident)
        row = QHBoxLayout()
        row.setSpacing(0)
        self.values: dict[str, QLabel] = {}
        self.group_wraps: list[QWidget] = []
        self.group_gaps: list[QSpacerItem] = []
        for gi, group in enumerate(self.GROUPS):
            if gi:
                d = Divider(vertical=True)
                d.setFixedHeight(44)
                row.addWidget(d, 0, Qt.AlignmentFlag.AlignTop)
                gap = QSpacerItem(self.GROUP_GAP, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
                row.addSpacerItem(gap)
                self.group_gaps.append(gap)
            g = QGridLayout()
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(0)
            g.setVerticalSpacing(0)
            for ri, (key_html, prop, fmt, scale) in enumerate(group):
                k = QLabel(key_html)
                k.setObjectName("KeyValueKey")
                k.setTextFormat(Qt.TextFormat.RichText)
                k.setFixedSize(self.KEY_WIDTHS[gi], 18)
                v = QLabel("—")
                v.setObjectName("KeyValueValue")
                v.setTextFormat(Qt.TextFormat.RichText)
                v.setFixedHeight(18)
                g.addWidget(k, ri, 0)
                g.addWidget(v, ri, 1)
                self.values[prop] = (v, fmt, scale)
            wrap = QWidget()
            wrap.setLayout(g)
            wrap.setFixedWidth(self.GROUP_WIDTHS[gi])
            row.addWidget(wrap, 0, Qt.AlignmentFlag.AlignTop)
            self.group_wraps.append(wrap)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.show_element(None)

    def group_minimums(self) -> list[int]:
        fm = QFontMetrics(font(LABEL_01))
        return [k + fm.horizontalAdvance(v) + 4 for k, v in zip(self.KEY_WIDTHS, self.WORST_VALUES)]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit_groups()

    def fit_groups(self):
        """Design widths at 596 px; on a narrower panel the gaps after the dividers shrink first
        (20 -> 10 px), then the groups compress proportionally down to their content."""
        n_gaps = len(self.group_gaps)
        avail = self.width() - 40 - n_gaps                     # 20 px margins, 1 px dividers
        design = sum(self.GROUP_WIDTHS) + self.GROUP_GAP * n_gaps
        gap = self.GROUP_GAP if avail >= design else max(
            self.GROUP_GAP_MIN, self.GROUP_GAP - -(-(design - avail) // max(1, n_gaps)))
        widths = distribute(avail - gap * n_gaps, self.GROUP_WIDTHS, self.group_minimums(), self.GROUP_WIDTHS)
        for sp in self.group_gaps:
            sp.changeSize(gap, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        for w, wd in zip(self.group_wraps, widths):
            w.setFixedWidth(wd)
        self.layout().invalidate()

    def show_element(self, el: str | None):
        if not el:
            # design/screenshots/03: the hint owns the whole identity row while nothing is
            # selected, so it is never elided against the Z / category fields.
            self.name.setText("Hover over an element to see its properties")
            # sizeHint is measured before the stylesheet font applies, so allow a margin.
            self.name.setFixedWidth(self.name.sizeHint().width() + 24)
            self.z.setVisible(False)
            self.cat.setVisible(False)
            for v, _f, _s in self.values.values():
                v.setText("—")
            return
        self.z.setVisible(True)
        self.cat.setVisible(True)
        self.name.setFixedWidth(self.name_min_width)
        self.name.setText(f"{el} <b>{self.data.name(el)}</b>")
        z = int(self.data.prop(el, "atomic_number") or 0)
        self.z.setText(f"Z <b>{z}</b>")
        self.cat.setText(self.data.category(el))
        for prop, (v, fmt, scale) in self.values.items():
            val = self.data.prop(el, prop)
            v.setText("—" if val is None else fmt.format(val * scale))
            if prop == "atomic_radius" and val is not None and self.data.radius_is_supplementary(el):
                v.setText(fmt.format(val) + " *")
                v.setToolTip("Not in Guo & Liu (2011) Table 1 — supplementary value")
            else:
                v.setToolTip("")


class ElementPanel(Panel):
    selection_changed = Signal(list)
    element_toggled = Signal(str, bool)

    def __init__(self, engine: Engine, parent=None):
        super().__init__("Element selection", parent)
        self.engine = engine
        self.data = engine.data
        self.title_holder.setFixedHeight(49)
        body = QWidget()
        body.setFixedHeight(287)
        self.table = PeriodicTable(self.data, body)
        self.table.move(20, 0)
        self.support = ModelSupport(engine, body)
        self.support.move(114, 6)
        self.root.addWidget(body)
        self.root.addSpacing(19)
        self.root.addWidget(Divider())
        self.info = ElementInfo(self.data)
        self.root.addWidget(self.info, 1)
        self._sticky: str | None = None
        self.table.hovered.connect(self._preview)
        self.table.toggled.connect(self._toggled)
        self.table.installEventFilter(self)
        self.setMinimumWidth(ELEMENT_PANEL_MIN)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def relayout(self):
        """Fit the periodic table to the panel width and keep the model-support block in the gap of
        the first three periods (columns 2-11), at its design position when the tiles are 29 px."""
        tile = tile_size_for(self.width() - 2 * PANEL_PADDING_X, 18, TILE_GAP, TILE_SIZE, TILE_SIZE_MIN)
        self.table.set_tile_size(tile)
        pitch = self.table.pitch
        x = min(3 * pitch + 1, 12 * pitch - TILE_GAP - self.support.width())
        self.support.move(PANEL_PADDING_X + max(2 * pitch, x), 6)

    def _preview(self, el: str):
        self.support.show_element(el)
        self.info.show_element(el)

    def leave_preview(self):
        self.support.show_element(self._sticky)
        self.info.show_element(self._sticky)

    def eventFilter(self, obj, ev):
        if obj is self.table and ev.type() == ev.Type.Leave:
            self.leave_preview()
        return False

    def _toggled(self, el: str, checked: bool):
        self._sticky = el
        self._preview(el)
        self.element_toggled.emit(el, checked)
        self.selection_changed.emit(self.table.selected())

    def set_selected(self, elements: list[str]):
        current = set(self.table.selected())
        for el in current - set(elements):
            self.table.set_selected(el, False)
        for el in elements:
            self.table.set_selected(el, True)
        if elements:
            self._sticky = elements[-1]
            self.leave_preview()

    def clear(self):
        self.set_selected([])
        self._sticky = None
        self.leave_preview()
