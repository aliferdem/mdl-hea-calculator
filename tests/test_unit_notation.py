"""Scientific units are written with negative exponents (kJ mol⁻¹, J mol⁻¹ K⁻¹, g cm⁻³), never with a solidus.

Display formatting only: values, keys and machine-readable identifiers are unchanged (2026-11-05)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# a unit symbol, a solidus, then another unit symbol or a parenthesised unit: kJ/mol, g/cm³, J/(mol·K), meV/atom ...
_UNITS = r"(?:kJ|J|meV|eV|mAh|emu|g|kg|mg|cm³|cm3|m³|mol|W|A|V|Pa|GPa|K|s|m)"
_PER = r"(?:mol|atom|K|g|kg|cm³|cm3|cm|m³|m|s|Pa)"
SLASH_UNIT = re.compile(rf"(?<![\w/.:]){_UNITS}/(?:\(|{_PER}(?![A-Za-z_/]))")


def _no_slash_units(text: str, where: str) -> None:
    text = re.sub(r"https?://\S+|doi:\S+|`[^`]*`|\[[^\]]*\]\([^)]*\)", " ", text)     # links, code, file paths
    bad = SLASH_UNIT.findall(text)
    assert not bad, (where, bad)


def test_the_pattern_finds_units_and_spares_other_slashes():
    for unit in ("kJ/mol", "g/cm³", "J/(mol·K)", "meV/atom", "cm³/mol", "emu/g", "A/m", "m/s²", "mAh/g", "W/(m K)"):
        assert SLASH_UNIT.search(f"value ({unit})"), unit
    for ok in ("ΔSmix/δ²", "ΔH_IM/ΔHmix", "Tm ΔSmix / |ΔHmix|", "1/2", "data/periodic_table.json", "N/A", "and/or",
               "https://doi.org/10.1016/j.actamat.2015.08.076", "kJ mol⁻¹", "J mol⁻¹ K⁻¹"):
        assert not SLASH_UNIT.search(ok), ok


def test_results_columns_use_negative_exponents_once():
    from hea_calc.core.results import COLUMNS
    for c in COLUMNS:
        for text in (c.header, c.tooltip, c.chooser_tip, c.unit):
            _no_slash_units(text, c.key)
        if c.unit:
            assert c.header.endswith(f" ({c.unit})"), (c.key, c.header)
            assert c.tooltip.count(c.unit) == 1 and f"({c.unit})" in c.tooltip, (c.key, c.tooltip)
            assert c.tooltip.count("(") == c.tooltip.count(")")
        assert c.header.split(" (")[0] not in c.tooltip.split("\n")[0] or c.kind == "model" or not c.tooltip, \
            (c.key, "the tooltip does not repeat the column label")


def test_export_and_clipboard_headers_use_the_display_units():
    from hea_calc.core.export import export_headers, export_keys
    from hea_calc.core.results import table_tsv
    head = export_headers(["Co", "Cr"])
    assert "ΔHmix (kJ mol⁻¹)" in head and "ρ (g cm⁻³)" in head and "ΔSmix (J mol⁻¹ K⁻¹)" in head
    assert "Co (at.%)" in head
    for h in head:
        _no_slash_units(h, h)
    # the machine-readable column identifiers and their order are unchanged
    assert export_keys() == ["name", "run", "variables", "density", "tm", "dhmix", "dsmix", "delta", "delta_cn12",
                             "vec", "cstr", "dchi", "omega", "gamma", "lambda", "phi_ye", "s_e", "hf_min", "hf_max",
                             "hf_lower", "t_assess", "dhim", "k1", "k1cr", "phi_king", "dg_ss", "dg_max", "mean_mass",
                             "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]
    assert table_tsv([], ["name", "dhmix"]).split("\t")[1].startswith("ΔHmix (kJ mol⁻¹)")


def test_model_texts_figures_and_descriptors():
    from hea_calc.core.analysis.metrics import DESCRIPTORS
    from hea_calc.core.analysis.model_figures import figure
    from hea_calc.core.engine import MODEL_KEYS, MODELS
    for k in MODEL_KEYS:
        m = MODELS[k]
        for text in (m.criterion, m.note, m.title):
            _no_slash_units(text, k)
        f = figure(k)
        for text in [f.x_label, f.y_label, f.caption, f.title] + [ln.label for ln in f.lines if ln.label]:
            _no_slash_units(text, f"{k} figure")
    assert figure("M2").y_label == "ΔHmix (kJ mol⁻¹)" and figure("M6").y_label == "ΔHf (meV atom⁻¹)"
    assert figure("M4").y_label == "Λ (J mol⁻¹ K⁻¹)"
    for d in DESCRIPTORS.values():
        for text in (d.unit, d.name, d.selector_text(), d.axis_title()):
            _no_slash_units(text, d.key)


def test_engine_messages_use_the_display_units():
    from hea_calc.core.engine import Engine
    eng = Engine()
    res = eng.calculate({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "Mn": 1})
    for k, o in res.models.items():
        _no_slash_units(o.reason or "", k)
        _no_slash_units(o.caution or "", k)


@pytest.mark.parametrize("path", sorted((ROOT / "hea_calc" / "docs" / "pages").glob("*.md")) + [ROOT / "README.md"],
                         ids=lambda p: p.name)
def test_documentation_pages(path):
    _no_slash_units(path.read_text(encoding="utf-8"), path.name)


def test_values_are_unchanged_by_the_notation():
    """Formatting only: the same composition gives the same numbers as before (CoCrFeMnNi, README example)."""
    from hea_calc.core.engine import Engine
    d = Engine().calculate({"Co": 1, "Cr": 1, "Fe": 1, "Mn": 1, "Ni": 1}).descriptors
    assert round(d["dhmix"], 2) == -4.16 and round(d["dsmix"], 2) == 13.38 and round(d["omega"], 2) == 5.79
