"""Reusable Carbon-inspired building blocks (styling via theme tokens, behaviour per Carbon v11)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QStyleOptionButton, QVBoxLayout,
                               QWidget)

from .. import crisp, icons
from .tooltip import CarbonToolTip, InfoButton, Toggletip, install_tooltips  # noqa: F401 (re-exported)
from ..theme import (BODY_COMPACT_01, CONTROL_HEIGHT, LABEL_01, PANEL_PADDING_X, TAG_LONG_NAMES,
                     THEME, font, t)


_SUPERSCRIPTS = {"⁻": "−", "¹": "1", "²": "2", "³": "3", "⁰": "0", "⁴": "4"}


def sup_html(text: str) -> str:
    """Convert unicode superscript runs (e.g. 'mol⁻¹') to HTML <sup> for fonts lacking those glyphs."""
    out, run = [], ""
    for ch in text:
        if ch in _SUPERSCRIPTS and not (ch in "²³" and not run and False):
            run += _SUPERSCRIPTS[ch]
        else:
            if run:
                out.append(f"<sup>{run}</sup>")
                run = ""
            out.append(ch)
    if run:
        out.append(f"<sup>{run}</sup>")
    return "".join(out)


_GRAVEYARD: list[QWidget] = []


def retire(w: QWidget) -> None:
    """Remove ``w`` from its layout and widget tree and delete it later - without ever making it a window.

    ``setParent(None)`` turns a child into a top-level window; a later ``setVisible(True)`` (a deferred update,
    a late background result) then flashes it on screen as a transient window while the main window is resized
    (release reconciliation, resize regression).  Retired widgets are moved under one hidden holder instead.
    """
    parent = w.parentWidget()
    if parent is not None and parent.layout() is not None:
        parent.layout().removeWidget(w)
    w.hide()
    if not _GRAVEYARD:
        holder = QWidget()
        holder.setObjectName("RetiredWidgets")
        holder.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        _GRAVEYARD.append(holder)
    w.setParent(_GRAVEYARD[0])
    w.deleteLater()


def refresh_style(w: QWidget) -> None:
    """Re-polish after a dynamic property change so QSS selectors re-evaluate."""
    st = w.style()
    st.unpolish(w)
    st.polish(w)
    w.update()


class Panel(QFrame):
    """Layer-01 container with the Figma panel header: 40 px, a body-compact-01 title at x = 16 and the panel's
    40 × 40 collapse button on the right edge (``collapse_btn``; ``collapsible=False`` leaves it out)."""

    def __init__(self, title: str = "", parent=None, collapsible: bool = True):
        super().__init__(parent)
        from ..theme import PANEL_HEADER_HEIGHT
        self.setObjectName("Panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)
        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(PANEL_PADDING_X, 0, 0, 0)
        self.title_row.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("PanelTitle")
        self.title_suffix = QLabel("")
        self.title_suffix.setObjectName("PanelTitleSuffix")
        self.title_row.addWidget(self.title)
        self.title_row.addWidget(self.title_suffix)
        self.title_row.addStretch(1)
        self.collapse_btn = None
        if collapsible and title:
            from .status_tag import HeaderIconButton
            self.collapse_btn = HeaderIconButton("panel_collapse", f"Collapse {title}")
            self.title_row.addWidget(self.collapse_btn)
        holder = QWidget()
        holder.setFixedHeight(PANEL_HEADER_HEIGHT)
        holder.setLayout(self.title_row)
        self.title_holder = holder
        self.root.addWidget(holder)


class Divider(QFrame):
    def __init__(self, vertical: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)


def button(text: str, kind: str = "ghost", size: str = "sm", parent=None) -> QPushButton:
    b = QPushButton(text, parent)
    b.setProperty("kind", kind)
    # Not "size": QWidget already declares a read-only `size` QSize property, so setProperty("size")
    # fails silently and the QSS selectors below never matched - every md button rendered 32 px
    # instead of 40 px.  `btnsize` has no collision.
    b.setProperty("btnsize", size)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return b


ILLUSTRATIONS_DIR = Path(__file__).resolve().parent.parent / "illustrations"
_ILLUSTRATIONS: dict[str, tuple[QSize, QPixmap]] = {}


def set_prop(w: QWidget, name: str, value) -> None:
    """Set a Qt property and re-polish, so a stylesheet attribute selector sees it immediately.

    Preferred over a widget-level ``setStyleSheet``: a widget that carries its own sheet stops
    inheriting the application rules, which is how the Export button lost its 16 px label padding.
    """
    w.setProperty(name, value)
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def illustration(name: str) -> tuple[QSize, QPixmap]:
    """Size and pixmap of an empty-state illustration, rendered at its exported Figma size.

    The artwork is theme-independent: the three files in ``hea_calc/ui/illustrations`` were
    exported with colours chosen to work in both themes, so nothing here depends on ``THEME`` and a
    theme switch must not recolour them.  The pixmap is rendered once and cached.
    """
    hit = _ILLUSTRATIONS.get(name)
    if hit is not None:
        return hit
    renderer = QSvgRenderer(str(ILLUSTRATIONS_DIR / f"{name}.svg"))
    size = renderer.defaultSize()
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p)
    p.end()
    _ILLUSTRATIONS[name] = (size, pm)
    return _ILLUSTRATIONS[name]


class Illustration(QWidget):
    """An empty-state illustration, sized to its exported artwork and left-aligned by its layout."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.setFixedSize(illustration(name)[0])
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), illustration(self.name)[1])
        p.end()


# Empty states (2026-10-28): the illustration / title / body group is centred vertically in the region it is
# given, optically - 45 % of the free height above it, 55 % below - with at least ``EMPTY_MIN_TOP`` above it, so
# it follows the panel's height and never clips.
EMPTY_ABOVE, EMPTY_BELOW = 9, 11          # stretch factors: 9 / 20 = 45 % of the free space above the group
EMPTY_MIN_TOP = 16


def empty_top(free: int, minimum: int = EMPTY_MIN_TOP) -> int:
    """Top offset of an empty-state group in a region with ``free`` px to spare (painted empty states): 45 % of the
    free height, never less than ``minimum`` (so a region at its natural height keeps the design's offset)."""
    return max(minimum, round(free * EMPTY_ABOVE / (EMPTY_ABOVE + EMPTY_BELOW)))


class EmptyState(QWidget):
    """Carbon empty state: illustration, title, body.

    The artwork sits at the panel's content margin, 24 px below it the title (20 px), directly under it the body
    (14 px).  Both are left-aligned, as in the design - Carbon's centred variant is not used anywhere in this
    app.  The group is centred vertically (optically, see ``EMPTY_ABOVE``) in the region.
    """

    def __init__(self, title: str, body: str, art: str | None = None, margin_x: int = 40,
                 margin_top: int = EMPTY_MIN_TOP, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margin_x, margin_top, 20, 0)
        lay.setSpacing(0)
        lay.addStretch(EMPTY_ABOVE)
        if art:
            lay.addWidget(Illustration(art), 0, Qt.AlignmentFlag.AlignLeft)
            lay.addSpacing(24)
        tt = QLabel(title)
        tt.setStyleSheet("font-size: 20px;")
        bd = QLabel(body)
        bd.setWordWrap(True)
        lay.addWidget(tt)
        lay.addWidget(bd)
        lay.addStretch(EMPTY_BELOW)


class MenuButton(QPushButton):
    """A button with an attached menu: label on the padding grid, chevron painted at the right.

    Qt reserves the platform's menu-indicator width inside the button's contents rect, so an
    attached menu silently moves the label off the grid: on the table toolbar's Export button the
    label rendered 4 px from the edge instead of 17 px, against `19_data_table_populated` and
    `21_dark_mode_fullscreen_tooltips`.  ``::menu-indicator { width: 0 }`` does not release the
    reservation - only clearing ``HasMenu`` does - but that also removes the indicator the design
    *does* show, so the chevron is painted here instead.

    Measured on the reference's 123x32 Export button: label ink at x 17..57 and a 16 px chevron
    whose ink is x 94..103, i.e. 16 px from the right edge.  ``setMenu`` still drives the popup.
    """

    CHEVRON = 16
    INDICATOR_PAD = 16

    def initStyleOption(self, option):
        super().initStyleOption(option)
        option.features &= ~QStyleOptionButton.ButtonFeature.HasMenu

    def attach(self, menu) -> None:
        """Carbon MenuButton: the click opens ``menu`` right-aligned and flush under the button; the chevron
        points up while it is open (CORRECT_MENU_BUTTON)."""
        self.menu_ = menu
        self.open = False
        self.clicked.connect(self._open_menu)
        menu.aboutToHide.connect(self._closed)

    def menu(self):                                # the attached Carbon menu (not QPushButton.setMenu)
        return getattr(self, "menu_", None) or super().menu()

    def _open_menu(self) -> None:
        self.open = True
        self.update()
        self.menu_.trigger_width = self.width()
        self.menu_.open_below(self, align_right=True)

    def _closed(self) -> None:
        self.open = False
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.isEnabled():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.CHEVRON
        x = self.width() - self.INDICATOR_PAD - size
        r = QRectF(x, (self.height() - size) / 2, size, size)
        if getattr(self, "open", False):
            p.translate(r.center())
            p.rotate(180)
            p.translate(-r.center())
        # icons on a coloured (secondary / primary) button surface use icon-on-color
        kind = self.property("kind")
        token = "icon-on-color" if kind in ("primary", "secondary", "danger") else "icon-primary"
        icons.paint(p, "chevron_down", r, token)
        p.end()


class IconButton(QPushButton):
    """Ghost icon-only button (Carbon icon button), painted rather than laid out by Qt.

    The icon is painted centred instead of going through ``QPushButton``'s icon+label layout.
    Qt inherits ``text-align: left`` from the sheet's base ``QPushButton`` rule, and a button
    with no text then places its icon at the *left* edge: measured 8 px left of centre in every
    32 × 32 button and 12.5 px in the 40 × 40 pagination buttons, in every state.  Painting here
    also keeps hover / pressed / active / disabled and the icon colour in one place instead of
    spread over stylesheet rules.
    """

    def __init__(self, icon_name: str, tooltip: str, parent=None, token: str = "icon-primary"):
        super().__init__(parent)
        self.icon_name = icon_name
        self.token = token
        self.setProperty("kind", "icon")
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(16, 16))
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def _size(self) -> int:
        return 16 if min(self.width(), self.height()) >= 32 else 12

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        enabled = self.isEnabled()
        bg = None
        if not enabled:
            bg = None
        elif self.isDown():
            bg = t("button-ghost-active")
        elif self.property("active") == "true" or self.isChecked():
            bg = t("layer-selected-01")
        elif self.underMouse():
            bg = t("button-ghost-hover")
        if bg:
            p.fillRect(r, QColor(bg))
        token = self.token if enabled else "icon-disabled"
        size = self._size()
        icons.paint(p, self.icon_name, QRectF((self.width() - size) / 2, (self.height() - size) / 2,
                                              size, size), token)
        if enabled and self.hasFocus():
            from .. import crisp
            from ..theme import FOCUS_WIDTH
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()


class TabButton(QAbstractButton):
    """One Carbon line tab (sm, 32 px), painted here.

    Label: body-compact-01, semibold when selected; underline 2 px - ``border-strong-01`` at rest,
    ``border-strong-02`` on hover, ``border-interactive`` when selected, ``border-disabled`` when
    disabled; keyboard focus draws the 2 px ``focus`` frame.  The underline and the focus frame are
    filled in device pixels (``crisp``), so the underline is the same thickness under every tab at
    any device pixel ratio.  The horizontal padding is the design's 16 px (scrollable :class:`LineTabs`
    never compress it).
    """

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(text)
        self.setFixedHeight(32)
        self.pad = 16
        self._hover = False
        from ..theme import HEADING_COMPACT_01
        self._semibold = font(HEADING_COMPACT_01)
        self._regular = font(BODY_COMPACT_01)
        # sized for the semibold (selected) label, so selecting a tab never moves its neighbours
        self.text_width = QFontMetrics(self._semibold).horizontalAdvance(text)
        self.set_padding(16)

    def set_padding(self, pad: int):
        self.pad = pad
        self.setFixedWidth(self.text_width + 2 * pad)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        from .. import crisp
        from ..theme import FOCUS_WIDTH, TAB_UNDERLINE
        p = QPainter(self)
        r = self.rect()
        enabled = self.isEnabled()
        if not enabled:
            line, text = "border-disabled", "text-disabled"
        elif self.isChecked():
            line, text = "border-interactive", "text-primary"
        elif self._hover:
            line, text = "border-strong-02", "text-primary"
        else:
            line, text = "border-strong-01", "text-secondary"
        crisp.hline_bottom(p, r, t(line), TAB_UNDERLINE)
        p.setFont(self._semibold if self.isChecked() else self._regular)
        p.setPen(QColor(t(text)))
        p.drawText(QRect(self.pad, 0, r.width() - self.pad, r.height() - 2),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.text())
        if enabled and self.hasFocus():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()


class _TabArrow(QAbstractButton):
    """Overflow button of scrollable line tabs (Carbon Tabs, "Line tab scrollable states"): the surface colour
    with an 8 px gradient fading into the tabs, a 16 px chevron in ``$icon-primary``; hover / active fill."""

    W = 40

    def __init__(self, direction: str, tabs: "LineTabs"):
        super().__init__(tabs)
        self.direction = direction
        self.tabs = tabs
        self.setFixedSize(self.W, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)            # keyboard users move with the arrow keys
        self.setAccessibleName("Scroll tabs left" if direction == "left" else "Scroll tabs right")
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        from PySide6.QtGui import QLinearGradient
        from .. import crisp
        p = QPainter(self)
        rest, hover, active = self.tabs.surface
        fill = QColor(t(active if self.isDown() else hover if self._hover else rest))
        body = QRectF(0, 0, self.W - 8, 32) if self.direction == "left" else QRectF(8, 0, self.W - 8, 32)
        p.fillRect(body, fill)
        fade = QRectF(self.W - 8, 0, 8, 32) if self.direction == "left" else QRectF(0, 0, 8, 32)
        g = QLinearGradient(fade.left(), 0, fade.right(), 0)
        clear = QColor(fill)
        clear.setAlpha(0)
        g.setColorAt(0.0, fill if self.direction == "left" else clear)
        g.setColorAt(1.0, clear if self.direction == "left" else fill)
        p.fillRect(fade, g)
        crisp.hline_bottom(p, QRectF(0, 0, self.W, 32), t("border-strong-01"), 1)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icons.paint(p, "chevron_left" if self.direction == "left" else "chevron_right",
                    QRectF(body.center().x() - 8, 8, 16, 16), "icon-primary")
        p.end()


class LineTabs(QWidget):
    """Carbon line tabs (small, auto width), scrollable when the row is too narrow.

    Every tab keeps its 16 px padding and its full label - never shrunk, wrapped or overlapped.  When the
    row cannot show all tabs, Carbon's scrollable pattern applies (CORRECT_SCROLLABLE_TABS_WHEN_TIGHT_SPACE,
    Carbon Tabs "Scrollable"): left / right overflow buttons appear at the clipped ends, and the selected or
    focused tab is always scrolled into view.  ``surface`` is the (rest, hover, active) token triple of what
    the tabs sit on - the overflow buttons take its colour.
    """

    changed = Signal(int)
    GAP = 1

    def __init__(self, labels: list[str], parent=None, surface=("layer-01", "layer-hover-01", "layer-active-01")):
        super().__init__(parent)
        self.surface = surface
        self.offset = 0
        self.strip = QWidget(self)
        lay = QHBoxLayout(self.strip)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self.GAP)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[TabButton] = []
        for i, text in enumerate(labels):
            b = TabButton(text)
            self.group.addButton(b, i)
            lay.addWidget(b)
            b.installEventFilter(self)
            self.buttons.append(b)
        self.natural = sum(b.width() for b in self.buttons) + self.GAP * (len(self.buttons) - 1)
        self.strip.setFixedSize(self.natural, 32)
        self.left_arrow = _TabArrow("left", self)
        self.right_arrow = _TabArrow("right", self)
        self.left_arrow.clicked.connect(lambda: self._step(-1))
        self.right_arrow.clicked.connect(lambda: self._step(1))
        self.setFixedHeight(32)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)
        self.group.idClicked.connect(lambda i: (self.ensure_visible(i), [b.update() for b in self.buttons]))
        self._relayout()

    # -------------------------------------------------------------- geometry
    def sizeHint(self) -> QSize:
        return QSize(self.natural, 32)

    def minimumSizeHint(self) -> QSize:
        return QSize(min(self.natural, 2 * _TabArrow.W + max(b.width() for b in self.buttons)), 32)

    def overflowing(self) -> bool:
        return self.natural > self.width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()
        if self.overflowing():
            self.ensure_visible(self.index())

    def _relayout(self) -> None:
        over = self.natural > self.width()
        self.offset = max(0, min(self.offset, self.natural - self.width())) if over else 0
        self.strip.move(-self.offset, 0)
        self.left_arrow.setVisible(over and self.offset > 0)
        self.right_arrow.setVisible(over and self.offset < self.natural - self.width())
        self.left_arrow.move(0, 0)
        self.right_arrow.move(self.width() - _TabArrow.W, 0)
        self.left_arrow.raise_()
        self.right_arrow.raise_()

    def ensure_visible(self, i: int) -> None:
        """Scroll so tab ``i`` is clear of the overflow buttons."""
        if not self.overflowing() or not 0 <= i < len(self.buttons):
            return
        b = self.buttons[i]
        left, right = b.x(), b.x() + b.width()
        lo = self.offset + (_TabArrow.W if self.offset > 0 else 0)
        hi = self.offset + self.width() - _TabArrow.W
        if left < lo:
            self.offset = 0 if i == 0 else left - _TabArrow.W
        elif right > hi:
            self.offset = (self.natural - self.width()) if i == len(self.buttons) - 1 else \
                right - self.width() + _TabArrow.W
        self._relayout()

    def _step(self, d: int) -> None:
        """Overflow buttons: bring the next tab hidden on that side into view."""
        vis_l = self.offset + (_TabArrow.W if self.offset > 0 else 0)
        vis_r = self.offset + self.width() - (_TabArrow.W if self.offset < self.natural - self.width() else 0)
        if d > 0:
            nxt = next((i for i, b in enumerate(self.buttons) if b.x() + b.width() > vis_r), len(self.buttons) - 1)
        else:
            nxt = next((i for i in range(len(self.buttons) - 1, -1, -1) if self.buttons[i].x() < vis_l), 0)
        self.ensure_visible(nxt)

    def wheelEvent(self, e):
        if not self.overflowing():
            return super().wheelEvent(e)
        d = e.angleDelta().x() or e.angleDelta().y()
        self.offset -= int(d / 2)
        self._relayout()
        e.accept()

    def eventFilter(self, obj, ev):
        if ev.type() == ev.Type.FocusIn and obj in self.buttons:
            self.ensure_visible(self.buttons.index(obj))
        return False

    # -------------------------------------------------------------- state
    def set_index(self, i: int) -> None:
        self.buttons[i].setChecked(True)
        self.ensure_visible(i)

    def index(self) -> int:
        return self.group.checkedId()

    def keyPressEvent(self, e):  # arrow keys move between tabs (Carbon keyboard pattern)
        i = self.index()
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Left):
            j = (i + (1 if e.key() == Qt.Key.Key_Right else -1)) % len(self.buttons)
            self.buttons[j].setChecked(True)
            self.buttons[j].setFocus()
            self.ensure_visible(j)
            self.changed.emit(j)
            return
        super().keyPressEvent(e)


class _SwitchItem(QAbstractButton):
    def __init__(self, icon_name: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setCheckable(True)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        # Measured in 21_dark_mode_fullscreen_tooltips: three contiguous 32 px segments, no gap;
        # the selected one carries a 1 px #f4f4f4 frame over #404040 and its icon is #f4f4f4; a
        # hovered segment is #333333 with the same bright icon; an unselected one is #212121 with a
        # #c6c6c6 icon.  The group's own surface, outline and the hover fill are painted by
        # IconContentSwitcher so the 1 px outline is not covered by the segments.  Rounded with the
        # CORNER_RADIUS token; frames in device pixels (crisp).
        from .. import crisp
        from ..theme import CORNER_RADIUS, FOCUS_WIDTH
        p = QPainter(self)
        r = self.rect()
        if self.isChecked():
            crisp.fill_rounded(p, r, CORNER_RADIUS, t("switcher-selected"))
            crisp.frame(p, r, 1, t("border-inverse"), CORNER_RADIUS)
            token = "icon-primary"
        else:
            token = "icon-primary" if self._hover else "icon-secondary"
        if self.hasFocus():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"), CORNER_RADIUS)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icons.paint(p, self.icon_name, QRectF(8, 8, 16, 16), token)
        p.end()


class IconContentSwitcher(QFrame):
    """Carbon icon-only content switcher (Figma 278:30258: 96 x 32), rounded with CORNER_RADIUS.

    Paints the group's surface (#212121 in the dark theme - darker than the panel's #262626), the
    hovered segment's fill, 1 px dividers between unselected neighbours and its 1 px
    ``border-strong-02`` outline (#8d8d8d, measured on the top, bottom and right edges of
    21_dark_mode_fullscreen_tooltips); the segments only add the selected frame and the icons, so the
    outline stays visible across the open segments.
    """

    changed = Signal(int)
    SEGMENT = 32

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SEGMENT * len(items), self.SEGMENT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.items: list[_SwitchItem] = []
        for i, (name, tip) in enumerate(items):
            it = _SwitchItem(name, tip, self)
            self.group.addButton(it, i)
            lay.addWidget(it)
            self.items.append(it)
        self.items[0].setChecked(True)
        self.group.idClicked.connect(self._clicked)

    def _clicked(self, i):
        self.update()
        self.changed.emit(i)

    def set_index(self, i: int):
        self.items[i].setChecked(True)
        self.update()

    def index(self) -> int:
        return self.group.checkedId()

    def paintEvent(self, _e):
        from .. import crisp
        from ..theme import CORNER_RADIUS, HAIRLINE
        p = QPainter(self)
        r = self.rect()
        crisp.fill_rounded(p, r, CORNER_RADIUS, t("switcher-unselected"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(r), CORNER_RADIUS, CORNER_RADIUS)
        p.save()
        p.setClipPath(path)
        idx = self.index()
        for i, it in enumerate(self.items):
            if it._hover and not it.isChecked():
                crisp.fill_rect(p, QRectF(i * self.SEGMENT, 0, self.SEGMENT, self.height()), t("layer-hover-01"))
        p.restore()
        for i in range(1, len(self.items)):
            if i != idx and i - 1 != idx and not (self.items[i]._hover or self.items[i - 1]._hover):
                crisp.vline(p, i * self.SEGMENT, 8, 24, t("border-strong-01"), HAIRLINE)
        crisp.frame(p, r, HAIRLINE, t("border-strong-02"), CORNER_RADIUS)
        p.end()


def tag_width(label: str, font_px: int = 12) -> float:
    """Width :func:`paint_tag` gives ``label`` (text + 8 px padding on each side)."""
    f = font(LABEL_01)
    f.setPixelSize(font_px)
    return QFontMetrics(f).horizontalAdvance(label) + 16


def paint_tag(p: QPainter, rect: QRectF, label: str, *, height: float = 18.0, font_px: int = 12,
              align_left: bool = False) -> float:
    """Paint a read-only Carbon tag (pill) for a scientific result class centred in ``rect``.

    Returns the painted width.
    """
    bg, fg = THEME.tag_colors(label)
    f = font(LABEL_01)
    f.setPixelSize(font_px)
    fm = QFontMetrics(f)
    w = fm.horizontalAdvance(label) + 16
    h = height
    x = rect.x() if align_left else rect.x() + (rect.width() - w) / 2
    y = rect.y() + (rect.height() - h) / 2
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillPath(path, QColor(bg))
    p.setPen(QColor(fg))
    p.setFont(f)
    p.drawText(QRectF(x, y, w, h), Qt.AlignmentFlag.AlignCenter, label)
    p.restore()
    return w


class TagLabel(QWidget):
    """Read-only tag widget (used in details tiles)."""

    def __init__(self, label: str = "N/A", long_text: bool = True, parent=None):
        super().__init__(parent)
        self.long_text = long_text
        self.set_label(label)
        THEME.changed.connect(self._theme_changed)

    def _theme_changed(self, *_):
        self.update()

    def set_label(self, label: str):
        self.label = label
        self.text = TAG_LONG_NAMES.get(label, label) if self.long_text else label
        fm = QFontMetrics(font(LABEL_01))
        self.setFixedSize(fm.horizontalAdvance(self.text) + 16, 24)
        self.setToolTip(TAG_LONG_NAMES.get(label, label))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        bg, fg = THEME.tag_colors(self.label)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        h = self.height() / 2           # pill (Carbon tag), not the CORNER_RADIUS token
        path.addRoundedRect(QRectF(self.rect()), h, h)
        p.fillPath(path, QColor(bg))
        p.setPen(QColor(fg))
        p.setFont(font(LABEL_01))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text)
        p.end()


class InlineNotification(QFrame):
    """Carbon inline notification, low contrast - the one notification component of the application
    (CORRECT_NOTIFICATION; Carbon MCP components/notification "Specifications - Low contrast / Inline").

    Painted: ``notification-<kind>-bg`` surface, a 1 px ``$support-<kind>`` border at 40 % opacity, the 3 px
    ``$support-<kind>`` left accent and the 20 px filled status icon 16 px in; title (heading-compact-01) above the
    message (body-compact-01), both ``$text-primary``, 12 px block padding (min height 48).  Optional ghost
    action (actionable notification) and the 48 px close button.
    """

    closed = Signal()
    action = Signal()
    ICONS = {"error": "notify_error", "warning": "notify_warning", "success": "notify_success",
             "info": "notify_info"}
    ICON_SIZE = 20
    TEXT_X = 48

    def __init__(self, parent=None, closable: bool = True):
        super().__init__(parent)
        self.setObjectName("InlineNotification")
        self.kind = "info"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(self.TEXT_X, 12, 0 if closable else 16, 12)
        lay.setSpacing(16)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("NotificationTitle")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setWordWrap(True)
        self.body = QLabel()
        self.body.setObjectName("NotificationBody")
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setWordWrap(True)
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        texts.addWidget(self.title)
        texts.addWidget(self.body)
        lay.addLayout(texts, 1)
        self.button = button("", "ghost", "sm")
        self.button.clicked.connect(self.action.emit)
        self.button.hide()
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.close_btn = IconButton("close", "Close notification")
        self.close_btn.setFixedSize(48, 48)
        self.close_btn.clicked.connect(self.dismiss)
        self.close_btn.setVisible(closable)
        lay.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.closable = closable
        self.setMinimumHeight(48)
        self.hide()

    def show_message(self, kind: str, title: str, body: str = "", action: str = ""):
        self.kind = kind if kind in self.ICONS else "info"
        self.setProperty("kind", self.kind)
        self.title.setText(sup_html(title))
        self.body.setText(sup_html(body))
        self.body.setVisible(bool(body))
        self.title.setVisible(bool(title))
        self.button.setText(action)
        self.button.setVisible(bool(action))
        if self.parentWidget() is None:
            # Not placed yet (built, filled, then added to a layout): showing a parentless widget creates a native
            # top-level window for a moment - the small window that flashed open and shut in Model details.  It is
            # shown when it gets its parent instead.
            self._show_when_parented = True
        else:
            self.show()
        self.update()

    def event(self, e):
        if e.type() == QEvent.Type.ParentChange and getattr(self, "_show_when_parented", False)                 and self.parentWidget() is not None:
            self._show_when_parented = False
            self.show()
        return super().event(e)

    def dismiss(self):
        self.hide()
        self.closed.emit()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        support = QColor(t(f"support-{self.kind}"))
        crisp.fill_rect(p, r, t(f"notification-{self.kind}-bg"))
        edge = QColor(support)
        edge.setAlphaF(0.4)
        crisp.frame(p, r, 1, edge)
        crisp.fill_rect(p, QRect(0, 0, 3, r.height()), support)
        icons.paint(p, self.ICONS[self.kind], QRectF(16, 14, self.ICON_SIZE, self.ICON_SIZE))
        p.end()


def key_value_label(key_html: str, value_html: str) -> tuple[QLabel, QLabel]:
    k = QLabel(key_html)
    k.setObjectName("KeyValueKey")
    k.setTextFormat(Qt.TextFormat.RichText)
    v = QLabel(value_html)
    v.setObjectName("KeyValueValue")
    v.setTextFormat(Qt.TextFormat.RichText)
    v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return k, v


class _WheelFilter(QObject):
    """Ignore wheel events on unfocused inputs so that the surrounding scroll area scrolls instead."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel and not obj.hasFocus():
            ev.ignore()
            return True
        return False


_WHEEL_FILTER: _WheelFilter | None = None


def install_wheel_guard(w: QWidget) -> None:
    global _WHEEL_FILTER
    if _WHEEL_FILTER is None:
        _WHEEL_FILTER = _WheelFilter()
    w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    w.installEventFilter(_WHEEL_FILTER)


# ====================================================================================== vertical tabs
from ..theme import HAIRLINE  # noqa: E402 (vertical tabs only)
class VerticalTab(QAbstractButton):
    """One Carbon vertical tab, lg (48 px): the label (body-compact-01) on the left and, on the same row, a result-class
    tag right-aligned (8 px from the label at the least, 16 px padding); a label that cannot fit beside the tag is
    elided - never overlapped - and the accessible name keeps it in full.

    Carbon v11 Tabs specification (vertical): unselected - ``$layer`` surface, 1 px ``$border-subtle`` bottom, right
    and left edges, ``$text-secondary`` label; selected - ``$layer`` surface, 1 px ``$border-subtle`` bottom, 3 px
    ``$border-interactive`` left indicator, no right edge (the tab opens into its panel), ``$text-primary`` label;
    hover - ``$layer-hover``, ``$text-primary``; focus - the 2 px ``$focus`` frame; 16 px label padding.  ``layer``
    is the contextual layer the tabs sit on: by default resolved from the host surface (ui/surface.py) - ``01`` in a
    region of the expanded workspace, ``02`` in a region of the docked panel."""

    HEIGHT = 48
    INDICATOR = 3
    TAG_GAP = 8

    def __init__(self, text: str, tag: str = "", layer: str | None = None, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.tag = tag
        self.layer = layer
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedHeight(self.HEIGHT)
        self._hover = False
        self._sync_name()

    def _sync_name(self) -> None:
        self.setAccessibleName(self.text() + (f", prediction {self.tag}" if self.tag else ""))

    def set_tag(self, tag: str) -> None:
        self.tag = tag
        self._sync_name()
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        from .. import crisp
        from ..theme import FOCUS_WIDTH
        p = QPainter(self)
        r = self.rect()
        on = self.isChecked()
        hover = self._hover and self.isEnabled() and not on
        layer = self.layer or contextual_layer(self)
        crisp.fill_rect(p, r, t(f"layer-hover-{layer}" if hover else f"layer-{layer}"))
        edge = t(f"border-subtle-{layer}")
        crisp.hline_bottom(p, r, edge, HAIRLINE)
        if on:
            crisp.fill_rect(p, QRectF(0, 0, self.INDICATOR, r.height()), t("border-interactive"))
        else:
            crisp.vline_left(p, r, edge, HAIRLINE)
            crisp.vline_right(p, r, edge, HAIRLINE)
        text = "text-primary" if (on or hover) else ("text-secondary" if self.isEnabled() else "text-on-color-disabled")
        p.setFont(font(BODY_COMPACT_01))
        p.setPen(QColor(t(text)))
        x = 16
        tw = tag_width(self.tag) if self.tag else 0.0
        tag_x = r.width() - x - tw
        room = (tag_x - self.TAG_GAP if self.tag else r.width() - x) - x
        f = font(BODY_COMPACT_01)
        text = QFontMetrics(f).elidedText(self.text(), Qt.TextElideMode.ElideRight, max(0, int(room)))
        p.drawText(QRectF(x, 0, max(0.0, room), r.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        if self.tag:
            paint_tag(p, QRectF(tag_x, 0, tw, r.height()), self.tag, align_left=True)
        if self.hasFocus():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()


class VerticalTabs(QWidget):
    """Carbon vertical tabs: the tab list on the left of its panel, with the tablist's *extended background* (its
    right edge continues under the last tab).  One tab in the Tab sequence (the selected one); Up / Down, Home / End
    move the selection (automatic activation, like the app's line tabs).  ``changed(index)`` on every user choice;
    :meth:`set_index` selects without emitting."""

    changed = Signal(int)

    def __init__(self, labels: list[str], width: int = 280, layer: str | None = None, accessible: str = "",
                 parent=None):
        super().__init__(parent)
        self.layer = layer
        self.setFixedWidth(width)
        self.setAccessibleName(accessible or "Tabs")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.tabs: list[VerticalTab] = []
        for i, text in enumerate(labels):
            b = VerticalTab(text, layer=layer)
            self.group.addButton(b, i)
            b.installEventFilter(self)
            lay.addWidget(b)
            self.tabs.append(b)
        lay.addStretch(1)
        if self.tabs:
            self.tabs[0].setChecked(True)
        self.group.idClicked.connect(self._chosen)
        self._sync_focus_policy()

    @property
    def index(self) -> int:
        return self.group.checkedId()

    def set_index(self, i: int) -> None:
        if 0 <= i < len(self.tabs) and i != self.index:
            self.tabs[i].setChecked(True)
            self._sync_focus_policy()
            for b in self.tabs:
                b.update()

    def set_tags(self, tags: list[str]) -> None:
        for b, tag in zip(self.tabs, tags):
            b.set_tag(tag)

    def _chosen(self, i: int) -> None:
        self._sync_focus_policy()
        for b in self.tabs:
            b.update()
        self.changed.emit(i)

    def _sync_focus_policy(self) -> None:
        """Roving Tab stop: only the selected tab is reached with Tab; arrows move within the list."""
        for i, b in enumerate(self.tabs):
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus if i == self.index else Qt.FocusPolicy.ClickFocus)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress and obj in self.tabs:
            i = self.tabs.index(obj)
            j = {Qt.Key.Key_Up: i - 1, Qt.Key.Key_Down: i + 1, Qt.Key.Key_Home: 0,
                 Qt.Key.Key_End: len(self.tabs) - 1}.get(ev.key())
            if j is not None:
                j = max(0, min(len(self.tabs) - 1, j))
                if j != i:
                    self.tabs[j].setChecked(True)
                    self.tabs[j].setFocus(Qt.FocusReason.TabFocusReason)
                    self._chosen(j)
                return True
        return super().eventFilter(obj, ev)

    def paintEvent(self, _e):
        """The extended background under the tabs: the tablist surface with its right edge."""
        from .. import crisp
        p = QPainter(self)
        r = self.rect()
        layer = self.layer or contextual_layer(self)
        crisp.fill_rect(p, r, t(f"layer-{layer}"))
        crisp.vline_right(p, r, t(f"border-subtle-{layer}"), HAIRLINE)
        p.end()


def contextual_layer(widget) -> str:
    """``"01"`` / ``"02"``: the Carbon layer of the surface ``widget`` sits on (ui/surface.py)."""
    from ..surface import surface_level
    return f"{max(1, min(2, surface_level(widget))):02d}"
