"""Shared fixtures and helpers of the UI regression modules (a real MainWindow on its own settings file)."""

import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    from hea_calc.ui.theme import load_fonts
    a = QApplication.instance() or QApplication([])
    load_fonts()
    return a


def pump(app, n=10):
    for _ in range(n):
        app.processEvents()


def make_window(app, theme="dark", size=(1920, 1040)):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(*size)
    w.show()
    pump(app)
    return w


def close(app, *ws):
    for w in ws:
        try:
            w.close()
            w.deleteLater()
        except RuntimeError:
            pass
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


def calc(win, app):
    win.calculate("single", ["CrFeMnCoNi"], [{"Cr": 1, "Fe": 1, "Mn": 1, "Co": 1, "Ni": 1}], [{}])
    pump(app, 20)


@pytest.fixture()
def win(app):
    w = make_window(app)
    yield w
    close(app, w)
