# System Size and Element Constraints

The number of elements in a composition is its system size N. Every calculated composition has at least two
elements with a non-zero amount. In a composition space, **Lock** and **System size** decide which element systems
are generated.

## Required and optional elements

In **Composition space**, every element row has a **Lock** switch:

* **Lock on** (default) — the element is required and present in every generated composition.
* **Lock off** — the element is optional: systems with and without it are generated.

The calculator forms every combination of the required elements with each subset of the optional elements,
including none. Each combination is an element system. Systems with fewer than two elements are not generated.

*Example.* Co, Cr, Fe and Ni required and Al optional give two systems: Co–Cr–Fe–Ni and Al–Co–Cr–Fe–Ni. With all
five of Co, Cr, Fe, Mn and Ni optional there are 26 systems: 10 binaries, 10 ternaries, 5 quaternaries and the
quinary.

## System size

**System size** (below the composition table) keeps only systems with the chosen numbers of elements. You can select
several values of N; the field then reads, for example, **4, 5**. **All** keeps every size. Only systems that satisfy
the required-element constraints are included: with three required elements, N = 2 produces nothing.

*Example.* All five of Co, Cr, Fe, Mn and Ni optional at an atomic ratio of 1, with System size 4: the five
equiatomic quaternaries.

## Elements present in one composition

Inside a system, every element takes each **positive** value of its range. A value of zero is not used: an optional
element is either absent (another system) or present with a positive amount. In Single composition, an element with
amount zero is left out of the calculation.
