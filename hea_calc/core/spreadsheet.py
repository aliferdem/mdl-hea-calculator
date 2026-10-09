"""Spreadsheet import (compositions) and export (results). No scientific calculations."""

from __future__ import annotations

import csv
import datetime as _dt
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .composition import FormulaError, parse_formula
from .data import Datasets, default_datasets
from .engine import MODEL_KEYS, MODELS
from .results import COLUMN_BY_KEY, COLUMNS, ResultRow

FORMULA_HEADERS = ("formula", "alloy", "composition", "identifier", "name")


class SpreadsheetError(ValueError):
    pass


@dataclass
class ImportResult:
    entries: list[tuple[str, dict[str, float]]] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)  # (spreadsheet row number, message)
    layout: str = ""


def _read_table(path: Path) -> list[list]:
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt", ".tsv"):
        with path.open(newline="", encoding="utf-8-sig") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            return [row for row in csv.reader(fh, dialect)]
    if suffix in (".xlsx", ".xlsm", ".xls"):
        try:
            import openpyxl  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise SpreadsheetError("openpyxl is required to read Excel files.") from exc
        if suffix == ".xls":
            raise SpreadsheetError("Legacy .xls files are not supported; save the workbook as .xlsx.")
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    raise SpreadsheetError(f"Unsupported file type '{path.suffix}'.")


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _element_header(h: str, data: Datasets) -> str | None:
    """'Fe', 'Fe (at.%)', 'Fe at%' → 'Fe'; otherwise None."""
    m = re.match(r"^\s*([A-Z][a-z]?)\s*(?:[\(\[].*[\)\]]|at\.?%|wt\.?%)?\s*$", h)
    if m and data.is_element(m.group(1)):
        return m.group(1)
    return None


def _parse_amount(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace(",", ".")
    if t == "":
        return None
    return float(t)  # raises ValueError for malformed text


def read_compositions(path: str | Path, datasets: Datasets | None = None) -> ImportResult:
    """Read compositions from a spreadsheet.

    Layouts:
      * a formula column (header contains formula/alloy/composition/identifier/name), or
      * one column per element (header 'Fe', 'Fe (at.%)', …) with proportional amounts; an optional
        name/alloy column labels the rows.
    Blank element cells mean 0. Malformed numbers, negative amounts, unknown elements and rows with
    fewer than two elements are reported per row and skipped.
    """
    data = datasets or default_datasets()
    path = Path(path)
    table = _read_table(path)
    table = [r for r in table if any(_cell_text(c) for c in r)]
    if not table:
        raise SpreadsheetError("The file is empty.")
    header = [_cell_text(c) for c in table[0]]
    body = table[1:]
    res = ImportResult()

    element_cols = {i: el for i, h in enumerate(header) if (el := _element_header(h, data))}
    name_col = next((i for i, h in enumerate(header) if h.lower() in ("name", "alloy", "id", "label")), None)
    formula_col = None
    if not element_cols:
        formula_col = next((i for i, h in enumerate(header)
                            if any(k in h.lower() for k in FORMULA_HEADERS)), None)
    if element_cols:
        res.layout = "element columns"
        suspicious = [h for i, h in enumerate(header)
                      if i not in element_cols and i != name_col and re.fullmatch(r"[A-Z][a-z]?", h)]
        for h in suspicious:
            res.errors.append((1, f"Column '{h}' is not a valid element symbol and was ignored."))
        for n, row in enumerate(body, start=2):
            amounts: dict[str, float] = {}
            bad = None
            for i, el in element_cols.items():
                cell = row[i] if i < len(row) else None
                try:
                    v = _parse_amount(cell)
                except ValueError:
                    bad = f"{el}: '{_cell_text(cell)}' is not a number."
                    break
                if v is None:
                    continue
                if not math.isfinite(v) or v < 0:
                    bad = f"{el}: amount must be a non-negative number."
                    break
                if v > 0:
                    amounts[el] = amounts.get(el, 0.0) + v
            if bad:
                res.errors.append((n, bad))
                continue
            if len(amounts) < 2:
                res.errors.append((n, "Fewer than two elements with non-zero amounts."))
                continue
            label = _cell_text(row[name_col]) if name_col is not None and name_col < len(row) else ""
            res.entries.append((label, amounts))
    elif formula_col is not None:
        res.layout = f"formula column '{header[formula_col]}'"
        for n, row in enumerate(body, start=2):
            text = _cell_text(row[formula_col]) if formula_col < len(row) else ""
            if not text:
                res.errors.append((n, "Missing formula."))
                continue
            try:
                amounts = parse_formula(text, data)
            except FormulaError as exc:
                res.errors.append((n, f"'{text}': {exc}"))
                continue
            if len([v for v in amounts.values() if v > 0]) < 2:
                res.errors.append((n, f"'{text}': fewer than two elements."))
                continue
            res.entries.append((text, amounts))
    else:
        raise SpreadsheetError(
            "No composition columns found. Use a 'Formula'/'Alloy'/'Composition' column or one column per "
            "element symbol (e.g. Fe, Co, Ni).")
    return res


# ---------------------------------------------------------------------- export
def export_rows(rows, path: str | Path, *, visible_keys: list[str] | None = None,
                notes: dict | None = None, elements: list[str] | None = None) -> Path:
    """Write results (any row-protocol iterable) to .xlsx (full precision) or .csv.

    ``elements`` fixes the at.% columns up front (the repository knows them per run); without it
    the rows are scanned once for their elements, so only pass a re-iterable sequence then."""
    from .export import write_records
    path = Path(path)
    if elements is None:
        elements = []
        for r in rows:
            for el in r.composition:
                if el not in elements:
                    elements.append(el)
    write_records(rows, path, elements, notes=notes)
    return path


_ = (csv, _dt, math, MODEL_KEYS, MODELS, COLUMN_BY_KEY, COLUMNS, ResultRow)
