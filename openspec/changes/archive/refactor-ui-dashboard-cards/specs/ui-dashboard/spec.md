# UI Dashboard

## ADDED Requirements

### Requirement: Dashboard renders 9 purpose-built cards in a 3-row grid

The system SHALL render the design dashboard as nine cards laid out in
three rows: row 0 = (Topologia, Resumo, Formas de Onda); row 1 =
(Núcleo, Visualização 3D spanning two columns); row 2 = (Perdas,
Bobinamento, Entreferro, Próximos Passos).

#### Scenario: Card grid is visible on launch

- **GIVEN** the application has just launched and Dashboard is the
  active sidebar area
- **WHEN** the workspace renders
- **THEN** all nine cards are visible in their assigned grid positions
- **AND** each card has its title, surface, border, and shadow.

### Requirement: Card widget enforces consistent visual style

The system SHALL provide a reusable `Card` widget that enforces a
16 px outer radius, 1 px `palette.border` stroke, surface
`palette.surface`, header with 14 px semibold title, and a
`palette.card_shadow_sm` drop shadow.

#### Scenario: Two cards rendered side-by-side share the same chrome

- **GIVEN** the dashboard renders the Resumo and Formas de Onda cards
- **WHEN** both are visible on screen
- **THEN** their outer corner radius, border colour, and shadow params
  are byte-equal at the QSS level.

### Requirement: MetricCard surfaces a single quantity with optional trend

The system SHALL provide a `MetricCard` widget showing a label, a
large numeric value, a unit, and an optional trend chip (e.g.
"▲ +5%"). The numeric value SHALL use the project's monospace numeric
family with the `tabular-nums` feature enabled so digits do not jitter
when the value updates.

#### Scenario: Trend chip colours match direction semantics

- **GIVEN** a `MetricCard` for `T_rise (°C)` with prior value 65 °C and
  current value 58 °C
- **WHEN** the card renders the trend
- **THEN** the chip text is `▼ −10.8 %`
- **AND** the chip uses the success colour (lower temperature is
  better).

### Requirement: ScorePill maps score ranges to semantic colours

The system SHALL provide a `ScorePill` widget that picks its colour
variant from the numeric score: `[85,100]→success, [70,85)→info,
[55,70)→warning, [40,55)→amber, [0,40)→danger`.

#### Scenario: Core selection table shows ranked scores

- **GIVEN** the Núcleo card's table contains rows with scores
  92, 78, 64, 50, 30
- **WHEN** the table renders
- **THEN** the pills are coloured success, info, warning, amber, danger
  respectively.

### Requirement: Dashboard updates atomically after a calculation

The system SHALL update all nine cards from a single
`update_from_design(result, spec, core, wire, material)` call. Cards
that have no data yet (e.g. before the first calculation) SHALL show a
neutral placeholder state rather than partial / stale numbers.

#### Scenario: First calculation populates every card

- **GIVEN** the user has just launched the app and clicks "Calcular"
- **WHEN** the design completes successfully
- **THEN** all nine cards transition from placeholder to populated in
  the same paint frame
- **AND** no card briefly shows the previous (placeholder) text.

### Requirement: Resumo do Projeto pill reflects aggregate status

The system SHALL display an aggregate status pill at the bottom of the
Resumo card: "Aprovado" (success) when every metric's individual
status is `ok`; "Verificar" (warning) when any is `warn`; "Reprovado"
(danger) when any is `err`.

#### Scenario: One warning trips the aggregate to "Verificar"

- **GIVEN** the Resumo card has 6 metrics — 5 with status `ok` and 1
  with status `warn`
- **WHEN** the aggregate pill is computed
- **THEN** the pill text is "Verificar" and the colour is the warning
  variant.

### Requirement: Próximos Passos surfaces actionable next steps

The system SHALL render a `NextStepsCard` whose items reflect the
current design state: "Validar com FEM", "Comparar com alternativos",
"Otimizar Litz", "Gerar relatório", "Buscar similares". Each item
SHALL show one of three statuses: `done` (check icon), `pending`
(clock icon), `todo` (arrow icon).

#### Scenario: After a Litz wire is selected, the Litz step shows done

- **GIVEN** the user picked a Litz wire (`wire.kind == "litz"`)
- **WHEN** the dashboard refreshes
- **THEN** the "Otimizar Litz" item shows the `done` status icon and
  is no longer interactive.

### Requirement: Legacy panels remain available behind a setting

The system SHALL keep the v1 panels (Spec / Plot / Result splitter)
reachable via Configurações → "Modo clássico" for one release. The
default setting is *off* (dashboard is the default view).

#### Scenario: Switching to classic mode swaps the central widget

- **GIVEN** the user enables "Modo clássico" in Configurações
- **WHEN** the setting is saved
- **THEN** the workspace central area shows the v1 splitter layout
- **AND** the dashboard page is removed from the stack but no data is
  lost.
