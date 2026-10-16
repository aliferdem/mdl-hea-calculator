# Scope and Scientific Limitations

The predictions are screening indicators. Read them as tendencies reported by published criteria, not as phase
diagrams or as a substitute for experiments or CALPHAD and first-principles calculations.

## What the models can and cannot tell you

* All eight criteria are empirical or semi-empirical rules calibrated on limited sets of mostly as-cast or annealed
  alloys. They predict tendencies, not the phases present after a given processing route.
* **MP** means "not a single solid solution". It does not identify the phases that form.
* Binary data describe binary systems only; ternary and higher-order compounds are not considered.
* The models use different radius sets, binary datasets and temperatures, so their numbers are not
  interchangeable: δ (Guo & Liu radii, M2–M5) is not δ<sub>CN12</sub> (Kittel radii, M1); φ of M5 is unrelated to Φ
  of M8.
* The models were derived from different alloy sets and can disagree for the same composition, especially near
  their thresholds. See [Prediction Result Labels](help://result-labels).
* A model's element coverage does not mean the model was validated for alloys of those elements. Predictions for
  noble gases, halogens and superheavy elements are formal evaluations without physical meaning for alloys.

## Approximations in the descriptors

* T<sub>m</sub> and ρ are rule-of-mixtures values; excess quantities are ignored.
* ΔH<sub>mix</sub> uses Miedema-model liquid mixing enthalpies of equiatomic binary pairs (Takeuchi & Inoue 2005)
  in the regular-solution form; ΔS<sub>mix</sub> is the ideal configurational entropy.
* Radii come from tabulations, not from the alloy. Elements outside Guo & Liu's table use supplementary radii of
  undocumented origin; results that depend on them carry a caution.

## Data quality flags

Some published binary formation enthalpies used by M6 and M7 are physically implausible. The calculator keeps every
value as published and marks the affected predictions as **Flagged binary data**; see
[Binary Interaction Data](help://binary-data). M7 results outside the domain its authors derived the criterion for
are marked **Extrapolated**.

## Numerical precision

The table rounds values for display. Full-precision values are in **Analysis › Descriptors** (**Full precision**)
and in exported files. Threshold comparisons use the unrounded values.
