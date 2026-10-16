"""Main window (Figma 'DARK MODE FULLSCREEN', node 341:33323 - formerly 170:11154)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QActionGroup, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QMainWindow, QMessageBox, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..core.engine import DEFAULT_TCRIT_FRACTION, Engine, default_engine
from ..core.export import CLIPBOARD_MAX_ROWS, XLSX_MAX_ROWS, write_records, write_tsv
from ..core.jobs import CalculationJob, CalculationService, JobInput
from ..core.limits import HARD_LIMIT, capacity_problem
from ..core.recipes import RecalcRecipe
from ..core.repository import RepositoryError, ResultRecord, ResultRepository, user_message
from ..core.results import DEFAULT_COLUMNS, COLUMN_BY_KEY, ResultRow, table_tsv
from ..core.spreadsheet import SpreadsheetError, read_compositions
from . import icons
from .theme import (ANALYSIS_WIDE_MIN, COMPOSITION_PANEL_MIN, COMPOSITION_PANEL_WIDTH, CONTENT_MARGIN_BOTTOM,
                    CONTENT_MARGIN_TOP, CONTENT_MARGIN_X, DETAILS_PANEL_WIDTH, ELEMENT_PANEL_MIN, ELEMENT_PANEL_WIDTH,
                    PANEL_GAP, THEME, TOP_ROW_HEIGHT, stylesheet)
from .widgets.common import InlineNotification
from . import system_theme, win_titlebar
from .preferences import Preferences
from ..core.analysis import state as AS
from .analysis.controller import AnalysisController
from .analysis.panel import AnalysisPanel
from .analysis.widgets import stylesheet_rules as analysis_rules
from .analysis.workspace import AnalysisWorkspace
from .widgets.composition_panel import CompositionPanel
from .widgets.dialogs import (AboutDialog, AlloyDetailsDialog, ChoiceDialog, ColumnsDialog, FilterDialog,
                              ImportReportDialog, SettingsDialog)
from .widgets.element_panel import ElementPanel
from .widgets.header import AppHeader
from .widgets.layouts import UpperPanels
from .widgets.menu import CarbonMenu, carbonize_popups
from .widgets.results_table import PAGE_SIZES, ResultsTable, StickyHeader, build_export_menu, update_export_menu
from .widgets.scroll import MainScrollArea
from .worker import ExportTask, JobRunner

APP_ICON = Path(__file__).resolve().parent / "icons" / "logo_icon.ico"
THEME_LABELS = (("system", "System default"), ("light", "Light"), ("dark", "Dark"))

_SHEET_CACHE: dict[str, str] = {}


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine | None = None, settings: QSettings | None = None):
        super().__init__()
        self.engine = engine or default_engine()
        self.settings = settings or QSettings("MDL", "HEA Calculator")
        self.prefs = Preferences(self.settings, self)
        self.os_theme = system_theme.SystemThemeWatcher(self)
        self.os_theme.changed.connect(self._os_scheme_changed)
        self.annealing: float | None = self.settings.value("annealing", None, float) if self.settings.contains(
            "annealing") else None
        self.fraction = float(self.settings.value("tcrit_fraction", DEFAULT_TCRIT_FRACTION))
        # The calculation dataset lives in a session SQLite database (core/repository.py); the table
        # is a page-sized view of it.  CPU-bound batches run in worker processes (core/jobs.py) whose
        # results go to the repository's single writer; the runner refreshes the view at 10 Hz.
        self.repo = ResultRepository(self.engine)
        self.jobs = CalculationService(channel=self.repo.writer.inbox)   # workers deliver to the writer
        self.jobs.scratch_dir = str(self.repo.session_dir)
        QApplication.instance().aboutToQuit.connect(self.shutdown)   # also when quit without a close
        self._job_queue: list = []          # recalculation: one job per stored run, run in sequence
        self._pending_delete: tuple[int, int] | None = None
        self._batch_added = 0
        self._batch_failed = 0
        self._batch_first: int | None = None
        self._details_id: int | None = None
        self._export_job: dict | None = None
        self._closed = False
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
        self.header.help_requested.connect(lambda: self.show_help("home"))
        root.addWidget(self.header)
        # calculation / export progress lives in the UI shell header (stable geometry)
        self.progress = self.header.progress
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
        self.composition = CompositionPanel(self.engine.data, engine=self.engine)
        self.composition.set_total_mass(self.prefs.total_mass)
        # Analysis (replaces Calculation details): one controller shared by the embedded panel and the
        # in-window workspace (docs/analysis-redesign/ANALYSIS_RESPONSIVE_LAYOUT.md section 5).
        self.analysis_ctl = AnalysisController(self.repo, None, self.engine, self)
        self.analysis_ctl.batch_mass = self.prefs.total_mass             # Mass (… g batch) in Analysis
        self.prefs.total_mass_changed.connect(self.analysis_ctl.set_batch_mass)
        self._restore_analysis_tabs()
        self.analysis_ctl.state_changed.connect(self._remember_analysis_tabs)
        self.analysis = AnalysisPanel(self.analysis_ctl)
        self.details = self.analysis                 # former name, kept for tools and tests
        top_w = UpperPanels([(self.elements, ELEMENT_PANEL_WIDTH, ELEMENT_PANEL_MIN, ELEMENT_PANEL_WIDTH),
                             (self.composition, COMPOSITION_PANEL_WIDTH, COMPOSITION_PANEL_MIN,
                              COMPOSITION_PANEL_WIDTH),
                             (self.details, DETAILS_PANEL_WIDTH, ANALYSIS_WIDE_MIN, None)],
                            TOP_ROW_HEIGHT, PANEL_GAP)
        self.top_row = top_w
        content.addWidget(top_w)
        table_col = QVBoxLayout()
        table_col.setSpacing(0)
        self.notification = InlineNotification()
        self.progress.cancel.clicked.connect(self.cancel_calculation)
        self.table = ResultsTable(engine=self.engine, repo=self.repo)
        self.analysis_ctl.model = self.table.model
        self.runner = JobRunner(self.jobs, self.table.model, self)
        self.exporter = ExportTask(self)
        self.exporter.progress.connect(self._export_progress)
        self.exporter.finished.connect(self._export_done)
        self.runner.progress.connect(self._progress)
        self.runner.finished.connect(self._done)
        table_col.addWidget(self.notification)
        table_col.addWidget(self.table, 1)
        content.addLayout(table_col, 1)
        # One primary vertical scrolling context below the fixed header.  The results section
        # is at least as tall as its current page (ResultsTable.natural_height) and otherwise fills
        # the remaining viewport height, so with few rows nothing scrolls and with many rows the
        # main area - never the table - scrolls.
        self.content = content_w
        self.scroll = MainScrollArea()
        self.scroll.setWidget(content_w)
        # Calculation layout and the expanded Analysis workspace are two pages of the same window
        # (presentation only; the app header stays).
        self.pages = QStackedWidget()
        self.pages.addWidget(self.scroll)
        self.workspace = AnalysisWorkspace(self.analysis_ctl)
        self.workspace.setMinimumSize(1200, 640)
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setObjectName("ContentScroll")
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        from .widgets.scroll import thin_scrollbars
        thin_scrollbars(self.workspace_scroll)
        self.workspace_scroll.setWidget(self.workspace)
        self.pages.addWidget(self.workspace_scroll)
        root.addWidget(self.pages, 1)
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
        self.composition.copy_text.connect(self._copy_text)
        self.composition.cancel_requested.connect(self.cancel_calculation)
        self.composition.total_mass_committed.connect(self.prefs.set_total_mass)
        self.prefs.total_mass_changed.connect(self.composition.set_total_mass)
        self.composition.set_service(self.jobs)
        # Batch modes calculate in the worker pool: start it in the background as soon as one is chosen
        # (measured: a cold pool start overlapping the first batch raised its longest event-loop gap
        # from ~80 ms to ~140 ms); single compositions never need it.
        self.composition.mode_changed.connect(
            lambda mode: self.jobs.warm_up() if mode in ("sweep", "expression") and not self._closed else None)
        # table: double click -> the active composition of Analysis; row menu -> separate details window
        self.table.view.details_requested.connect(self.show_details)
        self.table.view.window_requested.connect(self.open_details)
        self.table.view.rows_removed.connect(self._check_details)
        self.table.view.removed_ids.connect(self.analysis_ctl.results_removed)
        # Analysis wiring
        ctl = self.analysis_ctl
        self.analysis.expand_requested.connect(lambda: self.set_expanded(True))
        ctl.expand_requested.connect(self.set_expanded)
        self.workspace.back_requested.connect(lambda: self.set_expanded(False))
        ctl.show_in_table.connect(self.show_in_table)
        ctl.report_requested.connect(self.export_report)
        ctl.export_requested.connect(self.export_analysis)
        ctl.help_requested.connect(self.show_help)
        self.runner.progress.connect(lambda *_: ctl.rows_committed(self.runner.run_id))
        self._expand_shortcut = QShortcut(QKeySequence("Ctrl+Shift+E"), self)
        self._expand_shortcut.activated.connect(lambda: self.set_expanded(self.pages.currentIndex() == 0))
        self.table.delete_requested.connect(self.delete_rows)
        self.table.filter_requested.connect(self.edit_filters)
        self.table.columns_requested.connect(self.edit_columns)
        self.table.copy_requested.connect(self.copy_table)
        self.table.copy_page_requested.connect(self.copy_visible_rows)
        self.table.export_requested.connect(self.export)
        self.table.model.page_changed.connect(self._check_details)
        self.table.model.state_changed.connect(self._update_status)
        # restore table preferences
        cols = self.settings.value("columns", None)
        if isinstance(cols, list) and all(c in COLUMN_BY_KEY for c in cols) and "name" in cols:
            self.table.model.set_keys(cols)
        size = int(self.settings.value("page_size", 100))
        if size in PAGE_SIZES:
            self.table.pagination.size_box.setCurrentIndex(PAGE_SIZES.index(size))
        carbonize_popups(self)       # text-field context menus and dropdown lists use the Carbon popups
        win_titlebar.install(QApplication.instance(), lambda: THEME.name, lambda: THEME.tokens)
        THEME.changed.connect(self.apply_theme)
        # the effective theme was resolved at start-up (app.py) from this preference; from now on it follows
        # the user's choice and - with System default - the OS colour scheme
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
        build_export_menu(exp, self.export, self.copy_table, self.copy_visible_rows)
        exp.aboutToShow.connect(lambda: update_export_menu(exp, bool(self.table.model.filters)))
        c = self.file_menu.add_action("Copy table", self.copy_table, shortcut="Ctrl+Shift+C")
        self.file_menu.addSeparator()
        self.file_menu.add_action("Calculation settings…", self.edit_settings)
        self.file_menu.addSeparator()
        # one Help action (the header's Help icon and F1 run the same command: Documentation Home)
        hlp = self.file_menu.add_action("Help", lambda: self.show_help("home"), shortcut="F1")
        self.file_menu.add_action("About HEA Calculator", self.show_about)
        self.file_menu.addSeparator()
        q = self.file_menu.add_action("Exit", self.close, shortcut="Ctrl+Q")
        for act in (a, c, q, hlp):
            self.addAction(act)
        # Theme: only in the header's Theme action (no duplicate in File)
        self.theme_menu = CarbonMenu(parent=self)
        group = QActionGroup(self)
        group.setExclusive(True)
        pref = self.prefs.theme
        for name, label in THEME_LABELS:
            act = self.theme_menu.add_action(label, lambda n=name: self.set_theme(n), checkable=True,
                                             checked=pref == name)
            act.setData(name)
            group.addAction(act)
        self.theme_actions = group

    def set_theme(self, name: str):
        """Store the theme *preference* (system / light / dark) and apply the effective theme."""
        if name not in ("system", "light", "dark"):
            return
        self.prefs.set_theme(name)
        self._resolve_theme()

    def _resolve_theme(self, os_value: str | None = None):
        THEME.set_theme(system_theme.resolve(self.prefs.theme, os_value))
        self._sync_theme_actions()

    def _os_scheme_changed(self, scheme: str):
        """Windows switched light / dark: follow it only under System default (the preference is untouched)."""
        if self.prefs.theme == "system":
            self._resolve_theme(scheme)

    def _sync_theme_actions(self):
        pref = self.prefs.theme
        for act in self.theme_actions.actions():
            act.setChecked(act.data() == pref)

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
            sheet = stylesheet(lambda name, token: icons.file_url(name, token)) + analysis_rules(THEME.tokens)
            _SHEET_CACHE[THEME.name] = sheet
        self.setStyleSheet(sheet)
        self._sync_theme_actions()
        self.header.set_effective_theme(THEME.name)
        themer = win_titlebar.themer()
        if themer is not None:
            themer.apply_all()                  # every native caption follows the effective theme
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
        # The reference toolbar carries no standing label - the paginator already reports the
        # range - so this slot is reserved for filter / background sort state and cell info on hover.
        if m.pending:
            what = "Sorting" if m.sort_key and not m.filters else "Filtering" if not m.sort_key else \
                "Filtering and sorting"
            text = f"{what} {m.total_count():,} results…"
        elif m.filters:
            text = f"· filter active ({m.view_count():,} shown)"
        else:
            text = ""
        if self.table.status.text() != text:
            self.table.status.setText(text)

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

    def calculate(self, source, names=None, comps=None, envs=None, meta: dict | None = None):
        """Calculate compositions into a new run of the result repository.  ``comps`` is a list, or a
        recipe (``core/recipes.py``) generated and calculated in the worker processes."""
        if self.runner.running:
            self.notify("warning", "A calculation is already running.")
            return
        self.notification.dismiss()
        self._job_queue = []
        self._batch_added = self._batch_failed = 0
        self._batch_first = None
        if not callable(comps) and len(comps) == 1:
            res = self.engine.calculate(comps[0], **self.options())
            src = source[0] if isinstance(source, list) else source
            row = ResultRow(names[0], comps[0], res, src, envs[0] if envs else {})
            try:
                rng = self.table.model.append_rows([row], self.options(), mode=src, source=meta)
            except (RepositoryError, OSError) as exc:
                self.notify("error", str(exc) if isinstance(exc, RepositoryError) else user_message(exc))
                return
            self._update_status()
            if self.analysis_ctl.state.active is None:
                self.analysis_ctl.apply(AS.switch_context, AS.COMPOSITION)
            self._jump_to(rng.start)
            self.analysis_ctl.run_finished(None)
            if not res.ok:
                self.notify("error", res.error)
            return
        if callable(comps):
            rm = comps.run_meta()
            data = JobInput(source, (), comps, (), self.options())
            label, expected = "Generating compositions…", comps.estimate()
        else:
            elements: list[str] = []
            for c in comps:
                for el in c:
                    if el not in elements:
                        elements.append(el)
            mode = source if isinstance(source, str) else (source[0] if source else "single")
            rm = {"mode": mode, "elements": elements, "axes": [], "source": {}}
            data = JobInput(source, names, comps, envs, self.options())
            label, expected = f"Calculating {len(comps):,} compositions…", len(comps)
        if meta:
            rm["source"] = {**rm.get("source", {}), **meta}
        self._start_job(data, rm, expected, label)

    def _start_job(self, data: JobInput, rm: dict, expected: int | None, label: str) -> bool:
        recipe = data.compositions if callable(data.compositions) else None
        # at.% / wt.% sweeps count exactly; ratio / mass sweeps and expressions give upper bounds
        exact = recipe is None or getattr(recipe, "unit", None) in ("at", "wt")
        n = expected or 0
        problem = capacity_problem(n if exact else min(n, HARD_LIMIT), self.repo.session_dir)
        if problem:
            self.notify("error", problem)
            self._finish_batch(cancelled=True)
            return False
        try:
            run_id = self.repo.create_run(rm["mode"], settings=self.options(), source=rm.get("source"),
                                          axes=rm.get("axes"), elements=rm.get("elements"), expected=expected)
        except Exception as exc:                      # noqa: BLE001 - storage unavailable
            self.notify("error", user_message(exc))
            self._finish_batch(cancelled=True)
            return False
        self._cancelling = False
        self.progress.set_cancellable(False)          # a calculation is cancelled in Composition setup
        self.progress.set_progress(label.rstrip("…"), 0, 0, None)
        self.progress.cancel.setEnabled(True)
        self.progress.show()
        self.composition.set_calculating(True)
        self.runner.start(CalculationJob(data, self.engine), run_id)
        return True

    def _progress(self, done: int, total: int, eta: float):
        if not getattr(self, "_cancelling", False):
            verb = "Recalculating" if self._pending_delete else "Calculating"
            self.progress.set_progress(verb, done, total, eta)

    def _done(self, job):
        r = self.runner
        pc = getattr(job, "plan_counts", None)
        if r.run_id is not None and pc and len(pc) > 4:
            try:                                  # expression generation facts for Analysis (block restriction)
                self.repo.update_run_source(r.run_id, {"skipped": pc[1], "duplicates": pc[2], "combinations": pc[3],
                                                       "duplicates_by_block": {str(k): v for k, v in pc[4].items()}})
            except Exception:                     # noqa: BLE001 - informative only
                pass
        self.analysis_ctl.run_finished(r.run_id)
        info = self.repo.get_run(r.run_id) if r.run_id is not None else None
        self._batch_added += r.added
        self._batch_failed += info.errors if info else 0
        if self._batch_first is None and r.first_id is not None:
            self._batch_first = r.first_id
        cancelled = job.state == "cancelled"
        if r.storage_error:
            self._finish_batch(cancelled=True)
            self.notify("error", f"{r.storage_error} The calculation was stopped; {self._batch_added:,} "
                                 "calculated result(s) were kept.")
            return
        if job.state == "error":
            self._finish_batch(cancelled=True)
            self.notify("error", job.error or "The calculation failed.")
            return
        if self._job_queue and not cancelled:
            if self._next_job():
                return
        self._finish_batch(cancelled)
        if self._batch_first is not None:
            self._jump_to(self._batch_first)
        msg = f"{self._batch_added:,} composition(s) calculated" + (" (cancelled)" if cancelled else "")
        if self._batch_failed:
            msg += f"; {self._batch_failed:,} could not be evaluated (open one in Analysis to see the reason)"
        self.notify("warning" if cancelled or self._batch_failed else "success", msg + ".")

    def _finish_batch(self, cancelled: bool):
        self._job_queue = []
        self.progress.hide()
        self.composition.set_calculating(False)
        if self._pending_delete is not None:
            lo, hi = self._pending_delete           # recalculation: the superseded rows go now
            self._pending_delete = None
            try:
                self.repo.clear_range(lo, hi)
            except Exception:                         # noqa: BLE001 - hidden rows; the session file goes anyway
                pass

    def cancel_calculation(self):
        if self.exporter.running:
            self.progress.cancel.setEnabled(False)
            self.progress.label.setText("Cancelling…")
            self.exporter.cancel()
            return
        if self.runner.running:
            self._job_queue = []
            self._cancelling = True
            self.progress.cancel.setEnabled(False)
            self.progress.label.setText("Cancelling…")
            self.composition.clear_btn.setEnabled(False)
            self.runner.cancel()

    def _add_rows(self, rows: list[ResultRow], select_first: bool):
        rng = self.table.model.append_rows(rows, self.options())
        self._update_status()
        if select_first and len(rng):
            self._jump_to(rng.start)

    def _jump_to(self, row_id: int, analyse: bool = True):
        """Show the page holding result ``row_id`` (and make it the active composition of Analysis)."""
        m = self.table.model
        if not m.view.is_alive(row_id):
            return
        pos = m.position_of(row_id)
        if pos < 0:
            return
        m.set_page(pos // m.page_size)
        if analyse:
            rec = self.repo.get_result(row_id)
            if rec is not None:
                self.show_details(rec)

    def show_details(self, row):
        """The active composition of Analysis (double click, single calculation).  A stored record is
        reproduced into a full engine result once, by its stable id - never by its row on screen."""
        self.analysis.set_has_results(bool(self.table.model.total_count()))
        if row is None:
            self._details_id = None
            self.analysis_ctl.set_active(None)
            return
        if isinstance(row, ResultRecord):
            self._details_id = row.id
            self.analysis_ctl.set_active(row.id)

    def _check_details(self):
        m = self.table.model
        total = m.total_count()
        self.analysis.set_has_results(bool(total))
        st = self.analysis_ctl.state
        if st.active is not None and st.active_gone is None and not m.view.is_alive(st.active):
            self.analysis_ctl.results_removed([st.active])
        self._update_status()

    # ------------------------------------------------------------------ table actions
    def delete_rows(self):
        """Clear the results table.

        The toolbar's trash button is "Clear table" (tooltip in 21_dark_mode_fullscreen_tooltips): it
        deletes every result of the table from the dataset (in the background), immediately - no
        confirmation dialog.  The composition panel is left untouched, and so are filters and sort.
        """
        m = self.table.model
        if not m.total_count():
            return
        lo, hi = m.view.lo, m.view.hi
        m.clear()
        self.analysis_ctl.table_cleared(lo=lo, hi=hi)
        self.analysis.set_has_results(False)
        self._update_status()

    def edit_filters(self):
        dlg = FilterDialog(self.table.model.filters, self)
        if dlg.exec():
            self.table.model.set_filters(dlg.result_filters)
            self.table.set_filter_active(bool(dlg.result_filters))
            self.analysis_ctl.table_filter_changed()
            self._update_status()
        dlg.deleteLater()

    def edit_columns(self):
        dlg = ColumnsDialog(self.table.model.keys, self)
        if dlg.exec():
            keys = dlg.selected()
            self.table.model.set_keys(keys)
            self.settings.setValue("columns", keys)
        dlg.deleteLater()

    INLINE_ROWS = 2000          # exports / copies up to this size run at once (≈ 0.1 s); larger in a process

    def _busy(self) -> bool:
        if self.runner.running or self.exporter.running:
            self.notify("warning", "Wait for the running calculation or export to finish.")
            return True
        return False

    def copy_table(self):
        """Copy every row of the (filtered, sorted) table with the visible columns."""
        m = self.table.model
        n = m.view_count()
        if not n:
            self.notify("info", "The table is empty.")
            return
        if n > CLIPBOARD_MAX_ROWS:
            self.notify("warning", f"The table has {n:,} rows; the clipboard takes at most {CLIPBOARD_MAX_ROWS:,} "
                                   "(one Excel worksheet). Export the results instead.")
            return
        if n <= self.INLINE_ROWS:
            QGuiApplication.clipboard().setText(table_tsv(list(m.view_rows), m.keys))
            self.notify("success", f"Copied {n:,} row(s) × {len(m.keys)} columns (paste into Excel).", 4000)
            return
        if self._busy():
            return
        path = str(self.repo.session_dir / f"clipboard-{id(self)}.tsv")
        self._start_export(m.view.export_spec(filtered=True), path, "tsv", {"keys": list(m.keys)}, n,
                           f"Copying {n:,} rows…", {"kind": "copy", "rows": n, "cols": len(m.keys)})

    def copy_visible_rows(self):
        """Copy the rows of the current page only (what is on screen)."""
        m = self.table.model
        rows = m.page_rows()
        if not rows:
            self.notify("info", "The table is empty.")
            return
        QGuiApplication.clipboard().setText(table_tsv(rows, m.keys))
        self.notify("success", f"Copied {len(rows):,} visible row(s) × {len(m.keys)} columns.", 4000)

    def _copy_text(self, tsv: str, what: str):
        QGuiApplication.clipboard().setText(tsv)
        self.notify("success", f"Copied the {what} (paste into Excel).", 4000)

    def _copy_generated(self, tsv: str):
        QGuiApplication.clipboard().setText(tsv)
        n = max(len(tsv.strip().splitlines()) - 1, 0)
        self.notify("success", f"Copied {n:,} generated composition(s) (paste into Excel).", 4000)

    def export(self, fmt: str, scope: str = "all"):
        """Export the dataset: ``all`` results (filters ignored) or the ``filtered`` results, both in
        the table's current sort order.  Never just the visible page."""
        m = self.table.model
        if m.pending:
            self.notify("info", "The table is still being sorted or filtered; export when it has finished.")
            return
        filtered = scope == "filtered" and bool(m.filters)
        spec = m.view.export_spec(filtered)
        n = spec["count"]
        if not n:
            self.notify("info", "Nothing to export.")
            return
        if fmt == "xlsx" and n > XLSX_MAX_ROWS:
            sheets = -(-n // XLSX_MAX_ROWS)
            dlg = ChoiceDialog("Export results", "Excel row limit",
                               f"<b>{n:,}</b> results exceed one Excel worksheet ({XLSX_MAX_ROWS:,} rows).<br>"
                               f"Export them as CSV, or split them over {sheets} worksheets of one workbook.",
                               [("cancel", "Cancel"), ("sheets", f"Split into {sheets} worksheets"),
                                ("csv", "Export as CSV")], self)
            dlg.exec()
            choice = dlg.choice
            dlg.deleteLater()
            if choice in (None, "cancel"):
                return
            if choice == "csv":
                fmt = "csv"
        flt = "Excel workbook (*.xlsx)" if fmt == "xlsx" else "CSV (*.csv)"
        default = f"hea_results{'_filtered' if filtered else ''}.{fmt}"
        path, _ = QFileDialog.getSaveFileName(self, "Export results", default, flt)
        if not path:
            return
        view = m.view
        elements = self.repo.elements_of(self.repo.run_ids_in(view.lo, view.hi))
        notes = {"M6/M7 temperature": self._temperature_note(),
                 "Scope": "filtered results" if filtered else "all results"}
        if filtered:
            notes["Filters"] = "; ".join(repr(f) for f in m.filters)
        if n <= self.INLINE_ROWS:
            try:
                n = write_records(view.export_rows(filtered), path, elements, notes=notes)
            except Exception as exc:  # noqa: BLE001 - report any I/O problem to the user
                self.notify("error", f"Export failed: {exc}")
                return
            self.notify("success", f"Exported {n:,} rows to {Path(path).name}.")
            return
        if self._busy():
            return
        self._start_export(spec, path, "file", {"elements": elements, "notes": notes}, n,
                           f"Exporting {n:,} results…", {"kind": "export", "rows": n, "path": path})

    def _start_export(self, spec: dict, path: str, kind: str, payload: dict, total: int, label: str, job: dict):
        self._export_job = {**job, "path": path, "total": total}
        verb = "Copying" if job["kind"] == "copy" else "Exporting"
        self.progress.set_cancellable(True)           # exports have no other cancel control
        self.progress.set_progress(verb, 0, max(1, total), None)
        self.progress.cancel.setEnabled(True)
        self.progress.show()
        self.exporter.start(spec, path, kind, payload)

    def _export_progress(self, n: int):
        job = self._export_job
        if job is None or not self.progress.cancel.isEnabled():
            return
        verb = "Copying" if job["kind"] == "copy" else "Exporting"
        self.progress.set_progress(verb, n, job["total"], None)

    def _export_done(self, status: str, value):
        job, self._export_job = self._export_job, None
        if not self.runner.running:
            self.progress.hide()
        if job is None:
            return
        path = Path(job["path"])
        if status == "ok" and job["kind"] == "copy":
            try:
                with path.open(encoding="utf-8", newline="") as fh:      # keep the CR LF row breaks
                    QGuiApplication.clipboard().setText(fh.read())
            finally:
                path.unlink(missing_ok=True)
            self.notify("success", f"Copied {value:,} row(s) × {job['cols']} columns (paste into Excel).", 4000)
        elif status == "ok":
            self.notify("success", f"Exported {value:,} rows to {path.name}.")
        else:
            path.unlink(missing_ok=True)
            if status == "cancelled":
                self.notify("warning", "Export cancelled; no file was written.")
            else:
                self.notify("error", f"Export failed: {value}")

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
        self.calculate("import", names, comps, [{} for _ in comps],
                       meta={"file": Path(path).name, "layout": res.layout, "skipped_rows": len(res.errors)})

    def edit_settings(self):
        dlg = SettingsDialog(self.annealing, self.fraction, self)
        if dlg.exec():
            self.annealing, self.fraction = dlg.annealing, dlg.fraction
            if self.annealing is None:
                self.settings.remove("annealing")
            else:
                self.settings.setValue("annealing", self.annealing)
            self.settings.setValue("tcrit_fraction", self.fraction)
            n = self.table.model.total_count()
            if n and self.worker is None and QMessageBox.question(
                    self, "Recalculate results",
                    f"Recalculate the {n:,} existing result(s) with the new temperature setting?") \
                    == QMessageBox.StandardButton.Yes:
                self.recalculate_all()
            else:
                self.notify("info", f"M6/M7 temperature: {self._temperature_note()}. New calculations use it.")
        dlg.deleteLater()

    def recalculate_all(self):
        """Re-run every result of the table through the engine with the current settings: one job
        per stored run, reading the stored inputs (names, sources, design coordinates) from the
        database in the workers.  The superseded rows are hidden at once and deleted afterwards."""
        m = self.table.model
        if not m.total_count() or self.runner.running:
            return
        view = m.view
        runs = [self.repo.get_run(rid) for rid in self.repo.run_ids_in(view.lo, view.hi)]
        lo, hi = m.hide_all()
        self.analysis_ctl.table_cleared(recalculated=True, lo=lo, hi=hi)
        queue = []
        for info in runs:
            if info is None or info.first_id is None:
                continue
            first, last = max(info.first_id, lo), min(info.last_id, hi)
            cols = tuple(a["col"] for a in info.axes if a.get("col"))
            recipe = RecalcRecipe(str(self.repo.db_path), info.run_id, first, last, cols)
            rm = {"mode": info.mode, "elements": info.elements, "axes": info.axes,
                  "source": {**info.source, "recalculated_from": info.run_id}}
            queue.append((recipe, rm))
        self.notification.dismiss()
        self._batch_added = self._batch_failed = 0
        self._batch_first = None
        self._pending_delete = (lo, hi)
        self._job_queue = queue
        if not self._next_job():
            self._finish_batch(cancelled=True)

    def _next_job(self) -> bool:
        while self._job_queue:
            recipe, rm = self._job_queue.pop(0)
            data = JobInput("recalc", (), recipe, (), self.options())
            if self._start_job(data, rm, recipe.estimate(), "Recalculating…"):
                return True
        return False

    def open_details(self, row):
        """Composition analysis of one result in a separate window (row context menu).  The window
        holds a snapshot of the result, so it stays valid if the stored row is removed later."""
        if row is not None:
            info = None
            if isinstance(row, ResultRecord):
                info = self.repo.get_run(row.run_id)
                row = row.materialize()
            dlg = AlloyDetailsDialog(row, self, info=info)
            dlg.exec()
            dlg.deleteLater()

    # ------------------------------------------------------------------ Analysis
    def _restore_analysis_tabs(self) -> None:
        """The last viewed Composition / Collection tabs and Model details model (preferences).  A tab whose
        content is unavailable (no results yet) keeps the preference and shows its empty state."""
        p = self.prefs
        comp = str(p.get("analysis/composition_tab", "overview"))
        coll = str(p.get("analysis/collection_tab", "overview"))
        model = str(p.get("analysis/model", "M1"))
        from ..core.engine import MODEL_KEYS
        self.analysis_ctl.apply(AS.update, comp_tab=comp if comp in AS.COMP_TABS else "overview",
                                coll_tab=coll if coll in AS.COLL_TABS else "overview",
                                model=model if model in MODEL_KEYS else "M1")

    def _remember_analysis_tabs(self, old, new) -> None:
        if old is None or (old.comp_tab, old.coll_tab, old.model) != (new.comp_tab, new.coll_tab, new.model):
            self.prefs.put("analysis/composition_tab", new.comp_tab)
            self.prefs.put("analysis/collection_tab", new.coll_tab)
            self.prefs.put("analysis/model", new.model)

    def set_expanded(self, on: bool):
        """Expand analysis / Back to calculation: a page swap, nothing else (state is shared)."""
        if on and not self.table.model.total_count():
            return
        on = bool(on)
        if (self.pages.currentIndex() == 1) == on:
            return
        self.analysis_ctl.apply(AS.set_expanded, on)
        self.pages.setCurrentIndex(1 if on else 0)
        if on:
            self.workspace.focus_title()
        else:
            self.analysis.expand_btn.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_in_table(self, ids):
        """Analysis -> table: jump to one result; for several, check them and say so (never filters silently)."""
        ids = [int(i) for i in ids]
        if not ids:
            return
        self.set_expanded(False)
        if len(ids) == 1:
            self._jump_to(ids[0], analyse=False)
            return
        # several: an explicit, visible id filter (removable in the Filter dialog), never a silent change
        from ..core.analysis.idsets import id_table
        from ..core.results import IdSetFilter
        try:
            name = id_table(self.repo, ids)
        except Exception as exc:                      # noqa: BLE001 - storage problem, reported
            self.notify("error", user_message(exc))
            return
        m = self.table.model
        filters = [f for f in m.filters if not isinstance(f, IdSetFilter)] + [IdSetFilter(name, frozenset(ids))]
        m.set_filters(filters)
        self.table.set_filter_active(True)
        self.analysis_ctl.table_filter_changed()
        self._update_status()
        self.notify("info", f"The table shows the {len(ids):,} results selected in Analysis. Clear the filter in "
                            "Filter results to show all results.", 8000)

    def export_report(self, kind: str):
        from .analysis.report_ui import export_report, print_composition
        if kind == "print":
            print_composition(self)
            return
        export_report(self, kind)

    def export_analysis(self, kind: str):
        from .analysis.report_ui import export_analysis_data
        export_analysis_data(self, kind)

    def show_help(self, page: str, anchor: str = ""):
        from .analysis.help import open_help
        legacy = {"model-coverage": "models", "collection-analysis": "collections"}
        open_help(legacy.get(page, page), self)

    def show_about(self):
        dlg = AboutDialog(self)
        dlg.exec()
        dlg.deleteLater()

    def shutdown(self):
        """Stop the calculation, the export process, every worker process and the session database
        (deleted).  Idempotent: called on close and on application quit."""
        if self._closed:
            return
        self._closed = True
        try:
            self.settings.setValue("page_size", self.table.model.page_size)
        except RuntimeError:
            pass
        self.runner._timer.stop()
        if self.runner.job is not None:
            self.runner.job.cancel()
            self.runner.job.wait(2.0)
        self.exporter.shutdown()
        self.analysis_ctl.close()
        self.jobs.shutdown()          # no worker process outlives the window
        self.table.model.close()
        self.repo.close()

    def closeEvent(self, e):
        self.shutdown()
        super().closeEvent(e)


_ = (DEFAULT_COLUMNS, write_tsv)
