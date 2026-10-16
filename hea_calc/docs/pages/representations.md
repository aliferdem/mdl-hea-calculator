# Composition Representations

A composition can be written as atomic ratios, atomic percent, weight percent or masses. Every representation is
converted to atomic fractions before calculation, so the same alloy gives the same result whichever way it is
entered.

## The four representations

| Representation | Label | Meaning | Example: CoCrFeMnNi |
|---|---|---|---|
| Atomic ratio | **At. ratio** | Proportional numbers of atoms; only the ratios matter. 1 : 1 : 1 and 2 : 2 : 2 are the same alloy. | 1 : 1 : 1 : 1 : 1 |
| Atomic percent | **at.%** | Share of atoms, summing to 100. | 20 at.% each |
| Weight percent | **wt.%** | Share of mass, summing to 100, converted with the standard atomic masses. | Co 21.0166, Cr 18.5427, Fe 19.9153, Mn 19.5919, Ni 20.9335 |
| Mass | **Mass** | Grams of each element in a batch of the **Total mass**. | 2 g batch: Co 0.42033, Cr 0.37085, Fe 0.39831, Mn 0.39184, Ni 0.41867 |

Formulas such as Al0.5CoCrFeNi use atomic ratios: 0.5 : 1 : 1 : 1 : 1, which is 11.11 at.% Al and 22.22 at.% of
each other element.

## Conversions

* at.% and wt.% are converted through the atomic weights: x<sub>i</sub> = (w<sub>i</sub>/M<sub>i</sub>) /
  Σ(w<sub>j</sub>/M<sub>j</sub>).
* Mass values are treated like weight percent: only their proportions matter for the composition.
* Converted values are rounded for display — four decimals, five for Mass. Decimal commas are accepted (0,5 = 0.5).

## Total mass

The **Total mass** (in the **Total:** row of Single composition) sets the batch size used for the Mass column. It
must be greater than zero; the default is 2 g. The value you enter is remembered for later sessions and is used in
two places:

* the **Mass** column of Single composition;
* the **Mass** column of the composition table in **Analysis › Overview**, headed with the batch size — for
  example **Mass (2 g batch)** — for every result, whether it came from a single composition, a composition space,
  an expression or an import.

Changing the total mass never changes a descriptor or a prediction; it only rescales the masses.

## Representations in a composition space

A [Composition Space](help://composition-space) can be defined in any of the four representations (its **Range
basis**). at.% and wt.% ranges must add up to 100 for each composition; At. ratio and Mass ranges are proportional,
so a combination proportional to one already generated is the same alloy and is calculated once.
