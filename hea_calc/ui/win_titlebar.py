"""Native Windows title bars in the effective HEA theme (DWM attributes; the real caption is kept).

The application keeps the native frame - Snap Layouts, dragging, resizing, Alt+Tab, the system menu, the
shadow and the caption buttons stay Windows' own.  Only the caption colours are set, per window, through
``DwmSetWindowAttribute`` (dwmapi.dll):

* ``DWMWA_USE_IMMERSIVE_DARK_MODE`` = 20 (Windows 10 20H1 / build 19041 and later; the undocumented value 19
  on builds 17763-19040) - dark caption buttons and frame;
* ``DWMWA_BORDER_COLOR`` = 34, ``DWMWA_CAPTION_COLOR`` = 35, ``DWMWA_TEXT_COLOR`` = 36 - Windows 11 (build
  22000+) only; ``COLORREF`` is ``0x00BBGGRR``.

Colours are the theme's own tokens: caption = ``background`` (#161616 dark / #f4f4f4 light), text =
``text-primary``, border = ``background``.  Every call fails silently on other platforms and older builds
(the window then simply keeps the system caption).  Only this process's top-level QWidget windows are touched
- never native file dialogs, other applications or the global Windows theme.

``TitleBarThemer`` themes a window when it is shown or its native handle is recreated (``WinIdChange``) - as an
event filter on the application's own top-level windows only (:func:`watch`: main window, Help, About, every
``Modal``), never on the whole application: an application-wide Python event filter is called for every Qt event
and measurably stalled the GUI (≈ 0.5 s while Analysis rebuilt its widgets, release perf run 2026-10-16).  Windows
the application does not create itself (for example a ``QMessageBox``) are themed when they take focus
(``focusWindowChanged``).  :meth:`apply_all` re-themes every open window after a theme change.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36


def windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except AttributeError:
        return 0


def colorref(hex_color: str) -> int:
    """``#RRGGBB`` -> COLORREF ``0x00BBGGRR``."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r


def caption_attributes(theme: str, tokens: dict, build: int) -> list[tuple[int, int]]:
    """The (attribute, value) pairs for one window on this Windows build (pure: unit-tested anywhere)."""
    out: list[tuple[int, int]] = []
    dark = 1 if theme == "dark" else 0
    if build >= 19041:
        out.append((DWMWA_USE_IMMERSIVE_DARK_MODE, dark))
    elif build >= 17763:
        out.append((DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, dark))
    if build >= 22000:
        out.append((DWMWA_CAPTION_COLOR, colorref(tokens.get("shell", tokens["background"]))))
        out.append((DWMWA_TEXT_COLOR, colorref(tokens["text-primary"])))
        out.append((DWMWA_BORDER_COLOR, colorref(tokens.get("shell", tokens["background"]))))
    return out


def apply(widget: QWidget, theme: str, tokens: dict) -> bool:
    """Theme ``widget``'s native caption; True if DWM accepted every attribute."""
    build = windows_build()
    if not build or not widget.isWindow():
        return False
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = wintypes.HWND(int(widget.winId()))
        dwm = ctypes.windll.dwmapi
        ok = True
        for attr, value in caption_attributes(theme, tokens, build):
            v = wintypes.DWORD(value) if attr in (DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR) \
                else wintypes.BOOL(value)
            hr = dwm.DwmSetWindowAttribute(hwnd, wintypes.DWORD(attr), ctypes.byref(v), ctypes.sizeof(v))
            ok = ok and hr == 0
        widget.setProperty("titlebar_theme", theme if ok else "")
        return ok
    except Exception:                       # noqa: BLE001 - unsupported system: keep the default caption
        return False


def has_native_caption(w: QWidget) -> bool:
    """Top-level windows with a native caption (not popups, tooltips, frameless or native file dialogs)."""
    if not w.isWindow() or isinstance(w, QFileDialog):
        return False
    flags = w.windowFlags()
    if flags & Qt.WindowType.FramelessWindowHint:
        return False
    kind = flags & Qt.WindowType.WindowType_Mask
    return kind in (Qt.WindowType.Window, Qt.WindowType.Dialog)


class TitleBarThemer(QObject):
    """Keeps the native captions of watched windows in the effective theme (see module docstring)."""

    def __init__(self, app: QApplication, theme_getter, tokens_getter):
        super().__init__(app)
        self.theme = theme_getter
        self.tokens = tokens_getter
        app.focusWindowChanged.connect(self._focus_window)

    def watch(self, widget: QWidget) -> None:
        widget.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange) and isinstance(obj, QWidget) \
                and has_native_caption(obj):
            apply(obj, self.theme(), self.tokens())
        return False

    def _focus_window(self, window) -> None:
        if window is None:
            return
        for w in QApplication.topLevelWidgets():
            if w.windowHandle() is window and has_native_caption(w):
                apply(w, self.theme(), self.tokens())
                return

    def apply_all(self) -> None:
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and has_native_caption(w):
                apply(w, self.theme(), self.tokens())


_THEMER: TitleBarThemer | None = None
_PENDING: list = []


def install(app: QApplication, theme_getter, tokens_getter) -> TitleBarThemer:
    global _THEMER
    if _THEMER is None:
        _THEMER = TitleBarThemer(app, theme_getter, tokens_getter)
        for w in _PENDING:
            try:
                _THEMER.watch(w)
            except RuntimeError:
                pass
        _PENDING.clear()
    return _THEMER


def watch(widget: QWidget) -> None:
    """Theme ``widget``'s native caption whenever it is shown (call once, from the window's constructor)."""
    if _THEMER is not None:
        _THEMER.watch(widget)
    else:
        _PENDING.append(widget)


def themer() -> TitleBarThemer | None:
    return _THEMER
