"""Application Undo / Redo (Edit menu): one ``QUndoStack`` of meaningful data edits.

Undoable: Clear composition (Single, Composition space, Composition expression), Remove result(s) and Clear
table, and every finished edit of Single composition and Composition space (2026-10-28, :class:`SetupEditCommand`:
elements added / removed / renamed, amounts, ranges, locks, input column, range basis, system size, Set equal - one
step per finished edit, never per keystroke).  Not undoable: navigation and presentation (menus, Analysis tabs,
scrolling, expanding Analysis), switching the mode, and the expression text (its editor has its own undo).

Result removals never copy result rows into Python.  The window removes them through the repository's
reversible path (rows moved to a ``trash_<op>`` table in the session database, a whole-table clear being an O(1)
rename - ``core/repository.py``), and each command keeps only ids, the view range and the run ids it cleared.
A removal is deleted for good (``purge_trash``) when its command leaves the stack: pushed out by the undo limit,
or discarded because a new edit replaced the redo branch.
"""

from __future__ import annotations

import itertools

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

UNDO_LIMIT = 50
_OPS = itertools.count(1)


class _Command(QUndoCommand):
    """Base: a stable ``op`` id (names the repository trash of a removal) and an optional purge."""

    def __init__(self, text: str):
        super().__init__(text)
        self.op = next(_OPS)

    def purge(self) -> None:                   # the command left the stack: make it final
        pass


class ClearCompositionCommand(_Command):
    def __init__(self, panel, snapshot: dict, text: str):
        super().__init__(text)
        self.panel, self.snap = panel, snapshot

    def redo(self):
        self.panel.clear()

    def undo(self):
        self.panel.restore(self.snap)


class SetupEditCommand(_Command):
    """One finished edit of the composition setup: the panel's full state before and after it
    (``CompositionPanel.undo_state``).  Pushed after the edit has happened, so the first ``redo`` (QUndoStack runs
    it on push) does nothing."""

    def __init__(self, window, before: dict, after: dict, text: str):
        super().__init__(text)
        self.window, self.before, self.after = window, before, after
        self._done = True

    def redo(self):
        if self._done:
            self._done = False
            return
        self.window.apply_setup_state(self.after)

    def undo(self):
        self.window.apply_setup_state(self.before)


class RemoveResultsCommand(_Command):
    """Remove result(s) from the table and the dataset (reversible: repository trash)."""

    def __init__(self, window, records):
        n = len(records)
        super().__init__("Remove result" if n == 1 else f"Remove {n:,} results")
        self.window = window
        self.records = list(records)
        self.ids = [r.id for r in self.records]

    def redo(self):
        w = self.window
        w.table.model.remove_rows(self.records, self.op)
        w.table.view.removed_ids.emit(list(self.ids))
        w.table.view.rows_removed.emit()

    def undo(self):
        w = self.window
        w.repo.restore_trash(self.op)
        w.table.model.restore_rows(self.ids)
        w.results_restored()

    def purge(self):
        self.window.repo.purge_trash(self.op)


class ClearTableCommand(_Command):
    """Clear table: every result of the workspace (reversible: an O(1) table swap in the writer)."""

    def __init__(self, window, count: int):
        super().__init__("Clear results table" if count else "Clear table")
        self.window = window
        view = window.table.model.view
        self.lo, self.hi = view.lo, view.hi
        self.removed = list(view.removed)
        self.runs: list[int] = []

    def redo(self):
        w = self.window
        info = w.table.model.clear(self.op) or {}
        self.runs = list(info.get("runs", []))
        w.analysis_ctl.table_cleared(lo=self.lo, hi=self.hi)
        w.analysis.set_has_results(False)
        w._update_status()

    def undo(self):
        w = self.window
        w.repo.restore_trash(self.op, self.runs)
        w.table.model.restore_range(self.lo, self.removed)
        w.results_restored()

    def purge(self):
        self.window.repo.purge_trash(self.op, self.runs)


class UndoManager(QObject):
    """The window's undo stack, with purge of removals that can no longer be undone."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stack = QUndoStack(self)
        self.stack.setUndoLimit(UNDO_LIMIT)
        self._live: dict[int, _Command] = {}
        self.stack.indexChanged.connect(self._index_changed)   # a bound slot: disconnected when this object goes

    def _index_changed(self, _i: int) -> None:
        self.changed.emit()

    def push(self, cmd: _Command) -> None:
        self._live[cmd.op] = cmd
        self.stack.push(cmd)                   # runs cmd.redo() - the action itself
        self._sync()

    def _sync(self) -> None:
        """Purge commands QUndoStack dropped (undo limit, or the redo branch replaced by a new edit)."""
        present = {getattr(self.stack.command(i), "op", None) for i in range(self.stack.count())}
        for op in [op for op in self._live if op not in present]:
            cmd = self._live.pop(op)
            try:
                cmd.purge()
            except Exception:                  # noqa: BLE001 - the session database goes at exit anyway
                pass

    def can_undo(self) -> bool:
        return self.stack.canUndo()

    def can_redo(self) -> bool:
        return self.stack.canRedo()

    def undo(self) -> None:
        if self.stack.canUndo():
            self.stack.undo()

    def redo(self) -> None:
        if self.stack.canRedo():
            self.stack.redo()

    def clear(self) -> None:
        """Forget every command (their removals become final)."""
        for cmd in list(self._live.values()):
            try:
                cmd.purge()
            except Exception:                  # noqa: BLE001
                pass
        self._live.clear()
        self.stack.clear()
