"""Plot configuration, validity rules, defaults and representation disclosure (no Qt).

``ANALYSIS_PLOTTING_SPECIFICATION.md`` sections 1 (types and invalid configurations), 2 (defaults by run type)
and 4 (representation).  A configuration that violates a rule is *invalid* with a message the plot area
shows - it is never drawn approximately.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..repository import RunInfo
from .queries import (DIM_BLOCK, DIM_FAMILY, DIM_NONE, PlotMetric, is_dimension, run_metrics)

SCATTER, LINE, HISTOGRAM, BOX, HEATMAP, BAR_GROUPED, BAR_STACKED = (
    "scatter", "line", "histogram", "box", "heatmap", "bar_grouped", "bar_stacked")
PLOT_TYPES = (SCATTER, LINE, HISTOGRAM, BOX, HEATMAP, BAR_STACKED, BAR_GROUPED)
TYPE_LABELS = {SCATTER: "Scatter", LINE: "Line (ordered by parameter)", HISTOGRAM: "Histogram", BOX: "Box plot",
               HEATMAP: "Heatmap (two parameters)", BAR_STACKED: "Stacked bars (model classes)",
               BAR_GROUPED: "Grouped bars (model classes)"}
TYPE_SHORT = {SCATTER: "Scatter", LINE: "Line", HISTOGRAM: "Histogram", BOX: "Box plot", HEATMAP: "Heatmap",
              BAR_STACKED: "Stacked bars", BAR_GROUPED: "Grouped bars"}

AUTO, RAW, SAMPLED, BINNED, AGGREGATED = "AUTO", "RAW", "SAMPLED", "BINNED", "AGGREGATED"
REPRESENTATION_LABELS = {AUTO: "Automatic", RAW: "All points", SAMPLED: "Sample", BINNED: "Binned"}
BIN_CHOICES = (50, 100, 200, 400)
BOX_MAX_GROUPS = 30


@dataclass(frozen=True)
class PlotConfiguration:
    type: str = SCATTER
    x: str = "delta"
    y: str = "dhmix"
    color: str = "model:M2"           # dimension, metric id or "none"
    value: str = "delta"              # heatmap value / binned colour
    group: str = DIM_FAMILY           # box plot / grouped bars
    model: str = "M2"                 # bar plots
    representation: str = AUTO
    bins: int = 200
    log_x: bool = False
    log_y: bool = False
    thresholds: bool = True           # model reference lines
    model_strip: bool = True          # line plots
    fixed: tuple = ()                 # ((variable metric id, value), ...) for line / heatmap
    seed: int = 1

    def with_(self, **kw) -> "PlotConfiguration":
        return replace(self, **kw)

    @property
    def fixed_dict(self) -> dict:
        return dict(self.fixed)


@dataclass(frozen=True)
class Validity:
    ok: bool
    title: str = ""
    message: str = ""
    fix: str = ""                      # label of the one-click fix ("Use scatter plot")


VALID = Validity(True)


def design_variables(info: RunInfo | None) -> list[PlotMetric]:
    return [m for m in run_metrics(info) if m.kind == "variable"]


def ordered_axes(info: RunInfo | None) -> list[PlotMetric]:
    return [m for m in run_metrics(info) if m.ordered]


def available_types(info: RunInfo | None) -> list[str]:
    """Plot types offered for a run (line / heatmap only with design variables)."""
    out = [SCATTER]
    ordered = ordered_axes(info)
    variables = design_variables(info)
    if info is not None and info.mode == "expression" and variables:
        out.append(LINE)
        if len(variables) >= 2:
            out.append(HEATMAP)
    elif info is not None and info.mode == "sweep" and ordered:
        out.append(LINE)                 # valid only for a single free axis; validity explains otherwise
    out += [HISTOGRAM, BOX, BAR_STACKED, BAR_GROUPED]
    return out


def default_config(info: RunInfo | None) -> PlotConfiguration:
    """Plotting spec section 2 defaults by run type."""
    if info is not None and info.mode == "expression":
        variables = design_variables(info)
        blocks = (info.source or {}).get("blocks") or []
        if len(blocks) > 1:
            return PlotConfiguration(SCATTER, "delta", "dhmix", DIM_BLOCK)
        if len(variables) == 1:
            return PlotConfiguration(LINE, variables[0].id, "vec", DIM_NONE)
        if len(variables) >= 2:
            fixed = tuple((v.id, 0.0) for v in variables[2:])
            return PlotConfiguration(HEATMAP, variables[0].id, variables[1].id, DIM_NONE, value="delta",
                                     fixed=fixed)
        return PlotConfiguration(SCATTER, "delta", "dhmix", DIM_BLOCK)
    if info is not None and info.mode == "sweep":
        return PlotConfiguration(SCATTER, "delta", "dhmix", "model:M2")
    return PlotConfiguration(SCATTER, "delta", "dhmix", DIM_FAMILY)


def validate(cfg: PlotConfiguration, info: RunInfo | None) -> Validity:
    """The plotting spec's invalid configurations (section 1) - each blocked with its message."""
    metrics = {m.id: m for m in run_metrics(info)}
    t = cfg.type
    if t == SCATTER:
        if cfg.x not in metrics or cfg.y not in metrics:
            return Validity(False, "Choose two numeric metrics", "A scatter plot needs a numeric metric on each axis.")
        if cfg.x == cfg.y:
            return Validity(False, "Choose two different metrics",
                            "Plotting a metric against itself shows no relationship.")
        if cfg.color not in (DIM_NONE, "") and not is_dimension(cfg.color) and cfg.color not in metrics:
            return Validity(False, "Unknown colour", "Choose a colour from the list.")
        return VALID
    if t == LINE:
        x = metrics.get(cfg.x)
        if x is None or not x.ordered:
            if info is not None and info.mode == "sweep":
                return Validity(False, "A line plot needs an ordered axis",
                                "Composition-space results with optional elements have no single ordering parameter. "
                                "Use a scatter plot, or choose an expression variable as X.", "Use scatter plot")
            return Validity(False, "A line plot needs an ordered axis",
                            "Choose an expression variable as X, or use a scatter plot.", "Use scatter plot")
        if info is not None and info.mode == "sweep":
            specs = (info.source or {}).get("specs", [])
            optional = any(not s.get("required", True) for s in specs)
            varying = [s["element"] for s in specs if s.get("min") != s.get("max")]
            if optional or varying != [cfg.x.split(":", 1)[-1]]:
                return Validity(False, "A line plot needs an ordered axis",
                                "Composition-space results with optional elements have no single ordering parameter. "
                                "Use a scatter plot, or choose an expression variable as X.", "Use scatter plot")
        if info is not None and info.mode == "expression":
            others = [v for v in design_variables(info) if v.id != cfg.x and v.id not in cfg.fixed_dict]
            if others:
                names = ", ".join(v.plain for v in others)
                return Validity(False, f"Fix {names} to plot a line along {metrics[cfg.x].plain}",
                                "A line connects compositions along one variable; every other variable must be "
                                "held at one value.")
            blocks = (info.source or {}).get("blocks") or []
            if len(blocks) > 1:
                return Validity(False, "Restrict the collection to one parametric block",
                                "Lines join compositions of one expression block only.")
        if cfg.y not in metrics or is_dimension(cfg.y):
            return Validity(False, "Choose a numeric metric for Y", "")
        return VALID
    if t == HEATMAP:
        x, y = metrics.get(cfg.x), metrics.get(cfg.y)
        if x is None or y is None or x.kind != "variable" or y.kind != "variable" or cfg.x == cfg.y:
            return Validity(False, "A heatmap needs two expression variables",
                            "Choose two different expression variables for X and Y, or use a scatter plot.",
                            "Use scatter plot")
        others = [v for v in design_variables(info) if v.id not in (cfg.x, cfg.y) and v.id not in cfg.fixed_dict]
        if others:
            return Validity(False, "Fix the other variables",
                            "A heatmap shows two variables; hold " + ", ".join(v.plain for v in others) + " at one value.")
        if cfg.value not in metrics and not is_dimension(cfg.value):
            return Validity(False, "Choose a value", "")
        return VALID
    if t == HISTOGRAM:
        if cfg.x not in metrics:
            return Validity(False, "Choose a numeric metric", "A histogram needs a numeric metric.")
        return VALID
    if t == BOX:
        if cfg.x not in metrics:
            return Validity(False, "Choose a numeric metric", "A box plot needs a numeric metric.")
        if not is_dimension(cfg.group) or cfg.group.startswith("status:"):
            return Validity(False, "Choose a grouping", "Box plots compare one metric across groups.")
        return VALID
    if t in (BAR_STACKED, BAR_GROUPED):
        if t == BAR_GROUPED and (not is_dimension(cfg.group) or cfg.group.startswith(("model:", "status:"))):
            return Validity(False, "Choose a grouping", "Grouped bars count one model's classes per group.")
        return VALID
    return Validity(False, "Unknown plot type", "")


def choose_representation(cfg: PlotConfiguration, n_valid: int, raw_limit: int) -> str:
    """Scatter representation: the requested one, or RAW up to ``raw_limit`` valid points, else SAMPLED."""
    if cfg.type != SCATTER:
        return AGGREGATED if cfg.type in (BOX, BAR_GROUPED, BAR_STACKED) else RAW
    if cfg.representation in (RAW, SAMPLED, BINNED):
        return cfg.representation
    return RAW if n_valid <= raw_limit else SAMPLED


def representation_text(rep: str, *, shown: int = 0, population: int = 0, bins: tuple | None = None,
                        ordered_by: str = "", cells: int = 0, group: str = "") -> str:
    """The representation tag text (design guide 5.7) - every non-RAW plot discloses itself."""
    if rep == RAW and ordered_by:
        return f"All {shown:,} points · ordered by {ordered_by}"
    if rep == RAW:
        return f"All {shown:,} points"
    if rep == SAMPLED:
        return f"Sample · {shown:,} of {population:,} points"
    if rep == BINNED:
        bx, by = bins if bins and len(bins) == 2 else (bins[0] if bins else 0, 0)
        if by:
            return f"Binned · {bx} × {by} cells · {population:,} results"
        return f"Binned · {bx} bins · {population:,} results"
    if rep == "GRID":
        return f"All {cells:,} cells calculated"
    if rep == AGGREGATED:
        return f"Aggregated by {group}" if group else "Aggregated"
    return ""
