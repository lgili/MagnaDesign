# Replace FEMM stub with FEMMT integration

## Why

The current `add-fea-validation` ships a FEMM-based scaffolding that
**does not run on macOS** without Wine and is opaque to anyone without a
local FEMM install. **FEMMT** (Paderborn LEA, Python, ONELAB-based) gives
us a pure-Python, cross-platform alternative with the same fidelity and
a much friendlier install (`pip install femmt`).

Replacing the FEMM Lua-emit pipeline with FEMMT API calls:

- works natively on macOS / Linux / Windows
- removes external binary detection
- aligns with the same project (Paderborn LEA) that publishes the
  awesome-open-source-power-electronics list — a strong community signal
- gives us free upgrades (their team maintains the meshing, ONELAB
  bridge, loss models)

The FEMM scaffolding from the current `add-fea-validation` is preserved
behind a feature flag for users who do have FEMM and prefer it.

## What changes

- New module `fea/femmt_runner.py` that orchestrates a FEMMT
  `MagneticComponent` from our internal `Core`, `Material`, `Wire`,
  `DesignResult`.
- `fea/probe.py` extended to detect both FEMMT (default) and FEMM
  (opt-in via `PFC_FEA_BACKEND=femm`).
- The existing `fea/runner.py::validate_design` becomes a dispatcher:
  call FEMMT by default, fall through to FEMM if the user asked for it.
- Lua geometry generator becomes a `legacy/` submodule, kept for users
  who prefer FEMM.
- UI dialog labels switch from "FEMM/xfemm" to "FEM (FEMMT)" with a
  status row showing which backend will execute.
- README updates to drop the FEMM install instructions to a "Legacy"
  appendix.

## Impact

- Affected capabilities: MODIFIED `fea-validation`
- Depends on: nothing (can land independently of MAS work)
- New dep: `femmt>=0.5` (optional extra `[fea]`)
- Affected modules: `fea/__init__.py`, `fea/probe.py`, NEW
  `fea/femmt_runner.py`, MOVED `fea/geometry.py` →
  `fea/legacy/femm_geometry.py`, `ui/fea_dialog.py`, README.
- Removes the macOS-specific install pain point — biggest UX win in this
  whole roadmap.
