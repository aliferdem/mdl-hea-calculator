"""Reusable Carbon-inspired building blocks (styling via theme tokens, behaviour per Carbon v11)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QStyleOptionButton, QVBoxLayout,
                               QWidget)

from .. import icons
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


class CarbonToolTip(QWidget):
    """The design's tooltip: inverse surface, 2 px radius and a caret on the anchor's edge.

    Qt's native ``QToolTip`` is a plain rectangle with no caret, and the design has one -
    ``design/components/_Tooltip body item.png`` ("Composition space") carries a downward caret
    centred under the button, and ``Group 241.png`` (the model-support legend) a small upward
    caret on its top edge because that tooltip opens *below* its anchor.  Measured at 3x:
    body #f4f4f4, text #161616, radius ~2 px, caret ~12 px wide at the base tapering over ~4 px,
    single-line body 28 px tall with the text band 6.7-16.7 px inside it.
    """

    PAD_X, PAD_Y = 16, 6
    CARET_W, CARET_H, RADIUS = 6, 3, 2
    GAP = 6          # from the caret's tip to the anchor's edge
    WRAP = 170       # the reference's two-line tip breaks after 166 px of text

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._lines: list[str] = [""]
        self._below = False
        self._caret_x = 0
        self._caret = False
        self.setFont(font(BODY_COMPACT_01))

    def text_rect(self) -> QRectF:
        """Box holding the glyphs.  Its height follows the ink, not the line box: the reference's
        single-line tip measures 10.3 px of ink inside a 24 px body with ~6.5 px of padding, so a
        font-metrics line height would make the tip 7 px too tall."""
        fm = QFontMetrics(self.font())
        w = max((fm.horizontalAdvance(l) for l in self._lines), default=0)
        ink = fm.tightBoundingRect(self._lines[0] if self._lines else "").height()
        h = ink + max(0, len(self._lines) - 1) * fm.lineSpacing()
        return QRectF(self.PAD_X, self.PAD_Y, w, h)

    def body_size(self) -> QSize:
        r = self.text_rect()
        return QSize(int(r.width()) + 2 * self.PAD_X, int(r.height()) + 2 * self.PAD_Y)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t("border-inverse")))
        caret = self.CARET_H if self._caret else 0
        body = QRectF(0, 0, self.width(), self.height() - caret)
        p.drawRoundedRect(body, self.RADIUS, self.RADIUS)
        if self._caret:
            cx = self._caret_x
            half = self.CARET_W / 2
            if self._below:
                base = body.bottom()
                tri = QPolygonF([QPointF(cx - half, base), QPointF(cx + half, base),
                                 QPointF(cx, self.height() - 0.5)])
            else:
                tri = QPolygonF([QPointF(cx - half, self.CARET_H), QPointF(cx + half, self.CARET_H),
                                 QPointF(cx, 0.5)])
            p.drawPolygon(tri)
        fm = QFontMetrics(self.font())
        p.setPen(QColor(t("text-inverse")))
        p.setFont(self.font())
        tight = fm.tightBoundingRect(self._lines[0] if self._lines else "")
        y = self.PAD_Y + (tight.top() if tight.height() else fm.ascent())
        for line in self._lines:
            p.drawText(QPointF(self.PAD_X, y - tight.top()), line)
            y += fm.lineSpacing()
        p.end()

    def show_for(self, anchor: QRect, text: str, screen: QRect) -> None:
        """Place the tip above ``anchor`` (or below it if there is no room), caret on the anchor.

        The reference places the body so the **caret** lands on the anchor's centre, not so the
        body is centred on it: measured in 21_dark_mode_fullscreen_tooltips, the "Clear table" body
        is x 1615..1716 with the caret at 1696.5 while the trash button's centre is 1696 - the body
        hangs 66 px to the left of the button.  The caret tip is 6 px above the anchor's top edge.

        Near a screen edge the body may not fit at all, and then the caret would point at nothing:
        in that case it is dropped rather than drawn somewhere misleading.
        """
        fm = QFontMetrics(self.font())
        lines: list[str] = []
        for line in (text.split("\n") or [text]):
            lines.extend(self._wrap(line, fm, self.WRAP))
        self._lines = lines
        size = self.body_size()
        self.resize(size.width(), size.height() + self.CARET_H)
        below = anchor.top() - self.GAP - self.height() < screen.top()
        self._below = below
        y = anchor.top() - self.GAP - self.height() if not below else anchor.bottom() + self.GAP
        y = max(screen.top(), min(y, screen.bottom() - self.height() + 1))
        # centre the body on the anchor, then keep it on screen (QRect::right() is inclusive)
        x = anchor.center().x() - self.width() // 2
        x = max(screen.left(), min(x, screen.right() - self.width() + 1))
        self.move(x, y)
        centre = anchor.center().x() - self.x()
        margin = self.CARET_W          # keep the triangle off the rounded corners
        self._caret = (margin <= centre <= self.width() - margin)
        self._caret_x = int(centre)
        self.show()

    @staticmethod
    def _wrap(line: str, fm: QFontMetrics, width: int) -> list[str]:
        out, cur = [], ""
        for word in line.split(" "):
            trial = f"{cur} {word}".strip()
            if cur and fm.horizontalAdvance(trial) > width:
                out.append(cur)
                cur = word
            else:
                cur = trial
        out.append(cur)
        return out


class _ToolTipFilter(QObject):
    """Shows :class:`CarbonToolTip` for any widget with a tooltip, in place of Qt's own.

    Installed once on the application, so every existing ``setToolTip`` call site keeps working and
    a call site that clears the tooltip removes ours too.
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.tip: CarbonToolTip | None = None

    def hide(self):
        if self.tip is not None:
            self.tip.hide()

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.ToolTip:
            return False
        tip = obj.toolTip() if hasattr(obj, "toolTip") else ""
        if not tip:
            self.hide()
            return False
        if self.tip is None:
            self.tip = CarbonToolTip()
        g = obj.mapToGlobal(QPoint(0, 0))
        rect = QRect(g.x(), g.y(), obj.width(), obj.height())
        screen = QApplication.screenAt(g) or self.app.primaryScreen()
        self.tip.show_for(rect, tip, screen.availableGeometry())
        return True


_TOOLTIP_FILTER: _ToolTipFilter | None = None


def install_tooltips(app) -> None:
    """Route every tooltip through :class:`CarbonToolTip` (idempotent)."""
    global _TOOLTIP_FILTER
    if _TOOLTIP_FILTER is None:
        _TOOLTIP_FILTER = _ToolTipFilter(app)
        app.installEventFilter(_TOOLTIP_FILTER)


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
            p.setPen(QPen(QColor(t("focus")), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(r).adjusted(1, 1, -1, -1))
        p.end()


class LineTabs(QWidget):
    """Carbon line tabs (small, auto width)."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setObjectName("TabButton")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            # size for the semibold (selected) label so the text never clips when selected
            from ..theme import HEADING_COMPACT_01
            b.setMinimumWidth(QFontMetrics(font(HEADING_COMPACT_01)).horizontalAdvance(text) + 34)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        lay.addStretch(1)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)

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
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # Measured in 21_dark_mode_fullscreen_tooltips: three contiguous 32 px segments, no gap;
        # the selected one carries a 1 px #f4f4f4 frame over #404040 and its icon is #f4f4f4; a
        # hovered segment is #333333 with the same bright icon; an unselected one is #212121 with a
        # #c6c6c6 icon.  The group's own surface, outline and the hover fill are painted by
        # IconContentSwitcher so the 1 px outline is not covered by the segments.
        if self.isChecked():
            path = QPainterPath()
            path.addRoundedRect(r, 4, 4)
            p.fillPath(path, QColor(t("switcher-selected")))
            p.setPen(QPen(QColor(t("border-inverse")), 1))
            p.drawPath(path)
            token = "icon-primary"
        else:
            token = "icon-primary" if self._hover else "icon-secondary"
        if self.hasFocus():
            p.setPen(QPen(QColor(t("focus")), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        icons.paint(p, self.icon_name, QRectF(8, 8, 16, 16), token)
        p.end()


class IconContentSwitcher(QFrame):
    """Carbon icon-only content switcher (Figma 278:30258: 96 × 32, 4 px radius).

    Paints the group's surface (#212121 in the dark theme - darker than the panel's #262626), its
    1 px ``border-strong-02`` outline (#8d8d8d, measured on the top, bottom and right edges of
    21_dark_mode_fullscreen_tooltips) and the hovered segment's fill; the segments themselves only
    add the selected frame and the icons, so the outline stays visible across the open segments.
    """

    changed = Signal(int)

    def __init__(self, items: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.setFixedSize(32 * len(items), 32)
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

    def paintEvent(self, _e):
        p = QPainter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t("switcher-unselected")))
        p.drawRoundedRect(r, 4, 4)
        for i, it in enumerate(self.items):
            if it._hover and not it.isChecked():
                p.fillRect(QRectF(i * 32, 1, 32, self.height() - 2), QColor(t("layer-hover-01")))
        # the outline last, without antialiasing, so its 1 px rows are crisp like the reference's
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(QPen(QColor(t("border-strong-02")), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 4, 4)
        p.end()

    def _clicked(self, i):
        self.update()
        self.changed.emit(i)

    def set_index(self, i: int):
        self.items[i].setChecked(True)
        self.update()

    def _clicked(self, i):
        self.update()
        self.changed.emit(i)

    def set_index(self, i: int):
        self.items[i].setChecked(True)
        self.update()

    def index(self) -> int:
        return self.group.checkedId()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 4, 4)
        p.fillPath(path, QColor(t("switcher-unselected")))
        p.setPen(QPen(QColor(t("border-strong-02")), 1))
        p.drawPath(path)
        # dividers between unselected neighbours
        idx = self.index()
        p.setPen(QPen(QColor(t("border-strong-01")), 1))
        for i in range(1, len(self.items)):
            if i != idx and i - 1 != idx:
                x = 32 * i + 0.5
                p.drawLine(int(x), 8, int(x), 24)
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
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.fillPath(path, QColor(bg))
        p.setPen(QColor(fg))
        p.setFont(font(LABEL_01))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text)
        p.end()


class Toggletip(QFrame):
    """Carbon toggletip: click the (i) button to open, Esc/click elsewhere to close."""

    def __init__(self, anchor: QWidget, text: str):
        super().__init__(anchor.window(), Qt.WindowType.Popup)
        self.setObjectName("Toggletip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setFixedWidth(288)
        lay.addWidget(lbl)
        self.setStyleSheet(f"#Toggletip {{ background: {t('border-inverse')}; }} QLabel {{ color: {t('text-inverse')};"
                           f" font-size: 14px; }}")
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        self.move(pos)


class InfoButton(QAbstractButton):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.tip_text = text
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("More information")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip("Show legend")
        self.clicked.connect(self._open)

    def _open(self):
        Toggletip(self, self.tip_text).show()

    def paintEvent(self, _e):
        p = QPainter(self)
        icons.paint(p, "information", QRectF(0, 0, 16, 16), "icon-secondary")
        if self.hasFocus():
            p.setPen(QPen(QColor(t("focus")), 1))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
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
