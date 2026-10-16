"""System default theme: resolve the effective application theme from the operating-system colour scheme.

The stored *preference* is ``system`` | ``light`` | ``dark`` (``ui/preferences.py``).  With ``system`` the
effective theme follows the OS - Qt 6.5+ ``QStyleHints.colorScheme()`` (PySide6 6.7 here) and its
``colorSchemeChanged`` signal, so a Windows switch between light and dark apps is followed while the
application runs.  If Qt reports ``Unknown`` the Windows ``AppsUseLightTheme`` registry value is read
(``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize``); if that is unavailable too, dark (the
authoritative HEA theme) is used.  Resolving never writes the preference.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication


def _registry_scheme() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) else "dark"
    except OSError:
        return None


def os_scheme() -> str | None:
    """``light`` / ``dark`` as the OS reports it, or None when it cannot be determined."""
    app = QGuiApplication.instance()
    if app is not None:
        try:
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
            if scheme == Qt.ColorScheme.Light:
                return "light"
        except AttributeError:            # Qt < 6.5
            pass
    return _registry_scheme()


def resolve(preference: str, os_value: str | None = None) -> str:
    """The effective theme for a preference (``system`` follows the OS; unknown OS scheme -> dark)."""
    if preference in ("light", "dark"):
        return preference
    value = os_value if os_value is not None else os_scheme()
    return value if value in ("light", "dark") else "dark"


class SystemThemeWatcher(QObject):
    """Emits ``changed(scheme)`` when the OS colour scheme changes while the application runs."""

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        app = QGuiApplication.instance()
        self.supported = False
        if app is not None:
            try:
                app.styleHints().colorSchemeChanged.connect(self._changed)
                self.supported = True
            except AttributeError:
                pass

    def _changed(self, *_):
        scheme = os_scheme()
        if scheme:
            self.changed.emit(scheme)
