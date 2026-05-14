# 06 — Dowell AC Resistance (skin + proximity)

**Status**: LIVE (Phase 2.8)
**Code**: `physics/dowell_ac.py`, mirrors `pfc_inductor/physics/dowell.py`
**Tests**: `tests/test_direct_dowell.py`, `tests/test_direct_ac.py`

Once you switch above ~10 kHz, the DC resistance of a winding tells
you nothing useful — the AC resistance can be 5–50× higher because
of skin and proximity effects. This file documents Dowell's m-layer
formula, the Litz / foil extensions, and the contract the runner uses
to attach AC results to a DC solve.

## Symbols

| Symbol | Meaning | Units |
|---|---|---|
| `ω = 2πf` | angular frequency | rad/s |
| `σ` | conductor electrical conductivity | S/m |
| `δ` | skin depth | m |
| `d_cu` | bare copper diameter (round wire) | m |
| `h_foil` | foil thickness (foil wire) | m |
| `d_strand` | individual strand diameter (Litz) | m |
| `n_strands` | number of strands in a Litz bundle | — |
| `m` | number of winding layers | — |
| `η` | "porosity" — fraction of layer occupied by copper | — |
| `Δ`, `ξ` | Dowell non-dimensional parameters | — |
| `F_R` | AC/DC resistance ratio | — |
| `R_dc` | DC resistance | Ω |
| `R_ac = F_R · R_dc` | AC resistance | Ω |

## 1. Skin depth — the starting point

```
              ┌────────────────┐
              │       2        │
   δ   =   √ ─────────────────
              │  ω · σ · μ_0   │
              └────────────────┘
```

For copper at 20 °C (`σ = 5.96·10⁷ S/m`):

| f | δ (mm) |
|---:|---:|
| 60 Hz | 8.45 |
| 1 kHz | 2.07 |
| 10 kHz | 0.65 |
| 65 kHz | 0.258 |
| 100 kHz | 0.207 |
| 500 kHz | 0.092 |

Temperature correction (`σ` drops with T):

```
σ(T)  =  σ_20 / [1 + α(T − 20)]        α ≈ 3.9·10⁻³ /°C
```

This raises `δ` at hot operating points — the cold/hot skin-depth
spread matters for thermal-coupled solves (see
`07-thermal-coupling.md`).

`skin_depth_m` (`dowell_ac.py:82`).

## 2. Dowell's round-wire formula

Dowell's 1966 paper gives the AC/DC ratio for a winding of `m` layers
of round wire, each layer carrying the full ampere-turns of the layers
beneath it (an idealisation that's nearly exact for tightly-packed
foils and very close for round-wire bobbin layouts):

```
   Δ   =   d_cu · √(πη) / δ        (penetration parameter)


                ┌─────────────────────────────────────┐
                │             2·(m² − 1)              │
   F_R  =  ξ · │  Re₁(ξ) + ────────────── · Re₂(ξ)   │
                │                 3                   │
                └─────────────────────────────────────┘


   where ξ = (π/4) · d_cu · √η / δ
   Re₁(ξ) = sinh(2ξ) + sin(2ξ)
            ────────────────────
            cosh(2ξ) − cos(2ξ)
   Re₂(ξ) = sinh(ξ)  − sin(ξ)
            ─────────────────
            cosh(ξ)  + cos(ξ)
```

The first bracket term is **skin loss** (every layer alone), the
second is **proximity loss** (current induced by neighbouring
layers' field). The proximity term grows as `m²` and dominates for
multi-layer windings.

Implementation: `dowell_fr` (`dowell_ac.py:178`).

### 2a. Numerical example

Magnetic-wire winding, `d_cu = 0.5 mm`, `η = 0.9`, `f = 65 kHz`,
`δ = 0.258 mm`:

| `m` | `F_R` | notes |
|---:|---:|---|
| 1 | 1.05 | nearly DC |
| 2 | 1.32 | proximity kicks in |
| 4 | 2.84 | typical PFC choke |
| 8 | 9.50 | sub-optimal |
| 16 | 36.8 | bad — switch to Litz |

This is why high-N boost-PFC chokes nearly always need either Litz or
a multi-section bobbin to break the layer count.

## 3. Litz wire — `n_strands`-wise skin reduction

A Litz bundle of `n_strands` of diameter `d_strand` behaves like a
solid round wire **only** when `d_strand < δ · √2`. Below that
threshold, each strand carries quasi-uniform current and you skin-loss
the equivalent diameter of one strand.

```
d_eff_strand   ≈   d_strand   (when d_strand << δ)
F_R,Litz(m)    ≈   F_R,Dowell(d_eff_strand, m_apparent)
```

with `m_apparent` derived from how the strands stack azimuthally /
radially. The implementation uses the Albach / Tourkhani extension —
a closed-form fit calibrated against measurement on commercial Litz.

`dowell_fr_litz` (`dowell_ac.py:228`).

### 3a. Diameter selection rule

Quick rule for Litz strand selection:

```
d_strand ≤ δ · √2 ≈ 0.36 mm at 65 kHz
                 ≈ 0.13 mm at 500 kHz
```

If `d_strand >> δ`, the skin penalty per strand approaches that of a
single solid wire and the Litz is wasted copper.

## 4. Foil wire — 1-D skin only

For a foil of thickness `h_foil`:

```
Δ      =   h_foil / δ
F_R    =   Δ · (sinh Δ + sin Δ) / (cosh Δ − cos Δ)
```

Foil wins when:
- Single layer (no proximity penalty)
- Thin (`h ≤ δ`) so skin is dominated by the foil's full cross-section
- Wide aspect ratio (`width >> δ`) so edge effects are negligible

Common in planar transformers; rare in PFC boost chokes (round wire is
mechanically easier).

`dowell_fr_foil` (`dowell_ac.py:285`).

## 5. Integration with the direct backend runner

The AC pass is opt-in via `frequency_Hz`:

```python
result = run_direct_fea(
    core=core, material=material, wire=wire,
    n_turns=N, current_A=I_dc_pk,
    frequency_Hz=65_000,          # ← triggers Dowell pass
    n_layers=4,
    current_rms_A=2.3,            # for P_cu_ac
    T_winding_C=85,               # σ correction (optional)
)

# result fields populated:
#   result.R_ac_mOhm     → F_R · R_dc(T)
#   result.L_ac_uH       → L_dc · μ'(f) / μ_initial   (if complex_mu_r)
#   result.P_cu_ac_W     → I_rms² · R_ac
#   result.P_core_W      → pass-through from caller
```

`_apply_dowell_ac_if_requested` (`runner.py:399`).

## 6. Validation

vs analytical engine's `pfc_inductor.physics.dowell.evaluate`:

```
Boost PFC 65 kHz, d_cu = 0.5 mm, η = 0.9, T = 85 °C, AWG 24 Litz × 80
strands × 5 layers:

                Direct backend     Analytical engine
F_R              4.21                4.21         (0.0 % Δ)
R_ac (mΩ)       380.5               380.5         (0.0 % Δ)
L_ac (μH)       498                 498           (0.0 % Δ)
P_cu_ac (W)     2.01                2.01          (0.0 % Δ)
```

The two implementations share the same kernel
(`pfc_inductor/physics/dowell.py`); the direct backend's `dowell_ac.py`
is a wrapper that owns the result-projection logic (see "wrapper
rationale" below).

vs Pflueger (commercial Litz manufacturer) tabulated data:

```
1.5 mm² Litz, 100 strands, 65 kHz:
  Pflueger spec:  R_ac/R_dc = 1.25
  Direct (this):  R_ac/R_dc = 1.22       (2.4 % under)
```

## 7. Why a wrapper module, not a direct import

`physics/dowell_ac.py` reads like a thin re-export of the engine's
`physics/dowell.py`. The wrapping is deliberate:

1. It owns the **result projection** — packaging `F_R`, `R_ac`, `ξ`,
   `δ` into `DowellOutputs` so callers don't have to assemble the
   dataclass.
2. It owns the **runner-side glue** — temperature-corrected σ, layer
   count → m mapping, Litz strand-vs-bundle decisions.
3. It buffers the engine module from FEA-side wrap concerns: future
   AC-FEM postops (Phase 2.1 stretch) will populate `L_ac` from a
   GetDP `MagDyn_a` solve instead of from the closed-form Dowell, but
   the same `DowellOutputs` contract is preserved.

## 8. Code map

| Symbol | Location |
|---|---|
| `DowellOutputs` | `dowell_ac.py:72` |
| `skin_depth_m` | `dowell_ac.py:82` |
| `dowell_fr` (round wire) | `dowell_ac.py:178` |
| `dowell_fr_litz` | `dowell_ac.py:228` |
| `dowell_fr_foil` | `dowell_ac.py:285` |
| `evaluate_ac_resistance` (one-shot) | `dowell_ac.py:178` |
| Runner glue | `runner.py:399 (_apply_dowell_ac_if_requested)` |
| Engine equivalent | `pfc_inductor/physics/dowell.py` |

## 9. References

- Dowell, P.L. (1966), "Effects of eddy currents in transformer
  windings", *Proc. IEE* 113(8) — the original derivation.
- Albach, M. (1992), "Two-dimensional calculation of winding losses
  in transformers", *PESC* — multi-stranded extension.
- Tourkhani, F. & Viarouge, P. (2001), "Accurate analytical model of
  winding losses in round Litz wire windings", *IEEE Trans. Magn.*
- Ferreira, J. A. (1992), "Analytical computation of AC resistance of
  round and rectangular Litz wire windings", *IEE Proc. B* — foil
  extension.
- McLyman, *Transformer and Inductor Design Handbook*, ch. 7 — the
  practical-engineering view.
