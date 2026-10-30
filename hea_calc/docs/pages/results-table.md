# Results Table

Every calculated composition is one row of the results table. The table shows one page of results at a time;
sorting, filtering and export always apply to all results, not only to the visible page.

![The results table with the default columns and model prediction tags.](images/results-table.png)

## Columns

**Alloy** names the composition: for example CoCrFeMnNi for a single composition entered in atomic ratios,
Cr12Mn20Co3Ni15Cu20Zn20Si10 (at.%) or Fe70Cr18Ni12 (wt.%) for one entered in percent (the basis is part of the name),
Al10Co30Fe30Ni30 (at.%) for a percent composition space, (FeCoNi)0.9Al0.1 for an expression with its variable values
substituted, or the name from an imported file. Results calculated before names carried a basis keep their names.

**Run** is the calculation run of the result, and **Variables** its design values: the expression's variables
(x = 0.5) or the composition-space grid values. Variables is empty for single compositions and imports, cannot be
sorted, and is not part of the Excel / CSV dataset export (Run is). Add either with **Table columns**, where the
descriptors that belong to one model are listed under that model and the shared ones under General.

**Filter results** builds filters one at a time: **Add filter**, choose a parameter, then its condition: between,
at least or at most for a number, or "is one of" the classes a model can produce. A result is shown only when it
matches every filter. Remove a single filter with its **×**, or all of them with **Clear all**. Hover a column heading to see the unit and
definition.

| Heading | Quantity | Unit |
|---|---|---|
| **Alloy** | Composition name | — |
| **ρ** | Rule-of-mixtures density | g cm⁻³ |
| **T<sub>m</sub>** | Rule-of-mixtures melting temperature | K |
| **ΔH<sub>mix</sub>** | Regular-solution mixing enthalpy (Takeuchi & Inoue 2005 binaries) | kJ mol⁻¹ |
| **ΔS<sub>mix</sub>** | Ideal configurational mixing entropy | J mol⁻¹ K⁻¹ |
| **δ** | Atomic-size mismatch, Guo & Liu radii | % |
| **VEC** | Valence electron concentration | — |
| **Cryst. Str.** | VEC rule: FCC if VEC ≥ 8.0, BCC if VEC < 6.87, otherwise BCC + FCC | — |
| **M1** … **M8** | Prediction of each model | tag |

**Table columns** (settings icon) adds optional columns: the composition in at.%, δ<sub>CN12</sub>, Ω, γ, Λ, φ,
S<sub>E</sub>, ΔH<sub>f,min</sub>, ΔH<sub>f,max</sub>, −TΔS<sub>mix</sub>, T, ΔH<sub>IM</sub>, k<sub>1</sub>,
k<sub>1</sub><sup>cr</sup>, Φ, ΔG<sub>ss</sub>, ΔG<sub>max</sub> and M̄. **Reset to default** restores the default
set; **Alloy** is always shown. The choice is remembered. Definitions: [Symbols, Parameters and Units](help://symbols).

The prediction tags (SS, MP, IM, SS+IM, MG, N/A) are explained in [Prediction Result Labels](help://result-labels).

## Working with rows

| Action | How |
|---|---|
| Analyse a result | Double-click the row, or right-click › **Analyse composition**. With the top panels hidden or the Analysis panel collapsed, this opens the Analysis window (an open one is reused); the collapsed panel stays collapsed. From the keyboard: Tab into the table, choose the row with the arrow keys and press Enter (Shift+F10 opens the row menu). |
| Open in a separate window | Right-click › **Open details in new window** (the Analysis window). |
| Copy | Drag across the text of a cell and press Ctrl+C; or right-click › **Copy value** (full precision) or **Copy row**. |
| Remove one result | Right-click › **Remove result**. |
| Clear the table | **Clear table** (trash icon) removes every result at once. There is no undo. |

Rows highlight on hover. To work with a chosen group of results, select them in an Analysis plot and use **Show in
results table**; the table then shows exactly those results until you clear the filter.

## Pages

Choose **Items per page** (10, 20, 50 or 100) and move with the arrows, or type a page number in the page field and
press Enter. A number outside the range is corrected to the first or last page; **Esc** restores the current page.
The range of rows shown is displayed next to the controls, for example "1–12 of 12 items".

## Sorting

Click a column heading to sort ascending, again for descending, and a third time to return to the original order.
Sorting applies to all results; a large table sorts in the background.

## Filtering

**Filter results** (filter icon) limits the table by descriptor ranges — **Min** and **Max**, empty for no limit —
and by model predictions (**Any**, a single tag, or **SS (any SS)** for SS and SS+IM). **Clear filters** removes all
conditions. While a filter is active the toolbar says so and shows how many results pass; if none passes, the table
shows **No matching results**.
