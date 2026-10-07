"""Calculation jobs: CPU-bound engine work outside the GUI process (no Qt here).

Measured: one alloy costs ~0.5 ms of pure-Python engine work, so 100 000 alloys are ~55 s of CPU.
In a QThread that work holds the GIL and starves Qt's event loop, so batches of real size run in a
persistent pool of worker *processes* (``ProcessPoolExecutor``, ``spawn`` start method - the only
one on Windows - created once and reused):

* each worker builds its own :class:`~hea_calc.core.engine.Engine` once (pool initializer);
* compositions are sent in chunks of a few hundred, and results come back as columnar
  :func:`~hea_calc.core.store.pack_results` chunks - never one message per alloy;
* a coordinating thread in the GUI process (:class:`CalculationJob`) materialises the job's
  compositions (sweep / expression generation happens here, not on the GUI thread), submits the
  chunks, collects them *in order* and appends them to ``job.inbox``; the GUI drains the inbox on a
  timer (see ``ui/worker.py``), so the Qt event queue never sees per-alloy traffic;
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
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field

from .store import pack_results

INPROCESS_MAX = 300
MAX_CHUNK = 500
MIN_CHUNK = 50

# ---------------------------------------------------------------------- worker process side
_ENGINE = None
_CANCEL = None


def _init_worker(cancel_event) -> None:                       # pragma: no cover - runs in a child
    global _ENGINE, _CANCEL
    _watch_parent()
    from .engine import default_engine
    _ENGINE = default_engine()
    _CANCEL = cancel_event


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


def _calculate_chunk(compositions: list[dict], options: dict) -> dict:   # pragma: no cover - child
    return calculate_chunk(_ENGINE, compositions, options, _CANCEL.is_set)


# A recipe job is generated inside each worker, once per job (see core/recipes.py); only the latest
# job's batch is kept so a worker never holds more than one generated list.
_GENERATED: dict = {}


def _generated(key, recipe):                                 # pragma: no cover - runs in a child
    g = _GENERATED.get(key)
    if g is None:
        _GENERATED.clear()
        sources, names, comps, envs = recipe()
        n = len(comps)
        g = _GENERATED[key] = ([sources] * n if isinstance(sources, str) else list(sources),
                               list(names), list(comps), list(envs) if envs else [{}] * n)
    return g


def _recipe_size(key, recipe) -> int:                        # pragma: no cover - runs in a child
    return len(_generated(key, recipe)[2])


def _calculate_recipe_chunk(key, recipe, start: int, stop: int, options: dict) -> dict:  # pragma: no cover
    sources, names, comps, envs = _generated(key, recipe)
    chunk = calculate_chunk(_ENGINE, comps[start:stop], options, _CANCEL.is_set)
    n = chunk["n"]
    chunk["sources"], chunk["names"], chunk["variables"] = sources[start:start + n], names[start:start + n], \
        envs[start:start + n]
    return chunk


def run_in_worker(service: "CalculationService", fn, *args):
    """Run a picklable ``fn(*args)`` in the worker pool (heavy pre-flight counts); a Future."""
    return service.pool().submit(fn, *args)


def calculate_chunk(engine, compositions: Sequence[dict], options: dict,
                    cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Evaluate compositions with ``engine`` (stops early when ``cancelled()``); a packed chunk."""
    done_comps, results = [], []
    for comp in compositions:
        if cancelled():
            break
        results.append(engine.calculate(comp, **options))
        done_comps.append(comp)
    return pack_results(done_comps, results)


# ---------------------------------------------------------------------- pool service
def default_workers() -> int:
    return max(1, min((os.cpu_count() or 2) - 1, 8))


class CalculationService:
    """Owns the persistent worker pool (created lazily, off the GUI thread) and the cancel event."""

    def __init__(self, workers: int | None = None, inprocess_max: int = INPROCESS_MAX):
        self.workers = workers or default_workers()
        self.inprocess_max = inprocess_max
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
                                                 initargs=(self._cancel,))
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
class JobInput:
    """What a job calculates.  ``compositions`` may be a callable (lazy generation in the job thread)
    returning ``(sources, names, compositions, variables)``."""
    sources: Sequence[str] | str = "sweep"
    names: Sequence[str] = ()
    compositions: Sequence[dict] | Callable = ()
    variables: Sequence[dict] = ()
    options: dict = field(default_factory=dict)


class CalculationJob:
    """One calculation request (see module docstring).

    States: ``running`` → ``done`` | ``cancelled`` | ``error``.  ``inbox`` receives
    ``(start_index, chunk)`` tuples in composition order; ``names``/``sources``/``variables`` hold the
    per-composition metadata once generation has finished (``total`` is then known).
    """

    def __init__(self, data: JobInput, engine=None):
        self.data = data
        self.engine = engine                 # for in-process (small) jobs
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
        self.finished_at: float | None = None
        self.cancel_requested_at: float | None = None
        self.mode = "inprocess"
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
        return elapsed / self.done_count * (self.total - self.done_count)

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
                self._materialise()
                if not self.cancelled:
                    self._run_inprocess(self._comps)
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
        if callable(d.compositions):
            sources, names, comps, envs = d.compositions()
        else:
            sources, names, comps, envs = d.sources, d.names, d.compositions, d.variables
        comps = list(comps)
        n = len(comps)
        self.sources = list(sources) if not isinstance(sources, str) else [sources] * n
        self.names = list(names) if names else [""] * n
        self.variables = list(envs) if envs else [{}] * n
        self._comps = comps
        self.total = n

    def _emit(self, start: int, chunk: dict) -> None:
        if chunk["n"]:
            self.inbox.append((start, chunk))
            self.done_count = start + chunk["n"]

    def _run_inprocess(self, comps: list[dict]) -> None:
        self.mode = "inprocess"
        engine = self.engine
        if engine is None:
            from .engine import default_engine
            engine = default_engine()
        step = MIN_CHUNK
        for start in range(0, len(comps), step):
            chunk = calculate_chunk(engine, comps[start:start + step], self.data.options, self._cancel.is_set)
            self._emit(start, chunk)
            if chunk["n"] < len(comps[start:start + step]):
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
        try:
            n = self._wait(pool.submit(_recipe_size, key, recipe))
        except _Cancel:
            return
        self.total = n
        size = self._chunk_size(n)
        starts = list(range(0, n, size))
        futures = [pool.submit(_calculate_recipe_chunk, key, recipe, s, min(s + size, n), self.data.options)
                   for s in starts]
        self._collect(starts, [min(s + size, n) - s for s in starts], futures)

    def _run_pool(self, comps: list[dict]) -> None:
        self.mode = "process"
        svc = self._service
        pool = svc.pool()
        n = len(comps)
        size = self._chunk_size(n)
        starts = list(range(0, n, size))
        futures = [pool.submit(_calculate_chunk, comps[s:s + size], self.data.options) for s in starts]
        self._collect(starts, [len(comps[s:s + size]) for s in starts], futures)

    def _collect(self, starts, sizes, futures) -> None:
        event = self._service.cancel_event
        try:
            for s, k, fut in zip(starts, sizes, futures):
                chunk = self._wait(fut)
                self._emit(s, chunk)
                if chunk["n"] < k:
                    raise _Cancel
        except _Cancel:
            event.set()
            for f in futures:
                f.cancel()
            for f in futures:                      # running chunks stop at their next alloy
                try:
                    f.result(timeout=10)
                except (CancelledError, FutureTimeout, Exception):  # noqa: BLE001
                    pass
            event.clear()


class _Cancel(Exception):
    pass
