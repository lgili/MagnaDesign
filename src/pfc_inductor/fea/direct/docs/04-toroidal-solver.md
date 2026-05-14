# 04 — Toroidal Solver (closed-form `B_φ`)

**Status**: LIVE
**Code**: `physics/magnetostatic_toroidal.py`, `geometry/toroidal.py`
**Tests**: `tests/test_direct_toroidal.py`

Toroidal cores get their own dedicated path because the geometry is
**exactly solvable** in closed form — no mesh, no GetDP, no fringing
factor. The solver returns `L`, `B_pk`, `B_avg`, and energy in
microseconds and is more accurate than any FEM approximation we could
mount on top.

## Symbols

| Symbol | Meaning | Units |
|---|---|---|
| `OD`, `ID` | outer / inner diameter | m |
| `HT` | toroidal height (axial dimension) | m |
| `r_in = ID/2`, `r_out = OD/2` | inner / outer radii | m |
| `A_e` | catalog cross-section | m² (=`HT·(r_out − r_in)` for ring; aggregate otherwise) |
| `l_e` | effective magnetic path length | m (=`π(OD + ID)/2`) |
| `N` | turn count | — |
| `I` | DC current | A |
| `H_φ(r)` | tangential magnetic field at radius `r` | A/m |
| `B_φ(r) = μ·H_φ(r)` | flux density at radius `r` | T |
| `μ = μ_0·μ_r` | absolute permeability | H/m |
| `Φ` | total flux through one toroid cross-section | Wb |

## 1. Ampère's law on the symmetry path

For a wound toroid with `N` turns and current `I`, the field is purely
azimuthal (no `B_r`, no `B_z` in the ideal case). Ampère's law around
a circle at radius `r` inside the toroid window:

```
∮ H · dl  =  N · I
  H_φ(r) · 2πr  =  N · I

  H_φ(r)  =  N · I / (2πr)
  B_φ(r)  =  μ_0 · μ_r · N · I / (2πr)
```

The `1/r` dependence is the whole story. Field is **maximum at the
inner radius**, decays outward.

```
B_pk    =   B_φ(r_in)   =   μ · N · I / (2π · r_in)
```

## 2. Flux + inductance via volume integral

Flux through a single cross-section (between `r_in` and `r_out`,
height `HT`):

```
              r_out  HT
       Φ  =   ∫     ∫    B_φ(r) · dr · dz
             r_in   0


              μ · N · I · HT       r_out
          =  ────────────────  · ln(─────)
                 2π                 r_in

       L  =  N · Φ / I

              μ · N² · HT       OD
          =  ─────────────  · ln(──)
                 2π             ID
```

The factor `ln(OD/ID)` is the toroidal geometric integral — there's
no equivalent for E/EI cores, which is why those need either
reluctance or FEM.

### 2a. Volume-averaged `B`

```
              ∫ B_φ(r) · dV          μ · N · I · ln(OD/ID)
  ⟨B⟩  =  ─────────────────  =  ──────────────────────────────
              V_core               2π · (r_out − r_in)
```

For a 1:2 OD/ID ratio (typical PFC powder toroid), `⟨B⟩ ≈ 0.72 · B_pk`.

## 3. Two solve modes: geometric vs aggregate

Catalog entries split into two families:

### 3a. **Geometric** (`solve_toroidal`)
- Required fields: `OD`, `ID`, `HT`
- Used for: Ferroxcube T-series, Magnetics MS-* with explicit dims
- Returns: closed-form `L`, `B_pk` from the integrals above

### 3b. **Aggregate** (`solve_toroidal_aggregate`)
- Required fields: `A_e`, `l_e`, `A_L`
- Used for: Magnetics powder (HighFlux/Kool-Mu/MPP) — these ship
  `A_e` and `l_e` as derated values that absorb the distributed gap
- Returns: `L = A_L · N² · μ_pct(H)` with `B_pk` from flux balance

The dispatcher `solve_toroidal_from_core` (`magnetostatic_toroidal.py`)
picks the right mode based on which fields are populated. Powder
cores nearly always end up in the aggregate path because Magnetics
publishes only `A_e`/`l_e`/`A_L`.

## 4. Distributed gap (powder) handling

Powder cores have no discrete air gap — they're sintered from
insulated grains so the "gap" is distributed through the material.
The effect is captured by:

1. The catalog `A_L` already reflects the bulk distributed-gap
   permeability.
2. The `material.rolloff` block models `μ(H)` decay under DC bias
   (see `05-saturation-rolloff.md`).

For an MPP-60 toroid at `H = 50 Oe`:

```
μ_pct(H)  =  1 / (a + b · H^c)         (Magnetics fit)
           ≈  0.72        (still 72 % of low-signal μ)

L_actual  =  A_L · N² · μ_pct  =  0.72 · L_nominal
```

The toroidal solver applies this *inside* `solve_toroidal_from_core`
via `compute_mu_eff_dc_bias` so the user gets the rolled-off `L`
without needing a second call.

## 5. Discrete air gap (ferrite toroid)

Ferrite toroids are rare but exist (e.g. Ferroxcube `TG-*` series).
They can ship with a stamped cut + bonded epoxy gap. In that case the
solver:

1. Computes `R_iron = l_e / (μ_0 μ_r A_e)` from geometry + `μ_r`
   back-derived from `A_L`.
2. Computes `R_gap = l_gap / (μ_0 A_e · k_fringe)` with Roters.
3. Returns `L = N² / (R_iron + R_gap)`.

**Important**: the auto-gap path in `design/engine.py` does NOT inject
gaps into toroids — see `_CLOSED_PATH_SHAPES` gate. A toroid with no
catalog `lgap_mm` stays gapless. The above branch only fires when the
catalog explicitly ships `lgap_mm > 0`.

## 6. Partial winding coverage

The "ideal toroidal" derivation assumes the winding covers the entire
azimuthal angle (the `N · I` linkage is exact only when every turn
contributes the same `∮ dl`). Real toroids may have partial coverage —
e.g. a 270° wound section with a 90° gap for terminations.

The solver applies a coverage factor:

```
H_φ_effective  =  H_φ_full  ·  coverage_fraction
```

Empirically valid below `coverage ≈ 85 %` (above that, fringing flux
through the un-wound section becomes non-negligible and the closed
form starts to drift). This is an approximation, not a derivation — a
proper 3-D model is in the Phase 4 backlog.

## 7. Validation

vs catalog `A_L · N²` on representative powder toroids:

| Core | Catalog L (50 turns) | Direct L | Δ |
|---|---:|---:|---:|
| C058150A2 (HighFlux 125µi) | 24.7 μH | 24.7 μH | 0.0 % |
| C058120A2 (HighFlux 125µi medium) | 269 μH | 269 μH | 0.0 % |
| C058083A2 (HighFlux smallest) | 13.9 μH | 13.9 μH | 0.0 % |
| MPP 60µi (CM50-MPP) | 217 μH | 217 μH | 0.0 % |
| Kool-Mu 75µi | 511 μH | 511 μH | 0.0 % |

vs FEMMT for ferrite toroid (T 107/65/18 3C90, 20 turns @ 1 A):

| Backend | L (μH) | B_pk (T) | Wall time |
|---|---:|---:|---:|
| Direct | 1651 | 0.283 | 0.27 s |
| FEMMT | 20348 | **2.69** ⚠️ | 13.9 s |

FEMMT's `B_pk = 2.69 T` is unphysical (3C90 saturates at 0.5 T), and
its `L = 20 mH` would imply `μ_r = 30000`. The discrepancy almost
certainly comes from FEMMT's 2-D-axisymmetric approximation breaking
down on toroid geometry. The direct solver matches catalog `A_L`
(0.283 T is well within the linear regime).

## 8. When this solver is the wrong tool

- Cores with significant axial leakage (`HT >> OD − ID`): the 1/r
  Ampère law assumes the field stays in-window; tall toroids leak.
- Multi-winding designs where coupling matters: this solver assumes
  one winding.
- Saturation operation (`B_pk > 0.95 · B_sat`): the linear-`μ`
  assumption breaks; the engine flags this as a warning so the user
  picks a different core.

## 9. Code map

| Symbol | Location |
|---|---|
| `solve_toroidal` (geometric form) | `magnetostatic_toroidal.py` |
| `solve_toroidal_aggregate` (Ae/le form) | `magnetostatic_toroidal.py` |
| `solve_toroidal_from_core` (dispatcher) | `magnetostatic_toroidal.py` |
| `ToroidalInputs` / `ToroidalOutputs` | `magnetostatic_toroidal.py` |
| Toroid geometry helper | `geometry/toroidal.py` |
| Caller in runner | `runner.py:107` (`_run_toroidal_analytical`) |
