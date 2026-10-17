# Frequently Asked Questions

## Why is Calculate unavailable?

The footer of Composition setup names the reason: for example fewer than two elements, a missing or invalid value,
at.% or wt.% values that do not sum to 100 %, or no valid compositions. In **Composition expression**, Calculate
waits for an explicit **Parse**, and becomes unavailable again when you edit the document after parsing ("Expression
changed. Parse again to update the result."). Calculate is also unavailable while a batch is running; use **Cancel**
in the footer to stop it.

## Why does my composition space produce no compositions?

With **Range basis** at.% or wt.%, the values of each composition must add up to exactly 100; check the ranges and
steps (the footer reads **No valid compositions - values must sum to 100 %**). In a composition expression, every
combination may be skipped because an amount turns negative or fewer than two elements remain. The count is shown
before you calculate.

## Why are some prediction models unavailable (N/A)?

Each model needs its own elemental and binary data. If one element or pair is missing from a model's dataset, that
model shows N/A with the reason, and the other models are evaluated normally; the footer warns **Partial model
coverage** before you calculate. Missing data are never replaced by zero. See
[Prediction Model Coverage](help://model-coverage).

## Why do different models predict different phases?

The models are separate empirical or semi-empirical criteria based on different descriptors, data and alloy sets.
Disagreement is expected, especially near their thresholds. Read each tag as one model's indication and check the
values in **Analysis › Models**.

## What is the difference between atomic ratio and atomic percent?

An atomic ratio gives proportional numbers of atoms — Al0.5CoCrFeNi means 0.5 : 1 : 1 : 1 : 1. Atomic percent gives
the same proportions scaled to 100: 11.11 at.% Al and 22.22 at.% of each other element. The calculator converts
between them automatically.

## Why do δ and δ<sub>CN12</sub> differ?

They use different radius sets: Guo & Liu radii for δ (used by M2–M5) and Kittel's 12-coordination radii for
δ<sub>CN12</sub> (used by M1). For CoCrFeMnNi they are 3.27 % and 0.92 %. Each is compared only with the threshold of
the model that uses it.

## What does the total mass change?

Only the masses: the **Mass** column of Single composition and the Mass column in Analysis. Descriptors and
predictions do not depend on it. The value is remembered for later sessions.

## Why does counting compositions take time?

The count is exact. In at.% and wt.% it is immediate; in At. ratio and Mass the calculator must recognise
proportional duplicates, which can take a few seconds for large spaces. The count runs in the background, and the
footer shows **Updating…** meanwhile.

## What happens when the workload is very large?

Batches run in background processes and results are stored on disk, so the window stays responsive; sorting and
filtering then take a few seconds. Batches above 10,000,000 compositions, or without enough free disk space, are not
started. See [Workload Estimation](help://workload).

## How do I inspect a particular alloy?

Double-click its row in the results table, or right-click the row and select **Analyse composition**. To find it
first, sort by a column or use **Filter results**. **Open details in new window** shows it in a separate window.

## How do I export my results?

Select **Export** above the results table and choose Excel or CSV — all results, or the filtered results while a
filter is active. Exports include every descriptor at full precision. See [Exporting Results](help://export).

## Are my results saved when I close the calculator?

No. Results live in a temporary database that is deleted when the calculator closes. Export them, or copy the
table, before you exit.

## I cleared the table by mistake. Can I undo it?

No. **Clear table** removes every result immediately and cannot be undone. Calculate the compositions again; your
settings in Composition setup are unchanged.
