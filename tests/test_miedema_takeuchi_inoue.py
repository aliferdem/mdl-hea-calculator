"""Miedema classification of Ca, Sr and Ba against Takeuchi & Inoue (2005) Tables 1-2 (audit M8-AE).

Takeuchi & Inoue print Miedema liquid mixing enthalpies at the equiatomic composition, computed after de Boer et al.
(1988) - the only printed Miedema values for Ca/Sr/Ba with non-transition metals (no de Boer or Bakker table has
them).  The engine evaluates solids only, so the liquid formula is written out here from the printed equations
(de Boer et al. 1988):

* statistically ordered liquid: dH = c_A f_B^A dH_inter(A in B), f_B^A = c_B^s            (Eqs. 2.26-2.27)
* surface concentrations from V^{2/3} with the volume correction [1 + a f_B^A (phi_A - phi_B)] (Eqs. 2.32-2.33)
* R_liquid = 0.73 R_solid                                                                   (Eq. 2.39)

and fed with the engine's P, Q, R (``_pqr``), volume coefficient and elemental data: what is tested is the
classification, against printed numbers.  Pairs with H, B, C, N, P, Si, Ge are skipped (Takeuchi & Inoue subtracted
a dH_trans term from them).
"""

import pytest

from hea_calc.core.engine import _MIED_TRANSITION, Engine

ENGINE = Engine()
DATA = ENGINE.data
AE = ("Ca", "Sr", "Ba")
SKIP = {"H", "B", "C", "N", "P", "Si", "Ge"}
PARTNERS = sorted(e for e in DATA.mixing_elements if e not in SKIP and ENGINE.miedema_available(e))


def liquid_equiatomic(a, b):
    prop = DATA.prop
    pa, ra, aa = ENGINE._pqr(a, b)[0], ENGINE._pqr(a, b)[2], ENGINE._volume_coefficient(a)
    ab = ENGINE._volume_coefficient(b)
    phia, phib = prop(a, "work_function_phi"), prop(b, "work_function_phi")
    na, nb = prop(a, "n_ws"), prop(b, "n_ws")
    va, vb = prop(a, "molar_volume") ** (2 / 3), prop(b, "molar_volume") ** (2 / 3)
    csa = va / (va + vb)
    for _ in range(60):
        va_al = va * (1 + aa * (1 - csa) * (phia - phib))
        vb_al = vb * (1 + ab * csa * (phib - phia))
        csa = va_al / (va_al + vb_al)
    den = 0.5 * (na ** (-1 / 3) + nb ** (-1 / 3))
    inter = va_al / den * (-pa * (phia - phib) ** 2 + 9.4 * pa * (na ** (1 / 3) - nb ** (1 / 3)) ** 2 - 0.73 * ra)
    return 0.5 * (1 - csa) * inter


def residuals(x, select):
    out = []
    for b in PARTNERS:
        if b != x and select(b):
            out.append((b, liquid_equiatomic(x, b) - DATA.mixing_enthalpy(x, b)))
    return out


def test_partner_set_is_the_expected_one():
    assert len(PARTNERS) == 52  # 30 transition metals, 19 non-transition metals, Ca, Sr, Ba
    assert sum(b in _MIED_TRANSITION for b in PARTNERS) == 30


@pytest.mark.parametrize("x", AE)
def test_ca_sr_ba_with_transition_metals(x):
    res = residuals(x, lambda b: b in _MIED_TRANSITION)
    assert len(res) == 30
    assert max(abs(d) for _b, d in res) <= 2.0, res


@pytest.mark.parametrize("x", ["Ca", "Sr"])
def test_ca_sr_with_non_transition_metals(x):
    res = residuals(x, lambda b: b not in _MIED_TRANSITION)
    assert len(res) == 21  # 19 non-transition metals and the two other alkaline-earth metals
    assert max(abs(d) for _b, d in res) <= 2.0, res


def test_ba_with_non_transition_metals_is_a_known_discrepancy():
    """Takeuchi & Inoue's Ba / non-transition rows sit ~2 kJ/mol less negative than Fig. 2.28's factor 0.4 gives
    (they behave like 0.5; Ca and Sr in the same table fit 0.4).  The printed factor is kept; this test fails if the
    offset disappears or grows, so the discrepancy stays visible."""
    res = [(b, d) for b, d in residuals("Ba", lambda b: b not in _MIED_TRANSITION) if b not in AE]
    assert len(res) == 19
    mean = sum(d for _b, d in res) / len(res)
    assert 1.0 < mean < 3.0, mean
    assert max(abs(d) for _b, d in res) <= 5.0, res
