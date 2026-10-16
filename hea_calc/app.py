"""Application entry point."""

from __future__ import annotations

import os
import sys


def run(argv: list[str] | None = None) -> int:
    # High DPI: Qt 6 is per-monitor DPI aware on Windows and scales natively; nothing is forced or
    # faked here (no QT_SCALE_FACTOR / QT_FONT_DPI, and the Qt 5 QT_ENABLE_HIGHDPI_SCALING switch is
    # obsolete).  PassThrough - already the Qt 6 default - keeps Windows' fractional factors
    # (1.25 / 1.5) instead of rounding them; crisp strokes are handled by ui/crisp.py.
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("HEA Calculator")
    app.setOrganizationName("MDL")

    from .ui.theme import THEME, load_fonts

    load_fonts()
    # the stored preference is system | light | dark; the effective theme is resolved (System default follows
    # the OS colour scheme) before the first window exists, so nothing flashes in the wrong theme
    from .ui.preferences import DEFAULT_THEME, THEME_PREFERENCES
    from .ui.system_theme import resolve
    pref = QSettings("MDL", "HEA Calculator").value("theme", DEFAULT_THEME)
    THEME.set_theme(resolve(pref if pref in THEME_PREFERENCES else DEFAULT_THEME))

    from .ui.widgets.common import install_tooltips

    install_tooltips(app)   # the design's tooltip has a caret; Qt's own does not

    from .core.repository import RepositoryError
    from .ui.main_window import MainWindow

    try:
        win = MainWindow()
    except RepositoryError as exc:          # no writable folder for the session database
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "HEA Calculator", str(exc))
        return 1
    win.showMaximized()
    autoquit = os.environ.get("HEA_CALC_AUTOQUIT_MS")  # used by the entry-point smoke test
    if autoquit:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(int(autoquit), app.quit)
    return app.exec()
