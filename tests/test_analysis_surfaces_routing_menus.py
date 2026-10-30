"""2026-10-27: Analysis surfaces, Results double-click routing, header-menu trigger shadow.

1. Surfaces: docked Analysis is ``layer-01`` (light #ffffff, dark #262626); the separate Analysis window is the shell
   (light #ffffff, dark #161616) - the light theme's ``background`` token (#f4f4f4) had made it grey.
2. Routing: a Results activation goes to the docked panel only while this window shows Analysis (top panels visible
   and Analysis not collapsed, or the expanded workspace); otherwise to the separate window, reused.
3. Menu shadow: a merged header menu (File / Edit / View / Help) paints the trigger's share of its elevation in a
   separate overlay window.  It was placed with ``menu.mapToGlobal``, which for a top-level popup reads the native
   window position - still the previous popup position when the menu re-opens somewhere new (after the main window
   moved), so the trigger's shadow appeared displaced / clipped on one side.  It now follows the menu's Qt geometry.
"""

import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SPEC = {("light", "docked"): "#ffffff", ("light", "floating"): "#ffffff",
        ("dark", "docked"): "#262626", ("dark", "floating"): "#161616"}


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    a = QApplication.instance() or QApplication([])
    load_fonts()
    return a


def make_window(app, theme="dark"):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme(theme)
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1728, 1000)
    w.show()
    pump(app)
    return w


@pytest.fixture()
def win(app):
    from PySide6.QtCore import QEvent
    from hea_calc.ui.theme import THEME
    w = make_window(app)
    yield w
    aw = w.analysis_window(create=False)
    if aw is not None:
        aw.close()
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    THEME.set_theme("dark")
    pump(app)


def pump(app, n=8):
    for _ in range(n):
        app.processEvents()


def calc(win, app, name, comp):
    win.calculate("single", [name], [comp], [{}])
    pump(app)


def surface(widget) -> str:
    """The rendered surface colour: the bare top-left 8 x 8 px (outside every region, card and control in both
    the compact panel and the wide workspace layout); one colour, or the set found."""
    img = widget.grab().toImage()
    k = img.width() / widget.width()
    found = Counter(img.pixelColor(int(x * k), int(y * k)).name() for x in range(1, 9) for y in range(1, 9))
    return found.most_common(1)[0][0] if len(found) == 1 else "/".join(sorted(found))


# ============================================================================================ 1. surfaces
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_docked_and_floating_analysis_surfaces(app, theme):
    from PySide6.QtCore import QEvent
    w = make_window(app, theme)
    try:
        calc(w, app, "CoCrFeNi", {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1})
        aw = w.open_analysis_window()
        pump(app, 15)
        assert surface(w.analysis) == SPEC[(theme, "docked")]
        for width, wide in ((900, False), (1600, True)):          # compact panel and wide workspace layout
            aw.resize(width, 760)
            pump(app, 15)
            assert aw.wide is wide
            assert surface(aw) == SPEC[(theme, "floating")], width
        aw.close()
    finally:
        w.close()
        w.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_floating_surface_follows_runtime_theme_switch_and_reopen(app):
    from PySide6.QtCore import QEvent
    from hea_calc.ui.theme import THEME
    w = make_window(app, "light")
    try:
        calc(w, app, "CoCrFeNi", {"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1})
        aw = w.open_analysis_window()
        pump(app, 15)
        assert surface(aw) == "#ffffff"
        THEME.set_theme("dark")                                      # switched while the window is open
        pump(app, 15)
        assert surface(aw) == "#161616" and surface(w.analysis) == "#262626"
        aw.close()                                                   # closed (hidden) ...
        THEME.set_theme("light")                                     # ... theme changed meanwhile ...
        pump(app)
        again = w.open_analysis_window()                             # ... reopened: same window, current theme
        pump(app, 15)
        assert again is aw
        assert surface(again) == "#ffffff" and surface(w.analysis) == "#ffffff"
        again.close()
    finally:
        THEME.set_theme("dark")
        w.close()
        w.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# ============================================================================================ 2. routing
def route_spy(win, monkeypatch):
    calls = []
    orig_open, orig_show = win.open_analysis_window, win.show_details

    def opened(row=None):
        calls.append(("floating", getattr(row, "id", None)))
        return orig_open(row)

    def shown(row):
        calls.append(("docked", getattr(row, "id", None)))
        return orig_show(row)

    monkeypatch.setattr(win, "open_analysis_window", opened)
    monkeypatch.setattr(win, "show_details", shown)
    return calls


def double_click(win, app, r):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    m, view = win.table.model, win.table.view
    rect = view.visualRect(m.index(r, m.keys.index("name")))
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
    pump(app, 3)
    return m.id_at(r)


def three_results(win, app):
    for name, comp in (("Mo0.3CoCrFeNi", {"Mo": 0.3, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}),
                       ("AlCoCrFeNi", {"Al": 1, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}),
                       ("HfNbTaTiZr", {"Hf": 1, "Nb": 1, "Ta": 1, "Ti": 1, "Zr": 1})):
        calc(win, app, name, comp)


def test_double_click_routes_to_docked_analysis_while_it_is_expanded(win, app, monkeypatch):
    three_results(win, app)
    calls = route_spy(win, monkeypatch)
    for r in range(3):
        rid = double_click(win, app, r)
        assert calls[-1] == ("docked", rid)
        assert win.analysis_ctl.state.active == rid
    assert all(kind == "docked" for kind, _ in calls)
    aw = win.analysis_window(create=False)
    assert aw is None or not aw.isVisible()


def test_double_click_routes_to_floating_analysis_when_docked_analysis_is_collapsed(win, app, monkeypatch):
    three_results(win, app)
    win.top_row.set_collapsed(win.ANALYSIS_PANEL, True)
    pump(app)
    before = set(win.top_row.collapsed)
    calls = route_spy(win, monkeypatch)
    rid0 = double_click(win, app, 0)
    assert calls[-1] == ("floating", rid0)
    aw = win.analysis_window(create=False)
    assert aw is not None and aw.isVisible()
    assert win.analysis_ctl.state.active == rid0
    rid2 = double_click(win, app, 2)                                 # another row: the same window, updated
    assert calls[-1] == ("floating", rid2)
    assert win.analysis_window(create=False) is aw
    assert win.analysis_ctl.state.active == rid2 != rid0
    assert set(win.top_row.collapsed) == before                     # Analysis stays collapsed, others untouched
    assert win.top_row.is_collapsed(win.ANALYSIS_PANEL)
    # re-expanded: docked again, even though the separate window still exists and is open
    win.top_row.set_collapsed(win.ANALYSIS_PANEL, False)
    pump(app)
    rid1 = double_click(win, app, 1)
    assert calls[-1] == ("docked", rid1)
    assert win.analysis_ctl.state.active == rid1


def test_other_collapsed_panels_do_not_reroute(win, app, monkeypatch):
    three_results(win, app)
    win.top_row.set_collapsed(0, True)                               # Elements collapsed only
    pump(app)
    calls = route_spy(win, monkeypatch)
    rid = double_click(win, app, 0)
    assert calls[-1] == ("docked", rid)
    assert win.top_row.collapsed == {0}


def test_double_click_routes_to_floating_analysis_with_top_panels_hidden(win, app, monkeypatch):
    three_results(win, app)
    win.set_top_panels_visible(False)
    pump(app)
    calls = route_spy(win, monkeypatch)
    rid = double_click(win, app, 1)
    assert calls[-1] == ("floating", rid)
    assert win.analysis_ctl.state.active == rid
    win.set_top_panels_visible(True)
    pump(app)
    rid = double_click(win, app, 2)
    assert calls[-1] == ("docked", rid)


def test_expanded_workspace_counts_as_docked_analysis(win, app, monkeypatch):
    three_results(win, app)
    win.set_expanded(True)
    pump(app)
    assert win.docked_analysis_shown()
    win.set_expanded(False)
    pump(app)
    win.top_row.set_collapsed(win.ANALYSIS_PANEL, True)
    assert not win.docked_analysis_shown()


# ============================================================================================ 3. menu shadow
def header_items(win):
    from hea_calc.ui.widgets.header import HeaderMenuItem, TitleBar
    tb = win.findChild(TitleBar)
    return {it.text(): it for it in tb.menu_items if isinstance(it, HeaderMenuItem) and it.menu_ is not None}


def expected_overlay(item, menu):
    from PySide6.QtCore import QPoint, QRect
    from hea_calc.ui.widgets.menu import SHADOW
    trig = QRect(item.mapToGlobal(QPoint(0, 0)), item.size())
    top = trig.top() - SHADOW
    return QRect(trig.left() - SHADOW, top, trig.width() + 2 * SHADOW, menu.geometry().top() - top), trig


def side_shadows(overlay, trig_width):
    """Alpha just outside the tab's left and right edges, mid-height, in the overlay's own rendering."""
    from hea_calc.ui.widgets.menu import SHADOW
    img = overlay.grab().toImage()
    k = img.width() / overlay.width()
    y = img.height() // 2
    left = img.pixelColor(int((SHADOW - 2) * k), y).alpha()
    right = img.pixelColor(int((SHADOW + trig_width + 1) * k), y).alpha()
    inside = img.pixelColor(int((SHADOW + trig_width / 2) * k), y).alpha()
    return left, right, inside


@pytest.mark.parametrize("name", ["File", "Edit", "View", "Help"])
def test_trigger_shadow_follows_menu_geometry_not_a_stale_native_position(win, app, monkeypatch, name):
    """Regression for the displaced trigger shadow: simulate Windows' lagging native popup position (the menu's
    mapToGlobal still reports where the popup was last shown) and require the overlay around the trigger anyway."""
    from PySide6.QtCore import QPoint
    from hea_calc.ui.widgets.menu import CarbonMenu
    item = header_items(win)[name]
    m = item.menu_
    m.trigger_width = 0
    m.open_below(item, exec_=False, merge=True)
    pump(app)
    try:
        assert m.isVisible() and m.tab is not None and m._overlay is not None
        stale = QPoint(-180, -80)                                   # where the popup was before the window moved
        monkeypatch.setattr(CarbonMenu, "mapToGlobal", lambda self, p: p + self.geometry().topLeft() + stale)
        m._overlay.place()
        pump(app)
        want, trig = expected_overlay(item, m)
        got = m._overlay.geometry()
        assert (got.left(), got.top(), got.width()) == (want.left(), want.top(), want.width())
        assert got.height() in (want.height(), want.height() + 1)  # +1: the native seam seal (Windows only)
        left, right, inside = side_shadows(m._overlay, trig.width())
        assert left > 0 and right > 0, (left, right)               # both sides of the trigger are shadowed
        assert abs(left - right) <= 2
        assert inside == 0                                          # nothing painted over the trigger itself
    finally:
        m.close()
        pump(app)


def test_trigger_shadow_after_window_move_and_menu_switching(win, app):
    """Behavioural check: move the window, open every header menu (as hover / Left-Right switching would), and the
    overlay surrounds the current trigger each time; it hides with its menu."""
    items = header_items(win)
    for pos in ((40, 30), (260, 140), (120, 80)):
        win.move(*pos)
        pump(app)
        for name, item in items.items():
            m = item.menu_
            m.trigger_width = 0
            m.open_below(item, exec_=False, merge=True)
            pump(app)
            want, trig = expected_overlay(item, m)
            got = m._overlay.geometry()
            assert (got.left(), got.top(), got.width()) == (want.left(), want.top(), want.width()), (pos, name)
            m.close()
            pump(app)
            assert not m._overlay.isVisible()
            assert item.property("open") is False


NATIVE = sys.platform == "win32" and os.environ.get("HEA_NATIVE_TESTS") == "1"


@pytest.mark.skipif(not NATIVE, reason="opens a real Windows window (HEA_NATIVE_TESTS=1)")
def test_native_trigger_shadow_is_aligned_after_the_window_moves():
    """Real Windows platform: the first opening of each header menu after a window move (the reproduced failure:
    the overlay stayed at the previous trigger position) - Qt and native rectangles, and the composed screen."""
    import subprocess
    script = Path(__file__).with_name("_native_menu_shadow_check.py")
    env = dict(os.environ, QT_QPA_PLATFORM="windows")
    res = subprocess.run([sys.executable, str(script)], cwd=Path(__file__).resolve().parents[1], env=env,
                         capture_output=True, text=True, timeout=240)
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-3000:]
    assert "ALL ALIGNED" in res.stdout, res.stdout[-3000:]
