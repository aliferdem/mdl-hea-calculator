# Composition Expressions

Calculate compositions written as formulas — fixed alloys such as Al0.5CoCrFeNi, or families with a variable amount
such as AlxCoCrFeNi. Everything is written in one text area: the formula, and below it one line per variable that
says which values the variable takes. Select **Parse** to check what you wrote; **Calculate** then calculates one
composition per combination of variable values.

![Composition expression AlxCoCrFeNi with the range line 0 <= x <= 1, step=0.1, parsed: 11 compositions.](images/composition-expression.png)

## Blocks

A document is made of **blocks** separated by a blank line. In each block:

* the **first line** is the expression, for example `AlxCoCrFeNi`;
* each **following line** declares the range of one variable used in that expression, for example
  `0 <= x <= 1, step=0.1`.

A block without variables is a fixed composition and has only its first line. One document may mix fixed and
parametric blocks.

```
FeCoNi(AlCu)0.2

(Fe1.6CoCr0.4Mn)0.9Al0.1

(Co30Fe45Ni25)1-x(Al40Si60)x
0 <= x <= 1, step=0.05
```

## Writing the expression

| Write | Meaning | Example |
|---|---|---|
| Element symbol | Case-sensitive. A two-letter symbol takes precedence: **Ba** is barium. | `Fe`, `Co` |
| Number after a symbol | Amount as an atomic ratio; no number means 1. | `Al0.5CoCrFeNi` |
| ( … ) or [ … ] | Group: its contents are normalised to 1, then multiplied by the group's amount. | `(FeCoNi)90Al10` = 30 / 30 / 30 / 10 at.% |
| Lower-case name | Variable. | `x`, `y1`, `al_frac` |
| { … } or _( … ) | Any arithmetic with + − * / ^. | `Ti{0.1*k}`, `Mo_(1-y)` |

The full rules are in the [Expression Syntax Reference](help://expression-syntax). The information icon next to the
field label gives a short summary.

## Ranges: step or points

Each range line names one variable between its two bounds, then **either** a step **or** a number of points — never
both:

| Range line | Values |
|---|---|
| `0 <= x <= 1, step=0.1` | 0, 0.1, 0.2 … 1 — from the lower bound in equal steps up to the upper bound (11 values) |
| `0 <= x <= 1, points=11` | 11 equally spaced values; **points include both endpoints** (0 and 1) |
| `0.2 <= x <= 0.2, step=0.1` | one value, 0.2 |

A range line may end with `, p=0.5`: the value the preview of that block uses. Every variable in the expression
needs its own range line in the same block; a range belongs to its block only.

## Parse, then calculate

Parsing is explicit — the field does not check as you type. Select **Parse** (the icon in the field, or
**Ctrl+Enter**):

| State | What you see |
|---|---|
| Not parsed yet | The helper text "Enter one expression per block. Separate blocks with a blank line."; **Calculate** is unavailable. |
| Parsed | A green check, the summary — for example "Parsed successfully: Parametric composition, 5 elements, 1 variable, 11 compositions." — and the parsed blocks below the field. **Calculate** is available. |
| Changed after parsing (stale) | A yellow warning and "Expression changed. Parse again to update the result."; **Calculate** stays unavailable until you parse again, so the calculation always uses what was parsed. |
| Error | A red field and one message per block with its number and first line, for example "Unknown element "Xx"", "Unmatched parenthesis" or "Choose one sampling method. Specify either step or points, not both." |

For one fixed block the parsed result is its composition table (atomic ratio, at.%, wt.% and mass); for parametric
blocks it lists each variable with its range, step or points, preview value and number of values. Large documents
are counted in the background; the footer shows **Large workload** from 250,000 compositions.

## Counting

A combination is **skipped** when an amount becomes negative, a group sums to zero, or fewer than two elements
remain; the footer then notes *n* **combinations skipped**. A composition that another combination already produced
is a **duplicate** and is calculated once, in the block that produced it first. The number of combinations may not
exceed 5,000,000.

## Other actions

| Action | Effect |
|---|---|
| Periodic table | Clicking a tile adds the symbol to the end of the expression line; deselecting removes it with its amount. Range lines are never changed. |
| Calculate menu › **Copy table** | One fixed block: copies its composition table. Otherwise copies every generated composition as tab-separated text, without calculating. |
| **Clear** | Clears the document. |

## Examples

| Document | Result after Parse |
|---|---|
| `(FeCoNi)90Al10` | Single composition: Fe 30, Co 30, Ni 30, Al 10 at.% |
| `Al0.5CoCrFeNi` | Single composition: Al 11.11 at.%, Co, Cr, Fe and Ni 22.22 at.% each |
| `AlxCoCrFeNi` / `0 <= x <= 1, step=0.1` | 11 compositions, from CoCrFeNi to AlCoCrFeNi |
| `AlxCoCrFeNi` / `0 <= x <= 1, points=11` | the same 11 compositions, written as points |
| `(FeCoNi)1-xAlx` / `0 <= x <= 1, step=0.25` | 4 compositions, 1 combination skipped (at x = 1 only Al remains) |
| `(FeCoNi)1-x-y-z(AlTi)xCryCuz` with x, y from 0 to 0.2 step 0.1 and z from 0 to 0.1 step 0.05 | 27 compositions of 7 elements, 3 variables |
| `AlxCoCrFeNi` (x 0–2, step 0.1), blank line, `(CoCrFeNi)1-yAly` (y 0–0.3, step 0.05) | 26 compositions (2 duplicates) |

Worked example: [Parametric Expression: AlxCoCrFeNi](help://example-expression).
