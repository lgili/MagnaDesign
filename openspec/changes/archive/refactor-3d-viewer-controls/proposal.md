# Refactor 3D viewer chrome to dashboard-grade controls

## Why

`CoreView3D` today exposes three controls in a thin top toolbar
("Reset câmera", "Mostrar bobinagem", "Girar automático"). Functional,
but visually it reads as a debug scaffold next to the polished
mock-up. The mock requires:

- A **chip group** in the upper-left snapping the camera to canonical
  views (Frente / Cima / Lateral / Iso). This is the single most-used
  interaction on a 3D card and currently requires manual mouse drag.
- An **orientation cube** in the upper-right showing world axes (X / Y
  / Z) so the user always knows which way is up. Clickable faces
  trigger the same Frente / Cima / Lateral snaps.
- A **vertical right-edge toolbar** of icon buttons:
  fullscreen, screenshot, layers (toggle winding/bobbin/airgap),
  cross-section, ruler/measure, settings.
- A **bottom action bar** with named actions Explodir / Corte /
  Medidas / Exportar — high-affordance buttons rather than icons.

These controls also need to live cleanly inside the Visualização 3D
*card* (`Card` widget from `refactor-ui-dashboard-cards`), so the
viewer must accept its chrome without consuming the card's outer
header.

## What changes

- `ui/core_view_3d.py` re-organised:
  - The current top `QHBoxLayout` toolbar is removed.
  - A `QStackedLayout` sits over the `QtInteractor` widget, hosting
    overlay child widgets (the chips, cube, vertical toolbar, action
    bar) without intercepting mouse drags on the 3D scene itself.
  - Each overlay sits in a `QFrame.Overlay` panel (rounded, semi-
    transparent surface fill) so it reads as a HUD, not a docked
    toolbar.
- New `ui/viewer3d/view_chips.py::ViewChips(QWidget)`:
  - Four `QToolButton.Chip`s (`Frente`, `Cima`, `Lateral`, `Iso`).
  - Active chip uses `accent_subtle_bg`; emits
    `view_changed(name: Literal["front","top","side","iso"])`.
- New `ui/viewer3d/orientation_cube.py::OrientationCube(QWidget)`:
  - 60×60 px self-painted cube with face labels `+X / -X / +Y / -Y /
    +Z / -Z`.
  - Renders via `QPainter` over an isometric projection of the local
    frame the plotter is currently using (subscribes to camera
    changes).
  - `mousePressEvent` hit-tests faces; clicking `+Y` snaps the camera
    to "front" view (so the +Y face faces the user).
- New `ui/viewer3d/side_toolbar.py::SideToolbar(QWidget)`:
  - Vertical icon stack (Lucide): `maximize-2` (fullscreen),
    `image` (screenshot), `layers` (toggle), `crop` (section),
    `ruler` (measure), `settings-2`.
  - Each emits its own signal (`fullscreen_requested`,
    `screenshot_requested`, etc.).
- New `ui/viewer3d/bottom_actions.py::BottomActions(QWidget)`:
  - Four `QPushButton.Tertiary` buttons (Explodir / Corte / Medidas /
    Exportar) with their respective icons. Tertiary style = ghost
    button on the overlay surface.
- `CoreView3D` API additions:
  - `set_view(name)` — animates camera to the named preset. Reuses
    `_VIEW_CAMERAS` from `report/views_3d.py`.
  - `enable_layer(layer: Literal["winding","bobbin","airgap"], on: bool)`
    — toggles meshes without rebuilding.
  - `request_section_plane(active: bool, axis: Literal["x","y","z"])`
    — adds a clipping plane via `pv.Plane`.
  - `request_measure(active: bool)` — toggles a 2-click distance
    probe overlay (PyVista's `add_measurement_widget`).
  - `request_explode(factor: float = 1.0)` — animates core blocks
    apart along their local-frame normals (cosmetic only).
  - `request_screenshot(path: str | None = None)` — saves PNG of
    current view; if path is None, opens a save dialog.
  - `request_export(format: Literal["png","stl","vrml"])` — STL/VRML
    via `pv.MultiBlock.save`.
- Tests:
  - `tests/test_viewer_view_chips.py` — clicking each chip emits the
    right name.
  - `tests/test_viewer_orientation_cube.py` — click hit-test for each
    face triggers the corresponding `view_changed`.
  - `tests/test_viewer_layer_toggles.py` — `enable_layer("winding",
    False)` removes the winding mesh from the scene.
  - `tests/test_viewer_screenshot.py` — `request_screenshot(tmp.png)`
    writes a non-empty PNG.

## Impact

- **Affected capabilities:** NEW `ui-3d-viewer` (extending the
  existing 3D rendering capability with a chrome layer).
- **Affected modules:** rewrite of `ui/core_view_3d.py` (focused on
  layout — the rendering body is untouched), NEW `ui/viewer3d/*`,
  small additions to `report/views_3d.py` for `set_view` to share
  presets.
- **Dependencies:** none new. `pv.add_measurement_widget` is in
  PyVista 0.42+, already pinned in `pyproject.toml`.
- **Risk:** Low to medium. The overlay-over-QtInteractor pattern is
  proven (PyVistaQt examples ship one), but mouse-event passthrough
  needs verification on macOS specifically (where Qt's overlay
  semantics differ slightly).
- **Sequencing:** Depends on `refactor-ui-design-system-v2` (chip /
  tertiary button QSS). Independent of the dashboard grid — this
  change can land in parallel because it only restructures the
  internals of `CoreView3D`.
