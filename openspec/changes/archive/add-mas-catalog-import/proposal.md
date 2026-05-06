# Import the OpenMagnetics MAS catalog

## Why

OpenMagnetics ships a curated catalog of **410 materials, 300 core shapes,
4 350 wires, 300 bobbins**. Once we are MAS-compatible (see
`add-mas-schema-adoption`), pulling that catalog gives our users an
instant ~8× expansion of available components — for free, with zero
manual data entry.

This is a separate concern from the schema adoption itself: the import
script is a small, self-contained tool that consumes published MAS
documents and merges them with our database, deduplicating by `id`.

## What changes

- New script `scripts/import_mas_catalog.py [--source <url|path>]`
  - Default source: vendored `vendor/openmagnetics-catalog/` (downloaded
    at release-time, not at import-time).
  - Reads MAS-shaped material/core/wire docs.
  - Merges with our existing data, prioritising user edits in
    `~/Library/Application Support/PFCInductorDesigner/*.json` (never
    overwrites user data).
  - Tags every imported entry with `x-pfc-inductor.source = "openmagnetics"`
    so it can be filtered out later.
- New UI menu item **"Atualizar catálogo de componentes"** that runs the
  import in a `QThread`, reports new/updated/skipped counts.
- README section explaining the catalog source and update cadence.

## Impact

- Affected capabilities: NEW `mas-import`
- Depends on: `add-mas-schema-adoption` (must land first)
- Affected modules: NEW `scripts/import_mas_catalog.py`,
  `data_loader.py` (merge helper), `ui/main_window.py` (menu action),
  README.
- DB size grows ~8×; loading time stays under 100 ms (was ~30 ms) — the
  data loader caches.
- No new runtime deps if we vendor the catalog at release time;
  alternatively `[catalog]` extras with `requests`.
