"""Checked results: the explicit multi-result set of the Results table (data contract section 11; no Qt).

Checked ids live in ``views.sqlite`` (``vw.checked``), written only by the repository's view builder (the
single writer of that file), so "Check all filtered" inserts the filtered ids in SQL - no per-row Python
loop, nothing held in memory.  The GUI thread reads states for the visible page only (<= 100 ids, one
indexed query).  A toggle is shown at once through a small pending overlay until the builder has written
it, so a click never waits for a long sort the builder may be running.

The set is independent of the table filter, sort and page; removing or clearing results removes them.
``version`` increments on every change (the Analysis stale notice compares it with the snapshot's).
"""

from __future__ import annotations

import itertools
import uuid

from ..repository import ViewTask, q


class CheckedSet:
    def __init__(self, repo):
        self.repo = repo
        self.count = 0
        self.version = 0
        self.all_filtered_version: int | None = None   # version right after "check all filtered"
        self._overlay: dict[int, tuple[bool, int]] = {}  # rid -> (checked, seq) not yet written
        self._pending: list[tuple[ViewTask, list[int], int]] = []
        self._seq = itertools.count(1)
        self._counting: ViewTask | None = None
        self.last_error: str | None = None

    # -------------------------------------------------------------- reads (GUI thread)
    def _settle(self) -> None:
        keep = []
        failed = False
        for task, ids, seq in self._pending:
            if task.done.is_set():
                if task.error is not None:
                    self.last_error = str(task.error)
                    failed = True
                for i in ids:
                    st = self._overlay.get(i)
                    if st is not None and st[1] == seq:
                        del self._overlay[i]
            else:
                keep.append((task, ids, seq))
        self._pending = keep
        if failed:                                   # a write failed: the database is the truth
            self._overlay.clear()
            self.count = self._db_count()
        if self._counting is not None and self._counting.done.is_set():
            self._counting = None
            self.count = self._db_count()

    @property
    def busy(self) -> bool:
        self._settle()
        return bool(self._pending) or self._counting is not None

    def _db_count(self) -> int:
        return self.repo.con.execute("SELECT COUNT(*) FROM vw.checked").fetchone()[0]

    def states(self, ids) -> set[int]:
        """The checked ids among ``ids`` (a page), including changes not yet written."""
        self._settle()
        ids = [int(i) for i in ids]
        out: set[int] = set()
        for k in range(0, len(ids), 500):
            part = ids[k:k + 500]
            out.update(r[0] for r in self.repo.con.execute(
                f"SELECT rid FROM vw.checked WHERE rid IN ({','.join('?' * len(part))})", part))
        for i in ids:
            st = self._overlay.get(i)
            if st is not None:
                (out.add if st[0] else out.discard)(i)
        return out

    def is_checked(self, rid: int) -> bool:
        return int(rid) in self.states([rid])

    # -------------------------------------------------------------- writes
    def _submit(self, statements, ids=(), seq: int = 0) -> ViewTask:
        task = self.repo.builder.submit(ViewTask("exec", statements=list(statements)))
        self._pending.append((task, list(ids), seq))
        return task

    def set(self, ids, checked: bool) -> int:
        """Check / uncheck explicit ids; returns how many changed."""
        ids = sorted({int(i) for i in ids})
        if not ids:
            return 0
        cur = self.states(ids)
        changed = [i for i in ids if (i in cur) != checked]
        if not changed:
            return 0
        seq = next(self._seq)
        for i in changed:
            self._overlay[i] = (checked, seq)
        self.count += len(changed) if checked else -len(changed)
        stmts = []
        for k in range(0, len(changed), 500):
            part = changed[k:k + 500]
            if checked:
                stmts.append((f"INSERT OR IGNORE INTO vw.checked(rid) VALUES {','.join(['(?)'] * len(part))}", part))
            else:
                stmts.append((f"DELETE FROM vw.checked WHERE rid IN ({','.join('?' * len(part))})", part))
        self._submit(stmts, changed, seq)
        self.version += 1
        self.all_filtered_version = None
        return len(changed)

    def toggle(self, rid: int) -> bool:
        on = not self.is_checked(rid)
        self.set([rid], on)
        return on

    def set_matching(self, where: str, params, lo: int, hi: int, checked: bool) -> ViewTask:
        """Check / uncheck every result ``lo..hi`` passing the table filter ``where`` (in SQL)."""
        if checked:
            sql = (f"INSERT OR IGNORE INTO vw.checked(rid) SELECT result_id FROM main.results "
                   f"WHERE result_id BETWEEN ? AND ?{where}")
        else:
            sql = (f"DELETE FROM vw.checked WHERE rid IN (SELECT result_id FROM main.results "
                   f"WHERE result_id BETWEEN ? AND ?{where})")
        task = self._submit([(sql, (lo, hi, *params))])
        self._overlay.clear()
        self._recount_after(task)
        self.version += 1
        self.all_filtered_version = self.version if checked else None
        return task

    def clear(self) -> None:
        task = self._submit([("DELETE FROM vw.checked", ())])
        self._overlay.clear()
        self.count = 0
        self.version += 1
        self.all_filtered_version = None
        self._recount_after(task)

    def remove_ids(self, ids) -> None:
        """Results were removed: they leave the set (counts follow)."""
        ids = sorted({int(i) for i in ids})
        if not ids:
            return
        for i in ids:
            self._overlay.pop(i, None)
        stmts = [(f"DELETE FROM vw.checked WHERE rid IN ({','.join('?' * len(ids[k:k + 500]))})", ids[k:k + 500])
                 for k in range(0, len(ids), 500)]
        task = self._submit(stmts)
        self._recount_after(task)

    def remove_range(self, lo: int, hi: int) -> None:
        task = self._submit([("DELETE FROM vw.checked WHERE rid BETWEEN ? AND ?", (lo, hi))])
        self._overlay.clear()
        self._recount_after(task)

    def _recount_after(self, task: ViewTask) -> None:
        self._counting = task

    def wait(self, timeout: float = 30.0) -> None:
        """Block until every submitted change is written (tests, tools, snapshots)."""
        for task, _ids, _seq in list(self._pending):
            task.done.wait(timeout)
        if self._counting is not None:
            self._counting.done.wait(timeout)
        self._settle()

    # -------------------------------------------------------------- snapshots (checked-results collections)
    def snapshot(self) -> tuple[str, ViewTask]:
        """Copy the checked set into a new ``vw`` table (asynchronously); returns (table, task)."""
        name = f"snap_{uuid.uuid4().hex[:12]}"
        task = self.repo.builder.submit(ViewTask("exec", statements=[
            (f"CREATE TABLE vw.{q(name)}(rid INTEGER PRIMARY KEY)", ()),
            (f"INSERT INTO vw.{q(name)}(rid) SELECT rid FROM vw.checked", ())]))
        return name, task

    def drop_snapshot(self, name: str) -> None:
        self.repo.builder.submit(ViewTask("exec", statements=[(f"DROP TABLE IF EXISTS vw.{q(name)}", ())]))
