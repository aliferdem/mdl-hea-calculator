"""Main window (Figma 'DARK MODE FULLSCREEN', node 170:11154)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QActionGroup, QGuiApplication, QIcon
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QProgressBar, QVBoxLayout, QWidget)

from ..core.engine import DEFAULT_TCRIT_FRACTION, Engine, default_engine
from ..core.jobs import CalculationJob, CalculationService, JobInput
from ..core.results import DEFAULT_COLUMNS, COLUMN_BY_KEY, ResultRow, table_tsv
from ..core.spreadsheet import SpreadsheetError, export_rows, read_compositions
from ..core.store import StoredRow
from . import icons
from .theme import (COMPOSITION_PANEL_MIN, COMPOSITION_PANEL_WIDTH, CONTENT_MARGIN_BOTTOM, CONTENT_MARGIN_TOP,
                    CONTENT_MARGIN_X, DETAILS_PANEL_MIN, DETAILS_PANEL_WIDTH, ELEMENT_PANEL_MIN, ELEMENT_PANEL_WIDTH,
                    PANEL_GAP, THEME, TOP_ROW_HEIGHT, stylesheet)
from .widgets.common import InlineNotification, button
from .widgets.composition_panel import CompositionPanel
from .widgets.details_panel import DetailsPanel
from .widgets.dialogs import (AboutDialog, AlloyDetailsDialog, ColumnsDialog, FilterDialog, ImportReportDialog,
                              SettingsDialog)
from .widgets.element_panel import ElementPanel
from .widgets.header import AppHeader
from .widgets.layouts import UpperPanels
from .widgets.menu import CarbonMenu, carbonize_popups
from .widgets.results_table import PAGE_SIZES, ResultsTable, StickyHeader
from .widgets.scroll import MainScrollArea
from .worker import JobRunner

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


_SHEET_CACHE: dict[str, str] = {}


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine | None = None, settings: QSettings | None = None):
        super().__init__()
        self.engine = engine or default_engine()
        self.settings = settings or QSettings("MDL", "HEA Calculator")
        self.annealing: float | None = self.settings.value("annealing", None, float) if self.settings.contains(
            "annealing") else None
        self.fraction = float(self.settings.value("tcrit_fraction", DEFAULT_TCRIT_FRACTION))
        # CPU-bound batches run in worker processes (core/jobs.py); the runner feeds the table at 10 Hz
        self.jobs = CalculationService()
        QApplication.instance().aboutToQuit.connect(self.jobs.shutdown)   # also when quit without a close
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
        # Upper area: the design's 596 / 457 / 787 px panels (1920 px frame) as reference widths,
        # compressed proportionally on narrower windows (Windows 125 % / 150 %) and grown only in
        # Calculation details on wider ones (responsive.distribute).  Once the three no longer fit at
        # their minimum widths, Details moves below the other two (widgets/layouts.UpperPanels).
        self.elements = ElementPanel(self.engine)
        self.composition = CompositionPanel(self.engine.data)
        self.details = DetailsPanel()
        top_w = UpperPanels([(self.elements, ELEMENT_PANEL_WIDTH, ELEMENT_PANEL_MIN, ELEMENT_PANEL_WIDTH),
                             (self.composition, COMPOSITION_PANEL_WIDTH, COMPOSITION_PANEL_MIN,
                              COMPOSITION_PANEL_WIDTH),
                             (self.details, DETAILS_PANEL_WIDTH, DETAILS_PANEL_MIN, None)],
                            TOP_ROW_HEIGHT, PANEL_GAP)
        self.top_row = top_w
        content.addWidget(top_w)
        table_col = QVBoxLayout()
        table_col.setSpacing(0)
        self.notification = InlineNotification()
        self.progress = ProgressBanner()
        self.progress.cancel.clicked.connect(self.cancel_calculation)
        self.table = ResultsTable(engine=self.engine)
        self.runner = JobRunner(self.jobs, self.table.model, self)
        self.runner.progress.connect(self._progress)
        self.runner.finished.connect(self._done)
        table_col.addWidget(self.notification)
        table_col.addWidget(self.progress)
        table_col.addWidget(self.table, 1)
        content.addLayout(table_col, 1)
        # One primary vertical scrolling context below the fixed header.  The results section
        # is at least as tall as its current page (ResultsTable.natural_height) and otherwise fills
        # the remaining viewport height, so with few rows nothing scrolls and with many rows the
        # main area - never the table - scrolls.
        self.content = content_w
        self.scroll = MainScrollArea()
        self.scroll.setWidget(content_w)
        root.addWidget(self.scroll, 1)
        self.sticky = StickyHeader(self.table.view, self.scroll.viewport())
        # coalesced re-placement of the sticky header (owned by the window, so it dies with it)
        self._sticky_timer = QTimer(self)
        self._sticky_timer.setSingleShot(True)
        self._sticky_timer.setInterval(0)
        self._sticky_timer.timeout.connect(self._place_sticky)
        self.scroll.verticalScrollBar().valueChanged.connect(self._place_sticky)
        self.scroll.horizontalScrollBar().valueChanged.connect(self._place_sticky)
        content_w.installEventFilter(self)
        self.table.installEventFilter(self)
        self.table.model.page_changed.connect(self._sticky_timer.start)
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
        self.composition.set_service(self.jobs)
        # table: double click -> embedded details; row menu -> separate details window
        self.table.view.details_requested.connect(self.show_details)
        self.table.view.window_requested.connect(self.open_details)
        self.table.view.rows_removed.connect(self._check_details)
        self.table.delete_requested.connect(self.delete_rows)
        self.table.filter_requested.connect(self.edit_filters)
        self.table.columns_requested.connect(self.edit_columns)
        self.table.copy_requested.connect(self.copy_table)
        self.table.export_requested.connect(self.export)
        self.table.model.page_changed.connect(self._check_details)
        # restore table preferences
        cols = self.settings.value("columns", None)
        if isinstance(cols, list) and all(c in COLUMN_BY_KEY for c in cols) and "name" in cols:
            self.table.model.set_keys(cols)
        size = int(self.settings.value("page_size", 100))
        if size in PAGE_SIZES:
            self.table.pagination.size_box.setCurrentIndex(PAGE_SIZES.index(size))
        carbonize_popups(self)       # text-field context menus and dropdown lists use the Carbon popups
        THEME.changed.connect(self.apply_theme)
        self.apply_theme()
        self._update_status()

    # ------------------------------------------------------------------ scrolling / layout
    def eventFilter(self, obj, ev):
        if obj in (self.content, self.table) and ev.type() in (QEvent.Type.Resize, QEvent.Type.Move,
                                                               QEvent.Type.LayoutRequest):
            self._sticky_timer.start()
        return super().eventFilter(obj, ev)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_sticky_timer"):
            self._sticky_timer.start()

    def _place_sticky(self):
        self.sticky.place(self.scroll.viewport())

    def layout_report(self) -> dict:
        """Live layout facts for tools/dpi_diagnostics.py and the DPI tests."""
        vbar = self.table.view.verticalScrollBar()
        hbar = self.table.view.horizontalScrollBar()
        return {
            "upperPanels": [self.elements.width(), self.composition.width(), self.details.width()],
            "upperRowWidth": self.top_row.width(),
            "detailsStacked": self.top_row.stacked,
            "contentWidth": self.content.width(), "viewportWidth": self.scroll.viewport().width(),
            "viewportHeight": self.scroll.viewport().height(), "contentHeight": self.content.height(),
            "horizontalOverflow": self.content.width() > self.scroll.viewport().width(),
            "mainScrollbarVisible": self.scroll.main_scrollbar_visible(),
            "mainScrollMaximum": self.scroll.verticalScrollBar().maximum(),
            "tableVerticalScrollbarVisible": vbar.isVisible(),
            "tableVerticalScrollRange": vbar.maximum() - vbar.minimum(),
            "tableHorizontalScrollbarVisible": hbar.isVisible(),
            "tableWidth": self.table.width(),
            "tableColumnsSum": sum(self.table.view.header.sectionSize(i)
                                   for i in range(self.table.view.header.count())),
            "tableViewportWidth": self.table.view.viewport().width(),
            "tableRowsOnPage": self.table.model.rowCount(),
            "stickyHeaderActive": self.sticky.isVisible(),
            "tileSize": self.elements.table.tile_size,
        }

    # ------------------------------------------------------------------ menus
    def _build_menus(self):
        # Every opening menu is the shared Carbon menu (widgets/menu.py).
        self.file_menu = CarbonMenu(parent=self)
        a = self.file_menu.add_action("Import compositions…", self.import_compositions, shortcut="Ctrl+O")
        exp = self.file_menu.add_submenu("Export results")
        exp.add_action("Excel workbook (.xlsx)…", lambda: self.export("xlsx"))
        exp.add_action("CSV (.csv)…", lambda: self.export("csv"))
        c = self.file_menu.add_action("Copy table", self.copy_table, shortcut="Ctrl+Shift+C")
        self.file_menu.addSeparator()
        self.file_menu.add_action("Calculation settings…", self.edit_settings)
        self.file_menu.addSeparator()
        q = self.file_menu.add_action("Exit", self.close, shortcut="Ctrl+Q")
        for act in (a, c, q):
            self.addAction(act)
        self.theme_menu = CarbonMenu(parent=self)
        group = QActionGroup(self)
        for name, label in (("dark", "Dark (Gray 100)"), ("light", "Light (Gray 10)")):
            act = self.theme_menu.add_action(label, lambda n=name: self.set_theme(n), checkable=True,
                                             checked=THEME.name == name)
            group.addAction(act)
        self.theme_actions = group

    def set_theme(self, name: str):
        THEME.set_theme(name)
        self.settings.setValue("theme", name)

    def apply_theme(self, *_):
        # The sheet is scoped to this window rather than to QApplication.  Qt re-polishes every
        # registered widget for an application-wide sheet - measured at ~2.0 s for the 2783
        # widgets this window creates, against ~0.33 s for the window-scoped sheet.  Every dialog
        # is parented to this window, so it inherits the sheet and nothing loses styling.
        # The generated sheet is also memoised per theme: rebuilding it re-resolved every icon URL
        # and re-checked the icon cache on disk on every switch.
        app = QApplication.instance()
        if app.styleSheet():
            # only if something else left one behind: clearing it is itself a full re-polish
            app.setStyleSheet("")
        sheet = _SHEET_CACHE.get(THEME.name)
        if sheet is None:
            sheet = stylesheet(lambda name, token: icons.file_url(name, token))
            _SHEET_CACHE[THEME.name] = sheet
        self.setStyleSheet(sheet)
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
        flt = f" · filter active ({m.view_count():,} shown)" if m.filters else ""
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

    @property
    def worker(self):
        """The running calculation job (None when idle)."""
        return self.runner.job

    def calculate(self, source, names=None, comps=None, envs=None):
        """Calculate compositions.  ``comps`` is a list, or a callable returning
        ``(sources, names, compositions, variables)`` that runs off the GUI thread."""
        if self.runner.running:
            self.notify("warning", "A calculation is already running.")
            return
        self.notification.dismiss()
        if not callable(comps) and len(comps) == 1:
            res = self.engine.calculate(comps[0], **self.options())
            src = source[0] if isinstance(source, list) else source
            row = ResultRow(names[0], comps[0], res, src, envs[0] if envs else {})
            rng = self.table.model.append_rows([row], self.options())
            self._update_status()
            self._jump_to(rng.start)
            if not res.ok:
                self.notify("error", res.error)
            return
        if callable(comps):
            data = JobInput(source, (), comps, (), self.options())
            label = "Generating compositions…"
        else:
            data = JobInput(source, names, comps, envs, self.options())
            label = f"Calculating {len(comps):,} compositions…"
        self._first_new = len(self.table.model.store)
        self.progress.bar.setRange(0, 0)
        self.progress.label.setText(label)
        self.progress.cancel.setEnabled(True)
        self.progress.show()
        self.composition.set_calculating(True)
        self.runner.start(CalculationJob(data, self.engine))

    def _progress(self, done: int, total: int, eta: float):
        if self.progress.bar.maximum() != total:
            self.progress.bar.setRange(0, total)
        self.progress.bar.setValue(done)
        left = f" — about {eta:,.0f} s left" if done else ""
        if self.progress.cancel.isEnabled():
            self.progress.label.setText(f"Calculating {done:,} / {total:,}{left}")

    def _done(self, job):
        added = self.runner.added
        self.progress.hide()
        self.composition.set_calculating(False)
        if job.state == "error":
            self.notify("error", job.error or "The calculation failed.")
            return
        cancelled = job.state == "cancelled"
        if self.runner.first_id is not None:
            self._jump_to(self.runner.first_id)
        st = self.table.model.store
        failed = sum(1 for e in st.errors[self._first_new:] if e)
        msg = f"{added:,} composition(s) calculated" + (" (cancelled)" if cancelled else "")
        if failed:
            msg += f"; {failed:,} could not be evaluated (see Calculation details)"
        self.notify("warning" if cancelled or failed else "success", msg + ".")

    def cancel_calculation(self):
        if self.runner.running:
            self.progress.cancel.setEnabled(False)
            self.progress.label.setText("Cancelling…")
            self.runner.cancel()

    def _add_rows(self, rows: list[ResultRow], select_first: bool):
        rng = self.table.model.append_rows(rows, self.options())
        self._update_status()
        if select_first and len(rng):
            self._jump_to(rng.start)

    def _jump_to(self, row_id: int):
        """Show the page holding store row ``row_id`` and load it into Calculation details."""
        m = self.table.model
        if not m.store.is_alive(row_id):
            return
        pos = m.position_of(row_id)
        if pos < 0:
            return
        m.set_page(pos // m.page_size)
        self.show_details(StoredRow(m.store, row_id))

    def show_details(self, row):
        """Embedded Calculation details for a result row (double click)."""
        if row is None:
            self.details.show_row(None, has_results=bool(self.table.model.store.n_alive))
            return
        if isinstance(row, StoredRow):
            self._details_version = row.store.version
            row = row.materialize()
        self.details.show_row(row)

    def _check_details(self):
        row = self.details.row
        st = self.table.model.store
        if row is not None:
            rid = getattr(row, "row_id", None)
            if rid is not None and (not st.is_alive(rid) or getattr(self, "_details_version", st.version) != st.version):
                self.details.show_row(None, has_results=bool(st.n_alive))
        elif self.details.has_results != bool(st.n_alive):
            # empty state follows the table: "No alloy to show yet" <-> "No alloy selected"
            self.details.show_row(None, has_results=bool(st.n_alive))
        self._update_status()

    # ------------------------------------------------------------------ table actions
    def delete_rows(self):
        """Clear the results table.

        The toolbar's trash button is "Clear table" (tooltip in 21_dark_mode_fullscreen_tooltips),
        so it empties the table outright rather than acting on the selection, and it does so
        immediately - no confirmation dialog.  The composition panel is left untouched: only the
        table's rows go, which also resets its filters, page and page size through ``set_rows``.
        """
        if not self.table.model.store.n_alive:
            return
        self.table.model.clear()
        self.details.show_row(None, has_results=False)
        self._update_status()

    def edit_filters(self):
        dlg = FilterDialog(self.table.model.filters, self)
        if dlg.exec():
            self.table.model.set_filters(dlg.result_filters)
            self.table.set_filter_active(bool(dlg.result_filters))
            self.details.show_row(None, has_results=bool(self.table.model.store.n_alive))
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
        if not len(rows):
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
        if not len(rows):
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
            if len(rows) and self.worker is None and QMessageBox.question(
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
        sources, names = [r.source for r in rows], [r.name for r in rows]
        comps, envs = [r.input_amounts for r in rows], [r.variables for r in rows]
        self.table.model.clear()
        self.details.show_row(None)
        self.calculate(sources, names, comps, envs)

    def open_details(self, row):
        """Calculation details in a separate window (row context menu)."""
        if row is not None:
            if isinstance(row, StoredRow):
                row = row.materialize()
            dlg = AlloyDetailsDialog(row, self)
            dlg.exec()
            dlg.deleteLater()

    def show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()
        dlg.deleteLater()

    def closeEvent(self, e):
        self.settings.setValue("page_size", self.table.model.page_size)
        if self.runner.job is not None:
            self.runner.job.cancel()
            self.runner.job.wait(2.0)
        self.jobs.shutdown()          # no worker process outlives the window
        super().closeEvent(e)


_ = DEFAULT_COLUMNS
