"""Batch calculation benchmark: generation, the eight models, worker scaling, storage and memory (no window).

    uv run tools/bench_batch.py [--parts generation,engine,pipeline,workers,storage] [--sizes 10k,50k]
        [--workers-list 1,2,4] [--scaling-size 20k] [--engine-n 2000] [--storage-sizes 100k]
        [--quick] [--allow-large] [--out bench_batch.json]

Workload: a Composition space in atomic ratio with Fe, Co and Ni locked at 1 and Al and Cr varied on the same grid
(0.01, 0.02, ...), so every composition is distinct (no proportional duplicates) and the size is k² for k values
per element (the size asked for is rounded up to the next square).  The workload is deterministic.

Parts:

* ``generation`` - the exact count (``SweepRecipe.count``) and enumeration of the space (``iter_space``) in one
  process, without calculation: compositions per second;
* ``engine`` - ``Engine.calculate`` (descriptors and the eight models M1-M8) for the first ``--engine-n``
  compositions in this process: calculations per second;
* ``pipeline`` - the whole Calculate path for each of ``--sizes`` with the default worker count: generation and
  calculation in the worker processes, storage by the single writer into SQLite; time to the first stored chunk,
  rows per second, database size and peak memory of every process;
* ``workers`` - the pipeline at ``--scaling-size`` for each worker count in ``--workers-list`` (one worker
  calculates in-process, as the application does), with the speed-up relative to the first entry;
* ``storage`` - synthetic result chunks (``tests/_support.py``) submitted to the writer: SQLite insertion rate and
  bytes per stored row, independent of calculation speed.

Sizes above 1,000,000 need ``--allow-large``.  Results: one JSON line per measurement on stdout, and ``--out``.
"""

from __future__ import annotations

import argparse
import gc
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import (Report, add_common_arguments, check_sizes, parse_sizes, pipeline,  # noqa: E402
                          process_peaks, run_recipe)

LOCKED = ("Fe", "Co", "Ni")
VARIED = ("Al", "Cr")
STEP = 0.01


def space_recipe(n: int):
    """The deterministic Composition space of at least ``n`` compositions (k² for k = ceil(sqrt(n)))."""
    from hea_calc.core.generation import SweepSpec
    from hea_calc.core.recipes import SweepRecipe
    k = max(1, math.ceil(math.sqrt(n)))
    specs = [SweepSpec(el, 1.0, 1.0, 0.1, True) for el in LOCKED]
    specs += [SweepSpec(el, STEP, round(k * STEP, 6), STEP, True) for el in VARIED]
    return SweepRecipe(tuple(specs), "ratio", None)


def part_generation(rep: Report, sizes: list[int]) -> None:
    from hea_calc.core.generation import iter_space
    for n in sizes:
        recipe = space_recipe(n)
        t0 = time.perf_counter()
        count = recipe.count()
        count_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        produced = sum(1 for _ in iter_space(list(recipe.specs), recipe.unit))
        gen_s = time.perf_counter() - t0
        rep.emit({"part": "generation", "size": count, "count_s": round(count_s, 4), "enumerate_s": round(gen_s, 3),
                  "compositions_per_s": round(produced / gen_s) if gen_s else None, "enumerated": produced})


def part_engine(rep: Report, n: int) -> None:
    from hea_calc.core.engine import default_engine
    from hea_calc.core.generation import iter_space
    engine = default_engine()
    recipe = space_recipe(n)
    comps = []
    for c in iter_space(list(recipe.specs), recipe.unit):
        comps.append(c)
        if len(comps) >= n:
            break
    engine.calculate(comps[0])                      # data loading and caches outside the timing
    t0 = time.perf_counter()
    results = [engine.calculate(c) for c in comps]
    dt = time.perf_counter() - t0
    rep.emit({"part": "engine", "compositions": len(comps), "seconds": round(dt, 3),
              "calculations_per_s": round(len(comps) / dt) if dt else None,
              "us_per_composition": round(1e6 * dt / len(comps), 1), "results": len(results),
              "peak": process_peaks()})


def part_pipeline(rep: Report, sizes: list[int], workers: int | None) -> None:
    with pipeline(workers) as (engine, repo, svc):
        run_recipe(svc, repo, engine, space_recipe(200))        # warm both processes and the engine caches
        for n in sizes:
            gc.collect()
            r = run_recipe(svc, repo, engine, space_recipe(n))
            rep.emit({"part": "pipeline", "workers": svc.workers, "size": r["rows"], **r,
                      "db_mib": round(sum(repo.size_bytes().values()) / 2**20, 1),
                      "peak": process_peaks(svc, repo)})


def part_workers(rep: Report, size: int, counts: list[int]) -> None:
    base = None
    for w in counts:
        with pipeline(w) as (engine, repo, svc):
            run_recipe(svc, repo, engine, space_recipe(200))
            r = run_recipe(svc, repo, engine, space_recipe(size))
            base = base or r["rows_per_s"]
            rep.emit({"part": "workers", "workers": w, "path": "in-process" if w <= 1 else "worker pool",
                      "size": r["rows"], "stored_s": r["stored_s"], "rows_per_s": r["rows_per_s"],
                      "speedup": round(r["rows_per_s"] / base, 2) if base else None,
                      "peak": process_peaks(svc, repo)})


def part_storage(rep: Report, sizes: list[int]) -> None:
    import tempfile

    from _support import synthetic_chunk
    from hea_calc.core.engine import default_engine
    from hea_calc.core.repository import ResultRepository
    engine = default_engine()
    variants = [synthetic_chunk(engine, 500, i * 500) for i in range(20)]
    for n in sizes:
        repo = ResultRepository(engine, root=Path(tempfile.mkdtemp()) / "sessions")
        try:
            run = repo.create_run("sweep", settings={}, elements=["Fe", "Co", "Ni", "Cr", "Mn"],
                                  source={"synthetic": True})
            chunks = max(1, round(n / 500))
            gc.collect()
            t0 = time.perf_counter()
            for i in range(chunks):
                repo.submit_chunk(run, dict(variants[i % len(variants)]))
            repo.writer.flush(timeout=7200)
            dt = time.perf_counter() - t0
            rows = chunks * 500
            size = sum(repo.size_bytes().values())
            rep.emit({"part": "storage", "rows": rows, "insert_s": round(dt, 3),
                      "rows_per_s": round(rows / dt) if dt else None, "db_mib": round(size / 2**20, 1),
                      "bytes_per_row": round(size / rows), "peak": process_peaks(None, repo),
                      "data": "synthetic (engine results of 50 alloys replicated)"})
        finally:
            repo.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--parts", default="generation,engine,pipeline,workers,storage")
    ap.add_argument("--sizes", default="10k,50k", help="generation and pipeline sizes")
    ap.add_argument("--workers", type=int, default=None, help="worker count of the pipeline part (default: app's)")
    ap.add_argument("--workers-list", default="", help="worker counts of the scaling part (default 1,2,4,... CPUs)")
    ap.add_argument("--scaling-size", default="20k")
    ap.add_argument("--engine-n", type=int, default=2000)
    ap.add_argument("--storage-sizes", default="100k")
    add_common_arguments(ap)
    args = ap.parse_args()
    if args.quick:
        args.sizes, args.scaling_size, args.engine_n, args.storage_sizes = "1k", "1k", 100, "2k"
        args.workers_list = args.workers_list or "1,2"
    sizes, storage = parse_sizes(args.sizes), parse_sizes(args.storage_sizes)
    scaling = parse_sizes(args.scaling_size)[0]
    check_sizes(sizes + storage + [scaling], args.allow_large)
    cpus = os.cpu_count() or 2
    counts = [int(w) for w in args.workers_list.split(",") if w.strip()] or \
        sorted({1, 2, 4, 8, max(1, min(cpus - 1, 8))} & set(range(1, cpus + 1)))
    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    rep = Report("bench_batch", args)
    try:
        if "generation" in parts:
            part_generation(rep, sizes)
        if "engine" in parts:
            part_engine(rep, args.engine_n)
        if "pipeline" in parts:
            part_pipeline(rep, sizes, args.workers)
        if "workers" in parts:
            part_workers(rep, scaling, counts)
        if "storage" in parts:
            part_storage(rep, storage)
    finally:
        rep.close()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()          # worker processes re-import this file as __mp_main__
    main()
