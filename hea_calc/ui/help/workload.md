# Workload estimation

## 1. Overview

Before a batch calculation starts, the calculator counts the compositions it will generate and estimates the
calculation time and the temporary disk space the results will occupy. The count is exact; the time and storage
figures are estimates based on measurements made during development. Single compositions are calculated at once
and need no estimate.

Estimates appear in the Tooltip of the summary line below the composition table. Batches larger than
10,000,000 compositions, or batches whose results would not fit on the disk, are not started.

## 2. Composition enumeration

**Composition space.** Each element is varied from *Min* to *Max* in steps of *Step*. Values are handled as exact
decimals, so a range such as 0.1 to 1.0 in steps of 0.1 always contains ten values.

* **Required and optional elements.** An element with *Lock* on is present in every composition. An element with
  *Lock* off is optional: the calculator forms every combination of the required elements with any subset of the
  optional ones. Each combination is an element system; systems with fewer than two elements are not generated.
* **System size.** Restricts the generated systems to one number of elements. *System size* (no selection)
  keeps all sizes.
* **At. ratio.** Every element takes each positive value of its range independently. Compositions that are
  proportional to one already generated (for example 2 : 2 : 2 and 1 : 1 : 1) are the same alloy and are counted
  once.
* **at.%.** Only combinations whose values add up to exactly 100 at.% are valid compositions.
* **Counting.** The number of valid compositions is calculated exactly before anything is generated. In at.% the
  count takes milliseconds. In at. ratio the calculator must check proportional duplicates and may need a few
  seconds for large spaces; the count stops at 10,000,000.

*Example.* Co, Cr, Fe and Ni required at 1.0; Al optional from 0.05 to 1.5 in steps of 0.05; Mn optional from 0.1 to
1.0 in steps of 0.1. Four systems are formed (CoCrFeNi, +Al, +Mn, +Al+Mn) and the space contains
**341 valid compositions** (1 + 30 + 10 + 300).

**Composition expression.** Each block is one formula; blocks are separated by a blank line. Variables are written
in lower case; each variable has one *Min / Max / Step* range, shared by every block that uses it.

* **Combinations.** A block with variables produces one combination per set of variable values (the product of
  the number of values of each variable); a block without variables produces one. The total is the sum over all
  blocks and may not exceed 5,000,000.
* **Valid compositions.** A combination is skipped when an amount becomes negative, a bracketed group sums to zero,
  or fewer than two elements remain. A composition that has already been generated — in the same or an earlier
  block — is counted once, in the block that produced it first.
* **Groups.** A bracketed group is normalised before its amount is applied: (FeCoNi)90Al10 is 30 / 30 / 30 / 10 at.%.

*Examples.* AlxCoCrFeNi with x from 0 to 2 in steps of 0.05: 41 combinations, **41 valid compositions**.
Blocks AlxCoCrFeNi (x 0–2, step 0.1) and (CoCrFeNi)1-yAly (y 0–0.3, step 0.05): 28 combinations, **26 valid
compositions**, 2 duplicates (y = 0 and y = 0.2 repeat x = 0 and x = 1.0 of the first block).

## 3. Runtime estimation methodology

The estimated calculation time is

  *t* = *N* / (2 250 × *W*) seconds,

where *N* is the number of valid compositions and *W* the number of calculation processes used on this computer
(one fewer than the number of logical processors, at most eight). The rate of 2 250 compositions per second per
process was measured on the development computer for five-element compositions, including storage of the
results. It is a fixed value: it is not measured on your computer and does not account for processor speed, disk
speed or the number of elements per composition. Treat it as an order of magnitude.

During a calculation the progress bar shows the remaining time measured on your computer from the progress so
far; this value replaces the estimate.

## 4. Temporary storage estimation

Results are stored on disk, not in memory, in a temporary database created for this session. The estimated size is

  *S* = *N* × 480 bytes,

the largest size per result measured during development, including the database's write-ahead log. Sizes are shown
in decimal units (1 MB = 1,000,000 bytes). A batch starts only if the disk holding the temporary folder has room
for the estimate plus a reserve of 512 MiB used for sorting and filtering.

The database is stored in your temporary folder (`%TEMP%\HEA Calculator\`) and is deleted when the calculator
closes. Export results you want to keep.

| Composition count | Tier shown in the Tooltip | Estimated storage |
|---|---|---|
| fewer than 250,000 | — | below 120 MB |
| 250,000 – 999,999 | Large set | 120 – 480 MB |
| 1,000,000 – 10,000,000 | Very large set (more than one Excel worksheet) | 0.48 – 4.8 GB |
| more than 10,000,000 | Too large — not started | — |

## 5. Execution strategy

Small batches (up to 300 compositions) are calculated directly. Larger batches are generated and calculated in
parallel background processes in groups of 50 to 500 compositions; results are written to the database in order as
they arrive, so the table fills while the calculation runs and the interface remains responsive. Sorting and
filtering of large result sets run in the background.

*Cancel* stops the calculation; results calculated up to that point are kept.

## 6. Accuracy and limitations

* The composition count is exact.
* The runtime estimate uses one fixed rate measured on a different computer; actual time may differ by a factor of
  several. The remaining time shown during the calculation is measured and more reliable.
* The storage estimate uses the largest measured size per result; actual use is usually lower.
* The largest batch tested end to end is about 1.04 million compositions; storage and table operations were tested
  to 10 million results. The 10,000,000 limit reflects this testing, not a scientific restriction.
