# Phase-Formation Models M1–M8

The eight published criteria, as the calculator implements them. Bounds are stated with their inclusive (≤, ≥) or
strict (<, >) form; the numbers in brackets refer to [Scientific References](help://references).

## Calculated quantities

The calculations are based on normalized atomic fractions, *c<sub>i</sub>*. At least two elements must be present in
a composition. The table summarizes the main quantities, equations and data sources used in the application.

| Quantity | Equation or method | Data source | Description |
|---|---|---|---|
| ΔS<sub>mix</sub> | −R Σ *c<sub>i</sub>* ln *c<sub>i</sub>* | — | Ideal configurational entropy |
| ΔH<sub>mix</sub> | Σ<sub>i<j</sub> 4 *c<sub>i</sub>c<sub>j</sub>* ΔH<sub>ij</sub> | Takeuchi & Inoue (2005) [10], Miedema liquid enthalpies | Regular-solution estimate |
| T<sub>m</sub>, ρ | Rule of mixtures (ρ = Σ *c<sub>i</sub>M<sub>i</sub>* / Σ *c<sub>i</sub>V<sub>i</sub>*) | Elemental tables; Miedema molar volumes [11] | Approximation without excess terms |
| VEC | Σ *c<sub>i</sub>* VEC<sub>i</sub>; FCC if ≥ 8.0, BCC if < 6.87 | Guo et al. (2011) [13] | Empirical structure rule |
| δ | 100 √Σ *c<sub>i</sub>*(1 − *r<sub>i</sub>*/r̄)² | Guo & Liu (2011) radii [9] | Atomic-size mismatch used in M2–M5 |
| δ<sub>CN12</sub> | Same equation | Kittel CN12 radii [12] | Atomic-size mismatch used in M1 |
| Δχ | √Σ *c<sub>i</sub>*(χ<sub>i</sub> − χ̄)², χ̄ = Σ *c<sub>i</sub>*χ<sub>i</sub> (Guo & Liu, Eq. 4) | Guo & Liu (2011) Pauling electronegativities [9] | Electronegativity difference; used by no model |
| Ω, γ, Λ, φ, Φ, ΔH<sub>IM</sub>, k<sub>1</sub><sup>cr</sup> | Calculated according to the corresponding model | — | Model-dependent parameters |

Δχ is N/A when an element has no Pauling value in Guo & Liu's table (for example Sb, Bi or Hg); no other
electronegativity scale is substituted. The e/a ratio is not calculated. The remaining symbols, their units and
definitions are given under [Symbols, Parameters and Units](help://symbols).

## M1 — Yang & Zhang (2012): Ω–δ criterion

*X. Yang, Y. Zhang [1].* Separates solid-solution-forming compositions from those that form intermetallics or
segregate, using the balance of mixing entropy and enthalpy at the melting temperature and the atomic-size mismatch.

* **Criterion.** SS if Ω ≥ 1.1 **and** δ<sub>CN12</sub> ≤ 6.6 %; otherwise MP. Both bounds are inclusive.
* Ω = T<sub>m</sub>ΔS<sub>mix</sub>/|ΔH<sub>mix</sub>|; δ<sub>CN12</sub> = 100·√Σc<sub>i</sub>(1 − r<sub>i</sub>/r̄)² with
  Kittel's 12-coordination radii, the radius set the authors cite.
* **Limitations.** Empirical boundary fitted to as-cast alloys; MP does not distinguish intermetallics from
  segregated solid solutions.

## M2 — Guo et al. (2013): δ–ΔH<sub>mix</sub> map

*S. Guo, Q. Hu, C. Ng, C.T. Liu [2].* Locates a composition on the empirical δ–ΔH<sub>mix</sub> map that separates
solid solutions, intermetallic-containing alloys and the amorphous phase.

* **Criterion.** SS if δ ≤ 6.6 % and −11.6 ≤ ΔH<sub>mix</sub> ≤ 3.2 kJ mol⁻¹ (inclusive: the alloys of the
  publication's Table 1 at both edges are solid solutions); amorphous (MG) if δ > 6.4 % and ΔH<sub>mix</sub> < −12.2
  kJ mol⁻¹; otherwise MP. δ uses the Guo & Liu (2011) radii.
* **Limitation.** The publication bounds its intermetallic region only graphically; the calculator reports MP outside
  both printed criteria and does not separate intermetallics from other multiphase states.

## M3 — Wang et al. (2015): γ criterion

*Z. Wang, Y. Huang, Y. Yang, J. Wang, C.T. Liu [3].* Measures the packing strain around the smallest and largest atoms
through the ratio of their solid angles.

* **Criterion.** SS if γ < 1.175 (strict), otherwise MP; γ = ω<sub>S</sub>/ω<sub>L</sub>, ω = 1 − √[((r + r̄)² −
  r̄²)/(r + r̄)²] for the smallest (S) and largest (L) atom.
* **Calculator convention.** The publication does not name its radius set; the calculator uses the Guo & Liu (2011)
  radii of the same research group. This choice is supported by reproduction rather than by a statement of the
  authors: for 10 of the 11 superalloys of the paper's Table 1 whose compositions could be reconstructed from data
  sheets, Guo & Liu radii reproduce the printed γ to within 5 × 10⁻⁴ (the eleventh, one of two Inconel 690 rows, is
  reproduced by no radius set), and with the Guo et al. (2013) alloys they give exactly the six
  solid solutions with δ > 0.06 that the paper mentions; Kittel 12-coordination radii reproduce none of the printed γ
  values. With Kittel radii, γ and occasionally the verdict differ.
* **Limitation.** A necessary geometric condition, not a complete phase-selection rule.

## M4 — Singh et al. (2014): Λ criterion

*A.K. Singh, N. Kumar, A. Dwivedi, A. Subramaniam [4].*

* **Criterion.** Λ = ΔS<sub>mix</sub>/δ² (δ in %): SS if Λ > 0.96; solid solution with compounds (SS+IM) if 0.24 ≤ Λ ≤
  0.96; intermetallic compounds (IM) if Λ < 0.24 (J mol⁻¹ K⁻¹).

## M5 — Ye et al. (2015): φ criterion

*Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang [5].*

* **Criterion.** φ = (S<sub>c</sub> − S<sub>H</sub>)/|S<sub>E</sub>|, with S<sub>H</sub> = |ΔH<sub>mix</sub>|/T<sub>m</sub>
  and the excess entropy S<sub>E</sub> of a hard-sphere mixture averaged over the bcc (0.68) and fcc (0.74) packing
  fractions. SS if φ ≥ 20 (the authors' critical value φ<sub>c</sub> ≈ 20; the calculator treats the boundary as
  inclusive), otherwise MP.
* **Limitation: nearly equal atomic sizes.** For distinct but nearly equal radii S<sub>E</sub> is small without being
  zero (to leading order it is proportional to δ²), so φ remains evaluable. |φ| can then become very large and is
  sensitive to small radius differences; its sign is that of S<sub>c</sub> − S<sub>H</sub>. Far from φ<sub>c</sub> the
  verdict is then robust while the numerical value is not; a composition whose φ lies near φ<sub>c</sub> ≈ 20 can
  change class with small radius differences. Such compositions lie far outside the alloys on which φ<sub>c</sub> was
  calibrated.
* **Undefined φ: identical atomic sizes.** If r<sub>1</sub> = r<sub>2</sub> = … = r<sub>n</sub>, the mixture behaves
  as a single hard-sphere fluid and S<sub>E</sub> = 0 exactly at both packing fractions (0.68 and 0.74). The denominator
  |S<sub>E</sub>| of φ then vanishes, so φ is undefined and M5 returns N/A (undefined), not a solid-solution
  prediction.

## M6 — Troparevsky et al. (2015): binary formation-enthalpy window

*M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks [6].* A composition forms a single solid solution
if no binary compound is so stable that it precipitates and no pair is so unfavourable that it separates.

* **Criterion.** SS if −T·ΔS<sub>mix</sub> < ΔH<sub>f</sub>(i,j) < 37 meV atom⁻¹ for **every** pair (strict). A pair at
  or below the lower bound → IM; only the upper bound exceeded → MP (calculator convention for naming the two
  violations).
* **Temperature.** The annealing temperature from [Calculation Settings](help://calculation-settings), or f ×
  T<sub>m</sub> (default f = 0.55) when none is set.
* **Data.** DFT formation enthalpies of the lowest-energy binary compounds of 30 elements; see
  [Binary Interaction Data](help://binary-data).

## M7 — Senkov & Miracle (2016): solid solution versus intermetallic free energy

*O.N. Senkov, D.B. Miracle [7].*

* **Criterion.** SS if ΔH<sub>mix</sub> − TΔS<sub>mix</sub> < ΔH<sub>IM</sub> − k<sub>2</sub>TΔS<sub>mix</sub> with
  k<sub>2</sub> = 0.6; otherwise IM. ΔH<sub>IM</sub> = Σ4c<sub>i</sub>c<sub>j</sub>ΔH<sub>f,ij</sub> from the Troparevsky
  data. For ΔH<sub>mix</sub> < 0 this is the published form k<sub>1</sub> < k<sub>1</sub><sup>cr</sup>.
* **Extrapolation.** The authors derive the criterion for alloys with ΔH<sub>mix</sub> < 0. For ΔH<sub>mix</sub> ≥ 0 the
  calculator evaluates the same free-energy inequality and marks the result **Extrapolated**.
* **Temperature.** As M6.

## M8 — King et al. (2016): Φ parameter

*D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie [8].*

* **Criterion.** Φ = ΔG<sub>ss</sub>/(−|ΔG<sub>max</sub>|) ≥ 1 → SS, otherwise MP.
* ΔG<sub>ss</sub> is the Gibbs energy of the disordered solid solution at T<sub>m</sub> from Miedema's model (chemical,
  elastic and — for pairs of transition metals — structural terms); ΔG<sub>max</sub> is the binary ordered compound of
  largest magnitude, scaled to the number of disjoint pairs.
* The δ ≤ 6.6 % screen the authors used to generate candidate alloys is not part of the criterion.

## Reading the predictions together

The models use different descriptors, data and thresholds, calibrated on different sets of alloys, and can classify
the same composition differently — AlCoCrFeNi is SS in M1 and M3, MP in M2, M5 and M8, SS+IM in M4, and IM in M6 and
M7. Treat the tags as independent screening indicators, not as votes on one answer. See
[Equiatomic CoCrFeMnNi](help://example-cantor) for a worked comparison.

## Implementation decisions

A number of decisions were necessary when the published criteria were implemented. Their sources and the reasons
for the decisions are discussed in `CALCULATION_AUDIT.md` in the source repository.

* **Numerical boundaries.** Strict and inclusive inequalities were implemented according to the publications. For
  inclusive boundaries, a relative tolerance of 10⁻¹² is used to account for floating-point rounding. For example,
  ΔH<sub>mix</sub> for CoCrFeNiCu is represented as 3.200000000000001. Without the tolerance, the composition would
  incorrectly fall outside the M2 boundary of 3.2 kJ mol⁻¹. Strict inequalities are evaluated without this tolerance.
* **M2.** Guo et al. illustrate the intermetallic region without giving a numerical boundary. Thus, compositions
  satisfying neither of the two printed conditions are assigned MP with a caution. The calculation does not identify
  a separate intermetallic region from the figure.
* **M7.** The criterion was derived for ΔH<sub>mix</sub> < 0. Equation 6 is also evaluated for compositions outside
  that range, but these results are identified as *Extrapolated*.
* **M8.** The implemented criterion is Φ ≥ 1. The δ ≤ 6.6 % condition in Section 3.4 of King et al. was applied
  during the selection of candidate compositions, whereas the criterion itself is given in Section 3.1.
* **Troparevsky dataset.** There are 43 cells in the published data that lie outside the range represented in the
  publication's figure. The original values were retained. Calculations involving these values are marked
  *Flagged binary data*.
* **Undefined parameters.** Some ratios cannot be calculated for particular compositions, such as Ω when
  ΔH<sub>mix</sub> = 0. The model is then reported as N/A with an explanation rather than assigning an infinite value.
* **Incomplete data.** When elemental or binary interaction data are unavailable, only the models requiring those
  values are reported as N/A. The other models are still calculated; missing values are not replaced with zero.
