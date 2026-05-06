# Design — FEMMT integration

## Why FEMMT over FEMM

| Concern | FEMM (current) | FEMMT (proposed) |
|---------|----------------|------------------|
| macOS native | ✗ Wine required | ✓ ONELAB packaged |
| Linux native | partial (xfemm) | ✓ |
| Windows native | ✓ | ✓ |
| Install path | OS-specific binary | `pip install femmt` |
| Scriptable | Lua | Python (same as us) |
| Maintenance | Last release 2018 (FEMM 4.2) | active (Paderborn LEA, releases through 2024) |
| EE/ETD/PQ support | manual planar geometry | built-in shape library |
| Litz losses | hand-rolled | built-in |

## Backend dispatch

```
ui/fea_dialog → fea.runner.validate_design(...)
                       │
                       ├─ active_backend() == "femmt" → fea.femmt_runner
                       └─ active_backend() == "femm"  → fea.legacy.femm_*
```

Backend selection precedence:
1. `PFC_FEA_BACKEND` env var (testing/CI)
2. user-pref in `QSettings`
3. auto-detect: prefer FEMMT if `femmt` importable; else FEMM if binary
   present; else disabled.

## API mapping (toroid)

```python
# Our internal:
core: Core          # OD, ID, HT (or inferred from Ae/le/Wa)
material: Material  # μ_initial, Bsat, Steinmetz, rolloff
wire: Wire          # round/Litz; A_cu, d_strand, n_strands
result: DesignResult  # N_turns, I_line_pk_A

# Becomes:
import femmt as ft
component = ft.MagneticComponent(component_type=ft.ComponentType.Inductor)
component.set_core(ft.Core(core_inner_diameter=core.ID_mm * 1e-3,
                            window_w=(core.OD_mm - core.ID_mm)/2 * 1e-3,
                            window_h=core.HT_mm * 1e-3,
                            material=femmt_material_from(material)))
winding = ft.Winding(N_turns=result.N_turns,
                      strand_radius=wire.d_cu_mm/2 * 1e-3,
                      conductor_type=ft.ConductorType.RoundSolid
                                     if wire.type == "round"
                                     else ft.ConductorType.RoundLitz)
component.set_winding_window(...)
component.create_model(freq=spec.f_sw_kHz * 1000, ...)
component.single_simulation(freq=..., current=[result.I_line_pk_A], ...)
L_FEA = component.read_log()['inductance']
```

The FEMMT API mirrors what we already do internally — translation is
straightforward.

## Risks

- **FEMMT pip install** pulls ONELAB at runtime which is a few hundred
  MB. Document this clearly and offer a `--lite` mode if a user just
  wants the analytic engine.
- **Schema drift**: FEMMT's API has been moving in 0.5.x. Pin a tested
  version and gate upgrades on regression tests.
- **Bobbin shape resolutions**: FEMMT models bobbin geometries in a
  specific coordinate convention; mapping our (W, H, D) needs spot-checks
  against their shape catalog.

## Migration path for users

- Upgrade `pip install pfc-inductor-designer[fea]` →  FEMMT auto-detected.
- Existing FEMM users: keep FEMM by setting `PFC_FEA_BACKEND=femm` or
  toggling in the new settings menu. No data lost.
- Default UI label switches from "Validar com FEA (FEMM)" to
  "Validar com FEA".
