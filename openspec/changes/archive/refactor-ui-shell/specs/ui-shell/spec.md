# UI Shell

## ADDED Requirements

### Requirement: Persistent navy sidebar with branded navigation

The system SHALL display a 250 px wide sidebar on the left side of the
main window. The sidebar background SHALL use `SIDEBAR.bg` (theme-
invariant navy) and contain three sections: a brand block, a
navigation list, and a footer.

#### Scenario: Sidebar nav items map to workspace areas

- **GIVEN** the sidebar contains 8 nav items
  (Dashboard / Topologia / Núcleos / Bobinamento / Simulação /
  Mecânico / Relatórios / Configurações)
- **WHEN** the user clicks "Núcleos"
- **THEN** the sidebar emits `navigation_requested("nucleos")`
- **AND** the active state visually moves to that item.

#### Scenario: Footer overflow menu hosts legacy tools

- **GIVEN** the sidebar's footer "…" button is visible
- **WHEN** the user clicks it
- **THEN** a `QMenu` opens listing at minimum: DB Editor, MAS Catalog,
  Optimizer, FEA Validation, Litz Optimizer, BH Loop, Similar Parts,
  About.

### Requirement: Workspace header surfaces project state and CTAs

The system SHALL render a workspace header above the page area
containing: an editable project name, a save-status pill, a
"Comparar soluções" secondary button, and a "Gerar Relatório"
primary button.

#### Scenario: Editing the project name

- **GIVEN** the header shows project name "PFC-1500W-Wide-Input"
- **WHEN** the user clicks the pencil icon and types a new name
- **THEN** the header emits `name_changed(str)`
- **AND** the save-status pill switches from "Salvo" (green) to
  "Não salvo" (amber).

#### Scenario: Generate Report CTA is the primary action

- **GIVEN** the header is fully laid out
- **WHEN** the user inspects the right side
- **THEN** the rightmost button is "Gerar Relatório" with the primary
  fill (`palette.accent`)
- **AND** the immediately-left "Comparar soluções" uses the secondary
  outline style.

### Requirement: 8-step horizontal workflow stepper

The system SHALL display a stepper widget with 8 numbered segments in
this order: Topologia, Entrada de Dados, Cálculo, Núcleo, Bobinamento,
Simulação FEM, Mecânico, Relatório. Each segment SHALL render in one
of three states: `done`, `active`, `pending`.

#### Scenario: Stepper reflects current workflow position

- **GIVEN** the user has completed steps 1–3 and is currently on step 4
  ("Núcleo")
- **WHEN** the stepper renders
- **THEN** segments 1–3 use the `done` style (green circle with check
  glyph)
- **AND** segment 4 uses the `active` style (violet fill, semibold label)
- **AND** segments 5–8 use the `pending` style (outlined circle,
  muted label).

### Requirement: Bottom status bar with save status and validation pills

The system SHALL display a bottom status bar showing the project
save status on the left and three semantic pills on the right:
`Avisos` (warning), `Erros` (danger), `Validações` (success).

#### Scenario: Status bar updates after a successful calculation

- **GIVEN** a fresh design produced 12 passing validations and no
  warnings or errors
- **WHEN** `WorkflowState.set_validations(12)` etc. fires
- **THEN** the right side of the status bar shows
  `0 Avisos` (neutral pill), `0 Erros` (neutral pill), `12 Validações`
  (success pill)
- **AND** the left side shows the save status with a green dot.

#### Scenario: Zero counts use the neutral pill variant

- **GIVEN** a counter equals zero
- **WHEN** the status bar renders that pill
- **THEN** the background uses `palette.surface_elevated` (neutral)
  rather than the semantic colour
- **AND** the text colour stays `palette.text_secondary`.

### Requirement: WorkflowState is the single source of truth

The system SHALL expose a single `WorkflowState` object that owns the
mutable shell state (current step, completed steps, project name,
unsaved flag, last_saved_at, warnings/errors/validations counts).
The sidebar, header, stepper, and status bar SHALL subscribe to its
`state_changed` signal rather than mutate each other directly.

#### Scenario: A single update propagates to every subscriber

- **GIVEN** the sidebar, header, stepper, and status bar are all
  constructed and connected
- **WHEN** `WorkflowState.set_current_step(4)` is called
- **THEN** the stepper repaints with step 4 active
- **AND** the sidebar's "Núcleos" item highlights
- **AND** no other subscriber emits a redundant signal.

### Requirement: Project save state persists across launches

The system SHALL persist the project name, last_saved_at timestamp,
and completed_steps set in `QSettings` under the key prefix `shell/`.
On the next launch, those fields SHALL be restored before the shell
becomes visible.

#### Scenario: Persisted state survives quit and relaunch

- **GIVEN** a user named the project "PFC-1500W" and completed steps 1–3
- **WHEN** the user closes the application and reopens it
- **THEN** the header shows "PFC-1500W"
- **AND** the stepper shows steps 1–3 in `done` state.
