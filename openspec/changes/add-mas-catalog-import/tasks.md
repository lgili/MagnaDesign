# Tasks — Import OpenMagnetics MAS catalog

## 1. Catalog source

- [x] 1.1 Identify a stable release tag of `OpenMagnetics/MAS` to vendor.
      Document the tag in `vendor/openmagnetics-catalog/VERSION.txt`.
      (Vendored at commit `f634f7b15e9b` from
      `Power-Supply-Manufacturers-Association/MAS`.)
- [x] 1.2 Add a one-shot fetch step in our release workflow (not at
      install time) that vendors the catalog into the repo.
      (Documented in `vendor/openmagnetics-catalog/VERSION.txt` —
      curl/git-clone snippet for refresh.)

## 2. Import script

- [x] 2.1 `scripts/import_mas_catalog.py`:
      - load each MAS doc under the source dir
      - convert to internal `Material`/`Wire` (cores skipped — see
        script docstring; upstream cores reference shapes without
        effective dimensions)
      - tag `x-pfc-inductor.source = "openmagnetics"`,
        `x-pfc-inductor.catalog_version = <vendor tag>`
- [x] 2.2 Merge logic:
      - if `id` exists in our shipped data: keep ours (we've calibrated
        rolloff/Steinmetz; OpenMagnetics' values aren't always equal)
      - if `id` exists only in catalog: add
      - if `id` exists in user-data overlay: never touch
      - report a summary `<N added, M kept, K skipped (user-edited)>`
- [x] 2.3 Output target: write to `data/mas/catalog/*.json` so shipped
      curated data and imported catalog stay separated.

## 3. Loader integration

- [x] 3.1 `data_loader.py::load_*` discovers entries from both
      `data/mas/*.json` (curated) and `data/mas/catalog/*.json`
      (imported). User-data dir overrides both.
- [x] 3.2 De-duplicate by `id` with the precedence order:
      user-data > curated > catalog.

## 4. UI

- [x] 4.1 Toolbar/menu action "Atualizar catálogo".
- [x] 4.2 Background worker (`QThread`) so a 5–10 s import doesn't block
      the UI. Progress bar in a dialog.
- [x] 4.3 Result dialog: "+N novos, M mantidos, K seus (não tocados)".

## 5. Filtering

- [x] 5.1 In the spec panel material/core/wire combos, add an optional
      "Mostrar apenas curados" toggle for users who want our calibrated
      subset only.
- [x] 5.2 In the optimizer dialog, same toggle so the catalog doesn't
      drown ranking results.

## 6. Tests

- [x] 6.1 Unit test: import script run on a synthetic MAS dir of 3
      materials produces 3 entries with the expected source tag.
      (`tests/test_import_mas_catalog.py`)
- [x] 6.2 Integration test: shipped catalog (mocked) merges without
      colliding with curated data.
- [x] 6.3 Loader test: catalog-only material loads correctly and a
      design using it runs through the engine without errors.
      (`tests/test_data_loader.py::test_catalog_material_drives_design_engine`)

## 7. Docs

- [x] 7.1 README: "Atualizar catálogo" workflow.
- [x] 7.2 Note that imported entries may have different rolloff/Steinmetz
      calibrations than our curated set — link to the calibration
      methodology in the docs.
