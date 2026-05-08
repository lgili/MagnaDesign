# Tasks — add-validation-reference-set

## Phase 1 — Software scaffolding (no bench needed)

- [ ] `validation/README.md` — explain the directory's contract:
      one folder per design, mandatory files, acceptance thresholds.
- [ ] Define acceptance thresholds in `validation/thresholds.yaml`:
      `L_pct: ±5`, `Bpk_pct: ±8`, `dT_C: ±10`, `Pcu_pct: ±15`,
      `Pcore_pct: ±20`. Loosened where physics has known dispersion.
- [ ] `validation/lib/measure_loader.py` — Pydantic model parsing
      `measurements.csv` into a typed `MeasurementSet` (Z-vs-f
      table, B-coil scope, thermal map, line-cycle waveforms).
- [ ] `validation/lib/compare.py` — given a `MeasurementSet` and
      a `DesignResult`, return per-metric (predicted, measured,
      pct_delta, threshold, pass) tuples.
- [ ] `validation/lib/notebook_template.ipynb` — copy-paste skeleton
      that any new design can clone: load spec, run engine, run FEA,
      load measurements, render plots, emit PASS/FAIL summary.

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
