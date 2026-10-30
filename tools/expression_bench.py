"""Expression vs Composition space throughput on equivalent datasets (no Qt).

Each case is a pair that generates the *same* compositions: a Composition space with Fe, Co, Ni locked at 1 and the
varied elements on a grid, and the expression ``FeCoNiAl{x}…`` with the same grid as its variable ranges.  Both run
through the application's real pipeline: the persistent worker pool (:class:`~hea_calc.core.jobs.CalculationService`),
the single writer process and the SQLite repository - exactly what Calculate does, minus the window.

Usage:
    .venv/Scripts/python.exe tools/expression_bench.py [--workers N] [--cases 1v100,1v1k,1v10k,2v10k,3v10k,2v40k]
           [--out design/implementation/expression_bench.json] [--verify]

Reported per case and mode: generation / planning time (expression plan), first chunk latency, total wall time,
stored rows, rows/s, and the GUI-process peak working set (Windows).  ``--verify`` checks that both modes produce the
same compositions and the same descriptor values (to 1e-9).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Constrained expressions (most combinations skipped: 1-x-y-z >= 0) have no Composition-space twin; they are measured
# per valid composition against the space rate of a similar row count.
CONSTRAINED = {
    "c3v02": "(FeCoNi)1-x-y-z(AlTi)xCryCuz\n  0 <= x <= 1, step=0.02\n  0 <= y <= 1, step=0.02\n  0 <= z <= 1, step=0.02",
    "c3v01": "(FeCoNi)1-x-y-z(AlTi)xCryCuz\n  0 <= x <= 1, step=0.01\n  0 <= y <= 1, step=0.01\n  0 <= z <= 1, step=0.01",
}
CASES = {
    # name: (variables, values per variable)
    "1v100": (1, 100), "1v1k": (1, 1000), "1v10k": (1, 10000), "2v10k": (2, 100), "3v10k": (3, 22),
    "2v40k": (2, 200), "1v100k": (1, 100000),
}
VARIED = ("Al", "Cr", "Mn")
VARS = ("x", "y", "z")


def grid(n: int) -> tuple[float, float, float]:
    """``n`` values from 1/n to 1 in steps of 1/n, with a decimal step (exact grid)."""
    step = {100: 0.01, 1000: 0.001, 10000: 0.0001, 100000: 0.00001, 22: 0.05, 200: 0.005}[n]
    return step, 1.0, step


def peak_mb() -> float:
    if sys.platform != "win32":
        return 0.0
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t)] + \
                   [(f"f{i}", ctypes.c_size_t) for i in range(6)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.PeakWorkingSetSize / 2 ** 20


def recipes(nvars: int, n: int):
    from hea_calc.core.expression_doc import parse_document
    from hea_calc.core.generation import SweepSpec
    from hea_calc.core.recipes import ExpressionRecipe, SweepRecipe
    lo, hi, step = grid(n)
    specs = [SweepSpec(el, 1.0, 1.0, 0.1, True) for el in ("Fe", "Co", "Ni")]
    specs += [SweepSpec(VARIED[i], lo, hi, step, True) for i in range(nvars)]
    sweep = SweepRecipe(tuple(specs), "ratio", None)
    formula = "FeCoNi" + "".join(f"{VARIED[i]}{{{VARS[i]}}}" for i in range(nvars))
    text = formula + "".join(f"\n  {lo:g} <= {VARS[i]} <= {hi:g}, step={step:g}" for i in range(nvars))
    expr, parse_s = expression_recipe(text)
    return sweep, expr, parse_s


def expression_recipe(text: str):
    """The recipe as Parse expression builds it: parse, count (the editor's pre-flight), recipe.  Returns the recipe
    and the pre-flight seconds (parse + count)."""
    from hea_calc.core.expression import count_blocks_detail
    from hea_calc.core.expression_doc import parse_document
    from hea_calc.core.recipes import ExpressionRecipe
    t0 = time.perf_counter()
    doc = parse_document(text)
    assert doc.ok, doc.errors
    d = count_blocks_detail(doc.expressions, doc.block_ranges)
    pre = time.perf_counter() - t0
    args = (tuple(doc.expressions), (), doc.text, tuple(tuple(b.items()) for b in doc.block_ranges))
    counts = (d["valid"], d["skipped"], d["duplicates"], d["combinations"],
              tuple((i, b[2]) for i, b in enumerate(d["blocks"]) if b[2]))
    try:
        return ExpressionRecipe(*args, counts), pre
    except TypeError:                       # the code before the direct path (benchmark of the checkpoint)
        return ExpressionRecipe(*args), pre


def run(svc, repo, engine, recipe) -> dict:
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
    assert job.state == "done", job.error
    repo.finalize_run(run_id, "complete", upto=job.chunks_emitted)
    t1 = time.perf_counter()
    while repo.committed_last < (repo.get_run(run_id).last_id or 0) and time.perf_counter() - t1 < 60:
        time.sleep(0.005)
    stored_s = time.perf_counter() - t0
    info = repo.get_run(run_id)
    n = (info.last_id - info.first_id + 1) if info.first_id is not None else 0
    return {"run": run_id, "rows": n, "first_chunk_s": round(first or calc_s, 3), "calc_s": round(calc_s, 3),
            "stored_s": round(stored_s, 3), "rows_per_s": round(n / stored_s) if stored_s else 0,
            "plan_counts": list(job.plan_counts) if getattr(job, "plan_counts", None) else None,
            "mode": job.mode}


def verify(repo, run_a: int, run_b: int) -> dict:
    """Same compositions, same descriptor values."""
    def rows(run):
        info = repo.get_run(run)
        out = {}
        for r in repo.reader.iter_range(info.first_id, info.last_id):
            comp = r.composition if hasattr(r, "composition") else None
            key = tuple(sorted((el, round(v, 9)) for el, v in (comp or {}).items()))
            out[key] = (r.raw("delta"), r.raw("dhmix"), r.raw("smix"), r.raw("vec"))
        return out
    a, b = rows(run_a), rows(run_b)
    diff = [k for k in a if k not in b or any(abs((x or 0) - (y or 0)) > 1e-9 for x, y in zip(a[k], b[k]))]
    return {"compositions_a": len(a), "compositions_b": len(b), "mismatches": len(diff) + len(set(b) - set(a))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--cases", default="1v100,1v1k,1v10k,2v10k,3v10k,2v40k")
    ap.add_argument("--out", default=str(ROOT / "design" / "implementation" / "expression_bench.json"))
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--constrained", default="c3v02,c3v01")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    from hea_calc.core.engine import default_engine
    from hea_calc.core.jobs import CalculationService
    from hea_calc.core.repository import ResultRepository
    engine = default_engine()
    repo = ResultRepository(engine, root=Path(tempfile.mkdtemp()) / "sessions")
    svc = CalculationService(workers=args.workers, channel=repo.writer.inbox)
    svc.warm_up().join()
    out = {"label": args.label, "workers": svc.workers, "cases": []}
    try:
        # warm both code paths once (imports, pool processes, engine caches)
        s, e, _ = recipes(1, 100)
        run(svc, repo, engine, s)
        run(svc, repo, engine, e)
        for name in args.cases.split(","):
            nv, n = CASES[name]
            sweep, expr, parse_s = recipes(nv, n)
            rs = run(svc, repo, engine, sweep)
            re_ = run(svc, repo, engine, expr)
            rec = {"case": name, "variables": nv, "space": rs, "expression": re_, "preflight_s": round(parse_s, 4),
                   "ratio_expression_to_space": round(re_["stored_s"] / rs["stored_s"], 2) if rs["stored_s"] else None}
            if args.verify:
                rec["verify"] = verify(repo, rs["run"], re_["run"])
            out["cases"].append(rec)
            print(json.dumps({k: rec[k] for k in ("case", "ratio_expression_to_space")}),
                  "space", rs["rows"], rs["stored_s"], "expr", re_["rows"], re_["stored_s"], rec.get("verify", ""),
                  flush=True)
        for name in [c for c in args.constrained.split(",") if c]:
            expr, pre = expression_recipe(CONSTRAINED[name])
            r = run(svc, repo, engine, expr)
            rec = {"case": name, "expression": r, "preflight_s": round(pre, 3),
                   "combinations": (r["plan_counts"] or [None] * 4)[3]}
            out["cases"].append(rec)
            print(json.dumps({"case": name, "preflight_s": rec["preflight_s"], "rows": r["rows"],
                              "stored_s": r["stored_s"], "rows_per_s": r["rows_per_s"]}), flush=True)
        out["peak_gui_process_mb"] = round(peak_mb(), 1)
    finally:
        svc.shutdown()
        repo.close()
    Path(args.out).write_text(json.dumps(out, indent=1))
    print("wrote", args.out)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
