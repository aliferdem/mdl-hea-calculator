"""Application header - the current Figma "UI shell - Header" (node 170:11393, 1920 × 48).

Left: site name (173 px) | divider | the *File* and *About* menu items.  Centre: the calculation progress
region (Figma: Carbon ProgressBar, inline, small - "Calculating…25%" + 16 px gap + 4 px bar, 587 px - then a
16 px spacer and the label-01 detail "(24,990/99,961) 2 minutes remaining").  Right: two 48 × 48 header actions,
icon only - Help (Documentation Home) and Theme (the theme menu) - each with a Tooltip.

The progress region is always laid out (only its content is hidden when idle), so starting or finishing a
calculation never changes the header's geometry.  Cancelling a calculation is the Composition setup footer's
*Cancel*; the header's own Cancel appears only for exports and reports, which have no other control.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QWidget

from .. import crisp, icons
from ..theme import BODY_COMPACT_01, FOCUS_WIDTH, HEADER_HEIGHT, LABEL_01, font, t
from .common import button, refresh_style


class HeaderMenuItem(QPushButton):
    """UI shell header menu item (48 px, text-secondary, optional chevron)."""

    def __init__(self, text: str, menu: QMenu | None = None, parent=None):
        super().__init__(text, parent)
        self.setObjectName("HeaderMenuItem")
        self.setFixedHeight(HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_ = menu
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
        self.menu_.trigger_width = max(self.width(), 200)
        self.menu_.exec(self.mapToGlobal(QPoint(0, self.height())))

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.menu_ is not None:
            p = QPainter(self)
            x = self.width() - 16 - 16
            r = QRectF(x, (self.height() - 16) / 2, 16, 16)
            if self.property("open"):
                p.translate(r.center())
                p.rotate(180)
                p.translate(-r.center())
            icons.paint(p, "chevron_down", r,
                        "icon-primary" if self.underMouse() or self.property("open") else "icon-secondary")
            p.end()


class HeaderAction(QPushButton):
    """Carbon UI shell header action: 48 × 48, 20 px icon, icon only (Tooltip says what it does), hover
    ``layer-hover``, active (menu open) ``layer-selected``, 2 px inside focus frame."""

    def __init__(self, icon_name: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setObjectName("HeaderAction")
        self.setFixedSize(HEADER_HEIGHT, HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(tooltip)
        self.setProperty("tip_align", "bottom")
        self.setAccessibleName(tooltip)
        self.active = False

    def set_icon(self, name: str) -> None:
        self.icon_name = name
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        if self.active:
            crisp.fill_rect(p, r, t("layer-selected-01"))
        elif self.isDown():
            crisp.fill_rect(p, r, t("layer-active-01"))
        elif self.underMouse():
            crisp.fill_rect(p, r, t("layer-hover-01"))
        icons.paint(p, self.icon_name, QRectF((r.width() - 20) / 2, (r.height() - 20) / 2, 20, 20),
                    "icon-primary" if (self.underMouse() or self.active) else "icon-secondary")
        if self.hasFocus():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class _Bar(QWidget):
    """Carbon progress bar track (4 px, ``border-subtle`` track, ``border-interactive`` fill; indeterminate when
    the maximum is 0)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self.lo, self.hi, self.val = 0, 100, 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        from PySide6.QtCore import QTimer
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    # QProgressBar-compatible subset used by the window, exports and reports
    def setRange(self, lo: int, hi: int) -> None:
        self.lo, self.hi = lo, hi
        if hi <= lo and self.isVisible():
            self._timer.start()
        elif hi > lo:
            self._timer.stop()
        self.update()

    def setValue(self, v: int) -> None:
        self.val = v
        self.update()

    def maximum(self) -> int:
        return self.hi

    def value(self) -> int:
        return self.val

    def fraction(self) -> float | None:
        if self.hi <= self.lo:
            return None
        return max(0.0, min(1.0, (self.val - self.lo) / (self.hi - self.lo)))

    def _tick(self):
        self._phase = (self._phase + 0.02) % 1.0
        self.update()

    def showEvent(self, e):
        if self.hi <= self.lo:
            self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        crisp.fill_rect(p, r, t("border-subtle-01"))
        f = self.fraction()
        if f is None:
            w = r.width() * 0.25
            x = (r.width() + w) * self._phase - w
            crisp.fill_rect(p, QRectF(max(0.0, x), 0, min(w, r.width() - max(0.0, x)), r.height()),
                            t("border-interactive"))
        elif f > 0:
            crisp.fill_rect(p, QRectF(0, 0, r.width() * f, r.height()), t("border-interactive"))
        p.end()


class HeaderProgress(QWidget):
    """The header's progress region: label ("Calculating…25%"), bar, detail ("(24,990/99,961) 2 minutes
    remaining") and, for exports / reports only, a Cancel button.  ``show()`` / ``hide()`` show or hide the
    *content*; the region keeps its place in the header."""

    LABEL_WIDTH = 150

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeaderProgress")
        self.setFixedHeight(HEADER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(320)
        self.setMaximumWidth(587 + 16 + 216 + 96)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        self.label = QLabel("")
        self.label.setObjectName("HeaderProgressLabel")
        self.label.setFont(font(BODY_COMPACT_01))
        lay.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.bar = _Bar()
        lay.addWidget(self.bar, 1, Qt.AlignmentFlag.AlignVCenter)
        self.detail = QLabel("")
        self.detail.setObjectName("HeaderProgressDetail")
        self.detail.setFont(font(LABEL_01))
        lay.addWidget(self.detail, 0, Qt.AlignmentFlag.AlignVCenter)
        self.cancel = button("Cancel", "ghost", "sm")
        self.cancel.setToolTip("")
        lay.addWidget(self.cancel, 0, Qt.AlignmentFlag.AlignVCenter)
        self.active = False
        self._content = (self.label, self.bar, self.detail, self.cancel)
        for w in self._content:
            w.setVisible(False)
        self.setAccessibleName("Progress")

    # the window, exports and reports call show() / hide(): content only, never the region
    def show(self) -> None:                         # noqa: D401 - Qt-compatible name
        self.active = True
        for w in (self.label, self.bar, self.detail):
            w.setVisible(True)
        self.cancel.setVisible(bool(self.property("cancellable")))
        super().show()

    def hide(self) -> None:
        self.active = False
        for w in self._content:
            w.setVisible(False)

    def isVisible(self) -> bool:                    # "is a job shown" for callers and tests
        return self.active

    def set_cancellable(self, on: bool) -> None:
        self.setProperty("cancellable", on)
        if self.active:
            self.cancel.setVisible(on)

    def set_progress(self, verb: str, done: int, total: int, eta: float | None) -> None:
        """Carbon inline progress: "<verb>…NN%" + bar + "(done/total) N minutes remaining"."""
        if total > 0:
            pct = min(100, int(100 * min(done, total) / total + 0.5))     # nearest percent (Figma: 25 %)
            if pct == 100 and done < total:
                pct = 99                                                # never "100 %" before the end
            self.label.setText(f"{verb}…{pct}%")
            if self.bar.maximum() != total:
                self.bar.setRange(0, total)
            self.bar.setValue(min(done, total))
            rem = f" {format_eta(eta)}" if eta and done else ""
            self.detail.setText(f"({done:,}/{total:,}){rem}")
        else:
            self.label.setText(f"{verb}…")
            self.bar.setRange(0, 0)
            self.detail.setText("")


def format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{max(1, round(seconds))} second{'s' if round(seconds) != 1 else ''} remaining"
    if seconds < 3600:
        m = round(seconds / 60)
        return f"{m} minute{'s' if m != 1 else ''} remaining"
    return f"{seconds / 3600:.1f} hours remaining"


class AppHeader(QFrame):
    about_requested = Signal()
    help_requested = Signal()
    theme_requested = Signal()

    def __init__(self, file_menu: QMenu, theme_menu: QMenu, parent=None):
        super().__init__(parent)
        self.setObjectName("AppHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(HEADER_HEIGHT)
        self.theme_menu = theme_menu
        lay = QHBoxLayout(self)
        lay.setContentsMargins(15, 0, 0, 0)
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
        self.about_item = HeaderMenuItem("About")
        self.about_item.clicked.connect(self.about_requested.emit)
        for w in (self.file_item, self.about_item):
            lay.addWidget(w)
        # Figma: 194 px before the progress region, 454 px after it (at 1920 px) - kept as stretch ratios
        lay.addStretch(194)
        self.progress = HeaderProgress()
        lay.addWidget(self.progress, 819)
        lay.addStretch(454)
        self.help_btn = HeaderAction("help", "Help (F1)")
        self.help_btn.clicked.connect(self.help_requested.emit)
        self.theme_btn = HeaderAction("light", "Theme")
        self.theme_btn.clicked.connect(self._open_theme)
        theme_menu.aboutToHide.connect(self._theme_closed)
        lay.addWidget(self.help_btn)
        lay.addWidget(self.theme_btn)

    def _open_theme(self):
        self.theme_btn.active = True
        self.theme_btn.update()
        m = self.theme_menu
        m.trigger_width = 0
        m._fit_width()
        self.theme_requested.emit()
        m.exec(self.theme_btn.mapToGlobal(QPoint(self.theme_btn.width() - m.width(), self.theme_btn.height())))

    def _theme_closed(self):
        self.theme_btn.active = False
        self.theme_btn.update()

    def set_effective_theme(self, name: str) -> None:
        """The theme action's icon (Figma DARK_MODE_FULLSCREEN shows the sun on the dark theme): the sun on dark,
        the moon on light.  The menu itself lists System default / Light / Dark."""
        self.theme_btn.set_icon("light" if name == "dark" else "asleep")
