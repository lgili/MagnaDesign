# UI refactor — follow-ups

## Why

The five v2 UI changes (`refactor-ui-design-system-v2`,
`refactor-ui-shell`, `refactor-ui-dashboard-cards`,
`refactor-3d-viewer-controls`, `add-topology-schematic-card`) shipped
substantively but each left a small tail of items that did not block
the user-facing milestone. Capturing them in one change gives the
backlog a single home and keeps the parent OpenSpecs honest about what
"shipped" meant.

This change is intentionally **a list**, not a redesign. Every item
here is independent of the others and can be picked up in any order.

## What changes

### From `refactor-ui-design-system-v2`

- Add `LICENSE-LUCIDE.txt` next to `ui/icons.py` reproducing the ISC
  notice from the Lucide upstream.
- Sweep the legacy dialogs (`litz_dialog`, `fea_dialog`, `db_editor`,
  `compare_dialog`, `setup_dialog`) replacing any leftover
  `QIcon.fromTheme(...)` calls with the v2 `icon("...")` API.

### From `refactor-ui-dashboard-cards`

- **Núcleo card score-table view** (the biggest functional gap):
  swap the current "live selection summary" body for a tab strip
  (Material | Núcleo | Fio) where each tab is a `QTableView` with a
  `ScorePill` in the score column. Filters above: searchable
  `QLineEdit` + checkbox filters (curated only / feasible only /
  vendor). Footer "Aplicar seleção" primary button. Requires a
  scoring helper exposed from `optimize/feasibility.py`.
- Visual-regression tests: render `DashboardPage` to PNG via
  pytest-qt screenshot, commit a baseline, diff future PRs against
  it (tolerance 1 % per pixel).
- Update `README.md` screenshots to reflect the v2 dashboard layout.
- Add `docs/UI.md` with the card system recipe + how to add a new
  dashboard card.

### From `refactor-3d-viewer-controls`

- Animate `set_view` between camera presets via a 300 ms
  `QVariantAnimation` (currently snaps instantly).
- Animate `request_explode(factor)` with `QVariantAnimation` over
  ~250 ms (currently a step translate).
- Wire `OrientationCube` to repaint its visible faces when
  `CoreView3D.camera_changed` fires (currently the cube is static
  after construction).
- Add `tests/test_viewer_screenshot.py` exercising
  `request_screenshot(tmp.png)` with a live (non-offscreen)
  plotter on the macOS / Windows / Linux CI runners.
- Add the "3D viewer controls" section to `docs/UI.md`.

### From `add-topology-schematic-card`

- Add `tests/test_schematic_dpr.py` rendering at DPR 1.0 and 2.0 and
  asserting the 2.0 pixmap is 4× the pixel count.
- Add `tests/test_schematic_theme_change.py` rendering once in light,
  changing to dark, rendering again, and asserting the stroke colour
  pixel changes in the expected direction.

### Cross-cutting

- Wire a `theme_changed` Qt signal in `ui/theme.py` so widgets that
  do their own painting (schematic, donut chart, 3D viewer overlays)
  can subscribe to it instead of having to rely on a parent recompute.

## Impact

- **Affected capabilities:** none new; all items polish capabilities
  already shipped under their respective changes.
- **Affected modules:** several, each item is small (~50 LOC).
- **Dependencies:** none new.
- **Risk:** low. Each item is independently scoped and rolls back
  cleanly.
- **Sequencing:** can be picked up in any order. The Núcleo
  score-table is the most user-visible win (originally specced in
  `refactor-ui-dashboard-cards` 3d.2–3d.4); the rest are quality
  polish.
