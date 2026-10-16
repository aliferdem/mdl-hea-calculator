# About HEA Calculator

HEA Calculator is a desktop tool for screening multi-component and high-entropy alloy compositions with published
empirical and semi-empirical criteria. It is meant for exploring composition space quickly and consistently before
experiments or more expensive calculations.

## What it calculates

For every composition the calculator reports:

* **Descriptors** — rule-of-mixtures density ρ and melting temperature T<sub>m</sub>, mixing enthalpy
  ΔH<sub>mix</sub>, ideal mixing entropy ΔS<sub>mix</sub>, atomic-size mismatch δ (Guo & Liu radii) and
  δ<sub>CN12</sub> (Kittel radii), valence electron concentration VEC with the FCC/BCC rule, and the quantities of
  each model (Ω, γ, Λ, φ, Φ, ΔH<sub>IM</sub> …). See [Symbols, Parameters and Units](help://symbols).
* **Predictions of eight models** — M1 Yang & Zhang (2012), M2 Guo et al. (2013), M3 Wang et al. (2015), M4 Singh
  et al. (2014), M5 Ye et al. (2015), M6 Troparevsky et al. (2015), M7 Senkov & Miracle (2016) and M8 King et al.
  (2016). See [Phase-Formation Models M1–M8](help://phase-models).

## How it works

Every workflow — a single composition, a composition space, composition expressions and spreadsheet import —
produces plain compositions and passes them to the same calculation engine, so a composition gives the same result
whichever way it was entered. Large batches are generated and calculated in background processes and stored on
disk, so the window stays responsive while hundreds of thousands of compositions are calculated.

Missing data are never replaced by zero: when a model lacks a value it needs, its prediction is **N/A** with the
reason, and every other model is evaluated normally.

## Version, credits and licences

The version, the contributors, the technologies used and the licence information are in **File › About HEA
Calculator**. The scientific sources are listed in [Scientific References](help://references).
