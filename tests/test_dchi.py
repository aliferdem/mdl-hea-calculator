"""Pauling electronegativity difference Δχ (Guo & Liu 2011 Eq. 4) - data, published values, missing data,
integration and independence from M1-M8 (CALCULATION_AUDIT.md section 3.19)."""

import csv
import json
import math
import os
import shutil
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import REF  # noqa: E402
from hea_calc.core.composition import parse_formula  # noqa: E402
from hea_calc.core.data import DATA_DIR, Datasets  # noqa: E402
from hea_calc.core.engine import MODEL_KEYS, Engine  # noqa: E402

PAULING = json.loads((REF / "guo_liu_2011_table1_pauling.json").read_text(encoding="utf-8"))["pauling"]
PUBLISHED = json.loads((REF / "dchi_published.json").read_text(encoding="utf-8"))
GL_TABLE2 = PUBLISHED["guo_liu_2011_table2"]
SINGH = PUBLISHED["singh_2023"]["rows"]
KEY = "electronegativity_pauling"


@pytest.fixture(scope="module")
def data():
    return Datasets()


def _dchi(engine, formula):
    res = engine.calculate(parse_formula(formula))
    assert res.ok, res.error
    return res


# ---------------------------------------------------------------------- elemental data
def test_reference_holds_the_73_table1_elements():
    assert len(PAULING) == 73
    radius = json.loads((REF / "guo_liu_2011_table1.json").read_text(encoding="utf-8"))["radius_pm"]
    assert set(PAULING) == set(radius), "the same 73 rows as the radius column of Table 1"


@pytest.mark.parametrize("el", sorted(PAULING))
def test_pauling_value_equals_guo_liu_table1(data, el):
    assert data.prop(el, KEY) == PAULING[el]


def test_only_table1_elements_have_a_pauling_value(data):
    with_value = {el for el in data.elements if data.prop(el, KEY) is not None}
    assert with_value == set(PAULING)
    # the 45 elements outside Table 1 are exactly the supplementary-radius list
    assert set(data.elements) - with_value == set(data.periodic_table_metadata["atomic_radius_supplementary"])


def test_pauling_metadata_records_the_source(data):
    text = data.periodic_table_metadata["properties"][KEY]
    for needle in ("Guo & Liu", "Table 1", "435-436", "73 elements", "renderings", "no other electronegativity"):
        assert needle in text


# ---------------------------------------------------------------------- equation
def test_binary_closed_form(engine):
    """For a binary, Eq. 4 reduces to |χA − χB|·√(c(1 − c))."""
    for c in (0.1, 0.25, 0.5, 0.8):
        d = engine.calculate({"Fe": c, "Ni": 1 - c}).descriptors["dchi"]
        assert d == pytest.approx(abs(1.83 - 1.91) * math.sqrt(c * (1 - c)), rel=1e-12)


def test_hand_calculation_cocrfemnni(engine):
    chi = [1.88, 1.66, 1.83, 1.55, 1.91]
    mean = sum(chi) / 5
    expected = math.sqrt(sum((x - mean) ** 2 for x in chi) / 5)
    assert engine.calculate(parse_formula("CoCrFeMnNi")).descriptors["dchi"] == pytest.approx(expected, rel=1e-12)


def test_amounts_are_normalised(engine):
    a = engine.calculate({"Al": 1, "Co": 1, "Cr": 1}).descriptors["dchi"]
    b = engine.calculate({"Al": 33.3, "Co": 33.3, "Cr": 33.3}).descriptors["dchi"]
    assert a == pytest.approx(b, rel=1e-12)


# ---------------------------------------------------------------------- published values
@pytest.mark.parametrize("formula,printed,table", SINGH, ids=[r[0] for r in SINGH])
def test_dchi_reproduces_singh_2023(engine, formula, printed, table):
    """Singh et al. (2023) Tables 2-3 print Δχ truncated (not rounded) to the printed digits."""
    _ = table
    value = _dchi(engine, formula).descriptors["dchi"]
    unit = 10.0 ** Decimal(printed).as_tuple().exponent
    assert 0.0 <= value - float(printed) < unit + 1e-12, (formula, value, printed)


@pytest.mark.parametrize("formula,printed", GL_TABLE2["rows"], ids=[r[0] for r in GL_TABLE2["rows"]])
def test_dchi_reproduces_guo_liu_2011_table2(engine, formula, printed):
    """Guo & Liu (2011) Table 2 prints Δχ to 0.01 (round to nearest; exact halves such as 0.285 included)."""
    value = _dchi(engine, formula).descriptors["dchi"]
    assert abs(value - printed) <= 0.005 + 1e-12, (formula, value, printed)


def test_guo_liu_table2_misprint_is_documented_not_forced(engine):
    """Zr50Ni50: Table 1 gives |1.33 − 1.91|/2 = 0.29; Table 2 prints 0.24.  Recorded, not changed."""
    entry = GL_TABLE2["discrepancies"]["Zr50Ni50"]
    assert entry["printed"] == 0.24
    assert "Zr50Ni50" not in {r[0] for r in GL_TABLE2["rows"]}
    value = _dchi(engine, "Zr50Ni50").descriptors["dchi"]
    assert value == pytest.approx(entry["recalculated"], abs=1e-12)
    assert abs(value - entry["printed"]) > 0.005


# ---------------------------------------------------------------------- zero, single element, missing data
@pytest.mark.parametrize("comp", [{"Ru": 1, "Pd": 1, "Os": 1, "Ir": 1}, {"Cu": 3, "Si": 1}, {"La": 1, "Tb": 2, "Yb": 1},
                                  {"Hf": 1, "Th": 1}, {"Ta": 0.2, "Pa": 0.8}])
def test_equal_electronegativities_give_exactly_zero(engine, comp):
    res = engine.calculate(comp)
    assert res.ok
    assert res.descriptors["dchi"] == 0.0 and res.descriptors["dchi"] is not None
    assert res.descriptors["dchi_unavailable"] is None and res.descriptors["dchi_missing"] == []
    assert not any("electronegativity" in w for w in res.warnings)


def test_single_element_is_not_an_alloy_and_has_no_dchi(engine):
    for comp in ({"Fe": 1.0}, {"Fe": 1.0, "Ni": 0.0}):
        res = engine.calculate(comp)
        assert not res.ok and "dchi" not in res.descriptors
    # the equation itself gives 0 for one element (a zero spread), never None
    assert Engine._dchi({"Fe": 1.0}, {"Fe": 1.83}) == 0.0


@pytest.mark.parametrize("comp,missing", [({"Fe": 1, "Ni": 1, "Sb": 1}, ["Sb"]),
                                          ({"Bi": 1, "Cu": 1, "As": 0.5}, ["Bi", "As"]),
                                          ({"Pu": 1, "U": 1}, ["Pu"]), ({"Hg": 1, "Cd": 1}, ["Hg"])])
def test_missing_electronegativity_is_na_with_reason_never_zero(engine, comp, missing):
    res = engine.calculate(comp)
    assert res.ok
    d = res.descriptors
    assert d["dchi"] is None
    assert d["dchi_missing"] == missing
    reason = d["dchi_unavailable"]
    assert reason and "Pauling electronegativity" in reason and "Guo & Liu" in reason
    assert all(el in reason for el in missing)
    assert reason in res.warnings


def test_missing_electronegativity_does_not_block_other_descriptors(engine):
    res = engine.calculate({"Fe": 1, "Ni": 1, "Sb": 1})
    d = res.descriptors
    assert d["dchi"] is None
    assert d["vec"] is not None and d["delta"] is not None and d["dsmix"] > 0


def test_dchi_is_never_infinite_or_nan(engine):
    for comp in ({"W": 1, "Cs": 1}, {"O": 1, "Cs": 1}, {"Al": 1e-9, "Ni": 1}):
        v = engine.calculate(comp).descriptors["dchi"]
        assert v is not None and math.isfinite(v) and v >= 0


# ---------------------------------------------------------------------- independence / backward compatibility
@pytest.fixture(scope="module")
def engine_without_chi(tmp_path_factory):
    """The same engine on the same datasets with the Pauling column removed - the pre-Δχ data."""
    d = tmp_path_factory.mktemp("data_no_chi")
    for f in DATA_DIR.glob("*.json"):
        shutil.copy(f, d / f.name)
    pt = json.loads((d / "periodic_table.json").read_text(encoding="utf-8"))
    pt["_metadata"]["properties"].pop(KEY)
    for el, rec in pt.items():
        if el != "_metadata":
            rec["properties"].pop(KEY, None)
    (d / "periodic_table.json").write_text(json.dumps(pt, indent=2), encoding="utf-8")
    return Engine(Datasets(d))


COMPAT = ["CoCrFeMnNi", "Ti0.5NbMoTaW", "AlCoCrCuFeNi", "Zr50Cu50", "Cu0.5NiAlCoCrFeSi", "HfNbTaTiZr", "FeNiSb",
          "CaSrBaMg", "NbTiV2Zr", "SrCaYb(Li0.55Mg0.45)Zn", "Al0.5CrCuNiV", "PdPtRhIrCuNi", "BiCuAs0.5", "CNFe2"]


@pytest.mark.parametrize("formula", COMPAT)
def test_dchi_changes_no_other_descriptor_or_model(engine, engine_without_chi, formula):
    new = engine.calculate(parse_formula(formula))
    old = engine_without_chi.calculate(parse_formula(formula))
    assert new.ok == old.ok
    dchi_keys = {"dchi", "dchi_missing", "dchi_unavailable"}
    assert {k: v for k, v in new.descriptors.items() if k not in dchi_keys} == \
        {k: v for k, v in old.descriptors.items() if k not in dchi_keys}
    for k in MODEL_KEYS:
        a, b = new.models[k], old.models[k]
        assert (a.label, a.reason, a.caution, a.status, a.na_kind, a.values) == \
            (b.label, b.reason, b.caution, b.status, b.na_kind, b.values), (formula, k)
    assert [w for w in new.warnings if "electronegativity" not in w] == \
        [w for w in old.warnings if "electronegativity" not in w]
    assert old.descriptors["dchi"] is None            # without the column Δχ is N/A, never 0


# ---------------------------------------------------------------------- integration
def test_descriptor_is_a_results_column_and_analysis_metric():
    from hea_calc.core.analysis.metrics import DESCRIPTORS, G_ELECTRONIC, METRIC_KEYS
    from hea_calc.core.chunks import NUM_KEYS
    from hea_calc.core.results import COLUMN_BY_KEY, DEFAULT_COLUMNS, chooser_groups
    col = COLUMN_BY_KEY["dchi"]
    assert col.header == "Δχ" and col.kind == "num" and col.stored and col.decimals == 3
    assert col.model is None, "a shared descriptor: no model owns it"
    assert "dchi" not in DEFAULT_COLUMNS, "optional column: the default table layout is unchanged"
    assert "Pauling" in col.chooser_tip and "no model" in col.chooser_tip
    assert col.tooltip == col.chooser_tip and "Guo" not in col.tooltip, "plain description, no source"
    assert any(c.key == "dchi" for title, cols in chooser_groups() if title == "General" for c in cols)
    assert "dchi" in NUM_KEYS and "dchi" in METRIC_KEYS
    d = DESCRIPTORS["dchi"]
    assert d.group == G_ELECTRONIC and d.unit == "" and "Eq. 4" in d.definition and "Pauling" in d.data


def test_export_headers_include_dchi():
    from hea_calc.core.export import export_headers, export_keys
    assert "dchi" in export_keys()
    assert "Δχ" in export_headers(["Fe", "Ni"])


def test_tsv_and_cell_format(engine):
    from hea_calc.core.results import ResultRow, format_cell, table_tsv
    ok = ResultRow("CoCrFeMnNi", {"Co": 1}, engine.calculate(parse_formula("CoCrFeMnNi")))
    na = ResultRow("FeNiSb", {"Fe": 1}, engine.calculate({"Fe": 1, "Ni": 1, "Sb": 1}))
    zero = ResultRow("RuOs", {"Ru": 1}, engine.calculate({"Ru": 1, "Os": 1}))
    assert format_cell(ok, "dchi") == "0.138"
    assert format_cell(na, "dchi") == "N/A"
    assert format_cell(zero, "dchi") == "0.000"
    assert table_tsv([ok, na], ["name", "dchi"]).splitlines() == ["Alloy\tΔχ", "CoCrFeMnNi\t0.138", "FeNiSb\tN/A"]


def test_repository_round_trip_and_file_export(engine, tmp_path):
    import openpyxl
    from hea_calc.core.export import write_records
    from hea_calc.core.repository import ResultRepository, ResultView
    from hea_calc.core.results import RangeFilter, ResultRow
    repo = ResultRepository(engine, root=tmp_path / "sessions")
    try:
        comps = {"CoCrFeMnNi": parse_formula("CoCrFeMnNi"), "FeNiSb": {"Fe": 1, "Ni": 1, "Sb": 1},
                 "RuOs": {"Ru": 1, "Os": 1}}
        rows = [ResultRow(n, c, engine.calculate(c), "single", {}) for n, c in comps.items()]
        view = ResultView(repo)                                  # a view sees the results stored after it
        run = repo.create_run("single", settings={}, elements=["Co", "Cr", "Fe", "Mn", "Ni", "Sb", "Ru", "Os"])
        rng = repo.append_results(run, rows)
        repo.finalize_run(run, "complete")
        got = {repo.get_result(i).name: repo.get_result(i).raw("dchi") for i in rng}
        assert got["CoCrFeMnNi"] == pytest.approx(rows[0].result.descriptors["dchi"], rel=1e-15)
        assert got["FeNiSb"] is None, "N/A is stored as NULL, never 0"
        assert got["RuOs"] == 0.0
        view.refresh()
        assert view.request(filters=[RangeFilter("dchi", 0.1, 0.2)], wait=10)
        assert [r.name for r in view.iterate()] == ["CoCrFeMnNi"], "N/A never passes a numeric filter"
        assert view.request(filters=[], wait=10)
        els = ["Co", "Cr", "Fe", "Mn", "Ni", "Sb", "Ru", "Os"]
        out_csv, out_xlsx = tmp_path / "r.csv", tmp_path / "r.xlsx"
        assert write_records(view.iterate(), out_csv, els) == 3
        with out_csv.open(encoding="utf-8-sig", newline="") as fh:
            table = {r["Alloy"]: r["Δχ"] for r in csv.DictReader(fh)}
        assert float(table["CoCrFeMnNi"]) == pytest.approx(got["CoCrFeMnNi"], rel=1e-12)
        assert table["FeNiSb"] == "" and float(table["RuOs"]) == 0.0
        assert write_records(view.iterate(), out_xlsx, els) == 3
        wb = openpyxl.load_workbook(out_xlsx, read_only=True)
        sheet = list(wb["Results"].iter_rows(values_only=True))
        wb.close()
        i = sheet[0].index("Δχ")
        xl = {r[0]: r[i] for r in sheet[1:]}
        assert xl["CoCrFeMnNi"] == pytest.approx(got["CoCrFeMnNi"], rel=1e-12)
        assert xl["FeNiSb"] in (None, "") and xl["RuOs"] == 0.0
    finally:
        repo.close()


def test_details_value_shows_the_reason(engine):
    from hea_calc.ui.analysis.composition_view import kv_value
    d = engine.calculate({"Fe": 1, "Ni": 1, "Sb": 1}).descriptors
    text, tip = kv_value(d, "dchi")
    assert text == "N/A" and "Sb" in tip and "Pauling electronegativity" in tip
    text, _ = kv_value(engine.calculate({"Ru": 1, "Os": 1}).descriptors, "dchi")
    assert text == "0.000"
    # descriptors without a recorded reason keep the generic text; undefined ones keep theirs
    assert kv_value({"tm": None}, "tm") == ("N/A", "Not available (missing data)")
    assert kv_value({"omega": None, "omega_undefined": "why"}, "omega") == ("Undefined", "why")


def test_filter_dialog_offers_dchi():
    from hea_calc.ui.widgets.dialogs import FILTER_KEYS
    assert "dchi" in FILTER_KEYS


def test_help_documents_dchi():
    from hea_calc.core import docs
    symbols = docs.source("symbols")
    assert "Δχ" in symbols and "Electronegativity difference" in symbols
    hits = docs.index().search("electronegativity difference")
    assert hits, "Help search finds the descriptor"
    from hea_calc.core.references import DATA_REFERENCES
    gl = next(r for r in DATA_REFERENCES if r.key == "guo-liu")
    assert "Pauling electronegativities" in gl.note and "Eq. 4" in gl.note


# ---------------------------------------------------------------------- Elements panel
def test_element_panel_shows_pauling_electronegativity_from_the_dataset():
    from PySide6.QtWidgets import QApplication
    from hea_calc.ui.theme import load_fonts
    from hea_calc.ui.widgets.element_panel import ElementInfo
    app = QApplication.instance() or QApplication([])
    _ = app
    # the application fonts are registered before any widget asks for them, as at start-up (app.py); a font
    # requested earlier resolves to a fallback that Qt caches for the rest of the process
    load_fonts()
    data = Datasets()
    info = ElementInfo(data)
    try:
        assert max(len(g) for g in info.GROUPS) == 3, "χ uses a free row: the panel keeps three rows"
        assert info.keys["electronegativity_pauling"].text() == "χ"
        tip = info.keys["electronegativity_pauling"].toolTip()
        assert "Pauling" in tip and "Δχ" in tip
        label = info.values["electronegativity_pauling"][0]
        # printed precision (0.01), the dataset value itself: no second table of values
        for el, shown in (("Fe", "1.83"), ("W", "2.36"), ("Ca", "1.00"), ("Cs", "0.79"), ("U", "1.38")):
            info.show_element(el)
            assert label.text() == shown == f"{data.prop(el, KEY):.2f}", el
        # outside Guo & Liu's Table 1: the panel's "no value" dash, never 0
        for el in ("Sb", "Bi", "Hg", "H", "Pu"):
            info.show_element(el)
            assert data.prop(el, KEY) is None and label.text() == "—", el
        info.show_element(None)
        assert label.text() == "—"
    finally:
        info.deleteLater()
