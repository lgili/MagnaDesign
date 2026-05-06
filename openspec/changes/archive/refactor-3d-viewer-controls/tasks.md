# Tasks — Refactor 3D viewer chrome

> **Status: shipped (substantively).** All four overlay HUD panels are
> mounted on top of the QtInteractor; layer toggles, screenshot,
> section, measure and export work. Camera animation between presets
> is currently a snap, not the 300 ms `QVariantAnimation` interpolation
> originally specced — that and the deferred `docs/UI.md` section are
> tracked in `ui-refactor-followups`.

## 1. Layout re-arrangement

- [x] 1.1 Replace `QVBoxLayout(self)` + horizontal toolbar in
      `CoreView3D.__init__` with a layout that hosts the
      `QtInteractor.interactor` widget at full size and four overlay
      child widgets parented to ``self`` and ``raise_()``-d on top.
- [x] 1.2 Re-position overlays on `resizeEvent`:
      - chips: top-left, 12 px from edges.
      - cube: top-right, 12 px from edges.
      - side toolbar: vertically centred on the right edge,
        12 px inset.
      - bottom actions: bottom-centre, 12 px from bottom.
- [x] 1.3 3D drag still works under each overlay because mouse events
      outside the overlay rectangles fall through to the
      `QtInteractor`. Validated under offscreen Qt; macOS native
      validation still pending in CI matrix.

## 2. ViewChips

- [x] 2.1 `ui/viewer3d/view_chips.py::ViewChips(QWidget)`
      - Horizontal `QHBoxLayout` of four `QToolButton.Chip`s.
      - `setCheckable(True)`, exclusive via `QButtonGroup`.
      - Default active: `Iso`.
- [x] 2.2 Emit `view_changed(name)` on click; the consumer
      (`CoreView3D`) calls `set_view(name)`.

## 3. OrientationCube

- [x] 3.1 `ui/viewer3d/orientation_cube.py::OrientationCube(QWidget)`
      - `paintEvent`: render a small isometric cube using `QPainter`
        with face fills derived from the world-axis colours
        (X red / Y green / Z blue, muted).
      - Face labels rendered with a tabular sans-serif at 8 px.
- [~] 3.2 Subscribe to `CoreView3D.camera_changed` (signal emitted
      from `iren.add_observer("EndInteractionEvent", …)`) to keep the
      cube oriented with the current camera.
      _Partial — the signal exists and fires; the cube does not yet
      re-render its visible faces in response. Tracked in
      `ui-refactor-followups`._
- [x] 3.3 `mousePressEvent`: hit-test which face contains the click,
      emit `face_clicked(name)` and `view_requested(view)` mapped to
      the canonical preset (`+y → front`, `+z → top`, `+x → side`).

## 4. SideToolbar

- [x] 4.1 `ui/viewer3d/side_toolbar.py::SideToolbar(QWidget)`
      - Vertical layout of 6 `QToolButton`s using Lucide icons
        (`maximize-2`, `image`, `layers`, `crop`, `ruler`,
        `settings-2`).
- [x] 4.2 Each button emits a typed signal:
      `fullscreen_requested`, `screenshot_requested`,
      `layers_requested(dict)`, `section_toggled(bool)`,
      `measure_toggled(bool)`, `settings_requested`.
- [x] 4.3 The "layers" button opens a small popup with three
      `QCheckBox`es: Bobinagem, Bobina (plástico), Entreferro;
      bound to `enable_layer`.

## 5. BottomActions

- [x] 5.1 `ui/viewer3d/bottom_actions.py::BottomActions(QWidget)`
      - 4 `QPushButton.Tertiary` buttons, icons + labels, equal
        spacing.
- [x] 5.2 Signals: `explode_toggled(bool)`, `section_toggled(bool)`,
      `measure_toggled(bool)`, `export_requested(fmt)`.

## 6. CoreView3D API extensions

- [~] 6.1 `set_view(name)` — uses `VIEW_CAMERAS` (lifted to a shared
      `pfc_inductor.visual.views.VIEW_CAMERAS`).
      _Camera animation deferred — current implementation does an
      instant snap to the preset rather than a 300 ms
      `QVariantAnimation` interpolation. Functional behaviour
      identical; tracked in `ui-refactor-followups`._
- [x] 6.2 `enable_layer(layer, on)` — toggles actor visibility via
      `actor.SetVisibility()` without rebuilding the mesh.
- [x] 6.3 `request_section_plane(active)` — wraps
      `plotter.add_mesh_clip_plane` and `clear_plane_widgets`.
- [x] 6.4 `request_measure(active)` — toggles
      `plotter.add_measurement_widget`.
- [~] 6.5 `request_explode(factor)` — translates each block actor by
      `(8.0 if on else 0)` mm.
      _Animation deferred — currently a step translate, not the
      `QVariantAnimation` interpolation specced. Tracked in
      `ui-refactor-followups`._
- [x] 6.6 `request_screenshot(path)` — `plotter.screenshot(path)`,
      defaulting `path` to `QFileDialog.getSaveFileName`.
- [x] 6.7 `request_export(fmt)` —
      - `png` → `request_screenshot`
      - `stl` → `plotter.export_obj` (closest available — STL export
        sits behind PyVista's `MultiBlock.save` which we call directly
        when needed)
      - `vrml` → `plotter.export_vrml`

## 7. Wiring

- [x] 7.1 In `CoreView3D._build_overlays`:
      - Connect `self.chips.view_changed → self.set_view`.
      - Connect `self.cube.view_requested → self.set_view`.
      - Connect side toolbar signals to the matching `request_*`
        methods.
      - Connect bottom actions to the same `request_*` methods,
        keeping the two surfaces in sync via `_sync_section` /
        `_sync_measure` helpers.
- [x] 7.2 Camera-change observer:
      - `iren.add_observer("EndInteractionEvent",
        self._emit_camera_changed)`.
      - `camera_changed = Signal(dict)` carrying current
        `(position, focal, up)`.
- [x] 7.3 First-paint default: chips highlight `Iso`, all layers on
      (winding + airgap), bobbin off by default.

## 8. Tests

- [x] 8.1 `tests/test_viewer3d_overlays.py::test_view_chips_*` —
      instantiate `ViewChips`, click each chip, assert emitted name
      and exclusive selection.
- [x] 8.2 `tests/test_viewer3d_overlays.py::test_orientation_cube_*` —
      `paintEvent` runs without error in offscreen Qt; hit-test by
      simulating a `mousePressEvent` at known face coordinates and
      asserting the emitted view names.
- [x] 8.3 `tests/test_viewer3d_overlays.py::test_core_view_3d_falls_back_in_offscreen` —
      under offscreen Qt the plotter is None but every overlay still
      mounts. Layer-toggle behaviour with a live QtInteractor is only
      tested when 3D is available (CI matrix native runs).
- [~] 8.4 `tests/test_viewer_screenshot.py` — `request_screenshot(tmp)`
      writes a PNG with non-zero size.
      _Deferred — requires a live (non-offscreen) plotter; tracked in
      `ui-refactor-followups`._

## 9. Documentation

- [~] 9.1 Update `docs/UI.md` with a "3D viewer controls" section
      describing each overlay's role and signals.
      _Deferred to `ui-refactor-followups`._
