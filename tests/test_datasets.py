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
    assert math.isclose(data.prop("Fe", "atomic_radius"), 124.12)
