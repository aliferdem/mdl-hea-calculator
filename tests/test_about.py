"""About window (release brief sections 40-43): native caption, no Close button, identity from the running program,
numbered references shared with Help, confirmed technologies only."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from hea_calc import __version__
from hea_calc.core import references as R
from hea_calc.core.provenance import engine_version


def test_reference_list_is_mse_a_style_and_numbered_by_model():
    assert [r.key for r in R.MODEL_REFERENCES] == [f"M{i}" for i in range(1, 9)]
    assert R.number("M1") == 1 and R.number("M8") == 8 and R.number("kittel") == 12
    m1 = R.MODEL_REFERENCES[0].text()
    assert m1 == ("X. Yang, Y. Zhang, Prediction of high-entropy stabilized solid-solution in multi-component alloys, "
                  "Mater. Chem. Phys. 132 (2012) 233–238.")
    assert R.MODEL_REFERENCES[0].url == "https://doi.org/10.1016/j.matchemphys.2011.11.021"
    assert all(r.doi for r in R.MODEL_REFERENCES)
    # fields the local sources do not establish stay empty instead of being guessed
    guo_liu = next(r for r in R.DATA_REFERENCES if r.key == "guo-liu")
    assert guo_liu.title == "" and guo_liu.doi == ""
    assert R.markdown(R.MODEL_REFERENCES).startswith("[1] X. Yang")


def test_help_and_about_cite_the_same_list():
    from hea_calc.core import docs
    page = docs.source("references")
    for i, r in enumerate(R.REFERENCES, 1):
        assert f"[{i}] {r.text()}" in page


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    a = QApplication.instance() or QApplication([])
    load_fonts()
    return a


@pytest.fixture()
def win(app):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1440, 900)
    w.show()
    app.processEvents()
    yield w
    from PySide6.QtCore import QEvent
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_about_window_frame_and_identity(win, app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton
    about = win.show_about()
    app.processEvents()
    assert about.isWindow() and about.isVisible() and not about.isModal()
    assert about.windowTitle() == "About HEA Calculator"
    assert (about.width(), about.height()) == (720, 640)
    assert not about.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert not about.findChildren(QPushButton), "no in-content Close button: the native caption closes it"
    assert win.show_about() is about, "one About window"
    text = about.text()
    assert "MDL HEA Calculator" in text
    assert f"Version {__version__}" in text and engine_version() in text
    assert "Metals Development Laboratory (MDL)" in text and "Middle East Technical University (METU)" in text
    assert "Doğuhan Sarıtürk" in text and "github.com/dogusariturk/HEACalculator" in about.sections[
        "Original software"].text()


def test_about_references_and_technologies_are_verified(win, app):
    import sqlite3
    import sys
    from PySide6.QtCore import qVersion
    about = win.show_about()
    refs = about.sections["References"].text()
    for i, r in enumerate(R.REFERENCES, 1):
        assert f"[{i}] " in refs
        if r.url:
            assert r.url in refs
    tech = about.text()
    for item in ("Python " + sys.version.split()[0], "Qt " + qVersion(), "SQLite " + sqlite3.sqlite_version,
                 "openpyxl", "XlsxWriter", "IBM Plex Sans", "Carbon Design System"):
        assert item in tech, item
    for unconfirmed in ("Nuitka", "Inno Setup"):
        assert unconfirmed not in tech
    assert "GNU General Public License v3" in tech


def test_about_links_open_help(win, app):
    about = win.show_about()
    about._open_link("help://references")
    app.processEvents()
    assert win._help.page == "references" and win._help.isVisible()


def test_help_and_about_close_with_the_main_window(win, app):
    about = win.show_about()
    help_ = win.show_help("home")
    app.processEvents()
    win.close()
    app.processEvents()
    assert not about.isVisible() and not help_.isVisible(), "no window keeps the application alive"


def test_about_follows_the_theme(win, app):
    from hea_calc.ui.theme import THEME
    about = win.show_about()
    dark = about.styleSheet()
    THEME.set_theme("light")
    app.processEvents()
    assert about.styleSheet() != dark and THEME.tokens["layer-01"] in about.styleSheet()
    THEME.set_theme("dark")
