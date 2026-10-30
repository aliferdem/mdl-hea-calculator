"""The separate Analysis window: a normal top-level window with a third view of the shared Analysis controller.

It replaces the former modal "Alloy details" dialog.  The embedded panel, the expanded workspace and this window
are views of one :class:`~.controller.AnalysisController`: the active composition, context (Composition /
Collection), tabs, scope, plot configuration and selection are the same everywhere, so nothing is copied and
nothing can diverge.  The window has no state of its own beyond its geometry.

* a normal, non-modal top-level window: no owner, so it has its own taskbar button and Alt+Tab entry, and the
  native Windows caption (minimise, maximise / restore, close, Snap) in the effective theme;
* closing it only hides it (it is reused - opened, raised and focused - by the next request); it closes with the
  main window;
* the same Analysis panel as the embedded one (header, context bar, line tabs, Composition and Collection with
  Overview / Plots / Statistics / Models), responsive by its own width (size classes S / M / L); the panel's
  collapse and expand buttons are not shown here - the window itself is resized or maximised;
* export is in the panel's Options menu (the shared overflow actions); there is no separate Export button.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from ...core.analysis import state as S
from .. import win_titlebar

WINDOW_TITLE = "Analysis - MDL HEA Calculator"   # a plain hyphen: Windows title convention
DEFAULT_SIZE = QSize(1120, 760)
MINIMUM_SIZE = QSize(560, 520)


class AnalysisWindow(QWidget):
    def __init__(self, controller, main_window=None):
        super().__init__(None, Qt.WindowType.Window)          # unowned: own taskbar button, Alt+Tab entry
        from .panel import AnalysisPanel
        self.c = controller
        self.main = main_window
        self.setObjectName("AnalysisWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle(WINDOW_TITLE)
        if main_window is not None and not main_window.windowIcon().isNull():
            self.setWindowIcon(main_window.windowIcon())
        win_titlebar.watch(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # Two layouts of the one Analysis (views of the same controller): the compact panel, and - when the window
        # is as wide as the expanded workspace needs - that workspace's layout (created on first use).
        self.pages = QStackedWidget()
        lay.addWidget(self.pages)
        self.panel = AnalysisPanel(controller, external=True)
        self.panel.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.pages.addWidget(self.panel)
        self.workspace = None
        self.wide = False
        self.resize(DEFAULT_SIZE)
        self.setMinimumSize(MINIMUM_SIZE)
        self._choose_layout()
        controller.composition_changed.connect(self._update_title)
        controller.state_changed.connect(lambda _o, _n: self._update_title())
        self._update_title()

    def _update_title(self) -> None:
        """"<alloy> - Analysis - MDL HEA Calculator" while a composition is shown in Composition (no em dash)."""
        try:
            st = self.c.state
            row = self.c.row if st.active is not None and st.active_gone is None else None
            if st.context == S.COMPOSITION and row is not None:
                self.setWindowTitle(f"{row.name} - {WINDOW_TITLE}")
            else:
                self.setWindowTitle(WINDOW_TITLE)
        except RuntimeError:                                  # deleted during shutdown
            pass

    # ------------------------------------------------------------------ responsive layout
    def content_width(self) -> int:
        """The width the Analysis content gets (logical px: Qt applies the display scale): the window's client
        area - the layout has no margins and the pages' scroll bars overlay their content."""
        return self.contentsRect().width()

    def _ensure_workspace(self):
        if self.workspace is None:
            from ..widgets.scroll import thin_scrollbars
            from .workspace import WORKSPACE_MIN_WIDTH, AnalysisWorkspace
            self.workspace = AnalysisWorkspace(self.c, external=True)
            self.workspace.setMinimumWidth(WORKSPACE_MIN_WIDTH)
            sa = QScrollArea()
            sa.setObjectName("AnaWindowScroll")
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # wide only when it fits
            thin_scrollbars(sa)
            sa.setWidget(self.workspace)
            sa.viewport().setAutoFillBackground(False)
            self.workspace_scroll = sa
            self.pages.addWidget(sa)
        return self.workspace

    def _choose_layout(self) -> None:
        """Compact panel below the width at which the workspace layout is readable, the workspace layout from it
        on - decided by the width the content actually gets, in both directions, without reopening the window."""
        from .workspace import wide_layout_min
        wide = self.content_width() >= wide_layout_min()
        if wide == self.wide and (self.pages.currentIndex() == (1 if wide else 0)):
            return
        had_focus = self.isAncestorOf(self.focusWidget()) if self.focusWidget() is not None else False
        self.wide = wide
        if wide:
            self._ensure_workspace()
            self.pages.setCurrentIndex(1)
        else:
            self.pages.setCurrentIndex(0)
        self.panel.set_suspended(wide or not self.isVisible())   # only the layout on screen renders
        if had_focus:
            self._focus_view()
        self._views_changed()

    def compact_shown(self) -> bool:
        return not self.wide

    def current_view(self):
        return self.workspace if self.wide else self.panel

    def _focus_view(self) -> None:
        if self.wide:
            self.workspace.focus_title()
        else:
            self.panel.setFocus(Qt.FocusReason.OtherFocusReason)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._choose_layout()

    def present(self) -> None:
        """Open, restore, raise and focus the window (reused, never duplicated)."""
        self._choose_layout()
        self.panel.set_suspended(self.wide)                   # current before its first frame (compact layout)
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        # the window has the focus, not its first control: Windows otherwise focused the Content switcher on
        # activation and its keyboard focus ring read as a thick permanent border (Tab still reaches it)
        self._focus_view()

    def _views_changed(self) -> None:
        sched = getattr(self.main, "schedule_analysis_suspension", None)
        if sched is not None:
            try:
                sched()
            except RuntimeError:
                pass

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (e.Type.WindowStateChange, e.Type.ActivationChange):
            self._views_changed()

    def showEvent(self, e):
        super().showEvent(e)
        self._views_changed()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._views_changed()

    def closeEvent(self, e):
        # the window is hidden and kept: its state is the controller's, and it reopens where it was
        e.accept()
        self.hide()
