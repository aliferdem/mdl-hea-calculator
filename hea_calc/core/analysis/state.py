"""The Analysis state and its event rules (no Qt) - ``ANALYSIS_STATES_AND_INTERACTIONS.md`` section 3.

One immutable :class:`AnalysisState` drives the embedded panel *and* the expanded workspace (they are two
views of the same state).  Events are pure functions ``state -> state``; the invariant is that no state
variable changes unless the event's rule lists it:

1. double-click a row => active := its result_id; nothing else changes;
2. single click, hover, sort, page, column change => no change (no event exists for them);
3. table filter changed => if the scope's population is "filtered", the scope becomes stale (filter);
4. (removed with the Results checkbox column: there is no checked set)
5. results removed => the active composition is marked removed if it was one of them; the selection and
   inspector lose them; statistics become stale (data version);
6. rows committed to the scope's run => statistics stale (data version);
7. context / tab switches, expand / back => view changes only;
8. update collection => re-resolved scope; plot configuration kept; surviving selection kept;
9. "Analyse composition" on a plot point => active := id and context := composition (only this action).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .plotting import PlotConfiguration
from .scope import FILTERED, ResolvedScope

COMPOSITION, COLLECTION = "composition", "collection"
COMP_TABS = ("overview", "descriptors", "models", "model_details")
COLL_TABS = ("overview", "plots", "statistics", "models")
COMP_TAB_LABELS = ("Overview", "Descriptors", "Models", "Model details")
COLL_TAB_LABELS = ("Overview", "Plots", "Statistics", "Models")
STALE_FILTER = "filter"
REMOVED, RECALCULATED = "removed", "recalculated"


@dataclass(frozen=True)
class AnalysisState:
    context: str = COMPOSITION
    comp_tab: str = "overview"
    coll_tab: str = "overview"
    active: int | None = None
    active_gone: str | None = None             # REMOVED / RECALCULATED when the active result disappeared
    composition_badge: bool = False            # S-03: the active composition changed while in Collection
    model: str = "M1"                          # Model details selection
    resolved: ResolvedScope | None = None
    stale: str | None = None
    scope_gone: bool = False                   # S-41: the run of the collection was removed
    plot: PlotConfiguration = field(default_factory=PlotConfiguration)
    selection: frozenset = frozenset()         # PlotSelection result ids (visual only)
    inspector: int | None = None               # plot point shown in the inspector
    stats_metrics: tuple = ("dhmix", "dsmix", "omega", "delta", "delta_cn12", "vec", "phi_king")
    stats_group: str = "none"
    stats_all: bool = False                    # "All measures"
    stats_focus: str = ""                      # metric of the distribution (histogram / box plot); "" = none
                                               # chosen yet - a neutral "Select a descriptor" state, never a
                                               # default descriptor presented as more important
    denominator: str = "evaluated"             # model distributions: evaluated | population
    split_status: bool = True
    dist_group: str = "none"
    descriptor_search: str = ""
    full_precision: bool = False
    expanded: bool = False
    data_version: int = 0

    @property
    def scope(self):
        return self.resolved.scope if self.resolved else None


# ---------------------------------------------------------------------- events
def double_click(s: AnalysisState, rid: int) -> AnalysisState:
    """Rule 1 (S-03 / S-04): the row becomes the active composition."""
    return replace(s, active=int(rid), active_gone=None,
                   composition_badge=s.composition_badge or (s.context == COLLECTION and rid != s.active))


def set_active(s: AnalysisState, rid: int | None) -> AnalysisState:
    """A new single calculation becomes active (S-02); context unchanged."""
    if rid is None:
        return replace(s, active=None, active_gone=None)
    return double_click(s, rid)


def switch_context(s: AnalysisState, context: str) -> AnalysisState:
    if context not in (COMPOSITION, COLLECTION):
        raise ValueError(context)
    return replace(s, context=context, composition_badge=False if context == COMPOSITION else s.composition_badge)


def set_tab(s: AnalysisState, tab: str) -> AnalysisState:
    if s.context == COMPOSITION:
        if tab not in COMP_TABS:
            raise ValueError(tab)
        return replace(s, comp_tab=tab)
    if tab not in COLL_TABS:
        raise ValueError(tab)
    return replace(s, coll_tab=tab)


def select_model(s: AnalysisState, model: str, open_details: bool = False) -> AnalysisState:
    s = replace(s, model=model)
    return replace(s, comp_tab="model_details") if open_details else s


def table_filter_changed(s: AnalysisState, frozen_filters: tuple) -> AnalysisState:
    """Rule 3: never re-resolves; flags the scope when its filter copy no longer matches the table."""
    r = s.resolved
    if r is None or r.scope.base != FILTERED:
        return s
    if tuple(frozen_filters) != tuple(r.filter_snapshot):
        return replace(s, stale=STALE_FILTER)
    return replace(s, stale=None) if s.stale == STALE_FILTER else s


def results_removed(s: AnalysisState, ids) -> AnalysisState:
    """Rule 5 (S-35 / S-36)."""
    ids = set(ids)
    gone = s.active is not None and s.active in ids
    return replace(s, active_gone=REMOVED if gone else s.active_gone,
                   selection=frozenset(i for i in s.selection if i not in ids),
                   inspector=None if s.inspector in ids else s.inspector,
                   data_version=s.data_version + 1)


def table_cleared(s: AnalysisState, recalculated: bool = False, runs_removed=()) -> AnalysisState:
    """Clear table / recalculation: the active result and the collection's run disappear (S-35, S-40, S-41)."""
    gone = RECALCULATED if recalculated else REMOVED
    scope_gone = s.scope_gone or (s.resolved is not None and (not runs_removed or s.scope.run_id in set(runs_removed)))
    return replace(s, active_gone=gone if s.active is not None else s.active_gone, selection=frozenset(),
                   inspector=None, scope_gone=scope_gone, data_version=s.data_version + 1)


def run_committed(s: AnalysisState, run_id: int) -> AnalysisState:
    """Rule 6: new rows of the collection's (running) run make statistics stale."""
    if s.resolved is not None and s.scope.run_id == run_id:
        return replace(s, data_version=s.data_version + 1)
    return s


def update_collection(s: AnalysisState, resolved: ResolvedScope, surviving=None) -> AnalysisState:
    """Rule 8: a newly resolved scope; plot configuration kept, surviving selection kept."""
    sel = s.selection if surviving is None else frozenset(i for i in s.selection if i in set(surviving))
    return replace(s, resolved=resolved, stale=None, scope_gone=False, selection=sel,
                   inspector=s.inspector if s.inspector in sel or surviving is None else None)


def set_plot(s: AnalysisState, plot: PlotConfiguration, keep_selection: bool = True) -> AnalysisState:
    return replace(s, plot=plot, selection=s.selection if keep_selection else frozenset())


def select_points(s: AnalysisState, ids, add: bool = False) -> AnalysisState:
    """Visual selection only - never changes the scope."""
    ids = frozenset(int(i) for i in ids)
    sel = (s.selection | ids) if add else ids
    insp = next(iter(ids)) if len(ids) == 1 else s.inspector
    return replace(s, selection=sel, inspector=insp)


def clear_selection(s: AnalysisState) -> AnalysisState:
    return replace(s, selection=frozenset(), inspector=None)


def inspect(s: AnalysisState, rid: int | None) -> AnalysisState:
    return replace(s, inspector=rid)


def analyse_point(s: AnalysisState, rid: int) -> AnalysisState:
    """Rule 9: the inspector's explicit "Analyse composition"."""
    return replace(s, active=int(rid), active_gone=None, context=COMPOSITION, composition_badge=False)


def set_expanded(s: AnalysisState, expanded: bool) -> AnalysisState:
    """Rule 7: a presentation change only."""
    return replace(s, expanded=bool(expanded))


def update(s: AnalysisState, **kw) -> AnalysisState:
    """Plain view settings (statistics metrics, denominator, search text, ...)."""
    return replace(s, **kw)
