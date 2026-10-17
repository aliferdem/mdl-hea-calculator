# Importing Compositions

**File › Import compositions** (Ctrl+O) reads a spreadsheet and calculates every valid row as one run.

## Supported files

Excel workbooks (.xlsx, .xlsm) and CSV files (.csv). The first worksheet of a workbook is read. Legacy .xls files
are not supported; save them as .xlsx first.

## Layouts

Use one of two layouts:

* **One column per element** — headed with the symbol (Fe, Co …) or the symbol and a unit (Fe (at.%)). Amounts are
  proportional; blank element cells count as zero.
* **One formula column** — headed **Formula**, **Alloy**, **Composition**, **Identifier** or **Name**, with formulas
  such as Al0.5CoCrFeNi.

A **Name**, **Alloy**, **ID** or **Label** column labels the rows; the label becomes the alloy name in the results
table.

## Rows that cannot be read

Rows with an invalid amount or formula, a missing formula, or fewer than two elements with a non-zero amount are
skipped. Column headings that are not element symbols are ignored. Both are listed in the **Import report** with the
spreadsheet row and the reason, and the valid rows are calculated. If no row is valid, nothing is calculated and
a message says so.

## After importing

Imported results are a calculation run like any other: they appear in the results table, can be filtered and
exported, and can be analysed as a collection.
