# Desktop Layout

The main window has a header, three panels — Elements, Composition setup and Analysis — and the results
table below them. The whole window scrolls as one page; the results table never scrolls by itself, and its column
headings stay visible at the top while you scroll through it.

![The main window: header, the three upper panels and the results table.](images/main-window.png)

## Header

| Item | Use |
|---|---|
| **File** | **Import compositions** (Ctrl+O), **Export results**, **Copy table** (Ctrl+Shift+C), **Calculation settings**, **Exit** (Ctrl+Q). |
| **About** | Version, credits and licences. |
| Status (centre) | While a batch runs: "Calculating…" with the percentage, the number of compositions done and the remaining time, and a progress line along the header's lower edge. Afterwards: **Calculation succeeded** (green line), **Calculation cancelled** (yellow) or **Calculation failed** (red), with the number of compositions calculated. Exports show their progress here too, with **Cancel**. |
| **Help** (question-mark icon) | Opens Documentation Home. |
| **Theme** (icon of the chosen setting) | Choose **Light**, **Dark** or **System default**. |

## Panels

| Panel | Contents |
|---|---|
| **Elements** | The periodic table, the **Model support** row for the highlighted element and the element's properties. |
| **Composition setup** | The title names the active mode (**Single composition**, **Composition space** or **Composition expression**); the mode switcher is at the top right; the footer holds the status message, **Clear** and **Calculate**. |
| **Analysis** | One result in detail (**Composition**) or a calculation run (**Collection**). **Expand analysis** (Ctrl+Shift+E) shows it over the whole window; **Back to calculation** returns. |
| Results table | Every calculated composition, with filtering, columns, export and pagination. Errors that need your attention appear above it; the outcome of a calculation is shown in the header. |

Elements and Composition setup always keep their designed size. When the window is too narrow for Analysis
beside them, Analysis moves below them, spans the full width and becomes taller; the window then scrolls as a whole.
**Expand analysis** opens the Analysis workspace in the same window; on a small window its page scrolls as one, and
tabs that do not fit show scroll arrows.

## Theme

The **Theme** menu offers **System default** (follows the Windows light or dark setting, also when you change it
while the calculator runs), **Light** and **Dark**. The choice is remembered. The native title bars of the
calculator's windows follow the theme. Exported reports always use a light, printable layout.

## Messages

| Where | Meaning |
|---|---|
| Composition setup footer | Status of the current input: what is missing or invalid, warnings such as **Partial model coverage**, and **Ready** when a batch can be calculated. An information icon gives details. |
| Header status | Outcome of a calculation: succeeded, cancelled or failed. |
| Above the results table | Errors and warnings of other tasks (import, export, storage). |
| Red field frame | The value in that field cannot be used; the footer names the problem. |
