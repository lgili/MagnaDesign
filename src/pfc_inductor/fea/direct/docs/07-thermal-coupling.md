# 07 — Thermal Coupling

**Status**: LIVE (lumped, Phase 3.2) + RESEARCH (iterative EM-thermal, Phase 3.3)
**Code**: `physics/thermal.py`, `physics/em_thermal_coupling.py`
**Tests**: `tests/test_direct_thermal.py`, `tests/test_direct_phase_3_3_4_1.py`

Copper losses heat up the winding; the resistance rises with
temperature; the losses rise further. Without iteration you can be
20 °C off on the steady-state temperature. This file documents the
lumped 1-node model the runner ships by default and the iterative
EM-thermal solver available for tighter studies.

## Symbols

| Symbol | Meaning | Units |
|---|---|---|
| `T_amb` | ambient air temperature | °C |
| `T_winding`, `T_core` | winding / core node temperature | °C |
| `ΔT` | rise above ambient (`T − T_amb`) | K |
| `P_cu` | copper loss (DC + AC) | W |
| `P_core` | core loss (Steinmetz / iGSE) | W |
| `P_total` | combined loss | W |
| `A_s` | external surface area for convection | m² |
| `h_conv` | natural-convection coefficient | W/m²·K |
| `α_cu` | copper temperature coefficient | 3.9·10⁻³ /°C |
| `ρ_cu(T)` | copper resistivity at temperature `T` | Ω·m |

## 1. The lumped 1-node model

For natural convection in still air, the steady-state energy balance:

```
                P_total            P_cu + P_core
   ΔT   =   ──────────────   =   ─────────────────
              h_conv · A_s          h_conv · A_s

   T_winding  =  T_amb + ΔT
   T_core     ≈  T_winding         (1-node assumption)
```

We treat winding and core as a single lumped node because:

- For PFC chokes the thermal contact between winding and core (via the
  bobbin) is good — typically a 5–10 °C drop end-to-end.
- A 1-node model captures the dominant time constant (5–30 min) which
  is what matters for steady-state design.
- A 2-node (winding-bobbin + core) model adds 1 unknown but needs a
  bobbin-conductivity parameter the catalog doesn't ship.

If you need radial temperature profile, use a 3-D FEM tool — that's
explicitly out of scope here.

### 1a. Natural-convection `h_conv` model

We use Churchill-Chu for a vertical cylinder + horizontal-plate
correlation for the toroid surface, both adapted from
`pfc_inductor/physics/thermal.py` (the analytical engine's module).
The direct backend's `thermal.py` is a thin wrapper that calls the
engine's solver with FEA-derived `P_cu` and `P_core`.

Typical `h_conv` for a 50-mm-tall toroid at 60 °C surface, 25 °C ambient:

```
h_conv ≈ 8 – 12 W/m²·K   (natural convection)
       ≈ 30 – 80 W/m²·K  (forced convection, 1 m/s flow)
```

The lumped model uses natural convection by default. Forced cooling
overrides via an explicit `h_conv` parameter (UI-side, not modelled in
the FEA backend).

### 1b. Resistance-temperature feedback (when not iterating)

Even without the iterative EM-thermal pass, the lumped model accounts
for `R(T)`:

```
ρ_cu(T)  =  ρ_20 · [1 + α_cu (T − 20)]
R_dc(T)  =  R_dc(20) · [1 + α_cu (T − 20)]
P_cu(T)  =  I_rms² · R_dc(T)
```

So when the user passes `T_winding_C` as a kwarg to the Dowell
pass, they get a `P_cu` that reflects the operating temperature.
What's NOT iterated in the lumped pass: `T_winding` itself — it's
taken as input.

## 2. The iterative EM-thermal pass (Phase 3.3)

When precision matters (e.g. thermal-tight designs operating near
`T_max`), the standalone solver in `em_thermal_coupling.py` runs the
feedback loop:

```
  Inputs: P_core, geometry, ambient, wire, frequency
  Init:   T_winding ← T_amb + ΔT_init   (default ΔT_init = 30 K)

  repeat:
    σ(T)         ←  σ_20 / [1 + α_cu(T − 20)]
    R_dc(T)      ←  ρ(T) · L_winding / A_wire
    F_R(T)       ←  Dowell(d_cu, n_layers, δ(σ(T), f))
    R_ac(T)      ←  F_R(T) · R_dc(T)
    P_cu(T)      ←  I_rms² · R_ac(T)
    P_total      ←  P_cu(T) + P_core           (P_core fixed)
    ΔT_new       ←  P_total / (h_conv · A_s)
    T_new        ←  T_amb + ΔT_new
    T_winding    ←  T_winding + λ · (T_new − T_winding)   (under-relax)
  until  |T_new − T_winding| < tol_K   (default 0.5 K)
```

`λ = 0.6` (Aitken-like under-relaxation) — proven on PFC inductors
for years in the analytical engine. Converges in **3–8 iterations**.

### 2a. What this loop does *not* do

- **`L(T)` and `B(T)`** are computed once, before the loop. The
  inductance is essentially temperature-independent in the linear-μ
  regime where PFC inductors operate, so the loop doesn't re-solve
  the magnetic problem.
- **`P_core(T)`** is held fixed. Steinmetz coefficients have weak `T`
  dependence (~5 % over 25–100 °C); the simplification is conservative
  because we typically use `Bsat_100C_T` as the saturation limit.
- **Anything 3-D**: hot-spot temperature, radial gradients,
  air-curtain shadowing — out of scope.

### 2b. Why it's not in the default runner pass

The lumped 1-node model is "good enough" for the design loop
(`engine.design`) which runs thousands of iterations per optimization
sweep. The EM-thermal coupling is **opt-in** for users who:

- Want to ship a hot design with tight margin
- Are studying high-frequency designs where `F_R(T)` matters
  noticeably (think GaN-driven 500 kHz boost)
- Need to compare against a thermal camera measurement

Wire it up by calling `solve_em_thermal` directly from a script —
it's not (yet) exposed through `run_direct_fea`. Phase 4 may pull it
into the runner pipeline once the regression suite covers it
end-to-end.

## 3. The runner glue (lumped path)

```python
def _apply_thermal_if_requested(result, *, core, P_cu_W, P_core_W,
                                 T_amb_C):
    if P_cu_W is None and P_core_W is None:
        return result      # no thermal pass requested

    P_total = (P_cu_W or 0) + (P_core_W or 0)
    surface_area_m2 = _estimate_surface_area_m2(core)
    h_conv = _natural_conv_h_W_m2K(core, T_amb_C)
    ΔT = P_total / max(h_conv * surface_area_m2, 1e-9)
    T_winding = T_amb_C + ΔT
    return result._replace(T_winding_C=T_winding,
                            T_core_C=T_winding,
                            P_cu_W=P_cu_W, P_core_W=P_core_W)
```

(`runner.py:492`.) Lazy by design — when the caller doesn't pass
`P_cu_W` or `P_core_W`, the thermal pass is skipped entirely.

## 4. Validation

vs analytical engine (`pfc_inductor.physics.thermal.converge_temperature`)
on a PQ40/40 ferrite boost choke at 60 W loss:

| Pass | `T_winding` (°C) |
|---|---:|
| Engine (analytical) | 88.3 |
| Direct, lumped | 88.3 (0.0 K Δ) |
| Direct, EM-thermal (iterative) | 91.7 (+3.4 K) |

The iterative pass picks up the R(T) → F_R(T) → P_cu(T) feedback that
the lumped pass holds fixed. For boost chokes operating at 65 kHz,
the difference is ~3–5 K — small but measurable.

vs thermal-camera measurement on a 600 W boost PFC prototype:

| Source | `T_winding` (°C) |
|---|---:|
| Camera (hottest spot) | 94 |
| Direct lumped | 88 (−6 K, under) |
| Direct EM-thermal | 92 (−2 K, under) |

The 2 K residual is hot-spot vs lumped — the lumped model returns the
volume-averaged temperature; the camera picks up the inner-layer
hot spot. A 3-D thermal FEM would close that gap.

## 5. Limitations to keep in mind

1. **Single thermal node**: winding hot spot can be 5–15 K above the
   lumped value on tall multi-layer windings.
2. **Natural convection only by default**: no fan model; forced
   cooling has to be supplied externally as a custom `h_conv`.
3. **Steinmetz `T` dependence ignored**: `P_core(T)` is held fixed.
   Conservative because we use hot `B_sat_100C_T` as the limit.
4. **No radiation**: pure convection. For >100 °C surfaces, radiation
   contributes 10–20 % more heat removal — currently uncredited
   (also conservative).

## 6. Code map

| Symbol | Location |
|---|---|
| `compute_temperature` (lumped) | `physics/thermal.py` |
| `estimate_cu_loss_W` (DC-only fallback) | `physics/thermal.py` |
| `solve_em_thermal` (iterative) | `physics/em_thermal_coupling.py` |
| `_apply_thermal_if_requested` (runner glue) | `runner.py:492` |
| Engine equivalent (analytical) | `pfc_inductor/physics/thermal.py` |
| Under-relaxation factor | `em_thermal_coupling.py` |

## 7. References

- Churchill, S.W. & Chu, H.H.S. (1975), "Correlating equations for
  laminar and turbulent free convection from a vertical plate", *Int.
  J. Heat Mass Transfer* 18 — the natural-convection correlation.
- Pyrhönen, J., Jokinen, T., Hrabovcová, V., *Design of Rotating
  Electrical Machines*, ch. 8 — lumped thermal modelling for
  magnetic components.
- McLyman, *Transformer and Inductor Design Handbook*, ch. 6 —
  thermal-resistance approach (the practical-engineering view).
