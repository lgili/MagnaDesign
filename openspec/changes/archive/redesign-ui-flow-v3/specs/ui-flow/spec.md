# UI Flow v3

## ADDED Requirements

### Requirement: Persistent spec drawer

The system SHALL display a persistent SpecDrawer on the left side of
the Projeto workspace, hosting the same form fields as the legacy
`SpecPanel` (topology, AC input, converter, line-reactor, thermal,
selection). The drawer SHALL be collapsible to a 40 px icon strip and
remember its state across launches via `QSettings`.

#### Scenario: User collapses the drawer

- **GIVEN** the drawer is expanded at default width
- **WHEN** the user clicks the chevron toggle on the inner edge
- **THEN** the drawer animates to ~40 px width
- **AND** all form fields are hidden
- **AND** the chevron flips direction so the user can re-expand.

### Requirement: 4-area sidebar

The system SHALL display exactly four sidebar areas: Projeto,
Otimizador, Catálogo, Configurações. There SHALL be no other
top-level navigation surface (no QToolBar, no second sidebar).

#### Scenario: Sidebar lists exactly four items

- **GIVEN** the application has launched
- **WHEN** the user inspects the sidebar
- **THEN** four QPushButton items are visible
- **AND** their labels are "Projeto", "Otimizador", "Catálogo",
  "Configurações" in that order.

### Requirement: 3-tab workspace inside Projeto

The Projeto area SHALL host a `QTabWidget` with exactly three tabs in
this order: Design, Validar, Exportar. Tab switching SHALL update the
ProgressIndicator's current state.

#### Scenario: Switching to Validar updates the progress indicator

- **GIVEN** the user is on the Design tab; ProgressIndicator shows
  "Design" as current
- **WHEN** the user clicks the Validar tab
- **THEN** the workspace shows Validar content
- **AND** the ProgressIndicator's current state moves to "Validar".

### Requirement: ProgressIndicator with 4 informational states

The system SHALL render a ProgressIndicator widget showing four
states (Spec, Design, Validar, Exportar) above the workspace tabs.
Each state SHALL render in one of three visual modes: pending,
current, done. The widget SHALL NOT respond to mouse clicks (it is
informational, not navigational).

#### Scenario: Indicator is non-interactive

- **GIVEN** the ProgressIndicator is rendered with "Design" current
- **WHEN** the user clicks the "Validar" segment
- **THEN** nothing happens
- **AND** the cursor does not change to a pointing hand on the segment.

### Requirement: Scoreboard with KPI strip

The system SHALL render a Scoreboard at the bottom of the Projeto
area with three regions: save-status indicator on the left, KPI strip
in the centre showing the last calculation's L/B_pk/ΔT/η, Recalcular
icon button on the right (also bound to Ctrl+R).

#### Scenario: Scoreboard updates after recompute

- **GIVEN** a successful design completed: L=376 µH, B_pk=360 mT,
  ΔT=60 °C, η=97 %
- **WHEN** the Scoreboard receives the result
- **THEN** the KPI strip text is exactly
  "L=376 µH · B=360 mT · ΔT=60 °C · η=97 %".

#### Scenario: Ctrl+R triggers recalc

- **GIVEN** the application is focused, Projeto area active
- **WHEN** the user presses Ctrl+R
- **THEN** `_on_calculate` runs
- **AND** the KPI strip updates with the new values.

### Requirement: Optimizer is a first-class page

The system SHALL host the optimizer interface (Pareto sweep + ranked
table + "Aplicar") as a `QWidget` page reachable from the sidebar.
The legacy modal `OptimizerDialog` SHALL no longer be the entry
point.

#### Scenario: Sidebar Otimizador shows the optimizer page

- **GIVEN** the user clicks the Otimizador sidebar item
- **WHEN** the workspace switches
- **THEN** the central area shows a non-modal OtimizadorPage with the
  Pareto plot and candidate table.

### Requirement: Legacy splitter is removed from the shell

The system SHALL NOT mount `SpecPanel | PlotPanel | ResultPanel` as
a 3-column splitter anywhere in the visible UI. There SHALL be no
"Modo clássico" toggle in Configurações.

#### Scenario: No QSplitter in the central widget tree

- **GIVEN** the application has launched
- **WHEN** the central widget tree is inspected
- **THEN** no `QSplitter` containing `SpecPanel`, `PlotPanel`,
  `ResultPanel` exists.

### Requirement: Recalcular is the single Primary CTA

The system SHALL render exactly one Primary-styled
(`QPushButton[class~="Primary"]`) button per visible workspace, and
that button SHALL be the Recalcular action. Other CTAs (Comparar,
Gerar Relatório) SHALL use the Secondary class.

#### Scenario: Header has one Primary button

- **GIVEN** the workspace header is visible
- **WHEN** the user inspects the right-side CTA group
- **THEN** exactly one button has `class="Primary"` set
- **AND** that button's text is "Recalcular".

### Requirement: Topology change is initiated from the drawer

The system SHALL expose the topology selector inside the SpecDrawer.
The TopologyPickerDialog SHALL be reachable from a button next to the
topology combobox in the drawer (not from a card on the dashboard).

#### Scenario: Open picker from drawer

- **GIVEN** the user is on Projeto/Design with the drawer expanded
- **WHEN** the user clicks "Alterar Topologia" inside the drawer
- **THEN** TopologyPickerDialog opens
- **AND** applying a different topology updates the drawer's
  combobox and triggers a recalc.
