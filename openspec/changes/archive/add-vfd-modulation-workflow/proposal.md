# Add variable-frequency-drive modulation workflow

## Why

MagnaDesign's primary user designs PFC inductors for **variable-
frequency-drive (VFD) compressor inverters** — fridges, freezers,
HVAC. The compressor speed varies continuously to match thermal
load, which means **the PFC stage operates over an fsw band, not a
single fsw**. Today's `Spec.f_sw_kHz` is a scalar, the engine
solves at exactly that fsw, and the optimizer ranks designs as if
fsw were fixed — but a design that's optimal at 65 kHz might
saturate at 25 kHz (low speed, full DC bias) or run hot at 8 kHz
(near-line, audible band).

Without modelling the modulation envelope:

- The engine quietly picks the wrong optimum (best-case fsw).
- Worst-case loss / temperature / B_pk are under-reported.
- IEC 61000-3-2 line-cycle harmonics shift across the speed range
  and the existing compliance check evaluates only one point.
- Audible-noise predictions (see `add-acoustic-noise-prediction`)
  cannot resolve which speeds excite the worst hum.

Production compressor lines run from 1500 to 4500 RPM (a 3× speed
swing); the corresponding fsw band is 4×–6× wide. Every serious
VFD-PFC design today gets validated at minimum-, mid-, and
maximum-fsw by hand. MagnaDesign should bake this into the spec.

## What changes

A new optional `Spec.fsw_modulation` field describing the band:

```python
Spec.fsw_modulation: Optional[FswModulation] = None

class FswModulation(BaseModel):
    fsw_min_kHz: float
    fsw_max_kHz: float
    profile: Literal["uniform", "triangular_dither", "rpm_band"]
    n_eval_points: int = 5  # how many fsw points the engine evaluates
    # Optional VFD-specific:
    rpm_min: Optional[float]
    rpm_max: Optional[float]
    pole_pairs: Optional[int]  # 2 ⇒ fsw = rpm_to_fsw(rpm) when rpm_band
```

When set, `design()` evaluates the engine at every modulation
point and returns a `BandedDesignResult` that exposes:

- `worst_case`: the single point that violates each metric the
  most (per-metric different points may win).
- `nominal`: results at `(fsw_min + fsw_max) / 2`.
- `band`: the per-point full results, for plotting.
- `flagged_points`: any modulation point that fails feasibility,
  with the reason.

UI surface: a new sub-form inside the Spec drawer ("Modulation…")
that defaults off; when on, the `Resumo` strip shows the
worst-case envelope instead of a single value, the analysis
tab plots `Loss(fsw)` / `Bpk(fsw)` / `dT(fsw)` curves, and the
optimizer ranks designs by their worst-case across the band — not
their nominal performance.

## Impact

- **Spec extension**: new optional `fsw_modulation` field.
  Backward-compatible: `None` → today's behaviour exactly.
- **New module**: `pfc_inductor/topology/modulation.py` with the
  evaluation loop. Each topology adapter gains an
  `evaluate_band(spec, …)` method (default uses
  `evaluate(spec_at_each_fsw)`).
- **Engine**: `design()` returns `Union[DesignResult,
  BandedDesignResult]` driven by the spec's modulation field.
- **Optimizer**: `sweep` and cascade both honour the band; the
  ranking key is computed from `worst_case` not `nominal` when a
  band is set.
- **UI**: new spec-drawer subsection, new Analysis-tab plot,
  worst-case envelope on the KPI strip when active.
- **Datasheet**: extra page with the per-fsw curves when active.
- **Tests**: ~12 new across `tests/test_modulation_*` covering
  the evaluation loop, the Spec round-trip, the cascade integration,
  and a regression on a known compressor-VFD design.
- **Capability added**: `vfd-modulation`.
- **Effort**: ~1.5 weeks.
