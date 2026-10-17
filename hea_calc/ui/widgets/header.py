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

from PySide6.QtCore import QRectF, Qt, Signal
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
        # CORRECT_FILE_BUTTON: the open trigger sits on the menu surface (layer-02) with the chevron up, and
        # the menu opens flush beneath it
        self._set_open(True)
        self.menu_.trigger_width = 0
        self.menu_.open_below(self)

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
            crisp.fill_rect(p, r, t("layer-02"))        # merged with the open menu (CORRECT_THEME_BUTTON)
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


class ProgressLine(QWidget):
    """The shell's 4 px state line on the bottom edge of the header (Main window.svg: y = header bottom, full
    window width): ``border-interactive`` progress (indeterminate while the total is unknown), then
    ``support-success`` / ``support-warning`` / ``support-error`` for a succeeded / cancelled / failed run.
    It is an overlay on the 20 px page gap, so appearing never moves the shell or the panels."""

    HEIGHT = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(self.HEIGHT)
        self.lo, self.hi, self.val = 0, 100, 0
        self.kind: str | None = None             # None idle, "progress", "success", "warning", "error"
        from PySide6.QtCore import QTimer
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self.hide()

    # QProgressBar-compatible subset (exports, reports and tests use it)
    def setRange(self, lo: int, hi: int) -> None:
        self.lo, self.hi = lo, hi
        if hi <= lo and self.kind == "progress":
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

    def set_kind(self, kind: str | None) -> None:
        self.kind = kind
        if kind is None:
            self._timer.stop()
            self.hide()
            return
        if kind == "progress" and self.hi <= self.lo:
            self._timer.start()
        elif kind != "progress":
            self._timer.stop()
        self.show()
        self.raise_()
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.02) % 1.0
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        if self.kind in ("success", "warning", "error"):
            crisp.fill_rect(p, r, t(f"support-{self.kind}"))
        else:
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
    """The header's status region (Main window.svg; CORRECT_CALCULATING_STATE / CORRECT_CALCULATION_COMPLETED):

    * running: "Calculating…25%" (body-compact-01) + the label-01 helper "(772,860/3,091,441) 2 minutes
      remaining"; the :class:`ProgressLine` under the header shows the fraction;
    * finished: "Calculation succeeded" / "Calculation cancelled" / "Calculation failed", a 16 px status icon and
      the helper sentence; the line turns green / yellow / red.  The result stays until the next job;
    * exports and reports also show their progress here, with Cancel (they have no other cancel control).

    ``show()`` / ``hide()`` show or hide the *content*; the region keeps its place in the header.
    """

    RESULT_ICONS = {"success": "notify_success", "warning": "notify_warning", "error": "notify_error"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeaderProgress")
        self.setFixedHeight(HEADER_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(320)
        self.setMaximumWidth(587 + 16 + 216 + 96)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.label = QLabel("")
        self.label.setObjectName("HeaderProgressLabel")
        self.label.setFont(font(BODY_COMPACT_01))
        lay.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.detail = QLabel("")
        self.detail.setObjectName("HeaderProgressDetail")
        self.detail.setFont(font(LABEL_01))
        lay.addWidget(self.detail, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(8)
        self.cancel = button("Cancel", "ghost", "sm")
        self.cancel.setToolTip("")
        lay.addWidget(self.cancel, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        self.bar = ProgressLine(self)                # re-parented onto the window by the main window
        self.active = False
        self.result: str | None = None
        self._content = (self.label, self.icon, self.detail, self.cancel)
        for w in self._content:
            w.setVisible(False)
        self.setAccessibleName("Progress")

    # the window, exports and reports call show() / hide(): content only, never the region
    def show(self) -> None:                         # noqa: D401 - Qt-compatible name
        self.active = True
        self.result = None
        self.icon.setVisible(False)
        for w in (self.label, self.detail):
            w.setVisible(True)
        self.cancel.setVisible(bool(self.property("cancellable")))
        self.bar.set_kind("progress")
        super().show()

    def hide(self) -> None:
        self.active = False
        for w in self._content:
            w.setVisible(False)
        if self.result is None:
            self.bar.set_kind(None)

    def isVisible(self) -> bool:                    # "is a job shown" for callers and tests
        return self.active

    def set_cancellable(self, on: bool) -> None:
        self.setProperty("cancellable", on)
        if self.active:
            self.cancel.setVisible(on)

    def set_progress(self, verb: str, done: int, total: int, eta: float | None) -> None:
        """"<verb>…NN%" + "(done/total) N minutes remaining"; the edge line shows the fraction."""
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

    def set_result(self, kind: str, title: str, detail: str) -> None:
        """A finished run: ``kind`` success / warning (cancelled) / error (failed)."""
        from .. import icons
        self.active = False
        self.result = kind
        self.label.setText(title)
        self.detail.setText(detail)
        self.icon.setPixmap(icons.pixmap(self.RESULT_ICONS.get(kind, "notify_info"), size=16))
        for w in (self.label, self.icon, self.detail):
            w.setVisible(True)
        self.cancel.setVisible(False)
        self.bar.set_kind(kind)

    def clear_result(self) -> None:
        if self.result is not None and not self.active:
            self.result = None
            for w in self._content:
                w.setVisible(False)
            self.bar.set_kind(None)


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
        self.theme_requested.emit()
        m.open_below(self.theme_btn, align_right=True)

    def _theme_closed(self):
        self.theme_btn.active = False
        self.theme_btn.update()

    THEME_ICONS = {"light": "brightness_contrast", "dark": "asleep", "system": "contrast"}

    def set_theme_preference(self, pref: str) -> None:
        """CORRECT_THEME_BUTTON: the header icon shows the selected preference - Light (brightness-contrast),
        Dark (asleep) or System default (contrast) - not the effective theme."""
        self.theme_btn.set_icon(self.THEME_ICONS.get(pref, "contrast"))
