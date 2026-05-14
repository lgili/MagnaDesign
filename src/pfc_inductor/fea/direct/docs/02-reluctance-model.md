# 02 — Reluctance Model

**Status**: LIVE — default solver
**Code**: `physics/reluctance_axi.py`
**Tests**: `tests/test_direct_reluctance.py`, `tests/test_closed_path_no_autogap.py`

The reluctance model is the workhorse of the direct backend. It
returns `L`, `B_pk`, energy, and the fringing factor in **under a
millisecond** for any core in the catalog. The remaining 11 files in
this directory exist either to feed this solver (geometry, μ_eff) or
to layer additional physics on top (AC, thermal).

## Symbols

| Symbol | Meaning | Units | Source |
|---|---|---|---|
| `N` | turn count | — | input |
| `I` | DC current at operating point | A | input |
| `μ_0` | vacuum permeability | 4π×10⁻⁷ H/m | constant |
| `μ_r` | relative permeability of core | — | material or back-derived from `A_L` |
| `A_e` | effective core cross-section | m² | catalog (`mm²` × 10⁻⁶) |
| `l_e` | effective magnetic path length | m | catalog (`mm` × 10⁻³) |
| `l_gap` | physical air gap | m | catalog or auto-sized |
| `k_fringe` | Roters fringing factor | — | computed (see `03-fringing-roters.md`) |
| `R_iron` | iron-path reluctance | A·t/Wb | `l_e / (μ_0 μ_r A_e)` |
| `R_gap` | gap reluctance with fringing | A·t/Wb | `l_gap / (μ_0 A_e k_fringe)` |
| `Φ` | core flux | Wb | `N · I / R_total` |
| `L` | inductance | H | `N² / R_total` |
| `B_pk` | peak flux density | T | `Φ / A_e` |

## 1. Core physics

Faraday + Ampère + lumped magnetic circuit gives the well-known
reluctance form:

```
                    N·I
flux:     Φ  =  ──────────────
                R_iron + R_gap


inductance:    L  =  N · Φ / I  =  N² / R_total


reluctance:    R_iron = l_e / (μ_0 · μ_r · A_e)
               R_gap  = l_gap / (μ_0 · A_e · k_fringe)
```

For a closed core (`l_gap = 0`), only `R_iron` matters and the
formula collapses to:

```
L = μ_0 · μ_r · N² · A_e / l_e        ≡   A_L,closed · N²
```

where `A_L,closed = μ_0 μ_r A_e / l_e` is the "inductance per turn²"
the manufacturer publishes for ungapped cores.

## 2. Two solve modes: catalog-AL fast path vs explicit reluctance

The solver supports two routes through the same physics:

### 2a. **Catalog-AL fast path** (default when `A_L > 0`)

When the core has a manufacturer-measured `A_L` (which captures any
distributed gap, fringing, and finite-μ effects already), we use:

```
L_uH = A_L_nH · N² · μ_pct(H) · 10⁻³
B_pk = L · I / (N · A_e)        (flux-balance form)
```

`μ_pct(H)` is the DC-bias rolloff (see `05-saturation-rolloff.md`).
This route returns `method="catalog_AL"` in the result.

**Why it's the fast path**: `A_L` is experimentally measured, so it
already absorbs all the geometric corrections we'd otherwise have to
model. It matches `analytical_engine.inductance_uH(N, AL, μ_pct)`
*identically* — which is what makes engine-vs-direct parity possible.

### 2b. **Explicit reluctance** (fallback)

When the user overrides the gap (`gap_mm` kwarg), or the core has no
`A_L`, the solver constructs the reluctance circuit from first
principles:

```
                       μ_0 · A_e
L  =  N²  ·  ────────────────────────────────
              l_e / μ_r  +  l_gap / k_fringe
```

`μ_r` is back-derived from the catalog `A_L` of the closed-equivalent
core (`reluctance_axi.py:_mu_r_from_catalog_AL`) — this makes the
explicit-reluctance result fall back to catalog physics when the user
isn't overriding anything.

## 3. Algorithm

`solve_reluctance_from_core` (`reluctance_axi.py:246`):

```python
def solve_reluctance_from_core(core, material, n_turns, current_A,
                               gap_mm=None, apply_dc_bias_rolloff=True,
                               fringing_model="roters",
                               use_catalog_AL=True) -> ReluctanceOutputs:

    # ── Fast path ─────────────────────────────────────────────
    AL = core.AL_nH
    user_overrode_gap = (gap_mm is not None)
    if use_catalog_AL and AL > 0 and not user_overrode_gap:
        μ_pct = 1.0
        if apply_dc_bias_rolloff and material.rolloff is not None:
            _, μ_pct = compute_mu_eff_dc_bias(material=material,
                                              n_turns=n_turns,
                                              current_A=current_A,
                                              le_m=core.le_mm * 1e-3,
                                              fallback_mu_r=1.0)
        L_H  = AL * 1e-9 * n_turns**2 * μ_pct
        B_pk = L_H * current_A / (n_turns * core.Ae_mm2 * 1e-6)
        return ReluctanceOutputs(L_uH=L_H*1e6, B_pk_T=abs(B_pk),
                                  k_fringe=1.0, method="catalog_AL", ...)

    # ── Explicit reluctance ───────────────────────────────────
    μ_r = _mu_r_from_catalog_AL(core, material.mu_initial)
    return solve_reluctance(ReluctanceInputs(
        n_turns=n_turns, current_A=current_A,
        mu_r_core=μ_r, Ae_mm2=core.Ae_mm2, le_mm=core.le_mm,
        lgap_mm=gap_mm or 0, center_leg_w_mm=√A_e,
        fringing_model=fringing_model,
    ))
```

The lower-level `solve_reluctance(ReluctanceInputs)` (line 140) is
pure physics, callable without a `Core` instance — useful for tests
and unit-checking.

## 4. The `B_pk` calculation

We give two expressions of `B_pk`, mathematically identical when
self-consistent:

```
Flux-balance form:     B_pk  =  L · I / (N · A_e)
Reluctance form:       B_pk  =  N · I / (R_total · A_e)  =  μ_0 N I / l_eff
```

The catalog-AL fast path uses the flux-balance form (no `μ_r` needed).
The explicit-reluctance form is used inside `solve_reluctance` where
`R_total` is already known.

For boost-PFC and line-reactor topologies, the engine wraps `B_pk`
with topology-specific helpers (see
`07-thermal-coupling.md` cross-reference + `topology/line_reactor.py`)
because the operating-point current differs (peak vs RMS, with vs
without DC bias).

## 5. Back-deriving `μ_r` from catalog `A_L`

For a closed core, `A_L = μ_0 μ_r A_e / l_e`. Solving for `μ_r`:

```
μ_r  =  A_L · l_e / (μ_0 · A_e)        (closed core only)
```

`_mu_r_from_catalog_AL` (`reluctance_axi.py:194`) applies this only
when `core.lgap_mm == 0`. For pre-gapped cores the catalog `A_L`
already includes the gap, so back-deriving would double-count.

This is one of the calibration tricks: instead of trusting the
material's `μ_initial` field (which is often a conservative spec-sheet
value), we use the `A_L` the manufacturer actually measured. On
Ferroxcube 3C90 toroids this lifts the effective `μ_r` from 1416
(catalog `mu_initial`) to ~2300 (implied by `A_L`), which matches the
datasheet curve at the test point.

## 6. Validation

Boost PFC 230V→400V/600W at 65 kHz, 29 feasible cores (ferrite +
powder, every shape from EE to UR):

| Metric | Value |
|---|---|
| `\|L%err\|` median (vs direct backend) | **0.22%** |
| `\|L%err\|` max | 6.3 % |
| Cores within 5 % | **26 / 29** |
| Cores within 15 % | **27 / 29** |

vs catalog `A_L · N²` ground truth (8 representative cores):

| Material | Core | Catalog L | Direct L | Δ |
|---|---|---:|---:|---:|
| 3C90 | PQ40/40 | 822 μH | 822 μH | 0.0 % |
| 3C90 | PQ50/50 | 1342 μH | 1342 μH | 0.0 % |
| N87 | E100/60/28 | 728 μH | 728 μH | 0.0 % |
| HighFlux | C058150A2 toroid | 24.7 μH | 24.7 μH | 0.0 % |
| Kool-Mu 75 | 50 mm tor. | 510 μH | 510 μH | 0.0 % |
| MPP 60 | toroid | 217 μH | 217 μH | 0.0 % |
| 3C94 | ETD49 | 195 μH | 196 μH | 0.5 % |
| 3C90 | E55/28 | 1.10 mH | 1.13 mH | 2.7 % |

Source: `scripts/benchmark_shapes_vs_femmt.py` (FEMMT comparison) and
the boost-PFC sweep in `09-validation-benchmarks.md`.

## 7. Where this solver fails (briefly)

- **Closed toroid + injected gap**: previously broke on toroidal
  ferrites because the engine auto-gapped a closed core. Fixed by
  `_CLOSED_PATH_SHAPES` gate (see `08-engine-vs-direct-parity.md` §4).
- **Roters extrapolation at `l_gap/w_leg > 1`**: factor is clamped at
  3.0; for huge gaps the model is invalid. See
  `03-fringing-roters.md` §4 and `10-known-limitations.md` §2.
- **Magnetics LP catalog mismatch**: 2 cores show >8000 % error.
  Catalog import bug, not solver bug. Tracked separately.

## 8. Code map

| Symbol | Location |
|---|---|
| `ReluctanceInputs` dataclass | `reluctance_axi.py:74` |
| `ReluctanceOutputs` dataclass | `reluctance_axi.py:108` |
| `fringing_factor_roters` | `reluctance_axi.py:124` |
| `solve_reluctance` (pure physics) | `reluctance_axi.py:140` |
| `_mu_r_from_catalog_AL` | `reluctance_axi.py:194` |
| `solve_reluctance_from_core` | `reluctance_axi.py:246` |
| Fast-path catalog-AL block | `reluctance_axi.py:278–313` |
