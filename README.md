<div align="center">

# HEA Calculator

**Desktop screening of high-entropy alloy compositions with eight published phase-formation criteria.**

[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE.txt)
![Python 3.11](https://img.shields.io/badge/python-3.11-3776AB.svg)
![Qt for Python 6.7](https://img.shields.io/badge/PySide6-6.7.3-41CD52.svg)
![Platform: Windows](https://img.shields.io/badge/platform-Windows%2011-0078D4.svg)
![Status: pre-release](https://img.shields.io/badge/status-pre--release-lightgrey.svg)

[Features](#features) · [Science](#descriptors-and-models) · [Installation](#installation) ·
[Quick start](#quick-start) · [Limitations](#interpreting-results) · [Citing](#citing)

</div>

<picture>
  <source media="(prefers-color-scheme: light)" srcset="docs/screenshots/light/main-window.png">
  <img src="docs/screenshots/dark/main-window.png" alt="HEA Calculator main window: periodic table, composition setup, Analysis panel and results table for CoCrFeMnNi" width="100%">
</picture>

HEA Calculator takes an alloy composition, or a whole family of them, and reports the thermodynamic and
atomic-size descriptors used in the high-entropy alloy literature together with the verdicts of eight published
solid-solution criteria (Yang & Zhang, Guo, Wang, Singh, Ye, Troparevsky, Senkov & Miracle, King). It is built for
exploring composition space before experiments or before more expensive CALPHAD and first-principles work.

Every workflow (a single composition, a composition grid, parametric expressions or an imported spreadsheet) feeds
one calculation engine. Each equation, radius set, binary dataset and threshold is traced to its publication in
[`CALCULATION_AUDIT.md`](CALCULATION_AUDIT.md) and checked by regression tests against published tables.

> [!IMPORTANT]
> The criteria are empirical or semi-empirical screening rules. A prediction of **SS** says that a composition lies
> inside a published criterion's solid-solution region. It does not show that a single phase is stable or will form
> after a given processing route. See [Interpreting results](#interpreting-results).

## Status

HEA Calculator 1.0.0 is a pre-release. No binary distribution has been published yet. It runs from source.

| | |
|---|---|
| **Tested** | Windows 11, Python 3.11, PySide6 6.7.3. Display scaling: 125 % on a physical 2160 × 1440 display; 100 % and 150 % in controlled, emulated tests |
| **Not yet tested** | macOS and Linux. The Windows-specific code is guarded, but nobody has run the application on those systems |
| **Not included** | A command-line interface or Python API. All workflows run through the desktop application |

## Features

### Defining compositions

<table>
  <tr>
    <td width="33%"><img src="docs/screenshots/dark/single-composition.png" alt="Single composition editor"></td>
    <td width="33%"><img src="docs/screenshots/dark/composition-space.png" alt="Composition space editor"></td>
    <td width="33%"><img src="docs/screenshots/dark/composition-expression.png" alt="Composition expression editor"></td>
  </tr>
  <tr>
    <td><b>Single composition</b><br>Enter amounts as atomic ratio, at.%, wt.% or mass. The other columns are
    converted live, with <i>Set equal</i> and <i>Normalize</i>.</td>
    <td><b>Composition space</b><br>Min / max / step (or number of points) per element, in at. ratio, at.%, wt.%
    or mass. Optional elements and a system-size filter produce sub-systems.</td>
    <td><b>Composition expressions</b><br>Parametric formulas such as <code>AlxCoCrFeNi</code> with range lines,
    several blocks and duplicate removal. Syntax highlighting and inline diagnostics are included.</td>
  </tr>
</table>

- **Spreadsheet import.** Read `.xlsx`, `.xlsm` or `.csv` files with one formula column or one column per
  element. Rows that can't be read are listed with a reason, and the valid rows are still calculated.
- **Model coverage before you calculate.** The periodic table shows per-element data support for each model, and
  composition setup warns when a selected element set leaves a model without data.
- **Workload estimate.** Before a batch starts, the calculator gives the exact number of compositions, an estimated
  runtime and the temporary disk space the results will need.

### Calculating and storing results

- Batches are generated and calculated in background worker processes (up to eight), so the window stays
  responsive. Results stream into a session SQLite database rather than into memory. Batches of up to 10,000,000
  compositions are accepted.
- The **results table** is a paged view of that database, with sorting, filtering, optional columns and an
  Excel-style sticky header. Model verdicts appear as colour-coded class tags.
- **Export** writes the whole dataset or the filtered view to Excel or CSV at full precision. Exports above Excel's
  row limit are split or sent to CSV, never truncated. Results are temporary, so export what you want to keep.

### Analysis

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/dark/analysis-composition.png" alt="Analysis of one composition"></td>
    <td width="50%"><img src="docs/screenshots/dark/analysis-statistics.png" alt="Collection statistics"></td>
  </tr>
  <tr>
    <td><b>Composition analysis</b>: normalised composition in every unit, key and full-precision descriptors,
    each model's verdict with its criterion, values, cautions and N/A reasons.</td>
    <td><b>Collection analysis</b>: statistics, scatter, line, histogram, box, heatmap and class-count plots over a
    calculation run. Missing values are counted, never plotted or averaged as zero.</td>
  </tr>
</table>

Collections can be opened in an expanded workspace or a separate window. Composition and collection reports export
to PDF; statistics and plotted data export to CSV, and plots export to SVG or PNG.

### Interface

Light and dark themes (or follow Windows), undo/redo, keyboard shortcuts, collapsible panels and built-in
documentation (*Help › Documentation*). The layout is designed for high-DPI displays. The visual design follows the
[Carbon Design System](https://carbondesignsystem.com/) v11 (tokens, interaction states, IBM Plex Sans, Carbon icons),
reimplemented in Qt widgets. It is not an IBM product and does not use Carbon's web components.

<details>
<summary><b>Light theme</b></summary>
<br>
<img src="docs/screenshots/light/main-window.png" alt="Main window, light theme" width="100%">
<img src="docs/screenshots/light/analysis-collection.png" alt="Collection scatter plot, light theme" width="60%">
</details>

## Descriptors and models

### Calculated quantities

All quantities use normalised atomic fractions *c<sub>i</sub>*. Compositions need at least two elements.

| Quantity | As implemented | Data source | Nature |
|---|---|---|---|
| ΔS<sub>mix</sub> | −R Σ *c<sub>i</sub>* ln *c<sub>i</sub>* | — | Ideal configurational entropy |
| ΔH<sub>mix</sub> | Σ<sub>i&lt;j</sub> 4 *c<sub>i</sub>c<sub>j</sub>* ΔH<sub>ij</sub> | Takeuchi & Inoue (2005), Miedema liquid enthalpies | Regular-solution estimate |
| T<sub>m</sub>, ρ | Rule of mixtures (ρ = Σ*c<sub>i</sub>M<sub>i</sub>* / Σ*c<sub>i</sub>V<sub>i</sub>*) | Elemental tables; Miedema molar volumes | Approximation without excess terms |
| VEC | Σ *c<sub>i</sub>* VEC<sub>i</sub>; FCC if ≥ 8.0, BCC if < 6.87 | Guo et al. (2011) | Empirical structure rule |
| δ | 100 √Σ *c<sub>i</sub>*(1 − *r<sub>i</sub>*/r̄)² | Guo & Liu (2011) radii | Size mismatch, used by M2–M5 |
| δ<sub>CN12</sub> | Same equation | Kittel CN12 radii | Size mismatch, used by M1 |
| Ω, γ, Λ, φ, Φ, ΔH<sub>IM</sub>, k<sub>1</sub><sup>cr</sup> | Per model, see below | — | Model-specific parameters |

The two size mismatches are kept apart on purpose: each publication was calibrated with its own radius set.
Electronegativity differences and an e/a ratio are **not** computed.
[Symbols, parameters and units](hea_calc/docs/pages/symbols.md) has the full list.

### Phase-formation criteria

| | Publication | Criterion (as implemented) | Classes |
|---|---|---|---|
| **M1** | Yang & Zhang (2012) | SS if Ω ≥ 1.1 and δ<sub>CN12</sub> ≤ 6.6 % | SS, MP |
| **M2** | Guo et al. (2013) | SS if δ ≤ 6.6 % and −11.6 ≤ ΔH<sub>mix</sub> ≤ 3.2 kJ mol⁻¹; MG if δ > 6.4 % and ΔH<sub>mix</sub> < −12.2 kJ mol⁻¹ | SS, MG, MP |
| **M3** | Wang et al. (2015) | SS if γ < 1.175 | SS, MP |
| **M4** | Singh et al. (2014) | SS if Λ > 0.96; SS+IM if 0.24 ≤ Λ ≤ 0.96; IM if Λ < 0.24 | SS, SS+IM, IM |
| **M5** | Ye et al. (2015) | SS if φ ≥ 20 | SS, MP |
| **M6** | Troparevsky et al. (2015) | SS if −TΔS<sub>mix</sub> < ΔH<sub>f</sub>(i,j) < 37 meV/atom for every pair | SS, IM, MP |
| **M7** | Senkov & Miracle (2016) | SS if ΔH<sub>mix</sub> − TΔS<sub>mix</sub> < ΔH<sub>IM</sub> − k<sub>2</sub>TΔS<sub>mix</sub>, k<sub>2</sub> = 0.6 | SS, IM |
| **M8** | King et al. (2016) | SS if Φ ≥ 1, with Φ from Miedema-model ΔG<sub>ss</sub> and ΔG<sub>max</sub> | SS, MP |

SS solid solution · MP multiple phases (not a single solid solution) · IM intermetallic · SS+IM solid solution with
intermetallic · MG metallic glass · **N/A** not evaluated

M6 and M7 are evaluated at 0.55 T<sub>m</sub> unless you set an annealing temperature in *Calculation settings*.
Binary formation enthalpies come from the Troparevsky et al. supplemental matrix. King's Miedema terms use Bakker's
(1998) parameters.

<details>
<summary><b>Implementation decisions that affect results</b></summary>
<br>

These are documented with evidence in [`CALCULATION_AUDIT.md`](CALCULATION_AUDIT.md):

- **Inclusive and strict bounds follow each publication.** Inclusive comparisons tolerate floating-point noise
  (relative 10⁻¹²). Without that, CoCrFeNiCu would compute ΔH<sub>mix</sub> = 3.200000000000001 and fail M2.
  Strict bounds are compared exactly.
- **M2** has no numeric boundary for Guo's intermetallic region, which the paper only draws. Compositions outside
  both printed criteria are reported as MP with a caution, and SS is not separated from IM.
- **M7** was derived for ΔH<sub>mix</sub> < 0. Other compositions are still evaluated with Eq. 6 but marked
  *Extrapolated*.
- **M8** uses Φ ≥ 1 alone. The δ ≤ 6.6 % screen in King et al. is a candidate-generation filter (§3.4), not part of
  the criterion (§3.1).
- **Troparevsky data.** 43 published cells lie outside the range of the publication's own figure. They are kept as
  published, not corrected. Predictions that depend on them are marked *Flagged binary data*.
- **Undefined ratios** (for example Ω when ΔH<sub>mix</sub> = 0) give N/A with a reason, never ±∞.
- **Missing data is never zero.** A missing elemental value or binary pair makes only the models that depend on it
  N/A. Everything else is still evaluated.

</details>

### Validation

Regression tests in [`tests/`](tests) compare the engine with values transcribed from the publications
([`tests/reference/`](tests/reference)): Yang & Zhang Table 1, Guo et al. Table 1, Singh et al. Table 1, Ye et al.
excess entropies, Senkov & Miracle ΔH<sub>IM</sub> (44 of 45 values reproduced), King et al.'s worked examples, and
Bakker Table A2 (all 840 transition-metal pairs within ±2.1 kJ mol⁻¹). Remaining disagreements with published
tables, and the reason for each, are listed in section 8 of the audit.

## Installation

**Requirements:** Windows 11 (Windows 10 is untested) and Python 3.11. Large batches also need temporary disk
space; the calculator estimates it before starting.

```powershell
git clone <repository-url> hea-calculator
cd hea-calculator
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

`requirements.txt` pins PySide6 6.7.3 and installs openpyxl (import) and XlsxWriter (Excel export). It also
installs the development tools pytest, matplotlib and Nuitka, which the application doesn't need at runtime.

## Quick start

**One composition.** Click Co, Cr, Fe, Mn and Ni in the periodic table, keep *At. ratio* at 1 each and select
**Calculate**. For equiatomic CoCrFeMnNi the calculator reports ΔH<sub>mix</sub> = −4.16 kJ mol⁻¹,
ΔS<sub>mix</sub> = 13.38 J mol⁻¹ K⁻¹, Ω = 5.79, δ = 3.27 % and VEC = 8.0 (FCC), and all eight models return SS.

Now try AlCoCrFeNi, which is experimentally BCC + B2. The models disagree:

| M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 |
|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| SS | MP | SS | SS+IM | MP | IM | IM | MP |

This disagreement is expected. The criteria were calibrated on different alloy sets with different data, and
comparing them is the point of the tool.

**A composition space.** Switch the mode to *Composition space* and give each element a range. For example, Cr, Mn
and Ni from 0.5 to 1.5, Fe from 0.8 to 1.2 and Co fixed at 1.0, all in steps of 0.1, give 11 × 11 × 11 × 5 = 6,655
compositions. The workload summary shows this count, with runtime and storage estimates, before you calculate.
In at. ratio and mass bases, proportional duplicates such as 1:1 and 2:2 are calculated only once.

**An expression.** Switch to *Composition expression* and enter:

```text
AlxCoCrFeNi
0 <= x <= 1, step=0.1
```

**Parse** (Ctrl+Enter) reports 11 compositions, from CoCrFeNi (x = 0) to AlCoCrFeNi (x = 1). In *Analysis ›
Collection › Plots*, a *Line (ordered by parameter)* plot shows how each descriptor varies with x.

The built-in Help has walkthroughs: [first calculation](hea_calc/docs/pages/first-calculation.md),
[composition space](hea_calc/docs/pages/composition-space.md),
[expression syntax](hea_calc/docs/pages/expression-syntax.md) and
[importing spreadsheets](hea_calc/docs/pages/importing.md).

## Interpreting results

- **Treat verdicts as screening indicators.** All eight criteria are fitted to limited sets of mostly as-cast or
  annealed alloys. They show tendencies, not equilibrium phase assemblages, kinetics or processing effects.
- **MP means "not a single solid solution".** It does not identify which phases form.
- **Only binary data are used.** Ternary and higher-order compounds are not considered.
- **Read N/A as missing information, not as a phase.** The reason is shown in *Analysis › Models*.
- **Check statuses.** *Extrapolated* and *Flagged binary data* mean a verdict carries less weight than an in-domain
  prediction.
- **Element coverage is not validation.** A model that can be evaluated for an element set has not been validated
  on alloys of those elements.
- **Rounding is for display only.** The table rounds values, but threshold comparisons use full precision. Exports
  and *Analysis › Descriptors* show the full values.

Details: [Scope and scientific limitations](hea_calc/docs/pages/scope.md) ·
[Result labels](hea_calc/docs/pages/result-labels.md) ·
[Binary interaction data](hea_calc/docs/pages/binary-data.md) ·
[Elemental data](hea_calc/docs/pages/elemental-data.md)

## Documentation

| Document | Contents |
|---|---|
| [`hea_calc/docs/pages/`](hea_calc/docs/pages) | The user documentation shown in *Help › Documentation*: workflows, models, data, results, export, shortcuts |
| [`hea_calc/docs/pages/phase-models.md`](hea_calc/docs/pages/phase-models.md) | Each model's equation, criterion, bounds and limitations |
| [`CALCULATION_AUDIT.md`](CALCULATION_AUDIT.md) | Scientific audit: sources, equations, units, datasets, decisions and remaining discrepancies |

Links between Help pages use the application's internal `help://` scheme, so they don't resolve on GitHub.

## Architecture

```text
main.py                 entry point (spawn-safe for worker processes)
hea_calc/
  core/                 Qt-free logic
    engine.py           the single calculation engine: descriptors, M1–M8, data-availability rules
    data.py             dataset loading (data/*.json, with provenance metadata)
    composition.py      unit conversion (at. ratio, at.%, wt.%, mass)
    generation.py       composition-space enumeration and exact counting
    expression*.py      expression lexer, parser, diagnostics and compiled evaluator
    jobs.py, recipes.py worker-process pool and batch generation
    repository.py       session SQLite result store; sorting, filtering and export run in SQL
    analysis/           collection queries, statistics and report content
  ui/                   PySide6 widgets, theme tokens, icons, Analysis views, Windows title-bar integration
  docs/pages/           in-app documentation (Markdown)
data/                   elemental properties, Takeuchi & Inoue ΔH_mix, Troparevsky ΔH_f
tests/                  pytest suite; tests/reference/ holds values transcribed from publications
tools/                  developer tools: screenshots, DPI and performance harnesses
```

The user interface formats engine output and never computes a descriptor or verdict itself. Batches never hold the
whole result set in one process. Workers send result chunks to a single writer process, and the table, plots and
exports query the database.

## Development

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python -m pytest -q
```

The full suite (about 740 tests) takes 15 to 20 minutes. Native-window tests are opt-in (`HEA_NATIVE_TESTS=1`) and need a Windows
desktop session.

Scientific changes (equations, constants, thresholds or dataset values) need literature evidence, an entry in
`CALCULATION_AUDIT.md` and a regression test against published values.

## Origins and acknowledgements

HEA Calculator is derived from **[HEACalculator](https://github.com/dogusariturk/HEACalculator)** by
Doğuhan Sarıtürk, a GPL-3.0-licensed Python tool for the same family of parameters and solid-solution criteria. This
project began in 2024 as an adaptation of that application. Its calculation engine, datasets, workflows and
interface have since been rewritten and independently re-verified against the original publications. The original
HEACalculator was used as a reference implementation during that work, and copyright in it remains with its author.
If HEA Calculator is useful in your work, please also cite HEACalculator (see below).

HEA Calculator is developed at the Metals Development Laboratory (MDL), Department of Metallurgical and Materials
Engineering, Middle East Technical University (METU), Ankara.

The scientific content rests on the publications listed under [References](#references). Third-party components:
Qt for Python (LGPL-3.0), openpyxl (MIT), XlsxWriter (BSD-2-Clause), IBM Plex Sans (SIL Open Font License 1.1) and
Carbon icons (Apache-2.0).

## Citing

HEA Calculator has no DOI yet. Until a release is archived, cite the software by name, version and repository
URL, together with the publications of the models you report.

Please also cite the original HEACalculator:

> D. Sarıtürk, Y.E. Kalay, R. Arróyave, HEACalculator: An open-source Python tool for thermodynamic property
> calculation and solid solution prediction in high-entropy alloys, arXiv (2026).
> https://doi.org/10.48550/arXiv.2606.19661
>
> D. Sarıtürk, HEACalculator, Zenodo (2019). https://doi.org/10.5281/zenodo.3590318

## References

**Models**

1. X. Yang, Y. Zhang, Prediction of high-entropy stabilized solid-solution in multi-component alloys, *Mater. Chem.
   Phys.* 132 (2012) 233–238. https://doi.org/10.1016/j.matchemphys.2011.11.021
2. S. Guo, Q. Hu, C. Ng, C.T. Liu, More than entropy in high-entropy alloys: Forming solid solutions or amorphous
   phase, *Intermetallics* 41 (2013) 96–103. https://doi.org/10.1016/j.intermet.2013.05.002
3. Z. Wang, Y. Huang, Y. Yang, J. Wang, C.T. Liu, Atomic-size effect and solid solubility of multicomponent alloys,
   *Scr. Mater.* 94 (2015) 28–31. https://doi.org/10.1016/j.scriptamat.2014.09.010
4. A.K. Singh, N. Kumar, A. Dwivedi, A. Subramaniam, A geometrical parameter for the formation of disordered solid
   solutions in multi-component alloys, *Intermetallics* 53 (2014) 112–119.
   https://doi.org/10.1016/j.intermet.2014.04.019
5. Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang, Design of high entropy alloys: A single-parameter thermodynamic rule,
   *Scr. Mater.* 104 (2015) 53–55. https://doi.org/10.1016/j.scriptamat.2015.03.023
6. M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks, Criteria for predicting the formation of
   single-phase high-entropy alloys, *Phys. Rev. X* 5 (2015) 011041. https://doi.org/10.1103/PhysRevX.5.011041
7. O.N. Senkov, D.B. Miracle, A new thermodynamic parameter to predict formation of solid solution or intermetallic
   phases in high entropy alloys, *J. Alloys Compd.* 658 (2016) 603–607.
   https://doi.org/10.1016/j.jallcom.2015.10.279
8. D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie, Predicting the formation and stability of single phase
   high-entropy alloys, *Acta Mater.* 104 (2016) 172–179. https://doi.org/10.1016/j.actamat.2015.11.040

**Data**

9. S. Guo, C.T. Liu, *Prog. Nat. Sci.: Mater. Int.* 21 (2011) 433–446. Atomic radii (Table 1).
10. A. Takeuchi, A. Inoue, Classification of bulk metallic glasses by atomic size difference, heat of mixing and
    period of constituent elements and its application to characterization of the main alloying element,
    *Mater. Trans.* 46 (2005) 2817–2829. Liquid mixing enthalpies.
11. H. Bakker, *Enthalpies in Alloys: Miedema's Semi-Empirical Model*, Trans Tech Publications, 1998. Miedema
    parameters (Tables A1, A2, A5).
12. C. Kittel, *Introduction to Solid State Physics*, 8th ed., John Wiley & Sons, 2004. 12-coordination radii
    (Ch. 3, Table 9).
13. S. Guo et al., *J. Appl. Phys.* 109 (2011) 103505. VEC rule for FCC and BCC phases.

## License

HEA Calculator is free software, distributed under the GNU General Public License version 3. See
[`LICENSE.txt`](LICENSE.txt). It is provided without any warranty. Licence texts of third-party components are in
[`License/`](License).
