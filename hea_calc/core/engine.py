"""The single HEA calculation engine.

Every workflow (single composition, composition sweep, expression mode, spreadsheet import) hands a
composition ``{element: amount}`` to :meth:`Engine.calculate`.  No other module implements a
scientific equation.  Definitions, data sources and decisions are documented in
``CALCULATION_AUDIT.md``; the short references below point to it.

Model numbering follows the literature files / Figma design:

====  ============================  =====================================================
M1    Yang & Zhang (2012)           Omega >= 1.1 and delta(CN12) <= 6.6 %
M2    Guo et al. (2013)             delta-dHmix map (SS / amorphous / other)
M3    Wang et al. (2015)            gamma < 1.175
M4    Singh et al. (2014)           Lambda = dSmix / delta^2
M5    Ye et al. (2015)              phi = (Sc - S_H)/|S_E| >= 20
M6    Troparevsky et al. (2015)     -T dSmix < dHf(ij) < 37 meV/atom for every pair
M7    Senkov & Miracle (2016)       dHmix - T dSmix < dH_IM - k2 T dSmix  (k2 = 0.6)
M8    King et al. (2016)            Phi = dG_ss / -|dG_max| >= 1
====  ============================  =====================================================
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from functools import lru_cache

from .data import Datasets, default_datasets

R = 8.314462618  # J mol-1 K-1
MEV_PER_ATOM_TO_KJ_PER_MOL = 0.0964853321233  # 1 meV/atom = 96.485 J/mol
MEV_PER_ATOM_TO_J_PER_MOL = 96.4853321233

# Prediction labels (scientific result classes, not UI states).
SS, MP, IM, SS_IM, MG, NA = "SS", "MP", "IM", "SS+IM", "MG", "N/A"

DEFAULT_TCRIT_FRACTION = 0.55  # Troparevsky et al. (2015): T_crit = 0.55 T_m (see audit, M6)
SENKOV_K2 = 0.6  # Senkov & Miracle (2016): partially ordered IM, k2 = 0.6
TROPAREVSKY_UPPER_MEV = 37.0  # meV/atom

# ------------------------------------------------------------------ threshold resolution
# Every model boundary is a printed number, and the descriptor compared against it is a
# floating-point sum over up to ten concentration-weighted binary terms.  A value that differs from
# the printed threshold only in its last few bits is the *same number* for the purpose of this
# model, and letting IEEE-754 representation decide a scientific result class is simply wrong.
#
# THRESHOLD_REL_TOL is therefore twelve orders of magnitude finer than the precision any of these
# thresholds is quoted to.  It absorbs accumulated representation noise - the Cantor alloy computes
# dHmix = 3.200000000000001 against a printed window edge of 3.2 - and nothing else: a difference
# of 0.01, or of a single printed digit, still flips the verdict, so this cannot mask a genuine
# disagreement.  tests/test_models_published.py and tests/test_engine_behaviour.py pin both sides.
THRESHOLD_REL_TOL = 1e-12


def _tol(limit: float) -> float:
    """Absolute slack that still means 'the same number' as ``limit``."""
    return abs(limit) * THRESHOLD_REL_TOL


# The tolerance applies to INCLUSIVE comparisons only.  A source that prints ">=" or "<=" states an
# inclusive rule, so representation noise must not exclude a value equal to the bound.  A source that
# prints "<" or ">" states a strict rule and that strictness is meaningful at the bound: Guo Sec. 4.1
# prints dHmix < -12.2 kJ/mol, so an alloy at exactly -12.2 kJ/mol is not in the amorphous region.
# Strict comparisons below are therefore written exactly, without _ge/_le.


def _ge(value: float, limit: float) -> bool:
    """``value >= limit``, modulo representation noise only (see THRESHOLD_REL_TOL)."""
    return value >= limit - _tol(limit)


def _le(value: float, limit: float) -> bool:
    """``value <= limit``, modulo representation noise only (see THRESHOLD_REL_TOL)."""
    return value <= limit + _tol(limit)

MODEL_KEYS = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")


@dataclass(frozen=True)
class ModelInfo:
    key: str
    short: str
    title: str
    reference: str
    criterion: str
    name: str = ""      # short human name of the criterion, e.g. "Ω–δ solid solution criterion"
    note: str = ""      # one sentence on what the criterion does and does not claim


MODELS: dict[str, ModelInfo] = {
    "M1": ModelInfo("M1", "Yang & Zhang", "Model 1 – Yang & Zhang (2012)",
                    "X. Yang, Y. Zhang, Mater. Chem. Phys. 132 (2012) 233–238.",
                    "SS if Ω ≥ 1.1 and δ(CN12) ≤ 6.6 %, otherwise MP.",
                         name="Ω–δ solid solution criterion",
                         note="Empirical solid-solution region; outside this region the calculator reports MP rather than assigning a unique competing phase."),
    "M2": ModelInfo("M2", "Guo et al.", "Model 2 – Guo et al. (2013)",
                    "S. Guo, Q. Hu, C. Ng, C.T. Liu, Intermetallics 41 (2013) 96–103.",
                    "SS if δ ≤ 6.6 % and −11.6 ≤ ΔHmix ≤ 3.2 kJ/mol; MG (amorphous) if δ > 6.4 % and "
                    "ΔHmix < −12.2 kJ/mol; otherwise MP.",
                         name="δ–ΔH<sub>mix</sub> empirical phase-selection map",
                         note="For as-cast alloys: solid solution inside the printed δ–ΔH<sub>mix</sub> window, amorphous phase (MG) where δ and ΔH<sub>mix</sub> are both large, multi-phase (MP) otherwise. Guo's intermetallic region is bounded only graphically, so SS and IM are not separated here."),
    "M3": ModelInfo("M3", "Wang et al.", "Model 3 – Wang et al. (2015)",
                    "Z. Wang, Y. Huang, Y. Yang, J. Wang, C.T. Liu, Scr. Mater. 94 (2015) 28–31.",
                    "SS if γ < 1.175, otherwise MP.",
                         name="γ empirical atomic-size criterion",
                         note="A necessary size-mismatch condition, not a complete phase map. The 1.175 limit is Wang et al.'s empirical fit and is deliberately not refined."),
    "M4": ModelInfo("M4", "Singh et al.", "Model 4 – Singh et al. (2014)",
                    "A.K. Singh, N. Kumar, A. Dwivedi, A. Subramaniam, Intermetallics 53 (2014) 112–119.",
                    "SS if Λ > 0.96; SS+IM if 0.24 ≤ Λ ≤ 0.96; IM if Λ < 0.24 (Λ in J mol⁻¹ K⁻¹).",
                         name="Λ empirical enthalpy–entropy criterion",
                         note="Empirical Λ bands calibrated on as-cast HEAs. δ is the Guo & Liu 2011 radius set, so Λ is in J mol⁻¹ K⁻¹."),
    "M5": ModelInfo("M5", "Ye et al.", "Model 5 – Ye et al. (2015)",
                    "Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang, Scr. Mater. 104 (2015) 53–55.",
                    "SS if φ ≥ 20, otherwise MP.",
                         name="φ excess-entropy ordering criterion",
                         note="φ ≥ 20 separates a single solid solution from multi-phase; S<sub>E</sub> is the hard-sphere excess entropy averaged over the fcc and bcc packing factors."),
    "M6": ModelInfo("M6", "Troparevsky et al.", "Model 6 – Troparevsky et al. (2015)",
                    "M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks, Phys. Rev. X 5 "
                    "(2015) 011041.",
                    "SS if −T·ΔSmix < ΔHf(i,j) < 37 meV/atom for every binary; IM if any ΔHf is below the "
                    "lower bound; MP if only the upper bound is exceeded.",
                         name="ΔH<sub>f</sub> binary-window criterion",
                         note="Every binary pair in the composition must satisfy −T·ΔS<sub>mix</sub> &lt; ΔH<sub>f</sub>(i,j) &lt; 37 meV/atom; a pair below the lower bound is what drives IM."),
    "M7": ModelInfo("M7", "Senkov & Miracle", "Model 7 – Senkov & Miracle (2016)",
                    "O.N. Senkov, D.B. Miracle, J. Alloys Compd. 658 (2016) 603–607.",
                    "SS if ΔHmix − TΔSmix < ΔH_IM − k₂TΔSmix (k₂ = 0.6), i.e. k₁ < k₁cr(T) for ΔHmix < 0; "
                    "otherwise IM.",
                         name="ΔG solid-solution versus intermetallic criterion",
                         note="Compares solid-solution and intermetallic formation free energies at the assessment temperature. Derived for ΔH<sub>mix</sub> &lt; 0; other compositions are marked as an extrapolation."),
    "M8": ModelInfo("M8", "King et al.", "Model 8 – King et al. (2016)",
                    "D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie, Acta Mater. 104 (2016) 172–179.",
                     "SS if Φ ≥ 1, otherwise MP.  The δ ≤ 6.6 % screen is King §3.4’s candidate-generation filter, not part of the criterion; King §3.1 keeps NbTiV₂Zr — Φ > 1 with δ > 6.6 — in the success set.",
                          name="Φ thermodynamic stability criterion",
                          note="Φ ≥ 1 means forming a solid solution is thermodynamically preferred to an intermetallic. The δ ≤ 6.6 % screen is King §3.4's alloy-generation filter, not part of this criterion."),
}


# Evidence status of a verdict.  The label is always present; the status says how much weight it
# can carry, so the UI can separate a literature-defined prediction from an extrapolation or from
# one that rests on data the dataset itself flags as unreliable.
STATUS_IN_DOMAIN = "in_domain"          # the criterion applies as the publication defines it
STATUS_EXTRAPOLATED = "extrapolated"    # evaluated outside the criterion's stated domain
STATUS_DATA_SUSPECT = "data_suspect"    # a binary value flagged as unreliable drives it
STATUSES = (STATUS_IN_DOMAIN, STATUS_EXTRAPOLATED, STATUS_DATA_SUSPECT)

# Why a verdict is N/A.  Classification only - the reason text is unchanged - so that collection
# analysis can count "missing data" apart from "undefined" (a zero denominator) and from results
# that could not be evaluated at all.  Missing data is never zero (AGENTS.md section 4).
NA_MISSING_DATA = "missing_data"        # an elemental property or binary pair is not in the dataset
NA_UNDEFINED = "undefined"              # the criterion's quantity has a zero denominator here
NA_ERROR = "error"                      # the composition could not be evaluated at all
NA_KINDS = (NA_MISSING_DATA, NA_UNDEFINED, NA_ERROR)


@dataclass
class ModelOutcome:
    key: str
    label: str
    reason: str | None = None
    values: dict = field(default_factory=dict)
    caution: str | None = None
    status: str = STATUS_IN_DOMAIN
    na_kind: str | None = None      # NA_* when label is N/A, else None

    def __post_init__(self):
        if self.label == NA and self.na_kind is None:
            self.na_kind = NA_MISSING_DATA
        if self.label != NA:
            self.na_kind = None


@dataclass
class AlloyResult:
    composition: dict[str, float]  # normalised atomic fractions, input order
    descriptors: dict = field(default_factory=dict)
    models: dict[str, ModelOutcome] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    temperature: float | None = None
    temperature_source: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def label(self, model_key: str) -> str:
        outcome = self.models.get(model_key)
        return outcome.label if outcome else NA

    def value(self, key: str):
        if key in self.descriptors:
            return self.descriptors[key]
        if key in self.models:
            return self.models[key].label
        return None


class CompositionError(ValueError):
    """Raised for compositions that cannot be evaluated at all."""


# ---------------------------------------------------------------------- Miedema constants
# Miedema/Bakker (1998) classification. P depends on the pair class (Bakker Appendix; de Boer et al.
# 1988): TM-TM 14.2, non-TM/non-TM 10.7, mixed 12.35; Q/P = 9.4; R/P = product of element factors.
_MIED_TRANSITION = {
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu",
    "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag",
    "La", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au",
    "Th", "U", "Pu",
}
_MIED_NONTRANSITION = {
    "Li", "Be", "B", "C", "N", "Na", "Mg", "Al", "Si", "P", "K", "Ca", "Zn", "Ga", "Ge", "As",
    "Rb", "Sr", "Cd", "In", "Sn", "Sb", "Cs", "Ba", "Hg", "Tl", "Pb", "Bi",
}
_MIED_R_TRANSITION = {
    "Sc": 0.7, "Ti": 1.0, "V": 1.0, "Cr": 1.0, "Mn": 1.0, "Fe": 1.0, "Co": 1.0, "Ni": 1.0, "Cu": 0.3,
    "Y": 0.7, "Zr": 1.0, "Nb": 1.0, "Mo": 1.0, "Tc": 1.0, "Ru": 1.0, "Rh": 1.0, "Pd": 1.0, "Ag": 0.15,
    "La": 0.7, "Hf": 1.0, "Ta": 1.0, "W": 1.0, "Re": 1.0, "Os": 1.0, "Ir": 1.0, "Pt": 1.0, "Au": 0.3,
    "Th": 0.7, "U": 1.0, "Pu": 1.0,
}
_MIED_R_NONTRANSITION = {
    "Li": 0.0, "Be": 0.4, "B": 1.9, "C": 2.1, "N": 2.3, "Na": 0.0, "Mg": 0.4, "Al": 1.9, "Si": 2.1,
    "P": 2.3, "K": 0.0, "Zn": 1.4, "Ga": 1.9, "Ge": 2.1, "As": 2.3, "Rb": 0.0, "Cd": 1.4, "In": 1.9,
    "Sn": 2.1, "Sb": 2.3, "Cs": 0.0, "Hg": 1.4, "Tl": 1.9, "Pb": 2.1, "Bi": 2.3,
}
# Volume-correction coefficient a (Bakker 1998, Eq. for V^{2/3} alloy).
_MIED_A_014 = {"Li", "Na", "K", "Rb", "Cs"}
_MIED_A_010 = {"Be", "Mg", "Zn", "Cd", "Hg"}
_MIED_A_007 = {"Cu", "Ag", "Au", "Al", "Ga", "In", "Tl", "Sc", "Y", "La"}
# Structural (lattice-stability) contribution applies only to two transition metals with
# 3 <= z <= 10 (Bakker 1998, Part I §5.2 and Part II Eq. 51). Noble metals (z = 11) excluded.
_STRUCT_TRANSITION = _MIED_TRANSITION - {"Cu", "Ag", "Au"}
# Niessen/Miedema lattice-stability curves (kJ/mol) vs valence z (Bakker 1998 Fig. 6).
_Z_GRID = (3.0, 4.0, 5.0, 5.5, 6.0, 7.0, 8.0, 8.5, 9.0, 10.0)
_E_HCP = (-2.4, -2.5, 10.0, 15.0, 13.0, -5.0, -10.5, -11.0, -8.0, -1.0)
_E_FCC = (-2.0, -1.5, 9.0, 14.0, 11.0, -3.0, -9.5, -11.0, -9.0, -2.0)
_E_BCC = (2.2, 2.0, -9.5, -14.5, -12.0, 4.0, 10.0, 11.0, 8.5, 1.5)
_MIEDEMA_KEYS = ("work_function_phi", "n_ws", "molar_volume", "bulk_modulus", "shear_modulus", "nvalence")


def _interp(z: float, curve: tuple[float, ...]) -> float | None:
    if z < _Z_GRID[0] - 1e-12 or z > _Z_GRID[-1] + 1e-12:
        return None
    for i in range(len(_Z_GRID) - 1):
        z1, z2 = _Z_GRID[i], _Z_GRID[i + 1]
        if z1 - 1e-12 <= z <= z2 + 1e-12:
            t = (z - z1) / (z2 - z1)
            return curve[i] + t * (curve[i + 1] - curve[i])
    return None


@lru_cache(maxsize=4096)
def lattice_stability(z: float) -> float | None:
    """Most negative of the hcp/fcc/bcc lattice stabilities at valence ``z`` (Bakker Eq. 54)."""
    vals = [_interp(z, c) for c in (_E_HCP, _E_FCC, _E_BCC)]
    if any(v is None for v in vals):
        return None
    return min(vals)


def vec_structure(vec: float) -> str:
    """Guo et al., J. Appl. Phys. 109 (2011) 103505: VEC >= 8 FCC, VEC < 6.87 BCC."""
    if vec >= 8.0:
        return "FCC"
    if vec < 6.87:
        return "BCC"
    return "BCC + FCC"


class Engine:
    """Thermodynamic / empirical HEA calculation engine (descriptors + models M1–M8)."""

    def __init__(self, datasets: Datasets | None = None):
        self.data = datasets or default_datasets()
        self._inter_cache: dict[tuple[str, str], float] = {}
        self._elastic_cache: dict[tuple[str, str], float] = {}

    # ================================================================== public API
    def calculate(self, composition: dict, *, annealing_temperature: float | None = None,
                  tcrit_fraction: float = DEFAULT_TCRIT_FRACTION) -> AlloyResult:
        """Evaluate one composition.

        ``composition`` maps element symbols to non-negative amounts in any proportional unit
        (atomic ratio, at.% or atomic fraction). Zero amounts are dropped.
        ``annealing_temperature`` (K) is used by M6 and M7; when omitted
        ``tcrit_fraction * Tm`` is used and reported as an estimate.
        """
        try:
            c = self.normalise(composition)
        except CompositionError as exc:
            return AlloyResult(composition={}, error=str(exc))
        res = AlloyResult(composition=c)
        try:
            self._descriptors(res)
            self._temperature(res, annealing_temperature, tcrit_fraction)
            self._models(res)
        except Exception as exc:  # defensive: one bad composition must not stop a sweep
            res.error = f"Calculation failed: {exc}"
        return res

    def normalise(self, composition: dict) -> dict[str, float]:
        if not composition:
            raise CompositionError("Composition is empty.")
        comp: dict[str, float] = {}
        for el, amount in composition.items():
            el = str(el).strip()
            if not self.data.is_element(el):
                raise CompositionError(f"Unknown element symbol '{el}'.")
            try:
                value = float(amount)
            except (TypeError, ValueError):
                raise CompositionError(f"Invalid amount for {el}: {amount!r}.") from None
            if not math.isfinite(value) or value < 0:
                raise CompositionError(f"Invalid amount for {el}: {amount!r}.")
            if value > 0:
                comp[el] = comp.get(el, 0.0) + value
        total = sum(comp.values())
        if total <= 0:
            raise CompositionError("Total amount must be greater than zero.")
        if len(comp) < 2:
            raise CompositionError("At least two elements with non-zero amounts are required.")
        return {el: v / total for el, v in comp.items()}

    # ================================================================== descriptors
    def _descriptors(self, res: AlloyResult) -> None:
        c = res.composition
        d = res.descriptors
        data = self.data
        els = list(c)
        pairs = list(itertools.combinations(els, 2))

        def weighted(key: str) -> float | None:
            vals = [data.prop(el, key) for el in els]
            if any(v is None for v in vals):
                return None
            return sum(c[el] * v for el, v in zip(els, vals))

        mean_mass = weighted("atomic_weight")
        mean_volume = weighted("molar_volume")
        d["mean_mass"] = mean_mass
        d["density"] = mean_mass / mean_volume if mean_mass and mean_volume else None
        d["tm"] = weighted("melting_point")
        d["vec"] = weighted("nvalence")
        d["cstr"] = vec_structure(d["vec"]) if d["vec"] is not None else None
        d["dsmix"] = -R * sum(x * math.log(x) for x in c.values() if x > 0)
        d["n_elements"] = len(els)

        # Liquid mixing enthalpy (Takeuchi & Inoue 2005), regular solution: dHmix = sum 4 H_ij c_i c_j.
        missing_mix = [(a, b) for a, b in pairs if data.mixing_enthalpy(a, b) is None]
        d["missing_mixing_pairs"] = missing_mix
        if missing_mix:
            d["dhmix"] = None
            res.warnings.append("Missing ΔHmix data for " + ", ".join(f"{a}–{b}" for a, b in missing_mix) + ".")
        else:
            d["dhmix"] = sum(4.0 * c[a] * c[b] * data.mixing_enthalpy(a, b) for a, b in pairs)

        # Omega (Yang & Zhang 2012) = Tm dSmix / |dHmix|.
        # A tabulated 0 kJ/mol pair (Takeuchi & Inoue define H/C/N-containing pairs as 0) makes the
        # denominator vanish.  Omega is then mathematically divergent, not large, so it is reported
        # as unavailable with an explicit reason rather than as an infinite number that would read
        # as an unusually good solid solution.
        d["omega_undefined"] = None
        if d["dhmix"] is None or d["tm"] is None:
            d["omega"] = None
        elif d["dhmix"] == 0:
            d["omega"] = None
            d["omega_undefined"] = ("ΔHmix = 0 (tabulated zero pair), so "
                                    "Ω = Tm·ΔS/|"
                                    "ΔHmix| is divergent and "
                                    "Ω is undefined.")
        else:
            d["omega"] = d["tm"] * d["dsmix"] / (abs(d["dhmix"]) * 1000.0)

        # Atomic-size mismatch with the two radius sets used by the source papers.
        radii_gl = {el: data.prop(el, "atomic_radius") for el in els}
        radii_cn12 = {el: data.prop(el, "atomic_radius_cn12") for el in els}
        d["delta"] = self._delta(c, radii_gl)
        d["delta_cn12"] = self._delta(c, radii_cn12)
        supplementary = [el for el in els if data.radius_is_supplementary(el)]
        d["radius_supplementary"] = supplementary
        if supplementary:
            res.warnings.append("Atomic radius of " + ", ".join(supplementary)
                                + " is not from Guo & Liu (2011) Table 1 (supplementary value used).")
        if d["delta_cn12"] is None:
            missing = [el for el in els if radii_cn12[el] is None]
            res.warnings.append("No Kittel CN12 radius for " + ", ".join(missing) + ".")

        d["gamma"] = self._gamma(c, radii_gl)
        # Singh et al. (2014): Lambda = dSmix / delta^2 (delta in %).
        d["lambda_undefined"] = None
        if d["delta"] is None:
            d["lambda"] = None
        elif d["delta"] == 0:
            # delta = 0 needs identical radii for every element; ΔSmix/δ^2 then diverges.
            d["lambda"] = None
            d["lambda_undefined"] = ("δ = 0, so Λ = ΔS/δ² is divergent "
                                    "and Λ is undefined.")
        else:
            d["lambda"] = d["dsmix"] / d["delta"] ** 2

        # Ye et al. (2015): excess entropy S_E (MCSL hard spheres, averaged over bcc/fcc packing).
        try:
            d["s_e"] = self._excess_entropy(c, radii_gl) if d["delta"] is not None else None
        except (ValueError, ZeroDivisionError, OverflowError):
            d["s_e"] = None
        if d["s_e"] is None or d["dhmix"] is None or not d["tm"]:
            d["phi_ye"] = None
        else:
            s_h = abs(d["dhmix"]) * 1000.0 / d["tm"]
            num = d["dsmix"] - s_h
            d["s_h"] = s_h
            d["phi_ye_undefined"] = None
            if abs(d["s_e"]) < 1e-15:
                # |S_E| -> 0 makes phi = (dS - S_H)/|S_E| divergent, not large.
                d["phi_ye"] = None
                d["phi_ye_undefined"] = ("S_E = 0, so φ = (ΔS - S_H)/|S_E| is "
                                        "divergent and φ is undefined.")
            else:
                d["phi_ye"] = num / abs(d["s_e"])

        # Troparevsky (2015) binary formation enthalpies, meV/atom.
        missing_form = [(a, b) for a, b in pairs if data.formation_enthalpy(a, b) is None]
        d["missing_formation_pairs"] = missing_form
        if missing_form:
            d["hf_min"] = d["hf_max"] = d["dhim"] = None
            d["hf_min_pair"] = d["hf_max_pair"] = None
            d["formation_asymmetric_pairs"] = []
            d["formation_suspect_pairs"] = []
            d["formation_suspect_values"] = {}
        else:
            hf = {(a, b): data.formation_enthalpy(a, b) for a, b in pairs}
            (pmin, vmin) = min(hf.items(), key=lambda kv: kv[1])
            (pmax, vmax) = max(hf.items(), key=lambda kv: kv[1])
            d["hf_min"], d["hf_min_pair"] = vmin, "–".join(pmin)
            d["hf_max"], d["hf_max_pair"] = vmax, "–".join(pmax)
            # Senkov & Miracle (2016) Eq. (9): dH_IM = sum 4 H_ij^IM c_i c_j, converted to kJ/mol.
            d["dhim"] = sum(4.0 * c[a] * c[b] * v for (a, b), v in hf.items()) * MEV_PER_ATOM_TO_KJ_PER_MOL
            asym = {item["pair"] for item in data.formation_metadata.get("asymmetric_entries", [])}
            used = [f"{a}-{b}" for a, b in pairs if f"{a}-{b}" in asym or f"{b}-{a}" in asym]
            d["formation_asymmetric_pairs"] = used
            # Cells the dataset itself flags as outside the source figure's range.  They are kept
            # exactly as transcribed (never replaced, never clamped) but must not silently drive
            # an authoritative verdict.
            suspect = data.formation_suspect_pairs()
            d["formation_suspect_pairs"] = [f"{a}-{b}" for a, b in pairs
                                             if f"{a}-{b}" in suspect or f"{b}-{a}" in suspect]
            d["formation_suspect_values"] = {p: data.formation_enthalpy(*p.split("-"))
                                             for p in d["formation_suspect_pairs"]}

        d["k1"] = None
        if d["dhim"] is not None and d["dhmix"] not in (None, 0):
            d["k1"] = d["dhim"] / d["dhmix"]

        self._king_descriptors(res)

    @staticmethod
    def _delta(c: dict, radii: dict) -> float | None:
        if any(radii[el] is None or radii[el] <= 0 for el in c):
            return None
        r_bar = sum(c[el] * radii[el] for el in c)
        return 100.0 * math.sqrt(sum(c[el] * (1.0 - radii[el] / r_bar) ** 2 for el in c))

    @staticmethod
    def _gamma(c: dict, radii: dict) -> float | None:
        """Wang et al. (2015) Eq. (3): gamma = omega_S / omega_L."""
        if any(radii[el] is None or radii[el] <= 0 for el in c):
            return None
        r_bar = sum(c[el] * radii[el] for el in c)
        r_s = min(radii[el] for el in c)
        r_l = max(radii[el] for el in c)

        def solid_angle(r: float) -> float:
            return 1.0 - math.sqrt(((r + r_bar) ** 2 - r_bar ** 2) / (r + r_bar) ** 2)

        return solid_angle(r_s) / solid_angle(r_l)

    def _excess_entropy(self, c: dict, radii: dict) -> float:
        """Ye et al. (2015) / Mansoori et al. (1971): S_E in J mol-1 K-1, mean of xi = 0.68 and 0.74."""
        els = list(c)
        d = {el: 2.0 * radii[el] for el in els}
        sum_cd3 = sum(c[el] * d[el] ** 3 for el in els)

        def se_kb(xi: float) -> float:
            xi_i = {el: xi * c[el] * d[el] ** 3 / sum_cd3 for el in els}
            y3 = sum((xi_i[el] / xi) ** (2.0 / 3.0) * c[el] ** (1.0 / 3.0) for el in els) ** 3
            k_sum = sum((xi_i[k] / xi) / d[k] for k in els)
            y1 = y2 = 0.0
            for i, j in itertools.combinations(els, 2):
                sq = math.sqrt(d[i] * d[j])
                delta_ij = (math.sqrt(xi_i[i] * xi_i[j]) / xi) * ((d[i] - d[j]) ** 2 / (d[i] * d[j])) \
                    * math.sqrt(c[i] * c[j])
                y1 += delta_ij * (d[i] + d[j]) / sq
                y2 += delta_ij * sq * k_sum
            z = (1 + xi + xi ** 2 - 3 * xi * (y1 + y2 * xi) - xi ** 3 * y3) / (1 - xi) ** 3
            if z <= 0:
                raise ValueError("non-physical compressibility")
            f_ex = (-1.5 * (1 - y1 + y2 + y3) + (3 * y2 + 2 * y3) / (1 - xi)
                    + 1.5 * (1 - y1 - y2 - y3 / 3.0) / (1 - xi) ** 2 + (y3 - 1) * math.log(1 - xi))
            return (f_ex - math.log(z) - (3 - 2 * xi) / (1 - xi) ** 2 + 3
                    + math.log((1 + xi + xi ** 2 - xi ** 3) / (1 - xi) ** 3))

        return R * 0.5 * (se_kb(0.68) + se_kb(0.74))

    # ------------------------------------------------------------------ King / Miedema
    def miedema_available(self, el: str) -> bool:
        return all(self.data.prop(el, k) is not None for k in _MIEDEMA_KEYS) and (
            el in _MIED_TRANSITION or el in _MIED_NONTRANSITION)

    def _pqr(self, a: str, b: str) -> tuple[float, float, float]:
        ta, tb = a in _MIED_TRANSITION, b in _MIED_TRANSITION
        if ta and tb:
            p, r_over_p = 14.2, 0.0
        elif not ta and not tb:
            p, r_over_p = 10.7, 0.0
        else:
            t, n = (a, b) if ta else (b, a)
            if t not in _MIED_R_TRANSITION or n not in _MIED_R_NONTRANSITION:
                raise ValueError(f"Miedema R/P factor unavailable for {a}–{b}")
            p, r_over_p = 12.35, _MIED_R_TRANSITION[t] * _MIED_R_NONTRANSITION[n]
        return p, 9.4 * p, p * r_over_p

    @staticmethod
    def _volume_coefficient(el: str) -> float:
        if el in _MIED_A_014:
            return 0.14
        if el in _MIED_A_010:
            return 0.10
        if el in _MIED_A_007:
            return 0.07
        return 0.04

    def interfacial_enthalpy(self, a: str, b: str) -> float:
        """dH_inter(A in B), kJ per mole of A (Bakker 1998 Eq. 1; King et al. Eq. S4).

        Infinite dilution with Miedema's volume correction V_A^{2/3}[1 + a(phi_A - phi_B)].
        Reproduces Bakker Table A2 within +/-2.1 kJ/mol for all 840 transition-metal pairs.
        """
        key = (a, b)
        if key in self._inter_cache:
            return self._inter_cache[key]
        p_ = self.data.prop
        va, phi_a, phi_b = p_(a, "molar_volume"), p_(a, "work_function_phi"), p_(b, "work_function_phi")
        na, nb = p_(a, "n_ws"), p_(b, "n_ws")
        p, q, r = self._pqr(a, b)
        v23 = va ** (2.0 / 3.0) * (1.0 + self._volume_coefficient(a) * (phi_a - phi_b))
        den = 0.5 * (na ** (-1.0 / 3.0) + nb ** (-1.0 / 3.0))
        value = v23 / den * (-p * (phi_a - phi_b) ** 2 + q * (na ** (1.0 / 3.0) - nb ** (1.0 / 3.0)) ** 2 - r)
        self._inter_cache[key] = value
        return value

    def elastic_enthalpy(self, a: str, b: str) -> float:
        """dH_elastic(A in B), kJ per mole of A (Eshelby; Bakker Eq. 28; King Eqs. S5–S6)."""
        key = (a, b)
        if key in self._elastic_cache:
            return self._elastic_cache[key]
        p_ = self.data.prop
        va, vb = p_(a, "molar_volume"), p_(b, "molar_volume")
        phi_a, phi_b = p_(a, "work_function_phi"), p_(b, "work_function_phi")
        na, nb = p_(a, "n_ws"), p_(b, "n_ws")
        ka, gb = p_(a, "bulk_modulus"), p_(b, "shear_modulus")
        alpha = 1.5 * va ** (2.0 / 3.0) / (na ** (-1.0 / 3.0) + nb ** (-1.0 / 3.0))
        wa = va + alpha * (phi_a - phi_b) / na
        wb = vb - alpha * (phi_a - phi_b) / nb
        den = 3.0 * ka * wb + 4.0 * gb * wa
        if den == 0:
            raise ValueError(f"elastic denominator zero for {a} in {b}")
        # K, G in 1e10 Pa and W in cm3/mol: (1e10 Pa)(1e-6 m3/mol) = 10 kJ/mol.
        value = 10.0 * 2.0 * ka * gb * (wa - wb) ** 2 / den
        self._elastic_cache[key] = value
        return value

    def _structural(self, a: str, b: str, ca: float, cb: float) -> float:
        """Bakker Eq. (54): H_struct(<z>) - [c_A H_struct(z_A) + c_B H_struct(z_B)]; TM-TM only."""
        if a not in _STRUCT_TRANSITION or b not in _STRUCT_TRANSITION:
            return 0.0
        za, zb = self.data.prop(a, "nvalence"), self.data.prop(b, "nvalence")
        e_avg, e_a, e_b = lattice_stability(ca * za + cb * zb), lattice_stability(za), lattice_stability(zb)
        if e_avg is None or e_a is None or e_b is None:
            return 0.0
        return e_avg - ca * e_a - cb * e_b

    def binary_solid_solution_enthalpy(self, a: str, b: str, ca: float, cb: float) -> float:
        """King et al. Eqs. S1–S7 for a binary random solid solution, kJ per mole of atoms."""
        total = ca + cb
        ca, cb = ca / total, cb / total
        va23 = self.data.prop(a, "molar_volume") ** (2.0 / 3.0)
        vb23 = self.data.prop(b, "molar_volume") ** (2.0 / 3.0)
        den = ca * va23 + cb * vb23
        csa, csb = ca * va23 / den, cb * vb23 / den
        chem = ca * cb * (csb * self.interfacial_enthalpy(a, b) + csa * self.interfacial_enthalpy(b, a))
        elastic = ca * cb * (cb * self.elastic_enthalpy(a, b) + ca * self.elastic_enthalpy(b, a))
        return chem + elastic + self._structural(a, b, ca, cb)

    def binary_intermetallic_enthalpy(self, a: str, b: str, ca: float, cb: float) -> float:
        """King et al. Eqs. S9–S10 / Bakker Eq. 9: ordered compound, gamma = 8, kJ per mole of atoms.

        dH = c_A f_B^A dH_inter(A in B), f_B^A = c_B^s[1 + 8(c_A^s c_B^s)^2]; the A-in-B and B-in-A
        forms are averaged (best match to King's CrNi/CuFe/AlNi benchmarks; see audit M8).
        """
        total = ca + cb
        ca, cb = ca / total, cb / total
        va23 = self.data.prop(a, "molar_volume") ** (2.0 / 3.0)
        vb23 = self.data.prop(b, "molar_volume") ** (2.0 / 3.0)
        den = ca * va23 + cb * vb23
        csa, csb = ca * va23 / den, cb * vb23 / den
        order = 1.0 + 8.0 * (csa * csb) ** 2
        h_a = ca * csb * order * self.interfacial_enthalpy(a, b)
        h_b = cb * csa * order * self.interfacial_enthalpy(b, a)
        return 0.5 * (h_a + h_b)

    def _king_descriptors(self, res: AlloyResult) -> None:
        c = res.composition
        d = res.descriptors
        d["phi_king"] = d["dg_ss"] = d["dg_max"] = d["dh_ss_king"] = None
        d["king_pair"] = None
        missing = [el for el in c if not self.miedema_available(el)]
        if missing:
            d["king_missing"] = missing
            return
        try:
            h_ss = 0.0
            for i, xi in c.items():  # King Eq. S8 with x_k' = x_k / (1 - x_i)
                rem = 1.0 - xi
                for k, xk in c.items():
                    if k == i:
                        continue
                    h_ss += xi * (xk / rem) * self.binary_solid_solution_enthalpy(i, k, xi, xk)
            pair_h = [((a, b), self.binary_intermetallic_enthalpy(a, b, c[a], c[b]))
                      for a, b in itertools.combinations(c, 2)]
        except (ValueError, ZeroDivisionError, TypeError) as exc:
            d["king_missing"] = [str(exc)]
            return
        tm = d["tm"]
        dg_ss = h_ss - tm * d["dsmix"] / 1000.0
        pair, h_max = max(pair_h, key=lambda kv: abs(kv[1]))
        dg_max = h_max * max(1, len(c) // 2)  # extended to floor(N/2) disjoint pairs (King §2.1)
        d["dh_ss_king"] = h_ss
        d["dg_ss"] = dg_ss
        d["dg_max"] = dg_max
        d["dh_int_max"] = h_max
        d["king_pair"] = "–".join(pair)
        d["phi_king_undefined"] = None
        if dg_max == 0:
            # dG_max = 0 leaves Phi = dG_ss / -|dG_max| divergent.  Its sign would be a statement
            # about a zero denominator, not a physical prediction.
            d["phi_king"] = None
            d["phi_king_undefined"] = ("ΔG_max = 0, so Φ = "
                                       "ΔG_ss / -|ΔG_max| is divergent and "
                                       "Φ is undefined.")
        else:
            d["phi_king"] = dg_ss / (-abs(dg_max))

    # ================================================================== temperature
    @staticmethod
    def _temperature(res: AlloyResult, annealing_temperature, tcrit_fraction) -> None:
        if annealing_temperature is not None:
            res.temperature = float(annealing_temperature)
            res.temperature_source = "annealing temperature (user)"
        elif res.descriptors.get("tm"):
            res.temperature = tcrit_fraction * res.descriptors["tm"]
            res.temperature_source = f"estimated T = {tcrit_fraction:g}·Tm"
        d = res.descriptors
        d["t_assess"] = res.temperature
        t = res.temperature
        if t is not None and d.get("dhmix") not in (None, 0):
            d["k1cr"] = 1.0 + (1.0 - SENKOV_K2) * t * d["dsmix"] / (abs(d["dhmix"]) * 1000.0)
        else:
            d["k1cr"] = None
        d["hf_lower"] = -t * d["dsmix"] / MEV_PER_ATOM_TO_J_PER_MOL if t is not None else None

    # ================================================================== models
    def _models(self, res: AlloyResult) -> None:
        d = res.descriptors
        m = res.models
        caution_gl = None
        if d.get("radius_supplementary"):
            caution_gl = ("Radius of " + ", ".join(d["radius_supplementary"])
                          + " is not from Guo & Liu (2011); the model was calibrated with that set.")

        # M1 Yang & Zhang
        if d["omega"] is None:
            m["M1"] = ModelOutcome("M1", NA,
                                   d.get("omega_undefined") or "ΔHmix unavailable (missing binary data).",
                                   na_kind=NA_UNDEFINED if d.get("omega_undefined") else NA_MISSING_DATA)
        elif d["delta_cn12"] is None:
            m["M1"] = ModelOutcome("M1", NA, "Kittel CN12 radius unavailable.")
        else:
            ok = _ge(d["omega"], 1.1) and _le(d["delta_cn12"], 6.6)
            m["M1"] = ModelOutcome("M1", SS if ok else MP,
                                   values={"omega": d["omega"], "delta_cn12": d["delta_cn12"]})

        # M2 Guo et al.
        if d["dhmix"] is None:
            m["M2"] = ModelOutcome("M2", NA, "ΔHmix unavailable (missing binary data).")
        elif d["delta"] is None:
            m["M2"] = ModelOutcome("M2", NA, "Atomic radius unavailable.")
        else:
            dl, h = d["delta"], d["dhmix"]
            if _le(dl, 6.6) and _ge(h, -11.6) and _le(h, 3.2):
                lab = SS
            elif dl > 6.4 and h < -12.2:
                lab = MG
            else:
                lab = MP
            caution = caution_gl
            if lab == MP:
                # Guo Fig. 1 defines a third, intermetallic region between the solid-solution and
                # the metallic-glass regions, bounded only graphically.  It is not derivable from
                # the printed criteria, so this alloy is reported as "multiple phases" - correct as
                # a class - while stating that SS / IM / other cannot be separated here.
                caution = ((caution + "  ") if caution else "") + (
                    "Outside both published Guo criteria. Fig. 1 also defines an intermetallic "
                    "region bounded only graphically, so SS / IM / other is not separated here.")
            m["M2"] = ModelOutcome("M2", lab, values={"delta": dl, "dhmix": h}, caution=caution)

        # M3 Wang et al.
        if d["gamma"] is None:
            m["M3"] = ModelOutcome("M3", NA, "Atomic radius unavailable.")
        else:
            m["M3"] = ModelOutcome("M3", SS if d["gamma"] < 1.175 else MP,
                                   values={"gamma": d["gamma"]}, caution=caution_gl)

        # M4 Singh et al.
        lam = d["lambda"]
        if lam is None:
            m["M4"] = ModelOutcome("M4", NA, d.get("lambda_undefined") or "Atomic radius unavailable.",
                                   na_kind=NA_UNDEFINED if d.get("lambda_undefined") else NA_MISSING_DATA)
        else:
            lab = SS if lam > 0.96 else (SS_IM if lam >= 0.24 - _tol(0.24) else IM)
            m["M4"] = ModelOutcome("M4", lab, values={"lambda": lam}, caution=caution_gl)

        # M5 Ye et al.
        if d["phi_ye"] is None:
            reason = "ΔHmix unavailable (missing binary data)." if d["dhmix"] is None else "S_E could not be evaluated."
            kind = NA_MISSING_DATA if d["dhmix"] is None or d["delta"] is None else NA_UNDEFINED
            m["M5"] = ModelOutcome("M5", NA, reason, na_kind=kind)
        else:
            m["M5"] = ModelOutcome("M5", SS if d["phi_ye"] >= 20.0 - _tol(20.0) else MP,
                                   values={"phi": d["phi_ye"], "s_e": d["s_e"]},
                                   caution=caution_gl)

        t = res.temperature
        # M6 Troparevsky et al.
        if d["missing_formation_pairs"]:
            m["M6"] = ModelOutcome("M6", NA, "No Troparevsky formation enthalpy for "
                                   + ", ".join(f"{a}–{b}" for a, b in d["missing_formation_pairs"]) + ".")
        elif t is None:
            m["M6"] = ModelOutcome("M6", NA, "No temperature available.")
        else:
            # Troparevsky: a solid solution needs every dHf STRICTLY inside
            # (-T*dSmix, +37), so a cell sitting exactly on a bound violates it. The
            # tolerance only absorbs representation noise in the violating direction; it
            # never widens the window.
            low_bad = d["hf_min"] <= d["hf_lower"]
            high_bad = d["hf_max"] >= TROPAREVSKY_UPPER_MEV
            lab = IM if low_bad else (MP if high_bad else SS)
            status = STATUS_IN_DOMAIN
            notes = []
            if d.get("formation_asymmetric_pairs"):
                notes.append("Uses pair(s) printed asymmetrically in the published matrix: "
                             + ", ".join(d["formation_asymmetric_pairs"]) + ".")
            if d.get("formation_suspect_pairs"):
                notes.append("Verdict driven by binary value(s) the dataset flags as outside the "
                             "published figure's range and therefore unreliable: "
                             + ", ".join(f"{p} = {d['formation_suspect_values'][p]:g} meV/atom"
                                         for p in d["formation_suspect_pairs"]) + ".")
                status = STATUS_DATA_SUSPECT
            m["M6"] = ModelOutcome("M6", lab, values={"hf_min": d["hf_min"], "hf_max": d["hf_max"],
                                                      "lower": d["hf_lower"], "upper": TROPAREVSKY_UPPER_MEV,
                                                      "T": t},
                                   caution=("  ".join(notes) if notes else None), status=status)

        # M7 Senkov & Miracle
        if d["missing_formation_pairs"]:
            m["M7"] = ModelOutcome("M7", NA, "No Troparevsky formation enthalpy for "
                                   + ", ".join(f"{a}–{b}" for a, b in d["missing_formation_pairs"]) + ".")
        elif d["dhmix"] is None:
            m["M7"] = ModelOutcome("M7", NA, "ΔHmix unavailable (missing binary data).")
        elif t is None:
            m["M7"] = ModelOutcome("M7", NA, "No temperature available.")
        else:
            ts = t * d["dsmix"] / 1000.0
            g_ss = d["dhmix"] - ts
            g_im = d["dhim"] - SENKOV_K2 * ts
            lab = SS if g_ss < g_im else IM
            caution, status = None, STATUS_IN_DOMAIN
            # Senkov & Miracle 2016 Section 1.1 assumes the linear relations hold "for HEAs with
            # negative values of dHmix".  Outside that domain the verdict is an extrapolation, and
            # is labelled as one rather than presented as literature-defined.
            if d["dhmix"] >= 0:
                caution = ("Extrapolation: Senkov & Miracle (2016) derive this criterion for "
                           "ΔHmix < 0, but this alloy has "
                           "ΔHmix = %+.2f kJ/mol." % d["dhmix"])
                status = STATUS_EXTRAPOLATED
                if d["dhmix"] == 0:
                    caution += (" ΔHmix = 0 exactly (a tabulated zero pair), so the published "
                                "k₁ / k₁cr form is undefined and only the "
                                "ΔG form of Eq. (6) can be evaluated.")
            if d.get("formation_suspect_pairs"):
                extra = ("ΔH_IM is a weighted mean of the same matrix and is driven by binary "
                         "value(s) flagged as unreliable: "
                         + ", ".join(f"{p} = {d['formation_suspect_values'][p]:g} meV/atom"
                                     for p in d["formation_suspect_pairs"]) + ".")
                caution = (caution + "  " + extra) if caution else extra
                status = STATUS_DATA_SUSPECT
            m["M7"] = ModelOutcome("M7", lab,
                                   values={"k1": d["k1"], "k1cr": d["k1cr"], "g_ss": g_ss,
                                           "g_im": g_im, "T": t},
                                   caution=caution, status=status)

        # M8 King et al.
        if d["phi_king"] is None:
            reason = d.get("phi_king_undefined")
            if reason:
                m["M8"] = ModelOutcome("M8", NA, reason, na_kind=NA_UNDEFINED)
            else:
                missing = d.get("king_missing") or []
                m["M8"] = ModelOutcome("M8", NA, "Miedema parameters unavailable for "
                                       + ", ".join(missing) + ".")
        else:
            # King Section 3.1: a solid solution iff Phi >= 1.  Nothing else.  The d <= 6.6 % screen
            # belongs to Section 3.4, which describes how candidate alloys are generated, and King
            # explicitly keeps NbTiV2Zr - Phi > 1 with d > 6.6 - in the success set.
            ok = _ge(d["phi_king"], 1.0)
            m["M8"] = ModelOutcome("M8", SS if ok else MP,
                                   values={"phi": d["phi_king"], "dg_ss": d["dg_ss"],
                                           "dg_max": d["dg_max"]})

    # ================================================================== element support
    def model_support(self, element: str) -> dict[str, tuple[str, str]]:
        """Per-model data support for one element.

        Returns ``{model: (status, explanation)}`` with status one of ``ok``, ``warn`` (computable with
        supplementary data), ``pair`` (depends on the partner elements' binary data) or ``none``.
        """
        data = self.data
        out: dict[str, tuple[str, str]] = {}
        in_mix = element in data.mixing_elements
        supp = data.radius_is_supplementary(element)
        cn12 = data.prop(element, "atomic_radius_cn12") is not None
        in_form = element in data.formation_elements
        mied = self.miedema_available(element)

        def mix_status():
            return ("ok", "Takeuchi & Inoue (2005) ΔHmix available") if in_mix else \
                ("none", "Not in the Takeuchi & Inoue (2005) ΔHmix table")

        def gl_status(base):
            if base[0] != "ok":
                return base
            if supp:
                return "warn", "Atomic radius not from Guo & Liu (2011) — supplementary value"
            return base

        out["M1"] = mix_status() if not in_mix else (("ok", "ΔHmix and Kittel CN12 radius available") if cn12
                                                       else ("none", "No Kittel CN12 radius"))
        out["M2"] = gl_status(mix_status())
        out["M3"] = gl_status(("ok", "Atomic radius available"))
        out["M4"] = gl_status(("ok", "Atomic radius available"))
        out["M5"] = gl_status(mix_status())
        pair_msg = "Binary ΔHf available only for pairs within the 30-element Troparevsky set"
        out["M6"] = ("pair", pair_msg) if in_form else ("none", "Not in the Troparevsky (2015) matrix")
        if not in_form:
            out["M7"] = ("none", "Not in the Troparevsky (2015) matrix")
        elif not in_mix:
            out["M7"] = ("none", "Not in the Takeuchi & Inoue (2005) ΔHmix table")
        else:
            out["M7"] = ("pair", pair_msg)
        if not mied:
            out["M8"] = ("none", "Miedema parameters/classification unavailable")
        elif not cn12:
            out["M8"] = ("none", "No Kittel CN12 radius")
        else:
            out["M8"] = ("ok", "Miedema parameters available (Bakker 1998)")
        return out


@lru_cache(maxsize=1)
def default_engine() -> Engine:
    return Engine()
