# Cost Modeling Capability

## ADDED Requirements

### Requirement: Cost fields on materials, cores, wires

The system SHALL accept optional cost fields on each database entry:

- `Material.cost_per_kg`, `Material.cost_currency`
- `Core.cost_per_piece`, `Core.mass_g`
- `Wire.cost_per_meter`, `Wire.mass_per_meter_g`

#### Scenario: Cost fields default to absent

- **GIVEN** a material loaded from JSON without a `cost_per_kg` field
- **WHEN** the model is parsed
- **THEN** `cost_per_kg` is `None`
- **AND** validation does not fail

### Requirement: Estimate total design cost

The system SHALL compute the total cost of a design as the sum of the core
piece cost (or mass-derived cost) and the wire-length cost.

#### Scenario: Compute cost when all fields are populated

- **GIVEN** a core with `cost_per_piece = 2.50 USD`, a wire with
  `cost_per_meter = 0.10 USD/m`, MLT = 80 mm, N = 50
- **WHEN** `estimate(...)` is called
- **THEN** wire_cost = 50 · 0.080 m · $0.10 = $0.40
- **AND** core_cost = $2.50
- **AND** total_cost = $2.90

#### Scenario: Skip cost when wire price is missing

- **GIVEN** a wire without `cost_per_meter`
- **WHEN** `estimate(...)` is called
- **THEN** the function returns `None`

### Requirement: Cost-aware ranking in the optimizer

The optimizer SHALL support ranking designs by total cost (lowest first)
and by a composite score that weights loss, volume, and cost.

#### Scenario: Rank by cost

- **GIVEN** a sweep result containing 100 feasible designs with costs
  populated
- **WHEN** the user picks "Menor custo" in the rank dropdown
- **THEN** the result list is ordered by ascending total_cost

### Requirement: Display estimated cost in the result panel

When all required cost fields are present, the result panel SHALL display
a "Custo estimado" KPI group with separate rows for core, wire and total.

#### Scenario: Hide cost when missing

- **GIVEN** the wire selected has no `cost_per_meter`
- **WHEN** the result panel renders
- **THEN** the cost group is hidden (no empty rows)
