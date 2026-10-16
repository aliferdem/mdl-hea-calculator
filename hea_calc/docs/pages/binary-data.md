# Binary Interaction Data

Three kinds of binary data are used: liquid mixing enthalpies for ΔH<sub>mix</sub>, DFT formation enthalpies of
binary compounds for M6 and M7, and Miedema enthalpies for M8.

## Datasets

| Dataset | Elements | Pairs | Used by | Completeness |
|---|---|---|---|---|
| Takeuchi & Inoue (2005) liquid mixing enthalpies [10], kJ mol⁻¹ | 73 | 2,628 | ΔH<sub>mix</sub>; M1, M2, M5, M7 | Every pair of the 73 elements is tabulated; 159 pairs are tabulated as exactly 0 kJ mol⁻¹, which is a value, not missing data. |
| Troparevsky et al. (2015) formation enthalpies [6], meV atom⁻¹ | 30 | 435 | M6; ΔH<sub>IM</sub> of M7 | Complete for the 30 elements. |
| Miedema interfacial and elastic enthalpies, from Bakker (1998) parameters [11] | 57 | computed for any pair | M8 | Reproduces Bakker's Table A2 within ±2.1 kJ mol⁻¹. |

ΔH<sub>mix</sub> is the regular-solution sum Σ<sub>i&lt;j</sub> 4c<sub>i</sub>c<sub>j</sub>ΔH<sub>ij</sub><sup>mix</sup> over all
pairs.

## The Troparevsky matrix

The 30 elements are Mg, Al, Sc, Ti, V, Cr, Mn, Fe, Co, Ni, Cu, Zn, Y, Zr, Nb, Mo, Ru, Rh, Pd, Ag, Cd, La, Hf, Ta, W, Re,
Os, Ir, Pt and Au. The values are the formation enthalpies of the lowest-energy binary compounds from the
publication's supplement.

* Seven pairs are printed with two different values (Al–Ag, Ti–La, V–Cu, Cr–Cd, Mn–Mo, Co–Nb, Nb–Ir). The calculator
  uses the value in the row of the element that comes first in the published order.
* Four Laves-phase values in the matrix come from Chen et al. (2005), as cited in the publication; four Re pairs are
  referenced to the solid solution.

## Flagged binary data

Some published Troparevsky values are physically implausible: Fe–Ta −3468, Fe–Nb −2505, Al–Cd −1938, Fe–W −554 and
Fe–Mo −484 meV atom⁻¹. The publication attributes the Fe–Nb, Fe–Mo, Fe–Ta and Fe–W values to CALPHAD assessments.
The calculator keeps every value as published and marks M6 and M7 results of compositions containing a flagged pair
as **Flagged binary data**. It flags these five pairs and every pair with |ΔH<sub>f</sub>| > 700 meV atom⁻¹.

## Missing pairs

A pair outside a dataset makes only the dependent quantities N/A, with the pair named in the reason — for example
"No Troparevsky formation enthalpy for Co–Si, Cr–Si, Fe–Si, Ni–Si." for M6 and M7 of CoCrFeNiSi0.5. A missing value is
never replaced by zero.
