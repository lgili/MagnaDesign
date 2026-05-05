# Tasks — Refactor 3D viewer chrome

## 1. Layout re-arrangement

- [ ] 1.1 Replace `QVBoxLayout(self)` + horizontal toolbar in
      `CoreView3D.__init__` with:
      - Outer `QGridLayout` whose row 0 / col 0 contains the
        `QtInteractor.interactor` widget at full size.
      - Four overlay child widgets (chips, cube, side toolbar,
        bottom actions) each set with
        `setAttribute(Qt.WA_TransparentForMouseEvents, False)` and
        `raise_()` so they paint on top.
- [ ] 1.2 Re-position overlays on `resizeEvent`:
      - chips: top-left, 12 px from edges.
      - cube: top-right, 12 px from edges.
      - side toolbar: vertically centred on the right edge,
        12 px inset.
      - bottom actions: bottom-centre, 12 px from bottom.
- [ ] 1.3 Confirm 3D drag still works under each overlay (i.e. the
      QtInteractor still receives mouse events when the cursor is
      *not* over an overlay rect). Test on macOS specifically.

## 2. ViewChips

- [ ] 2.1 `ui/viewer3d/view_chips.py::ViewChips(QWidget)`
      - Horizontal `QHBoxLayout` of four `QToolButton.Chip`s.
      - `setCheckable(True)`, exclusive via `QButtonGroup`.
      - Default active: `Iso`.
- [ ] 2.2 Emit `view_changed(name)` on click; the consumer
      (`CoreView3D`) calls `_set_view(name)`.

## 3. OrientationCube

- [ ] 3.1 `ui/viewer3d/orientation_cube.py::OrientationCube(QWidget)`
      - `paintEvent`: render a small isometric cube using `QPainter`
        with face fills derived from the world-axis colours
        (X red / Y green / Z blue, muted).
      - Face labels rendered with a tabular sans-serif at 8 px.
- [ ] 3.2 Subscribe to `CoreView3D.camera_changed` (new Qt signal
      emitted from `iren.AddObserver("EndInteractionEvent",…)`) to
      keep the cube oriented with the current camera.
- [ ] 3.3 `mousePressEvent`: hit-test which face contains the click,
      emit `face_clicked(face: Literal["+x","-x","+y","-y","+z","-z"])`
      mapped to `view_changed("front"|"side"|...)`.

## 4. SideToolbar

- [ ] 4.1 `ui/viewer3d/side_toolbar.py::SideToolbar(QWidget)`
      - Vertical layout of 6 `QToolButton.Icon`s using Lucide
        icons.
- [ ] 4.2 Each button emits a typed signal:
      `fullscreen_requested`, `screenshot_requested`,
      `layers_menu_requested`, `section_toggled(bool)`,
      `measure_toggled(bool)`, `settings_requested`.
- [ ] 4.3 The "layers" button opens a small popup with three
      `QCheckBox`es: Bobinagem, Bobina (plástico), Entreferro;
      bound to `enable_layer`.

## 5. BottomActions

- [ ] 5.1 `ui/viewer3d/bottom_actions.py::BottomActions(QWidget)`
      - 4 `QPushButton.Tertiary` buttons, icons + labels, equal
        spacing.
- [ ] 5.2 Signals: `explode_toggled(bool)`, `section_toggled(bool)`,
      `measure_toggled(bool)`, `export_requested(fmt)`.

## 6. CoreView3D API extensions

- [ ] 6.1 `set_view(name)` — uses `_VIEW_CAMERAS` (same dict as
      `report/views_3d.py`, lifted to a shared
      `pfc_inductor.visual.views.VIEW_CAMERAS`). Animates over
      300 ms via `QVariantAnimation` interpolating
      `camera_position`.
- [ ] 6.2 `enable_layer(layer, on)` — keeps mesh handles in `self._layers`
      dict; on `False` removes the actor; on `True` re-adds. Avoid
      full `clear()` rebuilds for these toggles.
- [ ] 6.3 `request_section_plane(active, axis)` — wraps
      `plotter.add_volume_clip_plane` (or `add_mesh_clip_plane` for
      meshes).
- [ ] 6.4 `request_measure(active)` — toggles
      `plotter.add_measurement_widget(callback=self._on_measure)`.
- [ ] 6.5 `request_explode(factor)` — translates each block actor by
      `block.center * factor` for `factor` in [0, 1] using
      `QVariantAnimation`.
- [ ] 6.6 `request_screenshot(path)` — `plotter.screenshot(path)`,
      defaulting `path` to a `QFileDialog.getSaveFileName`.
- [ ] 6.7 `request_export(fmt)` —
      - `png` → `request_screenshot`
      - `stl` → `pv.MultiBlock([core, winding]).save("out.stl")`
      - `vrml` → `plotter.export_vrml("out.wrl")`

## 7. Wiring

- [ ] 7.1 In `CoreView3D._build_ui`:
      - Connect `self.chips.view_changed → self.set_view`.
      - Connect `self.cube.face_clicked → _face_to_view → set_view`.
      - Connect side toolbar signals to the matching `request_*`
        methods.
      - Connect bottom actions to the same `request_*` methods.
- [ ] 7.2 Camera-change observer:
      - `iren.AddObserver("EndInteractionEvent",
        self._emit_camera_changed)`.
      - `camera_changed = Signal(dict)` carrying current
        `(position, focal, up)`.
- [ ] 7.3 First-paint default: chips highlight `Iso`, cube oriented
      to iso, all layers on.

## 8. Tests

- [ ] 8.1 `tests/test_viewer_view_chips.py` — instantiate `ViewChips`,
      click each chip, assert emitted name and exclusive selection.
- [ ] 8.2 `tests/test_viewer_orientation_cube.py` — `paintEvent` runs
      without error in offscreen Qt; hit-test by simulating a
      `mousePressEvent` at known face coordinates and asserting the
      emitted face name.
- [ ] 8.3 `tests/test_viewer_layer_toggles.py` — instantiate
      `CoreView3D` with a synthetic core/wire/material/N (skip when
      `_can_use_3d() == False`); call `enable_layer("winding", False)`,
      assert the winding actor is no longer in the plotter renderer.
- [ ] 8.4 `tests/test_viewer_screenshot.py` — `request_screenshot(tmp)`
      writes a PNG with non-zero size.

## 9. Documentation

- [ ] 9.1 Update `docs/UI.md` with a "3D viewer controls" section
      describing each overlay's role and signals.
