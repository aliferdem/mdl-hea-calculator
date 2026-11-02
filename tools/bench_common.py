"""Shared parts of the benchmarks in ``tools/bench_*.py`` (developer utilities, not used by the application).

* :func:`environment` - application version, engine fingerprint, Python, platform and CPU count, recorded with
  every result so measurements from different versions are not compared by mistake;
* :func:`parse_sizes` / :func:`check_sizes` - ``10k,1m`` style workload sizes; sizes above :data:`LARGE` are refused
  unless ``--allow-large`` is given, so a million-composition run is always an explicit choice;
* :func:`pipeline` / :func:`run_recipe` - the application's real calculation path without the window: the worker
  pool (:class:`~hea_calc.core.jobs.CalculationService`), the single writer process and the SQLite repository,
  with the job delivered exactly as ``hea_calc/ui/worker.py`` delivers it;
* :func:`process_peaks` - peak memory of this process, the writer process and every worker process;
* :func:`emit` - one JSON line per measurement on stdout and, with ``--out``, one JSON file.

Synthetic result sets come from ``tests/_support.py`` (engine results of 50 alloys replicated, labelled ``SYN...``):
they measure storage and queries, never the scientific models.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LARGE = 1_000_000          # sizes above this need --allow-large


def parse_size(s: str) -> int:
    s = s.strip().lower()
    mult = 1_000_000 if s.endswith("m") else 1_000 if s.endswith("k") else 1
    return int(float(s.rstrip("mk")) * mult)


def parse_sizes(text: str) -> list[int]:
    return [parse_size(s) for s in text.split(",") if s.strip()]


def check_sizes(sizes: list[int], allow_large: bool) -> None:
    big = [n for n in sizes if n > LARGE]
    if big and not allow_large:
        sys.exit(f"Workloads above {LARGE:,} ({', '.join(f'{n:,}' for n in big)}) need --allow-large.")


def add_common_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--out", default="", help="write all results to this JSON file")
    ap.add_argument("--quick", action="store_true", help="tiny workloads (smoke test, a few seconds)")
    ap.add_argument("--allow-large", action="store_true", help=f"allow workloads above {LARGE:,}")


def environment() -> dict:
    from hea_calc import __version__
    from hea_calc.core.provenance import engine_version
    return {"app_version": __version__, "engine_version": engine_version(), "python": platform.python_version(),
            "platform": platform.platform(), "cpu_count": os.cpu_count(),
            "time": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ---------------------------------------------------------------------- memory
def peak_mib(pid: int | None = None) -> float | None:
    """Peak working set (Windows) or peak resident set (this process on POSIX) in MiB; None when unknown."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        from _support import _pmc
        k32 = ctypes.windll.kernel32
        if pid is None:
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            pmc = _pmc(k32.GetCurrentProcess())
        else:
            k32.OpenProcess.restype = wintypes.HANDLE
            h = k32.OpenProcess(0x1000 | 0x0010, False, pid)          # QUERY_LIMITED_INFORMATION | VM_READ
            if not h:
                return None
            try:
                pmc = _pmc(h)
            finally:
                k32.CloseHandle(h)
        return round(pmc.PeakWorkingSetSize / 2**20, 1) if pmc else None
    if pid is not None:
        return None
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (2**20 if sys.platform == "darwin" else 2**10), 1)


def process_peaks(svc=None, repo=None) -> dict:
    """Lifetime peaks: they include every earlier workload of the same process."""
    out = {"main_mib": peak_mib()}
    proc = getattr(getattr(repo, "writer", None), "_proc", None)
    if proc is not None and proc.pid:
        out["writer_mib"] = peak_mib(proc.pid)
    if svc is not None:
        out["workers_mib"] = [peak_mib(p) for p in svc.worker_pids()]
    return out


# ---------------------------------------------------------------------- calculation pipeline
@contextlib.contextmanager
def pipeline(workers: int | None = None, repo=None):
    """``(engine, repo, svc)``: a warmed worker pool feeding a repository (a new temporary one unless given)."""
    from hea_calc.core.engine import default_engine
    from hea_calc.core.jobs import CalculationService
    from hea_calc.core.repository import ResultRepository
    engine = default_engine()
    own = repo is None
    if own:
        repo = ResultRepository(engine, root=Path(tempfile.mkdtemp()) / "sessions")
    svc = CalculationService(workers=workers, channel=repo.writer.inbox)
    svc.warm_up().join()
    try:
        yield engine, repo, svc
    finally:
        svc.shutdown()
        if own:
            repo.close()


def run_recipe(svc, repo, engine, recipe) -> dict:
    """Calculate ``recipe`` and store it; times to the first chunk, to the last calculation and to the last commit."""
    from hea_calc.core.jobs import CalculationJob, Delivery, JobInput
    meta = recipe.run_meta()
    run_id = repo.create_run(meta["mode"], source=meta["source"], axes=meta["axes"], elements=meta["elements"])
    w = repo.writer
    if svc.channel is None:
        svc.channel = w.inbox
    delivery = Delivery(run_id, lambda i, ch: w.put_chunk(run_id, i, ch), lambda: w.stored_chunks(run_id),
                        lambda: bool(w.error), w.inbox)
    job = CalculationJob(JobInput(meta["mode"], (), recipe, (), {}), engine, delivery)
    t0 = time.perf_counter()
    svc.start(job)
    first = None
    while not job.finished:
        if first is None and job.done_count > 0:
            first = time.perf_counter() - t0
        time.sleep(0.002)
    calc_s = time.perf_counter() - t0
    if job.state != "done":
        raise RuntimeError(f"calculation {job.state}: {job.error}")
    repo.finalize_run(run_id, "complete", upto=job.chunks_emitted)
    t1 = time.perf_counter()
    while repo.committed_last < (repo.get_run(run_id).last_id or 0) and time.perf_counter() - t1 < 600:
        time.sleep(0.005)
    stored_s = time.perf_counter() - t0
    info = repo.get_run(run_id)
    n = (info.last_id - info.first_id + 1) if info.first_id is not None else 0
    return {"run": run_id, "rows": n, "first_chunk_s": round(first or calc_s, 3), "calc_s": round(calc_s, 3),
            "stored_s": round(stored_s, 3), "rows_per_s": round(n / stored_s) if stored_s else 0,
            "plan_counts": list(job.plan_counts) if getattr(job, "plan_counts", None) else None}


# ---------------------------------------------------------------------- output
class Report:
    def __init__(self, name: str, args):
        self.data = {"benchmark": name, "environment": environment(), "arguments": vars(args), "results": []}
        self.out = args.out
        print(json.dumps({"benchmark": name, **self.data["environment"]}), flush=True)

    def emit(self, record: dict) -> dict:
        self.data["results"].append(record)
        print(json.dumps(record), flush=True)
        return record

    def close(self) -> None:
        if self.out:
            Path(self.out).parent.mkdir(parents=True, exist_ok=True)
            Path(self.out).write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            print("wrote", self.out, flush=True)
