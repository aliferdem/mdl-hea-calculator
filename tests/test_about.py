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
    # a DOI with parentheses stays one link target (percent-encoded), with the readable DOI as the link text
    guo_liu = next(r for r in R.DATA_REFERENCES if r.key == "guo-liu")
    assert guo_liu.url == "https://doi.org/10.1016/S1002-0071(12)60080-X"
    assert f"[{guo_liu.url}](https://doi.org/10.1016/S1002-0071%2812%2960080-X)." in R.markdown(R.DATA_REFERENCES)
    # books carry no DOI
    assert all(not r.doi for r in R.REFERENCES if r.book)
    assert R.markdown(R.MODEL_REFERENCES).startswith("[1] X. Yang")


def test_readme_footnotes_match_the_application():
    """The README cites the bibliography as GitHub footnotes [^1]-[^14], each defined once at the end with the same
    entry as references.py and its DOI link; every definition is cited, and the first citations run 1, 2, ... 14, so
    the numbers GitHub displays are the application's numbers."""
    import re
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    first_def = readme.index("\n[^1]: ")
    body, notes = readme[:first_def], readme[first_def:]
    defs = {int(m.group(1)): " ".join(m.group(2).split())
            for m in re.finditer(r"^\[\^(\d+)\]: (.+?)(?=^\[\^\d+\]: |\Z)", notes, re.M | re.S)}
    assert sorted(defs) == list(range(1, len(R.REFERENCES) + 1))
    for i, r in enumerate(R.REFERENCES, 1):
        assert defs[i] == r.text() + (f" [{r.url}]({r.href})." if r.url else ""), i
    cites = [int(n) for n in re.findall(r"\[\^(\d+)\](?!:)", body)]
    assert list(dict.fromkeys(cites)) == list(range(1, len(R.REFERENCES) + 1)), "first citations in reference order"
    assert readme.splitlines()[0] == "![HEA Calculator main window](docs/screenshots/dark/main-window.png)"
    assert "criteria are implemented.[^1][^2][^3][^4][^5][^6][^7][^8]" in body
    for i in range(1, len(R.MODEL_REFERENCES) + 1):
        assert f"| **M{i}** | [^{i}] |" in body
    # no hand-made bibliography or anchors, and no citation linked straight to a DOI
    assert "## References" not in readme and "#ref-" not in readme and "<a name=" not in readme
    assert not re.search(r"\[\[\d+\]\]\(", readme)


def test_calculation_audit_footnotes_match_the_application():
    """CALCULATION_AUDIT.md cites with its own GitHub footnotes (named labels; footnotes are not shared between files).
    Every application reference is defined there with the same text and DOI link as references.py, every definition is
    cited, and every citation is defined."""
    import re
    root = Path(__file__).resolve().parents[1]
    audit = (root / "docs" / "CALCULATION_AUDIT.md").read_text(encoding="utf-8")
    defs = {m.group(1): " ".join(m.group(2).split())
            for m in re.finditer(r"^\[\^([\w-]+)\]: (.+?)(?=^\[\^[\w-]+\]: |\Z)", audit, re.M | re.S)}
    body = audit[:audit.index("\n[^")]
    cited = set(re.findall(r"\[\^([\w-]+)\](?!:)", body))
    assert cited == set(defs), (cited ^ set(defs))
    for r in R.REFERENCES:
        entry = r.text() + (f" [{r.url}]({r.href})." if r.url else "")
        assert entry in defs.values(), r.key


def test_help_citations_link_to_their_entries():
    """[n] in Help opens the entry in Scientific References (offline); the entries' DOIs are web links."""
    from hea_calc.core import docs
    refs_html = docs.to_html(docs.source("references"))
    for i, r in enumerate(R.REFERENCES, 1):
        assert f'<a name="ref-{i}"></a>[{i}] ' in refs_html
        if r.url:
            assert f'<a href="{r.href}">{r.url}</a>.' in refs_html
    page = docs.to_html(docs.source("elemental-data"))
    assert '<a href="help://references#ref-11">[11]</a>' in page
    assert docs.resolve("help://references#ref-11").page == "references"
    assert "[99]" in docs.inline("[99]") and "href" not in docs.inline("[99]"), "only real reference numbers link"


def test_version_is_consistent():
    """One version: the package, pyproject.toml, uv.lock, CITATION.cff and the README agree (PEP 440)."""
    import re
    import tomllib
    from packaging.version import Version
    root = Path(__file__).resolve().parents[1]
    assert str(Version(__version__)) == __version__, "PEP 440 normal form"
    assert tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == __version__
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    assert re.search(r'name = "hea-calculator"\s+version = "([^"]+)"', lock).group(1) == __version__
    assert re.search(r"^version: (\S+)$", (root / "CITATION.cff").read_text(encoding="utf-8"), re.M).group(1)         == __version__
    assert f"Version {__version__} " in (root / "README.md").read_text(encoding="utf-8")


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
    assert about.windowTitle() == "About MDL HEA Calculator"
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
