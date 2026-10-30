# Collection Analysis

**Analysis › Collection** analyses many results together: counts, distributions, statistics and plots. Switching
between Composition and Collection keeps the state of both.

![Analysis › Collection › Plots for a composition space.](images/analysis-collection.png)

## Which results are analysed

A collection belongs to one **calculation run**, or to runs you combine yourself; runs are never mixed silently.
Choose the run and its **population**:

* **Full result set** — every result of the run.
* **Filtered result set** — the results of the run that pass the results-table filter (available while a filter is
  set).

**Restrict** narrows either population further by **element family**, **system size** or **expression block**. The
summary line states exactly what is analysed: the number of results, the run and the population.

The collection is fixed when you create or update it. Sorting, paging and double-clicking in the results table do
not change it. If you change the table filter, the panel shows **Results filter changed**, and **Update collection**
applies the change. Removed results disappear from the collection immediately.

While a calculation stores results in the collection's run, the collection keeps the results it was loaded with: it
does not rebuild itself as results arrive. A notice says that newer results are available, and **Refresh** brings
them in when you choose. Refresh keeps the run, population, filter and restrictions.

### Combining runs

**Combine runs…** in the run list opens a list of the session's runs, with their type, number of results and status.
Select two or more and choose **Combine**. The collection then analyses their results together:

* Nothing is copied or merged. Every result keeps its own result and run, and the runs themselves are unchanged.
  Choose a single run in the run list to go back to it.
* The same composition calculated in two runs is two results, and each counts once. The collection notice says how
  many compositions occur in more than one run.
* Counts, statistics and model distributions use all selected runs together. Missing values are excluded and counted
  as for one run.
* Runs can be combined only if they were calculated with the same engine version, datasets and calculation settings.
  A run that differs is shown but cannot be selected, and its row says why.
* Expression variables, composition-space grid values and expression blocks belong to single runs, so they are not
  offered as plot axes or restrictions in a combined collection.

Reports of a combined collection name every contributing run.

## Tabs

| Tab | Contents |
|---|---|
| **Overview** | Size and composition of the collection, and how many results each model could evaluate. |
| **Plots** | Scatter, line, histogram, box plot, heatmap and model-class bars. See [Plots and Statistical Analysis](help://plots-statistics). |
| **Statistics** | Count, missing values, median, quartiles and range for the descriptors you choose; distribution of one descriptor. |
| **Models** | How many results each model placed in each of its classes. |

## Selecting results in a plot

Select points with the selection tools of a plot. The selection bar then offers **Show in results table** — the
table shows exactly the selected results, as a filter you can clear — and **Clear**. Double-click a point to analyse
that composition.

## Element families

An element family is the set of elements present in a composition, written alphabetically (for example
Al-Co-Cr-Fe-Ni). It does not depend on the order or unit in which the composition was entered. When expression blocks
produce the same composition, it is calculated once and belongs to the first block that produced it.

## Model distributions

For each model the **Models** tab shows how many results received each class. Percentages refer to the results for
which the model could be evaluated; results where the model is not available are counted separately and are never
treated as a class. Each model lists only the classes it can produce — M4 distinguishes SS, SS+IM and IM, while M1
distinguishes SS and MP — so a class missing from a model's bar is not a zero count. Extrapolated verdicts and
verdicts that depend on flagged data are counted separately within each class.

## Options menu

**Export analysis report…** (PDF), **Export statistics (CSV)…**, **Export plotted data (CSV)…**, **Export plot
(SVG)…**, **Export plot (PNG)…** and **Help: Analysing collections**.
