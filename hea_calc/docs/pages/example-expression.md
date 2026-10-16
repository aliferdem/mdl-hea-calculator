# Parametric Expression: AlxCoCrFeNi

The AlxCoCrFeNi family is a classic case of an FCC-to-BCC transition with increasing aluminium. A composition
expression calculates it in one run.

## Calculate the family

1. Select **Composition expression** with the mode switcher.
2. Type `AlxCoCrFeNi`. A row for the variable **x** appears with Min 0, Max 1 and Step 0.1.
3. The count reads **11 valid compositions**, from CoCrFeNi (x = 0) to AlCoCrFeNi (x = 1). The footer reads
   **Ready**.
4. Select **Calculate**.

To check the compositions first, select **Preview generated compositions** in the expression field.

## Read the trend

In **Analysis › Collection › Plots**, choose **Line (ordered by parameter)** with x on the horizontal axis and VEC on
the vertical axis. VEC falls from 8.25 at x = 0 to 7.20 at x = 1, crossing the 8.0 FCC limit of the VEC rule; the
**Cryst. Str.** column changes from FCC to BCC + FCC. Plot ΔH<sub>mix</sub> or δ the same way, or use **Stacked bars
(model classes)** to see where each model switches from SS.

## Extend the range

Set x from 0 to 2 in steps of 0.05: **41 valid compositions**.

## Two blocks

Type `AlxCoCrFeNi`, a blank line, and `(CoCrFeNi)1-yAly`. Set x from 0 to 2 in steps of 0.1 and y from 0 to 0.3 in
steps of 0.05. The 28 combinations give **26 valid compositions** and **2 duplicates**: y = 0 and y = 0.2 produce the
same alloys as x = 0 and x = 1 of the first block, so they are calculated once and belong to the first block.

## Skipped combinations

Type `(FeCoNi)1-xAlx` with x from 0 to 1 in steps of 0.25. At x = 1 only Al remains, so that combination is skipped:
**4 valid compositions**, and the footer notes **1 combination skipped**.
