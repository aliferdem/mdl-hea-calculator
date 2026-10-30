# Expression Syntax Reference

The complete syntax of **Composition expression**. A document is a set of blocks; the first line of each block is a
formula of element symbols and amounts (atomic ratios, which may contain variables), and the following lines give
the range of each variable.

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
| Blank line | Starts a new block. |
| First line of a block | The expression. |
| Following lines of a block | Range lines, one per variable of that expression. |

A block without variables has only its expression line (a fixed composition). Fixed and parametric blocks may be
mixed in one document.

## Range lines

```
lower <= variable <= upper, step=s
lower <= variable <= upper, points=n
lower < variable < upper, step=s
```

| Part | Rule |
|---|---|
| Bounds | Numbers; the lower bound may not exceed the upper bound. Equal bounds give one value. |
| `<=` (or `≤`) and `<` | `<=` includes the bound, `<` excludes it; the two sides may differ (`0 < x <= 1`). The values are first laid out on the closed interval (from the lower bound in steps, or n points including both bounds), then an excluded bound is removed: `0 < x < 1, step=0.1` gives 0.1 … 0.9 (9 values) and `0 < x < 1, points=11` gives 9 values. A range whose bounds exclude every value is an error. |
| `step=s` | Values from the lower bound in steps of s up to the upper bound; s must be greater than 0. |
| `points=n` | n equally spaced values including both bounds; n is a whole number of at least 2. |
| `step` and `points` | Exactly one of the two. |
| `p=v` (optional) | The value the block's preview uses; it must lie within the bounds. |

Each variable of an expression needs exactly one range line in its block, and every range line must name a variable
of that expression.  When you type a new variable, its range line is added for you - `0 <= x <= 1, step=0.1`, two
spaces in, after the block's last line - so you only edit the values.  It is added once: a range line you delete
or undo is not added again.  Renaming a variable renames its range line and keeps its values; a default range line
whose variable you removed is removed with it, an edited one stays and is reported as not used. A range belongs to its own block: the same letter in two blocks has two independent ranges.
There is no random sampling.

## Editor

* **Colours.** Element symbols, numbers, variables, range keywords (`step`, `points`, `p`), operators and comparisons,
  and brackets each have their own colour, read the way the calculation reads the text (`CrMnFeCoNiyCux` is
  Cr Mn Fe Co Ni y Cu x).  A thin vertical guide joins a block's range lines.
* **Problems** are underlined with a wavy line where they are, and marked in the strip on the right edge.  The panel
  header names the problem, or says "Multiple errors"; select it to see every problem by line.  A problem that only
  means the line is unfinished (a bracket not closed yet) waits until you leave the line or choose Parse expression.

## Parsing

**Parse expression** (the footer button, or Ctrl+Enter) parses every block and counts its compositions; the header
then shows **Parsed successfully** (or **Parsed with warnings** when combinations are skipped or duplicates removed),
and the footer button becomes **Calculate**. **Calculate** uses the parsed document only: editing after a parse
shows **Expression changed** and the button returns to Parse expression until the next parse.  A batch that is
large or above the combination limit is a workload message, not an expression error.

## Rules for generated compositions

* A combination is skipped when an amount becomes negative, a group sums to zero, or fewer than two elements remain.
* A composition generated more than once is calculated once, in the block that produced it first.
* The number of combinations may not exceed 5,000,000.

## Error messages

Each problem is underlined in place; the header's tag lists them by line.

| Message | Cause |
|---|---|
| Unknown element "Xx" | A symbol that is not an element. |
| Unmatched parenthesis | A group is not closed (or closed twice). |
| Choose one sampling method. Specify either step or points, not both. | A range line gives both. |
| Choose a sampling method for x. Specify step or points. | A range line gives neither. |
| The variable "x" has no range. Add a line such as 0 <= x <= 1, step=0.1. | A variable without a range line. |
| The variable "x" is declared twice. | Two range lines for the same variable. |
| The variable "x" is not used in the expression. | A range line for a letter the expression does not contain. |
| The range 0 < x < 0 contains no values. | Excluded bounds remove every value of the range. |
