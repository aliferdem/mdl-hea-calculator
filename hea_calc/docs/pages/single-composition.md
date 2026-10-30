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
| **El.** | Edit element symbols. Type a new symbol to replace an element and keep its amount. Selecting **El.** changes only which column you type in: the amounts and their unit stay as they are. |
| **At. ratio** | Proportional numbers of atoms. New elements start at 1. |
| **at.%** | Atomic percent, with a balance element (below). |
| **wt.%** | Weight percent, with a balance element (below). |
| **Mass** | Grams for the **Total mass** in the **Total:** row (default 2 g, remembered between sessions). |

See [Composition Representations](help://representations) for the conversions.

### Balance element (at.% and wt.%)

In **at.%** and **wt.%** the first element of the table is the *balance*: its value is always 100 minus the sum of
the other elements, updated as you type, and its field cannot be edited. You enter every other element; the column
therefore always sums to 100. Switching to at.% or wt.% from another column keeps the composition: the values are
converted (wt.% to at.% through the molar masses) and the balance takes the remainder.

If the other elements add up to more than 100, the balance would be negative. The footer then reports
**Composition exceeds 100%**, the balance field shows the negative remainder with a red frame, and Calculate is
unavailable until you reduce the other values — nothing is rescaled or cut off for you. If you remove the balance
element, the next element in the table becomes the balance; **Clear** removes the balance with the elements.

## Adding and removing elements

Besides clicking tiles in **Elements**, you can type elements in the table:

* Select **Add element** (the + button at the left of the panel footer). A blank row appears under the last row,
  **El.** is selected as the input column, and the cursor is in the new symbol field.
* Type a symbol (any case, for example *fe*) and press **Enter**. The element is added exactly as if you had clicked
  its tile — the tile is selected — and a new blank row is ready for the next symbol. An unknown symbol, or one
  already in the table, is reported in the footer and is not added.
* Press **Esc**, or click elsewhere while the blank row is empty, to close it. A blank row is never part of a
  calculation.
* To remove an element, right-click any of its fields and select **Remove element**. This is the same as clicking
  its selected tile.

## Actions

**Clear** and **Calculate** are in the panel footer; the chevron next to Calculate opens the other actions.

| Action | Effect | Available |
|---|---|---|
| **Calculate** | Calculates the composition and adds it to the results table. | The composition is valid (the footer shows no error). |
| **Set equal** | Gives every element the same value in the active column: 1 in At. ratio, 100/n in at.% and wt.%, total mass/n in Mass. | Every input column except **El.** |
| **Copy table** | Copies the composition table as tab-separated text for a spreadsheet. | Elements are selected |
| **Clear** | Removes all elements and deselects them in the periodic table. | Elements are selected |

## Rules checked before calculation

The footer names the first problem, and the affected field has a red frame:

* every element needs a valid number of zero or more (for example **Value required** or **Enter a number**);
* in at.% and wt.%, the elements other than the balance must not exceed 100 % (**Composition exceeds 100%**);
* at least two elements are selected, and at least two have a non-zero amount;
* the total mass must be greater than zero.

If the selected elements leave a model without data, the footer warns **Partial model coverage**; you can still
calculate — see [Model Support and Availability](help://model-availability).

## Result

The row is named in the basis you entered, in the order of selection. **At. ratio** and **Mass** give the atomic-ratio
formula (for example CoCrFeMnNi or Al0.5CoCrFeNi). **at.%** and **wt.%** give the values as entered with the basis
stated, for example Cr12Mn20Co3Ni15Cu20Zn20Si10 (at.%) or Fe70Cr18Ni12 (wt.%), so a weight composition is never read
as a formula. The name is only a label: the calculation always uses the atomic composition. The
composition opens in **Analysis** at once; a single composition needs no progress display.
