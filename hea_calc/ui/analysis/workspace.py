"""Expanded Analysis workspace (design guide section 4; frames 18-31) - an in-window page.

*Expand analysis* swaps the main window's content (upper panels + results table) for this page; the native
title bar and the 48 px HEA header stay.  It is a second view of the same
:class:`~.controller.AnalysisController`: context, active composition, tabs, scope, plot configuration, zoom
and selection are shared, so returning with *Back to calculation* restores everything, and focus returns to
the embedded *Expand analysis* button (``ANALYSIS_RESPONSIVE_LAYOUT.md`` section 6).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ...core import composition as CMP
from ...core.analysis import models as MD
from ...core.analysis import state as S
from ...core.analysis.scope import BASE_LABELS
from ...core.engine import MODEL_KEYS
from .. import icons
from ..widgets.common import IconButton, LineTabs
from .collection_view import CollectionContent, _Region
from .composition_view import CompositionContent, mode_name
from .panel import overflow_menu
from .widgets import ROW_SM, Cell, ContentSwitcher, CurrentStack, DataTable, label, rich


class BackButton(QPushButton):
    """*Back to calculation*: Carbon tertiary button (sm) with the trailing ``minimize`` icon."""

    def __init__(self, parent=None):
        super().__init__("Back to calculation", parent)
        self.setProperty("kind", "tertiary")
        self.setProperty("btnsize", "sm")
        self.setFixedSize(200, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        # the label says what it does; no Tooltip repeating it (the shortcut is in the accessible description)
        self.setAccessibleName("Back to calculation")
        self.setAccessibleDescription("Ctrl+Shift+E")

    def paintEvent(self, e):
        super().paintEvent(e)
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        token = "text-inverse" if self.underMouse() else "icon-primary"
        icons.paint(p, "minimize", QRectF(self.width() - 32, (self.height() - 16) / 2, 16, 16), token)
        p.end()


class WorkspaceTitle(QWidget):
    """Focusable heading "Analysis" (announced on expansion; not in the Tab sequence)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.lab = label("Analysis", "title")
        lay.addWidget(self.lab)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAccessibleName("Analysis workspace")


class AnalysisWorkspace(QWidget):
    back_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.setObjectName("AnaWorkspace")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 24, 20, 24)
        root.setSpacing(20)
        # ---- header (48)
        head = QWidget()
        head.setFixedHeight(48)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        self.title = WorkspaceTitle()
        hl.addWidget(self.title)
        hl.addSpacing(36)
        self.switcher = ContentSwitcher(["Composition", "Collection"])
        hl.addWidget(self.switcher)
        hl.addSpacing(32)
        self.tab_stack = QStackedWidget()
        # the tabs sit on the page background; when the header is tight they become scrollable (§21)
        surface = ("background", "background-hover", "layer-active-01")
        self.comp_tabs = LineTabs(list(S.COMP_TAB_LABELS), surface=surface)
        self.coll_tabs = LineTabs(list(S.COLL_TAB_LABELS), surface=surface)
        self.tab_stack.addWidget(self.comp_tabs)
        self.tab_stack.addWidget(self.coll_tabs)
        self.tab_stack.setFixedHeight(32)
        hl.addWidget(self.tab_stack, 1)
        hl.addSpacing(24)
        # the scope / identity text: in the header row when it fits, otherwise on its own line under it
        # (7.png: the tab row overlapped it) - see _reflow_header
        self.identity = label("", "secondary")
        self.identity_slot = QHBoxLayout()
        self.identity_slot.setContentsMargins(0, 0, 0, 0)
        self.identity_slot.addWidget(self.identity)
        hl.addLayout(self.identity_slot)
        hl.addSpacing(8)
        self.overflow_btn = IconButton("overflow_menu_vertical", "Options")
        hl.addWidget(self.overflow_btn)
        hl.addSpacing(8)
        self.back = BackButton()
        hl.addWidget(self.back)
        root.addWidget(head)
        self.head = head
        self.identity_row = QWidget()
        irl = QHBoxLayout(self.identity_row)
        irl.setContentsMargins(0, 0, 0, 0)
        irl.addStretch(1)
        self.identity_row.hide()
        root.addWidget(self.identity_row)
        self.identity_wrapped = False
        # ---- body
        self.body = CurrentStack()                  # sized by the visible page: the outer scroll owns overflow
        self.comp_body = CurrentStack()            # overview / descriptors / models / model details
        self.composition = CompositionContent("W")
        self.composition_details = CompositionContent("W")
        self.composition_details.setCurrentIndex(3)
        for content in (self.composition, self.composition_details):
            content.batch_mass = controller.batch_mass
            controller.batch_mass_changed.connect(content.set_batch_mass)
        # Model details selection list (6.png): compact 40 px rows, the selected model filled; no chevron - choosing
        # a model shows its details beside the list, it does not navigate
        self.model_list = DataTable([("Model", None)], [], 40, activatable=True, header=False, chevron=False)
        self._build_comp_pages()
        self.collection = CollectionContent(controller, "W")
        self.body.addWidget(self.comp_body)
        self.body.addWidget(self.collection)
        root.addWidget(self.body, 1)
        # ---- wiring
        self.switcher.changed.connect(lambda i: self.c.apply(S.switch_context, (S.COMPOSITION, S.COLLECTION)[i]))
        self.comp_tabs.changed.connect(lambda i: self.c.apply(S.set_tab, S.COMP_TABS[i]))
        self.coll_tabs.changed.connect(lambda i: self.c.apply(S.set_tab, S.COLL_TABS[i]))
        for content in (self.composition, self.composition_details):
            content.open_tab.connect(lambda tab: self.c.apply(S.set_tab, tab))
            content.model_selected.connect(lambda m: self.c.apply(S.select_model, m))
        self.model_list.activated.connect(lambda i: self.c.apply(S.select_model, MODEL_KEYS[i]))
        self.back.clicked.connect(self.back_requested.emit)
        self.overflow_btn.clicked.connect(self.open_overflow)
        controller.state_changed.connect(self._sync)
        controller.composition_changed.connect(self._composition_signal)
        self._rendered_key = None
        self._composition_dirty = False
        controller.data_ready.connect(lambda slot: self._identity() if slot == "population" else None)
        self.collection.set_has_results(True)
        self._sync(None, controller.state)
        self._composition_changed()

    # ------------------------------------------------------------------ header reflow (7.png)
    def header_needs(self) -> int:
        """Width the one-row header needs with every tab visible and the identity text beside them."""
        tabs = self.tab_stack.currentWidget()
        return (self.title.sizeHint().width() + 36 + self.switcher.width() + 32 + tabs.natural + 24
                + self.identity.sizeHint().width() + 8 + self.overflow_btn.width() + 8 + self.back.width())

    def _reflow_header(self) -> None:
        wrap = bool(self.identity.text()) and self.header_needs() > self.head.width()
        if wrap == self.identity_wrapped:
            return
        self.identity_wrapped = wrap
        lay = self.identity_row.layout()
        if wrap:                                    # move the text under the header, right-aligned
            self.identity_slot.removeWidget(self.identity)
            lay.addWidget(self.identity)
        else:
            lay.removeWidget(self.identity)
            self.identity_slot.addWidget(self.identity)
        self.identity_row.setVisible(wrap)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._reflow_header()

    def _build_comp_pages(self) -> None:
        # overview / descriptors / models share one CompositionContent (W layouts); model details adds the list
        self.comp_body.addWidget(self.composition)
        md = QWidget()
        ml = QHBoxLayout(md)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(20)
        lst = _Region()
        lst.setFixedWidth(280)
        lst.add(label("Models", "heading02"))
        lst.add(self.model_list)
        lst.lay.addStretch(1)
        ml.addWidget(lst)
        reg = _Region()
        reg.add(self.composition_details, 1)
        ml.addWidget(reg, 1)
        self.comp_body.addWidget(md)

    # ------------------------------------------------------------------ state -> view
    def _sync(self, old, new):
        ctx = 0 if new.context == S.COMPOSITION else 1
        self.switcher.set_index(ctx)
        self.switcher.set_badge(0, new.composition_badge)
        self.tab_stack.setCurrentIndex(ctx)
        self.body.setCurrentIndex(ctx)
        self.comp_tabs.set_index(S.COMP_TABS.index(new.comp_tab))
        self.coll_tabs.set_index(S.COLL_TABS.index(new.coll_tab))
        details = new.comp_tab == "model_details"
        self.comp_body.setCurrentIndex(1 if details else 0)
        if not details:
            self.composition.setCurrentIndex(S.COMP_TABS.index(new.comp_tab))
        self.composition.set_model(new.model)
        self.composition_details.set_model(new.model)
        self.composition.set_search(new.descriptor_search, new.full_precision)
        self.model_list.selected = MODEL_KEYS.index(new.model)
        self.model_list.update()
        if ctx == 1 and (old is None or old.context != new.context):
            self.c.ensure_scope()
        if old is not None and (old.active != new.active or old.active_gone != new.active_gone):
            self._composition_changed()
        self._identity()

    def _composition_key(self):
        return id(self.c.row), self.c.state.active, self.c.state.active_gone

    def _composition_signal(self):
        if self._composition_key() != self._rendered_key:
            self._composition_changed()

    def showEvent(self, e):
        super().showEvent(e)
        if self._composition_dirty:
            self._composition_changed()

    def _composition_changed(self):
        # the expanded workspace is a hidden page most of the time: rebuilding it there cost ~0.3 s on the GUI
        # thread for every activated result (release perf run 2026-10-16); it catches up when it is shown
        if not self.isVisible():
            self._composition_dirty = True
            return
        self._composition_dirty = False
        self._rendered_key = self._composition_key()
        row = self.c.row if self.c.state.active_gone is None else None
        if row is None:
            self.composition.set_empty("No composition selected",
                                       "Double-click a row in the results table to analyse that composition here.")
            self.composition_details.set_empty("No composition selected", "")
            self.model_list.set_rows([])
        else:
            info = self.c.run_info(self.c.record.run_id) if self.c.record is not None else None
            self.composition.set_result(row, info, self.c.record)
            self.composition_details.set_result(row, info, self.c.record)
            rows = []
            for k in MODEL_KEYS:
                o = row.result.models[k]
                rows.append([Cell(f"<b>{k}</b> &nbsp;<span style='font-size:12px'>{MD.MODELS[k].short}</span>",
                                  tag=None)])
                rows[-1].append(Cell(tag=o.label))
            self.model_list.columns = [("Model", None), ("", 96)]
            self.model_list.show_header = False
            self.model_list.set_rows(rows)
        self._identity()

    def _identity(self):
        self._set_identity()
        self._reflow_header()

    def _set_identity(self):
        st = self.c.state
        if st.context == S.COMPOSITION:
            row = self.c.row if st.active_gone is None else None
            if row is None:
                self.identity.setText("")
                return
            from ...core.family import family_key
            run = f" · Run {self.c.record.run_id}" if self.c.record is not None else ""
            self.identity.setText(rich(f"{CMP.name_html(row.name)} · {family_key(row.result.composition)}{run}"))
        else:
            sc = st.scope
            if sc is None:
                self.identity.setText("")
                return
            info = self.c.run_info(sc.run_id)
            n = st.resolved.n if st.resolved else 0
            text = f"Run {sc.run_id} · {mode_name(info.mode if info else '')} · {BASE_LABELS[sc.base]} · " \
                   f"{n:,} of {self.c.run_count(sc.run_id):,} results"
            if info is not None and info.status == "running":
                text += " (calculating)"
            self.identity.setText(text)

    def open_overflow(self):
        menu = overflow_menu(self, self.c)
        menu.open_below(self.overflow_btn, align_right=True)
        menu.deleteLater()

    def focus_title(self):
        self.title.setFocus(Qt.FocusReason.OtherFocusReason)


_ = (QFont, ROW_SM)
