# Exporting Results

Exports contain the dataset — all results, or all filtered results — never just the visible page, in the table's
current sort order. Results are deleted when the calculator closes, so export what you want to keep.

## Results

**Export** (above the results table) and **File › Export results** offer the same choices:

| Menu item | Writes |
|---|---|
| **Excel workbook (.xlsx)…** | All results |
| **CSV (.csv)…** | All results |
| **Filtered results (.xlsx)…** | Results that pass the active filter (available while a filter is active) |
| **Filtered results (.csv)…** | The same, as CSV |
| **Copy table to clipboard** | All filtered rows with the visible columns and displayed (rounded) values, tab-separated for a spreadsheet |
| **Copy visible rows** | The rows of the current page only |

**File › Copy table** (Ctrl+Shift+C) is the same as **Copy table to clipboard**.

### What an exported file contains

Each row contains the alloy name, its source, the at.% of every element of the exported runs, every descriptor
(whether or not its column is visible) at full precision, the M1–M8 predictions, a note per model and any warnings
or errors. An Excel file has a second worksheet, **About**, with the export date, the number of rows, the model
criteria, the M6/M7 temperature and the export scope. CSV files are UTF-8.

### Limits

* One Excel worksheet holds 1,048,575 rows. A larger export asks you to **Export as CSV** or to split the rows over
  several worksheets of one workbook; rows are never dropped silently.
* The clipboard takes at most 1,048,575 rows; export larger tables instead.
* Exports of more than 2,000 rows run in the background with their progress in the header and **Cancel**; a
  cancelled export writes no file.

## Analysis

| From | Export |
|---|---|
| Composition › **Options** | **Export composition report…** (PDF), **Print composition report…**, **Copy values** |
| Collection › **Options** | **Export analysis report…** (PDF), **Export statistics (CSV)…**, **Export plotted data (CSV)…**, **Export plot (SVG)…**, **Export plot (PNG)…** |
| Row menu › **Open details in new window** | **Export report…** in the Alloy details window |

Reports always use a light, printable layout, whichever theme the calculator uses. The composition report includes
the composition table with the Mass column for the current total mass.
