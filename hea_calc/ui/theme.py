"""Design tokens (Carbon v11-inspired Cool Gray 100 / Cool Gray 10) and the application stylesheet.

Geometry, spacing and sizes are identical in both themes; only semantic colour tokens change.
Neutral values use Carbon's Cool Gray scale, adapted to the original theme layering; Figma-specific accents remain.
"""

from __future__ import annotations

import re

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase

# ------------------------------------------------------------------ geometry (shared)
# Figma Main window (MDL HEA Calculator UI 501:39126 / 595:72002, 1920 x 1032): 16 px page margins and panel gaps,
# 40 px panel headers, the 32 px title bar + its 4 px state line at the top of the client area.
PANEL_GAP = 16
CONTENT_MARGIN_X = 16
CONTENT_MARGIN_BOTTOM = 16
TITLEBAR_BAR_HEIGHT = 32
HEADER_HEIGHT = 36       # title bar (32) + state line (4)
# The visible gap from the bottom of the 32 px title bar to the top of the panels is 16 px.  The 4 px state line
# under the bar (its background colour) is part of that gap, so the content margin is the rest of it.
TITLEBAR_PANEL_GAP = 16
CONTENT_MARGIN_TOP = TITLEBAR_PANEL_GAP - (HEADER_HEIGHT - TITLEBAR_BAR_HEIGHT)
PANEL_HEADER_HEIGHT = 40
COLLAPSED_PANEL = 40     # a collapsed panel's strip (Figma Mode=Collapsed, 40 x 490)
CONTROL_HEIGHT = 32      # Carbon "sm" fields/rows
BUTTON_HEIGHT = 40       # Carbon "md" buttons in panel footers
# A QLineEdit's QSS min/max-height applies to its *content* box, so a 32 px field plus a 1 px
# bottom stroke came out 33 px tall and the stroke sat outside the field.  The stroke is part of
# the control, so the content box is one pixel shorter (measured against 06_single_populated:
# field background 31 px + 1 px #878d96 stroke = 32 px, then a 1 px gap to the next field).
FIELD_CONTENT_HEIGHT = CONTROL_HEIGHT - 1
PANEL_TITLE_TOP = 12
PANEL_PADDING_X = 16
TILE_SIZE = 28          # CORRECT_ELEMENTS / Main window.svg: 28 x 28 tiles on a 30 px pitch, at every window size
TILE_GAP = 2
# Current Figma frame DARK_MODE_FULLSCREEN (node 341:33323, 1920 px): Elements 578 · Composition setup 457 ·
# Analysis 805, 20 px margins and gaps.
ELEMENT_PANEL_WIDTH = 570      # Figma Elements 570 x 490: 18 x 28 px tiles on a 30 px pitch + 2 x 16 px
# Composition setup is NOT responsive (product decision, release reconciliation): its geometry is the Figma
# component's (instance 415:59801, 457 × 465) at every window width.  When the row cannot hold it next to the
# periodic table and an 805 px Analysis, the main layout moves Analysis below the other two.
COMPOSITION_PANEL_WIDTH = 457
ANALYSIS_PANEL_WIDTH = 829
DETAILS_PANEL_WIDTH = ANALYSIS_PANEL_WIDTH      # former name of the third panel's reference width
TOP_ROW_HEIGHT = 490

# Upper row (brief 2026-10-16 §18, §64): Elements and Composition have FIXED designed sizes - they never stretch
# or shrink.  Analysis is the flexible panel: 805 px is its PREFERRED (reference) width, not a requirement.  The
# row stays wide while Analysis still gets its minimum: 578 + 457 + 454 + 2 × 20 = 1529 px of content (a 1569 px
# client with the 20 px content margins - e.g. a maximized window at Windows 125 % on a 2160 px display, 1728
# logical px).  Below that Analysis moves under the first two panels, spans the full width and gets the taller
# stacked height.  Between 1529 and 1880 px Analysis takes whatever the row leaves; wider windows give the extra
# width to Analysis only (MateBook native DPI pass, 2026-10-18).
ELEMENT_PANEL_MIN = ELEMENT_PANEL_WIDTH      # 18 × 28 px tiles + 17 × 2 px gaps + 2 × 16 px padding
COMPOSITION_PANEL_MIN = COMPOSITION_PANEL_WIDTH
ANALYSIS_STACKED_HEIGHT = 720   # stacked Analysis (§19): room for a plot / statistics table, not the 465 side row
DETAILS_PANEL_MIN = 454      # Analysis' own minimum (the five line tabs at compact padding + 2 × 20 px)
ANALYSIS_WIDE_MIN = DETAILS_PANEL_MIN      # narrowest Analysis allowed beside the other two panels

# ------------------------------------------------------------------ shape tokens (shared)
# One corner radius for every *rounded* component (tooltip, toggletip, content switcher, focus ring of
# a rounded control).  Components the design draws square - panels, tiles, buttons, fields, table
# cells - stay square; pills (tags, toggle track) are fully rounded by construction.
CORNER_RADIUS = 7
# Separator between parts of one line of application text ("Single composition | Run 1").  Not a middle dot: "·" is
# kept for multiplication in formulas (0.55·Tm, J/(mol·K)).
UI_SEPARATOR = " | "
# The content switcher's outline and segment frames (analysis/widgets.ContentSwitcher), measured from the approved
# Analysis header reference (2026-11-04): a 4 px corner, smaller than the panels' CORNER_RADIUS.
SWITCHER_RADIUS = 4
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
    "background": "#121619", "background-hover": "#222a2f",
    "layer-01": "#21272a", "layer-02": "#343a3f", "layer-03": "#4d5358",
    "layer-hover-01": "#2b3236", "layer-hover-02": "#434a51",
    "layer-active-01": "#4d5358", "layer-active-02": "#697077",
    "layer-selected-01": "#343a3f", "layer-selected-hover-01": "#434a51", "layer-selected-02": "#4d5358", "layer-selected-hover-02": "#5d646a", "shell": "#21272a", "window-background": "#121619", "notification-info-bg": "#21272a", "notification-success-bg": "#21272a", "notification-warning-bg": "#21272a", "notification-error-bg": "#21272a",
    "field-01": "#21272a", "field-02": "#343a3f", "field-hover-02": "#434a51", "field-on-background": "#343a3f",
    # a field on the dialog's Cool Gray 90 surface uses field-01 (field-02 is for fields on layer-01)
    "dialog-field": "#21272a", "dialog-field-hover": "#2b3236",
    "border-subtle-00": "#343a3f", "border-subtle-01": "#343a3f", "border-subtle-02": "#4d5358",
    # Composition fields (2026-10-28, explicit product values): the bottom rule of read-only and disabled fields and
    # the disabled text; the disabled background is field-02 (#343a3f)
    "field-border-quiet": "#697077", "field-text-disabled": "#a2a9b0",
    # contextual layering (ui/surface.py): the layer-02 roles of the table header and row rule (Cool Gray 100)
    "layer-accent-02": "#4d5358", "border-subtle-03": "#697077",
    "border-strong-01": "#697077", "border-strong-02": "#878d96", "border-tile": "#697077", "scrollbar-thumb": "#4d5358", "scrollbar-thumb-hover": "#878d96", "scrollbar-thumb-active": "#c1c7cd",
    # 2 px frame of a selected periodic-table tile: white on dark (as designed), and the
    # interactive blue on light, where a near-black frame disappears against the tile.
    "tile-selected-border": "#f2f4f8",
    "border-interactive": "#4589ff", "border-inverse": "#f2f4f8", "border-disabled": "#343a3f",
    "text-primary": "#f2f4f8", "text-secondary": "#c1c7cd", "text-helper": "#a2a9b0",
    "text-placeholder": "#a2a9b0", "text-disabled": "#697077", "text-on-color": "#ffffff",
    "text-error": "#ff8389", "text-inverse": "#121619",
    "link-primary": "#78a9ff", "link-primary-hover": "#a6c8ff",
    "icon-primary": "#f2f4f8", "icon-secondary": "#c1c7cd", "icon-disabled": "#697077",
    "button-primary": "#0f62fe", "button-primary-hover": "#0050e6", "button-primary-active": "#002d9c",
    "button-secondary": "#697077", "button-secondary-hover": "#585e64", "button-secondary-active": "#343a3f",
    "button-ghost-hover": "#2b3236", "button-ghost-active": "#4d5358",
    "button-danger-primary": "#da1e28", "button-danger-secondary": "#ff8389", "button-danger-hover": "#b81922", "button-danger-active": "#750e13",
    "button-disabled": "#697077", "button-disabled-bg": "#697077", "text-on-color-disabled": "#a2a9b0",
    "focus": "#ffffff", "focus-inset": "#121619",
    "background-inverse": "#f2f4f8", "highlight": "#002d9c",
    "support-error": "#fa4d56", "support-success": "#42be65", "support-warning": "#f1c21b",
    "support-info": "#4589ff",
    "status-green": "#24a148", "status-yellow": "#f1c21b", "status-red": "#fa4d56", "status-gray": "#878d96",
    "status-inner": "#000000",
    # Cool Gray 100 inverse tokens: content on the light inverse surface of tooltips / toggletips
    "icon-inverse": "#121619", "link-inverse": "#0f62fe", "link-inverse-hover": "#0043ce", "icon-on-color": "#ffffff",
    "support-success-inverse": "#24a148", "support-error-inverse": "#da1e28",
    "support-warning-inverse": "#f1c21b", "support-info-inverse": "#0f62fe", "status-gray-inverse": "#697077",
    "overlay": "rgba(0, 0, 0, 0.65)", "shadow": "rgba(0, 0, 0, 0.8)",
    "switcher-selected": "#3f4548", "switcher-unselected": "#21272a",
    # The selected row must not share the header's colour, and every row carries a 1 px top and
    # bottom rule.  Measured in 19_data_table_populated: header #343a3f for 32 px, then a 1 px
    # #4d5358 rule, the selected row #2e3439, then #4d5358 again under it.
    "row-hover": "#2b3236", "row-selected": "#2e3439", "header-row": "#343a3f", "row-border": "#4d5358",
    # Figma Background/background-selected (#878d96 at 24 %, Cool Gray 100): the panel rules of Composition setup
    "background-selected": "#3d878d96",
    # Figma Background/background-hover (16 %) / -active (40 %) of the title bar; its progress track
    "background-active": "#66878d96", "titlebar-hover": "#29878d96", "titlebar-track": "#4d5358",
    # The inactive title bar steps one Cool Gray level up from the active one (shell #21272a): #2b3236 (contrast
    # 1.16, as the Gray palette's #202020 on #161616, 1.11).  The Cool Gray mapping had made both #21272a, so an
    # inactive window no longer looked inactive (fixed 2026-11-04).
    # Inactive title and menus use readable Cool Gray text while remaining dimmer than active text.
    # The state line keeps its hue at INACTIVE_LINE_MIX of its strength.
    "titlebar-inactive": "#2b3236", "titlebar-inactive-title": "#c1c7cd", "titlebar-inactive-text": "#a2a9b0",
}

LIGHT = {
    "background": "#f2f4f8", "background-hover": "#e4e9f1",
    "layer-01": "#ffffff", "layer-02": "#f2f4f8", "layer-03": "#ffffff",
    "layer-hover-01": "#e4e9f1", "layer-hover-02": "#e4e9f1",
    "layer-active-01": "#c1c7cd", "layer-active-02": "#c1c7cd",
    "layer-selected-01": "#dde1e6", "layer-selected-hover-01": "#cdd3da", "layer-selected-02": "#dde1e6", "layer-selected-hover-02": "#cdd3da", "shell": "#ffffff", "window-background": "#ffffff", "notification-info-bg": "#edf5ff", "notification-success-bg": "#defbe6", "notification-warning-bg": "#fcf4d6", "notification-error-bg": "#fff1f1",
    "field-01": "#ffffff", "field-02": "#f2f4f8", "field-hover-02": "#e4e9f1", "field-on-background": "#ffffff",
    "dialog-field": "#f2f4f8", "dialog-field-hover": "#e4e9f1",
    "border-subtle-00": "#dde1e6", "border-subtle-01": "#dde1e6", "border-subtle-02": "#c1c7cd",
    # Composition fields (2026-10-28, explicit product values); disabled background = field-02 (#f2f4f8)
    "field-border-quiet": "#c1c7cd", "field-text-disabled": "#878d96",
    # contextual layering (ui/surface.py): the layer-02 roles of the table header and row rule (Cool Gray 10)
    "layer-accent-02": "#dde1e6", "border-subtle-03": "#c1c7cd",
    "border-strong-01": "#878d96", "border-strong-02": "#878d96", "border-tile": "#a2a9b0", "scrollbar-thumb": "#c1c7cd", "scrollbar-thumb-hover": "#878d96", "scrollbar-thumb-active": "#697077",
    "tile-selected-border": "#0f62fe",
    "border-interactive": "#0f62fe", "border-inverse": "#121619", "border-disabled": "#c1c7cd",
    "text-primary": "#121619", "text-secondary": "#4d5358", "text-helper": "#697077",
    "text-placeholder": "#697077", "text-disabled": "#a2a9b0", "text-on-color": "#ffffff",
    "text-error": "#da1e28", "text-inverse": "#ffffff",
    "link-primary": "#0f62fe", "link-primary-hover": "#0043ce",
    "icon-primary": "#121619", "icon-secondary": "#4d5358", "icon-disabled": "#a2a9b0",
    "button-primary": "#0f62fe", "button-primary-hover": "#0050e6", "button-primary-active": "#002d9c",
    "button-secondary": "#343a3f", "button-secondary-hover": "#434a51", "button-secondary-active": "#697077",
    "button-ghost-hover": "#e4e9f1", "button-ghost-active": "#c1c7cd",
    "button-danger-primary": "#da1e28", "button-danger-secondary": "#da1e28", "button-danger-hover": "#b81922", "button-danger-active": "#750e13",
    "button-disabled": "#a2a9b0", "button-disabled-bg": "#c1c7cd", "text-on-color-disabled": "#878d96",
    "focus": "#0f62fe", "focus-inset": "#ffffff",
    "background-inverse": "#343a3f", "highlight": "#d0e2ff",
    "support-error": "#da1e28", "support-success": "#24a148", "support-warning": "#f1c21b",
    "support-info": "#0043ce",
    "status-green": "#24a148", "status-yellow": "#f1c21b", "status-red": "#da1e28", "status-gray": "#878d96",
    "status-inner": "#000000",
    # Cool Gray 10 inverse tokens: content on the dark inverse surface of tooltips / toggletips
    "icon-inverse": "#ffffff", "link-inverse": "#78a9ff", "link-inverse-hover": "#a6c8ff", "icon-on-color": "#ffffff",
    "support-success-inverse": "#42be65", "support-error-inverse": "#fa4d56",
    "support-warning-inverse": "#f1c21b", "support-info-inverse": "#4589ff", "status-gray-inverse": "#a2a9b0",
    "overlay": "rgba(22, 22, 22, 0.5)", "shadow": "rgba(0, 0, 0, 0.3)",
    "switcher-selected": "#ffffff", "switcher-unselected": "#dde1e6",
    "row-hover": "#c1c7cd", "row-selected": "#e4e9f1", "header-row": "#dde1e6", "row-border": "#dde1e6",
    # Figma Background/background-selected (#878d96 at 20 %, White / Cool Gray 10)
    "background-selected": "#33878d96",
    "background-active": "#80878d96", "titlebar-hover": "#1f878d96", "titlebar-track": "#c1c7cd",
    # inactive window title bar: Cool Gray 10; active title bar is white like the panels.
    # The inactive foreground is dark enough for normal text readability.
    "titlebar-inactive": "#f2f4f8", "titlebar-inactive-title": "#4d5358", "titlebar-inactive-text": "#697077",
}

# Figma-derived application variables (original White / Gray 100 modes, now remapped to Cool Gray, read
# through the Figma MCP 2026-10-25).  Neutral token values are now maintained in code; status tags in
# the panel headers use the Carbon tag palettes bound in the Expression and Composition space bases.  Keys are the
# Figma variable names; SEMANTIC_ALIASES below maps them to the application's token names (one definition each).
FIGMA_VARIABLES = {
    "light": {
        "Syntax/syntax-1": "#121619", "Syntax/syntax-2": "#007d79", "Syntax/syntax-3": "#0072c3",
        "Syntax/syntax-4": "#d02670", "Syntax/syntax-5": "#697077", "Syntax/syntax-6": "#8a3ffc",
        "Syntax/syntax-7": "#cdd3da", "Syntax/syntax-8": "#e51400",
        "Syntax/syntax-line-number": "#237893", "Syntax/syntax-line-highlighted": "#0b216f",
        "Syntax/syntax-line": "#f2f4f8", "Syntax/syntax-scrollbar": "#ff5959",
        "Tag/Red/tag-background": "#ffd7d9", "Tag/Red/tag-color": "#a2191f",
        "Tag/Green/tag-background": "#a7f0ba", "Tag/Green/tag-color": "#0e6027",
        "Tag/Blue/tag-background": "#d0e2ff", "Tag/Blue/tag-color": "#0043ce",
        "Tag/Gray/tag-background": "#dde1e6", "Tag/Gray/tag-color": "#121619",
        "Layer accent/layer-accent-01": "#dde1e6", "border-subtle (contextual)": "#c1c7cd",
        "border-subtle-background (contextual)": "#dde1e6", "Text/text-helper": "#697077",
    },
    "dark": {
        "Syntax/syntax-1": "#f2f4f8", "Syntax/syntax-2": "#3ddbd9", "Syntax/syntax-3": "#82cfff",
        "Syntax/syntax-4": "#ff7eb6", "Syntax/syntax-5": "#878d96", "Syntax/syntax-6": "#be95ff",
        "Syntax/syntax-7": "#3f4548", "Syntax/syntax-8": "#f14c4c",
        "Syntax/syntax-line-number": "#878d96", "Syntax/syntax-line-highlighted": "#c1c7cd",
        "Syntax/syntax-line": "#121619", "Syntax/syntax-scrollbar": "#bd191a",
        "Tag/Red/tag-background": "#a2191f", "Tag/Red/tag-color": "#ffd7d9",
        "Tag/Green/tag-background": "#0e6027", "Tag/Green/tag-color": "#a7f0ba",
        "Tag/Blue/tag-background": "#0043ce", "Tag/Blue/tag-color": "#d0e2ff",
        "Tag/Gray/tag-background": "#4d5358", "Tag/Gray/tag-color": "#dde1e6",
        "Layer accent/layer-accent-01": "#343a3f", "border-subtle (contextual)": "#4d5358",
        "border-subtle-background (contextual)": "#343a3f", "Text/text-helper": "#878d96",
    },
}
SEMANTIC_ALIASES = {
    # expression editor (Figma Expression bases 584:51933): token kind -> Figma variable
    "syntax-element": "Syntax/syntax-1", "syntax-text": "Syntax/syntax-1", "syntax-caret": "Syntax/syntax-1",
    "syntax-keyword": "Syntax/syntax-2", "syntax-number": "Syntax/syntax-3", "syntax-variable": "Syntax/syntax-4",
    "syntax-punctuation": "Syntax/syntax-5", "syntax-operator": "Syntax/syntax-6",
    "syntax-indent-guide": "Syntax/syntax-7", "syntax-error": "Syntax/syntax-8",
    "syntax-line-number": "Syntax/syntax-line-number", "syntax-line-number-active": "Syntax/syntax-line-highlighted",
    "syntax-line-active": "Syntax/syntax-line", "syntax-overview-error": "Syntax/syntax-scrollbar",
    # status tags of the panel headers (Parsed successfully / Multiple errors / Expression changed / counts)
    "tag-red-bg": "Tag/Red/tag-background", "tag-red-fg": "Tag/Red/tag-color",
    "tag-green-bg": "Tag/Green/tag-background", "tag-green-fg": "Tag/Green/tag-color",
    "tag-blue-bg": "Tag/Blue/tag-background", "tag-blue-fg": "Tag/Blue/tag-color",
    "tag-gray-bg": "Tag/Gray/tag-background", "tag-gray-fg": "Tag/Gray/tag-color",
    # editor frame, parsed-expression lists and the title bar's helper text
    "layer-accent-01": "Layer accent/layer-accent-01",
    "list-divider": "border-subtle (contextual)", "list-row-border": "border-subtle-background (contextual)",
    "shell-helper": "Text/text-helper",
}
for _name, _tokens in (("dark", DARK), ("light", LIGHT)):
    for _alias, _var in SEMANTIC_ALIASES.items():
        _tokens[_alias] = FIGMA_VARIABLES[_name][_var]

# Scientific prediction classes → Carbon tag palettes. These encode result classes, not UI status.
TAG_COLORS = {
    "dark": {
        "SS": ("#0e6027", "#a7f0ba"), "MP": ("#9f1853", "#ffd6e8"), "IM": ("#a2191f", "#ffd7d9"),
        "SS+IM": ("#0043ce", "#d0e2ff"), "MG": ("#6929c4", "#e8daff"), "N/A": ("#4d5358", "#dde1e6"),
        "BCC": ("#4d5358", "#dde1e6"), "FCC": ("#4d5358", "#dde1e6"), "BCC + FCC": ("#4d5358", "#dde1e6"),
    },
    "light": {
        "SS": ("#a7f0ba", "#0e6027"), "MP": ("#ffd6e8", "#9f1853"), "IM": ("#ffd7d9", "#a2191f"),
        "SS+IM": ("#d0e2ff", "#0043ce"), "MG": ("#e8daff", "#6929c4"), "N/A": ("#dde1e6", "#121619"),
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


def qss_color(value: str) -> str:
    """A token value for a Qt style sheet: ``#AARRGGBB`` (translucent Figma variables such as background-hover)
    becomes ``rgba(r, g, b, a)`` - Qt style sheets ignore the alpha of an 8-digit hex colour."""
    if isinstance(value, str) and len(value) == 9 and value.startswith("#"):
        a, r, g, b = (int(value[i:i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r}, {g}, {b}, {a})"
    return value


def qss_tokens(tokens: dict | None = None) -> dict:
    return {k: qss_color(v) for k, v in (tokens or THEME.tokens).items()}


def stylesheet(icon_url) -> str:
    """Application QSS. ``icon_url(name, token)`` returns a file URL for indicator images."""
    k = qss_tokens()
    return f"""
* {{ font-family: "{FONT_FAMILY}"; font-size: 14px; outline: none; }}
QWidget {{ color: {k['text-primary']}; }}
QMainWindow, #AppBody, #ContentScroll {{ background: {k['background']}; }}
/* Tooltips and toggletips are painted by widgets/tooltip.py (Carbon inverse surface, caret, the
   CORNER_RADIUS token); Qt's native QToolTip is never shown. */

/* ---------------- panels */
#Panel {{ background: {k['layer-01']}; }}
#PanelTitle {{ font-size: 14px; font-weight: 400; color: {k['text-primary']}; letter-spacing: 0.16px; }}
#PanelTitleSuffix {{ font-size: 14px; font-weight: 400; color: {k['text-primary']}; letter-spacing: 0.16px; }}
#Divider {{ background: {k['border-subtle-01']}; border: none; }}
#Label01 {{ font-size: 12px; color: {k['text-secondary']}; letter-spacing: 0.32px; }}
#Secondary {{ color: {k['text-secondary']}; }}
#Helper {{ font-size: 12px; color: {k['text-helper']}; letter-spacing: 0.32px; }}
#ErrorText {{ font-size: 12px; color: {k['text-error']}; letter-spacing: 0.32px; }}

/* ---------------- header (UI shell) */
#HeaderMenuItem {{ background: transparent; border: none; color: {k['text-secondary']};
                   padding: 0px 16px; font-size: 14px; text-align: left; }}
/* inactive window: one foreground level down (before :hover, so hovering an inactive window still answers) */
#HeaderMenuItem[inactive="true"] {{ color: {k['titlebar-inactive-text']}; }}
#HeaderMenuItem:hover {{ background: {k['titlebar-hover']}; color: {k['text-primary']}; }}
#HeaderMenuItem:pressed {{ background: {k['background-active']}; color: {k['text-primary']}; }}
/* after :hover - the trigger keeps its under-mouse state while its menu grabs input (visual QA F-04) */
#HeaderMenuItem[open="true"], #HeaderMenuItem[open="true"]:hover {{ background: {k['layer-02']};
                   color: {k['text-primary']}; }}
#HeaderMenuItem:focus {{ border: 2px solid {k['focus']}; padding: 0px 14px; }}
#HeaderProgressLabel {{ color: {k['text-primary']}; font-size: 14px; }}
#HeaderProgressLabel[inactive="true"] {{ color: {k['titlebar-inactive-title']}; }}
#HeaderProgressDetail {{ color: {k['shell-helper']}; font-size: 14px; letter-spacing: 0.16px; }}
#HeaderProgressDetail[inactive="true"] {{ color: {k['titlebar-inactive-text']}; }}
#Heading {{ color: {k['text-primary']}; font-size: 14px; font-weight: 600; }}
#ParsedRule {{ background: {k['border-subtle-01']}; border: none; }}
#NotificationTitle {{ color: {k['text-primary']}; font-weight: 600; font-size: 14px; }}
#NotificationBody {{ color: {k['text-primary']}; font-size: 14px; }}
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
QPushButton[kind="danger"] {{ background: {k['button-danger-primary']}; color: {k['text-on-color']}; }}
QPushButton[kind="danger"]:hover {{ background: {k['button-danger-hover']}; }}
QPushButton[kind="danger"]:pressed {{ background: {k['button-danger-active']}; }}
QPushButton[kind="danger"]:disabled {{ background: {k['button-disabled-bg']}; color: {k['text-on-color-disabled']}; }}
QPushButton[kind="danger-ghost"] {{ background: transparent; color: {k['button-danger-secondary']}; }}
QPushButton[kind="danger-ghost"]:hover {{ background: {k['button-danger-hover']}; color: {k['text-on-color']}; }}
QPushButton[kind="danger-ghost"]:disabled {{ color: {k['button-disabled']}; background: transparent; }}
QPushButton[kind="icon"] {{ background: transparent; padding: 0px; min-width: 32px; max-width: 32px;
                            min-height: 32px; max-height: 32px; }}
QPushButton[kind="icon"]:hover {{ background: {k['button-ghost-hover']}; }}
QPushButton[kind="icon"]:pressed {{ background: {k['button-ghost-active']}; }}
QPushButton[kind="icon"][active="true"] {{ background: {k['layer-selected-01']}; }}
/* Focus: a 2 px inside frame.  The horizontal padding drops by the same 2 px so the label never moves between
   rest / hover / focus / pressed (release reconciliation: no text shift between states). */
QPushButton:focus {{ border: 2px solid {k['focus']}; padding: 0px 14px; }}
QPushButton[kind="icon"]:focus {{ padding: 0px; }}
QPushButton[kind="primary"]:focus, QPushButton[kind="secondary"]:focus, QPushButton[kind="danger"]:focus {{
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
/* a focused modal footer button keeps its label where it was (the focus rules above reset the padding) */
QPushButton[tall="64"]:focus {{ border: 2px solid {k['focus']}; padding: 0px 14px 22px 14px; }}
/* initial focus given by the program, not the keyboard: no ring yet (dialogs.quiet_focus) */
QPushButton[tall="64"][quietfocus="true"]:focus {{ border: none; padding: 0px 16px 24px 16px; }}

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
/* Carbon text input hover ($field-hover) on every editable cell, the element symbol included; focus and error
   frames are painted over it (Field.paintEvent), so hover never replaces them and never moves the text */
QLineEdit[cell="element"]:!read-only:hover {{ background: {k['field-hover-02']}; }}
QLineEdit[cell="total"] {{ font-weight: 400; }}
QLineEdit[cell="element-filled"] {{ font-weight: 600; background: {k['layer-02']}; qproperty-alignment: AlignCenter; }}
/* Disabled composition fields (the balance amount in its active column): explicit product colours - field-02 surface,
   field-text-disabled text; their bottom rule (field-border-quiet) stays visible, painted by Field.paintEvent */
QLineEdit[crisp="true"]:disabled {{ background: {k['field-02']}; color: {k['field-text-disabled']}; }}
#LockCell {{ border: none; background: transparent; }}
QLineEdit#PageField, QLineEdit#PageField:focus, QLineEdit#PageField:hover {{ min-height: 39px; max-height: 39px; }}
#ColHeader {{ color: {k['text-primary']}; font-size: 14px; font-weight: 400; }}
QPlainTextEdit, QTextEdit {{ background: {k['field-02']}; color: {k['text-primary']}; border: none;
             border-bottom: 1px solid {k['border-strong-02']}; padding: 8px 12px 7px 12px; }}
/* 2 px frames with the padding reduced by the frame width: the text never moves on focus / error */
QPlainTextEdit:focus, QTextEdit:focus {{ border: 2px solid {k['focus']}; padding: 6px 10px 5px 10px; }}
QPlainTextEdit[invalid="true"], QPlainTextEdit[invalid="true"]:focus {{ border: 2px solid {k['support-error']};
             padding: 6px 10px 5px 10px; }}
QPlainTextEdit[valid="true"] {{ border: 2px solid {k['support-success']}; padding: 6px 10px 5px 10px; }}
/* Expression code editor (Figma Expression bases): no field chrome - the editor paints its own rules, gutter and
   current-line band on the panel background, in every state */
#CodeEditor, #CodeEditor:focus {{ background: transparent; border: none; padding: 0px; }}

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
QComboBox:focus {{ border: 2px solid {k['focus']}; padding: 0px 6px; }}
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
#KeyValueKey {{ color: {k['text-primary']}; font-size: 12px; font-weight: 600; letter-spacing: 0.16px; }}
#KeyValueValue {{ color: {k['text-primary']}; font-size: 12px; letter-spacing: 0.16px; }}
#KeyValueValue[hint="true"] {{ color: {k['text-secondary']}; }}

/* ---------------- scroll bars
   Application scroll areas use widgets/scroll.ThinScrollBar (custom painted, device-pixel thumb).
   These rules give any remaining style-drawn bar (combo popups, text areas, dialogs) the same
   geometry: a {SCROLLBAR_VISIBLE} px visible thumb centred in a {SCROLLBAR_HIT} px hit target. */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: {SCROLLBAR_HIT}px; margin: 0px; }}
QScrollBar::handle:vertical {{ background: {k['scrollbar-thumb']}; min-height: {SCROLLBAR_MIN_THUMB}px;
                               border-radius: {SCROLLBAR_VISIBLE // 2}px;
                               margin: 0px {(SCROLLBAR_HIT - SCROLLBAR_VISIBLE) // 2}px; }}
QScrollBar::handle:vertical:hover {{ background: {k['scrollbar-thumb-hover']}; }}
QScrollBar::handle:vertical:pressed {{ background: {k['scrollbar-thumb-active']}; }}
QScrollBar:horizontal {{ background: transparent; height: {SCROLLBAR_HIT}px; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: {k['scrollbar-thumb']}; min-width: {SCROLLBAR_MIN_THUMB}px;
                                 border-radius: {SCROLLBAR_VISIBLE // 2}px;
                                 margin: {(SCROLLBAR_HIT - SCROLLBAR_VISIBLE) // 2}px 0px; }}
QScrollBar::handle:horizontal:hover {{ background: {k['scrollbar-thumb-hover']}; }}
QScrollBar::handle:horizontal:pressed {{ background: {k['scrollbar-thumb-active']}; }}
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
/* application dialogs are independent windows: their outer surface is `window-background` (dark #121619, the
   main window's background; light white).  `shell` stays the title-bar colour.  Carbon layers stay inside it */
QDialog {{ background: {k['window-background']}; }}
#ModalTitle {{ font-size: 20px; color: {k['text-primary']}; }}
#ModalLabel {{ font-size: 12px; color: {k['text-secondary']}; letter-spacing: 0.32px; }}
/* the footer is the dialog's own surface (Gray 100 / White) - the ghost action at its left showed a Gray 90 block */
#ModalFooter {{ background: {k['window-background']}; }}
QDialog QLineEdit {{ background: {k['dialog-field']}; }}
QDialog QLineEdit:hover {{ background: {k['dialog-field-hover']}; }}
QDialog QLineEdit:read-only, QDialog QLineEdit:disabled {{ background: transparent; }}
QProgressBar {{ background: {k['layer-02']}; border: none; height: 8px; max-height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {k['border-interactive']}; }}
QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ height: 32px; }}
QListWidget::item:hover {{ background: {k['layer-hover-01']}; }}
"""


_ANCHOR = re.compile(r"<a\b(?:\s+style=(['\"])[^'\"]*\1)?", re.IGNORECASE)


def style_links(html: str, color: str, underline: bool = False) -> str:
    """Give every ``<a>`` of a rich-text string its colour inline.

    Qt draws QLabel / QTextDocument links with the palette's Link / LinkVisited roles, and the windows11 style
    derives those from the Windows *accent colour* (a brown #8c7045 here); a widget style sheet re-polishes the
    palette, so a custom Link role set on the label does not survive.  An inline anchor colour is the one value
    Qt never overrides - and there is no visited state, so a visited link keeps the product link colour."""
    deco = "underline" if underline else "none"
    return _ANCHOR.sub(f"<a style='color:{color}; text-decoration:{deco}'", html)
