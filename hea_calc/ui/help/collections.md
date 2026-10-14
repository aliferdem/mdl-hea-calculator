# Analysing collections

## 1. Composition and collection

The Analysis panel has two views. **Composition** shows one result — the active composition — in detail: its
normalised composition, descriptors and the verdict of each model with the values and thresholds behind it.
Double-click a row in the results table to make it the active composition. **Collection** analyses many results at
once: counts, distributions, statistics and plots. Switching between the two views keeps the state of both.

## 2. Which results are analysed

A collection always belongs to one calculation run unless you combine runs explicitly. Choose the population:

* **Full result set** — every result of the run.
* **Filtered result set** — the results of the run that satisfy the results-table filter.
* **Checked results** — the results you checked in the table.

You can restrict any population further by element family, system size or expression block. The summary line
states exactly what is analysed, for example "Analysing 341 of 341 results · Run 3 · Full result set".

The collection is fixed when you create or update it. Sorting, paging and double-clicking in the results table do
not change it. If you change the table filter or the checked results, the panel shows a notice and *Update
collection* applies the change. Removed results disappear from the collection immediately.

Runs calculated with different M6/M7 temperatures or different program versions are not directly comparable; a
combined collection hides the affected model distributions.

## 3. Plots

Each point of a scatter plot is one composition. Lines connect points only along an ordered expression variable or
sweep axis; compositions of a general composition space are shown as points. Values that are not available are
never drawn as zero; the number of omitted results is stated below the plot. When a collection is too large to draw
every point, the plot shows a random sample or counts per bin and says so on the plot.

An element family is the set of elements present in a composition, written alphabetically (for example
Al-Co-Cr-Fe-Ni). It does not depend on the order or unit in which the composition was entered. When expression blocks
produce the same composition, it is calculated once and belongs to the first block that produced it.

## 4. Statistics

For each descriptor the panel reports the number of results with a value (N valid), the number without a value
(N missing), and the median, quartiles and range; the expanded view adds mean and standard deviation (n − 1).
Quartiles use linear interpolation between ordered values. Results without a value are excluded, never counted as
zero. Model verdicts are categories: they are counted, never averaged.

## 5. Model distributions

For each model the panel shows how many results received each class. Percentages refer to the results for which the
model could be evaluated; results where the model is not available are counted separately. Each model has its own
set of classes — for example M4 distinguishes SS, SS+IM and IM, while M1 distinguishes SS and MP — so a class missing
from a model's bar is not a zero count. Verdicts that are extrapolated or that depend on flagged data are counted
separately within each class.
