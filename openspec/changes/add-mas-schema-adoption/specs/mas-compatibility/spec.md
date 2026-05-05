# MAS Compatibility Capability

## ADDED Requirements

### Requirement: Persist data in MAS-compatible JSON

The application SHALL store its component database in JSON files conforming
to a pinned version of the OpenMagnetics MAS schema. Internal code SHALL
load these files via adapters into the existing `Material`/`Core`/`Wire`
API.

#### Scenario: Validate shipped data against the pinned schema

- **GIVEN** every file under `data/mas/*.json`
- **WHEN** the test suite runs `jsonschema.validate` against the pinned
  MAS schema version
- **THEN** every file passes validation with no errors

### Requirement: Round-trip equivalence

The system SHALL preserve a round-trip equivalence: parsing a MAS document
into our internal model and writing it back SHALL yield a document that
re-parses to the same internal values within float epsilon.

#### Scenario: Round-trip every material in the shipped catalog

- **WHEN** each material in `data/mas/materials.json` is loaded, converted
  to internal form, and re-emitted via `to_mas()`
- **THEN** the resulting MAS document differs from the source only in
  ordering or whitespace
- **AND** all numeric fields agree within 1e-9 relative tolerance

### Requirement: Backward-compatible loader

The data loader SHALL read both MAS-shaped JSON files and the legacy
schema, preferring MAS when both are present at the same path level.

#### Scenario: User has only legacy files

- **GIVEN** the user-data dir contains legacy-format `materials.json`
- **WHEN** the application starts
- **THEN** it loads the legacy file successfully
- **AND** the result panel renders identical KPIs vs. the MAS variant

### Requirement: Vendor extension namespace

Application-specific fields not covered by MAS (cost data, raw loss
measurements, demo flags) SHALL be stored under the `x-pfc-inductor`
namespace key in the MAS document, never at the top level.

#### Scenario: Custom cost field round-trips

- **GIVEN** a material with `cost_per_kg = 22.0 USD`
- **WHEN** the material is written to MAS form
- **THEN** the JSON contains
  `{"x-pfc-inductor": {"cost_per_kg": 22.0, "cost_currency": "USD"}}`
- **AND** loading the file restores the cost value to the internal model
