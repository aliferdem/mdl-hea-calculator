# Composition Space: Al–Co–Cr–Fe–Ni

Explore the effect of aluminium on CoCrFeNi with a composition space, then extend the space with a second optional
element and look at the same family in weight percent.

## Adding Al to CoCrFeNi

1. Select **Composition space** with the mode switcher.
2. Select Co, Cr, Fe, Ni and Al. Keep **Range basis** at **At. ratio**.
3. Keep the defaults for Co, Cr, Fe and Ni (Min 1.0, Max 1.0, Lock on).
4. For Al, switch **Lock** off and set Min 0.1, Max 0.5, Step 0.1.

The Workload summary reports **6 valid compositions** in 2 element systems: CoCrFeNi (Al absent) and Al0.1CoCrFeNi
to Al0.5CoCrFeNi. The footer reads **Ready**. Select **Calculate**.

In **Analysis › Collection › Plots**, choose a **Line** plot of ΔH<sub>mix</sub> along the Al amount to see the mixing
enthalpy fall as Al is added, or a **Stacked bars** plot to compare the model classes across the run.

The same space with **Range basis › Mass** — Co, Cr, Fe and Ni at 1.0 g, Al optional from 0.1 to 0.5 g — also
contains 6 compositions, but they are different alloys: equal masses, not equal numbers of atoms.

## Two optional elements

Add Mn and switch its Lock off; set Al from 0.05 to 1.5 in steps of 0.05 and Mn from 0.1 to 1.0 in steps of 0.1. The
space now has four element systems — CoCrFeNi, +Al, +Mn and +Al+Mn — and **341 valid compositions**
(1 + 30 + 10 + 300).

## Weight percent: Fe–Cr–Ni

Select Fe, Cr and Ni, choose **Range basis › wt.%**, and in the **All:** row set Min 20, Max 60, Step 10. Only
combinations that add up to 100 wt.% are valid: **15 valid compositions**. With the wt.% defaults (0 to 100, step 10)
the same three elements give 36. Each composition is converted to atomic fractions before calculation, and its wt.%
grid values are kept, so plots can use the wt.% axes.

The same ranges in **at.%** also give 15 and 36 compositions, but different alloys.

## Subsystems only

Select Co, Cr, Fe, Mn and Ni at At. ratio 1.0 and switch **Lock** off in the **All:** row. The space contains every
equiatomic binary, ternary, quaternary and the quinary: **26 valid compositions**. Choose **System size › 4** to keep
only the 5 quaternaries.
