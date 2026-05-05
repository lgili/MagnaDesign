# Design Comparison Capability

## ADDED Requirements

### Requirement: Compare 2 to 4 designs side-by-side

The system SHALL display up to four candidate designs in parallel columns,
each showing the same KPI groups (inductance, currents, flux, losses,
thermal, window utilization).

#### Scenario: Add three designs to comparison

- **GIVEN** the optimizer returned a Pareto-front of feasible designs
- **WHEN** the user adds three of them to the comparison view
- **THEN** the dialog shows three columns, each labelled by core part
  number + wire id + material
- **AND** every metric row aligns horizontally across columns

### Requirement: Diff-aware highlighting

For each metric the system SHALL colour cells in columns 2..N relative to
column 1 according to the metric's "better-is-lower" or "better-is-higher"
semantics.

#### Scenario: Loss is lower in column 2

- **GIVEN** column 1 P_total = 10.0 W and column 2 P_total = 7.5 W
- **WHEN** comparison is rendered
- **THEN** column 2's P_total cell has a green background
- **AND** the cell text shows "−25%" delta

#### Scenario: Sat margin is lower in column 2

- **GIVEN** column 1 sat_margin = 50% and column 2 sat_margin = 30%
- **WHEN** comparison is rendered
- **THEN** column 2's sat_margin cell has a red background
- **AND** the delta is "−40%"

### Requirement: Apply slot selection

The system SHALL allow the user to apply any compared design as the active
project selection in one click.

#### Scenario: Apply column 3

- **WHEN** the user clicks "Aplicar coluna 3"
- **THEN** the spec panel updates with that column's material/core/wire
- **AND** the main result panel recomputes for that selection
- **AND** the comparison dialog closes

### Requirement: Export comparison as report

The system SHALL export the comparison view as a self-contained HTML file
preserving the column layout and diff highlighting.

#### Scenario: Export 4-column comparison

- **WHEN** the user clicks "Exportar HTML"
- **THEN** an HTML file is written that, when opened in a browser, shows
  all four columns and their diff colours without external resources.
