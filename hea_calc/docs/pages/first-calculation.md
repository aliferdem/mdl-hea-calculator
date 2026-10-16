# Your First Calculation

In this tutorial you calculate the equiatomic Cantor alloy, CoCrFeMnNi, as a single composition, read its row in
the results table and open its details in Analysis. It takes about five minutes and uses only default settings.

> **Before you start.** You need nothing prepared. If the results table already contains rows, the new row is added
> to them.

## Step 1 — Start in Single composition

In **Composition setup**, make sure the panel title reads **Single composition**. If it does not, select the first
icon of the mode switcher at the top right of the panel. Single composition is selected when the calculator starts.

The panel shows **Start by selecting elements**, and **Calculate** is unavailable until you select elements.

## Step 2 — Select five elements

In **Element selection**, click **Co**, **Cr**, **Fe**, **Mn** and **Ni**, in this order. Each selected tile is
marked, and Composition setup adds one row per element in the order you clicked. Every **At. ratio** value reads
**1.0000**, so the composition is already equiatomic.

> **Common mistake.** Clicking a selected tile again deselects it and removes its row. The rows — and the alloy
> name — follow the order of selection: clicking Ni first would name the alloy NiCoCrFeMn.

## Step 3 — Check model support (optional)

Hover over **Fe**. Its properties appear below the periodic table, and the **Model support** row shows whether each
model has the data it needs for this element. For Fe, M1–M5 and M8 show **Data available**; M6 and M7 show
**Depends on partner elements**, because their binary data exist only for pairs within a set of 30 elements. Select
the information icon next to **Model support** for the legend.

Model support describes one element. Whether a model can be evaluated for the alloy depends on all its elements and
pairs; if a model cannot be evaluated, the footer of Composition setup warns **Partial model coverage** before you
calculate.

## Step 4 — Choose the input column

Under **Input column**, keep **At. ratio** selected. You type values in the active column only; the other columns
are converted immediately.

| Element | At. ratio | at.% | wt.% | Mass |
|---|---|---|---|---|
| Co | 1.0000 | 20.0000 | 21.0166 | 0.42033 |
| Cr | 1.0000 | 20.0000 | 18.5427 | 0.37085 |
| Fe | 1.0000 | 20.0000 | 19.9153 | 0.39831 |
| Mn | 1.0000 | 20.0000 | 19.5919 | 0.39184 |
| Ni | 1.0000 | 20.0000 | 20.9335 | 0.41867 |

**Mass** is in grams for the **Total mass** in the **Total:** row — 2 g unless you have changed it. The total mass
you enter is remembered for later sessions.

## Step 5 — Set equal amounts

If you have changed any value, open the menu next to **Calculate** (the chevron) and select **Set equal**. Every
element receives the same value in the active column: 1 in At. ratio, 100 divided by the number of elements in at.%
and wt.%, and the total mass divided by the number of elements in Mass.

> **Common mistake.** **Set equal** in **wt.%** makes the masses equal, not the numbers of atoms. Equal wt.% of
> these five elements is not equiatomic: it corresponds to 18.99 at.% Co and 21.53 at.% Cr, for example. Use At.
> ratio or at.% for an equiatomic alloy.

## Step 6 — Try Normalize (optional)

Select **at.%** under Input column and change the Ni value to 25. The footer reports **Composition sum ≠ 100%** and
Calculate is unavailable, because at.% and wt.% values must add up to 100. Open the Calculate menu and select
**Normalize**: the column is rescaled to 100 %, giving 19.0476 for Co, Cr, Fe and Mn and 23.8095 for Ni. Select
**Set equal** to return to 20.0000 each, then select **At. ratio** again.

## Step 7 — Calculate

Select **Calculate**. A row for **CoCrFeMnNi** is added to the results table, the table shows the page that holds
it, and the composition opens in **Analysis**. A single composition is calculated at once, without a progress bar.

> **Common mistake.** Calculate stays unavailable while the footer shows an error, for example a missing value or
> fewer than two elements with a non-zero amount. The footer names the problem.

## Step 8 — Read the result row

Find the new row in the results table. Hover a column heading to see the quantity's unit and definition.

| Alloy | ρ | T<sub>m</sub> | ΔH<sub>mix</sub> | ΔS<sub>mix</sub> | δ | VEC | Cryst. Str. | M1–M8 |
|---|---|---|---|---|---|---|---|---|
| CoCrFeMnNi | 8.02 | 1801.20 | −4.16 | 13.38 | 3.27 | 8.00 | FCC | SS (all eight) |

Units: ρ in g cm⁻³, T<sub>m</sub> in K, ΔH<sub>mix</sub> in kJ mol⁻¹, ΔS<sub>mix</sub> in J mol⁻¹ K⁻¹, δ in %.
**SS** in every model column means that each of the eight models predicts a single solid solution. Such agreement is
not typical; for many compositions the models differ — see [Prediction Result Labels](help://result-labels).

The table rounds values for display. Full-precision values are in **Analysis › Descriptors** (**Full precision**)
and in exported files.

## Step 9 — Inspect the composition in Analysis

Look at the **Analysis** panel. **Composition** is selected and shows CoCrFeMnNi. **Overview** lists the normalised
composition, key descriptors, the model predictions (8 of 8 evaluated, all SS) and the data quality. The
**Descriptors**, **Models** and **Model details** tabs show every value, criterion and threshold.

The temperature used by M6 and M7 is 991 K here: by default 0.55 × T<sub>m</sub>. You can set an annealing
temperature in **File › Calculation settings…**.

To show another result in Analysis later, double-click its row, or right-click the row and select **Analyse
composition**. A single click does not change Analysis.

## What you have done

You calculated one composition, read its descriptors and model predictions, and opened its details. Next, try a
[Composition Space](help://composition-space) or a [Composition Expression](help://composition-expressions) to
calculate many compositions at once.
