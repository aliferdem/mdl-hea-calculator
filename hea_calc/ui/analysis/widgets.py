"""Analysis UI primitives (Carbon v11 behaviour, HEA tokens, painted where Qt's stock widgets cannot match).

* :class:`ContentSwitcher` - text content switcher (sm, 32 px); arrow keys move, Enter/Space select;
* :class:`Dropdown` - Carbon dropdown (sm field or inline) whose label and items are rich text
  (``ΔH<sub>mix</sub>``); the list is the shared :class:`~..widgets.menu.CarbonMenu` (never a native menu);
* :class:`MultiSelect` - a dropdown whose list is a checkbox popover;
* :class:`Popover` - Carbon popover (``layer-02`` surface, caret on the trigger, Esc / outside click closes,
  focus returns to the trigger);
* :class:`DataTable` - painted read-only Carbon data table (xs 24 / sm 32 rows) with rich-text and tag cells,
  row hover, optional activation (drill-in chevron on hover/focus) and keyboard row focus;
* :class:`KVRows` - key-value rows (label, right-aligned value, unit, optional Toggletip);
* :class:`StatusIcon` - the 16 px scientific status icon (Tooltip on hover, Toggletip on click);
* :class:`ActionableNotification`, :class:`InlineLoading`, :class:`Skeleton`, :class:`EmptyBlock`.

No widget holds result objects: tables receive plain rows (text / tags), the views pass ids.
"""

from __future__ import annotations

import html as _html
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QTextDocument
from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from .. import crisp, icons
from ..theme import (BODY_COMPACT_01, CORNER_RADIUS, FOCUS_WIDTH, HAIRLINE, HEADING_COMPACT_01, LABEL_01, THEME,
                     font, t)
from ..widgets.common import button, paint_tag, sup_html
from ..widgets.menu import CarbonMenu
from ..widgets.scroll import inner_scroll_area
from ..widgets.tooltip import CARET_H, CARET_W, InfoButton, body_rect, bubble_path, place_popover, popover_size

ROW_XS, ROW_SM = 24, 32


# ====================================================================== rich text painting
def rich(text: str) -> str:
    """HTML with Unicode superscripts as <sup> (IBM Plex lacks ⁻ ¹ glyphs at small sizes)."""
    return sup_html(text or "")


_DOCS: dict = {}


def text_doc(html: str, typo=BODY_COMPACT_01, color: str = "text-primary", width: float = -1) -> QTextDocument:
    """A cached laid-out document for a short rich-text label (theme-aware)."""
    key = (html, typo, t(color), width, THEME.name)
    doc = _DOCS.get(key)
    if doc is None:
        if len(_DOCS) > 4000:
            _DOCS.clear()
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(font(typo))
        doc.setDefaultStyleSheet(f"body {{ color: {t(color)}; }} sub, sup {{ font-size: 70%; }}")
        doc.setHtml(f"<body>{rich(html)}</body>")
        if width > 0:
            doc.setTextWidth(width)
        _DOCS[key] = doc
    return doc


def html_width(html: str, typo=BODY_COMPACT_01) -> float:
    return text_doc(html, typo).idealWidth()


def paint_html(p: QPainter, rect: QRectF | QRect, html: str, typo=BODY_COMPACT_01, color: str = "text-primary",
               align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft, elide: bool = True) -> float:
    """Paint one line of rich text vertically centred in ``rect``; returns the width painted."""
    rect = QRectF(rect)
    doc = text_doc(html, typo, color)
    w = doc.idealWidth()
    h = doc.size().height()
    x = rect.left()
    if align & Qt.AlignmentFlag.AlignRight:
        x = rect.right() - w
    elif align & Qt.AlignmentFlag.AlignHCenter:
        x = rect.left() + (rect.width() - w) / 2
    y = rect.top() + (rect.height() - h) / 2
    p.save()
    if elide and w > rect.width():
        p.setClipRect(rect)
    p.translate(x, y)
    doc.drawContents(p)
    p.restore()
    return min(w, rect.width())


def plain_text(html: str) -> str:
    from ...core.analysis.models import plain
    return _html.unescape(plain(html))


def label(text: str, role: str = "body", wrap: bool = False, selectable: bool = False) -> QLabel:
    """A rich-text QLabel in one of the Analysis text roles."""
    lab = QLabel(rich(text))
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setWordWrap(wrap)
    lab.setObjectName({"body": "AnaBody", "secondary": "AnaSecondary", "label": "AnaLabel", "helper": "AnaHelper",
                       "heading": "AnaHeading", "title": "AnaTitle", "heading02": "AnaHeading02"}[role])
    if selectable:
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def stylesheet_rules(k: dict) -> str:
    """Analysis rules appended to the window stylesheet (theme tokens only)."""
    return f"""
#AnaBody {{ color: {k['text-primary']}; font-size: 14px; }}
#AnaSecondary {{ color: {k['text-secondary']}; font-size: 14px; }}
#AnaLabel {{ color: {k['text-secondary']}; font-size: 12px; letter-spacing: 0.32px; }}
#AnaHelper {{ color: {k['text-helper']}; font-size: 12px; letter-spacing: 0.32px; }}
#AnaHeading {{ color: {k['text-primary']}; font-size: 14px; font-weight: 600; }}
#AnaHeading02 {{ color: {k['text-primary']}; font-size: 16px; font-weight: 600; }}
#AnaTitle {{ color: {k['text-primary']}; font-size: 20px; }}
#AnaWorkspace {{ background: {k['background']}; }}
#AnaRail, #AnaRegion {{ background: {k['layer-01']}; }}
#AnaPopover {{ background: transparent; }}
#AnaNotification {{ background: {k['layer-02']}; border-left: 3px solid {k['support-info']}; }}
#AnaNotification[kind="warning"] {{ border-left: 3px solid {k['support-warning']}; }}
#AnaNotification[kind="error"] {{ border-left: 3px solid {k['support-error']}; }}
QPushButton[kind="tertiary"] {{ background: transparent; color: {k['text-primary']};
    border: 1px solid {k['border-inverse']}; padding: 0px 15px; }}
QPushButton[kind="tertiary"]:hover {{ background: {k['background-inverse']}; color: {k['text-inverse']}; }}
QPushButton[kind="tertiary"]:focus {{ border: 2px solid {k['focus']}; padding: 0px 14px; }}
"""


# ====================================================================== content switcher
class ContentSwitcher(QWidget):
    """Carbon content switcher (text, sm 32 px).  Segments share the group outline; the selected one is
    filled (``switcher-selected``) and framed; keyboard: ←/→ move focus, Enter/Space select (Carbon)."""

    changed = Signal(int)

    def __init__(self, labels: list[str], segment: int = 112, parent=None):
        super().__init__(parent)
        self.labels = list(labels)
        self.segment = segment
        self.index_ = 0
        self.focus_i = 0
        self.hover = -1
        self.badges: set[int] = set()
        self.setFixedSize(segment * len(labels), 32)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Analysis context")
        self._update_accessible()

    def _update_accessible(self):
        self.setAccessibleDescription(f"{self.labels[self.index_]} selected; arrow keys move, Enter selects")

    def index(self) -> int:
        return self.index_

    def set_index(self, i: int, emit: bool = False) -> None:
        if i == self.index_:
            return
        self.index_ = self.focus_i = i
        self.badges.discard(i)
        self._update_accessible()
        self.update()
        if emit:
            self.changed.emit(i)

    def set_badge(self, i: int, on: bool) -> None:
        (self.badges.add if on else self.badges.discard)(i)
        self.update()

    def _at(self, pos: QPoint) -> int:
        i = int(pos.x() // self.segment)
        return i if 0 <= i < len(self.labels) else -1

    def mouseMoveEvent(self, e):
        i = self._at(e.position().toPoint())
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            i = self._at(e.position().toPoint())
            if i >= 0:
                self.set_index(i, emit=True)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.focus_i = (self.focus_i + (1 if k == Qt.Key.Key_Right else -1)) % len(self.labels)
            self.update()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.set_index(self.focus_i, emit=True)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        self.focus_i = self.index_
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        crisp.fill_rounded(p, r, CORNER_RADIUS, t("switcher-unselected"))
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(r), CORNER_RADIUS, CORNER_RADIUS)
        for i, text in enumerate(self.labels):
            seg = QRect(i * self.segment, 0, self.segment, r.height())
            sel = i == self.index_
            if sel:
                crisp.fill_rounded(p, seg, CORNER_RADIUS, t("switcher-selected"))
                crisp.frame(p, seg, HAIRLINE, t("border-inverse"), CORNER_RADIUS)
            elif i == self.hover:
                p.save()
                p.setClipPath(clip)
                crisp.fill_rect(p, seg, t("layer-hover-01"))
                p.restore()
            f = font(HEADING_COMPACT_01 if sel else BODY_COMPACT_01)
            p.setFont(f)
            p.setPen(QColor(t("text-primary" if sel or i == self.hover else "text-secondary")))
            p.drawText(seg, int(Qt.AlignmentFlag.AlignCenter), text)
            if i in self.badges and not sel:
                tw = QFontMetrics(f).horizontalAdvance(text)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setBrush(QColor(t("support-info")))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(seg.center().x() + tw / 2 + 6, seg.center().y() - 6), 3, 3)
            if self.hasFocus() and i == self.focus_i:
                crisp.frame(p, seg, FOCUS_WIDTH, t("focus"), CORNER_RADIUS)
        crisp.frame(p, r, HAIRLINE, t("border-strong-02"), CORNER_RADIUS)
        p.end()


# ====================================================================== rich menu (shared Carbon menu)
class RichMenu(CarbonMenu):
    """:class:`CarbonMenu` whose items may carry rich text (``action.setProperty("html", ...)``) and
    section headers (``action.setProperty("section", True)``, disabled, not focusable)."""

    def content_width(self) -> int:
        w = super().content_width()
        lead = 24 if any(a.isCheckable() for a in self.actions()) else 0
        for a in self.actions():
            h = a.property("html")
            if h:
                w = max(w, int(html_width(h)) + 32 + lead + 8)
        return w

    def paintEvent(self, e):
        rich_acts = [a for a in self.actions() if a.property("html") or a.property("section")]
        if not rich_acts:
            return super().paintEvent(e)
        # paint the plain items through the base, then over-paint rich / section items
        saved = {}
        for a in rich_acts:
            saved[a] = a.text()
            a.setText("")
        super().paintEvent(e)
        for a, txt in saved.items():
            a.setText(txt)
        p = QPainter(self)
        check_col = any(a.isCheckable() for a in self.actions())
        active = self.activeAction()
        for a in rich_acts:
            if not a.isVisible():
                continue
            r = self.actionGeometry(a)
            x = 16 + (24 if check_col else 0)
            if a.property("section"):
                p.setFont(font(LABEL_01))
                p.setPen(QColor(t("text-helper")))
                p.drawText(QRectF(16, r.top(), self.width() - 32, r.height()),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), a.text())
                continue
            hot = a.isEnabled() and a is active
            color = "text-disabled" if not a.isEnabled() else ("text-primary" if hot else "text-secondary")
            paint_html(p, QRectF(x, r.top(), self.width() - x - 16, r.height()), a.property("html"),
                       BODY_COMPACT_01, color)
        p.end()


# ====================================================================== dropdown
class Dropdown(QAbstractButton):
    """Carbon dropdown, sm (32 px).  ``inline`` = transparent field with a leading label ("X", "Colour");
    otherwise the field style (``field-02`` fill, 1 px bottom rule).  Items: ``(value, html)`` tuples, a
    ``("--section--", title)`` header, or ``(value, html, enabled, tooltip)``."""

    changed = Signal(object)

    def __init__(self, items=(), value=None, prefix: str = "", inline: bool = False, accessible: str = "",
                 parent=None, width: int | None = None, placeholder: str = ""):
        super().__init__(parent)
        self.prefix = prefix
        self.inline = inline
        self.placeholder = placeholder
        self.items: list[tuple] = []
        self.value = None
        self.invalid = False
        self._hover = False
        self._open = False
        self.setFixedHeight(32)
        if width:
            self.setFixedWidth(width)
        self.setMinimumWidth(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(accessible or prefix or "Dropdown")
        self.clicked.connect(self.open_menu)
        self.set_items(items, value)

    # -------------------------------------------------------------- data
    def set_items(self, items, value=None) -> None:
        self.items = [tuple(i) for i in items]
        values = [i[0] for i in self.items if i[0] != "--section--"]
        self.value = value if value in values else (self.value if self.value in values else
                                                    (values[0] if values and value is None and not self.placeholder
                                                     else value if value in values else None))
        self.update()

    def set_value(self, value, emit: bool = False) -> None:
        if value == self.value:
            return
        self.value = value
        self.update()
        if emit:
            self.changed.emit(value)

    def current_html(self) -> str:
        """Field text: the item's short form (5th element) when it has one, else its list text."""
        for it in self.items:
            if it[0] == self.value and it[0] != "--section--":
                return it[4] if len(it) > 4 and it[4] else it[1]
        return self.placeholder

    def set_invalid(self, on: bool) -> None:
        self.invalid = on
        self.update()

    # -------------------------------------------------------------- menu
    def open_menu(self) -> None:
        menu = RichMenu(parent=self)
        menu.trigger_width = self.width()
        for it in self.items:
            if it[0] == "--section--":
                act = menu.add_action(plain_text(it[1]), enabled=False)
                act.setProperty("section", True)
                continue
            enabled = it[2] if len(it) > 2 else True
            act = menu.add_action(plain_text(it[1]), lambda v=it[0]: self.set_value(v, emit=True),
                                  enabled=enabled, checkable=True, checked=it[0] == self.value)
            act.setProperty("html", it[1])
            if len(it) > 3 and it[3]:
                act.setToolTip(it[3])
        self._open = True
        self.update()
        menu.exec(self.mapToGlobal(QPoint(0, self.height())))
        menu.deleteLater()
        self._open = False
        self.update()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Down):
            self.open_menu()
            return
        super().keyPressEvent(e)

    # -------------------------------------------------------------- painting
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self) -> QSize:
        w = 16 + (html_width(self.prefix) + 8 if self.prefix else 0) + html_width(self.current_html()) + 40
        return QSize(int(w), 32)

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        enabled = self.isEnabled()
        if self.inline:
            if enabled and (self._hover or self._open):
                crisp.fill_rect(p, r, t("layer-hover-01"))
        else:
            crisp.fill_rect(p, r, t("field-hover-02" if enabled and self._hover else "field-02"))
            crisp.hline_bottom(p, r, t("border-strong-02" if enabled else "border-disabled"), HAIRLINE)
        x = 16.0
        if self.prefix:
            x += paint_html(p, QRectF(x, 0, r.width() - x - 40, r.height()), self.prefix, BODY_COMPACT_01,
                            "text-secondary" if enabled else "text-disabled") + 8
        html = self.current_html()
        empty = self.value is None and not isinstance(self, MultiSelect)
        color = "text-disabled" if not enabled else ("text-placeholder" if empty else "text-primary")
        paint_html(p, QRectF(x, 0, r.width() - x - 40, r.height()), html, BODY_COMPACT_01, color)
        name = "chevron_down"
        p.save()
        if self._open:
            p.translate(r.width() - 24, r.height() / 2)
            p.rotate(180)
            p.translate(-(r.width() - 24), -r.height() / 2)
        icons.paint(p, name, QRectF(r.width() - 32, (r.height() - 16) / 2, 16, 16),
                    "icon-primary" if enabled else "icon-disabled")
        p.restore()
        if self.invalid:
            crisp.frame(p, r, FOCUS_WIDTH, t("support-error"))
        elif self.hasFocus():
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()


class LabeledField(QWidget):
    """A visible label (label-01) above a control (workspace rails, popovers)."""

    def __init__(self, text: str, control: QWidget, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.caption = label(text, "label")
        lay.addWidget(self.caption)
        lay.addWidget(control)
        self.control = control


# ====================================================================== popover
class Popover(QWidget):
    """Carbon popover: ``layer-02`` surface, 2 px corners (HEA tooltip radius), caret on the trigger, 16 px
    padding.  Closes on Esc, on an outside click or on the trigger; focus returns to the trigger."""

    closed = Signal()

    def __init__(self, anchor: QWidget, content: QWidget, width: int = 320, prefer: str = "bottom",
                 align: str = "start", title: str = ""):
        super().__init__(anchor.window(), Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.anchor = anchor
        self.setObjectName("AnaPopover")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAccessibleName(title or "Popover")
        lay = QVBoxLayout(self)
        content.setParent(self)
        content.setFixedWidth(width - 32)
        lay.addWidget(content)
        content.adjustSize()
        body = QSize(width, content.sizeHint().height() + 32)
        g = anchor.mapToGlobal(QPoint(0, 0))
        screen = (QApplication.screenAt(g) or QApplication.primaryScreen()).availableGeometry()
        self.placement = place_popover(body, QRect(g, anchor.size()), screen, prefer, align)
        side = self.placement.side
        lay.setContentsMargins(16 + (CARET_H if side == "right" else 0), 16 + (CARET_H if side == "bottom" else 0),
                               16 + (CARET_H if side == "left" else 0), 16 + (CARET_H if side == "top" else 0))
        self.setFixedSize(popover_size(body, side))
        self.move(self.placement.pos)

    def paintEvent(self, _e):
        from ..theme import TOOLTIP_RADIUS
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = body_rect(self.size(), self.placement.side)
        path = bubble_path(body, TOOLTIP_RADIUS, self.placement.caret, self.placement.side)
        p.fillPath(path, QColor(t("layer-02")))
        p.end()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        super().closeEvent(e)
        self.closed.emit()
        a = self.anchor
        if a is not None:
            a.closed_at = time.monotonic()
            a.setFocus(Qt.FocusReason.PopupFocusReason)


def open_popover(anchor: QWidget, content: QWidget, width: int = 320, prefer: str = "bottom",
                 align: str = "start", title: str = "") -> Popover | None:
    """Open a popover unless the trigger was just used to close one (outside click replayed)."""
    if time.monotonic() - getattr(anchor, "closed_at", 0.0) < 0.3:
        return None
    pop = Popover(anchor, content, width, prefer, align, title)
    pop.show()
    pop.setFocus(Qt.FocusReason.PopupFocusReason)
    return pop


# ====================================================================== multi-select
class MultiSelect(Dropdown):
    """Carbon MultiSelect (sm): the list is a checkbox popover; ``changed`` carries the selected values
    (an empty tuple means "all").  Field text: "All families (4)" / "2 selected"."""

    def __init__(self, noun: str, items=(), selected=(), parent=None, accessible: str = ""):
        self.noun = noun
        self.selected: tuple = tuple(selected)
        super().__init__([], None, accessible=accessible or noun, parent=parent)
        self.set_options(items, selected)

    def set_options(self, items, selected=()) -> None:
        self.options = [tuple(i) for i in items]        # (value, html)
        values = [o[0] for o in self.options]
        self.selected = tuple(v for v in selected if v in values)
        self.update()

    def current_html(self) -> str:
        if not self.selected:
            return f"All {self.noun} ({len(self.options)})"
        if len(self.selected) == 1:
            for v, h in self.options:
                if v == self.selected[0]:
                    return h
        return f"{len(self.selected)} selected"

    def open_menu(self) -> None:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        boxes = []
        for v, h in self.options:
            cb = QCheckBox(plain_text(h))
            cb.setChecked(v in self.selected)
            cb.setFixedHeight(32)
            cb.setProperty("value", v)
            lay.addWidget(cb)
            boxes.append(cb)
        foot = QHBoxLayout()
        clear = button("Clear", "ghost", "sm")
        foot.addWidget(clear)
        foot.addStretch(1)
        done = button("Apply", "primary", "sm")
        foot.addWidget(done)
        lay.addSpacing(8)
        lay.addLayout(foot)
        pop = open_popover(self, content, max(self.width(), 280), title=self.noun)
        if pop is None:
            return

        def apply():
            sel = tuple(cb.property("value") for cb in boxes if cb.isChecked())
            if len(sel) == len(boxes):
                sel = ()
            self.selected = sel
            self.update()
            pop.close()
            self.changed.emit(sel)

        def clear_all():
            for cb in boxes:
                cb.setChecked(False)

        clear.clicked.connect(clear_all)
        done.clicked.connect(apply)


# ====================================================================== section heading
class SectionHeading(QWidget):
    """heading-compact-01 title with an optional right-aligned summary (label-01) or a ghost link button."""

    link_clicked = Signal()

    def __init__(self, title: str, summary: str = "", link: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.title = label(title, "heading")
        lay.addWidget(self.title)
        lay.addStretch(1)
        self.summary = label(summary, "label")
        self.summary.setVisible(bool(summary))
        lay.addWidget(self.summary)
        self.link = None
        if link:
            self.link = button(link, "ghost", "sm")
            self.link.setFixedHeight(24)
            self.link.setStyleSheet("min-height: 24px; max-height: 24px; padding: 0px 8px;")
            self.link.clicked.connect(self.link_clicked.emit)
            lay.addWidget(self.link)
        self.setFixedHeight(24)

    def set_summary(self, text: str) -> None:
        self.summary.setText(rich(text))
        self.summary.setVisible(bool(text))


# ====================================================================== status icon
STATUS_ICON = {"in_domain": None, "extrapolated": ("warning_alt", "icon-secondary"),
               "data_suspect": ("warning_filled", "support-warning"), "caution": ("information", "icon-secondary"),
               "na": ("information", "icon-secondary")}
STATUS_NAME = {"extrapolated": "Extrapolated", "data_suspect": "Flagged binary data", "caution": "Caution",
               "na": "Not available"}


class StatusIcon(QAbstractButton):
    """16 px scientific status icon (design guide 5.10): Tooltip = short name, click = Toggletip text."""

    def __init__(self, kind: str, toggletip_html: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.tip_html = toggletip_html
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        name = STATUS_NAME.get(kind, kind)
        self.setToolTip(name)
        self.setAccessibleName(name)
        self.clicked.connect(self.open_tip)
        self._info = None

    def open_tip(self):
        if not self.tip_html:
            return
        from ..widgets.tooltip import Toggletip
        if time.monotonic() - getattr(self, "closed_at", 0.0) < 0.3:
            return
        tip = Toggletip(self, rich(self.tip_html), STATUS_NAME.get(self.kind, ""))
        tip.show()
        tip.setFocus(Qt.FocusReason.PopupFocusReason)

    def paintEvent(self, _e):
        spec = STATUS_ICON.get(self.kind)
        if not spec:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        name, token = spec
        icons.paint(p, name, QRectF(4, 4, 16, 16), token)
        if self.hasFocus():
            crisp.frame(p, self.rect(), FOCUS_WIDTH, t("focus"))
        p.end()


def paint_status(p: QPainter, rect: QRectF, kind: str | None) -> None:
    spec = STATUS_ICON.get(kind or "")
    if spec:
        icons.paint(p, spec[0], QRectF(rect.x(), rect.y() + (rect.height() - 16) / 2, 16, 16), spec[1])


# ====================================================================== data table
class Cell:
    """A table cell: rich text (``html``), a tag (``tag``), a status icon (``status``) or a bar
    (``bar`` = fraction 0..1).  ``align`` left/right/center; ``tip`` a Tooltip."""

    __slots__ = ("html", "tag", "status", "bar", "align", "tip", "color")

    def __init__(self, html: str = "", tag: str | None = None, status: str | None = None, bar: float | None = None,
                 align: str = "left", tip: str = "", color: str = ""):
        self.html, self.tag, self.status, self.bar, self.align, self.tip, self.color = (
            html, tag, status, bar, align, tip, color)


def C(x, **kw) -> Cell:
    return x if isinstance(x, Cell) else Cell("" if x is None else str(x), **kw)


class DataTable(QWidget):
    """Painted read-only Carbon data table (see module docstring).

    ``columns``: ``[(header_html, width_or_None, align)]`` - None columns share the remaining width.
    ``rows``: lists of cells (str or :class:`Cell`); ``groups`` (optional): {row index: group title} draws a
    32 px group-header row before that row.  ``activatable`` rows emit ``activated(index)`` on click /
    Enter and show a drill-in chevron on hover/focus.  The table is as tall as its rows (the page scrolls)."""

    activated = Signal(int)
    hovered = Signal(int)

    def __init__(self, columns, rows=(), row_height: int = ROW_XS, activatable: bool = False, header: bool = True,
                 parent=None, groups: dict | None = None, row_tips=None, selected: int = -1):
        super().__init__(parent)
        self.columns = list(columns)
        self.row_height = row_height
        self.activatable = activatable
        self.show_header = header
        self.hover = -1
        self.focus_row = -1
        self.selected = selected
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus if activatable else Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_rows(rows, groups, row_tips)

    # -------------------------------------------------------------- data
    def set_rows(self, rows, groups: dict | None = None, row_tips=None) -> None:
        self.rows = [[C(c) for c in r] for r in rows]
        self.groups = dict(groups or {})
        self.row_tips = list(row_tips) if row_tips else []
        self._layout_rows()
        self.update()

    def _layout_rows(self) -> None:
        y = ROW_SM if self.show_header else 0
        self.row_y: list[int] = []
        self.group_y: dict[int, int] = {}
        for i in range(len(self.rows)):
            if i in self.groups:
                self.group_y[i] = y
                y += ROW_SM
            self.row_y.append(y)
            y += self.row_height
        self.setFixedHeight(max(y, 1))

    def column_rects(self) -> list[tuple[float, float]]:
        fixed = sum(c[1] for c in self.columns if c[1])
        flex = [c for c in self.columns if not c[1]]
        free = max(0.0, self.width() - fixed)
        each = free / len(flex) if flex else 0
        out, x = [], 0.0
        for c in self.columns:
            w = c[1] if c[1] else each
            out.append((x, w))
            x += w
        return out

    def row_at(self, y: int) -> int:
        for i, ry in enumerate(self.row_y):
            if ry <= y < ry + self.row_height:
                return i
        return -1

    # -------------------------------------------------------------- input
    def mouseMoveEvent(self, e):
        i = self.row_at(int(e.position().y()))
        if i != self.hover:
            self.hover = i
            self.update()
            self.hovered.emit(i)
            tip = ""
            if 0 <= i < len(self.row_tips):
                tip = self.row_tips[i] or ""
            if not tip and i >= 0:
                x = e.position().x()
                for (cx, cw), cell in zip(self.column_rects(), self.rows[i]):
                    if cx <= x < cx + cw and cell.tip:
                        tip = cell.tip
            self.setToolTip(tip)
        if self.activatable:
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        if self.activatable and e.button() == Qt.MouseButton.LeftButton:
            i = self.row_at(int(e.position().y()))
            if i >= 0:
                self.focus_row = i
                self.activated.emit(i)

    def keyPressEvent(self, e):
        if not self.rows:
            return super().keyPressEvent(e)
        k = e.key()
        if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.focus_row = max(0, min(len(self.rows) - 1, self.focus_row + (1 if k == Qt.Key.Key_Down else -1)))
            self.update()
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.focus_row >= 0:
            self.activated.emit(self.focus_row)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        if self.focus_row < 0:
            self.focus_row = 0
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()

    # -------------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        w = self.width()
        cols = self.column_rects()
        if self.show_header:
            crisp.fill_rect(p, QRectF(0, 0, w, ROW_SM), t("header-row"))
            for (x, cw), c in zip(cols, self.columns):
                al = c[2] if len(c) > 2 else "left"
                self._text(p, QRectF(x, 0, cw, ROW_SM), c[0], al, HEADING_COMPACT_01, "text-primary")
        for i, gy in self.group_y.items():
            r = QRectF(0, gy, w, ROW_SM)
            crisp.hline_bottom(p, r, t("row-border"), HAIRLINE)
            paint_html(p, QRectF(16, gy, w - 32, ROW_SM), self.groups[i], HEADING_COMPACT_01, "text-primary")
        for i, row in enumerate(self.rows):
            y = self.row_y[i]
            r = QRectF(0, y, w, self.row_height)
            if i == self.selected:
                crisp.fill_rect(p, r, t("layer-selected-01"))
            elif i == self.hover:
                crisp.fill_rect(p, r, t("row-hover"))
            crisp.hline_bottom(p, r, t("row-border"), HAIRLINE)
            for (x, cw), cell, c in zip(cols, row, self.columns):
                self._cell(p, QRectF(x, y, cw, self.row_height), cell)
            if self.activatable and (i == self.hover or (self.hasFocus() and i == self.focus_row)):
                icons.paint(p, "chevron_right", QRectF(w - 24, y + (self.row_height - 16) / 2, 16, 16),
                            "icon-secondary")
            if self.hasFocus() and i == self.focus_row:
                crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()

    def _text(self, p, rect, html, align, typo, color):
        left, right = (8, 16) if align == "right" else (16, 4)
        inner = QRectF(rect.x() + left, rect.y(), max(0.0, rect.width() - left - right), rect.height())
        a = {"left": Qt.AlignmentFlag.AlignLeft, "right": Qt.AlignmentFlag.AlignRight,
             "center": Qt.AlignmentFlag.AlignHCenter}.get(align, Qt.AlignmentFlag.AlignLeft)
        paint_html(p, inner, html, typo, color, a)

    def _cell(self, p, rect: QRectF, cell: Cell):
        if cell.tag:
            x = rect.x() + 16
            wtag = paint_tag(p, QRectF(x, rect.y(), 0, rect.height()), cell.tag, align_left=True)
            if cell.status:
                paint_status(p, QRectF(x + wtag + 4, rect.y(), 16, rect.height()), cell.status)
            return
        if cell.status and not cell.html:
            paint_status(p, QRectF(rect.x() + 16, rect.y(), 16, rect.height()), cell.status)
            return
        if cell.bar is not None:
            track = QRectF(rect.x() + 16, rect.center().y() - 4, rect.width() - 32, 8)
            crisp.fill_rect(p, track, t("layer-hover-01"))
            crisp.fill_rect(p, QRectF(track.x(), track.y(), track.width() * max(0.0, min(1.0, cell.bar)), 8),
                            cell.color or t("border-strong-01"))
            return
        self._text(p, rect, cell.html, cell.align, BODY_COMPACT_01, cell.color or "text-primary")


# ====================================================================== key-value rows
class KVRows(QWidget):
    """Read-only key-value rows (design guide 5.2): label (secondary), value (right, tabular), unit, optional
    Toggletip trigger; 24 px rows with a 1 px row rule.  ``rows``: ``(label, value, unit, info_html|None)``
    or ``(label, value, unit, info, tag)`` where ``tag`` replaces the value."""

    def __init__(self, rows=(), label_w: int = 172, value_w: int = 88, unit_w: int = 79, parent=None):
        super().__init__(parent)
        self.label_w, self.value_w, self.unit_w = label_w, value_w, unit_w
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.set_rows(rows)

    def set_rows(self, rows) -> None:
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                _w = it.widget()
                _w.setParent(None)
                _w.deleteLater()
        for r in rows:
            self.lay.addWidget(_KVRow(r, self.label_w, self.value_w, self.unit_w))


class _KVRow(QWidget):
    def __init__(self, r, lw, vw, uw):
        super().__init__()
        self.setFixedHeight(ROW_XS)
        lab, val, unit = r[0], r[1], r[2]
        info = r[3] if len(r) > 3 else None
        tag = r[4] if len(r) > 4 else None
        self.tip = r[5] if len(r) > 5 else ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.k = label(lab, "secondary")
        self.k.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.k.setMinimumWidth(min(lw, 120))
        self.k.setToolTip(plain_text(lab))
        lay.addWidget(self.k, 1)
        if tag:
            from ..widgets.common import TagLabel
            tl = TagLabel(tag, long_text=False)
            tl.setFixedHeight(18)
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addStretch(1)
            bl.addWidget(tl)
            box.setFixedWidth(vw)
            lay.addWidget(box)
        else:
            self.v = label(val, "body", selectable=True)
            self.v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.v.setFixedWidth(vw)
            if self.tip:
                self.v.setToolTip(self.tip)
            lay.addWidget(self.v)
        lay.addSpacing(8)
        u = label(unit or "", "label")
        u.setFixedWidth(uw)
        lay.addWidget(u)
        if info:
            ib = InfoButton(rich(info), title=plain_text(lab))
            holder = QWidget()
            holder.setFixedSize(24, 24)
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(4, 4, 4, 4)
            hl.addWidget(ib)
            lay.addWidget(holder)
        else:
            lay.addSpacing(24)

    def paintEvent(self, _e):
        p = QPainter(self)
        crisp.hline_bottom(p, self.rect(), t("border-subtle-01"), HAIRLINE)
        p.end()


# ====================================================================== notifications / loading / empty
class ActionableNotification(QFrame):
    """Carbon actionable inline notification (low contrast): icon, title, subtitle, ghost action; no close."""

    action = Signal()
    ICONS = {"info": ("information", "support-info"), "warning": ("warning_filled", "support-warning"),
             "error": ("status_none", "support-error"), "success": ("status_ok", "support-success")}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AnaNotification")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 8, 8, 8)
        lay.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = label("", "heading", wrap=True)
        self.body = label("", "body", wrap=True)
        texts.addWidget(self.title)
        texts.addWidget(self.body)
        lay.addLayout(texts, 1)
        self.button = button("", "ghost", "sm")
        self.button.clicked.connect(self.action.emit)
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(48)
        self.hide()

    def show_message(self, kind: str, title: str, body: str = "", action: str = "") -> None:
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        name, token = self.ICONS.get(kind, self.ICONS["info"])
        self.icon.setPixmap(icons.pixmap(name, token, 20))
        self.title.setText(rich(title))
        self.body.setText(rich(body))
        self.body.setVisible(bool(body))
        self.button.setText(action)
        self.button.setVisible(bool(action))
        self.show()


class InlineLoading(QWidget):
    """Carbon inline loading: 16 px spinner + text (+ optional Cancel)."""

    cancel = Signal()

    def __init__(self, text: str = "Loading…", cancellable: bool = True, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.spin = _Spinner()
        lay.addWidget(self.spin)
        self.text = label(text, "secondary")
        lay.addWidget(self.text)
        self.cancel_btn = button("Cancel", "ghost", "sm")
        self.cancel_btn.clicked.connect(self.cancel.emit)
        self.cancel_btn.setVisible(cancellable)
        lay.addWidget(self.cancel_btn)
        lay.addStretch(1)
        self.setFixedHeight(32)

    def set_text(self, text: str) -> None:
        self.text.setText(rich(text))

    def showEvent(self, e):
        self.spin.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.spin.timer.stop()
        super().hideEvent(e)


class _Spinner(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.setAccessibleName("Loading")

    def _tick(self):
        self.angle = (self.angle + 18) % 360
        self.update()

    def paintEvent(self, _e):
        from PySide6.QtGui import QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(t("border-interactive")), 2)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawArc(QRectF(2, 2, 12, 12), -self.angle * 16, 270 * 16)
        p.end()


class Skeleton(QWidget):
    """Carbon skeleton placeholder (first load only): a ``layer-hover-01`` block with a slow shimmer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        self.phase = (self.phase + 0.02) % 1.4
        self.update()

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e):
        from PySide6.QtGui import QLinearGradient
        p = QPainter(self)
        r = QRectF(self.rect())
        base = QColor(t("layer-hover-01"))
        p.fillRect(r, base)
        g = QLinearGradient(r.left() + (self.phase - 0.4) * r.width(), 0, r.left() + self.phase * r.width(), 0)
        hi = QColor(t("layer-02"))
        g.setColorAt(0, base)
        g.setColorAt(0.5, hi)
        g.setColorAt(1, base)
        p.fillRect(r, g)
        p.end()


class EmptyBlock(QWidget):
    """HEA empty state (design guide 5.9): illustration, title 20/28, body, up to two sm buttons.
    ``centred`` for workspace panels; embedded panels keep the left-aligned x 64 geometry."""

    action = Signal(str)

    def __init__(self, title: str, body: str, art: str | None = "document", buttons=(), centred: bool = False,
                 margin_x: int = 44, margin_top: int = 24, parent=None):
        super().__init__(parent)
        from ..widgets.common import Illustration
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0 if centred else margin_x, margin_top, 0, 0)
        outer.setSpacing(0)
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        if art:
            lay.addWidget(Illustration(art), 0, Qt.AlignmentFlag.AlignHCenter if centred else Qt.AlignmentFlag.AlignLeft)
            lay.addSpacing(24)
        self.title = QLabel(title)
        self.title.setObjectName("AnaTitle")
        self.title.setWordWrap(True)
        self.body = label(body, "secondary", wrap=True)
        self.body.setMaximumWidth(420)
        lay.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter if centred else Qt.AlignmentFlag.AlignLeft)
        lay.addSpacing(8)
        lay.addWidget(self.body, 0, Qt.AlignmentFlag.AlignHCenter if centred else Qt.AlignmentFlag.AlignLeft)
        if centred:
            self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.body.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        if buttons:
            lay.addSpacing(16)
            row = QHBoxLayout()
            row.setSpacing(8)
            if centred:
                row.addStretch(1)
            for i, (key, text) in enumerate(buttons):
                b = button(text, "secondary" if i == 0 else "ghost", "sm")
                b.clicked.connect(lambda _c=False, k=key: self.action.emit(k))
                row.addWidget(b)
            row.addStretch(1)
            lay.addLayout(row)
        if centred:
            outer.addStretch(1)
            outer.addWidget(col, 0, Qt.AlignmentFlag.AlignHCenter)
            outer.addStretch(2)
        else:
            outer.addWidget(col)
            outer.addStretch(1)


def scroll_page(widget: QWidget, margins=(20, 16, 20, 16)) -> tuple[QScrollArea, QVBoxLayout]:
    """An inner scroll area (4 px overlay-style bar, wheel rule) whose content is ``widget`` with the
    embedded content padding; returns the area and the content layout."""
    lay = QVBoxLayout(widget)
    lay.setContentsMargins(*margins)
    lay.setSpacing(16)
    sa = inner_scroll_area(widget)
    return sa, lay


class Divider(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, _e):
        p = QPainter(self)
        crisp.fill_rect(p, QRectF(self.rect()), t("border-subtle-01"))
        p.end()


_ = (QEvent, CARET_W)
