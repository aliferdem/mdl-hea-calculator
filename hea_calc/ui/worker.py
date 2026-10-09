"""Qt side of calculation jobs (see ``core/jobs.py``), background exports and pre-flight counts.

* :class:`JobRunner` runs one :class:`~hea_calc.core.jobs.CalculationJob` into one repository
  run.  Chunks go from the calculation workers straight to the repository's writer process (never
  through the GUI process); a 100 ms timer (10 Hz) only reads the committed frontier from shared
  memory, lets the table view pick up committed rows (one page query at most) and emits
  ``progress`` - never anything per alloy.  When the job ends the run is finalised by the writer
  (exactly the chunks the job handed on), then ``finished``.
* :class:`ExportTask` streams a large export / clipboard table in a separate process that reads a
  snapshot of the database; progress is polled at 10 Hz and Cancel is honoured within a chunk.
* :class:`BackgroundTask` runs a short pure-Python function (a pre-flight count) on a daemon thread;
  only the latest request's answer is delivered, so typing never waits for a stale count.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.jobs import CalculationJob, CalculationService, Delivery

TICK_MS = 100            # GUI ingestion / progress rate (10 Hz)


class JobRunner(QObject):
    progress = Signal(int, int, float)   # calculated, total, eta seconds
    finished = Signal(object)            # the CalculationJob

    def __init__(self, service: CalculationService, model, parent=None):
        super().__init__(parent)
        self.service = service
        self.model = model
        self.job: CalculationJob | None = None
        self.run_id: int | None = None
        self.first_id: int | None = None
        self.added = 0
        self.ticks = 0
        self.ingest_seconds = 0.0           # GUI-thread time per tick (measured by tools/perf_harness)
        self.max_tick_seconds = 0.0
        self.storage_error: str | None = None
        self._finalizing = None
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def repo(self):
        return self.model.repo

    @property
    def running(self) -> bool:
        return self.job is not None

    def start(self, job: CalculationJob, run_id: int) -> CalculationJob:
        self.job = job
        self.run_id = run_id
        self.first_id = None
        self.added = 0
        self.ticks = 0
        self.ingest_seconds = 0.0
        self.max_tick_seconds = 0.0
        self.storage_error = None
        self._finalizing = None
        w = self.repo.writer
        job.delivery = Delivery(run_id, lambda i, ch: w.put_chunk(run_id, i, ch), lambda: w.stored_chunks(run_id),
                                lambda: bool(w.error), w.inbox)
        self.service.start(job)
        self._timer.start()
        return job

    def cancel(self) -> None:
        if self.job is not None:
            self.job.cancel()
            self._timer.setInterval(20)      # report the cancelled state promptly

    def _tick(self) -> None:
        job = self.job
        if job is None:
            self._timer.stop()
            return
        self.ticks += 1
        t0 = time.perf_counter()
        repo = self.repo
        if repo.writer.error and self.storage_error is None:
            self.storage_error = repo.writer.error           # disk full, I/O error, ...: stop calculating
            job.cancel()
        self.model.refresh_committed(resort=False)
        if self.model.view.wants_resort(running=True):
            self.model.resort(wait=0)
        self.added = repo.writer.committed_count(self.run_id)
        if job.total:
            self.progress.emit(job.done_count, job.total, job.eta())
        if job.finished and self._finalizing is None:
            status = {"done": "complete", "cancelled": "cancelled", "error": "failed"}[job.state]
            if self.storage_error:
                status = "failed"
            self._finalizing = repo.finalize_run(self.run_id, status, job.error or self.storage_error, wait=False,
                                                 upto=job.chunks_emitted)
        dt = time.perf_counter() - t0
        self.ingest_seconds += dt
        self.max_tick_seconds = max(self.max_tick_seconds, dt)
        if self._finalizing is not None and self._finalizing.done():
            self._timer.stop()
            self._timer.setInterval(TICK_MS)
            self.model.refresh_committed()
            if self.model.view.stale:
                self.model.resort()
            info = repo.get_run(self.run_id)
            self.added = info.calculated if info else self.added
            self.first_id = info.first_id if info else None
            self.job = None
            self.finished.emit(job)


class ExportTask(QObject):
    """A streamed export (or clipboard table) in its own process; ``finished(status, value)`` with
    status ok / cancelled / error."""

    progress = Signal(int)
    finished = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ctx = mp.get_context("spawn")
        self._proc = None
        self._cancel = None
        self._value = None
        self._results = None
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def running(self) -> bool:
        return self._proc is not None

    def start(self, spec: dict, path: str, kind: str, payload: dict) -> None:
        from ..core.export import export_process_main
        self._cancel = self._ctx.Event()
        self._value = self._ctx.Value("q", 0)
        self._results = self._ctx.Queue()
        self._proc = self._ctx.Process(target=export_process_main, name="hea-export",
                                       args=(spec, path, kind, payload, self._value, self._cancel, self._results),
                                       daemon=True)
        self._proc.start()
        self._timer.start()

    def cancel(self) -> None:
        if self._cancel is not None:
            self._cancel.set()

    def _tick(self) -> None:
        p = self._proc
        if p is None:
            self._timer.stop()
            return
        self.progress.emit(int(self._value.value))
        try:
            status, value = self._results.get_nowait()
        except queue.Empty:
            if p.is_alive():
                return
            status, value = "error", "The export process stopped unexpectedly."
        self._timer.stop()
        p.join(5)
        self._proc = None
        self.finished.emit(status, value)

    def shutdown(self, timeout: float = 3.0) -> None:
        p = self._proc
        if p is None:
            return
        self.cancel()
        p.join(timeout)
        if p.is_alive():
            p.terminate()
            p.join(1)
        self._timer.stop()
        self._proc = None


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
