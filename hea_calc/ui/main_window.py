"""Main window (Figma 'DARK MODE FULLSCREEN', node 170:11154)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QScrollArea, QVBoxLayout, QWidget)

from ..core.engine import DEFAULT_TCRIT_FRACTION, Engine, default_engine
from ..core.results import DEFAULT_COLUMNS, COLUMN_BY_KEY, ResultRow, table_tsv
from ..core.spreadsheet import SpreadsheetError, export_rows, read_compositions
from . import icons
from .theme import (CONTENT_MARGIN_BOTTOM, CONTENT_MARGIN_TOP, CONTENT_MARGIN_X, PANEL_GAP, THEME, TOP_ROW_HEIGHT,
                    stylesheet)
from .widgets.common import InlineNotification, button
from .widgets.composition_panel import CompositionPanel
from .widgets.details_panel import DetailsPanel
from .widgets.dialogs import (AboutDialog, AlloyDetailsDialog, ColumnsDialog, FilterDialog, ImportReportDialog,
                              SettingsDialog)
from .widgets.element_panel import ElementPanel
from .widgets.header import AppHeader
from .widgets.results_table import PAGE_SIZES, ResultsTable
from .worker import CalculationWorker

APP_ICON = Path(__file__).resolve().parent / "icons" / "logo_icon.ico"


class ProgressBanner(QWidget):
    """Inline loading banner shown above the table while a batch is calculated."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InlineNotification")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 0, 0)
        lay.setSpacing(16)
        self.label = QLabel("")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(320)
        self.cancel = button("Cancel", "ghost", "sm")
        lay.addWidget(self.label)
        lay.addWidget(self.bar)
        lay.addStretch(1)
        lay.addWidget(self.cancel)
        self.setFixedHeight(48)
        self.hide()


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine | None = None, settings: QSettings | None = None):
        super().__init__()
        self.engine = engine or default_engine()
        self.settings = settings or QSettings("MDL", "HEA Calculator")
        self.annealing: float | None = self.settings.value("annealing", None, float) if self.settings.contains(
            "annealing") else None
        self.fraction = float(self.settings.value("tcrit_fraction", DEFAULT_TCRIT_FRACTION))
        self.worker: CalculationWorker | None = None
        self._first_new = 0
        self.setWindowTitle("HEA Calculator")
        if APP_ICON.exists():
            self.setWindowIcon(QIcon(str(APP_ICON)))
        self.setMinimumSize(1024, 640)
        self._build_menus()
        body = QWidget()
        body.setObjectName("AppBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(body)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = AppHeader(self.file_menu, self.theme_menu)
        self.header.about_requested.connect(self.show_about)
        root.addWidget(self.header)
        content_w = QWidget()
        content_w.setObjectName("AppBody")
        content_w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content = QVBoxLayout(content_w)
        content.setContentsMargins(CONTENT_MARGIN_X, CONTENT_MARGIN_TOP, CONTENT_MARGIN_X, CONTENT_MARGIN_BOTTOM)
        content.setSpacing(PANEL_GAP)
        top = QHBoxLayout()
        top.setSpacing(PANEL_GAP)
        self.elements = ElementPanel(self.engine)
        self.composition = CompositionPanel(self.engine.data)
        self.details = DetailsPanel()
        top.addWidget(self.elements)
        top.addWidget(self.composition)
        top.addWidget(self.details, 1)
        top_w = QWidget()
        top_w.setLayout(top)
        top.setContentsMargins(0, 0, 0, 0)
        top_w.setFixedHeight(TOP_ROW_HEIGHT)
        content.addWidget(top_w)
        table_col = QVBoxLayout()
        table_col.setSpacing(0)
        self.notification = InlineNotification()
        self.progress = ProgressBanner()
        self.progress.cancel.clicked.connect(self.cancel_calculation)
        self.table = ResultsTable()
        table_col.addWidget(self.notification)
        table_col.addWidget(self.progress)
        table_col.addWidget(self.table, 1)
        content.addLayout(table_col, 1)
        self.table.setMinimumHeight(200)
        # Below the design's minimum content size the content area scrolls (header stays fixed);
        # at the design size (1920 × 1000) no outer scrolling occurs.
        content_w.setMinimumSize(2 * CONTENT_MARGIN_X + 596 + 457 + 480 + 2 * PANEL_GAP,
                                 CONTENT_MARGIN_TOP + TOP_ROW_HEIGHT + PANEL_GAP + 200 + CONTENT_MARGIN_BOTTOM)
        outer = QScrollArea()
        outer.setObjectName("ContentScroll")
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.Shape.NoFrame)
        outer.setWidget(content_w)
        root.addWidget(outer, 1)
        self.setCentralWidget(body)
        body.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        body.setFocus()  # no control shows a focus ring until the keyboard is used
        self._notify_timer = QTimer(self)
        self._notify_timer.setSingleShot(True)
        self._notify_timer.timeout.connect(self.notification.dismiss)

        # wiring: selection ↔ composition
        self.elements.element_toggled.connect(self.composition.element_toggled)
        self.composition.elements_changed.connect(self._composition_elements)
        self.composition.calculate_requested.connect(self.calculate)
        self.composition.message.connect(self.notify)
        self.composition.copy_compositions.connect(self._copy_generated)
        # table
        self.table.view.row_selected.connect(self.details.show_row)
        self.table.view.row_activated.connect(self.open_details)
        self.table.view.cell_info.connect(self.table.status.setText)
        self.table.delete_requested.connect(self.delete_rows)
        self.table.filter_requested.connect(self.edit_filters)
        self.table.columns_requested.connect(self.edit_columns)
        self.table.copy_requested.connect(self.copy_table)
        self.table.export_requested.connect(self.export)
        self.table.model.modelReset.connect(self._check_details)
        # restore table preferences
        cols = self.settings.value("columns", None)
        if isinstance(cols, list) and all(c in COLUMN_BY_KEY for c in cols) and "name" in cols:
            self.table.model.set_keys(cols)
        size = int(self.settings.value("page_size", 100))
        if size in PAGE_SIZES:
            self.table.pagination.size_box.setCurrentIndex(PAGE_SIZES.index(size))
        THEME.changed.connect(self.apply_theme)
        self.apply_theme()
        self._update_status()

    # ------------------------------------------------------------------ menus
    def _build_menus(self):
        self.file_menu = QMenu(self)
        a = self.file_menu.addAction("Import compositions…", self.import_compositions)
        a.setShortcut(QKeySequence("Ctrl+O"))
        exp = self.file_menu.addMenu("Export results")
        exp.addAction("Excel workbook (.xlsx)…", lambda: self.export("xlsx"))
        exp.addAction("CSV (.csv)…", lambda: self.export("csv"))
        c = self.file_menu.addAction("Copy table", self.copy_table)
        c.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.file_menu.addSeparator()
        self.file_menu.addAction("Calculation settings…", self.edit_settings)
        self.file_menu.addSeparator()
        q = self.file_menu.addAction("Exit", self.close)
        q.setShortcut(QKeySequence("Ctrl+Q"))
        for act in (a, c, q):
            self.addAction(act)
        self.theme_menu = QMenu(self)
        group = QActionGroup(self)
        for name, label in (("dark", "Dark (Gray 100)"), ("light", "Light (Gray 10)")):
            act = QAction(label, self, checkable=True)
            act.setChecked(THEME.name == name)
            act.triggered.connect(lambda _c=False, n=name: self.set_theme(n))
            group.addAction(act)
            self.theme_menu.addAction(act)
        self.theme_actions = group

    def set_theme(self, name: str):
        THEME.set_theme(name)
        self.settings.setValue("theme", name)

    def apply_theme(self, *_):
        app = QApplication.instance()
        app.setStyleSheet(stylesheet(lambda name, token: icons.file_url(name, token)))
        for act in self.theme_actions.actions():
            act.setChecked(act.text().lower().startswith(THEME.name))
        self.update()

    # ------------------------------------------------------------------ feedback
    def notify(self, kind: str, text: str, timeout_ms: int = 8000):
        titles = {"error": "Error", "warning": "Warning", "success": "Done", "info": "Info"}
        self.notification.show_message(kind, titles.get(kind, ""), text)
        if kind in ("success", "info"):
            self._notify_timer.start(timeout_ms)
        else:
            self._notify_timer.stop()

    def _update_status(self):
        m = self.table.model
        n = len(m.rows)
        flt = f" · filter active ({len(m.view_rows)} shown)" if m.filters else ""
        # The reference toolbar carries no standing label - the paginator already reports the
        # range - so this slot is reserved for filter state and for cell info on hover.
        self.table.status.setText(flt.strip() if flt else "")

    # ------------------------------------------------------------------ selection sync
    def _composition_elements(self, elements: list[str]):
        self.elements.set_selected(elements)
        if self.composition.mode != "expression":
            # ensure panel order follows the user's list (rename / clear)
            pass

    # ------------------------------------------------------------------ calculation
    def options(self) -> dict:
        return {"annealing_temperature": self.annealing, "tcrit_fraction": self.fraction}

    def calculate(self, source, names: list, comps: list, envs: list):
        if self.worker is not None:
            self.notify("warning", "A calculation is already running.")
            return
        self.notification.dismiss()
        if len(comps) == 1:
            res = self.engine.calculate(comps[0], **self.options())
            src = source[0] if isinstance(source, list) else source
            row = ResultRow(names[0], comps[0], res, src, envs[0] if envs else {})
            self._add_rows([row], select_first=True)
            if not res.ok:
                self.notify("error", res.error)
            return
        self._first_new = len(self.table.model.rows)
        self.worker = CalculationWorker(self.engine, source, names, comps, envs, self.options(), self)
        self.worker.batch.connect(lambda rows: self._add_rows(rows, select_first=False))
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.progress.bar.setRange(0, len(comps))
        self.progress.bar.setValue(0)
        self.progress.label.setText(f"Calculating {len(comps):,} compositions…")
        self.progress.show()
        self.composition.calc_btn.setEnabled(False)
        self.worker.start()

    def _progress(self, done: int, total: int, eta: float):
        self.progress.bar.setValue(done)
        self.progress.label.setText(f"Calculating {done:,} / {total:,} — about {eta:,.0f} s left")

    def _done(self, cancelled: bool):
        added = len(self.table.model.rows) - self._first_new
        self.worker.deleteLater()
        self.worker = None
        self.progress.hide()
        self.composition.calc_btn.setEnabled(True)
        self._jump_to(self._first_new)
        failed = sum(1 for r in self.table.model.rows[self._first_new:] if not r.result.ok)
        msg = f"{added:,} composition(s) calculated" + (" (cancelled)" if cancelled else "")
        if failed:
            msg += f"; {failed} could not be evaluated (see tooltips)"
        self.notify("warning" if cancelled or failed else "success", msg + ".")

    def cancel_calculation(self):
        if self.worker:
            self.worker.cancel()

    def _add_rows(self, rows: list[ResultRow], select_first: bool):
        m = self.table.model
        start = len(m.rows)
        m.append_rows(rows)
        self._update_status()
        if select_first:
            self._jump_to(start)

    def _jump_to(self, index_in_rows: int):
        m = self.table.model
        if not (0 <= index_in_rows < len(m.rows)):
            return
        target = m.rows[index_in_rows]
        try:
            pos = m.view_rows.index(target)
        except ValueError:
            return
        m.set_page(pos // m.page_size)
        self.table.view.selectRow(pos % m.page_size)
        self.details.show_row(target)

    def _check_details(self):
        if self.details.row is not None and self.details.row not in self.table.model.rows:
            self.details.show_row(None)
        self._update_status()

    # ------------------------------------------------------------------ table actions
    def delete_rows(self):
        rows = self.table.view.selected_rows()
        if not rows:
            if not self.table.model.rows:
                return
            if QMessageBox.question(self, "Delete results", "Delete all results?") != QMessageBox.StandardButton.Yes:
                return
            self.table.model.set_rows([])
        else:
            self.table.model.remove_rows(rows)
        self.details.show_row(None)
        self._update_status()

    def edit_filters(self):
        dlg = FilterDialog(self.table.model.filters, self)
        if dlg.exec():
            self.table.model.set_filters(dlg.result_filters)
            self.table.set_filter_active(bool(dlg.result_filters))
            self.details.show_row(None)
            self._update_status()
        dlg.deleteLater()

    def edit_columns(self):
        dlg = ColumnsDialog(self.table.model.keys, self)
        if dlg.exec():
            keys = dlg.selected()
            self.table.model.set_keys(keys)
            self.settings.setValue("columns", keys)
        dlg.deleteLater()

    def copy_table(self):
        """Copy every row of the (filtered, sorted) table with the visible columns."""
        m = self.table.model
        rows = m.view_rows
        if not rows:
            self.notify("info", "The table is empty.")
            return
        QGuiApplication.clipboard().setText(table_tsv(rows, m.keys))
        self.notify("success", f"Copied {len(rows):,} row(s) × {len(m.keys)} columns (paste into Excel).", 4000)

    def _copy_generated(self, tsv: str):
        QGuiApplication.clipboard().setText(tsv)
        n = max(len(tsv.strip().splitlines()) - 1, 0)
        self.notify("success", f"Copied {n:,} generated composition(s) (paste into Excel).", 4000)

    def export(self, fmt: str):
        rows = self.table.model.view_rows
        if not rows:
            self.notify("info", "Nothing to export.")
            return
        flt = "Excel workbook (*.xlsx)" if fmt == "xlsx" else "CSV (*.csv)"
        path, _ = QFileDialog.getSaveFileName(self, "Export results", f"hea_results.{fmt}", flt)
        if not path:
            return
        try:
            export_rows(rows, path, notes={"M6/M7 temperature": self._temperature_note()})
        except Exception as exc:  # noqa: BLE001 - report any I/O problem to the user
            self.notify("error", f"Export failed: {exc}")
            return
        self.notify("success", f"Exported {len(rows):,} rows to {Path(path).name}.")

    def _temperature_note(self) -> str:
        return f"{self.annealing:g} K (user)" if self.annealing else f"{self.fraction:g}·Tm (estimated)"

    def import_compositions(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import compositions", "",
                                              "Spreadsheets (*.xlsx *.xlsm *.csv);;All files (*.*)")
        if not path:
            return
        try:
            res = read_compositions(path, self.engine.data)
        except (SpreadsheetError, OSError, ValueError) as exc:
            self.notify("error", f"Import failed: {exc}")
            return
        if res.errors:
            rep = ImportReportDialog(Path(path).name, res.layout, len(res.entries), res.errors, self)
            rep.exec()
            rep.deleteLater()
        if not res.entries:
            self.notify("error", "No valid compositions found in the file.")
            return
        names = [n or "" for n, _ in res.entries]
        comps = [c for _, c in res.entries]
        from ..core.composition import alloy_name
        names = [n if n else alloy_name(c) for n, c in zip(names, comps)]
        self.calculate("import", names, comps, [{} for _ in comps])

    def edit_settings(self):
        dlg = SettingsDialog(self.annealing, self.fraction, self)
        if dlg.exec():
            self.annealing, self.fraction = dlg.annealing, dlg.fraction
            if self.annealing is None:
                self.settings.remove("annealing")
            else:
                self.settings.setValue("annealing", self.annealing)
            self.settings.setValue("tcrit_fraction", self.fraction)
            rows = self.table.model.rows
            if rows and self.worker is None and QMessageBox.question(
                    self, "Recalculate results",
                    f"Recalculate the {len(rows):,} existing result(s) with the new temperature setting?")                     == QMessageBox.StandardButton.Yes:
                self.recalculate_all()
            else:
                self.notify("info", f"M6/M7 temperature: {self._temperature_note()}. New calculations use it.")
        dlg.deleteLater()

    def recalculate_all(self):
        """Re-run every existing row through the engine with the current settings (same inputs)."""
        rows = list(self.table.model.rows)
        if not rows:
            return
        self.table.model.set_rows([])
        self.details.show_row(None)
        self.calculate([r.source for r in rows], [r.name for r in rows], [r.input_amounts for r in rows],
                       [r.variables for r in rows])

    def open_details(self, row):
        if row is not None:
            dlg = AlloyDetailsDialog(row, self)
            dlg.exec()
            dlg.deleteLater()

    def show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()
        dlg.deleteLater()

    def closeEvent(self, e):
        self.settings.setValue("page_size", self.table.model.page_size)
        if self.worker:
            self.worker.cancel()
            self.worker.wait(2000)
        super().closeEvent(e)


_ = DEFAULT_COLUMNS
