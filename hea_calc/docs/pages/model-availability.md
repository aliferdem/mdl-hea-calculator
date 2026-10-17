# Model Support and Availability

Each model needs its own elemental properties and binary data. The calculator shows what is available before you
calculate and explains every prediction that could not be made.

## Before calculating: Model support

Hover an element in the periodic table. The **Model support** row below the table shows one icon per model:

| Status | Meaning |
|---|---|
| **Data available** | The model has every value it needs for this element. |
| **Supplementary data used** | The model can be evaluated, but with a supplementary value (for example a radius not from Guo & Liu's table); results carry a caution. |
| **Depends on partner elements** | The model needs binary data for pairs; whether they exist depends on the other elements of the alloy (M6 and M7 cover pairs within a set of 30 elements). |
| **Data unavailable** | The model cannot be evaluated for any alloy containing this element. |

The information icon next to **Model support** opens the legend.

![The Elements panel with the Model support row and the element properties.](images/element-selection.png)

## For the selected elements: Partial model coverage

When the selected elements leave one or more models without data, the footer of Composition setup shows the warning
**Partial model coverage** — for example, for Co, Cr, Fe, Ni and Si: "M6 and M7 are unavailable for these elements:
No Troparevsky formation enthalpy for Co–Si, Cr–Si, Fe–Si, Ni–Si." The other models can still be evaluated, and you
can calculate. **View model support** opens [Prediction Model Coverage](help://model-coverage).

## After calculating: N/A

A model without the data it needs shows **N/A** in its column. Open the composition in Analysis to read the reason:
the **Models** tab lists every model, and **Overview** reports how many were evaluated (for example "6 of 8
evaluated"). N/A has two causes:

* **missing data** — a required elemental property or binary value is not tabulated;
* **undefined** — a quantity of the criterion has no value for this composition, for example Ω when
  ΔH<sub>mix</sub> is exactly zero (equiatomic CoNi).

Missing data are never replaced by zero. Tabulated zeros — for example the Takeuchi & Inoue value 0 kJ mol⁻¹ for
Fe–Mn — are real values and are used.
