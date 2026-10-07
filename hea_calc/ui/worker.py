"""Qt side of calculation jobs (see ``core/jobs.py``) and of background pre-flight counts.

* :class:`JobRunner` polls a running :class:`~hea_calc.core.jobs.CalculationJob` on a 100 ms timer
  (10 Hz): it moves finished chunks from the job's inbox into the results model within a small
  time budget and emits ``progress`` once per tick - never once per alloy.
* :class:`BackgroundTask` runs a short pure-Python function (a pre-flight count) on a daemon thread;
  only the latest request's answer is delivered, so typing never waits for a stale count.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.jobs import CalculationJob, CalculationService

TICK_MS = 100            # GUI ingestion / progress rate (10 Hz)
INGEST_BUDGET_S = 0.030  # GUI-thread time per tick spent appending chunks
RESORT_INTERVAL_S = 1.5  # an active sort is re-applied at most this often while rows stream in


class JobRunner(QObject):
    progress = Signal(int, int, float)   # done, total, eta seconds
    finished = Signal(object)            # the CalculationJob

    def __init__(self, service: CalculationService, model, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = model
        self.job: CalculationJob | None = None
        self.first_id: int | None = None
        self.added = 0
        self.ticks = 0
        self.ingest_seconds = 0.0           # GUI-thread time spent ingesting (measured by tools/perf_harness)
        self.max_tick_seconds = 0.0
        self._last_resort = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def running(self) -> bool:
        return self.job is not None

    def start(self, job: CalculationJob) -> CalculationJob:
        self.job = job
        self.first_id = None
        self.added = 0
        self.ticks = 0
        self.ingest_seconds = 0.0
        self.max_tick_seconds = 0.0
        self._last_resort = time.perf_counter()
        self.service.start(job)
        self._timer.start()
        return job

    def cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()

    def _tick(self) -> None:
        job = self.job
        if job is None:
            self._timer.stop()
            return
        self.ticks += 1
        t0 = time.perf_counter()
        ids = []
        while job.inbox and time.perf_counter() - t0 < INGEST_BUDGET_S:
            start, chunk = job.inbox.popleft()
            n = chunk["n"]
            if "names" in chunk:          # recipe jobs: generated in the worker, metadata travels with results
                names, sources, envs = chunk["names"], chunk["sources"], chunk["variables"]
            else:
                names, sources, envs = (job.names[start:start + n], job.sources[start:start + n],
                                        job.variables[start:start + n])
            rng = self.model.store.append_chunk(chunk, names, sources, envs, job.data.options)
            if self.first_id is None:
                self.first_id = rng.start
            ids.append(rng)
            self.added += n
        if ids:
            self.model.rows_appended(range(ids[0].start, ids[-1].stop))
            if self.model.sort_dirty and time.perf_counter() - self._last_resort > RESORT_INTERVAL_S:
                self.model.resort()
                self._last_resort = time.perf_counter()
        dt = time.perf_counter() - t0
        self.ingest_seconds += dt
        self.max_tick_seconds = max(self.max_tick_seconds, dt)
        if job.total:
            self.progress.emit(self.added, job.total, job.eta())
        if job.finished and not job.inbox:
            self._timer.stop()
            if self.model.sort_dirty:
                self.model.resort()
            self.job = None
            self.finished.emit(job)


class BackgroundTask(QObject):
    """Latest-wins background computation; ``done(value)`` / ``failed(exc)`` on the GUI thread.

    * ``run(fn, *args)`` - a *light* function on a daemon thread, called with ``cancelled=`` (a
      callable that turns true once a newer request supersedes this one).  Only for work of a few
      milliseconds: any CPU-bound Python thread in this process competes with the GUI thread for
      the GIL.
    * ``run_heavy(fn, *args)`` - a picklable function in a calculation worker *process* (a
      100 000-combination expression preview, a large ratio-space walk); the thread here only waits.
    """

    done = Signal(object)
    failed = Signal(object)
    _deliver = Signal(int, object, object)

    def __init__(self, parent=None, service: CalculationService | None = None):
        super().__init__(parent)
        self.service = service
        self._token = 0
        self._deliver.connect(self._on_deliver)
        self.busy = False

    def run(self, fn, *args) -> int:
        return self._start(lambda stale: fn(*args, cancelled=stale))

    def run_heavy(self, fn, *args) -> int:
        if self.service is None or self.service.workers <= 1:
            return self._start(lambda stale: fn(*args))
        svc = self.service
        return self._start(lambda stale: svc.pool().submit(fn, *args).result())

    def _start(self, call) -> int:
        self._token += 1
        token = self._token
        self.busy = True
        stale = lambda: token != self._token        # noqa: E731

        def work():
            try:
                value, exc = call(stale), None
            except Exception as e:                  # noqa: BLE001 - delivered to the GUI
                value, exc = None, e
            if not stale():
                self._deliver.emit(token, value, exc)

        threading.Thread(target=work, name="hea-preflight", daemon=True).start()
        return token

    def cancel(self) -> None:
        self._token += 1
        self.busy = False

    def _on_deliver(self, token: int, value, exc) -> None:
        if token != self._token:
            return
        self.busy = False
        if exc is not None:
            self.failed.emit(exc)
        else:
            self.done.emit(value)
