"""Batch-size tiers, run estimates and capacity checks - every number measured, none guessed.

The former 200 000-composition guard protected the in-memory result store; with results on disk
(``core/repository.py``) the count affects calculation time and disk use, not the interface.
Measurements (``design/implementation/performance.md``, dev box: 12 logical CPUs, 8 workers):

* real engine, 5-element at.% sweeps: ≈ 2 250 alloys/s per worker (18 900/s with 8 workers;
  1 039 776 alloys in 55 s, stored as they come), event-loop gaps typically 80-90 ms (one 147 ms gap
  at a scripted window resize in the final 1 M run);
* storage: ≈ 420-480 bytes per result on disk (results + design coordinates + WAL);
* interaction (synthetic rows, real writer path): page change, Details, row removal and memory are
  flat from 100 k to 10 M rows;
  a full-dataset sort or filter is materialised in the background at ≈ 1 s per million rows
  (0.17 s at 100 k, 1.3 s at 1 M, 9.8 s at 10 M).

Tiers:

* ``normal`` - below ``LARGE``: sorts/filters finish in well under a second;
* ``large`` - from ``LARGE`` (≈ 15 s of calculation, ≈ 120 MB on disk, sorts ≈ 0.3 s);
* ``very_large`` - from ``VERY_LARGE``: more than one Excel worksheet (1 048 575 rows), ≈ 1 min of
  calculation, ≈ 0.4 GB, sorts ≥ 1 s - results are stored and processed in the background.

Hard limit: ``HARD_LIMIT`` = 10 000 000 - the largest *repository/storage* size validated, with
SYNTHETIC rows inserted through the real writer path (4.0 GB, 9.8 s per full sort, 70 k rows/s
ingestion, flat GUI memory).  The real engine was validated end to end up to 1 039 776 alloys;
between ≈ 1 M and 10 M the calculation path is extrapolated (constant throughput and per-row size).
Beyond 10 M every sort/filter would be a multi-ten-second wait and nothing has been validated; raise
it by re-running ``tools/perf_harness.py --scenario storage`` (and a real-engine run) at a larger
size.  Independently, a batch is refused when its estimated database does not fit on the disk
holding the session.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

ALLOYS_PER_WORKER_S = 2_250          # real engine, measured: 1 039 776 alloys / 8 workers / 55 s (incl. storage)
BYTES_PER_RESULT = 480               # largest measured per-row size (100 k rows incl. WAL)
LARGE = 250_000
VERY_LARGE = 1_000_000
HARD_LIMIT = 10_000_000
DISK_RESERVE = 512 * 2**20           # keep this much free beyond the estimate (sort scratch, WAL)


@dataclass(frozen=True)
class RunEstimate:
    count: int
    tier: str                        # normal | large | very_large | too_large
    seconds: float                   # calculation time on this computer (measured rate × workers)
    bytes: int                       # temporary database size


def size_class(n: int) -> str:
    if n > HARD_LIMIT:
        return "too_large"
    if n >= VERY_LARGE:
        return "very_large"
    if n >= LARGE:
        return "large"
    return "normal"


def estimate(n: int, workers: int) -> RunEstimate:
    return RunEstimate(n, size_class(n), n / (ALLOYS_PER_WORKER_S * max(1, workers)), n * BYTES_PER_RESULT)


def capacity_problem(n: int, folder: Path | str | None) -> str | None:
    """Why a batch of ``n`` results cannot be stored (plain language), or None."""
    if n > HARD_LIMIT:
        return (f"{n:,} compositions exceed the largest tested batch ({HARD_LIMIT:,}); increase the steps or "
                "narrow the ranges.")
    if folder is not None:
        try:
            free = shutil.disk_usage(folder).free
        except OSError:
            return None
        need = n * BYTES_PER_RESULT + DISK_RESERVE
        if need > free:
            return (f"Not enough free disk space for {n:,} results: about {fmt_bytes(need)} is needed for the "
                    f"temporary results, {fmt_bytes(free)} is free.")
    return None


def fmt_bytes(b: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if b < 1000 or unit == "TB":
            return f"{b:,.0f} {unit}" if unit == "bytes" else f"{b:,.1f} {unit}"
        b /= 1000
    return f"{b:,.1f} TB"


def fmt_duration(s: float) -> str:
    if s < 60:
        return f"about {max(1, round(s)):,} s"
    if s < 3600:
        return f"about {round(s / 60):,} min"
    return f"about {s / 3600:,.1f} h"


def fmt_short_duration(s: float) -> str:
    """Compact form for the Composition setup workload summary (Figma "~1 s", "~3 min", "~9 min")."""
    if s < 60:
        return f"~{max(1, round(s)):,} s"
    if s < 3600:
        return f"~{round(s / 60):,} min"
    return f"~{s / 3600:,.1f} h"


def fmt_short_bytes(b: float) -> str:
    """Compact form for the workload summary (Figma "~3.2 MB", "~1.5 GB")."""
    return "~" + fmt_bytes(b)


def describe(est: RunEstimate) -> tuple[str, str]:
    """(short tier label for the summary line - empty for a normal set, tooltip with the estimates)."""
    tip = f"Estimated on this computer: {fmt_duration(est.seconds)} of calculation, " \
          f"{fmt_bytes(est.bytes)} of temporary storage."
    if est.tier == "large":
        return "Large set", "Large calculation set. " + tip
    if est.tier == "very_large":
        return "Very large set", ("Very large set: results are processed in the background and stored on disk; "
                                  "sorting and filtering take a few seconds. " + tip)
    if est.tier == "too_large":
        return "Too large", f"More than {HARD_LIMIT:,} compositions (the largest tested batch). " + tip
    return "", tip
