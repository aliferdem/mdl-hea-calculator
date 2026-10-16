# Single Composition

Calculate one alloy of known composition. Select its elements, choose the input column, enter the amounts and
select **Calculate**; the result is one row in the results table with every descriptor and the predictions of
M1–M8.

![Single composition with CoCrFeMnNi entered as atomic ratios.](images/single-composition.png)

## Input columns

Choose the column you type in under **Input column**. Only the active column is editable; every value you type is
converted through atomic fractions into the other columns at once, so switching the active column never changes the
composition.

| Column | Meaning |
|---|---|
| **El.** | Edit element symbols. Type a new symbol to replace an element and keep its amount. |
| **At. ratio** | Proportional numbers of atoms. New elements start at 1. |
| **at.%** | Atomic percent; the column must sum to 100. |
| **wt.%** | Weight percent; the column must sum to 100. |
| **Mass** | Grams for the **Total mass** in the **Total:** row (default 2 g, remembered between sessions). |

See [Composition Representations](help://representations) for the conversions.

## Actions

**Clear** and **Calculate** are in the panel footer; the chevron next to Calculate opens the other actions.

| Action | Effect | Available |
|---|---|---|
| **Calculate** | Calculates the composition and adds it to the results table. | The composition is valid (the footer shows no error). |
| **Normalize** | Rescales the at.% or wt.% column so that it sums to 100. | Input column **at.%** or **wt.%** |
| **Set equal** | Gives every element the same value in the active column: 1 in At. ratio, 100/n in at.% and wt.%, total mass/n in Mass. | Every input column except **El.** |
| **Copy table** | Copies the composition table as tab-separated text for a spreadsheet. | Elements are selected |
| **Clear** | Removes all elements and deselects them in the periodic table. | Elements are selected |

## Rules checked before calculation

The footer names the first problem, and the affected field has a red frame:

* every element needs a valid number of zero or more (for example **Value required** or **Enter a number**);
* at.% and wt.% values must sum to 100 % (**Composition sum ≠ 100%** — use **Normalize**);
* at least two elements are selected, and at least two have a non-zero amount;
* the total mass must be greater than zero.

If the selected elements leave a model without data, the footer warns **Partial model coverage**; you can still
calculate — see [Model Support and Availability](help://model-availability).

## Result

The row is named from the atomic ratios in the order of selection (for example CoCrFeMnNi or Al0.5CoCrFeNi). The
composition opens in **Analysis** at once; a single composition needs no progress display.
