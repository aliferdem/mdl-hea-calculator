"""Background calculation: feeds compositions from any workflow to the shared engine."""

from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from ..core.engine import Engine
from ..core.results import ResultRow


class CalculationWorker(QThread):
    progress = Signal(int, int, float)   # done, total, eta seconds
    batch = Signal(object)               # list[ResultRow] (object: keep Python payload untouched)
    done = Signal(bool)                  # cancelled?

    BATCH = 250

    def __init__(self, engine: Engine, source: str | list[str], names: list[str], compositions: list[dict],
                 variables: list[dict], options: dict, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.sources = source if isinstance(source, list) else [source] * len(compositions)
        self.names = names
        self.compositions = compositions
        self.variables = variables
        self.options = options
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        start = time.perf_counter()
        total = len(self.compositions)
        pending: list[ResultRow] = []
        for i, (name, comp, env, src) in enumerate(zip(self.names, self.compositions, self.variables, self.sources),
                                                   start=1):
            if self._cancel:
                break
            res = self.engine.calculate(comp, **self.options)
            pending.append(ResultRow(name or "", dict(comp), res, src, dict(env or {})))
            if len(pending) >= self.BATCH or i == total:
                self.batch.emit(pending)
                pending = []
                elapsed = time.perf_counter() - start
                self.progress.emit(i, total, elapsed / i * (total - i))
        if pending:
            self.batch.emit(pending)
        self.done.emit(self._cancel)
