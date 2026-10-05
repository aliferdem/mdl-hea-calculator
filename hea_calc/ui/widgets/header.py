"""Application header (Figma 170:11393, Carbon UI shell header translated to Qt)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from .. import icons
from ..theme import HEADER_HEIGHT, t
from .common import refresh_style


class HeaderMenuItem(QPushButton):
    """UI shell header menu item (48 px, text-secondary, optional chevron)."""

    def __init__(self, text: str, menu: QMenu | None = None, parent=None):
        super().__init__(text, parent)
        self.setObjectName("HeaderMenuItem")
        self.setFixedHeight(HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_ = menu
        from PySide6.QtGui import QFontMetrics
        from ..theme import BODY_COMPACT_01, font
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        fm = QFontMetrics(font(BODY_COMPACT_01))
        self.setFixedWidth(fm.horizontalAdvance(text) + 32 + (24 if menu else 0))
        if menu is not None:
            self.clicked.connect(self._open)
            menu.aboutToHide.connect(lambda: self._set_open(False))

    def _set_open(self, value: bool):
        self.setProperty("open", value)
        refresh_style(self)

    def _open(self):
        self._set_open(True)
        self.menu_.setMinimumWidth(max(self.width(), 200))
        self.menu_.exec(self.mapToGlobal(QPoint(0, self.height())))

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.menu_ is not None:
            p = QPainter(self)
            x = self.width() - 16 - 16
            icons.paint(p, "chevron_down", QRectF(x, (self.height() - 16) / 2, 16, 16),
                        "icon-primary" if self.underMouse() or self.property("open") else "icon-secondary")
            p.end()


class AppHeader(QFrame):
    about_requested = Signal()

    def __init__(self, file_menu: QMenu, theme_menu: QMenu, parent=None):
        super().__init__(parent)
        self.setObjectName("AppHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(HEADER_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(15, 0, 24, 0)
        lay.setSpacing(0)
        name = QLabel("MDL <span style='font-weight:600'>HEA Calculator</span>")
        name.setObjectName("HeaderName")
        name.setTextFormat(Qt.TextFormat.RichText)
        name.setContentsMargins(8, 0, 0, 0)
        name.setFixedWidth(173)  # Figma "Site name" block: pl 8 + text + pr 32
        lay.addWidget(name)
        div = QWidget()
        div.setFixedSize(17, HEADER_HEIGHT)
        line = QFrame(div)
        line.setObjectName("HeaderDivider")
        line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        line.setGeometry(0, 12, 1, 24)
        lay.addWidget(div)
        self.file_item = HeaderMenuItem("File", file_menu)
        self.theme_item = HeaderMenuItem("Theme", theme_menu)
        self.about_item = HeaderMenuItem("About")
        self.about_item.clicked.connect(self.about_requested.emit)
        for w in (self.file_item, self.theme_item, self.about_item):
            lay.addWidget(w)
        lay.addStretch(1)
        _ = t
