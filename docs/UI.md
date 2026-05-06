# UI guide — MagnaDesign v3

This document is the working reference for the Qt-side of the
PFC Inductor Designer. Read it before adding a card, a workspace
page, or a 3D viewer overlay.

The companion module-level docstrings stay authoritative for fine
details; this file ties them together.

---

## Layout overview

```
+-----------+--------------------------------------------------------+
| Sidebar   |  QStackedWidget — 4 pages                              |
| (4 itms)  |                                                        |
| navy      |  page 0  ProjetoPage                                   |
| brand     |          ├─ SpecDrawer (left, collapsible)             |
| invariant |          └─ Workspace column                           |
|           |              ├─ WorkspaceHeader (CTAs + project name)  |
|           |              ├─ ProgressIndicator (Spec→…→Exportar)    |
|           |              ├─ QTabWidget                             |
|           |              │   • Design   (DashboardPage)            |
|           |              │   • Validar  (ValidarTab)               |
|           |              │   • Exportar (ExportarTab)              |
|           |              └─ Scoreboard (KPI strip + Recalcular)    |
|           |                                                        |
|           |  page 1  OtimizadorPage   (OptimizerEmbed inline)      |
|           |  page 2  CatalogoPage     (DbEditorEmbed inline)       |
|           |  page 3  ConfiguracoesPage                             |
+-----------+--------------------------------------------------------+
```

## Design tokens (`pfc_inductor.ui.theme`)

The theme module exposes a small set of frozen dataclasses. Anything
visual reads from these — *no* literal hex codes elsewhere.

| Type | What it holds | Theme-invariant? |
|---|---|---|
| `Palette` | bg / surface / text / accent / semantic colours | No (light + dark) |
| `Sidebar` | navy chrome colours | **Yes** |
| `Viz3D` | material / bobbin / scene-bg colours for the 3D scene | **Yes** |
| `Spacing` | `xs/sm/md/lg/xl/xxl` + `page=24, card_pad=20, card_gap=16, section=32` | shared |
| `Radius` | `sm=4, md=6, lg=8, pill=999, card=16, button=10, chip=8` | shared |
| `Typography` | font stacks + sizes + weights | shared |

`set_theme(name)` flips between `LIGHT` and `DARK`. After mutating
the global state it emits the `theme_changed` Qt signal exposed via
the helper:

```python
from pfc_inductor.ui.theme import on_theme_changed
on_theme_changed(self._refresh_qss)
```

Any widget that holds *inline* `setStyleSheet(...)` calls (i.e. not
relying purely on `app.setStyleSheet(make_stylesheet(...))`) **must**
subscribe to that signal and re-emit its inline QSS, otherwise dark
mode looks broken on theme toggle.

## Card system (`pfc_inductor.ui.widgets`)

Reusable widgets that compose the dashboard:

- `Card(title, body, *, badge, badge_variant, actions, elevation)` —
  outer frame with header, optional badge, optional `…` overflow
  menu, animated drop-shadow on hover. 16 px radius, 1 px border,
  surface bg.
- `MetricCard(label, value, unit, *, trend_pct, trend_better, status)`
  — single-metric tile with optional trend chip and a coloured
  left accent bar (3 px) when status is non-neutral.
- `DataTable(rows, *, striped)` — flat label / value / unit table.
  Mono numerics with `tabular-nums` hint.
- `ScorePill(score, suffix)` — colour-graded pill from a 0–100
  score (success / info / warning / amber / danger bands).
- `DonutChart(segments, *, centre_total_format, centre_caption)` —
  matplotlib donut with centre total label.
- `NextStepsCard(items)` — vertical list of `ActionItem(title,
  status, callback)` rows with status-colour icons.
- `BHLoopChart()` — embeddable B-H operating-point chart (envelope +
  ripple + Bsat).
- `TopologySchematicWidget()` — procedural QPainter circuit
  schematic for the 4 supported topologies.

### Adding a new dashboard card — recipe

A "card" on the Design tab is just a `Card` instance with a body
widget that exposes `update_from_design(result, spec, core, wire,
material)` and `clear()`. Three steps:

1. **Body widget** — subclass `QWidget`, build the inside, expose the
   two methods. Example: `_PerdasBody`.
2. **Façade Card** — wrap the body in a `Card(title, body, …)` and
   forward `update_from_design` / `clear`. Example: `PerdasCard`.
3. **Mount it** in `DashboardPage.__init__`, append to `self._cards`,
   forward any signals you expose.

Cards on *other* tabs (Validar, Exportar) follow the same pattern;
only the parent layout differs.

## 3D viewer overlay surface (`pfc_inductor.ui.viewer3d`)

`CoreView3D` hosts a `QtInteractor` (the live scene) plus four
overlay HUD panels parented to the widget itself and `raise_()`-d:

- `ViewChips` — top-left chip group for the canonical Frente / Cima
  / Lateral / Iso presets (animated `set_view` 300 ms).
- `OrientationCube` — top-right axis cube, tracks the camera
  (`update_from_camera(payload)` keeps visible faces in sync).
  Clicking a face snaps the camera to the matching view.
- `SideToolbar` — vertical right-edge stack: fullscreen, screenshot,
  layers (popup with Bobinagem / Bobina / Entreferro checkboxes),
  cross-section, measure, settings.
- `BottomActions` — bottom labelled tertiary buttons: Explodir
  (250 ms ease-out animation), Corte, Medidas, Exportar.

In `_reposition_overlays()` the widget hides the side toolbar and
bottom-action bar when its area is small (< 520 × 360) and hides the
cube too when narrower than 380 — keeps the dashboard's small viewer
card legible. The full-bleed viewer (Mecânico / Validar) always
shows everything.

### Adding a new HUD button

1. Append a tuple to `_BUTTONS` in `side_toolbar.py` (icon-name,
   signal-attr-name, tooltip).
2. Declare a `Signal()` on `SideToolbar` matching the signal-attr.
3. Wire the new signal in `CoreView3D._build_overlays`.

Bottom-bar buttons follow the same recipe in `bottom_actions.py`.

## Workspace pages

All workspace pages live in `pfc_inductor.ui.workspace`:

- `ProjetoPage` — owns SpecDrawer + 3 tabs + Scoreboard. Default page.
- `OtimizadorPage` — embeds `OptimizerEmbed` (Pareto sweep + ranked
  table + Aplicar). The Apply signal bubbles up to
  `MainWindow._apply_optimizer_choice` exactly like the Núcleo card.
- `CatalogoPage` — embeds `DbEditorEmbed` plus quick-action cards
  for MAS import and Similar parts.
- `ConfiguracoesPage` — theme toggle, FEA installer, Litz
  optimizer, About.

### Adding a new workspace page

1. Add to `SIDEBAR_AREAS` in `ui/shell/sidebar.py`.
2. Create `ui/workspace/foo_page.py::FooPage(QWidget)` exposing the
   signals the host should listen to.
3. Add a `self.foo_page = FooPage()` line in `MainWindow.__init__`,
   `self.stack.addWidget(self.foo_page)` in `_build_shell`, and
   `wire_signals` to handle whatever the page emits.
4. Add the area_id to `AREA_PAGES` in stack-order.

## Persistence

- Window geometry: native Qt save/restore via `QSettings`.
- Theme: `QSettings` key `theme` (`"light"` | `"dark"`) at app boot.
- SpecDrawer collapsed state: `QSettings` key
  `shell/spec_drawer_collapsed` (bool).
- Project name + last_saved_at + completed_steps: persisted by
  `WorkflowState.to_settings(qs)` under the `shell/` group.

## Where to look for…

| If you need to | Look at |
|---|---|
| Wire a new dialog/page action | `MainWindow._wire_signals` |
| Change a card's title or body | `ui/dashboard/cards/<card>_card.py` |
| Add a token (colour, radius) | `ui/theme.py` |
| Tweak the QSS for a v2 button class | `ui/style.py::v2_buttons_qss` |
| Hook into theme toggles | `on_theme_changed(callback)` in `ui/theme.py` |
| Add a 3D viewer behaviour | `ui/core_view_3d.py` (request_*) |
| Reuse the optimizer body elsewhere | `OptimizerEmbed` in `ui/optimize_dialog.py` |

## Testing

Headless tests run under `QT_QPA_PLATFORM=offscreen`. Patterns:

- Unit tests for widgets live in `tests/test_widgets.py` and
  `tests/test_<widget>.py`.
- Integration tests for the shell are in `tests/test_main_window_shell.py`.
- The visual regression test
  (`tests/test_dashboard_visual.py`) renders `DashboardPage` to PNG
  and diffs it against `tests/baselines/dashboard_default.png` at
  ≤ 1 % per-pixel tolerance. Update the baseline only when the
  layout intentionally changes.
