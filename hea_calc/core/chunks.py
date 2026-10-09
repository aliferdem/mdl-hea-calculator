"""Columnar result chunks: what calculation workers send back (picklable, no Qt, no SQLite).

A chunk carries exactly what the results repository stores for each alloy, column by column, so the
single database writer only re-maps a few string codes and hands the columns to ``executemany``:

* every numeric table column as an ``array('d')`` (``None`` stored as NaN - SQLite stores a bound
  NaN as NULL, and the engine never yields NaN for a table column);
* text/label columns (crystal structure, M1-M8 labels, model notes, warnings, errors) as small
  integer codes into the chunk's own string table (code 0 is ``None``);
* per alloy: its element order (an index into ``elements``), the composition text shown in the
  table, and the input amounts followed by the normalised atomic fractions as one ``float64`` blob.

Everything per-alloy that is formatted for storage (composition text, amount blobs) is produced
here, in the worker process, so the GUI process never loops over alloys in Python.

Provenance travels with the chunk (``with_metadata``): names, sources, design variables, block
indices and the design-coordinate rows of the run's plot table (see ``core/repository.py``).
"""

from __future__ import annotations

from array import array
from collections.abc import Sequence

from .engine import MODEL_KEYS, AlloyResult
from .results import COLUMNS, composition_text

NUM_KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS if c.kind == "num")
TEXT_KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS if c.kind == "text" and c.key not in ("name", "composition"))
NAN = float("nan")


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
    warnings, errors, temps = array("H"), array("H"), array("d")
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
        warnings.append(strings.code(" ".join(res.warnings) or None))
        errors.append(strings.code(res.error))
        temps.append(NAN if res.temperature is None else float(res.temperature))
    return {"n": len(results), "strings": strings.table, "elements": elements, "el_idx": el_idx,
            "comp": comp_text, "amounts": blobs, "num": num, "text": text, "labels": labels, "notes": notes,
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
