# Refactor application shell to MagnaDesign layout

## Why

The current shell is a `QMainWindow` with one horizontal `QToolBar` (seven
unlabelled-ish text actions) above a 3-column `QSplitter`. It works, but it
reads as a v0.x prototype: no brand surface, no visible workflow, no
breathing room around CTAs, no place to surface persistence or validation
state. Engineering users have told us the app feels like "a Tk dialog with
extra panels".

The MagnaDesign mock fixes this by separating the chrome into four
purpose-built regions:

1. **Persistent sidebar** (navy, ~250 px) — brand identity + primary
   navigation between the *workflow areas* (Dashboard, Topologia, Núcleos,
   Bobinamento, Simulação, Mecânico, Relatórios, Configurações).
2. **Top header** inside the workspace — project identity (editable name +
   "Salvo" status) on the left, secondary CTA "Comparar soluções" and
   primary CTA "Gerar Relatório" on the right.
3. **Stepper card** — 8 numbered segments mapping the linear PFC design
   workflow (Topologia → Entrada de Dados → Cálculo → Núcleo →
   Bobinamento → Simulação FEM → Mecânico → Relatório). The active step
   is highlighted; completed steps show a check; pending steps are muted.
4. **Bottom status bar** — left: "Projeto salvo há N min" with a green
   dot. Right: three pill counters (Avisos / Erros / Validações) wired to
   the live design state.

This change introduces the shell. The 9-card dashboard grid lives inside
it but is scoped to a sibling change (`refactor-ui-dashboard-cards`) so
each piece can land independently.

## What changes

- New `ui/shell/` package:
  - `sidebar.py` — `Sidebar(QFrame)` with logo, nav items (8 entries),
    footer (theme toggle button + version label).
  - `header.py` — `WorkspaceHeader(QWidget)` with project-name editor,
    "Salvo" pill, "Comparar soluções" + "Gerar Relatório" CTA buttons.
  - `stepper.py` — `WorkflowStepper(QWidget)` rendering 8 segments with
    states (`done | active | pending`) and connecting hairlines.
  - `status_bar.py` — `BottomStatusBar(QFrame)` with the save-status
    label and three semantic pill counters.
- `ui/main_window.py` rewritten to:
  - Replace `QToolBar` with the new `Sidebar` (left dock area).
  - Replace the splitter wrapper with a `QFrame#Workspace` container
    holding `WorkspaceHeader` + `WorkflowStepper` + a `QStackedWidget`
    for the per-area pages (Dashboard is one of those pages; legacy
    panels keep working until later changes migrate them).
  - Replace the standard `statusBar()` with the new `BottomStatusBar`.
  - Wire `Sidebar.navigation_requested(area: str)` to the
    `QStackedWidget`.
  - Wire `WorkspaceHeader.report_requested` and `compare_requested`
    to the existing slots (`_export_report`, `_open_compare`).
- New `WorkflowState` (in `ui/state/workflow_state.py`):
  - Tracks `current_step: int`, `completed_steps: set[int]`,
    `unsaved: bool`, `last_saved_at: datetime | None`,
    `warnings: int`, `errors: int`, `validations_passed: int`.
  - Emits `state_changed` signal; the stepper, header pill, and
    status bar all subscribe.
- Persistence: project name + last_saved_at + completed_steps
  serialised under existing `QSettings` (key prefix `shell/`).
- Tests:
  - `tests/test_shell_sidebar.py` — instantiate, click each nav item,
    assert the right `area` string emits.
  - `tests/test_shell_stepper.py` — set active step + completed set,
    assert correct visual state classes on each segment.
  - `tests/test_shell_status_bar.py` — set warnings=2/errors=1, assert
    the pill widgets show "2 Avisos", "1 Erro", and use the correct
    semantic colour classes.
  - `tests/test_workflow_state.py` — round-trip serialise to QSettings.

## Impact

- **Affected capabilities:** NEW `ui-shell`.
- **Affected modules:** `ui/main_window.py` (significant rewrite of
  `_build_ui` only), NEW `ui/shell/`, NEW `ui/state/workflow_state.py`.
- **Removed:** the previous `_build_toolbar` action wiring is preserved
  but moved — actions now hang off the header (CTAs) and a small "more"
  overflow menu in the sidebar footer (DB editor, MAS catalog,
  optimizer, FEA, BH, Litz, similar, About).
- **Dependencies:** no new pip deps. All bundled icons come from
  `refactor-ui-design-system-v2`.
- **Risk:** Medium. `main_window.py` is the most-touched file in the
  app; the rewrite must keep every existing slot reachable. The stepper
  is purely visual at first — clicking a segment does *not* navigate
  yet (kept as a follow-up).
- **Sequencing:** Depends on `refactor-ui-design-system-v2`. Lands
  before the dashboard grid (`refactor-ui-dashboard-cards`) so the
  Dashboard area has a frame to mount into.
