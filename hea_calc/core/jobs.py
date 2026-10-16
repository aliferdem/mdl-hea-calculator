"""Calculation jobs: CPU-bound engine work outside the GUI process (no Qt here).

Measured: one alloy costs ~0.5 ms of pure-Python engine work, so 100 000 alloys are ~55 s of CPU.
In a QThread that work holds the GIL and starves Qt's event loop, so batches of real size run in a
persistent pool of worker *processes* (``ProcessPoolExecutor``, ``spawn`` start method - the only
one on Windows - created once and reused):

* each worker builds its own :class:`~hea_calc.core.engine.Engine` once (pool initializer);
* compositions are calculated in chunks of a few hundred, and results come back as columnar
  :func:`~hea_calc.core.chunks.pack_results` chunks carrying their provenance - never one
  message per alloy;
* a coordinating thread in the GUI process (:class:`CalculationJob`) only decides, submits and
  collects: at most a small window of chunks is in flight.  With a :class:`Delivery` (the app),
  each worker puts its chunk - tagged with the run and its chunk index - straight into the
  results repository's writer process, which stores chunks strictly in index order (workers never
  write the database; the GUI process never unpickles a chunk) and the job thread only collects
  small acknowledgements, in order, for progress and cancellation.  Without one, chunks are
  collected in order into ``job.inbox``;
* recipe jobs are generated where they are calculated (``core/recipes.py``): no process holds the
  whole batch, so the batch size is bounded by time and disk, not by memory;
* cancellation sets a shared ``multiprocessing.Event`` that every worker checks between alloys,
  cancels queued chunks and keeps the contiguous prefix of finished results;
* small jobs (``INPROCESS_MAX`` alloys, a fraction of a second of work) run in the coordinating
  thread itself rather than paying for process start-up.

Spawned workers import ``__main__`` as ``__mp_main__``; ``main.py`` keeps its imports inside the
``__main__`` guard and calls ``multiprocessing.freeze_support()`` for frozen builds.
"""

from __future__ import annotations

import itertools
import multiprocessing as mp
import os
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field

from .chunks import pack_results, with_metadata

INPROCESS_MAX = 300
MAX_CHUNK = 500
MIN_CHUNK = 50
PLAN_BLOCK = 512             # expression combinations per plan range (a multiple of 8)
WINDOW_PER_WORKER = 4        # chunks in flight per worker: bounds results waiting in the GUI process

# ---------------------------------------------------------------------- worker process side
_ENGINE = None
_CANCEL = None
_CHANNEL = None          # the result writer's queue (None: chunks are returned to the job thread)


def _init_worker(cancel_event, channel=None) -> None:         # pragma: no cover - runs in a child
    global _ENGINE, _CANCEL, _CHANNEL
    _watch_parent()
    from .engine import default_engine
    _ENGINE = default_engine()
    _CANCEL = cancel_event
    _CHANNEL = channel


def _deliver(chunk: dict, deliver) -> dict:                  # pragma: no cover - runs in a child
    """Hand the chunk to the writer process (``deliver = (run_id, chunk index)``) and return a small
    acknowledgement - or return the chunk itself when there is no writer channel."""
    if deliver is None or _CHANNEL is None:
        return chunk
    run_id, index = deliver
    _CHANNEL.put(("chunk", run_id, index, chunk))
    return {"n": chunk["n"], "cancelled": chunk["cancelled"], "delivered": True}


def _watch_parent() -> None:                                 # pragma: no cover - runs in a child
    """Exit when the GUI process dies, however it dies.  A pool worker blocks reading its task pipe
    and itself holds that pipe's write end, so it would never see EOF and would linger forever."""
    parent = mp.parent_process()
    if parent is None:
        return

    def watch():
        from multiprocessing.connection import wait
        wait([parent.sentinel])
        os._exit(0)
    threading.Thread(target=watch, name="hea-parent-watch", daemon=True).start()


def _ping() -> int:                                          # pragma: no cover - runs in a child
    return os.getpid()


def _calculate_chunk(compositions: list[dict], options: dict, meta=None, deliver=None) -> dict:  # pragma: no cover
    chunk = calculate_chunk(_ENGINE, compositions, options, _CANCEL.is_set)
    chunk.pop("_results")
    if meta is not None:
        with_metadata(chunk, *meta)
    return _deliver(chunk, deliver)


# Per-worker generation state of the latest job only (a cursor never holds a generated list).
_STATE: dict = {}


def _job_state(key) -> dict:                                 # pragma: no cover - runs in a child
    st = _STATE.get(key)
    if st is None:
        _STATE.clear()
        st = _STATE[key] = {}
    return st


def _recipe_count(recipe) -> int:                            # pragma: no cover - runs in a child
    return recipe.count()


def _sweep_chunk(key, recipe, start: int, stop: int, options: dict, deliver=None) -> dict:  # pragma: no cover
    st = _job_state(key)
    cur = st.get("cursor")
    if cur is None:
        from .recipes import SweepCursor
        cur = st["cursor"] = SweepCursor(recipe)
    grid = cur.take(start, stop)
    comps = [recipe.atomic(g) for g in grid]
    return _deliver(calculate_recipe_chunk(_ENGINE, recipe, comps, None, None, None, "sweep", options,
                                           _CANCEL.is_set, design_rows=grid), deliver)


def _expression_plan(recipe, path: str, block: int):         # pragma: no cover - runs in a child
    return recipe.plan(path, block, _CANCEL.is_set)


def _expression_chunk(key, recipe, path: str, k: int, block: int, options: dict,
                      deliver=None) -> dict:                  # pragma: no cover - runs in a child
    with open(path, "rb") as fh:
        fh.seek(k * (block // 8))
        bits = fh.read(block // 8)
    comps, names, envs, blocks = recipe.take(bits, k, block)
    return _deliver(calculate_recipe_chunk(_ENGINE, recipe, comps, names, envs, blocks, "expression", options,
                                           _CANCEL.is_set), deliver)


def _recalc_chunk(key, recipe, lo: int, hi: int, options: dict, deliver=None) -> dict:  # pragma: no cover
    st = _job_state(key)
    con = st.get("con")
    if con is None:
        con = st["con"] = recipe.connect()
    d = recipe.read(con, lo, hi)
    return _deliver(calculate_recalc_chunk(_ENGINE, d, options, _CANCEL.is_set), deliver)


def _release(key) -> None:                                   # pragma: no cover - runs in a child
    st = _STATE.pop(key, None)
    if st and st.get("con") is not None:
        st["con"].close()


def run_in_worker(service: "CalculationService", fn, *args):
    """Run a picklable ``fn(*args)`` in the worker pool (heavy pre-flight counts); a Future."""
    return service.pool().submit(fn, *args)


# ---------------------------------------------------------------------- chunk calculation (any process)
def calculate_chunk(engine, compositions: Sequence[dict], options: dict,
                    cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Evaluate compositions with ``engine`` (stops early when ``cancelled()``); a packed chunk."""
    done_comps, results = [], []
    for comp in compositions:
        if cancelled():
            break
        results.append(engine.calculate(comp, **options))
        done_comps.append(comp)
    chunk = pack_results(done_comps, results)
    chunk["cancelled"] = len(results) < len(compositions)
    chunk["_results"] = results
    return chunk


def calculate_recipe_chunk(engine, recipe, comps, names, envs, blocks, source: str, options: dict,
                           cancelled: Callable[[], bool] = lambda: False, design_rows=None) -> dict:
    """``design_rows``: the generating coordinates when they differ from the calculated compositions (a
    wt.% / mass composition space calculates converted atomic amounts but keeps the entered values)."""
    chunk = calculate_chunk(engine, comps, options, cancelled)
    results = chunk.pop("_results")
    n = chunk["n"]
    if names is None:
        names = [recipe.name(c) for c in comps[:n]]
    design = recipe.design((design_rows if design_rows is not None else comps)[:n], (envs or [])[:n], results)
    return with_metadata(chunk, names, source, envs, blocks, design)


def calculate_recalc_chunk(engine, d: dict, options: dict, cancelled: Callable[[], bool] = lambda: False) -> dict:
    chunk = calculate_chunk(engine, d["comps"], options, cancelled)
    chunk.pop("_results")
    n = chunk["n"]
    design = d["design"]
    if design is not None and d["comps"]:
        k = len(design) // len(d["comps"])
        design = design[:n * k]
    return with_metadata(chunk, d["names"], d["sources"], None, d["blocks"], design)


# ---------------------------------------------------------------------- pool service
def default_workers() -> int:
    return max(1, min((os.cpu_count() or 2) - 1, 8))


class CalculationService:
    """Owns the persistent worker pool (created lazily, off the GUI thread) and the cancel event."""

    def __init__(self, workers: int | None = None, inprocess_max: int = INPROCESS_MAX, channel=None):
        self.workers = workers or default_workers()
        self.inprocess_max = inprocess_max
        self.channel = channel             # the result writer's queue, handed to every worker at start-up
        self.scratch_dir: str = tempfile.gettempdir()      # expression plans (the session folder in the app)
        self._ctx = mp.get_context("spawn")
        self._pool: ProcessPoolExecutor | None = None
        self._cancel = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._warm: threading.Thread | None = None
        self._atexit = False

    def pool(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._pool is None:
                if not self._atexit:
                    import atexit
                    import weakref
                    ref = weakref.ref(self)
                    atexit.register(lambda: ref() is not None and ref().shutdown(1.0))
                    self._atexit = True
                self._cancel = self._ctx.Event()
                self._pool = ProcessPoolExecutor(self.workers, mp_context=self._ctx, initializer=_init_worker,
                                                 initargs=(self._cancel, self.channel))
            return self._pool

    @property
    def cancel_event(self):
        return self._cancel

    def warm_up(self) -> threading.Thread:
        """Start the worker processes in the background (no GUI-thread cost)."""
        def run():
            try:
                pool = self.pool()
                for f in [pool.submit(_ping) for _ in range(self.workers)]:
                    f.result()
            except Exception:                          # noqa: BLE001 - a failed warm-up is retried by a job
                pass
        if self._warm is not None and self._warm.is_alive():
            return self._warm
        th = threading.Thread(target=run, name="hea-pool-warmup", daemon=True)
        self._warm = th
        th.start()
        return th

    @property
    def warm(self) -> bool:
        return self._pool is not None

    def worker_pids(self) -> list[int]:
        pool = self._pool
        procs = getattr(pool, "_processes", None) or {}
        return [p.pid for p in list(procs.values()) if p.is_alive()]

    def _discard_pool(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def shutdown(self, timeout: float = 3.0) -> None:
        """Stop every worker process (application exit) - none is left orphaned."""
        if self._warm is not None:
            self._warm.join(timeout)      # a pool still starting up is shut down once it exists
        with self._lock:
            pool, self._pool = self._pool, None
            if self._cancel is not None:
                self._cancel.set()
        if pool is None:
            return
        procs = list((getattr(pool, "_processes", None) or {}).values())
        # Orderly: queued chunks are cancelled, running ones stop at their next alloy (cancel event),
        # the executor sends its sentinels and joins.  Bounded, then anything left is terminated.
        closer = threading.Thread(target=lambda: pool.shutdown(wait=True, cancel_futures=True), daemon=True)
        closer.start()
        closer.join(timeout)
        for p in procs:
            if p.is_alive():
                p.terminate()
                p.join(0.5)

    def start(self, job: "CalculationJob") -> "CalculationJob":
        job.id = next(self._ids)
        job._service = self
        job._thread = threading.Thread(target=job._run, name=f"hea-job-{job.id}", daemon=True)
        job.state = "running"
        job.started = time.perf_counter()
        job._thread.start()
        return job


# ---------------------------------------------------------------------- job
@dataclass
class Delivery:
    """Where a job's chunks go: run ``run_id`` of the result writer (see module docstring)."""
    run_id: int
    put: Callable[[int, dict], bool]          # (chunk index, chunk) from this process (in-process jobs)
    stored: Callable[[], int]                 # chunks the writer has stored - back-pressure
    failed: Callable[[], bool] = lambda: False
    channel: object = None                    # the writer queue the pool workers were given


MAX_AHEAD_CHUNKS = 64                         # calculated but not yet stored (≈ 32 000 rows)


@dataclass
class JobInput:
    """What a job calculates.  ``compositions`` is a list, or a recipe (``core/recipes.py``)
    generated where it is calculated."""
    sources: Sequence[str] | str = "sweep"
    names: Sequence[str] = ()
    compositions: Sequence[dict] | Callable = ()
    variables: Sequence[dict] = ()
    options: dict = field(default_factory=dict)


class CalculationJob:
    """One calculation request (see module docstring).

    States: ``running`` → ``done`` | ``cancelled`` | ``error``.  Every chunk - in composition order,
    with its provenance attached - goes to the ``delivery`` (the result writer) as chunk 0, 1, 2 …,
    or to ``inbox`` as ``(start_index, chunk)`` tuples when there is none.  ``chunks_emitted`` is the
    contiguous prefix of chunks handed on (the writer keeps exactly those).  ``total`` is known once
    generation/counting has finished (an upper bound before that).
    """

    def __init__(self, data: JobInput, engine=None, delivery: Delivery | None = None):
        self.data = data
        self.engine = engine                 # for in-process (small) jobs
        self.delivery = delivery
        self.chunks_emitted = 0
        self.id = 0
        self.state = "pending"
        self.error: str | None = None
        self.total: int | None = None
        self.done_count = 0
        self.inbox: deque = deque()
        self.names: list[str] = []
        self.sources: list[str] = []
        self.variables: list[dict] = []
        self.started = 0.0
        self.first_result_at: float | None = None
        self.finished_at: float | None = None
        self.cancel_requested_at: float | None = None
        self.mode = "inprocess"
        self.plan_counts: tuple | None = None    # expression: (valid, skipped, duplicates, combinations, by block)
        self._cancel = threading.Event()
        self._service: CalculationService | None = None
        self._thread: threading.Thread | None = None

    # -------------------------------------------------------------- public
    def cancel(self) -> None:
        if not self._cancel.is_set():
            self.cancel_requested_at = time.perf_counter()
            self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def finished(self) -> bool:
        return self.state in ("done", "cancelled", "error")

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.finished

    def eta(self) -> float:
        if not self.total or not self.done_count:
            return 0.0
        elapsed = time.perf_counter() - self.started
        return elapsed / self.done_count * max(0, self.total - self.done_count)

    # -------------------------------------------------------------- job thread
    def _run(self) -> None:
        # Nothing CPU-heavy may run on this thread: it shares the GIL with the GUI thread, and every
        # Qt -> Python callback then waits for it (measured 0.5 s event-loop gaps).  It only decides,
        # submits and waits; generation and calculation happen in the worker processes.  The one
        # exception is a small batch (<= inprocess_max alloys, ~0.15 s) when no pool is running yet.
        try:
            svc = self._service
            d = self.data
            recipe = d.compositions if callable(d.compositions) else None
            size = recipe.estimate() if recipe is not None and hasattr(recipe, "estimate") else \
                (None if recipe is not None else len(d.compositions))
            small = size is not None and size <= svc.inprocess_max
            if svc.workers <= 1 or (small and not svc.warm):
                self._run_inprocess()
            elif recipe is not None:
                self._run_pool_recipe(recipe)
            else:
                self._materialise()
                self._run_pool(self._comps)
            self.state = "cancelled" if self.cancelled else "done"
        except BrokenProcessPool as exc:
            self._service._discard_pool()
            self.error = f"The calculation worker stopped unexpectedly ({exc})."
            self.state = "error"
        except Exception as exc:                  # noqa: BLE001 - reported to the user by the GUI
            self.error = str(exc)
            self.state = "error"
        finally:
            self.finished_at = time.perf_counter()

    def _materialise(self) -> None:
        d = self.data
        comps = list(d.compositions)
        n = len(comps)
        self.sources = list(d.sources) if not isinstance(d.sources, str) else [d.sources] * n
        self.names = list(d.names) if d.names else [""] * n
        self.variables = list(d.variables) if d.variables else [{}] * n
        self._comps = comps
        self.total = n

    def _emit(self, start: int, chunk: dict) -> bool:
        """Hand one chunk on (provenance attached) or count a delivered one; False if the writer
        could not take it."""
        n = chunk["n"]
        index = self.chunks_emitted
        if not chunk.get("delivered"):
            if "names" not in chunk:            # list jobs: the metadata lives in this job
                with_metadata(chunk, self.names[start:start + n], self.sources[start:start + n],
                              self.variables[start:start + n])
            if self.delivery is not None:
                if not self.delivery.put(index, chunk):
                    return False
            elif n:
                self.inbox.append((start, chunk))
        self.chunks_emitted = index + 1
        if n and self.first_result_at is None:
            self.first_result_at = time.perf_counter()
        self.done_count = start + n
        return True

    def _deliver_arg(self, index: int):
        d = self.delivery
        if d is not None and d.channel is not None and d.channel is self._service.channel:
            return d.run_id, index
        return None

    def _throttle(self, index: int) -> None:
        """Wait while the writer is more than ``MAX_AHEAD_CHUNKS`` behind (a slow disk)."""
        d = self.delivery
        if d is None:
            return
        while index - d.stored() > MAX_AHEAD_CHUNKS:
            if self.cancelled or d.failed():
                raise _Cancel
            time.sleep(0.01)

    def _run_inprocess(self) -> None:
        self.mode = "inprocess"
        engine = self.engine
        if engine is None:
            from .engine import default_engine
            engine = default_engine()
        d = self.data
        recipe = d.compositions if callable(d.compositions) else None
        if recipe is not None:
            m = recipe.materialise()
            comps, n = m["comps"], len(m["comps"])
            self.total = n
            if m.get("counts") is not None:            # expression: the generation facts the plan would give
                self.plan_counts = m["counts"]
            src = m["sources"]
            sources = [src] * n if isinstance(src, str) else list(src)
            design_all = m.get("design")
            k = (len(design_all) // n) if design_all is not None and n else 0
        else:
            self._materialise()
            comps, n = self._comps, self.total
        step = MIN_CHUNK
        for start in range(0, n, step):
            part = comps[start:start + step]
            if recipe is None:
                chunk = calculate_chunk(engine, part, d.options, self._cancel.is_set)
                chunk.pop("_results")
            elif recipe.kind == "recalc":
                sl = slice(start, start + step)
                dd = {"comps": part, "names": m["names"][sl], "sources": sources[sl], "blocks": m["blocks"][sl],
                      "design": design_all[start * k:(start + len(part)) * k] if k else None}
                chunk = calculate_recalc_chunk(engine, dd, d.options, self._cancel.is_set)
            else:
                sl = slice(start, start + step)
                envs = m["variables"][sl] if m["variables"] is not None else None
                blocks = m["blocks"][sl] if m["blocks"] is not None else None
                grid = m.get("grid")
                chunk = calculate_recipe_chunk(engine, recipe, part, m["names"][sl], envs, blocks, recipe.kind,
                                               d.options, self._cancel.is_set,
                                               design_rows=grid[sl] if grid is not None else None)
            if not self._emit(start, chunk) or chunk["cancelled"]:
                return
            if self.delivery is not None and self.delivery.failed():
                return

    def _wait(self, fut):
        while True:
            if self.cancelled:
                raise _Cancel
            try:
                return fut.result(timeout=0.05)
            except FutureTimeout:
                continue

    def _chunk_size(self, n: int) -> int:
        return max(MIN_CHUNK, min(MAX_CHUNK, n // (self._service.workers * 6) or MIN_CHUNK))

    def _run_pool_recipe(self, recipe) -> None:
        self.mode = "process"
        svc = self._service
        pool = svc.pool()
        key = (os.getpid(), self.id, time.perf_counter())
        options = self.data.options
        try:
            if recipe.kind == "expression":
                self._run_expression(pool, key, recipe, options)
                return
            if recipe.kind == "recalc":
                self.total = n = recipe.estimate()
                lo, hi = recipe.first_id, recipe.last_id
                size = self._chunk_size(n)
                tasks = ((lambda i, a=a: pool.submit(_recalc_chunk, key, recipe, a, min(a + size - 1, hi), options,
                                                     self._deliver_arg(i)))
                         for a in range(lo, hi + 1, size))
            else:
                # at.% / wt.%: exact DP, milliseconds; ratio / mass: a duplicate-aware walk - in a worker
                from .generation import SUM_UNITS, RangeError
                summed = recipe.unit in SUM_UNITS
                n = recipe.count() if summed else self._wait(pool.submit(_recipe_count, recipe))
                if not n:
                    raise RangeError("No valid compositions for these ranges"
                                     + (" (values must sum to 100 %)." if summed else "."))
                self.total = n
                size = self._chunk_size(n)
                tasks = ((lambda i, s=s: pool.submit(_sweep_chunk, key, recipe, s, min(s + size, n), options,
                                                     self._deliver_arg(i)))
                         for s in range(0, n, size))
            self._collect(tasks)
        except _Cancel:
            pass
        finally:
            self._release(pool, key)

    def _release(self, pool, key) -> None:
        try:
            for _ in range(self._service.workers):
                pool.submit(_release, key)
        except Exception:                          # noqa: BLE001 - pool shutting down
            pass

    def _run_expression(self, pool, key, recipe, options) -> None:
        block = PLAN_BLOCK
        path = os.path.join(self._service.scratch_dir, f"plan-{os.getpid()}-{self.id}-{int(time.time() * 1000)}.bin")
        combos = recipe.estimate()
        self.total = combos                                    # upper bound until the plan is complete
        ranges = -(-combos // block)
        plan = pool.submit(_expression_plan, recipe, path, block)
        state = {"next": 0}

        def available() -> int:
            if plan.done():
                return ranges
            try:
                return os.path.getsize(path) // (block // 8)
            except OSError:
                return 0

        def tasks():
            while state["next"] < ranges:
                if self.cancelled:
                    return
                if state["next"] < available():
                    k = state["next"]
                    state["next"] += 1
                    yield lambda i, k=k: pool.submit(_expression_chunk, key, recipe, path, k, block, options,
                                                     self._deliver_arg(i))
                elif plan.done():
                    exc = plan.exception()
                    if exc is not None:
                        raise exc
                else:
                    yield None                                # nothing ready yet: let the window drain
        try:
            self._collect(tasks(), on_idle=lambda: self._plan_done(plan))
            self._plan_done(plan)
        finally:
            try:
                plan.result(timeout=30)
            except Exception:                             # noqa: BLE001 - cancelled / failed plan
                pass
            try:
                os.remove(path)
            except OSError:
                pass

    def _plan_done(self, plan) -> None:
        if plan.done() and plan.exception() is None and self.plan_counts is None:
            self.plan_counts = plan.result()
            self.total = self.plan_counts[0]

    def _run_pool(self, comps: list[dict]) -> None:
        self.mode = "process"
        pool = self._service.pool()
        n = len(comps)
        size = self._chunk_size(n)
        options = self.data.options

        def task(i, s):
            meta = (self.names[s:s + size], self.sources[s:s + size], self.variables[s:s + size])
            return pool.submit(_calculate_chunk, comps[s:s + size], options, meta, self._deliver_arg(i))
        self._collect((lambda i, s=s: task(i, s)) for s in range(0, n, size))

    def _collect(self, tasks, on_idle: Callable[[], None] | None = None) -> None:
        """Run ``tasks`` (callables submitting one chunk; ``None`` = nothing ready yet) with at most
        ``WINDOW_PER_WORKER × workers`` in flight, emitting results in order."""
        event = self._service.cancel_event
        window: deque = deque()
        limit = WINDOW_PER_WORKER * self._service.workers
        tasks = iter(tasks)
        exhausted = False
        start = 0
        submitted = 0
        try:
            while True:
                while not exhausted and len(window) < limit:
                    t = next(tasks, StopIteration)
                    if t is StopIteration:
                        exhausted = True
                    elif t is None:
                        break
                    else:
                        self._throttle(submitted)
                        window.append(t(submitted))
                        submitted += 1
                if not window:
                    if exhausted:
                        return
                    if self.cancelled:
                        raise _Cancel
                    if on_idle is not None:
                        on_idle()
                    time.sleep(0.02)
                    continue
                if self.delivery is not None and self.delivery.failed():
                    raise _Cancel
                chunk = self._wait(window[0])
                window.popleft()
                if not self._emit(start, chunk):
                    raise _Cancel
                start += chunk["n"]
                if chunk.get("cancelled"):
                    raise _Cancel
        except _Cancel:
            event.set()
            for f in window:
                f.cancel()
            for f in window:                       # running chunks stop at their next alloy
                try:
                    f.result(timeout=10)
                except (CancelledError, FutureTimeout, Exception):  # noqa: BLE001
                    pass
            event.clear()
            if not self.cancelled:
                self.cancel()                      # the sink refused a chunk (writer failure)


class _Cancel(Exception):
    pass
