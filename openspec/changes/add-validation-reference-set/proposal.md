# Add measurement-validated reference design set

## Why

MagnaDesign's physics chain (Steinmetz + iGSE, Dowell, rolloff,
iterative thermal, FEMMT) is internally consistent but has **never
been audited against bench measurements published in the
repository**. The existing tests check analytical-vs-FEA agreement;
they do not show that either matches a real prototype. For an
engineer signing a design off for compressor-inverter production —
or for a quality auditor under ISO 9001 / IATF 16949 / IEC 60335 —
"the model agrees with itself" is not enough. They need
*predicted-vs-measured* deltas on actual hardware.

Without this artefact every other industrial-grade feature
(compliance report, manufacturing spec, worst-case envelope) ranks
as "plausible but unverified". With this artefact MagnaDesign
becomes the only open-source PFC tool with a published validation
chain — a 10× credibility multiplier.

## What changes

A new `validation/` directory at the repo root, containing for each
reference design:

- `<id>/spec.pfc` — the project file (engine inputs + selection).
- `<id>/measurements.csv` — instrument readings: impedance-analyzer
  (Z, L, R) at 5 frequencies, B-coil + integrator at the operating
  point, IR thermal at thermal steady state, line-cycle scope
  capture (V, I, B).
- `<id>/build.md` — build of materials, photos, vendor part numbers,
  shimming notes, winding sequence; everything needed to reproduce.
- `<id>/notebook.ipynb` — Jupyter notebook that loads `spec.pfc`,
  runs the engine + FEA, plots predicted-vs-measured for every
  metric, and emits PASS/FAIL per acceptance threshold.

Three reference designs land in this proposal (others can follow):

| ID | Topology | Pout | Core | Why this one |
|---|---|---:|---|---|
| `boost-600w-magnetics` | Boost CCM | 600 W | Magnetics 60 µ HighFlux toroid | Mainstream PFC; covers Steinmetz + Dowell + rolloff. |
| `line-reactor-3ph-5kw` | 3-phase line reactor | 5 kW | EI-150 silicon-steel lamination | 60 Hz path; covers air-gap + lamination loss. |
| `passive-choke-1kw` | Passive choke | 1 kW | Powder ring | Saturating regime; covers DC-bias + worst-case Bsat margin. |

A **CI job** runs every notebook on every release and uploads the
predicted-vs-measured plots to GitHub Pages. The release fails if
any acceptance threshold regresses.

A new **About → Validation** UI pane shows the latest validation
status (per-design PASS/FAIL chips) so end-users can see the
provenance without leaving the app.

## Impact

- **New artefact**: `validation/` directory (data + notebooks).
- **New CI**: `.github/workflows/validation.yml` (runs notebooks,
  publishes Pages site).
- **New UI surface**: a small "Validation" pane in About dialog
  pulling the latest CI status badge.
- **No engine changes** — this codifies what we already compute and
  measures the truth-gap.
- **External dependency**: needs ~3 weeks of bench time. The
  software side is ~1 week.
- **Capability added**: `validation-traceability`.
