"""Streaming export of the result dataset (CSV / Excel / clipboard TSV).  No Qt, no scientific logic.

Export works on the *dataset* - all results, or the current filtered/sorted view - never on the
visible page.  Rows are streamed from the repository in chunks and written as they arrive, so an
export of millions of rows holds a few thousand rows in memory at most:

* CSV is written row by row;
* Excel uses XlsxWriter's ``constant_memory`` mode.  One worksheet holds at most
  ``XLSX_MAX_ROWS`` = 1 048 575 data rows (1 048 576 including the header): larger exports are
  split over consecutive worksheets ("Results", "Results (2)", …) - never truncated - and the
  caller is expected to offer CSV first (see the UI);
* the rows are one query (``ResultView.export_spec``): all results (filters ignored) or the
  filtered results, in the table's current sort order - from the dataset, so rows committed
  after the table's sorted view was built are included;
* large exports run in a separate process (:func:`export_process_main`) that opens the database
  read-only inside one read transaction - a consistent snapshot even while results are removed
  or the table is re-sorted.
"""

from __future__ import annotations

import csv
import datetime as _dt
import math
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path

from .engine import MODEL_KEYS, MODELS
from .results import COLUMN_BY_KEY, COLUMNS, table_tsv

XLSX_MAX_ROWS = 1_048_575            # data rows per worksheet (Excel: 1 048 576 rows incl. header)
CLIPBOARD_MAX_ROWS = 1_048_575       # a clipboard table larger than one worksheet cannot be pasted


class ExportCancelled(Exception):
    pass


def export_keys() -> list[str]:
    return [c.key for c in COLUMNS if c.key != "composition"]


def export_headers(elements: list[str]) -> list[str]:
    keys = export_keys()
    return ["Alloy", "Source"] + [f"{el} (at.%)" for el in elements] + \
        [COLUMN_BY_KEY[k].header for k in keys if k != "name"] + \
        [f"{k} note" for k in MODEL_KEYS] + ["Warnings", "Error"]


def row_values(r, elements: list[str], keys: list[str] | None = None) -> list:
    keys = keys or export_keys()
    vals: list = [r.name, r.source]
    comp = r.composition
    vals += [100.0 * comp.get(el, 0.0) if comp else None for el in elements]
    for k in keys:
        if k == "name":
            continue
        v = r.raw(k)
        if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
            v = "inf" if v > 0 else ("-inf" if v < 0 else "nan")
        vals.append(v)
    for k in MODEL_KEYS:
        vals.append(r.model_note(k))
    vals.append(" ".join(r.warnings))
    vals.append(r.error or "")
    return vals


class _StoredRowValues:
    """:func:`row_values` for stored records, straight from their SQL tuple (≈ 3× faster than the row
    protocol: no per-cell property calls, one cached lookup per distinct string / element order)."""

    def __init__(self, elements: list[str], keys: list[str]):
        from .repository import COL
        self.elements = elements
        self.idx = [COL[k] for k in keys if k != "name"]
        self.notes = [COL["n_" + k] for k in MODEL_KEYS]
        self._strings: dict = {None: "", 0: ""}
        self._positions: dict = {}

    def string(self, reader, code) -> str:
        s = self._strings.get(code)
        if s is None:
            s = self._strings[code] = reader.string(code) or ""
            if len(self._strings) > 50_000:
                self._strings = {None: "", 0: ""}
        return s

    def __call__(self, rec) -> list:
        from array import array
        from .repository import _I_AMOUNTS, _I_ELSET, _I_ERR, _I_NAME, _I_SRC, _I_WARN
        v, rd = rec.v, rec.reader
        pos = self._positions.get(v[_I_ELSET])
        if pos is None:
            els = rd.elset(v[_I_ELSET])
            pos = self._positions[v[_I_ELSET]] = (len(els), [els.index(e) if e in els else -1 for e in self.elements])
        k, where = pos
        a = array("d")
        a.frombytes(v[_I_AMOUNTS])
        fr = a[k:2 * k]
        out: list = [v[_I_NAME] or "", self.string(rd, v[_I_SRC])]
        if any(x > 0 for x in fr):
            out += [100.0 * fr[p] if p >= 0 and fr[p] > 0 else 0.0 for p in where]
        else:
            out += [None] * len(where)
        for i in self.idx:
            x = v[i]
            if isinstance(x, float) and (x == math.inf or x == -math.inf):
                x = "inf" if x > 0 else "-inf"
            out.append(x)
        out += [self.string(rd, v[i]) for i in self.notes]
        out.append(self.string(rd, v[_I_WARN]))
        out.append(self.string(rd, v[_I_ERR]))
        return out


def _values_fn(records, elements, keys):
    """The fastest correct row formatter for these records."""
    fast = _StoredRowValues(elements, keys)
    generic = lambda r: row_values(r, elements, keys)          # noqa: E731

    def values(r):
        return fast(r) if hasattr(r, "reader") and hasattr(r, "v") else generic(r)
    return values


def write_records(records: Iterable, path: str | Path, elements: list[str], *, notes: dict | None = None,
                  total: int | None = None, progress: Callable[[int], None] | None = None,
                  cancelled: Callable[[], bool] | None = None, max_sheet_rows: int = XLSX_MAX_ROWS) -> int:
    """Write records (row protocol) to .csv or .xlsx; returns the number of rows written."""
    path = Path(path)
    headers = export_headers(elements)
    keys = export_keys()
    values = _values_fn(records, elements, keys)
    n = 0

    def tick():
        if cancelled is not None and not n % 2000 and cancelled():
            raise ExportCancelled()
        if progress is not None and not n % 2000:
            progress(n)

    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(headers)
            for r in records:
                w.writerow(["" if v is None else v for v in values(r)])
                n += 1
                tick()
        if progress is not None:
            progress(n)
        return n

    import xlsxwriter
    wb = xlsxwriter.Workbook(str(path), {"nan_inf_to_errors": True, "constant_memory": True})
    bold = wb.add_format({"bold": True})
    sheets = 0
    ws, i = None, 0
    try:
        for r in records:
            if ws is None or i > max_sheet_rows:
                sheets += 1
                ws = wb.add_worksheet("Results" if sheets == 1 else f"Results ({sheets})")
                for j, h in enumerate(headers):
                    ws.write(0, j, h, bold)
                ws.freeze_panes(1, 1)
                i = 1
            for j, v in enumerate(values(r)):
                if v is None:
                    continue
                if isinstance(v, (int, float)):
                    ws.write_number(i, j, v)
                else:
                    ws.write_string(i, j, str(v))
            i += 1
            n += 1
            tick()
        if ws is None:
            ws = wb.add_worksheet("Results")
            for j, h in enumerate(headers):
                ws.write(0, j, h, bold)
            sheets = 1
        meta = wb.add_worksheet("About")
        lines = [("Generated", _dt.datetime.now().isoformat(timespec="seconds")), ("Rows", n)]
        if sheets > 1:
            lines.append(("Worksheets", f"{sheets} (at most {max_sheet_rows:,} rows each - the Excel limit)"))
        for k in MODEL_KEYS:
            lines.append((k, f"{MODELS[k].title}: {MODELS[k].criterion}"))
        for k, v in (notes or {}).items():
            lines.append((k, v))
        for j, (a, b) in enumerate(lines):
            meta.write(j, 0, a, bold)
            meta.write(j, 1, str(b))
    finally:
        wb.close()
    if progress is not None:
        progress(n)
    return n


def write_tsv(records: Iterable, path: str | Path, keys: list[str],
              cancelled: Callable[[], bool] | None = None, progress: Callable[[int], None] | None = None) -> int:
    """The table's clipboard text (visible columns, displayed values) written to a file."""
    n = 0
    batch: list = []
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        first = True
        for r in records:
            batch.append(r)
            if len(batch) == 2000:
                text = table_tsv(batch, keys)
                fh.write(text if first else text.split("\r\n", 1)[1])
                first = False
                n += len(batch)
                batch = []
                if cancelled is not None and cancelled():
                    raise ExportCancelled()
                if progress is not None:
                    progress(n)
        if batch or first:
            text = table_tsv(batch, keys)
            fh.write(text if first else text.split("\r\n", 1)[1])
            n += len(batch)
    if progress is not None:
        progress(n)
    return n


# ---------------------------------------------------------------------- worker process
def open_snapshot(spec: dict) -> sqlite3.Connection:
    """Read-only connection to the session database (views attached) inside one read transaction."""
    con = sqlite3.connect(f"file:{Path(spec['db']).as_posix()}?mode=ro", uri=True, isolation_level=None, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("BEGIN")
    return con


def iter_spec(con: sqlite3.Connection, spec: dict, engine=None):
    from .repository import Reader
    rd = Reader(con, engine)
    return rd.iter_query(spec["lo"], spec["hi"], spec["where"], tuple(spec["params"]), spec["order"])


def export_process_main(spec: dict, path: str, kind: str, payload: dict, progress, cancel, results) -> None:
    """Entry point of the export process: ``kind`` is "file" (CSV/XLSX) or "tsv" (clipboard text)."""
    try:
        con = open_snapshot(spec)
        try:
            rows = iter_spec(con, spec)

            def prog(n):
                progress.value = n
            if kind == "tsv":
                n = write_tsv(rows, path, payload["keys"], cancel.is_set, prog)
            else:
                n = write_records(rows, path, payload["elements"], notes=payload.get("notes"), progress=prog,
                                  cancelled=cancel.is_set)
        finally:
            con.close()
        results.put(("ok", n))
    except ExportCancelled:
        results.put(("cancelled", 0))
    except Exception as exc:                          # noqa: BLE001 - reported by the GUI
        from .repository import user_message
        msg = user_message(exc) if isinstance(exc, sqlite3.Error) else str(exc)
        results.put(("error", msg))
