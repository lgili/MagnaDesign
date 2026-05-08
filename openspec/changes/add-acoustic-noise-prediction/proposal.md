# Add acoustic-noise prediction (audible band)

## Why

Compressor-inverter PFC inductors run with switching frequencies
in the 4–25 kHz range — squarely inside the audible band. The
inductor radiates acoustic noise via two mechanisms:

1. **Magnetostriction**: the core's dimensional change with B
   excites mechanical vibration of the bobbin / mounting at fsw
   and its harmonics.
2. **Winding Lorentz force**: alternating current in adjacent
   layers pushes/pulls them at fsw, exciting bobbin resonance.

For appliances (fridges, dishwashers, AC), audible inductor whine
at idle is a **direct customer complaint** — quality teams will
reject a working design that hums. Vendors' answer is normally
"design at fsw > 20 kHz" but the trade-off vs. losses, EMI, and
core cost is non-trivial. Today MagnaDesign gives the engineer
**zero visibility** into whether a chosen design will be quiet —
they ship a prototype and find out from QA.

## What changes

A new `acoustic` module exposing a fast, calibrated estimator
that takes `(spec, core, wire, material, design_result)` and
returns a `NoiseEstimate`:

- `dB_a_at_1m`: A-weighted SPL at 1 m, dominant tone (typically
  fsw or 2·fsw). Calibration to ±3 dB(A) against bench
  measurements on the validation reference designs.
- `dominant_frequencies_Hz`: list of mechanical-resonance peaks
  (fsw, 2·fsw, plus bobbin resonance picked up from a
  geometry-derived stiffness model).
- `headroom_to_threshold_dB`: distance to a configurable
  customer-grade threshold (default 30 dB(A) for "quiet
  appliance"; 45 dB(A) for industrial).
- `dominant_mechanism`: `"magnetostriction" | "winding_lorentz" |
  "bobbin_resonance"` so the engineer knows what to fix if the
  design is loud.

The model is **analytical, not FEA** — fast enough to evaluate
inside the cascade Tier-1 (microseconds per candidate). Inputs:
material magnetostrictive coefficient λ_s (bundled per material
in the catalogue), core geometry (Ae, le, mass), winding
geometry (layers, MLT), B_pk and ΔB at fsw from `DesignResult`.

UI surface: a new card on the Analysis tab showing the SPL gauge
(0 dB → 60 dB scale, color-graded), the dominant-frequency
spectrum, and the worst-case mechanism. The optimizer gains a
new objective option: **"Quietest @ idle"** ranking by
`dB_a_at_1m` so the user can pick the quiet candidate from the
Pareto front.

## Impact

- **New module**: `pfc_inductor/acoustic/` with `model.py` and
  `bobbin_resonance.py`.
- **Material catalogue extension**: optional
  `Material.magnetostrictive_lambda_s_ppm: Optional[float]` (vendor
  datasheets carry this for ferrites; powder cores have low
  intrinsic λ_s ≈ 1 ppm).
- **DesignResult extension**: `acoustic: Optional[NoiseEstimate]`,
  computed lazily.
- **Optimizer**: a new objective key `"noise"` joins the existing 6.
- **UI**: new Analysis-tab card; new option in the `OptimizerFiltersBar`
  objective combo.
- **Calibration**: piggy-back on `add-validation-reference-set` —
  capture dB(A) measurements as part of the bench protocol so the
  ±3 dB(A) accuracy claim is documented.
- **Tests**: ~8 across `tests/test_acoustic_*`.
- **Capability added**: `acoustic-noise`.
- **Effort**: ~1 week (the bobbin-resonance model is the trickiest;
  the magnetostriction estimate is closed-form per material).
