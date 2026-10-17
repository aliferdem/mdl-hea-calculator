"""Shared Carbon v11 selection controls (painted; one implementation for the whole application).

* :class:`Dropdown` - Carbon dropdown (sm 32 px, field or inline style).  The field text is painted at a fixed
  origin (16 px) in every state - rest, hover, focus, open, disabled, invalid - and the focus / invalid frames
  are painted *over* the field in device pixels (``crisp``), so no state moves the text.  The list is the
  shared :class:`~.menu.CarbonMenu` (never a native or QComboBox popup).  A closed dropdown ignores the mouse
  wheel (the event goes to the scroll area underneath: scrolling the page never changes a value); in the open
  list the wheel only scrolls.  Keyboard: Enter / Space / Down open; in the list Up/Down move, Enter selects,
  Esc closes.  :meth:`Dropdown.addItem` & co. give the subset of the ``QComboBox`` API the panels use.
* :class:`MultiSelect` - a dropdown whose list is a checkbox popover.
* :class:`Popover` / :func:`open_popover` - Carbon popover (``layer-02`` surface, caret on the trigger).
* :class:`RichMenu` - :class:`CarbonMenu` with rich-text items and section headers.
* rich-text helpers (``rich``, ``text_doc``, ``html_width``, ``paint_html``, ``plain_text``).
"""

from __future__ import annotations

import html as _html
import time

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTextDocument
from PySide6.QtWidgets import QAbstractButton, QApplication, QSizePolicy, QVBoxLayout, QWidget

from .. import crisp, icons
from ..theme import BODY_COMPACT_01, FOCUS_WIDTH, HAIRLINE, LABEL_01, THEME, font, t
from .common import sup_html
from .menu import CarbonMenu
from .tooltip import CARET_H, body_rect, bubble_path, place_popover, popover_size


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
    index_changed = Signal(int)

    def __init__(self, items=(), value=None, prefix: str = "", inline: bool = False, accessible: str = "",
                 parent=None, width: int | None = None, placeholder: str = "", open_label: str = "",
                 row_height: int = 32, max_rows: int = 10):
        super().__init__(parent)
        self.prefix = prefix
        self.inline = inline
        self.placeholder = placeholder
        self.open_label = open_label        # shown in the trigger while the list is open (Range basis)
        self.row_height = row_height
        self.max_rows = max_rows
        self.popup = None
        self.items: list[tuple] = []
        self.value = None
        self.invalid = False
        self._hover = False
        self._open = False
        self.setFixedHeight(32)
        if width:
            self.setFixedWidth(width)
        else:
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
        if emit and not self.signalsBlocked():
            self.changed.emit(value)
            self.index_changed.emit(self.currentIndex())

    # -------------------------------------------------------------- QComboBox-compatible subset
    # (Composition setup, pagination and dialogs moved off QComboBox: its focus border shifted the text
    # by 2 px and a closed combo box changed its value under the mouse wheel.)
    @property
    def currentIndexChanged(self):
        return self.index_changed

    def addItem(self, text: str, data=None) -> None:
        self.items.append((data if data is not None else text, text))
        if self.value is None and not self.placeholder:
            self.value = self.items[-1][0]
        self.update()

    def clear(self) -> None:
        self.items = []
        self.value = None
        self.update()

    def _values(self) -> list:
        return [i[0] for i in self.items if i[0] != "--section--"]

    def count(self) -> int:
        return len(self._values())

    def currentIndex(self) -> int:
        vals = self._values()
        return vals.index(self.value) if self.value in vals else -1

    def setCurrentIndex(self, i: int) -> None:
        vals = self._values()
        if 0 <= i < len(vals):
            self.set_value(vals[i], emit=True)

    def currentData(self):
        return self.value

    def currentText(self) -> str:
        return plain_text(self.current_html())

    def itemData(self, i: int):
        vals = self._values()
        return vals[i] if 0 <= i < len(vals) else None

    def itemText(self, i: int) -> str:
        its = [it for it in self.items if it[0] != "--section--"]
        return plain_text(its[i][1]) if 0 <= i < len(its) else ""

    def findData(self, data) -> int:
        vals = self._values()
        return vals.index(data) if data in vals else -1

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
    def list_options(self) -> list:
        from .listbox import Option
        out = []
        for it in self.items:
            if it[0] == "--section--":
                out.append(Option(None, plain_text(it[1]), False, "", True))
                continue
            out.append(Option(it[0], it[1], it[2] if len(it) > 2 else True, it[3] if len(it) > 3 else ""))
        return out

    def open_menu(self) -> None:
        """Open the shared Carbon list (scrollable, screen-clamped; see ``listbox.py``)."""
        from .listbox import open_list
        pop = open_list(self, self.list_options(), value=self.value, row_height=self.row_height,
                        max_rows=self.max_rows)
        if pop is None:
            return
        self.popup = pop
        self._open = True
        self.update()
        pop.selected.connect(lambda v: self.set_value(v, emit=True))
        pop.closed.connect(self._popup_closed)

    def _popup_closed(self) -> None:
        self.popup = None
        self._open = False
        self.update()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Down):
            self.open_menu()
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        e.ignore()              # scrolling the page over a closed dropdown never changes it

    # -------------------------------------------------------------- painting
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def width_for_items(self) -> int:
        """Width that shows the longest item unclipped (16 px start + text + 8 px + 16 px chevron + 16 px)."""
        texts = [it[4] if len(it) > 4 and it[4] else it[1] for it in self.items if it[0] != "--section--"]
        widest = max((html_width(h) for h in texts), default=0)
        pre = html_width(self.prefix) + 8 if self.prefix else 0
        return int(16 + pre + widest + 40 + 1)

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
        html = self.open_label if (self._open and self.open_label) else self.current_html()
        empty = self.value is None and not isinstance(self, MultiSelect)
        color = "text-disabled" if not enabled else ("text-placeholder" if empty else
                                                     ("link-primary" if getattr(self, "link", False) else "text-primary"))
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
        elif self.hasFocus() or self._open:
            crisp.frame(p, r, FOCUS_WIDTH, t("focus"))     # Carbon: the open field keeps the focus frame
        p.end()


# ==================== popover
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
    """Carbon MultiSelect (sm): the shared list popup with a checkbox per option; every toggle applies at once
    (``changed`` carries the selected values; an empty tuple means "all").  ``all_label`` adds an "All" option
    (System size); field text: "All families (4)" / "2 selected" / ``summary(values)``."""

    ALL = "__all__"

    def __init__(self, noun: str, items=(), selected=(), parent=None, accessible: str = "", all_label: str = "",
                 summary=None, width: int | None = None):
        self.noun = noun
        self.all_label = all_label
        self.summary = summary
        self.selected: tuple = tuple(selected)
        super().__init__([], None, accessible=accessible or noun, parent=parent, width=width)
        self.set_options(items, selected)

    def set_options(self, items, selected=()) -> None:
        self.options = [tuple(i) for i in items]        # (value, html)
        values = [o[0] for o in self.options]
        self.selected = tuple(v for v in selected if v in values)
        self.update()

    def current_html(self) -> str:
        if self.summary is not None:
            return self.summary(self.selected)
        if not self.selected:
            return f"All {self.noun} ({len(self.options)})"
        if len(self.selected) == 1:
            for v, h in self.options:
                if v == self.selected[0]:
                    return h
        return f"{len(self.selected)} selected"

    def list_options(self) -> list:
        from .listbox import Option
        out = [Option(self.ALL, self.all_label)] if self.all_label else []
        return out + [Option(v, h) for v, h in self.options]

    def _checked_values(self) -> list:
        if not self.selected:
            return ([self.ALL] if self.all_label else []) + ([] if self.all_label else [v for v, _h in self.options])
        return list(self.selected)

    def open_menu(self) -> None:
        from .listbox import open_list
        pop = open_list(self, self.list_options(), values=self._checked_values(), multi=True,
                        row_height=self.row_height, max_rows=self.max_rows)
        if pop is None:
            return
        self.popup = pop
        self._open = True
        self.update()
        pop.toggled.connect(lambda vals, p=pop: self._toggled(vals, p))
        pop.closed.connect(self._popup_closed)

    def _toggled(self, vals, pop) -> None:
        values = [v for v, _h in self.options]
        if self.all_label:
            had_all = not self.selected
            if self.ALL in vals and not had_all:
                sel = ()                                         # "All" chosen: every size
            else:
                sel = tuple(v for v in values if v in vals and v != self.ALL)
        else:
            sel = tuple(v for v in values if v in vals)
            if len(sel) == len(values):
                sel = ()
        self.selected = sel
        pop.values = self._checked_values()
        pop.body.update()
        self.update()
        self.changed.emit(sel)
