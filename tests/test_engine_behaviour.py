"""Engine behaviour: input validation, missing data, normalisation, thresholds."""

import math

import pytest

from hea_calc.core.engine import AlloyResult, MODEL_KEYS, NA, Engine


def test_invalid_inputs(engine):
    assert engine.calculate({}).error
    assert "Unknown element" in engine.calculate({"Xx": 1, "Fe": 1}).error
    assert engine.calculate({"Fe": -1, "Co": 1}).error
    assert engine.calculate({"Fe": 0, "Co": 0}).error
    assert "two elements" in engine.calculate({"Fe": 1}).error
    assert "two elements" in engine.calculate({"Fe": 1, "Co": 0}).error
    assert engine.calculate({"Fe": "abc", "Co": 1}).error
    assert engine.calculate({"Fe": float("nan"), "Co": 1}).error


def test_normalisation_invariance(engine):
    a = engine.calculate({"Al": 0.5, "Co": 1, "Cr": 1, "Fe": 1, "Ni": 1})
    b = engine.calculate({"Al": 11.111111111, "Co": 22.222222222, "Cr": 22.222222222, "Fe": 22.222222222,
                          "Ni": 22.222222222})
    c = engine.calculate({"Al": 1, "Co": 2, "Cr": 2, "Fe": 2, "Ni": 2})
    for key in ("dhmix", "delta", "delta_cn12", "omega", "phi_ye", "phi_king", "dhim", "tm", "density"):
        assert a.descriptors[key] == pytest.approx(b.descriptors[key], rel=1e-8)
        assert a.descriptors[key] == pytest.approx(c.descriptors[key], rel=1e-12)
    assert sum(a.composition.values()) == pytest.approx(1.0)


def test_equiatomic_basic_descriptors(engine):
    d = engine.calculate({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}).descriptors
    assert d["dsmix"] == pytest.approx(8.314462618 * math.log(4))
    assert d["dhmix"] == pytest.approx(-3.75)  # 4·(1/16)·(-4-1+0-1-7-2)
    assert d["vec"] == pytest.approx((9 + 6 + 8 + 10) / 4)
    assert d["cstr"] == "FCC"
    assert d["tm"] == pytest.approx((1768 + 2180 + 1811 + 1728) / 4)


def test_binary_and_physical_zero_mixing(engine):
    # Takeuchi & Inoue define H/C/N-containing pairs as exactly 0 kJ/mol.  That is a tabulated
    # VALUE, not missing data, so dHmix is 0.0 and the pair is not reported as missing.  Omega is
    # then mathematically divergent, so it is reported as unavailable with a reason instead of as
    # +inf, which would read as an unusually good solid solution.  M1 needs Omega, so it is N/A.
    res = engine.calculate({"Fe": 1, "Mn": 1})
    d = res.descriptors
    assert d["dhmix"] == 0.0
    assert d["omega"] is None
    assert d["omega_undefined"] and "undefined" in d["omega_undefined"]
    assert res.label("M1") == NA
    assert res.models["M1"].reason == d["omega_undefined"]
    assert not d["missing_mixing_pairs"]
    # A tabulated zero is still a real value for every model that does not divide by dHmix.
    assert res.label("M4") != NA and res.label("M3") != NA


def test_missing_mixing_pair_only_affects_dependent_models(engine):
    res = engine.calculate({"Fe": 1, "Co": 1, "Og": 1})  # Og: no Takeuchi data
    assert res.ok
    d = res.descriptors
    assert d["dhmix"] is None and d["omega"] is None
    assert d["missing_mixing_pairs"]
    for key in ("M1", "M2", "M5"):
        assert res.label(key) == NA
        assert "ΔHmix" in res.models[key].reason
    assert res.label("M7") == NA  # also lacks Troparevsky data
    assert res.label("M3") != NA and res.label("M4") != NA


def test_missing_formation_pair_gives_na_for_m6_m7(engine):
    res = engine.calculate({"Al": 1, "Co": 1, "Cu": 1, "Fe": 1, "Ni": 1, "Si": 1})
    assert res.label("M6") == NA and res.label("M7") == NA
    assert "Si" in res.models["M6"].reason
    assert res.label("M8") != NA


def test_missing_miedema_data_gives_na_for_m8(engine):
    res = engine.calculate({"Fe": 1, "Co": 1, "Nd": 1})
    assert res.label("M8") == NA


def test_supplementary_radius_warning(engine):
    res = engine.calculate({"Fe": 1, "Hg": 1})
    assert any("Hg" in w for w in res.warnings)
    assert res.models["M3"].caution


def test_all_models_present_and_labels_valid(engine):
    res = engine.calculate({"Cr": 1, "Mn": 1, "Fe": 1, "Co": 1, "Ni": 1, "Mo": 1, "Ti": 1})
    assert set(res.models) == set(MODEL_KEYS)
    for o in res.models.values():
        assert o.label in {"SS", "MP", "IM", "SS+IM", "MG", "N/A"}


def test_temperature_policy(engine):
    r = engine.calculate({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1})
    assert r.temperature == pytest.approx(0.55 * r.descriptors["tm"])
    assert "0.55" in r.temperature_source
    r2 = engine.calculate({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1}, annealing_temperature=1273)
    assert r2.temperature == 1273 and "user" in r2.temperature_source


def _judge(engine, **desc):
    base = dict(dhmix=-5.0, delta=3.0, delta_cn12=3.0, omega=2.0, gamma=1.1, lambda_=1.0, phi_ye=30.0,
                missing_formation_pairs=[], hf_min=-50.0, hf_max=10.0, hf_lower=-100.0, dhim=-6.0, k1=1.2,
                k1cr=2.0, phi_king=1.2, dg_ss=-20.0, dg_max=-10.0, dsmix=13.38, s_e=-0.1)
    base.update(desc)
    base["lambda"] = base.pop("lambda_")
    res = AlloyResult(composition={"Fe": 0.5, "Co": 0.5}, descriptors=base, temperature=1000.0)
    engine._models(res)
    return res


def test_threshold_boundaries_inclusive_exclusive(engine):
    # Yang & Zhang: Omega >= 1.1 and delta <= 6.6 (inclusive; CoCrFeNiAl3 Omega = 1.10 is SS in Table 1)
    assert _judge(engine, omega=1.1, delta_cn12=6.6).label("M1") == "SS"
    assert _judge(engine, omega=1.0999, delta_cn12=6.6).label("M1") == "MP"
    # Guo: -11.6 <= dHmix <= 3.2, delta <= 6.6 (Table 1 lists SS alloys exactly at -11.60 and 3.20)
    assert _judge(engine, dhmix=3.2, delta=6.6).label("M2") == "SS"
    assert _judge(engine, dhmix=-11.6).label("M2") == "SS"
    assert _judge(engine, dhmix=3.21).label("M2") == "MP"
    assert _judge(engine, dhmix=-12.3, delta=6.5).label("M2") == "MG"
    assert _judge(engine, dhmix=-12.2, delta=6.5).label("M2") == "MP"  # strict for amorphous
    # Wang: gamma < 1.175 (strict)
    assert _judge(engine, gamma=1.175).label("M3") == "MP"
    assert _judge(engine, gamma=1.1749).label("M3") == "SS"
    # Singh: SS > 0.96, SS+IM in [0.24, 0.96], IM < 0.24
    assert _judge(engine, lambda_=0.96).label("M4") == "SS+IM"
    assert _judge(engine, lambda_=0.9601).label("M4") == "SS"
    assert _judge(engine, lambda_=0.24).label("M4") == "SS+IM"
    assert _judge(engine, lambda_=0.2399).label("M4") == "IM"
    # Ye: phi >= 20
    assert _judge(engine, phi_ye=20.0).label("M5") == "SS"
    assert _judge(engine, phi_ye=19.99).label("M5") == "MP"
    # Troparevsky: strict window
    assert _judge(engine, hf_min=-100.0).label("M6") == "IM"
    assert _judge(engine, hf_min=-99.9).label("M6") == "SS"
    assert _judge(engine, hf_max=37.0).label("M6") == "MP"
    assert _judge(engine, hf_max=36.9).label("M6") == "SS"
    # King (2016) Section 3.1: Phi >= 1, and nothing else.  The d <= 6.6 % screen is Section 3.4's
    # candidate-generation filter, so a Phi success must survive any delta - and M8 must not need
    # a Kittel CN12 radius at all.
    assert _judge(engine, phi_king=1.0).label("M8") == "SS"
    assert _judge(engine, phi_king=0.999).label("M8") == "MP"
    assert _judge(engine, phi_king=1.5, delta_cn12=12.0).label("M8") == "SS"
    assert _judge(engine, phi_king=1.0, delta_cn12=None).label("M8") == "SS"
    # CrMnNbTaW (Phi 1.467, dCN12 6.61) and CrMnTiVSc (Phi 1.110, dCN12 10.00) are exactly these cases.


def test_senkov_miracle_equation_6_both_signs(engine):
    # dHmix < 0: equivalent to k1 < k1cr
    r = _judge(engine, dhmix=-5.0, dhim=-6.0)
    ts = 1000 * 13.38 / 1000
    assert (r.label("M7") == "SS") == (-5.0 - ts < -6.0 - 0.6 * ts)
    # dHmix > 0 with a positive dH_IM: intermetallic cannot compete -> SS (Eq. 6 evaluated directly)
    assert _judge(engine, dhmix=2.0, dhim=10.0).label("M7") == "SS"


def test_structural_term_only_for_transition_pairs(engine):
    assert engine._structural("Al", "Ni", 0.5, 0.5) == 0.0
    assert engine._structural("Cu", "Ni", 0.5, 0.5) == 0.0
    assert engine._structural("Cr", "Ni", 0.5, 0.5) != 0.0


def test_model_support(engine):
    s = engine.model_support("Fe")
    assert s["M1"][0] == "ok" and s["M6"][0] == "pair" and s["M8"][0] == "ok"
    s = engine.model_support("Si")
    assert s["M6"][0] == "none"
    s = engine.model_support("Hg")
    assert s["M3"][0] == "warn"
    s = engine.model_support("Og")
    assert s["M1"][0] == "none" and s["M8"][0] == "none"


def test_engine_is_deterministic_and_cached():
    e = Engine()
    a = e.calculate({"Al": 1, "Ni": 1}).descriptors["phi_king"]
    b = e.calculate({"Ni": 1, "Al": 1}).descriptors["phi_king"]
    assert a == pytest.approx(b)
