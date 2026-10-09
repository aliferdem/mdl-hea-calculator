"""Synthetic result chunks for storage/query benchmarks and tests - clearly not new calculations.

A chunk of ``base`` real engine results is replicated (column arrays repeated) to any size, with
distinct names and a deterministic per-row perturbation of a few numeric columns so sorts and
filters see realistic value spreads.  Values are therefore *engine outputs of a small set of
alloys*, labelled ``SYN…``: use for repository/query measurements only.
"""

from __future__ import annotations

from array import array

from hea_calc.core.chunks import pack_results, with_metadata


def _base(engine, base: int):
    comps = [{"Fe": 1 + i % 7, "Co": 1 + (i // 7) % 3, "Ni": 1 + i % 3, "Cr": 0.5 + i % 5, "Mn": 0.2 + (i % 4) * 0.4}
             for i in range(base)]
    comps[-1] = {"Fe": 1.0}                         # one engine error row (N/A everywhere)
    return comps, pack_results(comps, [engine.calculate(c) for c in comps])


_CACHE: dict = {}


def synthetic_chunk(engine, n: int, start: int = 0, base: int = 50, source: str = "sweep") -> dict:
    """``n`` rows (names ``SYN<start+i>``) replicated from ``base`` real results."""
    key = (id(engine), base)
    if key not in _CACHE:
        _CACHE[key] = _base(engine, base)
    comps, ch = _CACHE[key]
    reps = -(-n // base)
    big = {"n": n, "strings": ch["strings"], "elements": ch["elements"], "cancelled": False}
    for k in ("el_idx", "warnings", "errors", "temps"):
        big[k] = (ch[k] * reps)[:n]
    for k in ("comp", "amounts"):
        big[k] = (ch[k] * reps)[:n]
    for group in ("num", "text", "labels", "notes"):
        big[group] = {k: (v * reps)[:n] for k, v in ch[group].items()}
    # spread a few columns so a sort is not mostly ties (deterministic, small)
    for k, scale in (("dhmix", 1e-7), ("delta", 1e-8), ("omega", 1e-7), ("phi_king", 1e-8)):
        col = big["num"][k]
        big["num"][k] = array("d", (v + scale * ((i + start) % 100_003) if v == v else v for i, v in enumerate(col)))
    return with_metadata(big, [f"SYN{start + i}" for i in range(n)], source)


def fill(repo, n: int, engine, chunk: int = 5000, mode: str = "sweep", run_id: int | None = None) -> int:
    """Insert ``n`` synthetic rows as one run through the single writer (synchronous commits)."""
    if run_id is None:
        run_id = repo.create_run(mode, settings={}, elements=["Fe", "Co", "Ni", "Cr", "Mn"], expected=n,
                                 source={"synthetic": True})
    done = 0
    while done < n:
        k = min(chunk, n - done)
        repo.append_chunk(run_id, synthetic_chunk(engine, k, done))
        done += k
    repo.finalize_run(run_id, "complete")
    return run_id
