# Parts Finder Capability

## ADDED Requirements

### Requirement: Find equivalent cores by geometry

The system SHALL identify cores from the database whose geometric
parameters (Ae, Wa, AL, Bsat, μ_r) fall within configurable tolerances of
a target core.

#### Scenario: Default tolerance match

- **GIVEN** a target core with Ae=200 mm², Wa=500 mm², AL=150 nH
- **WHEN** `find_equivalents` is called with default criteria (10/15/20%)
- **THEN** the result list contains every core with
  - 180 ≤ Ae ≤ 220
  - 425 ≤ Wa ≤ 575
  - 120 ≤ AL ≤ 180

#### Scenario: Exclude target itself

- **GIVEN** the target core is in the database
- **WHEN** `find_equivalents` runs with `exclude_self=True`
- **THEN** the target's own entry does not appear in the results

### Requirement: Cross-material equivalents

The system SHALL include "same vendor + same shape + alternate material"
candidates and recompute the design for each so the user can see how
losses, B_pk and turns change with the swap.

#### Scenario: Cross-material on Magnetics shape

- **GIVEN** target = Magnetics 0058072A2 with default material
  High Flux 60µ
- **WHEN** cross-material is enabled
- **THEN** the result list also includes the same physical shape paired
  with Kool Mu 60µ, MPP 60µ, and XFlux 60µ if those materials exist in
  the database
- **AND** each entry shows the redesigned N, B_pk and loss for that pair

### Requirement: Apply alternative to spec

The system SHALL allow the user to apply any matched alternative as the
active selection in one click.

#### Scenario: Apply matched core

- **WHEN** the user clicks "Aplicar" on a matched row
- **THEN** the spec panel updates with that core (and optionally its
  paired material if cross-material was selected)
- **AND** the result panel recomputes
