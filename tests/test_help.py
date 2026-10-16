"""Help documentation: structure (release brief section 46), routing, search, links, images, content verified
against the current engine, and the Help window itself (offscreen)."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pytest

from hea_calc.core import docs

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TREE = [
    ("Welcome to HEA Calculator", ["Navigating the Documentation", "Your First Calculation"]),
    ("1. Introduction", ["About HEA Calculator", "Scope and Scientific Limitations"]),
    ("2. Key Concepts and Features", ["Desktop Layout", "Composition Representations",
                                      "System Size and Element Constraints", "Model Support and Availability"]),
    ("3. Defining Alloy Compositions", ["Single Composition", "Composition Space", "Composition Expressions",
                                        "Importing Compositions"]),
    ("4. Performing Calculations", ["Calculation Workflow", "Composition Enumeration", "Workload Estimation",
                                    "Calculation Settings"]),
    ("5. Results and Visualizations", ["Results Table", "Individual Composition Analysis", "Collection Analysis",
                                       "Plots and Statistical Analysis", "Exporting Results"]),
    ("6. Software Examples", ["Equiatomic CoCrFeMnNi", "Composition Space: Al–Co–Cr–Fe–Ni",
                              "Parametric Expression: AlxCoCrFeNi"]),
    ("7. Data and Prediction Models", ["Elemental Property Data", "Binary Interaction Data",
                                       "Prediction Model Coverage", "Phase-Formation Models M1–M8",
                                       "Scientific References"]),
    ("8. General Reference", ["Symbols, Parameters and Units", "Prediction Result Labels",
                              "Expression Syntax Reference", "Keyboard Shortcuts", "Frequently Asked Questions"]),
]


# ====================================================================== structure
def test_tree_matches_the_documentation_hierarchy():
    assert docs.TREE.title == "Documentation Home"
    got = [(n.title, [c.title for c in n.children]) for n in docs.TREE.children]
    assert got == EXPECTED_TREE


def test_every_page_has_its_own_content_file_with_matching_h1():
    for page in docs.ORDER:
        path = docs.PAGES_DIR / f"{page}.md"
        assert path.exists(), page
        first = path.read_text(encoding="utf-8").lstrip().splitlines()[0]
        assert first == f"# {docs.NODES[page].title}", page


def test_navigation_breadcrumb_and_neighbours():
    assert docs.breadcrumb("model-coverage") == [("home", "Documentation Home"),
                                                 ("data-models", "7. Data and Prediction Models"),
                                                 ("model-coverage", "Prediction Model Coverage")]
    assert docs.neighbours("home") == (None, "welcome")
    assert docs.neighbours("faq")[1] is None
    prev, nxt = docs.neighbours("first-calculation")
    assert (prev, nxt) == ("navigating", "introduction")
    for page in docs.ORDER:
        for r in docs.related(page):
            assert r in docs.NODES and r != page


def test_routing_accepts_urls_aliases_and_rejects_unknown_pages():
    assert docs.resolve("help://models") == docs.Route("model-coverage")
    assert docs.resolve("help://models#model-requirements") == docs.Route("model-coverage", "model-requirements")
    assert docs.resolve("collections").page == "collection-analysis"
    assert docs.resolve("workload").page == "workload"
    assert docs.resolve("help://") == docs.Route("home")
    assert docs.resolve("") == docs.Route("home")
    assert docs.resolve("help://no-such-page") is None


# ====================================================================== links, anchors, images
LINK = re.compile(r"\]\((help://[^)\s]+)\)")


def _anchors(page: str) -> set[str]:
    return {a for _l, _t, a in docs.headings(page)} | {"related-topics", "in-this-section"}


def test_every_help_link_in_the_documentation_resolves_to_a_page_and_anchor():
    for page in docs.ORDER:
        for href in LINK.findall(docs.source(page)):
            route = docs.resolve(href)
            assert route is not None, (page, href)
            if route.anchor:
                assert route.anchor in _anchors(route.page), (page, href)


def test_every_in_app_help_link_resolves():
    """Toggletips, footer messages and menus link into the documentation with help:// URLs."""
    hrefs = set()
    for path in (ROOT / "hea_calc").rglob("*.py"):
        # links are quoted (href='help://…', "help://…"); docstrings show the scheme in ``…``
        hrefs |= set(re.findall(r"(?<=['\"])help://[A-Za-z0-9_#-]+", path.read_text(encoding="utf-8")))
    assert hrefs, "the application links into Help"
    for href in hrefs:
        if href.endswith("://"):
            continue
        route = docs.resolve(href)
        assert route is not None, href
        if route.anchor:
            assert route.anchor in _anchors(route.page), href


def test_analysis_menu_help_ids_resolve():
    src = (ROOT / "hea_calc" / "ui" / "analysis" / "panel.py").read_text(encoding="utf-8")
    for page in re.findall(r'help_requested\.emit\("([^"]+)"\)', src):
        assert docs.resolve(page) is not None, page


def test_images_exist_are_real_captures_and_are_referenced():
    referenced = set()
    for page in docs.ORDER:
        for src in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", docs.source(page)):
            referenced.add(src)
            size = docs.png_size(docs.DOCS_DIR / src)
            assert size and size[0] >= 400 and size[1] >= 300, src
    on_disk = {f"images/{p.name}" for p in docs.IMAGES_DIR.glob("*.png")}
    assert referenced <= on_disk
    assert len(referenced) >= 7


def test_rendered_articles_have_breadcrumb_heading_lead_and_prev_next():
    html = docs.article_html("composition-space", 600)
    assert "breadcrumb" in html and 'href="help://defining"' in html
    assert '<h1><a name="composition-space"></a>Composition Space</h1>' in html
    assert 'class="lead"' in html
    assert ">Previous<" in html and ">Next<" in html and "Related topics" in html
    assert docs.article_html("home").count("breadcrumb") == 0       # Home has no breadcrumb
    overview = docs.article_html("results")
    for child in docs.NODES["results"].children:
        assert f'href="help://{child.id}"' in overview


def test_markdown_subset_rendering():
    out = docs.to_html("# T\n\nLead.\n\n| a | b \\| c |\n|---|---|\n| 1 | x<sub>i</sub> |\n\n> **Note.** n\n\n"
                       "* one\n  continued\n* two\n\n1. first\n2. second\n\nkJ mol⁻¹ <script>bad</script>")
    assert '<p class="lead">Lead.</p>' in out
    assert "<th align=\"left\">b | c</th>" in out and "x<sub>i</sub>" in out
    assert 'class="callout"' in out and "<b>Note.</b>" in out
    assert "<li>one continued</li>" in out and "<ol>" in out
    assert "mol<sup>−1</sup>" in out and "<script>" not in out and "&lt;script&gt;" in out


# ====================================================================== search
def _pages(query: str) -> list[str]:
    return [h.page for h in docs.index().search(query)]


@pytest.mark.parametrize("query, page", [
    ("delta", "symbols"),
    ("δ", "symbols"),
    ("delta CN12", "symbols"),
    ("mixing enthalpy", "symbols"),
    ("ΔHmix", "symbols"),
    ("atomic percent", "representations"),
    ("at.%", "representations"),
    ("weight percent", "representations"),
    ("range basis", "composition-space"),
    ("total mass", "representations"),
    ("workload", "workload"),
    ("troparevsky", "binary-data"),
    ("expression syntax", "expression-syntax"),
    ("keyboard", "shortcuts"),
])
def test_search_finds_topics_through_aliases(query, page):
    assert page in _pages(query), (query, _pages(query)[:8])


def test_search_aliases_are_symmetric_and_ranked():
    assert set(_pages("delta")) & set(_pages("δ"))
    assert set(_pages("mixing enthalpy")) & set(_pages("ΔHmix"))
    assert set(_pages("atomic percent")) & set(_pages("at.%"))
    assert set(_pages("delta cn12")) & set(_pages("δCN12"))
    hits = docs.index().search("workload estimation")
    assert hits[0].page == "workload"                         # title matches rank first
    assert docs.index().search("") == [] and docs.index().search("zzqqxx") == []
    assert all(h.excerpt for h in docs.index().search("Normalize"))


def test_search_index_is_built_once():
    assert docs.index() is docs.index()
    assert len(docs.index().entries) > 200


# ====================================================================== content verified against the engine
def test_documented_values_match_the_current_engine():
    from hea_calc.core import composition as C
    from hea_calc.core.engine import default_engine
    from hea_calc.core.expression import VariableRange, count_blocks, parse_blocks
    from hea_calc.core.generation import SweepSpec, count_space, summarize_space

    e = default_engine()
    text = "\n".join(docs.source(p) for p in docs.ORDER)
    cantor = e.calculate({"Co": 1, "Cr": 1, "Fe": 1, "Mn": 1, "Ni": 1})
    d = cantor.descriptors
    for value, fmt in ((d["density"], "{:.2f}"), (d["tm"], "{:.2f}"), (d["dsmix"], "{:.2f}"), (d["delta"], "{:.2f}"),
                       (d["delta_cn12"], "{:.2f}"), (d["vec"], "{:.2f}"), (d["omega"], "{:.2f}")):
        assert fmt.format(value) in text, value
    assert f"−{abs(d['dhmix']):.2f}" in text
    assert all(o.label == "SS" for o in cantor.models.values())
    assert f"{round(cantor.temperature)} K" in text
    mass = C.from_fractions(C.fractions({e_: 1 for e_ in ("Co", "Cr", "Fe", "Mn", "Ni")}), "mass", total_mass=2.0)
    for v in mass.values():
        assert f"{v:.5f}" in docs.source("first-calculation")
    al = e.calculate({"Al": 1, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1})
    labels = [al.models[f"M{i}"].label for i in range(1, 9)]
    assert labels == ["SS", "MP", "SS", "SS+IM", "MP", "IM", "IM", "MP"]
    assert "| Prediction | SS | MP | SS | SS+IM | MP | IM | IM | MP |" in docs.source("example-cantor")
    si = e.calculate({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "Si": 0.5})
    assert si.models["M6"].reason in docs.source("binary-data")

    base = [SweepSpec(x, 1.0, 1.0, 0.1) for x in ("Co", "Cr", "Fe", "Ni")]
    assert summarize_space(base + [SweepSpec("Al", 0.1, 0.5, 0.1, False)], "ratio").compositions == 6
    assert summarize_space(base + [SweepSpec("Al", 0.1, 0.5, 0.1, False)], "mass").compositions == 6
    for unit in ("at", "wt"):
        assert count_space([SweepSpec(x, 20, 60, 10) for x in ("Fe", "Cr", "Ni")], unit).count == 15
        assert count_space([SweepSpec(x, 0, 100, 10) for x in ("Fe", "Cr", "Ni")], unit).count == 36
    five = [SweepSpec(x, 1.0, 1.0, 0.1, False) for x in ("Co", "Cr", "Fe", "Mn", "Ni")]
    assert count_space(five, "ratio").count == 26 and count_space(five, "ratio", {4}).count == 5
    ws = base + [SweepSpec("Al", 0.05, 1.5, 0.05, False), SweepSpec("Mn", 0.1, 1.0, 0.1, False)]
    assert summarize_space(ws, "ratio").compositions == 341

    def expr(text_, ranges):
        return count_blocks(parse_blocks(text_, e.data), {k: VariableRange(k, *v) for k, v in ranges.items()})
    assert expr("AlxCoCrFeNi", {"x": (0, 1, 0.1)}) == (11, 0, 0)
    assert expr("AlxCoCrFeNi", {"x": (0, 2, 0.05)}) == (41, 0, 0)
    assert expr("(FeCoNi)1-xAlx", {"x": (0, 1, 0.25)}) == (4, 1, 0)
    assert expr("AlxCoCrFeNi\n\n(CoCrFeNi)1-yAly", {"x": (0, 2, 0.1), "y": (0, 0.3, 0.05)}) == (26, 0, 2)


def test_documented_limits_match_the_code():
    from hea_calc.core import limits
    from hea_calc.core.expression import MAX_COMBINATIONS
    from hea_calc.ui.preferences import DEFAULT_TOTAL_MASS
    from hea_calc.ui.widgets.composition_panel import RANGE_DEFAULTS
    w = docs.source("workload")
    assert f"{limits.ALLOYS_PER_WORKER_S:,}" in w and f"{limits.BYTES_PER_RESULT}" in w
    assert f"{limits.LARGE:,}" in w and f"{limits.HARD_LIMIT:,}" in w
    assert f"{MAX_COMBINATIONS:,}" in docs.source("expression-syntax")
    assert f"default is {DEFAULT_TOTAL_MASS:g} g" in docs.source("representations")
    space = docs.source("composition-space")
    for unit, label in (("ratio", "At. ratio"), ("at", "at.%"), ("wt", "wt.%"), ("mass", "Mass")):
        assert f"| **{label}** | {', '.join(RANGE_DEFAULTS[unit])}" in space, unit


def test_descriptor_reference_is_generated_from_the_engine_registry():
    from hea_calc.core.analysis.metrics import DESCRIPTORS
    sym = docs.source("symbols")
    assert "<!-- descriptors -->" not in sym
    for dd in DESCRIPTORS.values():
        assert dd.name in sym, dd.key
    assert "Size mismatch — Guo & Liu radii" in sym and "Size mismatch — Kittel CN12 radii" in sym


def test_documentation_describes_the_current_product():
    text = "\n".join(docs.source(p) for p in docs.ORDER)
    for gone in ("Checked results", "Check results", "Composition sweep", "Expression mode", "Settings…"):
        assert gone not in text, gone
    for current in ("Composition space", "Composition expression", "Range basis", "System default",
                    "Mass (2 g batch)", "Partial model coverage", "Show in results table", "Distribution of"):
        assert current in text, current


def test_references_are_numbered_with_verified_dois():
    ref = docs.source("references")
    for n in range(1, 14):
        assert f"[{n}] " in ref
    for doi in ("10.1016/j.matchemphys.2011.11.021", "10.1016/j.intermet.2013.05.002",
                "10.1016/j.scriptamat.2014.09.010", "10.1016/j.intermet.2014.04.019",
                "10.1016/j.scriptamat.2015.03.023", "10.1103/PhysRevX.5.011041",
                "10.1016/j.jallcom.2015.10.279", "10.1016/j.actamat.2015.11.040"):
        assert f"https://doi.org/{doi}" in ref


# ====================================================================== Help window (offscreen)
@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    a = QApplication.instance() or QApplication([])
    load_fonts()
    return a


@pytest.fixture()
def win(app):
    from PySide6.QtCore import QSettings
    from hea_calc.ui.main_window import MainWindow
    from hea_calc.ui.theme import THEME
    THEME.set_theme("dark")
    w = MainWindow(settings=QSettings(str(Path(tempfile.mkdtemp()) / "s.ini"), QSettings.Format.IniFormat))
    w.resize(1440, 900)
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def pump(app, n=4):
    for _ in range(n):
        app.processEvents()


def test_help_window_is_one_native_window_with_the_documented_frame(win, app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton
    hw = win.show_help("home")
    pump(app)
    assert hw.isWindow() and hw.isVisible()
    assert hw.windowTitle() == "Help — HEA Calculator"
    assert (hw.width(), hw.height()) == (960, 720)
    assert not hw.windowFlags() & Qt.WindowType.FramelessWindowHint, "native caption"
    assert not [b for b in hw.findChildren(QPushButton) if b.text().strip().lower() == "close"]
    assert 260 <= hw.nav.width() <= 270
    assert win.show_help("faq") is hw, "one Help window"
    assert hw.page == "faq"


def test_help_entry_points_route_to_their_pages(win, app):
    from hea_calc.ui import help_router
    act = next(a for a in win.file_menu.actions() if a.text().startswith("Help"))
    assert act.shortcut().toString() == "F1"
    act.trigger()
    pump(app)
    assert win._help.page == "home"
    win.header.help_requested.emit()
    pump(app)
    assert win._help.page == "home"
    assert help_router.open("help://models#model-requirements", win.composition)
    pump(app)
    assert (win._help.page, win._help.anchor) == ("model-coverage", "model-requirements")
    win.analysis_ctl.help_requested.emit("collections")
    pump(app)
    assert win._help.page == "collection-analysis"
    assert help_router.open("help://workload", win)
    assert win._help.page == "workload"
    assert not help_router.open("help://nowhere", win)


def test_help_window_navigation_search_and_theme(win, app):
    from hea_calc.ui.theme import THEME
    hw = win.show_help("composition-space")
    pump(app)
    assert hw.nav.currentItem().data(0, 256) == "composition-space"
    assert "Composition Space" in hw.article_text() and "Range basis" in hw.article_text()
    hw.view.link.emit("help://defining")                       # breadcrumb
    pump(app)
    assert hw.page == "defining"
    hw.home_btn.click()
    assert hw.page == "home"
    hw.search.setText("mixing enthalpy")
    hw._run_search()
    pump(app)
    assert "Search results" in hw.article_text() and hw.hits
    first = hw.hits[0]
    hw._open_first_hit()
    pump(app)
    assert hw.page == first.page and not hw.search.text()
    assert hw.view.extraSelections(), "matched terms are highlighted"
    hw.search.setText("delta")
    hw._run_search()
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    hw.eventFilter(hw.search, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    pump(app)
    assert not hw.search.text() and "Search results" not in hw.article_text()
    dark_css = hw.view.document().defaultStyleSheet()
    THEME.set_theme("light")
    pump(app)
    assert hw.view.document().defaultStyleSheet() != dark_css
    assert THEME.tokens["text-primary"] in hw.view.document().defaultStyleSheet()
    THEME.set_theme("dark")


def test_help_images_load_scaled_for_the_screen(win, app):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QTextDocument
    hw = win.show_help("welcome")
    pump(app)
    pm = hw.view.loadResource(QTextDocument.ResourceType.ImageResource.value, QUrl("images/main-window.png"))
    assert not pm.isNull()
    assert abs(pm.width() / pm.devicePixelRatio() - hw.view.image_width) < 1.0
