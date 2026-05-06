# Litz Optimization Capability

## ADDED Requirements

### Requirement: Sullivan-criterion strand diameter

The system SHALL compute the optimal Litz strand diameter for a given
frequency and layer count using the Sullivan (1999) criterion:
`d_strand ≈ 2·δ(f) · √(η · π / Nₗ²)`.

#### Scenario: Strand diameter at 100 kHz

- **WHEN** `sullivan_strand_diameter(f_Hz=100_000, layers=1)` is called
- **THEN** the result is between 0.08 mm and 0.13 mm

### Requirement: Recommend a Litz construction

The system SHALL, given a spec and a chosen core, recommend a Litz
construction (strand AWG, count, bundle diameter) that minimises copper
loss subject to current density and feasibility constraints, and compare
it against the best round-wire option from the current database.

#### Scenario: Litz beats round wire at high frequency

- **GIVEN** a 65 kHz boost CCM design with a Magnetics High Flux 60µ core
- **WHEN** the user runs the Litz optimizer with target_J = 4 A/mm² and
  target_AC_DC = 1.10
- **THEN** the recommended construction has strand AWG between 38 and 42
- **AND** strand count between 100 and 600
- **AND** the recommended construction has lower P_cu than the best
  round-AWG wire in the database

### Requirement: Save recommended Litz as a database entry

The system SHALL allow the recommended Litz construction to be saved as a
new entry in the user-data wires.json so it persists across sessions and
can be selected directly without re-running the optimizer.

#### Scenario: Save recommended Litz

- **GIVEN** the optimizer recommended a 200×AWG40 Litz wire
- **WHEN** the user clicks "Salvar como novo fio"
- **THEN** a `Wire` entry with `type="litz"`, `n_strands=200`,
  `awg_strand=40`, computed `A_cu_mm2` and `d_bundle_mm` is written to
  the user-data wires.json
- **AND** the wire combobox in the spec panel includes the new entry on
  next refresh
