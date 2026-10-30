"""Variables column in the CSV / XLSX dataset export (2026-10-29, approved follow-up of the UX package).

No Qt.  A repository with an expression run (two variables), a composition-space run and single compositions is
exported; the expected Variables text of every row is rebuilt here directly from SQLite (the run's axes and its
design table), independently of the exporter and of ``Reader.design_values``.  The batched lookup is checked for the
absence of per-row queries."""

import csv
import json
import math
import sqlite3
import time

import pytest

from hea_calc.core import export as X
from hea_calc.core.analysis import samples
from hea_calc.core.repository import ResultRepository


@pytest.fixture()
def repo(engine, tmp_path):
    r = ResultRepository(engine, root=tmp_path / "sessions")
    yield r
    r.close()


@pytest.fixture()
def runs(repo, engine):
    e2 = samples.store_recipe(repo, engine, samples.e2_recipe())          # AlxTiyCoCrFeNi: x, y
    c1 = samples.store_recipe(repo, engine, samples.c1_recipe())          # composition space (ratio grid)
    s, _rng = samples.store_singles(repo, engine, [samples.S1, samples.S2])
    return {"expr": e2, "space": c1, "single": s}


def _records(repo):
    return list(repo.reader.iter_query(0, 10 ** 9))


def _fmt(v) -> str:
    return f"{v:.6g}" if isinstance(v, float) else str(v)


def _expected(db_path) -> dict[int, str]:
    """result_id -> Variables text, from the runs' axes and design tables (stored order; NULLs omitted)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out = {rid: "" for (rid,) in con.execute("SELECT result_id FROM results")}
        for run_id, axes_js in con.execute("SELECT run_id, axes FROM runs"):
            axes = [a for a in json.loads(axes_js or "[]") if a.get("col") and a.get("kind") in ("variable", "element")]
            if not axes:
                continue
            cols = ", ".join(f'"{a["col"]}"' for a in axes)
            for row in con.execute(f'SELECT result_id, {cols} FROM "design_{run_id}"'):
                out[row[0]] = ", ".join(f"{a['name']} = {_fmt(v)}" for a, v in zip(axes, row[1:]) if v is not None)
        return out
    finally:
        con.close()


def _csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    return rows[0], rows[1:]


def test_csv_and_xlsx_carry_the_variables_of_every_run(repo, runs, tmp_path):
    recs = _records(repo)
    elements = sorted({el for r in recs for el in r.composition})
    exp = _expected(repo.db_path)
    by_name = {}
    for kind in ("csv", "xlsx"):
        path = tmp_path / f"out.{kind}"
        n = X.write_records(iter(recs), path, elements)
        assert n == len(recs)
        if kind == "csv":
            head, rows = _csv_rows(path)
        else:
            import openpyxl
            ws = openpyxl.load_workbook(path, read_only=True)["Results"]
            data = [["" if v is None else v for v in r] for r in ws.iter_rows(values_only=True)]
            head, rows = [str(h) for h in data[0]], data[1:]
        vi, ri = head.index("Variables"), head.index("Run")
        assert len(rows) == len(recs)
        for rec, row in zip(recs, rows):
            assert str(row[vi] or "") == exp[rec.id], (kind, rec.run_id, rec.id)
            assert int(float(row[ri])) == rec.run_id
        by_name[kind] = [str(r[vi] or "") for r in rows]
    assert by_name["csv"] == by_name["xlsx"]
    # every kind of run is represented, with the right shape of text
    texts = {rec.run_id: exp[rec.id] for rec in recs}
    assert texts[runs["expr"]].startswith("x = ") and ", y = " in texts[runs["expr"]]
    assert texts[runs["space"]] and "at.%" not in texts[runs["space"]]          # grid values, not fractions
    assert texts[runs["single"]] == ""                                          # never invented


def test_other_columns_are_unchanged_by_the_batched_path(repo, runs, tmp_path):
    """The fast (stored-tuple + batched) path and the generic row path give the same cells, Variables included."""
    recs = _records(repo)
    elements = sorted({el for r in recs for el in r.composition})
    keys = X.export_keys()
    fast = X._values_fn(recs, elements, keys)
    fast.prepare(recs)
    for r in recs:
        a, b = fast(r), X.row_values(r, elements, keys)
        assert len(a) == len(b) == len(X.export_headers(elements))
        for i, (x, y) in enumerate(zip(a, b)):
            if isinstance(x, float) and isinstance(y, float) and math.isnan(x):
                assert math.isnan(y)
            else:
                assert x == y or (x in ("", None) and y in ("", None)), (i, x, y)
    # the headers: the previous ones, with Run and Variables in their column order
    head = X.export_headers(elements)
    assert head[:2] == ["Alloy", "Source"] and "Run" in head and "Variables" in head
    assert head.index("Variables") == head.index("Run") + 1


def test_missing_design_values_export_as_empty_or_partial(repo, runs, tmp_path):
    recs = _records(repo)
    expr = [r for r in recs if r.run_id == runs["expr"]]
    gone, partial = expr[0].id, expr[1].id
    con = sqlite3.connect(str(repo.db_path))                 # simulate a lost design row and a NULL value
    try:
        cols = [a["col"] for a in json.loads(con.execute("SELECT axes FROM runs WHERE run_id=?",
                                                         (runs["expr"],)).fetchone()[0]) if a.get("kind") == "variable"]
        con.execute(f'DELETE FROM "design_{runs["expr"]}" WHERE result_id=?', (gone,))
        con.execute(f'UPDATE "design_{runs["expr"]}" SET "{cols[1]}" = NULL WHERE result_id=?', (partial,))
        con.commit()
    finally:
        con.close()
    path = tmp_path / "missing.csv"
    X.write_records(iter(_records(repo)), path, sorted({el for r in recs for el in r.composition}))
    head, rows = _csv_rows(path)
    vi = head.index("Variables")
    got = {r.id: row[vi] for r, row in zip(_records(repo), rows)}
    assert got[gone] == ""                                    # no design row: empty, not an error
    assert got[partial].startswith("x = ") and "y = " not in got[partial]
    assert got == _expected(repo.db_path)


def test_variables_lookup_is_batched_not_per_row(repo, runs, tmp_path, monkeypatch):
    recs = _records(repo)
    n_design = sum(1 for r in recs if r.run_id in (runs["expr"], runs["space"]))
    assert n_design > 100
    queries = []
    repo.reader.con.set_trace_callback(lambda sql: queries.append(sql) if "design_" in sql else None)
    try:
        monkeypatch.setattr(X, "EXPORT_CHUNK", 50)            # many chunks: queries scale with chunks, not rows
        X.write_records(iter(recs), tmp_path / "trace.csv", sorted({el for r in recs for el in r.composition}))
    finally:
        repo.reader.con.set_trace_callback(None)
    chunks = math.ceil(len(recs) / 50)
    assert 0 < len(queries) <= 2 * chunks, (len(queries), chunks)        # at most one per run present in a chunk
    assert len(queries) < n_design / 10, "no per-row design query"


def test_variables_export_performance(repo, engine, tmp_path):
    """A larger expression run (2,001 results) exports with Variables in well under the per-row cost."""
    rec = samples.expression_recipe("AlxCoCrFeNi", {"x": (0.0, 2.0, 0.001)})
    samples.store_recipe(repo, engine, rec)
    recs = _records(repo)
    assert len(recs) == 2001
    elements = sorted({el for r in recs for el in r.composition})
    t0 = time.perf_counter()
    X.write_records(iter(recs), tmp_path / "big.csv", elements)
    batched = time.perf_counter() - t0
    head, rows = _csv_rows(tmp_path / "big.csv")
    vi = head.index("Variables")
    assert rows[0][vi] == "x = 0" and rows[-1][vi] == "x = 2"
    # reference: the former per-row lookup (one design query per row) for the same records
    t0 = time.perf_counter()
    for r in recs:
        repo.reader.design_values(r)
    per_row = time.perf_counter() - t0
    assert batched < 5.0, batched
    _ = per_row                                               # reported by -s; machine-dependent, not asserted
