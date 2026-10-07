"""Columnar result store: the backing data of the results table, independent of Qt.

A 100 000-row sweep kept as ``ResultRow`` objects (full ``AlloyResult`` with descriptor and model
dicts) measured 5.8 KiB per row - 565 MiB.  The table only needs what it displays, sorts, filters,
copies and exports, so the store keeps exactly that, column by column:

* every numeric table column as an ``array('d')`` (``None`` stored as NaN; the engine never yields
  NaN for a table column - undefined values are ``None`` - so NaN reads back as ``None``);
* text/label columns (crystal structure, M1-M8 labels, model notes, warnings, errors, sources) as
  small integer codes into one interned string table;
* input amounts and normalised atomic fractions as flat ``array('d')`` slices over an interned
  element-tuple table.

Row identity is the insertion index (``row id``), stable for the lifetime of the store: sorting,
filtering and paging only permute an ``array('I')`` of ids.  Deleted rows are tombstoned.

The full :class:`~hea_calc.core.engine.AlloyResult` (every descriptor, model value and reason) is
reproduced on demand for one row - Calculation details, the details window - by re-running the
engine on the stored inputs with the stored options: the engine is deterministic and evaluates
one alloy in about 0.5 ms, so nothing is cached per row.

Chunks produced in worker processes use the same layout (:func:`pack_results`), so ingestion is a
handful of C-level ``array.extend`` calls plus a code remap.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Iterable, Sequence

from .engine import MODEL_KEYS, NA, AlloyResult
from .results import COLUMN_BY_KEY, COLUMNS, ModelFilter, RangeFilter, ResultRow, composition_text, format_cell

NUM_KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS if c.kind == "num")
TEXT_KEYS: tuple[str, ...] = tuple(c.key for c in COLUMNS if c.kind == "text" and c.key not in ("name", "composition"))
NAN = float("nan")


# ---------------------------------------------------------------------- packing (worker side)
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


def pack_results(compositions: Sequence[dict], results: Sequence[AlloyResult]) -> dict:
    """Columnar chunk of calculated results (picklable, cheap to unpickle and ingest)."""
    strings = _Strings()
    elements: list[tuple[str, ...]] = []
    el_index: dict[tuple[str, ...], int] = {}
    el_idx, in_vals, fr_vals = array("I"), array("d"), array("d")
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
        for e, v in zip(els, comp.values()):
            in_vals.append(float(v))
            fr_vals.append(frac.get(e, 0.0))
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
            "in_vals": in_vals, "fr_vals": fr_vals, "num": num, "text": text, "labels": labels,
            "notes": notes, "warnings": warnings, "errors": errors, "temps": temps}


# ---------------------------------------------------------------------- store
class ResultStore:
    """All calculated rows (see module docstring).  Not thread-safe: owned by the GUI thread."""

    def __init__(self, engine=None):
        self.engine = engine
        self.clear()

    def clear(self) -> None:
        self.names: list[str] = []
        self.sources = array("H")
        self.variables: list[dict | None] = []
        self.options_idx = array("H")
        self.options: list[dict] = []
        self._options_key: dict[tuple, int] = {}
        self.strings: list[str | None] = [None]
        self._string_index: dict[str | None, int] = {None: 0}
        self.elements: list[tuple[str, ...]] = []
        self._element_index: dict[tuple[str, ...], int] = {}
        self.el_idx = array("I")
        self.offsets = array("Q", [0])
        self.in_vals = array("d")
        self.fr_vals = array("d")
        self.num = {k: array("d") for k in NUM_KEYS}
        self.text = {k: array("H") for k in TEXT_KEYS}
        self.labels = {k: array("H") for k in MODEL_KEYS}
        self.notes = {k: array("H") for k in MODEL_KEYS}
        self.warnings = array("H")
        self.errors = array("H")
        self.temps = array("d")
        self.alive = bytearray()
        self.n_alive = 0
        self.version = getattr(self, "version", 0) + 1     # bumps on clear(): ids from before are void

    # ------------------------------------------------------------------ size
    def __len__(self) -> int:
        return len(self.names)

    def is_alive(self, rid: int) -> bool:
        return 0 <= rid < len(self.alive) and bool(self.alive[rid])

    def nbytes(self) -> int:
        """Approximate size of the column buffers (strings and names counted by length)."""
        arrays = [self.sources, self.options_idx, self.el_idx, self.offsets, self.in_vals, self.fr_vals,
                  self.warnings, self.errors, self.temps, *self.num.values(), *self.text.values(),
                  *self.labels.values(), *self.notes.values()]
        n = sum(a.itemsize * len(a) for a in arrays) + len(self.alive)
        n += sum(49 + len(s) + 8 for s in self.names) + 8 * len(self.variables)
        return n

    # ------------------------------------------------------------------ interning
    def _code(self, s: str | None) -> int:
        c = self._string_index.get(s)
        if c is None:
            c = self._string_index[s] = len(self.strings)
            self.strings.append(s)
        return c

    def _options_code(self, options: dict | None) -> int:
        options = dict(options or {})
        key = tuple(sorted(options.items()))
        c = self._options_key.get(key)
        if c is None:
            c = self._options_key[key] = len(self.options)
            self.options.append(options)
        return c

    def string(self, code: int) -> str | None:
        return self.strings[code]

    # ------------------------------------------------------------------ ingestion
    def append_chunk(self, chunk: dict, names: Sequence[str], sources: Sequence[str],
                     variables: Sequence[dict | None], options: dict | None) -> range:
        """Append a :func:`pack_results` chunk; returns the new row ids."""
        n = chunk["n"]
        start = len(self.names)
        remap = [self._code(s) for s in chunk["strings"]]
        identity = all(i == c for i, c in enumerate(remap))

        def codes(a: array) -> array:
            return a if identity else array("H", [remap[c] for c in a])

        el_remap = []
        for els in chunk["elements"]:
            i = self._element_index.get(els)
            if i is None:
                i = self._element_index[els] = len(self.elements)
                self.elements.append(els)
            el_remap.append(i)
        self.el_idx.extend(array("I", [el_remap[i] for i in chunk["el_idx"]]))
        off = self.offsets[-1]
        for i in chunk["el_idx"]:
            off += len(chunk["elements"][i])
            self.offsets.append(off)
        self.in_vals.extend(chunk["in_vals"])
        self.fr_vals.extend(chunk["fr_vals"])
        for k in NUM_KEYS:
            self.num[k].extend(chunk["num"][k])
        for k in TEXT_KEYS:
            self.text[k].extend(codes(chunk["text"][k]))
        for k in MODEL_KEYS:
            self.labels[k].extend(codes(chunk["labels"][k]))
            self.notes[k].extend(codes(chunk["notes"][k]))
        self.warnings.extend(codes(chunk["warnings"]))
        self.errors.extend(codes(chunk["errors"]))
        self.temps.extend(chunk["temps"])
        self.names.extend(str(x or "") for x in names[:n])
        self.sources.extend(array("H", [self._code(s) for s in sources[:n]]))
        self.variables.extend((dict(v) if v else None) for v in variables[:n])
        self.options_idx.extend(array("H", [self._options_code(options)]) * n)
        self.alive.extend(b"\x01" * n)
        self.n_alive += n
        return range(start, start + n)

    def append_results(self, rows: Iterable[ResultRow], options: dict | None = None) -> range:
        """Append already-calculated rows (single composition, tests, tools)."""
        rows = list(rows)
        chunk = pack_results([r.input_amounts for r in rows], [r.result for r in rows])
        return self.append_chunk(chunk, [r.name for r in rows], [r.source for r in rows],
                                 [r.variables for r in rows], options)

    def remove(self, ids: Iterable[int]) -> None:
        for rid in ids:
            if self.is_alive(rid):
                self.alive[rid] = 0
                self.n_alive -= 1

    def ids(self) -> array:
        """Alive row ids in insertion order."""
        if self.n_alive == len(self.alive):
            return array("I", range(len(self.alive)))
        return array("I", (i for i, a in enumerate(self.alive) if a))

    # ------------------------------------------------------------------ cell access
    def input_amounts(self, rid: int) -> dict[str, float]:
        a, b = self.offsets[rid], self.offsets[rid + 1]
        return dict(zip(self.elements[self.el_idx[rid]], self.in_vals[a:b]))

    def fractions(self, rid: int) -> dict[str, float]:
        """Normalised atomic fractions (the engine's ``AlloyResult.composition``; empty on error)."""
        a, b = self.offsets[rid], self.offsets[rid + 1]
        return {e: v for e, v in zip(self.elements[self.el_idx[rid]], self.fr_vals[a:b]) if v > 0}

    def error(self, rid: int) -> str | None:
        return self.strings[self.errors[rid]]

    def ok(self, rid: int) -> bool:
        return self.errors[rid] == 0

    def raw(self, rid: int, key: str):
        if key == "name":
            return self.names[rid]
        if key == "composition":
            return composition_text(self.fractions(rid))
        col = self.num.get(key)
        if col is not None:
            v = col[rid]
            return None if v != v else v
        if key in self.labels:
            return self.strings[self.labels[key][rid]]
        if key in self.text:
            return self.strings[self.text[key][rid]]
        return None

    def model_label(self, rid: int, key: str) -> str:
        return self.strings[self.labels[key][rid]] or NA

    def model_note(self, rid: int, key: str) -> str:
        return self.strings[self.notes[key][rid]] or ""

    def row(self, rid: int) -> "StoredRow":
        return StoredRow(self, rid)

    def result(self, rid: int) -> AlloyResult:
        """The complete engine result for one row, reproduced from its inputs and options."""
        if self.engine is None:
            raise RuntimeError("ResultStore has no engine to reproduce a full result.")
        return self.engine.calculate(self.input_amounts(rid), **self.options[self.options_idx[rid]])

    # ------------------------------------------------------------------ view building
    def filter_ids(self, ids: Sequence[int], filters: list) -> array:
        """Ids passing every filter.  Range and model filters read the columns directly."""
        out = array("I", ids)
        for f in filters:
            if isinstance(f, RangeFilter) and f.key in self.num:
                col, lo, hi = self.num[f.key], f.minimum, f.maximum
                ok = self.errors
                out = array("I", (i for i in out if ok[i] == 0 and col[i] == col[i]
                                  and (lo is None or col[i] >= lo) and (hi is None or col[i] <= hi)))
            elif isinstance(f, ModelFilter) and f.key in self.labels:
                accepted = {self._string_index[s] for s in f.labels if s in self._string_index}
                if NA in f.labels:
                    accepted.add(0)
                col = self.labels[f.key]
                out = array("I", (i for i in out if col[i] in accepted))
            else:
                out = array("I", (i for i in out if f.accepts(StoredRow(self, i))))
        return out

    def sort_ids(self, ids: Sequence[int], key: str, descending: bool) -> array:
        """Stable sort; missing values (None / N/A numbers) always last, as in the original table."""
        ids = list(ids)
        col = self.num.get(key)
        if col is not None:
            ok = self.errors
            present = [i for i in ids if ok[i] == 0 and col[i] == col[i]]
            missing = [i for i in ids if not (ok[i] == 0 and col[i] == col[i])]
            present.sort(key=col.__getitem__, reverse=descending)
            return array("I", present + missing)
        if key == "name":
            vals = self.names
            getter = vals.__getitem__
        elif key == "composition":
            cache = {i: self.raw(i, "composition") for i in ids}
            getter = cache.__getitem__
        else:
            codes = self.labels.get(key) or self.text.get(key)
            if codes is None:
                return array("I", ids)
            strings = self.strings
            present = [i for i in ids if codes[i]]
            missing = [i for i in ids if not codes[i]]
            present.sort(key=lambda i: strings[codes[i]], reverse=descending)
            return array("I", present + missing)
        ids.sort(key=getter, reverse=descending)
        return array("I", ids)


class StoredRow:
    """A row of a :class:`ResultStore`, created on demand (the store never holds row objects).

    Implements the row protocol used by formatting, filters, clipboard and export
    (``name``, ``source``, ``raw``, ``ok``, ``composition``, ``model_label``, ``model_note``,
    ``warnings``, ``error``); ``result`` reproduces the full engine result.
    """

    __slots__ = ("store", "id", "_version")

    def __init__(self, store: ResultStore, rid: int):
        self.store, self.id, self._version = store, rid, store.version

    def __eq__(self, other):
        return isinstance(other, StoredRow) and other.store is self.store and other.id == self.id \
            and other._version == self._version

    def __hash__(self):
        return hash((id(self.store), self.id, self._version))

    def __repr__(self):
        return f"StoredRow({self.id}, {self.name!r})"

    @property
    def valid(self) -> bool:
        return self._version == self.store.version and self.store.is_alive(self.id)

    @property
    def name(self) -> str:
        return self.store.names[self.id]

    @property
    def source(self) -> str:
        return self.store.strings[self.store.sources[self.id]] or ""

    @property
    def variables(self) -> dict:
        return dict(self.store.variables[self.id] or {})

    @property
    def input_amounts(self) -> dict[str, float]:
        return self.store.input_amounts(self.id)

    @property
    def composition(self) -> dict[str, float]:
        return self.store.fractions(self.id)

    @property
    def ok(self) -> bool:
        return self.store.ok(self.id)

    @property
    def error(self) -> str | None:
        return self.store.error(self.id)

    @property
    def warnings(self) -> list[str]:
        w = self.store.strings[self.store.warnings[self.id]]
        return [w] if w else []

    @property
    def temperature(self) -> float | None:
        v = self.store.temps[self.id]
        return None if v != v else v

    def raw(self, key: str):
        return self.store.raw(self.id, key)

    def model_label(self, key: str) -> str:
        return self.store.model_label(self.id, key)

    def model_note(self, key: str) -> str:
        return self.store.model_note(self.id, key)

    def display(self, key: str) -> str:
        return format_cell(self, key)

    @property
    def result(self) -> AlloyResult:
        return self.store.result(self.id)

    def materialize(self) -> ResultRow:
        """A full :class:`ResultRow` (engine result reproduced) - for Calculation details."""
        return ResultRow(self.name, self.input_amounts, self.result, self.source, self.variables, row_id=self.id)


_ = (math, COLUMN_BY_KEY)
