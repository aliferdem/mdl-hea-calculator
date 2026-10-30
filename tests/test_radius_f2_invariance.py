"""F2 (audit section 20): the 26 Guo & Liu printed radii change only what reads ``atomic_radius``.

The installed engine is compared with the same engine reading the 26 pre-F2 values (0.01 pm: Zhang 2014 / untraced).
M1 (Kittel CN12) and M6-M8 read no ``atomic_radius``; compositions without the 26 elements read none of the changed
values; the supplementary flag and model availability do not depend on the value."""

import itertools
import random

import pytest

from hea_calc.core.engine import Engine

PRE_F2 = {"Fe": 124.12, "Ni": 124.59, "Cr": 124.91, "Ru": 133.84, "Os": 135.23, "Ir": 135.73, "Mo": 136.26,
          "Pd": 137.54, "Zn": 139.45, "Al": 143.17, "Ag": 144.47, "Ti": 146.15, "Li": 151.94, "Cd": 156.83,
          "Hf": 157.75, "Mg": 160.13, "Zr": 160.25, "Lu": 173.49, "Pb": 174.97, "Er": 175.58, "Ho": 176.61,
          "Tb": 178.14, "Gd": 180.13, "Y": 180.15, "Ce": 182.47, "Eu": 198.44}
UNAFFECTED = ["Co", "Cu", "Mn", "Nb", "Ta", "V", "W", "Sn", "Si", "Sc", "Pt", "Au", "Sb", "Ga", "Ge", "In"]
AFFECTED = ["Fe", "Ni", "Cr", "Al", "Ti", "Zr", "Mo", "Hf", "Mg", "Zn", "Y", "Li", "Pd", "Ag"]


class _Pre:
    def __init__(self, base):
        self._base = base

    def __getattr__(self, name):
        return getattr(self._base, name)

    def prop(self, el, key):
        if key == "atomic_radius" and el in PRE_F2:
            return PRE_F2[el]
        return self._base.prop(el, key)


@pytest.fixture(scope="module")
def engines():
    new, old = Engine(), Engine()
    old.data = _Pre(old.data)
    return old, new


def _snap(res, models=None, descriptors=True):
    out = {k: (o.label, o.status, o.na_kind, o.reason) for k, o in res.models.items() if models is None or k in models}
    if descriptors:
        out["_d"] = {k: (repr(v) if isinstance(v, float) else v) for k, v in res.descriptors.items()}
        out["_w"] = list(res.warnings)
    return out


def test_the_26_values_are_the_pre_f2_ones_rounded(engines):
    old, new = engines
    for el, v in PRE_F2.items():
        assert abs(new.data.prop(el, "atomic_radius") - v) <= 0.05 + 1e-9, el


def test_compositions_without_the_26_elements_are_identical_in_every_field(engines):
    old, new = engines
    rng = random.Random(20)
    comps = [{e: 1.0 for e in s} for s in itertools.combinations(UNAFFECTED, 3)][:200]
    comps += [{e: rng.choice([0.1 * k for k in range(1, 21)]) for e in rng.sample(UNAFFECTED, rng.randint(2, 6))}
              for _ in range(200)]
    for c in comps:
        assert _snap(old.calculate(c)) == _snap(new.calculate(c)), c


def test_m1_and_m6_to_m8_never_change(engines):
    old, new = engines
    rng = random.Random(21)
    for _ in range(300):
        els = rng.sample(AFFECTED, rng.randint(1, 3)) + rng.sample(UNAFFECTED, rng.randint(1, 3))
        c = {e: rng.choice([0.1 * k for k in range(1, 21)]) for e in els}
        a, b = old.calculate(c), new.calculate(c)
        assert _snap(a, {"M1", "M6", "M7", "M8"}, False) == _snap(b, {"M1", "M6", "M7", "M8"}, False), c
        for k in ("delta_cn12", "omega", "dhmix", "dsmix", "tm", "phi_king", "dg_ss", "dg_max", "dhim", "k1"):
            assert a.descriptors.get(k) == b.descriptors.get(k), (c, k)
        assert a.warnings == b.warnings


def test_model_support_and_supplementary_flag_unchanged(engines):
    old, new = engines
    for el in list(PRE_F2) + ["Sb", "Hg", "Pu", "Co"]:
        assert old.model_support(el) == new.model_support(el), el
        assert old.data.radius_is_supplementary(el) == new.data.radius_is_supplementary(el)


def test_pd_re_have_identical_printed_radii_so_lambda_and_phi_are_undefined(engines):
    """Guo & Liu (2011) Table 1 prints Pd and Re both as 1.375 A (the former 0.01 pm column held 137.54 for Pd).  An
    all-equal-radius composition has delta = 0 and S_E = 0 (section 19): Lambda and phi are undefined, M4 and M5 N/A
    (undefined) - before F2 the 0.04 pm gap gave Lambda ~ 3e4 and phi ~ 6e5 (SS)."""
    from hea_calc.core.engine import NA, NA_UNDEFINED
    old, new = engines
    assert new.data.prop("Pd", "atomic_radius") == new.data.prop("Re", "atomic_radius") == 137.5
    for x in (0.5, 0.2):
        res = new.calculate({"Pd": x, "Re": 1 - x})
        d = res.descriptors
        assert d["delta"] == 0.0 and d["s_e"] == 0.0 and d["lambda"] is None and d["phi_ye"] is None
        for m in ("M4", "M5"):
            assert res.models[m].label == NA and res.models[m].na_kind == NA_UNDEFINED
        assert old.calculate({"Pd": x, "Re": 1 - x}).models["M5"].label != NA     # the pre-F2 gap gave a verdict
