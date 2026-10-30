"""Composition setup footer (current Figma component "Composition setup", Mode=Single / Space / Expression,
nodes 392:69182 / 392:69349 / 392:69514 and the Composition space / Expression bases).

Geometry: a 40 px footer under a 1 px ``background-selected`` rule (Figma Rectangle 257, y = 449 of 490).  On the
right the ghost *Clear* button (``link-primary``, 66 px) and the split *Calculate* button - a 141 px primary part
and a 40 px chevron segment (1 px apart) opening the secondary actions (Set equal, Copy table) - flush
with the panel edge.  While a batch runs (State=Calculating) *Clear* becomes *Cancel* and *Calculate* an inline
loading "Calculating…"; the progress itself is shown in the title bar.

The panel's status (invalid input, counting, readiness, workload, model coverage) is no longer in the footer: it is
the panel header's :class:`~.status_tag.PanelStatus` (``footer.status``, placed in the header by the panel).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QWidget

from .. import crisp, icons
from ..theme import HAIRLINE, LABEL_01, font, t
from .common import button
from .menu import CarbonMenu
from .tooltip import InfoButton

FOOTER_HEIGHT = 40
CALC_WIDTH = 141
CHEVRON_WIDTH = 40
STATUS_ICON_X = 12
STATUS_TEXT_X = 36

# kind -> (icon, text token)
STATUS_STYLE = {
    "ready": ("notify_success", "text-secondary"),
    "info": ("notify_info", "text-secondary"),
    "warning": ("notify_warning", "text-secondary"),
    "error": ("notify_error", "text-error"),
    "loading": (None, "text-secondary"),
}


@dataclass(frozen=True)
class Status:
    """What the footer says: ``kind`` (ready / info / warning / error / loading), a short ``text`` and an
    optional Toggletip (``info`` - rich text or toggletip blocks) that explains it."""
    kind: str
    text: str
    info: object = None
    info_title: str = ""
    tag: str | None = None           # tag colour override (red / green / blue / gray) of the header status

    @property
    def blocking(self) -> bool:
        return self.kind == "error"


class _Spinner(QWidget):
    """Carbon small loading indicator (16 px), animated only while visible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        self.angle = (self.angle + 24) % 360
        self.update()

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1.5, 1.5, 13, 13)
        p.setPen(QPen(QColor(t("border-subtle-01")), 2))
        p.drawEllipse(r)
        pen = QPen(QColor(t("support-info")), 2)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawArc(r, -self.angle * 16, 270 * 16)
        p.end()


class SplitButton(QWidget):
    """Primary button with a chevron segment opening secondary actions (Figma: Calculate ▾).  The main part
    keeps the Figma width (141 px); the chevron is a 40 px primary segment after a 1 px separator."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.main = button(text, "primary", "md")
        self.main.setFixedSize(CALC_WIDTH, FOOTER_HEIGHT)
        lay.addWidget(self.main)
        self.chevron = QPushButton()
        self.chevron.setProperty("kind", "primary")
        self.chevron.setProperty("btnsize", "md")
        self.chevron.setObjectName("SplitChevron")
        self.chevron.setFixedSize(CHEVRON_WIDTH, FOOTER_HEIGHT)
        self.chevron.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chevron.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.chevron.setAccessibleName("More actions")
        self.chevron.setToolTip("More actions")
        self.chevron.setProperty("tip_align", "bottom")
        self.chevron.clicked.connect(self.open_menu)
        self.chevron.installEventFilter(self)
        lay.addWidget(self.chevron)
        self.menu_items: list[tuple] = []          # (text, slot, enabled, icon)
        self._open = False

    def set_split(self, on: bool) -> None:
        self.chevron.setVisible(on)
        self.setFixedWidth(CALC_WIDTH + ((CHEVRON_WIDTH + 1) if on else 0))

    def set_actions(self, items: list[tuple]) -> None:
        self.menu_items = list(items)
        self.chevron.setEnabled(any(i[2] for i in items))

    def open_menu(self) -> None:
        menu = CarbonMenu(parent=self)
        for text, slot, enabled, icon in self.menu_items:
            if text == "-":
                menu.addSeparator()
                continue
            menu.add_action(text, slot, enabled=enabled, icon=icon)
        menu.trigger_width = self.width()
        self._open = True
        self.chevron.update()
        menu.open_below(self, align_right=True)
        menu.deleteLater()
        self._open = False
        self.chevron.update()

    def eventFilter(self, obj, ev):
        if obj is self.chevron and ev.type() == ev.Type.Paint:
            QPushButton.paintEvent(obj, ev)
            p = QPainter(obj)
            r = QRectF((obj.width() - 16) / 2, (obj.height() - 16) / 2, 16, 16)
            if self._open:
                p.translate(r.center())
                p.rotate(180)
                p.translate(-r.center())
            icons.paint(p, "chevron_down", r, color=t("text-on-color") if obj.isEnabled()
                        else t("text-on-color-disabled"))
            p.end()
            return True
        return False


class CompositionFooter(QWidget):
    """The 40 px Composition setup footer (Clear | Calculate [▾]); ``status`` is the header status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from .status_tag import PanelStatus
        self.setObjectName("CompositionFooter")
        self.setFixedHeight(FOOTER_HEIGHT + 1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 0)
        lay.setSpacing(0)
        self.status = PanelStatus()            # shown in the panel header (CompositionPanel places it)
        # Add element (icon-only ghost, md 40 x 40) at the far left: compositions can be built with the Elements
        # panel collapsed.  Clear and Calculate keep their group and geometry on the right.
        from .common import IconButton, set_prop
        self.add_btn = IconButton("add", "Add element")
        set_prop(self.add_btn, "square", str(FOOTER_HEIGHT))   # the 40 x 40 icon buttons' rule (toolbar, pager)
        lay.addWidget(self.add_btn)
        lay.addStretch(1)
        self.clear_btn = button("Clear", "ghost", "md")
        self.clear_btn.setProperty("tip_align", "bottom")
        lay.addWidget(self.clear_btn)
        self.action_stack = QStackedWidget()
        self.calc = SplitButton("Calculate")
        self.calc_btn = self.calc.main
        self.busy = QWidget()
        bl = QHBoxLayout(self.busy)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(8)
        self.busy_spinner = _Spinner()
        bl.addWidget(self.busy_spinner)
        self.busy_text = QLabel("Calculating…")
        bl.addWidget(self.busy_text)
        bl.addStretch(1)
        self.action_stack.addWidget(self.calc)
        self.action_stack.addWidget(self.busy)
        lay.addWidget(self.action_stack)
        self.running = False
        self.set_split(True)

    def set_split(self, on: bool) -> None:
        self.calc.set_split(on)
        self.action_stack.setFixedWidth(CALC_WIDTH + CHEVRON_WIDTH + 1)

    def set_primary(self, text: str, split: bool) -> None:
        """The primary action: Calculate [v], or Expression's Parse expression - full width (182 px, Figma Draft)
        or split (Stale).  The footer's geometry never changes."""
        if self.calc.main.text() != text:
            self.calc.main.setText(text)
        self.calc.set_split(split)
        self.calc.main.setFixedWidth(CALC_WIDTH if split else CALC_WIDTH + CHEVRON_WIDTH + 1)
        self.calc.setFixedWidth(CALC_WIDTH + CHEVRON_WIDTH + 1)

    def set_running(self, running: bool) -> None:
        """State=Calculating: Clear -> Cancel, Calculate -> inline loading (geometry unchanged)."""
        self.running = running
        self.action_stack.setCurrentIndex(1 if running else 0)
        self.clear_btn.setText("Cancel" if running else "Clear")
        self.clear_btn.setEnabled(True if running else self.clear_btn.isEnabled())

    def paintEvent(self, _e):
        p = QPainter(self)
        crisp.hline(p, 0, self.width(), 0, t("background-selected"), HAIRLINE)
        p.end()


class WorkloadSummary(QWidget):
    """Composition space workload summary (Figma State=Normal / Large workload): label + Toggletip, the
    number of valid compositions (body-compact semibold) and the estimated runtime / temporary storage with
    the Carbon time and file--storage icons.  Estimates come from core.limits (measured rates)."""

    changed = Signal()

    def __init__(self, info_html: str, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        cap = QLabel("Workload summary")
        cap.setObjectName("Label01")
        head.addWidget(cap)
        self.info = InfoButton(info_html, title="Workload summary")
        head.addWidget(self.info)
        head.addStretch(1)
        lay.addLayout(head)
        self.count = QLabel("")
        self.count.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.count)
        self.est = _EstimateRow()
        lay.addWidget(self.est)
        lay.addStretch(1)

    def set_values(self, count_html: str, runtime: str, storage: str) -> None:
        self.count.setText(count_html)
        self.est.set_values(runtime, storage)


class _EstimateRow(QWidget):
    """"⏱ ~1 s runtime   🗄 ~3.2 MB temp. storage" with vector Carbon icons.  Text that does not fit ends in an
    ellipsis and the full estimate becomes the row's Tooltip (Carbon overflow content; visual QA F-06 - a
    five-character storage value was cut mid-word: "temp. storag")."""

    ICON_ADVANCE = 20
    GAP = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.runtime = ""
        self.storage = ""

    def set_values(self, runtime: str, storage: str) -> None:
        self.runtime, self.storage = runtime, storage
        self._sync_tip()
        self.update()

    def _fonts(self):
        f = font(LABEL_01)
        fb = font(LABEL_01)
        fb.setWeight(fb.Weight.DemiBold)
        return f, fb

    def _parts(self):
        return (("time", self.runtime or "…", " runtime"), ("file_storage", self.storage or "…", " temp. storage"))

    def full_text(self) -> str:
        return f"{self.runtime or '…'} runtime, {self.storage or '…'} temp. storage"

    def natural_width(self) -> float:
        f, fb = self._fonts()
        fm, fmb = QFontMetricsF(f), QFontMetricsF(fb)
        parts = self._parts()
        return sum(self.ICON_ADVANCE + fmb.horizontalAdvance(v) + fm.horizontalAdvance(w) for _i, v, w in parts) \
            + self.GAP * (len(parts) - 1)

    def is_elided(self) -> bool:
        return self.natural_width() > self.width()

    def _sync_tip(self) -> None:
        self.setToolTip(self.full_text() if self.is_elided() else "")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._sync_tip()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f, fb = self._fonts()
        avail = float(self.width())
        x = 0.0
        for icon, value, word in self._parts():
            if x + 16 > avail:
                break
            icons.paint(p, icon, QRectF(x, 1, 16, 16), "icon-secondary")
            x += self.ICON_ADVANCE
            stop = False
            for text, fnt, token in ((value, fb, "text-primary"), (word, f, "text-secondary")):
                fm = QFontMetricsF(fnt)
                adv = fm.horizontalAdvance(text)
                if x + adv > avail:                     # overflow: end in a visible ellipsis, never a cut glyph
                    text = fm.elidedText(text, Qt.TextElideMode.ElideRight, max(0.0, avail - x))
                    stop = True
                p.setFont(fnt)
                p.setPen(QColor(t(token)))
                p.drawText(QRectF(x, 0, max(0.0, avail - x), 18), int(Qt.AlignmentFlag.AlignVCenter), text)
                if stop:
                    break
                x += adv
            if stop:
                break
            x += self.GAP
        p.end()
