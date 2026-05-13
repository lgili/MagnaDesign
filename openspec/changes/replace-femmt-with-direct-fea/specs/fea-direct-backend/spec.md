# FEA Direct Backend Capability

## ADDED Requirements

### Requirement: End-to-end pipeline without FEMMT

The system SHALL provide a complete FEA pipeline (geometry → mesh
→ solve → post-process → result dataclass + field PNGs) that does
not import `femmt` or `materialdatabase` at any point. The
pipeline SHALL use only Gmsh (Python API) and GetDP (subprocess)
plus the standard MagnaDesign numpy / matplotlib stack.

#### Scenario: Direct backend runs with FEMMT uninstalled

- **GIVEN** a Python environment where `femmt` is not installed
- **WHEN** the caller invokes
  `run_direct_fea(core=..., material=..., wire=..., n_turns=...,
  current_A=..., workdir=..., backend="axi")` on a valid EI core
- **THEN** the call completes without `ImportError`
- **AND** returns a `DirectFeaResult` populated with `L_dc_uH`,
  `B_pk_T`, `energy_J`, `workdir`, `field_pngs`
- **AND** writes `.geo`, `.msh`, `.pro`, `.pre`, `.res`,
  `.pos` artifacts under `workdir`

#### Scenario: No FEMMT call inside the cascade Tier 3 (Phase 5.2)

- **GIVEN** the user has selected the `direct` FEA backend in
  Configurações
- **WHEN** the cascade Tier 3 runs against a candidate
- **THEN** no symbol in `pfc_inductor.fea.femmt_runner` is touched
  during the run (verified by import-trace test)
- **AND** the candidate's `T3_metrics` payload is identical-
  shape to the FEMMT-produced payload it replaced

### Requirement: L_dc accuracy parity with FEMMT

The system SHALL deliver DC self-inductance within 5 % of the
FEMMT result on the same geometry, for at least every shape in
the curated benchmark set (`tests/benchmarks/cores.yaml`).

#### Scenario: Direct vs FEMMT on a curated PQ ferrite

- **GIVEN** a PQ 40/40 N87 ferrite inductor at N = 60, I = 5 A,
  lgap = 0.5 mm
- **WHEN** both backends run via `compare_backends`
- **THEN** `|L_dc_direct - L_dc_femmt| / L_dc_femmt < 0.05`

#### Scenario: Toroidal accuracy

- **GIVEN** an ideal ferrite toroid (OD = 27, ID = 14, HT = 11 mm,
  N = 50, μ_r = 2300) — the Phase 1.8 reference case
- **WHEN** the direct backend runs with `backend="axi"` using the
  toroidal B_φ physics template (Phase 2.5)
- **THEN** the returned `L_dc_uH` lands within 5 % of
  `μ₀ · μ_r · N² · A / (2π·R)`
- **AND** within 10 % of the FEMMT-produced `L_dc` for the same
  inputs (FEMMT uses a less accurate A_φ formulation for
  toroidals)

### Requirement: AC harmonic — loss extraction

When the AC pass is requested (Phase 2.1 onward), the system SHALL
extract:

- `L_ac_uH` — AC self-inductance at the given frequency.
- `R_ac_mOhm` — AC winding resistance including skin and proximity.
- `P_cu_ac_W` — total copper loss.
- `P_core_W` — total core loss.

#### Scenario: AC sweep matches FEMMT

- **GIVEN** the same PQ ferrite case at the same N and I, swept
  over {100 Hz, 50 kHz, 100 kHz}
- **WHEN** both backends run the AC pass
- **THEN** `|L_ac_direct - L_ac_femmt| / L_ac_femmt < 0.05` at each
  frequency
- **AND** `|R_ac_direct - R_ac_femmt| / R_ac_femmt < 0.10`
- **AND** `|P_core_direct - P_core_femmt| / P_core_femmt < 0.15`

### Requirement: Thermal pass — steady-state coupling

When the thermal pass is requested (Phase 3.2 onward), the system
SHALL compute steady-state `T_winding_C` and `T_core_C` from the
AC pass's loss density distribution, with case-edge Dirichlet and
optional convection boundary conditions.

#### Scenario: Thermal matches bench measurement

- **GIVEN** a benched ferrite inductor with measured T_winding =
  85 °C at the rated operating point
- **WHEN** the direct backend runs DC → AC → thermal
- **THEN** the returned `T_winding_C` is within 10 °C of 85 °C

### Requirement: Cold-import budget

The system SHALL keep cold-import cost of the public entry point
below 80 ms.

#### Scenario: Lazy import enforcement

- **GIVEN** a fresh Python process with cleared bytecode cache
- **WHEN** the caller executes
  `from pfc_inductor.fea.direct import run_direct_fea`
- **THEN** the import completes in ≤ 80 ms wall (measured by
  `tests/test_perf_cold_import.py`)
- **AND** the import does NOT execute `import gmsh`,
  `import matplotlib`, or any GetDP-related code

### Requirement: Single-solve wall budget

The system SHALL complete one DC magnetostatic solve on a typical
PFC inductor in ≤ 3 s wall on a single CPU core.

#### Scenario: PQ 40/40 baseline solve time

- **GIVEN** a PQ 40/40 ferrite inductor case (cardinality of the
  cascade Tier 3 reference)
- **WHEN** `run_direct_fea(backend="axi")` runs end-to-end
- **THEN** the returned `solve_wall_s` is ≤ 3.0
- **AND** the full pipeline (mesh + solve + parse + PNGs) is ≤ 5.0 s

### Requirement: Crash isolation

The system SHALL contain any GetDP failure in its subprocess. A
solver crash MUST NOT propagate to the host Python process; it
MUST raise `SolveError` with stdout/stderr captured.

#### Scenario: Pathological geometry crashes GetDP

- **GIVEN** a geometry that triggers a known GetDP failure
  (degenerate mesh, missing region, etc.)
- **WHEN** `run_direct_fea` invokes the solver
- **THEN** the host Python process keeps running
- **AND** the call raises `pfc_inductor.fea.direct.solver.SolveError`
  with the GetDP error message in the exception text
- **AND** any partial output in `workdir` is left in place for
  post-mortem inspection

### Requirement: Cancellation

The system SHALL accept a `Cancellable` token; on cancel the
solver SHALL SIGTERM its process group and raise `SolveCancelled`.

#### Scenario: UI cancels a long-running solve

- **GIVEN** a solve in progress
- **WHEN** the UI thread calls `cancel_token.cancel()` and waits
- **THEN** within 1 second the GetDP process group is terminated
- **AND** `run_direct_fea` raises `SolveCancelled`
- **AND** no zombie processes remain

### Requirement: Two inductance extraction methods, kept in sync

Every magnetostatic post-processing block SHALL emit both:

- `L_energy = 2·W/I²` where `W = ∫ ½ν|B|² dV`.
- `L_flux = ∫ (CompZ[a]/AreaCell) / I dA` over the source region.

#### Scenario: Self-consistency invariant

- **GIVEN** any valid magnetostatic case the backend supports
- **WHEN** both extractions run in the same `.pro` post-op
- **THEN** `|L_energy - L_flux| / max(|L_energy|, ε) < 1e-4`

#### Scenario: Divergence indicates a bug

- **GIVEN** any case where the invariant above fails
- **WHEN** the runner reads the two values
- **THEN** the runner logs a structured warning and the
  `compare_backends` calibration report flags the case as
  `inconsistent` — never silently picks one method

### Requirement: Axisymmetric source convention

For runs with `backend="axi"`, the system SHALL pass
`coil_area_m2 = A_2d × 2π·R_mean` to the physics template so that
the `Jacobian VolAxiSqu` integration delivers `N·I` ampere-turns
through any (r, z) Ampere-loop in the bundle.

#### Scenario: Axisymmetric inductance matches the analytical envelope

- **GIVEN** an ideal axisymmetric inductor with high-μ iron and a
  single discrete gap
- **WHEN** `run_direct_fea(backend="axi")` runs
- **THEN** `L_dc_uH` is within 50 % of the textbook
  `μ₀ · N² · Aᵉ / lgap` analytical
- **AND** within 5 % of FEMMT's `L_dc` on the same geometry
- (the 50 % gap vs textbook is the inherent leakage of the
  cylindrical-shell approximation; FEMMT has the same gap on the
  same geometry)

### Requirement: Region tagging via fragment output map

The geometry layer SHALL determine physical-group membership by
tracking the output map of Gmsh's `fragment` operation, not by
post-hoc centroid classification.

#### Scenario: Concave core surfaces tag correctly

- **GIVEN** an EI core whose meridian-plane cross-section is
  C-shaped (concave) and whose centroid would fall inside the
  air-gap rectangle
- **WHEN** the geometry layer emits physical groups
- **THEN** the `Core` group contains the C-shaped surface
- **AND** the `AirGap` group contains only the gap rectangle
- **AND** `μ_r` of the Core region is honoured by the solver
  (verifiable via `B_core / B_air > 1` in the field plot)

### Requirement: Configurable output directory

The system SHALL accept a `workdir` parameter and write every
artifact (`.geo`, `.msh`, `.pro`, `.pre`, `.res`, `.pos`, `.png`)
under that directory only. No artifact may land outside it.

#### Scenario: Project-scoped FEA artifacts

- **GIVEN** a user with project saved at `~/my_pfc/`
- **WHEN** the cascade calls `run_direct_fea(workdir=~/my_pfc/.fea/c42/)`
- **THEN** every FEA artifact lands under `~/my_pfc/.fea/c42/`
- **AND** no file is written to `~/onelab/`, `~/.cache/`, or any
  global location

### Requirement: Shape coverage parity with FEMMT

The system SHALL support every core shape FEMMT supports through
the same public API (`run_direct_fea(core=..., backend=...)`).

#### Scenario: A new shape adds with one file

- **GIVEN** a developer who wants to add support for a U-core
- **WHEN** they create `geometry/u_core.py` implementing the
  `CoreGeometry` ABC and add the shape's dispatcher entry in
  `runner.py`
- **THEN** the entire pipeline (mesh, solve, post-proc, PNGs)
  works on a U-core without changes to physics, solver, or
  postproc layers

#### Scenario: Rectangular-leg EI in 3-D mode

- **GIVEN** an EI core whose datasheet rectangular-leg geometry
  is meaningfully different from the cylindrical-shell axi
  approximation
- **WHEN** `run_direct_fea(backend="3d")` runs (Phase 4.2)
- **THEN** the returned `L_dc_uH` matches the manufacturer
  AL · N² datasheet value within 3 %
- **AND** beats the `backend="axi"` accuracy on the same case by
  at least 10 percentage points

### Requirement: DirectFeaResult mirrors the FEMMT contract

The result dataclass SHALL expose exactly the field names
FEMMT-derived code in the cascade expects, with optional fields
left `None` when not computed.

#### Scenario: Dual-backend cutover is a flag flip

- **GIVEN** cascade Tier 3 code that consumes
  `result.L_dc_uH`, `result.B_pk_T`, `result.T_winding_C`, ...
- **WHEN** the backend toggle flips from `"femmt"` to `"direct"`
- **THEN** every consumer continues to work without type errors
  or missing fields (optional fields read as `None` in either
  backend's absent passes)
