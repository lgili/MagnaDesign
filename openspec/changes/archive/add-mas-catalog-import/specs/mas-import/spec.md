# MAS Catalog Import Capability

## ADDED Requirements

### Requirement: Import OpenMagnetics MAS catalog into the database

The application SHALL provide a one-click action to import a vendored
release of the OpenMagnetics MAS catalog into the local component
database, growing the catalog of available materials, cores and wires
without overwriting user-edited entries.

#### Scenario: Fresh install, no user edits

- **GIVEN** the application has just been installed and the user has
  made no DB edits
- **WHEN** the user clicks "Atualizar catálogo"
- **THEN** the imported catalog merges with the curated set, no
  duplicate IDs are created, and the result dialog reports
  `<N> novos · <M> mantidos · 0 seus`

#### Scenario: User has edited a material

- **GIVEN** the user has saved a custom version of `magnetics-60_highflux`
  via the DB editor
- **WHEN** the user clicks "Atualizar catálogo"
- **THEN** the user-edited entry is left untouched
- **AND** the result dialog reports the user entry under
  `seus (não tocados)`

### Requirement: Source-tag every imported entry

Every imported entry SHALL be tagged with provenance metadata so it can
be distinguished from curated and user-edited entries.

#### Scenario: Imported material carries source tag

- **GIVEN** an entry imported from the OpenMagnetics catalog
- **WHEN** the entry is read back from disk
- **THEN** it carries `x-pfc-inductor.source = "openmagnetics"`
- **AND** carries `x-pfc-inductor.catalog_version` equal to the vendored
  catalog tag

### Requirement: Filter curated vs. imported in UI

The spec panel and optimizer dialog SHALL expose a toggle to restrict
selection lists to curated entries only, hiding catalog imports.

#### Scenario: Toggle hides catalog entries

- **GIVEN** the catalog has been imported and the spec panel material
  combo lists 460 entries
- **WHEN** the user enables "Mostrar apenas curados"
- **THEN** the combo lists only the curated 50 entries
