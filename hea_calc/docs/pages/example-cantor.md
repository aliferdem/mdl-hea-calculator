# Equiatomic CoCrFeMnNi

The Cantor alloy is the reference single-phase FCC high-entropy alloy. Every model predicts a solid solution for it;
replacing Mn by Al shows how quickly the models begin to disagree.

## Calculate CoCrFeMnNi

1. In **Single composition**, select Co, Cr, Fe, Mn and Ni; every At. ratio is 1.
2. Select **Calculate**.

| Descriptor | Value | Unit |
|---|---|---|
| ρ | 8.02 | g cm⁻³ |
| T<sub>m</sub> | 1801.20 | K |
| ΔH<sub>mix</sub> | −4.16 | kJ mol⁻¹ |
| ΔS<sub>mix</sub> | 13.38 | J mol⁻¹ K⁻¹ |
| δ (Guo & Liu radii) | 3.27 | % |
| δ<sub>CN12</sub> (Kittel radii) | 0.92 | % |
| Ω | 5.79 | — |
| VEC | 8.00 | — (FCC) |

All eight models predict **SS**. M6 and M7 are evaluated at T = 0.55 × T<sub>m</sub> = 991 K.

Why: ΔH<sub>mix</sub> is small and negative, so Ω = T<sub>m</sub>ΔS<sub>mix</sub>/|ΔH<sub>mix</sub>| is far above
1.1 (M1); δ is well below 6.6 % (M1, M2); and no binary formation enthalpy falls outside the M6 window at 991 K.

## Compare AlCoCrFeNi

Replace Mn by Al: deselect **Mn**, select **Al**, and calculate.

| Descriptor | AlCoCrFeNi |
|---|---|
| ΔH<sub>mix</sub> | −12.32 kJ mol⁻¹ |
| δ | 5.77 % |
| δ<sub>CN12</sub> | 5.25 % |
| Ω | 1.83 |
| VEC | 7.20 (BCC + FCC) |

| Model | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 |
|---|---|---|---|---|---|---|---|---|
| Prediction | SS | MP | SS | SS+IM | MP | IM | IM | MP |

ΔH<sub>mix</sub> is now below the −11.6 kJ mol⁻¹ bound of M2. At T = 0.55 × T<sub>m</sub> = 926 K, the Al–Ni
formation enthalpy (−677 meV atom⁻¹) lies far below the M6 lower bound −TΔS<sub>mix</sub> = −128 meV atom⁻¹, and M7
finds k<sub>1</sub> = 2.54 above k<sub>1</sub><sup>cr</sup> = 1.40: both predict intermetallics. Φ of M8 falls to 0.36,
below 1. M1 and M3 still predict SS because Ω (1.83), δ<sub>CN12</sub> (5.25 %) and γ (1.169) remain within their
limits. Open **Analysis › Models** to see each criterion value against its threshold.

## Partial coverage: CoCrFeNiSi0.5

Enter Co, Cr, Fe and Ni at 1 and Si at 0.5. Before you calculate, the footer warns **Partial model coverage**: M6
and M7 have no Troparevsky formation enthalpy for Co–Si, Cr–Si, Fe–Si and Ni–Si. After calculating, M6 and M7 show
**N/A** with this reason; the other six models are evaluated normally (SS for M1, M3, M4 and M5; MP for M2 and M8).
