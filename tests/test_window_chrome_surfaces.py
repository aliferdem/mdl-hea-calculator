"""Window frame treatment by state, outer window surfaces and native caption colours (2026-11-04).

Native maximise / restore / full-screen behaviour runs on a Windows desktop with HEA_NATIVE_TESTS=1
(``tests/_native_window_frame_check.py``)."""

import os
import sys

import pytest

import _ui_support as U
from _ui_support import ROOT, calc, close, make_window, pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")



def test_frame_treatment_is_square_and_borderless_when_maximised_or_full_screen():
    from hea_calc.ui import win_chrome as C
    assert C.frame_treatment(False, False) == (C.DWMWCP_ROUND, C.DWMWA_COLOR_DEFAULT)
    for maximized, fullscreen in ((True, False), (False, True), (True, True)):
        assert C.frame_treatment(maximized, fullscreen) == (C.DWMWCP_DONOTROUND, C.DWMWA_COLOR_NONE)


@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("HEA_NATIVE_TESTS") != "1",
                    reason="opens real windows; set HEA_NATIVE_TESTS=1 on a Windows desktop")
def test_native_window_frame(tmp_path):
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "_native_window_frame_check.py"), str(tmp_path / "s.ini")],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr


def _corner(widget) -> str:
    img = widget.grab().toImage()
    return img.pixelColor(2, img.height() - 3).name()


@pytest.mark.parametrize("theme,outer", [("dark", "#121619"), ("light", "#ffffff")])
def test_independent_windows_use_the_outer_window_background(app, theme, outer):
    from hea_calc.ui.theme import THEME, t
    from hea_calc.ui.widgets.dialogs import FilterDialog
    w = make_window(app, theme)
    try:
        assert t("window-background") == outer
        assert t("shell") == ("#21272a" if theme == "dark" else "#ffffff"), "the title bars keep `shell`"
        calc(w, app)
        help_w = w.show_help("home")
        w.show_about()
        dlg = FilterDialog([], w)
        dlg.show()
        aw = w.open_analysis_window()
        pump(app, 20)
        for name, widget in (("help", help_w), ("about", w._about), ("filter", dlg), ("analysis", aw)):
            assert _corner(widget) == outer, (theme, name)
        # inner panels keep their own layer (the analysis regions are not the outer colour)
        assert THEME.tokens["layer-01"] != outer or theme == "light"
        dlg.close()
        close(app, help_w, w._about, aw)
    finally:
        close(app, w)
        THEME.set_theme("dark")


def test_native_captions_of_independent_windows_are_the_window_surface():
    from hea_calc.ui import win_titlebar as W
    from hea_calc.ui.theme import DARK, LIGHT
    for theme, tokens, want in (("dark", DARK, "#121619"), ("light", LIGHT, "#ffffff")):
        attrs = dict(W.caption_attributes(theme, tokens, 22631))
        assert attrs[W.DWMWA_CAPTION_COLOR] == attrs[W.DWMWA_BORDER_COLOR] == W.colorref(want), theme
    assert DARK["shell"] == "#21272a", "the main window's own title bar keeps its colour"
