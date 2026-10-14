"""Analysis controller: the one state holder shared by the embedded panel and the expanded workspace,
the background query runner and the bounded query cache.

* :class:`QueryRunner` - one daemon thread with its own read-only SQLite connection.  Jobs are keyed by a
  *slot* ("population", "stats", "plot", ...): a newer job for a slot supersedes the queued one and
  interrupts the running one (``sqlite3.Connection.interrupt``); a superseded answer is never delivered
  (stale-result rejection).  SQLite runs the queries in C with the GIL released; nothing here loops over
  results in Python on the GUI thread.  One queued signal per finished job - no signal flooding.
* :class:`AnalysisController` - wraps the immutable :class:`~...core.analysis.state.AnalysisState`; every
  change goes through :meth:`set_state`, which emits ``state_changed(old, new)``.  Views subscribe and
  redraw from the state; they never own analytical data.  Results are cached in an LRU keyed by
  (slot kind, scope key, data version, parameters) - never by widget state.
"""

from __future__ import annotations

import datetime as _dt
import queue
import threading
import time
from collections import OrderedDict

from PySide6.QtCore import QObject, QTimer, Signal

from ...core.analysis import state as S
from ...core.analysis.checked import CheckedSet
from ...core.analysis.plotting import default_config
from ...core.analysis.queries import QueryCancelled, ScopeQuery
from ...core.analysis.scope import CHECKED, FILTERED, FULL, CollectionScope, ResolvedScope, freeze_filters
from ...core.repository import user_message

CACHE_SIZE = 48


class QueryRunner(QObject):
    """Background query thread (see module docstring)."""

    finished = Signal(str, int, object, object)          # slot, token, result, error message

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.repo = repo
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._tokens: dict[str, int] = {}
        self._running: tuple[str, int, ScopeQuery | None] | None = None
        self._next = 0
        self._closed = False
        self.busy_slots: set[str] = set()
        self._thread = threading.Thread(target=self._loop, name="hea-analysis-queries", daemon=True)
        self._thread.start()

    def submit(self, slot: str, scope: CollectionScope, info, lo: int, fn) -> int:
        """Run ``fn(ScopeQuery)`` for ``slot``; returns the job token."""
        with self._lock:
            self._next += 1
            token = self._next
            self._tokens[slot] = token
            run = self._running
            if run is not None and run[0] == slot and run[2] is not None:
                run[2].cancel()                           # superseded while running
        self.busy_slots.add(slot)
        self._q.put((slot, token, scope, info, lo, fn))
        return token

    def cancel(self, slot: str) -> None:
        with self._lock:
            self._tokens[slot] = -1
            run = self._running
            if run is not None and run[0] == slot and run[2] is not None:
                run[2].cancel()
        self.busy_slots.discard(slot)

    def current(self, slot: str, token: int) -> bool:
        with self._lock:
            return self._tokens.get(slot) == token

    def close(self) -> None:
        self._closed = True
        with self._lock:
            run = self._running
            if run is not None and run[2] is not None:
                run[2].cancel()
        self._q.put(None)
        self._thread.join(3)

    def _loop(self) -> None:
        con = None
        while True:
            job = self._q.get()
            if job is None:
                break
            slot, token, scope, info, lo, fn = job
            if not self.current(slot, token):
                continue
            try:
                if con is None:
                    con = self.repo.reader_connection()
                sq = ScopeQuery(con, scope, info, lo)
                with self._lock:
                    self._running = (slot, token, sq)
                result, err = fn(sq), None
            except QueryCancelled:
                result, err = None, "cancelled"
            except Exception as exc:                      # noqa: BLE001 - reported in the view
                result, err = None, user_message(exc) if exc.__class__.__module__ == "sqlite3" else str(exc)
            finally:
                with self._lock:
                    self._running = None
            if self._closed:
                break
            if self.current(slot, token):
                try:
                    self.finished.emit(slot, token, result, err)
                except RuntimeError:                      # receiver deleted on shutdown
                    break
        if con is not None:
            con.close()


class AnalysisController(QObject):
    """The Analysis state holder (see module docstring)."""

    state_changed = Signal(object, object)               # old, new AnalysisState
    data_ready = Signal(str)                              # slot
    loading = Signal(str, bool)                           # slot, busy
    failed = Signal(str, str)                             # slot, message
    runs_changed = Signal()
    checked_changed = Signal()
    composition_changed = Signal()                        # the active composition's record (re)loaded
    report_requested = Signal(str)                        # "composition" | "collection"
    expand_requested = Signal(bool)
    show_in_table = Signal(object)                        # result ids
    help_requested = Signal(str)                          # Help page id
    export_requested = Signal(str)                        # stats_csv | plot_csv | plot_svg | plot_png
    check_results = Signal(object)                        # result ids to check in the table

    def __init__(self, repo, table_model=None, engine=None, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.model = table_model                          # ResultsModel (the table's view; may be None in tests)
        self.engine = engine
        self.state = S.AnalysisState()
        self.checked = table_model.checked if table_model is not None else CheckedSet(repo)
        self.runner = QueryRunner(repo, self)
        self.runner.finished.connect(self._on_finished)
        self.cache: OrderedDict = OrderedDict()
        self.data: dict[str, object] = {}                 # slot -> last delivered result
        self.data_keys: dict[str, tuple] = {}
        self.errors: dict[str, str] = {}
        self._jobs: dict[str, tuple] = {}                 # slot -> (token, cache key)
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

    def run_info(self, run_id: int):
        for r in self.runs():
            if r.run_id == run_id:
                return r
        return self.repo.get_run(run_id)

    def run_count(self, run_id: int) -> int:
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

    def table_checked_changed(self) -> None:
        self.apply(S.checked_changed, self.checked.version)
        self.checked_changed.emit()

    def results_removed(self, ids) -> None:
        ids = list(ids)
        self.checked.remove_ids(ids)
        self.cache.clear()
        self.apply(S.results_removed, ids)
        self.checked_changed.emit()
        self.refresh_runs()
        self._requery_scope()

    def table_cleared(self, recalculated: bool = False, lo: int | None = None, hi: int | None = None) -> None:
        if lo is not None and hi is not None and hi >= lo:
            self.checked.remove_range(lo, hi)
        self.cache.clear()
        if self.state.active is not None:
            self.record = self.row = None
        self.apply(S.table_cleared, recalculated)
        self.checked_changed.emit()
        self.refresh_runs()

    def rows_committed(self, run_id: int | None) -> None:
        """Rows arrived (a calculation is storing them): runs list, partial collections (throttled)."""
        self._runs_cache = []
        if run_id is not None and self.state.resolved is not None and self.state.scope.run_id == run_id:
            if not self._partial.isActive():
                self._partial.start()
        self.runs_changed.emit()

    def run_finished(self, run_id: int | None) -> None:
        self.refresh_runs()
        if run_id is not None and self.state.resolved is not None and self.state.scope.run_id == run_id:
            self._partial_refresh()

    def _partial_refresh(self) -> None:
        if self.state.resolved is None:
            return
        self.cache.clear()
        self.apply(S.run_committed, self.state.scope.run_id)
        self._requery_scope()

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
        version = self.checked.version

        def count(sq):
            return sq.count()

        def done(n):
            resolved = ResolvedScope(scope, n, _dt.datetime.now().strftime("%H:%M:%S"), filt, version,
                                     self.state.data_version)
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
        """Build and resolve a scope; a checked-results scope first snapshots the checked set."""
        if base == FILTERED:
            scope = CollectionScope(run_id, FILTERED, filters=freeze_filters(self.model.filters if self.model else ()))
        elif base == CHECKED:
            name, task = self.checked.snapshot()
            self._await(task, lambda: self._finish_checked(run_id, name, families, sizes, blocks))
            return
        else:
            scope = CollectionScope(run_id, FULL)
        scope = scope.with_restrictions(families, sizes, blocks)
        self.resolve(scope)

    def _finish_checked(self, run_id, name, families, sizes, blocks):
        old = self.state.scope
        scope = CollectionScope(run_id, CHECKED, snapshot=name, snapshot_count=self.checked.count)
        self.resolve(scope.with_restrictions(families, sizes, blocks))
        if old is not None and old.base == CHECKED and old.snapshot and old.snapshot != name:
            self.checked.drop_snapshot(old.snapshot)

    def update_collection(self) -> None:
        """The stale notice's "Update collection": re-resolve with the current filter / checked set."""
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
                  use_cache: bool = True, on_done=None) -> None:
        """Run ``fn(ScopeQuery)`` for ``slot`` in the background (cache first)."""
        scope = scope or self.state.scope
        if scope is None:
            return
        key = (slot, scope.key(), self.state.data_version, self.workspace_lo, params)
        if use_cache and key in self.cache:
            self.cache.move_to_end(key)
            self.runner.cancel(slot)
            self._jobs.pop(slot, None)
            self._deliver(slot, self.cache[key], key, on_done)
            return
        info = self.run_info(scope.run_id)
        token = self.runner.submit(slot, scope, info, self.workspace_lo, fn)
        self._jobs[slot] = (token, key if use_cache else None, on_done, key)
        self.loading.emit(slot, True)

    def cancel(self, slot: str) -> None:
        self.runner.cancel(slot)
        self._jobs.pop(slot, None)
        self.loading.emit(slot, False)

    def busy(self, slot: str) -> bool:
        return slot in self._jobs

    def _on_finished(self, slot: str, token: int, result, err) -> None:
        job = self._jobs.get(slot)
        if job is None or job[0] != token:
            return                                       # superseded: never delivered
        del self._jobs[slot]
        self.runner.busy_slots.discard(slot)
        self.loading.emit(slot, False)
        if err == "cancelled":
            return
        if err is not None:
            self.errors[slot] = err
            self.failed.emit(slot, err)
            return
        _token, cache_key, on_done, key = job
        if cache_key is not None:
            self.cache[cache_key] = result
            while len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)
        self._deliver(slot, result, key, on_done)

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

    def _requery_scope(self) -> None:
        """Population-level data of the current scope (overview); other slots are requested by views."""
        if self.state.resolved is None:
            return
        self.run_query("population", lambda sq: sq.population())
        self.requery.emit()

    requery = Signal()                                    # views re-request their own slots

    # ================================================================== convenience for views
    def query(self, slot: str, fn, params: tuple = ()) -> None:
        self.run_query(slot, fn, params=params)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Process events until no job is pending (tests / tools only)."""
        from PySide6.QtWidgets import QApplication
        end = time.perf_counter() + timeout
        while (self._jobs or self._awaiting) and time.perf_counter() < end:
            QApplication.processEvents()
            time.sleep(0.005)
        QApplication.processEvents()
        return not self._jobs and not self._awaiting
