"""Explicit result-id sets for the Results table's id filter (no Qt).

"Show in results table" (Analysis plot selection) filters the table to exactly the selected result ids.  The ids
are written to a ``vw`` table by the repository's view builder (the single writer of ``views.sqlite``), and the
table's :class:`~..results.IdSetFilter` joins it in SQL - no per-row Python work, nothing held in memory.

This is the only id-set infrastructure: the former "Checked results" set and its checkbox column were removed
(release reconciliation product decision).
"""

from __future__ import annotations

import uuid

from ..repository import ViewTask, q


def id_table(repo, ids, timeout: float = 30.0) -> str:
    """A ``vw`` table holding exactly ``ids``; written by the view builder, returned once written.  Raises the
    builder's error if it failed."""
    name = f"sel_{uuid.uuid4().hex[:12]}"
    ids = sorted({int(i) for i in ids})
    stmts = [(f"CREATE TABLE vw.{q(name)}(rid INTEGER PRIMARY KEY)", ())]
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        stmts.append((f"INSERT OR IGNORE INTO vw.{q(name)}(rid) VALUES {','.join(['(?)'] * len(part))}", part))
    task = repo.builder.submit(ViewTask("exec", statements=stmts))
    task.done.wait(timeout)
    if task.error is not None:
        raise task.error
    return name


def drop_id_table(repo, name: str) -> None:
    repo.builder.submit(ViewTask("exec", statements=[(f"DROP TABLE IF EXISTS vw.{q(name)}", ())]))
