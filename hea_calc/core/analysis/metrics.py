"""Descriptor and metric registry for Analysis (display only; no Qt, no equations evaluated).

Wording follows the approved Analysis documents: ``ANALYSIS_PANEL_SPECIFICATION.md`` section 4 (registry
and display precision), ``ANALYSIS_PLOTTING_SPECIFICATION.md`` section 2 (metric selector) and
``ANALYSIS_FIGMA_DESIGN_GUIDE.md`` frame 3 (descriptor groups).  Values always come from the engine:
the stored results table for collections, ``AlloyResult.descriptors`` for one composition.

Symbols are HTML (``ΔH<sub>mix</sub>``) with a plain-text twin for CSV and clipboard; units keep the
Unicode superscripts (``kJ mol⁻¹``) and are converted to ``<sup>`` by the UI where a font lacks them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..chunks import NUM_KEYS
from ..results import format_number

# ---------------------------------------------------------------------- groups (Frame 3 order)
G_MIXING = "Mixing thermodynamics"
G_SIZE = "Atomic size"
G_ELECTRONIC = "Electronic structure"
G_YE = "Excess entropy (Ye et al. 2015)"
G_BINARY = "Binary compounds (Troparevsky et al. 2015; Senkov & Miracle 2016)"
G_KING = "Miedema solid solution (King et al. 2016)"
G_PHYSICAL = "Physical"
GROUPS = (G_MIXING, G_SIZE, G_ELECTRONIC, G_YE, G_BINARY, G_KING, G_PHYSICAL)
# short section names for the metric selectors (plotting spec section 2)
GROUP_SHORT = {G_MIXING: "Mixing thermodynamics", G_SIZE: "Atomic size", G_ELECTRONIC: "Electronic structure",
               G_YE: "Excess entropy", G_BINARY: "Binary compounds", G_KING: "Miedema / King", G_PHYSICAL: "Physical"}

DATA_TAKEUCHI = "Takeuchi & Inoue (2005), 2,628 binary pairs"
DATA_GUO_LIU = "Guo & Liu (2011) atomic radii (supplementary values cautioned)"
DATA_KITTEL = "Kittel CN12 (12-coordination) radii"
DATA_TROP = "Troparevsky et al. (2015) DFT formation enthalpies, 30 elements, 435 pairs"
DATA_MIEDEMA = "Bakker (1998) Miedema parameters"
DATA_ELEMENTS = "Elemental property table of the calculator"


@dataclass(frozen=True)
class Descriptor:
    key: str                 # AlloyResult.descriptors key; also the results-table column when stored
    name: str                # scientific name ("Mixing enthalpy")
    symbol: str              # HTML symbol ("ΔH<sub>mix</sub>"); "" for none
    plain: str               # plain-text symbol ("ΔHmix")
    unit: str                # "" = dimensionless (shown as "–")
    group: str
    decimals: int            # display precision (panel spec 4.3)
    definition: str          # Toggletip "Definition"
    equation: str = ""       # Toggletip "Equation" (HTML)
    data: str = ""           # Toggletip "Data"
    undefined: str = ""      # when the value is undefined rather than missing
    undefined_sql: str = ""  # SQL condition (over results ``r``) that makes a NULL value "undefined"
    log_default: bool = False
    stored: bool = True      # a results-table column (plottable / collection statistics)
    pair_key: str = ""       # descriptor naming the pair the value belongs to (shown in the name)
    source_note: str = ""    # radius set / source, appended to axis titles where two variants exist

    @property
    def unit_text(self) -> str:
        return self.unit or "–"

    def selector_text(self) -> str:
        """Plotting spec section 2: "Symbol — descriptive name (unit)"."""
        unit = self.unit or "–"
        return f"{self.symbol or self.plain} — {self.name} ({unit})"

    def axis_title(self) -> str:
        unit = self.unit or "–"
        title = f"{self.symbol or self.plain} ({unit})"
        return f"{title} — {self.source_note}" if self.source_note else title

    def plain_title(self) -> str:
        return f"{self.plain} ({self.unit or '-'})"

    @property
    def unit_plain(self) -> str:
        """The unit without superscript minus signs (for controls that cannot render rich text)."""
        return UNIT_PLAIN.get(self.unit, self.unit) or "–"


# Units written with a solidus for plain-text controls (check boxes, native titles): IBM Plex lacks the
# superscript minus glyph at small sizes.
UNIT_PLAIN = {"kJ mol⁻¹": "kJ/mol", "J mol⁻¹ K⁻¹": "J/(mol·K)", "meV atom⁻¹": "meV/atom", "g cm⁻³": "g/cm³",
              "g mol⁻¹": "g/mol"}


_D = Descriptor
DESCRIPTORS_LIST: list[Descriptor] = [
    # ---- mixing thermodynamics
    _D("dhmix", "Mixing enthalpy", "ΔH<sub>mix</sub>", "ΔHmix", "kJ mol⁻¹", G_MIXING, 2,
       "Regular-solution mixing enthalpy of the liquid.",
       "ΔH<sub>mix</sub> = Σ<sub>i&lt;j</sub> 4 c<sub>i</sub> c<sub>j</sub> ΔH<sub>ij</sub><sup>mix</sup>", DATA_TAKEUCHI),
    _D("dsmix", "Ideal mixing entropy", "ΔS<sub>mix</sub>", "ΔSmix", "J mol⁻¹ K⁻¹", G_MIXING, 2,
       "Ideal configurational entropy of mixing.", "ΔS<sub>mix</sub> = −R Σ c<sub>i</sub> ln c<sub>i</sub>",
       "Composition only"),
    _D("tm", "Melting temperature, rule of mixtures", "T<sub>m</sub>", "Tm", "K", G_MIXING, 0,
       "Concentration-weighted mean of the elemental melting points.", "T<sub>m</sub> = Σ c<sub>i</sub> T<sub>m,i</sub>",
       DATA_ELEMENTS),
    _D("omega", "Entropy–enthalpy ratio", "Ω", "Ω", "", G_MIXING, 2,
       "Ratio of the entropic to the enthalpic term at the melting temperature. Used by M1.",
       "Ω = T<sub>m</sub>ΔS<sub>mix</sub>/|ΔH<sub>mix</sub>|", DATA_TAKEUCHI,
       "Undefined when ΔH<sub>mix</sub> = 0.", "r.dhmix = 0"),
    # ---- atomic size
    _D("delta", "Size mismatch — Guo & Liu radii", "δ", "δ", "%", G_SIZE, 2,
       "Atomic-size mismatch with the Guo & Liu (2011) radii. Used by M2, M4 and M5. Not the same quantity as "
       "δ<sub>CN12</sub> (Kittel radii, used by M1).",
       "δ = 100 √(Σ c<sub>i</sub> (1 − r<sub>i</sub>/r̄)²)", DATA_GUO_LIU, source_note="Guo & Liu radii"),
    _D("delta_cn12", "Size mismatch — Kittel CN12 radii", "δ<sub>CN12</sub>", "δCN12", "%", G_SIZE, 2,
       "Atomic-size mismatch with Kittel's 12-coordination radii. Used by M1. (King et al. used a δ ≤ 6.6 % screen only to "
       "generate candidate alloys; it is not part of M8, which uses no radius.) Not the "
       "same quantity as δ (Guo & Liu radii, used by M2, M4, M5).",
       "δ<sub>CN12</sub> = 100 √(Σ c<sub>i</sub> (1 − r<sub>i</sub>/r̄)²)", DATA_KITTEL, source_note="Kittel CN12 radii"),
    _D("gamma", "Solid-angle ratio", "γ", "γ", "", G_SIZE, 4,
       "Ratio of the solid angles of the smallest and the largest atom. Used by M3.",
       "γ = ω<sub>S</sub>/ω<sub>L</sub>, ω = 1 − √[((r + r̄)² − r̄²)/(r + r̄)²]", DATA_GUO_LIU),
    _D("lambda", "Entropy–mismatch parameter", "Λ", "Λ", "J mol⁻¹ K⁻¹", G_SIZE, 3,
       "Mixing entropy divided by the squared size mismatch (δ in %). Used by M4.",
       "Λ = ΔS<sub>mix</sub>/δ²", DATA_GUO_LIU, "Undefined when δ = 0.", "r.delta = 0", log_default=True),
    # ---- electronic
    _D("vec", "Valence electron concentration", "VEC", "VEC", "", G_ELECTRONIC, 2,
       "Concentration-weighted mean number of valence electrons.", "VEC = Σ c<sub>i</sub> VEC<sub>i</sub>",
       DATA_ELEMENTS),
    _D("cstr", "Crystal structure (VEC rule)", "", "Crystal structure", "", G_ELECTRONIC, 0,
       "VEC rule of Guo et al. (2011): FCC if VEC ≥ 8.0, BCC if VEC < 6.87, otherwise BCC + FCC. "
       "A tendency, not an observed phase.", "", "Guo et al., J. Appl. Phys. 109 (2011) 103505", stored=True),
    # ---- Ye excess entropy
    _D("s_e", "Excess entropy", "S<sub>E</sub>", "SE", "J mol⁻¹ K⁻¹", G_YE, 3,
       "Hard-sphere excess entropy of mixing, mean of the bcc (0.68) and fcc (0.74) packing fractions.",
       "Mansoori et al. (1971) hard-sphere mixture", DATA_GUO_LIU),
    _D("s_h", "Enthalpy-equivalent entropy", "S<sub>H</sub>", "SH", "J mol⁻¹ K⁻¹", G_YE, 3,
       "Mixing enthalpy expressed as an entropy at the melting temperature.",
       "S<sub>H</sub> = |ΔH<sub>mix</sub>|/T<sub>m</sub>", DATA_TAKEUCHI, stored=False),
    _D("phi_ye", "Ye parameter", "φ", "φ", "", G_YE, 2,
       "Entropy balance of Ye et al. (2015). Used by M5.",
       "φ = (S<sub>c</sub> − S<sub>H</sub>)/|S<sub>E</sub>|", DATA_GUO_LIU + "; " + DATA_TAKEUCHI,
       "Undefined when S<sub>E</sub> = 0.", "abs(r.s_e) < 1e-15", log_default=True),
    # ---- binary compounds
    _D("t_assess", "Assessment temperature", "T", "T", "K", G_BINARY, 0,
       "Temperature used by M6 and M7: the annealing temperature from Calculation settings, or 0.55·T<sub>m</sub>.",
       "T = T<sub>anneal</sub>, or 0.55 T<sub>m</sub>", "Calculation settings"),
    _D("hf_lower", "Entropic lower bound", "−TΔS<sub>mix</sub>", "-TΔSmix", "meV atom⁻¹", G_BINARY, 1,
       "Lower bound of the Troparevsky window at the assessment temperature.",
       "−T ΔS<sub>mix</sub> (1 meV atom⁻¹ = 96.485 J mol⁻¹)", "Calculation settings"),
    _D("hf_min", "Most negative binary ΔH<sub>f</sub>", "ΔH<sub>f,min</sub>", "ΔHf,min", "meV atom⁻¹", G_BINARY, 0,
       "Most negative formation enthalpy of the binary compounds of the composition's element pairs.",
       "min<sub>i&lt;j</sub> ΔH<sub>f</sub>(i,j)", DATA_TROP, pair_key="hf_min_pair"),
    _D("hf_max", "Most positive binary ΔH<sub>f</sub>", "ΔH<sub>f,max</sub>", "ΔHf,max", "meV atom⁻¹", G_BINARY, 0,
       "Most positive formation enthalpy of the binary compounds of the composition's element pairs.",
       "max<sub>i&lt;j</sub> ΔH<sub>f</sub>(i,j)", DATA_TROP, pair_key="hf_max_pair"),
    _D("dhim", "Intermetallic formation enthalpy", "ΔH<sub>IM</sub>", "ΔHIM", "kJ mol⁻¹", G_BINARY, 2,
       "Concentration-weighted binary compound formation enthalpy (Senkov & Miracle Eq. 9).",
       "ΔH<sub>IM</sub> = Σ<sub>i&lt;j</sub> 4 c<sub>i</sub> c<sub>j</sub> ΔH<sub>f,ij</sub>", DATA_TROP),
    _D("k1", "Enthalpy ratio", "k<sub>1</sub>", "k1", "", G_BINARY, 2,
       "Ratio of the intermetallic to the mixing enthalpy. Used by M7.",
       "k<sub>1</sub> = ΔH<sub>IM</sub>/ΔH<sub>mix</sub>", DATA_TROP + "; " + DATA_TAKEUCHI,
       "Undefined when ΔH<sub>mix</sub> = 0.", "r.dhmix = 0"),
    _D("k1cr", "Critical enthalpy ratio", "k<sub>1</sub><sup>cr</sup>", "k1cr", "", G_BINARY, 2,
       "Critical value of k<sub>1</sub> at the assessment temperature, k<sub>2</sub> = 0.6. Used by M7.",
       "k<sub>1</sub><sup>cr</sup> = 1 + (1 − k<sub>2</sub>) TΔS<sub>mix</sub>/|ΔH<sub>mix</sub>|", DATA_TAKEUCHI,
       "Undefined when ΔH<sub>mix</sub> = 0.", "r.dhmix = 0"),
    # ---- King / Miedema
    _D("dh_ss_king", "Solid-solution formation enthalpy", "ΔH<sub>ss</sub>", "ΔHss", "kJ mol⁻¹", G_KING, 2,
       "Formation enthalpy of the disordered solid solution from Miedema's model (King Eq. S8).",
       "ΔH<sub>ss</sub> = Σ<sub>i</sub> Σ<sub>k≠i</sub> x<sub>i</sub> x<sub>k</sub>′ ΔH<sub>ik</sub><sup>ss</sup>", DATA_MIEDEMA,
       stored=False),
    _D("dg_ss", "Solid-solution Gibbs energy at T<sub>m</sub>", "ΔG<sub>ss</sub>", "ΔGss", "kJ mol⁻¹", G_KING, 2,
       "Gibbs energy of the disordered solid solution at the melting temperature.",
       "ΔG<sub>ss</sub> = ΔH<sub>ss</sub> − T<sub>m</sub>ΔS<sub>mix</sub>", DATA_MIEDEMA),
    _D("dh_int_max", "Strongest binary", "ΔH<sub>int,max</sub>", "ΔHint,max", "kJ mol⁻¹", G_KING, 2,
       "Ordered binary compound enthalpy of largest magnitude among the element pairs.",
       "max |ΔH<sub>ij</sub><sup>int</sup>|", DATA_MIEDEMA, stored=False, pair_key="king_pair"),
    _D("dg_max", "Competing intermetallic energy", "ΔG<sub>max</sub>", "ΔGmax", "kJ mol⁻¹", G_KING, 2,
       "Strongest binary compound energy scaled to the number of disjoint pairs.",
       "ΔG<sub>max</sub> = ΔH<sub>int,max</sub> × ⌊N/2⌋", DATA_MIEDEMA),
    _D("phi_king", "King stability parameter", "Φ", "Φ", "", G_KING, 2,
       "Solid-solution Gibbs energy relative to the competing intermetallic. Used by M8.",
       "Φ = ΔG<sub>ss</sub>/(−|ΔG<sub>max</sub>|)", DATA_MIEDEMA, "Undefined when ΔG<sub>max</sub> = 0.",
       "r.dg_max = 0"),
    # ---- physical
    _D("mean_mass", "Mean atomic mass", "M̄", "M", "g mol⁻¹", G_PHYSICAL, 2,
       "Concentration-weighted mean atomic mass.", "M̄ = Σ c<sub>i</sub> M<sub>i</sub>", DATA_ELEMENTS),
    _D("density", "Density, rule of mixtures", "ρ", "ρ", "g cm⁻³", G_PHYSICAL, 2,
       "Rule-of-mixtures density from atomic masses and molar volumes; excess volume is ignored.",
       "ρ = Σ c<sub>i</sub> M<sub>i</sub> / Σ c<sub>i</sub> V<sub>i</sub>", DATA_ELEMENTS),
]
DESCRIPTORS: dict[str, Descriptor] = {d.key: d for d in DESCRIPTORS_LIST}

# Key descriptors of the Composition Overview (Frame 2), in order, with the frame's short row labels.
KEY_DESCRIPTORS = ("dhmix", "dsmix", "tm", "omega", "delta", "vec")
KEY_LABELS = {"dhmix": "Mixing enthalpy", "dsmix": "Mixing entropy", "tm": "Melting temperature",
              "omega": "Entropy–enthalpy ratio", "delta": "Size mismatch — Guo & Liu radii",
              "vec": "Valence electron conc."}

# Numeric metrics available for collections (stored columns), in selector order: every one of them is
# statistics-eligible (Statistics table, histogram, box plot) - no descriptor is privileged.
METRIC_KEYS: tuple[str, ...] = tuple(d.key for d in DESCRIPTORS_LIST if d.stored and d.key in NUM_KEYS)
STATISTICS_ELIGIBLE = METRIC_KEYS
# The Statistics table's initial rows (the user chooses any of METRIC_KEYS).  Both size-mismatch descriptors are
# listed: δ (Guo & Liu radii) and δCN12 (Kittel radii) are different quantities, neither stands for the other.
STATS_DEFAULT = ("dhmix", "dsmix", "omega", "delta", "delta_cn12", "vec", "phi_king")


def descriptor(key: str) -> Descriptor:
    return DESCRIPTORS[key]


# ---------------------------------------------------------------------- formatting
def decimals_for(key: str, value) -> int:
    d = DESCRIPTORS.get(key)
    n = d.decimals if d else 2
    if key == "phi_ye" and isinstance(value, (int, float)) and math.isfinite(value) and abs(value) >= 100:
        return 0                                           # panel spec 4.3: φ ≥ 100 -> 3 significant figures
    return n


def format_value(key: str, value, full: bool = False) -> str:
    """Display text of a descriptor value (typographic minus; "N/A" for missing)."""
    if isinstance(value, str):
        return value
    if full and isinstance(value, float) and math.isfinite(value):
        return format_number(value, 6)
    return format_number(value, decimals_for(key, value))


def format_sig(value, sig: int = 4) -> str:
    """Value with ``sig`` significant figures (Model details criterion values)."""
    if value is None or isinstance(value, str):
        return format_number(value)
    if not math.isfinite(value):
        return format_number(value)
    if value == 0:
        return "0"
    digits = max(0, sig - 1 - int(math.floor(math.log10(abs(value)))))
    return format_number(value, digits)


def with_unit(text: str, unit: str) -> str:
    return text if not unit or text in ("N/A", "Not available") else f"{text} {unit}"


def full_precision(value) -> str:
    """Exactly as calculated (engine repr), for value Tooltips."""
    if isinstance(value, float) and math.isfinite(value):
        return repr(value).replace("-", "−")
    return format_number(value)
