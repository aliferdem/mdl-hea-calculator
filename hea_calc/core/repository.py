"""SQLite result repository: the calculation dataset lives on disk; the table is a view of it.

No Qt here.  Measured design decisions (``design/implementation/performance.md``):

Files
    One session directory per running application, ``%TEMP%/HEA Calculator/session-<uuid>/``:
    ``results.sqlite`` (the dataset) and ``views.sqlite`` (materialised table orders), both WAL.
    The directory is deleted on close; a directory left by a crash is removed at the next start
    (on Windows a live session's open files cannot be deleted, so only dead sessions go).

Concurrency (one writer, readers never block it)
    * the writer *process* (:func:`writer_main`, handle :class:`ResultWriter`) owns the only write
      connection to ``results.sqlite``.  Calculation workers put their chunks straight into its
      queue (they never open the database for writing; the GUI process never touches a chunk);
      chunks are stored strictly in chunk order, inserted with ``executemany`` and committed in
      batches (time/row bounded), so readers see whole committed batches only.  The committed
      frontier and counters are shared memory.
    * :class:`ViewBuilder` - a thread owning the only write connection to ``views.sqlite``; it
      materialises the table order of a filter/sort (``INSERT INTO v(rid) SELECT ... ORDER BY``)
      in C, with the GIL released, and can be interrupted when superseded.
    * the GUI thread reads through :class:`Reader` (``query_only``): page fetches, single records.
    * worker processes may open the database read-only (export, recalculation input).

Identity
    ``result_id`` (``INTEGER PRIMARY KEY``) is assigned by the writer in arrival order, is never
    reused within a session and is the only identity of a result.  A visible row index never is.

Schema 2 (Analysis data contract, ``docs/analysis-redesign/ANALYSIS_DATA_CONTRACT.md``)
    * ``results.status_M1..M8`` - evidence status of an evaluated verdict (``chunks.STATUS_CODES``:
      0 in domain, 1 extrapolated, 2 flagged data); NULL when the verdict is N/A;
    * ``results.na_kind_M1..M8`` - why a verdict is N/A (``chunks.NA_CODES``: 1 missing data,
      2 undefined, 3 not evaluable); NULL when evaluated;
    * ``results.family_id`` -> ``families(family_id, key, size)`` (canonical element family,
      ``core/family.py``) and ``results.n_elements``; NULL for a row that could not be evaluated;
    * ``runs.app_version``, ``runs.engine_version``, ``runs.dataset_ids`` (``core/provenance.py``).
    Session databases are temporary and always created by this version; a database that reports
    another schema version is refused by :func:`check_schema` rather than misread.

Table views (:class:`ResultView`)
    * natural order (no filter, no sort): the workspace is the contiguous id range ``lo..hi``
      minus the ids the user removed - pages are ``WHERE result_id >= ? LIMIT n`` (O(page));
    * filter and/or sort: a materialised ``(pos INTEGER PRIMARY KEY, rid)`` table built once per
      state; pages are ``pos >= ? LIMIT n`` joined to ``results`` (O(page)).  A removed row keeps
      its position (the join drops it); removed positions are skipped arithmetically.
    ``OFFSET`` paging is never used: measured 8.4 s for a mid page of 1 M sorted rows.
"""

from __future__ import annotations

import bisect
import datetime as _dt
import itertools
import json
import math
import os
import queue
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from array import array
from collections import OrderedDict
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from itertools import repeat
from pathlib import Path

from .chunks import NUM_KEYS, TEXT_KEYS, decode_amounts, pack_results, with_metadata
from .engine import MODEL_KEYS, NA, AlloyResult
from .results import COLUMN_BY_KEY, IdSetFilter, ModelFilter, RangeFilter, ResultRow, format_cell

SCHEMA_VERSION = 2
APP_DIR_NAME = "HEA Calculator"
NOTE_COLS = tuple(f"n_{k}" for k in MODEL_KEYS)
STATUS_COLS = tuple(f"status_{k}" for k in MODEL_KEYS)
NA_COLS = tuple(f"na_kind_{k}" for k in MODEL_KEYS)
RECORD_COLS: tuple[str, ...] = ("result_id", "run_id", "seq", "block", "src", "name", "comp", "elset", "amounts",
                                *NUM_KEYS, *TEXT_KEYS, *MODEL_KEYS, *NOTE_COLS, "warn", "err", "temp",
                                *STATUS_COLS, *NA_COLS, "family_id", "n_elements")
COL = {c: i for i, c in enumerate(RECORD_COLS)}
_I_ID, _I_RUN, _I_SEQ, _I_BLOCK, _I_SRC, _I_NAME, _I_COMP, _I_ELSET, _I_AMOUNTS = range(9)
_I_WARN, _I_ERR, _I_TEMP = COL["warn"], COL["err"], COL["temp"]
_I_FAMILY, _I_NEL = COL["family_id"], COL["n_elements"]

COMMIT_ROWS = 20_000          # rows per write transaction at most
COMMIT_SECONDS = 0.25         # ... and at most this long before committed rows become visible
MAX_AHEAD_CHUNKS = 64         # writer back-pressure: chunks calculated but not yet stored (≈ 0.3 s of inserts)
CLEAR_BATCH = 50_000          # rows deleted per transaction by a background clear
SYNC_WAIT_S = 0.075           # a view build finishing within this is applied synchronously (gap < 100 ms)
POSITION_SCAN_MAX = 1_000_000  # position lookup by scan in a sorted view (≈ 50 ms per 1 M rows)


def q(name: str) -> str:
    """Quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


_SELECT = ", ".join(q(c) for c in RECORD_COLS)
_SELECT_R = ", ".join("r." + q(c) for c in RECORD_COLS)


class RepositoryError(RuntimeError):
    """A storage failure, with a message fit for the user (never a raw SQLite message)."""


def user_message(exc: BaseException) -> str:
    """Plain-language description of a storage failure."""
    text = str(exc).lower()
    if isinstance(exc, RepositoryError):
        return str(exc)
    if "full" in text:
        return "The disk holding the temporary results database is full."
    if "disk i/o" in text or "ioerr" in text:
        return "A disk error occurred while saving results."
    if "locked" in text or "busy" in text:
        return "The results database is busy."
    if "malformed" in text or "not a database" in text or "no such table" in text or "corrupt" in text:
        return "The results database became unreadable."
    if "readonly" in text or "read-only" in text or "permission" in text or "access" in text:
        return "The results database could not be written (no permission)."
    return "Results could not be saved."


# ====================================================================== session files
def session_roots() -> list[Path]:
    """Candidate folders for session databases, most preferred first."""
    roots = [Path(tempfile.gettempdir()) / APP_DIR_NAME]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / APP_DIR_NAME / "sessions")
    roots.append(Path.home() / ".hea-calculator" / "sessions")
    return roots


def cleanup_stale_sessions(root: Path, keep: Path | None = None) -> int:
    """Delete session folders left by sessions that are no longer running; returns how many."""
    removed = 0
    if not root.is_dir():
        return 0
    for d in root.glob("session-*"):
        if keep is not None and d.resolve() == keep.resolve():
            continue
        pid_file = d / "owner.pid"
        if os.name != "nt":
            try:
                pid = int(pid_file.read_text().split()[0])
                os.kill(pid, 0)
                continue                      # owner alive
            except (OSError, ValueError, IndexError):
                pass
        try:
            # Windows refuses to delete a file another process has open: a live session survives.
            for f in sorted(d.iterdir(), key=lambda p: p.name != "results.sqlite"):
                f.unlink()
            d.rmdir()
            removed += 1
        except OSError:
            continue
    return removed


def _make_session_dir(root: Path | None) -> Path:
    errors = []
    for r in ([root] if root else session_roots()):
        try:
            r.mkdir(parents=True, exist_ok=True)
            cleanup_stale_sessions(r)
            d = r / f"session-{uuid.uuid4().hex}"
            d.mkdir()
            (d / "owner.pid").write_text(f"{os.getpid()} {time.time():.0f}")
            return d
        except OSError as exc:
            errors.append(f"{r}: {exc}")
    raise RepositoryError("No folder for the temporary results database could be created ("
                          + "; ".join(errors) + ").")


def _connect(path: Path | str, *, readonly: bool = False, same_thread: bool = True,
             cache_kib: int = 16_384) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, isolation_level=None,
                              check_same_thread=same_thread, timeout=10)
    else:
        con = sqlite3.connect(str(path), isolation_level=None, check_same_thread=same_thread, timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    con.execute(f"PRAGMA cache_size=-{cache_kib}")
    return con


_RESULTS_DDL = (
    "CREATE TABLE IF NOT EXISTS results(result_id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, "
    "seq INTEGER NOT NULL, block INTEGER, src INTEGER, name TEXT, comp TEXT, elset INTEGER, amounts BLOB, "
    + ", ".join(f"{q(k)} REAL" for k in NUM_KEYS) + ", "
    + ", ".join(f"{q(k)} TEXT" for k in (*TEXT_KEYS, *MODEL_KEYS)) + ", "
    + ", ".join(f"{q(k)} INTEGER" for k in NOTE_COLS)
    + ", warn INTEGER, err INTEGER NOT NULL DEFAULT 0, temp REAL, "
    + ", ".join(f"{q(k)} INTEGER" for k in (*STATUS_COLS, *NA_COLS))
    + ", family_id INTEGER, n_elements INTEGER)")

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS runs(run_id INTEGER PRIMARY KEY, mode TEXT NOT NULL, label TEXT, "
    "status TEXT NOT NULL, created TEXT, finished TEXT, expected INTEGER, calculated INTEGER NOT NULL DEFAULT 0, "
    "first_id INTEGER, last_id INTEGER, settings TEXT, source TEXT, axes TEXT, elements TEXT, message TEXT, "
    "cleared TEXT, errors INTEGER NOT NULL DEFAULT 0, app_version TEXT, engine_version TEXT, dataset_ids TEXT)",
    "CREATE TABLE IF NOT EXISTS strings(code INTEGER PRIMARY KEY, s TEXT NOT NULL UNIQUE)",
    "CREATE TABLE IF NOT EXISTS elsets(id INTEGER PRIMARY KEY, els TEXT NOT NULL UNIQUE)",
    "CREATE TABLE IF NOT EXISTS families(family_id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, size INTEGER)",
    _RESULTS_DDL,
]


def design_table(run_id: int) -> str:
    return f"design_{int(run_id)}"


# ====================================================================== small LRU
class LRU(OrderedDict):
    def __init__(self, maxsize: int):
        super().__init__()
        self.maxsize = maxsize

    def get(self, key, default=None):
        if key in self:
            self.move_to_end(key)
            return self[key]
        return default

    def put(self, key, value):
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.maxsize:
            self.popitem(last=False)


# ====================================================================== runs
@dataclass
class RunInfo:
    run_id: int
    mode: str
    label: str | None = None
    status: str = "running"
    created: str | None = None
    finished: str | None = None
    expected: int | None = None
    calculated: int = 0
    first_id: int | None = None
    last_id: int | None = None
    settings: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    axes: list = field(default_factory=list)
    elements: list = field(default_factory=list)
    message: str | None = None
    cleared: str | None = None
    errors: int = 0                 # results that could not be evaluated (engine error)
    app_version: str | None = None
    engine_version: str | None = None
    dataset_ids: dict = field(default_factory=dict)

    @staticmethod
    def from_row(r) -> "RunInfo":
        def js(x, default):
            return json.loads(x) if x else default
        return RunInfo(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7] or 0, r[8], r[9], js(r[10], {}),
                       js(r[11], {}), js(r[12], []), js(r[13], []), r[14], r[15], r[16] or 0,
                       r[17], r[18], js(r[19], {}))

    def axis(self, name: str) -> dict | None:
        return next((a for a in self.axes if a["name"] == name), None)


_RUN_COLS = ("run_id, mode, label, status, created, finished, expected, calculated, first_id, last_id, settings, "
             "source, axes, elements, message, cleared, errors, app_version, engine_version, dataset_ids")


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# ====================================================================== writer (its own process)
# Measured: a writer *thread* converting and inserting chunks shares the GIL with the GUI thread and
# raised the longest event-loop gap of a 94 k-alloy run from ~90 ms to ~200 ms (every Qt -> Python
# callback queues behind it).  The writer is therefore a process: calculation workers put their
# chunks straight into its queue, so the GUI process never unpickles, converts or inserts a result.
_S_COMMITTED, _S_ROWS, _S_COMMITS, _S_INSERT_S, _S_RUN, _S_RUN_COUNT, _S_RUN_NEXT, _S_READY = range(8)
FINALIZE_WAIT_S = 30.0       # a finalize waits this long for chunks still in transit, then closes the run


def check_schema(con: sqlite3.Connection) -> int:
    """The database's schema version; raises :class:`RepositoryError` unless it is this version's."""
    row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    version = int(row[0]) if row and str(row[0]).isdigit() else 0
    if version != SCHEMA_VERSION:
        raise RepositoryError(f"The results database has schema version {version}; this version of the "
                              f"calculator reads version {SCHEMA_VERSION}.")
    return version


def _init_database(db_path: Path) -> int:
    """Create the schema (WAL) and return the highest stored result id."""
    con = _connect(db_path)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        for ddl in _SCHEMA:
            con.execute(ddl)
        con.execute("INSERT OR IGNORE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        check_schema(con)
        con.execute("INSERT OR IGNORE INTO meta VALUES('created', ?)", (_now(),))
        row = con.execute("SELECT COALESCE(MAX(result_id), 0) FROM results").fetchone()
        stored = con.execute("SELECT value FROM meta WHERE key='next_result_id'").fetchone()
        return max(int(row[0]), int(stored[0]) - 1 if stored else 0)
    finally:
        con.close()


@dataclass
class _RunState:
    run_id: int
    design_cols: int = 0
    seq: int = 0
    count: int = 0
    first_id: int | None = None
    last_id: int | None = None
    failed: bool = False
    errors: int = 0
    next_index: int = 0                      # chunks arrive out of order; stored strictly in index order
    buffer: dict = field(default_factory=dict)
    finalize: tuple | None = None            # (req, status, message, upto, deadline) waiting for chunks
    committed: tuple = (0, 0, None, None, 0)  # (seq, count, first_id, last_id, errors) at the last commit

    def snapshot(self) -> None:
        self.committed = (self.seq, self.count, self.first_id, self.last_id, self.errors)

    def restore(self) -> None:
        self.seq, self.count, self.first_id, self.last_id, self.errors = self.committed


class _WriterCore:
    """The single writer of ``results.sqlite``; runs in the writer process (:func:`writer_main`)."""

    def __init__(self, db_path: str, shared, err, inbox):
        self.shared, self.err, self.inbox = shared, err, inbox
        self.error: str | None = None
        self._runs: dict[int, _RunState] = {}
        self._closed_runs: set[int] = set()
        self._strings = LRU(20_000)
        self._elsets = LRU(8_192)
        self._families = LRU(8_192)
        self.delay = 0.0                       # test hooks (inject): a slow or failing disk
        self.fail: str | None = None
        con = _connect(db_path, same_thread=False, cache_kib=16_384)    # append-only: a small cache suffices
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")      # WAL: consistent after a crash, no fsync per commit
        row = con.execute("SELECT COALESCE(MAX(result_id), 0) FROM results").fetchone()
        stored = con.execute("SELECT value FROM meta WHERE key='next_result_id'").fetchone()
        self.next_id = max(int(row[0]) + 1, int(stored[0]) if stored else 1)
        self._con = con
        self.in_txn = False
        self._pending_rows = 0
        self._txn_start = 0.0
        self._txn_first_id = self.next_id
        self.shared[_S_COMMITTED] = self.next_id - 1

    # -------------------------------------------------------------- transactions
    def begin(self) -> None:
        if not self.in_txn:
            self._con.execute("BEGIN")
            self.in_txn = True
            self._pending_rows = 0
            self._txn_start = time.perf_counter()
            self._txn_first_id = self.next_id

    def due(self) -> bool:
        return self.in_txn and (self._pending_rows >= COMMIT_ROWS
                                or time.perf_counter() - self._txn_start >= COMMIT_SECONDS)

    def commit(self) -> None:
        if not self.in_txn:
            return
        try:
            for st in self._runs.values():
                if st.count and st.first_id is not None:
                    self._con.execute("UPDATE runs SET calculated=?, first_id=?, last_id=?, errors=? WHERE run_id=?",
                                      (st.count, st.first_id, st.last_id, st.errors, st.run_id))
            self._con.execute("COMMIT")
        except sqlite3.Error as exc:
            self._fail(exc)
            return
        self.in_txn = False
        sh = self.shared
        sh[_S_COMMITS] += 1
        sh[_S_COMMITTED] = self.next_id - 1
        for st in self._runs.values():
            st.snapshot()
            if sh[_S_RUN] == st.run_id:
                sh[_S_RUN_COUNT] = st.count

    def rollback(self) -> None:
        try:
            self._con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        self.in_txn = False
        # nothing of the batch was committed: its ids and per-run counters are handed out again,
        # so the committed ids stay contiguous
        self.next_id = self._txn_first_id
        for st in self._runs.values():
            st.restore()

    def _fail(self, exc: BaseException) -> None:
        self.rollback()
        if self.error is None:
            self.error = user_message(exc)
            data = self.error.encode("utf-8")[:1000]
            self.err[:len(data)] = data
        for st in self._runs.values():
            st.failed = True

    # -------------------------------------------------------------- interning
    def _string(self, s: str | None) -> int | None:
        if s is None:
            return None
        c = self._strings.get(s)
        if c is None:
            con = self._con
            row = con.execute("SELECT code FROM strings WHERE s=?", (s,)).fetchone()
            c = row[0] if row else con.execute("INSERT INTO strings(s) VALUES(?)", (s,)).lastrowid
            self._strings.put(s, c)
        return c

    def _elset(self, els: tuple[str, ...]) -> int:
        key = ",".join(els)
        c = self._elsets.get(key)
        if c is None:
            con = self._con
            row = con.execute("SELECT id FROM elsets WHERE els=?", (key,)).fetchone()
            c = row[0] if row else con.execute("INSERT INTO elsets(els) VALUES(?)", (key,)).lastrowid
            self._elsets.put(key, c)
        return c

    def _family(self, key: str) -> int:
        c = self._families.get(key)
        if c is None:
            con = self._con
            row = con.execute("SELECT family_id FROM families WHERE key=?", (key,)).fetchone()
            c = row[0] if row else con.execute("INSERT INTO families(key, size) VALUES(?, ?)",
                                               (key, key.count("-") + 1)).lastrowid
            self._families.put(key, c)
        return c

    # -------------------------------------------------------------- chunks
    def chunk(self, run_id: int, index: int | None, chunk: dict) -> None:
        """Store chunk ``index`` of a run; out-of-order chunks wait until their predecessors arrive."""
        st = self._runs.get(run_id)
        if st is None or run_id in self._closed_runs:
            return                                   # a late chunk of a finished (cancelled) run
        if index is None:
            index = st.next_index
        if index != st.next_index:
            st.buffer[index] = chunk
            return
        self._store(st, chunk)
        while st.next_index in st.buffer:
            self._store(st, st.buffer.pop(st.next_index))

    def _store(self, st: _RunState, chunk: dict) -> None:
        st.next_index += 1
        if self.shared[_S_RUN] == st.run_id:
            self.shared[_S_RUN_NEXT] = st.next_index
        if st.failed or not chunk["n"] or self.error:
            return
        if st.finalize is not None and st.next_index > st.finalize[3]:
            return                                   # beyond the prefix the job kept (cancelled)
        t0 = time.perf_counter()
        try:
            self.begin()
            self._insert(st, chunk)
        except Exception as exc:                     # noqa: BLE001 - disk full, I/O error, ...
            self._fail(exc)
            return
        self.shared[_S_INSERT_S] += time.perf_counter() - t0
        if self.due():
            self.commit()

    def _insert(self, st: _RunState, chunk: dict) -> None:
        if self.fail:
            raise sqlite3.OperationalError(self.fail)
        if self.delay:
            time.sleep(self.delay)
        n = chunk["n"]
        con = self._con
        strings = chunk["strings"]
        db = [None] + [self._string(s) for s in strings[1:]]
        els = [self._elset(e) for e in chunk["elements"]]
        first = self.next_id
        ids = range(first, first + n)
        seqs = range(st.seq, st.seq + n)
        src = chunk.get("sources", "")
        srcs = repeat(self._string(src), n) if isinstance(src, str) else [self._string(s) for s in src]
        blocks = chunk.get("blocks") or repeat(None, n)
        names = chunk.get("names") or repeat("", n)
        cols = [ids, repeat(st.run_id, n), seqs, blocks, srcs, names, chunk["comp"],
                [els[i] for i in chunk["el_idx"]], chunk["amounts"]]
        cols += [chunk["num"][k] for k in NUM_KEYS]
        cols += [[strings[c] for c in chunk["text"][k]] for k in TEXT_KEYS]
        cols += [[strings[c] for c in chunk["labels"][k]] for k in MODEL_KEYS]
        cols += [[db[c] for c in chunk["notes"][k]] for k in MODEL_KEYS]
        cols += [[db[c] for c in chunk["warnings"]], [db[c] or 0 for c in chunk["errors"]], chunk["temps"]]
        for group in ("status", "na_kind"):
            arrays = chunk.get(group)
            cols += [[None if c < 0 else c for c in arrays[k]] if arrays else repeat(None, n) for k in MODEL_KEYS]
        fams = chunk.get("families")
        if fams is not None:
            fid = [self._family(f) for f in fams]
            cols.append([None if i < 0 else fid[i] for i in chunk["fam_idx"]])
            cols.append([None if x < 0 else x for x in chunk["n_els"]])
        else:
            cols += [repeat(None, n), repeat(None, n)]
        con.executemany(f"INSERT INTO results VALUES ({','.join('?' * len(RECORD_COLS))})", zip(*cols))
        design = chunk.get("design")
        if st.design_cols and design is not None:
            k = st.design_cols
            con.executemany(f"INSERT INTO {q(design_table(st.run_id))} VALUES ({','.join('?' * (k + 1))})",
                            zip(ids, *[design[j::k] for j in range(k)]))
        self.next_id += n
        st.seq += n
        st.count += n
        st.errors += n - chunk["errors"].count(0)
        if st.first_id is None:
            st.first_id = first
        st.last_id = first + n - 1
        self._pending_rows += n
        self.shared[_S_ROWS] += n

    # -------------------------------------------------------------- finalising runs
    def request_finalize(self, req: int, run_id: int, status: str, message: str | None, upto: int | None):
        """Close a run once its first ``upto`` chunks are stored (None: whatever has arrived)."""
        st = self._runs.get(run_id)
        if st is None:
            return self._finish(run_id, None, status, message)
        upto = st.next_index if upto is None else upto
        st.finalize = (req, status, message, upto, time.perf_counter() + FINALIZE_WAIT_S)
        return self.ready(st)

    def ready(self, st: _RunState, expired: bool = False):
        """``(req, value)`` when the run's pending finalize can be answered, else None."""
        f = st.finalize
        if f is None or (st.next_index < f[3] and not expired):
            return None
        self.commit()
        req, status, message, upto, _deadline = f
        if st.next_index < upto:                     # chunks lost in transit (a worker died)
            status, message = "failed", message or "Some calculated results never reached the database."
        return req, self._finish(st.run_id, st, status, message)

    def pending_finalizers(self, now: float, all_runs: bool = True) -> list:
        out = []
        for st in list(self._runs.values()):
            if st.finalize is not None:
                r = self.ready(st, expired=now >= st.finalize[4])
                if r is not None:
                    out.append(r)
        return out

    def _finish(self, run_id: int, st: _RunState | None, status: str, message: str | None):
        self._runs.pop(run_id, None)
        self._closed_runs.add(run_id)
        if st is not None and st.failed and status != "cancelled":
            status = "failed"
        try:
            if st is not None:
                self._con.execute("UPDATE runs SET status=?, finished=?, message=?, calculated=?, first_id=?, "
                                  "last_id=?, errors=? WHERE run_id=?", (status, _now(), message, st.count,
                                                                         st.first_id, st.last_id, st.errors, run_id))
            else:
                self._con.execute("UPDATE runs SET status=?, finished=?, message=? WHERE run_id=?",
                                  (status, _now(), message, run_id))
        except sqlite3.Error as exc:
            if self.error is None:
                self._fail(exc)
        if self.shared[_S_RUN] == run_id and st is not None:
            self.shared[_S_RUN_COUNT] = st.count
        return {"status": status, "calculated": st.count if st else 0, "first_id": st.first_id if st else None,
                "last_id": st.last_id if st else None, "errors": st.errors if st else 0}

    # -------------------------------------------------------------- commands
    def do_flush(self) -> int:
        return int(self.shared[_S_COMMITTED])

    def do_inject(self, delay: float = 0.0, fail: str | None = None) -> None:
        self.delay, self.fail = delay, fail

    def do_create_run(self, info: RunInfo) -> int:
        con = self._con
        con.execute("BEGIN")
        try:
            cur = con.execute(
                "INSERT INTO runs(mode, label, status, created, expected, settings, source, axes, elements, "
                "app_version, engine_version, dataset_ids) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (info.mode, info.label, "running", _now(), info.expected, json.dumps(info.settings),
                 json.dumps(info.source), json.dumps(info.axes), json.dumps(info.elements),
                 info.app_version, info.engine_version, json.dumps(info.dataset_ids)))
            run_id = cur.lastrowid
            cols = [a["col"] for a in info.axes if a.get("col")]
            if cols:
                con.execute(f"CREATE TABLE {q(design_table(run_id))}(result_id INTEGER PRIMARY KEY, "
                            + ", ".join(f"{q(c)} REAL" for c in cols) + ")")
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        self._runs[run_id] = _RunState(run_id, len(cols))
        sh = self.shared
        sh[_S_RUN], sh[_S_RUN_COUNT], sh[_S_RUN_NEXT] = run_id, 0, 0
        return run_id

    def do_append_sync(self, run_id: int, chunk: dict) -> range:
        st = self._runs.get(run_id)
        if st is None:
            raise RepositoryError("The calculation run is not open.")
        if self.error:
            raise RepositoryError(self.error)
        first = self.next_id
        try:
            self.begin()
            self._insert(st, chunk)
        except Exception as exc:                      # noqa: BLE001
            self._fail(exc)
            raise RepositoryError(self.error or user_message(exc)) from exc
        st.next_index += 1
        self.commit()
        if self.in_txn:                               # commit failed
            raise RepositoryError(self.error or "Results could not be saved.")
        return range(first, first + chunk["n"])

    def do_delete(self, ids: list[int]) -> int:
        con = self._con
        con.execute("BEGIN")
        self.in_txn = True
        self._txn_first_id = self.next_id
        try:
            removed = 0
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                marks = ",".join("?" * len(part))
                runs = {r[0] for r in con.execute(f"SELECT DISTINCT run_id FROM results WHERE result_id IN ({marks})",
                                                  part)}
                removed += con.execute(f"DELETE FROM results WHERE result_id IN ({marks})", part).rowcount
                for run_id in runs:
                    if self._has_design(run_id):
                        con.execute(f"DELETE FROM {q(design_table(run_id))} WHERE result_id IN ({marks})", part)
            con.execute("COMMIT")
        except Exception:
            self.rollback()
            raise
        self.in_txn = False
        return removed

    def _has_design(self, run_id: int) -> bool:
        return self._con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                 (design_table(run_id),)).fetchone() is not None

    def do_clear(self, lo: int, hi: int) -> int:
        """Delete ids ``lo..hi`` in bounded transactions (re-queued, so other commands interleave)."""
        con = self._con
        if hi < lo:
            return 0
        total = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        inside = con.execute("SELECT COUNT(*) FROM results WHERE result_id BETWEEN ? AND ?", (lo, hi)).fetchone()[0]
        runs = [r[0] for r in con.execute(
            "SELECT run_id FROM runs WHERE cleared IS NULL AND first_id IS NOT NULL AND first_id >= ? AND last_id <= ?",
            (lo, hi))]
        con.execute("BEGIN")
        self.in_txn = True
        self._txn_first_id = self.next_id
        try:
            if inside == total:
                con.execute("DELETE FROM results")             # truncate optimisation: frees pages wholesale
                done_to = hi
            else:
                done_to = min(hi, lo + CLEAR_BATCH - 1)
                con.execute("DELETE FROM results WHERE result_id BETWEEN ? AND ?", (lo, done_to))
            for run_id in runs:
                if done_to >= hi:
                    con.execute(f"DROP TABLE IF EXISTS {q(design_table(run_id))}")
                    con.execute("UPDATE runs SET cleared=? WHERE run_id=?", (_now(), run_id))
            con.execute("COMMIT")
        except Exception:
            self.rollback()
            raise
        self.in_txn = False
        if done_to < hi:
            self.inbox.put(("cmd", 0, "clear", (done_to + 1, hi)))
        elif con.execute("SELECT 1 FROM results LIMIT 1").fetchone() is None:
            # nothing left: give the space back (VACUUM of an empty table is quick; 10 M cleared rows
            # otherwise keep a 4 GB file until the session ends)
            try:
                con.execute("VACUUM")
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
        return inside

    def close(self) -> None:
        self.commit()
        try:
            # a run still open was interrupted (application closed): its committed rows form a valid
            # partial run, recoverable from the file if it is kept
            self._con.execute("UPDATE runs SET status='interrupted', finished=? WHERE status='running'", (_now(),))
            self._con.execute("INSERT OR REPLACE INTO meta VALUES('next_result_id', ?)", (str(self.next_id),))
            self._con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self._con.close()


def writer_main(db_path: str, inbox, replies, shared, err) -> None:                # pragma: no cover - child
    """Entry point of the writer process: chunks and commands from one queue, replies on another."""
    from .jobs import _watch_parent
    _watch_parent()
    try:
        core = _WriterCore(db_path, shared, err, inbox)
    except Exception as exc:                          # noqa: BLE001 - reported to every caller
        data = user_message(exc).encode("utf-8")[:1000]
        err[:len(data)] = data
        shared[_S_READY] = -1
        return
    shared[_S_READY] = 1
    while True:
        waiting = any(st.finalize is not None for st in core._runs.values())
        try:
            item = inbox.get(timeout=0.02 if (core.in_txn or waiting) else None)
        except queue.Empty:
            core.commit()
            for req, value in core.pending_finalizers(time.perf_counter()):
                replies.put((req, True, value))
            continue
        if item[0] == "chunk":
            _kind, run_id, index, chunk = item
            core.chunk(run_id, index, chunk)
            st = core._runs.get(run_id)
            if st is not None and st.finalize is not None:
                r = core.ready(st)
                if r is not None:
                    replies.put((r[0], True, r[1]))
            continue
        _kind, req, cmd, args = item
        core.commit()
        if cmd == "close":
            core.close()
            replies.put((req, True, None))
            return
        try:
            if cmd == "finalize":
                r = core.request_finalize(req, *args)
                if r is None:
                    continue                          # answered when its chunks have arrived
                value = r[1] if isinstance(r, tuple) else r
            else:
                value = getattr(core, "do_" + cmd)(*args)
        except Exception as exc:                      # noqa: BLE001 - delivered to the caller
            if core.in_txn:
                core.rollback()
            if req:
                replies.put((req, False, str(exc) if isinstance(exc, RepositoryError) else user_message(exc)))
            continue
        if req:
            replies.put((req, True, value))


class ResultWriter:
    """GUI-process handle of the writer process (see :func:`writer_main`)."""

    def __init__(self, db_path: Path):
        import multiprocessing as mp
        self.db_path = db_path
        last = _init_database(db_path)
        ctx = mp.get_context("spawn")
        self.inbox = ctx.Queue()                     # chunks (workers, job thread) and commands
        self._replies = ctx.Queue()
        self._shared = ctx.Array("d", 8, lock=False)
        self._err = ctx.Array("c", 1024, lock=False)
        self._shared[_S_COMMITTED] = last
        self._proc = ctx.Process(target=writer_main, name="hea-db-writer", daemon=True,
                                 args=(str(db_path), self.inbox, self._replies, self._shared, self._err))
        self._proc.start()
        self._futures: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._closed = False
        self._lost: str | None = None
        self._listener = threading.Thread(target=self._listen, name="hea-db-writer-replies", daemon=True)
        self._listener.start()

    # -------------------------------------------------------------- state (shared memory)
    @property
    def committed_last(self) -> int:
        return int(self._shared[_S_COMMITTED])

    @property
    def rows_written(self) -> int:
        return int(self._shared[_S_ROWS])

    @property
    def commits(self) -> int:
        return int(self._shared[_S_COMMITS])

    @property
    def insert_seconds(self) -> float:
        return self._shared[_S_INSERT_S]

    def committed_count(self, run_id: int) -> int:
        return int(self._shared[_S_RUN_COUNT]) if int(self._shared[_S_RUN]) == run_id else 0

    def stored_chunks(self, run_id: int) -> int:
        """Chunks of the active run already stored (or skipped) - the back-pressure measure."""
        return int(self._shared[_S_RUN_NEXT]) if int(self._shared[_S_RUN]) == run_id else 0

    @property
    def error(self) -> str | None:
        if self._lost:
            return self._lost
        raw = bytes(self._err).split(b"\0", 1)[0]
        return raw.decode("utf-8", "replace") or None

    @property
    def alive(self) -> bool:
        return self._proc.is_alive()

    @property
    def pid(self) -> int | None:
        return self._proc.pid

    # -------------------------------------------------------------- API (any thread)
    def call(self, kind: str, *args, wait: bool = True, timeout: float | None = 30.0):
        fut: Future = Future()
        if self._closed or self._lost:
            fut.set_exception(RepositoryError(self._lost or "The results database is closed."))
        else:
            req = next(self._ids)
            with self._lock:
                self._futures[req] = fut
            self.inbox.put(("cmd", req, kind, args))
        if not wait:
            return fut
        return fut.result(timeout)

    def put_chunk(self, run_id: int, index: int | None, chunk: dict) -> bool:
        """Queue a chunk from this process (in-process jobs); False once the writer has failed."""
        if self.error or self._closed:
            return False
        self.inbox.put(("chunk", run_id, index, chunk))
        return True

    def submit_chunk(self, run_id: int, chunk: dict, cancelled: Callable[[], bool] = lambda: False) -> bool:
        return self.put_chunk(run_id, None, chunk)

    def flush(self, timeout: float = 30.0) -> None:
        self.call("flush", timeout=timeout)

    def close(self, timeout: float = 10.0) -> None:
        if self._closed:
            return
        try:
            if self._proc.is_alive() and not self._lost:
                self.call("close", timeout=timeout)
        except Exception:                             # noqa: BLE001 - closing regardless
            pass
        self._closed = True
        self._proc.join(timeout)
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(2)
        self._replies.put(None)
        self._listener.join(2)
        for qu in (self.inbox, self._replies):
            qu.cancel_join_thread()
            qu.close()

    def _listen(self) -> None:
        while True:
            try:
                item = self._replies.get(timeout=0.5)
            except queue.Empty:
                if not self._proc.is_alive() and not self._closed:
                    self._lost = self.error or "The results writer stopped unexpectedly."
                    with self._lock:
                        futs, self._futures = list(self._futures.values()), {}
                    for f in futs:
                        if not f.done():
                            f.set_exception(RepositoryError(self._lost))
                    return
                continue
            except (EOFError, OSError):
                return
            if item is None:
                return
            req, ok, value = item
            with self._lock:
                fut = self._futures.pop(req, None)
            if fut is None or fut.done():
                continue
            if ok:
                fut.set_result(value)
            else:
                fut.set_exception(RepositoryError(value))


# ====================================================================== view builder
@dataclass
class ViewTask:
    kind: str                       # build | extend | drop | position | vacuum | exec
    token: int = 0
    table: str = ""
    where: str = ""
    params: tuple = ()
    order: str = ""
    lo: int = 0
    hi: int = 0
    rid: int = 0
    sorted: bool = False
    result: int = 0
    seconds: float = 0.0
    error: BaseException | None = None
    cancelled: bool = False
    done: threading.Event = field(default_factory=threading.Event)
    statements: list = field(default_factory=list)   # exec: [(sql, params), ...] in one transaction
    tag: object = None                               # exec: caller's label, returned untouched


class ViewBuilder:
    """The single writer of ``views.sqlite``: materialises table orders off the GUI thread."""

    def __init__(self, db_path: Path, views_path: Path, notify: Callable[[ViewTask], None] | None = None):
        self.notify = notify
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._running: ViewTask | None = None
        # 16 MiB page cache sorts 1 M rows as fast as 64 MiB (measured; the scan is the cost) and
        # keeps the GUI process 55 MiB smaller; helper threads make large sorts ~15 % faster.
        con = _connect(db_path, same_thread=False, cache_kib=16_384)
        con.execute("PRAGMA threads=4")
        con.execute(f"ATTACH DATABASE ? AS vw", (str(views_path),))
        con.execute("PRAGMA vw.journal_mode=WAL")
        con.execute("PRAGMA vw.synchronous=OFF")      # derived data only: rebuilt from results if lost
        # Checked results (Analysis "Checked results", data contract section 11): ids only, independent of
        # the table's filter and page; written here like every other views.sqlite table.
        con.execute("CREATE TABLE IF NOT EXISTS vw.checked(rid INTEGER PRIMARY KEY)")
        self._con = con
        self._thread = threading.Thread(target=self._loop, name="hea-view-builder", daemon=True)
        self._thread.start()

    def submit(self, task: ViewTask) -> ViewTask:
        self._q.put(task)
        return task

    def interrupt_stale(self, latest_token: int) -> None:
        """Stop a running build superseded by a newer request (its result would be discarded)."""
        with self._lock:
            t = self._running
            if t is not None and t.kind == "build" and t.token < latest_token:
                t.cancelled = True
                self._con.interrupt()

    def close(self, timeout: float = 10.0) -> None:
        with self._lock:
            if self._running is not None and self._running.kind == "build":
                self._running.cancelled = True
                self._con.interrupt()
        self._q.put(None)
        self._thread.join(timeout)

    def _loop(self) -> None:
        con = self._con
        while True:
            task = self._q.get()
            if task is None:
                con.close()
                return
            if task.cancelled:
                task.done.set()
                continue
            with self._lock:
                self._running = task
            t0 = time.perf_counter()
            try:
                if task.kind == "build":
                    con.execute("BEGIN")
                    try:
                        con.execute(f"CREATE TABLE vw.{q(task.table)}(pos INTEGER PRIMARY KEY, rid INTEGER NOT NULL)")
                        # rows are numbered in ORDER BY order: the auto rowid is the position
                        con.execute(f"INSERT INTO vw.{q(task.table)}(rid) SELECT result_id FROM main.results "
                                    f"WHERE result_id BETWEEN ? AND ?{task.where} ORDER BY {task.order}",
                                    (task.lo, task.hi, *task.params))
                        task.result = con.execute(f"SELECT COALESCE(MAX(pos), 0) FROM vw.{q(task.table)}").fetchone()[0]
                        con.execute("COMMIT")
                    except BaseException:
                        con.execute("ROLLBACK")
                        raise
                elif task.kind == "extend":
                    cur = con.execute(f"INSERT INTO vw.{q(task.table)}(rid) SELECT result_id FROM main.results "
                                      f"WHERE result_id BETWEEN ? AND ?{task.where} ORDER BY result_id",
                                      (task.lo, task.hi, *task.params))
                    task.result = cur.rowcount
                elif task.kind == "drop":
                    con.execute(f"DROP TABLE IF EXISTS vw.{q(task.table)}")
                elif task.kind == "vacuum":
                    con.execute("VACUUM vw")             # dropped orders of a cleared table give their space back
                elif task.kind == "exec":
                    con.execute("BEGIN")
                    try:
                        total = 0
                        for sql, params in task.statements:
                            cur = con.execute(sql, tuple(params))
                            total += max(0, cur.rowcount)
                        task.result = total
                        con.execute("COMMIT")
                    except BaseException:
                        con.execute("ROLLBACK")
                        raise
                elif task.kind == "position":
                    row = con.execute(f"SELECT pos FROM vw.{q(task.table)} WHERE rid=?", (task.rid,)).fetchone()
                    task.result = row[0] if row else 0
            except sqlite3.OperationalError as exc:
                if "interrupt" in str(exc).lower():
                    task.cancelled = True
                else:
                    task.error = exc
            except Exception as exc:                  # noqa: BLE001 - delivered to the view
                task.error = exc
            task.seconds = time.perf_counter() - t0
            with self._lock:
                self._running = None
            task.done.set()
            if self.notify is not None and task.kind in ("build", "extend", "position", "exec"):
                try:
                    self.notify(task)
                except Exception:                     # noqa: BLE001 - a closed GUI receiver
                    pass


# ====================================================================== records
class ResultRecord:
    """One stored result (row protocol of formatting, filters, clipboard, export and Details).

    Built from one SQL row; holds no Qt object and nothing per table cell.  ``pos`` is the row's
    position in the materialised view it was fetched from (0 for natural order).
    """

    __slots__ = ("reader", "v", "pos")

    def __init__(self, reader: "Reader", values: tuple, pos: int = 0):
        self.reader, self.v, self.pos = reader, values, pos

    def __eq__(self, other):
        return isinstance(other, ResultRecord) and other.v[_I_ID] == self.v[_I_ID] and other.reader is self.reader

    def __hash__(self):
        return hash(self.v[_I_ID])

    def __repr__(self):
        return f"ResultRecord({self.id}, {self.name!r})"

    @property
    def id(self) -> int:
        return self.v[_I_ID]

    result_id = id

    @property
    def run_id(self) -> int:
        return self.v[_I_RUN]

    @property
    def seq(self) -> int:
        return self.v[_I_SEQ]

    @property
    def block(self) -> int | None:
        return self.v[_I_BLOCK]

    @property
    def name(self) -> str:
        return self.v[_I_NAME] or ""

    @property
    def source(self) -> str:
        return self.reader.string(self.v[_I_SRC]) or ""

    @property
    def elements(self) -> tuple[str, ...]:
        return self.reader.elset(self.v[_I_ELSET])

    @property
    def input_amounts(self) -> dict[str, float]:
        return decode_amounts(self.elements, self.v[_I_AMOUNTS])[0]

    @property
    def composition(self) -> dict[str, float]:
        """Normalised atomic fractions (the engine's ``AlloyResult.composition``; empty on error)."""
        return decode_amounts(self.elements, self.v[_I_AMOUNTS])[1]

    @property
    def ok(self) -> bool:
        return not self.v[_I_ERR]

    @property
    def error(self) -> str | None:
        e = self.v[_I_ERR]
        return self.reader.string(e) if e else None

    @property
    def warnings(self) -> list[str]:
        w = self.reader.string(self.v[_I_WARN])
        return [w] if w else []

    @property
    def temperature(self) -> float | None:
        return self.v[_I_TEMP]

    def raw(self, key: str):
        if key == "name":
            return self.name
        if key == "composition":
            return self.v[_I_COMP] or ""
        i = COL.get(key)
        return None if i is None else self.v[i]

    def model_label(self, key: str) -> str:
        return self.v[COL[key]] or NA

    def model_note(self, key: str) -> str:
        return self.reader.string(self.v[COL["n_" + key]]) or ""

    def model_reason(self, key: str) -> str:
        """Why the verdict is N/A (empty for an evaluated verdict) - see the ``core/chunks`` notes."""
        return self.model_note(key) if self.v[COL[key]] in (None, NA) else ""

    def model_caution(self, key: str) -> str:
        return "" if self.v[COL[key]] in (None, NA) else self.model_note(key)

    def model_status(self, key: str) -> str | None:
        """Evidence status of an evaluated verdict (``engine.STATUS_*``), None when N/A."""
        from .chunks import STATUS_NAMES
        c = self.v[COL["status_" + key]]
        return None if c is None else STATUS_NAMES.get(c)

    def model_na_kind(self, key: str) -> str | None:
        """Why a verdict is N/A (``engine.NA_*``), None when evaluated."""
        from .chunks import NA_NAMES
        c = self.v[COL["na_kind_" + key]]
        return None if c is None else NA_NAMES.get(c)

    @property
    def family_id(self) -> int | None:
        return self.v[_I_FAMILY]

    @property
    def family(self) -> str | None:
        """Canonical element family key ("Co-Cr-Fe-Mn-Ni"), None for a row that was not evaluated."""
        return self.reader.family(self.v[_I_FAMILY])

    @property
    def n_elements(self) -> int | None:
        return self.v[_I_NEL]

    def display(self, key: str) -> str:
        return format_cell(self, key)

    @property
    def variables(self) -> dict:
        """Design variables of an expression result (x = 0.1, ...); empty otherwise."""
        return self.reader.variables(self)

    @property
    def design(self) -> dict:
        """Every stored design coordinate of this result (expression variables or sweep coordinates)."""
        return self.reader.design(self)

    @property
    def result(self) -> AlloyResult:
        return self.reader.reproduce(self)

    def materialize(self) -> ResultRow:
        """A full :class:`ResultRow` (engine result reproduced with the run's settings) - a snapshot
        for Calculation details that stays valid if the stored row is later removed."""
        return ResultRow(self.name, self.input_amounts, self.result, self.source, self.variables, row_id=self.id)


class Reader:
    """Read-side access over one connection: the GUI thread's, or a worker process's (export)."""

    def __init__(self, con: sqlite3.Connection, engine=None):
        self.con = con
        self.engine = engine
        self._strings = LRU(20_000)
        self._elsets = LRU(8_192)
        self._families = LRU(8_192)
        self._runs: dict[int, RunInfo] = {}

    # -------------------------------------------------------------- lookups
    def string(self, code: int | None) -> str | None:
        if not code:
            return None
        s = self._strings.get(code)
        if s is None:
            row = self.con.execute("SELECT s FROM strings WHERE code=?", (code,)).fetchone()
            s = row[0] if row else None
            self._strings.put(code, s)
        return s

    def family(self, family_id: int | None) -> str | None:
        if family_id is None:
            return None
        key = self._families.get(family_id)
        if key is None:
            row = self.con.execute("SELECT key FROM families WHERE family_id=?", (family_id,)).fetchone()
            key = row[0] if row else None
            self._families.put(family_id, key)
        return key

    def elset(self, i: int | None) -> tuple[str, ...]:
        if i is None:
            return ()
        e = self._elsets.get(i)
        if e is None:
            row = self.con.execute("SELECT els FROM elsets WHERE id=?", (i,)).fetchone()
            e = tuple(row[0].split(",")) if row and row[0] else ()
            self._elsets.put(i, e)
        return e

    def run(self, run_id: int, fresh: bool = False) -> RunInfo | None:
        info = None if fresh else self._runs.get(run_id)
        if info is None:
            row = self.con.execute(f"SELECT {_RUN_COLS} FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                return None
            info = RunInfo.from_row(row)
            if len(self._runs) > 4096:
                self._runs.clear()
            self._runs[run_id] = info
        return info

    # -------------------------------------------------------------- rows
    def records(self, rows, with_pos: bool = False) -> list[ResultRecord]:
        if with_pos:
            return [ResultRecord(self, r[1:], r[0]) for r in rows]
        return [ResultRecord(self, r) for r in rows]

    def get(self, rid: int) -> ResultRecord | None:
        row = self.con.execute(f"SELECT {_SELECT} FROM results WHERE result_id=?", (rid,)).fetchone()
        return ResultRecord(self, row) if row else None

    def exists(self, rid: int) -> bool:
        return self.con.execute("SELECT 1 FROM results WHERE result_id=?", (rid,)).fetchone() is not None

    def iter_range(self, lo: int, hi: int, chunk: int = 2000, where: str = "",
                   params: tuple = ()) -> Iterator[ResultRecord]:
        """Results ``lo..hi`` in id order (keyset paging: O(chunk) per step, bounded memory)."""
        last = lo - 1
        while True:
            rows = self.con.execute(f"SELECT {_SELECT} FROM results WHERE result_id > ? AND result_id <= ?{where} "
                                    f"ORDER BY result_id LIMIT ?", (last, hi, *params, chunk)).fetchall()
            if not rows:
                return
            yield from self.records(rows)
            last = rows[-1][0]

    def iter_query(self, lo: int, hi: int, where: str = "", params: tuple = (), order: str = "result_id",
                   chunk: int = 2000) -> Iterator[ResultRecord]:
        """Results ``lo..hi`` passing ``where`` in ``order`` - one statement streamed ``chunk`` rows at a
        time (SQLite's sorter holds the order, spilling to temporary files; Python never holds the set)."""
        cur = self.con.execute(f"SELECT {_SELECT} FROM results WHERE result_id BETWEEN ? AND ?{where} "
                               f"ORDER BY {order}", (lo, hi, *params))
        try:
            while True:
                rows = cur.fetchmany(chunk)
                if not rows:
                    return
                yield from self.records(rows)
        finally:
            cur.close()

    def iter_view(self, table: str, chunk: int = 2000, schema: str = "vw") -> Iterator[ResultRecord]:
        """Results in the order of a materialised view (removed rows are skipped by the join)."""
        last = 0
        while True:
            rows = self.con.execute(f"SELECT v.pos, {_SELECT_R} FROM {schema}.{q(table)} v JOIN results r "
                                    f"ON r.result_id = v.rid WHERE v.pos > ? ORDER BY v.pos LIMIT ?",
                                    (last, chunk)).fetchall()
            if not rows:
                return
            yield from self.records(rows, with_pos=True)
            last = rows[-1][0]

    # -------------------------------------------------------------- provenance
    def design(self, rec: ResultRecord) -> dict:
        info = self.run(rec.run_id)
        cols = [a for a in (info.axes if info else []) if a.get("col")]
        if not cols:
            return {}
        try:
            row = self.con.execute(f"SELECT {', '.join(q(a['col']) for a in cols)} FROM "
                                   f"{q(design_table(rec.run_id))} WHERE result_id=?", (rec.id,)).fetchone()
        except sqlite3.OperationalError:
            return {}
        return {a["name"]: v for a, v in zip(cols, row or ()) if v is not None}

    def variables(self, rec: ResultRecord) -> dict:
        info = self.run(rec.run_id)
        if not info or not any(a.get("kind") == "variable" for a in info.axes):
            return {}
        names = {a["name"] for a in info.axes if a.get("kind") == "variable"}
        return {k: v for k, v in self.design(rec).items() if k in names}

    def reproduce(self, rec: ResultRecord) -> AlloyResult:
        """The complete engine result for one stored row: the engine is deterministic, so the full
        result (every descriptor, model value and reason) is recomputed from the stored inputs with
        the run's stored settings rather than stored per row."""
        if self.engine is None:
            raise RuntimeError("The repository has no engine to reproduce a full result.")
        info = self.run(rec.run_id)
        settings = dict(info.settings) if info else {}
        opts = {k: settings[k] for k in ("annealing_temperature", "tcrit_fraction") if k in settings}
        return self.engine.calculate(rec.input_amounts, **opts)


# ====================================================================== query building
def filter_sql(filters: Sequence) -> tuple[str, tuple]:
    """SQL (``" AND ..."``) for the table's filters, with exactly the in-memory semantics:

    * :class:`RangeFilter` on a numeric column: only rows that were evaluated (no error) with a
      value (N/A / NULL never passes); bounds inclusive.
    * :class:`ModelFilter`: the label, with a missing label counting as "N/A".
    """
    parts, params = [], []
    for f in filters:
        if isinstance(f, RangeFilter) and f.key in NUM_KEYS:
            s = f"err = 0 AND {q(f.key)} IS NOT NULL"
            if f.minimum is not None:
                s += f" AND {q(f.key)} >= ?"
                params.append(float(f.minimum))
            if f.maximum is not None:
                s += f" AND {q(f.key)} <= ?"
                params.append(float(f.maximum))
            parts.append(s)
        elif isinstance(f, IdSetFilter):
            parts.append(f"result_id IN (SELECT rid FROM vw.{q(f.table)})")
        elif isinstance(f, ModelFilter) and f.key in MODEL_KEYS:
            labels = sorted(f.labels)
            if not labels:
                parts.append("0")
            else:
                parts.append(f"COALESCE({q(f.key)}, '{NA}') IN ({','.join('?' * len(labels))})")
                params.extend(labels)
        else:
            raise ValueError(f"Unsupported filter {f!r}")
    return "".join(f" AND ({p})" for p in parts), tuple(params)


def order_sql(key: str | None, descending: bool) -> str:
    """ORDER BY for a column sort: stable (ties keep id order), missing values (N/A) always last."""
    d = " DESC" if descending else ""
    if key is None:
        return "result_id"
    if key in ("name", "composition"):
        col = "name" if key == "name" else "comp"
        return f"{q(col)}{d}, result_id"
    if key in NUM_KEYS:
        return f"(err != 0 OR {q(key)} IS NULL), {q(key)}{d}, result_id"
    if key in MODEL_KEYS or key in TEXT_KEYS:
        return f"({q(key)} IS NULL), {q(key)}{d}, result_id"
    raise ValueError(f"Unknown sort column {key!r}")


# ====================================================================== repository
class ResultRepository:
    """The calculation dataset (see module docstring).  Create on the GUI thread; ``close()`` once."""

    def __init__(self, engine=None, root: Path | None = None, notify: Callable[[ViewTask], None] | None = None):
        self.engine = engine
        self.session_dir = _make_session_dir(root)
        self.db_path = self.session_dir / "results.sqlite"
        self.views_path = self.session_dir / "views.sqlite"
        self._notify = notify
        try:
            self.writer = ResultWriter(self.db_path)
            self.builder = ViewBuilder(self.db_path, self.views_path, self._on_task)
            con = _connect(self.db_path, cache_kib=8_192)
            con.execute("ATTACH DATABASE ? AS vw", (str(self.views_path),))
            con.execute("PRAGMA query_only=1")
        except (sqlite3.Error, OSError) as exc:
            shutil.rmtree(self.session_dir, ignore_errors=True)
            raise RepositoryError(f"The temporary results database could not be created. {user_message(exc)}") from exc
        self.con = con
        self.reader = Reader(con, engine)
        self._view_ids = 0
        self._closed = False

    # -------------------------------------------------------------- notification bridge
    def set_notify(self, fn: Callable[[ViewTask], None] | None) -> None:
        self._notify = fn

    def _on_task(self, task: ViewTask) -> None:
        if self._notify is not None:
            self._notify(task)

    def new_view_table(self) -> str:
        self._view_ids += 1
        return f"v{self._view_ids}"

    # -------------------------------------------------------------- runs
    def create_run(self, mode: str, *, label: str | None = None, settings: dict | None = None,
                   source: dict | None = None, axes: list | None = None, elements: list | None = None,
                   expected: int | None = None) -> int:
        from .provenance import run_provenance
        prov = run_provenance()
        info = RunInfo(0, mode, label, settings=dict(settings or {}), source=dict(source or {}),
                       axes=list(axes or []), elements=list(elements or []), expected=expected,
                       app_version=prov["app_version"], engine_version=prov["engine_version"],
                       dataset_ids=dict(prov["dataset_ids"]))
        return self.writer.call("create_run", info)

    def finalize_run(self, run_id: int, status: str, message: str | None = None, wait: bool = True,
                     upto: int | None = None):
        """Close a run (status complete | cancelled | failed) once its first ``upto`` chunks are stored."""
        fut = self.writer.call("finalize", run_id, status, message, upto, wait=False)
        return fut.result(60) if wait else fut

    def inject(self, delay: float = 0.0, fail: str | None = None) -> None:
        """Test hook: make the writer slow (``delay`` s per chunk) or fail every insert (``fail``)."""
        self.writer.call("inject", delay, fail)

    def get_run(self, run_id: int) -> RunInfo | None:
        return self.reader.run(run_id, fresh=True)

    def runs(self) -> list[RunInfo]:
        return [RunInfo.from_row(r) for r in self.con.execute(f"SELECT {_RUN_COLS} FROM runs ORDER BY run_id")]

    # -------------------------------------------------------------- writes
    @property
    def committed_last(self) -> int:
        return self.writer.committed_last

    @property
    def next_id(self) -> int:
        return self.writer.committed_last + 1

    def submit_chunk(self, run_id: int, chunk: dict, cancelled: Callable[[], bool] = lambda: False) -> bool:
        return self.writer.submit_chunk(run_id, chunk, cancelled)

    def append_chunk(self, run_id: int, chunk: dict) -> range:
        """Insert and commit one chunk synchronously (single compositions, tests, tools)."""
        return self.writer.call("append_sync", run_id, chunk)

    def append_results(self, run_id: int, rows: Sequence[ResultRow]) -> range:
        rows = list(rows)
        chunk = pack_results([r.input_amounts for r in rows], [r.result for r in rows])
        with_metadata(chunk, [r.name for r in rows], [r.source for r in rows], [r.variables for r in rows])
        return self.append_chunk(run_id, chunk)

    def delete_results(self, ids: Sequence[int]) -> int:
        return self.writer.call("delete", sorted(set(int(i) for i in ids)))

    delete_result = delete_results

    def clear_range(self, lo: int, hi: int, wait: bool = False):
        fut = self.writer.call("clear", lo, hi, wait=False)
        return fut.result(120) if wait else fut

    def clear_run(self, run_id: int, wait: bool = False):
        info = self.get_run(run_id)
        if info is None or info.first_id is None:
            return None
        return self.clear_range(info.first_id, info.last_id, wait)

    # -------------------------------------------------------------- reads
    def get_result(self, rid: int) -> ResultRecord | None:
        return self.reader.get(rid)

    def exists(self, rid: int) -> bool:
        return self.reader.exists(rid)

    def count(self, filters: Sequence = (), lo: int | None = None, hi: int | None = None) -> int:
        """``COUNT(*)`` over the dataset (full scan when filtered - the table uses :class:`ResultView`)."""
        where, params = filter_sql(filters)
        return self.con.execute(f"SELECT COUNT(*) FROM results WHERE result_id BETWEEN ? AND ?{where}",
                                (lo or 0, hi if hi is not None else 2**62, *params)).fetchone()[0]

    def fetch_page(self, filters: Sequence = (), sort: str | None = None, descending: bool = False,
                   offset: int = 0, limit: int = 100, lo: int | None = None, hi: int | None = None
                   ) -> list[ResultRecord]:
        """Ad-hoc page (``OFFSET``: fine for small offsets; the table pages through :class:`ResultView`)."""
        where, params = filter_sql(filters)
        rows = self.con.execute(f"SELECT {_SELECT} FROM results WHERE result_id BETWEEN ? AND ?{where} "
                                f"ORDER BY {order_sql(sort, descending)} LIMIT ? OFFSET ?",
                                (lo or 0, hi if hi is not None else 2**62, *params, limit, offset)).fetchall()
        return self.reader.records(rows)

    def stream_results(self, filters: Sequence = (), lo: int | None = None, hi: int | None = None,
                       chunk: int = 2000) -> Iterator[ResultRecord]:
        """Every matching result in id order, ``chunk`` rows per query (GUI-thread connection)."""
        where, params = filter_sql(filters)
        return self.reader.iter_range(lo or 0, hi if hi is not None else 2**62, chunk, where, params)

    def elements_of(self, run_ids: Sequence[int]) -> list[str]:
        """Union of the run element lists (export columns) - no pass over the results."""
        out: list[str] = []
        for rid in run_ids:
            info = self.reader.run(rid)
            for el in (info.elements if info else []):
                if el not in out:
                    out.append(el)
        return out

    def run_ids_in(self, lo: int, hi: int) -> list[int]:
        return [r[0] for r in self.con.execute(
            "SELECT run_id FROM runs WHERE first_id IS NOT NULL AND last_id >= ? AND first_id <= ? ORDER BY run_id",
            (lo, hi))]

    def size_bytes(self) -> dict:
        out = {}
        for name in ("results.sqlite", "results.sqlite-wal", "views.sqlite", "views.sqlite-wal"):
            p = self.session_dir / name
            out[name] = p.stat().st_size if p.exists() else 0
        return out

    # -------------------------------------------------------------- future plots (dataset queries)
    def available_axes(self, run_id: int) -> list[dict]:
        """Plot axes of a run: design coordinates, derived at.% axes, descriptors and model labels.

        Each axis is ``{"name", "kind", "sql", ...}``; ``sql`` is an expression over ``r`` (results)
        and ``d`` (the run's design table), so a plot query never decodes per-row Python objects.
        """
        info = self.get_run(run_id)
        if info is None:
            return []
        axes = []
        for a in info.axes:
            if a.get("col"):
                axes.append({**a, "sql": f"d.{q(a['col'])}"})
        if info.mode == "sweep" and info.source.get("unit") == "ratio":
            cols = [a["col"] for a in info.axes if a.get("kind") == "element"]
            total = " + ".join(f"d.{q(c)}" for c in cols)
            for a in info.axes:
                if a.get("kind") == "element":
                    axes.append({"name": f"{a['name']} at.%", "kind": "fraction", "unit": "at.%",
                                 "sql": f"(100.0 * d.{q(a['col'])} / ({total}))"})
        elif info.mode == "sweep":
            for a in info.axes:
                if a.get("kind") == "element":
                    axes.append({"name": f"{a['name']} at.%", "kind": "fraction", "unit": "at.%",
                                 "sql": f"d.{q(a['col'])}"})
        for k in NUM_KEYS:
            axes.append({"name": k, "kind": "descriptor", "unit": COLUMN_BY_KEY[k].unit, "sql": f"r.{q(k)}"})
        for k in MODEL_KEYS:
            axes.append({"name": k, "kind": "model", "sql": f"r.{q(k)}"})
        return axes

    def _axis_sql(self, run_id: int, name: str) -> str:
        for a in self.available_axes(run_id):
            if a["name"] == name:
                return a["sql"]
        raise KeyError(f"Run {run_id} has no axis {name!r}")

    def _plot_from(self, run_id: int) -> str:
        info = self.get_run(run_id)
        if info and any(a.get("col") for a in info.axes):
            return f"results r JOIN {q(design_table(run_id))} d ON d.result_id = r.result_id"
        return "results r"

    def _plot_where(self, run_id: int, fixed: dict | None, tol: float) -> tuple[str, list]:
        parts, params = ["r.run_id = ?"], [run_id]
        for name, value in (fixed or {}).items():
            parts.append(f"abs({self._axis_sql(run_id, name)} - ?) <= ?")
            params += [float(value), tol]
        return " AND ".join(parts), params

    def stream_plot_data(self, run_id: int, columns: Sequence[str], fixed: dict | None = None, tol: float = 1e-9,
                         chunk: int = 50_000, con: sqlite3.Connection | None = None) -> Iterator[list[array | list]]:
        """Plot columns of a run in chunks (numeric columns as ``array('d')``, NaN for N/A; model
        columns as lists of labels), ordered by result id - streamed, never the whole run at once."""
        con = con or self.con
        exprs = [self._axis_sql(run_id, c) for c in columns]
        kinds = ["model" if c in MODEL_KEYS else "num" for c in columns]
        where, params = self._plot_where(run_id, fixed, tol)
        last = 0
        while True:
            rows = con.execute(f"SELECT r.result_id, {', '.join(exprs)} FROM {self._plot_from(run_id)} WHERE {where} "
                               f"AND r.result_id > ? ORDER BY r.result_id LIMIT ?", (*params, last, chunk)).fetchall()
            if not rows:
                return
            out = []
            for j, kind in enumerate(kinds, start=1):
                if kind == "model":
                    out.append([r[j] or NA for r in rows])
                else:
                    out.append(array("d", (math.nan if r[j] is None else r[j] for r in rows)))
            yield out
            last = rows[-1][0]

    def get_series(self, run_id: int, x: str, y: str, fixed: dict | None = None, tol: float = 1e-9,
                   con: sqlite3.Connection | None = None) -> list[tuple]:
        """1-D series ``(x, y)`` ordered by x - e.g. x vs δ with y = 0.10 and z = 0.05 held fixed."""
        con = con or self.con
        xs, ys = self._axis_sql(run_id, x), self._axis_sql(run_id, y)
        where, params = self._plot_where(run_id, fixed, tol)
        return con.execute(f"SELECT {xs}, {ys} FROM {self._plot_from(run_id)} WHERE {where} AND {xs} IS NOT NULL "
                           f"ORDER BY {xs}, r.result_id", params).fetchall()

    def get_surface(self, run_id: int, x: str, y: str, value: str, fixed: dict | None = None, tol: float = 1e-9,
                    con: sqlite3.Connection | None = None) -> list[tuple]:
        """2-D scatter/map ``(x, y, value)`` - e.g. x, y coloured by Φ or by the M1 label (z fixed)."""
        con = con or self.con
        xs, ys, vs = (self._axis_sql(run_id, a) for a in (x, y, value))
        where, params = self._plot_where(run_id, fixed, tol)
        return con.execute(f"SELECT {xs}, {ys}, {vs} FROM {self._plot_from(run_id)} WHERE {where} "
                           f"AND {xs} IS NOT NULL AND {ys} IS NOT NULL ORDER BY {xs}, {ys}, r.result_id",
                           params).fetchall()

    def aggregate_plot_data(self, run_id: int, x: str, y: str, value: str, bins: tuple[int, int] = (200, 200),
                            agg: str = "avg", fixed: dict | None = None, tol: float = 1e-9,
                            con: sqlite3.Connection | None = None) -> dict:
        """Binned map for millions of points: at most ``bins[0] × bins[1]`` cells, computed in SQL.
        ``agg``: avg | min | max | count, or ``mode`` for a model label (most frequent)."""
        con = con or self.con
        xs, ys, vs = (self._axis_sql(run_id, a) for a in (x, y, value))
        where, params = self._plot_where(run_id, fixed, tol)
        frm = self._plot_from(run_id)
        x0, x1, y0, y1 = con.execute(f"SELECT min({xs}), max({xs}), min({ys}), max({ys}) FROM {frm} WHERE {where}",
                                     params).fetchone()
        if x0 is None or y0 is None:
            return {"x": (None, None), "y": (None, None), "bins": bins, "cells": []}
        nx, ny = bins
        dx = (x1 - x0) / nx or 1.0
        dy = (y1 - y0) / ny or 1.0
        bx = f"min(CAST(({xs} - {x0!r}) / {dx!r} AS INTEGER), {nx - 1})"
        by = f"min(CAST(({ys} - {y0!r}) / {dy!r} AS INTEGER), {ny - 1})"
        if agg == "mode":
            sql = (f"SELECT bx, by, v, n FROM (SELECT {bx} AS bx, {by} AS by, {vs} AS v, count(*) AS n, "
                   f"row_number() OVER (PARTITION BY {bx}, {by} ORDER BY count(*) DESC, {vs}) AS k "
                   f"FROM {frm} WHERE {where} GROUP BY 1, 2, 3) WHERE k = 1")
        else:
            fn = {"avg": "avg", "min": "min", "max": "max", "count": "count"}[agg]
            sql = f"SELECT {bx}, {by}, {fn}({vs}), count(*) FROM {frm} WHERE {where} GROUP BY 1, 2"
        return {"x": (x0, x1), "y": (y0, y1), "bins": bins, "cells": con.execute(sql, params).fetchall()}

    # -------------------------------------------------------------- lifecycle
    def reader_connection(self) -> sqlite3.Connection:
        """A new read-only connection (views attached) for another thread of this process."""
        con = _connect(self.db_path, readonly=True, same_thread=False)
        con.execute("ATTACH DATABASE ? AS vw", (f"file:{self.views_path.as_posix()}?mode=ro",))
        return con

    def close(self, delete: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        for stop in (self.builder.close, self.writer.close, self.con.close):
            try:
                stop()
            except Exception:                         # noqa: BLE001 - closing regardless
                pass
        if delete:
            for _ in range(20):
                try:
                    shutil.rmtree(self.session_dir)
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    time.sleep(0.05)               # a worker process may still be closing its read handle

    @property
    def closed(self) -> bool:
        return self._closed


# ====================================================================== table view
@dataclass
class _Mat:
    table: str
    token: int
    n: int                                   # positions built (removed rows keep theirs)
    upto: int                                # highest result id the view covers
    sorted: bool
    removed: list = field(default_factory=list)   # sorted removed positions


class ResultView:
    """What the results table shows: the workspace, filtered and sorted (see module docstring).

    GUI-thread object.  ``request(filters, sort)`` starts a materialisation when needed; small
    datasets are applied synchronously (``SYNC_WAIT_S``), large ones asynchronously -
    ``pending`` is then true and the previous state stays on screen until ``apply_task`` delivers.
    """

    def __init__(self, repo: ResultRepository):
        self.repo = repo
        self.lo = repo.next_id                 # first id of the workspace
        self.hi = self.lo - 1                  # highest committed id the view has seen
        self.removed: list[int] = []           # ids the user removed inside lo..hi (sorted)
        self.filters: list = []                # requested state
        self.sort_key: str | None = None
        self.sort_desc = False
        self.mat: _Mat | None = None           # applied materialised view (None: natural order)
        self._token = 0
        self.pending: ViewTask | None = None   # build in progress
        self._pending_removed: list[int] = []
        self._extending: ViewTask | None = None
        self.last_build_seconds = 0.0
        self.last_build_end = 0.0
        self._cache = LRU(4)
        self.streaming = False                 # a calculation is storing rows (re-sorts are paced then)

    # -------------------------------------------------------------- state
    @property
    def natural(self) -> bool:
        return not self.filters and self.sort_key is None

    @property
    def stale(self) -> bool:
        """A sorted view that does not yet include rows committed after it was built."""
        return self.mat is not None and self.mat.sorted and self.mat.upto < self.hi

    def total(self) -> int:
        """Results in the workspace (alive)."""
        return max(0, self.hi - self.lo + 1 - len(self.removed))

    def count(self) -> int:
        """Rows of the current (applied) view."""
        if self.mat is None:
            return self.total()
        return max(0, self.mat.n - len(self.mat.removed))

    def is_alive(self, rid: int) -> bool:
        if not self.lo <= rid <= self.hi:
            return False
        i = bisect.bisect_left(self.removed, rid)
        return not (i < len(self.removed) and self.removed[i] == rid)

    # -------------------------------------------------------------- committed rows
    def refresh(self, frontier: int | None = None) -> bool:
        """New rows committed up to ``frontier``: extend the natural range or a filtered view."""
        hi = self.repo.committed_last if frontier is None else frontier
        if hi <= self.hi:
            return False
        self.hi = hi
        self._cache.clear()
        if self.pending is None:
            self._catch_up()
        return True

    # -------------------------------------------------------------- requests
    def request(self, filters: Sequence | None = None, sort: tuple[str | None, bool] | None = None,
                wait: float = SYNC_WAIT_S) -> bool:
        """Apply a new filter and/or sort.  True when applied now, False while building."""
        if filters is not None:
            self.filters = list(filters)
        if sort is not None:
            self.sort_key, self.sort_desc = sort
        return self.rebuild(wait)

    def rebuild(self, wait: float = SYNC_WAIT_S) -> bool:
        self._cache.clear()
        self._token += 1
        self.repo.builder.interrupt_stale(self._token)
        if self.natural:
            self._drop_pending()
            self._set_mat(None)
            return True
        where, params = filter_sql(self.filters)
        table = self.repo.new_view_table()
        task = ViewTask("build", self._token, table, where, params, order_sql(self.sort_key, self.sort_desc),
                        lo=self.lo, hi=self.hi)
        task.sorted = self.sort_key is not None
        self._drop_pending()
        self.pending = task
        self._pending_removed = []
        self.repo.builder.submit(task)
        if wait > 0 and task.done.wait(wait):
            self.apply_task(task)
            return True
        return False

    def wait(self, timeout: float = 60.0) -> bool:
        """Block until a pending build is applied (tools and tests)."""
        t = self.pending
        if t is not None and t.done.wait(timeout):
            self.apply_task(t)
        e = self._extending
        if e is not None and e.done.wait(timeout):
            self.apply_task(e)
        return self.pending is None

    def _drop_pending(self) -> None:
        t = self.pending
        if t is not None:
            t.cancelled = True
            self.pending = None
            self.repo.builder.submit(ViewTask("drop", table=t.table))

    def _set_mat(self, mat: _Mat | None) -> None:
        old = self.mat
        self.mat = mat
        self._cache.clear()
        if old is not None and (mat is None or old.table != mat.table):
            self.repo.builder.submit(ViewTask("drop", table=old.table))

    def apply_task(self, task: ViewTask) -> bool:
        """Deliver a finished builder task (GUI thread).  Returns True when the view changed."""
        if task.kind == "build":
            if task is not self.pending:
                return False
            self.pending = None
            if task.cancelled or task.error is not None:
                self.repo.builder.submit(ViewTask("drop", table=task.table))
                if task.error is not None:
                    raise RepositoryError(f"The table could not be sorted or filtered. {user_message(task.error)}")
                return False
            self.last_build_seconds = task.seconds
            self.last_build_end = time.perf_counter()
            self._set_mat(_Mat(task.table, task.token, task.result, task.hi, task.sorted))
            for rid in self._pending_removed:              # removed while the view was being built
                pos = self._lookup_position(rid)
                if pos:
                    bisect.insort(self.mat.removed, pos)
            self._pending_removed = []
            self._catch_up()
            return True
        if task.kind == "extend":
            if task is self._extending:
                self._extending = None
            m = self.mat
            if m is None or task.token != m.token or task.error is not None or task.cancelled:
                # an extend of a replaced view: ignored, but the current view may have been waiting
                # for it to finish before extending itself over the rows committed meanwhile
                if self.pending is None:
                    self._catch_up()
                return False
            m.n += task.result
            m.upto = task.hi
            self._cache.clear()
            self._catch_up()
            return True
        return False

    def _catch_up(self) -> None:
        """Extend a filtered (unsorted) view over rows committed while it was being built."""
        m = self.mat
        if m is not None and not m.sorted and self.hi > m.upto and self._extending is None:
            where, params = filter_sql(self.filters)
            self._extending = self.repo.builder.submit(
                ViewTask("extend", m.token, m.table, where, params, lo=m.upto + 1, hi=self.hi))

    def needs_final_rebuild(self) -> bool:
        """A sorted order (applied or still building) that misses committed rows - checked when rows
        stop arriving, so the final view holds every eligible result."""
        t = self.pending
        if t is not None:
            return t.sorted and t.hi < self.hi
        return self.stale

    def wants_resort(self, running: bool) -> bool:
        """Sorted view and new rows: rebuild with back-off (≥ 1.5 s and ≥ 4 × the last build)."""
        if not self.stale or self.pending is not None:
            return False
        if not running:
            return True
        since = time.perf_counter() - self.last_build_end
        return since >= max(1.5, 4 * self.last_build_seconds)

    # -------------------------------------------------------------- pages
    def _natural_start(self, index: int) -> int:
        start = self.lo + index
        for r in self.removed:
            if r <= start:
                start += 1
            else:
                break
        return start

    def _view_start(self, index: int) -> int:
        p = index + 1
        for r in self.mat.removed:
            if r <= p:
                p += 1
            else:
                break
        return p

    def page(self, index: int, size: int, natural: bool = False) -> list[ResultRecord]:
        """Rows ``index .. index+size-1`` of the view - or of the whole workspace in id order when
        ``natural`` - (bounded cache of a few pages)."""
        mat = None if natural else self.mat
        key = (mat.token if mat else 0, index, size, self.hi, len(self.removed), len(mat.removed) if mat else 0)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        rd = self.repo.reader
        if index < 0 or size <= 0:
            return []
        if mat is None:
            start = self._natural_start(index)
            rows = rd.con.execute(f"SELECT {_SELECT} FROM results WHERE result_id >= ? AND result_id <= ? "
                                  f"ORDER BY result_id LIMIT ?", (start, self.hi, size)).fetchall()
            out = rd.records(rows)
        else:
            start = self._view_start(index)
            rows = rd.con.execute(f"SELECT v.pos, {_SELECT_R} FROM vw.{q(self.mat.table)} v JOIN results r "
                                  f"ON r.result_id = v.rid WHERE v.pos >= ? ORDER BY v.pos LIMIT ?",
                                  (start, size)).fetchall()
            out = rd.records(rows, with_pos=True)
        self._cache.put(key, out)
        return out

    def at(self, index: int, natural: bool = False) -> ResultRecord | None:
        n = self.total() if natural else self.count()
        if index < 0:
            index += n
        if not 0 <= index < n:
            return None
        p = self.page(index, 1, natural)
        return p[0] if p else None

    def iterate(self, natural: bool = False, chunk: int = 2000) -> Iterator[ResultRecord]:
        """Every row of the view (or the workspace), streamed ``chunk`` rows per query."""
        rd = self.repo.reader
        if natural or self.mat is None:
            return rd.iter_range(self.lo, self.hi, chunk)
        return rd.iter_view(self.mat.table, chunk)

    def __iter__(self) -> Iterator[ResultRecord]:
        return self.iterate()

    def export_spec(self, filtered: bool) -> dict:
        """The export of this table as one query: every committed result of the workspace (``filtered``
        False: filters ignored) or the rows passing the current filters, both in the current sort
        order (ties by id).  Built from the dataset, not from the materialised view, so an export
        during a calculation includes rows the (lagging) view does not show yet."""
        hi = max(self.hi, self.repo.committed_last)          # everything committed, not just what is shown
        where, params = filter_sql(self.filters) if filtered else ("", ())
        return {"db": str(self.repo.db_path), "views": str(self.repo.views_path), "lo": self.lo, "hi": hi,
                "where": where, "params": params,
                "order": order_sql(self.sort_key, self.sort_desc),
                "count": self.count() if filtered and self.filters else self.total()}

    def export_rows(self, filtered: bool) -> Iterator[ResultRecord]:
        """:meth:`export_spec` streamed through this process's connection (small exports)."""
        sp = self.export_spec(filtered)
        return self.repo.reader.iter_query(sp["lo"], sp["hi"], sp["where"], sp["params"], sp["order"])

    def position_of(self, rid: int) -> int:
        """Logical index of result ``rid`` in the view, or -1 (not shown / not found quickly)."""
        if not self.is_alive(rid):
            return -1
        if self.mat is None:
            return rid - self.lo - bisect.bisect_left(self.removed, rid)
        pos = self._lookup_position(rid)
        if not pos:
            return -1
        return pos - 1 - bisect.bisect_left(self.mat.removed, pos)

    def _lookup_position(self, rid: int, scan_limit: int | None = POSITION_SCAN_MAX) -> int:
        m = self.mat
        if m is None:
            return 0
        con = self.repo.reader.con
        table = f"vw.{q(m.table)}"
        if not m.sorted:                                 # positions follow ids: binary search
            lo, hi = 1, m.n
            while lo <= hi:
                mid = (lo + hi) // 2
                row = con.execute(f"SELECT rid FROM {table} WHERE pos=?", (mid,)).fetchone()
                if row is None:
                    return 0
                if row[0] == rid:
                    return mid
                if row[0] < rid:
                    lo = mid + 1
                else:
                    hi = mid - 1
            return 0
        if scan_limit is not None and m.n > scan_limit:
            return 0
        row = con.execute(f"SELECT pos FROM {table} WHERE rid=?", (rid,)).fetchone()
        return row[0] if row else 0

    # -------------------------------------------------------------- removal / clear
    def remove(self, records: Sequence[ResultRecord]) -> int:
        """Delete these results from the dataset and from the view (positions known from the page)."""
        records = list({r.id: r for r in records if self.is_alive(r.id)}.values())    # each result once
        if not records:
            return 0
        positions = [self._verified_position(r) for r in records] if self.mat is not None else []
        self.repo.delete_results([r.id for r in records])
        for r in records:
            bisect.insort(self.removed, r.id)
            if self.pending is not None:
                self._pending_removed.append(r.id)
        for pos in positions:
            if pos and pos not in self.mat.removed:
                bisect.insort(self.mat.removed, pos)
        self._cache.clear()
        return len(records)

    def _verified_position(self, rec: ResultRecord) -> int:
        """The record's position in the applied view (from its page when still valid, else looked up)."""
        if rec.pos:
            row = self.repo.reader.con.execute(f"SELECT rid FROM vw.{q(self.mat.table)} WHERE pos=?",
                                               (rec.pos,)).fetchone()
            if row is not None and row[0] == rec.id:
                return rec.pos
        return self._lookup_position(rec.id, scan_limit=None)

    def remove_ids(self, ids: Sequence[int]) -> int:
        return self.remove([rec for rec in (self.repo.get_result(i) for i in ids) if rec is not None])

    def hide_all(self) -> tuple[int, int]:
        """Empty the workspace (the rows stay in the database until deleted); returns the old range.
        Filters and sort stay requested and apply to the rows that arrive next."""
        old = (self.lo, self.hi)
        if self._extending is not None:
            self._extending.cancelled = True
            self._extending = None
        self.lo = self.hi + 1
        self.removed = []
        self.rebuild()
        return old

    def clear(self) -> None:
        """Trash: delete every result of the workspace (in the background) and empty the view."""
        lo, hi = self.hide_all()
        if hi >= lo:
            self.repo.clear_range(lo, hi)
            self.repo.builder.submit(ViewTask("vacuum"))


_ = (Future,)
