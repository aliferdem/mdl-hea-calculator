"""Application title bar - Figma "Title bar" (572:52827: Default / Calculating / Completed / Cancelled / Failed,
1920 × 32 + the 4 px state line).

The window has no native caption: this 32 px bar *is* the title bar (``ui/win_chrome.py`` gives it the native
Windows behaviour - dragging, double-click maximise, Aero Snap, Snap Layouts on the maximise button, the system
menu, edge and corner resizing).  Left to right:

* a 24 px spacer, the site name ("MDL" body-compact-01 + "HEA Calculator" heading-compact-01, 8 px left / 32 px right
  padding: 173 px), a 17 px divider (1 px × 16 px ``border-subtle-00`` line);
* the menu items File, Edit, View, Help (UI shell header menu items: 16 px inline padding, body-compact-01
  ``text-secondary``; hover ``titlebar-hover`` (Figma background-hover) + ``text-primary``; open: merged with the menu on ``layer-02``);
* the status column (:class:`HeaderProgress`), which starts at the left edge of the Composition setup title text
  (:meth:`TitleBar.align_status_to`): "Calculating…25%" + "(772,860/3,091,441) 2 minutes remaining", or a finished
  run's title, 16 px status icon and sentence (body-compact-01 ``text-primary`` + ``shell-helper``);
* the top-panels header action (32 × 32, 16 px Carbon ``open-panel--filled--top`` / ``open-panel--top``);
* the caption buttons Minimise, Maximise / Restore and Close (46 × 32, the Windows 11 caption glyphs at 10 px in
  ``text-primary``; hover / pressed / inactive values of the Windows 11 title bar kit the Figma instance uses -
  see :data:`CAPTION`).

Inactive window (another application, or one of the calculator's own windows or dialogs, is active): the bar
takes the ``titlebar-inactive`` surface (Windows 11's solid inactive caption: Gray 10 / #202020) and its foreground
steps down, never to the disabled colours - site name and status title -> ``titlebar-inactive-title`` (Gray 60 /
Gray 40), menu labels, the panels icon and the status detail -> ``titlebar-inactive-text`` (Gray 50); the caption
glyphs take the Windows 11 kit's ``Inactive=True`` value (36 % of the foreground, :data:`CAPTION`); the state line
keeps its colour's hue and meaning at :data:`INACTIVE_LINE_MIX` of its strength (a warning stays visible).  Hover /
pressed fills are unchanged (an inactive window still answers the pointer).  One state
(:meth:`TitleBar.set_window_active`), evaluated
from the top-level window's activation after the event loop settles, so opening a title-bar menu (a popup, which
does not take activation) never flickers.

Under the bar, the 4 px state line (:class:`ProgressLine`): ``border-interactive`` progress on a ``titlebar-track``
(indeterminate while the total is unknown), then ``support-success`` / ``support-warning`` / ``support-error`` for a
completed / cancelled / failed run.  Its 4 px are always reserved (the bar is 36 px tall), so a run starting or
ending never moves the panels; while idle the bar's 1 px bottom rule shows instead.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSizePolicy, QSpacerItem, QWidget)

from .. import crisp, icons
from ..theme import BODY_COMPACT_01, FOCUS_WIDTH, HAIRLINE, HEADING_COMPACT_01, THEME, font, t
from .common import button, refresh_style

TITLEBAR_HEIGHT = 32
LINE_HEIGHT = 4
CAPTION_W = 46
ACTION_W = 32

# Windows 11 title bar kit ("Parts / Title Bar Caption Control Button", Mode × States), as used by the Figma
# instance: base fill (colour, alpha) and glyph alpha; the glyph colour itself is the instance's text-primary.
CAPTION = {
    "light": {"hover": ("#000000", 0.037, 0.90), "pressed": ("#000000", 0.024, 0.61), "rest": (None, 0, 1.0)},
    "dark": {"hover": ("#ffffff", 0.060, 1.00), "pressed": ("#ffffff", 0.042, 0.79), "rest": (None, 0, 1.0)},
    "close": {"hover": ("#c42b1c", 1.0, 1.0), "pressed": ("#c42b1c", 0.90, 0.70)},
    "inactive_alpha": 0.36,
}
INACTIVE_LINE_MIX = 0.7        # the state line of an inactive window: 70 % of its colour over the line background
GLYPHS = {"min": "", "max": "", "restore": "", "close": ""}
_GLYPH_FAMILY: str | None = None


def bar_active(widget: QWidget) -> bool:
    """The activation state of the title bar ``widget`` belongs to (True outside a title bar)."""
    w = widget
    while w is not None and not isinstance(w, TitleBar):
        w = w.parentWidget()
    return True if w is None else w.window_active


def glyph_family() -> str:
    """Segoe Fluent Icons (Windows 11), Segoe MDL2 Assets (Windows 10), or "" (the glyphs are drawn)."""
    global _GLYPH_FAMILY
    if _GLYPH_FAMILY is None:
        fams = set(QFontDatabase.families())
        _GLYPH_FAMILY = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in fams), "")
    return _GLYPH_FAMILY


class HeaderMenuItem(QPushButton):
    """UI shell header menu item: 32 px, 16 px inline padding, ``text-secondary`` (no chevron - Figma)."""

    def __init__(self, text: str, menu: QMenu | None = None, parent=None):
        super().__init__(text, parent)
        self.setObjectName("HeaderMenuItem")
        self.setFixedHeight(TITLEBAR_HEIGHT)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.menu_ = menu
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        fm = QFontMetrics(font(BODY_COMPACT_01))
        self.setFixedWidth(fm.horizontalAdvance(text) + 32)
        if menu is not None:
            self.clicked.connect(self._open)
            menu.aboutToHide.connect(lambda: self._set_open(False))

    def _set_open(self, value: bool):
        self.setProperty("open", value)
        refresh_style(self)

    def _open(self, keyboard: bool = False):
        # the open trigger sits on the menu surface (layer-02), the menu opens flush beneath it
        bar = self.parent()
        while bar is not None and not isinstance(bar, TitleBar):
            bar = bar.parent()
        self._set_open(True)
        self.menu_.trigger_width = 0
        self.menu_.menubar = bar
        first = next((a for a in self.menu_.actions() if a.isVisible() and a.isEnabled() and not a.isSeparator()
                      and not a.property("section")), None) if keyboard else None
        if bar is not None:
            bar.open_item = self
        try:
            self.menu_.open_below(self, merge=True, active=first)
        finally:
            if bar is not None:
                bar.open_item = None
                bar.menu_closed(self)

    def keyPressEvent(self, e):
        bar = self.parent()
        while bar is not None and not isinstance(bar, TitleBar):
            bar = bar.parent()
        if bar is not None and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            bar.move_menu_focus(self, -1 if e.key() == Qt.Key.Key_Left else 1)
            return
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.menu_:
            self._open(keyboard=True)           # from the keyboard: the first item is active (Windows)
            return
        if e.key() == Qt.Key.Key_Escape and bar is not None:
            bar.leave_menu_mode()
            return
        super().keyPressEvent(e)


class HeaderAction(QAbstractButton):
    """UI shell header action of the title bar: 32 × 32, 16 px icon, icon only (a Tooltip says what it does);
    hover ``titlebar-hover`` (Figma background-hover), pressed ``background-active``, 2 px inside focus frame."""

    def __init__(self, icon_name: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setObjectName("HeaderAction")
        self.setFixedSize(ACTION_W, TITLEBAR_HEIGHT)
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
            crisp.fill_rect(p, r, t("layer-02"))
        elif self.isDown():
            crisp.fill_rect(p, r, t("background-active"))
        elif self.underMouse():
            crisp.fill_rect(p, r, t("titlebar-hover"))
        token = "icon-primary" if bar_active(self) or self.active else "titlebar-inactive-text"
        icons.paint(p, self.icon_name, QRectF((r.width() - 16) / 2, (r.height() - 16) / 2, 16, 16), token)
        if self.hasFocus():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class CaptionButton(QAbstractButton):
    """Minimise / Maximise-Restore / Close (46 × 32).  ``native_hover`` / ``native_down`` are set by the native
    chrome while Windows owns the pointer over the maximise button (Snap Layouts: the button is HTMAXBUTTON)."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind                       # "min" | "max" | "close"
        self.maximized = False
        self.native_hover = False
        self.native_down = False
        self.setFixedSize(CAPTION_W, TITLEBAR_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)    # Windows' own caption buttons are not in the tab order
        self.setObjectName(f"Caption_{kind}")
        names = {"min": "Minimize", "max": "Maximize", "close": "Close"}
        # accessible name only, no tooltip: Windows 11's own caption buttons show none (Snap Layouts opens over
        # Maximize), and a tooltip under the caption covered the content (2026-10-27)
        self.setAccessibleName(names[kind])

    def set_maximized(self, on: bool) -> None:
        self.maximized = on
        if self.kind == "max":
            self.setAccessibleName("Restore down" if on else "Maximize")
        self.update()

    def glyph(self) -> str:
        if self.kind == "max":
            return "restore" if self.maximized else "max"
        return self.kind

    def state(self) -> str:
        if self.isDown() or self.native_down:
            return "pressed"
        if self.underMouse() or self.native_hover:
            return "hover"
        return "rest"

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        st = self.state()
        theme = THEME.name
        active = bar_active(self)
        fg = QColor(t("text-primary"))
        if self.kind == "close" and st != "rest":
            col, a, ga = CAPTION["close"][st]
            fg = QColor("#ffffff")
        else:
            col, a, ga = CAPTION[theme][st]
        if col is not None and a > 0:
            bg = QColor(col)
            bg.setAlphaF(a)
            p.fillRect(self.rect(), bg)
        if st == "rest" and not active:
            ga = CAPTION["inactive_alpha"]
        fg.setAlphaF(ga)
        paint_glyph(p, self.glyph(), QRectF((self.width() - 16) / 2, (self.height() - 16) / 2, 16, 16), fg)
        p.end()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


def paint_glyph(p: QPainter, name: str, box: QRectF, color: QColor) -> None:
    """A Windows caption glyph (10 px) centred in a 16 px box: the system icon font, else drawn lines."""
    fam = glyph_family()
    if fam:
        f = QFont(fam)
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(color)
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), GLYPHS[name])
        return
    pen = QPen(color, 1)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    c = box.center()
    if name == "min":
        p.drawLine(QPoint(int(c.x() - 5), int(c.y())), QPoint(int(c.x() + 5), int(c.y())))
    elif name == "max":
        p.drawRect(QRectF(c.x() - 4.5, c.y() - 4.5, 9, 9))
    elif name == "restore":
        p.drawRect(QRectF(c.x() - 4.5, c.y() - 2.5, 7, 7))
        p.drawPolyline([QPoint(int(c.x() - 2.5), int(c.y() - 2.5)), QPoint(int(c.x() - 2.5), int(c.y() - 4.5)),
                        QPoint(int(c.x() + 4.5), int(c.y() - 4.5)), QPoint(int(c.x() + 4.5), int(c.y() + 2.5)),
                        QPoint(int(c.x() + 2.5), int(c.y() + 2.5))])
    else:
        p.drawLine(QPoint(int(c.x() - 5), int(c.y() - 5)), QPoint(int(c.x() + 5), int(c.y() + 5)))
        p.drawLine(QPoint(int(c.x() + 5), int(c.y() - 5)), QPoint(int(c.x() - 5), int(c.y() + 5)))


class ProgressLine(QWidget):
    """The 4 px state line under the title bar (see module docstring).  It reports real progress only: a determinate
    fraction while the total is known, an indeterminate sweep while it is not."""

    HEIGHT = LINE_HEIGHT

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(self.HEIGHT)
        self.lo, self.hi, self.val = 0, 100, 0
        self.kind: str | None = None             # None idle, "progress", "success", "warning", "error"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

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

    def isVisible(self) -> bool:                 # "is a state shown" (the 4 px are always laid out)
        return self.kind is not None and super().isVisible()

    def set_kind(self, kind: str | None) -> None:
        self.kind = kind
        if kind is None:
            self._timer.stop()
        elif kind == "progress" and self.hi <= self.lo:
            self._timer.start()
        elif kind != "progress":
            self._timer.stop()
        self.update()
        if self.parent() is not None:
            self.parent().update()

    def _tick(self):
        self._phase = (self._phase + 0.02) % 1.0
        self.update()

    def color(self, token: str) -> QColor:
        """A state-line colour: the token itself in an active window; in an inactive one the same hue at
        INACTIVE_LINE_MIX over the line's background (subdued, never grey, never hidden)."""
        c = QColor(t(token))
        if bar_active(self):
            return c
        bg = QColor(t("background"))
        m = INACTIVE_LINE_MIX
        return QColor(round(c.red() * m + bg.red() * (1 - m)), round(c.green() * m + bg.green() * (1 - m)),
                      round(c.blue() * m + bg.blue() * (1 - m)))

    def paintEvent(self, _e):
        if self.kind is None:
            return
        p = QPainter(self)
        r = self.rect()
        if self.kind in ("success", "warning", "error"):
            crisp.fill_rect(p, r, self.color(f"support-{self.kind}"))
        else:
            crisp.fill_rect(p, r, self.color("titlebar-track"))
            f = self.fraction()
            if f is None:
                w = r.width() * 0.25
                x = (r.width() + w) * self._phase - w
                crisp.fill_rect(p, QRectF(max(0.0, x), 0, min(w, r.width() - max(0.0, x)), r.height()),
                                self.color("border-interactive"))
            elif f > 0:
                crisp.fill_rect(p, QRectF(0, 0, r.width() * f, r.height()), self.color("border-interactive"))
        p.end()


class HeaderProgress(QWidget):
    """The title bar's status column (Figma Title bar Calculating / Completed / Cancelled / Failed):

    * running: "Calculating…25%" (body-compact-01 ``text-primary``) + "(772,860/3,091,441) 2 minutes remaining"
      (body-compact-01 ``shell-helper``, 8 px after); the :class:`ProgressLine` shows the fraction;
    * finished: "Calculation completed" / "Calculation cancelled" / "Calculation failed", a 16 px status icon (8 px
      apart) and the sentence; the line turns green / yellow / red.  The result stays until the user's next mouse
      press anywhere in the application (or the next job), then the bar returns to idle;
    * exports and reports also show their progress here, with Cancel (they have no other cancel control);
    * messages (:meth:`show_message`): every confirmation, warning and error of the window ("Table copied to
      clipboard", "Export failed", ...) - title, 16 px status icon, sentence.  Nothing is shown above the results
      table.  Success / info go after their timeout or the next mouse press, warnings / errors on the next mouse
      press.  A message never changes the state line (that is the run's status) and never replaces a running job:
      it takes the column's text for its time, the progress line keeps moving, and the job's text returns after.
      A sentence that does not fit is elided and given in full in the tooltip and accessible description.

    ``show()`` / ``hide()`` show or hide the *content*; the column keeps its place in the bar.
    """

    RESULT_ICONS = {"success": "notify_success", "warning": "notify_warning", "error": "notify_error",
                    "info": "notify_info"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeaderProgress")
        self.setFixedHeight(TITLEBAR_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(120)
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
        self.detail.setFont(font(BODY_COMPACT_01))
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.detail, 1, Qt.AlignmentFlag.AlignVCenter)
        self.cancel = button("Cancel", "ghost", "sm")
        self.cancel.setToolTip("")
        lay.addWidget(self.cancel, 0, Qt.AlignmentFlag.AlignVCenter)
        self.bar = ProgressLine(self)                # re-parented under the bar by the title bar
        self.active = False
        self.result: str | None = None
        self.message: tuple[str, str, str] | None = None      # (kind, title, text) while a message is shown
        self._shown: tuple[str, str] = ("", "")                 # the job's / result's own title and detail
        self._full_detail = ""
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(lambda: self.dismiss_message(by_press=False))
        self.detail.installEventFilter(self)          # re-elide when the layout gives the sentence its width
        self._content = (self.label, self.icon, self.detail, self.cancel)
        for w in self._content:
            w.setVisible(False)
        self.setAccessibleName("Progress")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    # the window, exports and reports call show() / hide(): content only, never the column
    def show(self) -> None:                         # noqa: D401 - Qt-compatible name
        _NextPress.disarm(self)                     # a new job replaces any finished state at once
        self._end_message()
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
        if self.message is not None:                # a message outlives the job it interrupted
            self.cancel.setVisible(False)
            if self.result is None:
                self.bar.set_kind(None)
            return
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
        """"<verb>…NN%" + "(done/total) N minutes remaining"; the line shows the fraction."""
        if total > 0:
            pct = min(100, int(100 * min(done, total) / total + 0.5))     # nearest percent (Figma: 25 %)
            if pct == 100 and done < total:
                pct = 99                                                # never "100 %" before the end
            if self.bar.maximum() != total:
                self.bar.setRange(0, total)
            self.bar.setValue(min(done, total))
            rem = f" {format_eta(eta)}" if eta and done else ""
            self._texts(f"{verb}…{pct}%", f"({done:,}/{total:,}){rem}")
        else:
            self.bar.setRange(0, 0)
            self._texts(f"{verb}…", "")

    def _texts(self, title: str, detail: str) -> None:
        """The job's / result's own title and detail (held back while a message is shown)."""
        self._shown = (title, detail)
        if self.message is None:
            self.label.setText(title)
            self._set_detail(detail)

    def _set_detail(self, text: str) -> None:
        self._full_detail = text
        self._elide()

    def _elide(self) -> None:
        text = self._full_detail
        room = self.detail.width() if self.detail.isVisible() and self.detail.width() > 20 else 10 ** 6
        fm = QFontMetrics(self.detail.font())
        shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, room) if fm.horizontalAdvance(text) > room else text
        self.detail.setText(shown)
        self.detail.setToolTip(text if shown != text else "")
        self.detail.setAccessibleDescription(text)

    def eventFilter(self, obj, ev):
        if obj is self.detail and ev.type() == QEvent.Type.Resize:
            self._elide()
        return False

    # -------------------------------------------------------------- messages
    def show_message(self, kind: str, title: str, text: str = "", timeout_ms: int | None = None) -> None:
        """A confirmation / warning / error in the title bar (see the class docstring).  ``timeout_ms``: the
        time a success / info message stays (warnings and errors stay until the next mouse press)."""
        self.message = (kind, title, text)
        self.label.setText(title)
        self.icon.setPixmap(icons.pixmap(self.RESULT_ICONS.get(kind, "notify_info"), size=16))
        for w in (self.label, self.icon, self.detail):
            w.setVisible(True)
        if not self.active:
            self.cancel.setVisible(False)
        self._set_detail(text)
        self.setAccessibleName(f"{title}. {text}" if text else title)
        _NextPress.arm(self, self.dismiss_message)
        if kind in ("success", "info") and timeout_ms:
            self._msg_timer.start(timeout_ms)
        else:
            self._msg_timer.stop()
        super().show()

    def message_text(self) -> str:
        """The shown message's title and sentence ("" when none) - for callers and tests."""
        return "" if self.message is None else f"{self.message[1]} {self.message[2]}".strip()

    def _end_message(self) -> None:
        self._msg_timer.stop()
        self.message = None
        self.setAccessibleName("Progress")

    def dismiss_message(self, by_press: bool = True) -> None:
        """The message goes; the running job's text returns (or the finished run's result, unless the press
        that dismissed the message also dismissed the result)."""
        if self.message is None:
            return
        self._end_message()
        _NextPress.disarm(self)
        if self.active:
            self.label.setText(self._shown[0])
            self._set_detail(self._shown[1])
            self.icon.setVisible(False)
            self.cancel.setVisible(bool(self.property("cancellable")))
        elif self.result is not None and not by_press:
            self.label.setText(self._shown[0])
            self._set_detail(self._shown[1])
            self.icon.setPixmap(icons.pixmap(self.RESULT_ICONS.get(self.result, "notify_info"), size=16))
            _NextPress.arm(self, self.clear_result)
        else:
            self.result = None
            for w in self._content:
                w.setVisible(False)
            self.bar.set_kind(None)

    def set_result(self, kind: str, title: str, detail: str) -> None:
        """A finished run: ``kind`` success / warning (cancelled) / error (failed).  It stays until the next mouse
        press in the application (:class:`_NextPress`), never dismissed by the run's own end."""
        self.active = False
        self.result = kind
        self._end_message()                         # the run's own outcome replaces a message
        self._texts(title, detail)
        self.icon.setPixmap(icons.pixmap(self.RESULT_ICONS.get(kind, "notify_info"), size=16))
        for w in (self.label, self.icon, self.detail):
            w.setVisible(True)
        self.cancel.setVisible(False)
        self.bar.set_kind(kind)
        _NextPress.arm(self, self.clear_result)

    def set_reason(self, reason: str) -> None:
        """The specific cause of a failed run (the Figma sentence stays): the detail's tooltip and accessible
        description; Composition setup's footer states it too."""
        self.detail.setToolTip(reason)
        self.detail.setAccessibleDescription(f"{self._full_detail} {reason}".strip())

    def clear_result(self) -> None:
        _NextPress.disarm(self)
        if self.message is not None:
            self.dismiss_message()
            return
        if self.result is not None and not self.active:
            self.result = None
            for w in self._content:
                w.setVisible(False)
            self.bar.set_kind(None)


class _NextPress(QObject):
    """Dismisses a terminal status on the user's next mouse press anywhere in the application.

    The application event filter exists only while a terminal status is shown: it is installed by
    :meth:`HeaderProgress.set_result`, looks at mouse presses only, and removes itself on the first one (and when
    the status goes for any other reason - a new job).  No filter runs during normal work (a permanent
    application-wide Python filter stalled the UI before).  The press itself is delivered normally."""

    def __init__(self, owner, callback):
        super().__init__(owner)
        self.callback = callback
        self.fired = False

    @classmethod
    def arm(cls, owner, callback) -> None:
        cls.disarm(owner)
        f = cls(owner, callback)                  # a child of the owner: it never outlives it
        owner._next_press = f
        QApplication.instance().installEventFilter(f)

    @classmethod
    def disarm(cls, owner) -> None:
        f = getattr(owner, "_next_press", None)
        owner._next_press = None
        if f is not None:
            app = QApplication.instance()
            try:
                if app is not None:
                    app.removeEventFilter(f)
                f.deleteLater()
            except RuntimeError:                  # already gone with its owner
                pass

    @staticmethod
    def armed(owner) -> bool:
        return getattr(owner, "_next_press", None) is not None

    def eventFilter(self, obj, ev):
        if not self.fired and ev.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.NonClientAreaMouseButtonPress):
            self.fired = True
            QTimer.singleShot(0, self, self.callback)  # after the press is delivered; cancelled if the owner goes
        return False


def format_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{max(1, round(seconds))} second{'s' if round(seconds) != 1 else ''} remaining"
    if seconds < 3600:
        m = round(seconds / 60)
        return f"{m} minute{'s' if m != 1 else ''} remaining"
    return f"{seconds / 3600:.1f} hours remaining"


class _SiteName(QWidget):
    """"MDL" + "HEA Calculator" (Figma Site name: 8 px left padding, 3 px gap, 32 px right padding)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(173, TITLEBAR_HEIGHT)
        self.setAccessibleName("MDL HEA Calculator")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setPen(QColor(t("text-primary" if bar_active(self) else "titlebar-inactive-title")))
        p.setFont(font(BODY_COMPACT_01))
        x = 8.0
        p.drawText(QRectF(x, 0, 60, TITLEBAR_HEIGHT), int(Qt.AlignmentFlag.AlignVCenter), "MDL")
        x += QFontMetrics(font(BODY_COMPACT_01)).horizontalAdvance("MDL") + 3
        p.setFont(font(HEADING_COMPACT_01))
        p.drawText(QRectF(x, 0, 140, TITLEBAR_HEIGHT), int(Qt.AlignmentFlag.AlignVCenter), "HEA Calculator")
        p.end()


class _Divider(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(17, TITLEBAR_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _e):
        p = QPainter(self)
        crisp.vline(p, 0, 8, 24, t("border-subtle-00"), HAIRLINE)
        p.end()


class TitleBar(QFrame):
    """See module docstring.  Signals: ``minimize_requested``, ``maximize_requested`` (toggle), ``close_requested``,
    ``top_panels_toggled``.  :meth:`hit_test` tells the native chrome what a point of the bar is."""

    about_requested = Signal()
    help_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()
    top_panels_toggled = Signal()
    exit_fullscreen_requested = Signal()

    def __init__(self, file_menu: QMenu, view_menu: QMenu, parent=None, edit_menu: QMenu | None = None,
                 help_menu: QMenu | None = None):
        super().__init__(parent)
        self.setObjectName("AppHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFixedHeight(TITLEBAR_HEIGHT + LINE_HEIGHT)
        self.view_menu = view_menu
        self.theme_menu = view_menu                  # former name (the Theme choices are in View)
        bar = QWidget(self)
        bar.setObjectName("TitleBarRow")
        self.row = bar
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 0, 0, 0)
        lay.setSpacing(0)
        self.name = _SiteName()
        lay.addWidget(self.name)
        lay.addWidget(_Divider())
        self.file_item = HeaderMenuItem("File", file_menu)
        self.edit_item = HeaderMenuItem("Edit", edit_menu) if edit_menu is not None else None
        self.view_item = HeaderMenuItem("View", view_menu)
        self.help_item = HeaderMenuItem("Help", help_menu)
        self.menu_items = [w for w in (self.file_item, self.edit_item, self.view_item, self.help_item) if w]
        for w in self.menu_items:
            lay.addWidget(w)
        # the status column starts where the Composition panel's title text starts (align_status_to); until the
        # window lays out, the Figma gap (165 px at 1920 px)
        self.status_gap = QSpacerItem(165, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        lay.addSpacerItem(self.status_gap)
        self.progress = HeaderProgress()
        lay.addWidget(self.progress, 1)
        lay.addSpacing(16)
        self.panels_btn = HeaderAction("open_panel_filled_top", "Hide top panels")
        self.panels_btn.clicked.connect(self.top_panels_toggled.emit)
        lay.addWidget(self.panels_btn)
        # full screen only (2026-10-28): the caption buttons are hidden there, so the way out sits beside the
        # top-panels action (F11 still toggles)
        self.exit_fs_btn = HeaderAction("minimize", "Exit full screen (F11)")
        self.exit_fs_btn.setAccessibleName("Exit full screen")
        self.exit_fs_btn.clicked.connect(self.exit_fullscreen_requested.emit)
        self.exit_fs_btn.hide()
        lay.addWidget(self.exit_fs_btn)
        self.min_btn = CaptionButton("min")
        self.max_btn = CaptionButton("max")
        self.close_btn = CaptionButton("close")
        self.min_btn.clicked.connect(self.minimize_requested.emit)
        self.max_btn.clicked.connect(self.maximize_requested.emit)
        self.close_btn.clicked.connect(self.close_requested.emit)
        for b in (self.min_btn, self.max_btn, self.close_btn):
            lay.addWidget(b)
        self.line = self.progress.bar
        self.line.setParent(self)
        self._menu_mode_focus: QWidget | None = None
        # the menu bar: the open title-bar menu, and the one to open when it closes (hover / Left / Right)
        self.open_item: HeaderMenuItem | None = None
        self._switch_to: tuple | None = None
        # the activation state of the top-level window (one place; see the module docstring)
        self.window_active = True
        self._watched = None
        self._activation_timer = QTimer(self)
        self._activation_timer.setSingleShot(True)
        self._activation_timer.setInterval(0)
        self._activation_timer.timeout.connect(self._evaluate_activation)
        app = QApplication.instance()
        if app is not None:
            app.focusWindowChanged.connect(self._schedule_activation)

    # -------------------------------------------------------------- geometry / paint
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.row.setGeometry(0, 0, self.width(), TITLEBAR_HEIGHT)
        self.line.setGeometry(0, TITLEBAR_HEIGHT, self.width(), LINE_HEIGHT)

    def paintEvent(self, _e):
        p = QPainter(self)
        crisp.fill_rect(p, QRectF(0, 0, self.width(), TITLEBAR_HEIGHT), self.surface())
        crisp.fill_rect(p, QRectF(0, TITLEBAR_HEIGHT, self.width(), LINE_HEIGHT), t("background"))
        if self.line.kind is None:
            crisp.hline(p, 0, self.width(), TITLEBAR_HEIGHT - 1, t("border-subtle-00"), HAIRLINE)
        p.end()

    def set_maximized(self, on: bool) -> None:
        self.max_btn.set_maximized(on)

    # -------------------------------------------------------------- active / inactive window
    def showEvent(self, e):
        super().showEvent(e)
        w = self.window()
        if w is not self._watched and w is not self:
            if self._watched is not None:
                self._watched.removeEventFilter(self)
            w.installEventFilter(self)
            self._watched = w
        self._schedule_activation()

    def eventFilter(self, obj, ev):
        if obj is self._watched and ev.type() in (QEvent.Type.ActivationChange, QEvent.Type.WindowActivate,
                                                  QEvent.Type.WindowDeactivate, QEvent.Type.WindowStateChange):
            self._schedule_activation()
        return False

    def _schedule_activation(self, *_):
        # coalesced: the activation changes that accompany one user action (a popup opening, a dialog closing)
        # are evaluated once, after they have all arrived - no transient inactive frame, no flicker
        try:
            self._activation_timer.start()
        except RuntimeError:                         # deleted with the window
            pass

    def _evaluate_activation(self) -> None:
        w = self.window()
        if w is None or w is self:
            return
        active = w.isActiveWindow()
        if not active:
            # a title-bar menu or another popup of this window does not deactivate it (Windows does not either)
            pop = QApplication.activePopupWidget()
            owner = pop.parentWidget() if pop is not None else None
            active = owner is not None and owner.window() is w
        self.set_window_active(active)

    def surface(self) -> str:
        """The bar's background: ``shell`` (Figma) while the window is active, ``titlebar-inactive`` otherwise."""
        return t("shell" if self.window_active else "titlebar-inactive")

    def set_window_active(self, on: bool) -> None:
        """Show the bar as the title bar of an active or an inactive window (no-op when unchanged)."""
        on = bool(on)
        if on == self.window_active:
            return
        self.window_active = on
        if not on:
            # the pointer left for another window without a Leave: no stale hover / pressed feedback
            from PySide6.QtGui import QCursor
            pos = QCursor.pos()
            for b in self.findChildren(QAbstractButton):
                if b.testAttribute(Qt.WidgetAttribute.WA_UnderMouse) and \
                        not b.rect().contains(b.mapFromGlobal(pos)):
                    b.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
                if b.isDown():
                    b.setDown(False)
        for w in [*self.menu_items, self.progress.label, self.progress.detail]:
            w.setProperty("inactive", not on)
            refresh_style(w)
        self.update()                                # the bar and its state line only - never the whole window
        self.row.update()
        self.line.update()
        for b in (self.panels_btn, self.exit_fs_btn, self.min_btn, self.max_btn, self.close_btn):
            b.update()

    def set_top_panels_visible(self, on: bool) -> None:
        self.panels_btn.set_icon("open_panel_filled_top" if on else "open_panel_top")
        tip = "Hide top panels" if on else "Show top panels"
        self.panels_btn.setToolTip(tip)
        self.panels_btn.setAccessibleName(tip)

    def set_caption_buttons_visible(self, on: bool) -> None:
        """Normal / maximized: the caption buttons; full screen (``on`` False): Exit full screen instead."""
        for b in (self.min_btn, self.max_btn, self.close_btn):
            b.setVisible(on)
        self.exit_fs_btn.setVisible(not on)

    def hit_test(self, pos: QPoint) -> str:
        """What the bar is at ``pos`` (bar coordinates, logical px): ``"max"`` (the maximise button - Snap
        Layouts), ``"client"`` (a control: menus, the panels action, minimise, close, a status Cancel) or
        ``"caption"`` (empty bar: drag, double-click, system menu)."""
        if not (0 <= pos.y() < TITLEBAR_HEIGHT) or not (0 <= pos.x() < self.width()):
            return "client" if self.rect().contains(pos) else "outside"
        if self.max_btn.isVisible() and self.max_btn.geometry().contains(self.row.mapFrom(self, pos)):
            return "max"
        child = self.row.childAt(self.row.mapFrom(self, pos))
        while child is not None and child is not self.row:
            if isinstance(child, (QAbstractButton, QPushButton)) and child.isVisible():
                return "client"
            child = child.parentWidget()
        return "caption"

    # -------------------------------------------------------------- keyboard (F10 / Alt: the menu bar)
    def enter_menu_mode(self) -> None:
        """F10 (or Alt alone): focus File; Left / Right move between the menus, Down / Enter open one, Esc leaves."""
        self._menu_mode_focus = QApplication.focusWidget()
        self.file_item.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def leave_menu_mode(self) -> None:
        w = self._menu_mode_focus
        self._menu_mode_focus = None
        try:
            if w is not None and w.isVisible():
                w.setFocus(Qt.FocusReason.ShortcutFocusReason)
                return
        except RuntimeError:
            pass
        self.window().setFocus()

    def in_menu_mode(self) -> bool:
        return any(w.hasFocus() for w in self.menu_items)

    # -------------------------------------------------------------- menu bar (one menu open at a time)
    def item_at_global(self, gp) -> "HeaderMenuItem | None":
        for it in self.menu_items:
            if it.isVisible() and it.rect().contains(it.mapFromGlobal(gp)):
                return it
        return None

    def hover_switch(self, menu, gp) -> bool:
        """The pointer, while ``menu`` is open, is over another title-bar menu: close this one, open that one
        (Windows menu bar).  Nothing opens on hover while no menu is open."""
        it = self.item_at_global(gp)
        if it is None or it is self.open_item or it.menu_ is None or self._switch_to is not None:
            return False
        self._switch_to = (it, False)
        menu.close()
        return True

    def switch_menu(self, menu, d: int, keyboard: bool = True) -> bool:
        """Left / Right in an open title-bar menu: the adjacent menu opens (first item active)."""
        if self.open_item is None or self.open_item not in self.menu_items:
            return False
        items = [w for w in self.menu_items if w.isVisible() and w.menu_ is not None]
        i = items.index(self.open_item)
        self._switch_to = (items[(i + d) % len(items)], keyboard)
        menu.close()
        return True

    def menu_closed(self, item) -> None:
        nxt, self._switch_to = self._switch_to, None
        if nxt is not None:
            target, keyboard = nxt
            # next event-loop turn: the closed menu's modal loop has returned - one menu at a time, no nesting
            QTimer.singleShot(0, lambda: target._open(keyboard=keyboard) if target.isVisible() else None)

    def move_menu_focus(self, item: QWidget, d: int) -> None:
        i = self.menu_items.index(item)
        self.menu_items[(i + d) % len(self.menu_items)].setFocus(Qt.FocusReason.ShortcutFocusReason)

    # -------------------------------------------------------------- status alignment
    def align_status_to(self, title: QWidget) -> None:
        """Start the status text ("Calculating…", "Calculation completed") at the left edge of ``title``'s text
        (the Composition panel title below it), from the live geometry: the panel moves with the window width
        and the horizontal scroll, so no fixed margin can keep the two aligned."""
        if title is None or not title.isVisible():
            return
        x = self.row.mapFromGlobal(title.mapToGlobal(QPoint(title.contentsRect().left() + max(0, title.indent()),
                                                            0))).x()
        start = self.menu_items[-1].geometry().right() + 1
        gap = max(16, x - start)
        if gap != self.status_gap.sizeHint().width():
            self.status_gap.changeSize(gap, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            self.row.layout().invalidate()

    THEME_ICONS = {"light": "brightness_contrast", "dark": "asleep", "system": "screen"}

    def set_theme_preference(self, pref: str) -> None:
        """The View menu's Theme choice marks the preference (the title bar has no theme button any more)."""
        self.theme_preference = pref


AppHeader = TitleBar          # former name (tools, tests)
