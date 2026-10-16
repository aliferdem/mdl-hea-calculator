# Composition Expressions

Calculate compositions written as formulas — fixed alloys such as Al0.5CoCrFeNi, or families with a variable amount
such as AlxCoCrFeNi. Lower-case names are variables; for each variable you set **Min**, **Max** and **Step**, and the
calculator calculates one composition per combination of variable values.

![Composition expression AlxCoCrFeNi with the variable x from 0 to 1 in steps of 0.1.](images/composition-expression.png)

## Writing expressions

Type one or more formulas in the expression field. Each formula is a block; separate blocks with a blank line.

| Write | Meaning | Example |
|---|---|---|
| Element symbol | Case-sensitive. A two-letter symbol takes precedence: **Ba** is barium. | `Fe`, `Co` |
| Number after a symbol | Amount as an atomic ratio; no number means 1. | `Al0.5CoCrFeNi` |
| ( … ) or [ … ] | Group: its contents are normalised to 1, then multiplied by the group's amount. | `(FeCoNi)90Al10` = 30 / 30 / 30 / 10 at.% |
| Lower-case name | Variable. | `x`, `y1`, `al_frac` |
| { … } or _( … ) | Any arithmetic with + − * / ^. | `Ti{0.1*k}`, `Mo_(1-y)` |

The full rules are in the [Expression Syntax Reference](help://expression-syntax). The information icon next to the
field label gives a short summary.

## Variables

For each variable a row with **Min**, **Max** and **Step** appears; the defaults are 0, 1 and 0.1. A variable used in
several blocks has one shared range. If you delete a variable and type it again, its last range is restored.

## Counting and status

The number of valid compositions updates as you type. A combination is **skipped** when an amount becomes negative,
a group sums to zero, or fewer than two elements remain; a composition that another combination already produced is
a **duplicate** and is calculated once, in the block that produced it first. The footer shows:

| Footer | Meaning |
|---|---|
| **Ready** | The expression can be calculated. |
| **Invalid expression** | A syntax error; the message below the field gives the position, for example "Unknown element 'Q' (at position 5)", and the block number when there are several blocks. |
| **Missing range values** | A Min, Max or Step is empty or not a number. |
| *n* **combinations skipped** | Some combinations produce no composition (information only). |
| **No valid compositions** | Every combination was skipped. |
| **Large workload** | 250,000 compositions or more. |

The number of combinations may not exceed 5,000,000; increase the steps or narrow the ranges.

## Other actions

| Action | Effect |
|---|---|
| Periodic table | Clicking a tile adds the symbol to the end of the expression; deselecting removes it with its amount. |
| **Preview generated compositions** (icon in the expression field) | Opens **Generated compositions** with the full list and **Copy table**. |
| Calculate menu › **Copy table** | Copies the generated compositions as tab-separated text, without calculating them. |
| **Clear** | Clears the expression. |

## Examples

| Expression | Ranges | Result |
|---|---|---|
| `(FeCoNi)90Al10` | — | 1 composition: Fe 30, Co 30, Ni 30, Al 10 at.% |
| `Al0.5CoCrFeNi` | — | 1 composition: Al 11.11 at.%, Co, Cr, Fe and Ni 22.22 at.% each |
| `AlxCoCrFeNi` | x 0–1, step 0.1 | 11 compositions, from CoCrFeNi to AlCoCrFeNi |
| `(FeCoNi)1-xAlx` | x 0–1, step 0.25 | 4 compositions, 1 skipped (at x = 1 only Al remains) |
| `AlxCoCrFeNi`, blank line, `(CoCrFeNi)1-yAly` | x 0–2 step 0.1; y 0–0.3 step 0.05 | 28 combinations: 26 compositions, 2 duplicates |

Worked example: [Parametric Expression: AlxCoCrFeNi](help://example-expression).
