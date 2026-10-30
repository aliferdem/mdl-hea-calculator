"""Model availability (``Engine.model_support``) agrees with evaluation for every model (CALCULATION_AUDIT.md §15).

The periodic-table indicator must never promise a model the engine then reports as N/A for missing data, and never
deny one the engine evaluates.  These corrections change availability metadata and N/A wording only - the values
and verdicts pinned below were recorded before the change (publication-validation-2026-10-26/parity_pre_phase6.json).
"""

import itertools

import pytest

from hea_calc.core import engine as E
from hea_calc.core.composition import parse_formula

ENGINE = E.Engine()
DATA = ENGINE.data
NO_RADIUS = ["At", "Rn", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr"]


def test_the_elements_without_a_radius_are_exactly_the_documented_ten():
    assert sorted(el for el in DATA.elements if DATA.prop(el, "atomic_radius") is None) == sorted(NO_RADIUS)


@pytest.mark.parametrize("el", NO_RADIUS)
def test_models_needing_a_radius_report_none_for_elements_without_one(el):
    support = ENGINE.model_support(el)
    for m in ("M2", "M3", "M4", "M5"):
        assert support[m][0] == "none", (el, m, support[m])
    res = ENGINE.calculate({el: 1, "Fe": 1})
    for m in ("M3", "M4"):
        out = res.models[m]
        assert out.label == E.NA and out.na_kind == E.NA_MISSING_DATA, (el, m, out)


def test_supplementary_radius_elements_keep_their_warning():
    """A supplementary (non Guo & Liu) radius is still a computable value with a caution - not 'none'."""
    for el in ("Sb", "Bi", "Hg", "As", "Pu"):
        assert DATA.prop(el, "atomic_radius") is not None
        assert ENGINE.model_support(el)["M3"][0] == "warn"
        assert ENGINE.model_support(el)["M4"][0] == "warn"


def test_every_models_support_agrees_with_evaluation_for_every_element_pair():
    """Exhaustive over all 118 elements (6 903 equiatomic binaries): 'none' never evaluates, 'ok'/'warn' with
    'ok'/'warn' never returns N/A for missing data ('pair' elements depend on the partner by definition)."""
    els = list(DATA.elements)
    support = {el: {k: v[0] for k, v in ENGINE.model_support(el).items()} for el in els}
    bad = []
    for a, b in itertools.combinations(els, 2):
        res = ENGINE.calculate({a: 1, b: 1})
        if not res.ok:
            continue
        for m in E.MODEL_KEYS:
            out = res.models[m]
            sa, sb = support[a][m], support[b][m]
            if out.label != E.NA and "none" in (sa, sb):
                bad.append((m, a, b, "evaluated although 'none'"))
            if out.label == E.NA and out.na_kind == E.NA_MISSING_DATA and {sa, sb} <= {"ok", "warn"}:
                bad.append((m, a, b, out.reason))
    assert not bad, bad[:10]


def test_alkaline_earth_with_transition_metals_evaluates_and_missing_data_message_is_unchanged():
    # Ca-Fe used to be N/A for a missing R/P factor; with the de Boer Fig. 2.28 factor it evaluates (audit M8-AE).
    out = ENGINE.calculate({"Ca": 1, "Fe": 1, "Ni": 1}).models["M8"]
    assert out.label != E.NA, out.reason
    # The R/P error path itself is kept for any element without a factor (none among the Miedema elements now).
    assert all(E.Engine._r_factor_available(el) for el in DATA.elements if ENGINE.miedema_available(el))
    nd = ENGINE.calculate({"Co": 1, "Cr": 1, "Fe": 1, "Ni": 1, "Nd": 0.2}).models["M8"]
    assert nd.reason == "Miedema parameters unavailable for Nd."


# The M3/M4 verdicts recorded before the availability correction (pinned).  gamma and Lambda were pinned engine
# output until F2 (audit section 20) moved the radii to the printed Guo & Liu values; they are now checked against an
# independent evaluation of the papers' equations with those printed radii (supplementary radii: the stored value).
PINNED_VERDICTS = {"CoCrFeNi": ("SS", "SS"), "AlCoCrFeNi": ("SS", "SS+IM"), "CoCrFeNiTi0.5": ("MP", "SS+IM"),
                   "CoCrFeNiSb0.2": ("MP", "SS")}


def _printed_radii():
    import json
    from conftest import REF
    gl = json.loads((REF / "guo_liu_2011_table1.json").read_text(encoding="utf-8"))["radius_pm"]
    return lambda el: gl[el] if el in gl else DATA.prop(el, "atomic_radius")


def _independent_gamma_lambda(formula):
    """Wang et al. (2015) Eqs. (1)-(3) and Singh et al. (2014) Lambda = dS_mix / delta^2, written out here."""
    import math
    amounts = parse_formula(formula)
    tot = sum(amounts.values())
    c = {e: v / tot for e, v in amounts.items()}
    r = _printed_radii()
    rbar = sum(x * r(e) for e, x in c.items())
    delta = 100.0 * math.sqrt(sum(x * (1.0 - r(e) / rbar) ** 2 for e, x in c.items()))

    def omega(ri):
        return 1.0 - math.sqrt(((ri + rbar) ** 2 - rbar ** 2) / (ri + rbar) ** 2)

    gamma = omega(min(r(e) for e in c)) / omega(max(r(e) for e in c))
    lam = -E.R * sum(x * math.log(x) for x in c.values()) / delta ** 2
    return gamma, lam


@pytest.mark.parametrize("formula", list(PINNED_VERDICTS))
def test_gamma_lambda_and_m3_m4_verdicts_are_unchanged(formula):
    m3, m4 = PINNED_VERDICTS[formula]
    gamma, lam = _independent_gamma_lambda(formula)
    res = ENGINE.calculate(parse_formula(formula))
    assert res.descriptors["gamma"] == pytest.approx(gamma, rel=1e-12)
    assert res.descriptors["lambda"] == pytest.approx(lam, rel=1e-12)
    assert res.label("M3") == m3 and res.label("M4") == m4
