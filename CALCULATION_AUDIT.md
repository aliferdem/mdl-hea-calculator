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
| F3 | **Yang & Zhang δ used the wrong radius set.** Old preview used one radius (`atomic_radius`, Guo & Liu 2011) for everything. | Yang & Zhang cite Kittel (CN12 radii). Recomputing their Table 1: Kittel CN12 reproduces 88 % of δ within 0.02 (median error 0.003); Guo–Liu radii median error 0.43. Guo 2013 / Singh 2014 / Guo–Liu 2011 tables are reproduced by Guo–Liu radii (96 %/86 %/96 %). | Added `atomic_radius_cn12` (Kittel Table 9, hand-transcribed, matches legacy for all 70 elements). δ_CN12 used by M1 and M8; δ (Guo–Liu) by M2, M3, M4, M5. |
| F4 | **King structural term applied to non-transition metals** (e.g. Al–Ni). | Bakker (1998) Part I §5.2 and Part II Eq. 51: the structural term "is only non-zero for a solid solution of two transition metals". King benchmark AlCoCrFeNi ΔG_ss: −34.96 (old) → −33.71 (new) vs −33.89 published. | Structural term restricted to transition-metal pairs with 3 ≤ z ≤ 10. |
| F5 | **Senkov–Miracle returned N/A for ΔH_mix ≥ 0** (old) / used the k₁ ratio regardless of sign (legacy). | Eq. (6) SS condition ΔH_mix − TΔS < ΔH_IM − k₂TΔS is general; Eq. (7)/(8) divide by ΔH_mix assuming ΔH_mix < 0 (inequality flips for ΔH_mix > 0). Authors still report positive-ΔH_mix alloys (CoCrCuFeMn, Cu0.5CoCrFeNi) in Table 1. | Evaluate Eq. (6) directly — identical to k₁ < k₁cr for ΔH_mix < 0, physically correct for ΔH_mix ≥ 0. Reproduces every Table 1 classification of the positive-ΔH_mix alloys. |
| F6 | Default assessment temperature for M6/M7 (old 0.60·Tm, legacy 0.55·Tm). | Troparevsky: experimental T_ann of the known HEAs correspond to 0.53–0.56 Tm and the authors later refer to "T_crit = 0.55 T_M as suggested above"; Senkov & Miracle describe Troparevsky's model as annealing at T_cr ≈ 0.55 Tm. | Default **0.55·Tm**, overridable by an explicit annealing temperature (shared by M6 and M7); the source is reported with each result. |
| F7 | Old preview raised an exception (whole alloy failed) when any ΔH_mix pair was missing. | Requirement: missing data ≠ zero; independent descriptors must still be produced. | Missing binary data → only dependent descriptors/models are N/A with an explicit reason. Tabulated zeros (e.g. Fe–Mn = 0) are values. |
| F8 | Legacy King implementation uses a hand-transcribed interfacial table with errors (Cu-in-Ni 4 vs Bakker +14, Ir-in-Fe −59 vs −38, Ir-in-Cu 64 vs +1, W-in-Fe −6 vs 0, Au-in-Co 25 vs +33, Mo-in-Y −70 vs +114). | Bakker Table A2 pages rendered and read. | New engine computes ΔH_inter from the Miedema equation with Bakker Table A1 parameters; it reproduces Bakker Table A2 within ±2.1 kJ/mol for all 840 TM–TM pairs (test). |

Items flagged for user review are marked **⚑ REVIEW**.

---

## 1. Elemental data (`data/periodic_table.json`)

| Property | Source | Verification |
|---|---|---|
| `atomic_radius` (pm) | Guo & Liu, Prog. Nat. Sci. 21 (2011) Table 1 (not in Model Sources). | Reproduces published δ of Guo 2013 T1 (183/186 within 0.05), Singh 2014 T1 (68/76), Guo–Liu 2011 T2–3 (96 % within 0.02). 45 elements absent from Guo–Liu Table 1 carry supplementary values of unknown origin (list in `_metadata.atomic_radius_supplementary`); the engine warns and the periodic table shows ⚠ for M2–M5. **⚑ REVIEW** origin of supplementary radii. |
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
| Ω | T_m ΔS_mix / \|ΔH_mix\| (YZ Eq. 5); ∞ if ΔH_mix = 0 | — | same | same | `test_yang_zhang_omega_examples`, `test_binary_and_physical_zero_mixing` |
| γ | ω_S/ω_L, ω = 1 − √[((r + r̄)² − r̄²)/(r + r̄)²] with r_S, r_L (Wang Eqs. 2–3) | — ; Guo–Liu radii (paper does not name its radii; same group as Guo 2013, whose δ it compares with) | same (variable names swapped but equivalent) | CN12 radii | Guo–Liu. **⚑ REVIEW** radius choice is inferred. `test_wang_hume_rothery_limit` |
| Λ | ΔS_mix / δ² (Singh; δ in %) | J mol⁻¹ K⁻¹ | same | same | `test_singh_2014_table1_*` |
| S_E | Mansoori–Carnahan–Starling–Leland hard-sphere excess entropy, dᵢ = 2rᵢ, averaged over ξ = 0.68 (bcc) and 0.74 (fcc) (Ye Scr. Mater. 2015 text; Ye Intermetallics 2015 App.) | J mol⁻¹ K⁻¹; Guo–Liu radii | same | same | 171/174 Ye |S_E| values within 5 %; `test_ye_excess_entropy` |
| φ (Ye) | (S_c − S_H)/\|S_E\|, S_H = \|ΔH_mix\|/T_m | — | same | same | FeCrCuNiCo 371 (paper 369), FeCrCuNiAl 11.4 (paper 11) |
| ΔH_f,min/max | extremes of Troparevsky ΔH_ij over all pairs | meV/atom | Morris data | published (lower-triangle mix) | published matrix (F2) |
| −TΔS_mix | lower bound, T × ΔS_mix / 96.4853 | meV/atom | 0.60 Tm default | 0.55 Tm | 0.55 Tm default (F6); "−138.7 meV/atom at 1000 K" test |
| ΔH_IM | Σ_{i<j} 4cᵢcⱼ ΔH_ij^IM × 0.0964853 (Senkov Eq. 9) | kJ/mol | Morris data | published | 44/45 Senkov values; `test_senkov_2016_dhim_*` |
| k₁, k₁cr | k₁ = ΔH_IM/ΔH_mix; k₁cr = 1 + (1 − k₂)TΔS_mix/\|ΔH_mix\|, k₂ = 0.6 (Eq. 7) | — | same | same | `test_senkov_k1cr_definition` (CoCrFeNi at 573 K → 1.70) |
| ΔH_ss (King) | Σᵢ Σ_{k≠i} cᵢ (c_k/(1 − cᵢ)) ΔH_ik^form(ss) (Eq. S8); binary ΔH^form(ss) = chem + elastic + struct (S1–S7, Bakker Eqs. 51–54) evaluated at the pair ratio cᵢ:c_k | kJ/mol; Bakker A1/A5 | struct for all pairs | table-based, directional struct | struct TM–TM only (F4) |
| ΔH_inter(A in B) | V_A^{2/3}[1 + a(φ_A − φ_B)] / ½(n_A^{−1/3} + n_B^{−1/3}) × [−P(Δφ*)² + Q(Δn_ws^{1/3})² − R]; P = 14.2/10.7/12.35, Q = 9.4P, R = P·(R/P)_A(R/P)_B | kJ/mol A | same | Bakker table (with errors) | equation; reproduces Bakker A2 ±2.1 (F8) |
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

### M4 — Singh et al. (2014), `model_4.pdf`
* Λ = ΔS_mix/δ²; **SS if Λ > 0.96; SS+IM if 0.24 ≤ Λ ≤ 0.96** (Table 2 "[0.24, 0.96]", "DSS + compound(s)"); **IM if Λ < 0.24**.
* Old preview: same. Legacy: middle class called "Multiple Phases" — the paper's class is DSS + compound → **SS+IM**.
* Tests: Singh T1 δ/Λ (68/76; exceptions are table values not reproducible from the paper's own radii), boundary test.

### M5 — Ye et al. (2015), `model_5.pdf`
* φ = (S_c − S_H)/|S_E|, S_H = |ΔH_mix|/T_m, S_E averaged over fcc and bcc packing. **SS if φ ≥ 20** (φ_c ≈ 20; the boundary itself is not specified, inclusive used), otherwise MP.
* Old preview: same equation (labelled R7). Legacy: same.
* Tests: main-text examples (369, 11), Table S1 classification, Intermetallics |S_E| table.

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
* Φ = ΔG_ss/(−|ΔG_max|) at T_m; criterion used by the authors for screening (Sec. 3.4): **Φ ≥ 1 and δ ≤ 6.6 %**, δ with the Goldschmidt (CN12) radius (paper Eq. 5 and supplement) → δ_CN12. Otherwise MP.
* Implementation details and decisions in §3 (ΔH_inter equation, structural term TM–TM only, ordered compound averaging, ⌊N/2⌋ scaling).
* King used Bakker-tabulated ΔH_inter "where available, otherwise Zhang's Miedema Calculator (Mied89)"; the equation reproduces Bakker's table within rounding, so results are equivalent.
* Elements without Miedema parameters or classification (e.g. Nd and most lanthanides) → N/A. **⚑ REVIEW** whether rare earths should be added with Miedema's transition-metal treatment.
* Tests: `test_king_2016_worked_examples` (ΔG_ss within 0.4 kJ/mol, Φ within 0.03, pairs CrNi/CuFe/AlNi), `test_structural_term_only_for_transition_pairs`, `test_miedema_formula_reproduces_bakker_table_a2`.

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
* Missing Miedema data → King descriptors and M8 = N/A. Missing CN12 radius → δ_CN12, M1, M8 = N/A.
* Supplementary (non-Guo–Liu) radius → values computed, warning on the result, caution on M2–M5, ⚠ on the periodic table.
* Tests: `test_missing_*`, `test_binary_and_physical_zero_mixing`.

## 7. Composition generation (workflow semantics, no physics)

All workflows produce plain `{element: amount}` dictionaries that the single engine normalises.

* **Single composition** — the active input column (At. ratio, at.%, wt.%, Mass) is converted to atomic
  fractions; the other columns are derived from those fractions (`core/composition.py`), so switching the
  input column never changes the composition. *Set equal* sets equal values in the active column
  (ratio 1, percentages 100/n, mass total/n); *Normalize* rescales at.% or wt.% to 100 % and refuses blanks,
  invalid/negative values and zero totals.
* **Composition sweep** (`core/generation.py: iter_space`, Figma 278:17008) — each element has Min / Max /
  Step. Unit *At. ratio*: every element takes each positive grid value independently (cartesian product);
  proportional duplicates are removed (e.g. 1:1 and 2:2). Unit *at.%*: only combinations summing to exactly
  100 % are valid (integer arithmetic, no float drift). *Lock* on = required (always present, value > 0);
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
