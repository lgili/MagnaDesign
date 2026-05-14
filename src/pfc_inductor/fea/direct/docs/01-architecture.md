# 01 — Architecture

**Status**: LIVE
**Code**: `runner.py`, `models.py`
**Tests**: `tests/test_fea_dispatch_direct.py`

## 1. Why this backend exists

We replaced FEMMT with an in-tree backend for four engineering reasons:

| Concern | FEMMT | Direct |
|---|---|---|
| Shapes supported | 6/12 catalog shapes | **12/12** (every shape with `A_e`/`l_e`) |
| Median solve time | ~12 s | **~0.3 s** (40× faster) |
| Median accuracy vs FEMMT | (reference) | within 10 % on comparable cases |
| Accuracy vs catalog `A_L` | 8–20 % off on powder | **5 %** (8/8 within tolerance) |
| Cold-import cost | 4 s (loads ONELAB Python) | **0.05 s** (no eager imports) |
| Crashes on E/EI/PQ-style shapes | RM, P, EP, EFD fail | **0 failures** in sweep |

The full numbers live in `09-validation-benchmarks.md`. The point here:
the direct backend is faster, more reliable, and covers more of the
catalog — and we control the source.

## 2. Public API surface

One function, one result type. Everything else is an implementation
detail.

```python
from pfc_inductor.fea.direct.runner import run_direct_fea

result: DirectFeaResult = run_direct_fea(
    core=...,           # pfc_inductor.models.Core
    material=...,       # pfc_inductor.models.Material
    wire=...,           # pfc_inductor.models.Wire
    n_turns=int,
    current_A=float,
    workdir=Path,
    # ---------- optional kwargs ----------
    backend="reluctance",      # "reluctance" (default) | "axi" | "planar"
    gap_mm=None,               # override catalog lgap
    P_cu_W=None,               # enable thermal pass
    P_core_W=None,
    T_amb_C=25.0,
    frequency_Hz=None,         # enable Dowell AC pass
    n_layers=1,
    current_rms_A=None,
    getdp_exe=None,
    timeout_s=600,
)
```

The orchestrator at `src/pfc_inductor/fea/runner.py:validate_design`
wraps `run_direct_fea` and projects the result into the legacy
`FEAValidation` contract the UI/cascade consume.

## 3. Dispatch logic

`run_direct_fea` is a dispatcher. The decision tree:

```
                              shape?
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        toroid / t          axi shape        unknown shape
              │           {ei,ee,e,pq,           │
              │            etd,rm,ep,            ▼
              │            efd,eq,p}      log + try reluctance
              │                  │              │
              ▼                  ▼              ▼
   _run_toroidal_analytical   backend=?  ──┬── "reluctance" (default)
                                           │
                                  ├── "axi" → FEM (mesh+GetDP)
                                  └── "planar" → FEM (mesh+GetDP)
```

| Branch | Solver | Cost | Where the math lives |
|---|---|---|---|
| Toroidal | Closed-form `B_φ`, energy integral | 0.1 ms | `physics/magnetostatic_toroidal.py` |
| Reluctance (default) | `L = N²/(R_iron + R_gap/k_fringe)` | 1 ms | `physics/reluctance_axi.py` |
| Axi FEM | Gmsh + GetDP `MagSta_a` | 2–10 s | `geometry/ei_axi.py`, `physics/magnetostatic_axi.py` |
| Planar FEM | Gmsh + GetDP `MagSta_a` | 2–10 s | `geometry/ei.py`, `physics/magnetostatic.py` |

The default `backend="reluctance"` is selected because it meets the
≤15 % vs FEMMT accuracy target at 100× lower wall time. FEM is kept
for research / cross-check and is documented in
`12-fem-templates-research.md`.

## 4. Module map

The directory is layered so each module has one job:

```
src/pfc_inductor/fea/direct/
├── runner.py                    # 🟢 dispatcher; public API
├── models.py                    # 🟢 DirectFeaResult, EICoreDims, RegionTag enum
├── solver.py                    # 🟢 GetDP subprocess (used by FEM paths)
├── postproc.py                  # 🟢 parse .pos / .txt → scalars
├── calibration.py               # 🟡 Phase 1.2 oracle (FEMMT diff harness)
├── geometry/
│   ├── base.py                  # 🟢 CoreGeometry ABC + region tags
│   ├── ei.py                    # 🟢 planar 2-D
│   ├── ei_axi.py                # 🟢 axisymmetric (recommended for FEM)
│   └── toroidal.py              # 🟢 toroidal closed-form
└── physics/
    ├── reluctance_axi.py        # 🟢 default solver
    ├── saturation.py            # 🟢 μ_eff(H), complex_mu_r interp
    ├── magnetostatic_toroidal.py# 🟢 toroidal analytical
    ├── magnetostatic.py         # 🟢 planar GetDP template
    ├── magnetostatic_axi.py     # 🟢 axi GetDP template
    ├── dowell_ac.py             # 🟢 AC resistance (Phase 2.8)
    ├── thermal.py               # 🟢 lumped convection (Phase 3.2)
    ├── em_thermal_coupling.py   # 🟡 iterative T convergence
    ├── magnetostatic_globalq.py # 🔵 alt template (research)
    ├── magnetostatic_ac.py      # 🔵 frequency-domain (research)
    ├── magnetostatic_3d.py      # 🔵 stub (Phase 4.2)
    ├── transient.py             # 🔵 stub (Phase 4.1)
    └── rom_proxy.py             # 🔵 stub (Phase 4.3)
```

Legend: 🟢 LIVE · 🟡 RESEARCH (wired but experimental) · 🔵 FUTURE (stub).

## 5. Two complementary paths — engine vs direct

A frequent source of confusion: the project has **two independent
solvers** that must agree:

1. **Analytical engine** (`src/pfc_inductor/design/engine.py`) — the
   design-loop fast path. Sweeps `N` against `L_target`, `B_pk_limit`,
   `Ku_max`. Uses `A_L · N² · μ_pct(H)` for inductance and
   topology-specific `B_pk` expressions.
2. **Direct backend** (this directory) — the validation path called
   *after* the engine settles on a candidate `(core, N, I)`. Computes
   the same quantities through a reluctance model.

They must agree to numerical precision when fed the same inputs.
`08-engine-vs-direct-parity.md` is dedicated to that contract — read it
before changing physics in either module.

## 6. Result contract

`DirectFeaResult` (in `models.py`) is what every solve path returns:

| Field | Always populated | Units | Source |
|---|---|---|---|
| `L_dc_uH` | ✅ | μH | reluctance / toroidal / FEM |
| `B_pk_T` | ✅ | T | flux-density peak |
| `B_avg_T` | ✅ | T | volume-averaged (≈ `B_pk` for 1-D reluctance) |
| `energy_J` | ✅ | J | `½·L·I²` |
| `solve_wall_s` | ✅ | s | wall-clock |
| `workdir` | ✅ | Path | output directory (for artefacts) |
| `mesh_n_elements` | FEM only | — | mesh size diagnostic |
| `field_pngs` | ✅ | — | dict of label → PNG path (heatmaps) |
| `L_ac_uH` | if `frequency_Hz` | μH | Dowell + complex-μ correction |
| `R_ac_mOhm` | if `frequency_Hz` | mΩ | Dowell `F_R · R_dc` |
| `P_cu_ac_W` | if `frequency_Hz` and `current_rms_A` | W | `I_rms² · R_ac` |
| `P_core_W` | if supplied to runner | W | passed-through to thermal |
| `T_winding_C` | if `P_cu_W` or `P_core_W` | °C | lumped thermal |
| `T_core_C` | as above | °C | ≈ T_winding for 1-node model |

Optional fields default to `None`. Downstream consumers (UI, PDF
report, cascade) should branch on `is not None` rather than zero.

## 7. Performance budget

Cold-import + one solve on a representative core (PQ40/40 N87, boost
PFC, 65 kHz with AC + thermal):

| Pass | Time | Cumulative |
|---|---:|---:|
| Import (`from runner import …`) | 50 ms | 50 ms |
| Reluctance solve | 0.4 ms | 50 ms |
| Synthetic field-PNG render | 30 ms | 80 ms |
| Dowell AC pass | 0.2 ms | 80 ms |
| Thermal pass | 0.1 ms | 80 ms |
| **Total** | | **~80 ms** |

A full FEM solve (`backend="axi"`) adds **2–10 s** for Gmsh meshing +
GetDP. That's why the default is reluctance.

## 8. What this backend is NOT

- **Not a 3-D solver.** The reluctance solver is 1-D; the FEM
  backends are 2-D (axi or planar extruded). 3-D is Phase 4.2.
- **Not a transient simulator.** The transient path is Phase 4.1; for
  now, transient analysis uses `simulate/nonlinear_inductor.py` (RK4
  in the analytical engine).
- **Not a circuit-coupled solver.** Source is a fixed DC current (`I`
  parameter); no PWM, no MOSFET model.
- **Not a substitute for measurement.** The `09-validation-benchmarks.md`
  file documents what we trust and at what tolerance.
