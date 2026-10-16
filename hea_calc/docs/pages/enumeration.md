# Composition Enumeration

Batch modes turn ranges or variables into a list of compositions. The rules below decide which compositions are
generated and how they are counted; the count shown before calculating is exact.

## Composition space

Each element is varied from **Min** to **Max** in steps of **Step**. Values are handled as exact decimals, so a range
such as 0.1 to 1.0 in steps of 0.1 always contains ten values.

* **Systems.** Required elements (Lock on) are always present; optional elements (Lock off) form every subset. Each
  combination is an element system; systems with fewer than two elements, or of a size excluded by **System size**,
  are not generated.
* **Values.** Inside a system, every element takes each positive value of its range independently.
* **At. ratio and Mass.** Compositions proportional to one already generated (for example 2 : 2 : 2 and 1 : 1 : 1)
  are the same alloy and are counted once.
* **at.% and wt.%.** Only combinations whose values add up to exactly 100 are valid compositions.
* **Counting.** The number of valid compositions is calculated before anything is generated. In at.% and wt.% the
  count takes milliseconds. In At. ratio and Mass the calculator must check proportional duplicates and may need a
  few seconds for large spaces; the count stops above 10,000,000.

*Example.* Co, Cr, Fe and Ni required at 1.0; Al optional from 0.05 to 1.5 in steps of 0.05; Mn optional from 0.1 to
1.0 in steps of 0.1. Four systems are formed (CoCrFeNi, +Al, +Mn, +Al+Mn) and the space contains **341 valid
compositions** (1 + 30 + 10 + 300).

## Composition expressions

* **Combinations.** A block with variables produces one combination per set of variable values (the product of the
  number of values of each variable); a block without variables produces one. The total is the sum over all blocks
  and may not exceed 5,000,000.
* **Valid compositions.** A combination is skipped when an amount becomes negative, a bracketed group sums to zero,
  or fewer than two elements remain. A composition that has already been generated — in the same or an earlier block
  — is counted once, in the block that produced it first.
* **Groups.** A bracketed group is normalised before its amount is applied: (FeCoNi)90Al10 is 30 / 30 / 30 / 10 at.%.

*Examples.* AlxCoCrFeNi with x from 0 to 2 in steps of 0.05: 41 combinations, **41 valid compositions**. Blocks
AlxCoCrFeNi (x 0–2, step 0.1) and (CoCrFeNi)1-yAly (y 0–0.3, step 0.05): 28 combinations, **26 valid
compositions** and 2 duplicates (y = 0 and y = 0.2 repeat x = 0 and x = 1 of the first block).

## Design coordinates

Every result of a batch keeps the values that generated it — the grid values of a composition space in its range
basis, or the variable values of an expression, and the block number. Analysis plots can use them as axes, and lines
connect results only along such an ordered variable.
