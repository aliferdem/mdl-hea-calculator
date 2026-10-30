"""M5 (Ye et al. 2015): MCSL excess entropy S_E at equal and nearly equal atomic diameters (audit section 19).

Every expected value here comes from the MCSL equations of Ye et al., Intermetallics 59 (2015) 75, Appendix
(Mansoori et al., J. Chem. Phys. 54 (1971) 1523) by analysis, never from engine output:

* Equal diameters: Delta_ij = 0, so y1 = y2 = 0, and xi_i/xi = x_i, so y3 = (sum x_i)^3 = 1.  Z is then the
  one-component Carnahan-Starling Z and S_E/kB = -3 + 2/(1-xi) + 1/(1-xi)^2 - (3-2xi)/(1-xi)^2 + 3 = 0 identically,
  at every packing fraction, for any number of components and any composition.
* Species of identical diameter merge exactly: Delta_ij sqrt-weights, y1, y2 and y3 are linear in the fractions of
  equal-diameter species, so splitting one species into two of the same size changes nothing.
* Nearly equal diameters d_i = d(1 + eps_i): y1 = 2V, y2 = V, y3 = 1 - 3V + O(eps^3) with V = sum x_i eps_i^2 -
  (sum x_i eps_i)^2, giving S_E/kB = A(xi) V with
  A(xi) = 6 - 3/(1-xi) - 3/(1-xi)^2 - 3 ln(1-xi) + 3 xi (2 + xi - xi^2)/(1 + xi + xi^2 - xi^3) < 0.
  V = (delta/100)^2 to the same order, so S_E is second order in the size misfit and strictly negative.
  (Checked against a 60-digit evaluation of the full equations: docs/analysis-redesign/scripts/m5_se_stability.py.)
"""

import math

import pytest

from hea_calc.core.composition import parse_formula
from hea_calc.core.engine import NA, NA_MISSING_DATA, NA_UNDEFINED, R

XIS = (0.68, 0.74)  # Ye et al. 2015: bcc and fcc packing, S_E averaged over both


def _a(xi):
    return (6 - 3 / (1 - xi) - 3 / (1 - xi) ** 2 - 3 * math.log(1 - xi)
            + 3 * xi * (2 + xi - xi * xi) / (1 + xi + xi * xi - xi ** 3))


A_MEAN = sum(_a(xi) for xi in XIS) / 2


def _second_order_se(comp, radii):
    s = sum(comp.values())
    x = {e: v / s for e, v in comp.items()}
    r_bar = sum(x[e] * radii[e] for e in x)
    v = sum(x[e] * (radii[e] / r_bar - 1) ** 2 for e in x)  # = (delta/100)^2, Yang & Zhang definition
    return R * A_MEAN * v


def test_second_order_coefficient_is_negative_at_both_packings():
    assert _a(0.68) == pytest.approx(-26.7787, abs=1e-4)
    assert _a(0.74) == pytest.approx(-43.2903, abs=1e-4)


# --------------------------------------------------------------------------- exactly equal diameters
@pytest.mark.parametrize("comp", [
    {"A": 0.5, "B": 0.5}, {"A": 0.3, "B": 0.7}, {"A": 0.1, "B": 0.9}, {"A": 0.2, "B": 0.3, "C": 0.5},
    {"A": 0.1, "B": 0.2, "C": 0.3, "D": 0.4}, {e: 1 / 7 for e in "ABCDEFG"},
])
@pytest.mark.parametrize("r0", [111.0, 135.0, 164.0, 181.0, 124.12])
def test_equal_diameters_give_exactly_zero_excess_entropy(engine, comp, r0):
    assert engine._excess_entropy(comp, {e: r0 for e in comp}) == 0.0


@pytest.mark.parametrize("formula", ["NdPu", "Nd0.3Pu0.7", "Nd0.1Pu0.9", "Nd0.9Pu0.1", "Nd0.37Pu0.63"])
def test_nd_pu_equal_radii_s_e_zero_and_m5_undefined(engine, formula):
    """Nd and Pu both hold 164 pm (Guo & Liu Table 1; Pu supplementary) and have Takeuchi-Inoue data, so phi is
    reached: S_E = 0 makes phi = (S_c - S_H)/|S_E| undefined, which must be N/A (undefined), never SS."""
    res = engine.calculate(parse_formula(formula))
    d = res.descriptors
    assert d["delta"] == 0.0
    assert d["dhmix"] is not None and d["tm"]
    assert d["s_e"] == 0.0
    assert d["phi_ye"] is None
    m5 = res.models["M5"]
    assert m5.label == NA
    assert m5.na_kind == NA_UNDEFINED
    assert m5.reason == d["phi_ye_undefined"]
    assert "S_E = 0" in m5.reason
    # M4 is undefined for the same reason (delta = 0); unchanged
    assert res.models["M4"].label == NA and res.models["M4"].na_kind == NA_UNDEFINED


@pytest.mark.parametrize("els", [("Sm", "Am"), ("Tm", "Np"), ("Mn", "Nh"), ("Hg", "Rf", "Lv"), ("Br", "Ac")])
def test_other_equal_radius_sets_s_e_zero_and_m5_missing_data(engine, els):
    """No Takeuchi-Inoue pair for these: M5 stays N/A for missing data (that reason takes precedence)."""
    res = engine.calculate({e: 1 for e in els})
    assert len({engine.data.prop(e, "atomic_radius") for e in els}) == 1
    assert res.descriptors["s_e"] == 0.0
    assert res.descriptors["dhmix"] is None
    assert res.models["M5"].label == NA and res.models["M5"].na_kind == NA_MISSING_DATA


def test_s_e_is_never_positive_for_equal_or_distinct_radii(engine):
    """MCSL S_E <= 0 (Ye 2015: 'S_E is negative in sign'); the old float residual was +1.1e-14 for some Nd-Pu."""
    for k in range(1, 100):
        x = k / 100
        assert engine.calculate({"Nd": x, "Pu": 1 - x}).descriptors["s_e"] == 0.0
        assert engine.calculate({"Gd": x, "Y": 1 - x}).descriptors["s_e"] < 0.0


# --------------------------------------------------------------------------- merging identical species
@pytest.mark.parametrize("split,merged", [
    ({"Nd": 0.3, "Pu": 0.2, "Fe": 0.5}, {"Nd": 0.5, "Fe": 0.5}),
    ({"Nd": 0.1, "Pu": 0.15, "Co": 0.25, "Cr": 0.25, "Ni": 0.25}, {"Pu": 0.25, "Co": 0.25, "Cr": 0.25, "Ni": 0.25}),
])
def test_equal_diameter_species_merge_exactly(engine, split, merged):
    """A partial equal-radius subset is a legitimate mixture: S_E is finite and equals that of the merged species."""
    a = engine.calculate(split).descriptors
    b = engine.calculate(merged).descriptors
    assert a["s_e"] < 0
    assert a["s_e"] == pytest.approx(b["s_e"], rel=1e-12)
    assert a["phi_ye"] is not None


# --------------------------------------------------------------------------- nearly equal diameters
SHAPES = {
    "binary 50/50": ({"A": 0.5, "B": 0.5}, {"A": 0.0, "B": 1.0}),
    "binary 10/90": ({"A": 0.1, "B": 0.9}, {"A": 0.0, "B": 1.0}),
    "ternary": ({"A": 0.2, "B": 0.3, "C": 0.5}, {"A": -1.0, "B": 0.5, "C": 1.0}),
    "quinary": ({e: 0.2 for e in "ABCDE"}, {"A": -1.0, "B": -0.3, "C": 0.2, "D": 0.6, "E": 1.0}),
}


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("eps", [1e-3, 1e-4, 1e-5])
def test_nearly_equal_diameters_follow_the_second_order_limit(engine, shape, eps):
    """Small but legitimate: S_E -> R * A * (delta/100)^2 with a relative O(eps) correction; never zeroed."""
    comp, u = SHAPES[shape]
    radii = {e: 150.0 * (1 + eps * u[e]) for e in comp}
    se = engine._excess_entropy(comp, radii)
    assert se < 0.0
    assert se == pytest.approx(_second_order_se(comp, radii), rel=5 * eps)


@pytest.mark.parametrize("x_gd", [0.5, 0.1, 0.01, 0.001])
def test_smallest_real_radius_gap_keeps_a_finite_phi(engine, x_gd):
    """Gd-Y differ by 0.1 pm (180.1 / 180.2, printed Guo & Liu values since F2, section 20; 0.02 pm before): the
    smallest non-zero gap among the 73 Takeuchi-Inoue elements, shared with Bi-Mg, Fe-Ge and Gd-Th.  S_E is small but
    legitimate, so phi stays finite and M5 classifies."""
    comp = {"Gd": x_gd, "Y": 1 - x_gd}
    res = engine.calculate(comp)
    d = res.descriptors
    radii = {e: engine.data.prop(e, "atomic_radius") for e in comp}
    assert radii["Gd"] != radii["Y"]
    assert d["s_e"] < 0.0
    assert d["s_e"] == pytest.approx(_second_order_se(comp, radii), rel=1e-3)
    assert d["phi_ye"] is not None and math.isfinite(d["phi_ye"])
    assert res.models["M5"].label != NA
