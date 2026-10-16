"""The embedded Analysis panel (design guide section 3; frames 1-17).

Fixed regions (never scroll): header 56 px (title, alloy suffix, Composition / Collection content
switcher, *Expand analysis*, overflow), context bar 40 px (48 px at S for Composition), line tabs 32 px.
Only the content region scrolls (inner scroll areas, 4 px overlay bar).  Size classes from the panel's own
width: S 454-719, M 720-1039, L >= 1040; fonts never shrink, content reflows.

The panel is a *view* of :class:`~.controller.AnalysisController`; the expanded workspace is another view
of the same controller, so presentation changes never change state.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ...core import composition as CMP
from ...core.analysis import state as S
from ...core.engine import MODEL_KEYS
from ..theme import DETAILS_PANEL_MIN, PANEL_PADDING_X
from ..widgets.common import IconButton, LineTabs
from ..widgets.menu import CarbonMenu
from ..widgets.tooltip import InfoButton
from .collection_view import CollectionContent, ScopeBar
from .composition_view import CompositionContent, mode_name
from .widgets import ContentSwitcher, label, rich

S_MAX, M_MAX = 719, 1039


def size_class_for(width: int) -> str:
    return "S" if width <= S_MAX else ("M" if width <= M_MAX else "L")


class CompositionBar(QWidget):
    """Composition context bar: identity line + "Calculated with T = … K for M6, M7" (Toggletip ANA-PROVENANCE).
    At S: two lines (alloy name heading / family · elements)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(PANEL_PADDING_X, 0, PANEL_PADDING_X, 8)
        self.lay.setSpacing(8)
        self.col = QVBoxLayout()
        self.col.setSpacing(2)
        self.name = label("", "heading")
        self.identity = label("", "secondary")
        self.col.addWidget(self.name)
        self.col.addWidget(self.identity)
        self.lay.addLayout(self.col, 1)
        self.temp = label("", "label")
        self.lay.addWidget(self.temp)
        self.info = InfoButton("", title="Calculation provenance")
        self.lay.addWidget(self.info)
        self.compact = False

    def set_content(self, name_html: str, identity: str, temp_text: str, prov_html: str, compact: bool) -> None:
        self.compact = compact
        self.name.setText(rich(name_html))
        self.name.setVisible(compact and bool(name_html))
        self.identity.setText(rich(identity))
        self.identity.setObjectName("AnaLabel" if compact else "AnaSecondary")
        self.identity.style().unpolish(self.identity)
        self.identity.style().polish(self.identity)
        self.temp.setText(rich(temp_text))
        self.temp.setVisible(bool(temp_text) and not compact)
        self.info.tip_text = prov_html
        self.info.setVisible(bool(prov_html))


class AnalysisPanel(QFrame):
    """Embedded Analysis (replaces the former Calculation details panel)."""

    expand_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.setObjectName("Panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(DETAILS_PANEL_MIN)
        self.size_class = "M"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # ---- header 56
        head = QWidget()
        head.setFixedHeight(56)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(PANEL_PADDING_X, 0, PANEL_PADDING_X, 0)
        hl.setSpacing(0)
        self.title = label("Analysis", "heading02")
        self.title.setObjectName("PanelTitle")
        hl.addWidget(self.title)
        hl.addSpacing(8)
        self.suffix = label("", "body")
        self.suffix.setObjectName("PanelTitleSuffix")
        hl.addWidget(self.suffix)
        hl.addStretch(1)
        self.switcher = ContentSwitcher(["Composition", "Collection"])
        hl.addWidget(self.switcher)
        hl.addSpacing(12)
        self.expand_btn = IconButton("maximize", "Expand analysis (Ctrl+Shift+E)")
        self.expand_btn.setAccessibleName("Expand analysis")
        hl.addWidget(self.expand_btn)
        hl.addSpacing(4)
        self.overflow_btn = IconButton("overflow_menu_vertical", "Options")
        hl.addWidget(self.overflow_btn)
        root.addWidget(head)
        # ---- context bar
        self.context_stack = QStackedWidget()
        self.comp_bar = CompositionBar()
        self.scope_bar = ScopeBar(controller)
        self.context_stack.addWidget(self.comp_bar)
        self.context_stack.addWidget(self.scope_bar)
        self.context_stack.setFixedHeight(40)
        root.addWidget(self.context_stack)
        # ---- tabs
        self.tab_stack = QStackedWidget()
        self.comp_tabs = LineTabs(list(S.COMP_TAB_LABELS))
        self.coll_tabs = LineTabs(list(S.COLL_TAB_LABELS))
        for tabs in (self.comp_tabs, self.coll_tabs):
            wrap = QWidget()
            tl = QHBoxLayout(wrap)
            tl.setContentsMargins(PANEL_PADDING_X, 0, PANEL_PADDING_X, 0)
            tl.addWidget(tabs)
            self.tab_stack.addWidget(wrap)
        self.tab_stack.setFixedHeight(32)
        root.addWidget(self.tab_stack)
        # ---- content
        self.content_stack = QStackedWidget()
        self.composition = CompositionContent("M")
        self.composition.batch_mass = controller.batch_mass
        controller.batch_mass_changed.connect(self.composition.set_batch_mass)
        self.collection = CollectionContent(controller, "M")
        self.content_stack.addWidget(self.composition)
        self.content_stack.addWidget(self.collection)
        root.addWidget(self.content_stack, 1)
        # ---- wiring
        self.switcher.changed.connect(lambda i: self.c.apply(S.switch_context, (S.COMPOSITION, S.COLLECTION)[i]))
        self.comp_tabs.changed.connect(lambda i: self.c.apply(S.set_tab, S.COMP_TABS[i]))
        self.coll_tabs.changed.connect(lambda i: self.c.apply(S.set_tab, S.COLL_TABS[i]))
        self.composition.open_tab.connect(lambda tab: self.c.apply(S.set_tab, tab))
        self.composition.model_selected.connect(lambda m: self.c.apply(S.select_model, m))
        self.expand_btn.clicked.connect(self.expand_requested.emit)
        self.overflow_btn.clicked.connect(self.open_overflow)
        controller.state_changed.connect(self._state_changed)
        controller.composition_changed.connect(self._composition_changed)
        self._has_results = False
        self._sync(None, controller.state)
        self._composition_changed()

    # ------------------------------------------------------------------ compatibility (tests / tools)
    @property
    def row(self):
        """The materialised result shown in Composition (``ResultRow``) or None."""
        return self.c.row if self.c.state.active is not None and self.c.state.active_gone is None else None

    @property
    def has_results(self) -> bool:
        return self._has_results

    def set_has_results(self, has: bool) -> None:
        if has != self._has_results:
            self._has_results = has
            self._composition_changed()
            self.collection.set_has_results(has)
            self._sync_enabled()

    # ------------------------------------------------------------------ sizing
    def resizeEvent(self, e):
        super().resizeEvent(e)
        cls = size_class_for(self.width())
        if cls != self.size_class:
            self.size_class = cls
            self.composition.set_size_class(cls)
            self.collection.set_size_class(cls)
            self.scope_bar.set_size_class(cls)
            # at S the header has room only for the title, the switcher and the two icon buttons: the alloy
            # name moves to the context bar (frame 13)
            self.suffix.setVisible(self.c.state.context == S.COMPOSITION and cls != "S")
            self._composition_changed()

    def sizeHint(self) -> QSize:
        return QSize(805, 465)

    # ------------------------------------------------------------------ state -> view
    def _state_changed(self, old, new):
        self._sync(old, new)

    def _sync(self, old, new: S.AnalysisState):
        ctx = 0 if new.context == S.COMPOSITION else 1
        self.switcher.set_index(ctx)
        self.switcher.set_badge(0, new.composition_badge)
        self.context_stack.setCurrentIndex(ctx)
        self.tab_stack.setCurrentIndex(ctx)
        self.content_stack.setCurrentIndex(ctx)
        self.comp_tabs.set_index(S.COMP_TABS.index(new.comp_tab))
        self.coll_tabs.set_index(S.COLL_TABS.index(new.coll_tab))
        self.composition.setCurrentIndex(S.COMP_TABS.index(new.comp_tab))
        self.composition.set_model(new.model)
        self.composition.set_search(new.descriptor_search, new.full_precision)
        if ctx == 1 and (old is None or old.context != new.context):
            self.c.ensure_scope()
        self.suffix.setVisible(ctx == 0 and self.size_class != "S")
        self.context_stack.setFixedHeight(48 if ctx == 0 and self.size_class == "S" and self.row is not None else 40)
        if old is not None and (old.active_gone != new.active_gone or old.active != new.active):
            self._composition_changed()
        self._sync_enabled()

    def _sync_enabled(self):
        has = self._has_results
        self.expand_btn.setEnabled(has)
        self.expand_btn.setToolTip("Expand analysis (Ctrl+Shift+E)" if has else
                                   "Expand analysis — available after a calculation")
        self.overflow_btn.setEnabled(has)
        comp_ok = self.row is not None
        for b in self.comp_tabs.buttons:
            b.setEnabled(comp_ok)
        for b in self.coll_tabs.buttons:
            b.setEnabled(has)

    def _composition_changed(self):
        st = self.c.state
        row = self.row
        if row is None:
            self.suffix.setText("")
            self.comp_bar.set_content("", "", "", "", False)
            if st.active is not None and st.active_gone:
                if st.active_gone == S.RECALCULATED:
                    title, body = "This composition was recalculated", \
                        "The result was recalculated; double-click the row again."
                else:
                    title, body = "This composition was removed", \
                        "The result you were analysing was removed from the results table. Double-click another " \
                        "row to continue."
            elif self._has_results:
                title, body = "No composition selected", \
                    "Double-click a row in the results table to analyse that composition here."
            else:
                title, body = "No results to analyse yet", \
                    "Calculate a composition or a composition set. Its descriptors, model predictions and " \
                    "collection statistics appear here."
            self.composition.set_empty(title, body)
            self._sync_enabled()
            return
        info = self.c.run_info(self.c.record.run_id) if self.c.record is not None else None
        self.composition.set_result(row, info, self.c.record)
        name_html = CMP.name_html(row.name)
        self.suffix.setText(name_html)
        res = row.result
        temp = f"Calculated with T = {res.temperature:.0f} K for M6, M7" if res.temperature is not None else ""
        prov = provenance_html(res, info)
        compact = self.size_class == "S"
        ident = self.composition.identity_text()
        if compact:
            from ...core.family import family_key
            ident = f"{family_key(res.composition)} · {len(res.composition)} elements"
        self.comp_bar.set_content(name_html, ident, temp, prov, compact)
        self.context_stack.setFixedHeight(48 if compact and self.c.state.context == S.COMPOSITION else 40)
        self._sync_enabled()

    # ------------------------------------------------------------------ overflow
    def open_overflow(self):
        menu = overflow_menu(self, self.c)
        menu.exec(self.overflow_btn.mapToGlobal(self.overflow_btn.rect().bottomLeft()))
        menu.deleteLater()


def provenance_html(res, info) -> str:
    parts = []
    if info is not None:
        parts.append(f"Calculated {(info.created or '').replace('T', ' ')[:16]} with engine "
                     f"{info.engine_version or '—'} ({mode_name(info.mode)}, run {info.run_id}).")
    if res.temperature is not None:
        src = res.temperature_source or ""
        parts.append(f"M6/M7 temperature {res.temperature:.1f} K ({src}).")
    parts.append("Data: Takeuchi &amp; Inoue (2005), Troparevsky et al. (2015), Kittel CN12, Guo &amp; Liu (2011), "
                 "Bakker (1998).")
    return " ".join(parts)


def overflow_menu(parent, c) -> CarbonMenu:
    """Analysis overflow (design guide 3.1) - same commands in the embedded panel and the workspace."""
    menu = CarbonMenu(parent=parent)
    st = c.state
    if st.context == S.COMPOSITION:
        ok = c.row is not None and st.active_gone is None and c.row.result.ok
        menu.add_action("Copy values", lambda: copy_values(c), enabled=ok)
        a = menu.add_action("Export composition report…", lambda: c.report_requested.emit("composition"),
                            enabled=ok, icon="document_export")
        a.setToolTip("" if ok else "No composition to report")
        menu.add_action("Print composition report…", lambda: c.report_requested.emit("print"), enabled=ok,
                        icon="printer")
        menu.add_action("Show full precision", lambda: c.apply(S.update, full_precision=not st.full_precision),
                        checkable=True, checked=st.full_precision)
        menu.addSeparator()
        nw = menu.add_action("Open in new window", None, enabled=False)
        nw.setToolTip("Not available in this version")
        menu.addSeparator()
        menu.add_action("Help: Prediction model coverage", lambda: c.help_requested.emit("models"))
    else:
        has = st.resolved is not None and st.resolved.n > 0
        a = menu.add_action("Export analysis report…", lambda: c.report_requested.emit("collection"),
                            enabled=has, icon="document_export")
        a.setToolTip("" if has else "Nothing to export in this collection")
        menu.add_action("Export statistics (CSV)…", lambda: c.export_requested.emit("stats_csv"), enabled=has)
        menu.add_action("Export plotted data (CSV)…", lambda: c.export_requested.emit("plot_csv"), enabled=has)
        menu.add_action("Export plot (SVG)…", lambda: c.export_requested.emit("plot_svg"), enabled=has)
        menu.add_action("Export plot (PNG)…", lambda: c.export_requested.emit("plot_png"), enabled=has)
        menu.addSeparator()
        menu.add_action("Help: Analysing collections", lambda: c.help_requested.emit("collections"))
    return menu


def copy_values(c) -> None:
    """Copy the active composition's descriptors and verdicts (TSV, ASCII minus) to the clipboard."""
    from PySide6.QtGui import QGuiApplication
    from ...core.analysis.metrics import DESCRIPTORS_LIST
    row = c.row
    if row is None:
        return
    d = row.result.descriptors
    lines = ["Quantity\tSymbol\tValue\tUnit"]
    for dd in DESCRIPTORS_LIST:
        v = d.get(dd.key)
        if v is None:
            continue
        lines.append(f"{dd.name}\t{dd.plain}\t{v!r}\t{dd.unit}".replace("−", "-"))
    for k in MODEL_KEYS:
        o = row.result.models[k]
        lines.append(f"{k}\t\t{o.label}\t{o.status if o.label != 'N/A' else (o.na_kind or '')}")
    QGuiApplication.clipboard().setText(row.name + "\r\n" + "\r\n".join(lines) + "\r\n")


_ = QTimer
