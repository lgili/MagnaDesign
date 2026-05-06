# Adopt OpenMagnetics MAS schema

## Why

The PSMA-incubated **OpenMagnetics MAS** (Magnetic Agnostic Structure) is
becoming the industry's vendor-neutral data model for power magnetics. It
ships with **410 materials, 300 core shapes, 4 350 wires, 300 bobbins** —
roughly 8× our current dataset — and is what the broader open-source
community will converge on (FEMMT is already adopting it).

Refactoring our `Material`/`Core`/`Wire` models to be MAS-compatible buys us:

- a 1-step path to importing the OpenMagnetics catalog (see
  `add-mas-catalog-import`)
- interoperability with FEMMT, MKF, and other consumers of MAS documents
- fewer bespoke fields invented by us; clearer semantics

What we'd break: today's hand-rolled JSON layout. We'd need a one-shot
migration of `data/*.json` and the importer (`scripts/import_xlsm.py`).

## What changes

- New module `models/mas/` with pydantic models that mirror the MAS JSON
  schema (Inputs / Magnetic / Outputs blocks).
- Adapters: `Material.from_mas(mas_doc)` and `to_mas()`. Same for `Core`,
  `Wire`. Internal API stays — only the persisted JSON migrates.
- Migration script `scripts/migrate_to_mas.py` that reads our current
  data files and writes the MAS-shaped equivalents to `data/mas/*.json`.
- Loader (`data_loader.py`) gains MAS-first detection, falling back to the
  legacy schema for any user-edited file still in the old format.
- All physics modules (rolloff, copper, core_loss, thermal, cost) read
  from the same `Material`/`Core`/`Wire` API, so they need zero changes
  if the adapters are correct.

## Impact

- Affected capabilities: NEW `mas-compatibility`
- Affected modules: `models/material.py`, `models/core.py`, `models/wire.py`,
  `data_loader.py`, NEW `scripts/migrate_to_mas.py`, `data/*.json` (migrated).
- Existing tests must keep passing; tests against MAS round-trips added.
- Heaviest single change in the v3 roadmap; gates `add-mas-catalog-import`.
- Time-bounded risk: MAS schema is in incubation, so we'll pin a specific
  schema version and update on cadence (semver).
