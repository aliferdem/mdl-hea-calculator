# Composition Space

Explore a region of composition space systematically. Select the elements, give each a range — **Min**, **Max** and
**Step** — and the calculator generates every valid composition on these grids and calculates them as one run.

![Composition space: Al optional from 0.1 to 0.5 in an Al–Co–Cr–Fe–Ni space defined in atomic ratios.](images/composition-space.png)

## Controls

| Control | Effect |
|---|---|
| **Range basis** (panel heading) | The representation of Min, Max and Step: **At. ratio**, **at.%**, **wt.%** or **Mass**. Changing it resets the ranges to the defaults of the new basis. |
| Element symbol | Type a new symbol to replace the element and keep its range. A duplicate or unknown symbol is reported in the footer. |
| **Min**, **Max**, **Step** | The values of an element are Min, Min + Step, Min + 2 × Step, … up to Max, handled as exact decimals. With Min = Max the element has one value. |
| **Lock** | On: the element is required in every composition. Off: optional — systems with and without it are generated. |
| **All:** row | A value typed in its Min, Max or Step sets every element; its Lock switches every element. "Mixed" means the rows differ. |
| **System size** | Keeps only systems with the chosen numbers of elements; **All** keeps every size. See [System Size and Element Constraints](help://system-size). |
| **Workload summary** | The exact number of valid compositions with the estimated runtime and temporary storage. |

### Range bases and defaults

| Range basis | Defaults (Min, Max, Step) | What counts as a valid composition |
|---|---|---|
| **At. ratio** | 1.0, 1.0, 0.1 | Every combination; a combination proportional to one already generated (2 : 2 : 2 after 1 : 1 : 1) is the same alloy and counted once. |
| **at.%** | 0, 100, 10 | Only combinations whose values add up to exactly 100 at.%. |
| **wt.%** | 0, 100, 10 | Only combinations whose values add up to exactly 100 wt.%; each is converted to atomic fractions. |
| **Mass** | 1.0, 1.0, 0.1 (g) | Like At. ratio: masses are proportional, so proportional combinations are counted once. |

Whatever the basis, every generated composition is converted to atomic fractions before calculation. The values
you entered are kept with each result, so plots of a composition space can use the grid coordinates of the chosen
basis.

## What belongs to the composition space

1. **Element systems.** Every system contains all required elements plus one subset of the optional elements
   (including none). Systems with fewer than two elements, or of a size excluded by System size, are dropped.
2. **Values.** Each element present in a system takes each positive value of its range. Zero is not used.
3. **Duplicates and sums.** At. ratio and Mass drop proportional duplicates; at.% and wt.% keep only combinations
   that sum to 100.

## Workload summary and status

The count is exact and updates as you type; while it is being counted, the footer shows **Updating…**. The footer
then shows **Ready**, or the reason the space cannot be calculated:

| Footer | Meaning |
|---|---|
| **Missing range values** | A Min, Max or Step is empty or not a number. |
| **No valid compositions - values must sum to 100 %** | at.% or wt.%: no combination of the grid values adds up to 100. |
| **Large workload** | 250,000 compositions or more; the information icon gives the estimates. You can still calculate. |
| **Workload too large** | More than 10,000,000 valid compositions; narrow the ranges or increase the steps. |

The runtime and storage figures are estimates; see [Workload Estimation](help://workload).

## Examples

| Space | Range basis | Valid compositions |
|---|---|---|
| Co, Cr, Fe, Ni required at 1.0; Al optional 0.1–0.5, step 0.1 | At. ratio | 6 (CoCrFeNi and Al0.1CoCrFeNi to Al0.5CoCrFeNi), 2 systems |
| The same with masses: Co, Cr, Fe, Ni 1.0 g; Al optional 0.1–0.5 g | Mass | 6, 2 systems |
| Fe, Cr, Ni required, 20–60, step 10 | at.% | 15 |
| Fe, Cr, Ni required, 20–60, step 10 | wt.% | 15 |
| Fe, Cr, Ni with the defaults 0–100, step 10 | at.% or wt.% | 36 |
| Co, Cr, Fe, Mn, Ni all optional at 1.0 | At. ratio | 26 (26 systems); System size 4 → 5 |

More worked spaces: [Composition Space: Al–Co–Cr–Fe–Ni](help://example-space).

## Calculating

Select **Calculate**. The compositions are generated and calculated in background processes; the header shows the
progress and the remaining time, and the footer's **Clear** becomes **Cancel**. Cancelling keeps the results
calculated so far. When the run finishes, a message above the results table reports the number of compositions
calculated, and the first result becomes the active composition in Analysis.
