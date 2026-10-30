"""Carbon v11 Menu for PySide6 - the one popup-menu primitive of the application.

Every opening menu (File, Theme, Export, the results-row context menu and any submenu) is a
:class:`CarbonMenu`, so none falls back to the native Windows menu look.

Behaviour comes from ``QMenu``, which already implements the Carbon menu keyboard contract
(Carbon MCP, components/menu-buttons "Keyboard interaction"): Up/Down move focus, Enter/Space activate,
Right/Left open/close a submenu, Esc closes and returns focus to the trigger; it also handles
screen-edge collision, submenu placement and accessibility.  Appearance is painted here from the
semantic theme tokens (Carbon MCP, components/menu "Specifications - Color / Interactive state color"):

* container ``$layer`` - contextual: the menu opens over ``layer-01`` panels, so it is ``layer-02`` - with the
  Carbon elevation ``box-shadow 0 2px 6px rgba(0,0,0,.2)`` painted in a transparent margin.  That is the only
  elevation: Qt 6.7's ``windows11`` style installs a ``QGraphicsDropShadowEffect`` (3, 3, #b43f3f3f) on every
  QMenu, which stacked a hard right/bottom band (a light rim in the dark theme) on it - it is removed whenever
  the style polishes the menu (visual QA F-03);
* header menus (``open_below(..., merge=True)``) are one elevated surface with their trigger
  (CORRECT_FILE_BUTTON / CORRECT_THEME_BUTTON): the union outline of trigger and menu is shadowed - no seam at
  the join, the trigger elevated (F-05).  The menu itself stays an ordinary QMenu (its geometry and hit-testing
  untouched: offsetting its items under the trigger made QMenu drop the last item's hit area - "Exit" and
  "System default" were not clickable); the trigger's share of the shadow is a separate decorative window that
  is transparent for input (:class:`_TriggerShadow`).  A shadow margin at the screen edge hangs off-screen instead
  of pushing the surface (F-08);
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

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QFontMetrics, QFontMetricsF, QKeySequence, QPainter, QRegion
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QMenu, QWidget

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
        # the merged trigger (header menus) in menu coordinates: it lies just above the surface, outside the
        # widget, and only shapes the painted shadow - never the menu's geometry or hit-testing
        self.tab: QRect | None = None
        self._trigger = None
        self._target: QPoint | None = None        # the intended top-left (Qt clamps popups to the screen)
        self._overlay: _TriggerShadow | None = None
        self._apply_style()
        self.aboutToShow.connect(self._fit_width)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"QMenu#CarbonMenu {{ background: transparent; border: none; margin: {SHADOW}px; "
            f"padding: {self.block_padding}px 0px; }}"
            f"QMenu#CarbonMenu::item {{ padding: 0px 16px; min-height: {self.item_height}px; "
            f"height: {self.item_height}px; }}"
            f"QMenu#CarbonMenu::separator {{ height: 1px; margin: 0px; }}")
        self._strip_style_shadow()

    def _strip_style_shadow(self) -> None:
        """Remove the windows11 style's QMenu drop shadow (F-03): Carbon's painted elevation is the only one."""
        if isinstance(self.graphicsEffect(), QGraphicsDropShadowEffect):
            self.setGraphicsEffect(None)

    def event(self, e):
        res = super().event(e)
        if e.type() in (QEvent.Type.Polish, QEvent.Type.StyleChange):
            self._strip_style_shadow()
        return res

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

    def open_below(self, trigger, exec_: bool = True, align_right: bool = False, merge: bool = False,
                   active=None):
        """Open with the surface flush under ``trigger`` (the shadow margin hangs outside it); above it when the
        screen has no room below.  ``merge`` (header menus): trigger and menu are one elevated surface."""
        self.trigger_width = max(getattr(self, "trigger_width", 0), trigger.width())
        self.tab, self._trigger = None, None
        self._fit_width()
        top_left = trigger.mapToGlobal(QPoint(0, 0))
        pos = self.placed(self.target_below(trigger, align_right), top_left.y())
        if merge and not self.opens_up:
            dx = top_left.x() - pos.x()
            if SHADOW <= dx and dx + trigger.width() <= self.width() - SHADOW:
                self.tab = QRect(dx, SHADOW - trigger.height(), trigger.width(), trigger.height())
                self._trigger = trigger
        self._target = pos
        if exec_:
            return self.exec(pos, active) if active is not None else self.exec(pos)
        self.popup(pos, active) if active is not None else self.popup(pos)
        return None

    def exec_at(self, global_pos: QPoint):
        """Context menu: the surface's top-left corner at ``global_pos`` (upward from it near the screen bottom)."""
        self.tab, self._trigger = None, None
        self._fit_width()
        self._target = self.placed(global_pos - QPoint(SHADOW, SHADOW))
        return self.exec(self._target)

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
        bar = getattr(self, "menubar", None)
        if bar is not None and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            act = self.activeAction()
            if not (e.key() == Qt.Key.Key_Right and act is not None and act.menu() is not None):
                if bar.switch_menu(self, -1 if e.key() == Qt.Key.Key_Left else 1, keyboard=True):
                    return
        super().keyPressEvent(e)
        self.update()

    def mouseMoveEvent(self, e):
        if self._keyboard:
            self._keyboard = False
            self.update()
        bar = getattr(self, "menubar", None)
        if bar is not None and bar.hover_switch(self, e.globalPosition().toPoint()):
            return
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        # the popup receives every press while open; one on its own trigger only closes it (no replay to the
        # trigger, which would open the menu again) - QMenu does the same for QPushButton::setMenu triggers
        if self.tab is not None and self.tab.contains(e.position().toPoint()):
            self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, True)
            self.close()
            e.accept()
            return
        super().mousePressEvent(e)

    def showEvent(self, e):
        self._keyboard = False
        self._strip_style_shadow()
        super().showEvent(e)
        # Qt clamps the whole popup, transparent shadow margin included, to the screen: at the screen edge the
        # surface stopped 6 px short of its trigger (F-08).  The margin may hang off-screen; the surface may not.
        if self._target is not None and self.pos() != self._target:
            self.move(self._target)
        if self.tab is not None:
            if self._overlay is None:
                self._overlay = _TriggerShadow(self)
            self._overlay.place()

    def hideEvent(self, e):
        self._target = None
        if self._overlay is not None:
            self._overlay.hide()
        super().hideEvent(e)

    def shadow_rects(self) -> tuple[QRect, ...]:
        """The elevated outline in menu coordinates: the surface, plus the trigger tab for a merged menu."""
        return (self.surface(),) if self.tab is None else (self.surface(), self.tab)

    # -------------------------------------------------------------- painting
    def paintEvent(self, _e):
        from .listbox import paint_shadow
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        surface = self.surface()
        if self.tab is not None:
            # one outline for trigger + menu; nothing is painted over the trigger (its bottom edge overlaps the
            # top shadow margin), so the join has no seam
            p.save()
            p.setClipRegion(QRegion(self.rect()).subtracted(QRegion(self.tab)))
            paint_shadow(p, surface, self.tab)
            p.restore()
        else:
            paint_shadow(p, surface)
        crisp.fill_rect(p, surface, t("layer-02"))
        if self.tab is not None:
            # The menu window and the main window (which paints the open trigger, layer-02) are placed in device
            # pixels each with its own rounding: at 125 % one device row of the title bar (#161616 in the dark theme)
            # stayed visible between the trigger and the surface - a seam.  At a fractional ratio the menu paints the
            # one device row directly above its surface in the open trigger's colour (layer-02): it closes that row
            # when there is a gap and repaints the trigger's own colour when there is none.  At an integral ratio
            # both windows sit on whole pixels, there is no gap, and nothing is painted over the trigger.  The
            # shadow outline is unchanged (painted above, clipped).
            scale = abs(p.deviceTransform().m11() or 1.0)
            if abs(scale - round(scale)) > 1e-6:
                crisp.fill_rect(p, QRectF(self.tab.left(), surface.top() - 1 / scale, self.tab.width(), 1 / scale),
                                t("layer-02"))
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


class _TriggerShadow(QWidget):
    """The trigger's share of a merged header menu's elevation: a decorative, input-transparent window around the
    trigger, ending where the menu window begins (no area is painted twice).  It paints the same union outline
    as the menu, clipped out of the trigger, so trigger and menu read as one elevated surface."""

    def __init__(self, menu: CarbonMenu):
        super().__init__(menu, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.menu = menu
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def place(self) -> None:
        m = self.menu
        origin = _origin(m)
        tab_global = QRect(origin + m.tab.topLeft(), m.tab.size())
        top = tab_global.top() - SHADOW
        self.overlap = 0                          # device rows shared with the menu window (painted by the menu)
        h = origin.y() - top
        self._rect = QRect(tab_global.left() - SHADOW, top, tab_global.width() + 2 * SHADOW, h)
        self.setGeometry(self._rect)
        self.show()
        self.update()
        # The two windows are placed in device pixels, each rounded on its own: at a fractional scale (125 %) the
        # overlay could end one device row above the menu window and that row of the trigger's shadow stayed
        # unpainted - a white line beside the open trigger in the light theme.  The native rectangles are final
        # only after this event-loop turn; then the seam is closed exactly.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._seal)

    def _seal(self) -> None:
        m = self.menu
        if not self.isVisible() or m.tab is None or not m.isVisible():
            return
        gap = _native_gap(self, m)
        if gap is not None and gap > 0:
            r = QRect(self._rect)
            r.setHeight(r.height() + 1)           # one logical px = 1-2 device rows: the overlap is clipped
            self.setGeometry(r)
            gap = _native_gap(self, m)
        self.overlap = -gap if gap is not None and gap < 0 else 0
        self.update()

    def paintEvent(self, _e):
        from .listbox import paint_shadow
        m = self.menu
        if m.tab is None:
            return
        off = _origin(m) - _origin(self)
        surface, tab = m.surface().translated(off), m.tab.translated(off)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QRegion(self.rect()).subtracted(QRegion(tab))
        p.setClipRegion(clip)
        if self.overlap:                          # the rows the menu window paints itself: never twice
            dpr = self.devicePixelRatioF()
            p.setClipRect(QRectF(0, 0, self.width(), self.height() - self.overlap / dpr),
                          Qt.ClipOperation.IntersectClip)
        paint_shadow(p, surface, tab)
        p.end()


def _origin(window: QWidget) -> QPoint:
    """Global top-left of a frameless top-level (the menu, the overlay) from its Qt geometry.

    Not ``mapToGlobal``: for a top-level it reads the native window position, which still holds the previous popup
    position while a menu is shown somewhere new (after the main window moved).  The overlay was then placed where
    the trigger used to be and the trigger's shadow appeared displaced or clipped on one side."""
    return window.geometry().topLeft()


def _native_gap(overlay: QWidget, menu: QWidget) -> int | None:
    """Device rows between the overlay window's bottom and the menu window's top (negative: overlap), from the
    windows' real native rectangles; None where they cannot be read (not Windows)."""
    import sys
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        a, b = wintypes.RECT(), wintypes.RECT()
        u = ctypes.windll.user32
        if not (u.GetWindowRect(wintypes.HWND(int(overlay.winId())), ctypes.byref(a)) and
                u.GetWindowRect(wintypes.HWND(int(menu.winId())), ctypes.byref(b))):
            return None
        return b.top - a.bottom
    except Exception:                             # noqa: BLE001 - cosmetic only
        return None


# ---------------------------------------------------------------------- other popups
def carbon_context_menu(widget) -> None:
    """Show a text widget's standard context menu (Undo / Cut / Copy / Paste / Select all) as a
    CarbonMenu: the actions are Qt's own (behaviour, enablement, shortcuts), only the popup is ours.

    A widget may add its own items after the standard ones: ``widget.context_extra`` is a callable returning
    ``(text, slot, danger)`` tuples (e.g. "Remove element" on a composition row).  Their slots run after the menu
    has closed, so a slot may delete the widget that owns the menu."""
    def show(pos):
        std = widget.createStandardContextMenu()
        menu = CarbonMenu(parent=widget)
        for act in std.actions():
            menu.addAction(act)
        extra = getattr(widget, "context_extra", None)
        items = extra() if callable(extra) else []
        if items:
            from PySide6.QtCore import QTimer
            menu.addSeparator()
            for text, slot, danger in items:
                menu.add_action(text, lambda s=slot: QTimer.singleShot(0, s), danger=danger)
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
