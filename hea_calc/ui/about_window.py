"""About HEA Calculator: identity, purpose, institution, credits, references, technologies and licences.

Figma ``About`` (494:94818): a window with the native caption (no in-content Close button), 720 px wide, the
"MDL **HEA Calculator**" lock-up and three body paragraphs.  Below them, compact sections carry what the release brief
asks for: development and original-software credits, the numbered references (Materials Science and Engineering: A
style, ``core/references.py`` - the same list Help shows), the technologies the application is built with (versions
read at runtime) and the licences.  Nothing here is hard-coded that the running program can report itself.

Non-modal, one instance: links to Help open the documentation beside it; Esc or the caption's Close closes it.
"""

from __future__ import annotations

import html
import sqlite3
import sys
from importlib import metadata

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from .. import __version__
from ..core import references as R
from ..core.provenance import engine_version
from . import win_titlebar
from .theme import FONT_FAMILY, THEME
from .widgets.scroll import inner_scroll_area

WINDOW_TITLE = "About HEA Calculator"
SIZE = QSize(720, 640)
MARGIN = 40

PURPOSE = (
    "HEA Calculator is a scientific computing application for the design, exploration, and evaluation of "
    "multicomponent alloy compositions.",
    "The software provides tools for composition generation, thermodynamic and physical property calculations, and "
    "empirical phase prediction based on published scientific models.",
    "Developed at the Metals Development Laboratory (MDL), Department of Metallurgical and Materials Engineering, "
    "Middle East Technical University (METU), Ankara, Türkiye.",
)
AUTHOR = "Ali Fethi Erdem"


def _version(dist: str) -> str:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return ""


def built_with() -> list[tuple[str, str, str]]:
    """(component, version, role) of the technologies in use - versions from the running program."""
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import qVersion
    return [
        ("Python", sys.version.split()[0], "application and calculation engine"),
        ("Qt", qVersion(), "user interface, via Qt for Python (PySide6 " + pyside_version + ")"),
        ("SQLite", sqlite3.sqlite_version, "session results database"),
        ("openpyxl", _version("openpyxl"), "spreadsheet import"),
        ("XlsxWriter", _version("XlsxWriter"), "Excel export"),
        ("IBM Plex Sans", "", "typeface"),
        ("IBM Carbon Design System", "v11", "design reference and icons"),
    ]


LICENCES = (
    "HEA Calculator is free software, licensed under the GNU General Public License v3. It is provided without "
    "warranty.",
    "Third-party components: Qt for Python (GNU LGPL v3), IBM Plex Sans (SIL Open Font License 1.1), Carbon icons "
    "(Apache License 2.0).",
)


def _link(url: str, label: str | None = None) -> str:
    return f"<a href='{html.escape(url)}'>{html.escape(label or url)}</a>"


class AboutWindow(QDialog):
    """See module docstring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AboutWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.setModal(False)
        win_titlebar.watch(self)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.resize(SIZE)
        self.setMinimumSize(560, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        body.setObjectName("AboutBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(MARGIN, MARGIN + 8, MARGIN, MARGIN)
        lay.setSpacing(0)
        self.labels: list[QLabel] = []

        self.title = self._label("<span style='font-weight:300'>MDL</span> "
                                 "<span style='font-weight:600'>HEA Calculator</span>", "AboutTitle")
        lay.addWidget(self.title)
        lay.addSpacing(8)
        self.version = self._label(f"Version {html.escape(__version__)} · Calculation engine "
                                   f"{html.escape(engine_version())}", "AboutMeta")
        lay.addWidget(self.version)
        lay.addSpacing(32)
        for text in PURPOSE:
            lay.addWidget(self._label(html.escape(text), "AboutBodyText"))
            lay.addSpacing(16)

        self.sections: dict[str, QLabel] = {}

        def section(heading: str, content: str):
            lay.addSpacing(16)
            lay.addWidget(self._label(html.escape(heading), "AboutHeading"))
            lay.addSpacing(8)
            lab = self._label(content, "AboutSmall")
            lay.addWidget(lab)
            self.sections[heading] = lab

        section("Development", f"{html.escape(AUTHOR)} · Metals Development Laboratory, METU")
        o = R.ORIGINAL_SOFTWARE
        section("Original software",
                f"HEA Calculator is derived from {o['name']}, the open-source program created by "
                f"{html.escape(o['author'])}. Copyright in the original {o['name']} remains with its author.<br>"
                f"{_link(o['repository'], 'HEACalculator on GitHub')} · "
                f"{_link('https://doi.org/' + o['doi'], 'Cite HEACalculator (Zenodo)')}")
        refs = []
        for i, r in enumerate(R.REFERENCES, 1):
            line = f"[{i}] {html.escape(r.text())}"
            if r.url:
                line += " " + _link(r.url)
            refs.append(line)
        section("References", "".join(f"<p style='margin:0 0 6px 0'>{r}</p>" for r in refs)
                + "<p style='margin:10px 0 0 0'>Models M1–M8 are references [1]–[8]. Details: "
                + _link("help://references", "Help › Scientific References") + ".</p>")
        tech = []
        for name, ver, role in built_with():
            tech.append(f"<b>{html.escape(name)}</b>{(' ' + html.escape(ver)) if ver else ''} — {html.escape(role)}")
        section("Built with", "<br>".join(tech))
        section("Licence", "<br>".join(html.escape(t) for t in LICENCES))
        lay.addStretch(1)
        self.scroll = inner_scroll_area(body)
        self.scroll.setObjectName("AboutScroll")
        root.addWidget(self.scroll)
        THEME.changed.connect(self._apply_style)
        self._apply_style()

    def _label(self, rich: str, name: str) -> QLabel:
        lab = QLabel(rich)
        lab.setObjectName(name)
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        lab.setOpenExternalLinks(False)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lab.linkActivated.connect(self._open_link)
        lab.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        lab.customContextMenuRequested.connect(lambda pos, w=lab: self._context_menu(w, pos))
        self.labels.append(lab)
        return lab

    def _context_menu(self, lab: QLabel, pos) -> None:
        """Copy / Copy all as the shared Carbon menu (QLabel has no standard menu to restyle)."""
        from PySide6.QtGui import QGuiApplication, QTextDocument
        from .widgets.menu import CarbonMenu
        menu = CarbonMenu(parent=lab)
        menu.add_action("Copy", lambda: QGuiApplication.clipboard().setText(lab.selectedText()),
                        enabled=lab.hasSelectedText())
        doc = QTextDocument()
        doc.setHtml(lab.text())
        menu.add_action("Copy all", lambda: QGuiApplication.clipboard().setText(doc.toPlainText()))
        menu.exec(lab.mapToGlobal(pos))
        menu.deleteLater()

    def _open_link(self, href: str) -> None:
        if href.startswith("help://"):
            from . import help_router
            help_router.open(href, self.parentWidget() or self)
        else:
            QDesktopServices.openUrl(QUrl(href))

    def _apply_style(self, *_):
        k = THEME.tokens
        self.setStyleSheet(
            f"#AboutWindow, #AboutBody, #AboutScroll {{ background: {k['layer-01']}; border: none; }}"
            f"QLabel {{ font-family: '{FONT_FAMILY}'; background: transparent; }}"
            f"#AboutTitle {{ font-size: 32px; color: {k['text-primary']}; }}"
            f"#AboutMeta {{ font-size: 12px; color: {k['text-secondary']}; letter-spacing: 0.32px; }}"
            f"#AboutBodyText {{ font-size: 14px; color: {k['text-secondary']}; }}"
            f"#AboutHeading {{ font-size: 14px; font-weight: 600; color: {k['text-primary']}; }}"
            f"#AboutSmall {{ font-size: 12px; color: {k['text-secondary']}; letter-spacing: 0.32px; }}")
        link = k["link-primary"]
        for lab in self.labels:
            text = lab.text()
            if "<a " in text:
                # QLabel ignores QSS for anchors: colour them from the token
                import re
                text = re.sub(r"<a (style='[^']*' )?href=", f"<a style='color:{link}; text-decoration:none' href=",
                              text)
                lab.setText(text)

    def text(self) -> str:
        """Plain text of the window (tests)."""
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        return "\n".join((doc.setHtml(lab.text()), doc.toPlainText())[1] for lab in self.labels)
