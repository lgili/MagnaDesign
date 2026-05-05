# Design — FEA validation

## Why FEMM specifically

- Free, mature 2D FEA (since 1998), permissive licence, batch-scriptable.
- `pyfemm` is the official Python binding — no need to write our own COM
  bridge.
- 2D axisymmetric handles toroids exactly. 2D planar handles E-cores
  reasonably (ignores fringing in the third dimension; acceptable for
  cross-validation).
- Solve time for our inductor sizes (1–100 cm³ cores, ~30 turns): **1–10 s**.
  Fast enough for one-shot validation; not for live recompute on every
  parameter tweak.

## Why not Ansys / COMSOL / FEMM4 / Maxwell

- All commercial, expensive licences, can't ship.
- We don't need 3D FEA — the symmetries of our cores give 2D enough fidelity.

## Architecture

```
pfc_inductor/fea/
  __init__.py
  probe.py          # detect FEMM install, return version
  geometry.py       # build FEMM problems from our Core + winding info
  solver.py         # invoke FEMM, return path to .ans
  postprocess.py    # parse .ans, compute L/B/losses
  models.py         # FEAValidation pydantic model
```

## Threading model

- FEMM is a separate process. Our `QThread` wraps `subprocess.run` of
  `femm-batch -lua run.lua`. The Lua script handles geometry/solve/output.
- Alternative: use `pyfemm`'s in-process binding — simpler, but couples
  our process lifetime to FEMM. Subprocess is more robust.

## Data flow

```
DesignResult ──┐
Core, Wire, N ─┼─► geometry.py ─► .fem file ─► FEMM solve ─► .ans
material ──────┘                                                 │
                                                                 ▼
                                                          postprocess.py
                                                                 │
                                                                 ▼
                                                         FEAValidation
                                                                 │
                                                                 ▼
                                                          UI (plot tab)
```

## Failure modes & handling

- **FEMM not installed**: detect at startup, gray out button + tooltip.
- **Solve diverges (mesh problem)**: subprocess timeout 60 s, report error
  in UI with last 50 lines of FEMM log.
- **Material not in FEMM library**: auto-register with our μ_r/Bsat. Log
  a warning that loss coefficients are extrapolated.
- **Result outside 30% of analytic**: surface a "verifique modelagem"
  warning. Likely cause: rolloff/Steinmetz miscalibrated for this material.

## Open questions

- Should we cache FEA solutions across sessions? Disk space ~ few MB per
  result. Probably yes, hash by (core_id, material_id, wire_id, N, I_pk).
- Magmattec materials aren't in FEMM's standard library — need to ship our
  own material library file (`pfc_inductor/fea/materials.lib`).
