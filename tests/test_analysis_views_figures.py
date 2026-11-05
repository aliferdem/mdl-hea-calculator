"""Analysis descriptor views, model figures (proportions, star, captions, M8 criterion) and UI text separators
(2026-11-04)."""

import math
import os
import sys

import pytest

import _ui_support as U
from _ui_support import ROOT, calc, close, make_window, pump

app, win = U.app, U.win                      # the shared fixtures (tests/_ui_support.py)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402



def _analysis_composition(win, app, tab):
    from hea_calc.core.analysis import state as S
    calc(win, app)
    c = win.analysis_ctl
    c.set_active(win.table.model.page_rows()[0].id, by="table")
    c.apply(S.switch_context, S.COMPOSITION)
    c.apply(S.set_tab, tab)
    pump(app, 30)


def test_key_descriptors_and_descriptors_show_no_hover_tooltips(win, app):
    from hea_calc.ui.analysis.composition_view import CompositionContent
    from hea_calc.ui.analysis.widgets import DataTable, KVRows
    _analysis_composition(win, app, "overview")
    content = win.analysis.findChildren(CompositionContent)[0]
    rows = content.key_descriptor_rows(content.row.result.descriptors)
    assert all(len(r) < 6 or not r[5] for r in rows), "no value Tooltip in Key descriptors"
    from PySide6.QtWidgets import QLabel
    kv = [r for r in win.analysis.findChildren(KVRows) if r.isVisible()]
    assert kv and not [lab.text() for k in kv for lab in k.findChildren(QLabel) if lab.toolTip()],         "no label / value Tooltips in Overview"
    from hea_calc.core.analysis import state as S
    win.analysis_ctl.apply(S.set_tab, "descriptors")
    pump(app, 30)
    tables = [t_ for t_ in win.analysis.findChildren(DataTable) if t_.isVisible()]
    for tb in tables:
        for r in tb.rows:
            for cell in r:
                assert not getattr(cell, "tip", ""), "no value Tooltip in Descriptors"


def test_unavailable_value_is_explained_in_the_info_toggletip(app):
    from hea_calc.core.engine import Engine
    from hea_calc.ui.analysis.composition_view import descriptor_tip
    d = Engine().calculate({"Fe": 1, "Ni": 1, "Sb": 1}).descriptors
    tip = descriptor_tip("dchi", d)
    assert "Not available" in tip and "Sb" in tip and "Definition" in tip
    ok = Engine().calculate({"Fe": 1, "Ni": 1}).descriptors
    assert "Not available" not in descriptor_tip("dchi", ok)


def _figure(k, current=None):
    from hea_calc.core.analysis.model_figures import figure
    from hea_calc.ui.analysis.model_figure import ModelFigureWidget
    return ModelFigureWidget(figure(k), current or {"x": 2.2, "y": 1.6})


def test_figures_keep_bounded_proportions_and_are_centred(app):
    from hea_calc.ui.analysis import model_figure as MF
    for k in ("M1", "M2", "M4", "M6", "M7"):
        w = _figure(k)
        sizes = [w.figure_size(width) for width in (600, 1500, 2600)]
        assert sizes[1] == sizes[2], (k, "a wider window does not stretch the figure")
        assert sizes[2][0] <= w.max_width()
        w.resize(2000, w.heightForWidth(2000))
        r = w.drawing_rect()
        assert abs(r.left() - (2000 - r.width()) / 2) < 1, "centred"
        if k != "M7":
            plot_w = sizes[2][0] - MF.PAD_L - MF.PAD_R
            plot_h = sizes[2][1] - MF.PAD_T - MF.PAD_B - MF.LEGEND_H
            assert abs(plot_h - min(MF.PLOT_H_MAX, plot_w / MF.SCATTER_ASPECT)) < 0.01, k     # 3:2, height-capped
            assert plot_w / plot_h <= 2.0, (k, "never a wide, flat strip")
        small = w.figure_size(320)
        assert small[0] <= 320 and small[1] > 0, "shrinks without clipping"


def test_m7_uses_equal_data_unit_scaling(app):
    from hea_calc.ui.analysis import model_figure as MF
    w = _figure("M7")
    assert w.equal_scale()
    (x0, x1), (y0, y1) = w.ranges()
    for width in (500, 900, 1800):
        fw, fh = w.figure_size(width)
        plot_w = fw - MF.PAD_L - MF.PAD_R
        plot_h = fh - MF.PAD_T - MF.PAD_B - MF.LEGEND_H
        assert abs(plot_w / (x1 - x0) - plot_h / (y1 - y0)) < 1e-6, "one data unit, one length"
    assert not _figure("M2").equal_scale(), "unrelated quantities are not forced to equal scaling"


def test_one_dimensional_criteria_are_compact_strips(app):
    from hea_calc.ui.analysis import model_figure as MF
    for k in ("M3", "M5", "M8"):
        w = _figure(k, {"x": 1.1})
        assert w.plot_aspect() is None
        assert w.heightForWidth(1500) == MF.STRIP_PLOT_H + MF.PAD_T + MF.PAD_B + MF.LEGEND_H


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_this_composition_is_a_star_in_plot_legend_and_export(app, tmp_path, monkeypatch, theme):
    from PySide6.QtGui import QImage, QPainter
    from hea_calc.ui.analysis import model_figure as MF
    from hea_calc.ui.theme import THEME, t
    THEME.set_theme(theme)
    try:
        calls = []
        real = MF.paint_star
        monkeypatch.setattr(MF, "paint_star", lambda p, x, y, r: (calls.append(r), real(p, x, y, r)))
        w = _figure("M7")
        img = QImage(900, 600, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        w.render_to(p, *w.figure_size(900))
        p.end()
        assert calls == [MF.STAR_R, MF.STAR_LEGEND_R], "the plot marker and the legend symbol are both stars"
        assert MF.STAR_R >= 10
        poly = MF.star_polygon(0, 0, 10)
        assert poly.size() == 10, "a five-pointed star"
        # the star is opaque text-primary with a halo in the surface colour (contrast in both themes)
        w.resize(900, w.heightForWidth(900))
        shot = w.grab().toImage()
        assert any(shot.pixelColor(x, y).name() == t("text-primary")
                   for x in range(0, shot.width(), 2) for y in range(0, shot.height(), 2))
        calls.clear()
        out = tmp_path / "m7.png"
        w.export(str(out))
        assert out.stat().st_size > 2000 and calls == [MF.STAR_R, MF.STAR_LEGEND_R], "exports keep the star"
    finally:
        THEME.set_theme("dark")


def test_model_details_figure_has_a_caption_and_no_repeated_reference(win, app):
    from hea_calc.core.analysis import state as S
    from hea_calc.core.analysis.model_figures import figure
    _analysis_composition(win, app, "model_details")
    for k in ("M7", "M8"):
        win.analysis_ctl.apply(S.select_model, k)
        pump(app, 30)
        from PySide6.QtWidgets import QLabel
        labels = [lb for lb in win.analysis.findChildren(QLabel) if lb.isVisible()]
        assert not any(lb.objectName() == "ModelFigureSource" for lb in labels)
        assert not any(lb.text().startswith("Source:") for lb in labels), "no citation under the figure"
        caps = [lb for lb in labels if lb.objectName() == "ModelFigureCaption"]
        assert caps and caps[0].text().startswith(figure(k).caption[:30]), "the caption stays"


def test_m8_criterion_equation_is_phi_alone():
    """King §3.1: the criterion is Φ ≥ 1; the δ ≤ 6.6 % screen (§3.4) is not part of it - not even in the equation."""
    sys.path.insert(0, str(ROOT / "tools"))
    import re
    src = (ROOT / "tools" / "render_equations.py").read_text(encoding="utf-8")
    m8 = src[src.index('"M8": ['):]
    tex = re.findall(r'r"(\$[^"]*\$)"', m8[:m8.index("],") + 2])          # the TeX statements, not the comments
    assert len(tex) == 2 and tex[1] == r"$\mathrm{SS:}\ \Phi\geq 1$"
    assert not any("6.6" in x or "CN12" in x for x in tex)
    svg = (ROOT / "hea_calc" / "ui" / "equations" / "M8_2.svg").read_text(encoding="utf-8")
    assert svg.count("<use") < 12, "the SS line holds 'SS: Φ ≥ 1' only (a few glyphs)"


def test_identity_line_uses_the_ui_separator(win, app):
    from hea_calc.ui.analysis.composition_view import identity_line
    from hea_calc.ui.theme import UI_SEPARATOR
    calc(win, app)
    rid = win.table.model.page_rows()[0].id
    info = win.analysis_ctl.run_info(win.repo.get_result(rid).run_id) if hasattr(win.analysis_ctl, "run_info") else None
    if info is not None:
        line = identity_line(info)
        assert UI_SEPARATOR in line and "·" not in line and "⋅" not in line
    assert UI_SEPARATOR == " | "


def test_math_middle_dots_are_kept():
    from hea_calc.core.engine import MODELS
    assert "−T·ΔSmix" in MODELS["M6"].criterion, "a product in a formula keeps its middle dot"
    assert math.isfinite(1.0)


def test_expanded_window_rule():
    from hea_calc.ui.surface import expanded_window
    assert not expanded_window(False, False), "restored (compact or wide layout): the window surface"
    assert expanded_window(True, False) and expanded_window(False, True), "maximised / full screen"


def _surfaces(app, root, c, tab):
    """(outer surface, first visible region, Find a descriptor field) colours of ``root`` on ``tab``."""
    from PySide6.QtWidgets import QLineEdit, QWidget
    from hea_calc.core.analysis import state as S
    c.apply(S.set_tab, tab)
    pump(app, 20)
    img = root.grab().toImage()
    at = lambda w, dx, dy: img.pixelColor(w.mapTo(root, QPoint(dx, dy)))       # noqa: E731
    if tab == "descriptors":
        f = next(f for f in root.findChildren(QLineEdit) if f.placeholderText() == "Find a descriptor" and f.isVisible())
        return at(f, -8, 6).name(), None, at(f, f.width() - 12, 6).name()
    regs = [r for r in root.findChildren(QWidget) if r.objectName() in ("AnaRegion", "AnaRail") and r.isVisible()]
    if not regs:
        return None, None, None
    reg = regs[0]
    return at(reg, -4, 4).name() if reg.mapTo(root, QPoint(0, 0)).x() >= 4 else None, at(reg, 3, 3).name(), None


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_analysis_surface_hierarchy_follows_the_presentation_state(app, theme):
    """Light: restored Analysis is a white surface with Cool Gray regions and a Cool Gray search field; expanded
    Analysis (Expand analysis in the main window, or the separate window maximised or full screen) is Cool Gray
    outside with white regions and a white search field - distinguishable from the surface.  Dark is unchanged."""
    from hea_calc.ui.theme import THEME
    w = make_window(app, theme)
    try:
        calc(w, app)
        c = w.analysis.c
        want = {"light": {"compact": ("#ffffff", "#f2f4f8", "#f2f4f8"), "expanded": ("#f2f4f8", "#ffffff", "#ffffff")},
                "dark": {"compact": ("#121619", "#21272a", "#343a3f"), "expanded": ("#121619", "#21272a", "#343a3f")}}
        want = want[theme]
        # the in-window expanded workspace
        w.set_expanded(True)
        pump(app, 20)
        for tab in ("overview", "descriptors"):
            outer, region, field = _surfaces(app, w, c, tab)
            exp = want["expanded"]
            assert (outer, region or exp[1], field or exp[2]) == exp, ("in-window", tab, outer, region, field)
        w.set_expanded(False)
        pump(app)
        aw = w.open_analysis_window()
        seen = set()
        try:
            for state in ("compact", "maximized", "compact-again", "fullscreen", "restored-wide"):
                aw.showNormal()
                if state == "maximized":
                    aw.showMaximized()
                elif state == "fullscreen":
                    aw.showFullScreen()
                aw.resize(*((1920, 1040) if state == "restored-wide" else (900, 700) if "compact" in state else (aw.width(),
                                                                                                         aw.height())))
                pump(app, 20)
                kind = "expanded" if state in ("maximized", "fullscreen") else "compact"
                assert (aw.property("carbon_layer") == 0) == (kind == "expanded"), state
                for tab in ("overview", "descriptors"):
                    outer, region, field = _surfaces(app, aw, c, tab)
                    seen.add((kind, tab, region is not None))
                    exp = want[kind]
                    got = (outer or exp[0], region or exp[1], field or exp[2])
                    assert got == exp, (theme, state, tab, outer, region, field)
        finally:
            close(app, aw)
        assert ("compact", "overview", True) in seen, "a restored wide window's regions were measured"
        assert THEME.name == theme
    finally:
        close(app, w)
