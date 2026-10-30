"""Columnar result chunks: what calculation workers send back (picklable, no Qt, no SQLite).

A chunk carries exactly what the results repository stores for each alloy, column by column, so the
single database writer only re-maps a few string codes and hands the columns to ``executemany``:

* every numeric table column as an ``array('d')`` (``None`` stored as NaN - SQLite stores a bound
  NaN as NULL, and the engine never yields NaN for a table column);
* text/label columns (crystal structure, M1-M8 labels, model notes, warnings, errors) as small
  integer codes into the chunk's own string table (code 0 is ``None``);
* per alloy: its element order (an index into ``elements``), the composition text shown in the
  table, and the input amounts followed by the normalised atomic fractions as one ``float64`` blob;
* per alloy and model (schema 2): the evidence status of the verdict and, for N/A verdicts, why it
  is not available - as small integer codes (``STATUS_CODES`` / ``NA_CODES``, -1 = none);
* per alloy: its element family (an index into ``families``, -1 for a row that could not be
  evaluated) and the number of elements of that family.

Model notes: the engine gives an N/A verdict a ``reason`` and never a ``caution``, and an evaluated
verdict a ``caution`` at most and never a ``reason`` (tests/test_analysis_schema.py pins this), so the
one stored note per model is unambiguous: it is the reason when the label is N/A, else the caution.

Everything per-alloy that is formatted for storage (composition text, amount blobs) is produced
here, in the worker process, so the GUI process never loops over alloys in Python.

Provenance travels with the chunk (``with_metadata``): names, sources, design variables, block
indices and the design-coordinate rows of the run's plot table (see ``core/repository.py``).
"""

from __future__ import annotations

from array import array
from collections.abc import Sequence

from .engine import (MODEL_KEYS, NA_ERROR, NA_MISSING_DATA, NA_UNDEFINED, STATUS_DATA_SUSPECT,
                     STATUS_EXTRAPOLATED, STATUS_IN_DOMAIN, AlloyResult)
from .family import family_key
from .results import COLUMNS, composition_text

# stored result columns only: Run and Variables (2026-10-28) are read from run_id and the design tables
NUM_KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS if c.kind == "num" and c.stored)
TEXT_KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS if c.kind == "text" and c.stored
                                   and c.key not in ("name", "composition"))
NAN = float("nan")

# Storage codes (schema 2).  SQL stores NULL for "none" (-1 in a chunk).
STATUS_CODES = {STATUS_IN_DOMAIN: 0, STATUS_EXTRAPOLATED: 1, STATUS_DATA_SUSPECT: 2}
STATUS_NAMES = {v: k for k, v in STATUS_CODES.items()}
NA_CODES = {NA_MISSING_DATA: 1, NA_UNDEFINED: 2, NA_ERROR: 3}
NA_NAMES = {v: k for k, v in NA_CODES.items()}


class _Strings:
    """Per-chunk string table: code 0 is ``None``."""

    def __init__(self):
        self.table: list[str | None] = [None]
        self.index: dict[str | None, int] = {None: 0}

    def code(self, s: str | None) -> int:
        c = self.index.get(s)
        if c is None:
            c = self.index[s] = len(self.table)
            self.table.append(s)
        return c


def amounts_blob(inputs: Sequence[float], fractions: Sequence[float]) -> bytes:
    """Input amounts then normalised fractions (same element order), little-endian float64."""
    return array("d", list(inputs) + list(fractions)).tobytes()


def decode_amounts(elements: Sequence[str], blob: bytes) -> tuple[dict[str, float], dict[str, float]]:
    """(input amounts, positive normalised fractions) from :func:`amounts_blob`."""
    a = array("d")
    a.frombytes(blob)
    k = len(elements)
    return dict(zip(elements, a[:k])), {e: v for e, v in zip(elements, a[k:2 * k]) if v > 0}


def pack_results(compositions: Sequence[dict], results: Sequence[AlloyResult]) -> dict:
    """Columnar chunk of calculated results (picklable, cheap to unpickle and store)."""
    strings = _Strings()
    elements: list[tuple[str, ...]] = []
    el_index: dict[tuple[str, ...], int] = {}
    el_idx = array("I")
    comp_text: list[str] = []
    blobs: list[bytes] = []
    num = {k: array("d") for k in NUM_KEYS}
    text = {k: array("H") for k in TEXT_KEYS}
    labels = {k: array("H") for k in MODEL_KEYS}
    notes = {k: array("H") for k in MODEL_KEYS}
    status = {k: array("b") for k in MODEL_KEYS}
    na_kind = {k: array("b") for k in MODEL_KEYS}
    warnings, errors, temps = array("H"), array("H"), array("d")
    families: list[str] = []
    fam_index: dict[str, int] = {}
    fam_idx, n_els = array("i"), array("b")
    for comp, res in zip(compositions, results):
        els = tuple(str(e).strip() for e in comp)
        i = el_index.get(els)
        if i is None:
            i = el_index[els] = len(elements)
            elements.append(els)
        el_idx.append(i)
        frac = res.composition
        blobs.append(amounts_blob([float(v) for v in comp.values()], [frac.get(e, 0.0) for e in els]))
        comp_text.append(composition_text(frac))
        d = res.descriptors
        for k in NUM_KEYS:
            v = d.get(k)
            num[k].append(NAN if v is None else float(v))
        for k in TEXT_KEYS:
            v = d.get(k)
            text[k].append(strings.code(None if v is None else str(v)))
        for k in MODEL_KEYS:
            o = res.models.get(k)
            labels[k].append(strings.code(o.label if o else None))
            notes[k].append(strings.code((o.reason or o.caution or None) if o else None))
            if o is None:                       # not evaluated at all (engine error)
                status[k].append(-1)
                na_kind[k].append(NA_CODES[NA_ERROR] if res.error else -1)
            elif o.na_kind is not None:         # N/A verdict
                status[k].append(-1)
                na_kind[k].append(NA_CODES[o.na_kind])
            else:
                status[k].append(STATUS_CODES[o.status])
                na_kind[k].append(-1)
        fkey = family_key(frac) if res.ok else None
        if fkey is None:
            fam_idx.append(-1)
            n_els.append(-1)
        else:
            j = fam_index.get(fkey)
            if j is None:
                j = fam_index[fkey] = len(families)
                families.append(fkey)
            fam_idx.append(j)
            n_els.append(fkey.count("-") + 1)
        warnings.append(strings.code(" ".join(res.warnings) or None))
        errors.append(strings.code(res.error))
        temps.append(NAN if res.temperature is None else float(res.temperature))
    return {"n": len(results), "strings": strings.table, "elements": elements, "el_idx": el_idx,
            "comp": comp_text, "amounts": blobs, "num": num, "text": text, "labels": labels, "notes": notes,
            "status": status, "na_kind": na_kind, "families": families, "fam_idx": fam_idx, "n_els": n_els,
            "warnings": warnings, "errors": errors, "temps": temps, "cancelled": False}


def with_metadata(chunk: dict, names: Sequence[str], sources: Sequence[str] | str,
                  variables: Sequence[dict] | None = None, blocks: Sequence[int] | None = None,
                  design: array | None = None) -> dict:
    """Attach per-alloy provenance (first ``chunk['n']`` entries of each sequence)."""
    n = chunk["n"]
    chunk["names"] = [str(x or "") for x in list(names)[:n]]
    chunk["sources"] = sources if isinstance(sources, str) else list(sources)[:n]
    chunk["variables"] = list(variables)[:n] if variables is not None else None
    chunk["blocks"] = list(blocks)[:n] if blocks is not None else None
    chunk["design"] = design
    return chunk


def chunk_rows(chunk: dict) -> int:
    return chunk["n"]
