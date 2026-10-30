"""M8 availability (``Engine.model_support``) must agree with M8 evaluation (CALCULATION_AUDIT.md §14).

M8 (King et al. 2016) is Phi >= 1 alone (F9): it reads no atomic radius.  Its data requirements are the Miedema
parameters and classification of every element and, for a transition / non-transition pair, both R/P factors.
The per-element indicator must report exactly that - no CN12 dependency, no relaxed Miedema requirement - and the
correction must not move a single calculated value.
"""

import itertools
import re
from pathlib import Path

import pytest

from hea_calc.core.composition import parse_formula
from hea_calc.core.engine import MODELS, MP, NA, NA_MISSING_DATA, SS, Engine

ENGINE = Engine()
DATA = ENGINE.data
ROOT = Path(__file__).resolve().parents[1]


def calc(formula):
    return ENGINE.calculate(parse_formula(formula))


def m8_status(el):
    return ENGINE.model_support(el)["M8"][0]


# ------------------------------------------------------------------ 1. CN12 is not an M8 requirement
def test_m8_support_is_not_disabled_by_a_missing_cn12_radius():
    affected = [el for el in DATA.elements
                if ENGINE.miedema_available(el) and DATA.prop(el, "atomic_radius_cn12") is None]
    assert affected == ["P"]            # the only element in the dataset with Miedema data and no CN12 radius
    for el in affected:
        assert m8_status(el) == "ok", el


# ------------------------------------------------------------------ 2. phosphorus: indicator == calculation
@pytest.mark.parametrize("formula", ["FeNiP0.2", "NiP0.25", "CoCrFeNiP0.1"])
def test_phosphorus_alloys_report_m8_availability_consistently(formula):
    res = calc(formula)
    assert res.models["M8"].label != NA                     # M8 is evaluated ...
    assert m8_status("P") == "ok"                           # ... and the indicator says so
    assert ENGINE.model_coverage(list(res.composition))["M8"] is None
    # M1 genuinely needs the CN12 radius: still unavailable, and the indicator still says so.
    assert res.models["M1"].label == NA
    assert ENGINE.model_support("P")["M1"][0] == "none"


# ------------------------------------------------------------------ 3. genuine M8 requirements still apply
def test_missing_miedema_parameters_still_make_m8_unavailable():
    assert m8_status("Nd") == "none" and m8_status("Te") == "none"
    res = calc("CoCrFeNiNd0.2")
    assert res.models["M8"].label == NA and res.models["M8"].na_kind == NA_MISSING_DATA
    assert ENGINE.model_coverage(list(res.composition))["M8"] is not None


@pytest.mark.parametrize("el", ["Ca", "Sr", "Ba"])
def test_alkaline_earth_r_over_p_factor_makes_m8_available_with_every_partner(el):
    """Ca, Sr, Ba have the R/P factor 0.4 of de Boer et al. Fig. 2.28 (audit M8-AE, 2026-10-27): M8 is evaluated with
    transition and non-transition partners alike, and the indicator says so.  (Until then: 'pair', N/A with a TM.)"""
    assert ENGINE.model_support(el)["M8"][0] == "ok"
    for partners in ({"Fe": 1, "Ni": 1}, {"Mg": 1, "Al": 1}):
        res = ENGINE.calculate({el: 1, **partners})
        out = res.models["M8"]
        assert out.label in (SS, MP), (el, partners, out.reason)
        phi = res.descriptors["phi_king"]
        assert phi is not None and phi == phi and abs(phi) != float("inf")


def test_m8_support_and_evaluation_agree_for_every_miedema_pair():
    """Exhaustive over the 57 Miedema-available elements: 'ok' with 'ok' always evaluates, 'pair' elements
    evaluate with some partners and not with others.  Elements without Miedema data are 'none' and never
    evaluate (checked against one partner each)."""
    mied = [el for el in DATA.elements if ENGINE.miedema_available(el)]
    seen = {el: set() for el in mied}
    for a, b in itertools.combinations(mied, 2):
        out = ENGINE.calculate({a: 1, b: 1}).models["M8"]
        evaluated = out.label != NA
        seen[a].add(evaluated)
        seen[b].add(evaluated)
        if m8_status(a) == "ok" and m8_status(b) == "ok":
            assert evaluated, (a, b, out.reason)
    for el in mied:
        assert m8_status(el) in ("ok", "pair"), el
        if m8_status(el) == "pair":
            assert seen[el] == {True, False}, el
    for el in DATA.elements:
        if el not in mied and el != "Fe":
            assert m8_status(el) == "none", el
            res = ENGINE.calculate({el: 1, "Fe": 1})
            assert not res.ok or res.models["M8"].label == NA, el


# ------------------------------------------------------------------ 4. other models keep their dependencies
# M1-M7 statuses frozen from the committed engine (HEAD c2fa310) before the M8 correction (section 14).  One later,
# deliberate change (CALCULATION_AUDIT.md section 15): the ten elements with no radius at all (At, Rn, Cm-Lr) report
# M3/M4 "none" instead of "warn", because both models are N/A for them.
_RARE = "Ac Am Ar At Bh Bk Br Cf Cl Cm Cn Db Ds Es F Fl Fm Fr He Hs I Kr Lr Lv Mc Md Mt Ne Nh No Np Og Pa Ra Rf Rg Rn Sg Ts Xe"
_NO_TROP = ("Ac Am Ar As At B Ba Be Bh Bi Bk Br C Ca Ce Cf Cl Cm Cn Cs Db Ds Dy Er Es Eu F Fl Fm Fr Ga Gd Ge H He Hg "
            "Ho Hs I In K Kr Li Lr Lu Lv Mc Md Mt N Na Nd Ne Nh No Np O Og P Pa Pb Pm Po Pr Pu Ra Rb Rf Rg Rn S Sb Se "
            "Sg Si Sm Sn Sr Tb Tc Te Th Tl Tm Ts U Xe Yb")
_TROP = "Ag Al Au Cd Co Cr Cu Fe Hf Ir La Mg Mn Mo Nb Ni Os Pd Pt Re Rh Ru Sc Ta Ti V W Y Zn Zr"
_NOT_MIX = _RARE + " O Po S Se Te"
_NO_RADIUS = "At Rn Cm Bk Cf Es Fm Md No Lr"
_GL_SUPP = "Ac Am Ar As Bh Bi Br Cl Cn Db Ds F Fl Fr H He Hg Hs I Kr Lv Mc Mt Ne Nh Np Og Pu Ra Rf Rg Sb Sg Ts Xe"
FROZEN = {
    "M1": {"none": _RARE + " H Lu N O P Po S Se Te"},
    "M2": {"none": _NOT_MIX, "warn": "As Bi H Hg Pu Sb"},
    "M3": {"warn": _GL_SUPP, "none": _NO_RADIUS},
    "M4": {"warn": _GL_SUPP, "none": _NO_RADIUS},
    "M5": {"none": _NOT_MIX, "warn": "As Bi H Hg Pu Sb"},
    "M6": {"none": _NO_TROP, "pair": _TROP},
    "M7": {"none": _NO_TROP, "pair": _TROP},
}


@pytest.mark.parametrize("model", list(FROZEN))
def test_other_models_keep_their_data_dependencies(model):
    for status in ("none", "warn", "pair"):
        expected = set(FROZEN[model].get(status, "").split())
        actual = {el for el in DATA.elements if ENGINE.model_support(el)[model][0] == status}
        assert actual == expected, (model, status, sorted(actual ^ expected))


# ------------------------------------------------------------------ 5. no calculated value moved
# Values recorded by the pre-correction parity run
# (docs/analysis-redesign/data/revalidation-2026-10-26/parity_pre_fix.json); compared with ==.
PINNED = {
    "FeNiP0.2": (0.6326642278795442, -22.908034433512277, -36.20883467726871, MP),
    "NiP0.25": (0.93254089289859, -36.82121735562203, -39.48482863970898, MP),
    "CoCrFeNiP0.1": (0.5467542083300513, -25.433192144396735, -46.51668292060744, MP),
    # "CaMgAl" was pinned here (Phi 0.971, MP) until the deliberate Ca/Sr/Ba Miedema correction (audit M8-AE,
    # 2026-10-27: a = 0.10, R/P factor 0.4) moved its values.  It is not re-pinned with engine output; the Ca/Sr/Ba
    # Miedema terms are now checked against printed tables (test_datasets.py, test_miedema_takeuchi_inoue.py).
    "CrMnNbTaW": (1.4672322610528554, -36.54509356770361, -24.907504106731956, SS),
    "CoCrFeNi": (1.183170658843056, -23.73887337928424, -20.063777952790772, SS),
}


@pytest.mark.parametrize("formula", list(PINNED))
def test_m8_values_and_verdicts_are_unchanged(formula):
    phi, dg_ss, dg_max, label = PINNED[formula]
    res = calc(formula)
    assert res.descriptors["phi_king"] == phi
    assert res.descriptors["dg_ss"] == dg_ss
    assert res.descriptors["dg_max"] == dg_max
    assert res.models["M8"].label == label


def test_m8_threshold_is_still_inclusive_phi_one():
    assert MODELS["M8"].criterion.startswith("SS if Φ ≥ 1, otherwise MP.")


# ------------------------------------------------------------------ 6. documentation agrees with the code
def test_calculation_audit_states_the_implemented_m8_criterion():
    text = (ROOT / "CALCULATION_AUDIT.md").read_text(encoding="utf-8")
    m8 = re.search(r"### M8 .*?(?=\n---|\n## )", text, re.S).group(0)
    assert "**SS if Φ ≥ 1**" in m8
    assert "**Φ ≥ 1 and δ ≤ 6.6 %**" not in text                   # the pre-F9 criterion is gone as a rule
    missing = re.search(r"Missing CN12 radius →[^\n]*\n[^\n]*", text).group(0)
    assert "M8 is unaffected" in missing
    assert "## 14. M8 documentation and model-support correction" in text
