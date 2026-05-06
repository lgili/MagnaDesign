# Tasks — UI refactor follow-ups

## 1. Design system v2 tail

- [ ] 1.1 Add `LICENSE-LUCIDE.txt` next to `src/pfc_inductor/ui/icons.py`
      reproducing the ISC license notice from upstream Lucide.
- [ ] 1.2 Replace any remaining `QIcon.fromTheme(...)` usages in
      `ui/litz_dialog.py`, `ui/fea_dialog.py`, `ui/db_editor.py`,
      `ui/compare_dialog.py`, `ui/setup_dialog.py` with `icon("…")`
      calls from the v2 API.

## 2. Núcleo card — score table

- [ ] 2.1 Expose a `score(spec, candidate, ...)` helper from
      `optimize/feasibility.py` so the table can derive a 0–100 score
      per row without re-running the engine.
- [ ] 2.2 Replace `_NucleoBody` with a tabbed view (Material | Núcleo
      | Fio); each tab a `QTableView` backed by a small `QAbstractTableModel`.
- [ ] 2.3 Add a `ScorePill` delegate so the score column renders as a
      coloured pill.
- [ ] 2.4 Filters above the table: searchable `QLineEdit` + checkboxes
      (Apenas curados / Apenas viáveis / Vendor: Magnetics / Magmattec
      / Micrometals / CSC / Dongxing).
- [ ] 2.5 Footer: "Aplicar seleção" primary button (enabled when the
      user picks a non-current row); emits a signal handled by
      `MainWindow._apply_optimizer_choice` for consistency.
- [ ] 2.6 Tests: feeding 50 candidates produces a sorted-by-score
      table; clicking "Aplicar" with a different row dispatches the
      selection; vendor filter narrows the visible rows.

## 3. Dashboard polish

- [ ] 3.1 Visual-regression test: render `DashboardPage` headlessly to
      PNG, commit `tests/baselines/dashboard_default.png`, add a
      `tests/test_dashboard_visual.py` that diffs new renders against
      the baseline at < 1 % per-pixel tolerance.
- [ ] 3.2 Update `README.md` screenshots from the v1 splitter layout
      to the v2 dashboard.
- [ ] 3.3 Create `docs/UI.md`:
      - Section 1: design system tokens (theme, sidebar, palette).
      - Section 2: dashboard card recipe — how to add a new card.
      - Section 3: 3D viewer overlay surface — how to add a new HUD
        button.

## 4. 3D viewer animations + cube sync

- [ ] 4.1 Animate `CoreView3D.set_view(name)` over 300 ms via
      `QVariantAnimation` interpolating each component of
      `camera_position`.
- [ ] 4.2 Animate `CoreView3D.request_explode(factor)` over ~250 ms;
      ease-out interpolation feels right for a single click.
- [ ] 4.3 Wire `OrientationCube` to subscribe to
      `CoreView3D.camera_changed` and recompute its visible faces +
      labels when the user manually orbits the scene.
- [ ] 4.4 Add `tests/test_viewer_screenshot.py` exercising
      `request_screenshot(tmp.png)` with a live (non-offscreen)
      plotter — guard with `_can_use_3d()` so offscreen CI skips it.

## 5. Schematic widget tests

- [ ] 5.1 `tests/test_schematic_dpr.py` — render the schematic at
      DPR 1.0 and 2.0; assert the 2.0 pixmap has 4× the pixel count
      and antialiasing is present.
- [ ] 5.2 `tests/test_schematic_theme_change.py` — render in light,
      switch to dark, render again; assert stroke pixels change in
      the expected direction.

## 6. theme_changed signal

- [ ] 6.1 Add a global `theme_changed` `Signal()` in
      `pfc_inductor/ui/theme.py` (module-level singleton), emitted by
      `set_theme(name)` after the state mutates.
- [ ] 6.2 Subscribe `TopologySchematicWidget`, `DonutChart`, and the
      3D-viewer overlays to `theme_changed` so they repaint when the
      user toggles light/dark — without relying on a recompute path.

## 7. Documentation linkage

- [ ] 7.1 Once `docs/UI.md` exists, add a link to it in
      `openspec/README.md` and `README.md`.
- [ ] 7.2 Cross-link from `docs/POSITIONING.md` differential #6
      ("polished UX") to `docs/UI.md`.
