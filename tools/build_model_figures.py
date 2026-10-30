"""Dev tool: build ``data/model_figures.json`` - the published tabulated values the Model details figures plot.

Source: ``tests/reference/published_benchmarks.json`` (values transcribed from the model publications' tables, each with
its DOI and table location; see that file's ``_metadata``).  Only published values are copied - no engine output, no
digitised figure points.  Run from the project root:

    .venv/Scripts/python.exe tools/build_model_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tests" / "reference" / "published_benchmarks.json"
OUT = ROOT / "data" / "model_figures.json"

# model -> (x key, y key or None) of the published values plotted
AXES = {"M1": ("delta_cn12", "omega"), "M2": ("delta", "dhmix"), "M3": ("gamma", None), "M4": ("delta", "lambda"),
        "M5": ("phi_ye", None), "M6": (None, None), "M7": ("k1cr", "k1"), "M8": ("phi_king", None)}


def main() -> None:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    out = {"_metadata": {
        "description": "Published tabulated values plotted by the Model details figures (M1-M8). Each point is one "
                       "alloy of a publication's table with the values and the class (or observed phase) printed "
                       "there. Figures built from these points are reconstructions from tabulated data, not "
                       "reproductions of the publishers' figures.",
        "source_file": "tests/reference/published_benchmarks.json",
        "source_description": src.get("_metadata", {}).get("description", ""),
        "generated_by": "tools/build_model_figures.py",
        "fields": {"f": "formula as printed", "x": "x value", "y": "y value (or null)", "c": "published class, "
                   "else observed phase (or null)", "doi": "publication", "loc": "table / page"}},
        "models": {}}
    for model, (xk, yk) in AXES.items():
        pts = []
        for c in src["cases"]:
            if c["model"] != model or xk is None:
                continue
            p = c["published"]
            if xk not in p or (yk is not None and yk not in p):
                continue
            pts.append({"f": c["formula"], "x": p[xk], "y": p[yk] if yk else None,
                        "c": c.get("published_class") or c.get("observed"), "doi": c["doi"], "loc": c["location"],
                        "id": c["id"]})
        out["models"][model] = {"x": xk, "y": yk, "points": pts}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print({m: len(v["points"]) for m, v in out["models"].items()})


if __name__ == "__main__":
    main()
