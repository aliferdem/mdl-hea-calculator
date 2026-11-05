"""Selected text uses the theme's text-selection pair (Carbon `highlight`) in every window, focused or not, and
follows theme switches - never the operating system's accent colour (2026-11-05)."""

import os

import pytest

import _ui_support as U
from _ui_support import close, pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402

WANT = {"light": ("#d0e2ff", "#121619"), "dark": ("#002d9c", "#f2f4f8")}


def _selection(widget):
    pal = widget.palette()
    out = set()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        out.add((pal.color(group, QPalette.ColorRole.Highlight).name(),
                 pal.color(group, QPalette.ColorRole.HighlightedText).name()))
    return out


def test_tokens_are_the_carbon_highlight_pair():
    from hea_calc.ui.theme import DARK, LIGHT
    for name, tokens in (("light", LIGHT), ("dark", DARK)):
        assert (tokens["text-selection"], tokens["text-selection-text"]) == WANT[name]
        assert tokens["text-selection"] == tokens["highlight"] and tokens["text-selection-text"] == tokens["text-primary"]


def test_documentation_about_and_fields_select_with_the_theme_colours(win, app):
    from PySide6.QtWidgets import QLabel, QLineEdit, QTextBrowser
    from hea_calc.ui.theme import THEME
    hw = win.show_help("home")
    win.show_about()
    about = win._about
    try:
        for theme in ("dark", "light", "dark"):
            THEME.set_theme(theme)
            pump(app, 20)
            browser = hw.findChildren(QTextBrowser)[0]
            selectable = [lb for lb in about.findChildren(QLabel) if lb.textInteractionFlags()]
            field = win.findChildren(QLineEdit)[0]
            assert selectable, "About has selectable text"
            for wd in (browser, selectable[0], field, hw.search):
                assert _selection(wd) == {WANT[theme]}, (theme, type(wd).__name__)
    finally:
        close(app, hw, about)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_selected_text_is_readable(theme):
    from PySide6.QtGui import QColor
    bg, fg = (QColor(c) for c in WANT[theme])

    def lum(c):
        ch = [v / 255 for v in (c.red(), c.green(), c.blue())]
        ch = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    hi, lo = sorted((lum(bg), lum(fg)), reverse=True)
    assert (hi + 0.05) / (lo + 0.05) >= 4.5, "WCAG AA for body text"
