"""Result rows, column definitions, formatting, filtering and clipboard/TSV export.

Formatting only — values come from :class:`hea_calc.core.engine.AlloyResult`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .engine import MODEL_KEYS, MODELS, NA, AlloyResult


@dataclass(frozen=True)
class Column:
    key: str
    header: str            # plain-text header (clipboard / export)
    html: str              # rich header for the UI
    unit: str = ""
    kind: str = "num"      # "text" | "num" | "model"
    decimals: int = 2
    default: bool = False
    group: str = "Descriptors"
    tooltip: str = ""


COLUMNS: list[Column] = [
    Column("name", "Alloy", "Alloy", kind="text", default=True, group="Composition"),
    Column("composition", "Composition (at.%)", "Composition (at.%)", kind="text", group="Composition"),
    Column("density", "ρ (g/cm³)", "ρ", "g cm⁻³", default=True, group="Physical",
           tooltip="Rule-of-mixtures density ΣcᵢMᵢ / ΣcᵢVᵢ"),
    Column("tm", "Tm (K)", "T<sub>m</sub>", "K", default=True, group="Thermodynamic",
           tooltip="Rule-of-mixtures melting temperature"),
    Column("dhmix", "ΔHmix (kJ/mol)", "ΔH<sub>mix</sub>", "kJ mol⁻¹", default=True, group="Thermodynamic",
           tooltip="Regular-solution mixing enthalpy, Takeuchi & Inoue (2005) binaries"),
    Column("dsmix", "ΔSmix (J/mol·K)", "ΔS<sub>mix</sub>", "J mol⁻¹ K⁻¹", default=True, group="Thermodynamic",
           tooltip="Ideal configurational entropy −RΣcᵢ ln cᵢ"),
    Column("delta", "δ (%)", "δ", "%", default=True, group="Structural",
           tooltip="Atomic-size mismatch, Guo & Liu (2011) radii"),
    Column("delta_cn12", "δ CN12 (%)", "δ<sub>CN12</sub>", "%", group="Structural",
           tooltip="Atomic-size mismatch, Kittel CN12 radii (Yang & Zhang, King)"),
    Column("vec", "VEC", "VEC", default=True, group="Structural", tooltip="Valence electron concentration"),
    Column("cstr", "Cryst. Str.", "Cryst. Str.", kind="text", default=True, group="Structural",
           tooltip="VEC rule (Guo et al. 2011): FCC ≥ 8.0, BCC < 6.87"),
    Column("omega", "Ω", "Ω", group="Thermodynamic", tooltip="TmΔSmix/|ΔHmix| (Yang & Zhang 2012)"),
    Column("gamma", "γ", "γ", decimals=4, group="Structural", tooltip="Solid-angle ratio (Wang et al. 2015)"),
    Column("lambda", "Λ", "Λ", decimals=3, group="Structural", tooltip="ΔSmix/δ² (Singh et al. 2014)"),
    Column("phi_ye", "φ", "φ", group="Thermodynamic", tooltip="(Sc − S_H)/|S_E| (Ye et al. 2015)"),
    Column("s_e", "S_E (J/mol·K)", "S<sub>E</sub>", "J mol⁻¹ K⁻¹", decimals=4, group="Thermodynamic",
           tooltip="Excess entropy, mean of bcc/fcc packing (Ye et al. 2015)"),
    Column("hf_min", "ΔHf min (meV/atom)", "ΔH<sub>f,min</sub>", "meV atom⁻¹", decimals=0, group="Thermodynamic",
           tooltip="Most negative Troparevsky binary formation enthalpy"),
    Column("hf_max", "ΔHf max (meV/atom)", "ΔH<sub>f,max</sub>", "meV atom⁻¹", decimals=0, group="Thermodynamic",
           tooltip="Most positive Troparevsky binary formation enthalpy"),
    Column("hf_lower", "−TΔSmix (meV/atom)", "−TΔS<sub>mix</sub>", "meV atom⁻¹", decimals=1, group="Thermodynamic",
           tooltip="Troparevsky lower bound at the assessment temperature"),
    Column("t_assess", "T (K)", "T", "K", decimals=0, group="Thermodynamic",
           tooltip="Temperature used by M6/M7 (annealing temperature or 0.55·Tm)"),
    Column("dhim", "ΔH_IM (kJ/mol)", "ΔH<sub>IM</sub>", "kJ mol⁻¹", group="Thermodynamic",
           tooltip="Σ4cᵢcⱼΔHᵢⱼ^IM (Senkov & Miracle 2016)"),
    Column("k1", "k₁", "k<sub>1</sub>", group="Thermodynamic", tooltip="ΔH_IM/ΔHmix"),
    Column("k1cr", "k₁cr", "k<sub>1</sub><sup>cr</sup>", group="Thermodynamic",
           tooltip="1 + (1 − k₂)TΔSmix/|ΔHmix|, k₂ = 0.6"),
    Column("phi_king", "Φ", "Φ", group="Thermodynamic", tooltip="ΔG_ss / −|ΔG_max| (King et al. 2016)"),
    Column("dg_ss", "ΔG_ss (kJ/mol)", "ΔG<sub>ss</sub>", "kJ mol⁻¹", group="Thermodynamic"),
    Column("dg_max", "ΔG_max (kJ/mol)", "ΔG<sub>max</sub>", "kJ mol⁻¹", group="Thermodynamic"),
    Column("mean_mass", "M̄ (g/mol)", "M̄", "g mol⁻¹", group="Physical"),
] + [
    Column(k, k, k, kind="model", default=True, group="Models", tooltip=MODELS[k].title + ". " + MODELS[k].criterion)
    for k in MODEL_KEYS
]
COLUMN_BY_KEY = {c.key: c for c in COLUMNS}
DEFAULT_COLUMNS = [c.key for c in COLUMNS if c.default]


@dataclass
class ResultRow:
    """One row of the results table."""
    name: str
    input_amounts: dict[str, float]
    result: AlloyResult
    source: str = "single"          # single | sweep | expression | import
    variables: dict = field(default_factory=dict)
    row_id: int | None = None       # id in the ResultStore it was reproduced from, if any

    # Row protocol shared with store.StoredRow (formatting, filters, clipboard, export).
    def raw(self, key: str):
        if key == "name":
            return self.name
        if key == "composition":
            return composition_text(self.result.composition)
        return self.result.value(key)

    @property
    def ok(self) -> bool:
        return self.result.ok

    @property
    def error(self) -> str | None:
        return self.result.error

    @property
    def composition(self) -> dict[str, float]:
        return self.result.composition

    @property
    def warnings(self) -> list[str]:
        return list(self.result.warnings)

    def model_label(self, key: str) -> str:
        return self.result.label(key)

    def model_note(self, key: str) -> str:
        o = self.result.models.get(key)
        return (o.reason or o.caution or "") if o else ""


def composition_text(fractions: dict[str, float], decimals: int = 2) -> str:
    return " ".join(f"{el}{100 * v:.{decimals}f}" for el, v in fractions.items())


def format_number(value, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, str):
        return value
    if isinstance(value, float) and math.isinf(value):
        return "∞" if value > 0 else "−∞"
    if isinstance(value, float) and math.isnan(value):
        return "N/A"
    text = f"{value:.{decimals}f}"
    if text.startswith("-"):
        text = "−" + text[1:]  # typographic minus
    if text in ("−0", "−0.0", "−0.00", "−0.000", "−0.0000"):
        text = text[1:]
    return text


def format_cell(row: ResultRow, key: str) -> str:
    col = COLUMN_BY_KEY[key]
    if not row.ok and key not in ("name", "composition"):
        return "N/A"
    value = row.raw(key)
    if col.kind == "model":
        return value or NA
    if col.kind == "text":
        return "" if value is None else str(value)
    return format_number(value, col.decimals)


def full_precision(row: ResultRow, key: str) -> str:
    value = row.raw(key)
    if isinstance(value, float):
        if math.isinf(value) or math.isnan(value):
            return format_number(value)
        return repr(value)
    return "" if value is None else str(value)


def table_tsv(rows: list[ResultRow], keys: list[str]) -> str:
    """Clipboard text that pastes into Excel: tabs between columns, newlines between rows.

    Uses the visible headers, column order, row order and displayed values. Typographic minus signs are
    converted back to ASCII '-' so spreadsheets parse numbers.
    """
    def clean(text: str) -> str:
        return text.replace("\t", " ").replace("\r", " ").replace("\n", " ").replace("−", "-")

    lines = ["\t".join(clean(COLUMN_BY_KEY[k].header) for k in keys)]
    for row in rows:
        lines.append("\t".join(clean(format_cell(row, k)) for k in keys))
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------- filters
@dataclass
class RangeFilter:
    key: str
    minimum: float | None = None
    maximum: float | None = None

    def accepts(self, row: ResultRow) -> bool:
        v = row.raw(self.key)
        if not isinstance(v, (int, float)):
            return False
        if self.minimum is not None and v < self.minimum:
            return False
        if self.maximum is not None and v > self.maximum:
            return False
        return True


@dataclass
class ModelFilter:
    key: str
    labels: set[str]

    def accepts(self, row: ResultRow) -> bool:
        return row.model_label(self.key) in self.labels


@dataclass
class IdSetFilter:
    """Only the given results ("Show in results table" from an Analysis plot selection).

    ``table`` is a ``views.sqlite`` id table written by the view builder (SQL path); ``ids`` the same ids in
    memory (small: a plot selection), for the in-memory row protocol."""
    table: str
    ids: frozenset = frozenset()
    label: str = "Selected in Analysis"

    @property
    def count(self) -> int:
        return len(self.ids)

    def accepts(self, row) -> bool:
        rid = getattr(row, "id", None) or getattr(row, "row_id", None)
        return rid in self.ids


def apply_filters(rows: list[ResultRow], filters: list) -> list[ResultRow]:
    if not filters:
        return list(rows)
    return [r for r in rows if all(f.accepts(r) for f in filters)]
