"""Records every top-level window the application shows and flags the unexpected ones.

A widget shown while it has no parent becomes a native top-level window - for a moment, if it is placed in a layout
right after - which reads as a small window flashing open and shut.  :class:`WindowWatch` is an application-wide
event filter: every ``Show`` of a widget that ``isWindow()`` is recorded, and any that is not one of the
application's intended windows (main / Help / About / Analysis windows, dialogs, menus, popups, tooltips,
toggletips, the menu-trigger shadow) is listed in ``unexpected``.

    from tools.window_watch import WindowWatch
    with WindowWatch(app) as ww:
        ...drive the UI...
    assert not ww.unexpected, ww.unexpected

``tools/window_audit.py`` drives the main flows (Analysis Composition / Model details for every model and warning
state, Collection notices, dialogs, Help, the Analysis window, theme switches) and prints what it saw.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QDialog, QMenu, QWidget

INTENDED = ("MainWindow", "HelpWindow", "AboutWindow", "AnalysisWindow", "CarbonToolTip", "Toggletip",
            "_TriggerShadow", "QFileDialog", "QColorDialog", "QPrintDialog")


class WindowWatch(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.shown: list[tuple[str, str]] = []
        self.unexpected: list[tuple[str, str, str]] = []

    def __enter__(self):
        self.app.installEventFilter(self)
        return self

    def __exit__(self, *exc):
        self.app.removeEventFilter(self)
        return False

    @staticmethod
    def intended(w: QWidget) -> bool:
        if isinstance(w, (QDialog, QMenu)):
            return True
        if w.windowFlags() & Qt.WindowType.Popup == Qt.WindowType.Popup:          # dropdown lists, popovers
            return True
        if w.windowFlags() & Qt.WindowType.ToolTip == Qt.WindowType.ToolTip:
            return True
        return any(c.__name__ in INTENDED for c in type(w).__mro__)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            name = type(obj).__name__
            self.shown.append((name, obj.objectName()))
            if not self.intended(obj):
                text = ""
                for attr in ("text", "windowTitle"):
                    try:
                        text = text or str(getattr(obj, attr)())[:60]
                    except Exception:                   # noqa: BLE001 - diagnostics only
                        pass
                self.unexpected.append((name, obj.objectName(), text))
        return False
