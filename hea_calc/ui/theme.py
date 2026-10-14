"""Design tokens (Carbon v11 Gray 100 / Gray 10) and the application stylesheet.

Geometry, spacing and sizes are identical in both themes; only semantic colour tokens change.
Dark values come from the Figma variables of frame 170:11154; light values follow Carbon g10.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase

# ------------------------------------------------------------------ geometry (shared)
PANEL_GAP = 20
CONTENT_MARGIN_X = 20
CONTENT_MARGIN_TOP = 24
CONTENT_MARGIN_BOTTOM = 24
HEADER_HEIGHT = 48
CONTROL_HEIGHT = 32      # Carbon "sm" fields/rows
BUTTON_HEIGHT = 40       # Carbon "md" buttons in panel footers
# A QLineEdit's QSS min/max-height applies to its *content* box, so a 32 px field plus a 1 px
# bottom stroke came out 33 px tall and the stroke sat outside the field.  The stroke is part of
# the control, so the content box is one pixel shorter (measured against 06_single_populated:
# field background 31 px + 1 px #8d8d8d stroke = 32 px, then a 1 px gap to the next field).
FIELD_CONTENT_HEIGHT = CONTROL_HEIGHT - 1
PANEL_TITLE_TOP = 20
PANEL_PADDING_X = 20
TILE_SIZE = 29          # design tile; the periodic table shrinks it down to TILE_SIZE_MIN on narrow windows
TILE_SIZE_MIN = 24
TILE_GAP = 2
ELEMENT_PANEL_WIDTH = 596
# Approved Analysis layout (docs/analysis-redesign/ANALYSIS_RESPONSIVE_LAYOUT.md section 1): at the 1920 px
# reference the Analysis panel is 805 px; the 18 px come from Composition setup (457 -> 439), so the periodic
# table keeps its 29 px tiles.
COMPOSITION_PANEL_WIDTH = 439
ANALYSIS_PANEL_WIDTH = 805
DETAILS_PANEL_WIDTH = ANALYSIS_PANEL_WIDTH      # former name of the third panel's reference width
TOP_ROW_HEIGHT = 465

# Responsive upper row.  The 1920 px design frame (20 px margins and gaps) gives the reference widths
# above; narrower windows compress the panels proportionally down to these minimums (at Windows 150 %
# on a 2160 × 1440 display the client is 1440 logical px wide: 506 + 400 + 454 + 4 × 20 = 1440).
# Wider windows give the extra width to Calculation details only - the periodic table and the
# composition columns have nothing to show in extra width.
ELEMENT_PANEL_MIN = 506      # 18 tiles of TILE_SIZE_MIN + gaps, plus 2 × 20 px padding
COMPOSITION_PANEL_MIN = 400
DETAILS_PANEL_MIN = 454      # the five line tabs at compact padding, plus 2 × 20 px padding

# ------------------------------------------------------------------ shape tokens (shared)
# One corner radius for every *rounded* component (tooltip, toggletip, content switcher, focus ring of
# a rounded control).  Components the design draws square - panels, tiles, buttons, fields, table
# cells - stay square; pills (tags, toggle track) are fully rounded by construction.
CORNER_RADIUS = 7
# Tooltip / toggletip bubbles are the one intentional exception to CORNER_RADIUS: the HEA reference
# (design/components/Group 241.png, 308 px wide at 3x) has 2 px corners.
TOOLTIP_RADIUS = 2
# Carbon v11 Menu, size "sm" (the React default): 32 px items, 4 px block padding, 16 px inline
# padding, 1 px divider with 4 px margins; min 10 rem / max 18 rem.
MENU_ITEM_HEIGHT = 32
MENU_PADDING_Y = 4
MENU_PADDING_X = 16
MENU_MIN_WIDTH = 160
MENU_MAX_WIDTH = 288
# Scroll bars: 4 px visible track/thumb inside a wider invisible hit target.
SCROLLBAR_VISIBLE = 4
SCROLLBAR_HIT = 12
SCROLLBAR_MIN_THUMB = 24
# Crisp stroke widths (logical px).  Painted through ui/crisp.py, which converts them to whole
# device pixels once (floor, min 1) so every side of a frame is identical at fractional DPR.
BORDER_SELECTED = 2
FOCUS_WIDTH = 2
TAB_UNDERLINE = 2
HAIRLINE = 1

DARK = {
    "background": "#161616", "background-hover": "#292929",
    "layer-01": "#262626", "layer-02": "#393939", "layer-03": "#525252",
    "layer-hover-01": "#333333", "layer-hover-02": "#474747",
    "layer-active-01": "#525252", "layer-active-02": "#6f6f6f",
    "layer-selected-01": "#393939", "layer-selected-hover-01": "#474747",
    "field-01": "#262626", "field-02": "#393939", "field-hover-02": "#474747",
    "border-subtle-00": "#393939", "border-subtle-01": "#393939", "border-subtle-02": "#525252",
    "border-strong-01": "#6f6f6f", "border-strong-02": "#8d8d8d", "border-tile": "#6f6f6f",
    # 2 px frame of a selected periodic-table tile: white on dark (as designed), and the
    # interactive blue on light, where a near-black frame disappears against the tile.
    "tile-selected-border": "#f4f4f4",
    "border-interactive": "#4589ff", "border-inverse": "#f4f4f4", "border-disabled": "#393939",
    "text-primary": "#f4f4f4", "text-secondary": "#c6c6c6", "text-helper": "#a8a8a8",
    "text-placeholder": "#6f6f6f", "text-disabled": "#6f6f6f", "text-on-color": "#ffffff",
    "text-error": "#ff8389", "text-inverse": "#161616",
    "link-primary": "#78a9ff", "link-primary-hover": "#a6c8ff",
    "icon-primary": "#f4f4f4", "icon-secondary": "#c6c6c6", "icon-disabled": "#6f6f6f",
    "button-primary": "#0f62fe", "button-primary-hover": "#0050e6", "button-primary-active": "#002d9c",
    "button-secondary": "#6f6f6f", "button-secondary-hover": "#606060", "button-secondary-active": "#393939",
    "button-ghost-hover": "#333333", "button-ghost-active": "#525252",
    "button-danger-primary": "#da1e28", "button-danger-secondary": "#ff8389", "button-danger-hover": "#b81922",
    "button-disabled": "#6f6f6f", "button-disabled-bg": "#6f6f6f", "text-on-color-disabled": "#a8a8a8",
    "focus": "#ffffff", "focus-inset": "#161616",
    "background-inverse": "#f4f4f4", "highlight": "#002d9c",
    "support-error": "#fa4d56", "support-success": "#42be65", "support-warning": "#f1c21b",
    "support-info": "#4589ff",
    "status-green": "#24a148", "status-yellow": "#f1c21b", "status-red": "#fa4d56", "status-gray": "#8d8d8d",
    "status-inner": "#000000",
    "overlay": "rgba(0, 0, 0, 0.65)", "shadow": "rgba(0, 0, 0, 0.8)",
    "switcher-selected": "#404040", "switcher-unselected": "#212121",
    # The selected row must not share the header's colour, and every row carries a 1 px top and
    # bottom rule.  Measured in 19_data_table_populated: header #393939 for 32 px, then a 1 px
    # #525252 rule, the selected row #333333, then #525252 again under it.
    "row-hover": "#333333", "row-selected": "#333333", "header-row": "#393939", "row-border": "#525252",
}

LIGHT = {
    "background": "#f4f4f4", "background-hover": "#e8e8e8",
    "layer-01": "#ffffff", "layer-02": "#f4f4f4", "layer-03": "#ffffff",
    "layer-hover-01": "#e8e8e8", "layer-hover-02": "#e8e8e8",
    "layer-active-01": "#c6c6c6", "layer-active-02": "#c6c6c6",
    "layer-selected-01": "#e0e0e0", "layer-selected-hover-01": "#d1d1d1",
    "field-01": "#ffffff", "field-02": "#f4f4f4", "field-hover-02": "#e8e8e8",
    "border-subtle-00": "#e0e0e0", "border-subtle-01": "#e0e0e0", "border-subtle-02": "#c6c6c6",
    "border-strong-01": "#8d8d8d", "border-strong-02": "#8d8d8d", "border-tile": "#a8a8a8",
    "tile-selected-border": "#0f62fe",
    "border-interactive": "#0f62fe", "border-inverse": "#161616", "border-disabled": "#c6c6c6",
    "text-primary": "#161616", "text-secondary": "#525252", "text-helper": "#6f6f6f",
    "text-placeholder": "#a8a8a8", "text-disabled": "#a8a8a8", "text-on-color": "#ffffff",
    "text-error": "#da1e28", "text-inverse": "#ffffff",
    "link-primary": "#0f62fe", "link-primary-hover": "#0043ce",
    "icon-primary": "#161616", "icon-secondary": "#525252", "icon-disabled": "#a8a8a8",
    "button-primary": "#0f62fe", "button-primary-hover": "#0050e6", "button-primary-active": "#002d9c",
    "button-secondary": "#393939", "button-secondary-hover": "#474747", "button-secondary-active": "#6f6f6f",
    "button-ghost-hover": "#e8e8e8", "button-ghost-active": "#c6c6c6",
    "button-danger-primary": "#da1e28", "button-danger-secondary": "#da1e28", "button-danger-hover": "#b81922",
    "button-disabled": "#a8a8a8", "button-disabled-bg": "#c6c6c6", "text-on-color-disabled": "#8d8d8d",
    "focus": "#0f62fe", "focus-inset": "#ffffff",
    "background-inverse": "#393939", "highlight": "#d0e2ff",
    "support-error": "#da1e28", "support-success": "#24a148", "support-warning": "#f1c21b",
    "support-info": "#0043ce",
    "status-green": "#24a148", "status-yellow": "#f1c21b", "status-red": "#da1e28", "status-gray": "#8d8d8d",
    "status-inner": "#000000",
    "overlay": "rgba(22, 22, 22, 0.5)", "shadow": "rgba(0, 0, 0, 0.3)",
    "switcher-selected": "#ffffff", "switcher-unselected": "#e0e0e0",
    "row-hover": "#c6c6c6", "row-selected": "#e8e8e8", "header-row": "#e0e0e0", "row-border": "#e0e0e0",
}

# Scientific prediction classes → Carbon tag palettes. These encode result classes, not UI status.
TAG_COLORS = {
    "dark": {
        "SS": ("#0e6027", "#a7f0ba"), "MP": ("#9f1853", "#ffd6e8"), "IM": ("#a2191f", "#ffd7d9"),
        "SS+IM": ("#0043ce", "#d0e2ff"), "MG": ("#6929c4", "#e8daff"), "N/A": ("#525252", "#e0e0e0"),
        "BCC": ("#4d5358", "#dde1e6"), "FCC": ("#4d5358", "#dde1e6"), "BCC + FCC": ("#4d5358", "#dde1e6"),
    },
    "light": {
        "SS": ("#a7f0ba", "#0e6027"), "MP": ("#ffd6e8", "#9f1853"), "IM": ("#ffd7d9", "#a2191f"),
        "SS+IM": ("#d0e2ff", "#0043ce"), "MG": ("#e8daff", "#6929c4"), "N/A": ("#e0e0e0", "#161616"),
        "BCC": ("#dde1e6", "#343a3f"), "FCC": ("#dde1e6", "#343a3f"), "BCC + FCC": ("#dde1e6", "#343a3f"),
    },
}

TAG_LONG_NAMES = {
    "SS": "Solid solution", "MP": "Multiple phases", "IM": "Intermetallic", "SS+IM": "Solid solution + intermetallic",
    "MG": "Metallic glass (amorphous)", "N/A": "Not available",
}

FONT_FAMILY = "IBM Plex Sans"


@dataclass(frozen=True)
class Typo:
    size: int
    weight: int
    line: int
    spacing: float


BODY_COMPACT_01 = Typo(14, 400, 18, 0.16)
HEADING_COMPACT_01 = Typo(14, 600, 18, 0.16)
LABEL_01 = Typo(12, 400, 16, 0.32)
HEADING_03 = Typo(20, 400, 28, 0.0)


def font(t: Typo = BODY_COMPACT_01, *, italic: bool = False) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(t.size)
    f.setWeight(QFont.Weight(t.weight))
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, t.spacing)
    f.setItalic(italic)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def load_fonts() -> None:
    from pathlib import Path
    fonts_dir = Path(__file__).with_name("fonts")
    if fonts_dir.is_dir():
        for path in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(path))


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, name: str = "dark"):
        super().__init__()
        self.name = name if name in ("dark", "light") else "dark"

    @property
    def tokens(self) -> dict:
        return DARK if self.name == "dark" else LIGHT

    def color(self, token: str) -> QColor:
        return QColor(self.tokens[token])

    def tag_colors(self, label: str) -> tuple[str, str]:
        palette = TAG_COLORS[self.name]
        return palette.get(label, palette["N/A"])

    def set_theme(self, name: str) -> None:
        if name not in ("dark", "light") or name == self.name:
            return
        self.name = name
        self.changed.emit(name)


THEME = ThemeManager()


def t(token: str) -> str:
    return THEME.tokens[token]


def stylesheet(icon_url) -> str:
    """Application QSS. ``icon_url(name, token)`` returns a file URL for indicator images."""
    k = THEME.tokens
    return f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: 14px; outline: none; }}
QWidget {{ color: {k['text-primary']}; }}
QMainWindow, #AppBody, #ContentScroll {{ background: {k['background']}; }}
/* Tooltips and toggletips are painted by widgets/tooltip.py (Carbon inverse surface, caret, the
   CORNER_RADIUS token); Qt's native QToolTip is never shown. */

/* ---------------- panels */
#Panel {{ background: {k['layer-01']}; }}
#PanelTitle {{ font-size: 16px; font-weight: 600; color: {k['text-primary']}; letter-spacing: 0px; }}
#PanelTitleSuffix {{ font-size: 16px; font-weight: 400; color: {k['text-primary']}; }}
#Divider {{ background: {k['border-subtle-01']}; border: none; }}
#Label01 {{ font-size: 12px; color: {k['text-secondary']}; letter-spacing: 0.32px; }}
#Secondary {{ color: {k['text-secondary']}; }}
#Helper {{ font-size: 12px; color: {k['text-helper']}; letter-spacing: 0.32px; }}
#ErrorText {{ font-size: 12px; color: {k['text-error']}; letter-spacing: 0.32px; }}

/* ---------------- header (UI shell) */
#AppHeader {{ background: {k['background']}; border-bottom: 1px solid {k['border-subtle-00']}; }}
#HeaderName {{ font-size: 14px; color: {k['text-primary']}; }}
#HeaderDivider {{ background: {k['border-subtle-01']}; }}
#HeaderMenuItem {{ background: transparent; border: none; color: {k['text-secondary']};
                   padding: 0px 16px; font-size: 14px; text-align: left; }}
#HeaderMenuItem:hover, #HeaderMenuItem[open="true"] {{ background: {k['layer-hover-01']};
                   color: {k['text-primary']}; }}
#HeaderMenuItem:focus {{ border: 2px solid {k['focus']}; }}
/* Menus are widgets/menu.CarbonMenu (painted from tokens); these rules only give it Carbon geometry:
   4 px block padding, 32 px items, 9 px dividers (1 px rule + 4 px margins). */
QMenu {{ background: {k['layer-01']}; border: none; padding: 4px 0px; }}
QMenu::item {{ padding: 0px 16px; min-height: 32px; height: 32px; color: {k['text-secondary']}; }}
QMenu::item:selected {{ background: {k['layer-hover-01']}; color: {k['text-primary']}; }}
QMenu::item:disabled {{ color: {k['text-disabled']}; }}
QMenu::separator {{ height: 1px; background: {k['border-subtle-01']}; margin: 4px 0px; }}
QMenu::indicator {{ width: 16px; height: 16px; padding-left: 8px; }}

/* ---------------- buttons */
QPushButton {{ border: none; min-height: {CONTROL_HEIGHT}px; padding: 0px 16px; text-align: left; }}
QPushButton[kind="primary"] {{ background: {k['button-primary']}; color: {k['text-on-color']}; }}
QPushButton[kind="primary"]:hover {{ background: {k['button-primary-hover']}; }}
QPushButton[kind="primary"]:pressed {{ background: {k['button-primary-active']}; }}
QPushButton[kind="primary"]:disabled {{ background: {k['button-disabled-bg']}; color: {k['text-on-color-disabled']}; }}
QPushButton[kind="secondary"] {{ background: {k['button-secondary']}; color: {k['text-on-color']}; }}
QPushButton[kind="secondary"]:hover {{ background: {k['button-secondary-hover']}; }}
QPushButton[kind="secondary"]:pressed {{ background: {k['button-secondary-active']}; }}
QPushButton[kind="secondary"]:disabled {{ background: {k['button-disabled-bg']}; color: {k['text-on-color-disabled']}; }}
QPushButton[kind="ghost"] {{ background: transparent; color: {k['link-primary']}; }}
QPushButton[kind="ghost"]:hover {{ background: {k['button-ghost-hover']}; color: {k['link-primary-hover']}; }}
QPushButton[kind="ghost"]:pressed {{ background: {k['button-ghost-active']}; }}
QPushButton[kind="ghost"]:disabled {{ background: transparent; color: {k['button-disabled']}; }}
QPushButton[kind="danger-ghost"] {{ background: transparent; color: {k['button-danger-secondary']}; }}
QPushButton[kind="danger-ghost"]:hover {{ background: {k['button-danger-hover']}; color: {k['text-on-color']}; }}
QPushButton[kind="danger-ghost"]:disabled {{ color: {k['button-disabled']}; background: transparent; }}
QPushButton[kind="icon"] {{ background: transparent; padding: 0px; min-width: 32px; max-width: 32px;
                            min-height: 32px; max-height: 32px; }}
QPushButton[kind="icon"]:hover {{ background: {k['button-ghost-hover']}; }}
QPushButton[kind="icon"]:pressed {{ background: {k['button-ghost-active']}; }}
QPushButton[kind="icon"][active="true"] {{ background: {k['layer-selected-01']}; }}
QPushButton:focus {{ border: 2px solid {k['focus']}; }}
QPushButton[kind="primary"]:focus, QPushButton[kind="secondary"]:focus {{
    border: 2px solid {k['focus']}; padding: 0px 14px; }}
QPushButton[btnsize="md"] {{ min-height: {BUTTON_HEIGHT}px; max-height: {BUTTON_HEIGHT}px; }}
QPushButton[btnsize="sm"] {{ min-height: {CONTROL_HEIGHT}px; max-height: {CONTROL_HEIGHT}px; }}
/* Shapes are selected by property rather than by a widget-level stylesheet: a widget that carries
   its own sheet stops inheriting the rules above, which silently cost the Export button its 16 px
   label padding (the label then rendered 4 px from the edge instead of 17 px, against
   19_data_table_populated).  set_prop() in widgets/common.py re-polishes after the change. */
QPushButton[square="40"] {{ min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; }}
QPushButton[square="48"] {{ min-width: 48px; max-width: 48px; min-height: 48px; max-height: 48px; }}
QPushButton[tall="64"] {{ min-height: 64px; max-height: 64px; padding-bottom: 24px; padding-top: 0px; }}

/* ---------------- text inputs (Carbon text input, sm) */
QLineEdit {{ background: {k['field-02']}; color: {k['text-primary']}; border: none;
             border-bottom: 1px solid {k['border-strong-02']}; padding: 0px 16px;
             min-height: {FIELD_CONTENT_HEIGHT}px; max-height: {FIELD_CONTENT_HEIGHT}px;
             selection-background-color: {k['border-interactive']}; selection-color: {k['text-on-color']}; }}
QLineEdit:hover {{ background: {k['field-hover-02']}; }}
/* All four sides are declared explicitly.  A bare `border: 2px solid ...` leaves the bottom at
   1 px, because the base rule's `border-bottom` longhand outranks it - measured in the light theme,
   where `focus` is blue: blue 2 px on three sides and blue 1 px along the bottom.  The padding
   compensation (16 -> 14, i.e. 2 px) keeps the text exactly where it was, so nothing moves. */
QLineEdit:focus {{ border-top: 2px solid {k['focus']}; border-right: 2px solid {k['focus']};
                   border-bottom: 2px solid {k['focus']}; border-left: 2px solid {k['focus']};
                   padding: 0px 14px; }}
QLineEdit[invalid="true"] {{ border-top: 2px solid {k['support-error']};
                            border-right: 2px solid {k['support-error']};
                            border-bottom: 2px solid {k['support-error']};
                            border-left: 2px solid {k['support-error']}; padding: 0px 14px; }}
QLineEdit:read-only {{ background: transparent; border: none; border-bottom: 1px solid {k['border-strong-01']};
                      color: {k['text-primary']}; }}
QLineEdit:read-only:focus {{ border: none; border-bottom: 1px solid {k['border-strong-01']}; padding: 0px 16px; }}
QLineEdit:disabled {{ color: {k['text-disabled']}; border-bottom: 1px solid transparent; background: transparent; }}
/* Composition fields (widgets/composition_panel.Field) paint their own strokes in device pixels -
   bottom rule, focus frame, invalid frame - so they carry no QSS border at all, in any state, and
   their text padding is set per column through QLineEdit.setTextMargins. */
QLineEdit[crisp="true"], QLineEdit[crisp="true"]:hover, QLineEdit[crisp="true"]:focus,
QLineEdit[crisp="true"]:read-only, QLineEdit[crisp="true"]:read-only:focus, QLineEdit[crisp="true"]:disabled,
QLineEdit[crisp="true"][invalid="true"], QLineEdit[crisp="true"][invalid="true"]:focus {{
    border: none; padding: 0px; min-height: {CONTROL_HEIGHT}px; max-height: {CONTROL_HEIGHT}px; }}
QLineEdit[cell="element"] {{ font-weight: 600; background: transparent; qproperty-alignment: AlignCenter; }}
QLineEdit[cell="element"]:!read-only {{ background: {k['field-02']}; }}
QLineEdit[cell="total"] {{ font-weight: 400; }}
QLineEdit[cell="element-filled"] {{ font-weight: 600; background: {k['layer-02']}; qproperty-alignment: AlignCenter; }}
#LockCell {{ border-bottom: 1px solid {k['border-strong-01']}; }}
QPlainTextEdit[invalid="true"] {{ border: 2px solid {k['support-error']}; }}
QPlainTextEdit, QTextEdit {{ background: {k['field-02']}; color: {k['text-primary']}; border: none;
             border-bottom: 1px solid {k['border-strong-02']}; padding: 8px 12px; }}
QPlainTextEdit:focus, QTextEdit:focus {{ border: 2px solid {k['focus']}; }}

/* ---------------- radio buttons / checkboxes */
QRadioButton, QCheckBox {{ spacing: 8px; color: {k['text-primary']}; background: transparent; }}
QRadioButton[compact="true"] {{ spacing: 4px; }}
QRadioButton::indicator, QCheckBox::indicator {{ width: 20px; height: 20px; }}
QRadioButton::indicator:unchecked {{ image: url({icon_url('radio', 'icon-primary')}); }}
QRadioButton::indicator:checked {{ image: url({icon_url('radio_checked', 'icon-primary')}); }}
QRadioButton::indicator:disabled {{ image: url({icon_url('radio', 'icon-disabled')}); }}
QRadioButton:disabled, QCheckBox:disabled {{ color: {k['text-disabled']}; }}
QCheckBox::indicator:unchecked {{ image: url({icon_url('checkbox', 'icon-primary')}); }}
QCheckBox::indicator:checked {{ image: url({icon_url('checkbox_checked', 'icon-primary')}); }}
QCheckBox::indicator:disabled {{ image: url({icon_url('checkbox', 'icon-disabled')}); }}
QRadioButton:focus, QCheckBox:focus {{ border: 1px solid {k['focus']}; }}

/* ---------------- combo (Carbon select, inline) */
QComboBox {{ background: transparent; border: none; padding: 0px 8px; min-height: {CONTROL_HEIGHT}px;
             color: {k['text-primary']}; }}
QComboBox:hover {{ background: {k['layer-hover-01']}; }}
QComboBox:focus {{ border: 2px solid {k['focus']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: url({icon_url('chevron_down', 'icon-primary')}); width: 16px; height: 16px; }}
QComboBox QAbstractItemView {{ background: {k['layer-01']}; color: {k['text-primary']}; border: none;
             selection-background-color: {k['layer-hover-01']}; outline: none; }}
QComboBox QAbstractItemView::item {{ min-height: 32px; padding: 0px 16px; color: {k['text-secondary']}; }}
QComboBox QAbstractItemView::item:hover {{ background: {k['layer-hover-01']}; color: {k['text-primary']}; }}
QComboBox QAbstractItemView::item:selected {{ background: {k['layer-selected-01']}; color: {k['text-primary']}; }}
QComboBox[field="true"] {{ background: {k['field-02']}; border-bottom: 1px solid {k['border-strong-02']};
             padding: 0px 16px; }}

/* ---------------- tabs: painted by widgets/common.TabButton (crisp 2 px underline) */

/* ---------------- tiles / details */
#Tile {{ background: {k['layer-02']}; border: 1px solid {k['border-tile']}; }}
#TileTitle {{ font-weight: 600; color: {k['text-primary']}; }}
#TileBody {{ color: {k['text-primary']}; }}
#KeyValueKey {{ color: {k['text-secondary']}; font-size: 12px; font-weight: 600; letter-spacing: 0.16px; }}
#KeyValueValue {{ color: {k['text-secondary']}; font-size: 12px; letter-spacing: 0.16px; }}

/* ---------------- scroll bars
   Application scroll areas use widgets/scroll.ThinScrollBar (custom painted, device-pixel thumb).
   These rules give any remaining style-drawn bar (combo popups, text areas, dialogs) the same
   geometry: a {SCROLLBAR_VISIBLE} px visible thumb centred in a {SCROLLBAR_HIT} px hit target. */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: {SCROLLBAR_HIT}px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: {k['border-strong-01']}; min-height: {SCROLLBAR_MIN_THUMB}px;
                               border-radius: 0px; margin: 0px {(SCROLLBAR_HIT - SCROLLBAR_VISIBLE) // 2}px; }}
QScrollBar::handle:vertical:hover {{ background: {k['border-strong-02']}; }}
QScrollBar:horizontal {{ background: transparent; height: {SCROLLBAR_HIT}px; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: {k['border-strong-01']}; min-width: {SCROLLBAR_MIN_THUMB}px;
                                 margin: {(SCROLLBAR_HIT - SCROLLBAR_VISIBLE) // 2}px 0px; }}
QScrollBar::handle:horizontal:hover {{ background: {k['border-strong-02']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------- data table */
#DataTable {{ background: {k['layer-01']}; }}
#TableToolbar {{ background: {k['layer-01']}; }}
#PaginationBar {{ background: {k['layer-01']}; border-top: 1px solid {k['border-subtle-02']}; }}
QTableView {{ background: {k['layer-01']}; alternate-background-color: {k['layer-01']}; border: none;
              gridline-color: {k['border-subtle-01']}; color: {k['text-secondary']};
              selection-background-color: {k['row-selected']}; selection-color: {k['text-primary']}; }}
QTableView:focus {{ border: none; }}
QHeaderView {{ background: {k['header-row']}; border: none; }}
QHeaderView::section {{ background: {k['header-row']}; color: {k['text-primary']}; border: none;
                        padding: 0px 8px 0px 16px; font-weight: 600; height: 32px; }}
QHeaderView::section:hover {{ background: {k['layer-hover-02']}; }}
QTableCornerButton::section {{ background: {k['header-row']}; border: none; }}

/* ---------------- dialogs / notifications */
QDialog {{ background: {k['layer-01']}; }}
#ModalTitle {{ font-size: 20px; color: {k['text-primary']}; }}
#ModalLabel {{ font-size: 12px; color: {k['text-secondary']}; letter-spacing: 0.32px; }}
#ModalFooter {{ background: {k['layer-01']}; }}
#InlineNotification {{ background: {k['layer-02']}; border-left: 3px solid {k['support-info']}; }}
#InlineNotification[kind="error"] {{ border-left: 3px solid {k['support-error']}; }}
#InlineNotification[kind="warning"] {{ border-left: 3px solid {k['support-warning']}; }}
#InlineNotification[kind="success"] {{ border-left: 3px solid {k['support-success']}; }}
QProgressBar {{ background: {k['layer-02']}; border: none; height: 8px; max-height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {k['border-interactive']}; }}
QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ height: 32px; }}
QListWidget::item:hover {{ background: {k['layer-hover-01']}; }}
"""
