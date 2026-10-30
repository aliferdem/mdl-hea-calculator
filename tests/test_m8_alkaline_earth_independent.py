"""M8 (King et al. 2016) for Ca/Sr/Ba alloys, re-derived independently of the engine's Miedema code (audit §16).

No published King/M8 value involves Ca, Sr or Ba, so there is no printed alloy-level oracle.  This file is an
*implementation-consistency* test of a different kind: the Miedema pair rules are typed in here from the source
(de Boer et al. 1988: Eq. 2.33 for a, Eqs. 2.35-2.36 for P, Fig. 2.28 for the R/P factors), and the King chain is
written out from its equations (King S1-S10, Bakker Eqs. 1, 9, 28).  Only elemental data (Bakker A1/A5, melting
points) are read from the dataset.  Two anchors make the comparison meaningful:

* with the PRE-correction rule (a = 0.04, no Ca/Sr/Ba factor), the re-derivation reproduces the M8 values recorded
  for CaMgAl before the correction (``docs/analysis-redesign/data/revalidation-2026-10-26/parity_pre_fix.json``,
  formerly pinned in test_m8_support.py) - so it is a faithful copy of the old chain;
* with the SOURCE rule, it must equal the corrected engine - so the engine change is exactly the rule change.

The published-value comparisons for the rule itself are in test_datasets.py (Bakker A3/A4, de Boer V-4.02) and
test_miedema_takeuchi_inoue.py.
"""

import itertools
import math

import pytest

from hea_calc.core.composition import parse_formula
from hea_calc.core.engine import R, Engine

ENGINE = Engine()
PROP = ENGINE.data.prop

# --- de Boer et al. (1988), typed from the book (only the elements used below) --------------------------------
TRANSITION = {"Fe", "Ni", "Cu"}                     # P class "transition" (Eqs. 2.35-2.36); Ca/Sr/Ba are not
FACTOR_D = {"Fe": 1.0, "Ni": 1.0, "Cu": 0.3, "Ca": 0.4, "Sr": 0.4, "Ba": 0.4}   # Fig. 2.28, transition block
FACTOR_P = {"Li": 0.0, "Mg": 0.4, "Zn": 1.4, "Al": 1.9}                       # Fig. 2.28, non-transition block
A_COEF = {"Li": 0.14, "Mg": 0.10, "Zn": 0.10, "Ca": 0.10, "Sr": 0.10, "Ba": 0.10,  # Eq. 2.33
          "Al": 0.07, "Cu": 0.07, "Fe": 0.04, "Ni": 0.04}
STRUCT = set()  # structural term only for two transition metals with 3 <= z <= 10: none of the test alloys has two


def source_rule(a, b):
    """(P, R/P, a_A) for A in B."""
    ta, tb = a in TRANSITION, b in TRANSITION
    p = 14.2 if ta and tb else 10.7 if not ta and not tb else 12.35
    da, db = a in FACTOR_D, b in FACTOR_D
    r = 0.0 if da == db else (FACTOR_D[a] * FACTOR_P[b] if da else FACTOR_D[b] * FACTOR_P[a])
    return p, r, A_COEF[a]


def pre_correction_rule(a, b):
    """The engine before §16: Ca/Sr/Ba non-transition without a factor (R = 0 with p-block metals), a = 0.04."""
    ae = {"Ca", "Sr", "Ba"}
    if (a in ae or b in ae) and (a in TRANSITION or b in TRANSITION):
        raise ValueError("no R/P factor")
    ta, tb = a in TRANSITION, b in TRANSITION
    p = 14.2 if ta and tb else 10.7 if not ta and not tb else 12.35
    r = 0.0 if ta == tb or a in ae or b in ae else (
        FACTOR_D[a] * FACTOR_P[b] if ta else FACTOR_D[b] * FACTOR_P[a])
    return p, r, 0.04 if a in ae else A_COEF[a]


def h_inter(rule, a, b):  # Bakker Eq. 1, infinite dilution
    p, r, ac = rule(a, b)
    va, pa, pb = PROP(a, "molar_volume"), PROP(a, "work_function_phi"), PROP(b, "work_function_phi")
    na, nb = PROP(a, "n_ws"), PROP(b, "n_ws")
    v23 = va ** (2 / 3) * (1 + ac * (pa - pb))
    return v23 / (0.5 * (na ** (-1 / 3) + nb ** (-1 / 3))) * p * (
        -(pa - pb) ** 2 + 9.4 * (na ** (1 / 3) - nb ** (1 / 3)) ** 2 - r)


def h_elastic(a, b):  # Bakker Eqs. 14, 28; K, G in 1e10 Pa, V in cm3/mol -> x10 kJ/mol
    va, vb = PROP(a, "molar_volume"), PROP(b, "molar_volume")
    pa, pb = PROP(a, "work_function_phi"), PROP(b, "work_function_phi")
    na, nb = PROP(a, "n_ws"), PROP(b, "n_ws")
    ka, gb = PROP(a, "bulk_modulus"), PROP(b, "shear_modulus")
    alpha = 1.5 * va ** (2 / 3) / (na ** (-1 / 3) + nb ** (-1 / 3))
    wa, wb = va + alpha * (pa - pb) / na, vb - alpha * (pa - pb) / nb
    return 10.0 * 2.0 * ka * gb * (wa - wb) ** 2 / (3.0 * ka * wb + 4.0 * gb * wa)


def surface(a, b, ca, cb):
    va, vb = PROP(a, "molar_volume") ** (2 / 3), PROP(b, "molar_volume") ** (2 / 3)
    return ca * va / (ca * va + cb * vb), cb * vb / (ca * va + cb * vb)


def king_phi(rule, comp):
    tot = sum(comp.values())
    c = {k: v / tot for k, v in comp.items()}
    h_ss = 0.0
    for i, xi in c.items():  # King S8, binary terms at the pair ratio
        for k, xk in c.items():
            if k == i:
                continue
            ca, cb = xi / (xi + xk), xk / (xi + xk)
            sa, sb = surface(i, k, ca, cb)
            chem = ca * cb * (sb * h_inter(rule, i, k) + sa * h_inter(rule, k, i))
            el = ca * cb * (cb * h_elastic(i, k) + ca * h_elastic(k, i))
            h_ss += xi * (xk / (1 - xi)) * (chem + el)
    pairs = []
    for a, b in itertools.combinations(c, 2):  # Bakker Eq. 9 / King S9-S10, both directions averaged
        ca, cb = c[a] / (c[a] + c[b]), c[b] / (c[a] + c[b])
        sa, sb = surface(a, b, ca, cb)
        order = 1 + 8 * (sa * sb) ** 2
        pairs.append(0.5 * (ca * sb * order * h_inter(rule, a, b) + cb * sa * order * h_inter(rule, b, a)))
    tm = sum(x * PROP(k, "melting_point") for k, x in c.items())
    dsmix = -R * sum(x * math.log(x) for x in c.values())
    dg_max = max(pairs, key=abs) * max(1, len(c) // 2)
    return (h_ss - tm * dsmix / 1000.0) / (-abs(dg_max))


def test_rederivation_reproduces_the_recorded_pre_correction_camgal_value():
    # parity_pre_fix.json / former test_m8_support.PINNED: CaMgAl Phi = 0.9710296979039487 (MP)
    assert king_phi(pre_correction_rule, parse_formula("CaMgAl")) == pytest.approx(0.9710296979039487, rel=1e-12)


ALLOYS = ["CaMgAl", "Ca65Mg15Zn20", "CaMgZn", "Ca50Mg20Cu30", "Al85Ca10Ni5", "AlCaMgZnLi", "BaCaMgZnAl",
          "SrMgAl", "BaZn", "CaFe", "Ca20Ni80"]  # at most one transition metal each (no structural term)


@pytest.mark.parametrize("formula", ALLOYS)
def test_engine_m8_equals_the_source_rule_rederivation(formula):
    comp = parse_formula(formula)
    phi = king_phi(source_rule, comp)
    res = ENGINE.calculate(comp)
    assert res.descriptors["phi_king"] == pytest.approx(phi, rel=1e-10)
    assert res.models["M8"].label == ("SS" if phi >= 1 else "MP")


def test_the_correction_moves_camgal_by_the_rule_change_alone():
    old, new = king_phi(pre_correction_rule, parse_formula("CaMgAl")), king_phi(source_rule, parse_formula("CaMgAl"))
    assert abs(old - new) > 0.3  # the R term of Ca-Al / Ca-Mg and a = 0.10: not a rounding effect
