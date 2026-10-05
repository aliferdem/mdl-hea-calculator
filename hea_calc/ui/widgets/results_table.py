"""Results data table (Figma 278:20578): toolbar, sortable header, prediction tags in cells, pagination.

Only the current page is exposed to Qt, so thousands of rows stay responsive.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu,
                               QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget)

from ...core import composition as C
from ...core.results import (COLUMN_BY_KEY, DEFAULT_COLUMNS, ResultRow, apply_filters, format_cell, full_precision,
                             table_tsv)
from .. import icons
from ..theme import BODY_COMPACT_01, HEADING_COMPACT_01, THEME, font, t
from .common import (Divider, IconButton, MenuButton, button, illustration, paint_tag, set_prop)

PAGE_SIZES = (10, 20, 50, 100)
MODEL_COL_WIDTH = 79


class ResultsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[ResultRow] = []      # all rows (insertion order)
        self.view_rows: list[ResultRow] = []  # filtered + sorted
        self.keys: list[str] = list(DEFAULT_COLUMNS)
        self.filters: list = []
        self.page = 0
        self.page_size = 100
        self.sort_key: str | None = None
        self.sort_desc = False

    # ------------------------------------------------------------------ data management
    def set_rows(self, rows: list[ResultRow]):
        self.beginResetModel()
        self.rows = list(rows)
        self._rebuild()
        self.endResetModel()

    def append_rows(self, rows: list[ResultRow]):
        self.beginResetModel()
        self.rows.extend(rows)
        self._rebuild()
        self.endResetModel()

    def remove_rows(self, rows: list[ResultRow]):
        ids = {id(r) for r in rows}
        self.beginResetModel()
        self.rows = [r for r in self.rows if id(r) not in ids]
        self._rebuild()
        self.endResetModel()

    def set_keys(self, keys: list[str]):
        self.beginResetModel()
        self.keys = list(keys)
        self.endResetModel()

    def set_filters(self, filters: list):
        self.beginResetModel()
        self.filters = list(filters)
        self.page = 0
        self._rebuild()
        self.endResetModel()

    def set_page(self, page: int):
        page = max(0, min(page, self.page_count() - 1))
        if page != self.page:
            self.beginResetModel()
            self.page = page
            self.endResetModel()

    def set_page_size(self, n: int):
        first = self.page * self.page_size
        self.beginResetModel()
        self.page_size = n
        self.page = first // n
        self.endResetModel()

    def sort_by(self, key: str):
        if self.sort_key == key:
            if self.sort_desc:
                self.sort_key, self.sort_desc = None, False  # third click: original order (Carbon)
            else:
                self.sort_desc = True
        else:
            self.sort_key, self.sort_desc = key, False
        self.beginResetModel()
        self._rebuild()
        self.endResetModel()

    def _rebuild(self):
        rows = apply_filters(self.rows, self.filters)
        if self.sort_key:
            key = self.sort_key

            def k(r: ResultRow):
                v = r.raw(key)
                if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                    return (0, float(v), "")
                if v is None:
                    return (2, 0.0, "")
                return (1, 0.0, str(v))
            rows = sorted(rows, key=k, reverse=self.sort_desc)
            if self.sort_desc:  # keep missing values last
                rows = [r for r in rows if r.raw(key) is not None] + [r for r in rows if r.raw(key) is None]
        self.view_rows = rows
        self.page = max(0, min(self.page, self.page_count() - 1))

    def page_count(self) -> int:
        return max(1, math.ceil(len(self.view_rows) / self.page_size))

    def page_rows(self) -> list[ResultRow]:
        a = self.page * self.page_size
        return self.view_rows[a:a + self.page_size]

    def row_at(self, r: int) -> ResultRow | None:
        rows = self.page_rows()
        return rows[r] if 0 <= r < len(rows) else None

    # ------------------------------------------------------------------ Qt model
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.page_rows())

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.keys)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.row_at(index.row())
        key = self.keys[index.column()]
        col = COLUMN_BY_KEY[key]
        if role == Qt.ItemDataRole.DisplayRole:
            return format_cell(row, key)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col.kind == "model":
                o = row.result.models.get(key)
                if o is None:
                    return row.result.error or "N/A"
                tip = f"{col.tooltip}\nResult: {o.label}"
                if o.reason:
                    tip += f"\n{o.reason}"
                if o.caution:
                    tip += f"\n⚠ {o.caution}"
                return tip
            if key == "name":
                return C.composition_text(row.result.composition) + (f"\n{row.result.error}" if row.result.error else "")
            return f"{col.header}: {full_precision(row, key)}"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col.kind == "model":
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.UserRole:
            return key
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        key = self.keys[section]
        col = COLUMN_BY_KEY[key]
        if role == Qt.ItemDataRole.DisplayRole:
            return col.html
        if role == Qt.ItemDataRole.ToolTipRole:
            return (col.tooltip or col.header) + (f" [{col.unit}]" if col.unit else "")
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable  # read-only cells


class Delegate(QStyledItemDelegate):
    """Paints rows per Carbon data table: 32 px, hover/selected layers, tags, subscript alloy names."""

    def __init__(self, view: "ResultsView"):
        super().__init__(view)
        self.view = view

    def paint(self, p: QPainter, opt: QStyleOptionViewItem, index: QModelIndex):
        p.save()
        r = opt.rect
        row = index.row()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        if selected:
            p.fillRect(r, QColor(t("row-selected")))
        elif row == self.view.hover_row:
            p.fillRect(r, QColor(t("row-hover")))
        p.setPen(QPen(QColor(t("row-border")), 1))
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())
        key = index.data(Qt.ItemDataRole.UserRole)
        col = COLUMN_BY_KEY[key]
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if col.kind == "model":
            paint_tag(p, QRectF(r.x() + 10, r.y(), 0, r.height()), text, align_left=True)
        elif key == "name":
            self._paint_name(p, r, text, selected)
        else:
            p.setFont(font(BODY_COMPACT_01))
            p.setPen(QColor(t("text-primary" if selected else "text-secondary")))
            tr = r.adjusted(16, 0, -8, 0)
            p.drawText(tr, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetrics(p.font()).elidedText(text, Qt.TextElideMode.ElideRight, tr.width()))
        if opt.state & QStyle.StateFlag.State_HasFocus and self.view.hasFocus():
            p.setPen(QPen(QColor(t("focus")), 2))
            p.drawRect(QRectF(r).adjusted(1, 1, -1, -1))
        p.restore()

    def _paint_name(self, p: QPainter, r: QRect, name: str, selected: bool):
        base = font(BODY_COMPACT_01)
        sub = font(BODY_COMPACT_01)
        sub.setPixelSize(10)
        fm, fs = QFontMetrics(base), QFontMetrics(sub)
        x = r.left() + 16
        y_base = r.center().y() + fm.ascent() / 2 - 2
        p.setPen(QColor(t("text-primary" if selected else "text-secondary")))
        for text, is_sub in C.name_segments(name):
            f, m = (sub, fs) if is_sub else (base, fm)
            w = m.horizontalAdvance(text)
            if x + w > r.right() - 8:
                p.setFont(base)
                p.drawText(QPoint(int(x), int(y_base)), "…")
                break
            p.setFont(f)
            p.drawText(QPoint(int(x), int(y_base + (4 if is_sub else 0))), text)
            x += w

    def sizeHint(self, opt, index):
        return QSize(80, 32)


class Header(QHeaderView):
    """Carbon table header: 32 px, semibold, sort arrows, rich text (subscripts)."""

    def __init__(self, model: ResultsModel, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.m = model
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setFixedHeight(32)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._hover = -1
        self.setMouseTracking(True)

    def mouseMoveEvent(self, e):
        self._hover = self.logicalIndexAt(e.position().toPoint())
        self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = -1
        self.viewport().update()
        super().leaveEvent(e)

    def paintSection(self, p: QPainter, rect: QRect, logical: int):
        if not rect.isValid():
            return
        p.save()
        key = self.m.keys[logical]
        col = COLUMN_BY_KEY[key]
        p.fillRect(rect, QColor(t("layer-hover-02" if logical == self._hover else "header-row")))
        # 1 px rule under the header, in the same colour as the row rules (19_data_table_populated:
        # header #393939, then a 1 px #525252 line, then the first row).
        p.setPen(QPen(QColor(t("row-border")), 1))
        p.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        f = font(HEADING_COMPACT_01)
        p.setPen(QColor(t("text-primary")))
        doc_x = rect.left() + 16
        # minimal rich-text: render subscripts/superscripts
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setDefaultFont(f)
        doc.setDocumentMargin(0)
        doc.setDefaultStyleSheet(f"body {{ color: {t('text-primary')}; }}")
        doc.setHtml(f"<body>{col.html}</body>")
        w = doc.idealWidth()
        y = rect.top() + (rect.height() - doc.size().height()) / 2
        p.translate(doc_x, y)
        doc.drawContents(p)
        p.translate(-doc_x, -y)
        if self.m.sort_key == key:
            name = "arrow_down" if self.m.sort_desc else "arrow_up"
            ax = min(rect.left() + 16 + w + 8, rect.right() - 18)
            icons.paint(p, name, QRectF(ax, rect.center().y() - 8, 16, 16), "icon-primary")
        p.restore()

    def sizeHint(self):
        s = super().sizeHint()
        return QSize(s.width(), 32)


class ResultsView(QTableView):
    row_activated = Signal(object)   # double click → details dialog
    row_selected = Signal(object)

    def __init__(self, model: ResultsModel, parent=None):
        super().__init__(parent)
        self.m = model
        self.setModel(model)
        self.hover_row = -1
        self.header = Header(model, self)
        self.setHorizontalHeader(self.header)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(32)
        self.setShowGrid(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setItemDelegate(Delegate(self))
        self.setMouseTracking(True)
        self.setWordWrap(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.header.sectionClicked.connect(lambda i: self.m.sort_by(self.m.keys[i]))
        self.doubleClicked.connect(lambda idx: self.row_activated.emit(self.m.row_at(idx.row())))
        self.clicked.connect(self._cell_clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        model.modelReset.connect(self.apply_widths)
        self.apply_widths()

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        rows = self.selected_rows()
        self.row_selected.emit(rows[-1] if rows else None)

    cell_info = Signal(str)

    def _cell_clicked(self, idx):
        row = self.m.row_at(idx.row())
        if row is None:
            return
        key = self.m.keys[idx.column()]
        col = COLUMN_BY_KEY[key]
        if col.kind == "model":
            o = row.result.models.get(key)
            text = f"{row.name} · {key}: {o.label}" + (f" — {o.reason}" if o and o.reason else "") if o else ""
        else:
            text = f"{row.name} · {col.header} = {full_precision(row, key)}"
        self.cell_info.emit(text)

    def selected_rows(self) -> list[ResultRow]:
        out = []
        for idx in self.selectionModel().selectedRows():
            r = self.m.row_at(idx.row())
            if r is not None:
                out.append(r)
        return out

    def keyPressEvent(self, e):
        from PySide6.QtGui import QKeySequence
        if e.matches(QKeySequence.StandardKey.Copy):
            rows = self.selected_rows()
            if rows:
                QGuiApplication.clipboard().setText(table_tsv(rows, self.m.keys))
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            rows = self.selected_rows()
            if rows:
                self.row_activated.emit(rows[-1])
            return
        super().keyPressEvent(e)

    def mouseMoveEvent(self, e):
        r = self.rowAt(e.position().toPoint().y())
        if r != self.hover_row:
            self.hover_row = r
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover_row = -1
        self.viewport().update()
        super().leaveEvent(e)

    # Figma widths at 1880 px: Alloy 180, rho 133, other descriptors 157, models 79.
    BASE_WIDTH = {"name": 180, "density": 133}
    MIN_WIDTH = {"name": 140}

    def apply_widths(self):
        h = self.header
        h.setMinimumSectionSize(48)
        for i in range(len(self.m.keys)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
        self._distribute()

    def _distribute(self):
        keys = self.m.keys
        if not keys:
            return
        avail = self.viewport().width()
        fixed = sum(MODEL_COL_WIDTH for k in keys if COLUMN_BY_KEY[k].kind == "model")
        flex = [k for k in keys if COLUMN_BY_KEY[k].kind != "model"]
        weights = {k: self.BASE_WIDTH.get(k, 157) for k in flex}
        total_w = sum(weights.values())
        room = max(avail - fixed, 0)
        scale = room / total_w if total_w else 1
        used = 0
        for i, k in enumerate(keys):
            if COLUMN_BY_KEY[k].kind == "model":
                w = MODEL_COL_WIDTH
            else:
                w = max(int(weights[k] * scale), self.MIN_WIDTH.get(k, 72))
                if k == flex[-1]:
                    w = max(room - used, self.MIN_WIDTH.get(k, 72))
                used += w
            self.header.resizeSection(i, w)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._distribute()

    def _context_menu(self, pos):
        idx = self.indexAt(pos)
        if not idx.isValid():
            return
        row = self.m.row_at(idx.row())
        key = self.m.keys[idx.column()]
        menu = QMenu(self)
        a1 = menu.addAction("Copy value (full precision)")
        a2 = menu.addAction("Copy selected rows")
        a3 = menu.addAction("Open alloy details…")
        menu.addSeparator()
        a4 = menu.addAction("Remove row")
        act = menu.exec(self.viewport().mapToGlobal(pos))
        if act is a1:
            QGuiApplication.clipboard().setText(full_precision(row, key))
        elif act is a2:
            QGuiApplication.clipboard().setText(table_tsv(self.selected_rows() or [row], self.m.keys))
        elif act is a3:
            self.row_activated.emit(row)
        elif act is a4:
            self.m.remove_rows([row])


class PaginationBar(QFrame):
    """Carbon pagination (table bar): items per page, range text, page select, prev/next."""

    def __init__(self, model: ResultsModel, parent=None):
        super().__init__(parent)
        self.setObjectName("PaginationBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.m = model
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(QLabel("Items per page:"))
        self.size_box = QComboBox()
        for n in PAGE_SIZES:
            self.size_box.addItem(str(n), n)
        self.size_box.setCurrentIndex(PAGE_SIZES.index(model.page_size))
        self.size_box.setFixedWidth(64)
        self.size_box.setAccessibleName("Items per page")
        lay.addWidget(self.size_box)
        lay.addWidget(self._vdiv())
        self.range_lbl = QLabel("")
        self.range_lbl.setObjectName("Secondary")
        self.range_lbl.setContentsMargins(16, 0, 0, 0)
        lay.addWidget(self.range_lbl, 1)
        lay.addWidget(self._vdiv())
        lay.addSpacing(8)
        self.page_box = QComboBox()
        self.page_box.setMinimumWidth(56)
        self.page_box.setAccessibleName("Current page")
        lay.addWidget(self.page_box)
        self.of_lbl = QLabel("")
        self.of_lbl.setContentsMargins(4, 0, 16, 0)
        lay.addWidget(self.of_lbl)
        lay.addWidget(self._vdiv())
        self.prev_btn = IconButton("caret_left", "Previous page")
        self.next_btn = IconButton("caret_right", "Next page")
        for b in (self.prev_btn, self.next_btn):
            set_prop(b, "square", "40")
        lay.addWidget(self.prev_btn)
        lay.addWidget(self._vdiv())
        lay.addWidget(self.next_btn)
        self.size_box.currentIndexChanged.connect(lambda i: self.m.set_page_size(PAGE_SIZES[i]))
        self.page_box.activated.connect(lambda i: self.m.set_page(i))
        self.prev_btn.clicked.connect(lambda: self.m.set_page(self.m.page - 1))
        self.next_btn.clicked.connect(lambda: self.m.set_page(self.m.page + 1))
        self.m.modelReset.connect(self.refresh)
        self.refresh()

    def _vdiv(self):
        d = Divider(vertical=True)
        d.setFixedHeight(40)
        return d

    def refresh(self):
        n = len(self.m.view_rows)
        total = len(self.m.rows)
        a = self.m.page * self.m.page_size
        b = min(a + self.m.page_size, n)
        suffix = f" (filtered from {total})" if n != total else ""
        self.range_lbl.setText(f"{a + 1 if n else 0}–{b} of {n} item{'s' if n != 1 else ''}{suffix}")
        pc = self.m.page_count()
        if self.page_box.count() != pc:
            self.page_box.blockSignals(True)
            self.page_box.clear()
            self.page_box.addItems([str(i + 1) for i in range(pc)])
            self.page_box.blockSignals(False)
        self.page_box.setCurrentIndex(self.m.page)
        self.of_lbl.setText(f"of {pc} page{'s' if pc != 1 else ''}")
        self.prev_btn.setEnabled(self.m.page > 0)
        self.next_btn.setEnabled(self.m.page < pc - 1)


class TableEmptyState(QWidget):
    """Figma 289:44643 / 291:45055: empty-state illustration over the table body."""

    def __init__(self, view: QTableView):
        super().__init__(view.viewport())
        self.view = view
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title, self.body = "", ""
        THEME.changed.connect(self._theme_changed)

    def set_text(self, title: str, body: str):
        self.title, self.body = title, body
        self.setGeometry(self.view.viewport().rect())
        self.setVisible(bool(title))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Figma 289:44643 - artwork at x = 64, its exported height, title 24 px below it.
        x, y = 64, 32
        size, pm = illustration("box")
        p.drawPixmap(QRect(x, y, size.width(), size.height()), pm, QRect(pm.rect()))
        f = font(BODY_COMPACT_01)
        f.setPixelSize(20)
        p.setFont(f)
        p.setPen(QColor(t("text-primary")))
        p.drawText(QRectF(x, y + size.height() + 24, 600, 28),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.title)
        p.setFont(font(BODY_COMPACT_01))
        p.setPen(QColor(t("text-secondary")))
        p.drawText(QRectF(x, y + size.height() + 56, 600, 20),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.body)
        p.end()

    def _theme_changed(self, *_):
        self.update()


class ResultsTable(QFrame):
    """Toolbar + table + pagination."""

    delete_requested = Signal()
    filter_requested = Signal()
    columns_requested = Signal()
    copy_requested = Signal()
    export_requested = Signal(str)  # "xlsx" | "csv"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataTable")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.model = ResultsModel(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("TableToolbar")
        bar.setFixedHeight(32)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 0, 0)
        bl.setSpacing(0)
        self.status = QLabel("")
        self.status.setObjectName("Secondary")
        bl.addWidget(self.status, 1)
        self.copy_btn = IconButton("copy", "Copy table (tab-separated, pastes into Excel)")
        self.delete_btn = IconButton("trash_can", "Delete selected rows (all rows if none selected)")
        self.filter_btn = IconButton("filter", "Filter results")
        self.columns_btn = IconButton("settings", "Table columns")
        for b in (self.copy_btn, self.delete_btn, self.filter_btn, self.columns_btn):
            bl.addWidget(b)
        self.export_btn = MenuButton("Export")
        self.export_btn.setProperty("kind", "secondary")
        self.export_btn.setProperty("btnsize", "sm")
        self.export_btn.setFixedWidth(123)
        menu = QMenu(self.export_btn)
        menu.addAction("Excel workbook (.xlsx)…", lambda: self.export_requested.emit("xlsx"))
        menu.addAction("CSV (.csv)…", lambda: self.export_requested.emit("csv"))
        menu.addSeparator()
        menu.addAction("Copy table to clipboard", self.copy_requested.emit)
        self.export_btn.setMenu(menu)
        bl.addWidget(self.export_btn)
        lay.addWidget(bar)
        self.view = ResultsView(self.model)
        lay.addWidget(self.view, 1)
        self.pagination = PaginationBar(self.model)
        lay.addWidget(self.pagination)
        self.empty = TableEmptyState(self.view)
        self.model.modelReset.connect(self._update_empty)
        self.view.viewport().installEventFilter(self)
        self._update_empty()
        self.copy_btn.clicked.connect(self.copy_requested.emit)
        self.delete_btn.clicked.connect(self.delete_requested.emit)
        self.filter_btn.clicked.connect(self.filter_requested.emit)
        self.columns_btn.clicked.connect(self.columns_requested.emit)
        THEME.changed.connect(self._theme_changed)

    def _theme_changed(self, *_):
        self.view.viewport().update()
        self.view.header.viewport().update()

    def _update_empty(self):
        m = self.model
        if not m.rows:
            self.empty.set_text("No results yet", "Click Calculate to add alloys to this table.")
        elif not m.view_rows:
            self.empty.set_text("No matching results", "Change or clear the filters in the toolbar.")
        else:
            self.empty.set_text("", "")

    def eventFilter(self, obj, ev):
        if obj is self.view.viewport() and ev.type() == QEvent.Type.Resize:
            self.empty.setGeometry(self.view.viewport().rect())
        return False

    def set_filter_active(self, active: bool):
        self.filter_btn.setProperty("active", active)
        self.filter_btn.style().unpolish(self.filter_btn)
        self.filter_btn.style().polish(self.filter_btn)
        self.filter_btn.setToolTip("Filter results (active)" if active else "Filter results")


_ = (QAction, QEvent, QFontMetrics)
