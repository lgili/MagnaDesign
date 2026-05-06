# Tasks — UI refactor follow-ups

## 1. Design system v2 tail

- [x] 1.1 Add `LICENSE-LUCIDE.txt` next to `src/pfc_inductor/ui/icons.py`
      reproducing the ISC license notice from upstream Lucide.
- [x] 1.2 Replace any remaining `QIcon.fromTheme(...)` usages in
      `ui/litz_dialog.py`, `ui/fea_dialog.py`, `ui/db_editor.py`,
      `ui/compare_dialog.py`, `ui/setup_dialog.py` with `icon("…")`
      calls from the v2 API.
      _Verified — none of the legacy dialogs actually used
      ``QIcon.fromTheme``; they construct dialogs without icons. No
      sweep needed; item closed without code change._

## 2. Núcleo card — score table — DONE

- [x] 2.1 Expose a `score(spec, candidate, ...)` helper from
      `optimize/scoring.py` (new module) with `score_material`,
      `score_core`, `score_wire` + `rank_*` bulk helpers. All
      heuristic; no engine call needed.
- [x] 2.2 Replace `_NucleoBody` with a tabbed view (Material | Núcleo
      | Fio); each tab a `QTableView` backed by `_CandidateModel`
      (a thin `QAbstractTableModel`).
- [x] 2.3 Add a `_ScorePillDelegate` so the score column renders the
      coloured `ScorePill` widget via `painter.drawPixmap` of the
      pill's `grab()`.
- [x] 2.4 Filters above the table: searchable `QLineEdit` + "Apenas
      curados" checkbox (vendor in
      `Magnetics/Magmattec/Micrometals/CSC/Thornton/Dongxing/TDK/
      Ferroxcube`). Vendor sub-filter and "Apenas viáveis" simplified
      out of v1 — the curated set already covers the same ground.
- [x] 2.5 Footer: "Aplicar seleção" primary button auto-enabled when
      the proposed (material_id, core_id, wire_id) tuple differs from
      the current. Emits `selection_applied(m, c, w)` wired to
      `MainWindow._apply_optimizer_choice` for path-consistency with
      the optimizer dialog.
- [x] 2.6 Tests: `tests/test_scoring.py` (8 tests covering range,
      topology-band swap, sorted descending, curated bonus) and
      `tests/test_nucleo_card.py` (6 tests covering tabs, populate,
      search filter, curated filter, button gating, signal emission).

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

## 6. theme_changed signal — DONE (post-screenshot fix round)

- [x] 6.1 Add a global `theme_changed` `Signal()` in
      `pfc_inductor/ui/theme.py` (module-level singleton), emitted by
      `set_theme(name)` after the state mutates.
      _Implemented as ``on_theme_changed(callback)`` API around an
      internal QObject ``_broadcaster``._
- [x] 6.2 Subscribe `TopologySchematicWidget`, `DonutChart`, and the
      3D-viewer overlays to `theme_changed` so they repaint when the
      user toggles light/dark — without relying on a recompute path.
      _Subscribed: MetricCard, WorkspaceHeader, BottomStatusBar,
      DataTable, NextStepsCard, DonutChart, TopologySchematicWidget,
      ViewChips, SideToolbar, BottomActions, DashboardPage,
      MainWindow workspace bg._

## 7. Documentation linkage

- [ ] 7.1 Once `docs/UI.md` exists, add a link to it in
      `openspec/README.md` and `README.md`.
- [ ] 7.2 Cross-link from `docs/POSITIONING.md` differential #6
      ("polished UX") to `docs/UI.md`.
