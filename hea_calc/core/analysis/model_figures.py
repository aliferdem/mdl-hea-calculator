"""Model figures of Model details (no Qt) - 2026-10-28.

One figure per model, built from the model's documented criterion and, where the publication tabulates them, the
published values of its alloys (``data/model_figures.json``, transcribed from the papers' tables with DOI and table
location; ``tools/build_model_figures.py``).  Nothing here is digitised from a published figure and nothing is
invented: a figure whose paper gives too few tabulated values is an *illustrative* criterion figure from the
documented equation and thresholds, and says so.

Kinds: ``scatter`` (x, y published values), ``strip`` (one published value per alloy along x), ``curves`` (the
criterion's bounds as functions of temperature).  ``provenance`` is ``"publication"`` (the points are published
tabulated values) or ``"illustrative"``.  Thresholds are the criterion's own (``MODELS[k].criterion``; a test checks
every one against that text; two come from the engine's named constants).  The presentation
(``ui/analysis/model_figure.py``) only draws what this returns.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..engine import SENKOV_K2, TROPAREVSKY_UPPER_MEV

DATA = Path(__file__).resolve().parents[3] / "data" / "model_figures.json"
K_B_MEV = 0.08617333262        # Boltzmann constant, meV K⁻¹ (CODATA 2018)

REFS = {
    "M1": "Yang & Zhang, Mater. Chem. Phys. 132 (2012) 233, Table 1 (doi 10.1016/j.matchemphys.2011.11.021)",
    "M2": "Guo et al., Intermetallics 41 (2013) 96, Table 1 (doi 10.1016/j.intermet.2013.05.002)",
    "M3": "Wang et al., Scripta Mater. 94 (2015) 28, Table 1 (doi 10.1016/j.scriptamat.2014.09.010)",
    "M4": "Singh et al., Intermetallics 53 (2014) 112, Table 1 (doi 10.1016/j.intermet.2014.04.019)",
    "M5": "Ye et al., Scripta Mater. 104 (2015) 53, p. 54 (doi 10.1016/j.scriptamat.2015.03.023)",
    "M6": "Troparevsky et al., Phys. Rev. X 5 (2015) 011041 (doi 10.1103/PhysRevX.5.011041), criterion",
    "M7": "Senkov & Miracle, J. Alloys Compd. 658 (2016) 603, Table 1 (doi 10.1016/j.jallcom.2015.10.279)",
    "M8": "King et al., Acta Mater. 104 (2016) 172, Section 2.1 / 3.2.1 (doi 10.1016/j.actamat.2015.11.040)",
}


@dataclass
class Line:
    kind: str                 # "v" (x = value), "h" (y = value), "diag" (y = x), "curve" (xs, ys)
    value: float = 0.0
    label: str = ""
    xs: list = field(default_factory=list)
    ys: list = field(default_factory=list)


@dataclass
class Region:
    """A class region of the criterion: x0..x1 × y0..y1 (None = open), shaded in the class colour."""
    cls: str
    x0: float | None = None
    x1: float | None = None
    y0: float | None = None
    y1: float | None = None


@dataclass
class Figure:
    model: str
    kind: str
    title: str
    x_label: str
    y_label: str
    provenance: str                       # "publication" | "illustrative"
    caption: str
    source: str
    points: list = field(default_factory=list)      # dicts: x, y, cls, label
    lines: list = field(default_factory=list)
    regions: list = field(default_factory=list)
    log_y: bool = False
    log_x: bool = False
    x_key: str | None = None              # descriptor of the current composition along x / y (marker)
    y_key: str | None = None
    x_range: tuple | None = None
    y_range: tuple | None = None


@lru_cache(maxsize=1)
def published() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))["models"]


def _points(model: str) -> list[dict]:
    out = []
    for i, p in enumerate(published()[model]["points"]):
        out.append({"x": float(p["x"]), "y": None if p["y"] is None else float(p["y"]), "cls": p["c"] or "",
                    "label": p["f"], "index": i})
    return out


def figure(model: str) -> Figure:
    """The figure of ``model`` (see the module docstring)."""
    return _BUILDERS[model]()


def _pub_caption(model: str, n: int, what: str) -> str:
    return (f"Reconstructed from the {n} alloys tabulated in the publication ({what}); colours are the published "
            "classes. The lines are the model's thresholds. This is an original chart of the tabulated values, not "
            "a reproduction of the publisher's figure.")


def _m1() -> Figure:
    pts = _points("M1")
    return Figure("M1", "scatter", "Ω against δ (CN12)", "δ (CN12) (%)", "Ω", "publication",
                  _pub_caption("M1", len(pts), "δ, Ω"), REFS["M1"], pts,
                  [Line("v", 6.6, "δ = 6.6 %"), Line("h", 1.1, "Ω = 1.1")], [Region("SS", None, 6.6, 1.1, None)],
                  log_y=True, x_key="delta_cn12", y_key="omega")


def _m2() -> Figure:
    pts = _points("M2")
    return Figure("M2", "scatter", "ΔHmix against δ", "δ (%)", "ΔHmix (kJ/mol)", "publication",
                  _pub_caption("M2", len(pts), "δ, ΔHmix"), REFS["M2"], pts,
                  [Line("v", 6.6, "δ = 6.6 %"), Line("h", -11.6, "−11.6"), Line("h", -12.2, "−12.2"),
                   Line("h", 3.2, "3.2"), Line("v", 6.4, "δ = 6.4 %")],
                  [Region("SS", None, 6.6, -11.6, 3.2), Region("MG", 6.4, None, None, -12.2)],
                  x_key="delta", y_key="dhmix")


def _m3() -> Figure:
    pts = _points("M3")
    return Figure("M3", "strip", "γ of the tabulated alloys", "γ", "", "publication",
                  _pub_caption("M3", len(pts), "γ; only these alloys have γ printed") , REFS["M3"], pts,
                  [Line("v", 1.175, "γ = 1.175")], [Region("SS", None, 1.175)], x_key="gamma")


def _m4() -> Figure:
    pts = _points("M4")
    return Figure("M4", "scatter", "Λ against δ", "δ (%)", "Λ (J/(mol K))", "publication",
                  _pub_caption("M4", len(pts), "δ, Λ"), REFS["M4"], pts,
                  [Line("h", 0.96, "Λ = 0.96"), Line("h", 0.24, "Λ = 0.24")],
                  [Region("SS", None, None, 0.96, None), Region("SS+IM", None, None, 0.24, 0.96),
                   Region("IM", None, None, None, 0.24)], log_y=True, x_key="delta", y_key="lambda")


def _m5() -> Figure:
    pts = _points("M5")
    return Figure("M5", "strip", "φ and the solid-solution limit", "φ", "", "illustrative",
                  f"Illustrative criterion chart: the paper prints φ for {len(pts)} alloys in its text, too few for a "
                  "data figure; the line is the model's threshold φ = 20.", REFS["M5"], pts,
                  [Line("v", 20.0, "φ = 20")], [Region("SS", 20.0, None)], x_key="phi_ye", x_range=(1, 1000),
                  log_x=True)


def _m6() -> Figure:
    ts = [300.0 + 25.0 * i for i in range(69)]               # 300 ... 2000 K
    lines = [Line("h", TROPAREVSKY_UPPER_MEV, f"{TROPAREVSKY_UPPER_MEV:g} meV/atom")]
    for n in (3, 4, 5, 6):
        lines.append(Line("curve", label=f"−TΔSmix, {n} elements", xs=ts,
                          ys=[-K_B_MEV * t * math.log(n) for t in ts]))
    return Figure("M6", "curves", "The formation-enthalpy window", "T (K)", "ΔHf (meV/atom)", "illustrative",
                  "Illustrative criterion chart from the model's equations: every binary ΔHf of an alloy must lie "
                  "between the lower bound −TΔSmix (ideal entropy of an equiatomic alloy, kB T ln N per atom) and "
                  f"{TROPAREVSKY_UPPER_MEV:g} meV/atom. No published values are plotted.", REFS["M6"], [],
                  lines, [], x_range=(300, 2000), y_range=(-320, 80))


M7_RANGE = ((0.0, 6.0), (-2.0, 6.0))      # where the tabulated alloys cluster; the rest are counted in the caption


def _m7() -> Figure:
    pts = _points("M7")
    (xa, xb), (ya, yb) = M7_RANGE
    out = sum(1 for p in pts if not (xa <= p["x"] <= xb and ya <= p["y"] <= yb))
    extra = (f" {out} of the {len(pts)} alloys lie outside the plotted range (k₁cr up to "
             f"{max(p['x'] for p in pts):g}, k₁ down to {min(p['y'] for p in pts):g}) and are not drawn." if out else "")
    return Figure("M7", "scatter", "k₁ against k₁cr", "k₁cr", "k₁", "publication",
                  _pub_caption("M7", len(pts), "k₁, k₁cr") + f" Solid solutions lie below the diagonal k₁ = k₁cr "
                  f"(k₂ = {SENKOV_K2:g})." + extra, REFS["M7"], pts, [Line("diag", 0.0, "k₁ = k₁cr")], [],
                  x_key="k1cr", y_key="k1", x_range=M7_RANGE[0], y_range=M7_RANGE[1])


def _m8() -> Figure:
    pts = _points("M8")
    return Figure("M8", "strip", "Φ and the solid-solution limit", "Φ", "", "illustrative",
                  f"Illustrative criterion chart: the paper works {len(pts)} examples in its text; the "
                  "supplementary table is not part of the sources. The line is the model's threshold Φ = 1.",
                  REFS["M8"], pts, [Line("v", 1.0, "Φ = 1")], [Region("SS", 1.0, None)], x_key="phi_king",
                  x_range=(0, 2))


_BUILDERS = {"M1": _m1, "M2": _m2, "M3": _m3, "M4": _m4, "M5": _m5, "M6": _m6, "M7": _m7, "M8": _m8}

# The thresholds each figure draws, for the check against the criterion text (tests)
THRESHOLDS = {"M1": (6.6, 1.1), "M2": (6.6, -11.6, 3.2, 6.4, -12.2), "M3": (1.175,), "M4": (0.96, 0.24),
              "M5": (20.0,), "M6": (TROPAREVSKY_UPPER_MEV,), "M7": (SENKOV_K2,), "M8": (1.0,)}


def evidence_table() -> list[tuple[str, str, str, int]]:
    """(model, provenance, source, number of published points) - the implementation report's evidence table."""
    return [(k, figure(k).provenance, REFS[k], len(figure(k).points)) for k in _BUILDERS]


__all__ = ["Figure", "Line", "Region", "figure", "published", "evidence_table", "THRESHOLDS", "REFS", "K_B_MEV"]
