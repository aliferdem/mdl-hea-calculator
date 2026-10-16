"""Help window: the HEA Calculator documentation (``core/docs.py`` is the model; this module only presents it).

A non-modal top-level window with the native Windows caption (no in-content Close button), titled
"Help — HEA Calculator", 960 × 720 by default.  Layout (Thermo-Calc-style documentation browser, Carbon v11
behaviour):

* compact 48 px header - Home (Documentation Home) and the documentation search field;
* 264 px navigation tree - every section and page of ``docs.TREE``, the current page marked with the Carbon
  selected-node bar; sections expand and collapse;
* article view - breadcrumb, H1, lead, body, related topics and previous / next, rendered from Markdown.

Every link goes through ``help://page#anchor``; external links open in the default browser.  Search results
replace the article until the field is cleared (Esc); following a result highlights the matched terms.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QKeySequence, QPainter, QPixmap, QShortcut,
                           QTextCharFormat, QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLineEdit, QStyle, QStyledItemDelegate,
                               QTextBrowser, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import docs
from . import crisp, icons, win_titlebar
from .theme import BODY_COMPACT_01, FONT_FAMILY, HEADING_COMPACT_01, THEME, font, t
from .widgets.common import IconButton
from .widgets.menu import carbonize_popups
from .widgets.scroll import thin_scrollbars

WINDOW_TITLE = "Help — HEA Calculator"
DEFAULT_SIZE = QSize(960, 720)
MINIMUM_SIZE = QSize(720, 560)
NAV_WIDTH = 264
HEADER_HEIGHT = 48
ROW_HEIGHT = 32
CONTENT_MARGIN = 40           # article side margins
MAX_IMAGE_WIDTH = 760
PAGE_ROLE = Qt.ItemDataRole.UserRole


class _NavDelegate(QStyledItemDelegate):
    """Carbon tree-view rows: 32 px, section rows semibold with a chevron, current page on layer-selected with
    the 3 px interactive bar; hover on layer-hover."""

    def __init__(self, tree: "HelpNav"):
        super().__init__(tree)
        self.tree = tree

    def sizeHint(self, option, index):
        return QSize(NAV_WIDTH, ROW_HEIGHT)

    def paint(self, p: QPainter, option, index: QModelIndex):
        p.save()
        r = option.rect
        item = self.tree.itemFromIndex(index)
        depth = 0
        parent = item.parent()
        while parent is not None:
            depth += 1
            parent = parent.parent()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            crisp.fill_rect(p, r, t("layer-selected-01"))
            crisp.fill_rect(p, QRect(r.x(), r.y(), 3, r.height()), t("border-interactive"))
        elif hover:
            crisp.fill_rect(p, r, t("layer-hover-01"))
        has_children = item.childCount() > 0
        f = font(HEADING_COMPACT_01 if (depth == 0 and has_children) or selected else BODY_COMPACT_01)
        p.setFont(f)
        p.setPen(QColor(t("text-primary") if selected or depth == 0 else t("text-secondary")))
        x = r.x() + 16 + 16 * depth
        right = r.right() - (36 if has_children else 12)
        text_rect = QRect(x, r.y(), max(0, right - x), r.height())
        text = p.fontMetrics().elidedText(item.text(0), Qt.TextElideMode.ElideRight, text_rect.width())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if has_children:
            size = 16
            cx = r.right() - 12 - size
            cy = r.y() + (r.height() - size) / 2
            p.translate(cx + size / 2, cy + size / 2)
            p.rotate(90 if item.isExpanded() else 0)          # chevron_right -> down when expanded
            icons.paint(p, "chevron_right", QRectF(-size / 2, -size / 2, size, size), "icon-secondary")
        p.restore()


class HelpNav(QTreeWidget):
    """The documentation tree (one item per ``docs`` page)."""

    page_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HelpNav")
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.setMouseTracking(True)
        self.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAccessibleName("Documentation contents")
        self.setItemDelegate(_NavDelegate(self))
        thin_scrollbars(self)
        self.items: dict[str, QTreeWidgetItem] = {}
        home = QTreeWidgetItem([docs.NODES[docs.HOME].title])
        home.setData(0, PAGE_ROLE, docs.HOME)
        self.addTopLevelItem(home)
        self.items[docs.HOME] = home
        for node in docs.TREE.children:
            self._add(node, None)
        self.itemClicked.connect(self._clicked)
        self.currentItemChanged.connect(self._current_changed)
        self._silent = False

    def _add(self, node: docs.Node, parent: QTreeWidgetItem | None):
        item = QTreeWidgetItem([node.title])
        item.setData(0, PAGE_ROLE, node.id)
        item.setToolTip(0, "")
        if parent is None:
            self.addTopLevelItem(item)
        else:
            parent.addChild(item)
        self.items[node.id] = item
        for c in node.children:
            self._add(c, item)

    def _clicked(self, item: QTreeWidgetItem, _col: int):
        pos = self.viewport().mapFromGlobal(self.cursor().pos())
        rect = self.visualItemRect(item)
        on_chevron = item.childCount() and pos.x() >= rect.right() - 40
        if on_chevron:
            item.setExpanded(not item.isExpanded())
            return
        if item.childCount() and not item.isExpanded():
            item.setExpanded(True)

    def _current_changed(self, cur, _prev):
        if cur is not None and not self._silent:
            self.page_activated.emit(cur.data(0, PAGE_ROLE))

    def select_page(self, page: str) -> None:
        item = self.items.get(page)
        if item is None:
            return
        p = item.parent()
        while p is not None:
            p.setExpanded(True)
            p = p.parent()
        self._silent = True
        try:
            self.setCurrentItem(item)
        finally:
            self._silent = False
        self.scrollToItem(item)

    def keyPressEvent(self, e):
        item = self.currentItem()
        if item is not None and item.childCount():
            if e.key() == Qt.Key.Key_Right and not item.isExpanded():
                item.setExpanded(True)
                return
            if e.key() == Qt.Key.Key_Left and item.isExpanded():
                item.setExpanded(False)
                return
        super().keyPressEvent(e)


class _Divider(QWidget):
    """1 px crisp separator (horizontal or vertical)."""

    def __init__(self, vertical: bool, parent=None):
        super().__init__(parent)
        self.vertical = vertical
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)

    def paintEvent(self, _e):
        p = QPainter(self)
        crisp.fill_rect(p, self.rect(), t("border-subtle-01"))
        p.end()


class HelpBrowser(QTextBrowser):
    """Article view: help:// links are routed by the window; images resolve against ``docs.DOCS_DIR``."""

    link = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HelpBrowser")
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setSearchPaths([str(docs.DOCS_DIR)])
        self.setAccessibleName("Help article")
        self.image_width = 640
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        thin_scrollbars(self)
        self.anchorClicked.connect(lambda url: self.link.emit(url.toString()))
        self._images: dict = {}

    def loadResource(self, kind, url):
        """Screenshots are scaled here, smoothly and at the screen's device-pixel ratio, to the width the article
        gives them - QTextDocument would otherwise scale the full-size capture with a fast, jagged transform."""
        if kind == QTextDocument.ResourceType.ImageResource.value or kind == QTextDocument.ResourceType.ImageResource:
            name = url.toString()
            path = docs.DOCS_DIR / name
            size = docs.png_size(path)
            if size:
                width = min(self.image_width, size[0])
                dpr = self.devicePixelRatioF()
                key = (name, width, dpr)
                pm = self._images.get(key)
                if pm is None:
                    src = QPixmap(str(path))
                    target = max(1, round(width * dpr))
                    pm = src if src.width() <= target else src.scaledToWidth(
                        target, Qt.TransformationMode.SmoothTransformation)
                    pm.setDevicePixelRatio(pm.width() / width)
                    if len(self._images) > 32:
                        self._images.clear()
                    self._images[key] = pm
                return pm
        return super().loadResource(kind, url)


def stylesheet() -> str:
    k = THEME.tokens
    return f"""
body {{ color: {k['text-primary']}; font-family: '{FONT_FAMILY}'; font-size: 14px; }}
p {{ margin-top: 0px; margin-bottom: 12px; line-height: 110%; }}
li {{ margin-bottom: 4px; line-height: 110%; }}
ul, ol {{ margin-top: 0px; margin-bottom: 12px; }}
h1 {{ font-size: 32px; font-weight: 300; margin-top: 0px; margin-bottom: 16px; }}
h2 {{ font-size: 20px; font-weight: 400; margin-top: 28px; margin-bottom: 12px; }}
h3 {{ font-size: 16px; font-weight: 600; margin-top: 20px; margin-bottom: 8px; }}
h4 {{ font-size: 14px; font-weight: 600; margin-top: 16px; margin-bottom: 6px; }}
a {{ color: {k['link-primary']}; text-decoration: none; }}
b {{ font-weight: 600; }}
code {{ font-family: 'IBM Plex Mono', Consolas, monospace; font-size: 13px; color: {k['text-primary']};
        background-color: {k['layer-02']}; }}
kbd {{ font-family: 'IBM Plex Mono', Consolas, monospace; font-size: 13px; background-color: {k['layer-02']}; }}
pre {{ font-family: 'IBM Plex Mono', Consolas, monospace; font-size: 13px; background-color: {k['layer-01']};
       margin-bottom: 12px; }}
p.lead {{ font-size: 16px; color: {k['text-secondary']}; margin-bottom: 20px; line-height: 115%; }}
p.breadcrumb {{ font-size: 12px; color: {k['text-secondary']}; margin-bottom: 12px; }}
span.sep {{ color: {k['text-helper']}; }}
p.figure {{ margin-top: 8px; margin-bottom: 4px; }}
p.caption {{ font-size: 12px; color: {k['text-secondary']}; margin-bottom: 16px; }}
table.data {{ margin-top: 4px; margin-bottom: 16px; border-collapse: collapse; }}
table.data th {{ background-color: {k['layer-accent-01'] if 'layer-accent-01' in k else k['layer-02']};
                 font-weight: 600; color: {k['text-primary']}; }}
table.data td {{ border-bottom: 1px solid {k['border-subtle-01']}; color: {k['text-primary']}; }}
table.callout {{ margin-top: 4px; margin-bottom: 16px; }}
td.bar {{ background-color: {k['border-interactive']}; }}
td.note {{ background-color: {k['layer-01']}; padding: 12px 16px 0px 16px; }}
h2.related {{ margin-top: 32px; }}
table.prevnext {{ margin-top: 32px; border-top: 1px solid {k['border-subtle-01']}; }}
td.pn {{ padding-top: 16px; padding-bottom: 24px; }}
span.pnlabel {{ font-size: 12px; color: {k['text-secondary']}; }}
p.hit {{ margin-bottom: 18px; }}
span.hitpath {{ font-size: 12px; color: {k['text-helper']}; }}
span.excerpt {{ color: {k['text-secondary']}; }}
"""


class HelpWindow(QWidget):
    """The single documentation window (see module docstring)."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("HelpWindow")
        self.setWindowTitle(WINDOW_TITLE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        win_titlebar.watch(self)
        self.resize(DEFAULT_SIZE)
        self.setMinimumSize(MINIMUM_SIZE)
        self.page = docs.HOME
        self.anchor = ""
        self.query = ""
        self._highlight: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("HelpHeader")
        header.setFixedHeight(HEADER_HEIGHT)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 8, 0)
        hl.setSpacing(0)
        self.home_btn = IconButton("home", "Documentation Home", header)
        self.home_btn.setFixedSize(HEADER_HEIGHT, HEADER_HEIGHT)
        self.home_btn.clicked.connect(lambda: self.open(docs.HOME))
        self.home_btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        hl.addWidget(self.home_btn)
        hl.addSpacing(NAV_WIDTH - HEADER_HEIGHT)
        self.search = QLineEdit(header)
        self.search.setObjectName("HelpSearch")
        self.search.setPlaceholderText("Search documentation")
        self.search.setAccessibleName("Search documentation")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", "icon-secondary"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedHeight(32)
        hl.addSpacing(CONTENT_MARGIN - 8)
        hl.addWidget(self.search, 1)
        hl.addSpacing(CONTENT_MARGIN - 8)
        root.addWidget(header)
        root.addWidget(_Divider(False))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.nav = HelpNav(self)
        self.nav.setFixedWidth(NAV_WIDTH)
        body.addWidget(self.nav)
        body.addWidget(_Divider(True))
        self.view = HelpBrowser(self)
        body.addWidget(self.view, 1)
        root.addLayout(body, 1)

        self._search_timer = QTimer(self, singleShot=True, interval=150)
        self._search_timer.timeout.connect(self._run_search)
        self._resize_timer = QTimer(self, singleShot=True, interval=120)
        self._resize_timer.timeout.connect(self._rerender)
        self.search.textChanged.connect(self._search_edited)
        self.search.returnPressed.connect(self._open_first_hit)
        self.search.installEventFilter(self)
        self.nav.page_activated.connect(lambda pid: self.open(pid))
        self.view.link.connect(self.follow)
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self._focus_search)
        QShortcut(QKeySequence("Alt+Home"), self, activated=lambda: self.open(docs.HOME))
        QShortcut(QKeySequence("F1"), self, activated=lambda: self.open(docs.HOME))
        THEME.changed.connect(self._theme_changed)
        self._image_width = 0
        self._apply_style()
        self.open(docs.HOME)
        self.setFocusProxy(self.nav)            # keyboard focus starts in the contents, not on Home
        carbonize_popups(self)                  # search field and article: the shared Carbon context menu

    def showEvent(self, e):
        super().showEvent(e)
        self.nav.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------ styling
    def _apply_style(self):
        k = THEME.tokens
        self.setStyleSheet(
            f"#HelpWindow, #HelpHeader {{ background: {k['background']}; }}"
            f"#HelpNav {{ background: {k['background']}; border: none; outline: none; }}"
            f"#HelpBrowser {{ background: {k['background']}; border: none; }}")
        self.view.document().setDefaultStyleSheet(stylesheet())

    def _theme_changed(self, *_):
        self._apply_style()
        self._rerender()

    # ------------------------------------------------------------------ navigation
    def open(self, page: str, anchor: str = "", highlight: list[str] | None = None) -> None:
        """Show ``page`` (an id, alias or help:// URL) scrolled to ``anchor``; unknown targets show Home."""
        route = docs.resolve(page) or docs.Route(docs.HOME)
        self.page = route.page
        self.anchor = anchor or route.anchor
        self._highlight = list(highlight or [])
        if self.search.text() and highlight is None:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.query = ""
        self.nav.select_page(self.page)
        self._render_page()

    def follow(self, href: str) -> None:
        if href.startswith(("http://", "https://", "mailto:")):
            QDesktopServices.openUrl(QUrl(href))
            return
        if href.startswith("#"):
            self.anchor = href[1:]
            self._scroll_to_anchor()
            return
        route = docs.resolve(href)
        if route is None:
            return
        highlight = self._terms() if self.query else None
        if highlight is not None:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.query = ""
        self.open(route.page, route.anchor, highlight)

    def _content_width(self) -> int:
        return max(200, self.view.viewport().width() - 2 * CONTENT_MARGIN)

    def _render_page(self):
        self._image_width = self.view.image_width = min(MAX_IMAGE_WIDTH, self._content_width())
        self._set_html(docs.article_html(self.page, self._image_width))
        QTimer.singleShot(0, self._scroll_to_anchor)
        self._apply_highlight()

    def _set_html(self, html_text: str):
        doc = self.view.document()
        doc.setDefaultStyleSheet(stylesheet())
        doc.setDocumentMargin(0)
        self.view.setHtml(html_text)
        fmt = doc.rootFrame().frameFormat()
        fmt.setLeftMargin(CONTENT_MARGIN)
        fmt.setRightMargin(CONTENT_MARGIN)
        fmt.setTopMargin(24)
        fmt.setBottomMargin(24)
        doc.rootFrame().setFrameFormat(fmt)

    def _scroll_to_anchor(self):
        if self.anchor:
            self.view.scrollToAnchor(self.anchor)
        else:
            self.view.verticalScrollBar().setValue(0)

    def _rerender(self):
        bar = self.view.verticalScrollBar()
        frac = bar.value() / bar.maximum() if bar.maximum() else 0.0
        if self.query:
            self._run_search()
            return
        anchor, self.anchor = self.anchor, ""
        self._image_width = self.view.image_width = min(MAX_IMAGE_WIDTH, self._content_width())
        self._set_html(docs.article_html(self.page, self._image_width))
        self._apply_highlight()
        self.anchor = anchor
        QTimer.singleShot(0, lambda: bar.setValue(round(frac * bar.maximum())))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._image_width and min(MAX_IMAGE_WIDTH, self._content_width()) != self._image_width:
            self._resize_timer.start()

    # ------------------------------------------------------------------ search
    def _focus_search(self):
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def _terms(self) -> list[str]:
        idx = docs.index()
        return [a for alts in idx._alternatives(self.query) for a in alts if len(a) > 1]

    def _search_edited(self, text: str):
        if text.strip():
            self._search_timer.start()          # debounce typing
        else:
            self._search_timer.stop()           # cleared: back to the page at once
            self._run_search()

    def _run_search(self):
        q = self.search.text().strip()
        self.query = q
        if not q:
            self._render_page()
            return
        hits = docs.index().search(q)
        self.hits = hits
        self._set_html(docs.search_html(q, hits))
        self.view.verticalScrollBar().setValue(0)

    def _open_first_hit(self):
        self._search_timer.stop()
        self._run_search()
        if self.query and getattr(self, "hits", None):
            h = self.hits[0]
            self.follow(f"help://{h.page}" + (f"#{h.anchor}" if h.anchor else ""))

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.Type.KeyPress and ev.key() == Qt.Key.Key_Escape \
                and self.search.text():
            self.search.clear()
            return True
        return super().eventFilter(obj, ev)

    def _apply_highlight(self):
        """Mark the search terms that led to this page (extra selections; cleared on the next navigation)."""
        sels = []
        if self._highlight:
            doc = self.view.document()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(t("highlight")))
            for term in self._highlight:
                cur = QTextCursor(doc)
                while True:
                    cur = doc.find(term, cur)
                    if cur.isNull():
                        break
                    sel = QTextEdit.ExtraSelection()
                    sel.cursor = cur
                    sel.format = fmt
                    sels.append(sel)
                    if len(sels) > 400:
                        break
        self.view.setExtraSelections(sels)

    # ------------------------------------------------------------------ facts for tests
    def article_text(self) -> str:
        return self.view.toPlainText()
