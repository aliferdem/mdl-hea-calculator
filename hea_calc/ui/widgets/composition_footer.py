"""Composition setup footer (current Figma component "Composition setup", Mode=Single / Space / Expression).

Geometry (Figma 392:69349 and its bases): a 32 px footer whose 1 px ``border-subtle`` rule is the panel's at
y = 433; the status sits on the left - a 16 px status icon at x = 12, label-01 text at x = 36 and, when the
status explains itself further, a Toggletip trigger 8 px after the text; on the right the danger-ghost
*Clear* button and the 141 px primary *Calculate* button, flush with the panel edge, followed in Single and
Expression mode by a 32 px chevron segment (1 px separator) opening the secondary actions (Normalize,
Set equal, Copy table).  While a batch runs (State=Calculating) *Clear* becomes *Cancel* and *Calculate* an
inline loading "Calculating…"; the progress itself is shown in the UI shell header.

The footer is the one place where Composition setup explains a problem: invalid input, counting, readiness,
workload and model coverage.  Fields only mark *which* input is invalid (red frame).  Its geometry never
changes with the message, so a status never moves the panel.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QWidget

from .. import crisp, icons
from ..theme import HAIRLINE, LABEL_01, font, t
from .common import button
from .menu import CarbonMenu
from .tooltip import InfoButton

FOOTER_HEIGHT = 32
CALC_WIDTH = 141
CHEVRON_WIDTH = 32
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


class FooterStatus(QWidget):
    """Left part of the footer: status icon, label-01 text, optional Toggletip trigger."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status: Status | None = None
        self.setFixedHeight(FOOTER_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(STATUS_TEXT_X, 0, 0, 0)
        lay.setSpacing(8)
        self.text = QLabel("")
        self.text.setObjectName("FooterStatusText")
        self.text.setFont(font(LABEL_01))
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.text, 0, Qt.AlignmentFlag.AlignVCenter)
        self.info = InfoButton("", title="Status details")
        lay.addWidget(self.info, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        self.spinner = _Spinner(self)
        self.spinner.move(STATUS_ICON_X, (FOOTER_HEIGHT - 16) // 2)
        self.spinner.hide()
        self.info.hide()
        self.setAccessibleName("Composition status")

    def set_status(self, status: Status | None) -> None:
        if status == self.status:
            return
        self.status = status
        if status is None:
            self.text.setText("")
            self.info.hide()
            self.spinner.hide()
            self.setAccessibleDescription("")
            self.update()
            return
        _icon, token = STATUS_STYLE.get(status.kind, STATUS_STYLE["info"])
        self.text.setStyleSheet(f"color: {t(token)}; font-size: 12px; letter-spacing: 0.32px;")
        avail = max(40, self.width() - STATUS_TEXT_X - (24 if status.info else 0))
        self.text.setText(QFontMetrics(self.text.font()).elidedText(status.text, Qt.TextElideMode.ElideRight, avail))
        self.text.setToolTip(status.text if self.text.text() != status.text else "")
        self.info.tip_text = status.info or ""
        self.info.title = status.info_title or status.text
        self.info.setAccessibleName(f"About: {status.text}")
        self.info.setVisible(bool(status.info))
        self.spinner.setVisible(status.kind == "loading")
        self.setAccessibleDescription(status.text)
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        st, self.status = self.status, None
        self.set_status(st)

    def paintEvent(self, _e):
        st = self.status
        if st is None:
            return
        name = STATUS_STYLE.get(st.kind, STATUS_STYLE["info"])[0]
        if name:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            icons.paint(p, name, QRectF(STATUS_ICON_X, (FOOTER_HEIGHT - 16) / 2, 16, 16))
            p.end()


class SplitButton(QWidget):
    """Primary button with a chevron segment opening secondary actions (Figma: Calculate ▾).  The main part
    keeps the Figma width (141 px); the chevron is a 32 px primary segment after a 1 px separator."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.main = button(text, "primary", "sm")
        self.main.setFixedSize(CALC_WIDTH, FOOTER_HEIGHT)
        lay.addWidget(self.main)
        self.chevron = QPushButton()
        self.chevron.setProperty("kind", "primary")
        self.chevron.setProperty("btnsize", "sm")
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
        menu._fit_width()
        self._open = True
        self.chevron.update()
        pos = self.mapToGlobal(QPoint(self.width() - menu.width(), self.height()))
        menu.exec(pos)
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
    """The 32 px Composition setup footer (status | Clear | Calculate [▾])."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CompositionFooter")
        self.setFixedHeight(FOOTER_HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.status = FooterStatus()
        lay.addWidget(self.status, 1)
        self.clear_btn = button("Clear", "danger-ghost", "sm")
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
        self.action_stack.setFixedWidth(self.calc.width())

    def set_running(self, running: bool) -> None:
        """State=Calculating: Clear -> Cancel, Calculate -> inline loading (geometry unchanged)."""
        self.running = running
        self.action_stack.setCurrentIndex(1 if running else 0)
        self.clear_btn.setText("Cancel" if running else "Clear")
        self.clear_btn.setEnabled(True if running else self.clear_btn.isEnabled())

    def paintEvent(self, _e):
        p = QPainter(self)
        crisp.hline(p, 0, self.width(), 0, t("border-subtle-01"), HAIRLINE)
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
    """"⏱ ~1 s runtime   🗄 ~3.2 MB temp. storage" with vector Carbon icons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self.runtime = ""
        self.storage = ""

    def set_values(self, runtime: str, storage: str) -> None:
        self.runtime, self.storage = runtime, storage
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = font(LABEL_01)
        fb = font(LABEL_01)
        fb.setWeight(fb.Weight.DemiBold)
        x = 0.0
        for icon, value, word in (("time", self.runtime, " runtime"), ("file_storage", self.storage,
                                                                           " temp. storage")):
            icons.paint(p, icon, QRectF(x, 1, 16, 16), "icon-secondary")
            x += 20
            p.setFont(fb)
            p.setPen(QColor(t("text-primary")))
            p.drawText(QRectF(x, 0, 200, 18), int(Qt.AlignmentFlag.AlignVCenter), value or "…")
            x += QFontMetrics(fb).horizontalAdvance(value or "…")
            p.setFont(f)
            p.setPen(QColor(t("text-secondary")))
            p.drawText(QRectF(x, 0, 200, 18), int(Qt.AlignmentFlag.AlignVCenter), word)
            x += QFontMetrics(f).horizontalAdvance(word) + 12
        p.end()
