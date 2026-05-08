# Tasks — add-validation-reference-set

## Phase 1 — Software scaffolding (no bench needed)

- [x] `validation/README.md` — explain the directory's contract:
      one folder per design, mandatory files, acceptance thresholds,
      onboarding flow ("how to add a new reference").
- [x] Define acceptance thresholds in `validation/thresholds.yaml`:
      `L_pct: 5`, `Bpk_pct: 8`, `dT_C: 10` (absolute °C),
      `Pcu_pct: 15`, `Pcore_pct: 20`, `total_loss_pct: 15`,
      `R_ac_pct: 25`. Each tolerance carries an inline citation
      explaining the band choice (Magnetics AL spread, IEC 60401-3
      lot variation, Dowell residual, etc.).
- [x] `validation/lib/measure_loader.py` — typed
      `Measurement` + `MeasurementSet` containers parsing
      long-form CSV (one row per metric × condition × frequency).
      SI suffix tolerant (``510u``, ``65k``), defensive against
      malformed rows (skip + stderr warning, never crash the load).
      Plus `load_thresholds(yaml)` companion.
- [x] `validation/lib/compare.py` — `compare(result,
      measurements, thresholds)` returns
      ``(list[MetricComparison], PassFailSummary)``. Built-in
      DSL maps each threshold key to a `DesignResult` attribute
      with optional unit-scaling (`L_actual_uH * 1e-6` to match
      bench henries). Missing measurements surface as "no
      measurement" entries — never silently dropped.
- [x] `validation/lib/notebook_template.ipynb` — 5-cell skeleton
      tagged ``load`` / ``engine`` / ``compare`` / ``plots`` /
      ``summary``. The summary cell asserts ``summary.all_passed``
      so papermill exit codes regress on regressions.
- [x] `tests/test_validation_lib.py` — 11 tests covering SI-suffix
      parsing, malformed-row skip, threshold YAML loader, exact-
      match passes, 50 %-disagreement fails, missing-measurement
      "skip" entries, render_summary verdict line.

## Phase 2 — First reference design (`boost-600w-magnetics`)

- [ ] Build the 600 W boost-PFC choke per the spec recommended by
      MagnaDesign at default catalogue + Magnetics 60 µ HighFlux.
- [ ] Capture impedance sweep on Keysight E4990 (or equivalent) —
      L vs f from 10 kHz to 1 MHz; ESR at fsw.
- [ ] Capture B-pk via integrating B-coil at low-line worst-case
      operating point.
- [ ] Capture thermal steady-state via FLIR / thermocouple at
      Pout, T_amb = 25 °C.
- [ ] Populate `validation/boost-600w-magnetics/` with `spec.pfc`,
      `measurements.csv`, `build.md` (incl. 4 photos), `notebook.ipynb`.
- [ ] Run the notebook locally; iterate until acceptance thresholds
      pass OR document the gap (and use it to file engine bug
      reports for follow-up).

## Phase 3 — CI pipeline

- [ ] `.github/workflows/validation.yml`: install `[validation]`
      extra (papermill + nbformat + plotly), run `papermill` on each
      notebook with timeout, fail on PASS/FAIL summary regression.
- [ ] Publish rendered HTML notebooks to GitHub Pages under
      `gh-pages/validation/<id>/`.
- [ ] Add a status-badge endpoint
      (`https://raw.githubusercontent.com/.../validation/badge.svg`)
      readable from the app's About dialog.

## Phase 4 — UI surface

- [ ] In `AboutDialog`, add a "Validation" tab that:
      - Fetches the badge URL (with a 2 s timeout, graceful fallback
        to "offline").
      - Shows per-design PASS/FAIL chips with a "View report" link
        opening the GitHub Pages notebook.
      - Surfaces the validation date + commit SHA so users can
        match the version they're running against the proven set.
- [ ] Test: `tests/test_about_dialog_validation_pane.py` — mock the
      HTTP call; verify the chips render and links open.

## Phase 5 — Two more reference designs

- [ ] Build, measure, document `line-reactor-3ph-5kw`.
- [ ] Build, measure, document `passive-choke-1kw`.
- [ ] CI runs all three on every release.

## Phase 6 — Docs + Release

- [ ] `docs/validation/methodology.md`: bench setup, instruments,
      uncertainties, acceptance threshold rationale.
- [ ] Reference the validation page from `README.md` (top
      "Validated" badge + link).
- [ ] Tag a release that includes the first three validated
      designs; mention them in `CHANGELOG.md`.
