# Tasks — MAS schema adoption

## 1. Vendor + pin

- [x] 1.1 Pin OpenMagnetics MAS schema version (e.g. 0.4.x) in
      `pyproject.toml` extras `[mas]` and document in README.
- [x] 1.2 Vendor the schema JSON files into `vendor/openmagnetics-mas/` so
      builds are reproducible without network.
- [x] 1.3 Generate pydantic models from the MAS JSON Schema using
      `datamodel-code-generator` → `models/mas/_generated.py`.
- [x] 1.4 Wrap the generated models with thin pydantic-v2 friendly classes
      under `models/mas/__init__.py` (cleaner type names, defaults for
      optional fields).

## 2. Adapters

- [x] 2.1 `models/mas/adapters.py::material_from_mas(doc) -> Material`
      and `material_to_mas(m) -> dict`. Cover: μ_initial, Bsat at temps,
      Steinmetz coefs, rolloff, density, cost.
- [x] 2.2 Same for `core_from_mas` / `core_to_mas`. Map MAS shape →
      our `Core.shape`; preserve OD/ID/HT for toroids and W/H/D for
      bobbin shapes.
- [x] 2.3 Same for `wire_from_mas` / `wire_to_mas`. Cover round + Litz +
      foil with MAS construction descriptors.
- [x] 2.4 Round-trip property tests: `to_mas(from_mas(doc)) == doc`
      modulo float epsilon.

## 3. Loader migration

- [x] 3.1 `data_loader.py`: add format probe — first try MAS shape
      (presence of `magneticInputs`, `magnetic`, etc.), fall back to
      legacy.
- [x] 3.2 New `data/mas/{materials,cores,wires}.json` containing the
      migrated content.
- [x] 3.3 Keep legacy `data/*.json` available behind a CLI flag so the
      user-data overlay continues to work while users adopt the new
      format.

## 4. Migration script

- [x] 4.1 `scripts/migrate_to_mas.py` reads legacy `data/*.json` and
      writes equivalent `data/mas/*.json`. Idempotent.
- [x] 4.2 Verify with diff that round-tripping our existing 50 materials
      / 1008 cores / 48 wires preserves all design results within float
      tolerance (smoke: regenerate every `tests/test_design_engine`
      fixture under MAS).

## 5. Importer adaptation

- [x] 5.1 Update `scripts/import_xlsm.py` to emit MAS-shaped JSON
      (instead of legacy). Demo costs and rolloff library remain.
- [x] 5.2 Add a `--legacy` flag for users who want the old layout.

## 6. Documentation

- [x] 6.1 README: data layout section explaining MAS adoption, with a
      link to the OpenMagnetics MAS spec.
- [x] 6.2 `docs/data-format.md`: side-by-side legacy ↔ MAS field map for
      anyone editing JSON by hand.

## 7. Tests

- [x] 7.1 Property test: round-trip every shipped Material/Core/Wire to
      MAS and back; equal up to float epsilon.
- [x] 7.2 Regression: existing `tests/test_design_engine.py` and
      `tests/test_optimize.py` must pass unchanged when DB is loaded
      from MAS-shaped files.
- [x] 7.3 Schema validation test: every `data/mas/*.json` file passes
      `jsonschema.validate(...)` against the pinned MAS schema.
