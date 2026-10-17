# Parametric Expression: AlxCoCrFeNi

The AlxCoCrFeNi family is a classic case of an FCC-to-BCC transition with increasing aluminium. A composition
expression calculates it in one run.

## Calculate the family

Select **Composition expression** with the mode switcher. Type the expression and, on the next line, the range of x:

```
AlxCoCrFeNi
0 <= x <= 1, step=0.1
```

Select **Parse** (or press Ctrl+Enter). The field turns green and reads "Parsed successfully: Parametric
composition, 5 elements, 1 variable, 11 compositions." — from CoCrFeNi (x = 0) to AlCoCrFeNi (x = 1). Then select
**Calculate**.

`0 <= x <= 1, points=11` gives the same eleven values: points always include both endpoints.

## Read the trend

In **Analysis › Collection › Plots**, choose **Line (ordered by parameter)** with x on the horizontal axis and VEC on
the vertical axis. VEC falls from 8.25 at x = 0 to 7.20 at x = 1, crossing the 8.0 FCC limit of the VEC rule; the
**Cryst. Str.** column changes from FCC to BCC + FCC. Plot ΔH<sub>mix</sub> or δ the same way, or use **Stacked bars
(model classes)** to see where each model switches from SS.

## Extend the range

Change the range line to `0 <= x <= 2, step=0.05`. The field now reads "Expression changed. Parse again to update the
result." and Calculate waits; parse again: **41 compositions**.

## Two blocks

Write a second block after a blank line:

```
AlxCoCrFeNi
0 <= x <= 2, step=0.1

(CoCrFeNi)1-yAly
0 <= y <= 0.3, step=0.05
```

The 28 combinations give **26 compositions (2 duplicates)**: y = 0 and y = 0.2 produce the same alloys as x = 0 and
x = 1 of the first block, so they are calculated once and belong to the first block.

## Skipped combinations

Parse `(FeCoNi)1-xAlx` with the range `0 <= x <= 1, step=0.25`. At x = 1 only Al remains, so that combination is
skipped: **4 compositions**, and the footer notes **1 combination skipped**.
