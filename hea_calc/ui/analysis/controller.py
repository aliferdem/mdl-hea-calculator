"""Analysis controller: the one state holder shared by the embedded panel and the expanded workspace,
the background query runner and the bounded query cache.

* :class:`QueryRunner` - ``QUERY_THREADS`` daemon threads, each with its own read-only SQLite connection,
  serving one priority queue (a waiting view before prefetch).  Views ask per *slot* ("population", "stats",
  "plot", ...): a newer request for a slot supersedes its older one, which is dropped from the queue or
  interrupted (``sqlite3.Connection.interrupt``) unless another slot shares it; a superseded answer is never
  delivered (stale-result rejection).  SQLite runs the queries in C with the GIL released; nothing here loops
  over results in Python on the GUI thread.  One queued signal per finished job - no signal flooding.
* :class:`AnalysisController` - wraps the immutable :class:`~...core.analysis.state.AnalysisState`; every
  change goes through :meth:`set_state`, which emits ``state_changed(old, new)``.  Views subscribe and
  redraw from the state; they never own analytical data.  Results are cached in an LRU keyed by
  (slot kind, scope key, data version, parameters) - never by widget state.
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from collections import OrderedDict

from PySide6.QtCore import QObject, QTimer, Signal

from ...core.analysis import state as S
from ...core.analysis.plotting import default_config
from ...core.analysis.queries import QueryCancelled, ScopeQuery, merge_statistics
from ...core.analysis.scope import COMBINED_RUN_ID, FILTERED, FULL, CollectionScope, ResolvedScope, freeze_filters
from ...core.repository import user_message

CACHE_SIZE = 96
# Parallel read-only connections (SQLite releases the GIL while it works): measured on a 1 M-row run, six
# single-column scans take 1.3 s on six connections against 5.7 s one after another.  At most one of them
# serves prefetch, so a view never waits behind speculative work.
QUERY_THREADS = max(2, min(6, (os.cpu_count() or 4) // 2))


class QueryRunner(QObject):
    """Background query threads (see module docstring).

    ``threads`` daemon threads, each with its own read-only SQLite connection, take jobs from one queue in
    priority order (0 = a view is waiting, 1 = prefetch), then submission order; at most one thread runs a
    prefetch job at a time.  A job is identified by its
    token; ``cancel(token)`` drops a queued job or interrupts a running one, and a cancelled job's answer is never
    delivered.  SQLite runs the queries in C with the GIL released, so parallel queries do not starve Qt."""

    finished = Signal(int, object, object)               # token, result, error message

    def __init__(self, repo, parent=None, threads: int | None = None):
        super().__init__(parent)
        self.repo = repo
        self._cv = threading.Condition()
        self._queue: list[list] = []                      # [priority, token, scope, info, lo, fn]
        self._live: set[int] = set()                      # queued or running, still wanted
        self._running: dict[int, ScopeQuery | None] = {}
        self._prefetching = 0                             # running priority >= 1 jobs
        self._next = 0
        self._closed = False
        n = threads or QUERY_THREADS
        self._threads = [threading.Thread(target=self._loop, name=f"hea-analysis-queries-{i}", daemon=True)
                         for i in range(n)]
        for th in self._threads:
            th.start()

    def submit(self, scope: CollectionScope, info, lo: int, fn, priority: int = 0) -> int:
        """Run ``fn(ScopeQuery)`` in the background; returns the job token."""
        with self._cv:
            self._next += 1
            token = self._next
            self._live.add(token)
            self._queue.append([priority, token, scope, info, lo, fn])
            self._cv.notify()
        return token

    def promote(self, token: int, priority: int = 0) -> None:
        """A view now waits for a queued (prefetch) job: run it before lower-priority work."""
        with self._cv:
            for e in self._queue:
                if e[1] == token and e[0] > priority:
                    e[0] = priority

    def cancel(self, token: int) -> None:
        with self._cv:
            self._live.discard(token)
            self._queue = [e for e in self._queue if e[1] != token]
            sq = self._running.get(token)
            if sq is not None:
                sq.cancel()                               # under the lock: never interrupts the next job

    def live(self, token: int) -> bool:
        with self._cv:
            return token in self._live

    @property
    def idle(self) -> bool:
        with self._cv:
            return not self._live

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._queue.clear()
            for sq in self._running.values():
                if sq is not None:
                    sq.cancel()
            self._cv.notify_all()
        for th in self._threads:
            th.join(3)

    def _pick(self):
        if not self._queue:
            return None
        i = min(range(len(self._queue)), key=lambda k: (self._queue[k][0], self._queue[k][1]))
        if self._queue[i][0] >= 1 and self._prefetching:
            return None                                   # one prefetch at a time
        return i

    def _take(self):
        with self._cv:
            while not self._closed and (i := self._pick()) is None:
                self._cv.wait()
            if self._closed:
                return None
            job = self._queue.pop(i)
            if job[0] >= 1:
                self._prefetching += 1
            self._running[job[1]] = None
            return job

    def _loop(self) -> None:
        con = None
        while True:
            job = self._take()
            if job is None:
                break
            prio, token, scope, info, lo, fn = job
            try:
                if con is None:
                    con = self.repo.reader_connection()
                sq = ScopeQuery(con, scope, info, lo)
                with self._cv:
                    if token not in self._live:
                        raise QueryCancelled()
                    self._running[token] = sq
                result, err = fn(sq), None
            except QueryCancelled:
                result, err = None, "cancelled"
            except Exception as exc:                      # noqa: BLE001 - reported in the view
                result, err = None, user_message(exc) if exc.__class__.__module__ == "sqlite3" else str(exc)
            finally:
                with self._cv:
                    self._running.pop(token, None)
                    wanted = token in self._live
                    self._live.discard(token)
                    if prio >= 1:
                        self._prefetching -= 1
                        self._cv.notify_all()                 # a queued prefetch may run now
            if self._closed:
                break
            if wanted:
                try:
                    self.finished.emit(token, result, err)
                except RuntimeError:                      # receiver deleted on shutdown
                    break
        if con is not None:
            con.close()


class _Job:
    """One background query and the slots waiting for its answer (several slots may share one query)."""

    __slots__ = ("token", "key", "cacheable", "subs", "prefetch")

    def __init__(self, token: int, key: tuple, cacheable: bool, prefetch: bool = False):
        self.token, self.key, self.cacheable, self.prefetch = token, key, cacheable, prefetch
        self.subs: dict[str, object] = {}                 # slot -> on_done (or None)



class AnalysisController(QObject):
    """The Analysis state holder (see module docstring)."""

    state_changed = Signal(object, object)               # old, new AnalysisState
    data_ready = Signal(str)                              # slot
    loading = Signal(str, bool)                           # slot, busy
    failed = Signal(str, str)                             # slot, message
    runs_changed = Signal()
    composition_changed = Signal()                        # the active composition's record (re)loaded
    report_requested = Signal(str)                        # "composition" | "collection"
    expand_requested = Signal(bool)
    window_requested = Signal()                           # Options > Open in new window (the Analysis window)
    show_in_table = Signal(object)                        # result ids
    help_requested = Signal(str)                          # Help page id
    export_requested = Signal(str)                        # stats_csv | plot_csv | plot_svg | plot_png
    batch_mass_changed = Signal(float)                    # Total mass preference (g): Mass (… g batch) column

    def __init__(self, repo, table_model=None, engine=None, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.model = table_model                          # ResultsModel (the table's view; may be None in tests)
        self.engine = engine
        self.state = S.AnalysisState()
        from ..preferences import DEFAULT_TOTAL_MASS
        self.batch_mass = DEFAULT_TOTAL_MASS              # display preference only (never a model input)
        self.runner = QueryRunner(repo, self)
        self.runner.finished.connect(self._on_finished)
        self.cache: OrderedDict = OrderedDict()
        self.data: dict[str, object] = {}                 # slot -> last delivered result
        self.data_keys: dict[str, tuple] = {}
        self.errors: dict[str, str] = {}
        self._by_token: dict[int, _Job] = {}              # every background job not yet answered
        self._by_key: dict[tuple, _Job] = {}              # cacheable jobs by answer key (shared by slots)
        self._slots: dict[str, _Job] = {}                 # slot -> the job it waits for
        self._stats_req = None
        self._stats_parts: dict = {}
        self.prefetch_enabled = True
        self._runs_cache: list = []
        self._run_counts: dict[int, int] = {}
        self.record = None                                # ResultRecord of the active composition
        self.row = None                                   # materialised ResultRow (engine result)
        self._resolving = None
        self._poll = QTimer(self)
        self._poll.setInterval(20)
        self._poll.timeout.connect(self._poll_tasks)
        self._partial = QTimer(self)                      # throttled re-query of a running run (rule 6)
        self._partial.setSingleShot(True)
        self._partial.setInterval(2000)
        self._partial.timeout.connect(self._partial_refresh)

    # ================================================================== state
    def set_state(self, new: S.AnalysisState) -> None:
        old = self.state
        if new == old:
            return
        self.state = new
        self.state_changed.emit(old, new)

    def apply(self, fn, *args, **kw) -> None:
        self.set_state(fn(self.state, *args, **kw))

    def set_batch_mass(self, grams: float) -> None:
        """The Total mass preference changed: views redraw their Mass column; nothing is re-queried."""
        if grams and grams > 0 and grams != self.batch_mass:
            self.batch_mass = float(grams)
            self.batch_mass_changed.emit(self.batch_mass)

    def close(self) -> None:
        self._poll.stop()
        self.runner.close()

    # ================================================================== workspace / runs
    @property
    def workspace_lo(self) -> int:
        return self.model.view.lo if self.model is not None else 0

    def runs(self, refresh: bool = False) -> list:
        """Calculation runs with results in the table's workspace (newest first)."""
        if refresh or not self._runs_cache:
            lo = self.workspace_lo
            hi = self.model.view.hi if self.model is not None else 2 ** 62
            out = []
            for info in self.repo.runs():
                if info.first_id is None or info.cleared or info.last_id < lo or info.first_id > hi:
                    continue
                out.append(info)
            self._runs_cache = list(reversed(out))
        return self._runs_cache

    combined_runs: tuple | None = None                     # the user's combined selection (Combine runs)

    def combine(self, run_ids) -> str | None:
        """Combine runs: show the selected compatible runs as one collection (a logical view; the stored runs are
        not touched).  Returns why they cannot be combined, or ``None`` when the combined scope is being resolved."""
        from ...core.analysis.combine import combine_problem
        runs = tuple(sorted({int(r) for r in run_ids}))
        problem = combine_problem([self.run_info(r) for r in runs])
        if problem:
            return problem
        self.combined_runs = runs
        self.scope_for(COMBINED_RUN_ID, FULL)
        return None

    def run_info(self, run_id: int):
        if run_id == COMBINED_RUN_ID:
            if not self.combined_runs:
                return None
            from ...core.analysis.combine import combined_info
            infos = [self.run_info(r) for r in self.combined_runs]
            return combined_info(infos) if all(i is not None for i in infos) else None
        for r in self.runs():
            if r.run_id == run_id:
                return r
        return self.repo.get_run(run_id)

    def run_count(self, run_id: int) -> int:
        if run_id == COMBINED_RUN_ID:
            return sum(self.run_count(r) for r in (self.combined_runs or ()))
        return self._run_count(run_id)

    def _run_count(self, run_id: int) -> int:
        return self._run_counts.get(run_id, (self.run_info(run_id).calculated if self.run_info(run_id) else 0))

    def refresh_runs(self) -> None:
        self.runs(refresh=True)
        lo = self.workspace_lo
        ids = [r.run_id for r in self._runs_cache]

        def count(sq):
            return sq.run_counts(ids)
        _ = lo
        if ids:
            self.run_query("run_counts", count, scope=CollectionScope(ids[0]), use_cache=False)
        self.runs_changed.emit()

    def default_run(self) -> int | None:
        """The run of the active composition, else the most recent complete run (data contract 5.2)."""
        runs = self.runs()
        if self.record is not None and any(r.run_id == self.record.run_id for r in runs):
            return self.record.run_id
        for r in runs:
            if r.status == "complete":
                return r.run_id
        return runs[0].run_id if runs else None

    # ================================================================== active composition
    def set_active(self, rid: int | None, by: str = "double_click") -> None:
        """Rule 1 / rule 9 (by = "inspector")."""
        if rid is None:
            self.record = self.row = None
            self.apply(S.set_active, None)
            self.composition_changed.emit()
            return
        rec = self.repo.get_result(int(rid))
        if rec is None:
            return
        self.record = rec
        self.row = rec.materialize()
        if by == "inspector":
            self.apply(S.analyse_point, rid)
        else:
            self.apply(S.double_click, rid)
        self.composition_changed.emit()

    # ================================================================== table events
    def table_filter_changed(self) -> None:
        if self.model is not None:
            self.apply(S.table_filter_changed, freeze_filters(self.model.filters))

    def results_removed(self, ids) -> None:
        ids = list(ids)
        self.cache.clear()
        self.apply(S.results_removed, ids)
        self.refresh_runs()
        self._requery_scope()

    def results_restored(self) -> None:
        """Edit > Undo brought removed results back: runs, caches and the current collection are re-read."""
        self.cache.clear()
        self.refresh_runs()
        if self.state.resolved is not None and not self.state.scope_gone:
            self._requery_scope()
        # the active composition was among them: it is shown again, not "removed"
        if self.state.active is not None and self.state.active_gone == S.REMOVED:
            rec = self.repo.get_result(int(self.state.active))
            if rec is not None:
                self.record, self.row = rec, rec.materialize()
                self.apply(S.active_restored)
                self.composition_changed.emit()

    def table_cleared(self, recalculated: bool = False, lo: int | None = None, hi: int | None = None) -> None:
        _ = (lo, hi)
        self.cache.clear()
        if self.state.active is not None:
            self.record = self.row = None
        self.apply(S.table_cleared, recalculated)
        self.refresh_runs()

    def rows_committed(self, run_id: int | None) -> None:
        """Rows arrived (a calculation is storing them): the runs list, and - when they belong to the open
        collection's run - the "newer results available" mark.  The collection itself keeps its snapshot: nothing
        is re-queried while results stream in (2026-10-28); the user refreshes it (:meth:`refresh_collection`)."""
        self._runs_cache = []
        if run_id is not None and self.state.resolved is not None and run_id in self.state.scope.run_ids:
            self.apply(S.run_committed, self.state.scope.run_id)
        self.runs_changed.emit()

    def run_finished(self, run_id: int | None) -> None:
        self.refresh_runs()
        if run_id is not None and self.state.resolved is not None and run_id in self.state.scope.run_ids:
            self.apply(S.run_committed, self.state.scope.run_id)   # newer results: offered, not applied

    def refresh_collection(self) -> None:
        """Refresh (the notice's action): the same scope - run, population, filter, restrictions - re-counted and
        re-queried on the stored data as it is now.  Idempotent; a refresh while one is pending replaces it (the
        query runner is latest-wins), so old and new answers are never mixed."""
        sc = self.state.scope
        if sc is None:
            return
        self.cache.clear()
        self.apply(S.refresh_collection)
        self.resolve(sc)

    def _partial_refresh(self) -> None:                    # kept for callers of the former "Refresh now"
        self.refresh_collection()

    # ================================================================== scope resolution
    def ensure_scope(self) -> None:
        """First switch to Collection: default scope = full result set of the default run."""
        if self.state.resolved is not None and not self.state.scope_gone:
            return
        run = self.default_run()
        if run is not None:
            self.resolve(CollectionScope(run))

    def resolve(self, scope: CollectionScope, keep_plot: bool = True) -> None:
        """Resolve a scope explicitly (creation, Update collection, run / population / restriction change)."""
        info = self.run_info(scope.run_id)
        filt = scope.filters if scope.base == FILTERED else ()

        def count(sq):
            return sq.count()

        def done(n):
            resolved = ResolvedScope(scope, n, _dt.datetime.now().strftime("%H:%M:%S"), filt,
                                     data_version=self.state.data_version)
            old = self.state
            new = S.update_collection(old, resolved)
            if not keep_plot or old.resolved is None or old.scope.run_id != scope.run_id:
                new = S.set_plot(new, default_config(info), keep_selection=False)
                new = S.clear_selection(new)
            self.cache.clear() if old.resolved is not None and old.scope.run_id != scope.run_id else None
            self.set_state(new)
            self._requery_scope()
        self._resolving = (scope, done)
        self.run_query("resolve", count, scope=scope, use_cache=False, on_done=done)

    def scope_for(self, run_id: int, base: str, families=None, sizes=None, blocks=None, on_ready=None) -> None:
        """Build and resolve a scope (full or filtered result set of one run, with optional restrictions)."""
        runs = self.combined_runs if run_id == COMBINED_RUN_ID else None
        if run_id == COMBINED_RUN_ID:
            blocks = None                                  # blocks are per run: not in a combined collection
        if base == FILTERED:
            scope = CollectionScope(run_id, FILTERED, filters=freeze_filters(self.model.filters if self.model else ()),
                                    runs=runs)
        else:
            scope = CollectionScope(run_id, FULL, runs=runs)
        scope = scope.with_restrictions(families, sizes, blocks)
        self.resolve(scope)

    def update_collection(self) -> None:
        """The stale notice's "Update collection": re-resolve with the current table filter."""
        sc = self.state.scope
        if sc is None:
            return
        self.scope_for(sc.run_id, sc.base, sc.families, sc.sizes, sc.blocks)

    _awaiting: list = []

    def _await(self, task, fn) -> None:
        self._awaiting = [*self._awaiting, (task, fn)]
        self._poll.start()

    def _poll_tasks(self) -> None:
        rest = []
        for task, fn in self._awaiting:
            if task.done.is_set():
                fn()
            else:
                rest.append((task, fn))
        self._awaiting = rest
        if not rest:
            self._poll.stop()

    # ================================================================== queries
    def run_query(self, slot: str, fn, *, params: tuple = (), scope: CollectionScope | None = None,
                  use_cache: bool = True, on_done=None, share: str | None = None, priority: int = 0) -> None:
        """Run ``fn(ScopeQuery)`` for ``slot`` in the background (cache first).

        The answer is identified by ``(share or slot, scope, data version, workspace, params)``: a cached answer
        is delivered at once, and a slot asking for a query that is already running (for another slot, or as a
        prefetch) waits for that job instead of starting a second one.  A newer request for a slot replaces
        its older one (the older job is cancelled unless another slot still waits for it)."""
        scope = scope or self.state.scope
        if scope is None:
            return
        key = (share or slot, scope.key(), self.state.data_version, self.workspace_lo, params)
        cur = self._slots.get(slot)
        if cur is not None and use_cache and cur.cacheable and cur.key == key:
            cur.subs[slot] = on_done                      # the same question is already being answered
            return
        self._release(slot, signal=False)
        if use_cache and key in self.cache:
            self.cache.move_to_end(key)
            self.loading.emit(slot, False)
            self._deliver(slot, self.cache[key], key, on_done)
            return
        job = self._by_key.get(key) if use_cache else None
        if job is None:
            info = self.run_info(scope.run_id)
            token = self.runner.submit(scope, info, self.workspace_lo, fn, priority)
            job = _Job(token, key, use_cache)
            self._by_token[token] = job
            if use_cache:
                self._by_key[key] = job
        else:
            self.runner.promote(job.token, priority)
        job.subs[slot] = on_done
        self._slots[slot] = job
        self.loading.emit(slot, True)

    def prefetch(self, share: str, fn, params: tuple = (), scope: CollectionScope | None = None) -> None:
        """Compute an answer a view is likely to ask for next, at low priority, into the cache only."""
        if not self.prefetch_enabled:
            return
        scope = scope or self.state.scope
        if scope is None or self.state.scope_gone:
            return
        key = (share, scope.key(), self.state.data_version, self.workspace_lo, params)
        if key in self.cache or key in self._by_key:
            return
        token = self.runner.submit(scope, self.run_info(scope.run_id), self.workspace_lo, fn, 1)
        job = _Job(token, key, True, prefetch=True)
        self._by_token[token] = job
        self._by_key[key] = job

    def _release(self, slot: str, signal: bool = True) -> None:
        """``slot`` no longer waits for its query; a job nobody waits for (and no prefetch) is cancelled."""
        job = self._slots.pop(slot, None)
        if job is None:
            return
        job.subs.pop(slot, None)
        if not job.subs and not job.prefetch:
            self.runner.cancel(job.token)
            self._drop(job)
        if signal:
            self.loading.emit(slot, False)

    def _drop(self, job: _Job) -> None:
        self._by_token.pop(job.token, None)
        if self._by_key.get(job.key) is job:
            del self._by_key[job.key]

    def cancel(self, slot: str) -> None:
        if slot == "stats":
            self._stats_req = None
            for s in [s for s in self._slots if s.startswith("stats:")]:
                self._release(s)
        self._release(slot, signal=False)
        self.loading.emit(slot, False)

    def busy(self, slot: str) -> bool:
        if slot == "stats":
            return any(s.startswith("stats:") for s in self._slots)
        return slot in self._slots

    def _on_finished(self, token: int, result, err) -> None:
        job = self._by_token.get(token)
        if job is None:
            return                                       # cancelled / superseded: never delivered
        self._drop(job)
        if err is None and job.cacheable:
            self.cache[job.key] = result
            self.cache.move_to_end(job.key)
            while len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)
        for slot, on_done in list(job.subs.items()):
            if self._slots.get(slot) is not job:
                continue
            del self._slots[slot]
            self.loading.emit(slot, False)
            if err == "cancelled":
                continue
            if err is not None:
                self.errors[slot] = err
                self.failed.emit(slot, err)
                continue
            self._deliver(slot, result, job.key, on_done)

    def _deliver(self, slot, result, key, on_done) -> None:
        self.errors.pop(slot, None)
        if slot == "run_counts":
            self._run_counts.update(result or {})
            self.runs_changed.emit()
            return
        if on_done is not None:
            on_done(result)
            return
        self.data[slot] = result
        self.data_keys[slot] = key
        self.data_ready.emit(slot)

    # ---- Statistics: one query per metric, delivered as each finishes
    def request_statistics(self, metrics, priority: int = 0) -> None:
        """The Statistics table of ``metrics``: one background query per metric (they run in parallel and each is
        cached on its own, so adding a metric calculates only that metric).  ``data["stats"]`` is published as
        metrics arrive, with ``pending`` naming those still being calculated."""
        sc = self.state.scope
        if sc is None:
            return
        metrics = tuple(metrics)
        req = (sc.key(), self.state.data_version, self.workspace_lo, metrics)
        self._stats_req = req
        self._stats_parts = {}
        for s in [s for s in self._slots if s.startswith("stats:") and s[6:] not in metrics]:
            self._release(s, signal=False)
        for m in metrics:
            self.run_query(f"stats:{m}", lambda sq, m=m: sq.statistics([m]), params=(m,), share="stat1",
                           on_done=lambda res, m=m, req=req: self._stats_part(req, m, res), priority=priority)
        self._publish_stats()

    def statistics_cached(self, metric: str):
        """``statistics([metric])`` of the current scope if it is already known, else None."""
        sc = self.state.scope
        if sc is None:
            return None
        return self.cache.get(("stat1", sc.key(), self.state.data_version, self.workspace_lo, (metric,)))

    def _stats_part(self, req, metric, result) -> None:
        if req != self._stats_req:
            return
        self._stats_parts[metric] = result
        self._publish_stats()

    def _publish_stats(self) -> None:
        req = self._stats_req
        if req is None:
            return
        metrics = req[3]
        parts = [self._stats_parts[m] for m in metrics if m in self._stats_parts]
        pending = tuple(m for m in metrics if m not in self._stats_parts)
        self.loading.emit("stats", bool(pending))
        if not parts:
            return
        self.data["stats"] = merge_statistics(parts, pending)
        self.data_keys["stats"] = ("stats",) + req[:3] + (metrics,)
        self.data_ready.emit("stats")

    def _requery_scope(self) -> None:
        """Population-level data of the current scope (overview); other slots are requested by views."""
        if self.state.resolved is None:
            return
        self.run_query("population", lambda sq: sq.population())
        if self.state.scope.combined:
            self.run_query("dups", lambda sq: sq.cross_run_duplicates())
        self.requery.emit()
        self._prefetch_tabs()

    def _prefetch_tabs(self) -> None:
        """While the user reads one tab, the answers the other tabs open with are calculated in the background
        (low priority, cache only): population, model distributions, the default statistics."""
        st = self.state
        if st.resolved is None or st.scope_gone:
            return
        self.prefetch("population", lambda sq: sq.population())
        self.prefetch("dist", lambda sq: sq.distribution())
        for m in st.stats_metrics:
            self.prefetch("stat1", lambda sq, m=m: sq.statistics([m]), (m,))

    requery = Signal()                                    # views re-request their own slots

    # ================================================================== convenience for views
    def query(self, slot: str, fn, params: tuple = ()) -> None:
        self.run_query(slot, fn, params=params)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Process events until no job is pending (tests / tools only)."""
        from PySide6.QtWidgets import QApplication
        end = time.perf_counter() + timeout
        while (self._by_token or self._awaiting) and time.perf_counter() < end:
            QApplication.processEvents()
            time.sleep(0.005)
        QApplication.processEvents()
        return not self._by_token and not self._awaiting
