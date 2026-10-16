# Individual Composition Analysis

**Analysis › Composition** shows one result — the active composition — in detail: its normalised composition, its
descriptors and, for each model, the prediction with the values and thresholds behind it.

![Analysis › Composition › Overview for CoCrFeMnNi.](images/analysis-composition.png)

## Choosing the composition

The active composition changes when you double-click a result row, choose **Analyse composition** in the row menu,
calculate a single composition, or finish a batch (its first result). The panel heading shows the alloy name; the
line below gives its element family, number of elements, run and mode, and the temperature used for M6 and M7.

## Tabs

| Tab | Contents |
|---|---|
| **Overview** | The composition table in at.%, at. ratio, wt.% and mass; key descriptors; the model predictions with the number of models evaluated; data quality (missing data, supplementary values and cautions). |
| **Descriptors** | Every descriptor with symbol, value and unit; **Find a descriptor**; **Full precision**. |
| **Models** | One row per model with its prediction, status, criterion value and threshold. Select a row for its details. |
| **Model details** | One model at a time: criterion, evaluated values, interpretation, data, limitations, when it is not available, and the reference. For M6, the pair window and every binary pair. |

The last tab and model you used are remembered.

### Mass column

The composition table in Overview includes a **Mass** column for a batch of the **Total mass** set in Single
composition, headed for example **Mass (2 g batch)**. It is shown for every result, whatever mode produced it, and
follows the total mass immediately when you change it. Masses never change a descriptor or a prediction.

### δ and δ<sub>CN12</sub>

Two size-mismatch values are listed separately: **Size mismatch — Guo & Liu radii** (δ, used by M2–M5) and **Size
mismatch — Kittel CN12 radii** (δ<sub>CN12</sub>, used by M1). They use the same equation with different radius sets
and are not interchangeable.

## Options menu

The **Options** menu (⋮) of Composition offers **Copy values**, **Export composition report…** (PDF), **Print
composition report…**, **Show full precision** and **Help: Prediction model coverage**. To see a result in its own
window, use the row menu's **Open details in new window**; it opens **Alloy details** with the same tabs.

## Expanded analysis

**Expand analysis** (icon at the top right of the panel, Ctrl+Shift+E) shows Analysis over the whole window with
more room for tables and plots. **Back to calculation** (Ctrl+Shift+E) returns to the normal layout; the tab and the
model you were viewing are kept.

## Empty states

| State | Title |
|---|---|
| No results yet | **No results to analyse yet** |
| Results exist, none chosen | **No composition selected** — double-click a row to analyse it |
| The result was removed | **This composition was removed** |
| The result was recalculated | **This composition was recalculated** — double-click the row again |
