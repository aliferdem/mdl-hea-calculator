"""Regression tests against published values (see CALCULATION_AUDIT.md for every exception)."""

import pytest

import published_tables as P
from hea_calc.core.composition import parse_formula
from hea_calc.core.engine import R

# Rows whose published value disagrees with a recomputation from the paper's own definitions/data.
# They are documented in CALCULATION_AUDIT.md (most are internal inconsistencies/typos in the tables).
YZ_EXCEPTIONS = {
    ("CoCrFeNiCuAl0.3", "enthalpy"),  # YZ prints 1.56; Guo 2013 Table 1 prints 0.16 for the same alloy
    ("CoCrFeNiCuAl1.8", "delta"), ("CoCrFeNiCuAl3", "delta"), ("CoCrNiCu0.5Al", "delta"),
    ("CuNiAl", "delta"), ("CuNi", "delta"), ("Ti0.5Co3CrFeNiAl", "enthalpy"),
    ("Ti0.5CoCrFeNiCu0.25Al0.75", "enthalpy"), ("CoFeNiCuV", "delta"), ("CoFeNiCuV", "enthalpy"),
    ("MnCrFe1.5Ni0.5Al0.5", "enthalpy"), ("MoCrFeNiCu", "delta"), ("CoCrFeNiCuAl0.5V0.4", "delta"),
    ("Mn2CrFeNi2Cu", "delta"), ("Mn2CrFeNi2Cu", "enthalpy"), ("Ti1.5CoCrFeNiAl", "delta"),
    ("ZrTiVCuNiBe", "delta"), ("TiCoCrNiCuAlY0.5", "delta"), ("TiCoCrNiCuAlY0.8", "delta"),
    ("TiCoCrNiCuAlY", "delta"),
}
GUO_EXCEPTIONS = {("SrCaYb(Li0.55Mg0.45)Zn", "delta"), ("Ti2.5CrCuFeCoNi", "delta"),
                  ("Ti2.5CrCuFeCoNi", "enthalpy")}
SINGH_EXCEPTIONS = {"ZrCrFeNiCu", "ZrHfTiCuFe", "ZrHfTiCuCo", "AlTiCoCrNiCu",
                    "Al25.53Co19.24Cr19.06Fe19.11Ni19.06", "AlTiCoNiCuZn",
                    "Co24.90Cr25.12Fe24.58Ni25.90", "Co32.9Fe34.0Ni33.1"}
SENKOV_EXCEPTIONS = {"Al0.3NbTa0.8Ti1.4V0.2Zr1.3"}
# rows internally inconsistent in the Ye Intermetallics SI (verified against the source 2026-10-28; reasons in
# test_published_benchmarks.KNOWN_DISCREPANCIES and YE_INTERMETALLICS_SOURCE_VERIFICATION_2026-10-28.md)
YE_SE_EXCEPTIONS = {"FeCoNiCrCuAl0.3", "CoCrFeNiAlNb0.25",
                    "Fe66Ni8.46Ti0.35Cr20.16Mo0.75W0.39Nb0.24C1.38Mn1.1Si1.18"}


def _calc(engine, formula):
    res = engine.calculate(parse_formula(formula))
    assert res.ok, res.error
    return res


def _rows(table):
    for row in table:
        try:
            parse_formula(row["formula"])
        except ValueError:
            continue
        yield row


def test_yang_zhang_table1_delta_cn12_and_dhmix(engine):
    checked = 0
    for row in _rows(P.YANG_ZHANG_2012_TABLE_1):
        d = _calc(engine, row["formula"]).descriptors
        for pub, mine in (("delta", "delta_cn12"), ("enthalpy", "dhmix")):
            if (row["formula"], pub) in YZ_EXCEPTIONS:
                continue
            assert d[mine] == pytest.approx(row[pub], abs=0.05), (row["formula"], pub)
            checked += 1
    assert checked >= 240


def test_yang_zhang_omega_examples(engine):
    # Omega depends on the elemental Tm set; YZ's Tm differ by a few K, so compare loosely.
    for formula, omega in (("CoCrFeNi", 5.71), ("CoCrFeNiMn", 5.77), ("CoCrFeNiAl", 1.83)):
        assert _calc(engine, formula).descriptors["omega"] == pytest.approx(omega, rel=0.02)


def test_guo_2013_table1_delta_and_dhmix(engine):
    checked = 0
    for row in _rows(P.GUO_2013_TABLE_1):
        d = _calc(engine, row["formula"]).descriptors
        for pub, mine in (("delta", "delta"), ("enthalpy", "dhmix")):
            if (row["formula"], pub) in GUO_EXCEPTIONS:
                continue
            assert d[mine] == pytest.approx(row[pub], abs=0.05), (row["formula"], pub)
            checked += 1
    assert checked >= 180


# Lambda-only published-reference discrepancy (audit section 20): delta is still checked; Lambda must stay a bounded
# discrepancy (outside 2 %, within 3 %), so it can neither grow nor disappear unnoticed.
SINGH_LAMBDA_KNOWN = {
    "Mo0.3CoCrFeNi": "Singh et al. used Smithells radii (Ref. [47]); with the Guo & Liu printed radii Lambda 2.2686 vs "
                     "printed 2.317 (-2.09 %, tolerance 2 %); delta 2.3777 vs 2.35 within tolerance",
}


def test_singh_2014_table1_delta_and_lambda(engine):
    checked = known = 0
    for row in _rows(P.SINGH_2014_TABLE_1):
        if row["formula"] in SINGH_EXCEPTIONS:
            continue
        d = _calc(engine, row["formula"]).descriptors
        assert d["delta"] == pytest.approx(row["delta"], abs=0.05), row["formula"]
        if row["formula"] in SINGH_LAMBDA_KNOWN:
            rel = abs(d["lambda"] - row["lambda"]) / row["lambda"]
            assert 0.02 < rel <= 0.03, (row["formula"], rel, SINGH_LAMBDA_KNOWN[row["formula"]])
            known += 1
        else:
            assert d["lambda"] == pytest.approx(row["lambda"], rel=0.02, abs=0.005), row["formula"]
        checked += 1
    assert checked >= 65 and known == len(SINGH_LAMBDA_KNOWN)


def test_singh_row_067_lambda_is_the_independent_f2_value(engine):
    """The F2 descriptor itself for the documented row: Singh's Lambda = dS_mix / delta^2 written out with the
    printed Guo & Liu radii (Mo 136.3, Co 125.1, Cr 124.9, Fe 124.1, Ni 124.6 pm)."""
    import math
    r = {"Mo": 136.3, "Co": 125.1, "Cr": 124.9, "Fe": 124.1, "Ni": 124.6}
    a = {"Mo": 0.3, "Co": 1.0, "Cr": 1.0, "Fe": 1.0, "Ni": 1.0}
    c = {e: v / sum(a.values()) for e, v in a.items()}
    rbar = sum(c[e] * r[e] for e in c)
    delta = 100 * math.sqrt(sum(c[e] * (1 - r[e] / rbar) ** 2 for e in c))
    lam = -R * sum(x * math.log(x) for x in c.values()) / delta ** 2
    d = _calc(engine, "Mo0.3CoCrFeNi").descriptors
    assert d["delta"] == pytest.approx(delta, rel=1e-9) and d["lambda"] == pytest.approx(lam, rel=1e-9)
    assert lam == pytest.approx(2.26864, abs=5e-5)


def test_senkov_2016_dhim_from_published_troparevsky_matrix(engine):
    checked = 0
    for row, dhim in zip(P.SENKOV_2016_TABLE_1, P.SENKOV_2016_DHIM):
        if row["formula"] in SENKOV_EXCEPTIONS:
            continue
        assert _calc(engine, row["formula"]).descriptors["dhim"] == pytest.approx(dhim, abs=0.02), row["formula"]
        checked += 1
    assert checked == 44


def test_senkov_k1cr_definition(engine):
    # k1cr = 1 + (1 - k2) T dSmix/|dHmix| with k2 = 0.6 (Eq. 7); CoCrFeNi at T_A = 573 K -> 1.70 in Table 1.
    res = engine.calculate(parse_formula("CoCrFeNi"), annealing_temperature=573)
    d = res.descriptors
    assert d["k1cr"] == pytest.approx(1 + 0.4 * 573 * d["dsmix"] / (abs(d["dhmix"]) * 1000))
    assert d["k1cr"] == pytest.approx(1.70, abs=0.01)


def test_ye_excess_entropy(engine):
    checked = 0
    for row in _rows(P.YE_2015_INTERMETALLICS_EXCESS_ENTROPY):
        if row["formula"] in YE_SE_EXCEPTIONS:
            continue
        pub = (row["excess_entropy_068"] + row["excess_entropy_074"]) / 2
        se = abs(_calc(engine, row["formula"]).descriptors["s_e"]) / R
        assert se == pytest.approx(pub, rel=0.05, abs=0.002), row["formula"]
        checked += 1
    assert checked >= 170


@pytest.mark.parametrize("formula,phi,tol", [("FeCrCuNiCo", 369, 6), ("FeCrCuNiAl", 11, 0.6)])
def test_ye_phi_main_text_examples(engine, formula, phi, tol):
    assert _calc(engine, formula).descriptors["phi_ye"] == pytest.approx(phi, abs=tol)


def test_ye_phi_classification_table_s1(engine):
    mismatches = []
    for row in _rows(P.YE_2015_TABLE_S1):
        phi = _calc(engine, row["formula"]).descriptors["phi_ye"]
        lo, hi = sorted((row["phi_bcc"], row["phi_fcc"]))
        if lo < 20 <= hi:
            continue  # published values straddle the threshold
        if (phi >= 20) != (lo >= 20):
            mismatches.append(row["formula"])
    assert not mismatches


@pytest.mark.parametrize("formula,dg_ss,pair,dg_int,phi", [
    ("CoCrFeNi", -23.43, ("Cr", "Ni"), -10.08, 1.16),
    ("CoCrCuFeNi", -21.08, ("Cu", "Fe"), 19.14, 0.55),
    ("AlCoCrFeNi", -33.89, ("Al", "Ni"), -47.33, 0.36),
])
def test_king_2016_worked_examples(engine, formula, dg_ss, pair, dg_int, phi):
    res = _calc(engine, formula)
    d = res.descriptors
    assert d["dg_ss"] == pytest.approx(dg_ss, abs=0.4)
    assert set(d["king_pair"].split("–")) == set(pair)
    assert d["dh_int_max"] == pytest.approx(dg_int, abs=0.6)
    assert d["dg_max"] == pytest.approx(2 * d["dh_int_max"])
    assert d["phi_king"] == pytest.approx(phi, abs=0.03)
    assert res.label("M8") == ("SS" if phi >= 1 else "MP")


@pytest.mark.parametrize("additions,expected", [
    # Troparevsky et al. (2015) Table I, FeCoNi base, T_ann = 1000 K (Otto et al.)
    (("Cr",), "SS"), (("Pd",), "SS"), (("Mn",), "SS"), (("Mo",), "IM"), (("Ti",), "IM"),
    (("V",), "IM"), (("Cr", "Pd"), "SS"), (("Cr", "Mn"), "SS"), (("Pd", "Mn"), "IM"), (("Mn", "V"), "IM"),
    (("Cr", "Mo"), "IM"),
])
def test_troparevsky_table1_feconi(engine, additions, expected):
    comp = {el: 1.0 for el in ("Fe", "Co", "Ni", *additions)}
    assert engine.calculate(comp, annealing_temperature=1000).label("M6") == expected


@pytest.mark.parametrize("additions,expected", [
    # Table I, NbMoTa base, T_ann = 1673 K (Senkov et al.)
    (("W",), "SS"), (("V",), "SS"), (("Ti",), "SS"), (("Zr",), "SS"), (("W", "V"), "SS"),
    (("Ti", "Zr"), "SS"), (("Hf",), "MP"), (("W", "Hf"), "MP"), (("Zr", "Hf"), "MP"),
])
def test_troparevsky_table1_nbmota(engine, additions, expected):
    comp = {el: 1.0 for el in ("Nb", "Mo", "Ta", *additions)}
    assert engine.calculate(comp, annealing_temperature=1673).label("M6") == expected


def test_troparevsky_text_examples(engine):
    d = engine.calculate({"Cr": 1, "Mn": 1, "Fe": 1, "Co": 1, "Ni": 1}, annealing_temperature=1000).descriptors
    assert d["hf_min"] == -115
    assert d["hf_lower"] == pytest.approx(-138.7, abs=0.1)  # "-138.7 meV/atom" at 1000 K
    d = engine.calculate({"Nb": 1, "Mo": 1, "Ta": 1, "W": 1}).descriptors
    assert d["hf_min"] == -193 and d["hf_min_pair"] == "Mo–Ta"


def test_wang_hume_rothery_limit(engine):
    # Wang et al.: the 15 % size rule corresponds to gamma ~ 1.167 for a binary.
    from hea_calc.core.engine import Engine
    gamma = Engine._gamma({"A": 0.5, "B": 0.5}, {"A": 100.0, "B": 115.0})
    assert 1.15 < gamma < 1.19
