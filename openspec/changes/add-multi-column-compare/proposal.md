# Add multi-column design comparison

## Why

A trained engineer makes the final design pick by comparing candidates
side-by-side: "Core A is smaller but hotter; B is bigger but uses cheaper
wire; C has more saturation margin." Today our app shows one design at a
time; the optimizer Pareto plot shows a scatter but you can't see the
*details* of two designs together.

Magnetics Inc Designer's most-praised UX feature is its 4-column
comparison view. Coilcraft's parts selector mirrors the pattern. Adding
this to our app turns it from "single calculation" to "design exploration".

## What changes

- New "Comparar designs" toolbar action → opens a dialog with up to 4
  columns, each showing the same KPI groups as the side panel (inductance,
  currents, flux, losses, thermal, window).
- "Add current design to comparison" sends the present selection into the
  next free column.
- "Compare with optimizer top-N" populates columns from the optimizer's
  ranked feasible list.
- Cells that differ from the leftmost column are highlighted (better in
  green, worse in red) per metric semantics.
- "Send to design" button on any column applies that selection back to the
  spec panel.
- Export: comparison table to HTML/CSV.

## Impact

- Affected capabilities: NEW `design-comparison`
- Affected modules: NEW `ui/compare_dialog.py`,
  `ui/main_window.py` (toolbar), `report/html_report.py` (new layout for
  multi-design report).
- No new deps.
- Medium-size change, all UI + small data wrangling.
