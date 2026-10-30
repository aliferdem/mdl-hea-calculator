# Calculation Audit — HEA Calculator

Scope: every descriptor and phase-prediction model in `hea_calc/core/engine.py`, compared across

* **New** — `hea_calc/core/engine.py` (this audit's result; the single shared engine),
* **Old preview** — `engine.py` of `hea-calculator-preview` before this audit (git `24be036` + uncommitted work),
* **Legacy** — `HEACalculator-2.2.0/src/HEACalculator/core/{thermodynamics,models}.py`,
* **Literature** — PDFs in `Model Sources/` (read independently; conclusions of earlier agents were re-derived, not trusted).

Regression tests: `tests/test_datasets.py`, `tests/test_models_published.py`, `tests/test_engine_behaviour.py`,
`tests/test_workflows.py` (run `.venv/Scripts/python.exe -m pytest -q`).

Units: R = 8.314462618 J mol⁻¹ K⁻¹; 1 meV/atom = 96.4853 J/mol = 0.0964853 kJ/mol. Compositions are normalised
atomic fractions cᵢ (Σcᵢ = 1); zero amounts are dropped; at least two elements are required.

---

## 0. Summary of findings and corrections

| # | Finding | Evidence | Decision |
|---|---|---|---|
| F1 | **Model numbering scrambled** in the old preview (R5 Troparevsky, R6 Senkov–Miracle, R7 Ye). | Literature files `model_5.pdf` = Ye, `model_6.pdf` = Troparevsky, `model_7.pdf` = Senkov & Miracle; legacy uses the same order. | M1 Yang–Zhang, M2 Guo, M3 Wang, M4 Singh, **M5 Ye, M6 Troparevsky, M7 Senkov–Miracle**, M8 King. (The Figma mock-up table was filled with old-preview output; only the column meaning changes.) |
| F2 | **Binary formation-enthalpy dataset was not the published Troparevsky matrix.** The old `binary_formation_enthalpy_data.json` (from `update_miedema.py`, attributed to an unlocatable "Morris et al. 2020 Table 4") differed in 15 cells, incl. sign flips Ti–La (−170 vs +134/+170) and Mo–Zn (+42 vs −42), Ti–Cr −119 (published −372), Fe–Mo −61 (−484), Fe–W −33 (−554). | Published supplement & main-text Fig. 1 (both rendered and read). Troparevsky Table I (FeCoNi+Mo multiphase) is only reproduced with Fe–Mo = −484. Senkov & Miracle Table 1 ΔH_IM: published matrix reproduces **44/45** values exactly; the old data fails 9/45 (e.g. CrNbTiZr −6.27 vs −12.37). Practical check: CoFeMnMoNi (exp. FCC+IM) and CrNbTiZr (exp. BCC+IM) were predicted SS by old M6/M7. | Replaced with the published matrix (upper-triangle rule, §3.3). Old data preserved in `archive/update_miedema.py`. |
| F3 | **Yang & Zhang δ used the wrong radius set.** Old preview used one radius (`atomic_radius`, Guo & Liu 2011) for everything. | Yang & Zhang cite Kittel (CN12 radii). Recomputing their Table 1: Kittel CN12 reproduces 88 % of δ within 0.02 (median error 0.003); Guo–Liu radii median error 0.43. Guo 2013 / Singh 2014 / Guo–Liu 2011 tables are reproduced by Guo–Liu radii (96 %/86 %/96 %). | Added `atomic_radius_cn12` (Kittel Table 9, hand-transcribed, matches legacy for all 70 elements). δ_CN12 used by M1 (and by M8 until F9 removed the δ screen from the M8 criterion); δ (Guo–Liu) by M2, M3, M4, M5. |
| F4 | **King structural term applied to non-transition metals** (e.g. Al–Ni). | Bakker (1998) Part I §5.2 and Part II Eq. 51: the structural term "is only non-zero for a solid solution of two transition metals". King benchmark AlCoCrFeNi ΔG_ss: −34.96 (old) → −33.71 (new) vs −33.89 published. | Structural term restricted to transition-metal pairs with 3 ≤ z ≤ 10. |
| F5 | **Senkov–Miracle returned N/A for ΔH_mix ≥ 0** (old) / used the k₁ ratio regardless of sign (legacy). | Eq. (6) SS condition ΔH_mix − TΔS < ΔH_IM − k₂TΔS is general; Eq. (7)/(8) divide by ΔH_mix assuming ΔH_mix < 0 (inequality flips for ΔH_mix > 0). Authors still report positive-ΔH_mix alloys (CoCrCuFeMn, Cu0.5CoCrFeNi) in Table 1. | Evaluate Eq. (6) directly — identical to k₁ < k₁cr for ΔH_mix < 0, physically correct for ΔH_mix ≥ 0. Reproduces every Table 1 classification of the positive-ΔH_mix alloys. **F9 adds:** the verdict is kept, but any ΔH_mix ≥ 0 result now carries `status="extrapolated"` and an explicit caution, because §1.1 states the derivation's domain. |
| F6 | Default assessment temperature for M6/M7 (old 0.60·Tm, legacy 0.55·Tm). | Troparevsky: experimental T_ann of the known HEAs correspond to 0.53–0.56 Tm and the authors later refer to "T_crit = 0.55 T_M as suggested above"; Senkov & Miracle describe Troparevsky's model as annealing at T_cr ≈ 0.55 Tm. | Default **0.55·Tm**, overridable by an explicit annealing temperature (shared by M6 and M7); the source is reported with each result. |
| F7 | Old preview raised an exception (whole alloy failed) when any ΔH_mix pair was missing. | Requirement: missing data ≠ zero; independent descriptors must still be produced. | Missing binary data → only dependent descriptors/models are N/A with an explicit reason. Tabulated zeros (e.g. Fe–Mn = 0) are values. |
| F8 | Legacy King implementation uses a hand-transcribed interfacial table with errors (Cu-in-Ni 4 vs Bakker +14, Ir-in-Fe −59 vs −38, Ir-in-Cu 64 vs +1, W-in-Fe −6 vs 0, Au-in-Co 25 vs +33, Mo-in-Y −70 vs +114). | Bakker Table A2 pages rendered and read. | New engine computes ΔH_inter from the Miedema equation with Bakker Table A1 parameters; it reproduces Bakker Table A2 within ±2.1 kJ/mol for all 840 TM–TM pairs (test). |
| F9 | **M8 applied a δ ≤ 6.6 % screen that is not part of King's criterion.** The code used `Φ ≥ 1 AND δ_CN12 ≤ 6.6`, and M8 returned `N/A` whenever a Kittel CN12 radius was missing. | King et al. 2016 **§3.1** states the solid-solution region as **Φ ≥ 1 and nothing else**; the δ screen is **§3.4**'s description of how candidate alloys are *generated*. King explicitly keeps NbTiV2Zr — "the only system that has both Φ > 1 and δ > 6.6" — in the success set. An exhaustive scan of 523 204 equimolar 5/6/7-element combinations found 20 systems the AND-term demoted. | M8 is now **Φ ≥ 1 alone**; no radius set is required. `CrMnNbTaW` (Φ 1.467, δ 6.61), `CrMnTiNbTa` (1.425, 6.96) and `CrMnTiVSc` (1.110, 10.00) are `SS`, as King requires. Criterion text in `MODELS["M8"]` updated. Tests: `tests/test_model_boundaries.py::test_m8_*`. |
| F10 | **A threshold decided by IEEE-754 noise.** `CoCrFeNiCu` computes ΔH_mix = 3.200000000000001, one ULP above Guo's printed window edge of 3.2, so the most-cited Cantor-type HEA was reported `MP`. | Yang & Zhang 7.36/FCC, Guo Table 1 `SS`, Singh Λ 12.529 — all treat it as a solid solution. | `engine.THRESHOLD_REL_TOL = 1e-12` **relative**, applied **only to inclusive comparisons** (`_ge`/`_le`). A source printing `>`/`<` keeps an exact comparison, so strictness at the bound still means what it says (Guo −12.2, Wang 1.175, Troparevsky 37 meV/atom). A difference of 0.01 still flips every verdict — asserted in `tests/test_model_boundaries.py`. |
| F11 | **Divergent descriptors were exposed as ±∞.** Ω = Tm·ΔS/|ΔH_mix| became `+inf` for a tabulated 0 kJ/mol pair (Takeuchi & Inoue define H/C/N pairs as exactly 0), which reads as an unusually good solid solution. Same for Λ when δ = 0, φ when S_E = 0 and Φ when ΔG_max = 0. | A vanishing denominator makes a ratio divergent, not large. `math.inf` is not a scientific result class. | All four now return `None` with a dedicated `*_undefined` reason string, and the affected model reports `N/A` carrying that reason. No descriptor is ever infinite — asserted over 3 000+ compositions in `tests/test_model_boundaries.py::test_no_descriptor_is_ever_infinite`. (*2026-10-27, §19: for φ this path was never reached — the S<sub>E</sub> rounding residual at equal radii stayed above the 10⁻¹⁵ test — and M5 did not carry the reason; both corrected.*) |
| F12 | **43 of 435 formation-enthalpy cells lie outside the publication figure's own range and only 5 were flagged; none reached the user.** Fe–Ta −3468, Fe–Nb −2505, Al–Cd −1938 … W–Re −719 meV/atom. FeTa was therefore classified `IM` by M6 from a transcription artefact. | The source is a colour-scaled **figure** (Supplemental Fig. 1, legend ≈ −500…+300). Independently: \|ΔH_mix\| = 4·\|Σ cᵢcⱼΔH(ij)\| ≤ 2·max\|ΔH(ij)\|, and the largest ΔH_mix published anywhere in the eight-model corpus is 29.97 kJ/mol, so a cell above ~1000 meV/atom cannot contribute to any published ΔH_mix. | `_metadata.data_quality` now carries the guard, its justification, the three prose anchors and a `suspect_override` list. **No value was replaced, clamped or interpolated.** `Datasets.formation_suspect_pairs()` derives the flags from metadata; the engine exposes `descriptors["formation_suspect_pairs"]` and marks M6/M7 `status="data_suspect"` with a caution naming the offending cell. A corrected matrix is a pure data swap — asserted by `test_matrix_can_be_replaced_without_touching_model_code`. |
| F13 | **M7 presented an extrapolation as a literature-defined prediction.** §1.1 assumes the relations hold "for HEAs with negative values of ΔH_mix"; the code returned a bare SS/IM for ΔH_mix ≥ 0. | Senkov & Miracle 2016 §1.1. | The verdict is kept (see F5) but ΔH_mix ≥ 0 now yields `status="extrapolated"` plus a caution quoting the paper's domain; ΔH_mix = 0 additionally states that the published k₁/k₁cr form is undefined and only the ΔG form of Eq. (6) can be evaluated. |
| F14 | **M2's intermetallic region was silently unresolved.** Guo Fig. 1 defines three regions; the engine implements two, so M2 can never return `IM`. Six published Guo rows disagree *(2026-10-27, §17.4: three of the six are published IM alloys inside the numeric MG window; the other three are published amorphous alloys outside it)*. | Guo Fig. 1 gives the intermetallic region only graphically — no numeric boundary exists in the source. | **No boundary was invented.** M2 now reports `MP` *and* attaches a caution: outside both published criteria, with an intermetallic region bounded only graphically, so SS / IM / other is not separated here. `MODELS["M2"].criterion` states which signs are project convention. |
| F15 | **Miedema parameters for Ca, Sr, Ba.** Volume coefficient a = 0.04 (the source gives 0.10), and no R/P factor, so M8 was N/A for Ca/Sr/Ba with every transition metal and Ca/Sr/Ba–p-block pairs lacked the hybridisation term (e.g. Ca–Al liquid −9.7 vs Takeuchi & Inoue −20 kJ/mol). | de Boer et al. 1988 (*Cohesion in Metals*) Eq. 2.33, §2.3, Eqs. 2.35–2.36, Fig. 2.28, program Table V-3; reproduces Bakker A3/A4 (144 values) and Takeuchi & Inoue (147 pairs). | Corrected 2026-10-27 (§16): a = 0.10; R/P factor 0.4 on the d-type side; P unchanged. Every pair without Ca/Sr/Ba unchanged. |

Items flagged for user review are marked **⚑ REVIEW**.

---

## 1. Elemental data (`data/periodic_table.json`)

| Property | Source | Verification |
|---|---|---|
| `atomic_radius` (pm) | Guo & Liu, Prog. Nat. Sci.: Mater. Int. 21 (2011) Table 1 — the radius *family*; 73 elements printed at 0.1 pm (now in Model Sources, "Guo and Liu - 2011 - Phase stability…pdf"). *Provenance per element corrected 2026-10-27 (§17.1):* 13 stored values equal the Guo & Liu printed value; 47 equal Zhang et al. (2014) Table 1 at 0.01 pm (the same set at higher precision, rounding to Guo & Liu); 9 carry extra digits found in neither table (Cd, Er, Eu, Ho, Ir, Lu, Os, Ru, Tb; all round to Guo & Liu); **4 (Pm, Po, Pa, U) were Kittel CN12 values that contradicted both tables** (181/176/163/156 vs Guo & Liu 163/153/161/142) — *corrected 2026-10-27 to the Guo & Liu printed values (§18); they now belong to the first group (Pm, Po, Pa) and the Zhang group (U).* *Since 2026-10-27 (§20, F2) all 73 hold the printed 0.1 pm values; the 17 Zhang-precision and 9 untraced values were rounded to the print (≤ 0.05 pm).* | Reproduces published δ of Guo 2013 T1 (183/186 within 0.05), Singh 2014 T1 (68/76), Guo–Liu 2011 T2–3 (96 % within 0.02); at the printed 0.1 pm precision far more rows reproduce to the last digit (Guo 2013 δ 81–86/93 vs 25/93 stored; §17.1). The 45-element supplementary list (`_metadata.atomic_radius_supplementary`) holds 35 elements with a value of undocumented origin and 10 with none (At, Rn, Cm–Lr); the engine warns and the periodic table shows ⚠ for M2–M5. **⚑ REVIEW** origin of supplementary radii (the 0.01 pm digits: resolved by §20) (investigation plan: `docs/analysis-redesign/ATOMIC_RADIUS_INVESTIGATION_PLAN_2026-10-27.md`; its item 1, Pm/Po/Pa/U, is done — §18). Tests: `test_atomic_radius_follows_guo_liu_table1_within_printed_precision`, `test_atomic_radius_equals_guo_liu_table1_exactly` (§20). |
| `atomic_radius_cn12` (pm) | Kittel, ISSP 8th ed., Ch. 3 Table 9 "Radii of ions in 12-coordinated metals". | Hand-transcribed from the rendered page; identical to legacy for 70 elements. Range/valence entries: Ce 1.71–1.82 → 182, Eu²⁺ 204, Yb²⁺ 194, Pu 1.58–1.64 → 161. |
| `work_function_phi`, `n_ws`, `molar_volume` | Bakker (1998) Table A1. | Parsed and compared for all elements — identical except Eu/Yb (divalent parameter set used; the book also lists trivalent). |
| `bulk_modulus`, `shear_modulus` (10¹⁰ Pa) | Bakker Table A5. | Identical (the PDF text layer is offset by one row; the stored values match the correctly aligned table). |
| `melting_point` (K), `atomic_weight`, `nvalence` | Standard tabulations (pre-existing). | Yang & Zhang Tm differ by a few K (their elemental Tm set); Ω tests use 2 % tolerance. |

## 2. Binary data

### 2.1 Liquid mixing enthalpy ΔH_AB^mix (`data/mixing_enthalpy_data.json`)
* Source: Takeuchi & Inoue, Mater. Trans. 46 (2005) 2817 (`46_2817.pdf`), Miedema model, equiatomic liquid, kJ/mol. 73 elements, 2628 pairs, complete.
* Old preview, `mixing_data.json` and legacy `mixing_enthalpy.json` are identical (2628 pairs, 0 differences).
* Verification: ΔH_mix recomputed for Yang & Zhang T1 (95 % within 0.02 kJ/mol) and Guo 2013 T1 (99 %).
* Zero entries (e.g. Fe–Mn, Co–Ni, Mo–V) are tabulated values. Missing pairs → `None`.

### 2.2 Binary formation enthalpy ΔH_f (`data/binary_formation_enthalpy_data.json`)
* Source: Troparevsky et al., PRX 5 (2015) 011041, Supplemental Appendix A (30 × 30) and Fig. 1 (18 × 18), meV/atom.
* **Asymmetric published entries** (row value ≠ column value) — 7 pairs:
  Al–Ag (−254/−76), Ti–La (134/170), V–Cu (13/54), Cr–Cd (133/113), Mn–Mo (−138/−136), Co–Nb (−178/−150), Nb–Ir (−628/−830).
  Rule: use the value in the row of the element that comes first in the published order (upper triangle).
  Evidence: Senkov & Miracle's CoFeMnMoNi ΔH_IM (−16.63) requires Mn–Mo = −138 (upper). M6 results list these pairs as a caution.
  **⚑ REVIEW** V–Cu (13 vs 54) can change M6 for V+Cu alloys (upper bound 37 meV/atom).
* **Suspicious published values kept as published** (authors' own predictions depend on them): Fe–Nb −2505, Fe–Ta −3468, Fe–Mo −484, Fe–W −554 (σ/μ phases the authors took from Ansara et al. CALPHAD — magnitudes suggest a units/decimal error in the publication), Al–Cd −1938. Laves values Ti–Cr −372, Cr–Zr −150, Cr–Nb −47, Cr–Hf −362 from Chen et al. (2005). **⚑ REVIEW** if a corrected matrix from the authors becomes available.
* Re pairs Ti–Re, V–Re, Nb–Re, Ta–Re are referenced to the solid solution (bold blue in Fig. 1), as published.

---

## 3. Descriptors

| Descriptor | Equation | Units / data | Old preview | Legacy | Decision / test |
|---|---|---|---|---|---|
| ΔS_mix | −R Σ cᵢ ln cᵢ | J mol⁻¹ K⁻¹ | same | same | `test_equiatomic_basic_descriptors` |
| ΔH_mix | Σ_{i<j} 4 cᵢcⱼ ΔH_ij^mix (Yang & Zhang Eq. 2) | kJ/mol; Takeuchi 2005 | same, but raised on missing pair | NaN on missing pair | N/A + reason on missing pair (F7); `test_missing_mixing_pair_*`, published-table tests |
| T_m | Σ cᵢ T_m,i (YZ Eq. 6) | K | same | `ceil()` applied (not in literature) | no rounding |
| ρ | Σ cᵢMᵢ / Σ cᵢVᵢ (rule of mixtures) | g cm⁻³; M, Miedema V | same | atomic volume | descriptor only |
| VEC, Cryst. Str. | Σ cᵢ VECᵢ; FCC if VEC ≥ 8.0, BCC if < 6.87, else BCC+FCC (Guo et al., J. Appl. Phys. 109 (2011) 103505) | — | same | same | `test_equiatomic_basic_descriptors` |
| δ | 100 √Σcᵢ(1 − rᵢ/r̄)², r̄ = Σcᵢrᵢ | %; Guo–Liu radii | same radii for all models | Guo–Liu | used by M2–M5; Guo/Singh table tests |
| δ_CN12 | same equation | %; Kittel CN12 | **missing** | CN12 for M1 | added (F3); `test_yang_zhang_table1_*` |
| Ω | T_m ΔS_mix / \|ΔH_mix\| (YZ Eq. 5); undefined if ΔH_mix = 0: `omega` = None with `omega_undefined`, M1 N/A (`na_kind` undefined) — F11 (*corrected 2026-10-27, §17; read "∞" before*) | — | same | same | `test_yang_zhang_omega_examples`, `test_binary_and_physical_zero_mixing`, `test_model_boundaries.py::test_no_descriptor_is_ever_infinite` |
| γ | ω_S/ω_L, ω = 1 − √[((r + r̄)² − r̄²)/(r + r̄)²] with r_S, r_L (Wang Eqs. 2–3) | — ; Guo–Liu radii (paper does not name its radii; same group as Guo 2013, whose δ it compares with) | same (variable names swapped but equivalent) | CN12 radii | Guo–Liu. Radius choice is not stated by the authors but is reproduction-supported (§15.1, §17.2: 4 Wang rows exact in δ and γ with Guo & Liu at 0.1 pm, 0 with any other set). `test_wang_hume_rothery_limit` |
| Λ | ΔS_mix / δ² (Singh; δ in %) | J mol⁻¹ K⁻¹ | same | same | `test_singh_2014_table1_*` |
| S_E | Mansoori–Carnahan–Starling–Leland hard-sphere excess entropy, dᵢ = 2rᵢ, averaged over ξ = 0.68 (bcc) and 0.74 (fcc) (Ye Scr. Mater. 2015 text; Ye Intermetallics 2015 App.) | J mol⁻¹ K⁻¹; Guo–Liu radii | same | same | 171/174 Ye |S_E| values within 5 %; `test_ye_excess_entropy`; identical diameters give S_E = 0 exactly (§19, `test_m5_excess_entropy_limits.py`) |
| φ (Ye) | (S_c − S_H)/\|S_E\|, S_H = \|ΔH_mix\|/T_m, \|S_E\| averaged over ξ = 0.68 / 0.74 (Scr. Mater. main text) | — | same | same | FeCrCuNiCo 371 (paper 369), FeCrCuNiAl 11.4 (paper 11). The Scripta SI prints per-packing columns under two other conventions (§17.3); the main-text φ is kept |
| ΔH_f,min/max | extremes of Troparevsky ΔH_ij over all pairs | meV/atom | Morris data | published (lower-triangle mix) | published matrix (F2) |
| −TΔS_mix | lower bound, T × ΔS_mix / 96.4853 | meV/atom | 0.60 Tm default | 0.55 Tm | 0.55 Tm default (F6); "−138.7 meV/atom at 1000 K" test |
| ΔH_IM | Σ_{i<j} 4cᵢcⱼ ΔH_ij^IM × 0.0964853 (Senkov Eq. 9) | kJ/mol | Morris data | published | 44/45 Senkov values; `test_senkov_2016_dhim_*` |
| k₁, k₁cr | k₁ = ΔH_IM/ΔH_mix; k₁cr = 1 + (1 − k₂)TΔS_mix/\|ΔH_mix\|, k₂ = 0.6 (Eq. 7) | — | same | same | `test_senkov_k1cr_definition` (CoCrFeNi at 573 K → 1.70) |
| ΔH_ss (King) | Σᵢ Σ_{k≠i} cᵢ (c_k/(1 − cᵢ)) ΔH_ik^form(ss) (Eq. S8); binary ΔH^form(ss) = chem + elastic + struct (S1–S7, Bakker Eqs. 51–54) evaluated at the pair ratio cᵢ:c_k | kJ/mol; Bakker A1/A5 | struct for all pairs | table-based, directional struct | struct TM–TM only (F4) |
| ΔH_inter(A in B) | V_A^{2/3}[1 + a(φ_A − φ_B)] / ½(n_A^{−1/3} + n_B^{−1/3}) × [−P(Δφ*)² + Q(Δn_ws^{1/3})² − R]; P = 14.2 (TM–TM) / 10.7 (non-TM–non-TM) / 12.35 (mixed), Ca/Sr/Ba counting as non-TM; Q = 9.4P; R = P·(R/P)_d(R/P)_p only between a d-type metal (TM, or Ca/Sr/Ba with 0.4) and a non-transition metal; a = 0.14/0.10/0.07/0.04 (de Boer Eq. 2.33; Ca/Sr/Ba 0.10) | kJ/mol A | same | Bakker table (with errors) | equation; reproduces Bakker A2 ±2.1 (F8), Bakker A3/A4 Ca/Sr/Ba ≤ 3.6 and Mg/Al ≤ 2.6, de Boer V-4.02 238/240 ≤ 2.0 (§16) |
| ΔH_elastic(A in B) | 2K_AG_B(W_A − W_B)²/(3K_AW_B + 4G_BW_A), W_A = V_A + α(φ_A − φ_B)/n_A, W_B = V_B − α(φ_A − φ_B)/n_B, α = 1.5V_A^{2/3}/(n_A^{−1/3} + n_B^{−1/3}) (Bakker Eqs. 14, 28; King S6) | ×10 kJ/mol for K,G in 10¹⁰ Pa | same | same form | sign of ΔV follows Bakker (A expands if φ_A > φ_B); King's printed "V − ΔV" is inconsistent with Bakker's derivation |
| ΔH_int (ordered) | ½[c_A f_B^A ΔH_inter(A in B) + c_B f_A^B ΔH_inter(B in A)], f_B^A = c_B^s[1 + 8(c_A^s c_B^s)²] (Bakker Eq. 9; King S9–S10) | kJ/mol | same | sign taken from directional sum | Benchmarks: CrNi −10.03 (paper −10.08), CuFe +19.32 (19.14), AlNi −47.5 (−47.33). King's printed S9 uses c_A^s instead of c_A; difference < 0.4 kJ/mol, Bakker's form kept. |
| ΔG_ss, ΔG_max, Φ | ΔG_ss = ΔH_ss − T_mΔS_mix; ΔG_max = ⌊N/2⌋ × ΔH_int of the largest-magnitude pair; Φ = ΔG_ss/(−\|ΔG_max\|) | kJ/mol | same | same | CoCrFeNi Φ 1.18 (1.16), CoCrCuFeNi 0.55 (0.55), AlCoCrFeNi 0.36 (0.36) |

---

## 4. Models

### M1 — Yang & Zhang (2012), `model_1.pdf`
* Equation/criterion: SS if **Ω ≥ 1.1 and δ ≤ 6.6 %** (text: "Ω ≥ 1.1 and δ ≤ 6.6% … criteria"); otherwise MP (intermetallics and/or segregation).
* Variables: Ω (T_m, ΔS_mix, ΔH_mix — Takeuchi data, Ref. 39), δ with **Kittel radii (Ref. 41)**.
* Boundaries inclusive: Table 1 lists CoCrFeNiAl3 (Ω = 1.10, BCC) as SS.
* Old preview: δ with Guo–Liu radii. Legacy: CN12 ✓, output "Intermetallic" otherwise.
* Decision: CN12 radii, inclusive, outside → MP. Tests: `test_yang_zhang_*`, `test_threshold_boundaries_inclusive_exclusive`.
* Known table inconsistencies (exceptions in tests, 20/266 values): e.g. CoCrFeNiCuAl0.3 ΔH_mix printed 1.56 (Guo prints 0.16, we compute 0.157); CuNi δ 1.63 (we compute 1.19); MoCrFeNiCu δ 2.92 (4.10); TiCoCrNiCuAlY0.5 δ 7.53 (11.11).

### M2 — Guo et al. (2013), `model_2.pdf`
* SS: **δ ≤ 6.6 % and −11.6 ≤ ΔH_mix ≤ 3.2 kJ/mol**; amorphous (MG): **δ > 6.4 % and ΔH_mix < −12.2 kJ/mol**; otherwise MP ("intermetallic compounds can form in the intermediate conditions").
* Radii: Guo–Liu (reproduces Guo T1). ΔH_mix: Takeuchi.
* Boundaries: text writes "< ~0.066" and "−11.6 < ΔH_mix < 3.2", but Table 1 lists SS alloys exactly at ΔH_mix = 3.20 (FeCoNiCrCu) and −11.60 (Al2CoCrCu0.5FeNi) → inclusive SS boundaries; amorphous boundaries strict as written.
* Old preview: same thresholds, MP outside. Legacy: strict, no MG class, "Intermetallic" outside.
* Tests: `test_guo_2013_*`, boundary test.

### M3 — Wang et al. (2015), `model_3.pdf`
* SS if **γ < 1.175** (strict, "c < 1.175"), otherwise MP (multiphase with intermetallics).
* Radii: not stated; Guo–Liu used (see γ above). Legacy uses CN12 → different labels for e.g. CoCrFeNiTi0.5. **⚑ REVIEW**.
  Evidence added in §15: Guo–Liu radii reproduce Wang's printed γ for 10 of 11 superalloys with reconstructed
  compositions (Kittel CN12: 0 of 11) and Wang's "six solid solutions with δ > 0.06" statement (CN12: one). The
  choice is now evidence-supported; it is still not stated by the authors.
  *Added 2026-10-27 (§17.2):* with the superalloy compositions documented in the same group's Ye et al. (2015) SI
  Table S2, Hastelloy B, Inconel 600, Nimonic 75 and Incoloy 800H reproduce Wang's δ **and** γ to the last printed
  digit with Guo & Liu radii at 0.1 pm — the strongest evidence available.  No other set gives an exact δ + γ row,
  including the stored 0.01 pm values (γ within 6 × 10⁻⁴ there, no verdict affected).  The ⚑ REVIEW now concerns the
  stored precision and provenance of the radius set (§1), not the choice of family.

### M4 — Singh et al. (2014), `model_4.pdf`
* Λ = ΔS_mix/δ²; **SS if Λ > 0.96; SS+IM if 0.24 ≤ Λ ≤ 0.96** (Table 2 "[0.24, 0.96]", "DSS + compound(s)"); **IM if Λ < 0.24**.
* Old preview: same. Legacy: middle class called "Multiple Phases" — the paper's class is DSS + compound → **SS+IM**.
* Tests: Singh T1 δ/Λ (68/76; exceptions are table values not reproducible from the paper's own radii), boundary test.

### M5 — Ye et al. (2015), `model_5.pdf`
* φ = (S_c − S_H)/|S_E|, S_H = |ΔH_mix|/T_m, S_E averaged over fcc and bcc packing. **SS if φ ≥ 20** (φ_c ≈ 20; the boundary itself is not specified, inclusive used), otherwise MP.
* Old preview: same equation (labelled R7). Legacy: same.
* Tests: main-text examples (369, 11), Table S1 classification, Intermetallics |S_E| table.
* *Added 2026-10-27 (§17.3):* the Scripta SI (Model Sources "Ye et al supplements.pdf"; it is **not** the
  Intermetallics 59 SI, so the 174 |S_E| reference values remain unverified against their own source) prints φ at
  ξ = 0.68 and 0.74 under two conventions, neither of which is the main-text φ the engine implements.  Classification
  agrees for 41/41 Table S1 rows that do not straddle φ = 20.
* *Note 2026-10-28 (investigation only; nothing changed):* the Intermetallics 59 SI is now in Model Sources
  (`1-s2.0-S0966979514003239-mmc1.docx`).
  * The 174 |S_E| reference rows equal it exactly (0 transcription differences).
  * The Appendix equations match the implementation term by term.
  * 159/174 rows reproduce exactly in both packing columns with the printed Guo & Liu radii.
  * S-005, S-042 and S-166 are internally inconsistent rows of the source.
  * Report: `docs/analysis-redesign/YE_INTERMETALLICS_SOURCE_VERIFICATION_2026-10-28.md`.
  * The "remain unverified" statement above is superseded.
  * *Applied 2026-10-28 (approved; text only, no value, tolerance or expectation changed):*
    * the provenance note of `published_tables.YE_2015_INTERMETALLICS_EXCESS_ENTROPY`;
    * the `location` and `reproducibility` of the 174 `M5-YE15I-S-*` catalogue cases, in the JSON and in its
      generator;
    * the three `KNOWN_DISCREPANCIES` reasons, now the source-row findings;
    * the comment of `test_models_published.YE_SE_EXCEPTIONS` (the same three rows).

### M6 — Troparevsky et al. (2015), `model_6.pdf` + `HEAs_Sup_012515.pdf`
* Criterion: single phase if **−T·ΔS_mix < ΔH_f(i,j) < 37 meV/atom for every pair** (strict; Table II "−138 < ΔH_f < 37").
* Labels: lower bound violated → **IM** (a binary compound too stable — precipitation); only upper bound violated → **MP** (immiscibility/phase separation); otherwise SS. Old preview used IM/PS/MP; PS is not a supported category.
* T: annealing temperature if given, else **0.55·T_m** (F6). Data: published matrix (F2).
* Tests: Table I FeCoNi (T = 1000 K) and NbMoTa (T = 1673 K) additions; text values (−115, −138.7, −193 Mo–Ta).

### M7 — Senkov & Miracle (2016), `model_7.pdf`
* SS if **ΔH_mix − TΔS_mix < ΔH_IM − k₂TΔS_mix**, k₂ = 0.6 (Eq. 6; equals k₁ < k₁cr(T) for ΔH_mix < 0, Eq. 8); otherwise **IM**.
* ΔH_IM from the Troparevsky matrix (Ref. 16, Eq. 9); ΔH_mix from Takeuchi (Ref. 12). T as in M6.
* Note: Senkov's printed ΔH_mix for several Al/V/Zr alloys differ from Takeuchi-based values that reproduce Yang & Zhang and Guo; ΔH_IM is reproduced (44/45; Al0.3NbTa0.8Ti1.4V0.2Zr1.3 printed −5.62, computed −6.69 — likely a table typo).
* Tests: `test_senkov_*`, `test_senkov_miracle_equation_6_both_signs`.

### M8 — King et al. (2016), `model_8.pdf` + supplement docx
* Φ = ΔG_ss/(−|ΔG_max|) at T_m. Criterion (King §3.1): **SS if Φ ≥ 1** (inclusive), otherwise MP. No radius is
  used. The **δ ≤ 6.6 %** condition (δ with the Goldschmidt CN12 radius, paper Eq. 5) is King §3.4's filter for
  *generating* candidate alloys, not part of the solid-solution criterion; King keeps NbTiV2Zr (Φ > 1, δ > 6.6) in
  the success set (F9). Before F9 this section described the criterion as "Φ ≥ 1 and δ ≤ 6.6 %"; corrected in §14.
* Data requirements: Miedema parameters and classification for every element, and R/P factors for mixed
  d-type / non-transition pairs. `Engine.model_support` reports exactly these (§14). Since §16 every element with
  Miedema parameters has its factor (Ca, Sr, Ba: 0.4, de Boer Fig. 2.28), so M8 is available for all 57.
* Implementation details and decisions in §3 (ΔH_inter equation, structural term TM–TM only, ordered compound averaging, ⌊N/2⌋ scaling).
* King used Bakker-tabulated ΔH_inter "where available, otherwise Zhang's Miedema Calculator (Mied89)"; the equation reproduces Bakker's table within rounding, so results are equivalent.
* Elements without Miedema parameters or classification (e.g. Nd and most lanthanides) → N/A. **⚑ REVIEW** whether rare earths should be added with Miedema's transition-metal treatment.
* Tests: `test_king_2016_worked_examples` (ΔG_ss within 0.4 kJ/mol, Φ within 0.03, pairs CrNi/CuFe/AlNi), `test_structural_term_only_for_transition_pairs`, `test_miedema_formula_reproduces_bakker_table_a2`; Ca/Sr/Ba and the non-transition path (§16): `test_miedema_reproduces_bakker_a3_a4_*`, `test_miedema_classification_ca_sr_ba`, `test_miedema_volume_coefficient`, `test_miedema_reproduces_de_boer_table_v4_02`, `tests/test_miedema_takeuchi_inoue.py`.

---

## 5. Three-way comparison (default temperature 0.55·T_m; legacy 0.55·T_m; old 0.60·T_m)

Labels M1…M8 (old preview re-mapped to literature numbering):

| Alloy | New | Old preview | Legacy | Experiment / note |
|---|---|---|---|---|
| CoCrFeNi | SS ×8 | SS ×8 | SS ×8 | FCC |
| AlCoCrFeNi | SS MP SS SS+IM MP IM IM MP | same | SS IM SS MP MP MP IM MP | BCC + B2 |
| CoCrCuFeNi | SS MP SS SS SS MP SS MP | M6 PS, M7 N/A | SS IM SS SS SS MP SS MP | FCC + Cu-rich FCC |
| HfNbTaTiZr | SS SS SS SS+IM MP MP SS SS | M6 PS, M7 N/A | … M6 MP | BCC |
| CoFeMnMoNi | … M6 **IM**, M7 **IM** | M6 SS, M7 SS | M6 MP, M7 IM | FCC + IM (Otto 2013) |
| CrNbTiZr | … M6 **IM**, M7 **IM** | M6 SS, M7 SS | M6 MP, M7 IM | BCC + Laves (Senkov T1) |
| CoCrFeNiTi0.5 | … M3 MP, M7 **IM** | M7 SS | M3 IM, M7 IM | FCC + IM |
| AlCoCuFeNiSi | SS MG MP SS+IM MP N/A N/A MP | same | SS IM SS MP MP N/A N/A MP | Si not in Troparevsky set |

## 6. Missing data vs physical zero

* `Datasets.mixing_enthalpy`/`formation_enthalpy` return `None` when a pair is not tabulated; `0.0` is a value.
* Missing ΔH_mix → ΔH_mix, Ω, φ, M1, M2, M5, M7 = N/A (reason given); δ, γ, Λ, M3, M4, M6, M8 still computed.
* Missing Troparevsky pair → ΔH_f, ΔH_IM, M6, M7 = N/A.
* Missing Miedema data (parameters or classification), or a missing R/P factor for a d-type / non-transition
  pair → King descriptors and M8 = N/A (since §16 no element with Miedema parameters lacks a factor; until then this
  hit Ca, Sr, Ba with a transition metal). Missing CN12 radius → δ_CN12 and M1 = N/A; M8 is unaffected (F9, §14).
* Supplementary (non-Guo–Liu) radius → values computed, warning on the result, caution on M2–M5, ⚠ on the periodic table.
  *(2026-10-27, §17.1: Pm, Po, Pa and U hold Kittel CN12 values, not Guo & Liu values, but are not on the
  supplementary list, so they carry no warning — open data-provenance item.  Corrected in §18: they now hold the
  Guo & Liu values and correctly carry no warning.)*
* Tests: `test_missing_*`, `test_binary_and_physical_zero_mixing`.

## 7. Composition generation (workflow semantics, no physics)

All workflows produce plain `{element: amount}` dictionaries that the single engine normalises.

* **Single composition** — the active input column (At. ratio, at.%, wt.%, Mass) is converted to atomic
  fractions; the other columns are derived from those fractions (`core/composition.py`), so switching the
  input column never changes the composition. *Set equal* sets equal values in the active column
  (ratio 1, percentages 100/n, mass total/n); *Normalize* rescales at.% or wt.% to 100 % and refuses blanks,
  invalid/negative values and zero totals.
* **Composition space** (formerly "Composition sweep"; `core/generation.py: iter_space`, Figma 278:17008) —
  each element has Min / Max / Step in the chosen *Range basis*. *At. ratio* and *Mass*: every element takes each
  positive grid value independently (cartesian product); proportional duplicates are removed (e.g. 1:1 and 2:2) —
  masses are proportional amounts exactly like ratios. *at.%* and *wt.%*: only combinations summing to exactly
  100 are valid (integer arithmetic, no float drift); wt.% and mass grid points are converted to atomic fractions
  with `composition.to_fractions` (standard atomic weights) before they reach the engine (section 10). *Lock* on = required (always present, value > 0);
  off = optional — every subset of optional elements forms a system ("combinations"), filtered by
  *System size*. Points with fewer than two elements are never generated. Reproduces the Figma example
  (Cr/Mn/Ni 0.5–1.5, Fe 0.8–1.2, Co 1.0, step 0.1 → 6,655 compositions; 4 optional elements and sizes ≥ 4
  → 15 combinations).
* **Expression mode** (`core/expression.py`) — one or more expression blocks (separated by blank lines)
  with lowercase variables; groups are normalised (HEA convention: `(FeCoNi)90Al10` = 30/30/30/10 at.%).
  Variable grids are combined per block; combinations giving negative amounts or fewer than two elements
  are skipped and reported; duplicates across blocks are removed. The parser contains no scientific
  calculations.
* **Spreadsheet import** (`core/spreadsheet.py`) — a formula column or one column per element; malformed
  numbers, negative amounts, unknown element columns and rows with < 2 elements are reported per row.

---

## 8. Independent validator reconciliation (independent audit applied)

Baseline commit `cced89b`. Findings F9–F14 above came from an independent re-derivation of the
eight publications from `Model Sources/`, cross-checked against the literature *and* against a
from-scratch recomputation using the same binary tables — never against the implementation's own
output. The independent harness is kept outside the project test suite on purpose:
the independent validator script (read-only, 799 checks).

| | before | after |
|---|---|---|
| Project test suite | 140 passed | **203 passed** |
| Validator PASS | 594 | **600** |
| Validator FAIL | 56 | **8** |
| Validator UNSUPPORTED | 5 | 5 |
| Validator ERROR | 0 | 0 |

The 8 remaining validator failures are all deliberate and documented, not outstanding work:

1. **6 × M2 intermetallic region** (F14) — the source bounds it only graphically.
2. **1 × Φ accuracy** — `Co43Cr1Fe7Ni49` computes 9.288 against a published 8.93 (+4.0 %), while
   King's three equimolar worked examples match within 1–2 %. Documented accuracy envelope, not a
   coding error; the constants are not retuned to chase one table.
3. **1 × |ΔH_f| ≤ 700 meV/atom** — F12. The cells are still in the dataset because **no replacement
   value may be invented**; they are flagged instead.
4. **1 × Yang & Zhang melting-point column** — reproduces 6/133 against any modern table, because
   their Ω column implies Cr ≈ 2133 K, Ti ≈ 1946 K, Co ≈ 1770 K. Ω is Tm-insensitive. **Do not
   retrofit one publication's melting-point column.**

*Reconciliation note (2026-10-27, §17.4; the table and list above are kept as recorded).*  The validator has a fourth
non-failing status the table omits: **DOC** (documented discrepancy, 186 checks), so 799 = 600 PASS + 8 FAIL +
5 UNSUPPORTED + 186 DOC + 0 ERROR.  The list above adds up to 9, not 8: item 4 (Yang & Zhang melting points) is
recorded by the validator as DOC, not FAIL.  The 8 FAILs are 6 M2 verdicts, the King Φ accuracy case and the
|ΔH<sub>f</sub>| range check.  Of the 6 M2 verdicts only 3 concern the intermetallic region (CoCrFeNiTi,
AlCoCrFeNiTi1.5, ZrTiVCuNiBe: published IM, numeric criteria give MG); the other 3 are published amorphous alloys
outside Guo's numeric MG window (Cu0.5NiAlCoCrFeSi, CoCrCuFeNiZr0.6, CoCrCuFeNiZr0.8: MP).  Re-run read-only
(`--no-write`) on 2026-10-27 with the current engine, after §16: identical counts and identical failing cases.

### Two earlier claims in the independent audit that were corrected

* **Senkov k₁ᶜʳ 45/45 → 24/45.** The 21 non-reproducing rows are not a data defect: Senkov's own
  printed ΔH_mix column disagrees with the Takeuchi–Inoue binary table that every other model uses
  (`Al0.5CoCrCuFeNi`: Senkov −3.40, table −1.521, while Yang & Zhang and Guo both print −1.52).
  k₁ᶜʳ depends only on ΔS, |ΔH_mix| and T_A, never on the damaged formation matrix.
* **Yang & Zhang Table 2 ΔH_mix 33/33 → 30/33.** Three bulk-metallic-glass rows differ; the app
  matches the binary table in each case.

### Threshold comparison — the rule, stated once

`engine.THRESHOLD_REL_TOL = 1e-12`, relative, applied through `_ge`/`_le` to **inclusive**
comparisons only. A source that prints `≥` or `≤` states an inclusive rule, so representation noise
must not exclude a value equal to the bound. A source that prints `<` or `>` states a strict rule,
and that strictness is meaningful at the bound, so those comparisons are exact. Both halves are
pinned from both sides in `tests/test_model_boundaries.py`.

---

## 9. Analysis redesign (2026-10-14): what changed in `core/engine.py` and the result store

No equation, constant, threshold, dataset value, radius set, parser convention or reason text changed.
The scientific validator (the independent validator script) gives the same
600 PASS / 8 FAIL / 5 UNSUPPORTED / 0 ERROR as before (the 8 documented failures of section 8).

| Change | Kind | Why |
|---|---|---|
| `ModelOutcome.na_kind` (`missing_data` / `undefined`; `error` for a composition the engine rejects) | classification of an existing N/A, set at the site that already wrote its reason | Collection analysis must count "not available — missing data" apart from "not available — undefined" (zero denominator: Ω, Λ, φ, Φ) and from not-evaluable results; missing data is never zero (section 6). M5: a missing ΔH<sub>mix</sub> or radius is `missing_data`; an S<sub>E</sub> that cannot be evaluated or is zero is `undefined` |
| `Engine.formation_pairs(composition)` | read-only dataset accessor (no calculation) | Model details draws the M6 pair window from the same Troparevsky values the engine compares; the UI may not look datasets up itself (AGENTS.md section 3) |
| Results store schema 2: `status_M*`, `na_kind_M*`, `family_id` / `families`, `n_elements`, run `app_version` / `engine_version` / `dataset_ids` | storage of values the engine already produced | evidence status survives storage, so distributions never flatten N/A, extrapolated and flagged verdicts into one state |

Invariant relied on by the store (tested in `tests/test_analysis_schema.py`): an N/A verdict carries a reason and
never a caution; an evaluated verdict carries a caution at most and never a reason, so the one stored note per
model is unambiguous.

Open scientific questions recorded by the Analysis audit (`docs/analysis-redesign/AUDIT_WORK_STATUS.md` items 1-7:
Troparevsky suspect rule and causal flagging, M3 radius set, formula-group convention, density volume source,
supplementary radii) are **unchanged**; Analysis displays CURRENT engine behaviour and its existing caution texts.

---

## 10. Release reconciliation (2026-10-16): workflow and presentation changes around the engine

No equation, constant, threshold, dataset value, radius set or reason text changed. The scientific validator
(the independent validator script) still gives 600 PASS / 8 FAIL / 5 UNSUPPORTED / 0 ERROR (the
8 documented failures of section 8), before and after these changes.

| Change | Kind | Why |
|---|---|---|
| `Engine.model_coverage(elements)` | read-only accessor: evaluates the equiatomic alloy of the element set and returns the reason of every model that is N/A for *missing data* | Composition setup warns "Partial model coverage" before calculating; the rule comes from the engine itself, so nothing is re-implemented in the UI (AGENTS.md section 3). Data availability depends only on the element set, not on the amounts |
| Composition space range bases *wt.%* and *Mass* (`generation.SUM_UNITS = ("at", "wt")`, `recipes.SweepRecipe.atomic`) | workflow: enumeration and unit conversion | wt.% counts like at.% (sum = 100 on the grid); mass counts like At. ratio (proportional duplicates removed). Every grid point is converted with `composition.to_fractions` - the same conversion Single composition uses - and stored with its design coordinates in the entered basis; `available_axes` derives at.% axes from them in SQL. Tests: `tests/test_space_units.py` (the four bases agree for CoCrFeMnNi) |
| Analysis Mass column "Mass (*g* g batch)" (`report.composition_report_html(batch_mass=…)`) | presentation: `composition.from_fractions(..., "mass", total_mass)` of the stored atomic fractions | the persisted Total mass preference applies to every result type; it never enters the engine |
| Descriptor names "Size mismatch — Guo & Liu radii" (δ) / "Size mismatch — Kittel CN12 radii" (δ<sub>CN12</sub>) | label text in `core/analysis/metrics.py` | the two size mismatches use different radius sets (section 1); the labels say which, so neither is privileged in Statistics |
| `t_assess` definition: "from Calculation settings" (was "from Settings") | label text | the menu item is *Calculation settings…* |
| Engine fingerprint `daf5fcf9f33b` → `32c617b4c92d` | consequence of the `model_coverage` addition to `core/engine.py` | `provenance.engine_version()` hashes the engine sources; any source edit changes the ID even without a numerical change. Runs record the ID they were calculated with |

The Help documentation (`hea_calc/docs/pages/`) quotes engine values only where `tests/test_help.py` recomputes
them with the current engine (CoCrFeMnNi descriptors and verdicts, AlCoCrFeNi verdicts, the CoCrFeNiSi0.5 N/A reason,
every composition-space and expression count, workload constants); its descriptor reference table is generated
from the descriptor registry, and its reference list from `core/references.py`, so neither can drift from the code.

---

## 11. Final Figma implementation (2026-10-25): expression grammar and result order

No equation, constant, threshold, dataset value, radius set, model eligibility rule or reason text changed; the
engine sources are untouched.  The changes are workflow semantics around the engine:

| Change | Kind | Why / evidence |
|---|---|---|
| Strict bounds in range lines: `0 < x < 1`, mixed `0 < x <= 1` (`expression_doc.DECL`, `VariableRange.min_inclusive` / `max_inclusive`) | grammar: which grid points a variable takes | `<` was rejected before; it is now read as written and never normalised to `<=`.  The discretisation is defined on the closed interval (``step`` from the lower bound, or ``points`` evenly spaced including both ends) and a strict bound removes that endpoint (within 1e-12 relative; the grid is exact decimal).  So `0 < x < 1, step=0.1` = 0.1…0.9 (9 values) and `0 < x < 1, points=11` = 9 values.  Counting, the combination limit, resource estimates, generation and run metadata all use `VariableRange.values()`, so they agree.  A range left empty by its bounds is an error.  Tests: `tests/test_figma_final.py::test_strict_and_inclusive_bounds` and neighbours |
| Preview default of a strict range: the first grid value (was the lower bound) | preview only | an excluded lower bound is not a value of the range; identical for inclusive ranges |
| Run metadata of an expression range: a dict (`VariableRange.to_meta`, `min`, `max`, `step`, `points`, bounds); `range_from_meta` still reads the earlier list form | storage format (no schema change) | stored runs stay readable; Analysis' fixed-variable choices now use the engine grid (they did not handle `points` ranges before) |
| Automatic range declarations `0 <= v <= 1, step=0.1` (`expression_doc.plan_declarations`) | editor convenience | a declaration is text the user can edit; it changes nothing until it is parsed, and it is the same default the error message already suggested |
| Results table order without a column sort: newest first (`ResultView.newest_first`, set by the table) | presentation | the dataset order (`ResultView.iterate`, exports, Analysis collections) stays the calculation order; result ids, runs and design coordinates are unchanged |

## 12. Stabilization pass (2026-10-25, second round): faster evaluation paths, identical numbers

No equation, constant, threshold, dataset value, radius set, model eligibility rule or reason text changed; the
engine sources are untouched.  Three evaluation paths were made faster; each produces bit-identical numbers and
each is pinned by a regression test that compares with the previous path using `==` on every float:

| Change | Kind | Why / evidence |
|---|---|---|
| Expression evaluation compiled per block (`core/expression_compile.py`): the expression tree is turned once into a Python function with the same operations in the same order (`evaluate_positive` stays the reference) | performance | The tree walk was the per-combination cost of Expression mode.  Same IEEE-754 operations and order, so every amount is identical; skipped / invalid combinations are the same.  Tests: `tests/test_stabilization.py::test_compiled_evaluator_is_bit_identical_to_the_tree_evaluator` (12 expressions × 400 random and edge environments, incl. division by zero, negative and tiny amounts, nested groups) |
| Expression jobs without duplicates skip the serial duplicate plan (`CalculationJob._run_expression_direct`), using the editor's Parse count of the same document (`ExpressionRecipe.counts`) | performance, workflow | With zero duplicates the plan keeps every valid combination, so the direct path stores exactly the same compositions, names, design coordinates and order.  With duplicates (or no count) the plan path runs as before.  Test: `test_direct_expression_jobs_store_exactly_what_the_plan_stores` |
| Collection statistics run one query per metric, in parallel (`AnalysisController.request_statistics`, `queries.merge_statistics`) | performance | Every per-metric number is computed by the same SQL a multi-metric call runs for that metric (its own column aggregates over the same rows in the same order); the merge equals `statistics(metrics)` exactly, for the exact and the binned quartile paths.  Test: `test_per_metric_statistics_merge_equals_the_multi_metric_query` |
| Plot colour scales (`ui/analysis/plot.py`: `sequential`, `sequential_mark`, `category_colors`) | presentation only | Low / high ends of the blue ramp matched the panel colour and categorical cells used a per-process string hash; colours now come from one deterministic assignment and keep contrast.  No plotted value changed |
| Elements panel property readout regrouped (thermophysical / atomic / electronic / elastic), symbols with source tooltips (`r` = Guo & Liu 2011 Table 1, `r_CN12` = Kittel CN12) | presentation only | The two radius sets stay separate datasets, shown side by side, never merged; values are the dataset values (moduli 10^10 Pa shown in GPa as before) |

---

## 13. Final stabilization follow-up (2026-10-26): Step size | Points, property documentation

No equation, constant, threshold, dataset value, radius set, model eligibility rule or reason text changed; the engine
sources and `data/*.json` are untouched.

| Change | Kind | Why / evidence |
|---|---|---|
| Composition space: the Step column heading (Figma: Dropdown, Style=Inline) chooses **Step size** or **Points** per run (`ElementRange.points`, `core/generation.grid` / `grid_scale`) | workflow (grid definition) | *Points* = n evenly spaced values including Min and Max (n ≥ 2 when Max > Min; Min = Max gives 1).  The grid is exact: the integer scale is 10^decimals × lcm(points − 1) of all ranges, so thirds (4 points on 0–1) are exact and at.% / wt.% sums of exactly 100 stay integer comparisons — no float drift.  A Points grid equivalent to a step grid (0–1, step 0.25 ↔ 5 points) yields the identical compositions, order and count.  Switching converts a value only when an exact equivalent exists (`step_to_points` / `points_to_step`, Decimal); otherwise the field is cleared and flagged — a step is never reinterpreted as a count or vice versa.  Run metadata stores `points` next to the effective step.  Tests: `tests/test_stabilization.py::test_points_grids_equal_the_equivalent_step_grids_and_counts_agree`, `test_points_mode_is_exact_for_non_decimal_steps_and_validates_counts`, `test_switching_step_and_points_converts_only_exact_equivalents`, `test_points_mode_count_and_calculation_match_the_step_mode` |
| New Documentation page *Element Property Definitions* (`docs/pages/element-properties.md`), linked from a Toggletip in the Elements panel | documentation | Every value the panel shows: symbol, name, meaning, unit, convention, source (from `_metadata` and this audit's §1), use.  Coverage numbers are tested against the dataset (`test_element_property_definitions_page_documents_every_displayed_value`) |
| *Elemental Property Data*: "45 elements … carry supplementary radii" corrected to "35 of them carry supplementary radii; At, Rn and Cm–Lr have no radius" | documentation correction | `Datasets.prop(el, "atomic_radius")` is None for those 10 elements (counted by the test above) |
| Elemental density `ρ` (Elements panel only) documented as *source not recorded*; gases are stored as g L⁻¹ at 0 °C, 1 atm (N 1.251, O 1.429) under the panel's g cm⁻³ label | documentation of an existing dataset convention | Open item, **not changed**: the dataset records no source for `density` and no descriptor or model uses it (the alloy ρ is Σc·M / Σc·V with Miedema volumes).  Changing the values or the label needs the source first |
| Sampled scatter markers are filled discs like RAW (hollow rings dropped) | presentation only | A sample is identified by its tag, Toggletip and legend counts; no plotted value or sample changed |

---

## 14. M8 documentation and model-support correction (2026-10-26)

No equation, constant, threshold, dataset value, radius set, eligibility rule of a calculation or reason text of a
result changed.  `Engine.calculate` is untouched; only the per-element *availability* report `Engine.model_support`
(the periodic-table "Model support" indicator) and this audit's text changed.  Full record:
`docs/analysis-redesign/SCIENTIFIC_PARITY_REVALIDATION_2026-10-26.md`.

| Change | Kind | Why / evidence |
|---|---|---|
| §4 M8, §6 and F3 now state the criterion as **Φ ≥ 1** with no radius requirement | documentation correction | The text still described the pre-F9 criterion "Φ ≥ 1 and δ ≤ 6.6 %". F9 (King §3.1 vs §3.4) and the code (`engine.py` M8 branch, `_ge(phi_king, 1.0)`) use Φ ≥ 1 alone; `tests/test_model_boundaries.py::test_m8_*` already pinned it |
| `model_support(el)["M8"]` no longer requires a Kittel CN12 radius | availability metadata | M8 reads no radius.  P has Miedema data but no CN12 radius: the indicator said "none" while M8 evaluates with all 56 Miedema partners (EVID-M8-002) |
| `model_support(el)["M8"]` = `pair` for an element without an R/P factor (Ca, Sr, Ba) | availability metadata | `_pqr` needs both R/P factors for a transition / non-transition pair and raises otherwise, so M8 is N/A for Ca/Sr/Ba with each of the 30 transition metals (and evaluates with non-transition partners); the indicator said "ok".  Tightened, not relaxed: the R/P factor is a genuine requirement.  *(Superseded in §16: Ca, Sr, Ba now have the de Boer factor 0.4 and report "ok".)* |

Verification: an exhaustive binary check (`docs/analysis-redesign/scripts/m8_support_check.py`, every element ×
every Miedema-available partner) found 292 support/evaluation contradictions before and 0 after.  The parity run of
261 alloys gives bit-identical descriptor values, verdicts, statuses, N/A kinds, reasons and cautions before and
after.  Tests: `tests/test_m8_support.py`.

Open, not changed (recorded for a decision): Miedema volume coefficient *a* for Ca, Sr, Ba (0.04 here; Miedema's
divalent value is 0.10 — not verifiable from the local Bakker text layer); R/P factors for Ca, Sr, Ba (absent, so
M8 is N/A with transition metals; the legacy program substitutes 0); `model_support` for M3 and M4 reports "warn"
for the ten elements with no Guo & Liu radius (At, Rn, Cm–Lr) although both models are N/A for them (M2 and M5
correctly report "none").  *(Resolved in §15; the Ca/Sr/Ba items in §16.)*

---

## 15. Publication-based validation, M3 radius evidence, availability and wording corrections (2026-10-26)

No equation, constant, threshold, dataset value, radius set, model eligibility rule or verdict changed.  The parity
run of 261 alloys before and after these changes differs in one reason text only (CaFeNi, M8, below); every value,
label, status and N/A kind is identical.  Full records: `docs/analysis-redesign/PUBLICATION_VALIDATION_REPORT_2026-10-26.md`,
`PUBLISHED_MODEL_BENCHMARKS.md`, `M3_ATOMIC_RADIUS_INVESTIGATION.md`.

| Change | Kind | Why / evidence |
|---|---|---|
| `Engine.model_support`: M2–M5 report **none** for an element with no radius at all (At, Rn, Cm–Lr) | availability metadata | The engine returns N/A ("Atomic radius unavailable.") for M3/M4 with these elements, but the indicator said "warn" because they are also on the supplementary list.  Exhaustive check of all 6 903 binaries × 8 models (`scripts/model_support_check.py`): 2 250 contradictions before (M3 1 125, M4 1 125), 0 after.  M2/M5 already said "none" (no Takeuchi data).  Test: `tests/test_model_support_consistency.py` |
| M8 N/A text for a missing R/P factor: "Not evaluable: no Miedema R/P (hybridisation) factor for the Ca–Fe pair (transition / non-transition)." (was "Miedema parameters unavailable for Miedema R/P factor unavailable for Ca–Fe.") | wording of an existing reason | Same label, `na_kind` (missing data) and behaviour; the exception text of `_pqr` and the sentence around it were merged.  The element-level message is unchanged |
| M8 described as using CN12 radii in user-facing text: `ui/widgets/element_panel.py` (tooltip, docstring), `core/results.py` (column tooltip), `core/analysis/metrics.py` (descriptor text), Help `elemental-data.md`, `element-properties.md`; `data/periodic_table.json` `_metadata.properties.atomic_radius_cn12` | documentation / metadata text | M8 uses no radius (F9, §14).  Element values in `periodic_table.json` are untouched (verified key by key against HEAD) |
| Help `phase-models.md` (M3) and `elemental-data.md`: the Guo & Liu choice for M3 is described as supported by reproduction, not by an authors' statement | documentation | Evidence below |

### 15.1 M3 radius set — evidence (resolves the ⚑ REVIEW of §3/§4 as far as the sources allow)

Wang et al. name no radius table and give no compositions for their 83 superalloys.  Compositions of 11 alloys were
reconstructed from manufacturer / distributor data sheets and sampled over their whole specification ranges with the
paper's stated rule (elements > 1 at.%); γ was recomputed independently of the engine from Eqs. (1)–(3) with each
candidate radius set (`scripts/m3_radius_investigation.py`).  Within 5 × 10⁻⁴: Guo & Liu radii at 0.1 pm precision
10/11, at the stored 0.01 pm precision 9/11, Kittel ½ nearest-neighbour distance (Ch. 1, Table 4) 5/11, Kittel CN12
(Ch. 3, Table 9; the legacy choice) 0/11.  With the Guo et al. (2013) Table 1 alloys, Guo & Liu radii give exactly
the six solid solutions with δ > 0.06 the paper reports (CN12: 1).  Decision unchanged (Guo & Liu); the remaining
uncertainty is the authors' exact compositions and radius precision.

### 15.2 Findings recorded, not changed

* **Senkov & Miracle Table 1**: with the authors' own printed ΔH<sub>mix</sub>, Eq. (7) reproduces their k₁<sup>cr</sup>
  in 33/45 rows exactly (remaining: last-digit rounding and 8 rows whose printed Ω or k₁<sup>cr</sup> are internally
  inconsistent — CrMo<sub>0.5</sub>NbTa<sub>0.5</sub>TiZr, CrNbTiVZr and CrNbTiZr violate k₁<sup>cr</sup> = 1 + 0.4 Ω of
  their own table).  The engine's k₁<sup>cr</sup> differs because Senkov's printed ΔH<sub>mix</sub> is not the
  Takeuchi & Inoue value he cites (up to 7 kJ/mol for Al-containing refractory alloys).  Two M7 verdict
  disagreements with the paper (CrMo<sub>0.5</sub>NbTa<sub>0.5</sub>TiZr, CrNbTiVZr) rest on those inconsistent rows.
* **Guo et al. (2013) Table 1, Ti<sub>2.5</sub>CrCuFeCoNi**: the printed δ and ΔH<sub>mix</sub> are those of
  Ti<sub>2</sub>CrCuFeCoNi.
* **Yang & Zhang Table 1**: 22 printed δ<sub>CN12</sub>/ΔH<sub>mix</sub> values in 20 rows are not reproducible from
  the formula and the cited data; all 20 rows were checked against the rendered pages (printed so).  The PDF text layer of this table and of
  Senkov's Table 1 is misaligned and must not be used for transcription.
* **Miedema parameters for Ca, Sr, Ba**: volume coefficient *a* (0.04 here; Miedema's divalent class is 0.10) and R/P
  factors (absent) remain unverified — *Cohesion in Metals* in Model Sources is an image scan and Bakker's text layer
  does not contain the tables.  *(Verified from the rendered scan and corrected in §16.)*

---

## 16. Miedema parameters for Ca, Sr and Ba (2026-10-27, finding F15)

Evidence and the full reasoning: `docs/analysis-redesign/MIEDEMA_CA_SR_BA_CORRECTION_PROPOSAL_2026-10-26.md`
(script `docs/analysis-redesign/scripts/miedema_ca_sr_ba_rules.py`; transcriptions in
`docs/analysis-redesign/data/source-reconciliation-2026-10-26/`).

**Sources (de Boer, Boom, Mattens, Miedema & Niessen, *Cohesion in Metals*, 1988; image scan, read from renderings).**

| Item | Book p. | Content |
|---|---|---|
| Eq. 2.33 | 45 | a = 0.14 alkaline, **0.10 divalent**, 0.07 noble and trivalent, 0.04 all other metals |
| §2.3 | 45 | "alloys of two transition metals" include the divalent d-type metals Ca, Sr, Ba, Eu, Yb |
| Eqs. 2.35–2.36 | 45–46 | P = 14.2 for two metals of valence > 2, 10.7 for two mono-/divalent metals, 12.35 for one of each |
| Fig. 2.28 | 66 | R/P = factor (transition block) × factor (non-transition block); the transition block lists **Ca, Sr, Ba = 0.4** |
| Table V-3 | 718–719 | program: `detr` (R class) = transition set + Ca, Sr, Ba (indices 55–57 of Table V-1.3); R = 0 if both or neither are `detr` |
| Tables V-4.01/4.02 | 720–721 | liquid ΔH<sup>inter</sup> of alkali / polyvalent non-transition pairs; **no Ca, Sr, Ba** (V-4.02 is printed with rows = solute) |

**Change (`core/engine.py`).**

* `_MIED_A_010` += Ca, Sr, Ba (a 0.04 → 0.10, Eq. 2.33).
* New `_MIED_R_DIVALENT_D = {Ca, Sr, Ba: 0.4}`.  `_pqr`: P unchanged (Ca/Sr/Ba stay non-transition, so 12.35 with a
  transition metal and 10.7 otherwise); R is taken between a d-type metal (transition, or Ca/Sr/Ba) and a non-transition
  metal only: R = 0 for Ca/Sr/Ba with transition metals and with each other, R/P = 0.4·R<sub>X</sub> with non-transition
  metals (e.g. Ca–Al 0.76).
* `_r_factor_available` includes Ca, Sr, Ba, so `model_support(el)["M8"]` is "ok" for them (was "pair").
* Unchanged: elemental data, structural term (TM–TM only), elastic term, ordering factor, M8 criterion.

**Not adopted, with reasons.** The printed program line for P (`… detr(a) equiv detr(b) then 12.35/1.15 …`) would give
P = 10.74 for Ca/Sr/Ba with transition metals; it contradicts the book's own Tables V-4.03 ff. (via Bakker A3/A4: rms
19–26 kJ/mol with a = 0.10) and Eqs. 2.35–2.36, and is taken as a misprint of `detp` **[INFER]**.  Takeuchi & Inoue's Ba /
non-transition rows fit a factor 0.5 better than the printed 0.4 (Ca and Sr rows fit 0.4); the printed factor is kept.

**Verification (expected values printed in the sources; none from the engine).**

| Oracle | Result |
|---|---|
| Bakker A3/A4, Ca/Sr/Ba with 24 TMs, 48 values each | rms 1.76 / 1.80 / 1.11, max 3.0 / 3.5 / 2.4 kJ/mol (were N/A).  With de Boer's printed n<sub>ws</sub><sup>1/3</sup>, V<sup>2/3</sup> for Ca/Sr/Ba all 144 are within 1.4: the residual is the 2-decimal n<sub>ws</sub> of Bakker A1, not the rule |
| Bakker A3/A4, Mg and Al (calibration, unchanged path) | max 1.2 / 2.5 kJ/mol |
| de Boer Table V-4.02 (non-transition pairs, unchanged path) | 238/240 within 2.0 kJ/mol; Be in As (+2 printed, +21 calc) and Sb in Cd (−1, −11) printed so |
| Takeuchi & Inoue, equiatomic liquid (Eq. 2.39 R<sub>liq</sub> = 0.73 R), Ca/Sr/Ba with 30 TMs | max 1.2 / 1.2 / 1.1 kJ/mol |
| Takeuchi & Inoue, Ca/Sr with the 21 other metallic partners | max 1.7 / 1.3 kJ/mol (Ca–Al −19.7 vs −20; before: −9.7) |
| Takeuchi & Inoue, Ba with 19 non-transition metals | mean +2.0, max 4.9 kJ/mol — known discrepancy (kept visible by a test) |
| Every ordered Miedema pair without Ca/Sr/Ba (2862) | bit-identical before and after |
| `m8_support_check.py` | 57 "ok", 0 "pair", 0 support/evaluation contradictions |

**Effect.** M8 is now evaluated for Ca/Sr/Ba with transition metals (90 pairs were N/A).  Ca/Sr/Ba–p-block
interfacial enthalpies become about twice as negative (Ca in Al −50.5 → −111.0 kJ/mol), which lowers Φ for Ca–Zn/Ca–Al
alloys (CaMgZn 0.721 → 0.569, MP; Ca65Mg15Zn20 1.250 → 1.024, SS; CaMgAl 0.971 → 0.582, MP).  No published M8/King
value involves Ca, Sr or Ba, so no alloy-level benchmark exists.

**Tests.** New: `tests/test_datasets.py::test_miedema_reproduces_bakker_a3_a4_alkaline_earth` (|Δ| ≤ 4.0, rms ≤ 2.0),
`…_calibration_rows` (Mg, Al ≤ 3.0), `test_miedema_classification_ca_sr_ba` (P and R/P of 12 pairs, exact),
`test_miedema_volume_coefficient`, `test_miedema_reproduces_de_boer_table_v4_02` (≤ 2.0 plus the 2 printed outliers);
`tests/test_miedema_takeuchi_inoue.py` (test-side de Boer liquid formula; Ca/Sr/Ba–TM and Ca/Sr–other ≤ 2.0, Ba
known discrepancy).  Reference files: `tests/reference/bakker_table_A3_A4.json`, `tests/reference/de_boer_table_V4_02.json`.
Replaced behaviour tests (they pinned the former N/A): `test_m8_support.py::test_missing_r_over_p_factor_is_reported_as_a_partner_dependency`
→ `test_alkaline_earth_r_over_p_factor_makes_m8_available_with_every_partner`;
`test_model_support_consistency.py::test_missing_r_over_p_factor_message_is_readable_and_behaviour_unchanged` →
`test_alkaline_earth_with_transition_metals_evaluates_and_missing_data_message_is_unchanged`.  The CaMgAl entry of
`test_m8_support.py::PINNED` (values pinned before §14) was removed, not re-pinned with engine output.
Negative control: with the former constants, 19 of the new tests fail.

**Open (not changed).** Help text (`hea_calc/docs/pages/model-coverage.md` lines 34 and 51, "Ca, Sr and Ba only without
transition metals") still describes the former behaviour — to be revised separately *(done in §16.1)*; n<sub>ws</sub>
precision of Bakker A1 vs de Boer V-1.3 (all elements); Table V-4.01 (alkali pairs: 81/160 within 2.0, max 7.2) not
investigated.

### 16.1 Post-implementation verification and documentation (2026-10-27)

No numerical change.  Script: `docs/analysis-redesign/scripts/ca_sr_ba_impact.py`, output
`docs/analysis-redesign/data/ca-sr-ba-correction-2026-10-27/impact.json`.

**Code review.** The §16 diff of `engine.py` is three edits: `_MIED_A_010` (+ Ca, Sr, Ba), `_MIED_R_DIVALENT_D` with
the R class in `_pqr` (P computed exactly as before), and `_r_factor_available`.  No other Miedema constant changed.

**Old vs new engine over 11 950 compositions.** The pre-§16 rule is restored in a subclass and accepted because it
reproduces the recorded CaMgAl value (Φ = 0.9710296979039487, `parity_pre_fix.json`) bit for bit.

| Set | Compositions | Result |
|---|---|---|
| without Ca/Sr/Ba (parity 59 + sample 200, benchmark catalogue 537, random 3–5-component 3000) | 3 796 | identical in every descriptor, label, status, N/A kind and reason |
| with Ca/Sr/Ba: binaries (5 ratios × 56 partners × 3), equiatomic ternaries (4 293), random multicomponent (3 000), named/benchmark/parity (21) | 8 154 | M1–M7 and every non-King descriptor identical; only M8 changes |

M8 changes: 6 907 compositions go from N/A to evaluated (6 252 MP, 655 SS); **21 change verdict** among those
evaluated before (18 SS → MP, 3 MP → SS), all through the Ca/Sr/Ba–p-block term or a:

* binaries: Ca0.5Al0.5 (1.002 → 0.835), Ca0.1Al0.9, Ca0.75Tl0.25, Sr0.1C0.9, Ba0.1C0.9 (SS → MP); Ba0.75Al0.25
  (0.993 → 1.003), Ba0.9Ge0.1, Sr0.9Si0.1 (MP → SS);
* ternaries: BaAlBe, BaAlMg, BaBZn, BaBeZn, BaLiMg, CaBGa, CaBSi, CaLiMg, SrAlMg, SrBeZn, SrLiMg (SS → MP);
* named: Ca60Mg15Zn25 (1.113 → 0.927) and Sr60Mg18Zn22 (1.102 → 0.907), SS → MP.  Ca65Mg15Zn20 stays SS
  (1.250 → 1.024); CaMgAl stays MP (0.971 → 0.582).

113 compositions now lie within |Φ − 1| < 0.05 (31 of them evaluated before).  No random multicomponent alloy that
was evaluated before changed its verdict.  The two published Mg-alloy compositions with Ca or Sr (Ye S-092, S-093) go
from N/A to MP; no published M8 value exists for them.

**Tests by kind.**

| Kind | Tests |
|---|---|
| Direct comparison with independently transcribed published values (engine output vs printed numbers) | `test_miedema_reproduces_bakker_a3_a4_alkaline_earth`, `…_calibration_rows`, `test_miedema_reproduces_de_boer_table_v4_02`, `test_miedema_formula_reproduces_bakker_table_a2` |
| Printed values through a test-side formula fed with the engine's classification (`_pqr`, `_volume_coefficient`) and elemental data: tests the classification, not the formula | `tests/test_miedema_takeuchi_inoue.py` |
| Source rules typed into the test (no engine value involved) | `test_miedema_classification_ca_sr_ba`, `test_miedema_volume_coefficient` |
| Analytically independent re-derivation (rules typed from the source, King chain written out; elemental data shared) — anchored on the recorded pre-correction CaMgAl value; replaces the removed CaMgAl pin | `tests/test_m8_alkaline_earth_independent.py` (11 alloys incl. CaMgAl, Ca65Mg15Zn20, CaFe, Al85Ca10Ni5) |
| Implementation consistency / behaviour (no scientific oracle) | `test_alkaline_earth_r_over_p_factor_makes_m8_available_with_every_partner`, `test_alkaline_earth_with_transition_metals_evaluates_and_missing_data_message_is_unchanged`, `test_m8_support_and_evaluation_agree_for_every_miedema_pair`, `test_partner_set_is_the_expected_one` |

Partial circularity, stated: the Takeuchi & Inoue and independent-King tests read the same elemental dataset as the
engine (Bakker A1/A5 values, themselves printed); tolerances of the published-value tests (4.0, 2.0) were set after
the residuals were known, with the n<sub>ws</sub>-rounding explanation of §16.  Negative controls: with the pre-§16
constants 19 of the published/rule tests and 11 of the independent re-derivation tests fail.

**Documentation.** `hea_calc/docs/pages/model-coverage.md` (M8 coverage: 57 elements; N/A condition; a paragraph on
the Ca/Sr/Ba classification and that availability is not validation), `binary-data.md` (Bakker A3/A4 agreement),
`hea_calc/core/references.py` (new data reference [14], de Boer et al. 1988, appended so [1]–[13] keep their numbers).
`docs/analysis-redesign/MODEL_SUPPORT_HELP_CONTENT.md` (design draft) annotated as superseded, not rewritten;
`docs/analysis-redesign/data/coverage.json` is a dated snapshot and was left as it is.

Final verification results (2026-10-27): full suite 1352 passed, 7 skipped (the 7 are native-window tests that run only
with `HEA_NATIVE_TESTS=1`; not run); independent validator unchanged (§17.4).  Remaining limitations: §17.6.

---

## 17. Audit consolidation against the 2026-10-26/27 primary-source findings (2026-10-27)

No equation, constant, threshold, dataset value, radius, model eligibility rule, test expectation or engine source
changed.  This section reconciles the audit text with `docs/analysis-redesign/SOURCE_RECONCILIATION_REPORT_2026-10-26.md`
and §16.  Corrections in §0–§6 (which describe current behaviour) are marked "(2026-10-27, §17)"; the historical
sections §8–§16 received dated notes only.

### 17.0 Inconsistencies found

| # | Where | Inconsistency | Kind | Action |
|---|---|---|---|---|
| 1 | §1 `atomic_radius` | "Guo & Liu Table 1 (not in Model Sources)"; "45 elements … carry supplementary values"; precision and per-element provenance not described | Documentation **and** an open data-provenance problem (Pm/Po/Pa/U; unsourced digits; supplementary origin) | Text corrected (§17.1); data unchanged; investigation plan written |
| 2 | §3 Ω | "∞ if ΔH<sub>mix</sub> = 0" — the engine has returned None with `omega_undefined` and M1 N/A (undefined) since F11 | Documentation only | Corrected |
| 3 | §3 γ, §4 M3 | ⚑ REVIEW "radius choice is inferred" did not reflect the exact Wang reproductions | Documentation; the residual scientific question is the stored precision, not the family | Updated (§17.2) |
| 4 | §3 φ, §4 M5 | Nothing on the Scripta SI or its φ conventions; the "Intermetallics \|S<sub>E</sub>\| table" source is still absent | Documentation; the conventions are an open interpretation question with no effect on the implemented φ | Added (§17.3) |
| 5 | §8 Independent validator | Counts omit the DOC status (799 ≠ 600 + 8 + 5); the "8 failures" list sums to 9; the 6 M2 failures are not all intermetallic-region cases | Documentation only | Dated note in §8, F14 annotated (§17.4) |
| 6 | §6 | "Supplementary radius → warning" is accurate for flagged elements, but 4 non-Guo-&-Liu values are unflagged | Open data-provenance problem | Noted; no change *(corrected in §18)* |
| 7 | §16 | Final test result and limitation summary not recorded | Documentation only | Added after §16.1 and in §17.6 |

### 17.1 `atomic_radius` provenance [SOURCE + CALC]

Comparison of `data/periodic_table.json` with Guo & Liu (2011) Table 1 (73 elements, 0.1 pm) and Zhang et al. (2014)
Table 1 (48 elements, 0.01 pm); transcriptions in `docs/analysis-redesign/data/source-reconciliation-2026-10-26/`:

| Group | n | Elements |
|---|---:|---|
| Equal to the Guo & Liu printed value, element not in Zhang's table | 13 | — |
| Equal to Zhang 2014 at 0.01 pm (rounds to Guo & Liu; Zr 160.25 vs G&L 160.3) | 47 | Zhang's 48 except U |
| Extra digits found in neither table (round to Guo & Liu) | 9 | Cd, Er, Eu, Ho, Ir, Lu, Os, Ru, Tb |
| Kittel CN12 values contradicting both tables, not flagged | 4 | Pm 181 (G&L 163), Po 176 (153), Pa 163 (161), U 156 (142) *(as found; corrected in §18 — the groups above then hold 16 and 48)* |
| Supplementary list, value of undocumented origin | 35 | `_metadata.atomic_radius_supplementary` minus the 10 below |
| No radius | 10 | At, Rn, Cm, Bk, Cf, Es, Fm, Md, No, Lr |

Published-value reproduction by radius precision (independent harness `docs/analysis-redesign/scripts/radius_precision_rerun.py`;
exact = within half a unit of the printed last digit; within = δ ±0.05, Λ ±2 %, |S<sub>E</sub>| ±5 %):

| Quantity | n | Stored (0.01 pm): exact / within | Guo & Liu printed (0.1 pm): exact / within | Kittel CN12: exact / within |
|---|---:|---|---|---|
| Guo 2013 δ (M2) | 93 | 25 / 91 | 81 / 91 | 1 / 5 |
| Singh 2014 δ (M4) | 76 | 26 / 68 | 56 / 68 | 3 / 4 |
| Singh 2014 Λ (M4) | 76 | 6 / 68 | 26 / 67 | 1 / 2 |
| Ye 2015 \|S<sub>E</sub>\| (M5) | 174 | 16 / 170 | 75 / 171 | 1 / 47 |

[CALC] The legacy HEACalculator 2.2.0 (`elements.json`) holds exactly the Guo & Liu printed values for all 73 elements
(including Pm 163, Po 153, Pa 161, U 142 — an independent check of the transcription) and no value for the 35
supplementary elements.  [SOURCE: git] The current column (0.01 pm digits, the four Kittel values, the supplementary
values) entered this project in commit `cced89b`; the initial commit held a different generic set (e.g. Fe 127, U 175)
and no generating script or source note exists in the repository.

The published tables were computed at 0.1 pm; the stored 0.01 pm values change last digits and leave tolerance-level
agreement unchanged.  They can still decide a verdict at a threshold: Guo 2013 Table 1 FeCoNiCrCuAl3 prints δ = 6.61
(Guo's criterion: MP; observed phase SS); the stored radii give δ = 6.598 (M2 SS), printed-precision radii 6.610 (MP).
Scoping estimate: `docs/analysis-redesign/data/atomic-radius-2026-10-27/radius_scoping.json`.  The `periodic_table.json` metadata still describes the whole column as
"Guo & Liu Table 1"; that text is part of the dataset file and was not edited here.

### 17.2 M3 radius conclusion

[CALC] With Ye et al. (2015) SI Table S2 compositions, Wang's printed δ **and** γ reproduce to the last digit for
Hastelloy B, Inconel 600, Nimonic 75 and Incoloy 800H with Guo & Liu radii at 0.1 pm (also with the stored values
rounded to 0.1 pm); no row does with the stored 0.01 pm values, Kittel CN12 or Kittel ½ n.n.  [SOURCE] Wang names no
radius source.  [INFER] The authors used the Guo & Liu set at its printed precision.  Decision unchanged (Guo & Liu);
§15.1's data-sheet result (10/11 within 5 × 10⁻⁴) stands.  The earlier inference that Zhang 2008's Kittel citation
meant the nearest-neighbour table is superseded: Zhang 2008 δ is reproduced 6/6 by Kittel CN12 (this concerns M1's
δ<sub>CN12</sub>, not γ).

### 17.3 Ye (2015) supplementary φ conventions

* [SOURCE] "Ye et al supplements.pdf" is the SI of **Scr. Mater. 104 (2015) 53**: Table S1 (43 cast HEAs: S<sub>c</sub>,
  φ at ξ = 0.68 and 0.74, phase) and Table S2 (BMGs, conventional alloys, 43 superalloys).  No S<sub>E</sub> column;
  it is not the Intermetallics 59 SI.
* [CALC] S<sub>c</sub>: Table S1 42/43 (FeCoNiCrCuAl0.3 prints the Al0.8 value), Table S2 superalloys 43/43.
* [RECON] Table S2 columns fit single-packing φ(ξ) = (S<sub>c</sub> − S<sub>H</sub>)/|S<sub>E</sub>(ξ)|: 42/43 within 2 %
  (Guo & Liu radii; Kittel CN12 6/43).  The SI does not print this formula.
* [RECON] Table S1 columns fit φ<sub>ξ</sub> = S<sub>c</sub>/|S̄<sub>E</sub>| − S<sub>H</sub>/|S<sub>E</sub>(ξ)|: 39/43
  within 1 % (printed Guo & Liu radii); back-solving each printed pair returns the alloy's S<sub>c</sub> and
  |ΔH<sub>mix</sub>|.  [INFER] Neither paper states or motivates this form; it is a reconstruction, not a verified
  formula.
* [SOURCE] The main text defines φ with the averaged |S<sub>E</sub>|; the engine implements that.  Its φ lies between
  the two S1 columns; classification agrees for 41/41 rows that do not straddle φ = 20.  No change.
* The three |S<sub>E</sub>| known discrepancies (S-005, S-042, S-166) are characterised in the report (composition
  mix-ups, interstitial C) but not confirmed; their source table is still absent.

### 17.4 Independent validator

Recorded results (2026-10-17) and a read-only re-run (2026-10-27, `run_validation.py --no-write`, current engine):
799 checks = 600 PASS + 8 FAIL + 5 UNSUPPORTED + 186 DOC + 0 ERROR, with identical cases.  FAILs: 6 M2 verdicts (3
published IM alloys in the numeric MG window, 3 published amorphous alloys outside it), King Φ for Co43Cr1Fe7Ni49
(9.288 vs 8.93), and |ΔH<sub>f</sub>| ≤ 700 meV/atom (43 cells, F12).  UNSUPPORTED: 5 M7 rows with
ΔH<sub>mix</sub> ≥ 0 (F13).  The validator has no Ca/Sr/Ba M8 case, so §16 cannot change it.

### 17.5 Preservation of the historical record

`git diff` of this file against the last commit (a97b05e) removes lines only in sections that describe current
behaviour (§0 F3, §3 ΔH<sub>inter</sub>, §4 M8 criterion and tests, §6), and each replacement states what it replaced
("Before F9 …", "until then …", "§16").  §8–§16 have only received appended dated notes.  The corrections of this
section follow the same rule: §1, §3 (Ω, γ, φ), §4 M3/M5 and §6 carry "(2026-10-27, §17)" marks.

### 17.6 Ca/Sr/Ba: final status and remaining limitations

Implemented (§16), verified (§16.1: 11 950 compositions; no change outside M8; M8 follows de Boer et al. 1988), Help
updated, full suite 1352 passed / 7 skipped.  Remaining limitations, none hidden by a test:

* Takeuchi & Inoue's Ba / non-transition rows are ≈ 2 kJ/mol less negative than the printed factor 0.4 gives (they
  behave like 0.5); kept visible by `test_ba_with_non_transition_metals_is_a_known_discrepancy`.
* The printed program line for P (Table V-3) is read as a misprint [INFER].
* n<sub>ws</sub> is stored to 2 decimals (Bakker A1), worth 1–3 kJ/mol for low-density metals against de Boer's
  n<sub>ws</sub><sup>1/3</sup> (affects every element; a separate dataset question).
* de Boer V-4.02: 2 printed values not reproduced; V-4.01 (alkali pairs) not investigated.
* No published M8 result exists for a Ca-, Sr- or Ba-containing alloy; 21 verdicts changed and 113 compositions lie
  within |Φ − 1| < 0.05, so M8 verdicts for these alloys are formal predictions, not validated ones.

---

## 18. `atomic_radius` of Pm, Po, Pa and U corrected to Guo & Liu (2011) (2026-10-27)

Item 1 of `docs/analysis-redesign/ATOMIC_RADIUS_INVESTIGATION_PLAN_2026-10-27.md`; evidence, impact analysis and the
GO decision in `docs/analysis-redesign/ATOMIC_RADIUS_ITEM1_REVIEW_2026-10-27.md`.  No equation, constant, threshold,
engine source, other radius, flag or precision changed.

**Change (`data/periodic_table.json`, `<el>.properties.atomic_radius`).**

| Element | Before (Kittel CN12) | After (Guo & Liu Table 1) | Primary source of the new value |
|---|---|---|---|
| Pm | 181.0 | **163.0** | Guo & Liu 2011 Table 1, p. 436: 1.630 Å |
| Po | 176.0 | **153.0** | p. 436: 1.530 Å |
| Pa | 163.0 | **161.0** | p. 436: 1.610 Å |
| U | 156.0 | **142.0** | p. 436: 1.420 Å; Zhang et al. 2014 Table 1, p. 15: 0.14200 nm |

* Why: the column is defined as Guo & Liu Table 1 for M2–M5; these four held the Kittel Ch. 3 Table 9 CN12 values
  (identical to the separate `atomic_radius_cn12` column) — a provenance error, not a documented convention.  The
  legacy HEACalculator 2.2.0 holds the Guo & Liu values.  All values read from rendered pages.
* Not changed: `atomic_radius_cn12` (M1; Kittel values, still correct); the supplementary list (these are Guo & Liu
  elements); the 0.01 pm digits of other elements (plan item 2, separate decision).  The new values are the printed
  0.1 pm values; Zhang 2014 lists only U, with the same value.
* `_metadata.properties.atomic_radius` records the correction in one sentence.

**Isolation (verified twice).**  Before the edit, the review harness (`scripts/radius_item1_review.py`) compared the
installed engine with the same engine reading the four new values: 38 649 compositions without these elements were
identical in every field; with them, only δ, γ, Λ, S<sub>E</sub>, φ and M2–M5 changed (M1, M6–M8, warnings, cautions,
`model_support`, `model_coverage` identical).  After the edit, the same harness finds the installed engine identical to
the reviewed corrected state in every field (0 differences).  The independent validator (read-only re-run): unchanged,
799 = 600 PASS + 8 FAIL + 5 UNSUPPORTED + 186 DOC + 0 ERROR.

**Effect.**  Only compositions containing Pm, Po, Pa or U, and only M2–M5 (Pm and U: M2–M5; Po and Pa: M3/M4, since
they have no Takeuchi & Inoue data).  Verdicts change for many such alloys (review §2.3; e.g. UZr M4 SS → IM and M5
SS → MP; Pm0.2CoCrFeNi M2 MP → SS); Pa (−2 pm) barely moves.  No published alloy behind M2–M5 (748 rows) and no
benchmark contains these elements: **the correction restores source consistency; it does not validate predictions for
these elements**, which remain outside every model's calibration domain.  Side effect: the Pm–Sm and Tm–U binaries no
longer have equal radii, so the δ = 0 S<sub>E</sub> rounding issue (review, separate findings) now affects only Nd–Pu. (*§19: true for verdicts; the residual itself was the S<sub>E</sub> value of all 15 equal-radius pairs, Sm–Am and Tm–Np included. Corrected in §19.*)

**Fingerprints.**  `engine_version()` unchanged (`73587fb319df`; it hashes `engine.py` and `data.py` only);
`dataset_ids()["periodic_table.json"]` `4f5e64ecf7c1` → `f429d8b5822a`, so new runs are distinguishable.  Stored
session results are not recalculated.

**Tests.**  New: `tests/reference/guo_liu_2011_table1.json` (73 printed values; copy of the 2026-10-26 transcription,
re-read for these four on 2026-10-27, equal to the legacy column 73/73);
`test_datasets.py::test_atomic_radius_follows_guo_liu_table1_within_printed_precision` (every Guo & Liu element within
half a printed unit, 0.05 pm — compatible with either precision, so it does not decide item 2);
`test_datasets.py::test_pm_po_pa_u_radii_are_guo_liu_values_not_cn12` (the four values, and the unchanged CN12 column).
Negative control: with the former values all 5 new test cases fail.  No existing test expectation changed.
Full suite after the change: 1357 passed, 7 skipped (1352 before + the 5 new cases; the 7 are native-window tests
that run only with `HEA_NATIVE_TESTS=1`, not run).

---

## 19. M5: S<sub>E</sub> = 0 exactly for identical atomic diameters; an undefined φ carries its reason (2026-10-27)

Numerical-stability pass.  No equation, constant, packing fraction, threshold, dataset value or other model changed.
Evidence: `docs/analysis-redesign/scripts/m5_se_stability.py` (the MCSL equations evaluated in 60-digit decimal
arithmetic on the engine's own float inputs; `data/m5-se-2026-10-27/before.json`, `after.json`) and
`scripts/m5_se_isolation.py` (pre-fix source loaded side by side; `isolation.json`).

**Defect (reproduced with the installed engine).**  Nd and Pu both hold `atomic_radius` 164.0 pm (Pu supplementary)
and the pair has a Takeuchi & Inoue ΔH<sub>mix</sub> (+5 kJ/mol), so φ is reached.  NdPu: δ = 0 exactly,
S<sub>E</sub> = −3.69 × 10⁻¹⁵ J mol⁻¹ K⁻¹, φ = 3.35 × 10¹⁴, **M5 = SS** (in domain); Nd0.2Pu0.8 and Nd0.9Pu0.1:
S<sub>E</sub> = **+**1.11 × 10⁻¹⁴ (a positive MCSL S<sub>E</sub> is impossible), φ ≈ 10¹⁴, SS.  M4 was already
N/A (undefined, δ = 0).  The F11 guard `|S_E| < 1e-15` never triggered because the rounding residual
(−1.8 × 10⁻¹⁴ … +1.1 × 10⁻¹⁴) is larger than 10⁻¹⁵.  Behind it sat a second defect: had φ ever been undefined, M5
would have reported "S_E could not be evaluated." instead of the `phi_ye_undefined` reason F11 specifies (the path
had never been reached; `test_undefined_descriptors_carry_a_reason_the_model_surfaces` covers only M1).

**Scope in the dataset.**  11 groups of identical stored radii, 15 pairs: He/Hs/Rg, Mn/Nh, As/Mt, Se/Fl, Br/Ac,
Sb/Mc, Nd/Pu, Sm/Am, Tm/Np, Hg/Rf/Lv, Bi/Og.  All of them exposed the residual as their S<sub>E</sub> value; only
Nd–Pu has ΔH<sub>mix</sub> (the other 14 pairs: M5 N/A for missing data, correctly), so only Nd–Pu had a wrong
verdict.  (§18's "now affects only Nd–Pu" holds for verdicts; Sm–Am and Tm–Np still have equal radii, without
ΔH<sub>mix</sub>.)

**Analytical limit [derivation from the source equations].**  Ye et al., Intermetallics 59 (2015) 75, Appendix
(MCSL; Mansoori et al., J. Chem. Phys. 54 (1971) 1523), as implemented and as in the legacy code.  With d<sub>i</sub> = d
for every component:
* Δ<sub>ij</sub> ∝ (d<sub>i</sub> − d<sub>j</sub>)² = 0, so y<sub>1</sub> = y<sub>2</sub> = 0;
* ξ<sub>i</sub>/ξ = x<sub>i</sub>, so y<sub>3</sub> = (Σ x<sub>i</sub><sup>2/3</sup> x<sub>i</sub><sup>1/3</sup>)³ = (Σ x<sub>i</sub>)³ = 1;
* Z = (1 + ξ + ξ² − ξ³)/(1 − ξ)³ (one-component Carnahan–Starling), so −ln Z cancels the last logarithm;
* F<sub>ex</sub> = −3 + 2/(1 − ξ) + 1/(1 − ξ)², and S<sub>E</sub>/k<sub>B</sub> = F<sub>ex</sub> − (3 − 2ξ)/(1 − ξ)² + 3
  = 2/(1 − ξ) − 2/(1 − ξ) = **0**.

Exactly zero at every packing fraction (0.68 and 0.74 alike), for every composition and any number of components:
identical hard spheres form a one-component fluid and have no excess entropy of mixing.  The Scripta paper says the
same qualitatively (minimising |S<sub>E</sub>| "is equivalent to minimizing the atomic size misfit"); the legacy
docstring states "zero for identical atom sizes" (the legacy then maps φ = ∞ to SS, which F11 rejected).
With S<sub>E</sub> = 0, φ = (S<sub>c</sub> − S<sub>H</sub>)/|S<sub>E</sub>| has a zero denominator: undefined under
F11, exactly like Λ at δ = 0.  Corollary of the same equations: the Δ<sub>ij</sub> weights, y<sub>1</sub>,
y<sub>2</sub> and y<sub>3</sub> are linear in the fractions of equal-diameter species, so splitting a species into two
of identical diameter leaves S<sub>E</sub> unchanged.  A partial equal-radius subset (e.g. Nd–Pu–Fe) is therefore an
ordinary mixture with a finite S<sub>E</sub>; only an all-equal composition is degenerate.

**Nearly equal diameters are legitimate, not noise.**  With d<sub>i</sub> = d(1 + ε<sub>i</sub>):
y<sub>1</sub> = 2V, y<sub>2</sub> = V, y<sub>3</sub> = 1 − 3V + O(ε³), V = Σx<sub>i</sub>ε<sub>i</sub>² −
(Σx<sub>i</sub>ε<sub>i</sub>)² = (δ/100)² to the same order, giving S<sub>E</sub> = R·Ā·(δ/100)² with
A(ξ) = 6 − 3/(1 − ξ) − 3/(1 − ξ)² − 3 ln(1 − ξ) + 3ξ(2 + ξ − ξ²)/(1 + ξ + ξ² − ξ³):
A(0.68) = −26.78, A(0.74) = −43.29, Ā = −35.03.  S<sub>E</sub> is second order in the size misfit and strictly
negative.  The 60-digit evaluation agrees: S<sub>E</sub>/ε² → −72.823 for a 50/50 binary (R·Ā/4 = −72.823) and
−26.216 for 10/90 (−26.216); ternary and quinary shapes converge likewise.

**Numerical floor (float vs 60 digits).**  The formula forms S<sub>E</sub> by cancelling terms of size 1–23
(e.g. (3 − 2ξ)/(1 − ξ)² = 21.5 at ξ = 0.68, 22.9 at 0.74), so its absolute error is a few ulp × 20 × R:
≤ 4.7 × 10⁻¹⁴ J mol⁻¹ K⁻¹ over 1 217 real alloys (relative ≤ 2.8 × 10⁻¹⁰), similar at both packings.  Synthetic
near-equal diameters lose accuracy only below |S<sub>E</sub>| ≈ 10⁻¹² (ε ≲ 10⁻⁷).  The smallest non-zero radius
gap among the 73 Takeuchi & Inoue elements is Gd–Y, 0.02 pm: S<sub>E</sub> = −9.0 × 10⁻⁷ at 50/50 and
−3.6 × 10⁻¹² even at 1 ppm Gd (float error 0.3 %; 3 × 10⁻⁶ at 0.1 at.%).  The only floating-point artifact real
data can reach is therefore the exactly equal case.

**Change (`hea_calc/core/engine.py`).**
1. `_excess_entropy`: when every diameter in the composition is identical, return 0.0 (the analytic value) instead
   of evaluating the cancelling terms.  Distinct diameters take the unchanged code path (bit-identical results).
2. M5 outcome: when `phi_ye_undefined` is set, M5 is N/A with that reason and `na_kind` undefined (F11).  The
   existing branches (missing ΔH<sub>mix</sub> or radius → missing data; S<sub>E</sub> not evaluable → undefined)
   are unchanged.

Not changed: Ye's φ, the MCSL equations, ξ = 0.68 / 0.74 and their averaging, the φ ≥ 20 threshold, the existing
|S<sub>E</sub>| < 10⁻¹⁵ test in the φ branch (no new threshold), radii, M1–M4, M6–M8.

Rejected: (a) clamping |S<sub>E</sub>| below some ε, or raising the 10⁻¹⁵ guard to the rounding floor — an absolute
threshold with no dimensional basis that would also erase legitimate values (Gd–Y at 1 ppm is 3.6 × 10⁻¹²);
(b) a cancellation-free rearrangement of S<sub>E</sub>/k<sub>B</sub> in terms of y<sub>1</sub>, y<sub>2</sub> and
y<sub>3</sub> − 1 (exact algebra; it removes the O(20) cancellation, but y<sub>3</sub> − 1 is itself a difference of
O(1) quantities, so it still would not give exactly 0 at equal diameters, and it would improve the floor about tenfold
only for values no real composition reaches).  (b) is a broader rewrite; documented, not implemented.

**Isolation.**  57 600 compositions (17 334 binaries of every element with a radius at three compositions, 106
Nd–Pu–X ternaries, 748 published-table rows, 763 benchmark cases, 33 649 equiatomic 4/5-element and 5 000 random
alloys): 45 differ, all of them binaries with identical radii (15 pairs × 3).  Changed fields: S<sub>E</sub> in 45
(residual → 0.0; 29 of the residuals were positive), and φ, `phi_ye_undefined` and M5 in 3:

| Composition | S<sub>E</sub> before | φ before | M5 before → after |
|---|---|---|---|
| Nd0.5Pu0.5 | −3.69 × 10⁻¹⁵ | 3.35 × 10¹⁴ | SS → N/A (undefined) |
| Nd0.2Pu0.8 | +1.11 × 10⁻¹⁴ | 8.36 × 10¹³ | SS → N/A (undefined) |
| Nd0.9Pu0.1 | +1.11 × 10⁻¹⁴ | 1.15 × 10¹⁴ | SS → N/A (undefined) |

Every composition with at least one distinct radius — all Nd–Pu–X ternaries and every published row included — is
identical in every descriptor (float repr) and in every model outcome M1–M8 (label, status, N/A kind, reason,
caution, values).  The independent validator (read-only re-run): unchanged, 799 = 600 PASS + 8 FAIL + 5 UNSUPPORTED +
186 DOC + 0 ERROR.

**Fingerprints.**  `engine_version()` `73587fb319df` → `f64504541a84`; dataset IDs unchanged
(`periodic_table.json` `f429d8b5822a`).  Stored session results are not recalculated.

**Tests.**  New `tests/test_m5_excess_entropy_limits.py` (60 cases; expected values from the derivation above, none
from engine output): equal diameters → S<sub>E</sub> == 0 exactly (30 synthetic cases, 2–7 components, 5 radii);
Nd–Pu at 5 compositions → S<sub>E</sub> = 0, φ None, M5 N/A undefined carrying `phi_ye_undefined`, M4 N/A undefined;
five other equal-radius sets → S<sub>E</sub> = 0, M5 N/A missing data; S<sub>E</sub> never positive (Nd–Pu and Gd–Y,
99 compositions each); identical species merge (Nd–Pu–Fe = Nd–Fe, Nd–Pu–Co–Cr–Ni = Pu–Co–Cr–Ni, rel 10⁻¹²); nearly
equal diameters (4 shapes × ε = 10⁻³, 10⁻⁴, 10⁻⁵) → the second-order limit within 5ε, never zero; Gd–Y (0.02 pm) at 4
compositions → finite φ and an M5 verdict; the A(ξ) constants.  Published references re-run unchanged:
`test_ye_excess_entropy` (171 |S<sub>E</sub>| rows), φ 369 / 11, Table S1 classification, benchmarks.  Negative
controls: against the pre-fix engine 41 of 60 cases fail (every equal-diameter case, none of the legitimate ones);
with change 1 alone the 5 Nd–Pu cases still fail on the reason text.  No existing test, expectation or tolerance
changed.  Full suite after the change: 1417 passed, 7 skipped (1357 before + the 60 new cases; the 7 are native-window tests that run only with `HEA_NATIVE_TESTS=1`, not run).

**Remaining limitations.**
* The φ branch keeps the pre-existing |S<sub>E</sub>| < 10⁻¹⁵ test (F11).  With equal diameters now exactly 0 it
  acts only on exact zeros in practice; real distinct radii give |S<sub>E</sub>| ≥ 3.6 × 10⁻¹² down to 1 ppm.  Below
  about 10⁻¹² J mol⁻¹ K⁻¹ (synthetic ε ≲ 10⁻⁷ or sub-ppm fractions) double precision does not resolve S<sub>E</sub>;
  no realistic composition gets there.
* For nearly equal radii φ ∝ 1/δ² is legitimately very large (Gd–Y 50/50: δ = 0.006 %, φ = 6.4 × 10⁶, SS); that is
  the criterion's behaviour, not a rounding artifact, and far outside the δ range of Ye's calibration alloys (Help,
  M5 limitation).
* Nd–Pu remains outside every model's calibration domain (Pu radius supplementary).
* Help (`phase-models.md`, M5 limitation) described the near-equal case but not the exactly equal one; the same day
  it gained a separate "Undefined φ: identical atomic sizes" item (r<sub>1</sub> = … = r<sub>n</sub> gives
  S<sub>E</sub> = 0 at both packings, φ undefined, M5 N/A), and the near-equal item now states that S<sub>E</sub> is
  small but non-zero (∝ δ² to leading order) and that the sign of φ follows S<sub>c</sub> − S<sub>H</sub>.

---

## 20. `atomic_radius`: Guo & Liu (2011) Table 1 printed values for all 73 elements — F2 (2026-10-27)

Item 2 of the radius plan.  Evidence and decision: `docs/analysis-redesign/ATOMIC_RADIUS_ITEM2_PRECISION_2026-10-27.md`;
approved proposal: `docs/analysis-redesign/F2_ATOMIC_RADIUS_IMPLEMENTATION_PROPOSAL_2026-10-27.md` (approved
2026-10-27, as proposed).  No equation, constant, threshold, engine source, supplementary radius, CN12 value or other
property changed.

**Change (`data/periodic_table.json`, `<el>.properties.atomic_radius`; CRLF kept).**  26 values, each to the value
printed in Guo & Liu, Prog. Nat. Sci.: Mater. Int. 21 (2011) 433, Table 1, pp. 435–436 (Å, 3 decimals):

| From Zhang 2014 Table 1 (0.01 pm) → printed | Untraced 0.01 pm → printed |
|---|---|
| Fe 124.12 → 124.1, Ni 124.59 → 124.6, Cr 124.91 → 124.9, Mo 136.26 → 136.3, Pd 137.54 → 137.5, Zn 139.45 → 139.5, Al 143.17 → 143.2, Ag 144.47 → 144.5, Ti 146.15 → 146.2, Li 151.94 → 151.9, Hf 157.75 → 157.8, Mg 160.13 → 160.1, Zr 160.25 → 160.3, Pb 174.97 → 175.0, Gd 180.13 → 180.1, Y 180.15 → 180.2, Ce 182.47 → 182.5 | Ru 133.84 → 133.8, Os 135.23 → 135.2, Ir 135.73 → 135.7, Cd 156.83 → 156.8, Lu 173.49 → 173.5, Er 175.58 → 175.6, Ho 176.61 → 176.6, Tb 178.14 → 178.1, Eu 198.44 → 198.4 |

* All 73 Table 1 values now equal the print exactly (47 already did, Pm/Po/Pa/U since §18).  Zn 139.5 and Zr 160.3 are
  the printed values; no rounding function was used (half-even rounding of the former values would give 139.4 / 160.2).
* `_metadata.properties.atomic_radius` gained one sentence recording the change (section 20).

**Why.**
* The column is defined as Guo & Liu Table 1, and only the printed values *are* that table.
* The 0.01 pm digits are a later re-compilation of the same derived quantity: half interatomic distances from lattice
  parameters, via the JIM *Metal Databook*, Takeuchi & Inoue and Zhang 2014. They are labelled "CN12", although for bcc
  metals they are 8-neighbour half-distances, and 9 of them are untraceable.
* A radius's physical uncertainty (percent level) dwarfs either precision, so the decision rests on provenance and on
  the reproducibility of the cited M2–M5 publications, not on physical accuracy or experimental agreement.

**Measured after the change** (harnesses `scripts/radius_f2_isolation.py`, `scripts/radius_item2_reproduction.py`;
data `data/atomic-radius-f2-2026-10-27/`; every number equals the proposal's prediction):

* *Isolation:*
  * 0 differences in every field for all compositions without the 26 elements.
  * 0 changes to M1, M6–M8, non-radius descriptors, warnings and `model_support`.
  * The comparison covered 11 556 binaries, 748 published-table rows, 763 benchmark cases, 33 649 equiatomic 4/5-element
    alloys and 5 000 random alloys.
* *Reproduction (before → after, exact / within tolerance):*
  * Guo 2013 δ 25 → **81** / 91.
  * Singh δ 26 → **56** / 68; Singh Λ 6 → **26** / 68 → 67.
  * Ye Intermetallics |S<sub>E</sub>| 16 → **75** / 170 → 171.
  * Ye main-text φ FeCrCuNiCo 371.3 → **369.5** (printed 369).
  * Wang δ + γ (Ye SI compositions) 0 → **4** / 4.
* *Classification* (changes only at thresholds):
  * Sweeps: equiatomic-4 17 / 7 315, equiatomic-5 35 / 26 334, random 8 / 5 000.
  * Published and benchmark compositions — three alloys, under several catalogue rows:
    * FeCoNiCrCuAl3 M2 SS → MP (δ 6.598 → 6.610; Guo prints 6.61 and classifies MP; observed SS);
    * Al36.3Co13.0Cr11.8Cu11.3Fe14.1Ni13.4 M2 SS → MP (observed F + F + B2);
    * NbMoTaV M4 SS+IM → SS (Λ 0.958 → 0.960).
  * Agreement with each paper's own classification: Guo M2 92 → 93 / 93; M4 76 / 76 and M5 43 / 43 unchanged.
  * Agreement with observed phases: M2 72 → 71; M4 75 / 76 and M5 41 / 43 unchanged.
* *New identical-radius pairs (not anticipated in the proposal):*
  * **Pd–Re** — Guo & Liu print both as 1.375 Å, formerly 137.54 vs 137.5. Pd–Re-only compositions now have δ = 0 and
    S<sub>E</sub> = 0, so Λ and φ are undefined and M4 / M5 report N/A (undefined), §19 / F11. Before, the 0.04 pm gap
    gave Λ ≈ 3 × 10⁴ and φ ≈ 6 × 10⁵ (SS).
  * **Pb–Fr** — Pb 175.0 equals Fr's supplementary 175, so M4 is N/A (undefined) for Pb–Fr only. Fr has no
    Takeuchi–Inoue data, so φ is never reached.
  * The smallest non-zero gap among the 73 Takeuchi–Inoue elements becomes 0.1 pm (Gd–Y, Bi–Mg, Fe–Ge, Gd–Th).
* *Independent validator* (read-only): 799 checks, 600 PASS / 8 FAIL → **599 / 9**, 5 UNSUPPORTED, 186 DOC, 0 ERROR.
  The new FAIL is FeCoNiCrCuAl3 M2: the validator compares the M2 verdict with the *observed* phase (SS); F2
  reproduces Guo's own MP. Nothing else changed.

**Documented discrepancy (published reference, radius source).**
* *Row:* Singh 2014 Table 1, Mo0.3CoCrFeNi (catalogue M4-SINGH14-T1-067).
* *Values:* Λ 2.2686 against the printed 2.317 (−2.09 %; tolerance 2 %; formerly 2.2871, −1.29 %). δ 2.3777 against
  2.35, within the 0.05 tolerance.
* *Cause:* Singh et al. take their data from *Smithells* (their Ref. 47), not Guo & Liu.
* *Treatment:* a Λ-only entry in `test_published_benchmarks.KNOWN_DISCREPANCIES`, plus `SINGH_LAMBDA_KNOWN` in
  `test_models_published.py`:
  * δ is still checked;
  * Λ must stay outside 2 % and within 3 %;
  * the F2 Λ itself is checked against an independent evaluation.
* *Not changed:* the published value and the tolerance; the row is not skipped.

**Zr.** The printed 160.3 is kept. Guo 2013's δ column implies 160.2 (8/8 Zr rows exact), Ye's S<sub>E</sub> table 160.3
(17/30 against 4/30). The conflict between the publications is documented, not resolved.

**Fingerprints.** `engine_version()` unchanged (`f64504541a84`); `dataset_ids()["periodic_table.json"]`
`f429d8b5822a` → **`581eea161276`**.  Stored session results are not recalculated.

**Tests.**
* *New:*
  * `test_datasets.py::test_atomic_radius_equals_guo_liu_table1_exactly` (73 printed values, Zn/Zr as printed).
  * `tests/test_radius_f2_invariance.py`, which compares with the engine reading the pre-F2 values:
    * unaffected compositions identical in every field;
    * M1 and M6–M8 never change;
    * model support and the supplementary flag unchanged;
    * Pd–Re undefined Λ / φ.
  * `test_models_published.py::test_singh_row_067_lambda_is_the_independent_f2_value`.
* *Changed:*
  * `test_supplementary_radius_flag`: Fe 124.12 → 124.1, the printed value.
  * `test_model_support_consistency.py::test_gamma_lambda_and_m3_m4_verdicts_are_unchanged`: the four pinned engine
    γ / Λ values are replaced by an independent evaluation of Wang Eqs. (1)–(3) and Singh's Λ with the printed radii,
    rel 1e-12. The M3 / M4 verdicts stay pinned and are unchanged.
  * The Singh 067 entries above.
* *Also changed — not anticipated in the proposal* (its dry run covered the engine test files only):
  * four Analysis-pipeline tests in `tests/test_analysis_core.py` pinned "canonical sample data" generated with the
    pre-F2 radii: the C1 δ quartiles, the M4 and M5 class counts, the δ histogram and family box plot, and the E2 δ grid
    cells;
  * their radius-dependent assertions now use expectations computed in the test from the recipes' compositions:
    * δ, Singh Λ and the M4 class;
    * Ye φ with the MCSL S<sub>E</sub>, using the dataset's Takeuchi–Inoue ΔH<sub>mix</sub> and T<sub>m</sub>;
    * the printed radii;
    * the normative type-7 quartiles and the histogram binning rule;
  * the non-radius statistics stay pinned;
  * `ANALYSIS_FIGMA_SAMPLE_DATA.md` carries a dated note (C1 δ quartiles 4.35 / 5.29 / 5.83, M4 53 / 288, M5 68 / 273).
* *Unchanged:* every other expectation and every tolerance.
* *Negative control:* with the pre-F2 values restored, all 10 new or changed cases fail, and so do the 4 changed
  Analysis tests.
* Full suite after the change: 1469 passed, 8 skipped (1462 before + 7 new: the exact-table test, the Singh 067 F2 check, 5 invariance tests; the 8 are native-window tests that run only with `HEA_NATIVE_TESTS=1`).

**Rollback.** Revert the 26 value lines and the metadata sentence in `data/periodic_table.json` (dataset ID returns to
`f429d8b5822a`) and the test changes above; no migration, no stored-data change.

**Open.**
* The element panel shows radii with `{:.2f}` ("124.10 pm"); the label precision is plan item 5 and needs Help review.
* The 35 supplementary radii are plan item 4.
* The Ye Intermetallics SI is plan item 6.

## 2026-10-28 - Model details figures (display only; no engine change)

- New dataset `data/model_figures.json`, built by `tools/build_model_figures.py` from
  `tests/reference/published_benchmarks.json`. It holds published tabulated values only, each with its DOI and table
  location: M1 133 alloys (Yang & Zhang 2012, Table 1: δ_CN12, Ω), M2 93 (Guo 2013, Table 1: δ, ΔHmix), M3 11
  (Wang 2015, Table 1: γ), M4 76 (Singh 2014, Table 1: δ, Λ), M5 2 (Ye 2015, p. 54: φ), M7 45 (Senkov & Miracle
  2016, Table 1: k₁, k₁cr), M8 4 (King 2016, worked examples: Φ). No point is digitised from a figure.
- The engine never reads the file. It is not one of the provenance `DATA_FILES`, so run provenance and dataset IDs
  are unchanged.
- `core/analysis/model_figures.py` draws each model's thresholds. A test checks every value against
  `MODELS[k].criterion`; k₂ and the 37 meV/atom bound come from the engine constants.
- Figures are labelled by provenance:
  - publication-data-backed: M1, M2, M3, M4, M7;
  - illustrative criterion charts: M5 and M8, with the few published values; M6, from −k_B·T·ln N and 37 meV/atom,
    with no published values.
