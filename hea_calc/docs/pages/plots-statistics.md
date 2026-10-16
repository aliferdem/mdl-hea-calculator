# Plots and Statistical Analysis

The Plots and Statistics tabs of a collection describe how descriptors and predictions vary across a calculation
run. Values that are not available are excluded and counted — never drawn or averaged as zero.

## Plot types

| Plot | Shows |
|---|---|
| **Scatter** | One point per composition: a descriptor or design coordinate against another, optionally coloured by a model's prediction or a descriptor. |
| **Line (ordered by parameter)** | Values along an ordered variable — an expression variable or a composition-space axis. Points are connected only along such a variable. |
| **Histogram** | Distribution of one descriptor. |
| **Box plot** | Median, quartiles and range of one descriptor, optionally per group (family, system size, block). |
| **Heatmap (two parameters)** | A value over two design parameters, for example two at.% axes of a composition space. |
| **Stacked bars** / **Grouped bars (model classes)** | Counts of each model's classes. |

Hover a point for its values; double-click it to analyse that composition. The number of results omitted because a
value is not available is stated below the plot.

### Large collections

Up to 50,000 points are drawn individually. Larger scatter plots show a random sample, or counts per bin, and say so
on the plot. **Representation** chooses **Automatic**, **All points**, **Sample** or **Binned**; the bin grid is
50 × 50 to 400 × 400.

## Statistics

Choose the descriptors with **Metrics**. The default set is ΔH<sub>mix</sub>, ΔS<sub>mix</sub>, Ω, δ,
δ<sub>CN12</sub>, VEC and Φ; no descriptor is given special weight. For each descriptor the table reports the
number of results with a value (**N**; hover it for the number missing), the **Median**, the quartiles **Q1 – Q3**
and the range **Min – Max**. **All measures** — and the expanded view — show every measure:

| Column | Meaning |
|---|---|
| N valid | Results with a value |
| N missing | Results without a value (missing data or undefined) |
| Mean, SD | Arithmetic mean and standard deviation (n − 1) |
| Min, Q1, Median, Q3, Max | Range and quartiles; quartiles by linear interpolation between ordered values |

**Group** splits the statistics by element family, system size or expression block.

### Distribution of one descriptor

**Distribution of** selects one descriptor for the histogram and box plot; you can also activate a statistics row.
Until you choose one, the area shows **Select a descriptor**.

### Size mismatch: two descriptors

δ and δ<sub>CN12</sub> appear as **Size mismatch — Guo & Liu radii** and **Size mismatch — Kittel CN12 radii**. They
use the same equation with different radii; compare each with the model that uses it (δ for M2–M5,
δ<sub>CN12</sub> for M1).

## Model verdicts are categories

Predictions are counted, never averaged. Model distributions are in the collection's **Models** tab; see
[Collection Analysis](help://collection-analysis).
