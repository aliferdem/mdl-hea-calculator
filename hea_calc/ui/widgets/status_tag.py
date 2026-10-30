"""Panel header status - a Carbon tag or an inline loading indicator in a panel header (Figma Composition space
bases 393:66042, Expression bases 584:51933: "Large workload", "Partial model coverage", "Missing range values",
"Parsed successfully", "Multiple errors", "Expression changed", "◌ Updating…").

* :class:`StatusTag` - Carbon *operational* tag, 24 px pill (radius 12), 8 px inline padding, label-01 text, in
  the Carbon tag palettes bound in Figma (``tag-{red,green,blue,gray}-{bg,fg}``).  When the status has an
  explanation the tag is a toggletip trigger (click / Enter / Space opens it, Esc closes it) - the same behaviour as
  :class:`~.tooltip.InfoButton`; without one it is static content.
* :class:`PanelStatus` - shows one :class:`~.composition_footer.Status`: ``loading`` as a 16 px spinner + label-01
  ``text-secondary`` text; ``error`` as a red tag; ``info`` / ``warning`` as a blue tag; ``success`` as a green
  tag; ``ready`` (and ``None``) as nothing.  A ``Status.tag`` colour overrides the mapping.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from .. import crisp
from ..theme import FOCUS_WIDTH, LABEL_01, font, t
from .tooltip import InfoButton

TAG_H = 24
TAG_PAD = 8
KIND_TAG = {"error": "red", "info": "blue", "warning": "blue", "success": "green"}


class StatusTag(InfoButton):
    """See module docstring."""

    def __init__(self, parent=None):
        super().__init__("", parent, title="Status")
        self.text_ = ""
        self.color = "gray"
        self.max_w = 10_000
        self.setFont(font(LABEL_01))
        self.setFixedHeight(TAG_H)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_tag(self, text: str, color: str = "gray", info=None, title: str = "") -> None:
        self.text_ = text
        self.color = color if color in ("red", "green", "blue", "gray") else "gray"
        self.tip_text = info or ""
        self.title = title or text
        interactive = bool(info)
        self.setEnabled(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus if interactive else Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor if interactive else Qt.CursorShape.ArrowCursor)
        self.setAccessibleName(text)
        self.setAccessibleDescription("Opens an explanation; press Escape to close it." if interactive else "")
        self._fit()
        self.update()

    def set_max_width(self, w: int) -> None:
        self.max_w = max(TAG_H, int(w))
        self._fit()

    def _fit(self) -> None:
        natural = QFontMetrics(font(LABEL_01)).horizontalAdvance(self.text_) + 2 * TAG_PAD + 2   # + rounding
        self.setFixedSize(min(natural, self.max_w), TAG_H)
        self.setToolTip(self.text_ if natural > self.max_w else "")

    def interactive(self) -> bool:
        return bool(self.tip_text)

    def toggle(self):
        if self.interactive():
            super().toggle()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        crisp.fill_pill(p, r, t(f"tag-{self.color}-bg"))
        p.setFont(font(LABEL_01))
        p.setPen(QColor(t(f"tag-{self.color}-fg")))
        fm = QFontMetrics(p.font())
        text = fm.elidedText(self.text_, Qt.TextElideMode.ElideRight, int(r.width()) - 2 * TAG_PAD + 2)
        p.drawText(r.adjusted(TAG_PAD, 0, -TAG_PAD + 2, 0), int(Qt.AlignmentFlag.AlignVCenter), text)
        if self.hasFocus():
            crisp.frame(p, self.rect(), FOCUS_WIDTH, t("focus"), TAG_H / 2)
        p.end()


class HeaderIconButton(InfoButton):
    """A 40 × 40 icon-only ghost button of a panel header (Figma: the Expression help button at x 377 and every
    panel's collapse button at x 417): 16 px ``icon-primary`` icon, hover ``layer-hover-01``, pressed
    ``layer-active-01``, 2 px inside focus frame, a Tooltip naming the action.  With ``toggletip`` (rich text or a
    callable returning it) it is a toggletip trigger; otherwise ``clicked`` is the action."""

    SIZE = 40

    def __init__(self, icon_name: str, tip: str, parent=None, toggletip=None):
        super().__init__(toggletip or "", parent, title=tip)
        self.icon_name = icon_name
        self.has_toggletip = toggletip is not None
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setToolTip(tip)
        self.setProperty("tip_align", "bottom")
        self.setAccessibleName(tip)
        self.setAccessibleDescription("Opens an explanation; press Escape to close it." if self.has_toggletip
                                      else "")

    def set_icon(self, name: str) -> None:
        if name != self.icon_name:
            self.icon_name = name
            self.update()

    def toggle(self):
        if self.has_toggletip:
            super().toggle()

    def paintEvent(self, _e):
        from .. import icons
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        if not self.isEnabled():
            token = "icon-disabled"
        else:
            token = "icon-primary"
            if self.isDown():
                crisp.fill_rect(p, r, t("layer-active-01"))
            elif self.underMouse() or self.is_open():
                crisp.fill_rect(p, r, t("layer-hover-01"))
        icons.paint(p, self.icon_name, QRectF((r.width() - 16) / 2, (r.height() - 16) / 2, 16, 16), token)
        if self.hasFocus():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()


class PanelStatus(QWidget):
    """See module docstring.  ``status`` is the shown :class:`Status` (or ``None``)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from .composition_footer import _Spinner
        self.status = None
        self.setObjectName("PanelStatus")
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addStretch(1)
        self.spinner = _Spinner()
        lay.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        self.text = QLabel("")
        self.text.setObjectName("PanelStatusText")
        self.text.setFont(font(LABEL_01))
        lay.addWidget(self.text, 0, Qt.AlignmentFlag.AlignVCenter)
        self.tag = StatusTag()
        lay.addWidget(self.tag, 0, Qt.AlignmentFlag.AlignVCenter)
        for w in (self.spinner, self.text, self.tag):
            w.hide()
        self.setAccessibleName("Composition status")

    def set_status(self, status) -> None:
        if status == self.status:
            return
        self.status = status
        loading = status is not None and status.kind == "loading"
        color = None
        if status is not None and not loading:
            color = getattr(status, "tag", None) or KIND_TAG.get(status.kind)
        self.spinner.setVisible(loading)
        self.text.setVisible(loading)
        if loading:
            self.text.setText(status.text)
            self.text.setStyleSheet(f"color: {t('text-secondary')};")
        self.tag.setVisible(color is not None)
        if color is not None:
            self.tag.set_tag(status.text, color, status.info, status.info_title or status.text)
            self.tag.set_max_width(max(TAG_H, self.width()))
        self.setAccessibleDescription(status.text if status is not None else "")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.tag.isVisible():
            self.tag.set_max_width(max(TAG_H, self.width()))

    # the footer's former API (tests, tools)
    @property
    def info(self):
        return self.tag
