"""Publication-based regression tests, case by case (docs/analysis-redesign/PUBLICATION_VALIDATION_REPORT_2026-10-26.md).

Reference values come only from ``tests/reference/published_benchmarks.json`` - numbers printed in the original
papers, each checked against the paper (text layer and rendered page).  No expected value is produced by the engine.

Only quantities whose inputs are fully sourced are hard oracles (``HARD``).  Each is compared with its OWN
documented tolerance (catalogue ``_metadata.tolerances``: half a unit of the printed last digit, plus a stated
input-uncertainty allowance).  Published values that the paper's own definitions and cited data do not reproduce
are listed in ``KNOWN_DISCREPANCIES`` with the reason; the test fails if one of them silently starts to agree,
so a documented discrepancy can never disappear from view.

M3 (Wang 2015) superalloys and the M5/M7/M8 classification rows are diagnostics only (approximate compositions or
no published parameter) - see the report; they are not asserted here.
"""

import json
from pathlib import Path

import pytest

from hea_calc.core.composition import parse_formula
from hea_calc.core.engine import R, Engine

CATALOGUE = json.loads((Path(__file__).parent / "reference" / "published_benchmarks.json").read_text(encoding="utf-8"))
TOL = CATALOGUE["_metadata"]["tolerances"]
ENGINE = Engine()

# (model, quantity) -> (tolerance key, printed decimals or None = from the published number)
HARD = {
    ("M1", "delta_cn12"): ("delta_cn12", 2), ("M1", "dhmix"): ("dhmix", 2),
    ("M2", "delta"): ("delta_gl", 2), ("M2", "dhmix"): ("dhmix", 2),
    ("M4", "delta"): ("delta_gl", 2), ("M4", "lambda"): ("lambda", None),
    ("M5", "phi_ye"): ("phi_ye", 0), ("M5", "s_e_over_kB"): ("s_e", 3),
    ("M6", "hf"): ("hf", 0), ("M6", "hf_min"): ("hf", 0), ("M6", "hf_lower"): ("hf_lower", None),
    ("M7", "dhim"): ("dhim", 2),
    ("M8", "dg_ss"): ("king_dg", 2), ("M8", "dh_int_max"): ("king_dgint", 2), ("M8", "dg_max"): ("king_dgint", 2),
    ("M8", "phi_king"): ("king_phi", 2),
}

# Published values the paper's own formula and cited data do not reproduce.  Every entry was checked against the
# rendered page (it is printed so, not a transcription error).  Reasons: PUBLICATION_VALIDATION_REPORT section 3.
_YZ = "Yang & Zhang Table 1 value not reproducible from the formula and Kittel/Takeuchi data (printed so; internal inconsistency)"
KNOWN_DISCREPANCIES = {
    **{f"M1-YZ12-T1-{n}": ({"delta_cn12"}, _YZ) for n in
       ("009", "014", "020", "024", "025", "026", "056", "069", "073", "097", "130", "131", "132", "133")},
    **{f"M1-YZ12-T1-{n}": ({"dhmix"}, _YZ) for n in ("003", "046", "048", "068")},
    "M1-YZ12-T1-050": ({"delta_cn12", "dhmix"}, _YZ),
    "M1-YZ12-T1-080": ({"delta_cn12", "dhmix"}, _YZ),
    "M2-GUO13-T1-005": ({"delta"}, "SrCaYb(Li0.55Mg0.45)Zn: printed 15.63 vs 15.71; no supplementary radius involved; "
                                   "cause not identified"),
    "M2-GUO13-T1-077": ({"delta", "dhmix"}, "Ti2.5CrCuFeCoNi: the printed values are those of Ti2CrCuFeCoNi "
                                            "(computed dHmix -14.04 = printed, delta 7.22 vs 7.24)"),
    **{f"M4-SINGH14-T1-{n}": ({"delta", "lambda"}, "Singh Table 1 row not reproducible with the paper's radius set")
       for n in ("002", "003", "004", "008", "013", "019", "075", "076")},
    "M4-SINGH14-T1-067": ({"lambda"}, "Mo0.3CoCrFeNi: Singh used Smithells radii; with the Guo & Liu printed radii "
                                      "(F2, audit section 20) Lambda 2.2686 vs printed 2.317 (-2.09 %, tolerance 2 %); "
                                      "delta 2.3777 vs 2.35 within tolerance"),
    "M5-YE15I-S-005": ({"s_e_over_kB"}, "FeCoNiCrCuAl0.3: row internally inconsistent in the source SI (|S_E| 0.68/0.74 "
                                        "ratio 0.60 against >= 1.5 in every other row; printed S_c is that of Al0.8)"),
    "M5-YE15I-S-042": ({"s_e_over_kB"}, "CoCrFeNiAlNb0.25: the source's xi = 0.68 cell is inconsistent (+20 %, ratio "
                                        "1.35); its xi = 0.74 cell is reproduced exactly (0.16592 vs 0.166)"),
    "M5-YE15I-S-166": ({"s_e_over_kB"}, "printed S_E (both xi) corresponds to ~0.03 at.% C, while the formula and the "
                                        "printed S_c give 1.38 at.% C; C is included in the 50 other C rows"),
    "M7-SENKOV16-T1-005": ({"dhim"}, "Senkov prints -5.62; the published matrix gives -6.69 (likely table typo)"),
    "M8-KING16-S321-Co43Cr1Fe7Ni49": ({"phi_king"}, "King Phi 8.93 vs 9.29 (+4 %): Bakker-table vs equation inputs"),
}


def _status(pub, calc, tol_key, dp):
    if dp is None:
        s = repr(float(pub))
        dp = len(s.split(".")[1].rstrip("0")) if "." in s else 0
    half = 0.5 * 10 ** -dp + 1e-9
    diff = calc - pub
    if abs(diff) <= half:
        return "EXACT", diff
    t = TOL[tol_key]
    lim = t["value"] * abs(pub) if t["kind"] == "rel" else t["value"]
    return ("WITHIN_DOCUMENTED_TOLERANCE" if abs(diff) <= lim + half else "DISCREPANCY"), diff


def _calculate(case):
    if case["id"].startswith("M6-TROP15-HF-"):
        a, b = list(parse_formula(case["formula"]))
        return {"hf": ENGINE.data.formation_enthalpy(a, b)}
    st = case.get("settings") or {}
    temp = st.get("T_A") if isinstance(st.get("T_A"), (int, float)) else st.get("T") if isinstance(st.get("T"), (int, float)) else None
    res = ENGINE.calculate(parse_formula(case["formula"]), annealing_temperature=temp)
    d = dict(res.descriptors)
    if d.get("s_e") is not None:
        d["s_e_over_kB"] = abs(d["s_e"]) / R
    return d


HARD_CASES = [c for c in CATALOGUE["cases"] if any((c["model"], q) in HARD for q in c["published"])]


def test_catalogue_covers_every_published_table():
    by_model = {}
    for c in HARD_CASES:
        by_model[c["model"]] = by_model.get(c["model"], 0) + 1
    assert by_model == {"M1": 133, "M2": 93, "M4": 76, "M5": 176, "M6": 5, "M7": 45, "M8": 4}, by_model


@pytest.mark.parametrize("case", HARD_CASES, ids=[c["id"] for c in HARD_CASES])
def test_published_value_is_reproduced_within_its_documented_tolerance(case):
    calc = _calculate(case)
    known, reason = KNOWN_DISCREPANCIES.get(case["id"], (set(), ""))
    for q, pub in case["published"].items():
        if (case["model"], q) not in HARD:
            continue
        tol_key, dp = HARD[(case["model"], q)]
        assert calc.get(q) is not None, (case["id"], q, "engine returned no value")
        status, diff = _status(pub, calc[q], tol_key, dp)
        if q in known:
            assert status == "DISCREPANCY", (f"{case['id']} {q} now agrees with the publication ({diff:+.4g}); "
                                             f"update KNOWN_DISCREPANCIES and the report: {reason}")
        else:
            assert status != "DISCREPANCY", (case["id"], case["formula"], q, pub, calc[q], diff)


def test_troparevsky_1673_K_bound_for_five_components():
    """Troparevsky et al. (2015) p. 4: T_ann = 1673 K corresponds to -232 meV/atom (five-component equimolar)."""
    d = ENGINE.calculate({e: 1 for e in ("Nb", "Mo", "Ta", "W", "V")}, annealing_temperature=1673).descriptors
    assert d["hf_lower"] == pytest.approx(-232.0, abs=0.5)


def test_known_discrepancy_list_names_only_catalogue_cases():
    ids = {c["id"] for c in CATALOGUE["cases"]}
    assert set(KNOWN_DISCREPANCIES) <= ids
