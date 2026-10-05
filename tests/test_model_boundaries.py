"""Scientific regression tests for the criteria reconciled with the independent audit.

Each test names the publication clause it pins.  Two rules govern everything here:

* **A published criterion is exactly what the source prints.** Where the source is ambiguous the
  project convention is recorded in ``CALCULATION_AUDIT.md`` and pinned as such, not smuggled in.
* **Representation noise must never decide a scientific result class**, and nothing coarser than
  that may be used to avoid it.  ``engine.THRESHOLD_REL_TOL`` is 1e-12 relative; a difference of a
  single printed digit still flips the verdict, which is asserted below for every threshold.
"""

import math

import pytest

from hea_calc.core.composition import parse_formula
from hea_calc.core.engine import (
    MP, NA, SS, SS_IM, STATUS_DATA_SUSPECT, STATUS_EXTRAPOLATED, STATUS_IN_DOMAIN,
    THRESHOLD_REL_TOL, AlloyResult, Engine, MODELS,
)

ENGINE = Engine()
DATA = ENGINE.data


def calc(formula, **kw):
    return ENGINE.calculate(parse_formula(formula), **kw)


def judge(**descriptors):
    """Run ``Engine._models`` over a synthetic descriptor set, as the app's own tests do."""
    base = dict(dhmix=-5.0, delta=3.0, delta_cn12=3.0, omega=2.0, gamma=1.1, lambda_=1.0,
                phi_ye=30.0, missing_formation_pairs=[], hf_min=-50.0, hf_max=10.0,
                hf_lower=-100.0, dhim=-6.0, k1=1.2, k1cr=2.0, phi_king=1.2, dg_ss=-20.0,
                dg_max=-10.0, dsmix=13.38, s_e=-0.1, formation_asymmetric_pairs=[],
                formation_suspect_pairs=[], formation_suspect_values={})
    base.update(descriptors)
    base["lambda"] = base.pop("lambda_")
    res = AlloyResult(composition={"Fe": 0.5, "Co": 0.5}, descriptors=base, temperature=1000.0)
    ENGINE._models(res)
    return res


# ======================================================================================
# M8 - King et al. (2016): the criterion is Phi >= 1 and nothing else
# ======================================================================================
# King Section 3.1 states the solid-solution region as Phi >= 1.  The d <= 6.6 % screen belongs to
# Section 3.4, which describes HOW CANDIDATE ALLOYS ARE GENERATED, and King keeps NbTiV2Zr - the
# "only system that has both Phi > 1 and d > 6.6" - inside the success set.  Applying the screen as
# a second AND-term therefore demotes alloys the publication counts as successes.


def test_m8_criterion_is_phi_alone():
    assert judge(phi_king=1.0).label("M8") == SS
    assert judge(phi_king=0.999).label("M8") == MP


@pytest.mark.parametrize("delta_cn12", [0.0, 4.9, 6.61, 9.998, 12.0, 20.0])
def test_m8_verdict_is_independent_of_delta(delta_cn12):
    """CrMnNbTaW (Phi 1.467, d 6.61) and CrMnTiVSc (Phi 1.110, d 10.00) are exactly these cases."""
    assert judge(phi_king=1.4, delta_cn12=delta_cn12).label("M8") == SS


def test_m8_does_not_require_a_cn12_radius():
    """M8 must not need delta_CN12 at all - it is not part of the criterion."""
    assert judge(phi_king=1.2, delta_cn12=None).label("M8") == SS


def test_m8_published_worked_examples():
    """King et al. 2016 supplementary worked examples, recomputed from the app's own engine."""
    for formula, expected in (("CoCrFeNiMn", 1.1016), ("NbMoTaW", 1.7317), ("VNbMoTaW", 1.7386)):
        assert calc(formula).descriptors["phi_king"] == pytest.approx(expected, rel=0.01), formula


def test_m8_refractory_alloys_with_wide_delta_are_solid_solutions():
    for formula in ("CrMnNbTaW", "CrMnTiNbTa", "CrMnTiVSc"):
        res = calc(formula)
        assert res.descriptors["phi_king"] >= 1.0
        assert res.descriptors["delta_cn12"] > 6.6        # the screen King does not apply
        assert res.label("M8") == SS


def test_m8_criterion_text_matches_the_publication():
    text = MODELS["M8"].criterion
    assert "3.4" in text and "candidate-generation" in text
    assert "and \u03b4" not in text.split("otherwise")[0]        # no delta conjunct in the rule


def test_m8_delta_g_max_keeps_its_sign():
    assert calc("Co0.43Cr1Fe7Ni49").descriptors["dg_max"] < 0.0
    assert calc("FeCoNiCrCu").descriptors["dg_max"] > 0.0


# ======================================================================================
# Threshold comparison: representation noise is absorbed, nothing coarser is
# ======================================================================================


def test_threshold_tolerance_is_negligible():
    """One ULP of noise is absorbed; a single printed digit is not."""
    assert THRESHOLD_REL_TOL <= 1e-11
    # 3.2 + one ULP (what the Cantor alloy actually computes) is inside the tolerance ...
    value = 3.2 + math.ulp(3.2)
    assert abs(value - 3.2) <= abs(3.2) * THRESHOLD_REL_TOL
    # ... but a thousand ULPs, let alone a hundredth of a kJ/mol, is not.
    assert abs(3.2 + 1e4 * math.ulp(3.2) - 3.2) > abs(3.2) * THRESHOLD_REL_TOL
    assert judge(dhmix=3.21, delta=6.6).label("M2") == MP


@pytest.mark.parametrize("value,expected", [
    (3.2, SS),                 # Yang & Zhang 7.36 / Guo Table 1 "SS"
    (3.2 + math.ulp(3.2), SS),  # the value the engine actually computes
    (3.2 + 1e-13, SS),          # still representation noise at 4 significant figures
    (3.2 + 0.01, MP),           # a hundredth of a kJ/mol is a real difference
])
def test_m2_window_edge_is_stable_against_representation_noise(value, expected):
    assert judge(dhmix=value, delta=6.6).label("M2") == expected


def test_cantor_alloy_is_a_solid_solution_in_m2():
    """The most-cited HEA in the literature: Guo 2013 Table 1 lists it as SS."""
    res = calc("CoCrFeNiCu")
    assert res.descriptors["dhmix"] == pytest.approx(3.20, abs=0.02)
    assert res.label("M2") == SS


@pytest.mark.parametrize("kwargs,expected", [
    (dict(phi_king=1.0), SS),                    # King 3.1, inclusive
    (dict(phi_king=1.0 - 1e-13), SS),            # representation noise
    (dict(phi_king=1.0 - 1e-3), MP),             # a real difference
])
def test_m8_phi_edge(kwargs, expected):
    assert judge(**kwargs).label("M8") == expected


# ======================================================================================
# Divergent descriptors are unavailable with a reason, never +inf
# ======================================================================================
# Takeuchi & Inoue 2005 define H/C/N-containing pairs as exactly 0 kJ/mol.  Omega = Tm*dS/|dHmix| is
# then mathematically divergent.  Reporting +inf would read as an unusually good solid solution,
# which is not what a vanishing denominator means.


def test_omega_is_undefined_not_infinite_when_dhmix_is_zero():
    res = calc("AlB")                       # Al-B is a tabulated 0 kJ/mol pair
    assert res.descriptors["dhmix"] == 0.0
    assert res.descriptors["omega"] is None
    assert res.descriptors["omega_undefined"]
    assert res.label("M1") == NA
    assert res.models["M1"].reason == res.descriptors["omega_undefined"]


def test_a_tabulated_zero_is_a_value_not_missing_data():
    res = calc("FeMn")                      # Fe-Mn is also tabulated as 0 kJ/mol
    assert res.descriptors["dhmix"] == 0.0
    assert not res.descriptors["missing_mixing_pairs"]
    # Models that do not divide by dHmix are unaffected.
    assert res.label("M3") != NA and res.label("M4") != NA


def test_no_descriptor_is_ever_infinite():
    import itertools
    pool = ["Co", "Cr", "Fe", "Ni", "Cu", "Mn", "Al", "Ti", "V", "Nb", "Zr", "B", "H"]
    for n in (2, 3, 4):
        for combo in itertools.islice(itertools.combinations(pool, n), 0, 120):
            res = ENGINE.calculate({e: 1 for e in combo})
            for key, value in res.descriptors.items():
                if isinstance(value, float):
                    assert math.isfinite(value), f"{key} infinite for {''.join(combo)}"


def test_undefined_descriptors_carry_a_reason_the_model_surfaces():
    res = calc("AlB")
    for key, model in (("omega_undefined", "M1"),):
        assert res.models[model].reason == res.descriptors[key]


# ======================================================================================
# M7 - Senkov & Miracle: the criterion's stated domain is made explicit
# ======================================================================================
# Section 1.1 assumes the linear relations hold "for HEAs with negative values of dHmix".  Outside
# that domain the verdict is an extrapolation and must be labelled as one, not presented as a
# literature-defined prediction.


@pytest.mark.parametrize("formula,anneal", [("Cu0.5CoCrFeNi", 1273), ("HfNbTaTiZr", 1473),
                                           ("CoCrCuFeMn", 1123)])
def test_m7_positive_dhmix_is_flagged_as_an_extrapolation(formula, anneal):
    res = calc(formula, annealing_temperature=anneal)
    assert res.descriptors["dhmix"] > 0
    m7 = res.models["M7"]
    assert m7.status == STATUS_EXTRAPOLATED
    assert m7.caution
    assert "Extrapolation" in m7.caution
    assert "\u0394Hmix < 0" in m7.caution        # the paper's stated domain


def test_m7_negative_dhmix_is_in_domain():
    for formula in ("CoCrFeNiMn", "CrMnFeCoNi", "MoNbTaW", "AlCoCrFeNi"):
        assert calc(formula).models["M7"].status == STATUS_IN_DOMAIN


def test_m7_zero_dhmix_leaves_the_k1_form_undefined():
    res = calc("FeMn")          # Fe-Mn is tabulated as 0 kJ/mol and IS in the formation matrix
    assert res.descriptors["dhmix"] == 0.0
    assert res.label("M6") != NA
    assert res.descriptors["k1"] is None and res.descriptors["k1cr"] is None
    # ... and the verdict that is still produced says so explicitly.
    assert res.models["M7"].status == STATUS_EXTRAPOLATED
    assert "undefined" in (res.models["M7"].caution or "")


def test_m7_equation_6_is_evaluated_directly():
    """The sign-agnostic form of Eq. (6) is valid whenever both sides are defined."""
    r = judge(dhmix=-5.0, dhim=-6.0)
    ts = 1000 * 13.38 / 1000
    assert r.label("M7") == ("SS" if -5.0 - ts < -6.0 - 0.6 * ts else "IM")


# ======================================================================================
# M6/M7 - unreliable binary values are labelled, never replaced
# ======================================================================================


def test_dataset_declares_a_range_guard_and_provenance():
    dq = DATA.formation_metadata["data_quality"]
    assert dq["out_of_range_guard_mev"] == 700
    assert dq["publication_colour_scale_mev"] == [-500, 300]
    assert dq["guard_justification"]
    assert dq["verified_anchors_mev_per_atom"] == {"Al-Ni": -677.0, "Mo-Ta": -193.0, "Mn-Ni": -115.0}


def test_published_anchors_are_exact_and_symmetric():
    for a, b, expected in (("Al", "Ni", -677.0), ("Mo", "Ta", -193.0), ("Mn", "Ni", -115.0)):
        assert DATA.formation_enthalpy(a, b) == expected, f"{a}-{b} forward"
        assert DATA.formation_enthalpy(b, a) == expected, f"{a}-{b} reverse"


def test_suspect_cells_are_flagged_not_altered():
    suspect = DATA.formation_suspect_pairs()
    assert "Fe-Ta" in suspect and "Ta-Fe" in suspect
    assert "Al-Cd" in suspect
    # the value itself is untouched - it is still what the publication figure was read as
    assert DATA.formation_enthalpy("Fe", "Ta") == -3468.0


def test_suspect_cells_surface_on_the_affected_alloy():
    res = calc("FeTa")
    assert res.descriptors["formation_suspect_pairs"] == ["Fe-Ta"]  # input order is Fe, Ta
    assert res.descriptors["formation_suspect_values"]["Fe-Ta"] == -3468.0
    for key in ("M6", "M7"):
        assert res.models[key].status == STATUS_DATA_SUSPECT
        caution = res.models[key].caution or ""
        assert "unreliable" in caution and "Fe-Ta = -3468" in caution, caution


def test_clean_alloys_are_not_flagged():
    res = calc("CoCrFeNiMn")
    assert res.descriptors["formation_suspect_pairs"] == []
    for key in ("M6", "M7"):
        assert res.models[key].status == STATUS_IN_DOMAIN
        assert res.models[key].caution is None


def test_missing_pair_is_na_not_zero():
    res = calc("SiCoCrFeNi")
    assert res.descriptors["hf_min"] is None
    assert res.descriptors["formation_suspect_pairs"] == []
    for key in ("M6", "M7"):
        assert res.label(key) == NA
        assert res.models[key].reason


def test_matrix_can_be_replaced_without_touching_model_code():
    """No literal formation-enthalpy number may appear in engine.py or data.py."""
    from pathlib import Path
    import hea_calc.core.engine as eng
    for module in (eng, __import__("hea_calc.core.data", fromlist=["x"])):
        text = Path(module.__file__).read_text(encoding="utf-8")
        for literal in ("-3468", "-2505", "-1938", "-1252", "-1155", "-1101"):
            assert literal not in text, f"{literal} is hard-coded in {module.__name__}"


def test_m6_window_stays_strict_at_the_boundary():
    # Troparevsky: -T*dSmix < dHf < 37 meV/atom.  A cell exactly on a bound violates it.
    assert judge(hf_min=-100.0, hf_lower=-100.0).label("M6") == "IM"
    assert judge(hf_min=-99.9).label("M6") == SS
    assert judge(hf_max=37.0).label("M6") == "MP"
    assert judge(hf_max=36.9).label("M6") == SS


def test_cantor_alloy_is_a_solid_solution_in_m6_and_m7():
    res = calc("CoCrFeNiMn", annealing_temperature=1000)
    assert res.descriptors["hf_min"] == -115.0        # the Mn-Ni anchor
    assert res.descriptors["hf_max"] == 9.0
    assert res.label("M6") == SS and res.label("M7") == SS


# ======================================================================================
# M2 - Guo et al. (2013): the intermetallic region is honestly unresolved
# ======================================================================================
# Guo Fig. 1 defines three regions - solid solution, metallic glass, and an intermetallic region
# between them.  Only the first two are bounded numerically, so the third cannot be implemented
# without inventing boundaries.  The project therefore reports MP and SAYS SO.


@pytest.mark.parametrize("formula", ["Cu0.5NiAlCoCrFeSi", "CoCrCuFeNiZr0.6", "CoCrCuFeNiZr0.8"])
def test_m2_states_that_the_intermetallic_region_is_unresolved(formula):
    """Guo lists these alloys as intermetallic / amorphous; the published criteria cannot separate
    the intermetallic region from the surrounding ones, so M2 says so instead of guessing."""
    m2 = calc(formula).models["M2"]
    assert m2.label == MP
    assert m2.caution and "intermetallic" in m2.caution and "graphically" in m2.caution


@pytest.mark.parametrize("formula", ["CoCrFeNiTi", "AlCoCrFeNiTi1.5", "ZrTiVCuNiBe"])
def test_m2_amorphous_alloys_are_mg_by_the_published_criterion(formula):
    """Guo labels these intermetallic, but delta > 6.4 % with dHmix < -12.2 kJ/mol is the printed
    amorphous rule, so MG is the only class the published criteria support."""
    assert calc(formula).models["M2"].label == "MG"


def test_m2_printed_criteria_are_implemented_as_printed():
    # Section 4.1: dHmix < -12.2 kJ/mol with delta > 6.4 % gives the amorphous region, and both
    # signs are strict - so an alloy sitting exactly on -12.2 is NOT in it.
    assert judge(dhmix=-12.3, delta=6.5).label("M2") == "MG"
    assert judge(dhmix=-12.2, delta=6.5).label("M2") == "MP"     # strict
    assert judge(dhmix=3.2, delta=6.6).label("M2") == SS
    assert judge(dhmix=-11.6).label("M2") == SS
    assert judge(dhmix=3.21).label("M2") == MP
    assert judge(dhmix=-11.7).label("M2") == MP


def test_m2_cantor_alloy():
    res = calc("CoCrFeNiMn")
    assert res.descriptors["delta"] == pytest.approx(3.27, abs=0.06)
    assert res.descriptors["dhmix"] == pytest.approx(-4.16, abs=0.02)
    assert res.label("M2") == SS


# ======================================================================================
# Cross-cutting invariants the eight models depend on
# ======================================================================================


def test_dhmix_uses_four_times_the_unordered_pair_sum():
    """Yang & Zhang eq. (2); reproduces Guo Table 1 for the Cantor alloy."""
    import itertools
    amounts = parse_formula("CoCrFeNiMn")
    total = sum(amounts.values())
    c = {el: v / total for el, v in amounts.items()}
    acc = sum(c[a] * c[b] * DATA.mixing_enthalpy(a, b) for a, b in itertools.combinations(sorted(c), 2))
    assert calc("CoCrFeNiMn").descriptors["dhmix"] == pytest.approx(4 * acc, abs=1e-12)


def test_lambda_uses_delta_in_percent():
    d = calc("CoCrFeNiMn").descriptors
    assert d["lambda"] == pytest.approx(d["dsmix"] / d["delta"] ** 2, rel=1e-12)
    assert d["lambda"] == pytest.approx(1.2534, rel=0.02)      # Singh et al. 2014 Table 1
    assert d["lambda"] < 100                                    # a fraction would be ~1e5


def test_two_radius_sets_are_kept_separate():
    d = calc("CoCrFeNiMn").descriptors
    assert d["delta_cn12"] == pytest.approx(0.93, abs=0.06)     # Kittel CN12, Yang & Zhang
    assert d["delta"] == pytest.approx(3.27, abs=0.06)          # Guo & Liu 2011 Table 1
    assert calc("CoCrFeNi").descriptors["delta_cn12"] != calc("CoCrFeNi").descriptors["delta"]


@pytest.mark.parametrize("omega,expected", [(2.0, SS), (1.1, SS), (1.0999, MP)])
def test_m1_omega_edge(omega, expected):
    assert judge(omega=omega, delta_cn12=3.0).label("M1") == expected


@pytest.mark.parametrize("gamma,expected", [(1.1749, SS), (1.175, MP), (1.17499, SS)])
def test_m3_gamma_is_strict(gamma, expected):
    """Wang's 1.175 is empirical and is not 'improved'."""
    assert judge(gamma=gamma).label("M3") == expected


@pytest.mark.parametrize("lam,expected", [(0.96, SS_IM), (0.9601, SS), (0.24, SS_IM), (0.2399, "IM")])
def test_m4_lambda_edges(lam, expected):
    assert judge(lambda_=lam).label("M4") == expected


@pytest.mark.parametrize("phi,expected", [(20.0, SS), (19.99, MP)])
def test_m5_phi_edge(phi, expected):
    assert judge(phi_ye=phi).label("M5") == expected