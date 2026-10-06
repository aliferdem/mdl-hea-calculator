"""Reusable Carbon-inspired building blocks (styling via theme tokens, behaviour per Carbon v11)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QStyleOptionButton, QVBoxLayout,
                               QWidget)

from .. import icons
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


def refresh_style(w: QWidget) -> None:
    """Re-polish after a dynamic property change so QSS selectors re-evaluate."""
    st = w.style()
    st.unpolish(w)
    st.polish(w)
    w.update()


class Panel(QFrame):
    """Layer-01 container with a 16 px semibold title at the Figma position (20, 20)."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)
        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(PANEL_PADDING_X, 0, PANEL_PADDING_X, 0)
        self.title_row.setSpacing(4)
        self.title = QLabel(title)
        self.title.setObjectName("PanelTitle")
        self.title_suffix = QLabel("")
        self.title_suffix.setObjectName("PanelTitleSuffix")
        self.title_row.addWidget(self.title)
        self.title_row.addWidget(self.title_suffix)
        self.title_row.addStretch(1)
        holder = QWidget()
        holder.setFixedHeight(56)
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


class EmptyState(QWidget):
    """Carbon empty state: illustration, title, body.

    Geometry is the Figma one: the artwork sits at the panel's content margin, 24 px below it the
    title (20 px), directly under it the body (14 px).  Both are left-aligned, as in the design -
    Carbon's centred variant is not used anywhere in this app.
    """

    def __init__(self, title: str, body: str, art: str | None = None, margin_x: int = 40,
                 margin_top: int = 40, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(margin_x, margin_top, 20, 0)
        lay.setSpacing(0)
        if art:
            lay.addWidget(Illustration(art), 0, Qt.AlignmentFlag.AlignLeft)
            lay.addSpacing(24)
        tt = QLabel(title)
        tt.setStyleSheet("font-size: 20px;")
        bd = QLabel(body)
        bd.setWordWrap(True)
        lay.addWidget(tt)
        lay.addWidget(bd)
        lay.addStretch(1)


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

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.isEnabled():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = self.CHEVRON
        x = self.width() - self.INDICATOR_PAD - size
        icons.paint(p, "chevron_down", QRectF(x, (self.height() - size) / 2, size, size),
                    "icon-primary" if not self.isDown() else "icon-primary")
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
    any device pixel ratio.  The horizontal padding is set by :class:`LineTabs` (16 px design,
    compressed on narrow panels).
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


class LineTabs(QWidget):
    """Carbon line tabs (small, auto width).

    Tabs keep the design's 16 px padding when the row has room; on a narrower panel the padding of
    every tab shrinks equally (down to 6 px) so all five tabs stay visible and unclipped, instead of
    the row overflowing (``responsive.tab_padding``).
    """

    changed = Signal(int)
    GAP = 1

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self.GAP)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[TabButton] = []
        for i, text in enumerate(labels):
            b = TabButton(text)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        lay.addStretch(1)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)
        self.group.idClicked.connect(lambda _i: [b.update() for b in self.buttons])

    def minimumSizeHint(self) -> QSize:
        from ..responsive import tab_padding
        widths = [b.text_width for b in self.buttons]
        pad = tab_padding(0, widths, self.GAP)
        return QSize(sum(widths) + 2 * pad * len(widths) + self.GAP * (len(widths) - 1), 32)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        from ..responsive import tab_padding
        pad = tab_padding(self.width(), [b.text_width for b in self.buttons], self.GAP)
        for b in self.buttons:
            if b.pad != pad:
                b.set_padding(pad)

    def set_index(self, i: int) -> None:
        self.buttons[i].setChecked(True)

    def index(self) -> int:
        return self.group.checkedId()

    def keyPressEvent(self, e):  # arrow keys move between tabs (Carbon keyboard pattern)
        i = self.index()
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Left):
            j = (i + (1 if e.key() == Qt.Key.Key_Right else -1)) % len(self.buttons)
            self.buttons[j].setChecked(True)
            self.buttons[j].setFocus()
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
    """Carbon inline notification (low-contrast) with optional close button."""

    closed = Signal()

    ICONS = {"error": "status_none", "warning": "status_warn", "success": "status_ok", "info": "information"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InlineNotification")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 0, 0, 0)
        lay.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.close_btn = IconButton("close", "Close notification")
        self.close_btn.clicked.connect(self.dismiss)
        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addWidget(self.body, 1)
        lay.addWidget(self.close_btn)
        self.setMinimumHeight(48)
        self.hide()

    def show_message(self, kind: str, title: str, body: str = ""):
        self.setProperty("kind", kind)
        refresh_style(self)
        self.icon.setPixmap(icons.pixmap(self.ICONS.get(kind, "information"), "icon-primary", 20))
        self.title.setText(title)
        self.body.setText(body)
        self.show()

    def dismiss(self):
        self.hide()
        self.closed.emit()


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
