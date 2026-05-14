# 10 — Known Limitations

**Status**: LIVE — re-check on physics changes
**Code**: scattered across `physics/`; tracked here for visibility
**Tests**: see individual entries

This file is the **honest catalog of things the direct backend gets
wrong or doesn't model well**. A doc that lists only the wins is
marketing; a doc that lists the failures is engineering. Each
limitation has: regime where it manifests, observed error magnitude,
workaround, and the long-term fix.

## 1. Roters fringing factor — saturates at `k = 3` for huge gaps

**Regime**: `lgap_mm / w_centerleg_mm > 1.0`. Above that ratio the
empirical Roters fit is outside its calibration range.

**Manifestation**: `k_fringe` clamps at 3.0 instead of growing
unboundedly. The actual physical L for such designs depends on a
fully-3-D fringing flux pattern the closed-form can't capture.

**Where it bites**:
- Designs that exceed the catalog's reasonable gap range — usually
  cores chosen too small for the L target.
- Si-Fe / amorphous lamination cases pre-fix (synthetic 10+ mm gaps
  in small cores). These are now blocked by `_CLOSED_PATH_SHAPES` and
  `_CLOSED_PATH_MATERIAL_TYPES` gates — but if you remove those gates
  for any reason, the clamping resurfaces.

**Magnitude**: factor of ~2× under-estimate of `L` once `k > 3.0`.
Acceptable as a soft warning (the engine also flags `B_pk > B_sat`
on the same design); not acceptable as a quantitative answer.

**Workaround**: design picks a bigger core. If you genuinely need
small core + large gap, jump to 3-D FEM.

**Long-term fix**: Phase 4.2 — 3-D tet-mesh FEM
(`physics/magnetostatic_3d.py` is a stub).

## 2. Toroid with significant axial leakage

**Regime**: tall toroids where `HT >> (OD − ID) / 2`. The closed-form
`B_φ = NI/(2πr)` assumes flux stays in-window; tall toroids leak axially.

**Manifestation**: `L` is over-estimated because the model assumes
all flux links every turn.

**Magnitude**: 5–15 % over-estimate when `HT > 2 · (OD − ID)`.
Rare in PFC catalogs (most powder toroids are flat).

**Workaround**: none in the reluctance solver. FEMMT supports
axisymmetric toroids but with its own (also imperfect) axisymmetric
approximation.

**Long-term fix**: 3-D FEM, or specific Schwarz-Christoffel
correction for toroid axial geometry.

## 3. Magnetics LP powder cores — 8000 %+ catalog mismatch

**Regime**: two specific catalog entries:
- `mas-magnetics-lp-lp-32-15-22---edge-26---ungapped`
- `mas-magnetics-lp-lp-32-15-22---high-flux-26---ungapped`

**Manifestation**: engine reports `L ≈ 521 μH`, direct reports
`L ≈ 46111 μH` (88×). Both solvers use the same `AL_nH` × N² × μ_pct
fast path, so the only way they can disagree is if `AL_nH` is being
read differently — or if `μ_pct` returns wildly different values.

**Magnitude**: catastrophic. Excluded from feasibility stats in the
boost-PFC sweep.

**Hypothesis**: catalog AL convention mismatch. Magnetics historically
ships `AL` per N=10 (their measurement reference) for some series.
Our importer assumes N=1. A 100× factor would be 10² (the AL-per-N=10
to AL-per-N=1 conversion). 88× is close enough that this is the
leading hypothesis.

**Workaround**: don't use LP cores until the catalog import is fixed.

**Long-term fix**: investigate `scripts/import_magnetics.py` (or
equivalent) and apply the AL convention conversion. Tracked as a
separate task (chip spawned in May 2026 session).

## 4. EI shape via axisymmetric approximation

**Regime**: FEM backend (`backend="axi"`) on EI / EE cores.

**Manifestation**: the axisymmetric solver replaces the rectangular
center leg + two outer legs with a cylinder + cylindrical shell of
equivalent area. Flux path lengths differ from the true rectangular
geometry.

**Magnitude**: 5–10 % deviation from a 3-D model on EI cores. The
reluctance backend (default) avoids this entirely by using catalog
`A_L`, which is measured on the real geometry.

**Workaround**: use `backend="reluctance"` (default).

**Long-term fix**: Phase 4.2 (3-D tet FEM).

## 5. Thermal lumped 1-node model — hot-spot under-estimate

**Regime**: tall multi-layer windings, especially without spacer
bobbins.

**Manifestation**: the lumped model returns a volume-averaged
temperature. The hot-spot temperature (innermost layer) can be
5–15 K higher than the lumped value.

**Magnitude**: 2–6 K on a typical PFC choke at 600 W. Has been
measured on a single thermal-camera comparison; needs more data
points.

**Workaround**: design with > 10 K margin against `T_max`.

**Long-term fix**: multi-node thermal model (Phase 4 stretch) or
3-D thermal FEM.

## 6. Saturation cliff — model invalid above 1.2 × B_sat

**Regime**: any operating point where `B_pk > 1.2 · B_sat_100C_T`.

**Manifestation**: the rolloff / soft-knee model is calibrated for
the linear-to-knee transition. Deep in saturation the `μ_r` collapses
toward 1 and the inductance becomes intrinsically nonlinear (cycle
shape depends on di/dt).

**Magnitude**: indeterminate. The engine throws a warning at
`B_pk > 0.8 · B_sat_100C_T` (a 20 % margin) and the user is expected
to pick a different core rather than trust the L number.

**Workaround**: respect the warning.

**Long-term fix**: full B-H curve model + nonlinear transient
(Phase 4.1, see `physics/transient.py` stub).

## 7. Partial-winding coverage on toroids

**Regime**: toroids with `winding_coverage_fraction < 0.85`.

**Manifestation**: the toroidal closed form assumes uniform azimuthal
linkage. Partial winding (e.g. 270° wound + 90° gap for terminations)
exhibits fringing through the un-wound section.

**Magnitude**: 5–15 % L over-estimate at 50 % coverage.
Empirically valid down to ~85 % coverage with the linear correction
in `solve_toroidal`.

**Workaround**: design coverage ≥ 85 %.

**Long-term fix**: 3-D FEM, or a more nuanced 2-D model.

## 8. Steinmetz `T` dependence not modeled in iterative coupling

**Regime**: `em_thermal_coupling.solve_em_thermal` at temperatures
far from 25 °C.

**Manifestation**: `P_core` is held fixed across thermal iterations.
Real Steinmetz coefficients have weak `T` dependence (~5 %).

**Magnitude**: < 5 % error on `T_winding`. Conservative because we
use hot `B_sat_100C_T` as the saturation limit.

**Workaround**: none needed for design margin.

**Long-term fix**: add `Steinmetz(T)` to the catalog material model
(Phase 4 stretch).

## 9. Hysteresis not modeled

**Regime**: any AC analysis.

**Manifestation**: rolloff curves are single-valued (no loop). Real
μ has a hysteretic loop with major/minor cycles.

**Magnitude**: factored into core loss via Steinmetz; the
inductance value is not affected at the linear-μ operating points
PFC inductors live in.

**Workaround**: trust the Steinmetz / iGSE for core loss; trust the
single-valued μ for L.

**Long-term fix**: Preisach or Jiles-Atherton model (Phase 5+
stretch). Not on the roadmap.

## 10. Anisotropy not modeled

**Regime**: Si-Fe laminations operated cross-grain (rare).

**Manifestation**: grain-oriented Si-Fe (M5, M4) has ~10× higher μ
along the rolling direction than transverse. The catalog ships only
the rolling-direction `μ_initial`.

**Magnitude**: indeterminate; the design would have to specify
cross-grain operation, which our spec doesn't currently expose.

**Workaround**: only use Si-Fe in rolling-direction designs.

**Long-term fix**: extend catalog material model with `μ_parallel` /
`μ_perpendicular`. Not on roadmap.

## 11. No radiation in thermal model

**Regime**: surface temperatures > 100 °C.

**Manifestation**: lumped thermal model uses convection only.
Radiation contributes ~10–20 % additional heat removal above 100 °C.

**Magnitude**: 5–10 K conservative under-estimate of `h_eff` at high
T.

**Workaround**: design margin already absorbs this.

**Long-term fix**: add radiation term to `h_conv`. Trivial extension
(Stefan-Boltzmann with `ε ≈ 0.95` for varnished copper).

## 12. Single-winding only

**Regime**: any multi-winding design (forward, flyback, push-pull,
LLC).

**Manifestation**: the runner accepts one `wire` and one `n_turns`.
Multi-winding designs need to call it once per winding and sum
results manually.

**Magnitude**: not a numerical limitation, an API limitation.

**Workaround**: external Python script that combines per-winding
results.

**Long-term fix**: `Winding` list in the API + coupling matrix
computation (Phase 5+).

---

## Summary table

| # | Limitation | Magnitude | Severity | Tracked |
|---|---|---:|---|---|
| 1 | Roters clamp at k=3 | 2× under | LOW (gated) | Phase 4.2 |
| 2 | Tall toroids (axial leak) | 5–15 % over | LOW | Phase 4.2 |
| 3 | LP catalog mismatch | 8000× | HIGH | Follow-up issue |
| 4 | Axi EI approximation | 5–10 % | LOW (default is reluctance) | Phase 4.2 |
| 5 | Hot-spot under-estimate | 2–6 K | LOW | Phase 4 stretch |
| 6 | Saturation cliff | unbounded | LOW (gated by warning) | Phase 4.1 |
| 7 | Partial toroid coverage | 5–15 % | LOW | Future |
| 8 | Steinmetz(T) | < 5 % | LOW | Phase 4 stretch |
| 9 | Hysteresis | n/a for L | LOW | Not on roadmap |
| 10 | Anisotropy | n/a | LOW | Not on roadmap |
| 11 | Radiation | < 10 K | LOW | Trivial fix |
| 12 | Multi-winding | API | MEDIUM | Phase 5+ |

The **HIGH-severity** items (LP catalog) are the only ones that
actively mislead the user today. The rest are bounded under-estimates
the engine already flags via design warnings.
