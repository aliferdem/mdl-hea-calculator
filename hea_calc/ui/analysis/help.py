"""Help window (``HELP_UI_CONTENT_LAYOUT.md``): a non-modal window with a page list and the approved Help copy.

Pages are the final English content packaged in ``hea_calc/ui/help`` (``tools/build_help.py`` copies them from
``docs/analysis-redesign``): Workload estimation, Prediction model coverage, Analysing collections.  Reached
from the Analysis overflow menus and the Toggletips that point to them; search filters with highlighting.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QListWidget, QTextBrowser, QVBoxLayout

from ..theme import t
from ..widgets.scroll import thin_scrollbars

HELP_DIR = Path(__file__).resolve().parents[1] / "help"
PAGES = (("workload", "Workload estimation"), ("models", "Prediction model coverage"),
         ("collections", "Analysing collections"))

_OPEN: dict = {}


class HelpDialog(QDialog):
    def __init__(self, page: str = "models", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(960, 720)
        self.setMinimumSize(720, 560)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search help…")
        self.search.setAccessibleName("Search help")
        root.addWidget(self.search)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.nav = QListWidget()
        self.nav.setFixedWidth(240)
        self.nav.setAccessibleName("Help pages")
        for _key, title in PAGES:
            self.nav.addItem(title)
        row.addWidget(self.nav)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setAccessibleName("Help content")
        thin_scrollbars(self.view)
        row.addWidget(self.view, 1)
        root.addLayout(row, 1)
        self.nav.currentRowChanged.connect(self.show_page)
        self.search.textChanged.connect(self._find)
        keys = [k for k, _t in PAGES]
        self.nav.setCurrentRow(keys.index(page) if page in keys else 0)

    def show_page(self, i: int) -> None:
        if i < 0:
            return
        key = PAGES[i][0]
        path = HELP_DIR / f"{key}.md"
        text = path.read_text(encoding="utf-8") if path.exists() else f"# {PAGES[i][1]}\n\nHelp page not found."
        doc = self.view.document()
        doc.setDefaultStyleSheet(f"body {{ color: {t('text-primary')}; }} th {{ text-align: left; }} "
                                 f"table {{ border-collapse: collapse; }} td, th {{ padding: 3px 6px; }}")
        self.view.setMarkdown(text)
        self._find(self.search.text())

    def _find(self, text: str) -> None:
        if text:
            self.view.moveCursor(self.view.textCursor().MoveOperation.Start)
            self.view.find(text, QTextDocument.FindFlag(0))


def open_help(page: str, parent=None) -> HelpDialog:
    """Show (or raise) the single Help window at ``page``."""
    dlg = _OPEN.get("help")
    try:
        if dlg is not None and dlg.isVisible():
            keys = [k for k, _t in PAGES]
            dlg.nav.setCurrentRow(keys.index(page) if page in keys else 0)
            dlg.raise_()
            dlg.activateWindow()
            return dlg
    except RuntimeError:
        pass
    dlg = HelpDialog(page, parent)
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    _OPEN["help"] = dlg
    dlg.show()
    return dlg
