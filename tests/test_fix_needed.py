"""Acceptance tests for the fix-needed pass (``design/implementation/FIX_NEEDED_AUDIT.md``).

Shared Carbon popups (long lists, text origin), scrollbar states, the notification anatomy, the header theme icon
and the Export MenuButton.  Offscreen; the references are ``design/fix needed/CORRECT_*.png``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QWheelEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from hea_calc.ui.theme import load_fonts
    load_fonts()
    return a


def pump(app, n: int = 4):
    for _ in range(n):
        app.processEvents()


@pytest.fixture()
def win(app):
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("light")
    st = QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings=st)
    w.resize(1920, 1000)
    w.show()
    pump(app)
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    pump(app)


def _host(app, child: QWidget, w: int = 300, h: int = 120) -> QWidget:
    host = QWidget()
    host.resize(w, h)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.addWidget(child)
    lay.addStretch(1)
    host.show()
    pump(app)
    return host


def _wheel(widget: QWidget, dy: int) -> None:
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    e = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, e)


# ====================================================================== shared list popup (brief §4-6, 3.png)
def test_long_dropdown_list_is_screen_clamped_and_scrolls_with_the_wheel(app):
    from hea_calc.ui.widgets.dropdown import Dropdown
    items = [(f"v{i}", f"Option {i}") for i in range(60)]
    d = Dropdown(items, "v0", accessible="Long list")
    d.setFixedWidth(220)
    host = _host(app, d)
    d.open_menu()
    pump(app)
    pop = d.popup
    screen = QApplication.primaryScreen().availableGeometry()
    assert pop is not None and pop.isVisible()
    assert pop.height() <= screen.height() and pop.height() <= 10 * 32 + 2 * 8, "at most ten rows, never the screen"
    assert pop.geometry().top() >= screen.top() and pop.geometry().bottom() <= screen.bottom() + 1
    assert pop.scroll_scrollable(), "the rest of a long list scrolls inside the popup"
    sb = pop.scroll.verticalScrollBar()
    before = sb.value()
    _wheel(pop.scroll.viewport(), -120)
    pump(app)
    assert sb.value() > before, "the wheel scrolls the open list"
    assert d.value == "v0", "scrolling the list never changes the value"
    pop.close()
    pump(app)
    assert d.popup is None
    host.close()


def test_closed_dropdown_ignores_the_wheel(app):
    from hea_calc.ui.widgets.dropdown import Dropdown
    d = Dropdown([("a", "A"), ("b", "B")], "a", accessible="Two")
    host = _host(app, d)
    _wheel(d, -120)
    pump(app)
    assert d.value == "a"
    host.close()


def _text_columns(img, bg: QColor) -> list[int]:
    cols = []
    for x in range(6, img.width() - 44):                 # skip the focus frame and the chevron
        for y in range(6, img.height() - 6):
            c = img.pixelColor(x, y)
            if abs(c.lightness() - bg.lightness()) > 60:
                cols.append(x)
                break
    return cols


def test_dropdown_text_keeps_its_origin_when_opened(app):
    """Brief §6: the value text never moves between the closed and the open state."""
    from hea_calc.ui.widgets.dropdown import Dropdown
    d = Dropdown([("ratio", "At. ratio"), ("at", "at.%")], "ratio", accessible="Basis")
    d.setFixedSize(200, 40)
    host = _host(app, d)
    closed = d.grab().toImage()
    bg = closed.pixelColor(8, 4)
    d.open_menu()
    pump(app)
    opened = d.grab().toImage()
    a, b = _text_columns(closed, bg), _text_columns(opened, bg)
    assert a and b and a[0] == b[0] and a[-1] == b[-1], (a[:3], b[:3])
    d.popup.close()
    pump(app)
    host.close()


def test_open_list_marks_the_selected_row_and_closes_on_choice(app):
    from hea_calc.ui.widgets.dropdown import Dropdown
    d = Dropdown([("ratio", "At. ratio"), ("at", "at.%"), ("wt", "wt.%")], "at", accessible="Basis")
    host = _host(app, d)
    d.open_menu()
    pump(app)
    pop = d.popup
    assert pop.active == 1 and pop.is_selected(1)
    pop.choose(2)
    pump(app)
    assert d.value == "wt" and d.popup is None
    host.close()


# ====================================================================== scrollbars (brief §22)
def test_scrollbar_thumb_changes_colour_not_geometry_on_hover_and_drag(app):
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.scroll import ThinScrollBar
    sb = ThinScrollBar(Qt.Orientation.Vertical)
    sb.setRange(0, 1000)
    sb.setPageStep(100)
    sb.resize(12, 300)
    sb.show()
    pump(app)
    rest_rect = sb.thumb_rect()
    sb._hover, sb._drag = False, None           # the offscreen pointer may start over the bar

    def thumb_colour():
        img = sb.grab().toImage()
        r = sb.thumb_rect()
        return img.pixelColor(int(r.center().x()), int(r.center().y())).name()
    rest = thumb_colour()
    sb._hover = True
    hover = thumb_colour()
    sb._drag = (0, 0)
    active = thumb_colour()
    assert {rest, hover, active} == {t("scrollbar-thumb").lower(), t("scrollbar-thumb-hover").lower(),
                                     t("scrollbar-thumb-active").lower()}
    assert len({rest, hover, active}) == 3, "rest, hover and active are distinguishable"
    assert sb.thumb_rect() == rest_rect, "only the colour changes"
    sb.close()


# ====================================================================== notification (CORRECT_NOTIFICATION)
@pytest.mark.parametrize("kind", ["info", "success", "warning", "error"])
def test_inline_notification_anatomy(app, kind):
    from hea_calc.ui.theme import t
    from hea_calc.ui.widgets.common import InlineNotification
    n = InlineNotification(closable=False)
    host = _host(app, n, 600, 140)
    n.show_message(kind, "Title", "Message")
    pump(app)
    assert n.height() >= 48
    img = n.grab().toImage()
    y = n.height() // 2
    accent = img.pixelColor(1, y).name()
    surface = img.pixelColor(n.width() // 2, y).name()
    assert accent == t(f"support-{kind}").lower(), "3 px status accent on the left edge"
    assert surface == t(f"notification-{kind}-bg").lower(), "tinted low-contrast surface"
    assert img.pixelColor(2, y).name() == accent and img.pixelColor(4, y).name() != accent, "accent is 3 px"
    assert n.title.text() == "Title" and n.body.text() == "Message"
    assert n.title.geometry().bottom() <= n.body.geometry().top(), "title above message"
    host.close()


# ====================================================================== header (CORRECT_THEME_BUTTON, §9)
@pytest.mark.parametrize("pref, icon", [("light", "brightness_contrast"), ("dark", "asleep"),
                                        ("system", "contrast")])
def test_theme_button_shows_the_selected_preference(win, app, pref, icon):
    win.prefs.set_theme(pref)
    win._sync_theme_actions()
    pump(app)
    assert win.header.theme_btn.icon_name == icon
    checked = [a.text() for a in win.theme_menu.actions() if a.isCheckable() and a.isChecked()]
    assert checked == [{"light": "Light", "dark": "Dark", "system": "System default"}[pref]]


# ====================================================================== Export MenuButton (§8, 11.png)
def test_export_menu_button_chevron_flips_and_filtered_items_follow_the_filter(win, app):
    b = win.table.export_btn
    m = b.menu()
    labels = [a.text() for a in m.actions() if a.isVisible() and not a.isSeparator()]
    assert labels[:2] == ["Excel workbook (.xlsx)", "CSV (.csv)"] and "Copy table to clipboard" in labels
    assert not any("filtered" in x.lower() for x in labels), "filtered variants only with an active filter"
    for name, comp in (("CoCrFeNi", {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}), ("CoFeNi", {"Co": 1, "Fe": 1, "Ni": 1})):
        win.calculate("single", [name], [comp], [{}])
        pump(app)
    win.table.model.wait()
    pump(app)
    win.show_in_table([r.id for r in win.table.model.page_rows()][:2])      # an explicit id filter
    win.table.model.wait()
    pump(app)
    m.aboutToShow.emit()
    labels = [a.text() for a in m.actions() if a.isVisible() and not a.isSeparator()]
    assert sum("filtered" in x.lower() for x in labels) == 2, labels
    closed = b.grab().toImage()
    b.open = True
    opened = b.grab().toImage()
    b.open = False
    x0 = b.width() - b.INDICATOR_PAD - b.CHEVRON
    region = [(x, y) for x in range(x0, x0 + b.CHEVRON) for y in range(b.height())]
    assert any(closed.pixelColor(x, y) != opened.pixelColor(x, y) for x, y in region), "chevron points up when open"
