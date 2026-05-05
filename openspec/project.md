# PFC Inductor Designer — Project Overview

Desktop tool (Python 3.11+, PySide6) for designing PFC choke inductors for
worldwide-input refrigerator-compressor inverters (200–2000 W). Targets two
topologies: active boost CCM and passive line-frequency choke.

## Why this exists

The open-source magnetics-design landscape (FEMMT, OpenMagnetics MAS,
AI-mag) is strong on FEM and generic schemas but does not serve the
specific need of **a PFC engineer who has to ship inverters worldwide
with cost-aware decisions and a Brazilian supply chain**. This project
specialises vertically rather than horizontally: PFC topology-aware
maths, in-tool cost model, Litz optimizer, multi-design compare, B-H
loop visualisation, polished bilingual UI, Brazilian vendors.

When in doubt about scope or trade-offs, see
[`docs/POSITIONING.md`](../docs/POSITIONING.md) and
[ADR 0001 — Positioning](../docs/adr/0001-positioning.md). PRs are
expected to respect the seven differentials documented there.

## Current state (v0.1)

- ~4400 LOC across `src/pfc_inductor/`, 33 pytest cases (all green).
- 5 vendors imported from `Otimizador_Magneticos.xlsm`: 50 materials, 1008
  cores, 48 wires (full AWG range).
- Calibrated DC-bias rolloff per (vendor, family, μ_r) for Magnetics families
  (Kool Mu, MPP, High Flux, XFlux), Magmattec, Micrometals, CSC.
- Anchored Steinmetz (Pv_ref, α, β fitted from 12 datapoints per material).
- iGSE for ripple loss (time-averaged Pv(t) over the line cycle).
- Boost CCM operating-point + waveform generation; passive choke topology.
- Iterative thermal solve coupled with copper resistivity vs T.
- Dowell AC resistance for round wire and Litz.
- Pareto sweep optimizer (cores × wires) with QtThread worker, ~2000 designs/s.
- Database editor (JSON-backed, user-data-dir overlay).
- Self-contained HTML report (embedded base64 plots).
- 3D core viewer (PyVista/pyvistaqt) with parametric meshes for toroid, EE,
  ETD, PQ + helical winding; falls back gracefully on offscreen platforms.

## Architecture

```
src/pfc_inductor/
  models/      # Pydantic v2: Spec, Core, Wire, Material, DesignResult
  physics/     # rolloff, copper (DC + Dowell), core_loss (iGSE), thermal
  topology/    # boost_ccm, passive_choke
  design/      # engine.py (orchestrator)
  optimize/    # sweep.py + Pareto
  visual/      # core_3d.py (parametric meshes)
  ui/          # PySide6 widgets: spec/result/plot panels, optimizer dialog,
               # DB editor, 3D viewer
  report/      # html_report.py
data/          # bundled materials/cores/wires JSON
scripts/       # import_xlsm.py
tests/         # pytest regression suite
```

## Conventions

- All physics units: SI internally; UI shows engineering units (mT, Oe, mm,
  A, W, °C, kHz). Conversions at the boundary.
- Steinmetz form: `Pv [mW/cm³] = Pv_ref · (f/f_ref)^α · (B/B_ref)^β`,
  anchored at (100 kHz, 100 mT) by default.
- Rolloff form: `μ_fraction = 1 / (a + b · H[Oe]^c)`, calibrated against
  vendor 50%-permeability bias points.
- Worst-case design point: low-line (`Vin_min_Vrms`), peak ripple at
  `vin = Vout/2` (or line peak when `Vin_pk < Vout/2`).
- All physics modules are stateless functions; orchestration lives in
  `design.engine`.
- Tests under `tests/`; every physics module has a regression test against a
  textbook or vendor app-note datapoint.

## Roadmap (v2 capabilities planned)

These have OpenSpec proposals in `openspec/changes/`:

- `add-fea-validation` — confirm analytic design against FEMM 2D-axisymmetric
- `add-bh-loop-visual` — render B–H operating loop at the design point
- `add-multi-column-compare` — side-by-side comparison of 2–4 designs
- `add-litz-optimizer` — automatic strand-count/gauge optimizer for Litz
- `add-cost-model` — `$` per design, including in optimizer Pareto axes
- `add-similar-parts-finder` — drop-in replacement search across vendors
- `add-circuit-export` — emit Modelica / PSIM / LTspice subcircuit of the
  final inductor for plug-into-converter simulation
