"""Reusable Carbon-inspired building blocks (styling via theme tokens, behaviour per Carbon v11)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import icons
from ..theme import (CONTROL_HEIGHT, LABEL_01, PANEL_PADDING_X, TAG_LONG_NAMES, THEME, font, t)


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
    b.setProperty("size", size)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return b


class IconButton(QPushButton):
    """32 × 32 ghost icon button with a tooltip (Carbon icon-only button)."""

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
        self.refresh_icon()
        THEME.changed.connect(self.refresh_icon)

    def refresh_icon(self, *_):
        self.setIcon(icons.icon(self.icon_name, self.token))


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
        if self.isChecked():
            path = QPainterPath()
            path.addRoundedRect(r, 4, 4)
            p.fillPath(path, QColor(t("switcher-selected")))
            p.setPen(QPen(QColor(t("border-inverse")), 1))
            p.drawPath(path)
            token = "icon-primary"
        else:
            if self._hover:
                p.fillRect(r, QColor(t("layer-hover-01")))
            token = "icon-secondary"
        if self.hasFocus():
            p.setPen(QPen(QColor(t("focus")), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        icons.paint(p, self.icon_name, QRectF(8, 8, 16, 16), token)
        p.end()


class IconContentSwitcher(QFrame):
    """Carbon icon-only content switcher (Figma 278:30258: 96 × 32, 4 px radius)."""

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
