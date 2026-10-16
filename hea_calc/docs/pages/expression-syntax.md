# Expression Syntax Reference

The complete syntax of **Composition expression**. An expression is a formula of element symbols and amounts; the
amounts are atomic ratios and may contain variables.

## Elements and amounts

| Write | Meaning | Example |
|---|---|---|
| Element symbol | Case-sensitive symbol. A two-letter symbol takes precedence: **Ba** is barium, not boron and a. | `Fe`, `Co` |
| Number after a symbol | Amount as an atomic ratio. No number means 1. | `Al0.5CoCrFeNi` |
| Same element twice | The amounts add up. | `FeCoFe` = Fe2Co |

## Groups

| Write | Meaning | Example |
|---|---|---|
| ( … ) or [ … ] | Group. Its contents are normalised to a total of 1, then multiplied by the group's amount. | `(FeCoNi)90Al10` = 30 / 30 / 30 / 10 at.% |
| Nested groups | Each level is normalised in turn. | `((FeNi)1Co1)0.8Al0.2` |

## Variables and arithmetic

| Write | Meaning | Example |
|---|---|---|
| Lower-case name | Variable: a lower-case letter, optionally followed by lower-case letters, digits and _. | `x`, `y1`, `al_frac` |
| Simple amount | A number, a variable or a chain with + − * /; "2x" means 2 × x. | `Alx`, `(FeCoNi)1-x`, `100-2x` |
| { … } or _( … ) | Any arithmetic with + − * / ^ and parentheses. Use braces when a variable would merge with a symbol: `B{a}` is boron with amount a. | `Ti{0.1*k}`, `Fe{2-x}`, `Mo_(1-y)` |

## Blocks

| Write | Meaning |
|---|---|
| Blank line | Starts a new block. Each block is one formula. |
| Spaces, single line breaks | Ignored. |

## Ranges

Each variable has one **Min**, **Max** and **Step** (defaults 0, 1, 0.1), shared by every block that uses it. Values
form a regular grid from Min to Max; Min = Max gives one value. There is no random sampling.

## Rules for generated compositions

* A combination is skipped when an amount becomes negative, a group sums to zero, or fewer than two elements remain.
* A composition generated more than once is calculated once, in the block that produced it first.
* The number of combinations may not exceed 5,000,000.

## Error messages

Syntax errors appear below the expression field with the position, for example "Unknown element 'Q' (at position
5)". With several blocks the message starts with the block number ("Block 2: …"), and the footer shows **Invalid
expression**.
