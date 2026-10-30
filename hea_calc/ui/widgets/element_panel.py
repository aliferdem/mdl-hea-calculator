"""Elements panel (CORRECT_ELEMENTS.png, Figma 170:13202): periodic table of selectable element tiles,
per-model data-support indicators and the element property readout.  Fixed geometry: 28 × 28 px tiles on a
30 px pitch at every window size (brief 2026-10-16 §17-18)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractButton, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QSpacerItem, QVBoxLayout,
                               QWidget)

from ...core.data import Datasets
from ...core.engine import MODEL_KEYS, MODELS, Engine
from .. import crisp, icons
from ..crisp import device_inset
from ..responsive import distribute
from ..theme import (BODY_COMPACT_01, BORDER_SELECTED, ELEMENT_PANEL_WIDTH, FOCUS_WIDTH, LABEL_01, PANEL_PADDING_X,
                     THEME, TILE_GAP, TILE_SIZE, font, t)
from .common import Divider, InfoButton, Panel, refresh_style

# Figma places La and Ac at the start of the f-block rows (row 8/9, column 2).
_DISPLAY_POSITION = {"La": (8, 2), "Ac": (9, 2)}
_FBLOCK_EXTRA_GAP = 10  # px between the main table and the f-block rows (Figma: 41 px pitch vs 31)


class ElementTile(QAbstractButton):
    """Selectable element tile — a customised Carbon selectable Tile (28 × 28, CORRECT_ELEMENTS).

    States: rest (layer-02 with a 1 px ``border-subtle-02`` inner stroke), hover (layer-hover-02), pressed
    (layer-active-02), selected (2 px
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
        self.read_only = False
        self.setFont(font(BODY_COMPACT_01))

    def sizeHint(self):
        return QSize(self.width(), self.height())

    def set_read_only(self, on: bool) -> None:
        """State = Calculating (visual QA F-02): the setup of the running batch is frozen.  The tile keeps its
        look and still reports hover / focus (element inspection, CORRECT_CALCULATING_STATE), but no mouse,
        Space or Enter path can change its selection, and it shows no hover / pressed affordance."""
        self.read_only = bool(on)
        self.setCursor(Qt.CursorShape.ArrowCursor if on else Qt.CursorShape.PointingHandCursor)
        self.update()

    def nextCheckState(self):
        if not self.read_only:
            super().nextCheckState()

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
        if self.isDown() and not self.read_only:
            bg = t("layer-active-02")
        elif self._hover and not self.read_only:
            bg = t("layer-hover-02")
        else:
            bg = t("layer-02")
        crisp.fill_rect(p, r, bg)
        if self.isChecked():
            crisp.frame(p, r, BORDER_SELECTED, t("tile-selected-border"))
        else:
            crisp.frame(p, r, 1, t("border-subtle-02"))      # bordered tile (CORRECT_ELEMENTS)
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
        """Lay the tiles out at ``size`` px (TILE_SIZE, fixed)."""
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

    def set_read_only(self, on: bool) -> None:
        for tile in self.tiles.values():
            tile.set_read_only(on)

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
        self.model_labels: list[QLabel] = []
        for i, key in enumerate(MODEL_KEYS):
            m = QLabel(key)
            self.model_labels.append(m)
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

    def group_span(self) -> tuple[int, int]:
        """Left and right x (in this widget) of the M1-M8 labels and indicators: the visible group."""
        ws = self.model_labels + list(self.icons.values())
        return min(w.x() for w in ws), max(w.geometry().right() + 1 for w in ws)

    def show_element(self, element: str | None):
        if not element:
            for ic in self.icons.values():
                ic.set_status("pending")
            return
        support = self.engine.model_support(element)
        for key, (status, text) in support.items():
            self.icons[key].set_status(status, f"{MODELS[key].title}\n{element}: {text}")


def properties_help_html() -> list:
    """Toggletip of the element properties: what the values are and the page that defines each of them."""
    return ["Values of the element under the pointer, from the calculator's elemental dataset; a dash means no "
            "value (never zero). Each symbol's tooltip gives its name and unit. r and r<sub>CN12</sub> are "
            "two different radius sets, each used by its own models.",
            "<a href='help://element-properties'>Property definitions and sources</a>"]


class ElementInfo(QWidget):
    """Figma 220:28174 — element identity line and four property groups separated by dividers.

    Groups by scientific category (each key a symbol; its Tooltip gives the full name, unit and data source):
    thermophysical (ρ, Tm, Vm) | atomic (atomic mass, the two radius sets) | electronic (VEC and the Miedema
    φ* and n_ws) | elastic (K, G).  ``r`` is the Guo & Liu (2011, Table 1) radius used by M2-M5 (δ, γ, S_E);
    ``r_CN12`` the Kittel CN12 metallic radius used for δ_CN12 by M1 (M8 uses no radius) - two datasets, shown side
    by side, never merged.
    Formatting only: every value is the dataset value (moduli are stored in 10^10 Pa and shown in GPa)."""

    # (key html, property, value format, scale, tooltip)
    GROUPS = [
        [("ρ", "density", "{:.2f} g cm<sup>−3</sup>", 1.0, "Density (g cm⁻³)"),
         ("T<sub>m</sub>", "melting_point", "{:.0f} K", 1.0, "Melting point (K)"),
         ("V<sub>m</sub>", "molar_volume", "{:.2f} cm³ mol<sup>−1</sup>", 1.0,
          "Molar volume (cm³ mol⁻¹), the Miedema V")],
        [("m<sub>a</sub>", "atomic_weight", "{:.3f} u", 1.0, "Atomic mass (u = g mol⁻¹)"),
         # display precision = the source's printed precision: Guo & Liu print 0.001 Å (0.1 pm), Kittel 0.01 Å (1 pm)
         ("r", "atomic_radius", "{:.1f} pm", 1.0,
          "Atomic radius (pm), given to 0.1 pm; the radius set used by M2–M5 (δ, γ, Λ, S_E)"),
         ("r<sub>CN12</sub>", "atomic_radius_cn12", "{:.0f} pm", 1.0,
          "Metallic radius for coordination number 12 (pm) — a different radius set; used for δ by M1 "
          "(M8 uses no radius)")],
        [("VEC", "nvalence", "{:g}", 1.0, "Valence electron count (s + d electrons)"),
         ("φ*", "work_function_phi", "{:.2f} V", 1.0, "Miedema electronegativity parameter φ* (V)"),
         ("n<sub>ws</sub>", "n_ws", "{:.2f} d.u.", 1.0,
          "Miedema electron density at the Wigner–Seitz cell boundary (density units)")],
        [("K", "bulk_modulus", "{:.1f} GPa", 10.0, "Bulk modulus (GPa)"),
         ("G", "shear_modulus", "{:.1f} GPa", 10.0, "Shear modulus (GPa)")],
    ]
    KEY_GAP = 8                           # key column to value column
    GROUP_GAP = 20                        # after each divider; compresses to GROUP_GAP_MIN
    GROUP_GAP_MIN = 10

    def __init__(self, datasets: Datasets, parent=None):
        super().__init__(parent)
        self.data = datasets
        self._measure()
        # Identity line, then the four property groups filling the rest of the area
        # down to a 16 px bottom padding (the rows share the height; the group dividers span all rows).  Formerly
        # the rows were 18 px with a stretch under them (~38 px unused) and 44 px dividers beside 54 px groups.
        lay = QVBoxLayout(self)
        lay.setContentsMargins(PANEL_PADDING_X, self.TOP_PAD, PANEL_PADDING_X, self.BOTTOM_PAD)
        lay.setSpacing(0)
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
        # what the values are: a Toggletip with the Documentation page that defines every property shown
        self.info_btn = InfoButton(properties_help_html, title="Element properties", width=308)
        ident.addWidget(self.info_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(ident)
        lay.addSpacing(self.IDENT_GAP)        # no rule between identity and grid (removed 2026-10-27)
        row = QHBoxLayout()
        row.setSpacing(0)
        self.values: dict[str, QLabel] = {}
        self.keys: dict[str, QLabel] = {}
        self.group_wraps: list[QWidget] = []
        self.group_gaps: list[QSpacerItem] = []
        self.group_dividers: list[QWidget] = []
        rows = max(len(g) for g in self.GROUPS)
        for gi, group in enumerate(self.GROUPS):
            if gi:
                d = Divider(vertical=True)    # full height of the property rows
                row.addWidget(d)
                self.group_dividers.append(d)
                gap = QSpacerItem(self.GROUP_GAP, 1, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
                row.addSpacerItem(gap)
                self.group_gaps.append(gap)
            g = QGridLayout()
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(0)
            g.setVerticalSpacing(0)
            for ri, (key_html, prop, fmt, scale, tip) in enumerate(group):
                # the tooltip belongs to the symbol only: a label sized to its text inside the key column, so the
                # hover area is the symbol and the tooltip caret points at it (not at the column's centre)
                k = QLabel(key_html)
                k.setObjectName("KeyValueKey")
                k.setTextFormat(Qt.TextFormat.RichText)
                k.setMinimumHeight(self.ROW_MIN)
                k.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                k.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
                k.setToolTip(tip)
                kcol = QWidget()
                kcol.setFixedWidth(self.KEY_WIDTHS[gi])
                kl = QHBoxLayout(kcol)
                kl.setContentsMargins(0, 0, 0, 0)
                kl.setSpacing(0)
                kl.addWidget(k)
                kl.addStretch(1)
                v = QLabel("—")
                v.setObjectName("KeyValueValue")
                v.setTextFormat(Qt.TextFormat.RichText)
                v.setMinimumHeight(self.ROW_MIN)
                v.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                g.addWidget(kcol, ri, 0)
                g.addWidget(v, ri, 1)
                self.keys[prop] = k
                self.values[prop] = (v, fmt, scale)
            for ri in range(rows):                # every group has the same row pitch (rows align across groups)
                g.setRowStretch(ri, 1)
                g.setRowMinimumHeight(ri, self.ROW_MIN)
            wrap = QWidget()
            wrap.setLayout(g)
            wrap.setFixedWidth(self.GROUP_WIDTHS[gi])
            row.addWidget(wrap)
            self.group_wraps.append(wrap)
        row.addStretch(1)
        lay.addLayout(row, 1)
        self.show_element(None)

    TOP_PAD = 12
    BOTTOM_PAD = 16                       # kept visible under the last row
    IDENT_GAP = 20                        # identity line to the property grid
    ROW_MIN = 18

    def _value_html(self, el: str, prop: str, fmt: str, scale: float) -> str:
        val = self.data.prop(el, prop)
        if val is None:
            return "—"
        text = fmt.format(val * scale)
        if prop == "atomic_radius" and self.data.radius_is_supplementary(el):
            text += " *"
        return text

    def _measure(self) -> None:
        """Key and group widths from the text they hold: the widest key of a group plus ``KEY_GAP``; the widest
        value any element of the dataset gives in that group (so no value is ever clipped)."""
        from .dropdown import html_width
        els = list(self.data.elements)
        keys, groups = [], []
        for group in self.GROUPS:
            kw = max(html_width(f"<b>{k}</b>", LABEL_01) for k, *_r in group)
            vw = max(html_width(self._value_html(el, prop, fmt, sc), LABEL_01)
                     for el in els for _k, prop, fmt, sc, _t in group)
            keys.append(int(kw + 0.999) + self.KEY_GAP)
            groups.append(keys[-1] + int(vw + 0.999) + 4)
        self.KEY_WIDTHS = tuple(keys)
        self.GROUP_WIDTHS = tuple(groups)

    def group_minimums(self) -> list[int]:
        return list(self.GROUP_WIDTHS)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit_groups()

    def fit_groups(self):
        """Measured group widths with 20 px gaps after the dividers; on a narrower panel the gaps shrink first
        (20 -> 10 px).  Groups never go below their content (``group_minimums``)."""
        n_gaps = len(self.group_gaps)
        avail = self.width() - 2 * PANEL_PADDING_X - n_gaps    # the layout's 16 px margins, 1 px dividers
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
            self.name.setProperty("hint", True)
            refresh_style(self.name)
            # sizeHint is measured before the stylesheet font applies, so allow a margin.
            self.name.setFixedWidth(self.name.sizeHint().width() + 24)
            self.z.setVisible(False)
            self.cat.setVisible(False)
            for v, _f, _s in self.values.values():
                v.setText("—")
            return
        self.z.setVisible(True)
        self.cat.setVisible(True)
        if self.name.property("hint"):
            self.name.setProperty("hint", False)
            refresh_style(self.name)
        self.name.setFixedWidth(self.name_min_width)
        self.name.setText(f"{el} <b>{self.data.name(el)}</b>")
        z = int(self.data.prop(el, "atomic_number") or 0)
        self.z.setText(f"Z <b>{z}</b>")
        self.cat.setText(self.data.category(el))
        tips = {prop: tip for group in self.GROUPS for _k, prop, _f, _s, tip in group}
        for prop, (v, fmt, scale) in self.values.items():
            v.setText(self._value_html(el, prop, fmt, scale))
            if prop == "atomic_radius" and self.data.prop(el, prop) is not None \
                    and self.data.radius_is_supplementary(el):
                self.keys[prop].setToolTip(f"{el}: supplementary radius (*) - not in the source table of this radius set; M2–M5 results that use it "
                    "are flagged")
            else:
                self.keys[prop].setToolTip(tips[prop])


class ElementPanel(Panel):
    selection_changed = Signal(list)
    element_toggled = Signal(str, bool)

    def __init__(self, engine: Engine, parent=None):
        super().__init__("Elements", parent)
        self.engine = engine
        self.data = engine.data
        # Figma Elements (570 x 490): the tiles start 16 px under the 40 px header, at x = 16; the divider is at
        # y = 355 and the element properties follow it
        body = QWidget()
        body.setFixedHeight(16 + 278)
        self.table = PeriodicTable(self.data, body)
        self.table.move(PANEL_PADDING_X, 16)
        self.support = ModelSupport(engine, body)
        self.support.move(103, 15)
        self.root.addWidget(body)
        self.root.addSpacing(21)
        self.root.addWidget(Divider())
        self.info = ElementInfo(self.data)
        self.root.addWidget(self.info, 1)
        self._sticky: str | None = None
        self.table.hovered.connect(self._preview)
        self.table.toggled.connect(self._toggled)
        self.table.installEventFilter(self)
        self.setFixedWidth(ELEMENT_PANEL_WIDTH)       # fixed geometry: never stretched or squeezed
        self.relayout()

    def relayout(self):
        """Model-support block in the gap of the first three periods: its M1-M8 group centred between the Be and B
        tiles, measured on the tiles and the indicator labels (2026-10-28; formerly M1 at Figma's x = 103)."""
        self.support.layout().activate()
        be, b = self.table.tiles["Be"], self.table.tiles["B"]
        gap_l = be.mapTo(self.table, be.rect().topLeft()).x() + be.width()
        gap_r = b.mapTo(self.table, b.rect().topLeft()).x()
        g_l, g_r = self.support.group_span()
        x = round((gap_l + gap_r) / 2 - (g_l + g_r) / 2)
        self.support.move(self.table.x() + x, 15)

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

    def set_read_only(self, on: bool) -> None:
        """Freeze the element selection while a calculation runs, like the composition fields."""
        self.table.set_read_only(on)

    def set_selected(self, elements: list[str]):
        """The committed selection (from the composition).  The details show the last committed element; an empty
        selection (Clear) returns them to the empty state - unless the pointer is hovering a tile, whose preview stays
        until it leaves the table (hover is a preview, never the committed state)."""
        current = set(self.table.selected())
        for el in current - set(elements):
            self.table.set_selected(el, False)
        for el in elements:
            self.table.set_selected(el, True)
        sticky = elements[-1] if elements else None
        if sticky != self._sticky or not elements:
            self._sticky = sticky
            if not self.table.underMouse():
                self.leave_preview()

    def clear(self):
        self.set_selected([])
        self._sticky = None
        self.leave_preview()
