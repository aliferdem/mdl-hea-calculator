"""Collection analysis: scope bar and the Overview / Plots / Statistics / Models pages (design guide frames
6-12, 16-17, 20-31).  Every number is the answer of a repository query on the resolved scope (controller
slots, background thread); the pages only format it.

Size classes: ``S`` / ``M`` / ``L`` (embedded panel) and ``W`` (expanded workspace: a controls rail and
regions on the background).  Views request their data only while visible; answers are cached by the
controller (scope key, data version, parameters), so switching tabs, contexts or presentation does not
query again.
"""

from __future__ import annotations

import html as _html

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout,
                               QWidget)

from ...core.analysis import models as MD
from ...core.analysis import state as S
from ...core.analysis.metrics import DESCRIPTORS, GROUP_SHORT, METRIC_KEYS, format_value
from ...core.analysis.plotting import (AUTO, BAR_GROUPED, BAR_STACKED, BINNED, BOX, HEATMAP, HISTOGRAM, LINE,
                                       PLOT_TYPES, RAW, SAMPLED, SCATTER, TYPE_LABELS, TYPE_SHORT, available_types,
                                       default_config, representation_text, validate)
from ...core.analysis.queries import (DIM_BLOCK, DIM_CSTR, DIM_FAMILY, DIM_NONE, DIM_SIZE, RAW_POINT_LIMIT,
                                      dim_label, dim_value_text, is_dimension, run_metrics)
from ...core.analysis.scope import BASE_LABELS, COMBINED_RUN_ID, FILTERED, FULL, filter_text
from ...core.engine import MODEL_KEYS, NA, NA_ERROR, NA_MISSING_DATA, NA_UNDEFINED, MODELS
from .. import crisp, icons
from ..theme import LABEL_01, PANEL_PADDING_X, font, t
from ..widgets.common import IconButton, button
from ..widgets.common import retire
from ..widgets.tooltip import InfoButton
from .composition_view import mode_name
from .plot import PlotSpec, PlotWidget, class_color, categorical
from .widgets import (ROW_SM, ROW_XS, ActionableNotification, Cell, DataTable, Divider, Dropdown, EmptyBlock,
                      InlineLoading, KVRows, LabeledField, MultiSelect, SectionHeading, Skeleton, label,
                      CurrentStack, hstrip, open_popover, plain_text, rich, scroll_page)

ANA_SCOPE = ("The collection is fixed when it is created or updated. Sorting, paging and double-clicking in the "
             "results table do not change it. Changes to the table filter are announced here; choose Update "
             "collection to apply them.")
ANA_STATS = ("N = {n} results in scope. N/A values are excluded and counted under N missing. Quartiles by linear "
             "interpolation between ordered values (type 7); SD uses n − 1.")
ANA_DENOMINATOR = ("Percentages are relative to the {e} results for which the model could be evaluated; {na} "
                   "not-available results are listed separately. Choose \"All results in scope\" to include them in "
                   "the denominator.")
ANA_SAMPLED = ("{N} points are too many to draw individually. A uniform random sample of {n} points (fixed seed) is "
               "shown; statistics and counts use all {N} results.")


# ====================================================================== helpers
def run_label(info, count: int | None = None, short: bool = False) -> str:
    if info.run_id == COMBINED_RUN_ID:
        from ...core.analysis.combine import combined_label
        base = combined_label((info.source or {}).get("combined", ()))
        if short or count is None:
            return base
        return f"{base}, {count:,} result{'s' if count != 1 else ''}"
    base = f"Run {info.run_id} ({mode_name(info.mode)})"
    if short or count is None:
        return base
    return f"{base}, {count:,} result{'s' if count != 1 else ''}"


def metric_items(info, include_design: bool = True, numeric_only: bool = True):
    """Dropdown items "Symbol (unit)" grouped by section headers (plotting spec section 2)."""
    out, last = [], None
    for m in run_metrics(info):
        if m.kind != "descriptor" and not include_design:
            continue
        section = {"variable": "Design", "fraction": "Composition", "grid": "Design", "count": "Composition"}.get(
            m.kind, GROUP_SHORT.get(DESCRIPTORS[m.id].group, "") if m.id in DESCRIPTORS else "")
        if section != last:
            out.append(("--section--", section))
            last = section
        out.append((m.id, f"{m.symbol} ({m.unit or '–'})"))
    return out


def color_items(info):
    out = [("none", "None"), ("--section--", "Model prediction")]
    out += [(f"model:{k}", f"{k} class") for k in MODEL_KEYS]
    out += [("--section--", "Model status")] + [(f"status:{k}", f"{k} status") for k in ("M6", "M7")]
    out += [("--section--", "Groups"), (DIM_FAMILY, "Element family"), (DIM_SIZE, "System size"),
            (DIM_CSTR, "Crystal structure (VEC rule)")]
    if info is not None and info.mode == "expression":
        out.append((DIM_BLOCK, "Expression block"))
    out += [("--section--", "Continuous metric")]
    out += [(k, f"{DESCRIPTORS[k].symbol} ({DESCRIPTORS[k].unit or '–'})") for k in METRIC_KEYS]
    return out


def group_items(info, with_none: bool = True):
    out = [("none", "None")] if with_none else []
    out += [(DIM_FAMILY, "Element family"), (DIM_SIZE, "System size")]
    if info is not None and info.mode == "expression":
        out.append((DIM_BLOCK, "Expression block"))
    return out


class _CountLabel(QWidget):
    """"**341** of 341 results" with an optional stale (warning--alt) icon before it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.icon = QWidget()
        self.icon.setFixedSize(16, 16)
        self.icon.paintEvent = self._paint_icon
        self.icon.setToolTip("Collection out of date")
        lay.addWidget(self.icon)
        self.text = label("", "body")
        lay.addWidget(self.text)

    def _paint_icon(self, _e):
        p = QPainter(self.icon)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icons.paint(p, "warning_alt", QRectF(0, 0, 16, 16), "support-warning")
        p.end()

    def set(self, n: int | None, total: int | None, stale: bool) -> None:
        self.icon.setVisible(stale)
        if n is None:
            self.text.setText("")
            return
        tot = f" of {total:,}" if total is not None else ""
        self.text.setText(f"<b>{n:,}</b>{tot} result{'s' if (total or n) != 1 else ''}")


# ====================================================================== scope controls (shared)
def run_items(c):
    out = [(info.run_id, run_label(info, c.run_count(info.run_id)), True, "", run_label(info, short=True))
           for info in c.runs()]
    if c.combined_runs:
        ci = c.run_info(COMBINED_RUN_ID)
        if ci is not None:
            out.append((COMBINED_RUN_ID, run_label(ci, c.run_count(COMBINED_RUN_ID)), True, "",
                        run_label(ci, short=True)))
    many = len(out) - (1 if c.combined_runs else 0) >= 2
    out.append(("combine", "Combine runs…", many, "" if many else "Combining needs at least two calculation runs"))
    return out


def pop_items(c):
    filt = bool(c.model and c.model.filters)
    return [(FULL, "Full result set"),
            (FILTERED, "Filtered result set", filt, "" if filt else "No filter is set in the results table")]


def run_changed(c, run_id, parent=None) -> None:
    if run_id is None:
        return
    if run_id == "combine":
        from .combine_dialog import CombineRunsDialog
        dlg = CombineRunsDialog(c, parent)
        if dlg.exec() and dlg.chosen:
            c.combine(dlg.chosen)
        dlg.deleteLater()
        return
    c.scope_for(int(run_id), FULL)


def pop_changed(c, base) -> None:
    sc = c.state.scope
    if sc is not None:
        c.scope_for(sc.run_id, base, sc.families, sc.sizes, sc.blocks)


def restriction_controls(c):
    """Element family / System size / Expression block MultiSelects with the unrestricted counts."""
    sc = c.state.scope
    opts = c.data.get("options") or {}
    fam = MultiSelect("families", [(k, f"{k} ({n:,})") for k, _s, n in opts.get("families", [])],
                      sc.families or (), accessible="Element family")
    size = MultiSelect("sizes", [(k, f"{k} elements ({n:,})") for k, n in opts.get("sizes", {}).items()
                                 if k is not None], sc.sizes or (), accessible="System size")
    info = c.run_info(sc.run_id)
    blocks = None
    if info is not None and info.mode == "expression":
        exprs = {b["index"]: b["expression"] for b in (info.source or {}).get("blocks", [])}
        blocks = MultiSelect("blocks", [(k, f"Block {k + 1}: {exprs.get(k, '')} ({n:,})")
                                        for k, n in opts.get("blocks", {}).items()], sc.blocks or (),
                             accessible="Expression block")
    return fam, size, blocks


# ====================================================================== scope bar
class ScopeBar(QWidget):
    """Collection scope controls (design guide 5.3).  M/L inline; S a summary button opening the popover."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.size_class = "M"
        self.stack = QStackedWidget(self)
        outer = QHBoxLayout(self)
        # The panel's Content switcher hangs 4 px into the top of this 40 px bar (Figma 494:69395: y = 12 .. 44,
        # the context bar's empty top 4 px).  The controls therefore start 4 px down - at the bar's top they ran
        # under the switcher wherever it is above them (Restrict, at docked widths).  Bar height unchanged.
        outer.setContentsMargins(PANEL_PADDING_X, 4, PANEL_PADDING_X, 4)
        outer.addWidget(self.stack)
        # ---- inline (M / L)
        inline = QWidget()
        il = QHBoxLayout(inline)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(8)
        self.run_dd = Dropdown(accessible="Calculation run", width=240)
        self.pop_dd = Dropdown(accessible="Population", width=184)
        self.restrict_btn = button("Restrict", "ghost", "sm")
        self.restrict_btn.setIcon(icons.icon("filter", "link-primary"))
        self.restrict_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        il.addWidget(self.run_dd)
        il.addWidget(self.pop_dd)
        il.addWidget(self.restrict_btn)
        il.addStretch(1)
        self.count = _CountLabel()
        il.addWidget(self.count)
        self.info = InfoButton(ANA_SCOPE, title="Collection scope")
        il.addWidget(self.info)
        self.stack.addWidget(inline)
        # ---- summary button (S)
        summary = QWidget()
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(0, 0, 0, 0)
        self.summary_btn = Dropdown([], None, inline=True, accessible="Collection scope", placeholder="")
        self.summary_btn.link = True
        self.summary_btn.clicked.disconnect()
        self.summary_btn.clicked.connect(self.open_scope_popover)
        sl.addWidget(self.summary_btn)
        self.stack.addWidget(summary)
        self.run_dd.changed.connect(self._run_changed)
        self.pop_dd.changed.connect(self._pop_changed)
        self.restrict_btn.clicked.connect(self.open_restrict)
        # bound methods only: they disconnect themselves when this widget is deleted
        controller.state_changed.connect(self._on_state)
        controller.runs_changed.connect(self.refresh)
        controller.data_ready.connect(self._on_data)
        self.refresh()

    def _on_state(self, *_):
        self.refresh()

    def _on_data(self, slot: str):
        if slot in ("population", "options"):
            self.refresh()

    def set_size_class(self, cls: str) -> None:
        self.size_class = cls
        self.stack.setCurrentIndex(1 if cls == "S" else 0)
        self.refresh()

    # -------------------------------------------------------------- content
    def run_items(self):
        return run_items(self.c)

    def pop_items(self):
        return pop_items(self.c)

    def refresh(self) -> None:
        st = self.c.state
        sc = st.scope
        self.run_dd.set_items(self.run_items(), sc.run_id if sc else None)
        self.pop_dd.set_items(self.pop_items(), sc.base if sc else FULL)
        self.restrict_btn.setText(f"Restrict ({sc.restricted})" if sc and sc.restricted else "Restrict")
        n = st.resolved.n if st.resolved else None
        pop = self.c.data.get("population") if self.c.data_keys.get("population", (None, None))[1] == (
            sc.key() if sc else None) else None
        n_now = pop["n"] if pop else n
        total = self.c.run_count(sc.run_id) if sc else None
        self.count.set(n_now, total, st.stale is not None)
        enabled = sc is not None
        for w in (self.pop_dd, self.restrict_btn):
            w.setEnabled(enabled)
        if sc is not None:
            info = self.c.run_info(sc.run_id)
            text = f"Run {sc.run_id}, {BASE_LABELS[sc.base]}" + (f", {n_now:,} results" if n_now is not None else "")
            if sc.restricted:
                text += f", restricted ({sc.restricted})"
            if st.stale:
                text = "⚠ " + text
            self.summary_btn.items = [("s", text)]
            self.summary_btn.value = "s"
            self.summary_btn.update()
            _ = info
        else:
            self.summary_btn.items = [("s", "No collection")]
            self.summary_btn.value = "s"
            self.summary_btn.update()

    # -------------------------------------------------------------- actions
    def _run_changed(self, run_id):
        run_changed(self.c, run_id, self.window())
        self.refresh()                       # a cancelled Combine runs dialog leaves the scope as it was

    def _pop_changed(self, base):
        pop_changed(self.c, base)

    def restriction_controls(self):
        return restriction_controls(self.c)

    def open_restrict(self):
        sc = self.c.state.scope
        if sc is None:
            return
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        fam, size, blocks = self.restriction_controls()
        lay.addWidget(LabeledField("Element family", fam))
        lay.addWidget(LabeledField("System size", size))
        if blocks is not None:
            lay.addWidget(LabeledField("Expression block", blocks))
            by_block = (self.c.run_info(sc.run_id).source or {}).get("duplicates_by_block") or {}
            for b, d in sorted(by_block.items(), key=lambda kv: int(kv[0])):
                if d:
                    lay.addWidget(label(f"Block {int(b) + 1}: {d:,} compositions were first generated by an earlier "
                                        "block and are counted there.", "helper", wrap=True))
        foot = QHBoxLayout()
        clear = button("Clear restrictions", "ghost", "sm")
        apply = button("Apply", "primary", "sm")
        foot.addWidget(clear)
        foot.addStretch(1)
        foot.addWidget(apply)
        lay.addLayout(foot)
        pop = open_popover(self.restrict_btn, content, 360, title="Restrict collection")
        if pop is None:
            return

        def do_apply():
            self.c.scope_for(sc.run_id, sc.base, fam.selected, size.selected, blocks.selected if blocks else None)
            pop.close()

        def do_clear():
            self.c.scope_for(sc.run_id, sc.base)
            pop.close()
        apply.clicked.connect(do_apply)
        clear.clicked.connect(do_clear)

    def open_scope_popover(self):
        sc = self.c.state.scope
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        run = Dropdown(self.run_items(), sc.run_id if sc else None, accessible="Calculation run")
        pop_dd = Dropdown(self.pop_items(), sc.base if sc else FULL, accessible="Population")
        lay.addWidget(LabeledField("Calculation run", run))
        lay.addWidget(LabeledField("Population", pop_dd))
        fam = size = blocks = None
        if sc is not None:
            fam, size, blocks = self.restriction_controls()
            lay.addWidget(LabeledField("Element family", fam))
            lay.addWidget(LabeledField("System size", size))
            if blocks is not None:
                lay.addWidget(LabeledField("Expression block", blocks))
        foot = QHBoxLayout()
        clear = button("Clear restrictions", "ghost", "sm")
        apply = button("Apply", "primary", "sm")
        foot.addWidget(clear)
        foot.addStretch(1)
        foot.addWidget(apply)
        lay.addLayout(foot)
        pop = open_popover(self.summary_btn, content, 360, title="Collection scope")
        if pop is None:
            return

        def run_chosen(v):
            if v == "combine":                       # Combine runs… opens its own dialog at once
                pop.close()
                run_changed(self.c, "combine", self.window())
        run.changed.connect(run_chosen)

        def do_apply():
            rid = run.value if isinstance(run.value, int) else (sc.run_id if sc else None)
            if rid is None:
                pop.close()
                return
            same_run = sc is not None and rid == sc.run_id
            self.c.scope_for(rid, pop_dd.value or FULL, fam.selected if fam and same_run else None,
                             size.selected if size and same_run else None,
                             blocks.selected if blocks and same_run else None)
            pop.close()

        def do_clear():
            if sc is not None:
                self.c.scope_for(sc.run_id, sc.base)
            pop.close()
        apply.clicked.connect(do_apply)
        clear.clicked.connect(do_clear)


# ====================================================================== collection content
class CollectionContent(QWidget):
    """The four Collection pages for one controller (embedded panel or workspace)."""

    def __init__(self, controller, size_class: str = "M", parent=None):
        super().__init__(parent)
        self.c = controller
        self.size_class = size_class
        self.has_results = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = CurrentStack()
        lay.addWidget(self.stack)
        self.pages = [QWidget() for _ in S.COLL_TABS]
        for pg in self.pages:
            QVBoxLayout(pg).setContentsMargins(0, 0, 0, 0)
            self.stack.addWidget(pg)
        self._built: dict[int, tuple] = {}
        self.plot: PlotWidget | None = None
        self._pending_build = False
        # suspended: nobody is looking at this view (the other Analysis view is in use) - no builds, fills or
        # plot renders; what was skipped is caught up once, on resume
        self.suspended = False
        self._dirty = False
        controller.state_changed.connect(self._state_changed)
        controller.data_ready.connect(self._data_ready)
        controller.loading.connect(self._loading)
        controller.failed.connect(self._failed)
        controller.requery.connect(self._request_visible)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(0)
        self._rebuild_timer.timeout.connect(self._rebuild_now)
        self._rebuild_now()

    # -------------------------------------------------------------- lifecycle
    def set_size_class(self, cls: str) -> None:
        if cls != self.size_class:
            self.size_class = cls
            self._built.clear()
            self._schedule()

    def set_has_results(self, has: bool) -> None:
        if has != self.has_results:
            self.has_results = has
            self._built.clear()
            self._schedule()

    def _schedule(self):
        self._rebuild_timer.start()

    def set_suspended(self, on: bool) -> None:
        on = bool(on)
        if on == self.suspended:
            return
        self.suspended = on
        if not on and self._dirty:
            self._dirty = False
            self._built.clear()                  # the visible page is rebuilt once from the (cached) answers
            self._schedule()

    def _skip(self) -> bool:
        if self.suspended:
            self._dirty = True
            return True
        return False

    def showEvent(self, e):
        super().showEvent(e)
        self._schedule()

    def _visible_page(self) -> int:
        return S.COLL_TABS.index(self.c.state.coll_tab)

    def _signature(self, i: int) -> tuple:
        st = self.c.state
        sc = st.scope
        base = (self.size_class, sc.key() if sc else None, st.scope_gone, st.stale, self.has_results,
                st.data_version, st.newer_results,
                self.c.data.get("dups") if sc is not None and sc.combined else None)   # the combined notice's count
        if i == 1:
            return base + (st.plot,)
        if i == 2:
            return base + (st.stats_metrics, st.stats_group, st.stats_all, st.stats_focus, st.stats_view)
        if i == 3:
            return base + (st.denominator, st.split_status, st.dist_group)
        return base

    def _rebuild_now(self) -> None:
        if self._skip():
            return
        if not self.isVisible() and self._built:
            return
        i = self._visible_page()
        self.stack.setCurrentIndex(i)
        sig = self._signature(i)
        if self._built.get(i, (None,))[0] == sig:
            return
        holder = self.pages[i]
        lay = holder.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                _w = it.widget()
                retire(_w)
        if i == 1:
            self.plot = None
        widget = self._build(i)
        lay.addWidget(widget)
        self._built[i] = (sig, widget)
        self._request(i)

    def _state_changed(self, old, new):
        if self._skip():
            return
        if old.coll_tab != new.coll_tab or old.scope != new.scope or old.stale != new.stale or \
                old.data_version != new.data_version or old.scope_gone != new.scope_gone or                 old.newer_results != new.newer_results or \
                (new.coll_tab == "plots" and old.plot != new.plot) or \
                (new.coll_tab == "statistics" and
                 (old.stats_metrics, old.stats_group, old.stats_all, old.stats_focus, old.stats_view)
                 != (new.stats_metrics, new.stats_group, new.stats_all, new.stats_focus, new.stats_view)) or \
                (new.coll_tab == "models" and (old.denominator, old.split_status, old.dist_group)
                 != (new.denominator, new.split_status, new.dist_group)):
            if new.coll_tab == "plots" and old.plot != new.plot and old.coll_tab == new.coll_tab and \
                    old.scope == new.scope and self.plot is not None and _same_plot_layout(old.plot, new.plot):
                self._request(1)                      # same widgets, new data
                self._sync_plot_controls()
                return
            self._schedule()
        if old.selection != new.selection and self.plot is not None:
            self.plot.set_selection(new.selection)
        if old.active != new.active and self.plot is not None:
            try:
                self.plot.active_id = new.active
                self.plot.update()
            except RuntimeError:
                pass
        if old.inspector != new.inspector:
            self._update_inspector()

    # -------------------------------------------------------------- data requests
    def _request_visible(self):
        if self._skip():
            return
        if self.isVisible():
            self._request(self._visible_page())

    def _request(self, i: int) -> None:
        st = self.c.state
        sc = st.scope
        if sc is None or st.scope_gone:
            return
        info = self.c.run_info(sc.run_id)
        unrestricted = sc.without_restrictions()
        # the unrestricted population (scope options) is the same query as the population of an unrestricted
        # scope: one shared answer (share="population")
        self.c.run_query("options", lambda sq: sq.population(), scope=unrestricted, share="population")
        if i == 0:
            self.c.run_query("population", lambda sq: sq.population())
            self.c.run_query("dist", lambda sq: sq.distribution())
        elif i == 1:
            self.c.run_query("population", lambda sq: sq.population())
            self._request_plot(info)
        elif i == 2:
            metrics = tuple(st.stats_metrics)
            group = st.stats_group
            self.c.request_statistics(metrics)      # one query per metric, rows fill in as they finish
            if self.size_class == "W" and st.stats_focus:
                focus = st.stats_focus              # the user's selected metric (none -> nothing to query)
                known = self.c.statistics_cached(focus)
                self.c.run_query("outliers", lambda sq: sq.outliers(focus, known), params=(focus,))
                if st.stats_view == "groups":       # only the visualization that is shown is queried
                    g = group if group != "none" else DIM_FAMILY
                    self.c.run_query("box", lambda sq: sq.statistics([focus], group=g), params=(focus, g))
                else:
                    self.c.run_query("hist", lambda sq: sq.histogram(focus), params=(focus,))
            elif group != "none":
                self.c.run_query("stats_group", lambda sq: sq.statistics(list(metrics), group=group),
                                 params=(metrics, group))
        elif i == 3:
            g = st.dist_group
            self.c.run_query("dist", lambda sq: sq.distribution())
            if g != "none":
                self.c.run_query("dist_group", lambda sq: sq.distribution(g), params=(g,))

    def _request_plot(self, info) -> None:
        cfg = self.c.state.plot
        v = validate(cfg, info)
        if not v.ok:
            self._show_plot_invalid(v)
            return
        if cfg.type == SCATTER:
            x, y, color = cfg.x, cfg.y, cfg.color
            if cfg.representation == BINNED:
                bins = (cfg.bins, cfg.bins)
                self.c.run_query("plot", lambda sq: sq.binned(x, y, bins, color), params=("binned", cfg))
            else:
                force = cfg.representation if cfg.representation in (RAW, SAMPLED) else None
                seed = cfg.seed
                self.c.run_query("plot", lambda sq: sq.points(x, y, color, force=force, seed=seed),
                                 params=("points", cfg))
        elif cfg.type == LINE:
            x, y, fixed = cfg.x, cfg.y, cfg.fixed_dict
            self.c.run_query("plot", lambda sq: sq.series(x, [y], fixed), params=("series", cfg))
        elif cfg.type == HISTOGRAM:
            x = cfg.x
            self.c.run_query("plot", lambda sq: sq.histogram(x), params=("hist", cfg))
        elif cfg.type == BOX:
            x, g = cfg.x, cfg.group
            self.c.run_query("plot", lambda sq: sq.statistics([x], group=g), params=("box", cfg))
        elif cfg.type == HEATMAP:
            x, y, val, fixed = cfg.x, cfg.y, cfg.value, cfg.fixed_dict
            self.c.run_query("plot", lambda sq: sq.grid(x, y, val, fixed), params=("grid", cfg))
        elif cfg.type == BAR_STACKED:
            self.c.run_query("plot", lambda sq: sq.distribution(), params=("dist", cfg))
        elif cfg.type == BAR_GROUPED:
            g = cfg.group
            self.c.run_query("plot", lambda sq: sq.distribution(g), params=("distg", cfg))

    def _data_ready(self, slot: str) -> None:
        if self._skip() or not self.isVisible():
            return
        i = self._visible_page()
        if slot in ("population", "options"):
            if i == 0:
                self._fill_overview()
        elif slot == "plot" and i == 1:
            self._fill_plot()
        elif slot in ("stats", "stats_group", "hist", "box", "outliers") and i == 2:
            self._fill_statistics()
        elif slot in ("dist", "dist_group"):
            if i == 3:
                self._fill_models()
            elif i == 0:
                self._fill_overview()
        elif slot == "dups":
            self._schedule()                     # the combined-collection notice states the duplicate count

    def _loading(self, slot: str, busy: bool) -> None:
        if self.suspended:
            return
        if slot == "plot" and self.plot is not None and self._visible_page() == 1:
            self._set_plot_loading(busy)
        if slot == "stats" and self._visible_page() == 2 and hasattr(self, "stats_loading"):
            try:
                self.stats_loading.setVisible(busy)
            except RuntimeError:
                pass

    def _failed(self, slot: str, msg: str) -> None:
        if self._skip():
            return
        if slot == "plot" and self._visible_page() == 1 and hasattr(self, "plot_note"):
            try:
                self.plot_note.show_message("error", "The plot could not be loaded", _html.escape(msg), "Retry")
                self._set_plot_loading(False)
            except RuntimeError:
                pass

    # -------------------------------------------------------------- builders
    def _empty(self, title: str, body: str, buttons=()) -> QWidget:
        w = EmptyBlock(title, body, "magnifier" if "match" in title else "document", buttons,
                       centred=self.size_class == "W")
        w.action.connect(self._empty_action)
        return w

    def _empty_action(self, key: str) -> None:
        sc = self.c.state.scope
        if key == "full" and sc is not None:
            self.c.scope_for(sc.run_id, FULL)
        elif key == "back":
            self.c.expand_requested.emit(False)

    def _notices(self, lay) -> None:
        """Stale scope / partial run notifications: the first item of the scrolling content."""
        st = self.c.state
        sc = st.scope
        if st.stale:
            note = ActionableNotification()
            body = (f"This collection still uses the filter {filter_text(sc.filters) or '(none)'} "
                    f"({st.resolved.n:,} results). The results table now uses a different filter.")
            note.show_message("warning", "Results filter changed", body, "Update collection")
            note.action.connect(self.c.update_collection)
            lay.addWidget(note)
        info = self.c.run_info(sc.run_id) if sc else None
        if info is not None and sc.blocks:
            by_block = (info.source or {}).get("duplicates_by_block") or {}
            d = sum(int(by_block.get(str(b), 0)) for b in sc.blocks)
            if d:
                note = ActionableNotification()
                note.show_message("info", "Duplicates counted in an earlier block",
                                  f"{d:,} compositions generated by the selected block(s) were first generated by an "
                                  "earlier block and are counted there.")
                lay.addWidget(note)
        if sc is not None and sc.combined:
            parts = ", ".join(f"Run {r} ({self.c.run_count(r):,})" for r in sc.run_ids)
            dups = self.c.data.get("dups") if self.c.data_keys.get("dups", (None, None))[1] == sc.key() else None
            dup_text = (f" {dups:,} composition{'s occur' if dups != 1 else ' occurs'} in more than one run; each "
                        "result counts once." if dups else " Each result counts once; nothing is merged.")
            note = ActionableNotification()
            note.show_message("info", "Combined collection",
                              f"{parts}. Counts, statistics and distributions use all of them together.{dup_text} "
                              "Design variables and expression blocks belong to single runs and are not offered "
                              "here.")
            lay.addWidget(note)
        loaded = f" loaded at {st.resolved.resolved_at}" if st.resolved is not None else ""
        if info is not None and info.status == "running":
            # one notice while the run streams (never one per commit): the collection keeps its snapshot
            note = ActionableNotification()
            note.show_message("info", "Calculation in progress",
                              f"{self.c.run_count(sc.run_id):,} of {info.expected or 0:,} results stored. This "
                              f"collection shows the results{loaded}; refresh to include newer ones.", "Refresh")
            note.action.connect(self.c.refresh_collection)
            lay.addWidget(note)
        elif st.newer_results:
            note = ActionableNotification()
            note.show_message("info", "Newer results available",
                              f"Run {sc.run_id} has stored results since this collection was{loaded or ' loaded'}. "
                              "Refresh to include them.", "Refresh")
            note.action.connect(self.c.refresh_collection)
            lay.addWidget(note)
        elif info is not None and info.status in ("cancelled", "failed", "interrupted"):
            note = ActionableNotification()
            verb = {"cancelled": "was cancelled", "failed": "failed", "interrupted": "was interrupted"}[info.status]
            note.show_message("warning", f"Partial run",
                              f"This run {verb} after {info.calculated:,} of {info.expected or info.calculated:,} "
                              "compositions. The collection contains the stored results only.")
            lay.addWidget(note)

    def _scope_problem(self) -> QWidget | None:
        st = self.c.state
        if not self.has_results:
            return self._empty("No collection to analyse yet",
                               "Run a composition space or an expression to analyse many compositions together.")
        if st.scope_gone:
            return self._empty("The calculation run of this collection was removed",
                               "Choose another calculation run in the scope bar.")
        if st.resolved is None:
            return InlineLoading("Resolving the collection…", cancellable=False)
        if st.resolved.n == 0:
            return self._empty("No results match this collection",
                               f"The filter excludes every result of Run {st.scope.run_id}. Change the filter in the "
                               "results table, or analyse the full result set.",
                               (("full", "Use full result set"), ("back", "Back to calculation"))
                               if self.size_class == "W" else (("full", "Use full result set"),))
        return None

    def _build(self, i: int) -> QWidget:
        problem = self._scope_problem()
        if problem is not None:
            return problem
        return (self._build_overview, self._build_plots, self._build_statistics, self._build_models)[i]()

    # ================================================================== Overview
    def _build_overview(self) -> QWidget:
        if self.size_class == "W":
            return self._build_overview_ws()
        content = QWidget()
        sa, lay = scroll_page(content)
        self._notices(lay)
        self.ov_host = QWidget()
        self.ov_lay = QVBoxLayout(self.ov_host)
        self.ov_lay.setContentsMargins(0, 0, 0, 0)
        self.ov_lay.setSpacing(16)
        lay.addWidget(self.ov_host)
        lay.addStretch(1)
        self._fill_overview()
        return sa

    def _fill_overview(self) -> None:
        if self.size_class == "W":
            return self._fill_overview_ws()
        try:
            lay = self.ov_lay
        except (AttributeError, RuntimeError):
            return
        pop = self._current("population")
        if pop is None:
            return
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                retire(w)
            elif it.layout() is not None:
                _clear_layout(it.layout())
        cls = self.size_class
        sc = self.c.state.scope
        info = self.c.run_info(sc.run_id)
        population = self._population_rows(pop, info)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        ll.addWidget(SectionHeading("Population"))
        ll.addWidget(KVRows(population, label_w=172, value_w=160 if cls != "S" else 200, unit_w=0))
        ll.addStretch(1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(SectionHeading("System size", f"Denominator: {pop['n']:,}"))
        rl.addWidget(self._size_bars(pop, 140 if cls == "S" else 200))
        rl.addSpacing(8)
        rl.addWidget(SectionHeading("Element families"))
        rl.addWidget(self._family_table(pop, cls))
        if cls == "S":
            lay.addWidget(left)
            lay.addWidget(right)
        else:
            row = QHBoxLayout()
            row.setSpacing(24)
            row.addWidget(left, 1)
            row.addWidget(right, 1)
            lay.addLayout(row)
        lay.addWidget(SectionHeading("Source"))
        lay.addWidget(label(source_text(info, pop), "body", wrap=True))
        cov = SectionHeading("Model coverage", link="View distributions")
        cov.link_clicked.connect(lambda: self.c.apply(S.set_tab, "models"))
        lay.addWidget(cov)
        lay.addWidget(label(self._coverage_text(pop), "body", wrap=True))

    def _population_rows(self, pop, info):
        sizes = [k for k in pop["sizes"] if k is not None]
        status = {"complete": "Complete", "running": "Calculating", "cancelled": "Cancelled", "failed": "Failed",
                  "interrupted": "Interrupted"}.get(info.status if info else "", "—")
        return [("Results in collection", f"{pop['n']:,}", ""), ("Evaluated", f"{pop['n_evaluated']:,}", ""),
                ("Not evaluable", f"{pop['n_error']:,}", ""), ("Element families", f"{len(pop['families']):,}", ""),
                ("System sizes", (", ".join(str(s) for s in sizes) + " elements") if sizes else "—", ""),
                ("Status of run", status, "")]

    def _size_bars(self, pop, bar_max: int) -> DataTable:
        n = max(1, pop["n"])
        rows = []
        for size, cnt in pop["sizes"].items():
            rows.append([dim_value_text(DIM_SIZE, size), Cell(bar=cnt / n), Cell(f"{cnt:,}", align="right"),
                         Cell(f"{100 * cnt / n:.2f} %", align="right", color="text-secondary")])
        return DataTable([("", 96), ("", None), ("", 56, "right"), ("", 80, "right")], rows, ROW_XS,
                         header=False)

    def _family_table(self, pop, cls) -> DataTable:
        n = max(1, pop["n"])
        rows = [[k or "Not evaluable", Cell(f"{c:,}", align="right"), Cell(f"{100 * c / n:.2f} %", align="right")]
                for k, _s, c in pop["families"][:50]]
        if len(pop["families"]) > 50:
            rest = sum(c for _k, _s, c in pop["families"][50:])
            rows.append([f"Other families ({len(pop['families']) - 50:,})", Cell(f"{rest:,}", align="right"),
                         Cell(f"{100 * rest / n:.2f} %", align="right")])
        return DataTable([("Family", None), ("Results", 72 if cls == "S" else 80, "right"),
                          ("Share", 96, "right")], rows, ROW_XS)

    def _coverage_text(self, pop) -> str:
        dist = self._current("dist")
        if dist is None:
            return "…"
        models = dist["models"]
        full = [k for k in MODEL_KEYS if models[k]["evaluated"] == pop["n"]]
        if len(full) == 8:
            return f"All 8 models evaluated for {pop['n']:,} of {pop['n']:,} results."
        parts = [f"{k} {models[k]['evaluated']:,}" for k in MODEL_KEYS]
        return "Evaluated results per model: " + ", ".join(parts) + f" (of {pop['n']:,})."

    def _current(self, slot: str):
        """The slot's last answer if it belongs to the current scope and data version."""
        key = self.c.data_keys.get(slot)
        sc = self.c.state.scope
        if key is None or sc is None or key[1] != sc.key() or key[2] != self.c.state.data_version:
            return None
        return self.c.data.get(slot)

    # ---- workspace overview (Frame 20; 1.png: no filler medians, nothing stretched down the page)
    def _build_overview_ws(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)
        self.ws_regions = []
        for width in (560, None):
            reg = _Region()
            if width:
                reg.setFixedWidth(width)
            row.addWidget(reg, 0 if width else 1)
            self.ws_regions.append(reg)
        self._fill_overview_ws()
        return host

    def _fill_overview_ws(self) -> None:
        regs = getattr(self, "ws_regions", None)
        pop = self._current("population")
        if not regs or pop is None:
            return
        try:
            for r in regs:
                r.clear()
        except RuntimeError:
            return
        sc = self.c.state.scope
        info = self.c.run_info(sc.run_id)
        a, b = regs
        # what is in this collection and where it came from
        a.add(label("Population &amp; scope", "heading02"))
        self._notices(a.lay)
        a.add(KVRows(self._population_rows(pop, info), label_w=200, value_w=200, unit_w=0))
        a.add(SectionHeading("Source"))
        a.add(label(source_text(info, pop), "body", wrap=True))
        specs = (info.source or {}).get("specs") if info else None
        if specs:
            pts = any("points" in s_ for s_ in specs)
            a.add(DataTable([("Element", 100), ("Min", 90, "right"), ("Max", 90, "right"),
                             ("Points" if pts else "Step", 90, "right"), ("Lock", None)],
                            [[s_["element"], Cell(f"{s_['min']:g}", align="right"), Cell(f"{s_['max']:g}", align="right"),
                              Cell(f"{s_['points']}" if "points" in s_ else f"{s_['step']:g}", align="right"),
                              "On (required)" if s_["required"] else "Off (optional)"]
                             for s_ in specs], ROW_XS))
        a.lay.addStretch(1)
        # how it is made up: sizes, families, which models could evaluate it (counts only - no filler medians)
        b.add(label("Distributions", "heading02"))
        b.add(SectionHeading("System size", f"Denominator: {pop['n']:,}"))
        b.add(self._size_bars(pop, 420))
        b.add(SectionHeading("Element families"))
        b.add(self._family_table(pop, "W"))
        dist = self._current("dist")
        b.add(SectionHeading("Model coverage"))
        if dist is not None:
            rows = [[MD.title(k), Cell(f"Evaluated {dist['models'][k]['evaluated']:,} of {pop['n']:,}", align="left"),
                     Cell(f"N/A {dist['models'][k]['na']:,}", color="text-secondary")] for k in MODEL_KEYS]
            b.add(DataTable([("Model", 240), ("", None), ("", 120)], rows, ROW_XS, header=False))
        b.lay.addStretch(1)

    # ================================================================== Plots
    def _build_plots(self) -> QWidget:
        st = self.c.state
        info = self.c.run_info(st.scope.run_id)
        cfg = st.plot
        if self.size_class == "W":
            return self._build_plots_ws(info, cfg)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)
        self._notices(lay)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        if self.size_class == "S":
            self.plot_summary = label(plot_summary(cfg, info), "body")
            self.plot_summary.setToolTip(plain_text(plot_summary(cfg, info)))
            bar.addWidget(self.plot_summary, 1)
            settings = IconButton("settings", "Plot settings")
            settings.clicked.connect(lambda: self._open_plot_settings(settings, info))
            bar.addWidget(settings)
        else:
            self._plot_controls(bar, info, cfg, inline=True)
            bar.addStretch(1)
        reset = IconButton("fit_to_screen", "Reset axes")
        reset.clicked.connect(lambda: self.plot.reset_view() if self.plot else None)
        bar.addWidget(reset)
        exp = IconButton("maximize", "Expand analysis")
        exp.clicked.connect(lambda: self.c.expand_requested.emit(True))
        bar.addWidget(exp)
        lay.addLayout(bar)
        lay.addWidget(self._plot_area(compact=True), 1)
        return host

    def _plot_controls(self, bar_or_lay, info, cfg, inline: bool) -> None:
        """Plot type, X, Y / value / group, Colour dropdowns (+ representation in the workspace)."""
        types = [(tp, TYPE_LABELS[tp] if not inline else TYPE_SHORT[tp]) for tp in available_types(info)]
        self.type_dd = Dropdown(types, cfg.type, accessible="Plot type", inline=False,
                                width=136 if inline else None)
        self.type_dd.changed.connect(lambda tp: self._set_type(tp, info))
        x_items = metric_items(info)
        if cfg.type in (LINE, HEATMAP):
            x_items = [(m.id, f"{m.symbol} — {m.name}") for m in run_metrics(info) if m.ordered]
        self.x_dd = Dropdown(x_items, cfg.x, prefix="X" if inline else "", inline=False,
                             accessible="X metric" if cfg.type not in (HISTOGRAM, BOX) else "Metric",
                             width=160 if inline else None)
        self.x_dd.changed.connect(lambda v: self._set_cfg(x=v))
        controls = [("Plot type", self.type_dd), ("X" if cfg.type not in (HISTOGRAM, BOX) else "Metric", self.x_dd)]
        if cfg.type in (SCATTER, LINE, HEATMAP):
            y_items = x_items if cfg.type == HEATMAP else metric_items(info)
            self.y_dd = Dropdown(y_items, cfg.y, prefix="Y" if inline else "", accessible="Y metric",
                                 width=184 if inline else None)
            self.y_dd.changed.connect(lambda v: self._set_cfg(y=v))
            controls.append(("Y", self.y_dd))
        if cfg.type == SCATTER:
            self.color_dd = Dropdown(color_items(info), cfg.color, prefix="Colour" if inline else "",
                                     accessible="Colour", width=176 if inline else None)
            self.color_dd.changed.connect(lambda v: self._set_cfg(color=v))
            controls.append(("Colour", self.color_dd))
        if cfg.type == HEATMAP:
            vals = [("--section--", "Model prediction")] + [(f"model:{k}", f"{k} class") for k in MODEL_KEYS] + \
                [("--section--", "Metric")] + [(k, f"{DESCRIPTORS[k].symbol} ({DESCRIPTORS[k].unit or '–'})")
                                               for k in METRIC_KEYS]
            self.value_dd = Dropdown(vals, cfg.value, prefix="Value" if inline else "", accessible="Value",
                                     width=176 if inline else None)
            self.value_dd.changed.connect(lambda v: self._set_cfg(value=v))
            controls.append(("Value", self.value_dd))
        if cfg.type in (BOX, BAR_GROUPED):
            self.group_dd = Dropdown(group_items(info, with_none=False), cfg.group, prefix="Group" if inline else "",
                                     accessible="Group", width=176 if inline else None)
            self.group_dd.changed.connect(lambda v: self._set_cfg(group=v))
            controls.append(("Group", self.group_dd))
        if cfg.type == BAR_GROUPED:
            self.model_dd = Dropdown([(k, MD.title(k)) for k in MODEL_KEYS], cfg.model, prefix="Model" if inline else "",
                                     accessible="Model", width=176 if inline else None)
            self.model_dd.changed.connect(lambda v: self._set_cfg(model=v))
            controls.append(("Model", self.model_dd))
        # fixed variables (line / heatmap with more variables than axes)
        if cfg.type in (LINE, HEATMAP) and info is not None and info.mode == "expression":
            used = {cfg.x} | ({cfg.y} if cfg.type == HEATMAP else set())
            for m in run_metrics(info):
                if m.kind == "variable" and m.id not in used:
                    r = (info.source or {}).get("ranges", {}).get(m.plain)
                    vals = _range_values(r, m.plain) if r else []
                    dd = Dropdown([(v, f"{v:g}") for v in vals], cfg.fixed_dict.get(m.id),
                                  prefix=f"Fix {m.plain} at" if inline else "", accessible=f"Fix {m.plain} at",
                                  placeholder="Choose", width=176 if inline else None)
                    dd.changed.connect(lambda v, mid=m.id: self._set_fixed(mid, v))
                    controls.append((f"Fix {m.plain} at", dd))
        for caption, w in controls:
            if inline:
                bar_or_lay.addWidget(w)
            else:
                bar_or_lay.addWidget(LabeledField(caption, w))

    def _sync_plot_controls(self) -> None:
        cfg = self.c.state.plot
        for name, val in (("type_dd", cfg.type), ("x_dd", cfg.x), ("y_dd", cfg.y), ("color_dd", cfg.color),
                          ("value_dd", cfg.value), ("group_dd", cfg.group), ("model_dd", cfg.model),
                          ("rep_dd", cfg.representation)):
            w = getattr(self, name, None)
            try:
                if w is not None and w.value != val:
                    w.set_value(val)
            except RuntimeError:
                pass

    def _set_type(self, tp: str, info) -> None:
        cfg = self.c.state.plot
        d = default_config(info)
        x = cfg.x
        if tp in (LINE, HEATMAP):
            ordered = [m.id for m in run_metrics(info) if m.ordered]
            x = cfg.x if cfg.x in ordered else (ordered[0] if ordered else cfg.x)
        y = cfg.y
        if tp == HEATMAP:
            vars_ = [m.id for m in run_metrics(info) if m.kind == "variable" and m.id != x]
            y = vars_[0] if vars_ else cfg.y
        elif tp == LINE and (is_dimension(y) or y.startswith("var:")):
            y = "vec"
        elif tp == SCATTER and y.startswith("var:"):
            y = d.y if d.type == SCATTER else "dhmix"
        if tp in (HISTOGRAM, BOX) and x.startswith(("var:", "grid:")):
            x = "delta"
        group = cfg.group if cfg.group not in ("none",) else DIM_FAMILY
        self.c.apply(S.set_plot, cfg.with_(type=tp, x=x, y=y, group=group))

    def _set_cfg(self, **kw) -> None:
        self.c.apply(S.set_plot, self.c.state.plot.with_(**kw))

    def _set_fixed(self, mid: str, value) -> None:
        fixed = dict(self.c.state.plot.fixed)
        fixed[mid] = value
        self._set_cfg(fixed=tuple(sorted(fixed.items())))

    def _plot_area(self, compact: bool) -> QWidget:
        area = QWidget()
        lay = QVBoxLayout(area)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.plot_note = ActionableNotification()
        self.plot_note.action.connect(self._plot_note_action)
        lay.addWidget(self.plot_note)
        self.plot_stack = QStackedWidget()
        self.plot = PlotWidget(compact=compact)
        self.plot.legend_mode = "row" if self.size_class == "S" else ("column" if self.size_class in ("L", "W")
                                                                       else "overlay")
        self.plot.set_selection(self.c.state.selection)
        self.plot.active_id = self.c.state.active
        self.plot.point_clicked.connect(self._point_clicked)
        self.plot.point_activated.connect(lambda rid: self.c.set_active(rid, by="inspector"))
        self.skeleton = Skeleton()
        self.plot_empty = QWidget()
        QVBoxLayout(self.plot_empty).setContentsMargins(0, 0, 0, 0)
        self.plot_stack.addWidget(self.plot)
        self.plot_stack.addWidget(self.skeleton)
        self.plot_stack.addWidget(self.plot_empty)
        lay.addWidget(self.plot_stack, 1)
        self.strip = ModelStripPlot(self.plot)
        lay.addWidget(self.strip)
        self.strip.hide()
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.plot_loading = InlineLoading("Loading plot data…")
        self.plot_loading.cancel.connect(lambda: self.c.cancel("plot"))
        self.plot_loading.hide()
        foot.addWidget(self.plot_loading)
        foot.addStretch(1)
        self.selection_bar = QWidget()
        sb = QHBoxLayout(self.selection_bar)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(4)
        self.sel_text = label("", "label")
        sb.addWidget(self.sel_text)
        for text, fn in (("Show in results table", self._show_selection), ("Clear", self._clear_selection)):
            b = button(text, "ghost", "sm")
            b.clicked.connect(fn)
            sb.addWidget(b)
        foot.addWidget(self.selection_bar)
        lay.addLayout(foot)
        self._update_selection_bar()
        self._fill_plot()
        return area

    def _plot_note_action(self) -> None:
        text = self.plot_note.button.text()
        if text == "Retry":
            self.plot_note.hide()
            self._request(1)
        elif text == "Use scatter plot":
            self.plot_note.hide()
            info = self.c.run_info(self.c.state.scope.run_id)
            d = default_config(info)
            self.c.apply(S.set_plot, self.c.state.plot.with_(type=SCATTER, x="delta", y="dhmix",
                                                              color=d.color if d.type == SCATTER else "model:M2"))

    def _show_plot_invalid(self, v) -> None:
        if getattr(self, "plot_note", None) is None:
            return
        try:
            self.plot_note.show_message("error", v.title, v.message, v.fix)
            self.plot.set_spec(None)
            self.plot_stack.setCurrentIndex(0)
            for name in ("type_dd",):
                w = getattr(self, name, None)
                if w is not None:
                    w.set_invalid(True)
        except RuntimeError:
            pass

    def _set_plot_loading(self, busy: bool) -> None:
        try:
            first = self.plot.spec is None
            self.plot_loading.set_text("Loading plot data…" if first else "Updating plot…")
            self.plot_loading.setVisible(busy)
            self.plot.dim = busy and not first
            self.plot.update()
            self.plot_stack.setCurrentIndex(1 if busy and first else 0)
        except (RuntimeError, AttributeError):
            pass

    def _fill_plot(self) -> None:
        if self.plot is None:
            return
        st = self.c.state
        sc = st.scope
        if sc is None:
            return
        info = self.c.run_info(sc.run_id)
        cfg = st.plot
        v = validate(cfg, info)
        try:
            self.type_dd.set_invalid(not v.ok)
        except (AttributeError, RuntimeError):
            pass
        if not v.ok:
            self._show_plot_invalid(v)
            return
        data = self._current("plot")
        key = self.c.data_keys.get("plot")
        if data is None or key is None or len(key[4]) < 2 or key[4][1] != cfg:
            if not self.c.busy("plot"):
                self._request_plot(info)
            return
        self.plot_note.hide()
        spec, empty = build_spec(cfg, data, info, self.size_class)
        if empty is not None:
            self._show_plot_empty(*empty)
            return
        self.plot_stack.setCurrentIndex(0)
        self.plot.set_spec(spec, keep_view=False)
        self.plot.ctrl_zoom = False
        self.strip.setVisible(cfg.type == LINE and cfg.model_strip and self.size_class in ("L", "W"))
        self.strip.update()
        if self.size_class == "W":
            self._update_ws_plot_header(spec, data)

    def _show_plot_empty(self, title: str, body: str) -> None:
        lay = self.plot_empty.layout()
        _clear_layout(lay)
        lay.addWidget(EmptyBlock(title, body, "magnifier", centred=True))
        self.plot_stack.setCurrentIndex(2)

    # ---- selection / inspector
    def _point_clicked(self, rid) -> None:
        if rid is None:
            self.c.apply(S.clear_selection)
            return
        self.c.apply(S.select_points, [rid])
        if self.size_class != "W":
            self._inspector_popover(rid)

    def _update_selection_bar(self) -> None:
        try:
            n = len(self.c.state.selection)
            self.selection_bar.setVisible(n > 0)
            self.sel_text.setText(f"{n:,} point{'s' if n != 1 else ''} selected")
        except (RuntimeError, AttributeError):
            pass

    def _update_inspector(self) -> None:
        self._update_selection_bar()
        if self.size_class == "W" and hasattr(self, "inspector_region"):
            try:
                self._fill_inspector()
            except RuntimeError:
                pass

    def _show_selection(self):
        ids = sorted(self.c.state.selection)
        if ids:
            self.c.show_in_table.emit(ids)

    def _clear_selection(self):
        self.c.apply(S.clear_selection)

    def _inspector_content(self, rid: int, full: bool) -> QWidget | None:
        rec = self.c.repo.get_result(int(rid))
        if rec is None:
            return None
        from ...core import composition as CMP
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(label(CMP.name_html(rec.name), "heading02", wrap=True))
        lay.addWidget(label(f"{rec.family or '—'}, {rec.n_elements or 0} elements", "label"))
        comp = rec.composition
        lay.addWidget(label(", ".join(f"{el} {100 * x:.2f}" for el, x in comp.items()) + " at.%", "label", wrap=True))
        cfg = self.c.state.plot
        plotted = []
        for mid in (cfg.x, cfg.y):
            if mid in DESCRIPTORS:
                dd = DESCRIPTORS[mid]
                plotted.append((dd.symbol, format_value(mid, rec.raw(mid)), dd.unit))
        if plotted:
            lay.addWidget(label("Plotted values", "heading"))
            lay.addWidget(KVRows(plotted, label_w=96, value_w=88, unit_w=80))
        if full:
            lay.addWidget(label("Key descriptors", "heading"))
            rows = []
            for k in ("dsmix", "tm", "omega", "vec", "gamma", "phi_king"):
                if k in (cfg.x, cfg.y):
                    continue
                dd = DESCRIPTORS[k]
                unit = dd.unit
                if k == "vec" and rec.raw("cstr"):
                    unit = rec.raw("cstr")
                rows.append((dd.symbol, format_value(k, rec.raw(k)), unit))
            lay.addWidget(KVRows(rows, label_w=96, value_w=88, unit_w=80))
        lay.addWidget(label("Model predictions", "heading"))
        from .composition_view import _ModelCell
        from .widgets import FlowBox

        class _O:
            def __init__(self, lab, status, caution):
                self.label, self.status, self.caution, self.reason, self.na_kind = lab, status or "in_domain", \
                    caution, None, None
        # tags wrap to the inspector width (2.png: a fixed 4-column grid ran past the region's right edge)
        lay.addWidget(FlowBox([_ModelCell(k, _O(rec.model_label(k), rec.model_status(k), rec.model_caution(k)), 72)
                               for k in MODEL_KEYS]))
        acts = QVBoxLayout()                    # md buttons stacked: they fit the popover and the region
        acts.setSpacing(8)
        # Carbon Button md (40 px), brief §29
        a = button("Analyse composition", "primary", "md")
        a.clicked.connect(lambda: self.c.set_active(rid, by="inspector"))
        b = button("Show in results table", "secondary", "md")
        b.clicked.connect(lambda: self.c.show_in_table.emit([rid]))
        acts.addWidget(a)
        acts.addWidget(b)
        lay.addLayout(acts)
        return w

    def _inspector_popover(self, rid: int) -> None:
        content = self._inspector_content(rid, full=False)
        if content is None or self.plot is None:
            return
        open_popover(self.plot, content, 320, prefer="right", align="center", title="Point inspector")

    # ---- workspace plots (Frame 21)
    PLOTS_REFLOW = 1340          # rail 320 + plot 640 + inspector 340 + gaps: narrower puts the inspector below

    def _build_plots_ws(self, info, cfg) -> QWidget:
        host = _Reflow(self.PLOTS_REFLOW, self._plots_reflow)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)
        rail = _Region()
        rail.setFixedWidth(320)
        self._rail_collection(rail)
        rail.add(Divider())
        rail.add(label("Plot", "heading02"))
        self._plot_controls(rail.lay, info, cfg, inline=False)
        if cfg.type == SCATTER:
            thr = QCheckBox("Show model thresholds")
            thr.setChecked(cfg.thresholds)
            thr.toggled.connect(lambda on: self._set_cfg(thresholds=on))
            rail.add(thr)
            lx = QCheckBox("Logarithmic X")
            lx.setChecked(cfg.log_x)
            lx.toggled.connect(lambda on: self._set_cfg(log_x=on))
            ly = QCheckBox("Logarithmic Y")
            ly.setChecked(cfg.log_y)
            ly.toggled.connect(lambda on: self._set_cfg(log_y=on))
            rail.add(lx)
            rail.add(ly)
            self.rep_dd = Dropdown([(AUTO, "Automatic"), (RAW, "All points"), (SAMPLED, "Sample"),
                                    (BINNED, f"Binned ({cfg.bins} × {cfg.bins})")], cfg.representation,
                                   accessible="Representation")
            self.rep_dd.changed.connect(lambda v: self._set_cfg(representation=v))
            rail.add(LabeledField("Representation", self.rep_dd))
            if cfg.representation == BINNED:
                bins = Dropdown([(b, f"{b} × {b}") for b in (50, 100, 200, 400)], cfg.bins, accessible="Bins")
                bins.changed.connect(lambda v: self._set_cfg(bins=v))
                rail.add(LabeledField("Bins", bins))
            if cfg.representation == SAMPLED or (cfg.representation == AUTO):
                rs = button("Resample", "ghost", "sm")
                rs.clicked.connect(lambda: self._set_cfg(seed=cfg.seed + 1))
                rail.add(rs)
        if cfg.type == LINE:
            strip = QCheckBox("Show model strip")
            strip.setChecked(cfg.model_strip)
            strip.toggled.connect(lambda on: self._set_cfg(model_strip=on))
            rail.add(strip)
        rail.lay.addStretch(1)
        row.addWidget(rail)
        center = _Region()
        head = QHBoxLayout()
        self.ws_plot_title = label("", "heading")
        head.addWidget(self.ws_plot_title, 1)
        for name, tip, fn in (("zoom_in", "Zoom in", lambda: self.plot.zoom(0.8)),
                              ("zoom_out", "Zoom out", lambda: self.plot.zoom(1.25)),
                              ("fit_to_screen", "Reset axes", lambda: self.plot.reset_view())):
            b = IconButton(name, tip)
            b.clicked.connect(fn)
            head.addWidget(b)
        # no selection / pan modes: drag with the middle or right button pans, the wheel zooms (brief §27, §28)
        ex = IconButton("download", "Export")
        ex.clicked.connect(lambda: self._export_menu(ex))
        head.addWidget(ex)
        center.lay.addLayout(head)
        self.ws_caption = label("", "label")
        center.add(self._plot_area(compact=False), 1)
        center.add(self.ws_caption)
        self.plot.setMinimumHeight(360)            # a readable plot at any window size (§20)
        split = QWidget()
        self.plot_box = QBoxLayout(QBoxLayout.Direction.LeftToRight, split)
        self.plot_box.setContentsMargins(0, 0, 0, 0)
        self.plot_box.setSpacing(20)
        self.plot_box.addWidget(center, 1)
        self.inspector_region = _Region()
        self.plot_box.addWidget(self.inspector_region)
        row.addWidget(split, 1)
        self._plots_reflow(True)
        self._fill_inspector()
        return host

    def _plots_reflow(self, wide: bool) -> None:
        """Wide: plot | inspector (340 px).  Tight (7.png): the inspector moves under the plot, full width,
        instead of squeezing the plot into a sliver."""
        try:
            self.plot_box.setDirection(QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom)
            if wide:
                self.inspector_region.setFixedWidth(340)
            else:
                self.inspector_region.setMinimumWidth(0)
                self.inspector_region.setMaximumWidth(16777215)
        except (AttributeError, RuntimeError):
            pass

    def _export_menu(self, anchor) -> None:
        from ..widgets.menu import CarbonMenu
        menu = CarbonMenu(parent=anchor)
        menu.add_action("Plot as SVG…", lambda: self.c.export_requested.emit("plot_svg"))
        menu.add_action("Plot as PNG…", lambda: self.c.export_requested.emit("plot_png"))
        menu.add_action("Plotted data as CSV…", lambda: self.c.export_requested.emit("plot_csv"))
        menu.open_below(anchor, align_right=True)
        menu.deleteLater()

    def _update_ws_plot_header(self, spec: PlotSpec, data) -> None:
        try:
            self.ws_plot_title.setText(rich(spec.title))
            sc = self.c.state.scope
            n_missing = data.get("n_missing", 0) if isinstance(data, dict) else 0
            unit = "composition" if spec.kind in ("scatter", "line") else "result"
            self.ws_caption.setText(f"Each point is one {unit}. {n_missing:,} results omitted (no value). Run {sc.run_id}."
                                    if spec.kind in ("scatter", "line") else f"Run {sc.run_id}")
        except RuntimeError:
            pass

    def _fill_inspector(self) -> None:
        reg = self.inspector_region
        reg.clear()
        reg.add(label("Inspector", "heading02"))
        rid = self.c.state.inspector
        if rid is None:
            reg.add(label("No point selected", "heading"))
            reg.add(label("Click a point to inspect it. Analyse composition makes it the active composition.",
                          "secondary", wrap=True))
        else:
            content = self._inspector_content(rid, full=True)
            if content is not None:
                reg.add(content)
        reg.lay.addStretch(1)

    def _rail_collection(self, rail) -> None:
        """Workspace rail section "Collection": run, population, restrictions, count."""
        rail.add(label("Collection", "heading02"))
        c_ = self.c
        run_dd = Dropdown(run_items(c_), c_.state.scope.run_id, accessible="Calculation run")
        run_dd.changed.connect(lambda v: run_changed(c_, v))
        pop_dd = Dropdown(pop_items(c_), c_.state.scope.base, accessible="Population")
        pop_dd.changed.connect(lambda v: pop_changed(c_, v))
        rail.add(LabeledField("Calculation run", run_dd))
        rail.add(LabeledField("Population", pop_dd))
        fam, size, blocks = restriction_controls(c_)
        sc = self.c.state.scope
        fam.changed.connect(lambda sel: self.c.scope_for(sc.run_id, sc.base, sel, sc.sizes, sc.blocks))
        size.changed.connect(lambda sel: self.c.scope_for(sc.run_id, sc.base, sc.families, sel, sc.blocks))
        rail.add(LabeledField("Element family", fam))
        rail.add(LabeledField("System size", size))
        if blocks is not None:
            blocks.changed.connect(lambda sel: self.c.scope_for(sc.run_id, sc.base, sc.families, sc.sizes, sel))
            rail.add(LabeledField("Expression block", blocks))
        cnt = QHBoxLayout()
        c = _CountLabel()
        st = self.c.state
        c.set(st.resolved.n if st.resolved else None, self.c.run_count(sc.run_id), st.stale is not None)
        cnt.addWidget(c)
        cnt.addStretch(1)
        cnt.addWidget(InfoButton(ANA_SCOPE, title="Collection scope"))
        rail.lay.addLayout(cnt)

    def _open_plot_settings(self, anchor, info) -> None:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self._plot_controls(lay, info, self.c.state.plot, inline=False)
        done = button("Done", "primary", "sm")
        lay.addWidget(done, 0, Qt.AlignmentFlag.AlignRight)
        pop = open_popover(anchor, content, 320, title="Plot settings")
        if pop is not None:
            done.clicked.connect(pop.close)

    # ================================================================== Statistics
    def _build_statistics(self) -> QWidget:
        st = self.c.state
        info = self.c.run_info(st.scope.run_id)
        if self.size_class == "W":
            return self._build_statistics_ws(info)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(20, 16, 20, 0)
        lay.setSpacing(8)
        self._notices(lay)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        ms = MultiSelect("metrics", [(k, f"{DESCRIPTORS[k].symbol} ({DESCRIPTORS[k].unit or '–'})")
                                     for k in METRIC_KEYS], st.stats_metrics, accessible="Metrics")
        ms.current_html = lambda: f"Metrics ({len(self.c.state.stats_metrics)})"
        ms.changed.connect(lambda sel: self.c.apply(S.update, stats_metrics=tuple(sel) or METRIC_KEYS))
        ms.setFixedWidth(220 if self.size_class != "S" else 180)
        bar.addWidget(ms)
        grp = Dropdown(group_items(info), st.stats_group, prefix="Group", inline=True, accessible="Group",
                       width=200 if self.size_class != "S" else 180)
        grp.changed.connect(lambda v: self.c.apply(S.update, stats_group=v))
        bar.addWidget(grp)
        bar.addStretch(1)
        if self.size_class != "S":
            from ..widgets.composition_panel import Toggle
            tg = Toggle(st.stats_all)
            tg.setAccessibleName("All measures")
            tg.toggled.connect(lambda on: self.c.apply(S.update, stats_all=on))
            bar.addWidget(label("All measures", "secondary"))
            bar.addWidget(tg)
        lay.addLayout(bar)
        self.stats_loading = InlineLoading("Calculating statistics…")
        self.stats_loading.cancel.connect(lambda: self.c.cancel("stats"))
        lay.addWidget(self.stats_loading)
        self.stats_loading.setVisible(self.c.busy("stats"))
        content = QWidget()
        sa, cl = scroll_page(content, (0, 0, 0, 16))
        cl.setSpacing(8)
        self.stats_host = QVBoxLayout()
        cl.addLayout(self.stats_host)
        cl.addStretch(1)
        lay.addWidget(sa, 1)
        self._fill_statistics()
        return host

    def _stats_table(self, stats: dict, all_measures: bool, metrics) -> DataTable:
        def f(k, v):
            return format_value(k, v) if v is not None else "—"
        rows = []
        pending = stats.get("pending", ())
        ncols = 10 if all_measures else (4 if self.size_class == "S" else 5)
        for k in metrics:
            m = stats["metrics"].get(k)
            if m is None:
                if k in pending:                    # still being calculated: Carbon skeleton cells
                    dd = DESCRIPTORS[k]
                    rows.append([f"{dd.symbol} ({dd.unit or '–'})"] +
                                [Cell(align="right", skeleton=True) for _ in range(ncols - 1)])
                continue
            dd = DESCRIPTORS[k]
            name = f"{dd.symbol} ({dd.unit or '–'})"
            if all_measures:
                rows.append([name, Cell(f"{m['n_valid']:,}", align="right"),
                             Cell(f"{m['n_missing']:,}", align="right", tip=_missing_tip(m)),
                             Cell(f(k, m["mean"]), align="right"), Cell(f(k, m["sd"]), align="right"),
                             Cell(f(k, m["min"]), align="right"), Cell(f(k, m["q1"]), align="right"),
                             Cell(f(k, m["median"]), align="right"), Cell(f(k, m["q3"]), align="right"),
                             Cell(f(k, m["max"]), align="right")])
            elif self.size_class == "S":
                rows.append([name, Cell(f"{m['n_valid']:,}", align="right", tip=_missing_tip(m)),
                             Cell(f(k, m["median"]), align="right"),
                             Cell(f"{f(k, m['q1'])} … {f(k, m['q3'])}", align="right",
                                  tip=f"Min {f(k, m['min'])}, max {f(k, m['max'])}, mean {f(k, m['mean'])}, "
                                      f"SD {f(k, m['sd'])}, N missing {m['n_missing']:,}")])
            else:
                rows.append([name, Cell(f"{m['n_valid']:,}", align="right", tip=_missing_tip(m)),
                             Cell(f(k, m["median"]), align="right"),
                             Cell(f"{f(k, m['q1'])} … {f(k, m['q3'])}", align="right"),
                             Cell(f"{f(k, m['min'])} … {f(k, m['max'])}", align="right")])
        if all_measures:
            cols = [("Metric", 200), ("N valid", 80, "right"), ("N missing", 90, "right"), ("Mean", None, "right"),
                    ("SD", None, "right"), ("Min", None, "right"), ("Q1", None, "right"), ("Median", None, "right"),
                    ("Q3", None, "right"), ("Max", None, "right")]
        elif self.size_class == "S":
            cols = [("Metric", 150), ("N", 56, "right"), ("Median", None, "right"), ("Q1 – Q3", None, "right")]
        else:
            cols = [("Metric", 220), ("N", 64, "right"), ("Median", 104, "right"), ("Q1 – Q3", None, "right"),
                    ("Min – Max", None, "right")]
        return DataTable(cols, rows, ROW_XS if self.size_class != "W" else ROW_SM)

    def _fill_statistics(self) -> None:
        if self.size_class == "W":
            return self._fill_statistics_ws()
        lay = getattr(self, "stats_host", None)
        stats = self._current("stats")
        if lay is None or stats is None:
            return
        try:
            _clear_layout(lay)
        except RuntimeError:
            return
        st = self.c.state
        metrics = st.stats_metrics
        wide = self.size_class == "L"
        if st.stats_all and not wide:
            note = QHBoxLayout()
            note.addWidget(label("All measures need a wider view — Expand analysis", "secondary"))
            b = button("Expand analysis", "ghost", "sm")
            b.clicked.connect(lambda: self.c.expand_requested.emit(True))
            note.addWidget(b)
            note.addStretch(1)
            lay.addLayout(note)
        group = st.stats_group
        if group != "none":
            gs = self._current("stats_group")
            if gs is not None:
                for k in metrics:
                    groups = gs["metrics"].get(k, {})
                    lay.addWidget(label(f"{DESCRIPTORS[k].symbol} ({DESCRIPTORS[k].unit or '–'}) by "
                                        f"{dim_label(group).lower()}", "heading"))
                    rows = [[dim_value_text(group, g), Cell(f"{v['n_valid']:,}", align="right"),
                             Cell(format_value(k, v.get("median")), align="right"),
                             Cell(f"{format_value(k, v.get('q1'))} … {format_value(k, v.get('q3'))}", align="right")]
                            for g, v in groups.items()]
                    lay.addWidget(DataTable([("Group", None), ("N", 64, "right"), ("Median", 104, "right"),
                                             ("Q1 – Q3", 188, "right")], rows, ROW_XS))
        else:
            table = self._stats_table(stats, st.stats_all and wide, metrics)
            table.activatable = True
            table.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            keys = [k for k in metrics if k in stats["metrics"] or k in stats.get("pending", ())]
            table.selected = keys.index(st.stats_focus) if st.stats_focus in keys else -1
            table.row_tips = [f"Plot the distribution of {plain_text(DESCRIPTORS[k].symbol)} "
                              f"({plain_text(DESCRIPTORS[k].name)})" for k in keys]
            table.activated.connect(lambda i, ks=keys: self._plot_histogram(ks[i]))
            lay.addWidget(table)
        cap = QHBoxLayout()
        exact = "exact" if stats["exact"] else "Approximate (binned)"
        cap.addWidget(label(f"N = {stats['n']:,} results in scope. N/A values are excluded and counted as missing. "
                            f"Quartiles by linear interpolation. {exact}", "label", wrap=True), 1)
        cap.addWidget(InfoButton(ANA_STATS.format(n=f"{stats['n']:,}"), title="Statistics conventions"))
        lay.addLayout(cap)

    def _plot_histogram(self, key: str) -> None:
        """Activating a statistics row selects that metric (kept for the session) and shows its distribution."""
        self.c.apply(S.update, stats_focus=key)
        self.c.apply(S.set_plot, self.c.state.plot.with_(type=HISTOGRAM, x=key))
        self.c.apply(S.set_tab, "plots")

    def _focus_selector(self) -> QWidget:
        """Compact metric dropdown driving the distribution (histogram / box plot) - any statistics-eligible
        descriptor, in registry order; no default descriptor."""
        items = [(k, DESCRIPTORS[k].selector_text(), True, "", f"{DESCRIPTORS[k].symbol} — {DESCRIPTORS[k].name}")
                 for k in METRIC_KEYS]
        dd = Dropdown(items, self.c.state.stats_focus or None, prefix="Distribution of", inline=True,
                      accessible="Distribution metric", placeholder="Select a descriptor")
        dd.setMinimumWidth(360)
        dd.changed.connect(lambda k: self.c.apply(S.update, stats_focus=k))
        return dd

    STATS_VIZ_MIN = 340          # expanded Statistics visualization (region incl. its heading row)
    STATS_VIZ_MAX = 400

    def _build_statistics_ws(self, info) -> QWidget:
        st = self.c.state
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(20)
        rail = _Region()
        rail.setFixedWidth(320)
        self._rail_collection(rail)
        rail.add(Divider())
        rail.add(label("Metrics", "heading02"))
        from ...core.analysis.metrics import DESCRIPTORS_LIST
        last = None
        for dd in DESCRIPTORS_LIST:
            if dd.key not in METRIC_KEYS:
                continue
            if dd.group != last:
                rail.add(label(GROUP_SHORT.get(dd.group, dd.group), "label"))
                last = dd.group
            # symbol and unit in the 320 px rail; the full scientific name (e.g. which radius set) in the Tooltip
            cb = QCheckBox(f"{dd.plain} ({dd.unit_plain})")
            cb.setToolTip(plain_text(dd.name))
            cb.setAccessibleName(plain_text(f"{dd.plain} — {dd.name}"))
            cb.setChecked(dd.key in st.stats_metrics)
            cb.toggled.connect(lambda on, k=dd.key: self._toggle_metric(k, on))
            rail.add(cb)
        grp = Dropdown(group_items(info), st.stats_group, accessible="Group by")
        grp.changed.connect(lambda v: self.c.apply(S.update, stats_group=v))
        rail.add(LabeledField("Group by", grp))
        rail.lay.addStretch(1)
        row.addWidget(rail)
        right = QVBoxLayout()
        right.setSpacing(20)
        self.ws_stats = _Region()
        # the table region hugs its rows; the visualization takes the remaining height (one outer scroll)
        right.addWidget(self.ws_stats)
        # one visualization of the user's selected descriptor (4.png: no permanent second chart); Compare
        # groups is an explicit choice (Carbon content switcher, sm)
        dist = QHBoxLayout()
        dist.setSpacing(8)
        dist.addWidget(self._focus_selector())
        dist.addStretch(1)
        from .widgets import ContentSwitcher
        self.stats_view_sw = ContentSwitcher(["Histogram", "Compare groups"], segment=136)
        self.stats_view_sw.setAccessibleName("Visualization")
        self.stats_view_sw.set_index(1 if st.stats_view == "groups" else 0)
        self.stats_view_sw.changed.connect(
            lambda i: self.c.apply(S.update, stats_view="groups" if i == 1 else "histogram"))
        dist.addWidget(self.stats_view_sw)
        right.addLayout(dist)
        # Statistics leads with its table; the chart is supporting evidence: a bounded height (heading + a readable
        # histogram / box plot with its axes), not the rest of the page - the Plots tab is the chart-centric view
        self.ws_viz = _Region()
        self.ws_viz.setMinimumHeight(self.STATS_VIZ_MIN)
        self.ws_viz.setMaximumHeight(self.STATS_VIZ_MAX)
        right.addWidget(self.ws_viz)
        right.addStretch(1)
        row.addLayout(right, 1)
        self._fill_statistics_ws()
        return host

    def _toggle_metric(self, k: str, on: bool) -> None:
        cur = list(self.c.state.stats_metrics)
        if on and k not in cur:
            cur.append(k)
        elif not on and k in cur and len(cur) > 1:
            cur.remove(k)
        order = [m for m in METRIC_KEYS if m in cur]
        self.c.apply(S.update, stats_metrics=tuple(order))

    def _fill_statistics_ws(self) -> None:
        if not hasattr(self, "ws_stats"):
            return
        stats = self._current("stats")
        st = self.c.state
        try:
            self.ws_stats.clear()
        except RuntimeError:
            return
        self.ws_stats.add(label("Statistics", "heading02"))
        if stats is not None:
            table = self._stats_table(stats, True, st.stats_metrics)
            table.columns.insert(1, ("Unit", 120))
            for r, k in zip(table.rows, [m for m in st.stats_metrics if m in stats["metrics"] or m in stats.get("pending", ())]):
                r.insert(1, Cell(DESCRIPTORS[k].unit or "–", color="text-secondary"))
            table.columns[0] = ("Metric", 180)
            for r, k in zip(table.rows, [m for m in st.stats_metrics if m in stats["metrics"] or m in stats.get("pending", ())]):
                r[0] = Cell(DESCRIPTORS[k].symbol)
            table.activatable = True
            shown = [m for m in st.stats_metrics if m in stats["metrics"] or m in stats.get("pending", ())]
            table.selected = shown.index(st.stats_focus) if st.stats_focus in shown else -1
            table.row_tips = [f"Show the distribution of {plain_text(DESCRIPTORS[k].symbol)} "
                              f"({plain_text(DESCRIPTORS[k].name)})" for k in shown]
            table.activated.connect(lambda i, ks=shown: self.c.apply(S.update, stats_focus=ks[i]))
            table.set_rows(table.rows, row_tips=table.row_tips)
            self.ws_stats.add(hstrip(table))
            cap = QHBoxLayout()
            exact = "exact" if stats["exact"] else "Approximate (binned)"
            cap.addWidget(label(f"N = {stats['n']:,} results in scope. N/A values are excluded and counted as missing. "
                                f"Quartiles by linear interpolation. {exact}", "label"), 1)
            cap.addWidget(InfoButton(ANA_STATS.format(n=f"{stats['n']:,}"), title="Statistics conventions"))
            self.ws_stats.lay.addLayout(cap)
        else:
            self.ws_stats.add(InlineLoading("Calculating statistics…"))
        focus = st.stats_focus
        reg = self.ws_viz
        reg.clear()
        if not focus or focus not in DESCRIPTORS:
            # no metric chosen: a neutral prompt - no descriptor is shown by default
            reg.add(EmptyBlock("Select a descriptor",
                               "Choose a metric in “Distribution of” or activate a statistics row to see its "
                               "distribution.", "magnifier", centred=True), 1)
            return
        dd = DESCRIPTORS[focus]
        from ...core.analysis.queries import descriptor_metric
        head = QHBoxLayout()
        head.setSpacing(4)
        pw = None
        if st.stats_view == "groups":
            box = self._current("box")
            if box is not None:
                g = st.stats_group if st.stats_group != "none" else DIM_FAMILY
                head.addWidget(label(f"{dd.symbol} ({dd.unit or '–'}) by {dim_label(g).lower()}", "heading"))
                groups = box["metrics"].get(focus, {})
                pw = PlotWidget()
                pw.set_spec(PlotSpec("box", {"groups": dict(list(groups.items())[:30])}, x=descriptor_metric(focus),
                                     tag=representation_text("AGGREGATED", group=dim_label(g).lower()),
                                     extra={"group": g},
                                     caption="Whiskers: minimum and maximum; quartiles type 7"))
        else:
            hist = self._current("hist")
            if hist is not None and hist.get("n_valid"):
                w = hist.get("width") or 0
                head.addWidget(label(f"{dd.symbol} ({dd.unit or '–'}) histogram, bins {format_value(focus, w)} "
                                     f"{dd.unit}".strip(), "heading"))
                pw = PlotWidget()
                pw.set_spec(PlotSpec("histogram", hist, x=descriptor_metric(focus),
                                     tag=representation_text(BINNED, bins=(len(hist["counts"]),),
                                                             population=hist["n_valid"]),
                                     caption=f"{hist['n'] - hist['n_valid']:,} omitted (no value)"))
        if pw is None:
            reg.add(InlineLoading("Loading distribution…"))
            return
        head.addStretch(1)
        self.outlier_note = None
        out = self._current("outliers")
        if out is not None and out.get("metric") == focus and out["fences"] is not None:
            n_out = out["n_low"] + out["n_high"]
            if n_out:
                # a statistical indication, not a data-quality or model warning (brief §35, §72): neutral text
                self.outlier_note = label(f"{n_out:,} statistical outlier{'s' if n_out != 1 else ''}", "secondary")
                head.addWidget(self.outlier_note)
                head.addWidget(InfoButton(OUTLIER_TIP, title="Statistical outliers"))
        reg.lay.addLayout(head)
        reg.add(pw, 1)

    # ================================================================== Models
    def _build_models(self) -> QWidget:
        st = self.c.state
        info = self.c.run_info(st.scope.run_id)
        cls = self.size_class
        host = QWidget()
        if cls == "W":
            row = QHBoxLayout(host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(20)
            rail = _Region()
            rail.setFixedWidth(320)
            self._rail_collection(rail)
            rail.add(Divider())
            rail.add(label("Distribution", "heading02"))
            self._dist_controls(rail.lay, info, vertical=True)
            rail.lay.addStretch(1)
            row.addWidget(rail)
            right = QVBoxLayout()
            right.setSpacing(20)
            self.ws_bars = _Region()
            self.ws_bars.setMinimumHeight(460)
            self.ws_counts = _Region()
            right.addWidget(self.ws_bars)
            right.addWidget(self.ws_counts, 1)
            row.addLayout(right, 1)
            self._fill_models()
            return host
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        sa, cl = scroll_page(content)
        cl.setSpacing(8)
        self._notices(cl)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._dist_controls(bar, info, vertical=False)
        bar.addStretch(1)
        cl.addLayout(bar)
        self.models_host = QVBoxLayout()
        cl.addLayout(self.models_host)
        cl.addStretch(1)
        lay.addWidget(sa)
        self._fill_models()
        return host

    def _dist_controls(self, lay, info, vertical: bool) -> None:
        st = self.c.state
        den = Dropdown([("evaluated", "Of evaluated results"), ("population", "All results in scope")],
                       st.denominator, prefix="" if vertical else "Denominator", inline=not vertical,
                       accessible="Denominator", width=None if vertical else 300)
        den.changed.connect(lambda v: self.c.apply(S.update, denominator=v))
        split = QCheckBox("Split by status")
        split.setChecked(st.split_status)
        split.toggled.connect(lambda on: self.c.apply(S.update, split_status=on))
        if vertical:
            lay.addWidget(LabeledField("Denominator", den))
            lay.addWidget(split)
            grp = Dropdown(group_items(info), st.dist_group, accessible="Group by")
            grp.changed.connect(lambda v: self.c.apply(S.update, dist_group=v))
            lay.addWidget(LabeledField("Group by", grp))
        else:
            lay.addWidget(den)
            lay.addSpacing(8)
            lay.addWidget(split)

    def _fill_models(self) -> None:
        dist = self._current("dist")
        st = self.c.state
        if self.size_class == "W":
            if not hasattr(self, "ws_bars") or dist is None:
                return
            try:
                self.ws_bars.clear()
                self.ws_counts.clear()
            except RuntimeError:
                return
            group = st.dist_group
            if group != "none":
                gd = self._current("dist_group")
                self.ws_bars.add(label(f"Model classes by {dim_label(group).lower()}", "heading02"))
                if gd is not None:
                    sa_host = QWidget()
                    sl = QVBoxLayout(sa_host)
                    sl.setContentsMargins(0, 0, 0, 0)
                    for g, models in list(gd["groups"].items())[:12]:
                        n = models["M1"]["population"]
                        sl.addWidget(label(f"{dim_value_text(group, g)} (N = {n:,})", "heading"))
                        pw = PlotWidget()
                        pw.setMinimumHeight(36 + 8 * 26)
                        pw.set_spec(PlotSpec("bars_stacked", bars_data(models, st.denominator, st.split_status, 26,
                                                                        220, 200, legend=False)))
                        sl.addWidget(pw)
                    self.ws_bars.add(sa_host, 1)
            else:
                self.ws_bars.add(label("Model distributions", "heading02"))
                pw = PlotWidget()
                pw.set_spec(PlotSpec("bars_stacked", bars_data(dist["models"], st.denominator, st.split_status, 44, 220,
                                                                200)))
                self.ws_bars.add(pw, 1)
            self.ws_counts.add(label("Counts", "heading02"))
            self.ws_counts.add(counts_table(dist["models"], ROW_SM))
            self.ws_counts.add(self._dist_caption(dist))
            self.ws_counts.lay.addStretch(1)
            return
        lay = getattr(self, "models_host", None)
        if lay is None or dist is None:
            return
        try:
            _clear_layout(lay)
        except RuntimeError:
            return
        models = dist["models"]
        legend_row = QHBoxLayout()
        legend_row.setSpacing(12)
        for name in ("SS", "SS+IM", "MP", "IM", "MG", NA):
            legend_row.addWidget(_Swatch(bar_color(name), name))
        ext = sum(m["status"].get("extrapolated", 0) for m in models.values())
        flg = sum(m["status"].get("data_suspect", 0) for m in models.values())
        legend_row.addWidget(_Swatch(bar_color("SS"), f"Extrapolated ({ext:,})", hatch=True))
        legend_row.addWidget(_Swatch(bar_color("MP"), f"Flagged data ({flg:,})", hatch=True))
        legend_row.addStretch(1)
        lay.addLayout(legend_row)
        right_w = 113
        pw = PlotWidget()
        pw.setMinimumHeight(36 + 8 * 32)
        pw.setMaximumHeight(36 + 8 * 32 + 4)
        pw.set_spec(PlotSpec("bars_stacked", bars_data(models, st.denominator, st.split_status, 32,
                                                        156 if self.size_class != "S" else 120, right_w,
                                                        legend=False)))
        lay.addWidget(pw)
        lay.addWidget(self._dist_caption(dist))
        if self.size_class == "L":
            lay.addWidget(counts_table(models, ROW_XS))
        if st.dist_group != "none":
            gd = self._current("dist_group")
            if gd is not None:
                for g, ms in list(gd["groups"].items())[:12]:
                    lay.addWidget(label(f"{dim_value_text(st.dist_group, g)} (N = {ms['M1']['population']:,})",
                                        "heading"))
                    p2 = PlotWidget()
                    p2.setFixedHeight(8 * 24 + 8)
                    p2.set_spec(PlotSpec("bars_stacked", bars_data(ms, st.denominator, st.split_status, 24, 156,
                                                                    right_w, legend=False, top=0)))
                    lay.addWidget(p2)

    def _dist_caption(self, dist) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        st = self.c.state
        den = "evaluated results" if st.denominator == "evaluated" else "all results in scope"
        lay.addWidget(label(f"Percentages of {den}; not-available results are counted separately. Classes differ "
                            "between models; a class absent from a bar is not a zero count.", "label", wrap=True), 1)
        m1 = dist["models"]["M1"]
        e = min(m["evaluated"] for m in dist["models"].values())
        na = max(m["na"] for m in dist["models"].values())
        lay.addWidget(InfoButton(ANA_DENOMINATOR.format(e=f"{e:,}", na=f"{na:,}"), title="Denominator"))
        _ = m1
        return w


# ====================================================================== shared builders
class _Reflow(QWidget):
    """A workspace page that reports crossing ``breakpoint`` px of width (wide / tight layouts)."""

    def __init__(self, breakpoint: int, on_change):
        super().__init__()
        self.breakpoint = breakpoint
        self.on_change = on_change
        self.wide = True

    def resizeEvent(self, e):
        super().resizeEvent(e)
        wide = self.width() >= self.breakpoint
        if wide != self.wide:
            self.wide = wide
            self.on_change(wide)


class _Region(QWidget):
    """A workspace region: ``layer-01`` panel with 20 px padding.  Regions never scroll by themselves: the
    expanded workspace grows with its content and its one outer scroll owns the overflow (7.png, §20, §58)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("AnaRegion")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(20, 20, 20, 20)
        self.lay.setSpacing(12)
        outer.addWidget(inner)

    def add(self, w, stretch: int = 0):
        self.lay.addWidget(w, stretch)
        return w

    def clear(self):
        _clear_layout(self.lay)


class _Swatch(QWidget):
    def __init__(self, color: str, text: str, hatch: bool = False):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        sw = QWidget()
        sw.setFixedSize(10, 10)
        sw.paintEvent = lambda _e, w=sw: _fill(w, color, hatch)
        lay.addWidget(sw)
        lay.addWidget(label(text, "label"))


def _fill(w, color, hatch: bool = False):
    from PySide6.QtGui import QPen
    p = QPainter(w)
    p.fillRect(w.rect(), QColor(color))
    if hatch:
        p.setPen(QPen(QColor(t("background")), 1))
        for k in range(-10, 20, 4):
            p.drawLine(k, 10, k + 10, 0)
    p.end()


OUTLIER_TIP = ("Values outside Q1 − 1.5 × IQR to Q3 + 1.5 × IQR are marked as statistical outliers. They are not excluded from the analysis and do not necessarily indicate erroneous data.")


def _clear_layout(lay) -> None:
    while lay.count():
        it = lay.takeAt(0)
        if it.widget() is not None:
            _w = it.widget()
            retire(_w)
        elif it.layout() is not None:
            _clear_layout(it.layout())


def _missing_tip(m: dict) -> str:
    if not m.get("n_missing"):
        return ""
    return (f"N missing {m['n_missing']:,}: missing data {m['missing_data']:,}, undefined {m['undefined']:,}, "
            f"not evaluable {m['error']:,}")


def _range_values(r, name: str = "") -> list[float]:
    """The values of a stored variable range (the engine's grid, strict bounds applied; at most 10 000)."""
    from ...core.expression import range_from_meta
    try:
        return range_from_meta(name, r).values()[:10_000]
    except (ValueError, TypeError, KeyError, IndexError):
        return []


def _range_text(name: str, r) -> str:
    """``0 ≤ x < 1, step 0.1`` / ``…, 11 points`` for a stored range (either metadata form)."""
    from ...core.expression import range_from_meta
    try:
        v = range_from_meta(name, r)
    except (ValueError, TypeError, KeyError, IndexError):
        return name
    sampling = f"step {v.step:g}" if v.step is not None else f"{v.points} points" if v.points else ""
    return f"{v.bounds_text()}{', ' + sampling if sampling else ''}"


def _same_plot_layout(a, b) -> bool:
    """Only data-affecting fields changed (the controls do not need rebuilding)."""
    return a.type == b.type and a.representation == b.representation and \
        set(dict(a.fixed)) == set(dict(b.fixed))


def source_text(info, pop) -> str:
    if info is None:
        return "—"
    src = info.source or {}
    if info.mode == "sweep":
        unit = {"at": "at.%", "wt": "wt.%", "mass": "mass (g)"}.get(src.get("unit"), "at. ratio")
        req = [s for s in src.get("specs", []) if s.get("required")]
        opt = [s for s in src.get("specs", []) if not s.get("required")]
        parts = [f"Composition space ({unit})"]

        def rng(s):
            if s["min"] == s["max"]:
                return f"{s['min']:g}"
            return f"{s['min']:g}–{s['max']:g}, " + (f"{s['points']} points" if "points" in s else f"step {s['step']:g}")
        if req:
            same = len({(s['min'], s['max']) for s in req}) == 1
            if same:
                parts.append(f"{', '.join(s['element'] for s in req)} required at {rng(req[0])}")
            else:
                parts += [f"{s['element']} required {rng(s)}" for s in req]
        parts += [f"{s['element']} optional {rng(s)}" for s in opt]
        parts.append(f"{len(pop.get('families', []))} systems, {pop.get('n', 0):,} valid compositions")
        return "; ".join(parts)
    if info.mode == "expression":
        blocks = src.get("blocks", [])
        ranges = src.get("ranges", {})
        parts = ["Expression"] + [f"Block {b['index'] + 1}: {_html.escape(b['expression'])}" for b in blocks]
        parts += [_range_text(k, v) for k, v in ranges.items()]
        parts.append(f"{pop.get('n', 0):,} compositions")
        return "; ".join(parts)
    if info.mode == "import":
        return f"Imported from {_html.escape(str(src.get('file', 'a spreadsheet')))}, {pop.get('n', 0):,} compositions"
    return f"{mode_name(info.mode)}, {pop.get('n', 0):,} composition{'s' if pop.get('n', 0) != 1 else ''}"


def plot_summary(cfg, info) -> str:
    try:
        from ...core.analysis.queries import metric_by_id
        x = metric_by_id(info, cfg.x).symbol
        y = metric_by_id(info, cfg.y).symbol if cfg.type in (SCATTER, LINE, HEATMAP) else ""
    except KeyError:
        x, y = cfg.x, cfg.y
    parts = [TYPE_SHORT.get(cfg.type, cfg.type), f"{x} × {y}" if y else x]
    if cfg.type == SCATTER and cfg.color not in ("none", ""):
        parts.append(cfg.color[6:] if cfg.color.startswith("model:") else dim_label(cfg.color))
    return ", ".join(parts)


def bar_color(cls) -> str:
    """Class bars and swatches use the tag background (the saturated class colour of the mock-ups)."""
    from ..theme import THEME
    return THEME.tag_colors(cls if cls is not None else NA)[0]


def bars_data(models: dict, denominator: str, split: bool, row_h: int, label_w: int, right_w: int,
              legend: bool = True, top: int = 36) -> dict:
    """Stacked-bar rows: each model's own classes (never invented zero classes), N/A only when the
    denominator is the whole population; extrapolated / flagged shares hatched when ``split``."""
    rows = []
    for k in MODEL_KEYS:
        m = models[k]
        den = m["evaluated"] if denominator == "evaluated" else m["population"]
        segs = []
        status_text = {}
        for cls in MD.CLASSES[k]:
            n = m["classes"].get(cls, 0)
            flagged = m["class_status"].get((cls, "data_suspect"), 0) + m["class_status"].get((cls, "extrapolated"), 0)
            segs.append((cls, n, bar_color(cls), flagged if split else 0))
            parts = [f"{s_.replace('_', ' ')} {c:,}" for (c_, s_), c in m["class_status"].items() if c_ == cls]
            status_text[cls] = ", ".join(parts)
        if denominator == "population" and m["na"]:
            segs.append((NA, m["na"], bar_color(NA), 0))
        right = f"{m['evaluated']:,} of {m['population']:,}"
        if m["na"]:
            right += f", N/A {m['na']:,}"
        rows.append({"label": MD.title(k, short=label_w < 200), "denominator": den, "segments": segs,
                     "right": right, "status_text": status_text})
    data = {"rows": rows, "label_w": label_w, "right_w": right_w, "row_h": row_h}
    if legend:
        data["legend"] = [(c, bar_color(c)) for c in ("SS", "SS+IM", "MP", "IM", "MG")] + \
            ([(NA, bar_color(NA))] if denominator == "population" else [])
    return data


def counts_table(models: dict, row_h: int) -> DataTable:
    cols = [("Model", 220), ("Population", None, "right"), ("Evaluated", None, "right")] + \
        [(c, None, "right") for c in ("SS", "SS+IM", "MP", "IM", "MG")] + \
        [("N/A", None, "right"), ("Extrapolated", None, "right"), ("Flagged data", None, "right")]
    rows = []
    for k in MODEL_KEYS:
        m = models[k]
        cells = [MD.title(k), Cell(f"{m['population']:,}", align="right"), Cell(f"{m['evaluated']:,}", align="right")]
        for c in ("SS", "SS+IM", "MP", "IM", "MG"):
            if c in MD.CLASSES[k]:
                cells.append(Cell(f"{m['classes'].get(c, 0):,}", align="right"))
            else:
                cells.append(Cell("—", align="right", color="text-secondary",
                                  tip="Not a class of this model"))
        na_tip = ", ".join(f"{k_.replace('_', ' ')} {v:,}" for k_, v in m["na_by_kind"].items())
        cells += [Cell(f"{m['na']:,}", align="right", tip=na_tip),
                  Cell(f"{m['status'].get('extrapolated', 0):,}", align="right"),
                  Cell(f"{m['status'].get('data_suspect', 0):,}", align="right")]
        rows.append(cells)
    return DataTable(cols, rows, row_h)


def build_spec(cfg, data, info, size_class: str) -> tuple[PlotSpec | None, tuple | None]:
    """A :class:`PlotSpec` from a query answer, or ``(None, (title, body))`` for an empty plot."""
    from ...core.analysis.queries import descriptor_metric, metric_by_id
    model = cfg.color[6:] if cfg.color.startswith("model:") else None
    if cfg.type == SCATTER:
        x, y = metric_by_id(info, cfg.x), metric_by_id(info, cfg.y)
        cm = None if is_dimension(cfg.color) or cfg.color in ("none", "") else metric_by_id(info, cfg.color)
        if data.get("representation") == "BINNED":
            if not data["n_valid"]:
                return None, (f"{plain_text(y.symbol)} or {plain_text(x.symbol)} is not available for this collection",
                              "No result has both values. Choose other metrics.")
            tag = representation_text(BINNED, bins=data["bins"], population=data["n_valid"])
            title = f"{y.symbol} versus {x.symbol}, binned"
            info = (f"{data['n_valid']:,} results are counted in {data['bins'][0]} × {data['bins'][1]} cells; each cell "
                    "shows how many results fall into it (or their majority class / mean value). No result is "
                    "drawn individually and none is left out.")
            legend_title = MD.title(model, short=size_class != "W") if model else (
                dim_label(cfg.color) if not cm and cfg.color not in ("none", "") else "")
            return PlotSpec("binned", data, x=x, y=y, color=cfg.color, color_metric=cm, title=title, tag=tag,
                            caption=f"{data['n_missing']:,} omitted (no value)", legend_title=legend_title, model=model,
                            thresholds=cfg.thresholds, extra={"tag_info": info}), None
        if not data["n_valid"]:
            return None, (f"{plain_text(y.symbol)} or {plain_text(x.symbol)} is not available for this collection",
                          f"None of the {data['n']:,} results has both values. Choose another metric.")
        rep = data["representation"]
        tag = representation_text(rep, shown=data["n_shown"], population=data["n_valid"])
        info = ANA_SAMPLED.format(N=f"{data['n_valid']:,}", n=f"{data['n_shown']:,}") if rep == SAMPLED else ""
        title = f"{y.symbol} versus {x.symbol}"
        if cfg.color not in ("none", ""):
            title += ", coloured by " + (MD.title(model) if model else
                                          (cm.symbol if cm else dim_label(cfg.color).lower()))
        legend_title = MD.title(model, short=size_class != "W") if model else (dim_label(cfg.color) if not cm else "")
        return PlotSpec("scatter", data, x=x, y=y, color=cfg.color, color_metric=cm, title=title, tag=tag,
                        caption=f"{data['n_missing']:,} omitted (no value)", legend_title=legend_title, model=model,
                        thresholds=cfg.thresholds, log_x=cfg.log_x, log_y=cfg.log_y,
                        extra={"tag_info": info}), None
    if cfg.type == LINE:
        x, y = metric_by_id(info, cfg.x), metric_by_id(info, cfg.y)
        n = len(data["x"])
        if not n:
            return None, ("No results on this path", "No composition matches the fixed variable values.")
        tag = representation_text(RAW, shown=sum(1 for v in data["y"][cfg.y] if v is not None), ordered_by=x.plain)
        return PlotSpec("line", data, x=x, y=y, title=f"{y.symbol} along {x.symbol}", tag=tag,
                        caption="Line connects compositions in order of " + x.plain + ".",
                        extra={"vec_rule": cfg.y == "vec"}), None
    if cfg.type == HISTOGRAM:
        x = metric_by_id(info, cfg.x)
        if not data.get("n_valid"):
            return None, (f"{plain_text(x.symbol)} is not available for this collection", "Choose another metric.")
        tag = f"Binned: {len(data['counts'])} bins, {data['n_valid']:,} results"
        return PlotSpec("histogram", data, x=x, title=f"{x.symbol} histogram", tag=tag,
                        caption=f"{data['n'] - data['n_valid']:,} omitted (no value)"), None
    if cfg.type == BOX:
        x = metric_by_id(info, cfg.x)
        groups = data["metrics"].get(cfg.x, {})
        if not groups:
            return None, (f"{plain_text(x.symbol)} is not available for this collection", "Choose another metric.")
        if len(groups) > 30:
            groups = dict(sorted(groups.items(), key=lambda kv: -kv[1].get("n_valid", 0))[:30])
        return PlotSpec("box", {"groups": groups}, x=x, title=f"{x.symbol} by {dim_label(cfg.group).lower()}",
                        tag=representation_text("AGGREGATED", group=dim_label(cfg.group).lower()),
                        caption="Whiskers: minimum and maximum; quartiles type 7", extra={"group": cfg.group}), None
    if cfg.type == HEATMAP:
        x, y = metric_by_id(info, cfg.x), metric_by_id(info, cfg.y)
        if not data["cells"]:
            return None, ("No grid to show", "No composition matches the fixed variable values.")
        if not data["complete"]:
            return None, ("This grid is incomplete",
                          f"{data['missing_cells']:,} cells have no result and {data['multiple']:,} have more than one. "
                          "A heatmap needs exactly one result per cell; use a scatter plot.")
        vid = cfg.value if not is_dimension(cfg.value) else ""
        title_v = MD.title(cfg.value[6:]) if cfg.value.startswith("model:") else \
            (descriptor_metric(cfg.value).symbol if vid else cfg.value)
        return PlotSpec("heatmap", data, x=x, y=y, title=f"{title_v} on ({x.symbol}, {y.symbol})",
                        tag=representation_text("GRID", cells=len(data["cells"])),
                        extra={"value_id": vid, "value_label": cfg.value[6:] if cfg.value.startswith("model:") else
                               (descriptor_metric(cfg.value).plain if vid else dim_label(cfg.value))}), None
    if cfg.type == BAR_STACKED:
        return PlotSpec("bars_stacked", bars_data(data["models"], "evaluated", True, 32 if size_class != "W" else 44,
                                                   160 if size_class != "W" else 220, 140),
                        title="Model classes", tag=representation_text("AGGREGATED", group="model")), None
    if cfg.type == BAR_GROUPED:
        k = cfg.model
        rows = []
        for g, models in data["groups"].items():
            m = models[k]
            segs = [(c, m["classes"].get(c, 0), bar_color(c), 0) for c in MD.CLASSES[k]]
            rows.append({"label": dim_value_text(cfg.group, g), "denominator": m["evaluated"], "segments": segs,
                         "right": f"{m['evaluated']:,} evaluated" + (f", N/A {m['na']:,}" if m["na"] else "")})
        d = {"rows": rows[:40], "label_w": 200, "right_w": 160, "row_h": 28,
             "legend": [(c, bar_color(c)) for c in MD.CLASSES[k]]}
        return PlotSpec("bars_grouped", d, title=f"{MD.title(k)} by {dim_label(cfg.group).lower()}",
                        tag=representation_text("AGGREGATED", group=dim_label(cfg.group).lower())), None
    return None, ("Unknown plot type", "")


class ModelStripPlot(QWidget):
    """Model strip under an ordered line plot (frame 24): M1-M8 rows of class cells per x, aligned with the
    plot's x axis; transitions marked."""

    def __init__(self, plot: PlotWidget, parent=None):
        super().__init__(parent)
        self.plot = plot
        self.setFixedHeight(22 + 8 * 18 + 4)

    def paintEvent(self, _e):
        from ..theme import THEME
        s = self.plot.spec
        if s is None or s.kind != "line":
            return
        labels = s.data.get("labels") or {}
        xs = s.data.get("x") or []
        if not labels or not xs:
            return
        p = QPainter(self)
        rect = self.plot._frame_rect(self.plot.width(), self.plot.height())
        lim = self.plot._limits()
        if lim is None:
            p.end()
            return
        fx, _fy, _inv = self.plot._to_screen(rect, self.plot.view_window or lim)
        p.setFont(font(LABEL_01))
        p.setPen(QColor(t("text-primary")))
        x_name = s.x.plain if s.x is not None else "x"
        p.drawText(QRectF(0, 0, 400, 18), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   f"Model predictions along {x_name}")
        for j, k in enumerate(MODEL_KEYS):
            y = 22 + j * 18
            p.setPen(QColor(t("text-secondary")))
            p.drawText(QRectF(0, y, rect.left() - 6, 16), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       k)
            labs = labels.get(k, [])
            for i, xv in enumerate(xs):
                xa = fx(xv) if i == 0 else (fx(xs[i - 1]) + fx(xv)) / 2
                xb = fx(xv) if i == len(xs) - 1 else (fx(xv) + fx(xs[i + 1])) / 2
                lab = labs[i] if i < len(labs) else NA
                p.fillRect(QRectF(xa, y, max(1.0, xb - xa), 16), QColor(THEME.tag_colors(lab)[0]))
            # class transitions along the path: "SS → MP at x = 0.9" at the first x of the new class
            for i in range(1, min(len(xs), len(labs))):
                if labs[i] != labs[i - 1]:
                    xa = (fx(xs[i - 1]) + fx(xs[i])) / 2
                    crisp.vline(p, xa, y, y + 16, t("text-primary"))
                    p.setPen(QColor(THEME.tag_colors(labs[i])[1]))
                    p.drawText(QRectF(xa + 4, y, 240, 16), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                               f"{labs[i - 1]} → {labs[i]} at {x_name} = {xs[i]:g}")
        p.end()


_ = (QFrame, QLabel, QSizePolicy, crisp, categorical, ROW_SM, PLOT_TYPES, MODELS, NA_ERROR, NA_MISSING_DATA,
     NA_UNDEFINED, DIM_CSTR, RAW_POINT_LIMIT, ANA_SAMPLED)
