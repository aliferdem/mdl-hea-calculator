"""Dev-time generator for the vector equation assets used in Calculation details.

Run:  .venv/Scripts/python.exe tools/render_equations.py
Writes one SVG per equation to hea_calc/ui/equations/<key>.svg with ``currentColor`` fills so the
application recolours them at runtime (no per-theme duplicates). Requires matplotlib (dev only).
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("svg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["mathtext.fontset"] = "stix"
plt.rcParams["svg.fonttype"] = "path"

OUT = Path(__file__).resolve().parents[1] / "hea_calc" / "ui" / "equations"

EQUATIONS = {
    # descriptors
    "dsmix": r"$\Delta S_{\mathrm{mix}}=-R\sum_i c_i\ln c_i$",
    "dhmix": r"$\Delta H_{\mathrm{mix}}=\sum_{i<j}4\,\Delta H^{\mathrm{mix}}_{ij}\,c_i c_j$",
    "delta": r"$\delta=100\sqrt{\sum_i c_i\left(1-\frac{r_i}{\bar r}\right)^2},\quad \bar r=\sum_i c_i r_i$",
    "tm": r"$T_m=\sum_i c_i\,T_{m,i}$",
    "vec": r"$\mathrm{VEC}=\sum_i c_i\,\mathrm{VEC}_i$",
    # models - display-style fractions (\dfrac) and one statement per line (2026-10-28): inline \frac set numerators
    # and denominators at 70 % and nested ones at 49 % / 34 % of the base size (M3's gamma was unreadable); the
    # mathematics is unchanged, only its typesetting
    "M1": [r"$\Omega=\dfrac{T_m\Delta S_{\mathrm{mix}}}{|\Delta H_{\mathrm{mix}}|}$",
                     r"$\mathrm{SS:}\ \Omega\geq 1.1\ \ \mathrm{and}\ \ \delta_{\mathrm{CN12}}\leq 6.6\%$"],
    "M2": [r"$\mathrm{SS:}\ \delta\leq 6.6\%,\ -11.6\leq\Delta H_{\mathrm{mix}}\leq 3.2$",
                     r"$\mathrm{MG:}\ \delta>6.4\%,\ \Delta H_{\mathrm{mix}}<-12.2$"],
    "M3": [r"$\gamma=\dfrac{1-\sqrt{\dfrac{(r_S+\bar r)^2-\bar r^2}{(r_S+\bar r)^2}}}"
                     r"{1-\sqrt{\dfrac{(r_L+\bar r)^2-\bar r^2}{(r_L+\bar r)^2}}}$",
                     r"$\mathrm{SS:}\ \gamma<1.175$"],
    "M4": [r"$\Lambda=\dfrac{\Delta S_{\mathrm{mix}}}{\delta^2}$",
                     r"$\Lambda>0.96:\ \mathrm{SS},\ \ 0.24\leq\Lambda\leq 0.96:\ \mathrm{SS{+}IM},\ \ \Lambda<0.24:\ \mathrm{IM}$"],
    "M5": [r"$\phi=\dfrac{S_C-S_H}{|S_E|},\ \ S_H=\dfrac{|\Delta H_{\mathrm{mix}}|}{T_m}$",
                     r"$\mathrm{SS:}\ \phi\geq 20$"],
    "M6": r"$-T\,\Delta S_{\mathrm{mix}}<\Delta H_{f}(i,j)<37\ \mathrm{meV\,atom^{-1}}\quad \forall\,i,j$",
    "M7": [r"$k_1^{\mathrm{cr}}(T)=1+(1-k_2)\dfrac{T\Delta S_{\mathrm{mix}}}{|\Delta H_{\mathrm{mix}}|}$",
                     r"$k_1=\dfrac{\Delta H_{\mathrm{IM}}}{\Delta H_{\mathrm{mix}}}$",
                     r"$\mathrm{SS:}\ k_1<k_1^{\mathrm{cr}}$"],
    "M8": [r"$\Phi=\dfrac{\Delta G_{\mathrm{ss}}}{-|\Delta G_{\max}|},\ \ \Delta G_{\mathrm{ss}}=\Delta H_{\mathrm{ss}}-T_m\Delta S_{\mathrm{mix}}$",
                     r"$\mathrm{SS:}\ \Phi\geq 1,\ \delta_{\mathrm{CN12}}\leq 6.6\%$"],
}


def render(key: str, tex: str, size: float = 13.0) -> Path:
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, tex, fontsize=size, color="#000000")
    path = OUT / f"{key}.svg"
    fig.savefig(path, format="svg", bbox_inches="tight", pad_inches=0.02, transparent=True)
    plt.close(fig)
    svg = path.read_text(encoding="utf-8")
    svg = re.sub(r"<metadata>.*?</metadata>", "", svg, flags=re.S)
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = svg.replace("#000000", "currentColor")
    # glyph paths carry no explicit fill (SVG default black) -> inherit currentColor from the root
    svg = re.sub(r"<svg ", '<svg fill="currentColor" ', svg, count=1)
    path.write_text(svg, encoding="utf-8")
    return path


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    import sys
    keys = sys.argv[1:] or list(EQUATIONS)
    for k in keys:
        tex = EQUATIONS[k]
        if isinstance(tex, list):
            # one SVG per statement (<key>_1.svg, <key>_2.svg, ...): the widget stacks them (widgets/equation.py)
            (OUT / f"{k}.svg").unlink(missing_ok=True)
            for old in OUT.glob(f"{k}_*.svg"):
                old.unlink()
            for i, line in enumerate(tex, 1):
                print(render(f"{k}_{i}", line))
        else:
            for old in OUT.glob(f"{k}_*.svg"):
                old.unlink()
            print(render(k, tex))
