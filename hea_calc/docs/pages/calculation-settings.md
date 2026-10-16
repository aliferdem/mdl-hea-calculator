# Calculation Settings

**File › Calculation settings…** sets the temperature used by M6 (Troparevsky et al.) and M7 (Senkov & Miracle).
The other models do not use a temperature setting: M1, M5 and M8 work at the rule-of-mixtures T<sub>m</sub>, and
M2–M4 need no temperature.

## Settings

| Setting | Meaning |
|---|---|
| **Annealing temperature (K)** | The temperature of interest, for example an annealing or service temperature. Must be greater than 0 K. |
| **Fraction f of Tm (when empty)** | Used when no annealing temperature is entered: T = f × T<sub>m</sub> of each composition. Default 0.55 (Troparevsky et al. 2015); allowed range greater than 0 and at most 1.5. |

**Apply** stores the setting, **Reset** restores the defaults (no annealing temperature, f = 0.55), and **Cancel**
closes the dialog without changes. The temperature used for a result is shown in Analysis next to the composition,
for example "Calculated with T = 991 K for M6, M7".

## Recalculating existing results

New calculations use the new setting at once. If the table already contains results, the calculator asks
**Recalculate results** — "Recalculate the *n* existing result(s) with the new temperature setting?". Recalculating
replaces every stored result with one calculated at the new setting; the header shows **Recalculating** while it
runs. If you decline, existing results keep the temperature they were calculated with.

## Comparing runs

Runs calculated with different M6/M7 temperatures are not directly comparable for those two models. Analysis keeps
each collection within one run, so its model distributions always refer to one temperature setting.
