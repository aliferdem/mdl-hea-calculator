"""One entry point for every in-app Help link: ``help://<page>#<anchor>`` (see ``core/docs.py``).

F1, the header Help button, the File menu, Toggletip links and Analysis overflow menus all call ``open``; the
main window owns the single Help window and shows the requested page there.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from ..core import docs


def _main_window(widget: QWidget | None):
    w = widget.window() if widget is not None else None
    while w is not None and not hasattr(w, "show_help"):
        p = w.parentWidget()
        w = p.window() if p is not None else None
    if w is not None:
        return w
    for top in QApplication.topLevelWidgets():
        if hasattr(top, "show_help"):
            return top
    return None


def open(href: str, widget: QWidget | None = None) -> bool:  # noqa: A001 - mirrors QDesktopServices.openUrl
    """Show ``href`` in the Help window; False when the target is unknown or no main window exists."""
    route = docs.resolve(href)
    win = _main_window(widget)
    if route is None or win is None:
        return False
    win.show_help(route.page, route.anchor)
    return True
