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

- [~] 3.1 Visual-regression test for `DashboardPage` against a
      committed baseline. *Deferred — pixel-diff baselines are
      too flaky across font-rendering drift between macOS /
      Windows / Linux CI runners. The Análise-tab + dashboard
      layouts already have shape-level tests (card-mount counts,
      signal wiring) that catch meaningful regressions without
      the false-positive churn a baseline file would add.*
- [~] 3.2 Update `README.md` screenshots from the v1 splitter
      layout. *Deferred — README screenshot refresh batches with
      the next release tag's asset-update sweep.*
- [x] 3.3 `docs/UI.md` shipped — sections cover layout overview
      (Sidebar | QStackedWidget pages), design tokens (Palette /
      Sidebar / Viz3D / Spacing / Radius / Typography), dashboard
      card recipe, 3D viewer overlay surface, and the theme-
      change subscription pattern.

## 4. 3D viewer animations + cube sync

- [x] 4.1 `CoreView3D.set_view(name)` animates over 300 ms via
      ``QVariantAnimation`` with an out-cubic easing curve. The
      ``animated=False`` switch snaps for tests. See
      `src/pfc_inductor/ui/core_view_3d.py:442`.
- [x] 4.2 `CoreView3D.request_explode(on)` animates over 250 ms
      with ease-out interpolation — same module, line 593.
- [x] 4.3 ``camera_changed`` Qt signal emitted on
      ``EndInteractionEvent`` (line 270); ``OrientationCube``
      subscribes via
      ``self.camera_changed.connect(self.cube.update_from_camera)``
      (line 188) so manual orbits flip the cube's visible faces.
- [~] 4.4 `tests/test_viewer_screenshot.py` exercising a live
      (non-offscreen) plotter. *Deferred — live PyVista plotters
      need a real GL context that headless CI doesn't have, so
      the test would skip on every CI or flake on local Mac
      runs. Existing offscreen render tests in
      `tests/test_viewer3d.py` cover the API surface.*

## 5. Schematic widget tests

- [x] 5.1 `test_schematic_pixmap_has_logical_size` — grabs the
      pixmap, asserts logical size matches widget size +
      ``devicePixelRatio() >= 1.0`` so HiDPI builds keep the
      DPR-aware buffer. Lives in
      ``tests/test_schematic_widget.py``. (Full DPR=2 forcing
      isn't reliable on offscreen Qt — the logical-size guard
      catches the regression class without the platform
      fragility.)
- [x] 5.2 `test_schematic_repaints_on_theme_change` — renders
      the boost-CCM schematic in light + dark, asserts pixmap
      bytes differ. Same test file.

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

- [x] 7.1 ``README.md`` Development section links to
      ``docs/UI.md`` alongside the existing ADR / POSITIONING /
      openspec links. ``openspec/README.md`` referenced
      ``ui-refactor-followups`` itself which surfaces the UI
      docs through its own progress chain.
- [x] 7.2 ``docs/POSITIONING.md`` differential #6 ("UX polida")
      now ends with a sentence pointing at ``docs/UI.md`` for
      layout / token / card-recipe details.
