"""Carbon v11 Menu for PySide6 - the one popup-menu primitive of the application.

Every opening menu (File, Theme, Export, the results-row context menu and any submenu) is a
:class:`CarbonMenu`, so none falls back to the native Windows menu look.

Behaviour comes from ``QMenu``, which already implements the Carbon menu keyboard contract
(Carbon MCP, components/menu-buttons "Keyboard interaction"): Up/Down move focus, Enter/Space activate,
Right/Left open/close a submenu, Esc closes and returns focus to the trigger; it also handles
screen-edge collision, submenu placement and accessibility.  Appearance is painted here from the
semantic theme tokens (Carbon MCP, components/menu "Specifications - Color / Interactive state color"):

* container ``$layer`` - contextual: the menu opens over ``layer-01`` panels, so it is ``layer-02`` - with the
  Carbon elevation ``box-shadow 0 2px 6px rgba(0,0,0,.2)`` painted in a transparent margin;
* items ``sm`` 32 / ``md`` 40 / ``lg`` 48 px (Carbon "Sizing - Height"; a menu matches its trigger: header
  menus lg, the results context menu md, toolbar MenuButtons sm), 16 px inline padding, body-compact-01 text
  in ``$text-secondary``;
* hover / keyboard-active: ``$layer-hover`` and ``$text-primary``; keyboard focus adds the 2 px ``$focus`` frame
  inside the item; disabled ``$text-disabled``; danger hover ``$support-error`` with ``$text-on-color``;
* selectable (checkable) items reserve a 16 px check column (checkmark when checked); leading icons
  (``icon_name``) or trailing icons (``trailing_icon``) are 16 px in ``$icon-secondary`` / ``$icon-primary``;
* dividers are a full-width 1 px ``$border-subtle`` rule;
* width from the content, clamped to Carbon's 10 rem / 18 rem (160 / 288 px).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QFontMetrics, QFontMetricsF, QKeySequence, QPainter
from PySide6.QtWidgets import QMenu

from .. import crisp, icons
from ..theme import (BODY_COMPACT_01, FOCUS_WIDTH, HAIRLINE, MENU_MAX_WIDTH, MENU_MIN_WIDTH, MENU_PADDING_X,
                     font, t)

ICON = 16
ICON_GAP = 8
SHORTCUT_GAP = 32
SHADOW = 6
SIZES = {"sm": 32, "md": 40, "lg": 48}


class CarbonMenu(QMenu):
    def __init__(self, title: str = "", parent=None, size: str = "sm", block_padding: int = 4):
        super().__init__(title, parent)
        self.setObjectName("CarbonMenu")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFont(font(BODY_COMPACT_01))
        self.size_name = size
        self.item_height = SIZES.get(size, 32)
        self.block_padding = block_padding
        self._keyboard = False
        self.setStyleSheet(
            f"QMenu#CarbonMenu {{ background: transparent; border: none; margin: {SHADOW}px; "
            f"padding: {block_padding}px 0px; }}"
            f"QMenu#CarbonMenu::item {{ padding: 0px 16px; min-height: {self.item_height}px; "
            f"height: {self.item_height}px; }}"
            f"QMenu#CarbonMenu::separator {{ height: 1px; margin: 0px; }}")
        self.aboutToShow.connect(self._fit_width)

    # -------------------------------------------------------------- building
    def add_action(self, text: str, slot=None, *, danger: bool = False, icon: str | None = None,
                   shortcut: str | None = None, enabled: bool = True, checkable: bool = False,
                   checked: bool = False, trailing_icon: str | None = None) -> QAction:
        act = QAction(text, self)
        if slot is not None:
            act.triggered.connect(lambda _c=False: slot())
        if danger:
            act.setProperty("danger", True)
        if icon:
            act.setProperty("icon_name", icon)
        if trailing_icon:
            act.setProperty("trailing_icon", trailing_icon)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.setEnabled(enabled)
        if checkable:
            act.setCheckable(True)
            act.setChecked(checked)
        self.addAction(act)
        return act

    def add_submenu(self, title: str) -> "CarbonMenu":
        sub = CarbonMenu(title, self, self.size_name)
        self.addMenu(sub)
        return sub

    # -------------------------------------------------------------- geometry
    def surface(self) -> QRect:
        """The painted menu surface (the widget minus the transparent shadow margin)."""
        return self.rect().adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)

    def target_below(self, trigger, align_right: bool = False) -> QPoint:
        """Global position that puts the surface flush under ``trigger``."""
        x = trigger.width() - (self.width() - 2 * SHADOW) if align_right else 0
        return trigger.mapToGlobal(QPoint(x - SHADOW, trigger.height() - SHADOW))

    def placed(self, pos: QPoint, above_y: int | None = None) -> QPoint:
        """``pos`` (widget top-left, global) kept inside the available screen area (brief §5, §77): a menu that does
        not fit below opens above - flush over its trigger (``above_y``: the trigger's top) or upward from the
        pointer - and never covers the taskbar; Qt itself only clamps to the full screen."""
        from PySide6.QtGui import QGuiApplication
        size = self.sizeHint()
        scr = (QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()).availableGeometry()
        self.opens_up = False
        x, y = pos.x(), pos.y()
        if y + size.height() - SHADOW > scr.bottom() + 1:
            self.opens_up = True
            y = (above_y - size.height() + SHADOW) if above_y is not None else (pos.y() + 2 * SHADOW - size.height())
        y = max(scr.top() - SHADOW, min(y, scr.bottom() + 1 + SHADOW - size.height()))
        x = max(scr.left() - SHADOW, min(x, scr.right() + 1 + SHADOW - size.width()))
        return QPoint(x, y)

    def open_below(self, trigger, exec_: bool = True, align_right: bool = False):
        """Open with the surface flush under ``trigger`` (the shadow margin hangs outside it); above it when the
        screen has no room below."""
        self.trigger_width = max(getattr(self, "trigger_width", 0), trigger.width())
        self._fit_width()
        pos = self.placed(self.target_below(trigger, align_right), trigger.mapToGlobal(QPoint(0, 0)).y())
        if exec_:
            return self.exec(pos)
        self.popup(pos)
        return None

    def exec_at(self, global_pos: QPoint):
        """Context menu: the surface's top-left corner at ``global_pos`` (upward from it near the screen bottom)."""
        self._fit_width()
        return self.exec(self.placed(global_pos - QPoint(SHADOW, SHADOW)))

    def _columns(self) -> tuple[bool, bool, bool]:
        acts = [a for a in self.actions() if a.isVisible() and not a.isSeparator()]
        return (any(a.isCheckable() for a in acts), any(a.property("icon_name") for a in acts),
                any(a.property("trailing_icon") for a in acts))

    def content_width(self) -> int:
        # fractional metrics, rounded up (+1 px): at DPR 1.25 / 1.5 integer advances under-measured the painted
        # text and the longest item was elided ("Import compositio…")
        fm = QFontMetricsF(font(BODY_COMPACT_01))
        check, icon, trailing = self._columns()
        lead = (ICON + ICON_GAP if check else 0) + (ICON + ICON_GAP if icon else 0)
        show_sc = self.property("show_shortcuts") is not False
        widest = 0
        for a in self.actions():
            if a.isSeparator() or not a.isVisible():
                continue
            w = fm.horizontalAdvance(a.text().replace("&", ""))
            sc = a.shortcut().toString(QKeySequence.SequenceFormat.NativeText) if show_sc else ""
            if sc:
                w += SHORTCUT_GAP + fm.horizontalAdvance(sc)
            if a.menu() is not None or trailing:
                w += SHORTCUT_GAP + ICON
            widest = max(widest, w)
        return int(math.ceil(2 * MENU_PADDING_X + lead + widest)) + 1

    def _fit_width(self) -> None:
        w = max(MENU_MIN_WIDTH, getattr(self, "trigger_width", 0),
                min(MENU_MAX_WIDTH, self.content_width()))
        self.setFixedWidth(w + 2 * SHADOW)

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
        from .listbox import paint_shadow
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface = self.surface()
        paint_shadow(p, surface)
        crisp.fill_rect(p, surface, t("layer-02"))
        f = font(BODY_COMPACT_01)
        fm = QFontMetrics(f)
        p.setFont(f)
        check_col, icon_col, _trailing = self._columns()
        active = self.activeAction()
        show_sc = self.property("show_shortcuts") is not False
        for a in self.actions():
            if not a.isVisible():
                continue
            r = self.actionGeometry(a)
            # Qt sizes its action rects from its own metrics; the menu is fitted to our content
            r.setLeft(surface.left())
            r.setRight(surface.right())
            if a.isSeparator():
                y = r.top() + r.height() // 2
                crisp.hline(p, r.left(), r.right() + 1, y, t("border-subtle-02"), HAIRLINE)
                continue
            enabled = a.isEnabled()
            hot = enabled and a is active
            danger = bool(a.property("danger"))
            if hot:
                crisp.fill_rect(p, r, t("support-error" if danger else "layer-hover-02"))
            if not enabled:
                color = t("text-disabled")
            elif hot:
                color = t("text-on-color" if danger else "text-primary")
            else:
                color = t("text-secondary")
            icon_token = "icon-disabled" if not enabled else ("icon-primary" if hot else "icon-secondary")
            on_color = color if hot and danger else None
            x = r.left() + MENU_PADDING_X
            cy = r.top() + (r.height() - ICON) / 2
            if check_col:
                if a.isChecked():
                    icons.paint(p, "checkmark", QRectF(x, cy, ICON, ICON), icon_token, color=on_color)
                x += ICON + ICON_GAP
            if icon_col:
                name = a.property("icon_name")
                if name:
                    icons.paint(p, name, QRectF(x, cy, ICON, ICON), icon_token, color=on_color)
                x += ICON + ICON_GAP
            right = r.right() + 1 - MENU_PADDING_X
            trailing = a.property("trailing_icon")
            if a.menu() is not None or trailing:
                icons.paint(p, trailing or "chevron_right", QRectF(right - ICON, cy, ICON, ICON), icon_token,
                            color=on_color)
                right -= ICON + ICON_GAP
            sc = a.shortcut().toString(QKeySequence.SequenceFormat.NativeText) if show_sc else ""
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
        menu.exec_at(target.mapToGlobal(pos))
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
