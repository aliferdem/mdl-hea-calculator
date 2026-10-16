# Prediction Model Coverage

Each of the eight models uses its own descriptors and its own reference data, so a model can be available for one
composition and unavailable for another. A model is evaluated only when every elemental property and every binary
value it needs is tabulated; otherwise its prediction is *Not available* (N/A) and the reason names the missing data.
Missing data are never replaced by zero.

All eight models are available for compositions made only of these 30 elements: **Mg, Al, Sc, Ti, V, Cr, Mn, Fe, Co,
Ni, Cu, Zn, Y, Zr, Nb, Mo, Ru, Rh, Pd, Ag, Cd, La, Hf, Ta, W, Re, Os, Ir, Pt, Au.**

## Model requirements

| Model | Descriptors | Elemental data | Binary data | Temperature |
|---|---|---|---|---|
| M1 Yang & Zhang (2012) | Ω, δ<sub>CN12</sub> | melting point; Kittel CN12 radius | Takeuchi & Inoue (2005) | — (T<sub>m</sub> in Ω) |
| M2 Guo et al. (2013) | δ, ΔH<sub>mix</sub> | Guo & Liu (2011) radius | Takeuchi & Inoue (2005) | — |
| M3 Wang et al. (2015) | γ | Guo & Liu (2011) radius | — | — |
| M4 Singh et al. (2014) | Λ | Guo & Liu (2011) radius | — | — |
| M5 Ye et al. (2015) | φ | Guo & Liu radius; melting point | Takeuchi & Inoue (2005) | — (T<sub>m</sub> in S<sub>H</sub>) |
| M6 Troparevsky et al. (2015) | ΔH<sub>f</sub> of every pair, −TΔS<sub>mix</sub> | melting point (for f × T<sub>m</sub>) | Troparevsky et al. (2015) | annealing temperature or f × T<sub>m</sub> |
| M7 Senkov & Miracle (2016) | ΔH<sub>mix</sub>, ΔH<sub>IM</sub>, TΔS<sub>mix</sub> | melting point | Takeuchi & Inoue (2005); Troparevsky et al. (2015) | as M6 |
| M8 King et al. (2016) | Φ = ΔG<sub>ss</sub>/(−\|ΔG<sub>max</sub>\|) | Miedema parameters (Bakker 1998), melting point | computed with Miedema's model | T<sub>m</sub> |

The temperature for M6 and M7 is set in [Calculation Settings](help://calculation-settings).

## Element coverage

| Model | Supported elements | Count |
|---|---|---|
| M1 | Li Be B C Na Mg Al Si K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Th U Pu | 69 |
| M2, M5 | the 73 elements of the Takeuchi & Inoue table: H Li Be B C N Na Mg Al Si P K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Th U Pu — of which H, As, Sb, Hg, Bi and Pu use a supplementary radius | 73 |
| M3, M4 | 73 elements with a Guo & Liu radius (Li Be B C N O Na Mg Al Si P S K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge Se Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Te Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Tl Pb Po Th Pa U) plus 35 with a supplementary radius (H He F Ne Cl Ar As Br Kr Sb I Xe Hg Bi Fr Ra Ac Np Pu Am and the superheavy elements Rf–Og) | 108 |
| M6, M7 | Mg Al Sc Ti V Cr Mn Fe Co Ni Cu Zn Y Zr Nb Mo Ru Rh Pd Ag Cd La Hf Ta W Re Os Ir Pt Au | 30 |
| M8 | Li Be B C Na Mg Al Si P K Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Rb Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Cs La Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Th U Pu; Ca, Sr and Ba only without transition metals | 54 + 3 |

A supplementary radius is not from Guo & Liu (2011) and its origin is not documented; results that use one carry a
caution. Predictions for noble gases, halogens and superheavy elements are formal evaluations without physical
meaning for alloys.

## When a model is not available

| Model | Not available when |
|---|---|
| M1 | a pair lacks a Takeuchi & Inoue value, an element lacks a Kittel radius, or ΔH<sub>mix</sub> is exactly zero (Ω undefined — for example equiatomic CoNi) |
| M2 | a pair lacks a Takeuchi & Inoue value or an element lacks a radius |
| M3 | an element lacks a radius |
| M4 | an element lacks a radius, or δ = 0 (Λ undefined) |
| M5 | a pair lacks a Takeuchi & Inoue value, an element lacks a radius, or S<sub>E</sub> cannot be evaluated |
| M6 | any element is outside the 30-element Troparevsky set |
| M7 | any element is outside the Troparevsky set, or ΔH<sub>mix</sub> is missing |
| M8 | an element has no Miedema parameters, or Ca, Sr or Ba is combined with a transition metal (no Miedema hybridisation factor tabulated) |

See also [Model Support and Availability](help://model-availability) for how the calculator reports coverage before
and after calculating.
