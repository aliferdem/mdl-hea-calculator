# Calculation Workflow

Select **Calculate** at the bottom right of Composition setup. It is available when the footer shows no error. A
single composition is calculated at once; a batch runs in the background while you keep working.

## A single composition

The result is added to the results table immediately, the table shows the page that holds it, and the composition
opens in Analysis.

## A batch

A composition space, a set of expressions or an imported file is one **calculation run**:

1. The compositions are generated in background processes. The header shows **Generating compositions** while this
   takes noticeable time.
2. They are calculated in parallel background processes. The header shows **Calculating…** with the percentage, a
   progress bar, and a detail line such as "(24,990/99,961) 2 minutes remaining". The remaining time is measured on
   your computer from the progress so far.
3. Results are written to the session database in order as they arrive, so the table fills while the run continues.
4. When the run finishes, a message above the results table reports the number of compositions calculated, and the
   first result becomes the active composition in Analysis.

While a batch runs, **Calculate** is unavailable, the footer reads **Calculating…**, and **Clear** becomes
**Cancel**. Cancelling stops the run and keeps the results calculated so far; the message then reads, for example,
"6 composition(s) calculated (cancelled)."

## Runs

Every calculation adds a numbered run (Run 1, Run 2 …). The run records how its compositions were defined — mode,
ranges or expressions — and the calculation settings. Analysis uses runs to keep collections consistent: a
collection always belongs to one run. See [Collection Analysis](help://collection-analysis).

## Responsiveness

No calculation runs in the window's own process. The window stays responsive during large runs; sorting and filtering
very large result sets also run in the background, and the table says so while they are in progress.

## Errors

If a batch cannot start — for example because its results would not fit on the disk — or fails, an error message
appears above the results table and stays until you close it. Results calculated before a failure are kept.
