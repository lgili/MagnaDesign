# 03 — Fringing Factor (Roters / McLyman)

**Status**: LIVE — critical for engine-vs-direct parity
**Code**: `physics/reluctance_axi.py:124`, mirrored at `design/engine.py:_fringing_factor_roters`
**Tests**: `tests/test_closed_path_no_autogap.py::test_fringing_factor_matches_direct_backend_implementation`

The fringing factor is small in the equation but huge in consequence.
Get it wrong and L is off by 30–200 %; get the engine and the direct
backend to disagree on it and the user sees a "30 % discrepancy" with
no obvious cause. This file explains the formula, the iterative gap
sizing built on top, and why two copies of the same function live in
two modules.

## 1. The physics — why fringing matters

Around a discrete air gap in a magnetic circuit, the flux lines bulge
out into the surrounding window/air. That extra cross-section
through which flux flows means the gap behaves **as if** it were
shorter than its physical length. The factor by which it's shortened
is `k_fringe`:

```
                  l_gap
R_gap   =   ───────────────────       (with fringing)
              μ_0 · A_e · k_fringe


k_fringe   ≥   1.0     (more fringing → larger k → smaller R_gap → larger L)
```

For a typical 1-mm air gap on a PQ40-class ferrite, `k_fringe ≈ 1.4`,
meaning the effective gap reluctance is ~30 % lower than the
no-fringing formula predicts. That is precisely the magnitude of error
we observed when the engine ignored fringing while the direct backend
applied it.

## 2. The Roters / McLyman closed-form

We use the classical approximation (Roters 1941, popularised by
McLyman's transformer-design handbook):

```
                          ┌───────────┐
                          │   l_gap   │
k_fringe   =   1   +   2·√│ ────────  │
                          │ w_leg     │
                          └───────────┘
```

| Symbol | Meaning |
|---|---|
| `l_gap` | physical air-gap length (mm) |
| `w_leg` | centre-leg width perpendicular to the gap (mm) |

The factor is **clamped to `[1.0, 3.0]`** in code:

- `< 1.0` is impossible (would imply negative gap area).
- `> 3.0` is outside the formula's validity (full 3-D FEM needed).

```python
def fringing_factor_roters(lgap_mm, w_centerleg_mm) -> float:
    if lgap_mm <= 0 or w_centerleg_mm <= 0:
        return 1.0
    k = 1.0 + 2.0 * math.sqrt(lgap_mm / w_centerleg_mm)
    return max(1.0, min(k, 3.0))
```

(`reluctance_axi.py:124` and `design/engine.py:_fringing_factor_roters`.)

## 3. Where `w_leg` comes from

Most catalog entries don't ship an explicit `centre_leg_width_mm`
field, so we **estimate it from `A_e`** assuming a roughly square /
circular centre leg:

```
w_leg ≈ √A_e        (Ae in mm² → w in mm)
```

`_estimate_center_leg_width_mm` (`design/engine.py`). For a non-square
leg (e.g. a 1:2 rectangle) the estimate sits between the short and
long side — close enough for fringing, which only cares about the
order of magnitude. The direct backend's reluctance solver uses the
same approximation, which keeps the two paths in lock-step.

## 4. Iterative gap sizing — why the engine had to learn fringing

This is the more subtle part. The analytical engine often *invents* an
air gap for a saturating ferrite design (see
`08-engine-vs-direct-parity.md` §3). The naive formula:

```
l_gap   =   l_eff_required   −   l_e / μ_r        (no fringing)
```

under-sizes the gap, because fringing flux augments the actual
inductance. To deliver `L = L_target` on the real hardware, the
physical gap must be larger by exactly `k_fringe`. But `k_fringe`
itself depends on `l_gap` — fixed-point iteration:

```
l_gap_0      =   l_eff_required − l_e/μ_r          (no-fringe estimate)
repeat:
    k_n      =   roters(l_gap_n, w_leg)
    l_gap_n+1 =  (l_eff_required − l_e/μ_r) · k_n
until |l_gap_n+1 − l_gap_n| < 0.1 μm
```

Convergence is monotonic (Roters is slowly varying) and typically
takes **3–5 iterations** to settle. `_solve_lgap_with_fringing`
(`design/engine.py`) caps at 8 iterations with a 0.1 μm tolerance.

### 4a. Validation of the iteration

Boost PFC sweep, 11 ferrite cores with auto-gap:

| Core | Initial gap (no-fringe) | Converged gap | k_fringe | Δ vs no-fringe |
|---|---:|---:|---:|---:|
| ETD49 | 3.39 mm | 8.63 mm | 1.97 | +154 % |
| PQ35/35 | 5.57 mm | 16.70 mm | 2.31 | +200 % (clamped) |
| PQ40/40 | 5.01 mm | 15.04 mm | 2.21 | +200 % |
| PQ50/50 | 2.86 mm | 6.20 mm | 1.79 | +117 % |
| E100/60/28 | 1.23 mm | 1.87 mm | 1.43 | +52 % |
| EP10 (catalog 0.08mm) | 0.08 mm | 0.09 mm | 1.23 | +13 % |
| RM10 (catalog 0.74mm) | 0.74 mm | 0.75 mm | 1.50 | +1 % |
| PM114 | 0.50 mm | 0.64 mm | 1.23 | +28 % |
| UI25-16-6 | 1.79 mm | 3.22 mm | 1.60 | +80 % |

For PQ-family cores the gap nearly doubles or triples once fringing
is honoured. That magnitude is consistent with the L disagreement we
saw before the fix (median 166 %).

### 4b. Effect on `L`

After the iteration converges, `L_engine` and `L_direct` agree:

```
                    Before fringing-aware       After fringing-aware
                    engine sizing               engine sizing
Boost PFC ferrites:
  median |L%err|       166 %                       0.22 %
  max |L%err|         1577 %                       6.3 %
  cores within 5 %    0 / 29                       26 / 29
```

(Source: `scripts/benchmark_engine_vs_direct.py` — written in this
session's commit `84409b5`.)

## 5. Why TWO copies of the function exist

Both `design/engine.py` and `fea/direct/physics/reluctance_axi.py`
define `_fringing_factor_roters` / `fringing_factor_roters`. This is
**intentional duplication**, not an oversight. Reasons:

1. **`design.engine` must not import `fea`.** The analytical engine is
   on the design hot-path and a single FEA-side `import gmsh` would
   slow startup by 50 ms. Keeping `engine` free of FEA imports keeps
   the optimizer fast.
2. **The duplication is enforced by a parity test**:

   ```python
   def test_fringing_factor_matches_direct_backend_implementation():
       for lgap, w in [(0.5, 14), (3.4, 14.4), (5.6, 13.1),
                        (10.0, 5.0), (0.0, 14.0)]:
           assert engine_k(lgap, w) == pytest.approx(direct_k(lgap, w))
   ```

   Anyone changing the formula must change both copies — the test
   will fail otherwise. Bit-for-bit parity is the contract; physical
   equivalence is not enough.

## 6. Beyond the clamp — what to do when `k_fringe > 3`

The formula is valid for `l_gap << w_leg`. When `l_gap > w_leg`, the
flux pattern is no longer a simple bulge around the gap; it's a fully
3-D field with leakage into the window. The clamp at 3.0 prevents
runaway numbers, but it's a **soft warning** the design is outside
the model's regime, not a fix.

Concrete cases where we hit the clamp:

| Core | Synthetic gap | Leg width | `l_gap/w_leg` | k clamp? |
|---|---:|---:|---:|---|
| E10555 (pre-fix) | 86 mm | 11.6 mm | 7.4 | ✅ clamped |
| EFD10 ungapped | 58 mm | 4.5 mm | 12.9 | ✅ clamped |
| LP cores | 0 mm | 13 mm | 0 | n/a |

The fix for E10555 et al was the closed-shape gate in §3 of
`08-engine-vs-direct-parity.md`: these designs are infeasible and the
engine should warn, not invent a 86-mm gap. After that gate landed,
the clamp is reached only by genuinely bad designs (and the warning
fires).

## 7. Alternatives we considered and rejected

- **Schwarz–Christoffel transformation (exact 2-D fringing)**: closed
  form for an idealised gap geometry. ~5× more accurate than Roters
  but requires `w_leg`, `l_gap`, and `l_window` — fields the catalog
  doesn't ship. Deferred until 3-D mesh-based FEA (Phase 4.2).
- **Ferreira's edge-effect model**: similar accuracy improvement, same
  data-availability problem.
- **Constant `k_fringe = 1.15`** (the "flat" model option in code):
  works for tiny gaps (< 0.2 mm) but misses 30 % on PQ-class cores.
  Available via `fringing_model="flat"` for cross-checks.

Roters is the sweet spot: needs only `(l_gap, w_leg)`, both available
or trivially derivable; agrees with measurement to 10–15 % across the
PFC-relevant gap range (0.1–3 mm).

## 8. Code map

| Symbol | Location |
|---|---|
| `fringing_factor_roters` (direct backend) | `physics/reluctance_axi.py:124` |
| `_fringing_factor_roters` (engine — mirror) | `design/engine.py` |
| `_estimate_center_leg_width_mm` | `design/engine.py` |
| `_solve_lgap_with_fringing` (iteration) | `design/engine.py` |
| Application in fast path | `physics/reluctance_axi.py:280–313` |
| Application in `_resolve_gap_and_AL` | `design/engine.py` |
| Parity test (bit-for-bit) | `tests/test_closed_path_no_autogap.py` |

## 9. Further reading

- McLyman, *Transformer and Inductor Design Handbook*, Ch. 7 (fringing
  flux around an air gap).
- Roters, *Electromagnetic Devices* (1941), Ch. 5 — original
  derivation of the empirical fit.
- Mohan, *Power Electronics*, Ch. 30 — practical numbers for SMPS
  inductors.
