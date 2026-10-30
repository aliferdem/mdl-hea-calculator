"""Main window (Figma 'DARK MODE FULLSCREEN', node 341:33323 - formerly 170:11154)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QMainWindow, QMessageBox, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..core import destructive
from ..core.engine import DEFAULT_TCRIT_FRACTION, Engine, default_engine
from ..core.export import CLIPBOARD_MAX_ROWS, XLSX_MAX_ROWS, write_records, write_tsv
from ..core.jobs import CalculationJob, CalculationService, JobInput
from ..core.limits import HARD_LIMIT, capacity_problem
from ..core.recipes import RecalcRecipe
from ..core.repository import RepositoryError, ResultRecord, ResultRepository, user_message
from ..core.results import DEFAULT_COLUMNS, COLUMN_BY_KEY, ResultRow, table_tsv
from ..core.spreadsheet import SpreadsheetError, read_compositions
from . import icons
from .theme import (qss_tokens, ANALYSIS_STACKED_HEIGHT, ANALYSIS_WIDE_MIN, COMPOSITION_PANEL_MIN, COMPOSITION_PANEL_WIDTH, CONTENT_MARGIN_BOTTOM,
                    CONTENT_MARGIN_TOP, CONTENT_MARGIN_X, DETAILS_PANEL_WIDTH, ELEMENT_PANEL_MIN, ELEMENT_PANEL_WIDTH,
                    PANEL_GAP, THEME, TOP_ROW_HEIGHT, stylesheet)
from . import system_theme, win_titlebar
from .preferences import Preferences
from ..core.analysis import state as AS
from .analysis.controller import AnalysisController
from .analysis.panel import AnalysisPanel
from .analysis.widgets import stylesheet_rules as analysis_rules
from .analysis.workspace import AnalysisWorkspace
from .widgets.composition_panel import CompositionPanel
from .widgets.dialogs import (ChoiceDialog, ColumnsDialog, FilterDialog,
                              ImportReportDialog, SettingsDialog)
from .widgets.element_panel import ElementPanel
from .widgets.header import TitleBar
from .win_chrome import WinChrome
from .widgets.layouts import UpperPanels
from .widgets.menu import CarbonMenu, carbonize_popups
from .widgets.results_table import PAGE_SIZES, ResultsTable, StickyHeader
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
        # The 32 px title bar (+ its 4 px state line) is the window's caption: native behaviour from win_chrome
        self.header = TitleBar(self.file_menu, self.view_menu, edit_menu=self.edit_menu, help_menu=self.help_menu)
        self.titlebar = self.header
        self.header.about_requested.connect(self.show_about)
        self.header.help_requested.connect(lambda: self.show_help("home"))
        self.header.minimize_requested.connect(self.showMinimized)
        self.header.maximize_requested.connect(self.toggle_maximized)
        self.header.close_requested.connect(self.close)
        self.header.top_panels_toggled.connect(lambda: self.set_top_panels_visible(not self.top_panels_visible()))
        self.header.exit_fullscreen_requested.connect(lambda: self.set_fullscreen(False))
        root.addWidget(self.header)
        self.chrome = WinChrome(self, self.header)
        # calculation / export progress lives in the title bar (stable geometry)
        self.progress = self.header.progress
        self.progress_line = self.progress.bar
        content_w = QWidget()
        content_w.setObjectName("AppBody")
        content_w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content = QVBoxLayout(content_w)
        content.setContentsMargins(CONTENT_MARGIN_X, CONTENT_MARGIN_TOP, CONTENT_MARGIN_X, CONTENT_MARGIN_BOTTOM)
        content.setSpacing(PANEL_GAP)
        # Upper area: fixed Elements (578) and Composition setup (457); Analysis takes the rest of the row, from its
        # 454 px minimum (805 px preferred, grown beyond on wider windows - responsive.distribute).  Once Analysis
        # can no longer get its minimum, it moves below the other two (widgets/layouts.UpperPanels).
        self.elements = ElementPanel(self.engine)
        self.composition = CompositionPanel(self.engine.data, engine=self.engine)
        self.composition.set_total_mass(self.prefs.total_mass)
        # Analysis (replaces Calculation details): one controller shared by the embedded panel and the
        # in-window workspace (docs/analysis-redesign/ANALYSIS_RESPONSIVE_LAYOUT.md section 5).
        self.analysis_ctl = AnalysisController(self.repo, None, self.engine, self)
        self.analysis_ctl.batch_mass = self.prefs.total_mass             # Mass (… g batch) in Analysis
        self.prefs.total_mass_changed.connect(self.analysis_ctl.set_batch_mass)
        self._restore_analysis_tabs()
        # Composition space: Step size | Points (the Step heading) is remembered between sessions
        sweep = self.composition.sweep
        sweep.set_discretization(str(self.prefs.get("composition/space_discretization", "step")), convert=False)
        sweep.discretization_changed.connect(lambda m: self.prefs.put("composition/space_discretization", m))
        self.analysis_ctl.state_changed.connect(self._remember_analysis_tabs)
        self.analysis = AnalysisPanel(self.analysis_ctl)
        self.details = self.analysis                 # former name, kept for tools and tests
        # the Analysis slot: the compact panel, or the workspace layout when the slot is wide enough (C4, 2026-10-28)
        from .analysis.workspace import AnalysisDock
        self.analysis_dock = AnalysisDock(self.analysis, self.analysis_ctl)
        self.analysis_dock.layout_changed.connect(self._dock_layout_changed)
        top_w = UpperPanels([(self.elements, ELEMENT_PANEL_WIDTH, ELEMENT_PANEL_MIN, ELEMENT_PANEL_WIDTH),
                             (self.composition, COMPOSITION_PANEL_WIDTH, COMPOSITION_PANEL_MIN,
                              COMPOSITION_PANEL_WIDTH),
                             (self.analysis_dock, DETAILS_PANEL_WIDTH, ANALYSIS_WIDE_MIN, None)],
                            TOP_ROW_HEIGHT, PANEL_GAP, stacked_height=ANALYSIS_STACKED_HEIGHT,
                            titles=["Elements", "Composition setup", "Analysis"])
        self.top_row = top_w
        # each panel header's collapse button (Figma Mode=Collapsed); the choice is kept across sessions
        for i, panel in enumerate((self.elements, self.composition, self.details)):
            btn = getattr(panel, "collapse_btn", None)
            if btn is not None:
                btn.clicked.connect(lambda _c=False, i=i: self.top_row.set_collapsed(i, True))
        top_w.collapse_changed.connect(self._collapse_changed)
        content.addWidget(top_w)
        self._top_visible = True
        table_col = QVBoxLayout()
        table_col.setSpacing(0)
        # messages go to the title bar's status column (HeaderProgress.show_message) - never above the table
        self.progress.cancel.clicked.connect(self.cancel_calculation)
        self.table = ResultsTable(engine=self.engine, repo=self.repo)
        self.analysis_ctl.model = self.table.model
        self.runner = JobRunner(self.jobs, self.table.model, self)
        self.exporter = ExportTask(self)
        self.exporter.progress.connect(self._export_progress)
        self.exporter.finished.connect(self._export_done)
        self.runner.progress.connect(self._progress)
        self.runner.finished.connect(self._done)
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
        self.workspace.setProperty("carbon_layer", 0)       # the in-window workspace: background (ui/surface.py)
        # the workspace page grows with its content; its one vertical scroll is this page's (7.png, §20)
        from .analysis.workspace import WORKSPACE_MIN_WIDTH
        self.workspace.setMinimumWidth(WORKSPACE_MIN_WIDTH)
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

        # wiring: selection ↔ composition
        self.elements.element_toggled.connect(self.composition.element_toggled)
        self.composition.elements_changed.connect(self._composition_elements)
        # setup edits (2026-10-28): the last recorded state of the composition setup; each finished edit that
        # changes it becomes one Undo step (ui/undo.SetupEditCommand)
        self._setup_state = self.composition.undo_state()
        self.composition.edit_committed.connect(self._setup_committed)
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
        self.table.view.details_requested.connect(self._row_activated)
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
        ctl.window_requested.connect(lambda: self.open_analysis_window())
        ctl.export_requested.connect(self.export_analysis)
        ctl.help_requested.connect(self.show_help)
        self.runner.progress.connect(lambda *_: ctl.rows_committed(self.runner.run_id))
        # Ctrl+Shift+E is the View > Expand analysis action's shortcut (one command)
        self.table.delete_requested.connect(self.delete_rows)
        self.table.view.remove_handler = self.remove_results
        self.composition.clear_handler = self.clear_composition
        self.table.filter_requested.connect(self.edit_filters)
        self.table.columns_requested.connect(self.edit_columns)
        self.table.copy_requested.connect(self.copy_table)
        self.table.copy_page_requested.connect(self.copy_visible_rows)
        self.table.export_requested.connect(self.export)
        self.table.model.page_changed.connect(self._check_details)
        self.table.model.state_changed.connect(self._update_status)
        # restore table preferences
        cols = self.settings.value("columns", None)
        if isinstance(cols, list) and "name" in cols:
            # a stored layout keeps every column that still exists and is still offered (2026-10-28: Composition
            # (at.%) left Table columns - a layout that had it simply no longer shows it); unknown keys are dropped
            cols = [c for c in cols if c in COLUMN_BY_KEY and COLUMN_BY_KEY[c].chooser]
            if "name" in cols:
                self.table.model.set_keys(cols)
        self._restore_column_widths()
        self.table.view.user_widths_changed.connect(self._save_column_widths)
        size = int(self.settings.value("page_size", 100))
        if size in PAGE_SIZES:
            self.table.pagination.size_box.setCurrentIndex(PAGE_SIZES.index(size))
        carbonize_popups(self)       # text-field context menus and dropdown lists use the Carbon popups
        win_titlebar.install(QApplication.instance(), lambda: THEME.name, lambda: THEME.tokens)
        win_titlebar.watch(self)
        THEME.changed.connect(self.apply_theme)
        # the effective theme was resolved at start-up (app.py) from this preference; from now on it follows
        # the user's choice and - with System default - the OS colour scheme
        self.apply_theme()
        self._update_status()
        self._f10 = QShortcut(QKeySequence("F10"), self)
        self._f10.activated.connect(self._menu_mode)
        # Alt+F / Alt+E / Alt+V / Alt+H open File / Edit / View / Help (the Windows menu-bar access keys)
        self._menu_keys = []
        for key, item in (("Alt+F", self.header.file_item), ("Alt+E", self.header.edit_item),
                          ("Alt+V", self.header.view_item), ("Alt+H", self.header.help_item)):
            if item is None:
                continue
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda it=item: it._open(keyboard=True) if it.isVisible() else None)
            self._menu_keys.append(sc)
        self.set_top_panels_visible(self.settings.value("top_panels_visible", True, bool), persist=False)
        saved = self.settings.value("collapsed_panels", "")
        for part in str(saved or "").split(","):
            if part.strip().isdigit() and int(part) < 3:
                self.top_row.set_collapsed(int(part), True)

    # ------------------------------------------------------------------ scrolling / layout
    def eventFilter(self, obj, ev):
        if obj in (self.content, self.table) and ev.type() in (QEvent.Type.Resize, QEvent.Type.Move,
                                                               QEvent.Type.LayoutRequest):
            self._sticky_timer.start()
        return super().eventFilter(obj, ev)

    def _remember_normal(self) -> None:
        """The last geometry seen in the normal state - what Restore returns to.  (``normalGeometry()`` of a
        maximized window under this chrome is Windows' restore rectangle less frame margins Qt assumes.)"""
        if not (self.windowState() & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized
                                      | Qt.WindowState.WindowFullScreen)):
            self._normal_geometry = self.geometry()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._remember_normal()

    def resizeEvent(self, e):
        self._remember_normal()
        super().resizeEvent(e)
        if hasattr(self, "_sticky_timer"):
            self._sticky_timer.start()

    # ------------------------------------------------------------------ window chrome
    def nativeEvent(self, event_type, message):                 # noqa: N802 - Qt API
        chrome = getattr(self, "chrome", None)
        if chrome is not None:
            handled, result = chrome.native_event(event_type, message)
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    # ------------------------------------------------------------------ one Analysis view at work
    def _dock_layout_changed(self, wide: bool) -> None:
        """The docked Analysis switched layout: the workspace layout's collapse button collapses the slot like the
        panel's, and only the layout on screen renders."""
        ws = self.analysis_dock.workspace
        if wide and ws is not None and ws.collapse_btn is not None and not getattr(ws, "_collapse_wired", False):
            ws.collapse_btn.clicked.connect(lambda _c=False: self.top_row.set_collapsed(self.ANALYSIS_PANEL, True))
            ws.expand_btn.clicked.connect(lambda _c=False: self.set_expanded(True))
            ws._collapse_wired = True
        self._sync_view_actions()
        if hasattr(self, "top_row"):
            self.top_row._sync_directions()          # a workspace created just now gets the row's icon direction
        self.schedule_analysis_suspension()

    def schedule_analysis_suspension(self) -> None:
        t_ = getattr(self, "_suspension_timer", None)
        if t_ is None:
            t_ = self._suspension_timer = QTimer(self)
            t_.setSingleShot(True)
            t_.setInterval(0)
            t_.timeout.connect(self.sync_analysis_suspension)
        t_.start()

    def _owns_active_window(self) -> bool:
        w = QApplication.activeWindow()
        while w is not None:
            if w is self:
                return True
            w = w.parentWidget()
        return False

    def sync_analysis_suspension(self) -> None:
        """Only the Analysis view in use does work (AnalysisPanel.set_suspended): while the separate Analysis
        window is open and the main window is not the active one, the embedded panel is suspended; a minimised
        main window suspends it too; a minimised or hidden Analysis window suspends its own panel."""
        if getattr(self, "_closed", False) or not hasattr(self, "analysis"):
            return
        aw = self.analysis_window(create=False)
        ext_open = aw is not None and aw.isVisible() and not aw.isMinimized()
        try:
            dock_wide = getattr(getattr(self, "analysis_dock", None), "wide", False)   # the workspace layout shows
            self.analysis.set_suspended(self.isMinimized() or dock_wide
                                        or (ext_open and not self._owns_active_window()))
            if aw is not None:
                # the window's compact panel renders only while it is the layout on screen (not the wide one)
                aw.panel.set_suspended(not ext_open or not aw.compact_shown())
        except RuntimeError:                          # shutting down
            pass

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.WindowStateChange, QEvent.Type.ActivationChange):
            self.schedule_analysis_suspension()
        if e.type() == QEvent.Type.WindowStateChange and hasattr(self, "header"):
            self.header.set_maximized(bool(self.windowState() & Qt.WindowState.WindowMaximized))
            fs = self.isFullScreen()
            ws = self.windowState()
            if not (ws & Qt.WindowState.WindowMinimized) and not fs:
                self._last_state = "maximized" if ws & Qt.WindowState.WindowMaximized else "normal"
            self.header.set_caption_buttons_visible(not fs)      # full screen: no minimise / maximise / close
            if hasattr(self, "fullscreen_action") and self.fullscreen_action.isChecked() != fs:
                self.fullscreen_action.setChecked(fs)

    def toggle_maximized(self) -> None:
        if self.isFullScreen():
            self.set_fullscreen(False)
        elif self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def set_fullscreen(self, on: bool) -> None:
        """View > Full screen (F11): the window covers the screen (the title bar and its menus stay; the caption
        buttons hide); leaving it returns to the previous normal or maximized state."""
        on = bool(on)
        if on == self.isFullScreen():
            self.fullscreen_action.setChecked(on)
            return
        if on:
            self._pre_fullscreen_maximized = self.isMaximized()
            self.showFullScreen()
        elif getattr(self, "_pre_fullscreen_maximized", False):
            self.showMaximized()
        else:
            self.showNormal()

    def _menu_mode(self) -> None:
        """F10: keyboard access to the title bar menus (Left / Right between them, Down / Enter opens, Esc)."""
        if self.header.in_menu_mode():
            self.header.leave_menu_mode()
        else:
            self.header.enter_menu_mode()

    def _panel_action(self, i: int) -> None:
        """View > Panels: expand (check) or collapse (uncheck) one upper panel - exactly its header's collapse /
        strip's expand button.  Expanding a panel while the top panels are hidden shows them."""
        on = self.panel_actions[i].isChecked()
        if on and not self._top_visible:
            self.set_top_panels_visible(True)
        self.top_row.set_collapsed(i, not on)
        self._sync_view_actions()

    def _sync_view_actions(self) -> None:
        """View menu checks follow the window, whichever control changed it (panel buttons, strips, shortcuts)."""
        if not hasattr(self, "panel_actions"):
            return
        for i, act in enumerate(self.panel_actions):
            act.setChecked(not self.top_row.is_collapsed(i))
        expanded = self.pages.currentIndex() == 1 if hasattr(self, "pages") else False
        self.expand_action.setChecked(expanded)
        has = bool(self.table.model.total_count()) if hasattr(self, "table") else False
        self.expand_action.setEnabled(has or expanded)
        ws = getattr(getattr(self, "analysis_dock", None), "workspace", None)
        if ws is not None and ws.expand_btn is not None:      # the wide docked layout's Expand analysis
            ws.expand_btn.setEnabled(has)
            ws.expand_btn.setToolTip("Expand analysis (Ctrl+Shift+E)" if has else
                                     "Expand analysis — available after a calculation")

    def reset_workspace(self) -> None:
        """View > Reset workspace: the default layout - the calculation page, the top panels shown, every upper
        panel expanded, the page scrolled to the top.  Layout only: compositions, expressions, ranges, settings,
        results, the theme and the window's size / full-screen state are untouched."""
        if hasattr(self, "pages") and self.pages.currentIndex() != 0:
            self.set_expanded(False)
        for i in range(len(self.top_row.panels)):
            self.top_row.set_collapsed(i, False)
        self.set_top_panels_visible(True)
        self.scroll.verticalScrollBar().setValue(0)
        self.scroll.horizontalScrollBar().setValue(0)
        self._sync_view_actions()

    def _collapse_changed(self, i: int, on: bool) -> None:
        self.settings.setValue("collapsed_panels", ",".join(str(k) for k in sorted(self.top_row.collapsed)))
        self._sync_view_actions()
        # all three collapsed: the strips serve no purpose - the region hides, as Hide top panels does
        if on and len(self.top_row.collapsed) == len(self.top_row.panels) and self._top_visible:
            self._last_collapsed = i
            self.set_top_panels_visible(False)
        self._sticky_timer.start()

    def top_panels_visible(self) -> bool:
        return self._top_visible

    def set_top_panels_visible(self, on: bool, persist: bool = True) -> None:
        """Title bar top-panels action / View > Top panels (Figma Main window State=Top panels hidden): the
        Elements, Composition setup and Analysis row is hidden and the results table takes the page.

        Showing the region while all three panels are collapsed expands the one collapsed last (the
        configuration just before the region hid itself), so it never disappears again at once."""
        if on and len(self.top_row.collapsed) == len(self.top_row.panels):
            last = getattr(self, "_last_collapsed", len(self.top_row.panels) - 1)
            self.top_row.blockSignals(True)
            self.top_row.set_collapsed(last, False)
            self.top_row.blockSignals(False)
            self.settings.setValue("collapsed_panels", ",".join(str(k) for k in sorted(self.top_row.collapsed)))
        self._top_visible = bool(on)
        self.top_row.setVisible(self._top_visible)
        self.header.set_top_panels_visible(self._top_visible)
        if hasattr(self, "top_panels_action"):
            self.top_panels_action.setChecked(self._top_visible)
        self._sync_view_actions()
        if persist:
            self.settings.setValue("top_panels_visible", self._top_visible)
        self._sticky_timer.start()

    def _place_sticky(self):
        self.sticky.place(self.scroll.viewport())
        if self.top_row.isVisible():
            self.header.align_status_to(self.composition.title)

    def layout_report(self) -> dict:
        """Live layout facts for tools/dpi_diagnostics.py and the DPI tests."""
        vbar = self.table.view.verticalScrollBar()
        hbar = self.table.view.horizontalScrollBar()
        return {
            "upperPanels": [self.elements.width(), self.composition.width(), self.analysis_dock.width()],   # the slot
            "analysisWide": self.analysis_dock.wide,
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
        # Every opening menu is the shared Carbon menu (widgets/menu.py): 32 px items (the title bar height), the
        # shortcut column, an ellipsis on commands that open a dialog, separators between command groups.  The
        # contents follow the former window-chrome branch where its commands exist in this application (File /
        # Edit / View / Help, Copy table under Edit, Full screen, the Help pages); every action does something.
        # Shortcuts are window actions, so they work while the menus are closed.
        self.file_menu = CarbonMenu(parent=self)
        self.import_action = self.file_menu.add_action("Import compositions…", self.import_compositions,
                                                       shortcut="Ctrl+O")
        self.export_action = self.file_menu.add_action("Export results…", self.export_dialog)
        self.file_menu.addSeparator()
        self.settings_action = self.file_menu.add_action("Calculation settings…", self.edit_settings)
        self.file_menu.addSeparator()
        self.exit_action = self.file_menu.add_action("Exit", self.close, shortcut="Ctrl+Q")
        for act in (self.import_action, self.exit_action):
            self.addAction(act)
        # F1 / Help > Documentation: one command, Documentation Home
        self.help_action = QAction("Documentation", self)
        self.help_action.setShortcut(QKeySequence("F1"))
        self.help_action.triggered.connect(lambda: self.show_help("home"))
        self.addAction(self.help_action)
        # View (title bar): Top panels (Ctrl+B) and Full screen (F11), then the Theme choices (Light, Dark, System
        # default - one check; the Figma View menu)
        from .widgets.dropdown import RichMenu
        self.view_menu = RichMenu(parent=self)
        self.top_panels_action = self.view_menu.add_action(
            "Top panels", lambda: self.set_top_panels_visible(self.top_panels_action.isChecked()), checkable=True,
            checked=True, shortcut="Ctrl+B")
        self.fullscreen_action = self.view_menu.add_action(
            "Full screen", lambda: self.set_fullscreen(self.fullscreen_action.isChecked()), checkable=True,
            checked=False, shortcut="F11")
        # Expand analysis (Ctrl+Shift+E): the in-window expanded workspace - the panel's button and the shortcut, now
        # also in the menu (restored 2026-10-28; one action for the menu and the shortcut)
        self.expand_action = self.view_menu.add_action(
            "Expand analysis", lambda: (self.set_expanded(self.expand_action.isChecked()), self._sync_view_actions()),
            checkable=True,
            checked=False, shortcut="Ctrl+Shift+E")
        for act in (self.top_panels_action, self.fullscreen_action, self.expand_action):
            self.addAction(act)
        # Panels: each upper panel expanded (checked) or collapsed to its strip - the panel headers' collapse /
        # expand buttons as menu commands (restored 2026-10-28 from the former View > Panels; this application
        # collapses panels instead of hiding them, and the results table is always shown)
        self.view_menu.addSeparator()
        sec = self.view_menu.add_action("Panels", enabled=False)
        sec.setProperty("section", True)
        self.panel_actions = []
        for i, name in enumerate(("Elements", "Composition setup", "Analysis")):
            act = self.view_menu.add_action(name, lambda i=i: self._panel_action(i), checkable=True, checked=True)
            self.panel_actions.append(act)
        self.reset_workspace_action = self.view_menu.add_action("Reset workspace", self.reset_workspace)
        self.view_menu.addSeparator()
        sec = self.view_menu.add_action("Theme", enabled=False)
        sec.setProperty("section", True)
        group = QActionGroup(self)
        group.setExclusive(True)
        pref = self.prefs.theme
        icons_ = {"light": "brightness_contrast", "dark": "asleep", "system": "screen"}     # Carbon icons
        for name, label in (("light", "Light"), ("dark", "Dark"), ("system", "System default")):
            act = self.view_menu.add_action(label, lambda n=name: self.set_theme(n), checkable=True,
                                            checked=pref == name, trailing_icon=icons_[name])
            act.setData(name)
            group.addAction(act)
        self.theme_actions = group
        self.theme_menu = self.view_menu             # former name (tests, tools)
        # Help (title bar): Getting started, Documentation (F1), the reference pages, About
        self.help_menu = CarbonMenu(parent=self)
        self.help_menu.add_action("Getting started", lambda: self.show_help("first-calculation"))
        self.help_menu.addAction(self.help_action)
        self.help_menu.addSeparator()
        self.help_menu.add_action("Expression syntax", lambda: self.show_help("expression-syntax"))
        self.help_menu.add_action("Model support", lambda: self.show_help("model-coverage"))
        self.help_menu.add_action("Keyboard shortcuts", lambda: self.show_help("shortcuts"))
        self.help_menu.addSeparator()
        self.help_menu.add_action("About MDL HEA Calculator", self.show_about)
        # Edit (right of File): Undo / Redo of meaningful data edits (ui/undo.py); the command's name is shown
        from .undo import UndoManager
        self.undo_mgr = UndoManager(self)
        self.edit_menu = CarbonMenu(parent=self)
        self.undo_action = self.edit_menu.add_action("Undo", self.undo, shortcut="Ctrl+Z")
        self.redo_action = self.edit_menu.add_action("Redo", self.redo, shortcut="Ctrl+Y")
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.edit_menu.addSeparator()
        self.copy_table_action = self.edit_menu.add_action("Copy table", self.copy_table, shortcut="Ctrl+Shift+C")
        for act in (self.undo_action, self.redo_action, self.copy_table_action):
            self.addAction(act)            # window shortcuts; a focused text field keeps its own Ctrl+Z / Ctrl+Y
        self.undo_mgr.changed.connect(self._sync_edit_actions)
        self.undo_mgr.changed.connect(self._resync_setup_state)
        self._sync_edit_actions()

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
        if hasattr(self, "header"):
            self.header.set_theme_preference(pref)

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
            sheet = stylesheet(lambda name, token: icons.file_url(name, token)) + analysis_rules(qss_tokens())
            _SHEET_CACHE[THEME.name] = sheet
        self.setStyleSheet(sheet)
        w = self.analysis_window(create=False) if hasattr(self, "analysis_ctl") else None
        if w is not None:
            w.setStyleSheet(sheet)
        hw = getattr(self, "_help", None)          # unowned too (own taskbar button)
        try:
            if hw is not None:
                hw.set_base_sheet(sheet)
        except RuntimeError:
            self._help = None
        self._sync_theme_actions()
        themer = win_titlebar.themer()
        if themer is not None:
            themer.apply_all()                  # every native caption follows the effective theme
        self.update()

    # ------------------------------------------------------------------ feedback
    NOTIFY_TITLES = {"error": "Error", "warning": "Warning", "success": "Done", "info": "Info"}

    def notify(self, kind: str, text: str, timeout_ms: int = 8000, title: str | None = None):
        """A message of the window: shown in the title bar's status column (never above the results table).
        Success / info go after ``timeout_ms`` or the next mouse press; warnings and errors on the next press."""
        self.progress.show_message(kind, title or self.NOTIFY_TITLES.get(kind, ""), text, timeout_ms)

    def _update_status(self):
        m = self.table.model
        self.table.set_has_results(m.total_count() > 0)
        self._sync_view_actions()                       # Expand analysis needs results
        # The reference toolbar carries no standing label - the paginator already reports the
        # range - so this slot is reserved for filter / background sort state and cell info on hover.
        if m.pending:
            what = "Sorting" if m.sort_key and not m.filters else "Filtering" if not m.sort_key else \
                "Filtering and sorting"
            text = f"{what} {m.total_count():,} results…"
        elif m.filters:
            text = f"Filter active ({m.view_count():,} shown)"
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
        self.progress.dismiss_message()
        self._job_queue = []
        self._batch_added = self._batch_failed = 0
        self._batch_first = None
        self._batch_last = None
        self.table.model.user_paged = False          # paging during this run is the user's: it is kept
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
            self.table.model.user_paged = False
            self._show_new_results(rng.start)
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
        self.elements.set_read_only(True)            # the running setup is frozen (visual QA F-02)
        self._sync_edit_actions()                    # no Undo / Redo while a batch is stored
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
        if info is not None and info.last_id is not None:
            self._batch_last = info.last_id
        cancelled = job.state == "cancelled"
        if r.storage_error:
            self._finish_batch(cancelled=True)
            self.progress.set_result("error", "Calculation failed",
                                     "An error interrupted the calculation before completion.")
            reason = (f"{r.storage_error} The calculation was stopped; {self._batch_added:,} "
                      "calculated result(s) were kept.")
            self.progress.set_reason(reason)      # the Figma Failed state stays; the reason is its tooltip
            self.composition.set_run_failed(reason)
            return
        if job.state == "error":
            self._finish_batch(cancelled=True)
            self.progress.set_result("error", "Calculation failed",
                                     "An error interrupted the calculation before completion.")
            self.progress.set_reason(job.error or "The calculation failed.")
            self.composition.set_run_failed(job.error or "The calculation failed.")
            return
        if self._job_queue and not cancelled:
            if self._next_job():
                return
        self._finish_batch(cancelled)
        if self._batch_first is not None:
            self._show_new_results(self._batch_last if self._batch_last is not None else self._batch_first)
        # CORRECT_CALCULATION_COMPLETED: the outcome is the shell header's state, not a table notification
        n = self._batch_added
        failed = f"; {self._batch_failed:,} could not be evaluated" if self._batch_failed else ""
        if cancelled:
            self.progress.set_result("warning", "Calculation cancelled",
                                     f"{n:,} composition{'s' if n != 1 else ''} calculated before cancellation"
                                     + failed)
        else:
            self.progress.set_result("success", "Calculation completed",
                                     f"{n:,} composition{'s' if n != 1 else ''} calculated successfully" + failed)

    def _finish_batch(self, cancelled: bool):
        self._job_queue = []
        self.progress.hide()
        self.composition.set_calculating(False)
        self.elements.set_read_only(False)
        self._sync_edit_actions()
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

    def _show_new_results(self, newest_id: int) -> None:
        """A calculation has finished: the table shows page 1 - newest first, the new results at the top - unless
        the user paged during the run (their page is kept); Analysis shows the run's newest result.  Never the
        page of the run's first (oldest) result: with newest-first ordering that was the run's last page
        (2026-10-28).  Results committed while the run is active never move the page."""
        m = self.table.model
        if not getattr(m, "user_paged", False):
            m.set_page(0)
        rec = self.repo.get_result(newest_id) if m.view.is_alive(newest_id) else None
        if rec is not None:
            self.show_details(rec)

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

    ANALYSIS_PANEL = 2                       # index of Analysis in the top row (Elements, Composition setup, Analysis)

    def docked_analysis_shown(self) -> bool:
        """Whether this window itself shows Analysis: the expanded workspace, or the embedded panel with the top
        panels visible and Analysis not collapsed to its strip.  The one routing rule for a result activation."""
        if self.pages.currentIndex() == 1:
            return True
        return self.top_panels_visible() and not self.top_row.is_collapsed(self.ANALYSIS_PANEL)

    def _row_activated(self, row):
        """A results-row double click / Enter / "Analyse composition": the active composition of Analysis.  When
        this window does not show Analysis (top panels hidden, or Analysis collapsed - a collapse the user chose
        and that is not undone here) the separate Analysis window opens, or is reused and raised, with it;
        otherwise the embedded panel shows it (an open Analysis window follows - shared state)."""
        if not self.docked_analysis_shown():
            self.open_analysis_window(row)
            return
        self.show_details(row)

    def show_details(self, row):
        """The active composition of Analysis (double click, single calculation).  A stored record is
        reproduced into a full engine result once, by its stable id - never by its row on screen."""
        self._set_has_results(bool(self.table.model.total_count()))
        if row is None:
            self._details_id = None
            self.analysis_ctl.set_active(None)
            return
        if isinstance(row, ResultRecord):
            self._details_id = row.id
            self.analysis_ctl.set_active(row.id)
            if self.sender() is self.table.view:   # a results-row double click: brief acknowledgement (§38)
                self.analysis.acknowledge()

    def _check_details(self):
        m = self.table.model
        total = m.total_count()
        self._set_has_results(bool(total))
        st = self.analysis_ctl.state
        if st.active is not None and st.active_gone is None and not m.view.is_alive(st.active):
            self.analysis_ctl.results_removed([st.active])
        self._update_status()

    # ------------------------------------------------------------------ table actions
    def delete_rows(self):
        """Clear the results table (toolbar "Clear table").

        Undoable (Edit > Undo; ``ui/undo.ClearTableCommand``: an O(1) table swap in the session database, no
        copy).  A table of ``CONFIRM_AT`` results or more asks first in a Carbon danger modal
        (``core/destructive.py`` - the one policy); a handful is cleared at once.  The composition panel,
        filters and sort are left untouched.
        """
        from .undo import ClearTableCommand
        m = self.table.model
        n = m.total_count()
        if not n or self.runner.running:
            return
        if destructive.needs_confirmation(n) and not self._confirm_destructive(
                "Clear results", f"Clear all {destructive.describe(n)}?",
                "They are removed from this session's results table. Edit › Undo brings them back.",
                "Clear results"):
            return
        self.undo_mgr.push(ClearTableCommand(self, n))

    def remove_results(self, records) -> None:
        """Remove result(s) (row menu): undoable; a batch of ``CONFIRM_AT`` or more asks first."""
        from .undo import RemoveResultsCommand
        records = [r for r in records if r is not None]
        if not records or self.runner.running:
            return
        n = len(records)
        if destructive.needs_confirmation(n) and not self._confirm_destructive(
                "Remove results", f"Remove {destructive.describe(n)}?",
                "They are removed from this session's results table. Edit › Undo brings them back.", "Remove"):
            return
        self.undo_mgr.push(RemoveResultsCommand(self, records))

    def clear_composition(self) -> None:
        """Composition setup Clear: undoable (the setup is restored exactly, element selection included)."""
        from .undo import ClearCompositionCommand
        comp = self.composition
        if comp.is_empty():
            comp.clear()
            return
        text = {"single": "Clear composition", "sweep": "Clear composition space",
                "expression": "Clear composition expression"}[comp.mode]
        self.undo_mgr.push(ClearCompositionCommand(comp, comp.snapshot(), text))

    def _setup_committed(self, text: str) -> None:
        """A finished setup edit: one Undo step when the state changed (several boundaries of one edit - focus
        leaving the field after a commit, a toggle that changed nothing - record nothing)."""
        from .undo import SetupEditCommand
        comp = self.composition
        try:
            if not self.isVisible() or self.runner is None:
                return                                    # closing: focus changes are not edits
            after = comp.undo_state()
        except RuntimeError:                              # being destroyed
            return
        before = dict(self._setup_state, mode=after["mode"])     # switching the mode is not an edit
        if self.runner.running or before == after:
            self._setup_state = after
            return
        self._setup_state = after
        self.undo_mgr.push(SetupEditCommand(self, before, after, text))

    def apply_setup_state(self, st: dict) -> None:
        """Undo / Redo of a setup edit: the panel, the periodic table (``elements_changed``) and the baseline."""
        self.composition.apply_undo_state(st)
        self._setup_state = self.composition.undo_state()

    def _resync_setup_state(self) -> None:
        """Any undo stack move (Clear composition, its Undo, a result removal): the baseline is the setup as it is."""
        if hasattr(self, "composition"):
            self._setup_state = self.composition.undo_state()

    def _confirm_destructive(self, title: str, question: str, detail: str, action: str) -> bool:
        from .widgets.dialogs import DangerDialog
        dlg = DangerDialog(title, question, detail, action, self)
        ok = dlg.exec() == DangerDialog.DialogCode.Accepted
        dlg.deleteLater()
        return ok

    def results_restored(self) -> None:
        """Undo brought results back: Analysis, details and the toolbar follow."""
        self.analysis_ctl.results_restored()
        self._set_has_results(bool(self.table.model.total_count()))
        self._check_details()

    def undo(self) -> None:
        if not self.runner.running:
            self.undo_mgr.undo()

    def redo(self) -> None:
        if not self.runner.running:
            self.undo_mgr.redo()

    def _sync_edit_actions(self) -> None:
        st = self.undo_mgr.stack
        running = bool(getattr(self, "runner", None) and self.runner.running)
        u, r = st.undoText(), st.redoText()
        self.undo_action.setText(f"Undo {u[:1].lower() + u[1:]}" if u else "Undo")
        self.redo_action.setText(f"Redo {r[:1].lower() + r[1:]}" if r else "Redo")
        self.undo_action.setEnabled(st.canUndo() and not running)
        self.redo_action.setEnabled(st.canRedo() and not running)

    def _restore_column_widths(self) -> None:
        import json
        try:
            widths = json.loads(str(self.settings.value("column_widths", "{}")))
        except ValueError:
            widths = {}
        if isinstance(widths, dict):
            self.table.view.set_user_widths(widths)

    def _save_column_widths(self) -> None:
        import json
        self.settings.setValue("column_widths", json.dumps(self.table.view.user_widths))

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
            if dlg.reset_widths:
                self.table.view.reset_width(None)
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
            self.notify("success", f"{n:,} row(s) × {len(m.keys)} columns (paste into Excel).", 4000,
                        title="Table copied to clipboard")
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
        self.notify("success", f"{len(rows):,} visible row(s) × {len(m.keys)} columns (paste into Excel).", 4000,
                    title="Rows copied to clipboard")

    def _copy_text(self, tsv: str, what: str):
        QGuiApplication.clipboard().setText(tsv)
        self.notify("success", f"The {what} (paste into Excel).", 4000, title="Copied to clipboard")

    def _copy_generated(self, tsv: str):
        QGuiApplication.clipboard().setText(tsv)
        n = max(len(tsv.strip().splitlines()) - 1, 0)
        self.notify("success", f"{n:,} generated composition(s) (paste into Excel).", 4000,
                    title="Compositions copied to clipboard")

    def export_dialog(self):
        """File › Export results: one save dialog; the file type chosen there decides Excel or CSV."""
        path, sel = QFileDialog.getSaveFileName(self, "Export results", "hea_results.xlsx",
                                                "Excel workbook (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        fmt = "csv" if path.lower().endswith(".csv") or sel.startswith("CSV") else "xlsx"
        self.export(fmt, "all", path=path)

    def export(self, fmt: str, scope: str = "all", path: str | None = None):
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
        if path is None:
            flt = "Excel workbook (*.xlsx)" if fmt == "xlsx" else "CSV (*.csv)"
            default = f"hea_results{'_filtered' if filtered else ''}.{fmt}"
            path, _ = QFileDialog.getSaveFileName(self, "Export results", default, flt)
            if not path:
                return
        elif not path.lower().endswith("." + fmt):
            path = str(Path(path).with_suffix("." + fmt))      # a CSV fallback chosen in the row-limit dialog
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
                self.notify("error", str(exc), title="Export failed")
                return
            self.notify("success", f"{n:,} rows written to {Path(path).name}.", title="Export completed")
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
            self.notify("success", f"{value:,} row(s) × {job['cols']} columns (paste into Excel).", 4000,
                        title="Table copied to clipboard")
        elif status == "ok":
            self.notify("success", f"{value:,} rows written to {path.name}.", title="Export completed")
        else:
            path.unlink(missing_ok=True)
            if status == "cancelled":
                self.notify("warning", "No file was written.", title="Export cancelled")
            else:
                self.notify("error", str(value), title="Export failed")

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
            self.notify("error", str(exc), title="Import failed")
            return
        if res.errors:
            rep = ImportReportDialog(Path(path).name, res.layout, len(res.entries), res.errors, self)
            rep.exec()
            rep.deleteLater()
        if not res.entries:
            self.notify("error", "No valid compositions found in the file.", title="Import failed")
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
        self.progress.dismiss_message()
        self._batch_added = self._batch_failed = 0
        self._batch_first = None
        self._batch_last = None
        self.table.model.user_paged = False          # paging during this run is the user's: it is kept
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
        """Row menu "Open details in new window": the separate Analysis window with that composition."""
        self.open_analysis_window(row)

    def analysis_window(self, create: bool = True):
        """The one separate Analysis window (analysis/window.py), created on first use and then reused."""
        w = getattr(self, "_analysis_window", None)
        try:
            if w is not None:
                w.isVisible()                   # raises if Qt deleted it
        except RuntimeError:
            w = None
        if w is None and create and not self._closed:
            from .analysis.window import AnalysisWindow
            w = self._analysis_window = AnalysisWindow(self.analysis_ctl, self)
            w.setStyleSheet(self.styleSheet())  # unowned (own taskbar button): it does not inherit the sheet
            w.panel.set_has_results(bool(self.table.model.total_count()))
        return w

    def open_analysis_window(self, row=None):
        """Open (or raise) the separate Analysis window; ``row`` (a result) becomes the active composition and
        Analysis shows Composition.  The window and the embedded panel are views of the same state."""
        w = self.analysis_window()
        if w is None:
            return None
        if isinstance(row, ResultRecord):
            self._details_id = row.id
            self.analysis_ctl.set_active(row.id)
            self.analysis_ctl.apply(AS.switch_context, AS.COMPOSITION)
        w.present()
        if isinstance(row, ResultRecord):
            w.panel.acknowledge()
        return w

    def _set_has_results(self, has: bool) -> None:
        self.analysis.set_has_results(has)
        w = self.analysis_window(create=False)
        if w is not None:
            w.panel.set_has_results(has)

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
        self._sync_view_actions()
        if on:
            self.workspace.focus_title()
        else:
            dock = self.analysis_dock                  # focus returns to the Expand analysis that is on screen
            btn = dock.workspace.expand_btn if dock.wide and dock.workspace is not None else self.analysis.expand_btn
            btn.setFocus(Qt.FocusReason.OtherFocusReason)

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

    def show_help(self, page: str = "home", anchor: str = ""):
        """Show the single Help window at ``page`` (an id, legacy alias or help:// URL) and ``anchor``."""
        from .help_window import HelpWindow
        win = getattr(self, "_help", None)
        try:
            if win is None or not win.isVisible():
                if win is None:
                    win = self._help = self._new_help_window(HelpWindow)
                win.show()
        except RuntimeError:                       # deleted during shutdown
            win = self._help = self._new_help_window(HelpWindow)
            win.show()
        win.open(page, anchor)
        if win.isMinimized():
            win.showNormal()
        win.raise_()
        win.activateWindow()
        return win

    def _new_help_window(self, cls):
        """The Help window is an independent top-level window (no owner): its own taskbar button and Alt+Tab entry,
        minimisable on its own, free to go behind the main window - never a tool or always-on-top window.  Being
        unowned it does not inherit the window-scoped sheet, so it gets it here (and from ``apply_theme``)."""
        w = cls(None)
        w.main = self
        w.set_base_sheet(self.styleSheet())
        return w

    def show_about(self):
        """Show (or raise) the single, non-modal About window."""
        from .about_window import AboutWindow
        win = getattr(self, "_about", None)
        try:
            if win is None:
                win = self._about = AboutWindow(self)
            win.show()
        except RuntimeError:
            win = self._about = AboutWindow(self)
            win.show()
        win.raise_()
        win.activateWindow()
        return win
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
        rt = getattr(self, "_report_task", None)
        if rt is not None:
            rt.shutdown()                 # a report QThread is joined, never left running at exit
        self.analysis_ctl.close()
        self.jobs.shutdown()          # no worker process outlives the window
        self.table.model.close()
        self.repo.close()

    DEFAULT_SIZE = (1095, 670)      # first-run restored size (logical px); the minimum stays 1024 x 640

    def show_initial(self) -> None:
        """Open as the user left the window: maximized, or at the saved normal size and position (on a screen
        that still exists, inside its work area).  A fresh installation opens maximized on the primary screen
        (Restore then gives the default size, centred).  Closing minimized reopens in the state before
        minimising; closing in full screen reopens in the state before full screen."""
        from PySide6.QtCore import QRect
        st = self.settings
        state = st.value("window/state", None)
        rect = st.value("window/normal", None)
        if state is None and st.value("window_geometry", None) is not None:
            # a geometry saved by an earlier version (QWidget.saveGeometry)
            if self.restoreGeometry(st.value("window_geometry")):
                self.show()
                return
        screens = QGuiApplication.screens()
        primary = (QGuiApplication.primaryScreen() or self.screen()).availableGeometry()
        if isinstance(rect, QRect) and rect.isValid():
            target = rect
            home = next((sc.availableGeometry() for sc in screens if sc.availableGeometry().intersects(rect)
                         and sc.availableGeometry().intersected(rect).height() >= 40), None)
            if home is None:                          # its monitor is gone: centre on the primary screen
                home = primary
                target = QRect(0, 0, rect.width(), rect.height())
                target.moveCenter(home.center())
            w = max(self.minimumWidth(), min(target.width(), home.width()))
            h = max(self.minimumHeight(), min(target.height(), home.height()))
            x = max(home.left(), min(target.x(), home.right() + 1 - w))     # never above / left of the work area
            y = max(home.top(), min(target.y(), home.bottom() + 1 - h))
            self.setGeometry(QRect(x, y, w, h))
        else:
            self.resize(*self.DEFAULT_SIZE)
            frame = self.frameGeometry()
            frame.moveCenter(primary.center())
            self.move(frame.topLeft())
            state = state or "maximized"              # first launch
        self._last_state = "maximized" if state == "maximized" else "normal"
        if state == "maximized":
            normal = self.geometry()
            self._normal_geometry = normal
            self.showMaximized()
            # Restore must return to exactly this rectangle (no normal frame is shown first - no flash)
            from . import win_chrome
            if win_chrome.supported():
                dpr = self.devicePixelRatioF()
                win_chrome.set_normal_rect(int(self.winId()), round(normal.left() * dpr), round(normal.top() * dpr),
                                           round((normal.right() + 1) * dpr), round((normal.bottom() + 1) * dpr))
        else:
            self._normal_geometry = self.geometry()
            self.show()

    def _save_window_state(self) -> None:
        """The last meaningful state (never minimized / full screen) and the normal geometry - kept apart, so
        a maximized window never overwrites the size Restore returns to."""
        if self.isFullScreen():
            state = "maximized" if getattr(self, "_pre_fullscreen_maximized", False) else "normal"
        elif self.isMinimized():
            state = getattr(self, "_last_state", "normal")
        else:
            state = "maximized" if self.isMaximized() else "normal"
        if self.isMaximized() or self.isFullScreen() or self.isMinimized():
            normal = getattr(self, "_normal_geometry", None) or self.normalGeometry()
        else:
            normal = self.geometry()
        if normal.isValid() and normal.width() > 0:
            self.settings.setValue("window/normal", normal)
        self.settings.setValue("window/state", state)
        self.settings.remove("window_geometry")

    def closeEvent(self, e):
        self._save_window_state()
        # Help and About are top-level windows of their own: they close with the application, otherwise a visible
        # one would keep the process alive after the main window has gone
        for name in ("_help", "_about"):
            w = getattr(self, name, None)
            try:
                if w is not None:
                    w.close()
            except RuntimeError:
                pass
        # the Analysis window has no owner (own taskbar button): it is destroyed with the main window
        aw = self.analysis_window(create=False)
        if aw is not None:
            try:
                aw.hide()
                aw.deleteLater()
            except RuntimeError:
                pass
            self._analysis_window = None
        self.shutdown()
        super().closeEvent(e)


_ = (DEFAULT_COLUMNS, write_tsv)
