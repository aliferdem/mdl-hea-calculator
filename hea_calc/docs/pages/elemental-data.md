# Elemental Property Data

Every elemental property comes from a named source, and each model uses the radius set its authors used. Values are
never filled in by assumption: an element without a required property makes only the dependent quantities N/A.

## Properties and sources

| Property | Unit | Source | Used for |
|---|---|---|---|
| Atomic radius | pm | Guo & Liu (2011), Table 1 [9] | δ, γ, Λ, S<sub>E</sub>, φ — models M2–M5 |
| 12-coordination radius (CN12) | pm | Kittel, *Introduction to Solid State Physics*, 8th ed., Ch. 3, Table 9 [12] | δ<sub>CN12</sub> — model M1; the size term of M8 |
| Melting point | K | standard tabulation | T<sub>m</sub>; Ω (M1), φ (M5), the default M6/M7 temperature, M8 |
| Atomic weight | g mol⁻¹ | standard tabulation | conversions between at.%, wt.% and mass; ρ |
| Valence electrons (s + d) | — | standard tabulation | VEC and the crystal-structure rule; Miedema valence |
| Molar volume V | cm³ mol⁻¹ | Bakker (1998), Table A1 [11] | Miedema model (M8); ρ |
| Work function φ* | V | Bakker (1998), Table A1 | Miedema model (M8) |
| Electron density n<sub>ws</sub> | density units | Bakker (1998), Table A1 | Miedema model (M8) |
| Bulk and shear modulus | 10¹⁰ Pa | Bakker (1998), Table A5 | elastic term of the Miedema model (M8) |

The density is the rule-of-mixtures value ρ = Σc<sub>i</sub>M<sub>i</sub> / Σc<sub>i</sub>V<sub>i</sub>, with the
Miedema molar volumes.

## Two radius sets

Guo & Liu radii and Kittel CN12 radii give different size mismatches for the same alloy — for CoCrFeMnNi, δ = 3.27 %
and δ<sub>CN12</sub> = 0.92 %. Each is used only with the models whose authors used it, and both are reported. For
M3 the publication does not name its radius set; the calculator uses the Guo & Liu radii of the same research group.

Kittel lists ranges or valence-dependent radii for a few elements; the calculator uses Ce 182 pm, Eu (2+) 204 pm,
Yb (2+) 194 pm and Pu 161 pm.

## Supplementary radii

45 elements are absent from Guo & Liu's Table 1, among them H, the noble gases, the halogens, As, Sb, Hg, Bi, Pu and
the superheavy elements. They carry supplementary radii from other sources of undocumented origin. Models M2–M5 can
be evaluated with them, but the Model support row shows **Supplementary data used** and the result carries a
caution.
