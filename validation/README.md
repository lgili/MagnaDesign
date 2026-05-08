# MagnaDesign — measurement-validated reference designs

This directory holds the **predicted-vs-measured** evidence chain
for MagnaDesign's physics models. Each subdirectory is one
prototype that an engineer built, instrumented, and ran through
the engine; the associated notebook regenerates the comparison
plots from the raw bench data on every CI run.

For a quality auditor (ISO 9001 / IATF 16949 / IEC 60335) the
combination of measurement data + bench setup notes + code
references constitutes the **design-tool qualification dossier**
the standards demand. For an engineer, it's the sanity check
that says "the model agreed with reality on this many built
designs, within these tolerance bands".

## Layout

Each reference design lives at `validation/<id>/` with this
mandatory shape:

```
validation/
├── README.md                  ← this file
├── thresholds.yaml            ← acceptance thresholds (per-metric % delta)
├── lib/
│   ├── __init__.py
│   ├── measure_loader.py     ← parse measurements.csv → typed model
│   └── compare.py             ← (predicted, measured, delta, pass) tuples
├── notebook_template.ipynb   ← copy when starting a new reference
└── <id>/                      ← one folder per built prototype
    ├── spec.pfc               ← the project file the engine ran
    ├── measurements.csv       ← raw bench readings
    ├── build.md               ← BOM, photos, vendor PNs, winding notes
    └── notebook.ipynb         ← comparison + PASS/FAIL summary
```

### `thresholds.yaml`

Loosened where the underlying physics has known dispersion
(e.g. core loss runs ±20 % vendor-to-vendor on Steinmetz fits).
The numbers are project-wide defaults — a notebook may override
locally if its design exercises a known edge case.

### `measurements.csv`

A long-form table with one row per (frequency, condition, metric).
The schema is defined by `measure_loader.MeasurementSet`; see
that module for the canonical column list.

## Acceptance contract

A notebook ends with a single PASS/FAIL summary cell. PASS
means **every** measured metric stays inside its threshold
relative to the engine's prediction. CI runs the notebooks via
papermill and fails the release if a prior-PASS regresses.

## Adding a new reference

1. Build the prototype.
2. Capture the bench data (impedance sweep, B-coil at the
   operating point, thermal steady-state, line-cycle scope).
3. Copy `notebook_template.ipynb` to a new
   `validation/<your-id>/notebook.ipynb`.
4. Fill in `spec.pfc`, `measurements.csv`, and `build.md`.
5. Run the notebook locally; iterate on threshold values vs.
   physics edge cases (don't widen thresholds to mask a real
   gap — file a bug instead).
6. Open a PR. CI will render the notebook to GitHub Pages so
   the predicted-vs-measured plots are reviewable inline.
