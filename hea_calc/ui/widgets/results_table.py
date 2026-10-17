"""Results data table (Figma 278:20578): toolbar, sortable header, prediction tags in cells, pagination.

Architecture (measured; see ``tools/perf_harness.py`` and ``design/implementation/performance.md``):

* the results live in the SQLite :class:`~hea_calc.core.repository.ResultRepository`; the table
  is a *view* of that dataset (:class:`~hea_calc.core.repository.ResultView`), never the dataset;
* :class:`ResultsModel` is a ``QAbstractTableModel`` that exposes **only the current page**
  (10/20/50/100 rows) fetched from the view; filtering and sorting are materialised by the
  repository over the complete dataset (synchronously when that takes < 0.1 s, otherwise in the
  background while the previous page stays on screen - ``pending``);
* cells are painted by one delegate - no item, editor or widget per cell or row;
* there is no Qt selection: ``NoSelection``, no current cell, no focus rectangle.  Rows highlight on
  hover only; a drag inside a text cell selects its *characters* (``CellTextSelection``, one
  transient overlay that paints with the delegate's own text layout) and ``Ctrl+C`` copies them;
* double-click a row → the active composition of Analysis; right-click → :class:`~.menu.CarbonMenu` with
  "Analyse composition", "Open details in new window" and copy/remove actions.  Rows are identified by
  their stable ``result_id``, never by visual position;
* no checkbox column (product decision, release reconciliation: the clean table geometry was restored; the
  briefly added "Checked results" column and its set were removed).  Plot selections reach the table only as
  the explicit id filter of "Show in results table" (``core/analysis/idsets.py``);
* pagination: items per page (shared Carbon :class:`~.dropdown.Dropdown`), range text, an editable page
  number (:class:`PageField`: integers 1…last, Enter / focus-out commit, out-of-range values corrected
  visibly, no wheel changes) and previous / next.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QPoint, QPointF, QRect, QRectF,
                            QRegularExpression, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QKeySequence, QMouseEvent, QPainter,
                           QRegularExpressionValidator)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QStyledItemDelegate, QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget)

from ...core import composition as C
from ...core.repository import ResultRecord, ResultRepository, ResultView
from ...core.results import COLUMN_BY_KEY, DEFAULT_COLUMNS, ResultRow, format_cell, full_precision, table_tsv
from .. import crisp, icons
from ..responsive import distribute
from ..theme import BODY_COMPACT_01, HAIRLINE, HEADING_COMPACT_01, THEME, font, t
from .common import Divider, IconButton, MenuButton, illustration, install_wheel_guard, paint_tag, set_prop
from .dropdown import Dropdown
from .menu import CarbonMenu
from .scroll import ThinScrollBar

PAGE_SIZES = (10, 20, 50, 100)
MODEL_COL_WIDTH = 79
ROW_HEIGHT = 32
HEADER_HEIGHT = 32
TEXT_PAD_LEFT = 16
TEXT_PAD_RIGHT = 8


# ====================================================================== row sequences (lazy, streamed)
class RowSequence(Sequence):
    """Read-only sequence over the dataset: the whole workspace in id order (``natural``) or the
    table's filtered/sorted view.  Records are fetched on access; iteration streams in chunks."""

    def __init__(self, view: ResultView, natural: bool):
        self.view = view
        self.natural = natural

    def __len__(self):
        return self.view.total() if self.natural else self.view.count()

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(len(self)))]
        rec = self.view.at(i, self.natural)
        if rec is None:
            raise IndexError(i)
        return rec

    def __iter__(self):
        return self.view.iterate(self.natural)

    def __eq__(self, other):
        return list(self) == list(other)


# ====================================================================== model
class ResultsModel(QAbstractTableModel):
    """Page model over a :class:`ResultView` (see module docstring).

    ``page_changed`` fires when the visible page's rows or the view's counts change (pagination,
    natural height, empty state); ``columns_changed`` when the column set changes;
    ``state_changed`` when a background sort/filter starts or finishes.
    """

    page_changed = Signal()
    columns_changed = Signal()
    state_changed = Signal()
    _task_done = Signal(object)          # builder thread -> GUI thread (queued)

    def __init__(self, parent=None, engine=None, repo: ResultRepository | None = None):
        super().__init__(parent)
        self._own_repo = repo is None
        self.repo = repo if repo is not None else ResultRepository(engine)
        self.repo.set_notify(self._task_done.emit)
        self._task_done.connect(self._on_task)
        self.view = ResultView(self.repo)
        self.keys: list[str] = list(DEFAULT_COLUMNS)
        self.page = 0
        self.page_size = 100
        self._page: list[ResultRecord] = []
        self._cells: dict[int, list[str]] = {}
        self.last_error: str | None = None
        self._user_request = False           # the pending build was asked for by the user (sort/filter)

    def close(self) -> None:
        """Release the repository if this model created it."""
        self.repo.set_notify(None)
        if self._own_repo:
            self.repo.close()

    # ------------------------------------------------------------------ state
    @property
    def filters(self) -> list:
        return self.view.filters

    @property
    def sort_key(self) -> str | None:
        return self.view.sort_key

    @property
    def sort_desc(self) -> bool:
        return self.view.sort_desc

    @property
    def pending(self) -> bool:
        """A sort/filter the user asked for is being materialised in the background (large data)."""
        return self.view.pending is not None and self._user_request

    def view_count(self) -> int:
        return self.view.count()

    def total_count(self) -> int:
        return self.view.total()

    @property
    def rows(self) -> RowSequence:
        """Every result of the table's dataset (id order) - streamed, never materialised."""
        return RowSequence(self.view, True)

    @property
    def view_rows(self) -> RowSequence:
        """Filtered + sorted rows (the table's order) - streamed."""
        return RowSequence(self.view, False)

    def position_of(self, rid: int) -> int:
        return self.view.position_of(rid)

    def page_count(self) -> int:
        return max(1, math.ceil(self.view_count() / self.page_size))

    def page_rows(self) -> list[ResultRecord]:
        return list(self._page)

    def row_at(self, r: int) -> ResultRecord | None:
        return self._page[r] if 0 <= r < len(self._page) else None

    def id_at(self, r: int) -> int | None:
        return self._page[r].id if 0 <= r < len(self._page) else None

    # ------------------------------------------------------------------ data management
    def append_rows(self, rows: list[ResultRow], options: dict | None = None, mode: str = "single",
                    source: dict | None = None) -> range:
        """Store already-calculated rows as one run (single compositions, tools) - synchronous."""
        rows = list(rows)
        elements: list[str] = []
        for r in rows:
            for el in r.input_amounts:
                if el not in elements:
                    elements.append(el)
        run = self.repo.create_run(mode, settings=dict(options or {}), source=source or {}, elements=elements,
                                   expected=len(rows))
        try:
            rng = self.repo.append_results(run, rows)
        finally:
            self.repo.finalize_run(run, "complete")
        self.refresh_committed()
        return rng

    def refresh_committed(self, resort: bool = True) -> bool:
        """Pick up rows the writer has committed (cheap: no query unless the page changes).  A sorted
        view built before them is re-sorted (``resort``; a running job re-sorts with back-off instead)."""
        if self.view.refresh():
            if resort and self.view.wants_resort(running=False):
                self.resort()
            else:
                self._refresh_page()
            return True
        return False

    def remove_rows(self, rows):
        self.view.remove([r for r in rows if isinstance(r, ResultRecord)])
        ids = [int(r) for r in rows if isinstance(r, int)]
        if ids:
            self.view.remove_ids(ids)
        self._refresh_page(force=True)

    def clear(self):
        """Delete every result of the table (in the background); filters and sort stay."""
        self.view.clear()
        self.page = 0
        self._refresh_page(force=True)
        self.state_changed.emit()

    def hide_all(self) -> tuple[int, int]:
        old = self.view.hide_all()
        self.page = 0
        self._refresh_page(force=True)
        self.state_changed.emit()
        return old

    def set_keys(self, keys: list[str]):
        self.beginResetModel()
        self.keys = list(keys)
        self._cells.clear()
        self.endResetModel()
        self.columns_changed.emit()
        self.page_changed.emit()

    def set_filters(self, filters: list):
        self.page = 0
        self._user_request = True
        self._apply(self.view.request(filters=list(filters)))

    def set_page(self, page: int):
        page = max(0, min(page, self.page_count() - 1))
        if page != self.page:
            self.page = page
            self._refresh_page()

    def set_page_size(self, n: int):
        first = self.page * self.page_size
        self.page_size = n
        self.page = first // n
        self._refresh_page()

    def sort_by(self, key: str):
        if self.sort_key == key:
            if self.sort_desc:
                key, desc = None, False                  # third click: original order (Carbon)
            else:
                desc = True
        else:
            desc = False
        self._user_request = True
        self._apply(self.view.request(sort=(key, desc)))
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, max(0, len(self.keys) - 1))

    def resort(self, wait: float | None = None):
        """Re-materialise the current sort/filter (new rows while a sort is active)."""
        if self.view.pending is None:
            self._user_request = False
        self._apply(self.view.rebuild() if wait is None else self.view.rebuild(wait))

    def wait(self, timeout: float = 60.0) -> None:
        """Block until a background sort/filter is applied (tools and tests)."""
        if self.view.pending is not None or self.view._extending is not None:
            self.view.wait(timeout)
            self._refresh_page(force=True)
            self.state_changed.emit()

    def _apply(self, applied: bool):
        self._refresh_page(force=True)
        self.state_changed.emit()

    def _on_task(self, task):
        if task.kind == "exec":            # id tables of "Show in results table" (idsets.py)
            return
        try:
            changed = self.view.apply_task(task)
        except Exception as exc:                     # noqa: BLE001 - a failed build: keep the old view
            self.last_error = str(exc)
            changed = True
        if changed:
            self._refresh_page(force=True)
            self.state_changed.emit()
            if not self.view.streaming and self.view.needs_final_rebuild():
                self.resort()                       # built from fewer rows than are now committed

    def finish_streaming(self) -> None:
        """Rows stopped arriving (a calculation ended): make the view complete."""
        self.view.streaming = False
        self.refresh_committed(resort=False)
        if self.view.needs_final_rebuild():
            self.resort()

    def _refresh_page(self, force: bool = False):
        self.page = max(0, min(self.page, self.page_count() - 1))
        recs = self.view.page(self.page * self.page_size, self.page_size)
        ids = [r.id for r in recs]
        old = [r.id for r in self._page]
        if ids != old or force:
            if len(ids) == len(old) and ids:
                self._page = recs
                self._cells.clear()
                self.dataChanged.emit(self.index(0, 0), self.index(len(ids) - 1, max(0, len(self.keys) - 1)))
            elif len(ids) > len(old) and ids[:len(old)] == old:
                first = len(old)
                self.beginInsertRows(QModelIndex(), first, len(ids) - 1)
                self._page = recs
                self.endInsertRows()
            else:
                self.beginResetModel()
                self._page = recs
                self._cells.clear()
                self.endResetModel()
        else:
            self._page = recs                            # same rows: fresh records (positions)
        self.page_changed.emit()

    # ------------------------------------------------------------------ Qt model
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._page)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.keys)

    def cell_text(self, r: int, c: int) -> str:
        cells = self._cells.get(r)
        if cells is None:
            row = self._page[r]
            cells = self._cells[r] = [format_cell(row, k) for k in self.keys]
        return cells[c]

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        # No ToolTipRole for body cells: full information belongs in Calculation details.
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.cell_text(index.row(), index.column())
        if role == Qt.ItemDataRole.UserRole:
            return self.keys[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if COLUMN_BY_KEY[self.keys[index.column()]].kind == "model":
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(self.keys):
            return None
        col = COLUMN_BY_KEY[self.keys[section]]
        if role == Qt.ItemDataRole.DisplayRole:
            return col.html
        if role == Qt.ItemDataRole.ToolTipRole:
            # Carbon tooltip on header hover/focus: symbol with unit ("ΔHmix (kJ/mol)"), short meaning
            return f"{col.header}\n{col.tooltip}" if col.tooltip else col.header
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled            # never selectable, never editable


_ = time


# ====================================================================== cell text layout
@dataclass
class Run:
    text: str
    font: QFont
    x: float
    baseline: float
    first: int            # index of the run's first character in the cell's plain text


def _fonts() -> tuple[QFont, QFont]:
    base = font(BODY_COMPACT_01)
    sub = font(BODY_COMPACT_01)
    sub.setPixelSize(10)
    return base, sub


def cell_runs(key: str, text: str, rect: QRect | QRectF) -> list[Run]:
    """The painted layout of a text cell, shared by the delegate and the selection overlay so a
    selection never moves a glyph.  Alloy names use subscript runs; other cells one elided run."""
    base, sub = _fonts()
    fm = QFontMetricsF(base)
    x0 = rect.left() + TEXT_PAD_LEFT
    right = rect.right() + 1 - TEXT_PAD_RIGHT
    baseline = rect.top() + (rect.height() - fm.height()) / 2 + fm.ascent()
    if key != "name":
        shown = fm.elidedText(text, Qt.TextElideMode.ElideRight, right - x0)
        return [Run(shown, base, x0, baseline, 0)]
    runs, x, pos = [], x0, 0
    y_name = rect.top() + rect.height() / 2 + QFontMetricsF(base).ascent() / 2 - 2
    fs = QFontMetricsF(sub)
    for seg, is_sub in C.name_segments(text):
        f, m = (sub, fs) if is_sub else (base, fm)
        w = m.horizontalAdvance(seg)
        if x + w > right:
            runs.append(Run("…", base, x, y_name, pos))
            break
        runs.append(Run(seg, f, x, y_name + (4 if is_sub else 0), pos))
        x += w
        pos += len(seg)
    return runs


def paint_runs(p: QPainter, runs: list[Run], color: str) -> None:
    p.setPen(QColor(color))
    for r in runs:
        p.setFont(r.font)
        p.drawText(QPointF(r.x, r.baseline), r.text)


class Delegate(QStyledItemDelegate):
    """Paints rows per Carbon data table: 32 px, hover layer across the full row, tags, subscripts."""

    def __init__(self, view: "ResultsView"):
        super().__init__(view)
        self.view = view

    def paint(self, p: QPainter, opt: QStyleOptionViewItem, index: QModelIndex):
        p.save()
        r = opt.rect
        row = index.row()
        if row == self.view.hover_row:
            crisp.fill_rect(p, r, t("row-hover"))
        if row == self.view.flash_row and self.view.flash_level > 0:
            # double-click acknowledgement (brief §38): a Carbon active fill that fades out - feedback, not state
            c = QColor(t("layer-active-01"))
            c.setAlphaF(self.view.flash_level)
            p.fillRect(r, c)
        # row rule in device pixels: a 1 px QPen line came out 1 or 2 px tall at DPR 1.25
        crisp.hline_bottom(p, r, t("row-border"), HAIRLINE)
        key = self.view.m.keys[index.column()]
        text = self.view.m.cell_text(row, index.column())
        if COLUMN_BY_KEY[key].kind == "model":
            paint_tag(p, QRectF(r.x() + 10, r.y(), 0, r.height()), text, align_left=True)
        elif self.view.selection_cell() != (row, index.column()):
            paint_runs(p, cell_runs(key, text, r), t("text-secondary"))
        p.restore()

    def sizeHint(self, opt, index):
        return QSize(80, ROW_HEIGHT)


# ====================================================================== text selection overlay
class CellTextSelection(QWidget):
    """Web-like character selection inside one cell (no Qt item selection).

    One instance per table, shown over a single cell only while it holds a selection.  It paints
    the cell text with the delegate's own layout (``cell_runs``), adds the Carbon ``$highlight``
    behind the selected characters, and copies them with ``Ctrl+C``.  It has no frame, background
    or editor: inactive, the cell is the delegate's paint again.
    """

    def __init__(self, view: "ResultsView"):
        super().__init__(view.viewport())
        self.view = view
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)   # the row menu handles it
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAccessibleName("Selected cell text")
        self.cell: tuple[int, int] | None = None
        self.key = ""
        self.text = ""
        self.anchor = self.cursor_pos = 0
        self.hide()

    # -------------------------------------------------------------- state
    def begin(self, row: int, col: int, key: str, text: str, rect: QRect, press: QPoint):
        self.cell = (row, col)
        self.key, self.text = key, text
        self.setGeometry(rect)
        self.anchor = self.cursor_pos = self.hit(press - rect.topLeft())
        self.show()
        self.raise_()
        self.update()

    def extend_to(self, pos_in_view: QPoint):
        self.cursor_pos = self.hit(pos_in_view - self.pos())
        self.update()

    def end(self):
        if self.cell is None:
            return
        self.cell = None
        self.anchor = self.cursor_pos = 0
        self.hide()
        self.view.viewport().update()

    def selected_text(self) -> str:
        a, b = sorted((self.anchor, self.cursor_pos))
        return self.plain()[a:b]

    def clipboard_text(self) -> str:
        """The selection as pasted: the typographic minus becomes ASCII '-' so spreadsheets parse
        numbers (as the table's own copy does)."""
        return self.selected_text().replace("−", "-")

    def plain(self) -> str:
        return "".join(r.text for r in self._runs())

    def _runs(self) -> list[Run]:
        return cell_runs(self.key, self.text, QRect(0, 0, self.width(), self.height()))

    def hit(self, p: QPoint) -> int:
        """Character boundary nearest to ``p`` (local coordinates)."""
        best, best_d = 0, float("inf")
        for r in self._runs():
            fm = QFontMetricsF(r.font)
            for k in range(len(r.text) + 1):
                x = r.x + fm.horizontalAdvance(r.text[:k])
                d = abs(x - p.x())
                if d < best_d:
                    best, best_d = r.first + k, d
        return best

    # -------------------------------------------------------------- painting / input
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        a, b = sorted((self.anchor, self.cursor_pos))
        runs = self._runs()
        if b > a:
            for r in runs:
                lo, hi = max(a, r.first), min(b, r.first + len(r.text))
                if hi <= lo:
                    continue
                fm = QFontMetricsF(r.font)
                x1 = r.x + fm.horizontalAdvance(r.text[:lo - r.first])
                x2 = r.x + fm.horizontalAdvance(r.text[:hi - r.first])
                p.fillRect(QRectF(x1, 7, x2 - x1, self.height() - 14), QColor(t("highlight")))
        paint_runs(p, runs, t("text-secondary"))
        p.end()

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Copy):
            if self.selected_text():
                QGuiApplication.clipboard().setText(self.clipboard_text())
            return
        if e.matches(QKeySequence.StandardKey.SelectAll):
            self.anchor, self.cursor_pos = 0, len(self.plain())
            self.update()
            return
        if e.key() == Qt.Key.Key_Escape:
            self.end()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        # a press inside the active selection starts a new one (or is a plain click) - the view decides
        self.view.mousePressEvent(self._to_view(e))

    def mouseMoveEvent(self, e):
        self.view.mouseMoveEvent(self._to_view(e))

    def mouseReleaseEvent(self, e):
        self.view.mouseReleaseEvent(self._to_view(e))

    def mouseDoubleClickEvent(self, e):
        self.view.mouseDoubleClickEvent(self._to_view(e))

    def _to_view(self, e) -> QMouseEvent:
        pos = QPointF(self.mapTo(self.view.viewport(), e.position().toPoint()))
        return QMouseEvent(e.type(), pos, e.globalPosition(), e.button(), e.buttons(), e.modifiers())

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        if e.reason() != Qt.FocusReason.PopupFocusReason:     # keep it while the row menu is open
            self.end()


# ====================================================================== header
class Header(QHeaderView):
    """Carbon table header: 32 px, semibold, sort arrows, rich text (subscripts)."""

    def __init__(self, model: ResultsModel, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.m = model
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setFixedHeight(HEADER_HEIGHT)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._hover = -1
        self.setMouseTracking(True)
        self._docs: dict[tuple[str, str, str], object] = {}

    def mouseMoveEvent(self, e):
        h = self.logicalIndexAt(e.position().toPoint())
        if h != self._hover:
            self._hover = h
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = -1
        self.viewport().update()
        super().leaveEvent(e)

    def _doc(self, html: str):
        from PySide6.QtGui import QTextDocument
        key = (html, THEME.name, t("text-primary"))
        doc = self._docs.get(key)
        if doc is None:
            doc = QTextDocument()
            doc.setDefaultFont(font(HEADING_COMPACT_01))
            doc.setDocumentMargin(0)
            doc.setDefaultStyleSheet(f"body {{ color: {t('text-primary')}; }}")
            doc.setHtml(f"<body>{html}</body>")
            self._docs[key] = doc
        return doc

    def paintSection(self, p: QPainter, rect: QRect, logical: int):
        if not rect.isValid() or logical >= len(self.m.keys):
            return
        p.save()
        key = self.m.keys[logical]
        col = COLUMN_BY_KEY[key]
        crisp.fill_rect(p, rect, t("layer-hover-02" if logical == self._hover else "header-row"))
        # 1 px rule under the header, in the same colour as the row rules (19_data_table_populated:
        # header #393939, then a 1 px #525252 line, then the first row).
        crisp.hline_bottom(p, rect, t("row-border"), HAIRLINE)
        doc = self._doc(col.html)
        doc_x = rect.left() + 16
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
        return QSize(s.width(), HEADER_HEIGHT)


# ====================================================================== view
class ResultsView(QTableView):
    details_requested = Signal(object)   # double click anywhere on a row → the active composition of Analysis
    window_requested = Signal(object)    # row menu "Open details in new window"
    rows_removed = Signal()
    removed_ids = Signal(object)         # result ids removed through the row menu

    def __init__(self, model: ResultsModel, parent=None):
        super().__init__(parent)
        self.m = model
        self.setModel(model)
        self.hover_row = -1
        self.flash_row = -1                  # transient double-click acknowledgement (never a selection)
        self.flash_level = 0.0
        from PySide6.QtCore import QEasingCurve, QVariantAnimation
        self._flash = QVariantAnimation(self)
        self._flash.setStartValue(1.0)
        self._flash.setEndValue(0.0)
        self._flash.setDuration(self.FLASH_MS)
        self._flash.setEasingCurve(QEasingCurve.Type.InQuad)
        self._flash.valueChanged.connect(self._flash_step)
        self._flash.finished.connect(lambda: self._flash_step(0.0))
        self.header = Header(model, self)
        self.setHorizontalHeader(self.header)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setCornerButtonEnabled(False)
        self.setShowGrid(False)
        # Explicit product decision: no Qt cell/row selection, no current cell, no focus rectangle.
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setItemDelegate(Delegate(self))
        self.setMouseTracking(True)
        self.setWordWrap(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # Scroll ownership: the table never scrolls vertically - it is as tall as the rows of its
        # current page (see natural_height) and the main content area scrolls instead.  A thin
        # horizontal bar remains as the fallback for pathological column sets only.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBar(ThinScrollBar(Qt.Orientation.Horizontal))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizeAdjustPolicy(QAbstractItemView.SizeAdjustPolicy.AdjustIgnored)
        self.header.sectionClicked.connect(lambda i: self.m.sort_by(self.m.keys[i]))
        self.selection = CellTextSelection(self)
        self._press: tuple[int, int, QPoint] | None = None
        self._dragging = False
        model.columns_changed.connect(self.apply_widths)
        model.modelReset.connect(self.selection.end)
        model.dataChanged.connect(lambda *_: self.selection.end())
        self.apply_widths()

    # -------------------------------------------------------------- hover (full row, transient)
    def _row_rect(self, r: int) -> QRect:
        return QRect(0, self.rowViewportPosition(r), self.viewport().width(), ROW_HEIGHT)

    def _set_hover(self, r: int):
        if r == self.hover_row:
            return
        old, self.hover_row = self.hover_row, r
        for row in (old, r):
            if row >= 0:
                self.viewport().update(self._row_rect(row))

    def leaveEvent(self, e):
        self._set_hover(-1)
        super().leaveEvent(e)

    def selection_cell(self) -> tuple[int, int] | None:
        return self.selection.cell

    # -------------------------------------------------------------- mouse
    def _text_cell(self, idx: QModelIndex) -> bool:
        return idx.isValid() and COLUMN_BY_KEY[self.m.keys[idx.column()]].kind != "model"

    def mousePressEvent(self, e):
        # No super(): it would set a current index / start a selection.  A click does nothing.
        pos = e.position().toPoint()
        self.selection.end()
        self._dragging = False
        self._press = None
        if e.button() == Qt.MouseButton.LeftButton:
            idx = self.indexAt(pos)
            if self._text_cell(idx):
                self._press = (idx.row(), idx.column(), pos)
        e.accept()

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        self._set_hover(self.rowAt(pos.y()))
        if self._press and e.buttons() & Qt.MouseButton.LeftButton:
            r, c, start = self._press
            if not self._dragging and (pos - start).manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
                idx = self.m.index(r, c)
                self.selection.begin(r, c, self.m.keys[c], self.m.cell_text(r, c), self.visualRect(idx), start)
                self.viewport().update(self.visualRect(idx))
            if self._dragging:
                self.selection.extend_to(pos)
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._dragging:
            if self.selection.selected_text():
                self.selection.setFocus(Qt.FocusReason.MouseFocusReason)
            else:
                self.selection.end()
        self._dragging = False
        self._press = None
        e.accept()

    FLASH_MS = 450

    def flash(self, view_row: int) -> None:
        """Brief Carbon active flash of a row (double-click feedback); the row then returns to hover-only."""
        self.flash_row = view_row
        self.flash_level = 1.0                 # visible at once (the animation's first value comes on its first tick)
        self.viewport().update()
        self._flash.stop()
        self._flash.start()

    def _flash_step(self, v) -> None:
        self.flash_level = float(v)
        if self.flash_level <= 0:
            self.flash_row = -1
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        self.selection.end()
        self._press = None
        idx = self.indexAt(e.position().toPoint())
        if idx.isValid() and e.button() == Qt.MouseButton.LeftButton:
            row = self.m.row_at(idx.row())
            if row is not None:
                self.flash(idx.row())
                self.details_requested.emit(row)
        e.accept()

    def contextMenuEvent(self, e):
        idx = self.indexAt(self.viewport().mapFromGlobal(e.globalPos()))
        if not idx.isValid():
            return
        row = self.m.row_at(idx.row())
        if row is None:
            return
        key = self.m.keys[idx.column()]
        menu = self.row_menu(row, key)
        menu.exec_at(e.globalPos())
        menu.deleteLater()

    def row_menu(self, row: ResultRecord, key: str) -> CarbonMenu:
        menu = CarbonMenu(parent=self, size="md")     # CORRECT_RIGHT_CLICK: 40 px items, grouped
        sel = self.selection.clipboard_text()
        if sel:
            menu.add_action("Copy", lambda: QGuiApplication.clipboard().setText(sel), shortcut="Ctrl+C")
            menu.addSeparator()
        menu.add_action("Analyse composition", lambda: self.details_requested.emit(row))
        menu.add_action("Open details in new window", lambda: self.window_requested.emit(row))
        menu.addSeparator()
        menu.add_action("Copy value", lambda: QGuiApplication.clipboard().setText(
            self._copy_value(row, key)))
        menu.add_action("Copy row", lambda: QGuiApplication.clipboard().setText(table_tsv([row], self.m.keys)))
        menu.addSeparator()
        menu.add_action("Remove result", lambda: self._remove(row), danger=True, trailing_icon="delete_key")
        return menu

    @staticmethod
    def _copy_value(row: ResultRecord, key: str) -> str:
        if COLUMN_BY_KEY[key].kind == "model":
            return row.model_label(key)
        return full_precision(row, key)

    def _remove(self, row: ResultRecord):
        rid = row.id
        self.m.remove_rows([row])
        self.removed_ids.emit([rid])
        self.rows_removed.emit()

    # -------------------------------------------------------------- column widths
    # Figma widths at 1880 px: Alloy 180, rho 133, other descriptors 157, models 79.  These are the
    # reference weights; narrower tables compress every column proportionally down to its minimum
    # (no horizontal scroll bar for the default columns at 1440 logical px = Windows 150 % on a
    # 2160 px display), wider tables grow every column proportionally up to its maximum.
    BASE_WIDTH = {"name": 180, "density": 133, "composition": 220}
    MIN_WIDTH = {"name": 140, "composition": 160}
    MODEL_MIN = 64
    FLEX_MIN = 72
    GROW_LIMIT = 1.6          # no column wider than 1.6 × its reference (one column never hogs the row)

    def column_specs(self) -> tuple[list[int], list[int], list[int | None]]:
        refs, mins, maxs = [], [], []
        for k in self.m.keys:
            if COLUMN_BY_KEY[k].kind == "model":
                ref, mn = MODEL_COL_WIDTH, self.MODEL_MIN
            else:
                ref, mn = self.BASE_WIDTH.get(k, 157), self.MIN_WIDTH.get(k, self.FLEX_MIN)
            refs.append(ref)
            mins.append(mn)
            maxs.append(int(ref * self.GROW_LIMIT))
        return refs, mins, maxs

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
        refs, mins, maxs = self.column_specs()
        widths = distribute(self.viewport().width(), refs, mins, maxs)
        changed = False
        for i, w in enumerate(widths):
            if self.header.sectionSize(i) != w:
                self.header.resizeSection(i, w)
                changed = True
        if changed:
            self.selection.end()
        self.widths_changed.emit()

    widths_changed = Signal()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._distribute()

    def natural_height(self) -> int:
        """Header + the rows of the current page (+ the horizontal fallback bar when shown)."""
        rows = self.m.rowCount()
        h = HEADER_HEIGHT + rows * ROW_HEIGHT
        if self.horizontalScrollBar().isVisible():
            h += self.horizontalScrollBar().sizeHint().height()
        return h

    def wheelEvent(self, e):
        # Vertical wheel always belongs to the main content area; only a horizontal gesture (or
        # Shift+wheel) may move the fallback horizontal bar.
        horizontal = abs(e.angleDelta().x()) > abs(e.angleDelta().y()) or \
            bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        hbar = self.horizontalScrollBar()
        if horizontal and hbar.maximum() > hbar.minimum():
            delta = e.angleDelta().x() or e.angleDelta().y()
            hbar.setValue(hbar.value() - delta)
            e.accept()
            return
        e.ignore()


class StickyHeader(Header):
    """Excel-like frozen header: a synchronised clone of the table's header.

    It lives in the main scroll area's viewport (a direct child, so scrolling does not move it) and
    is shown pinned at the top of the viewport - directly under the fixed HEA header - while the
    table's own header is scrolled out of view but rows are still visible.  It shares the table's
    model, so labels, sort indicators and the column set are the table's own; section sizes,
    hidden sections and the horizontal offset are copied from the table header whenever they change,
    so it never has a geometry of its own.  Clicking a section sorts, exactly like the original.
    """

    def __init__(self, view: ResultsView, host: QWidget):
        super().__init__(view.m, host)
        self.view = view
        self.setObjectName("StickyHeader")
        self.setModel(view.m)
        self.sectionClicked.connect(lambda i: view.m.sort_by(view.m.keys[i]))
        src = view.header
        src.sectionResized.connect(lambda *_: self.sync())
        src.geometriesChanged.connect(self.sync)
        view.widths_changed.connect(self.sync)
        view.m.columns_changed.connect(self.sync)
        view.m.headerDataChanged.connect(lambda *_: self.viewport().update())
        view.horizontalScrollBar().valueChanged.connect(self.setOffset)
        self.hide()

    def sync(self):
        src = self.view.header
        n = self.count()
        for i in range(n):
            self.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            if i < src.count():
                hidden = src.isSectionHidden(i)
                if self.isSectionHidden(i) != hidden:
                    self.setSectionHidden(i, hidden)
                if self.sectionSize(i) != src.sectionSize(i):
                    self.resizeSection(i, src.sectionSize(i))
        self.setOffset(self.view.horizontalScrollBar().value())
        self.viewport().update()

    def matches_source(self) -> bool:
        src = self.view.header
        return self.count() == src.count() and all(
            self.sectionSize(i) == src.sectionSize(i) and self.isSectionHidden(i) == src.isSectionHidden(i)
            for i in range(self.count())) and self.offset() == src.offset()

    def place(self, host_viewport: QWidget) -> bool:
        """Pin or hide according to where the table currently sits in ``host_viewport``.

        Returns True while the sticky header is active.
        """
        src = self.view.header
        top = src.mapTo(host_viewport, QPoint(0, 0))
        rows_bottom = top.y() + HEADER_HEIGHT + self.view.m.rowCount() * ROW_HEIGHT
        active = top.y() < 0 and rows_bottom > HEADER_HEIGHT and src.isVisible()
        if not active:
            if self.isVisible():
                self.hide()
            return False
        # pushed up once only the last row is left under it, so it leaves together with the table
        y = min(0, rows_bottom - HEADER_HEIGHT - ROW_HEIGHT)
        self.setGeometry(top.x(), y, src.width(), HEADER_HEIGHT)
        if not self.isVisible():
            self.sync()
            self.show()
        self.raise_()
        return True


# ====================================================================== pagination
class PageField(QLineEdit):
    """Editable current-page number of the pagination bar (Carbon text input, sm, compact).

    Integers only (a digits validator); the value is committed on Enter and on focus-out; a value outside
    1…last is corrected to the nearest valid page and the field flashes its invalid frame, so the correction
    is visible; an empty field reverts.  The mouse wheel never changes it (wheel guard).  It never shows page
    0: an empty table shows 1, disabled."""

    committed = Signal(int)                 # 0-based page index

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PageField")
        self.setProperty("crisp", True)
        self.setFixedSize(56, 32)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,9}"), self))
        self.setAccessibleName("Current page")
        self.last = 1
        self.current = 0
        self._invalid = False
        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.setInterval(900)
        self._flash.timeout.connect(self._clear_flash)
        self.returnPressed.connect(self._commit)
        install_wheel_guard(self)
        from .menu import carbon_context_menu
        carbon_context_menu(self)

    def set_pages(self, current: int, last: int) -> None:
        self.current, self.last = current, max(1, last)
        if not self.hasFocus():
            self.setText(str(current + 1))
        self.setAccessibleDescription(f"Type a page number (1–{self.last:,}) and press Enter")

    def _commit(self) -> None:
        text = self.text().strip()
        if not text:
            self.setText(str(self.current + 1))
            return
        page = int(text)
        clamped = max(1, min(page, self.last))
        if clamped != page:
            self._invalid = True            # visibly corrected
            self._flash.start()
            self.update()
        self.setText(str(clamped))
        if clamped - 1 != self.current:
            self.committed.emit(clamped - 1)

    def _clear_flash(self) -> None:
        self._invalid = False
        self.update()

    def focusOutEvent(self, e):
        self._commit()
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.setText(str(self.current + 1))
            self.clearFocus()
            return
        super().keyPressEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        from ..theme import FOCUS_WIDTH
        p = QPainter(self)
        r = self.rect()
        if self._invalid:
            crisp.frame(p, r, FOCUS_WIDTH, t("support-error"))
        elif self.hasFocus():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        elif self.isEnabled():
            crisp.hline_bottom(p, r, t("border-strong-02"), HAIRLINE)
        p.end()


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
        self.size_box = Dropdown([(n, str(n)) for n in PAGE_SIZES], model.page_size, inline=True,
                                 accessible="Items per page")
        self.size_box.setFixedWidth(self.size_box.width_for_items())
        lay.addWidget(self.size_box)
        lay.addWidget(self._vdiv())
        self.range_lbl = QLabel("")
        self.range_lbl.setObjectName("Secondary")
        self.range_lbl.setContentsMargins(16, 0, 0, 0)
        lay.addWidget(self.range_lbl, 1)
        lay.addWidget(self._vdiv())
        lay.addSpacing(8)
        self.page_field = PageField()
        lay.addWidget(self.page_field)
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
        self.page_field.committed.connect(self.m.set_page)
        self.prev_btn.clicked.connect(lambda: self.m.set_page(self.m.page - 1))
        self.next_btn.clicked.connect(lambda: self.m.set_page(self.m.page + 1))
        self.m.page_changed.connect(self.refresh)
        self._state = None
        self.refresh()

    def _vdiv(self):
        d = Divider(vertical=True)
        d.setFixedHeight(40)
        return d

    def refresh(self):
        n = self.m.view_count()
        total = self.m.total_count()
        state = (n, total, self.m.page, self.m.page_size, bool(self.m.filters))
        if state == self._state:
            return
        self._state = state
        a = self.m.page * self.m.page_size
        b = min(a + self.m.page_size, n)
        if n == total:
            suffix = ""
        elif self.m.filters:
            suffix = f" (filtered from {total:,})"
        else:                                  # sorted view built before the latest rows arrived
            suffix = f" (+{total - n:,} not yet sorted)"
        self.range_lbl.setText(f"{a + 1 if n else 0:,}–{b:,} of {n:,} item{'s' if n != 1 else ''}{suffix}")
        pc = self.m.page_count()
        self.page_field.set_pages(self.m.page, pc)
        self.page_field.setEnabled(n > 0)
        self.of_lbl.setText(f"of {pc:,} page{'s' if pc != 1 else ''}")
        self.prev_btn.setEnabled(self.m.page > 0)
        self.next_btn.setEnabled(self.m.page < pc - 1)


# ====================================================================== empty state + container
class TableEmptyState(QWidget):
    """Figma 289:44643 / 291:45055: empty-state illustration over the table body."""

    TOP = 32

    def __init__(self, view: QTableView):
        super().__init__(view.viewport())
        self.view = view
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title, self.body = "", ""
        THEME.changed.connect(self._theme_changed)

    def set_text(self, title: str, body: str):
        if (title, body) == (self.title, self.body) and self.isVisible() == bool(title):
            return
        self.title, self.body = title, body
        self.setGeometry(self.view.viewport().rect())
        self.setVisible(bool(title))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Figma 289:44643 - artwork at x = 64, its exported height, title 24 px below it.
        x, y = 64, self.TOP
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


def build_export_menu(menu: CarbonMenu, export, copy_all, copy_page=None) -> None:
    """CORRECT_MENU_BUTTON: Excel workbook, CSV, divider, Copy table to clipboard (paste icon).  The dataset is
    exported - all results, never just the visible page; while a table filter is active two more items export
    the filtered results (they are hidden otherwise, not shown disabled)."""
    menu.add_action("Excel workbook (.xlsx)", lambda: export("xlsx", "all"))
    menu.add_action("CSV (.csv)", lambda: export("csv", "all"))
    a = menu.add_action("Filtered results (.xlsx)", lambda: export("xlsx", "filtered"))
    b = menu.add_action("Filtered results (.csv)", lambda: export("csv", "filtered"))
    a.setProperty("filtered_only", True)
    b.setProperty("filtered_only", True)
    menu.addSeparator()
    menu.add_action("Copy table to clipboard", copy_all, trailing_icon="paste")


def update_export_menu(menu: CarbonMenu, filtered: bool) -> None:
    for act in menu.actions():
        if act.property("filtered_only"):
            act.setVisible(filtered)


class ResultsTable(QFrame):
    """Toolbar + table + pagination."""

    delete_requested = Signal()
    filter_requested = Signal()
    columns_requested = Signal()
    copy_requested = Signal()
    copy_page_requested = Signal()
    export_requested = Signal(str, str)  # "xlsx" | "csv", "all" | "filtered"

    def __init__(self, parent=None, engine=None, repo: ResultRepository | None = None):
        super().__init__(parent)
        self.setObjectName("DataTable")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.model = ResultsModel(self, engine, repo)
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
        self.delete_btn = IconButton("trash_can", "Clear table")
        self.filter_btn = IconButton("filter", "Filter results")
        self.columns_btn = IconButton("settings", "Table columns")
        for b in (self.delete_btn, self.filter_btn, self.columns_btn):
            bl.addWidget(b)
        # CORRECT_MENU_BUTTON: Carbon MenuButton (secondary, sm): on-colour label and chevron, chevron up while
        # open, a sm menu right-aligned flush under the button
        self.export_btn = MenuButton("Export")
        self.export_btn.setProperty("kind", "secondary")
        self.export_btn.setProperty("btnsize", "sm")
        self.export_btn.setFixedWidth(123)
        menu = CarbonMenu(parent=self.export_btn, size="sm")
        build_export_menu(menu, self.export_requested.emit, self.copy_requested.emit, self.copy_page_requested.emit)
        update_export_menu(menu, False)             # no filter yet: the filtered variants start hidden
        menu.aboutToShow.connect(lambda: update_export_menu(menu, bool(self.model.filters)))
        self.export_menu = menu
        self.export_btn.attach(menu)
        bl.addWidget(self.export_btn)
        lay.addWidget(bar)
        self.view = ResultsView(self.model)
        lay.addWidget(self.view, 1)
        self.pagination = PaginationBar(self.model)
        lay.addWidget(self.pagination)
        self.empty = TableEmptyState(self.view)
        self.model.page_changed.connect(self._update_empty)
        self.view.viewport().installEventFilter(self)
        self._update_empty()
        # natural height: toolbar + header + current page rows + pagination (no inner scrolling)
        self._natural = -1
        self.model.page_changed.connect(self.update_natural_height)
        self.view.horizontalScrollBar().rangeChanged.connect(lambda *_: self.update_natural_height())
        self.update_natural_height()
        self.delete_btn.clicked.connect(self.delete_requested.emit)
        self.filter_btn.clicked.connect(self.filter_requested.emit)
        self.columns_btn.clicked.connect(self.columns_requested.emit)
        THEME.changed.connect(self._theme_changed)

    def _theme_changed(self, *_):
        self.view.viewport().update()
        self.view.header.viewport().update()

    TOOLBAR_HEIGHT = 32
    PAGINATION_HEIGHT = 40

    def empty_body_height(self) -> int:
        """Body height that shows the whole empty-state block (artwork, title, body, margin)."""
        size, _pm = illustration("box")
        return TableEmptyState.TOP + size.height() + 56 + 20 + TableEmptyState.TOP

    def natural_height(self) -> int:
        view_h = self.view.natural_height()
        if not self.model.view_count():
            view_h = max(view_h, HEADER_HEIGHT + self.empty_body_height())
        return self.TOOLBAR_HEIGHT + view_h + self.PAGINATION_HEIGHT

    def update_natural_height(self):
        # The view may grow beyond this (the section fills spare viewport height so the
        # pagination bar sits at the bottom, as in the design), but never shrinks below its rows:
        # the main content area scrolls instead.  Only a changed height re-lays the window out.
        h = self.natural_height()
        if h == self._natural:
            return
        self._natural = h
        self.view.setMinimumHeight(h - self.TOOLBAR_HEIGHT - self.PAGINATION_HEIGHT)
        self.setMinimumHeight(h)
        self.updateGeometry()

    def internal_vertical_scrollbar_visible(self) -> bool:
        vbar = self.view.verticalScrollBar()
        return vbar.isVisible() or vbar.maximum() > vbar.minimum()

    def _update_empty(self):
        m = self.model
        if not m.total_count():
            self.empty.set_text("No results yet", "Click Calculate to add alloys to this table.")
        elif not m.view_count():
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
