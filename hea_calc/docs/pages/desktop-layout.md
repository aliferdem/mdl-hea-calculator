# Desktop Layout

The main window has a title bar, three panels — Elements, Composition setup and Analysis — and the results
table below them. The whole window scrolls as one page; the results table never scrolls by itself, and its column
headings stay visible at the top while you scroll through it.

![The main window: title bar, the three upper panels and the results table.](images/main-window.png)

## Title bar

The calculator's title bar is the window's own: drag it to move the window, double-click it to maximise or restore,
drag it to a screen edge to snap, and right-click it (or press Alt+Space) for the window menu.  Hovering the maximise
button shows the Windows 11 snap layouts.

| Item | Use |
|---|---|
| **File** | **Import compositions…** (Ctrl+O), **Export results…**, **Calculation settings…**, **Exit** (Ctrl+Q). |
| **Edit** | **Undo** (Ctrl+Z), **Redo** (Ctrl+Y) and **Copy table** (Ctrl+Shift+C). |
| **View** | **Top panels** (Ctrl+B: show or hide the three upper panels), **Full screen** (F11), **Expand analysis** (Ctrl+Shift+E); **Panels**: **Elements**, **Composition setup** and **Analysis** (checked = expanded, unchecked = collapsed to its strip) and **Reset workspace** (top panels shown, every panel expanded, the calculation page — results, compositions and settings are kept); and the **Theme**: **Light**, **Dark** or **System default**. |
| **Help** | **Getting started**, **Documentation** (F1), **Expression syntax**, **Model support**, **Keyboard shortcuts** and **About MDL HEA Calculator**. |
| Status (centre) | While a batch runs: "Calculating…" with the percentage, the number of compositions done and the remaining time, and a progress line under the title bar. Afterwards: **Calculation completed** (green line), **Calculation cancelled** (yellow) or **Calculation failed** (red), with the number of compositions calculated. The outcome stays until your next click anywhere in the application. Exports show their progress here too, with **Cancel**. Messages appear here as well — confirmations such as **Table copied to clipboard** or **Export completed** go after a few seconds, warnings and errors stay until your next click; a message never interrupts a running calculation's progress. |
| Top panels button | Shows or hides the three upper panels, so the results table takes the window. |
| Minimise, Maximise / Restore, Close | The window buttons. |

Press **F10** to reach the menus from the keyboard: Left and Right move between them, Down or Enter opens one, Esc
returns.  **Alt+F**, **Alt+E**, **Alt+V** and **Alt+H** open File, Edit, View and Help directly.

## Panels

| Panel | Contents |
|---|---|
| **Elements** | The periodic table, the **Model support** row for the highlighted element and the element's properties. |
| **Composition setup** | The title is the mode menu: **Single composition**, **Composition space** — with its range basis (**At. ratio**, **at.%**, **wt.%** or **Mass**) — or **Expression**. The status of the input appears next to it; the footer holds **Clear** and **Calculate** (in Expression, **Parse expression** first). |
| **Analysis** | One result in detail (**Composition**) or a calculation run (**Collection**). **Expand analysis** (Ctrl+Shift+E) shows it over the whole window; **Back to calculation** returns. |
| Results table | Every calculated composition, newest first (select a column heading to sort; the third click returns to newest first), with filtering, columns, export and pagination. Messages and the outcome of a calculation are shown in the title bar, never above the table. |

Every upper panel has a collapse button at the right end of its header: a collapsed panel becomes a narrow strip
with its name and an expand button, and Analysis takes the space.  Elements and Composition setup otherwise always
keep their designed size. When the window is too narrow for Analysis beside them, Analysis moves below them, spans
the full width and becomes taller; the window then scrolls as a whole. **Expand analysis** opens the Analysis
workspace in the same window; on a small window its page scrolls as one, and tabs that do not fit show scroll arrows.

## Theme

**View > Theme** offers **System default** (follows the Windows light or dark setting, also when you change it
while the calculator runs), **Light** and **Dark**. The choice is remembered. The title bars of the calculator's
other windows follow the theme. Exported reports always use a light, printable layout.

## Messages

| Where | Meaning |
|---|---|
| Composition setup header | Status of the current input: what is missing or invalid, warnings such as **Partial model coverage** or **Large workload**, and in Expression the parse state (**Parsed successfully**, **Expression changed**, the problems found). Select it for details. |
| Title bar status | Outcome of a calculation (completed, cancelled or failed; for a failure, point at the sentence for the cause) and the window's messages: confirmations, warnings and errors. |
| Above the results table | Errors and warnings of other tasks (import, export, storage). |
| Red field frame | The value in that field cannot be used; the header names the problem. |
