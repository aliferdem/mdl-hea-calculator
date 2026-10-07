"""Carbon v11 Menu for PySide6 - the one popup-menu primitive of the application.

Every opening menu (File, Theme, Export, the results-row context menu and any submenu) is a
:class:`CarbonMenu`, so none falls back to the native Windows menu look.

Behaviour comes from ``QMenu``, which already implements the Carbon menu keyboard contract
(Carbon MCP, components/menu "Keyboard interaction"): Up/Down move focus, Enter/Space activate,
Right/Left open/close a submenu, Esc closes and returns focus to the trigger; it also handles
screen-edge collision, submenu placement and accessibility.  Appearance is painted here from the
semantic theme tokens, so it follows dark/light immediately:

* container ``$layer-01``, 4 px block padding, items 32 px (size "sm", the Carbon React default),
  16 px inline padding, body-compact-01 text in ``$text-secondary``;
* hover/keyboard-active: ``$layer-hover-01`` and ``$text-primary``; keyboard focus adds the 2 px
  ``$focus`` ring inside the item;
* disabled: ``$text-disabled``, no hover; destructive (``action.setProperty("danger", True)``):
  hover ``$button-danger-primary`` with ``$text-on-color``;
* selectable (checkable) items reserve a 16 px check column (checkmark when checked);
* icons (``action.setProperty("icon_name", ...)``) are 16 px, recoloured from tokens;
* dividers are a 1 px ``$border-subtle-01`` rule with 4 px margins;
* shortcut text right-aligned in ``$text-secondary``; submenus show a caret;
* width from the content, clamped to Carbon's 10 rem / 18 rem (160 / 288 px).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QFontMetrics, QKeySequence, QPainter
from PySide6.QtWidgets import QMenu

from .. import crisp, icons
from ..theme import (BODY_COMPACT_01, FOCUS_WIDTH, HAIRLINE, MENU_MAX_WIDTH, MENU_MIN_WIDTH, MENU_PADDING_X,
                     font, t)

ICON = 16
ICON_GAP = 8
SHORTCUT_GAP = 32


class CarbonMenu(QMenu):
    def __init__(self, title: str = "", parent=None):
        super().__init__(title, parent)
        self.setObjectName("CarbonMenu")
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.setFont(font(BODY_COMPACT_01))
        self._keyboard = False
        self.aboutToShow.connect(self._fit_width)

    # -------------------------------------------------------------- building
    def add_action(self, text: str, slot=None, *, danger: bool = False, icon: str | None = None,
                   shortcut: str | None = None, enabled: bool = True, checkable: bool = False,
                   checked: bool = False) -> QAction:
        act = QAction(text, self)
        if slot is not None:
            act.triggered.connect(lambda _c=False: slot())
        if danger:
            act.setProperty("danger", True)
        if icon:
            act.setProperty("icon_name", icon)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.setEnabled(enabled)
        if checkable:
            act.setCheckable(True)
            act.setChecked(checked)
        self.addAction(act)
        return act

    def add_submenu(self, title: str) -> "CarbonMenu":
        sub = CarbonMenu(title, self)
        self.addMenu(sub)
        return sub

    # -------------------------------------------------------------- geometry
    def _columns(self) -> tuple[bool, bool]:
        acts = [a for a in self.actions() if a.isVisible() and not a.isSeparator()]
        return any(a.isCheckable() for a in acts), any(a.property("icon_name") for a in acts)

    def content_width(self) -> int:
        fm = QFontMetrics(self.font())
        check, icon = self._columns()
        lead = (ICON + ICON_GAP if check else 0) + (ICON + ICON_GAP if icon else 0)
        widest = 0
        for a in self.actions():
            if a.isSeparator() or not a.isVisible():
                continue
            w = fm.horizontalAdvance(a.text().replace("&", ""))
            sc = a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if sc:
                w += SHORTCUT_GAP + fm.horizontalAdvance(sc)
            if a.menu() is not None:
                w += ICON_GAP + ICON
            widest = max(widest, w)
        return 2 * MENU_PADDING_X + lead + widest

    def _fit_width(self) -> None:
        w = max(MENU_MIN_WIDTH, getattr(self, "trigger_width", 0),
                min(MENU_MAX_WIDTH, self.content_width()))
        self.setFixedWidth(w)

    # -------------------------------------------------------------- input (focus ring only for keyboard)
    def keyPressEvent(self, e):
        self._keyboard = True
        super().keyPressEvent(e)
        self.update()

    def mouseMoveEvent(self, e):
        if self._keyboard:
            self._keyboard = False
            self.update()
        super().mouseMoveEvent(e)

    def showEvent(self, e):
        self._keyboard = False
        super().showEvent(e)

    # -------------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        crisp.fill_rect(p, self.rect(), t("layer-01"))
        fm = QFontMetrics(self.font())
        p.setFont(self.font())
        check_col, icon_col = self._columns()
        active = self.activeAction()
        for a in self.actions():
            if not a.isVisible():
                continue
            r = self.actionGeometry(a)
            # Qt sizes its action rects from its own metrics; the menu is fitted to our content
            r.setLeft(0)
            r.setRight(self.width() - 1)
            if a.isSeparator():
                y = r.top() + r.height() // 2
                crisp.hline(p, r.left(), r.right() + 1, y, t("border-subtle-01"), HAIRLINE)
                continue
            enabled = a.isEnabled()
            hot = enabled and a is active
            danger = bool(a.property("danger"))
            if hot:
                crisp.fill_rect(p, r, t("button-danger-primary" if danger else "layer-hover-01"))
            if not enabled:
                color = t("text-disabled")
            elif hot:
                color = t("text-on-color" if danger else "text-primary")
            else:
                color = t("text-secondary")
            icon_token = "icon-disabled" if not enabled else "icon-primary"
            x = r.left() + MENU_PADDING_X
            cy = r.top() + (r.height() - ICON) / 2
            if check_col:
                if a.isChecked():
                    icons.paint(p, "checkmark", QRectF(x, cy, ICON, ICON), icon_token,
                                color=color if hot and danger else None)
                x += ICON + ICON_GAP
            if icon_col:
                name = a.property("icon_name")
                if name:
                    icons.paint(p, name, QRectF(x, cy, ICON, ICON), icon_token,
                                color=color if hot and danger else None)
                x += ICON + ICON_GAP
            right = r.right() + 1 - MENU_PADDING_X
            if a.menu() is not None:
                icons.paint(p, "chevron_right", QRectF(right - ICON, cy, ICON, ICON), icon_token,
                            color=color if hot and danger else None)
                right -= ICON + ICON_GAP
            sc = a.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            p.setPen(QColor(color))
            if sc:
                p.setPen(QColor(t("text-disabled") if not enabled else (color if hot else t("text-secondary"))))
                p.drawText(QRectF(x, r.top(), right - x, r.height()),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), sc)
                right -= fm.horizontalAdvance(sc) + SHORTCUT_GAP
                p.setPen(QColor(color))
            text = fm.elidedText(a.text().replace("&", ""), Qt.TextElideMode.ElideRight, int(right - x))
            p.drawText(QRectF(x, r.top(), right - x, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
            if hot and self._keyboard:
                crisp.frame(p, r, FOCUS_WIDTH, t("focus"))
        p.end()


# ---------------------------------------------------------------------- other popups
def carbon_context_menu(widget) -> None:
    """Show a text widget's standard context menu (Undo / Cut / Copy / Paste / Select all) as a
    CarbonMenu: the actions are Qt's own (behaviour, enablement, shortcuts), only the popup is ours."""
    def show(pos):
        std = widget.createStandardContextMenu()
        menu = CarbonMenu(parent=widget)
        for act in std.actions():
            menu.addAction(act)
        target = widget.viewport() if hasattr(widget, "viewport") else widget
        menu.exec(target.mapToGlobal(pos))
        menu.deleteLater()
        std.deleteLater()
    widget.setProperty("carbon_menu", True)
    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    widget.customContextMenuRequested.connect(show)


def carbonize_popups(root) -> None:
    """Route every popup under ``root`` through the Carbon look: text-field context menus become
    :class:`CarbonMenu`; combo-box (Carbon dropdown) lists get the styled delegate, so the theme's
    32 px item / hover / selected rules apply instead of the platform list."""
    from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit, QStyledItemDelegate, QTextEdit
    for w in root.findChildren(QLineEdit) + root.findChildren(QPlainTextEdit) + root.findChildren(QTextEdit):
        if w.contextMenuPolicy() == Qt.ContextMenuPolicy.DefaultContextMenu and not w.property("carbon_menu"):
            carbon_context_menu(w)
    for cb in root.findChildren(QComboBox):
        if not isinstance(cb.itemDelegate(), QStyledItemDelegate) or cb.itemDelegate().metaObject().className() \
                == "QComboBoxDelegate":
            cb.setItemDelegate(QStyledItemDelegate(cb))
