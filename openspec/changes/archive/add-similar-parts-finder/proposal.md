# Add "find similar parts" finder

## Why

Once a design is settled, the engineer often wants to find equivalent
parts from other vendors — for second-source qualification, regional
availability, or cost negotiation. Coilcraft and Würth REDEXPERT both
expose this as a single click on a result.

Our database already has 1008 cores from 5 vendors. A query
"find me toroids with Ae within ±10%, Wa within ±15%, AL within ±20%,
material μ_r within ±20%" returns equivalents in milliseconds. The
machinery is in place — what's missing is just the search interface and
the result presentation.

## What changes

- New `optimize/similar.py::find_equivalents(target_core, target_material,
  cores, materials, tolerance_pct)` returns ranked alternatives.
- Result panel: small button "Achar peças similares" next to the chosen
  core; opens a popover/dialog listing equivalents grouped by vendor.
- Equivalence criteria configurable: by geometry (default), by inductance
  index (AL), or by both.
- Each row shows: vendor, part number, deltas vs target (Ae, Wa, AL, Bsat,
  μ_r), cost if available, and an "Aplicar" button.
- Cross-material recommendations: same vendor, same shape, alternate
  material (e.g. Magnetics High Flux 60µ → Magnetics XFlux 60µ).

## Impact

- Affected capabilities: NEW `parts-finder`
- Affected modules: NEW `optimize/similar.py`,
  NEW `ui/similar_parts_dialog.py`, `ui/result_panel.py` (button), 
  `ui/main_window.py` (open-dialog wiring).
- No new deps.
- Small effort.
