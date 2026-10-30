# Element Property Definitions

The lower part of the **Elements** panel shows the properties of the element under the pointer (or the last one you
selected). This page defines every value shown there: its symbol, name, meaning, unit, the calculator's convention
and the source of the number. The values are the calculator's elemental dataset (`data/periodic_table.json`),
formatted for display only — nothing is recalculated or rounded before it is used.

> **Note.** A dash (—) means the dataset has no value for this element. It is never treated as zero: the descriptors
> and models that need the value become N/A for alloys containing the element. See
> [Model Support and Availability](help://model-availability).

## Identity row

| Shown | Name | Meaning | Source |
|---|---|---|---|
| Symbol and **name** | Element | The chemical symbol and the element's name. | dataset |
| Z | Atomic number | The number of protons. | dataset |
| Category | Element category | The class used to colour the periodic table tiles: transition metal, lanthanide, actinide, post-transition metal, metalloid, nonmetal, halogen, noble gas, alkali metal or alkaline earth metal. | dataset |

## Thermophysical properties

| Symbol | Name | Unit | Meaning and convention | Source | Used for |
|---|---|---|---|---|---|
| ρ | Density | g cm⁻³ | The elemental density as stored in the dataset. For elements that are gases at room temperature the stored numbers are their gas densities in g L⁻¹ at 0 °C and 1 atm (N 1.251, O 1.429), shown with the panel's g cm⁻³ label. | The dataset does not record a source. | Display only. No descriptor or model uses it: the alloy density ρ in the results is calculated from atomic weights and molar volumes. |
| T<sub>m</sub> | Melting point | K | The melting temperature of the element. | standard tabulation | T<sub>m</sub> (rule of mixtures); Ω (M1), φ (M5), the default M6/M7 temperature, M8 |
| V<sub>m</sub> | Molar volume | cm³ mol⁻¹ | Miedema's molar volume V of the pure element. | Bakker (1998), Table A1 [11] | Miedema model (M8); the alloy density ρ |

## Atomic properties

| Symbol | Name | Unit | Meaning and convention | Source | Used for |
|---|---|---|---|---|---|
| m<sub>a</sub> | Atomic mass | u (= g mol⁻¹) | The standard atomic weight. | standard tabulation | conversions between at.%, wt.% and mass; the alloy density ρ |
| r | Atomic radius | pm | The radius set of Guo & Liu, shown to 0.1 pm as printed in their table (for example Fe 124.1 pm). A value marked **\*** is supplementary: the element is absent from Guo & Liu's table and the value comes from another source of undocumented origin. | Guo & Liu (2011), Table 1 [9] | δ, γ, Λ, S<sub>E</sub>, φ — models M2–M5 |
| r<sub>CN12</sub> | Metallic radius, coordination number 12 | pm | The radius of the element in a 12-coordinated metal, shown to 1 pm as Kittel lists it. For the few elements with a range or a valence-dependent value the calculator uses Ce 182 pm, Eu (2+) 204 pm, Yb (2+) 194 pm and Pu 161 pm. | Kittel, *Introduction to Solid State Physics*, 8th ed., Ch. 3, Table 9 [12] | δ<sub>CN12</sub> — model M1 (M8 uses no radius) |

> **Important.** r and r<sub>CN12</sub> are two different radius sets, not two precisions of one value. They give
> different size mismatches for the same alloy — for CoCrFeMnNi δ = 3.27 % and δ<sub>CN12</sub> = 0.92 % — and each
> is used only with the models whose authors used it. See [Elemental Property Data](help://elemental-data#two-radius-sets).

## Electronic properties

| Symbol | Name | Unit | Meaning and convention | Source | Used for |
|---|---|---|---|---|---|
| VEC | Valence electron count | — | The number of valence electrons counted as s + d electrons. | standard tabulation | VEC and the crystal-structure rule; the Miedema valence |
| φ* | Miedema electronegativity parameter | V | The electronegativity parameter φ* of Miedema's model (a work-function-like quantity, not the measured work function). | Bakker (1998), Table A1 [11] | Miedema model (M8) |
| n<sub>ws</sub> | Electron density at the Wigner–Seitz cell boundary | density units (d.u.) | Miedema's electron density parameter. | Bakker (1998), Table A1 [11] | Miedema model (M8) |

## Elastic properties

| Symbol | Name | Unit | Meaning and convention | Source | Used for |
|---|---|---|---|---|---|
| K | Bulk modulus | GPa | Stored in 10¹⁰ Pa as in the source table and shown in GPa (1 × 10¹⁰ Pa = 10 GPa). | Bakker (1998), Table A5 [11] | elastic term of the Miedema model (M8) |
| G | Shear modulus | GPa | Stored in 10¹⁰ Pa as in the source table and shown in GPa. | Bakker (1998), Table A5 [11] | elastic term of the Miedema model (M8) |

## Coverage

Of the 118 elements, the dataset has T<sub>m</sub>, V<sub>m</sub>, m<sub>a</sub> and VEC for all 118; ρ for 103;
r for 108 (35 of them supplementary values; At, Rn and Cm–Lr have none); r<sub>CN12</sub> for 73; φ*,
n<sub>ws</sub>, K and G for 71.

## Related

The tooltip of each symbol in the panel gives the same name, unit and source. The reference numbers point to
[Scientific References](help://references).
