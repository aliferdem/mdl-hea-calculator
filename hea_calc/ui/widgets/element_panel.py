"""Element Selection panel (Figma 170:13202): periodic table of selectable element tiles,
per-model data-support indicators and the element property readout."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget)

from ...core.data import Datasets
from ...core.engine import MODEL_KEYS, MODELS, Engine
from .. import icons
from ..theme import BODY_COMPACT_01, THEME, TILE_GAP, TILE_SIZE, font, t
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
        return QSize(TILE_SIZE, TILE_SIZE)

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
        p = QPainter(self)
        r = self.rect()
        if self.isDown():
            bg = t("layer-active-02")
        elif self._hover:
            bg = t("layer-hover-02")
        else:
            bg = t("layer-02")
        p.fillRect(r, QColor(bg))
        if self.isChecked():
            pen = QPen(QColor(t("tile-selected-border")), 2)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)
            p.drawRect(QRectF(r).adjusted(1, 1, -1, -1))
        if self.hasFocus() and self.focusPolicy() != Qt.FocusPolicy.NoFocus:
            pen = QPen(QColor(t("focus")), 2)
            pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            p.setPen(pen)
            p.drawRect(QRectF(r).adjusted(1, 1, -1, -1))
            p.setPen(QPen(QColor(t("focus-inset")), 1))
            p.drawRect(QRectF(r).adjusted(2.5, 2.5, -2.5, -2.5))
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
        pitch = TILE_SIZE + TILE_GAP
        max_x = max_y = 0
        for el in datasets.elements:
            row, col, _cat = datasets.position(el)
            row, col = _DISPLAY_POSITION.get(el, (row, col))
            tile = ElementTile(el, self)
            # No tile tooltip: the element inspector already reports the symbol and the full name
            # on hover (see ElementSelection.show_element), so a tooltip only repeated it.
            x = col * pitch
            y = row * pitch + (_FBLOCK_EXTRA_GAP - pitch if row >= 8 else 0)
            tile.move(x, y)
            tile.toggled.connect(lambda checked, s=el: self.toggled.emit(s, checked))
            tile.hovered.connect(self.hovered.emit)
            self.tiles[el] = tile
            self.grid_pos[(row, col)] = el
            max_x, max_y = max(max_x, x + TILE_SIZE), max(max_y, y + TILE_SIZE)
        self.setFixedSize(max_x, max_y)
        THEME.changed.connect(self.update_all)

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


class _StatusIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.status = None

    def set_status(self, status: str | None, tip: str = ""):
        self.status = status
        self.setToolTip(tip)
        self.update()

    def paintEvent(self, _e):
        if not self.status:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        name = {"ok": "status_ok", "warn": "status_warn", "pair": "status_pair", "none": "status_none"}[self.status]
        icons.paint(p, name, QRectF(0, 0, 16, 16))
        p.end()


SUPPORT_LEGEND = (
    "<b>Model support</b> for the highlighted element:<br>"
    "✔ data available from the model's source dataset<br>"
    "⚠ computable, but a supplementary (non-source) value is used<br>"
    "◆ depends on the partner elements (binary data exist only for pairs within the dataset)<br>"
    "✖ required data unavailable — the model returns N/A"
)


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
        head.addWidget(InfoButton(SUPPORT_LEGEND))
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
            ic = _StatusIcon()
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
                ic.set_status(None)
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
        for gi, group in enumerate(self.GROUPS):
            if gi:
                d = Divider(vertical=True)
                d.setFixedHeight(44)
                row.addSpacing(0)
                row.addWidget(d, 0, Qt.AlignmentFlag.AlignTop)
                row.addSpacing(20)
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
            wrap.setFixedWidth((125, 177, 107, 85)[gi])
            row.addWidget(wrap, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.show_element(None)

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
        self.setFixedWidth(596)

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
