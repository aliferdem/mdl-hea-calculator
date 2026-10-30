"""Dataset provenance: every value traced to the literature in Model Sources."""

import itertools
import json
import math

import pytest

from conftest import REF
from hea_calc.core.data import Datasets

TROP_ORDER = "Mg Al Sc Ti V Cr Mn Fe Co Ni Cu Zn Y Zr Nb Mo Ru Rh Pd Ag Cd La Hf Ta W Re Os Ir Pt Au".split()


@pytest.fixture(scope="module")
def data():
    return Datasets()


def test_formation_matrix_is_the_published_troparevsky_matrix(data):
    sup = json.loads((REF / "troparevsky_supplement.json").read_text())["matrix"]
    conflicts = []
    for i, a in enumerate(TROP_ORDER):
        for b in TROP_ORDER[i + 1:]:
            upper, lower = sup[a][b], sup[b][a]
            assert data.formation_enthalpy(a, b) == upper, (a, b)  # first-in-order row value
            assert data.formation_enthalpy(b, a) == upper  # symmetric lookup
            if upper != lower:
                conflicts.append(f"{a}-{b}")
    listed = {e["pair"] for e in data.formation_metadata["asymmetric_entries"]}
    assert set(conflicts) == listed
    assert len(listed) == 7


@pytest.mark.parametrize("pair,value", [
    (("Ti", "Cr"), -372), (("Cr", "Hf"), -362), (("Fe", "Mo"), -484), (("Fe", "W"), -554),
    (("Fe", "Nb"), -2505), (("Fe", "Ta"), -3468), (("Mn", "Mo"), -138), (("Ti", "La"), 134),
    (("Zn", "Mo"), -42), (("Mo", "Ta"), -193), (("Ni", "Al"), -677), (("Mn", "Ni"), -115),
])
def test_formation_values_quoted_in_papers(data, pair, value):
    # Troparevsky text: Mn-Ni -115, Mo-Ta -193, NiAl -677; others: published matrix cells.
    assert data.formation_enthalpy(*pair) == value


def test_formation_missing_pair_is_none_not_zero(data):
    assert data.formation_enthalpy("Fe", "Si") is None
    assert data.formation_enthalpy("Fe", "Fe") is None


def test_mixing_enthalpy_physical_zero_and_missing(data):
    assert data.mixing_enthalpy("Fe", "Mn") == 0.0  # tabulated zero (Takeuchi & Inoue 2005)
    assert data.mixing_enthalpy("Mn", "Fe") == 0.0
    assert data.mixing_enthalpy("Co", "Ni") == 0.0
    assert data.mixing_enthalpy("Fe", "Og") is None  # Og not in the table
    assert data.mixing_enthalpy("Al", "Ni") == -22.0
    assert data.mixing_enthalpy("Cu", "Fe") == 13.0


def test_mixing_table_covers_73_elements_completely(data):
    els = sorted(data.mixing_elements)
    assert len(els) == 73
    assert all(data.mixing_enthalpy(a, b) is not None for a, b in itertools.combinations(els, 2))


def test_kittel_cn12_radii(data):
    ref = json.loads((REF / "kittel_cn12.json").read_text())["values_pm"]
    for el, v in ref.items():
        assert data.prop(el, "atomic_radius_cn12") == pytest.approx(v), el


def test_atomic_radius_follows_guo_liu_table1_within_printed_precision(data):
    """Guo & Liu (2011) Table 1 prints 73 radii to 0.1 pm; every stored value of those elements must round to it.

    Half a printed unit (0.05 pm) accepts the 0.01 pm digits taken from Zhang et al. (2014) - that precision is a
    separate, open decision (CALCULATION_AUDIT.md section 17.1) - but no value from another table.  Before section 18
    this failed for exactly Pm, Po, Pa and U, which held Kittel CN12 values.
    """
    ref = json.loads((REF / "guo_liu_2011_table1.json").read_text(encoding="utf-8"))["radius_pm"]
    assert len(ref) == 73
    off = {el: (data.prop(el, "atomic_radius"), v) for el, v in ref.items()
           if data.prop(el, "atomic_radius") is None or abs(data.prop(el, "atomic_radius") - v) > 0.05 + 1e-9}
    assert not off, off
    assert not any(data.radius_is_supplementary(el) for el in ref)  # Guo & Liu elements are never flagged


def test_atomic_radius_equals_guo_liu_table1_exactly(data):
    """F2 (audit section 20): every Guo & Liu (2011) Table 1 element holds the printed value (0.1 pm) - no rounding
    function involved (Zn 139.5 and Zr 160.3 as printed, where half-even rounding of the former 0.01 pm values gives
    139.4 / 160.2)."""
    ref = json.loads((REF / "guo_liu_2011_table1.json").read_text(encoding="utf-8"))["radius_pm"]
    off = {el: (data.prop(el, "atomic_radius"), v) for el, v in ref.items() if data.prop(el, "atomic_radius") != v}
    assert not off, off
    assert (data.prop("Zn", "atomic_radius"), data.prop("Zr", "atomic_radius")) == (139.5, 160.3)


@pytest.mark.parametrize("el,guo_liu,kittel_cn12", [
    ("Pm", 163.0, 181.0), ("Po", 153.0, 176.0), ("Pa", 161.0, 163.0), ("U", 142.0, 156.0),
])
def test_pm_po_pa_u_radii_are_guo_liu_values_not_cn12(data, el, guo_liu, kittel_cn12):
    """Guo & Liu (2011) Table 1 p. 436 (1.630 / 1.530 / 1.610 / 1.420 A; U also Zhang et al. 2014 Table 1, 0.14200 nm)
    for M2-M5; the separate M1 column keeps Kittel's CN12 values (Ch. 3 Table 9, p. 71).  Audit section 18."""
    assert data.prop(el, "atomic_radius") == guo_liu
    assert data.prop(el, "atomic_radius_cn12") == kittel_cn12


def test_miedema_formula_reproduces_bakker_table_a2(engine):
    table = json.loads((REF / "bakker_table_A2.json").read_text())["table"]
    worst = 0.0
    n = 0
    for a, row in table.items():
        for b, v in row.items():
            if a == b:
                continue
            calc = engine.interfacial_enthalpy(a, b)
            worst = max(worst, abs(calc - v))
            n += 1
    assert n >= 800
    assert worst <= 2.2  # rounding of Bakker's integer table


# ---------------------------------------------------------------- Miedema: Ca, Sr, Ba (audit M8-AE, 2026-10-27)
def _bakker_a3_a4_residuals(engine, x):
    ref = json.loads((REF / "bakker_table_A3_A4.json").read_text(encoding="utf-8"))
    res = [engine.interfacial_enthalpy(x, t) - v for t, v in ref["A3_X_in_TM"][x].items()]
    res += [engine.interfacial_enthalpy(t, x) - v for t, v in ref["A4_TM_in_X"][x].items()]
    return res


@pytest.mark.parametrize("el", ["Ca", "Sr", "Ba"])
def test_miedema_reproduces_bakker_a3_a4_alkaline_earth(engine, el):
    """Bakker Tables A3/A4: Ca/Sr/Ba with 24 transition metals, both directions (48 printed values each).

    4.0 kJ/mol per value: the stored n_ws (Bakker A1, 2 decimals) vs the n_ws^1/3 behind the table (de Boer V-1.3) is
    worth up to ~3 kJ/mol for these low-density metals (all 144 values are within 1.4 with the printed n_ws^1/3);
    the rms bound keeps the test sharp (a = 0.04 gives rms 20-27, P = 10.7 gives >= 14).
    """
    res = _bakker_a3_a4_residuals(engine, el)
    assert len(res) == 48
    assert max(abs(r) for r in res) <= 4.0
    assert math.sqrt(sum(r * r for r in res) / len(res)) <= 2.0


@pytest.mark.parametrize("el", ["Mg", "Al"])
def test_miedema_reproduces_bakker_a3_a4_calibration_rows(engine, el):
    """The same tables for Mg and Al, whose factors were never in question: guards the unchanged mixed-pair path."""
    res = _bakker_a3_a4_residuals(engine, el)
    assert len(res) == 48
    assert max(abs(r) for r in res) <= 3.0


@pytest.mark.parametrize("a,b,p,r_over_p", [
    ("Ca", "Fe", 12.35, 0.0), ("Fe", "Ca", 12.35, 0.0),   # d-type with d-type: no R; divalent + high-valent P
    ("Ca", "Al", 10.7, 0.76), ("Al", "Ca", 10.7, 0.76),   # Fig. 2.28: 0.4 x 1.9; P of two non-transition metals
    ("Ca", "Mg", 10.7, 0.16), ("Ca", "Li", 10.7, 0.0), ("Ca", "Sr", 10.7, 0.0),
    ("Ba", "Sn", 10.7, 0.84), ("Sr", "Cu", 12.35, 0.0),
    ("Fe", "Al", 12.35, 1.9), ("Mg", "Al", 10.7, 0.0), ("Fe", "Ni", 14.2, 0.0),  # unchanged classes
])
def test_miedema_classification_ca_sr_ba(engine, a, b, p, r_over_p):
    """de Boer et al. 1988: Eqs. 2.35-2.36 (P), Fig. 2.28 and program Table V-3 `detr` (R class), Q/P = 9.4."""
    pp, q, r = engine._pqr(a, b)
    assert pp == p
    assert q == pytest.approx(9.4 * p)
    assert r / p == pytest.approx(r_over_p)


@pytest.mark.parametrize("el,a", [("Ca", 0.10), ("Sr", 0.10), ("Ba", 0.10), ("Mg", 0.10), ("Li", 0.14),
                                  ("Al", 0.07), ("Fe", 0.04)])
def test_miedema_volume_coefficient(engine, el, a):
    """de Boer et al. 1988 Eq. 2.33: 0.14 alkaline, 0.10 divalent, 0.07 noble and trivalent, 0.04 all others."""
    assert engine._volume_coefficient(el) == a


DE_BOER_V4_02_KNOWN = {("Be", "As"), ("Sb", "Cd")}  # printed values the equation does not give (checked on the page)


def test_miedema_reproduces_de_boer_table_v4_02(engine):
    """de Boer et al. 1988 Table V-4.02: two polyvalent non-transition metals (printed rows = solute, R = 0)."""
    table = json.loads((REF / "de_boer_table_V4_02.json").read_text(encoding="utf-8"))["table"]
    bad, known = [], []
    for a, row in table.items():
        for b, v in row.items():
            d = abs(engine.interfacial_enthalpy(a, b) - v)
            if (a, b) in DE_BOER_V4_02_KNOWN:
                known.append((a, b, v, d))
            elif d > 2.0:
                bad.append((a, b, v, d))
    assert sum(len(r) for r in table.values()) == 240
    assert not bad, bad
    assert len(known) == 2 and all(d > 5.0 for *_x, d in known), known  # a documented discrepancy must not silently disappear


@pytest.mark.parametrize("el,phi,nws,v,k,g", [
    ("Fe", 4.93, 5.55, 7.09, 16.83, 8.152), ("Al", 4.20, 2.70, 10.00, 7.218, 2.659),
    ("Cr", 4.65, 5.18, 7.23, 19.03, 11.67), ("Ni", 5.20, 5.36, 6.60, 18.64, 7.505),
])
def test_miedema_parameters_match_bakker_tables_a1_a5(data, el, phi, nws, v, k, g):
    assert (data.prop(el, "work_function_phi"), data.prop(el, "n_ws"), data.prop(el, "molar_volume")) == (phi, nws, v)
    assert (data.prop(el, "bulk_modulus"), data.prop(el, "shear_modulus")) == (k, g)


def test_supplementary_radius_flag(data):
    assert data.radius_is_supplementary("Hg")
    assert not data.radius_is_supplementary("Fe")
    assert data.prop("Fe", "atomic_radius") == 124.1    # Guo & Liu Table 1 printed value (audit section 20)
