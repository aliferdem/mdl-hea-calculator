# Prediction model coverage

## 1. Overview

The calculator evaluates eight published criteria (M1–M8) that predict whether a composition forms a single solid
solution. Each criterion uses its own descriptors and its own reference data. A model can therefore be available for
one composition and unavailable for another, and two models can disagree for the same composition. A model is
evaluated only when every elemental property and every binary value it needs is tabulated; otherwise the result is
*Not available* and the reason names the missing data. Missing data are never replaced by zero.

All eight models are available for compositions made only of these 30 elements:
**Mg, Al, Sc, Ti, V, Cr, Mn, Fe, Co, Ni, Cu, Zn, Y, Zr, Nb, Mo, Ru, Rh, Pd, Ag, Cd, La, Hf, Ta, W, Re, Os, Ir, Pt, Au.**

## 2. Model requirements

| Model | Descriptors | Elemental data | Binary data | Temperature |
|---|---|---|---|---|
| M1 Yang & Zhang (2012) | Ω, δ<sub>CN12</sub> | melting point; Kittel 12-coordination radius | Takeuchi & Inoue (2005) liquid mixing enthalpies | — |
| M2 Guo et al. (2013) | δ, ΔH<sub>mix</sub> | Guo & Liu (2011) atomic radius | Takeuchi & Inoue (2005) | — |
| M3 Wang et al. (2015) | γ | Guo & Liu (2011) atomic radius | — | — |
| M4 Singh et al. (2014) | Λ | Guo & Liu (2011) atomic radius | — | — |
| M5 Ye et al. (2015) | φ | Guo & Liu radius; melting point | Takeuchi & Inoue (2005) | — |
| M6 Troparevsky et al. (2015) | ΔH<sub>f</sub> of every pair, −TΔS<sub>mix</sub> | melting point (for 0.55·T<sub>m</sub>) | Troparevsky et al. (2015) formation enthalpies | annealing temperature or 0.55·T<sub>m</sub> |
| M7 Senkov & Miracle (2016) | ΔH<sub>mix</sub>, ΔH<sub>IM</sub>, TΔS<sub>mix</sub> | melting point | Takeuchi & Inoue (2005); Troparevsky et al. (2015) | as M6 |
| M8 King et al. (2016) | Φ = ΔG<sub>ss</sub>/(−|ΔG<sub>max</sub>|) | Miedema parameters (Bakker 1998): work function, electron density, molar volume, bulk and shear modulus, valence | computed from Miedema's model | melting point (T<sub>m</sub>) |

## 3. Model-by-model description

### M1 — Yang & Zhang (2012): Ω–δ criterion
*X. Yang, Y. Zhang, Mater. Chem. Phys. 132 (2012) 233–238.*
**Purpose.** Separates solid-solution-forming compositions from those that form intermetallics or segregate,
using the balance of mixing entropy and enthalpy at the melting temperature and the atomic-size mismatch.
**Criterion.** Solid solution (SS) if Ω ≥ 1.1 **and** δ<sub>CN12</sub> ≤ 6.6 %; otherwise multiple phases (MP).
Ω = T<sub>m</sub>ΔS<sub>mix</sub>/|ΔH<sub>mix</sub>|; δ<sub>CN12</sub> = 100·√Σc<sub>i</sub>(1 − r<sub>i</sub>/r̄)² with
Kittel's 12-coordination radii, the radius set the authors cite. Both bounds are inclusive.
**Not available when** a pair lacks a Takeuchi & Inoue value, an element lacks a Kittel radius, or ΔH<sub>mix</sub>
is exactly zero (Ω undefined — for example equiatomic CoNi).
**Limitations.** Empirical boundary fitted to as-cast alloys; MP does not distinguish intermetallics from
segregated solid solutions.

### M2 — Guo et al. (2013): δ–ΔH<sub>mix</sub> map
*S. Guo, Q. Hu, C. Ng, C.T. Liu, Intermetallics 41 (2013) 96–103.*
**Purpose.** Locates a composition on the empirical δ–ΔH<sub>mix</sub> map that separates solid solutions,
intermetallic-containing alloys and the amorphous phase.
**Criterion.** SS if δ ≤ 6.6 % and −11.6 ≤ ΔH<sub>mix</sub> ≤ 3.2 kJ mol⁻¹ (inclusive, as the alloys of Guo's
Table 1 at both edges are solid solutions); amorphous (MG) if δ > 6.4 % and ΔH<sub>mix</sub> < −12.2 kJ mol⁻¹;
otherwise MP. δ uses the Guo & Liu (2011) radii.
**Limitation.** The publication bounds its intermetallic region only graphically; the calculator therefore reports MP
outside both printed criteria and does not separate intermetallics from other multiphase states.

### M3 — Wang et al. (2015): γ criterion
*Z. Wang, Y. Huang, Y. Yang, J. Wang, C.T. Liu, Scr. Mater. 94 (2015) 28–31.*
**Purpose.** Measures the packing strain around the smallest and largest atoms through the ratio of their solid angles.
**Criterion.** SS if γ < 1.175 (strict), otherwise MP; γ = ω<sub>S</sub>/ω<sub>L</sub>,
ω = 1 − √[((r + r̄)² − r̄²)/(r + r̄)²] for the smallest (S) and largest (L) atom.
**Calculator convention.** The publication does not name its radius set; the calculator uses the Guo & Liu (2011)
radii of the same research group. With Kittel radii, γ and occasionally the verdict differ.
**Limitation.** A necessary geometric condition, not a complete phase-selection rule.

### M4 — Singh et al. (2014): Λ criterion
*A.K. Singh, N. Kumar, A. Dwivedi, A. Subramaniam, Intermetallics 53 (2014) 112–119.*
**Criterion.** Λ = ΔS<sub>mix</sub>/δ² (δ in %): SS if Λ > 0.96; solid solution with compounds (SS+IM) if
0.24 ≤ Λ ≤ 0.96; intermetallic compounds (IM) if Λ < 0.24 (J mol⁻¹ K⁻¹).
**Not available when** a radius is missing or δ = 0 (Λ undefined).

### M5 — Ye et al. (2015): φ criterion
*Y.F. Ye, Q. Wang, J. Lu, C.T. Liu, Y. Yang, Scr. Mater. 104 (2015) 53–55.*
**Criterion.** φ = (S<sub>c</sub> − S<sub>H</sub>)/|S<sub>E</sub>|, with S<sub>H</sub> = |ΔH<sub>mix</sub>|/T<sub>m</sub> and the
excess entropy S<sub>E</sub> of a hard-sphere mixture averaged over the bcc (0.68) and fcc (0.74) packing fractions.
SS if φ ≥ 20 (the authors' critical value φ<sub>c</sub> ≈ 20; the calculator treats the boundary as inclusive),
otherwise MP.
**Limitation.** For nearly equal atomic sizes |S<sub>E</sub>| approaches zero and φ becomes very large and sensitive
to small radius differences; the verdict is then robust, the numerical value is not.

### M6 — Troparevsky et al. (2015): binary formation-enthalpy window
*M.C. Troparevsky, J.R. Morris, P.R.C. Kent, A.R. Lupini, G.M. Stocks, Phys. Rev. X 5 (2015) 011041.*
**Purpose.** A composition forms a single solid solution if no binary compound is so stable that it precipitates and
no pair is so unfavourable that it separates.
**Criterion.** SS if −T·ΔS<sub>mix</sub> < ΔH<sub>f</sub>(i,j) < 37 meV atom⁻¹ for **every** pair (strict). A pair at
or below the lower bound → IM; only the upper bound exceeded → MP (calculator convention for naming the two
violations). T is the annealing temperature from *Settings*, or 0.55·T<sub>m</sub> when none is set.
**Data.** DFT formation enthalpies of the lowest-energy binary compounds, 30 elements (publication supplement).
Seven pairs are printed with two different values; the calculator uses the value in the row of the element that
comes first in the published order.
**Not available when** any element is outside the 30-element set.

### M7 — Senkov & Miracle (2016): solid solution versus intermetallic free energy
*O.N. Senkov, D.B. Miracle, J. Alloys Compd. 658 (2016) 603–607.*
**Criterion.** SS if ΔH<sub>mix</sub> − TΔS<sub>mix</sub> < ΔH<sub>IM</sub> − k₂TΔS<sub>mix</sub> with k₂ = 0.6; otherwise
IM. ΔH<sub>IM</sub> = Σ4c<sub>i</sub>c<sub>j</sub>ΔH<sub>f,ij</sub> from the Troparevsky data. For ΔH<sub>mix</sub> < 0 this is
the published form k₁ < k₁<sup>cr</sup>.
**Extrapolation.** The authors derive the criterion for alloys with ΔH<sub>mix</sub> < 0. For ΔH<sub>mix</sub> ≥ 0 the
calculator evaluates the same free-energy inequality and marks the result **Extrapolated**.
**Not available when** any element is outside the Troparevsky set, or ΔH<sub>mix</sub> is missing.

### M8 — King et al. (2016): Φ parameter
*D.J.M. King, S.C. Middleburgh, A.G. McGregor, M.B. Cortie, Acta Mater. 104 (2016) 172–179.*
**Criterion.** Φ = ΔG<sub>ss</sub>/(−|ΔG<sub>max</sub>|) ≥ 1 → SS, otherwise MP. ΔG<sub>ss</sub> is the Gibbs energy of
the disordered solid solution at T<sub>m</sub> from Miedema's model (chemical, elastic and — for pairs of transition
metals — structural terms); ΔG<sub>max</sub> is the binary ordered compound of largest magnitude, scaled to the
number of disjoint pairs. The δ ≤ 6.6 % screen used by the authors to generate candidate alloys is not part of the
criterion.
**Not available when** an element has no Miedema parameters (most lanthanides, noble gases, halogens), or Ca, Sr,
Ba are combined with transition metals (no Miedema hybridisation factor tabulated).

## 4. Element coverage

| Model | Supported elements | Count |
|---|---|---|
| M1 | Li Be B C Na Mg Al Si K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Th U Pu | 69 |
| M2, M5 | the 73 elements of the Takeuchi & Inoue table: H Li Be B C N Na Mg Al Si P K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Th U Pu — of which H, As, Sb, Hg, Bi, Pu use a supplementary radius ⚠ | 73 |
| M3, M4 | 73 elements with a Guo & Liu radius (Li Be B C N O Na Mg Al Si P S K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge Se Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Te Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Tl Pb Po Th Pa U) plus 35 with a supplementary radius ⚠ (H He F Ne Cl Ar As Br Kr Sb I Xe Hg Bi Fr Ra Ac Np Pu Am and the superheavy elements Rf–Og) | 108 |
| M6, M7 | Mg Al Sc Ti V Cr Mn Fe Co Ni Cu Zn Y Zr Nb Mo Ru Rh Pd Ag Cd La Hf Ta W Re Os Ir Pt Au | 30 |
| M8 | Li Be B C Na Mg Al Si P K Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Rb Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Cs La Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Th U Pu; Ca, Sr, Ba only without transition metals | 54 + 3 |

⚠ Supplementary radius: the value is not from Guo & Liu (2011) and its origin is not documented; the result carries a
caution. Predictions for noble gases, halogens and superheavy elements are formal evaluations without physical
meaning for alloys.

## 5. Binary dataset coverage

| Dataset | Elements | Pairs | Completeness |
|---|---|---|---|
| Takeuchi & Inoue (2005) liquid mixing enthalpies (kJ mol⁻¹) | 73 | 2,628 | every pair of the 73 elements is tabulated; 159 pairs are tabulated as exactly 0 kJ mol⁻¹, which is a value, not missing data |
| Troparevsky et al. (2015) formation enthalpies (meV atom⁻¹) | 30 | 435 | complete; 7 pairs printed with two values (Al–Ag, Ti–La, V–Cu, Cr–Cd, Mn–Mo, Co–Nb, Nb–Ir); 4 Laves values from Chen et al. (2005); 4 Re pairs referenced to the solid solution |
| Miedema interfacial enthalpies (kJ per mole of solute) | 57 | computed for any pair | reproduces Bakker (1998) Table A2 within ±2.1 kJ mol⁻¹ |

**Flagged binary data.** Some published Troparevsky values are
physically implausible: Fe–Ta −3468, Fe–Nb −2505, Al–Cd −1938, Fe–W −554 and Fe–Mo −484 meV atom⁻¹. The
publication attributes the Fe–Nb, Fe–Mo, Fe–Ta and Fe–W values to CALPHAD assessments. The calculator keeps every
value as published and marks M6 and M7 results of compositions containing a flagged pair as *Flagged data*. It
currently flags these five pairs and every pair with |ΔH<sub>f</sub>| > 700 meV atom⁻¹ (45 pairs in total).

## 6. Scientific limitations

* All eight criteria are empirical or semi-empirical screening rules calibrated on limited sets of mostly as-cast
  or annealed alloys; they predict tendencies, not phase diagrams.
* Different criteria use different radius sets, binary datasets and temperatures; their numbers are not
  interchangeable (δ for M2 is not δ<sub>CN12</sub> for M1; φ of M5 is unrelated to Φ of M8).
* MP means "not a single solid solution"; it does not identify the phases.
* Binary data refer to binary systems only; ternary and higher compounds are not considered.
* Element coverage of a model does not imply the model was validated for alloys of those elements.
* Rule-of-mixtures T<sub>m</sub> and density ignore excess quantities.

## 7. Data provenance and references

* Takeuchi A., Inoue A., Mater. Trans. 46 (2005) 2817 — liquid mixing enthalpies.
* Troparevsky M.C. et al., Phys. Rev. X 5 (2015) 011041, Supplemental Material Appendix A — formation enthalpies.
* Kittel C., Introduction to Solid State Physics, 8th ed., Ch. 3, Table 9 — 12-coordination radii (Yang & Zhang cite the 7th edition).
* Guo S., Liu C.T., Prog. Nat. Sci.: Mater. Int. 21 (2011) 433, Table 1 — atomic radii.
* Bakker H., Enthalpies in Alloys: Miedema's Semi-Empirical Model (1998), Tables A1, A2, A5 — Miedema parameters.
* Guo S. et al., J. Appl. Phys. 109 (2011) 103505 — VEC rule for FCC/BCC.
* Model publications M1–M8 as cited in §3.
