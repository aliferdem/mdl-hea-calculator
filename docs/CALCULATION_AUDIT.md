# Scientific Implementation and Validation

This document describes the scientific content of the HEA Calculator calculation engine
(`hea_calc/core/engine.py`): the quantities it computes, the data it uses, the eight phase-formation criteria as
they are implemented, and the evidence available for their validation. It describes the current implementation.
The investigation that led to it, including superseded findings and earlier versions of the engine, is recorded in
[`docs/SCIENTIFIC_DEVELOPMENT_HISTORY.md`](SCIENTIFIC_DEVELOPMENT_HISTORY.md). Section numbers such as
"audit section 19" or "audit F9" in source-code comments and test docstrings refer to that record.

The state described here corresponds to engine fingerprint `a741ab74769c` and dataset identifiers
`periodic_table.json` `99817a9deb58`, `mixing_enthalpy_data.json` `12bdfbcd5f00` and
`binary_formation_enthalpy_data.json` `633051507e72` (`hea_calc/core/provenance.py`). Validation figures marked
"measured 2026-11-02" were obtained with the previous state (engine `f64504541a84`, `periodic_table.json`
`581eea161276`); the only change since then is the $\Delta\chi$ descriptor and its data column (Section 3.19), which
changes no other descriptor or classification (development history, §21).

**Contents**

1. [Scope and methodology](#1-scope-and-methodology)
2. [Elemental and binary interaction data](#2-elemental-and-binary-interaction-data)
3. [Thermodynamic and atomic-size descriptors](#3-thermodynamic-and-atomic-size-descriptors)
4. [Phase-formation criteria](#4-phase-formation-criteria)
5. [Numerical implementation](#5-numerical-implementation)
6. [Validation against published results](#6-validation-against-published-results)
7. [Known discrepancies and scientific limitations](#7-known-discrepancies-and-scientific-limitations)
8. [Reproducibility and test methodology](#8-reproducibility-and-test-methodology)

---

## 1. Scope and methodology

### 1.1 What the engine computes

Every workflow of the application (single composition, composition space, composition expressions and spreadsheet
import) passes a composition $\lbrace \text{element}: \text{amount} \rbrace$ to one function, `Engine.calculate`. No
other module implements a scientific equation. For each composition the engine returns

* **descriptors**: thermodynamic, atomic-size and electronic quantities (Section 3);
* **classifications** M1–M8: the result of eight published phase-formation criteria (Section 4), each with a class
  label, an evidence status, and either a reason (when the model is not available) or an optional caution;
* **warnings** about the data used (for example a supplementary atomic radius).

| Model | Publication | Criterion family |
|---|---|---|
| M1 | Yang and Zhang (2012)[^yang2012] | $\Omega$ and atomic-size mismatch |
| M2 | Guo et al. (2013)[^guo2013] | Map of $\delta$ and $\Delta H_{\mathrm{mix}}$ |
| M3 | Wang et al. (2015)[^wang2015] | Atomic-packing parameter $\gamma$ |
| M4 | Singh et al. (2014)[^singh2014] | Geometrical parameter $\Lambda$ |
| M5 | Ye et al. (2015)[^ye2015] | Single-parameter rule $\phi$ with the excess entropy |
| M6 | Troparevsky et al. (2015)[^troparevsky2015] | Window of binary formation enthalpies |
| M7 | Senkov and Miracle (2016)[^senkov2016] | Solid-solution versus intermetallic free energy |
| M8 | King et al. (2016)[^king2016] | Thermodynamic parameter $\Phi$ from Miedema's model |

### 1.2 Descriptors and classifications

A **descriptor** is a quantity defined by an equation and the data it reads, such as $\Delta H_{\mathrm{mix}}$ or
$\delta$. It has a unit and, apart from the limitations of its data, a definite value.

A **classification** is the outcome of an empirical or semi-empirical criterion that compares descriptors with
thresholds fitted by the authors to a set of alloys. The result classes are SS (solid solution), MP (multiple phases,
or not classified as a single solid solution), IM (intermetallic), SS+IM (solid solution with intermetallic
compounds) and MG (metallic glass, M2 only); N/A means that the model was not evaluated. A classification states
whether the composition satisfies the criterion as published. It is not a prediction of the equilibrium phase
assemblage, and different criteria can classify the same alloy differently.

### 1.3 Calculation assumptions

* **Composition.** Amounts in any proportional unit are normalised to atomic fractions $c_i$ with
  $\sum_i c_i = 1$. Zero amounts are dropped; negative, non-finite or non-numeric amounts and unknown symbols reject
  the composition; at least two elements with non-zero amounts are required. Unit conversions before the engine
  (at.%, wt.% and mass to atomic fractions) are carried out in `hea_calc/core/composition.py` with standard atomic
  weights.
* **Ideal configurational entropy.** $\Delta S_{\mathrm{mix}}$ is the ideal mixing entropy of a random solution.
  Vibrational, electronic and magnetic contributions are not included.
* **Binary interactions only.** $\Delta H_{\mathrm{mix}}$, $\Delta H_{\mathrm{IM}}$ and the King enthalpies are
  built from binary values. Ternary and higher-order interactions or compounds are not represented.
* **Rule of mixtures.** $T_{\mathrm{m}}$, VEC and the density are composition-weighted means of elemental values,
  without excess terms.
* **Temperature.** M6 and M7 require an assessment temperature: the annealing temperature entered in Calculation
  settings, or $f\thinspace T_{\mathrm{m}}$ with $f = 0.55$ by default (Section 4, M6). M8 is evaluated at
  $T_{\mathrm{m}}$ as in the publication. M1–M5 contain no explicit temperature other than $T_{\mathrm{m}}$.

### 1.4 Units and conventions

| Quantity | Value or unit |
|---|---|
| Gas constant | $R = 8.314462618$ J mol⁻¹ K⁻¹ |
| Energy per atom | 1 meV atom⁻¹ = 96.4853321233 J mol⁻¹ = 0.0964853321233 kJ mol⁻¹ |
| Atomic radii | pm |
| $\Delta S_{\mathrm{mix}}$, $S_{\mathrm{c}}$, $S_{\mathrm{H}}$, $S_{\mathrm{E}}$ | J mol⁻¹ K⁻¹ |
| $\Delta H_{\mathrm{mix}}$, $\Delta H_{\mathrm{IM}}$, King enthalpies and free energies | kJ mol⁻¹ (per mole of atoms unless stated) |
| Troparevsky formation enthalpies $\Delta H_{\mathrm{f},ij}$ | meV atom⁻¹ |
| $\delta$, $\delta_{\mathrm{CN12}}$ | percent |
| $T_{\mathrm{m}}$, $T$ | K |
| Density $\rho$ | g cm⁻³ |

Subscripts that are labels are set in roman type ($\Delta H_{\mathrm{mix}}$, $T_{\mathrm{m}}$); indices are italic
($c_i$, $\Delta H_{ij}$). Sums over pairs run over unordered pairs $i \lt j$ unless stated otherwise.

### 1.5 Scope of the validation

The validation evidence in Section 6 is classified by kind, because the kinds are not interchangeable:

1. **Exact reproduction**: the engine gives the published number to within half a unit of its last printed digit.
2. **Agreement within a stated tolerance**: the difference is larger than the printing precision but within a
   tolerance whose reason is documented (for example the precision of the published input data).
3. **Disagreement with a published number**: a published value that the paper's own definitions and cited data do
   not reproduce; each is listed with its cause where known.
4. **Disagreement with experimentally observed phases**: a classification that differs from the phases reported for
   the alloy. This concerns the criterion, not the implementation.
5. **Internal consistency**: tests that the implementation behaves as specified (boundaries, missing data, symmetry,
   invariance), without a published oracle.
6. **Independent numerical verification**: a quantity recomputed outside the engine (for example from analytic
   limits or a separate implementation of the source equations) and compared with the engine.
7. **Outside the validation domain**: compositions or elements for which no published result exists. The engine
   evaluates them, but the result is a formal application of the criterion.

The validation covers the published tables that could be transcribed (Section 6). It does not establish that a
criterion predicts phases correctly for alloy families outside the alloys on which it was calibrated.

---

## 2. Elemental and binary interaction data

The data files are in [`data/`](../data). Each carries a `_metadata` block with its source and conventions.

### 2.1 Elemental properties

`data/periodic_table.json` holds 118 elements.

| Property | Unit | Source | Coverage | Used by |
|---|---|---|---|---|
| `atomic_radius` | pm | Guo and Liu (2011), Table 1[^guoliu2011]; supplementary values for other elements | 108 elements (73 from Table 1, 35 supplementary) | $\delta$, $\gamma$, $\Lambda$, $S_{\mathrm{E}}$, $\phi$; M2–M5 |
| `atomic_radius_cn12` | pm | Kittel, Ch. 3, Table 9[^kittel2005] | 73 elements | $\delta_{\mathrm{CN12}}$; M1 |
| `melting_point` | K | Standard tabulation; the source is not recorded in the dataset | 118 | $T_{\mathrm{m}}$; $\Omega$, $\phi$, M6/M7 default temperature, M8 |
| `atomic_weight` | g mol⁻¹ | Standard atomic weights | 118 | Unit conversion; density |
| `nvalence` | – | Number of s and d valence electrons; standard tabulation | 118 | VEC; Miedema valence $z$ |
| `molar_volume` | cm³ mol⁻¹ | Bakker (1998), Table A1[^bakker1998] for 71 elements; source not recorded for the other 47 | 118 | Miedema model (M8); density |
| `work_function_phi`, `n_ws` | V; density units | Bakker (1998), Table A1 | 71 | Miedema model (M8) |
| `bulk_modulus`, `shear_modulus` | 10¹⁰ Pa | Bakker (1998), Table A5 | 71 | Elastic term (M8) |
| `electronegativity_pauling` | – | Guo and Liu (2011), Table 1, Pauling column[^guoliu2011] | 73 elements (the Table 1 elements; no other source) | $\Delta\chi$ only; no model (Section 3.19) |

The Miedema parameters were compared with Bakker's tables for every element; the stored values are identical, with
the divalent parameter set used for Eu and Yb. The elemental `density` property is displayed in the Elements panel
only; no descriptor or model reads it, and its source is not recorded.

### 2.2 Atomic radii: two conventions

The publications behind the models use different radius definitions, and the calculated $\delta$ depends strongly on
the choice: for equiatomic CoCrFeMnNi, $\delta = 3.27$ % with Guo and Liu radii and $\delta_{\mathrm{CN12}} = 0.92$ %
with Kittel radii. Each model therefore uses the radius set with which its thresholds were derived, and both
mismatches are reported. Using one common set would move many alloys across the published thresholds.

| Radius set | Models | Evidence for the assignment |
|---|---|---|
| Guo and Liu (2011), Table 1 | M2, M3, M4, M5 | M2, M4, M5: the published $\delta$, $\Lambda$ and $S_{\mathrm{E}}$ values are reproduced (Section 6). M3: the authors name no radius set; see M3 in Section 4. |
| Kittel CN12 | M1 | Yang and Zhang cite Kittel; their Table 1 $\delta$ values are reproduced with these radii (Section 6). |
| None | M8 | King's criterion uses no radius (Section 4, M8). |

#### Guo and Liu radii

* **Precision.** All 73 elements of Guo and Liu's Table 1 hold the value printed in the table (Å to three decimals,
  stored in pm to 0.1 pm). The printed values were adopted because they *are* the cited table and because the
  published $\delta$, $\Lambda$, $S_{\mathrm{E}}$ and $\gamma$ values of M2–M5 were computed with them. In the
  comparison recorded in §17.1 and §20 of the development history, replacing the former 0.01 pm values (a later
  recompilation of the same radii) by the printed values raised the number of values reproduced to the last printed
  digit from 25 to 81 of Guo's 93 $\delta$ values, from 26 to 56 of Singh's 76 $\delta$ values and from 6 to 26 of his
  $\Lambda$ values. Section 6.2 gives the current counts under the rules of the regression tests. The physical
  uncertainty of a metallic radius is of the order of a percent, so the choice rests on provenance and
  reproducibility, not on physical accuracy. Zn (139.5 pm) and Zr (160.3 pm) are the printed values; no rounding
  function was applied.
* **Pm, Po, Pa and U.** These four elements hold the Guo and Liu values (163.0, 153.0, 161.0 and 142.0 pm). Earlier
  versions of the dataset held Kittel CN12 values for them (181, 176, 163 and 156 pm), which was a provenance error;
  the correction is documented in §18 of the development history. No published alloy behind M2–M5 contains these
  elements, so the correction restores consistency with the source but provides no validation of predictions for
  them.
* **Zr.** The publications disagree: the $\delta$ column of Guo et al. (2013) is reproduced with Zr = 160.2 pm (8 of 8
  Zr rows exact), while Ye's $S_{\mathrm{E}}$ table favours 160.3 pm (17 of 30 rows exact against 4 of 30). The printed
  Guo and Liu value 160.3 pm is used; the conflict is documented, not resolved.
* **Equal radii.** Some elements share a radius value, for example Pd and Re (both 137.5 pm), Nd and Pu, Sm and Am,
  Tm and Np. A composition made only of such elements has $\delta = 0$; $\Lambda$ and $\phi$ are then undefined
  (Section 5.3).

#### Supplementary radii

45 elements are not in Guo and Liu's Table 1 (`_metadata.atomic_radius_supplementary`). 35 of them carry a radius of
undocumented origin; 10 (At, Rn and Cm–Lr) have none. When a supplementary radius is used, the engine adds a warning
and a caution on M2–M5, and the periodic table shows that supplementary data are used. Results for these elements
are outside the calibration of M2–M5 and their radii have no traceable source.

#### Kittel CN12 radii

The 12-coordination radii are transcribed from Kittel's table "Radii of ions in 12-coordinated metals"
(`tests/reference/kittel_cn12.json`: 69 single values and 4 entries given as a range or for a stated valence). For
those four the dataset uses Ce 182 pm (range 171–182), Eu²⁺ 204 pm, Yb²⁺ 194 pm and Pu 161 pm (range 158–164).

### 2.3 Melting temperatures, atomic weights and valence electrons

The melting temperatures, atomic weights and valence-electron numbers are standard tabulated values; the dataset
does not record a specific source for them. Yang and Zhang's $\Omega$ column implies elemental melting temperatures
that differ from modern tabulations by up to a few hundred kelvin for some elements (for example their values imply
Cr ≈ 2133 K, Ti ≈ 1946 K and Co ≈ 1770 K); this is the reason $\Omega$ is compared with a relative tolerance and is
not used as an exact oracle (Section 6).

### 2.4 Miedema parameters

The Miedema model of M8 uses, for each element, the electronegativity parameter $\varphi^{\ast}$ (V), the electron
density at the Wigner–Seitz cell boundary $n_{\mathrm{ws}}$ (density units), the molar volume $V$ (cm³ mol⁻¹), the
bulk and shear moduli $K$ and $G$, and the valence $z$ for the structural term. In addition the model needs each
element's classification as a transition or non-transition metal and its hybridisation factor (Section 3.15). The
parameters are those of Bakker (1998)[^bakker1998]; the classification of Ca, Sr and Ba follows de Boer et al.
(1988)[^deboer1988].

57 elements have both the parameters and a classification. The lanthanides Ce–Lu have Bakker parameters but no
classification in the engine, so M8 is N/A for them. $n_{\mathrm{ws}}$ is stored to two decimals as printed in
Bakker's Table A1; de Boer et al. tabulate $n_{\mathrm{ws}}^{1/3}$ with more digits, and the difference is worth
1–3 kJ mol⁻¹ in interfacial enthalpies of low-density metals (Section 7.2).

### 2.5 Liquid mixing enthalpies

`data/mixing_enthalpy_data.json` holds the binary liquid mixing enthalpies $\Delta H_{ij}^{\mathrm{mix}}$ of Takeuchi
and Inoue (2005)[^takeuchi2005], calculated by the authors with Miedema's model for equiatomic liquids (kJ mol⁻¹). The
table covers 73 elements and all 2,628 of their pairs. 159 pairs are tabulated as exactly 0 kJ mol⁻¹; these are values
of the source (for example Fe–Mn), not missing data (Section 2.7).

### 2.6 Binary formation enthalpies

`data/binary_formation_enthalpy_data.json` holds the formation enthalpies $\Delta H_{\mathrm{f},ij}$ of the
lowest-energy binary compounds calculated by Troparevsky et al. (2015)[^troparevsky2015] (Supplemental Material,
Appendix A, and Fig. 1), in meV atom⁻¹, for 30 elements and their 435 pairs: Mg, Al, Sc, Ti, V, Cr, Mn, Fe, Co, Ni, Cu,
Zn, Y, Zr, Nb, Mo, Ru, Rh, Pd, Ag, Cd, La, Hf, Ta, W, Re, Os, Ir, Pt and Au.

* **Source format.** The published matrix is a colour-scaled figure with printed numbers; every cell was transcribed
  by eye. Three cells are quoted in the text of the publication and can be verified independently of the figure:
  Al–Ni −677, Mo–Ta −193 and Mn–Ni −115 meV atom⁻¹. They are asserted exactly in the tests.
* **Asymmetric entries.** Seven pairs are printed with different values in their row and column: Al–Ag (−254/−76),
  Ti–La (134/170), V–Cu (13/54), Cr–Cd (133/113), Mn–Mo (−138/−136), Co–Nb (−178/−150) and Nb–Ir (−628/−830). The
  value in the row of the element that comes first in the published order is used. This rule is supported by Senkov
  and Miracle's $\Delta H_{\mathrm{IM}}$ of CoFeMnMoNi (−16.63 kJ mol⁻¹), which is reproduced only with Mn–Mo = −138.
  M6 results that use one of these pairs carry a caution naming the pair.
* **Values from other sources.** As stated in the publication, the Laves-phase values Ti–Cr (−372), Cr–Zr (−150),
  Cr–Nb (−47) and Cr–Hf (−362) are taken from Chen et al. (2005)[^chen2005], and the Fe–Nb, Fe–Mo, Fe–Ta and Fe–W
  values from CALPHAD assessments of σ and μ phases (Ansara et al., as cited by Troparevsky et al.). The pairs Ti–Re,
  V–Re, Nb–Re and Ta–Re are referenced to the solid solution, as marked in the publication.
* **Flagged values.** Several published cells are physically implausible. They are kept exactly as published, because
  the authors' own predictions and Senkov and Miracle's $\Delta H_{\mathrm{IM}}$ were computed with them, but they are
  flagged (`_metadata.data_quality`). A cell is flagged when $\lvert \Delta H_{\mathrm{f},ij} \rvert \gt 700$ meV
  atom⁻¹ (43 cells, among them Fe–Ta −3468, Fe–Nb −2505 and Al–Cd −1938) or when it is named in the dataset's
  `suspect_override` list (adding Fe–Mo −484 and Fe–W −554): 45 pairs in total. The 700 meV atom⁻¹ guard rests on two
  bounds: the legend of the publication's figure spans about −500 to +300 meV atom⁻¹ (69 cells lie outside it), and
  since $\lvert \Delta H_{\mathrm{mix}} \rvert \le 2 \max_{i\lt j} \lvert \Delta H_{ij} \rvert$ and the largest
  $\lvert \Delta H_{\mathrm{mix}} \rvert$ published in the eight-model corpus is 29.97 kJ mol⁻¹, a cell above about
  1000 meV atom⁻¹ cannot correspond to any published alloy enthalpy. A verdict of M6 or M7 that involves a flagged
  pair carries the status `data_suspect` and a caution naming the cell (Section 5.5). No flagged value is replaced,
  clamped or interpolated; a corrected matrix can replace the file without a change to the model code.

### 2.7 Missing data and physical zeros

A pair or property absent from a dataset is missing data and is never treated as zero. A tabulated zero is a value.

| Missing input | Unavailable descriptors | Models reported N/A | Still evaluated |
|---|---|---|---|
| A $\Delta H_{ij}^{\mathrm{mix}}$ pair | $\Delta H_{\mathrm{mix}}$, $\Omega$, $S_{\mathrm{H}}$, $\phi$, $k_1$, $k_1^{\mathrm{cr}}$ | M1, M2, M5, M7 | $\delta$, $\gamma$, $\Lambda$; M3, M4, M6, M8 |
| A Guo and Liu (or supplementary) radius | $\delta$, $\gamma$, $\Lambda$, $S_{\mathrm{E}}$, $\phi$ | M2, M3, M4, M5 | M1, M6, M7, M8 |
| A Kittel CN12 radius | $\delta_{\mathrm{CN12}}$ | M1 | All other models, including M8 |
| A Troparevsky pair | $\Delta H_{\mathrm{f}}$ extremes, $\Delta H_{\mathrm{IM}}$, $k_1$ | M6, M7 | M1–M5, M8 |
| Miedema parameters or classification of an element | King descriptors | M8 | M1–M7 |
| A Guo and Liu Pauling electronegativity | $\Delta\chi$ | None | All descriptors and M1–M8 |

A missing Kittel CN12 radius makes only $\delta_{\mathrm{CN12}}$ and M1 unavailable; M8 is unaffected because its
criterion uses no radius. Each N/A carries a reason naming the missing element or pair (for example "No Troparevsky
formation enthalpy for Co–Si, Cr–Si, Fe–Si, Ni–Si."). Data availability depends only on the set of elements, not on
the amounts.

---

## 3. Thermodynamic and atomic-size descriptors

All equations below are those evaluated by `hea_calc/core/engine.py`. $c_i$ are the normalised atomic fractions of
the $N$ elements of the composition.

### 3.1 Configurational mixing entropy

$$
\Delta S_{\mathrm{mix}} = -R \sum_{i=1}^{N} c_i \ln c_i
$$

* **Units.** J mol⁻¹ K⁻¹.
* **Assumptions.** Ideal random mixing of $N$ components on one lattice.
* **Availability.** Always defined for a valid composition. Ye et al. denote the same quantity $S_{\mathrm{c}}$.

### 3.2 Mixing enthalpy

$$
\Delta H_{\mathrm{mix}} = 4 \sum_{i \lt j} c_i c_j \Delta H_{ij}^{\mathrm{mix}}
$$

* **Variables.** $\Delta H_{ij}^{\mathrm{mix}}$ is the mixing enthalpy of the equiatomic binary liquid $ij$.
* **Units.** kJ mol⁻¹.
* **Data.** Takeuchi and Inoue (2005)[^takeuchi2005]; the regular-solution form is Eq. (2) of Yang and
  Zhang[^yang2012].
* **Assumptions.** Regular-solution model with binary interaction parameters $4 \Delta H_{ij}^{\mathrm{mix}}$;
  no ternary terms.
* **Numerical notes.** The sum is formed in floating point; values that should equal a printed threshold can differ
  from it in the last bit (Section 5.2).
* **Unavailable** when any pair of the composition is missing from the table.

### 3.3 Average melting temperature

$$
T_{\mathrm{m}} = \sum_i c_i T_{\mathrm{m},i}
$$

* **Units.** K. **Data.** Elemental melting temperatures (Section 2.3). **Assumptions.** Rule of mixtures (Eq. (6) of
  Yang and Zhang); no rounding is applied.

### 3.4 Density

$$
\rho = \frac{\sum_i c_i M_i}{\sum_i c_i V_i}
$$

* **Variables.** $M_i$ atomic weight (g mol⁻¹); $V_i$ molar volume (cm³ mol⁻¹), the Miedema volume where available.
* **Units.** g cm⁻³.
* **Assumptions.** Ideal mixing of molar volumes (no excess volume). The quantity is reported as a descriptor only; no
  model uses it.
* **Limitation.** For the 47 elements whose molar volume is not from Bakker's Table A1 the source of $V_i$ is not
  recorded (Section 7.2).

### 3.5 Valence electron concentration

$$
\mathrm{VEC} = \sum_i c_i v_i
$$

* **Variables.** $v_i$ is the number of s and d valence electrons of element $i$.
* **Structure rule.** The descriptor "Cryst. Str." applies the rule of Guo et al. (2011),[^guo2011vec] namely FCC if
  $\mathrm{VEC} \ge 8.0$, BCC if $\mathrm{VEC} \lt 6.87$, otherwise BCC + FCC. These comparisons are exact. The rule is
  an empirical indicator for solid-solution HEAs and is not one of the eight criteria.

### 3.6 Atomic-size mismatch

$$
\delta = 100 \sqrt{\sum_i c_i \left(1 - \frac{r_i}{\bar{r}}\right)^2}, \qquad \bar{r} = \sum_i c_i r_i
$$

* **Variables.** $r_i$ atomic radius of element $i$.
* **Units.** Percent.
* **Data.** $\delta$ uses the Guo and Liu radii[^guoliu2011]; $\delta_{\mathrm{CN12}}$ evaluates the same equation
  with the Kittel CN12 radii[^kittel2005] (Section 2.2).
* **Assumptions.** Hard-sphere radii independent of the alloy environment.
* **Unavailable** when any element has no radius in the set used (or a non-positive radius). $\delta = 0$ exactly
  when all radii are equal.

### 3.7 Omega

$$
\Omega = \frac{T_{\mathrm{m}} \Delta S_{\mathrm{mix}}}{\lvert \Delta H_{\mathrm{mix}} \rvert}
$$

* **Units.** Dimensionless; the engine divides $T_{\mathrm{m}} \Delta S_{\mathrm{mix}}$ (J mol⁻¹) by
  $1000 \lvert \Delta H_{\mathrm{mix}} \rvert$ (J mol⁻¹). Eq. (5) of Yang and Zhang[^yang2012].
* **Undefined** when $\Delta H_{\mathrm{mix}} = 0$ exactly, which occurs for compositions whose pairs are all
  tabulated zeros (for example several pairs with H, C or N). $\Omega$ is then divergent, not large: it is reported as
  unavailable with the reason "ΔHmix = 0 (tabulated zero pair), so Ω = Tm·ΔS/|ΔHmix| is divergent and Ω is
  undefined." and M1 is N/A (undefined).
* **Unavailable** when $\Delta H_{\mathrm{mix}}$ or $T_{\mathrm{m}}$ is unavailable.

### 3.8 Gamma

Wang et al. (2015)[^wang2015], Eqs. (2) and (3):

$$
\omega(r) = 1 - \sqrt{\frac{(r + \bar{r})^2 - \bar{r}^2}{(r + \bar{r})^2}}, \qquad \gamma = \frac{\omega(r_{\mathrm{S}})}{\omega(r_{\mathrm{L}})}
$$

* **Variables.** $\omega(r)$ is the solid-angle term of an atom of radius $r$ in a matrix of mean radius
  $\bar{r} = \sum_i c_i r_i$; $r_{\mathrm{S}} = \min_i r_i$ and $r_{\mathrm{L}} = \max_i r_i$ are the smallest and
  largest radii present.
* **Units.** Dimensionless; $\gamma \ge 1$, with $\gamma = 1$ for equal radii.
* **Data.** Guo and Liu radii (Section 4, M3, for the evidence behind this choice).
* **Unavailable** when any radius is missing.

### 3.9 Lambda

$$
\Lambda = \frac{\Delta S_{\mathrm{mix}}}{\delta^2}
$$

* **Variables.** $\delta$ in percent, as in Singh et al. (2014)[^singh2014].
* **Units.** J mol⁻¹ K⁻¹ (per percent squared).
* **Undefined** when $\delta = 0$ exactly (all radii equal); the reason states that $\Lambda$ is divergent, and M4 is
  N/A (undefined).

### 3.10 Excess entropy of mixing

Ye et al. (2015)[^ye2015] use the excess entropy $S_{\mathrm{E}}$ of a mixture of hard spheres given by the
Mansoori–Carnahan–Starling–Leland equation of state[^mansoori1971]; the formulation implemented follows the Appendix
of Ye et al., Intermetallics 59 (2015)[^ye2015int]. With hard-sphere diameters $d_i = 2 r_i$ (Guo and Liu radii) and a
packing fraction $\xi$, define the volume fractions

$$
\zeta_i = \frac{c_i d_i^3}{\sum_k c_k d_k^3}
$$

and the auxiliary quantities

$$
\Delta_{ij} = \sqrt{\zeta_i \zeta_j} \frac{(d_i - d_j)^2}{d_i d_j} \sqrt{c_i c_j}
$$

$$
y_1 = \sum_{i \lt j} \Delta_{ij} \frac{d_i + d_j}{\sqrt{d_i d_j}}, \qquad y_2 = \sum_{i \lt j} \Delta_{ij} \sqrt{d_i d_j} \sum_k \frac{\zeta_k}{d_k}, \qquad y_3 = \left(\sum_i \zeta_i^{2/3} c_i^{1/3}\right)^3
$$

The compressibility factor and the excess free energy are

$$
Z = \frac{1 + \xi + \xi^2 - 3\xi\left(y_1 + y_2 \xi\right) - \xi^3 y_3}{(1 - \xi)^3}
$$

$$
F = -\frac{3}{2}\left(1 - y_1 + y_2 + y_3\right) + \frac{3 y_2 + 2 y_3}{1 - \xi} + \frac{3}{2}\frac{1 - y_1 - y_2 - y_3/3}{(1 - \xi)^2} + (y_3 - 1)\ln(1 - \xi)
$$

and the excess entropy per $k_{\mathrm{B}}$ at packing fraction $\xi$ is

$$
\frac{S_{\mathrm{E}}(\xi)}{k_{\mathrm{B}}} = F - \ln Z - \frac{3 - 2\xi}{(1 - \xi)^2} + 3 + \ln\frac{1 + \xi + \xi^2 - \xi^3}{(1 - \xi)^3}
$$

The engine reports the mean over the bcc and fcc packing fractions, per mole of atoms:

$$
S_{\mathrm{E}} = \frac{R}{2}\left[\frac{S_{\mathrm{E}}(0.68)}{k_{\mathrm{B}}} + \frac{S_{\mathrm{E}}(0.74)}{k_{\mathrm{B}}}\right]
$$

* **Units.** J mol⁻¹ K⁻¹. $S_{\mathrm{E}} \le 0$ for any hard-sphere mixture.
* **Assumptions.** Atoms are hard spheres with the Guo and Liu radii; $\xi = 0.68$ and $0.74$ represent bcc and fcc
  packing, averaged as in the main text of Ye et al. (2015).
* **Identical diameters.** If all $d_i$ are equal, $\Delta_{ij} = 0$, so $y_1 = y_2 = 0$; $\zeta_i = c_i$, so
  $y_3 = 1$; $Z$ reduces to the one-component Carnahan–Starling value and $S_{\mathrm{E}} = 0$ exactly at every
  packing fraction. Identical hard spheres form a one-component fluid with no excess entropy of mixing. The engine
  returns this analytic value directly instead of evaluating terms that cancel only to rounding error.
* **Nearly equal diameters.** For $d_i = d(1 + \varepsilon_i)$ the leading term is
  $S_{\mathrm{E}} \approx R \bar{A} (\delta/100)^2$ with
  $A(\xi) = 6 - 3/(1-\xi) - 3/(1-\xi)^2 - 3\ln(1-\xi) + 3\xi(2 + \xi - \xi^2)/(1 + \xi + \xi^2 - \xi^3)$,
  $A(0.68) = -26.78$, $A(0.74) = -43.29$ and $\bar{A} = -35.03$. $S_{\mathrm{E}}$ is therefore second order in the
  size misfit and strictly negative for distinct radii.
* **Numerical floor.** The final expression cancels terms of magnitude up to about 23, so the absolute rounding error
  of $S_{\mathrm{E}}$ is of the order of $10^{-14}$ J mol⁻¹ K⁻¹ (at most $4.7 \times 10^{-14}$ over 1,217 real alloys,
  recorded in §19 of the development history). The smallest non-zero radius gap among the elements with mixing data
  is 0.1 pm; such pairs give $\lvert S_{\mathrm{E}} \rvert$ many orders of magnitude above this floor.
* **Unavailable** when a radius is missing, or when the evaluation fails (a non-positive $Z$ is rejected as
  non-physical).

### 3.11 Ye's parameter phi

$$
S_{\mathrm{H}} = \frac{\lvert \Delta H_{\mathrm{mix}} \rvert}{T_{\mathrm{m}}}, \qquad \phi = \frac{S_{\mathrm{c}} - S_{\mathrm{H}}}{\lvert S_{\mathrm{E}} \rvert}
$$

* **Variables.** $S_{\mathrm{c}} = \Delta S_{\mathrm{mix}}$; $S_{\mathrm{H}}$ in J mol⁻¹ K⁻¹ (the engine converts
  $\Delta H_{\mathrm{mix}}$ to J mol⁻¹); $S_{\mathrm{E}}$ from Section 3.10.
* **Units.** Dimensionless.
* **Source.** Main text of Ye et al., Scripta Materialia 104 (2015)[^ye2015], with $\lvert S_{\mathrm{E}} \rvert$
  averaged over the two packing fractions. The supplementary tables of that paper print $\phi$ per packing fraction
  under conventions that are not the main-text definition (Section 7.3).
* **Undefined** when $\lvert S_{\mathrm{E}} \rvert \lt 10^{-15}$ J mol⁻¹ K⁻¹; in practice this occurs only for the
  exact zero of identical radii. M5 is then N/A (undefined) with the reason that $\phi$ is divergent.
* **Unavailable** when $\Delta H_{\mathrm{mix}}$, $T_{\mathrm{m}}$ or $S_{\mathrm{E}}$ is unavailable.
* **Numerical note.** For distinct but nearly equal radii $\phi \propto 1/\delta^2$ can be very large; this is the
  behaviour of the definition, not a rounding artefact (Section 7.6).

### 3.12 Binary formation-enthalpy descriptors

For the pairs of the composition the engine reports

$$
\Delta H_{\mathrm{f}}^{\min} = \min_{i \lt j} \Delta H_{\mathrm{f},ij}, \qquad \Delta H_{\mathrm{f}}^{\max} = \max_{i \lt j} \Delta H_{\mathrm{f},ij}
$$

with the pairs that attain them, and the lower bound of the Troparevsky window at the assessment temperature $T$:

$$
\Delta H_{\mathrm{f}}^{\mathrm{lower}} = -\frac{T \Delta S_{\mathrm{mix}}}{C}, \qquad C = 96.4853321233
$$

* **Units.** meV atom⁻¹; $C$ converts J mol⁻¹ to meV atom⁻¹ (Section 1.4).
* **Data.** Troparevsky et al. (2015)[^troparevsky2015] (Section 2.6).
* **Unavailable** when any pair is missing from the matrix, or when no temperature is available.

### 3.13 Intermetallic formation enthalpy

Senkov and Miracle (2016)[^senkov2016], Eq. (9):

$$
\Delta H_{\mathrm{IM}} = 4 \sum_{i \lt j} c_i c_j \Delta H_{\mathrm{f},ij}
$$

* **Units.** The sum is formed in meV atom⁻¹ and converted to kJ mol⁻¹ with the factor 0.0964853321233
  (Section 1.4).
* **Data.** The Troparevsky matrix, as in Senkov and Miracle (their Ref. 16).
* **Assumptions.** The regular-solution form applied to the formation enthalpies of the binary compounds.
* **Unavailable** when any pair is missing. A flagged pair (Section 2.6) enters the sum unchanged and is reported.

### 3.14 Senkov and Miracle parameters

$$
k_1 = \frac{\Delta H_{\mathrm{IM}}}{\Delta H_{\mathrm{mix}}}, \qquad k_1^{\mathrm{cr}}(T) = 1 + (1 - k_2)\frac{T \Delta S_{\mathrm{mix}}}{\lvert \Delta H_{\mathrm{mix}} \rvert}, \qquad k_2 = 0.6
$$

* **Variables.** $k_2 = 0.6$ is the ratio of the entropy of a partially ordered intermetallic to that of the
  solid solution adopted by Senkov and Miracle; $T$ is the assessment temperature.
* **Units.** Dimensionless; $T\Delta S_{\mathrm{mix}}$ and $\Delta H_{\mathrm{mix}}$ are converted to the same unit.
* **Undefined** when $\Delta H_{\mathrm{mix}} = 0$. These parameters are reported for comparison with the
  publication; the M7 classification evaluates the free-energy inequality directly (Section 4, M7).

### 3.15 Miedema interfacial enthalpy

The chemical interaction of an atom of $A$ dissolved in $B$ at infinite dilution (Bakker[^bakker1998], Eq. (1); King
et al., Eq. (S4); de Boer et al.[^deboer1988]):

$$
\Delta H_{A\text{ in }B}^{\mathrm{inter}} = \frac{V_A^{2/3}\left[1 + a_A\left(\varphi_A^{\ast} - \varphi_B^{\ast}\right)\right]} {\tfrac{1}{2}\left(n_{\mathrm{ws},A}^{-1/3} + n_{\mathrm{ws},B}^{-1/3}\right)} \left[-P\left(\varphi_A^{\ast} - \varphi_B^{\ast}\right)^2 + Q\left(n_{\mathrm{ws},A}^{1/3} - n_{\mathrm{ws},B}^{1/3}\right)^2 - R_{\mathrm{hyb}}\right]
$$

* **Units.** kJ per mole of $A$.
* **Volume correction** $a_A$ (de Boer et al., Eq. 2.33): 0.14 for the alkali metals Li, Na, K, Rb and Cs; 0.10 for
  the divalent metals Be, Mg, Zn, Cd, Hg, Ca, Sr and Ba; 0.07 for Cu, Ag, Au, Al, Ga, In, Tl, Sc, Y and La; 0.04 for
  all other metals.
* **Constant** $P$ (de Boer et al., Eqs. 2.35–2.36): 14.2 when both elements are transition metals, 10.7 when
  neither is, 12.35 otherwise. For $P$, Ca, Sr and Ba count as non-transition metals. $Q = 9.4 P$.
* **Hybridisation term** $R_{\mathrm{hyb}}$: non-zero only between a d-type metal (a transition metal, or Ca, Sr or
  Ba) and a non-transition metal, with $R_{\mathrm{hyb}} = P\thinspace h_{d}\thinspace h_{p}$, where $h_{d}$ and
  $h_{p}$ are the element factors of de Boer et al., Fig. 2.28 (for example Fe 1.0, Cu 0.3, Al 1.9, Si 2.1;
  Ca, Sr and Ba 0.4). Between two d-type metals or two non-transition metals $R_{\mathrm{hyb}} = 0$.
* **Unavailable** when an element lacks parameters or a classification, or a required hybridisation factor; M8 is
  then N/A with the element or pair named.

### 3.16 Miedema elastic enthalpy

The size-mismatch energy of $A$ dissolved in $B$ (Eshelby continuum model; Bakker, Eqs. (14) and (28); King et al.,
Eqs. (S5)–(S6)):

$$
\alpha = \frac{3}{2}\frac{V_A^{2/3}}{n_{\mathrm{ws},A}^{-1/3} + n_{\mathrm{ws},B}^{-1/3}}, \qquad W_A = V_A + \frac{\alpha\left(\varphi_A^{\ast} - \varphi_B^{\ast}\right)}{n_{\mathrm{ws},A}}, \qquad W_B = V_B - \frac{\alpha\left(\varphi_A^{\ast} - \varphi_B^{\ast}\right)}{n_{\mathrm{ws},B}}
$$

$$
\Delta H_{A\text{ in }B}^{\mathrm{el}} = \frac{2 K_A G_B \left(W_A - W_B\right)^2}{3 K_A W_B + 4 G_B W_A}
$$

* **Units.** With $K$ and $G$ in $10^{10}$ Pa and $W$ in cm³ mol⁻¹ the expression is in units of 10 kJ mol⁻¹; the
  engine multiplies by 10 to obtain kJ per mole of $A$.
* **Sign convention.** The volume change follows Bakker's derivation ($A$ expands when
  $\varphi_A^{\ast} \gt \varphi_B^{\ast}$). The expression printed by King et al., written as $V - \Delta V$, is
  not consistent with that derivation; Bakker's form is used.
* **Undefined** if the denominator vanishes (not reached with the stored data); M8 is then N/A.

### 3.17 Structural enthalpy

Bakker, Part I §5.2 and Eqs. (51)–(54): for two transition metals $A$ and $B$ with valences $z_A$, $z_B$ at
fractions $c_A$, $c_B$,

$$
\Delta H_{AB}^{\mathrm{struct}} = E_{\mathrm{lat}}(\bar{z}) - c_A E_{\mathrm{lat}}(z_A) - c_B E_{\mathrm{lat}}(z_B), \qquad \bar{z} = c_A z_A + c_B z_B
$$

* **Variables.** $E_{\mathrm{lat}}(z)$ is the most negative of the hcp, fcc and bcc lattice stabilities, linearly
  interpolated in the tabulated curves of Bakker's Fig. 6 on $3 \le z \le 10$.
* **Applicability.** Non-zero only when both elements are transition metals other than Cu, Ag and Au; zero for any
  pair involving a non-transition metal, and zero if a valence lies outside the tabulated range. Bakker states that
  the structural term "is only non-zero for a solid solution of two transition metals".
* **Units.** kJ mol⁻¹.

### 3.18 King model parameters

King et al. (2016)[^king2016], Supplementary Eqs. (S1)–(S10), with the Miedema terms above. For a binary $AB$ at
fractions normalised to $c_A + c_B = 1$, the surface fractions are

$$
c_A^{\mathrm{s}} = \frac{c_A V_A^{2/3}}{c_A V_A^{2/3} + c_B V_B^{2/3}}, \qquad c_B^{\mathrm{s}} = 1 - c_A^{\mathrm{s}}
$$

**Binary random solid solution** (chemical, elastic and structural terms):

$$
\Delta H_{AB}^{\mathrm{ss}} = c_A c_B\left(c_B^{\mathrm{s}} \Delta H_{A\text{ in }B}^{\mathrm{inter}} + c_A^{\mathrm{s}} \Delta H_{B\text{ in }A}^{\mathrm{inter}}\right) + c_A c_B\left(c_B \Delta H_{A\text{ in }B}^{\mathrm{el}} + c_A \Delta H_{B\text{ in }A}^{\mathrm{el}}\right) + \Delta H_{AB}^{\mathrm{struct}}
$$

**Multicomponent solid solution** (Eq. (S8); each binary is evaluated at the pair ratio $c_i : c_k$):

$$
\Delta H_{\mathrm{ss}} = \sum_i \sum_{k \neq i} c_i \frac{c_k}{1 - c_i} \Delta H_{ik}^{\mathrm{ss}}
$$

**Ordered binary compound** (Bakker, Eq. (9); King et al., Eqs. (S9)–(S10), ordering parameter 8):

$$
\Delta H_{AB}^{\mathrm{int}} = \frac{1}{2}\left[1 + 8\left(c_A^{\mathrm{s}} c_B^{\mathrm{s}}\right)^2\right] \left(c_A c_B^{\mathrm{s}} \Delta H_{A\text{ in }B}^{\mathrm{inter}} + c_B c_A^{\mathrm{s}} \Delta H_{B\text{ in }A}^{\mathrm{inter}}\right)
$$

**Free energies and the parameter** $\Phi$ (King et al., §2.1):

$$
\Delta G_{\mathrm{ss}} = \Delta H_{\mathrm{ss}} - T_{\mathrm{m}} \Delta S_{\mathrm{mix}}, \qquad \Delta G_{\max} = \left\lfloor \frac{N}{2} \right\rfloor \Delta H_{\mathrm{int}}^{\max}, \qquad \Phi = \frac{\Delta G_{\mathrm{ss}}}{-\lvert \Delta G_{\max} \rvert}
$$

* **Variables.** $\Delta H_{\mathrm{int}}^{\max}$ is the $\Delta H_{ij}^{\mathrm{int}}$ of largest magnitude among the
  pairs of the composition, each evaluated at its pair ratio; $\lfloor N/2 \rfloor$ is the number of disjoint pairs
  that can form, the extension of King et al. to $N$ components. $\Delta G_{\max}$ keeps its sign; $\Phi$ uses its
  magnitude.
* **Units.** Enthalpies and free energies in kJ mol⁻¹; $\Phi$ dimensionless. $T_{\mathrm{m}} \Delta S_{\mathrm{mix}}$
  is converted from J mol⁻¹.
* **Implementation decisions.** (i) The ordered-compound enthalpy averages the forms for $A$ dissolved in $B$ and
  for $B$ dissolved in $A$; this gives the closest agreement with King's worked examples for Cr–Ni, Cu–Fe and Al–Ni. (ii) King's printed Eq. (S9)
  uses $c_A^{\mathrm{s}}$ where Bakker's Eq. (9) has $c_A$; Bakker's form is used, and the difference is below
  0.4 kJ mol⁻¹ for the worked examples. (iii) King et al. used Bakker's tabulated interfacial enthalpies where
  available and Miedema-model values otherwise; the engine evaluates the Miedema equation for every pair, which
  reproduces Bakker's table within rounding (Section 6.3).
* **Undefined** when $\Delta G_{\max} = 0$; $\Phi$ is then divergent and M8 is N/A (undefined).

### 3.19 Electronegativity difference

$$
\Delta\chi = \sqrt{\sum_i c_i \left(\chi_i - \bar{\chi}\right)^2}, \qquad \bar{\chi} = \sum_i c_i \chi_i
$$

* **Source.** Guo and Liu (2011), Eq. (4),[^guoliu2011] with the Pauling electronegativities of their Table 1
  (pp. 435–436). Singh et al. (2023)[^singh2023] use the same definition "following Guo et al." and the same values
  (Section 6.2). There is no factor 100, unlike $\delta$.
* **Variables.** $\chi_i$ is the Pauling electronegativity of element $i$, `electronegativity_pauling` in
  `data/periodic_table.json`, stored as printed (0.01).
* **Units.** Dimensionless (Pauling scale). Values on the Allen or other scales are a different quantity and are not
  mixed in.
* **Data and coverage.** The 73 elements of Guo and Liu's Table 1, which are exactly the elements with a Guo and Liu
  radius. Every value was read on a 220-dpi rendering of pp. 435–436 on 2026-11-03 and equals the PDF text layer of
  the same row; the radius on the same printed line confirms the row alignment
  (`tests/reference/guo_liu_2011_table1_pauling.json`). The 45 other elements (among them H, the noble gases, the
  halogens, As, Sb, Hg, Bi and Pu) have no value, and no value from another source is substituted. Table 1 cites
  webelements.com and Senkov and Miracle (2001) as its sources. The printed values are kept as printed, because they
  are the values with which the published $\Delta\chi$ were calculated; they were not compared with other Pauling
  compilations.
* **Use.** A descriptor only. No criterion M1–M8 reads it, and adding it changed no other descriptor, classification,
  reason, caution or warning (`tests/test_dchi.py::test_dchi_changes_no_other_descriptor_or_model`).
* **Unavailable** when any element of the composition has no tabulated $\chi_i$. The value is then N/A
  (`dchi` = None), the missing elements are listed in `dchi_missing`, and the reason (for example "No Guo & Liu (2011)
  Pauling electronegativity for Sb, so Δχ is not available.") is stored in `dchi_unavailable` and added to the
  warnings. Missing data is never replaced by zero.
* **Zero.** $\Delta\chi = 0$ is a valid value when all elements have the same tabulated $\chi$ (for example Ru, Pd, Os
  and Ir, all 2.20; Cu and Si, both 1.90). The engine returns exactly 0 in that case, as for $S_{\mathrm{E}}$ with equal
  diameters, instead of a rounding residue of order $10^{-16}$.
* **Presentation.** Optional results-table and export column "Δχ" (three decimals in the table, full precision in the
  exported file); Analysis group "Electronic structure"; Details; filters; the Symbols page of Help. The
  elemental $\chi_i$ is shown in the Elements panel (row χ, a dash for the elements without a value).

---

## 4. Phase-formation criteria

For each model the description distinguishes what the publication states from the conventions this project
adopted where the publication leaves a choice open. Boundary handling is described in Section 5.2; validation results
are summarised in Section 6.

### M1: Yang and Zhang (2012)

* **Publication.** X. Yang, Y. Zhang, Mater. Chem. Phys. 132 (2012) 233–238[^yang2012].
* **Rationale.** A solid solution is favoured when the entropic term at the melting temperature outweighs the mixing
  enthalpy and the atomic-size mismatch is small.
* **Governing equations.** $\Omega$ (Section 3.7) and $\delta_{\mathrm{CN12}}$ (Section 3.6).

| | Publication | Implementation |
|---|---|---|
| Solid solution | $\Omega \ge 1.1$ and $\delta \le 6.6$ % (text) | SS if $\Omega \ge 1.1$ and $\delta_{\mathrm{CN12}} \le 6.6$ % |
| Otherwise | Intermetallics and/or segregation | MP |
| Boundaries | Inclusive in the text; Table 1 lists CoCrFeNiAl3 with $\Omega = 1.10$ as a solid solution | Inclusive, with the tolerance of Section 5.2 |

* **Data.** $\Delta H_{\mathrm{mix}}$ from Takeuchi and Inoue (the authors' Ref. 39); radii from Kittel (Ref. 41),
  12-coordination values.
* **Implementation decisions.** The Kittel CN12 radii are used because the authors cite Kittel and their Table 1
  $\delta$ values are reproduced with them (Section 6). In the comparison recorded during development (finding F3 of
  the development history), Kittel CN12 radii gave a median error of 0.003 in their Table 1 $\delta$ and Guo and Liu
  radii a median error of 0.43. MP is reported outside the region, because the criterion does not identify the
  competing phase.
* **Missing data.** N/A when $\Delta H_{\mathrm{mix}}$ or a CN12 radius is unavailable; N/A (undefined) when
  $\Delta H_{\mathrm{mix}} = 0$.
* **Limitations.** Empirical boundary fitted to as-cast alloys; MP does not distinguish intermetallics from segregated
  solid solutions. $\Omega$ depends on the elemental melting temperatures, which differ from the authors' set
  (Section 2.3).

### M2: Guo et al. (2013)

* **Publication.** S. Guo, Q. Hu, C. Ng, C.T. Liu, Intermetallics 41 (2013) 96–103[^guo2013].
* **Rationale.** An empirical map in the plane of $\delta$ and $\Delta H_{\mathrm{mix}}$ separating as-cast solid solutions,
  alloys containing intermetallics, and amorphous alloys.

| | Publication | Implementation |
|---|---|---|
| Solid solution | $\delta$ below about 6.6 % and $-11.6 \lt \Delta H_{\mathrm{mix}} \lt 3.2$ kJ mol⁻¹ (text) | SS if $\delta \le 6.6$ % and $-11.6 \le \Delta H_{\mathrm{mix}} \le 3.2$ kJ mol⁻¹ |
| Amorphous phase | $\delta \gt 6.4$ % and $\Delta H_{\mathrm{mix}} \lt -12.2$ kJ mol⁻¹ | MG if $\delta \gt 6.4$ % and $\Delta H_{\mathrm{mix}} \lt -12.2$ kJ mol⁻¹ (strict) |
| Intermetallic region | Shown graphically in Fig. 1, between the two regions; no numerical boundary | Not implemented |
| Otherwise | – | MP, with a caution |

* **Data.** Guo and Liu radii (reproduce Guo's Table 1, Section 6); Takeuchi and Inoue enthalpies.
* **Implementation decisions.** (i) The solid-solution boundaries are inclusive although the text prints strict
  inequalities, because Table 1 lists solid solutions exactly at $\Delta H_{\mathrm{mix}} = 3.20$ (FeCoNiCrCu) and
  $-11.60$ kJ mol⁻¹ (Al2CoCrCu0.5FeNi). (ii) The amorphous boundaries are strict as printed. (iii) The
  intermetallic region of Fig. 1 has no numerical definition, and no boundary was invented. A composition that
  satisfies neither printed criterion is reported as MP, with the caution "Outside both published Guo criteria. Fig. 1
  also defines an intermetallic region bounded only graphically, so SS / IM / other is not separated here." M2 therefore
  never returns IM.
* **Missing data.** N/A when $\Delta H_{\mathrm{mix}}$ or a radius is unavailable. A supplementary radius adds a
  caution.
* **Limitations.** Calibrated on as-cast alloys. Published intermetallic-containing alloys that fall in the numerical
  MG window are classified MG, and published amorphous alloys outside it are classified MP (Section 6.4).

### M3: Wang et al. (2015)

* **Publication.** Z. Wang, Y. Huang, Y. Yang, J. Wang, C.T. Liu, Scr. Mater. 94 (2015) 28–31[^wang2015].
* **Rationale.** The packing strain around the smallest and largest atoms, measured by the ratio of their solid
  angles, limits the solid solubility.
* **Criterion.** Publication: solid solution if $\gamma \lt 1.175$. Implementation: SS if $\gamma \lt 1.175$
  (strict, exact comparison), otherwise MP.
* **Data and evidence for the radius set.** The publication does not name its radius set. The Guo and Liu radii are
  used. This choice is supported by reproduction, not by a statement of the authors:
  * with superalloy compositions documented in the same group's supplementary data (Ye et al., Scripta Materialia
    2015, Table S2), Hastelloy B, Inconel 600, Nimonic 75 and Incoloy 800H reproduce Wang's printed $\delta$ and
    $\gamma$ to the last digit with the Guo and Liu radii at 0.1 pm; no other radius set gives an exact row;
  * with compositions reconstructed from manufacturers' data sheets, Guo and Liu radii reproduce the printed $\gamma$
    of 10 of 11 superalloys within $5 \times 10^{-4}$, Kittel's half nearest-neighbour distances 5 of 11 and Kittel
    CN12 radii none;
  * with the alloys of Guo et al. (2013), Guo and Liu radii give exactly the six solid solutions with $\delta \gt 0.06$
    mentioned by Wang et al. (Kittel CN12: one).

  These comparisons were made during development with scripts that are not part of the repository (Section 8.6); the
  regression tests check $\gamma$ against an independent evaluation of Wang's Eqs. (1)–(3) with the printed radii.
* **Missing data.** N/A when a radius is unavailable; a supplementary radius adds a caution.
* **Limitations.** A necessary geometric condition, not a complete phase-selection rule. The threshold 1.175 is the
  authors' empirical value and is used as printed. With Kittel radii $\gamma$, and occasionally the class, would differ.

### M4: Singh et al. (2014)

* **Publication.** A.K. Singh, N. Kumar, A. Dwivedi, A. Subramaniam, Intermetallics 53 (2014) 112–119[^singh2014].
* **Rationale.** The ratio of the configurational entropy to the squared size mismatch indicates whether a
  disordered solid solution is geometrically and entropically favoured.

| | Publication (Table 2) | Implementation |
|---|---|---|
| Disordered solid solution | $\Lambda \gt 0.96$ | SS if $\Lambda \gt 0.96$ (exact) |
| Solid solution and compounds | $\Lambda \in [0.24, 0.96]$ | SS+IM if $0.24 \le \Lambda \le 0.96$ |
| Compounds | $\Lambda \lt 0.24$ | IM if $\Lambda \lt 0.24$ |

* **Data.** Guo and Liu radii ($\delta$ in percent); $\Lambda$ in J mol⁻¹ K⁻¹.
* **Implementation decisions.** The middle class is named SS+IM after the publication's "disordered solid solution
  and compound(s)". The lower boundary 0.24 is inclusive with the tolerance of Section 5.2; the boundary 0.96 is
  evaluated as the strict condition $\Lambda \gt 0.96$ for SS, so $\Lambda = 0.96$ is SS+IM as in the closed interval.
* **Missing data.** N/A when a radius is unavailable; N/A (undefined) when $\delta = 0$.
* **Limitations.** Singh et al. took their radii from Smithells (their Ref. 47), not from Guo and Liu; a few of
  their rows are therefore reproduced only within tolerance or not at all (Section 6.4).

### M5: Ye et al. (2015)

* **Publication.** Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang, Scripta Materialia 104 (2015) 53–55[^ye2015]; the
  excess-entropy formulation follows Ye et al., Intermetallics 59 (2015) 75–80[^ye2015int].
* **Rationale.** A single solid solution forms when the configurational entropy, corrected for the enthalpic
  contribution, is large compared with the magnitude of the excess entropy caused by the atomic-size misfit.
* **Criterion.** Publication: single-phase solid solution for $\phi$ above a critical value
  $\phi_{\mathrm{c}} \approx 20$. Implementation: SS if $\phi \ge 20$, otherwise MP.
* **Implementation decisions.** (i) The publication gives $\phi_{\mathrm{c}} \approx 20$ without stating whether the
  boundary is inclusive; the project treats it as inclusive. (ii) $\lvert S_{\mathrm{E}} \rvert$ is the mean over the
  packing fractions 0.68 and 0.74, as in the main text. (iii) For identical radii $S_{\mathrm{E}} = 0$ exactly and
  M5 is N/A (undefined), not SS (Section 3.10).
* **Missing data.** N/A (missing data) when $\Delta H_{\mathrm{mix}}$ or a radius is unavailable; N/A (undefined)
  when $\phi$ is divergent or $S_{\mathrm{E}}$ cannot be evaluated. A supplementary radius adds a caution.
* **Limitations.** For distinct but nearly equal radii $\phi$ can be extremely large and sensitive to small radius
  differences; such compositions lie far outside the alloys on which $\phi_{\mathrm{c}}$ was calibrated.

### M6: Troparevsky et al. (2015)

* **Publication.** M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks, Phys. Rev. X 5 (2015)
  011041[^troparevsky2015].
* **Rationale.** A single solid solution is expected when no binary compound is stable enough to precipitate at the
  annealing temperature (lower bound $-T\Delta S_{\mathrm{mix}}$) and no pair is so unfavourable that the elements
  separate (upper bound 37 meV atom⁻¹).

| | Publication | Implementation |
|---|---|---|
| Single phase | $-T\Delta S_{\mathrm{mix}} \lt \Delta H_{\mathrm{f},ij} \lt 37$ meV atom⁻¹ for every pair (Table II) | SS if $\Delta H_{\mathrm{f}}^{\mathrm{lower}} \lt \Delta H_{\mathrm{f}}^{\min}$ and $\Delta H_{\mathrm{f}}^{\max} \lt 37$ meV atom⁻¹ (strict, exact) |
| Lower bound violated | Compound formation | IM (also when the upper bound is violated as well) |
| Only upper bound violated | Phase separation | MP |

* **Temperature.** The annealing temperature from Calculation settings, or $f\thinspace T_{\mathrm{m}}$ with
  $f = 0.55$ by default. Troparevsky et al. note that the annealing temperatures of the known single-phase HEAs
  correspond to 0.53–0.56 $T_{\mathrm{m}}$ and later refer to $T_{\mathrm{crit}} = 0.55 T_{\mathrm{M}}$; Senkov and
  Miracle describe the model in the same way. The temperature and its source are reported with each result.
* **Data.** The published matrix (Section 2.6), with the asymmetric-entry rule and the flagged values.
* **Implementation decisions.** The names IM and MP for the two violations are project conventions. A verdict that
  involves a flagged cell has the status `data_suspect` and names the cell; an asymmetric pair is named in a caution.
* **Missing data.** N/A when a pair is outside the 30-element matrix, or when no temperature is available.
* **Limitations.** Only binary compounds are considered. The result depends on the assessment temperature.

### M7: Senkov and Miracle (2016)

* **Publication.** O.N. Senkov, D.B. Miracle, J. Alloys Compd. 658 (2016) 603–607[^senkov2016].
* **Rationale.** A solid solution forms when its free energy is lower than that of a partially ordered intermetallic
  whose enthalpy is estimated from the binary formation enthalpies.
* **Governing equation.** Eq. (6) of the publication:

$$
\Delta H_{\mathrm{mix}} - T\Delta S_{\mathrm{mix}} \lt \Delta H_{\mathrm{IM}} - k_2 T \Delta S_{\mathrm{mix}}, \qquad k_2 = 0.6
$$

* **Criterion.** SS if the inequality holds (strict, exact), otherwise IM. For $\Delta H_{\mathrm{mix}} \lt 0$ the
  inequality is identical to the published form $k_1 \lt k_1^{\mathrm{cr}}(T)$ (Eqs. (7)–(8)); dividing by
  $\Delta H_{\mathrm{mix}}$ reverses the inequality when $\Delta H_{\mathrm{mix}} \gt 0$ and is impossible when it is
  zero, so the engine evaluates Eq. (6) directly.
* **Domain and extrapolation.** Section 1.1 of the publication assumes the relations hold "for HEAs with negative
  values of $\Delta H_{\mathrm{mix}}$". For $\Delta H_{\mathrm{mix}} \ge 0$ the verdict is still evaluated, but it has
  the status `extrapolated` and a caution stating the published domain; for $\Delta H_{\mathrm{mix}} = 0$ the caution
  adds that the $k_1/k_1^{\mathrm{cr}}$ form is undefined and only the free-energy form can be evaluated. The
  evaluation of Eq. (6) reproduces the published classes of the alloys of Table 1 with positive $\Delta H_{\mathrm{mix}}$
  (for example CoCrCuFeMn).
* **Temperature and data.** As M6; $\Delta H_{\mathrm{mix}}$ from Takeuchi and Inoue (their Ref. 12),
  $\Delta H_{\mathrm{IM}}$ from the Troparevsky matrix (Ref. 16, Eq. (9)). A flagged cell gives the status
  `data_suspect`.
* **Missing data.** N/A when a Troparevsky pair or $\Delta H_{\mathrm{mix}}$ is missing, or no temperature is available.
* **Limitations.** Senkov and Miracle's printed $\Delta H_{\mathrm{mix}}$ column differs from the Takeuchi and Inoue
  values they cite for several alloys (Section 6.4), so their printed $k_1^{\mathrm{cr}}$ is not always reproduced.

### M8: King et al. (2016)

* **Publication.** D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie, Acta Materialia 104 (2016)
  172–179[^king2016].
* **Rationale.** A solid solution is stable when its free energy of formation at $T_{\mathrm{m}}$ is more negative
  than that of the most stable binary intermetallic, with both estimated from Miedema's model.
* **Governing equations.** Section 3.18.
* **Criterion.** SS if $\Phi \ge 1$, otherwise MP. The boundary is inclusive with the tolerance of Section 5.2.
* **The atomic-size condition is not part of the criterion.** King et al. state the solid-solution condition in
  §3.1 as $\Phi \ge 1$. The condition $\delta \le 6.6$ % (with Goldschmidt 12-coordination radii, their Eq. (5))
  appears in §3.4, where it is one of the filters used to generate candidate alloys. King et al. keep NbTiV2Zr, "the
  only system that has both $\Phi \gt 1$ and $\delta \gt 6.6$", among the successful predictions. The engine
  therefore applies $\Phi \ge 1$ alone and requires no radius. For example CrMnNbTaW ($\Phi = 1.467$,
  $\delta_{\mathrm{CN12}} = 6.61$ %) is SS.
* **Data.** Bakker's Miedema parameters for 57 elements; the classification of Ca, Sr and Ba follows de Boer et al.
  (1988)[^deboer1988]: they are divalent d-type metals for the hybridisation term (factor 0.4, Fig. 2.28; program
  Table V-3) and non-transition metals for $P$ (Eqs. 2.35–2.36), with volume coefficient $a = 0.10$ (Eq. 2.33).
* **Temperature.** $T_{\mathrm{m}}$, as in the publication; the setting used for M6 and M7 does not apply.
* **Missing data.** N/A when an element has no Miedema parameters or classification (for example the lanthanides
  Ce–Lu), with the element named; N/A (undefined) when $\Delta G_{\max} = 0$.
* **Limitations.** King et al. used tabulated interfacial enthalpies where available; the equation reproduces them
  within rounding, but the accuracy of $\Phi$ for compositions far from the published examples is not established.
  M8 results for alloys containing Ca, Sr or Ba have no published counterpart (Section 7.7).

---

## 5. Numerical implementation

### 5.1 Floating-point evaluation

All quantities are evaluated in IEEE 754 double precision. Sums over pairs are formed in the order of the elements in
the composition; a value that equals a printed threshold mathematically can therefore differ from it in the last bit.
For example, $\Delta H_{\mathrm{mix}}$ of equiatomic CoCrFeNiCu evaluates to 3.2000000000000006 kJ mol⁻¹ against
Guo's boundary 3.2. Numerical values in the results table are rounded for display only; boundary comparisons and
exports use the full values.

### 5.2 Inclusive and strict inequalities

Each boundary is implemented with the inequality printed in the publication, except where Section 4 records a
project convention.

* **Inclusive comparisons** ($\ge$, $\le$) accept a value within a relative tolerance of the bound:
  $x \ge L$ is evaluated as $x \ge L - 10^{-12}\lvert L \rvert$, and $x \le L$ as
  $x \le L + 10^{-12}\lvert L \rvert$ (`engine.THRESHOLD_REL_TOL`). The tolerance is twelve orders of magnitude finer
  than the precision of any printed threshold; it absorbs representation error and nothing else. A difference of
  0.01, or of one printed digit, still changes the class.
* **Strict comparisons** ($\lt$, $\gt$) are evaluated exactly. A source that prints a strict inequality states that
  the bound itself is excluded, so a value exactly at the bound is not inside the region.

| Model | Boundary | Comparison | Tolerance |
|---|---|---|---|
| M1 | $\Omega \ge 1.1$; $\delta_{\mathrm{CN12}} \le 6.6$ % | Inclusive | Yes |
| M2 (SS) | $\delta \le 6.6$ %; $-11.6 \le \Delta H_{\mathrm{mix}} \le 3.2$ kJ mol⁻¹ | Inclusive (project convention, Section 4) | Yes |
| M2 (MG) | $\delta \gt 6.4$ %; $\Delta H_{\mathrm{mix}} \lt -12.2$ kJ mol⁻¹ | Strict | No |
| M3 | $\gamma \lt 1.175$ | Strict | No |
| M4 | $\Lambda \gt 0.96$ (SS); $\Lambda \ge 0.24$ (SS+IM) | Strict; inclusive | No; yes |
| M5 | $\phi \ge 20$ | Inclusive (project convention) | Yes |
| M6 | $\Delta H_{\mathrm{f}}^{\mathrm{lower}} \lt \Delta H_{\mathrm{f},ij} \lt 37$ meV atom⁻¹ | Strict | No |
| M7 | Eq. (6) | Strict | No |
| M8 | $\Phi \ge 1$ | Inclusive | Yes |
| VEC rule | $\mathrm{VEC} \ge 8.0$; $\mathrm{VEC} \lt 6.87$ | As printed | No |

Both sides of every boundary are tested in `tests/test_model_boundaries.py` and `tests/test_engine_behaviour.py`.

### 5.3 Undefined parameters

A ratio whose denominator vanishes is divergent, not large, and is never reported as infinite. The descriptor is
then unavailable with a reason, and the model that uses it is N/A with the kind "undefined":

| Quantity | Condition | Affected model |
|---|---|---|
| $\Omega$ | $\Delta H_{\mathrm{mix}} = 0$ exactly | M1 |
| $\Lambda$ | $\delta = 0$ exactly | M4 |
| $\phi$ | $\lvert S_{\mathrm{E}} \rvert \lt 10^{-15}$ J mol⁻¹ K⁻¹ (in practice $S_{\mathrm{E}} = 0$ for identical radii) | M5 |
| $\Phi$ | $\Delta G_{\max} = 0$ exactly | M8 |
| $k_1$, $k_1^{\mathrm{cr}}$ | $\Delta H_{\mathrm{mix}} = 0$ | None (M7 evaluates Eq. (6); the result is marked extrapolated) |

No descriptor is ever infinite; this is asserted over several thousand compositions in
`tests/test_model_boundaries.py::test_no_descriptor_is_ever_infinite`.

### 5.4 Missing-data propagation

Missing data make only the dependent quantities unavailable (Section 2.7). Each N/A result carries a reason and one of
three kinds: `missing_data` (an elemental property or binary pair is absent), `undefined` (Section 5.3) or `error`
(the composition could not be evaluated at all, for example an unknown symbol). The kinds are stored with each result,
so collection statistics count missing and undefined results separately and never as zero.

### 5.5 Evidence status, warnings and cautions

Every evaluated classification has one of three statuses:

* `in_domain`: the criterion is applied as the publication defines it;
* `extrapolated`: evaluated outside the stated domain of the criterion (M7 with $\Delta H_{\mathrm{mix}} \ge 0$);
* `data_suspect`: the verdict involves a binary value the dataset flags as unreliable (M6, M7).

Cautions accompany M2 outside both printed regions, M2–M5 with a supplementary radius, M6 with an asymmetric pair,
and every extrapolated or data-suspect verdict. An N/A result carries a reason and no caution; an evaluated result
carries at most a caution and no reason.

### 5.6 Model eligibility and coverage

`Engine.model_support(element)` reports, for each model, whether an element's own data allow it to be evaluated
(`ok`), allow it only with supplementary data (`warn`), depend on the partner elements' binary data (`pair`), or do
not allow it (`none`). `Engine.model_coverage(elements)` evaluates the equiatomic alloy of an element set and returns
the reason of every model that is N/A for missing data; it is used to warn before a calculation. Both are derived from
the engine itself, and their agreement with the actual evaluation is tested for every element and element pair
(`tests/test_model_support_consistency.py`, `tests/test_m8_support.py`). The availability of data does not imply
that a model has been validated for those elements.

### 5.7 Reproducibility of results

* The engine is deterministic: the same composition and settings give bit-identical results.
* Each calculation run stores the application version, the engine fingerprint (`provenance.engine_version()`, a hash
  of `engine.py` and `data.py`) and the dataset identifiers (`provenance.dataset_ids()`, hashes of the three data
  files). Any change to the engine source or the data changes these identifiers, even if no number changes.
* Stored session results are not recalculated after a change of engine or data.

---

## 6. Validation against published results

### 6.1 Reference data and method

Published values are transcribed in [`tests/reference/`](../tests/reference). The main catalogue,
`published_benchmarks.json`, holds 846 cases from the eight model publications, each with its DOI, table location,
formula, settings, a statement of how reproducible it is from the published information, the published values and
classes, and the observed phases where reported. Only published numbers are stored; no reference value was produced
by the engine.

A published value is **reproduced exactly** when the engine's value lies within half a unit of the last printed digit.
It is **within tolerance** when the difference exceeds that but stays within the documented tolerance of the quantity
(`_metadata.tolerances` in the catalogue):

| Quantity | Tolerance | Reason |
|---|---|---|
| $\delta$ (Guo and Liu) | ±0.05 | Radius precision of the authors' data |
| $\delta_{\mathrm{CN12}}$ | ±0.02 | Rounding of compositions |
| $\Delta H_{\mathrm{mix}}$ | ±0.02 kJ mol⁻¹ | Rounding of compositions (integer binary table) |
| $\Omega$ | 2 % | The authors' elemental melting temperatures |
| $\Lambda$ | 2 % | Twice the relative radius error of $\delta$ |
| $\lvert S_{\mathrm{E}} \rvert$ | 5 % | Cancellation in $S_{\mathrm{E}}$ amplifies radius precision |
| $\phi$ | 2 % | Inherits the $S_{\mathrm{E}}$ sensitivity |
| $\Delta H_{\mathrm{IM}}$ | ±0.02 kJ mol⁻¹ | Integer matrix values |
| King $\Delta G_{\mathrm{ss}}$ | ±0.4 kJ mol⁻¹ | Tabulated (integer) versus equation interfacial enthalpies |
| King $\Delta H^{\mathrm{int}}$, $\Delta G_{\max}$ | ±0.6 kJ mol⁻¹ | As above, and the ordered-compound prefactor |
| King $\Phi$ | ±0.03 | Ratio of two quantities each within tolerance |
| Troparevsky cells | 0 | Stored verbatim |

A value that is reproduced neither exactly nor within tolerance is a **known discrepancy** only if it is listed, with
its cause, in `KNOWN_DISCREPANCIES` of `tests/test_published_benchmarks.py`. The test fails if an unlisted value
disagrees and also if a listed discrepancy starts to agree, so a documented discrepancy cannot disappear silently.
Some tolerance reasons in the catalogue metadata refer to the earlier 0.01 pm radius values; the tolerances themselves
are unchanged.

### 6.2 Numerical reproduction of published values

Measured 2026-11-02 with the current engine and data, using the classification of `test_published_benchmarks.py`.

| Model | Source | Quantity | Cases | Exact | Within tolerance | Known discrepancies |
|---|---|---|---:|---:|---:|---:|
| M1 | Yang and Zhang, Table 1 | $\delta_{\mathrm{CN12}}$ | 133 | 109 | 8 | 16 |
| M1 | Yang and Zhang, Table 1 | $\Delta H_{\mathrm{mix}}$ | 133 | 124 | 3 | 6 |
| M2 | Guo et al., Table 1 | $\delta$ | 93 | 81 | 10 | 2 |
| M2 | Guo et al., Table 1 | $\Delta H_{\mathrm{mix}}$ | 93 | 91 | 1 | 1 |
| M4 | Singh et al., Table 1 | $\delta$ | 76 | 54 | 14 | 8 |
| M4 | Singh et al., Table 1 | $\Lambda$ | 76 | 26 | 41 | 9 |
| M5 | Ye et al., Intermetallics 59, supplementary tables | $\lvert S_{\mathrm{E}} \rvert / k_{\mathrm{B}}$ | 174 | 170 (see note) | 1 | 3 |
| M5 | Ye et al., Scripta Materialia 104, p. 54 | $\phi$ | 2 | 2 | 0 | 0 |
| M6 | Troparevsky et al., text | Matrix cells, $\Delta H_{\mathrm{f}}^{\min}$, $\Delta H_{\mathrm{f}}^{\mathrm{lower}}$ | 5 | 5 | 0 | 0 |
| M7 | Senkov and Miracle, Table 1 | $\Delta H_{\mathrm{IM}}$ | 45 | 42 | 2 | 1 |
| M8 | King et al., §2.1 worked examples | $\Delta G_{\mathrm{ss}}$, $\Delta H^{\mathrm{int}}$, $\Delta G_{\max}$ | 3 each | 0 | 3 each | 0 |
| M8 | King et al., §2.1 worked examples | $\Phi$ | 3 | 2 | 1 | 0 |
| M8 | King et al., §3.2.1 | $\Phi$ | 1 | 0 | 0 | 1 |
| Descriptor | Guo and Liu (2011), Table 2, p. 437 | $\Delta\chi$ | 41 | 40 | 0 | 1 |
| Descriptor | Singh et al. (2023), Tables 2–3 | $\Delta\chi$ | 6 | 6 (truncated, see note) | 0 | 0 |

Note on $\Delta\chi$ (measured 2026-11-03; `tests/test_dchi.py`, `tests/reference/dchi_published.json`): Guo and Liu
print two decimals; 40 of the 41 rows of p. 437 with an unambiguous formula agree within half a unit, four equiatomic
binaries (Cu50Zr50 0.285, Ni50Nb50 0.155, Zr50Ti50 0.105, Mg50Cu50 0.295) falling exactly on a rounding half that the
table rounds up. The row "6FeNiCoSiCrAlTi" and the continuation of the table on p. 438 (PDF text layer without row
alignment) were not transcribed. Singh et al. print three to five decimals and agree with **truncation**, not rounding:
for all six alloys $0 \le \Delta\chi_{\mathrm{engine}} - \Delta\chi_{\mathrm{printed}}$ is less than one unit of the
last printed digit (for example 0.36157 printed 0.361, 0.35656 printed 0.356, 0.23690 printed 0.236); under the
half-unit rule three of the six would count as within one unit only. The test asserts the truncation rule.

Note on $\lvert S_{\mathrm{E}} \rvert$: the catalogue stores, for each alloy, the mean of the two printed
packing-fraction columns, so many reference values have more digits than any printed number. The test resolves them
to 0.001, at which 170 of 174 agree; to the last digit of the stored value 75 agree. In a separate comparison recorded
on 2026-10-28 (development history, §4 M5), 159 of 174 rows reproduced both printed columns exactly. All except the 3
known discrepancies are within the 5 % tolerance.

Quantities compared as diagnostics only (not asserted case by case, because an input of the publication is not the
dataset value):

| Model | Quantity | Cases | Exact | Within tolerance | Outside tolerance | Reason |
|---|---|---:|---:|---:|---:|---|
| M1 | $\Omega$ | 133 | 36 | 86 | 11 | Yang and Zhang's melting temperatures (Section 2.3) |
| M7 | $\Delta H_{\mathrm{mix}}$ | 45 | 2 | 9 | 34 | Senkov and Miracle's printed column is not the Takeuchi and Inoue value |
| M7 | $k_1^{\mathrm{cr}}$ | 45 | 15 | 11 | 19 | Follows from the $\Delta H_{\mathrm{mix}}$ difference |

$\Omega$ is additionally asserted for selected rows within 2 % (`test_yang_zhang_omega_examples`).

### 6.3 Validation of the datasets

| Check | Result | Kind | Test |
|---|---|---|---|
| Troparevsky matrix against the transcription of the supplement (`troparevsky_supplement.json`), cell by cell, with the seven asymmetric pairs | Identical; the three cells quoted in the text exact | Exact reproduction (of a transcription made by eye from the figure) | `test_datasets.py::test_formation_matrix_is_the_published_troparevsky_matrix`, `test_formation_values_quoted_in_papers` |
| Senkov and Miracle $\Delta H_{\mathrm{IM}}$ from the matrix | 44 of 45 within ±0.02 kJ mol⁻¹ (42 exact); the remaining row is a likely table typo | Exact and within tolerance | `test_senkov_2016_dhim_from_published_troparevsky_matrix` |
| Miedema equation against Bakker Table A2 (transition-metal pairs) | 840 pairs, maximum deviation 2.09 kJ mol⁻¹ (integer table) | Within tolerance | `test_miedema_formula_reproduces_bakker_table_a2` |
| Miedema equation against Bakker Tables A3/A4, Ca, Sr, Ba with 24 transition metals | 48 values each; rms 1.76, 1.80, 1.11; maximum 3.0, 3.5, 2.4 kJ mol⁻¹ | Within tolerance | `test_miedema_reproduces_bakker_a3_a4_alkaline_earth` |
| Same tables, Mg and Al | Maximum 1.2 and 2.5 kJ mol⁻¹ | Within tolerance | `test_miedema_reproduces_bakker_a3_a4_calibration_rows` |
| de Boer et al. Table V-4.02 (non-transition pairs) | 238 of 240 within 2.0 kJ mol⁻¹; Be in As and Sb in Cd printed values not reproduced | Within tolerance; 2 discrepancies | `test_miedema_reproduces_de_boer_table_v4_02` |
| Takeuchi and Inoue liquid enthalpies of Ca, Sr, Ba with transition metals, from a test-side de Boer liquid formula | Within 2.0 kJ mol⁻¹; Ba with non-transition metals a known discrepancy | Within tolerance; known discrepancy | `tests/test_miedema_takeuchi_inoue.py` |
| Classification of Ca, Sr, Ba ($P$, hybridisation, $a$) | Source rules typed into the test | Internal consistency against the source rules | `test_miedema_classification_ca_sr_ba`, `test_miedema_volume_coefficient` |
| Miedema parameters against Bakker Tables A1/A5 | Identical for the checked elements | Exact | `test_miedema_parameters_match_bakker_tables_a1_a5` |
| Guo and Liu radii against Table 1 | All 73 printed values | Exact | `test_atomic_radius_equals_guo_liu_table1_exactly` |
| Guo and Liu Pauling electronegativities against Table 1 (rendered pp. 435–436) | All 73 printed values; no value for the 45 other elements | Exact | `test_dchi.py::test_pauling_value_equals_guo_liu_table1`, `test_only_table1_elements_have_a_pauling_value` |
| Kittel CN12 radii against Table 9 | All transcribed values | Exact | `test_kittel_cn12_radii` |
| Takeuchi and Inoue table completeness | 73 elements, 2,628 pairs | Internal consistency | `test_mixing_table_covers_73_elements_completely` |

**Radius conventions.** The reproduction rates in Section 6.2 are the main evidence for the radius assignment. In
the cross-comparison recorded during development (§17.1 of the development history), Kittel CN12 radii reproduced
Guo's $\delta$ exactly in 1 of 93 rows (5 within tolerance), Singh's in 3 of 76 (4) and Ye's
$\lvert S_{\mathrm{E}} \rvert$ in 1 of 174 (47), whereas in the same comparison the printed Guo and Liu radii
reproduced 81 (91), 56 (68) and 75 (171). Yang and Zhang's $\delta$ is reproduced with Kittel radii, and so are the
six $\delta$ values of Zhang et al. (2008),[^zhang2008] an earlier publication of the same group that also cites
Kittel (§17.2). The comparison with alternative radius sets is not part of the regression tests.

**Ca, Sr and Ba.** An independent re-derivation of King's chain for 11 alloys, with the source rules written out
in the test, agrees with the engine to $10^{-10}$ relative (`tests/test_m8_alkaline_earth_independent.py`); it
shares the elemental data with the engine, so it verifies the implementation of the rules, not the data.

### 6.4 Classifications

Comparison with the classes printed by each publication (the authors' own application of their criterion), measured
2026-11-02:

| Model | Source | Rows | Agree | Disagree | Notes |
|---|---|---:|---:|---:|---|
| M1 | Yang and Zhang, Table 1 | 133 | 132 | 1 | CoCrFeNiAl3: printed $\Omega = 1.10$ (SS), computed 1.098 (MP); caused by the melting-temperature set |
| M2 | Guo et al., Table 1 | 93 | 93 | 0 | |
| M3 | Wang et al., Table 1 | – | – | – | Table 1 gives no compositions; see M3 in Section 4 |
| M4 | Singh et al., Table 1 | 76 | 76 | 0 | |
| M5 | Ye et al., Scripta Materialia, Table S1 and p. 54 | 43 | 43 | 0 | 41 rows of Table S1 and the two text examples; Al0.3CoCrFeNi and Al0.5CrCuFeNi2 are not counted because their printed $\phi$ values for the two packing fractions lie on either side of 20 |
| M6 | Troparevsky et al., Table I | 20 | 20 | 0 | FeCoNi base at 1000 K and NbMoTa base at 1673 K |
| M7 | Senkov and Miracle, Table 1 | 45 | 43 | 2 | CrMo0.5NbTa0.5TiZr and CrNbTiVZr; their printed $\Omega$ and $k_1^{\mathrm{cr}}$ are internally inconsistent |
| M8 | King et al., §2.1 and §3.2.1 | 4 | 4 | 0 | |

Comparison with **experimentally observed phases** concerns the predictive power of each criterion, not the
implementation. Recorded on 2026-10-27 for the current engine and data (§20 of the development history): M2 agrees
with the observed phase for 71 of 93 alloys, M4 for 75 of 76 and M5 for 41 of 43. Examples of documented disagreements:

* M2: three published alloys containing intermetallics (CoCrFeNiTi, AlCoCrFeNiTi1.5, ZrTiVCuNiBe) lie in the
  numerical MG window and are classified MG; three published amorphous alloys (Cu0.5NiAlCoCrFeSi, CoCrCuFeNiZr0.6,
  CoCrCuFeNiZr0.8) lie outside it and are classified MP. FeCoNiCrCuAl3 has $\delta = 6.610$ %, is classified MP by
  Guo's criterion (as printed by Guo) and is observed as a solid solution.
* M6, M7: CoFeMnMoNi (observed FCC + intermetallic[^otto2013]) and CrNbTiZr (observed BCC + Laves) are classified IM
  with the published matrix.

The mapping of reported phases to classes used for these counts was made with development scripts that are not in
the repository (Section 8.6).

### 6.5 King worked examples

| Alloy | Quantity | Published | Engine | Difference |
|---|---|---:|---:|---:|
| CoCrFeNi | $\Delta G_{\mathrm{ss}}$ (kJ mol⁻¹) | −23.43 | −23.74 | −0.31 |
| CoCrFeNi | $\Delta H^{\mathrm{int}}$, Cr–Ni (kJ mol⁻¹) | −10.08 | −10.03 | +0.05 |
| CoCrFeNi | $\Phi$ | 1.16 | 1.183 | +0.023 |
| CoCrCuFeNi | $\Delta G_{\mathrm{ss}}$ | −21.08 | −21.11 | −0.03 |
| CoCrCuFeNi | $\Delta H^{\mathrm{int}}$, Cu–Fe | 19.14 | 19.32 | +0.18 |
| CoCrCuFeNi | $\Phi$ | 0.55 | 0.546 | −0.004 |
| AlCoCrFeNi | $\Delta G_{\mathrm{ss}}$ | −33.89 | −33.81 | +0.08 |
| AlCoCrFeNi | $\Delta H^{\mathrm{int}}$, Al–Ni | −47.33 | −47.49 | −0.16 |
| AlCoCrFeNi | $\Phi$ | 0.36 | 0.356 | −0.004 |
| Co43Cr1Fe7Ni49 (§3.2.1) | $\Phi$ | 8.93 | 9.288 | +0.36 (+4.0 %) |

The three equimolar examples agree within the stated tolerances. Co43Cr1Fe7Ni49 is a documented discrepancy: a
non-equimolar alloy with a very small $\lvert \Delta G_{\max} \rvert$ (1.53 kJ mol⁻¹), for which the difference
between tabulated and equation interfacial enthalpies is amplified. The constants were not adjusted to fit it.

### 6.6 Tests of implementation consistency and independent verification

| Subject | What is tested | Kind | Test file |
|---|---|---|---|
| Boundaries | Both sides of every threshold; tolerance absorbs one ULP but not 0.01 | Internal consistency | `test_model_boundaries.py`, `test_engine_behaviour.py` |
| Undefined parameters | No infinite descriptor; reasons surfaced by the models | Internal consistency | `test_model_boundaries.py` |
| Missing data | A missing pair is N/A, a tabulated zero is a value | Internal consistency | `test_engine_behaviour.py`, `test_model_boundaries.py` |
| M7 domain | Extrapolated status for $\Delta H_{\mathrm{mix}} \ge 0$; Eq. (6) for both signs | Internal consistency | `test_model_boundaries.py`, `test_engine_behaviour.py` |
| M8 criterion | $\Phi$ alone; no radius needed; published worked examples | Internal consistency and reproduction | `test_model_boundaries.py`, `test_m8_support.py` |
| Excess entropy limits | $S_{\mathrm{E}} = 0$ for equal diameters; never positive; second-order limit for nearly equal diameters; merging of equal-diameter species; $A(\xi)$ constants | Independent verification (analytic) | `test_m5_excess_entropy_limits.py` |
| Radius correction isolation | The printed Guo and Liu radii change only quantities that read `atomic_radius` | Internal consistency | `test_radius_f2_invariance.py` |
| $\gamma$ and $\Lambda$ | Independent evaluation of Wang's and Singh's equations with the printed radii | Independent verification | `test_model_support_consistency.py` |
| Model availability | `model_support` agrees with evaluation for every element pair | Internal consistency | `test_model_support_consistency.py`, `test_m8_support.py` |
| Ca, Sr, Ba in M8 | Engine against a re-derivation from the source rules | Independent verification (shared data) | `test_m8_alkaline_earth_independent.py` |

### 6.7 Outside the validation domain

The engine evaluates every composition for which data exist. Results are formal applications of the criteria, not
validated predictions, in particular for

* elements with supplementary radii (M2–M5), and Pm, Po, Pa and U, which no published M2–M5 alloy contains;
* alloys containing Ca, Sr or Ba in M8 (no published King result exists for them);
* compositions with nearly equal radii (very large $\phi$ and $\Lambda$);
* compositions with $\Delta H_{\mathrm{mix}} \ge 0$ in M7 (marked extrapolated);
* alloy families absent from a model's calibration set, such as light-metal or non-metal-rich compositions.

---

## 7. Known discrepancies and scientific limitations

Items are labelled **confirmed** (checked against the printed source), **interpretation** (a reading of an ambiguous
source adopted by this project) or **open** (unresolved).

### 7.1 Published values not reproduced

| Publication | Case | Discrepancy | Status and explanation |
|---|---|---|---|
| Yang and Zhang, Table 1 | 20 rows, 22 printed values ($\delta_{\mathrm{CN12}}$ or $\Delta H_{\mathrm{mix}}$) | For example CoCrFeNiCuAl0.3 $\Delta H_{\mathrm{mix}}$ printed 1.56 (Guo prints 0.16, engine 0.157); CuNi $\delta$ 1.63 (engine 1.19) | Confirmed on the rendered pages: printed so. Not reproducible from the formula and cited data. |
| Guo et al., Table 1 | SrCaYb(Li0.55Mg0.45)Zn | $\delta$ printed 15.63, engine 15.71 | Confirmed; cause not identified. |
| Guo et al., Table 1 | Ti2.5CrCuFeCoNi | Printed $\delta$ and $\Delta H_{\mathrm{mix}}$ are those of Ti2CrCuFeCoNi | Confirmed. |
| Singh et al., Table 1 | 8 rows | $\delta$ and $\Lambda$ not reproduced | Confirmed; not reproducible with the paper's radius source. |
| Singh et al., Table 1 | Mo0.3CoCrFeNi | $\Lambda$ 2.2686 against printed 2.317 (−2.09 %, tolerance 2 %); $\delta$ within tolerance | Confirmed; Singh et al. used Smithells radii. The test requires the difference to stay between 2 % and 3 %. |
| Ye et al., Intermetallics 59, supplementary tables | Rows S-005, S-042, S-166 | $\lvert S_{\mathrm{E}} \rvert$ not reproduced | Confirmed as internally inconsistent rows of the source (S-005: packing-fraction ratio and $S_{\mathrm{c}}$ of a different alloy; S-042: one packing column inconsistent; S-166: corresponds to a different C content). |
| Senkov and Miracle, Table 1 | Al0.3NbTa0.8Ti1.4V0.2Zr1.3 | $\Delta H_{\mathrm{IM}}$ printed −5.62, engine −6.69 | Interpretation: likely a typographical error in the table. |
| Senkov and Miracle, Table 1 | Printed $\Delta H_{\mathrm{mix}}$ column | Differs from the cited Takeuchi and Inoue values by up to 7 kJ mol⁻¹ for Al-containing refractory alloys (for example Al0.5CoCrCuFeNi printed −3.40, table −1.52, as also printed by Yang and Zhang and Guo et al.) | Confirmed. With the printed $\Delta H_{\mathrm{mix}}$, Eq. (7) reproduces the printed $k_1^{\mathrm{cr}}$ in 33 of 45 rows; three rows (CrMo0.5NbTa0.5TiZr, CrNbTiVZr, CrNbTiZr) violate the table's own relation $k_1^{\mathrm{cr}} = 1 + 0.4\thinspace\Omega$. |
| King et al., §3.2.1 | Co43Cr1Fe7Ni49 | $\Phi$ 9.288 against 8.93 (+4.0 %) | Confirmed; attributed to tabulated versus equation inputs. |
| Guo and Liu (2011), Table 2 | Zr50Ni50 | $\Delta\chi$ printed 0.24; from the paper's own Table 1, $\lvert 1.33 - 1.91 \rvert / 2 = 0.29$ exactly | Confirmed on the rendered page (p. 437); a misprint. The reference keeps 0.24 and the test asserts the difference. |
| Singh et al. (2023), Tables 2–3 | All six $\Delta\chi$ | Printed values are truncated, not rounded (Section 6.2) | Confirmed; a printing convention, not a disagreement. |
| de Boer et al., Table V-4.02 | Be in As; Sb in Cd | Printed +2 and −1 kJ mol⁻¹; equation +21 and −11 | Confirmed as printed. |
| Takeuchi and Inoue | Ba with 19 non-transition metals | Mean +2.0, maximum 4.9 kJ mol⁻¹ from the printed factor 0.4 | Interpretation: the Ba rows behave like a factor 0.5; the printed factor 0.4 is kept. |

### 7.2 Missing or uncertain source data

* **Supplementary radii (open).** 35 radii of undocumented origin; 10 elements without a radius (Section 2.2).
* **Molar volumes of 47 elements (open).** Not from Bakker's Table A1, source not recorded; they affect only the
  density descriptor.
* **Melting temperatures, atomic weights, valence numbers (open).** Standard values without a recorded source.
* **Elemental density (open).** Display-only property without a recorded source; gaseous elements are stored as gas
  densities in g L⁻¹ at 0 °C and 1 atm under the panel's g cm⁻³ label.
* **$n_{\mathrm{ws}}$ precision (open).** Stored to two decimals as in Bakker's Table A1; worth 1–3 kJ mol⁻¹ in
  interfacial enthalpies of low-density metals against de Boer's tabulated $n_{\mathrm{ws}}^{1/3}$.
* **Provenance of the higher-precision radii (resolved).** The 0.01 pm radius values used before the correction to
  the printed Guo and Liu values traced partly to the review of Zhang et al. (2014)[^zhang2014], Table 1, and partly
  to no identifiable source; they are no longer used. The development record identifies that table only as "Zhang et
  al. (2014) Table 1"; the attribution to the cited review has not been re-verified.

### 7.3 Ambiguous published definitions

* **M2 intermetallic region (confirmed ambiguity).** Defined only graphically; not implemented (Section 4).
* **M3 radius set (interpretation).** Not named by the authors; Guo and Liu radii adopted on reproduction evidence.
* **M5 boundary and conventions (interpretation).** $\phi_{\mathrm{c}} \approx 20$ treated as inclusive. The
  supplementary tables of the Scripta paper print $\phi$ per packing fraction under two conventions that are not the
  main-text definition: Table S2 fits
  $\phi(\xi) = (S_{\mathrm{c}} - S_{\mathrm{H}})/\lvert S_{\mathrm{E}}(\xi) \rvert$ (42 of 43 within 2 %), Table S1
  fits a mixed form (39 of 43 within 1 %). Neither form is stated in the
  papers; these are reconstructions. The engine implements the main-text definition; its classification agrees with
  Table S1 for all 41 rows that do not straddle $\phi = 20$.
* **M7 domain (confirmed).** The derivation assumes $\Delta H_{\mathrm{mix}} \lt 0$; results outside are marked
  extrapolated.
* **M8 equations (interpretation).** King's printed Eq. (S9) and elastic-term expression differ from Bakker's
  derivations; Bakker's forms are used (Section 3.16, 3.18).
* **Miedema program line for $P$ (interpretation).** de Boer et al.'s printed program (Table V-3) would give
  $P = 10.74$ for Ca, Sr and Ba with transition metals. This contradicts the book's Eqs. 2.35–2.36 and its own tables,
  and is read as a misprint.
* **Zr radius (open).** Guo et al. (2013) imply 160.2 pm, Ye's data 160.3 pm.
* **V–Cu formation enthalpy (open).** Printed as 13 and 54 meV atom⁻¹; the choice can change M6 for V- and Cu-containing
  alloys, because the upper bound is 37 meV atom⁻¹.

### 7.4 Flagged binary formation enthalpies

45 Troparevsky pairs are flagged (Section 2.6). The magnitudes of Fe–Nb (−2505) and Fe–Ta (−3468) suggest a unit or
transcription error in the publication; this is a hypothesis, not a confirmed finding. For example, FeTa is classified
IM by M6 with the status `data_suspect`. A corrected matrix from the authors would replace the values directly.

### 7.5 Extrapolation beyond the published domains

M7 for $\Delta H_{\mathrm{mix}} \ge 0$ is marked extrapolated. The other models have no stated domain in their
publications beyond their calibration alloys; results far outside those alloys (Section 6.7) are formal predictions.

### 7.6 Sensitivity near classification boundaries

* A threshold comparison is exact up to representation error (Section 5.2), but the descriptors inherit the
  uncertainty of their data. Small data differences can change a class near a boundary. For example FeCoNiCrCuAl3 has
  $\delta = 6.610$ % with the printed Guo and Liu radii (MP in M2, as printed by Guo) and 6.598 % with the former
  0.01 pm values (SS); NbMoTaV has $\Lambda = 0.96009$, which is SS in M4 by a margin of $9 \times 10^{-5}$ (it was
  SS+IM with the former values, $\Lambda = 0.958$).
* For Ca-, Sr- and Ba-containing compositions, 113 of the compositions examined during development lie within
  $\lvert \Phi - 1 \rvert \lt 0.05$; their M8 classes are sensitive to the Miedema inputs.
* For nearly equal radii, $\phi$ and $\Lambda$ are very large and sensitive to radius differences, although the class
  far from the threshold is robust.

### 7.7 Alloy families without experimental validation

* **Ca, Sr, Ba in M8.** The classification follows de Boer et al. and reproduces Bakker's interfacial enthalpies
  (Section 6.3), but no published M8 result exists for these alloys.
* **Pm, Po, Pa, U in M2–M5**, and elements with supplementary radii: no published alloy behind these models contains
  them.
* **Lanthanides in M8.** Not evaluated (no Miedema classification). Whether they should be treated as transition
  metals in Miedema's scheme is an open question.

---

## 8. Reproducibility and test methodology

### 8.1 Locations of data and reference values

| Content | Location |
|---|---|
| Calculation engine | `hea_calc/core/engine.py` |
| Dataset loading, symmetric lookup, flagged pairs | `hea_calc/core/data.py` |
| Elemental properties | `data/periodic_table.json` |
| Liquid mixing enthalpies | `data/mixing_enthalpy_data.json` |
| Formation enthalpies and their quality metadata | `data/binary_formation_enthalpy_data.json` |
| Bibliography used by the application | `hea_calc/core/references.py` |
| Engine and dataset fingerprints | `hea_calc/core/provenance.py` |
| Published benchmark catalogue (846 cases) | `tests/reference/published_benchmarks.json` |
| Transcribed published tables used by individual tests | `tests/reference/published_tables.py` |
| Guo and Liu Table 1; Kittel CN12; Bakker Tables A2, A3/A4; de Boer Table V-4.02; Troparevsky supplement | `tests/reference/*.json` |
| Guo and Liu Table 1 Pauling column; published $\Delta\chi$ (Guo and Liu Table 2, Singh et al. 2023) | `tests/reference/guo_liu_2011_table1_pauling.json`, `tests/reference/dchi_published.json` |
| Published values plotted in Analysis (display only; not read by the engine) | `data/model_figures.json`, built by `tools/build_model_figures.py` |

### 8.2 Use of published values in the tests

* `tests/test_published_benchmarks.py` compares every catalogue case with a fully sourced quantity against the engine,
  using the exact / within-tolerance rule of Section 6.1 and the list of known discrepancies.
* `tests/test_models_published.py` checks the published tables by model (Yang and Zhang, Guo, Singh, Senkov and
  Miracle, Ye, King, Troparevsky), each with its documented exceptions.
* `tests/test_datasets.py` checks the datasets against their printed sources (Section 6.3).
* Tests that pin a behaviour without a published oracle are described as such in their docstrings (Section 6.6).

Tolerances were chosen from the precision of the published inputs. For the Ca, Sr and Ba tests the tolerances (4.0
and 2.0 kJ mol⁻¹) were set after the residuals were known, with the $n_{\mathrm{ws}}$ explanation of Section 7.2.

### 8.3 Provenance recording

Each dataset records its source and conventions in `_metadata`; corrections to values are noted there with their
date. Calculation runs store the engine fingerprint and dataset identifiers (Section 5.7). The bibliography of the
application is maintained in one place, `hea_calc/core/references.py`, from which the README footnotes, the Help
pages and the About window are checked.

### 8.4 Running the verification tests

The scientific tests run without a display:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run pytest -q tests/test_published_benchmarks.py tests/test_models_published.py tests/test_datasets.py tests/test_model_boundaries.py tests/test_engine_behaviour.py tests/test_m5_excess_entropy_limits.py tests/test_miedema_takeuchi_inoue.py tests/test_m8_alkaline_earth_independent.py tests/test_m8_support.py tests/test_model_support_consistency.py tests/test_radius_f2_invariance.py tests/test_dchi.py
```

The full suite is run with `uv run pytest -q` (see [`CONTRIBUTING.md`](../CONTRIBUTING.md#development)). Test counts
change as tests are added; counts quoted in the development history are historical.

### 8.5 What has and has not been validated

**Validated** against printed sources: the published numerical tables listed in Section 6.2, the published classes
of Section 6.4, the datasets of Section 6.3, and the analytic limits of the excess entropy.

**Not validated**: classifications for compositions outside the publications' alloys (Section 6.7); the elements with
supplementary radii; the sources of the data listed in Section 7.2; M3 against the printed $\gamma$ within the
regression tests (no compositions are given in Wang's Table 1); and the general predictive accuracy of any criterion
for phase formation, which is a property of the published criterion and not of this implementation.

### 8.6 Material not in the repository

Part of the evidence summarised above was obtained during development with material that is not in this repository:
the publication PDFs and supplements, the investigation reports and scripts, and an independent validator with 799
checks. Their results are recorded with dates in [`docs/SCIENTIFIC_DEVELOPMENT_HISTORY.md`](SCIENTIFIC_DEVELOPMENT_HISTORY.md),
which lists the missing material. These results cannot be re-run from the repository; where this document relies on
them (the M3 radius evidence, the observed-phase comparisons, the radius-set cross-comparisons and the Ca, Sr and Ba
impact analysis), it says so. The comparisons of earlier engine versions with the original
HEACalculator[^sariturk2019] are also part of that record.

---

[^yang2012]: X. Yang, Y. Zhang, Prediction of high-entropy stabilized solid-solution in multi-component alloys,
    Mater. Chem. Phys. 132 (2012) 233–238.
    [https://doi.org/10.1016/j.matchemphys.2011.11.021](https://doi.org/10.1016/j.matchemphys.2011.11.021).
[^guo2013]: S. Guo, Q. Hu, C. Ng, C.T. Liu, More than entropy in high-entropy alloys: Forming solid solutions or
    amorphous phase, Intermetallics 41 (2013) 96–103.
    [https://doi.org/10.1016/j.intermet.2013.05.002](https://doi.org/10.1016/j.intermet.2013.05.002).
[^wang2015]: Z. Wang, Y. Huang, Y. Yang, J. Wang, C.T. Liu, Atomic-size effect and solid solubility of multicomponent
    alloys, Scr. Mater. 94 (2015) 28–31.
    [https://doi.org/10.1016/j.scriptamat.2014.09.010](https://doi.org/10.1016/j.scriptamat.2014.09.010).
[^singh2014]: A.K. Singh, N. Kumar, A. Dwivedi, A. Subramaniam, A geometrical parameter for the formation of
    disordered solid solutions in multi-component alloys, Intermetallics 53 (2014) 112–119.
    [https://doi.org/10.1016/j.intermet.2014.04.019](https://doi.org/10.1016/j.intermet.2014.04.019).
[^ye2015]: Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang, Design of high entropy alloys: A single-parameter
    thermodynamic rule, Scripta Materialia 104 (2015) 53–55.
    [https://doi.org/10.1016/j.scriptamat.2015.03.023](https://doi.org/10.1016/j.scriptamat.2015.03.023).
[^troparevsky2015]: M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks, Criteria for Predicting the
    Formation of Single-Phase High-Entropy Alloys, Phys. Rev. X 5 (2015) 011041.
    [https://doi.org/10.1103/PhysRevX.5.011041](https://doi.org/10.1103/PhysRevX.5.011041).
[^senkov2016]: O.N. Senkov, D.B. Miracle, A new thermodynamic parameter to predict formation of solid solution or
    intermetallic phases in high entropy alloys, J. Alloys Compd. 658 (2016) 603–607.
    [https://doi.org/10.1016/j.jallcom.2015.10.279](https://doi.org/10.1016/j.jallcom.2015.10.279).
[^king2016]: D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie, Predicting the formation and stability of
    single phase high-entropy alloys, Acta Materialia 104 (2016) 172–179.
    [https://doi.org/10.1016/j.actamat.2015.11.040](https://doi.org/10.1016/j.actamat.2015.11.040).
[^guoliu2011]: S. Guo, C.T. Liu, Phase stability in high entropy alloys: Formation of solid-solution phase or
    amorphous phase, Progress in Natural Science: Materials International 21 (2011) 433–446.
    [https://doi.org/10.1016/S1002-0071(12)60080-X](https://doi.org/10.1016/S1002-0071%2812%2960080-X).
[^takeuchi2005]: A. Takeuchi, A. Inoue, Classification of Bulk Metallic Glasses by Atomic Size Difference, Heat of
    Mixing and Period of Constituent Elements and Its Application to Characterization of the Main Alloying Element,
    Materials Transactions 46 (2005) 2817–2829.
    [https://doi.org/10.2320/matertrans.46.2817](https://doi.org/10.2320/matertrans.46.2817).
[^bakker1998]: H. Bakker, Enthalpies in Alloys: Miedema’s Semi-empirical Model, Trans Tech Publications, Zürich, 1998.
[^kittel2005]: C. Kittel, Introduction to Solid State Physics, 8th ed., John Wiley & Sons, Hoboken, NJ, 2005.
[^guo2011vec]: S. Guo, C. Ng, J. Lu, C.T. Liu, Effect of valence electron concentration on stability of fcc or bcc
    phase in high entropy alloys, Journal of Applied Physics 109 (2011) 103505.
    [https://doi.org/10.1063/1.3587228](https://doi.org/10.1063/1.3587228).
[^deboer1988]: F.R. de Boer, R. Boom, W.C.M. Mattens, A.R. Miedema, A.K. Niessen, Cohesion in Metals: Transition Metal
    Alloys, North-Holland, Amsterdam, 1988.
[^mansoori1971]: G.A. Mansoori, N.F. Carnahan, K.E. Starling, T.W. Leland, Equilibrium Thermodynamic Properties of the
    Mixture of Hard Spheres, J. Chem. Phys. 54 (1971) 1523–1525.
    [https://doi.org/10.1063/1.1675048](https://doi.org/10.1063/1.1675048).
[^ye2015int]: Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang, The generalized thermodynamic rule for phase selection in
    multicomponent alloys, Intermetallics 59 (2015) 75–80.
    [https://doi.org/10.1016/j.intermet.2014.12.011](https://doi.org/10.1016/j.intermet.2014.12.011).
[^zhang2008]: Y. Zhang, Y.J. Zhou, J.P. Lin, G.L. Chen, P.K. Liaw, Solid-Solution Phase Formation Rules for
    Multi-component Alloys, Adv. Eng. Mater. 10 (2008) 534–538.
    [https://doi.org/10.1002/adem.200700240](https://doi.org/10.1002/adem.200700240).
[^zhang2014]: Y. Zhang, T.T. Zuo, Z. Tang, M.C. Gao, K.A. Dahmen, P.K. Liaw, Z.P. Lu, Microstructures and properties
    of high-entropy alloys, Prog. Mater. Sci. 61 (2014) 1–93.
    [https://doi.org/10.1016/j.pmatsci.2013.10.001](https://doi.org/10.1016/j.pmatsci.2013.10.001).
[^chen2005]: X.-Q. Chen, W. Wolf, R. Podloucky, P. Rogl, Ab initio study of ground-state properties of the Laves phase
    compounds TiCr2, ZrCr2, and HfCr2, Phys. Rev. B 71 (2005) 174101.
    [https://doi.org/10.1103/PhysRevB.71.174101](https://doi.org/10.1103/PhysRevB.71.174101).
[^otto2013]: F. Otto, Y. Yang, H. Bei, E.P. George, Relative effects of enthalpy and entropy on the phase stability of
    equiatomic high-entropy alloys, Acta Materialia 61 (2013) 2628–2638.
    [https://doi.org/10.1016/j.actamat.2013.01.042](https://doi.org/10.1016/j.actamat.2013.01.042).
[^singh2023]: S. Singh, N.K. Katiyar, S. Goel, S.N. Joshi, Phase prediction and experimental realisation of a new
    high entropy alloy using machine learning, Sci. Rep. 13 (2023) 4811. Not the authors of model M4.
    [https://doi.org/10.1038/s41598-023-31461-7](https://doi.org/10.1038/s41598-023-31461-7).
[^sariturk2019]: D. Sarıtürk, HEACalculator, Zenodo (2019).
    [https://doi.org/10.5281/zenodo.3590318](https://doi.org/10.5281/zenodo.3590318).
