<p align="center">
  <img src="img/logo.png" alt="MagnaDesign" width="220" />
</p>

# MagnaDesign

> Topology-aware desktop application for inductor design in power-electronics
> converters — calibrated physics, multi-objective optimization, and FEA
> validation in a single workflow.

MagnaDesign takes a converter specification and produces a
manufacturable inductor design. It selects turns, picks a feasible
material/core/wire combination, evaluates the operating point against
real physics (DC-bias permeability rolloff, iGSE core loss, Dowell AC
copper loss, iterative thermal coupling), runs a multi-objective Pareto
sweep across the database, and cross-checks the result with a
finite-element solver — all from one PySide6 desktop UI.

The architecture is **topology-pluggable**: each converter family is
implemented as a small adapter that maps the spec to required
inductance and operating waveforms. Three topologies ship today; the
physics, optimization, FEA, and UI layers are reused unchanged when
new topologies are added.

## What is supported today

The matrix below lists the **currently implemented and tested**
capabilities. Items marked *Planned* live on the roadmap.

### Topologies

| Topology                 | Status      | Operating regime              | Typical use case                                   |
|--------------------------|-------------|-------------------------------|----------------------------------------------------|
| Active boost PFC         | Available   | Continuous Conduction Mode    | Single-phase universal-input PFC front-ends        |
| Passive line choke       | Available   | Line frequency (50/60 Hz)     | DC-bus or AC-side filtering, no switching          |
| Line reactor (1Ø and 3Ø) | Available   | Line frequency, %Z sizing     | Diode-bridge + DC-link drives, THD reduction       |
| Buck / Boost (DCM, BCM)  | Planned     | —                             | —                                                  |
| Flyback (coupled)        | Planned     | —                             | —                                                  |
| LLC / resonant           | Planned     | —                             | —                                                  |

### Physics models

| Model                              | Status        | Method                                                                                       |
|------------------------------------|---------------|----------------------------------------------------------------------------------------------|
| DC-bias permeability rolloff       | Available     | Power-law fit per family — calibrated for Kool Mu, MPP, High Flux, XFlux, Magmattec, iron powder |
| Core loss                          | Available     | Steinmetz baseline + iGSE (Mühlethaler) for non-sinusoidal flux; line-envelope and HF-ripple split |
| DC copper loss                     | Available     | Resistivity vs temperature, mean-turn-length geometry                                        |
| AC copper loss                     | Available     | Dowell formula (round wire and Litz strands), layer count inferred from window geometry      |
| Thermal model                      | Available     | Iterative convergence with ρ_cu(T) feedback, empirical h·A surface convection                |
| Cost / BOM                         | Available     | Mass × $/kg (core) + length × $/m (wire); cost-per-piece supported                           |
| B–H operating point + ripple loop  | Available     | Anhysteretic curve with HF ripple envelope                                                   |
| Full hysteresis (Preisach / J-A)   | Planned       | —                                                                                            |

### Optimization and analysis

| Capability                       | Status      | Notes                                                                              |
|----------------------------------|-------------|------------------------------------------------------------------------------------|
| Pareto sweep                     | Available   | Cores × wires (fixed material) or full 3-D (cores × wires × materials)             |
| Ranking objectives               | Available   | Total loss, volume, winding temperature, BOM cost, weighted score                  |
| Litz strand optimizer            | Available   | Sullivan criterion to hit a target Rac/Rdc; AWG-bounded; one-click save as new wire |
| Similar-parts finder             | Available   | Weighted distance over (Ae, Wa, AL, μr, Bsat); per-vendor and per-shape filters    |
| Multi-design comparator          | Available   | Up to four designs side-by-side, HTML / CSV export                                 |
| Cascade optimizer (Phase A)      | Available   | Multi-tier brute-force: Tier 0 envelope + Tier 1 analytical, persistent SQLite run store, resumable, parallel pool |
| Cascade Tier 2 (transient ODE)   | Planned     | Phase B — non-linear ODE simulator catches mid-cycle saturation                    |
| Cascade Tier 3 (batched FEA)     | Planned     | Phase C — FEMMT magnetostatic on the top-50                                        |
| Cascade Tier 4 (transient FEA)   | Planned     | Phase D — opt-in transient FEMMT on the top-5                                      |
| FEA validation (magnetostatic)   | Available   | FEMMT primary backend; legacy FEMM / xfemm auto-detected when installed            |
| IEC 61000-3-2 compliance plot    | Available   | Class D harmonic envelope (line-reactor flow)                                      |

### Database and catalogs

| Asset                          | Count          | Notes                                                                                       |
|--------------------------------|----------------|---------------------------------------------------------------------------------------------|
| Curated cores                  | 1 008          | Toroid, EE/EI, PQ — TDK/EPCOS, Magnetics Inc, Ferroxcube, Magmattec, Thornton               |
| Curated materials              | 50             | MnZn ferrite, iron powder, Kool Mu, High Flux, MPP, XFlux, Magmattec, M19, Metglas          |
| Curated wires                  | 48             | AWG solid + standard Litz constructions, with cost per metre                                |
| OpenMagnetics MAS catalog      | ~22 000 parts  | Optional, non-destructive merge with the curated set                                        |
| In-app database editor         | Available      | Pydantic-validated JSON forms for cores, materials, wires                                   |

### UI / UX

| Feature                                                | Status      |
|--------------------------------------------------------|-------------|
| Three-pane workspace (spec / plots / result)           | Available   |
| Real-time recalculation on any specification change    | Available   |
| Light and dark themes                                  | Available   |
| Interactive 3-D core + winding viewer (PyVista)        | Available   |
| Waveform plots — i_L(t) and B(t) over a line cycle     | Available   |
| B–H operating-point plot                               | Available   |
| Single-design HTML datasheet export                    | Available   |
| Multi-design HTML comparison report                    | Available   |
| CSV export of optimizer results                        | Available   |
| Cross-platform FEA installer                           | Available (macOS Intel / Apple Silicon, Linux x86_64, Windows x86_64) |

## Getting started

### Install

```bash
uv venv --python 3.12
uv pip install -e ".[dev,fea]"
magnadesign-setup        # downloads ONELAB and configures the FEA backend
uv run magnadesign       # launches the application
```

`magnadesign-setup` is idempotent and platform-aware. On the first
launch the application detects a missing FEA backend and offers the
same dialog. Run `magnadesign-setup --check` to verify the environment
without writing anything. Manual install steps are in
[`docs/fea-install.md`](docs/fea-install.md). The legacy
`pfc-inductor` / `pfc-inductor-setup` aliases are kept as back-compat
shims for existing scripts.

> Python 3.12 is required because the FEMMT 0.5.x solver does not yet
> support 3.13. The optional `[fea]` extra pins compatible scipy and
> setuptools versions for that solver.

### First design in 60 seconds

1. **Pick a topology.** The application opens on *Active boost PFC*;
   switch to passive choke or line reactor from the topology selector.
2. **Fill the specification block** on the left: input voltage range,
   output voltage, output power, switching frequency, ripple target,
   ambient temperature.
3. **Choose material, core and wire.** Lists are filtered to
   combinations that are valid for the active topology.
4. **Read the result column** on the right: required vs achieved
   inductance, turn count, peak flux density, copper and core losses,
   predicted winding temperature, BOM cost.
5. **If the manual choice does not converge**, open the **Optimizer**
   from the toolbar — sweep cores, wires and (optionally) materials,
   rank by your objective, promote the winner back to the design view.
6. **Open *Validate (FEA)*** for a numerical second-source check on
   inductance and peak flux density.

## Modeling notes

The analytical core is intentionally physical, not curve-fitted to a
single vendor's application note:

- **Permeability rolloff vs DC bias** is per-family and calibrated
  against published vendor curves. The solver iterates between bias
  field H and effective permeability μ until the operating point
  converges.
- **Core loss** uses Steinmetz coefficients fitted from datasheet loss
  curves, applied locally over the line cycle through iGSE. For PFC
  designs this matters: naive averaging under-predicts loss because
  B(t) is far from sinusoidal.
- **AC copper loss** uses Dowell with the Sullivan correction for
  Litz; layer count is inferred from window geometry.
- **Thermal** is iterative — copper resistivity rises with
  temperature, which raises losses, which raises temperature. The
  solver converges in a handful of iterations and exposes both cold
  and hot operating points.
- **Cost** is optional — designs without populated vendor pricing
  display "—" for BOM but are otherwise fully evaluated.

## FEA validation

The *Validate (FEA)* tool runs a magnetostatic finite-element
simulation of the chosen core and winding geometry, then compares
numerical inductance and peak flux density against the analytical
prediction.

Backends:

- **FEMMT** (default, cross-platform) — Python wrapper around ONELAB /
  GetDP, configured by `magnadesign-setup`. Native support for
  EE / ETD / PQ; toroids are mapped to a PQ-equivalent.
- **FEMM / xfemm** (auto-detected when present) — preferred for
  toroids on platforms where it is installed (`brew install xfemm` on
  macOS, `apt install xfemm` on Linux, the 4.2 installer on Windows).
  Force selection with `PFC_FEA_BACKEND=femm`.

| Core shape       | Backend                              | Typical error             |
|------------------|--------------------------------------|---------------------------|
| Toroid           | FEMM (axisymmetric)                  | < 5 %                     |
| Toroid           | FEMMT (PQ-equivalent)                | order-of-magnitude only   |
| EE / EI          | FEMMT (area-equivalent centre leg)   | 10 – 25 %                 |
| ETD / PQ / RM    | FEMMT (native round leg)             | 5 – 15 %                  |

The FEA flow is a sanity check on `L` and `B_pk`. AC copper loss, core
loss over arbitrary waveforms, and thermal estimation remain the
responsibility of the analytical models — those are the features the
FEA backend does not solve.

## Architecture

```
src/pfc_inductor/
  models/        # Pydantic schemas: Spec, Material, Core, Wire, Result, MAS adapters
  physics/       # Rolloff, core loss (iGSE), copper (DC + Dowell + Litz), thermal, cost
  topology/      # boost_ccm.py, passive_choke.py, line_reactor.py
  design/        # Design engine (orchestrator)
  optimize/      # Pareto sweep, Litz optimizer, similar-parts finder, scoring, feasibility
  fea/           # FEMMT runner (primary), legacy FEMM, geometry probes
  visual/        # 3-D meshes (PyVista), B–H trajectory
  standards/     # IEC 61000-3-2 compliance check
  compare/       # Multi-design comparison engine
  report/        # HTML datasheet, multi-design report, 3-D view export
  setup_deps/    # Cross-platform FEA installer (ONELAB, FEMMT)
  ui/            # Workspace shell, dashboard cards, dialogs, widgets, theme

data/            # Curated JSON: 50 materials, 1 008 cores, 48 wires
data/mas/        # Optional OpenMagnetics MAS catalog (~22 k parts)
docs/            # POSITIONING.md, UI.md, ADRs, FEA install notes
openspec/        # Versioned change proposals
tests/           # 40+ test files: physics, design, optimization, UI, FEA mocks
vendor/          # OpenMagnetics MAS source data (NDJSON)
```

The domain layer (`models/`, `physics/`, `topology/`, `design/`,
`optimize/`, `standards/`) is fully typed and runs under strict mypy.
Adding a new topology or physics model is a typed-Python change
against well-defined interfaces — it does not require touching the UI.

## Development

```bash
uv run pytest           # full test suite
uv run ruff check .     # lint
uv run mypy src         # type-check
```

Contribution guidelines and scope guardrails are in
[`CONTRIBUTING.md`](CONTRIBUTING.md). Architecture decisions live in
[`docs/adr/`](docs/adr/). Positioning against comparable open-source
magnetics tools is documented in
[`docs/POSITIONING.md`](docs/POSITIONING.md). Versioned change
proposals are tracked under [`openspec/`](openspec/).

## License

To be defined.
