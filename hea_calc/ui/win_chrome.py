"""Native Windows behaviour for the main window's custom 32 px title bar (``widgets/header.TitleBar``).

The window is a normal Windows window with a caption-less client area - not a "frameless" window that imitates
one.  The native style keeps ``WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX``, so
everything Windows does for a captioned window stays Windows' own:

* Aero Snap (drag to an edge or corner), Win+arrow keys, the minimise / maximise / restore animations, Alt+Space
  and right-click system menu, Alt+F4, Alt+Tab, the DWM shadow and the Windows 11 rounded corners;
* dragging and double-click maximise / restore: the empty parts of the bar answer ``HTCAPTION``;
* Snap Layouts: the maximise button answers ``HTMAXBUTTON``, so Windows 11 opens its layout flyout on hover; the
  button's hover / press is driven from the non-client mouse messages (Windows owns the pointer there) and a click
  toggles maximise;
* resizing: ``HTLEFT`` … ``HTBOTTOMRIGHT`` within the system resize border (``SM_CXSIZEFRAME`` +
  ``SM_CXPADDEDBORDER`` at the window's DPI) along every edge - the top one included, above the bar.

What changes: ``WM_NCCALCSIZE`` returns the whole window as client area, so Qt paints the title bar.  A maximised
window extends past the monitor by the resize border on every side; its client rectangle is inset by that border
(and by 2 px on the edge of an auto-hide taskbar, so the taskbar can still be revealed).

Qt is told the window is frameless (``FramelessWindowHint``), so its geometry has no frame margins - matching the
caption-less client area; the native style bits Qt removes for a frameless window are put back after every
native window (re)creation.  Every call fails silently on other platforms; non-Windows builds and the offscreen
test platform keep the bar's own buttons (minimise / maximise / close through Qt).
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtWidgets import QApplication, QWidget

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCMOUSEMOVE = 0x00A0
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCLBUTTONDBLCLK = 0x00A3
WM_NCMOUSELEAVE = 0x02A2
WM_NCACTIVATE = 0x0086

HTCLIENT, HTCAPTION, HTMAXBUTTON = 1, 2, 9
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
NATIVE_STYLE = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
SWP_FLAGS = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020    # NOSIZE | NOMOVE | NOZORDER | NOACTIVATE | FRAMECHANGED
SM_CXSIZEFRAME, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 32, 33, 92
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
ABM_GETSTATE, ABM_GETAUTOHIDEBAREX, ABS_AUTOHIDE = 4, 11, 1
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3
MONITOR_DEFAULTTONEAREST = 2
AUTOHIDE_GAP = 2


class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT), ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                ("rcNormalPosition", wintypes.RECT)]


def set_normal_rect(hwnd: int, left: int, top: int, right: int, bottom: int) -> bool:
    """Set the rectangle Restore returns a (maximized) window to, in screen device pixels.  With this chrome
    the whole window is client area, so this is exactly the window's normal geometry - a window maximized before
    it was ever shown normal otherwise kept Windows' guess, the client grown by the standard frame margins.
    ``rcNormalPosition`` is in work-area coordinates (they differ from screen coordinates when the taskbar is at
    the top or the left)."""
    if not supported():
        return False
    u = ctypes.windll.user32
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not u.GetWindowPlacement(wintypes.HWND(hwnd), ctypes.byref(wp)):
        return False
    mon = u.MonitorFromWindow(wintypes.HWND(hwnd), 2)          # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    dx = dy = 0
    if mon and u.GetMonitorInfoW(mon, ctypes.byref(mi)):
        dx, dy = mi.rcWork.left - mi.rcMonitor.left, mi.rcWork.top - mi.rcMonitor.top
    wp.rcNormalPosition = wintypes.RECT(left - dx, top - dy, right - dx, bottom - dy)
    wp.flags = 0
    return bool(u.SetWindowPlacement(wintypes.HWND(hwnd), ctypes.byref(wp)))


def supported() -> bool:
    """Custom chrome needs the real Windows platform (not offscreen / minimal test platforms)."""
    if sys.platform != "win32":
        return False
    app = QApplication.instance()
    return app is not None and app.platformName() == "windows"


def _user32():
    u = ctypes.windll.user32
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    u.DefWindowProcW.restype = ctypes.c_ssize_t
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    return u


def frame_thickness(hwnd: int) -> tuple[int, int]:
    """(x, y) resize border of ``hwnd`` in physical px at its DPI (size frame + padded border)."""
    u = ctypes.windll.user32
    try:
        dpi = u.GetDpiForWindow(wintypes.HWND(hwnd)) or 96
        pad = u.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
        return (u.GetSystemMetricsForDpi(SM_CXSIZEFRAME, dpi) + pad, u.GetSystemMetricsForDpi(SM_CYSIZEFRAME, dpi) + pad)
    except (AttributeError, OSError):
        pad = u.GetSystemMetrics(SM_CXPADDEDBORDER)
        return (u.GetSystemMetrics(SM_CXSIZEFRAME) + pad, u.GetSystemMetrics(SM_CYSIZEFRAME) + pad)


def hit_zone(x: int, y: int, w: int, h: int, bx: int, by: int, maximized: bool, bar: str) -> int:
    """The ``WM_NCHITTEST`` answer for window-local physical point (x, y) of a w × h window with resize borders
    (bx, by); ``bar`` is the title bar's own answer for that point (``TitleBar.hit_test``).  Pure (unit-tested)."""
    if not maximized:
        left, right = x < bx, x >= w - bx
        top, bottom = y < by, y >= h - by
        if top and left:
            return HTTOPLEFT
        if top and right:
            return HTTOPRIGHT
        if bottom and left:
            return HTBOTTOMLEFT
        if bottom and right:
            return HTBOTTOMRIGHT
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
        if bottom:
            return HTBOTTOM
        if top and bar != "max":
            return HTTOP
    return {"max": HTMAXBUTTON, "caption": HTCAPTION}.get(bar, HTCLIENT)


def maximized_client(rect: tuple[int, int, int, int], bx: int, by: int,
                     autohide: tuple[bool, bool, bool, bool] = (False, False, False, False)) -> tuple[int, int, int, int]:
    """Client rectangle of a maximised window whose window rectangle ``rect`` (l, t, r, b) overhangs the monitor
    by the resize border; ``autohide`` = auto-hide taskbar on (left, top, right, bottom).  Pure (unit-tested)."""
    l, t, r, b = rect
    l, t, r, b = l + bx, t + by, r - bx, b - by
    if autohide[0]:
        l += AUTOHIDE_GAP
    if autohide[1]:
        t += AUTOHIDE_GAP
    if autohide[2]:
        r -= AUTOHIDE_GAP
    if autohide[3]:
        b -= AUTOHIDE_GAP
    return l, t, r, b


def _autohide_edges(hwnd: int) -> tuple[bool, bool, bool, bool]:
    try:
        shell = ctypes.windll.shell32
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        if not shell.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd)) & ABS_AUTOHIDE:
            return (False, False, False, False)
        u = ctypes.windll.user32
        mon = u.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        u.GetMonitorInfoW(mon, ctypes.byref(mi))
        out = []
        for edge in (ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM):
            a = APPBARDATA()
            a.cbSize = ctypes.sizeof(APPBARDATA)
            a.uEdge = edge
            a.rc = mi.rcMonitor
            out.append(bool(shell.SHAppBarMessage(ABM_GETAUTOHIDEBAREX, ctypes.byref(a))))
        return tuple(out)
    except (AttributeError, OSError):
        return (False, False, False, False)


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


def _signed16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class WinChrome(QObject):
    """Installs the native behaviour on ``window`` (a QMainWindow) whose title bar is ``bar``.  The window
    forwards ``nativeEvent`` here (:meth:`native_event`)."""

    def __init__(self, window: QWidget, bar):
        super().__init__(window)
        self.window = window
        self.bar = bar
        self.enabled = supported()
        self._tracking = False
        if not self.enabled:
            return
        window.setWindowFlags(window.windowFlags() | Qt.WindowType.FramelessWindowHint)
        window.installEventFilter(self)

    # -------------------------------------------------------------- native window set-up
    def hwnd(self) -> int:
        return int(self.window.internalWinId() or 0)

    def apply_style(self) -> None:
        h = self.hwnd()
        if not self.enabled or not h:
            return
        try:
            u = _user32()
            style = u.GetWindowLongPtrW(wintypes.HWND(h), GWL_STYLE)
            if (style & NATIVE_STYLE) != NATIVE_STYLE:
                u.SetWindowLongPtrW(wintypes.HWND(h), GWL_STYLE, style | NATIVE_STYLE)
                u.SetWindowPos(wintypes.HWND(h), None, 0, 0, 0, 0, SWP_FLAGS)
            dwm = ctypes.windll.dwmapi
            m = MARGINS(0, 0, 1, 0)                 # a 1 px DWM frame: the shadow on Windows 10 (hidden by Qt)
            dwm.DwmExtendFrameIntoClientArea(wintypes.HWND(h), ctypes.byref(m))
            pref = ctypes.c_int(DWMWCP_ROUND)       # Windows 11 rounded corners (ignored on Windows 10)
            dwm.DwmSetWindowAttribute(wintypes.HWND(h), DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref),
                                      ctypes.sizeof(pref))
        except (AttributeError, OSError):
            pass

    def eventFilter(self, obj, ev):
        if obj is self.window:
            et = ev.type()
            if et in (QEvent.Type.Show, QEvent.Type.WinIdChange):
                self.apply_style()
            elif et == QEvent.Type.WindowStateChange:
                self.bar.set_maximized(bool(self.window.windowState() & Qt.WindowState.WindowMaximized))
            # activation: the title bar keeps its own active / inactive state (widgets/header.TitleBar)
        return False

    # -------------------------------------------------------------- messages
    def native_event(self, event_type, message):
        """``(handled, result)`` for the window's ``nativeEvent``."""
        if not self.enabled or event_type not in (b"windows_generic_MSG", "windows_generic_MSG"):
            return False, 0
        msg = _MSG.from_address(int(message))
        m = msg.message
        if m == WM_NCCALCSIZE:
            return self._calc_size(msg)
        if m == WM_NCHITTEST:
            return True, self._hit_test(msg)
        if m in (WM_NCMOUSEMOVE, WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCLBUTTONDBLCLK, WM_NCMOUSELEAVE):
            return self._max_button(msg)
        return False, 0

    def _calc_size(self, msg):
        if not msg.wParam:
            return True, 0
        params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
        if bool(ctypes.windll.user32.IsZoomed(msg.hwnd)):
            r = params.rgrc[0]
            bx, by = frame_thickness(int(msg.hwnd))
            l, t, rr, b = maximized_client((r.left, r.top, r.right, r.bottom), bx, by, _autohide_edges(int(msg.hwnd)))
            r.left, r.top, r.right, r.bottom = l, t, rr, b
        return True, 0                              # the whole (remaining) window is client area

    def _local(self, msg) -> tuple[int, int, int, int]:
        """(x, y, w, h) of the message's screen point in window-local physical px."""
        x, y = _signed16(msg.lParam), _signed16(msg.lParam >> 16)
        rc = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(msg.hwnd, ctypes.byref(rc))
        return x - rc.left, y - rc.top, rc.right - rc.left, rc.bottom - rc.top

    def bar_zone(self, x: int, y: int) -> str:
        """The title bar's answer for window-local physical point (x, y)."""
        dpr = self.window.devicePixelRatioF() or 1.0
        p = QPoint(int(x / dpr), int(y / dpr))
        bp = self.bar.mapFrom(self.window, p)
        return self.bar.hit_test(bp)

    def _hit_test(self, msg) -> int:
        x, y, w, h = self._local(msg)
        bx, by = frame_thickness(int(msg.hwnd))
        if self.window.isFullScreen():
            return HTCLIENT                    # full screen: no resize edges, no caption drag out of it
        maximized = bool(ctypes.windll.user32.IsZoomed(msg.hwnd))
        return hit_zone(x, y, w, h, bx, by, maximized, self.bar_zone(x, y))

    def _max_button(self, msg):
        """Windows owns the pointer over HTMAXBUTTON: drive the button's hover / press and the click here."""
        btn = self.bar.max_btn
        m = msg.message
        over = msg.wParam == HTMAXBUTTON
        if m == WM_NCMOUSELEAVE:
            self._tracking = False
            if btn.native_hover or btn.native_down:
                btn.native_hover = btn.native_down = False
                btn.update()
            return False, 0
        if m == WM_NCMOUSEMOVE:
            if btn.native_hover != over:
                btn.native_hover = over
                if not over:
                    btn.native_down = False
                btn.update()
            if over and not self._tracking:
                self._track_leave(msg.hwnd)
            return False, 0                         # no tooltip: the caption buttons have none (Snap Layouts)
        if not over:
            if btn.native_down:
                btn.native_down = False
                btn.update()
            return False, 0
        if m in (WM_NCLBUTTONDOWN, WM_NCLBUTTONDBLCLK):
            btn.native_down = True
            btn.update()
            return True, 0                          # eaten: no classic caption button tracking
        if m == WM_NCLBUTTONUP:
            was = btn.native_down
            btn.native_down = False
            btn.update()
            if was:
                self.bar.maximize_requested.emit()
            return True, 0
        return False, 0

    def _track_leave(self, hwnd) -> None:
        class TRACKMOUSEEVENT(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("hwndTrack", wintypes.HWND),
                        ("dwHoverTime", wintypes.DWORD)]
        tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), 0x00000002 | 0x00000010, hwnd, 0)  # LEAVE|NONCLIENT
        try:
            ctypes.windll.user32.TrackMouseEvent(ctypes.byref(tme))
            self._tracking = True
        except (AttributeError, OSError):
            pass

    # -------------------------------------------------------------- tests / diagnostics
    def send_hit_test(self, x: int, y: int) -> int:
        """``WM_NCHITTEST`` for window-local *logical* point (x, y), answered by the real window procedure."""
        h = self.hwnd()
        if not h:
            return 0
        dpr = self.window.devicePixelRatioF() or 1.0
        rc = wintypes.RECT()
        u = _user32()
        u.GetWindowRect(wintypes.HWND(h), ctypes.byref(rc))
        sx, sy = rc.left + int(x * dpr), rc.top + int(y * dpr)
        lp = ((sy & 0xFFFF) << 16) | (sx & 0xFFFF)
        u.SendMessageW.restype = ctypes.c_ssize_t
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        return int(u.SendMessageW(wintypes.HWND(h), WM_NCHITTEST, 0, lp))

    def native_style(self) -> int:
        h = self.hwnd()
        return int(_user32().GetWindowLongPtrW(wintypes.HWND(h), GWL_STYLE)) if h else 0


__all__ = ["WinChrome", "supported", "hit_zone", "maximized_client", "frame_thickness", "HTCLIENT", "HTCAPTION",
           "HTMAXBUTTON", "HTTOP", "HTLEFT", "HTRIGHT", "HTBOTTOM", "HTTOPLEFT", "HTTOPRIGHT", "HTBOTTOMLEFT",
           "HTBOTTOMRIGHT", "NATIVE_STYLE"]
