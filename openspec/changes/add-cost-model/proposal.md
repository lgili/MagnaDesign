# Add cost model

## Why

For a manufacturer shipping inverters worldwide, **cost per unit** is a
first-class design constraint, often more decisive than minor efficiency
differences. Today our optimizer ranks by loss/volume/temperature; it has
no notion of "this Magnetics Kool Mu is 40% cheaper than the High Flux
equivalent" or "switching from AWG 14 to AWG 16 saves $0.30 per unit".

Frenetic AI's main commercial pitch is precisely cost-aware optimization.
Adding a cost model gives our app a Pareto axis that drives real
purchasing decisions and unlocks "cheapest design that meets specs" runs.

## What changes

- Extend `Material`, `Core`, `Wire` with `cost_USD` (or `cost_BRL`) and
  `cost_unit` ("per_kg", "per_meter", "per_piece").
- New `physics/cost.py::estimate_design_cost(core, wire, material, N) ->
  CostBreakdown` totalling core $ + wire $ (mass × $/kg, length × $/m).
- Optimizer: optional "cost" axis in ranking; new "Score (40% perda + 30%
  volume + 30% custo)" preset.
- Result panel: new KPI row "Custo estimado: $X.XX (núcleo $A + cobre $B)".
- DB editor: cost fields surfaced for editing.
- Multi-currency support (BRL, USD, EUR) via a global preference.

## Impact

- Affected capabilities: NEW `cost-modeling`
- Affected modules: `models/material.py`, `models/core.py`, `models/wire.py`
  (new optional fields), NEW `physics/cost.py`,
  `optimize/sweep.py` (cost axis), `ui/result_panel.py` (cost row),
  `ui/optimize_dialog.py` (cost rank option), `ui/db_editor.py`
  (edit forms include cost fields), `data/*.json` (optional cost fields
  remain blank/null until populated by user).
- No new deps.
- Medium effort, lots of small touch-points across UI.
