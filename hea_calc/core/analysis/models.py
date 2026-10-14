"""Model presentation registry for Analysis (no Qt; no thresholds are evaluated here).

Titles, class sets, the criterion-value and threshold *texts* of the Models table (design guide frame 4)
and the Model details copy (purpose, data, limitations, not-available conditions) taken from the
approved Help page ``MODEL_SUPPORT_HELP_CONTENT.md`` section 3.  The verdicts themselves always come
from the engine; this module only formats the values the engine produced.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..engine import (MODEL_KEYS, MODELS, NA, NA_ERROR, NA_MISSING_DATA, NA_UNDEFINED, STATUS_DATA_SUSPECT,
                      STATUS_EXTRAPOLATED, STATUS_IN_DOMAIN, TROPAREVSKY_UPPER_MEV)
from ..results import format_number
from .metrics import format_value

YEARS = {"M1": 2012, "M2": 2013, "M3": 2015, "M4": 2014, "M5": 2015, "M6": 2015, "M7": 2016, "M8": 2016}

# Result classes each model can produce (plotting spec section 3; data contract section 10).
CLASSES: dict[str, tuple[str, ...]] = {
    "M1": ("SS", "MP"), "M2": ("SS", "MP", "MG"), "M3": ("SS", "MP"), "M4": ("SS", "SS+IM", "IM"),
    "M5": ("SS", "MP"), "M6": ("SS", "MP", "IM"), "M7": ("SS", "IM"), "M8": ("SS", "MP"),
}
ALL_CLASSES = ("SS", "SS+IM", "MP", "IM", "MG")

STATUS_LABELS = {STATUS_IN_DOMAIN: "In domain", STATUS_EXTRAPOLATED: "Extrapolated",
                 STATUS_DATA_SUSPECT: "Flagged binary data"}
STATUS_SHORT = {STATUS_IN_DOMAIN: "Within the published domain",
                STATUS_EXTRAPOLATED: "Extrapolated beyond the published domain",
                STATUS_DATA_SUSPECT: "Verdict uses flagged binary data"}
NA_LABELS = {NA_MISSING_DATA: "Not available — missing data", NA_UNDEFINED: "Not available — undefined",
             NA_ERROR: "Not evaluable"}
CLASS_NAMES = {"SS": "solid solution", "MP": "multiple phases", "IM": "intermetallic",
               "SS+IM": "solid solution + intermetallic", "MG": "metallic glass (amorphous)", NA: "not available"}


def title(key: str, short: bool = False) -> str:
    """"M1 · Yang & Zhang (2012)" (or "M1 · Yang & Zhang")."""
    base = f"{key} · {MODELS[key].short}"
    return base if short else f"{base} ({YEARS[key]})"


@dataclass(frozen=True)
class ModelHelp:
    purpose: str
    data: str
    not_available: str
    limitations: str
    interpretation: str = ""


# MODEL_SUPPORT_HELP_CONTENT.md section 3 (final copy); interpretation lines from the design guide frame 5
# where given, otherwise the engine's own one-sentence note (``MODELS[k].note``).
HELP: dict[str, ModelHelp] = {
    "M1": ModelHelp(
        "Separates solid-solution-forming compositions from those that form intermetallics or segregate, using "
        "the balance of mixing entropy and enthalpy at the melting temperature and the atomic-size mismatch.",
        "Melting point; Kittel 12-coordination radius; Takeuchi & Inoue (2005) liquid mixing enthalpies.",
        "A pair lacks a Takeuchi & Inoue value, an element lacks a Kittel radius, or ΔH<sub>mix</sub> is exactly "
        "zero (Ω undefined).",
        "Empirical boundary fitted to as-cast alloys; MP does not distinguish intermetallics from segregated "
        "solid solutions."),
    "M2": ModelHelp(
        "Locates a composition on the empirical δ–ΔH<sub>mix</sub> map that separates solid solutions, "
        "intermetallic-containing alloys and the amorphous phase.",
        "Guo & Liu (2011) atomic radii; Takeuchi & Inoue (2005) liquid mixing enthalpies.",
        "A pair lacks a Takeuchi & Inoue value or an element lacks an atomic radius.",
        "The publication bounds its intermetallic region only graphically; the calculator therefore reports MP "
        "outside both printed criteria and does not separate intermetallics from other multiphase states."),
    "M3": ModelHelp(
        "Measures the packing strain around the smallest and largest atoms through the ratio of their solid angles.",
        "Guo & Liu (2011) atomic radii. The publication does not name its radius set; the calculator uses the Guo & "
        "Liu radii of the same research group.",
        "An element lacks an atomic radius.",
        "A necessary geometric condition, not a complete phase-selection rule."),
    "M4": ModelHelp(
        "Compares the mixing entropy with the squared atomic-size mismatch.",
        "Guo & Liu (2011) atomic radii.",
        "A radius is missing or δ = 0 (Λ undefined).",
        "Empirical Λ bands calibrated on as-cast HEAs."),
    "M5": ModelHelp(
        "Balances the configurational entropy against the enthalpy-equivalent entropy, normalised by the "
        "hard-sphere excess entropy.",
        "Guo & Liu (2011) atomic radii; melting points; Takeuchi & Inoue (2005) liquid mixing enthalpies.",
        "ΔH<sub>mix</sub> is missing, or S<sub>E</sub> cannot be evaluated (φ undefined).",
        "For nearly equal atomic sizes |S<sub>E</sub>| approaches zero and φ becomes very large and sensitive to "
        "small radius differences; the verdict is then robust, the numerical value is not."),
    "M6": ModelHelp(
        "A composition forms a single solid solution if no binary compound is so stable that it precipitates and "
        "no pair is so unfavourable that it separates.",
        "Troparevsky et al. (2015), Supplemental Material, Appendix A — DFT formation enthalpies of the lowest-energy "
        "binary compounds, 30 elements.",
        "Any element is outside the 30-element set.",
        "Binary compounds only. Temperature 0.55·T<sub>m</sub> is used when no annealing temperature is set.",
        "A binary compound more stable than −TΔS<sub>mix</sub> would precipitate (IM); a pair above 37 meV atom⁻¹ "
        "would separate (MP)."),
    "M7": ModelHelp(
        "Compares the free energies of the solid solution and of the competing intermetallic at the assessment "
        "temperature.",
        "Takeuchi & Inoue (2005) mixing enthalpies; Troparevsky et al. (2015) formation enthalpies.",
        "Any element is outside the Troparevsky set, or ΔH<sub>mix</sub> is missing.",
        "The authors derive the criterion for alloys with ΔH<sub>mix</sub> &lt; 0. For ΔH<sub>mix</sub> ≥ 0 the "
        "calculator evaluates the same free-energy inequality and marks the result Extrapolated."),
    "M8": ModelHelp(
        "Compares the Gibbs energy of the disordered solid solution at T<sub>m</sub> with the most stable "
        "competing binary compound, both from Miedema's model.",
        "Miedema parameters (Bakker 1998): work function, electron density, molar volume, bulk and shear modulus, "
        "valence.",
        "An element has no Miedema parameters, or Ca, Sr, Ba are combined with transition metals.",
        "The δ ≤ 6.6 % screen used by the authors to generate candidate alloys is not part of the criterion."),
}

# Descriptors behind each criterion (Model details "Evaluated values"; Overview "Related descriptors").
CRITERION_KEYS: dict[str, tuple[str, ...]] = {
    "M1": ("omega", "delta_cn12"), "M2": ("delta", "dhmix"), "M3": ("gamma",), "M4": ("lambda",),
    "M5": ("phi_ye", "s_e", "dsmix", "s_h"), "M6": ("t_assess", "hf_lower", "hf_min", "hf_max"),
    "M7": ("t_assess", "dhmix", "dhim", "k1", "k1cr"), "M8": ("phi_king", "dg_ss", "dg_max", "dh_int_max"),
}


def _v(d: Mapping, key: str):
    v = d.get(key)
    return v if isinstance(v, (int, float)) else None


def criterion_value_text(key: str, d: Mapping, label: str) -> str:
    """Models-table "Criterion value" (HTML) from descriptor values ``d``."""
    if label in (NA, None, ""):
        return "Not available"
    f = format_value
    if key == "M1":
        return f"Ω {f('omega', _v(d, 'omega'))}; δ<sub>CN12</sub> {f('delta_cn12', _v(d, 'delta_cn12'))} %"
    if key == "M2":
        return f"δ {f('delta', _v(d, 'delta'))} %; ΔH<sub>mix</sub> {f('dhmix', _v(d, 'dhmix'))}"
    if key == "M3":
        return f"γ {f('gamma', _v(d, 'gamma'))}"
    if key == "M4":
        return f"Λ {f('lambda', _v(d, 'lambda'))}"
    if key == "M5":
        return f"φ {f('phi_ye', _v(d, 'phi_ye'))}"
    if key == "M6":
        return f"ΔH<sub>f</sub> {f('hf_min', _v(d, 'hf_min'))} … {f('hf_max', _v(d, 'hf_max'))} meV atom⁻¹"
    if key == "M7":
        h = _v(d, "dhmix")
        if h is not None and h >= 0:
            sign = "+" if h > 0 else ""
            return f"ΔH<sub>mix</sub> {sign}{f('dhmix', h)} kJ mol⁻¹; ΔG form"
        return f"k<sub>1</sub> {f('k1', _v(d, 'k1'))} vs k<sub>1</sub><sup>cr</sup> {f('k1cr', _v(d, 'k1cr'))}"
    if key == "M8":
        return f"Φ {f('phi_king', _v(d, 'phi_king'))}"
    return ""


def threshold_text(key: str, d: Mapping | None = None) -> str:
    """Models-table "Threshold" (HTML) - the published rule for a solid solution."""
    if key == "M1":
        return "Ω ≥ 1.1 and δ<sub>CN12</sub> ≤ 6.6 %"
    if key == "M2":
        return "δ ≤ 6.6 %; −11.6 ≤ ΔH<sub>mix</sub> ≤ 3.2"
    if key == "M3":
        return "γ &lt; 1.175"
    if key == "M4":
        return "Λ &gt; 0.96"
    if key == "M5":
        return "φ ≥ 20"
    if key == "M6":
        low = _v(d or {}, "hf_lower")
        lo = format_number(low, 1) if low is not None else "−TΔS<sub>mix</sub>"
        return f"{lo} &lt; ΔH<sub>f</sub> &lt; {TROPAREVSKY_UPPER_MEV:g}"
    if key == "M7":
        return "k<sub>1</sub> &lt; k<sub>1</sub><sup>cr</sup>"
    if key == "M8":
        return "Φ ≥ 1"
    return ""


def plain(html_text: str) -> str:
    """Strip the few HTML constructs used here (CSV / clipboard / accessible names)."""
    out = html_text
    for a, b in (("<sub>", ""), ("</sub>", ""), ("<sup>", ""), ("</sup>", ""), ("&lt;", "<"), ("&gt;", ">"),
                 ("&amp;", "&"), ("<i>", ""), ("</i>", ""), ("<b>", ""), ("</b>", "")):
        out = out.replace(a, b)
    return out


def summary_line(labels: Mapping[str, str]) -> tuple[int, str]:
    """("8 of 8 evaluated", "8 SS") pieces of the Overview/Models summary."""
    evaluated = [lab for lab in labels.values() if lab not in (NA, None, "")]
    counts: dict[str, int] = {}
    for lab in evaluated:
        counts[lab] = counts.get(lab, 0) + 1
    parts = [f"{counts[c]} {c}" for c in ALL_CLASSES if c in counts]
    return len(evaluated), " · ".join(parts)


_ = (MODEL_KEYS,)
