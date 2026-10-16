# Desktop Layout

The main window has a header, three panels — Element selection, Composition setup and Analysis — and the results
table below them. The whole window scrolls as one page; the results table never scrolls by itself, and its column
headings stay visible at the top while you scroll through it.

![The main window: header, the three upper panels and the results table.](images/main-window.png)

## Header

| Item | Use |
|---|---|
| **File** | **Import compositions…** (Ctrl+O), **Export results**, **Copy table** (Ctrl+Shift+C), **Calculation settings…**, **Help** (F1), **About HEA Calculator**, **Exit** (Ctrl+Q). |
| **About** | Version, credits and licences. |
| Progress (centre) | While a batch runs: "Calculating…" with the percentage, a progress bar, the number of compositions done and the remaining time. Exports show their progress here too, with **Cancel**. |
| **Help** (question-mark icon) | Opens Documentation Home. |
| **Theme** (sun or moon icon) | Choose **System default**, **Light** or **Dark**. |

## Panels

| Panel | Contents |
|---|---|
| **Element selection** | The periodic table, the **Model support** row for the highlighted element and the element's properties. |
| **Composition setup** | The title names the active mode (**Single composition**, **Composition space** or **Composition expression**); the mode switcher is at the top right; the footer holds the status message, **Clear** and **Calculate**. |
| **Analysis** | One result in detail (**Composition**) or a calculation run (**Collection**). **Expand analysis** (Ctrl+Shift+E) shows it over the whole window; **Back to calculation** returns. |
| Results table | Every calculated composition, with filtering, columns, export and pagination. Messages about finished tasks appear above it. |

On a narrow window, Analysis moves below Element selection and Composition setup. Composition setup keeps its
designed width; the other panels share the remaining space.

## Theme

The **Theme** menu offers **System default** (follows the Windows light or dark setting, also when you change it
while the calculator runs), **Light** and **Dark**. The choice is remembered. The native title bars of the
calculator's windows follow the theme. Exported reports always use a light, printable layout.

## Messages

| Where | Meaning |
|---|---|
| Composition setup footer | Status of the current input: what is missing or invalid, warnings such as **Partial model coverage**, and **Ready** when a batch can be calculated. An information icon gives details. |
| Above the results table | Outcome of a task: done, warning (for example a cancelled run) or error. Done messages close after a few seconds. |
| Red field frame | The value in that field cannot be used; the footer names the problem. |
