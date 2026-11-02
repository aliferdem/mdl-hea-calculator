"""Composition expression benchmark: parsing, generation, duplicates and calculation of parametric sweeps (no window).

    uv run tools/bench_expression.py [--parts parse,generate,pipeline] [--cases 1v1k,2v10k] [--documents ...]
        [--verify] [--quick] [--allow-large] [--out bench_expression.json]

Parts:

* ``parse`` - for each test document, what *Parse expression* does: parsing and validation of every block
  (``parse_document``) and the pre-flight count with duplicate detection (``count_blocks_detail``), with the valid,
  skipped and duplicate counts;
* ``generate`` - in-process generation of every composition of a document with duplicates removed
  (``generate_blocks``): compositions per second;
* ``pipeline`` - the whole Calculate path (worker pool, writer, SQLite) for paired cases that produce the *same*
  compositions as a Composition space (Fe, Co, Ni locked at 1, the varied elements on a grid) and as the expression
  ``FeCoNiAl{x}...`` with the same grid, and for the test documents (several blocks, duplicates, a constrained
  three-variable sweep in which most combinations are skipped).  ``--verify`` checks that each pair stores the same
  compositions with the same descriptor values (to 1e-9).

Documents (``--documents``): ``single``, ``blocks`` (three blocks), ``duplicates`` (two overlapping blocks, 1,001 duplicates),
``c3v02`` (constrained, 132,651 combinations) and ``c3v01`` (1,030,301 combinations: needs ``--allow-large``).
Cases (``--cases``): ``<variables>v<compositions>``, for example ``2v10k``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import (Report, add_common_arguments, check_sizes, pipeline, process_peaks,  # noqa: E402
                          run_recipe)

DOCUMENTS = {
    "single": "AlxCoCrFeNi\n0 <= x <= 2, step=0.001",
    "blocks": "AlxCoCrFeNi\n0 <= x <= 2, step=0.002\n\n(FeCoNi)1-yMny\n0 <= y <= 0.5, step=0.0005\n\n"
              "TizZrNbHfTa\n0 <= z <= 1, step=0.001",
    "duplicates": "AlxCoCrFeNi\n0 <= x <= 2, step=0.001\n\nAlxCoCrFeNi\n0 <= x <= 1, step=0.0005",
    "c3v02": "(FeCoNi)1-x-y-z(AlTi)xCryCuz\n0 <= x <= 1, step=0.02\n0 <= y <= 1, step=0.02\n0 <= z <= 1, step=0.02",
    "c3v01": "(FeCoNi)1-x-y-z(AlTi)xCryCuz\n0 <= x <= 1, step=0.01\n0 <= y <= 1, step=0.01\n0 <= z <= 1, step=0.01",
}
CASES = {   # name: (variables, values per variable); compositions = values ** variables
    "1v100": (1, 100), "1v1k": (1, 1000), "1v10k": (1, 10000), "2v10k": (2, 100), "3v10k": (3, 22),
    "2v40k": (2, 200), "1v100k": (1, 100000),
}
STEPS = {100: 0.01, 1000: 0.001, 10000: 0.0001, 100000: 0.00001, 22: 0.05, 200: 0.005}
VARIED = ("Al", "Cr", "Mn")
VARS = ("x", "y", "z")


def parse(text: str):
    """What Parse expression does: the document, its pre-flight count and the recipe Calculate receives (built as
    ``hea_calc/ui/widgets/expression_view.py`` builds it)."""
    from hea_calc.core.expression import count_blocks_detail
    from hea_calc.core.expression_doc import parse_document
    from hea_calc.core.recipes import ExpressionRecipe
    t0 = time.perf_counter()
    doc = parse_document(text)
    parse_s = time.perf_counter() - t0
    if not doc.ok:
        raise ValueError(doc.errors)
    t0 = time.perf_counter()
    d = count_blocks_detail(doc.expressions, doc.block_ranges)
    count_s = time.perf_counter() - t0
    merged: dict = {}
    for r in doc.block_ranges:
        for k, v in r.items():
            merged.setdefault(k, v)
    counts = (d["valid"], d["skipped"], d["duplicates"], d["combinations"],
              tuple((i, b[2]) for i, b in enumerate(d["blocks"]) if b[2]))
    recipe = ExpressionRecipe(tuple(doc.expressions), tuple(merged.items()), doc.text,
                              tuple(tuple(r.items()) for r in doc.block_ranges), counts)
    return doc, d, recipe, parse_s, count_s


def combinations(text: str) -> int:
    """Combinations before skips and duplicates (cheap: no enumeration), for the --allow-large check."""
    from hea_calc.core.expression import count_combinations
    from hea_calc.core.expression_doc import parse_document
    doc = parse_document(text)
    return count_combinations(doc.expressions, doc.block_ranges)


def pair(nvars: int, n: int):
    """A Composition space and an expression that generate the same compositions."""
    from hea_calc.core.generation import SweepSpec
    from hea_calc.core.recipes import SweepRecipe
    step = STEPS[n]
    specs = [SweepSpec(el, 1.0, 1.0, 0.1, True) for el in ("Fe", "Co", "Ni")]
    specs += [SweepSpec(VARIED[i], step, 1.0, step, True) for i in range(nvars)]
    text = "FeCoNi" + "".join(f"{VARIED[i]}{{{VARS[i]}}}" for i in range(nvars))
    text += "".join(f"\n{step:g} <= {VARS[i]} <= 1, step={step:g}" for i in range(nvars))
    return SweepRecipe(tuple(specs), "ratio", None), parse(text)


def verify(repo, run_a: int, run_b: int) -> dict:
    """Same compositions, same descriptor values."""
    def rows(run):
        info = repo.get_run(run)
        out = {}
        for r in repo.reader.iter_range(info.first_id, info.last_id):
            key = tuple(sorted((el, round(v, 9)) for el, v in (r.composition or {}).items()))
            out[key] = (r.raw("delta"), r.raw("dhmix"), r.raw("smix"), r.raw("vec"))
        return out
    a, b = rows(run_a), rows(run_b)
    diff = [k for k in a if k not in b or any(abs((x or 0) - (y or 0)) > 1e-9 for x, y in zip(a[k], b[k]))]
    return {"compositions_space": len(a), "compositions_expression": len(b),
            "mismatches": len(diff) + len(set(b) - set(a))}


def part_parse(rep: Report, docs: list[str], repeat: int) -> None:
    for name in docs:
        best_parse = best_count = None
        for _ in range(repeat):
            _doc, d, _recipe, p, c = parse(DOCUMENTS[name])
            best_parse = p if best_parse is None else min(best_parse, p)
            best_count = c if best_count is None else min(best_count, c)
        rep.emit({"part": "parse", "document": name, "blocks": len(d["blocks"]), "combinations": d["combinations"],
                  "valid": d["valid"], "skipped": d["skipped"], "duplicates": d["duplicates"],
                  "parse_s": round(best_parse, 5), "preflight_count_s": round(best_count, 4),
                  "combinations_per_s": round(d["combinations"] / best_count) if best_count else None})


def part_generate(rep: Report, docs: list[str]) -> None:
    from hea_calc.core.expression import generate_blocks
    for name in docs:
        doc, _d, _r, _p, _c = parse(DOCUMENTS[name])
        t0 = time.perf_counter()
        batch = generate_blocks(doc.expressions, doc.block_ranges)
        dt = time.perf_counter() - t0
        rep.emit({"part": "generate", "document": name, "compositions": len(batch.compositions),
                  "skipped": batch.skipped, "duplicates": batch.duplicates, "seconds": round(dt, 3),
                  "compositions_per_s": round(len(batch.compositions) / dt) if dt else None,
                  "peak": process_peaks()})


def part_pipeline(rep: Report, cases: list[str], docs: list[str], workers: int | None, check: bool) -> None:
    with pipeline(workers) as (engine, repo, svc):
        space, (_d, _c, expr, _p, _q) = pair(1, 100)
        run_recipe(svc, repo, engine, space)                    # warm both paths, the pool and the engine caches
        run_recipe(svc, repo, engine, expr)
        for name in cases:
            nv, n = CASES[name]
            space, (_doc, d, expr, parse_s, count_s) = pair(nv, n)
            rs = run_recipe(svc, repo, engine, space)
            re_ = run_recipe(svc, repo, engine, expr)
            rec = {"part": "pipeline", "case": name, "variables": nv, "workers": svc.workers, "space": rs,
                   "expression": re_, "preflight_s": round(parse_s + count_s, 4),
                   "expression_to_space": round(re_["stored_s"] / rs["stored_s"], 2) if rs["stored_s"] else None}
            if check:
                rec["verify"] = verify(repo, rs["run"], re_["run"])
            rec["peak"] = process_peaks(svc, repo)
            rep.emit(rec)
        for name in docs:
            _doc, d, expr, parse_s, count_s = parse(DOCUMENTS[name])
            r = run_recipe(svc, repo, engine, expr)
            rep.emit({"part": "pipeline", "document": name, "workers": svc.workers, "combinations": d["combinations"],
                      "valid": d["valid"], "duplicates": d["duplicates"], "preflight_s": round(parse_s + count_s, 4),
                      "expression": r, "peak": process_peaks(svc, repo)})
            if r["rows"] != d["valid"]:
                raise RuntimeError(f"{name}: {r['rows']} rows stored, {d['valid']} valid compositions expected")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--parts", default="parse,generate,pipeline")
    ap.add_argument("--cases", default="1v1k,1v10k,2v10k,3v10k")
    ap.add_argument("--documents", default="single,blocks,duplicates,c3v02")
    ap.add_argument("--repeat", type=int, default=3, help="parse timings: best of this many")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--verify", action="store_true", help="compare each space / expression pair value by value")
    add_common_arguments(ap)
    args = ap.parse_args()
    if args.quick:
        args.cases, args.documents, args.repeat = "1v100", "single,duplicates", 1
    cases = [c for c in args.cases.split(",") if c]
    docs = [d for d in args.documents.split(",") if d]
    unknown = [c for c in cases if c not in CASES] + [d for d in docs if d not in DOCUMENTS]
    if unknown:
        sys.exit(f"Unknown case or document: {', '.join(unknown)}")
    check_sizes([CASES[c][1] ** CASES[c][0] for c in cases] + [combinations(DOCUMENTS[d]) for d in docs],
                args.allow_large)
    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    rep = Report("bench_expression", args)
    try:
        if "parse" in parts:
            part_parse(rep, docs, args.repeat)
        if "generate" in parts:
            part_generate(rep, docs)
        if "pipeline" in parts:
            part_pipeline(rep, cases, docs, args.workers, args.verify)
    finally:
        rep.close()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
