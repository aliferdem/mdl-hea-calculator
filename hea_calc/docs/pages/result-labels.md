# Prediction Result Labels

Each model column of the results table shows one tag. The tag colours encode the predicted class; they are not
success or error indicators.

## Tags

| Tag | Meaning |
|---|---|
| **SS** | Solid solution |
| **MP** | Multiple phases — not a single solid solution |
| **IM** | Intermetallic |
| **SS+IM** | Solid solution with intermetallic |
| **MG** | Metallic glass (amorphous) |
| **N/A** | Not available — the model could not be evaluated |

## Classes each model can produce

| Model | Classes |
|---|---|
| M1 Yang & Zhang, M3 Wang, M5 Ye, M8 King | SS, MP |
| M2 Guo | SS, MG, MP |
| M4 Singh | SS, SS+IM, IM |
| M6 Troparevsky | SS, IM, MP |
| M7 Senkov & Miracle | SS, IM |

A class a model cannot produce is never shown for it, and collection statistics list only a model's own classes.

## N/A is not a phase

**N/A** means that the model gave no prediction: a required elemental property or binary value is missing, or a
quantity of the criterion is undefined for this composition (for example Ω when ΔH<sub>mix</sub> is exactly zero). It
says nothing about the phases that form. MP, IM and SS+IM are predictions: the model was evaluated and placed the
composition outside its solid-solution region. Open the composition in Analysis to read the reason for an N/A.

## Statuses

Some predictions carry a status. The tag in the table stays the same; the status icon and its explanation are in
**Analysis › Models**.

| Status | Meaning |
|---|---|
| **Extrapolated** | The composition lies outside the domain the criterion was derived for — for example M7 when ΔH<sub>mix</sub> ≥ 0. |
| **Flagged binary data** | A binary value marked as unreliable takes part in the decision (M6, M7). See [Binary Interaction Data](help://binary-data). |
| Caution | A supplementary value was used, for example a radius not from Guo & Liu's table. |

## When models disagree

The eight models use different descriptors, data and thresholds, calibrated on different sets of alloys. AlCoCrFeNi,
for example, is SS in M1 and M3, MP in M2, M5 and M8, SS+IM in M4, and IM in M6 and M7. Treat the tags as independent
screening indicators, not as votes on one answer.
