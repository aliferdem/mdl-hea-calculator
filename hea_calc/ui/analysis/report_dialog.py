"""Collection report contents (2026-10-28): the Carbon modal in which the user chooses the charts an Analysis report
includes, and their order, before the PDF is prepared.

One row per eligible chart (``report_ui.report_plot_candidates``): a checkbox with the chart's title and its tab,
and Move up / Move down.  The Plots tab's chart is preselected; tabs not opened yet are listed as unavailable with
the reason.  Zero charts is valid - the summary, statistics, distributions and provenance are always included."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..widgets.common import IconButton
from ..widgets.dialogs import Modal, scroll


class ReportPlotsDialog(Modal):
    def __init__(self, candidates: list[dict], parent=None):
        super().__init__("Report contents", "Analysis report", parent, width=600)
        intro = QLabel("Choose the charts to include, in the order shown. The collection summary, statistics, model "
                       "distributions and provenance are always part of the report; each chart is rendered as a "
                       "vector-quality image on its own page with its axes, legend and scope.")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self.items = [c for c in candidates if c.get("available")]
        self.unavailable = [c for c in candidates if not c.get("available")]
        inner = QWidget()
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(4)
        self.rows: list[tuple[dict, QWidget, QCheckBox]] = []
        for c in self.items:
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            cb = QCheckBox(f"{c['title']} ({c['tab_label']} tab)")
            cb.setChecked(c["tab"] == "plots")
            cb.setAccessibleName(f"Include {c['title']} ({c['tab_label']} tab)")
            lay.addWidget(cb, 1)
            up = IconButton("arrow_up", "Move up")
            down = IconButton("arrow_down", "Move down")
            for b in (up, down):
                b.setFixedSize(32, 32)
                lay.addWidget(b)
            up.clicked.connect(lambda _c=False, r=row: self.move(r, -1))
            down.clicked.connect(lambda _c=False, r=row: self.move(r, 1))
            self.list.addWidget(row)
            self.rows.append((c, row, cb))
        if not self.items:
            none = QLabel("No chart is available yet: open the Plots, Statistics or Models tab of this collection "
                          "first. The report can still be exported without charts.")
            none.setWordWrap(True)
            none.setObjectName("Helper")
            self.list.addWidget(none)
        for c in self.unavailable:
            lab = QLabel(f"{c['title']}: {c['reason']}")
            lab.setObjectName("Helper")
            lab.setWordWrap(True)
            self.list.addWidget(lab)
        self.list.addStretch(1)
        self.body.addWidget(scroll(inner), 1)
        self.add_footer_button("Cancel", "secondary", self.reject)
        self.add_footer_button("Continue", "primary", self.accept)
        self.fit_height(inner, minimum=320)

    def move(self, row: QWidget, step: int) -> None:
        i = next(n for n, (_c, r, _b) in enumerate(self.rows) if r is row)
        j = i + step
        if not 0 <= j < len(self.rows):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        for _c, r, _b in self.rows:
            self.list.removeWidget(r)
        for n, (_c, r, _b) in enumerate(self.rows):
            self.list.insertWidget(n, r)

    def chosen(self) -> list[dict]:
        """The selected charts, in the chosen order."""
        return [c for c, _r, cb in self.rows if cb.isChecked()]
