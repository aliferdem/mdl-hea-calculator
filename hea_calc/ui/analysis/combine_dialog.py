"""Combine runs (Analysis Collection, 2026-10-28): the Carbon modal in which the user selects two or more
compatible calculation runs to analyse as one collection (``AnalysisController.combine``).

One row per run: a checkbox, the run identifier, its kind, its result count and its status.  A run that cannot
join the current selection (different engine version, datasets or calculation settings -
``core.analysis.combine.combine_problem``) is disabled and says why in its row.  **Combine** is enabled from two
compatible runs; **Cancel** leaves the collection as it was.  Nothing is combined without this selection."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QWidget

from ...core.analysis.combine import combine_problem, compatible_with
from ..widgets.dialogs import Modal, scroll
from .composition_view import mode_name

STATUS = {"complete": "Complete", "running": "Running", "cancelled": "Cancelled", "failed": "Failed",
          "interrupted": "Interrupted"}


class CombineRunsDialog(Modal):
    def __init__(self, controller, parent=None):
        super().__init__("Combine runs", "Analysis collection", parent, width=600)
        self.c = controller
        self.chosen: tuple[int, ...] = ()
        self.infos = list(controller.runs())
        intro = QLabel("Select two or more calculation runs to analyse together. The runs themselves are not "
                       "changed: the combined collection is a view of their results, each result counted once.")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        for col, head in enumerate(("Run", "Type", "Results", "Status")):
            h = QLabel(head)
            h.setObjectName("Label01")
            grid.addWidget(h, 0, col)
        self.checks: dict[int, QCheckBox] = {}
        self.reasons: dict[int, QLabel] = {}
        pre = set(controller.combined_runs or ())
        for r, info in enumerate(self.infos, start=1):
            cb = QCheckBox(f"Run {info.run_id}")
            cb.setChecked(info.run_id in pre)
            cb.setAccessibleName(f"Run {info.run_id}, {mode_name(info.mode)}, "
                                 f"{controller.run_count(info.run_id):,} results")
            cb.toggled.connect(self._sync)
            self.checks[info.run_id] = cb
            grid.addWidget(cb, 2 * r - 1, 0)
            grid.addWidget(QLabel(mode_name(info.mode)), 2 * r - 1, 1)
            n = QLabel(f"{controller.run_count(info.run_id):,}")
            grid.addWidget(n, 2 * r - 1, 2)
            grid.addWidget(QLabel(STATUS.get(info.status, info.status.capitalize())), 2 * r - 1, 3)
            why = QLabel("")
            why.setObjectName("Helper")
            why.setWordWrap(True)
            why.hide()
            self.reasons[info.run_id] = why
            grid.addWidget(why, 2 * r, 0, 1, 4)
        grid.setRowStretch(2 * len(self.infos) + 1, 1)
        self.body.addWidget(scroll(inner), 1)
        self.problem = QLabel("")
        self.problem.setObjectName("Helper")
        self.problem.setWordWrap(True)
        self.body.addWidget(self.problem)
        self.add_footer_button("Cancel", "secondary", self.reject)
        self.combine_btn = self.add_footer_button("Combine", "primary", self._combine)
        self._sync()

    def selected_infos(self) -> list:
        return [i for i in self.infos if self.checks[i.run_id].isChecked()]

    def _sync(self, *_):
        sel = self.selected_infos()
        for info in self.infos:
            cb, why = self.checks[info.run_id], self.reasons[info.run_id]
            reason = None if cb.isChecked() else compatible_with(info, sel)
            cb.setEnabled(reason is None)
            why.setText(f"Not combinable with the selection: {reason}" if reason else "")
            why.setVisible(bool(reason))
            cb.setAccessibleDescription(reason or "")
        problem = combine_problem(sel) if len(sel) >= 2 else None
        n = sum(self.c.run_count(i.run_id) for i in sel)
        self.combine_btn.setEnabled(len(sel) >= 2 and problem is None)
        if len(sel) < 2:
            self.problem.setText("Select at least two runs.")
        else:
            self.problem.setText(problem or f"{len(sel)} runs, {n:,} results.")

    def _combine(self):
        sel = self.selected_infos()
        if len(sel) < 2 or combine_problem(sel):
            return
        self.chosen = tuple(sorted(i.run_id for i in sel))
        self.accept()
