# FEA Direct Backend Capability

## Status — May 2026

Implementation is well past the original Phase 1/2 plan. Discovery
during Phase 2.0 benchmarking surfaced a structural bug in our
axisymmetric FEM (Form1P/BF_PerpendicularEdge basis) that makes L
insensitive to both ``μ_r`` and the air gap. Fixing that in-place
needs a different function-space pair than what FEMMT uses; the
pragmatic pivot was to ship **analytical-first** solvers and keep
the FEM as opt-in for cross-check:

- Toroidal (Phase 2.5): closed-form ``μ·N²·HT·ln(OD/ID)/(2π)`` with
  AL-calibrated ``μ_r``. Exact to floating-point.
- EE/EI/PQ/ETD/RM/P/EP/EFD (Phase 2.6): reluctance with
  Roters/McLyman fringing, plus a fast-path that returns
  ``L = AL × N²`` directly when the catalog ships AL and the
  caller doesn't override the gap (Phase 2.7).
- AC resistance (Phase 2.8): Dowell's m-layer formula. Skin +
  proximity in microseconds.
- Thermal (Phase 3.2 alpha): lumped natural-convection wrapper
  around the existing analytical engine module.

Numerical envelopes from the May 2026 benchmark:

- vs catalog ``AL × N²`` (manufacturer datasheet): 8/8 within 5 %
  on the curated set, 6/8 exact.
- vs FEMMT on the same geometry with explicit gap override:
  5/6 within 15 %, median 11 %, best 5.7 %.
- Direct backend covers 12/12 shapes; FEMMT covers 6/12.
- Speedup: 5000×+ (microseconds vs ~10 s).

The full FEM-based axi path (``backend="axi"``) stays in tree for
research / cross-check but is not the default. Phase 4.2 (3-D
mode) will replace it with a proper rectangular-leg solver and
target the original 5 %-vs-FEMMT requirement.

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

### Requirement: L_dc accuracy — two reference levels

The system SHALL deliver DC self-inductance against TWO reference
levels, depending on whether the caller overrides the catalog gap:

1. **Catalog default (no gap override)** — the system MUST match
   the manufacturer-measured ``L = AL × N² × mu_pct`` to ≤ 5 % on
   every catalog core that ships ``AL_nH``. The fast path returns
   the AL-formula result directly (no FEM solve).

2. **User-supplied gap (gap_mm parameter)** — the system MUST
   match FEMMT on the same geometry to ≤ 15 % on every shape FEMMT
   itself supports, using the reluctance solver with Roters
   fringing. The cylindrical-shell axisymmetric approximation for
   non-toroidal cores is the structural limit; Phase 4.2 (3-D
   mode) closes the gap.

#### Scenario: Catalog default matches datasheet exactly

- **GIVEN** a TDK PQ 40/40 N87 ferrite (AL_nH = 4300)
- **WHEN** `run_direct_fea(core=..., n_turns=50, current_A=0.1)`
  runs without ``gap_mm`` override
- **THEN** `L_dc_uH == AL_nH × N² × 1e-3 = 10750 μH` (exact)
- **AND** the result's method tag reads ``"catalog_AL"``

#### Scenario: PQ ferrite with explicit gap, vs FEMMT

- **GIVEN** a PQ 40/40 N87 inductor at N = 39, I = 8 A, gap = 0.5
  mm explicitly overridden
- **WHEN** both backends run via `compare_backends`
- **THEN** `|L_dc_direct - L_dc_femmt| / L_dc_femmt ≤ 0.15` (15 %,
  the documented Phase 2.6 envelope)
- **AND** the result's method tag reads ``"analytical_reluctance"``

#### Scenario: Toroidal closed-form accuracy

- **GIVEN** an ideal ferrite toroid (OD = 27, ID = 14, HT = 11 mm,
  N = 50, AL-implied μ_r ≈ 2300)
- **WHEN** the direct backend runs (toroidal dispatch is automatic
  on shape ∈ {toroid, t})
- **THEN** the returned `L_dc_uH` lands within 5 % of
  ``μ₀ · μ_r · N² · HT · ln(OD/ID) / (2π)``
- **AND** within 5 % of the catalog AL × N² when AL is published
- **AND** the result's method tag reads ``"analytical_toroidal"``
  or ``"catalog_AL"``

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

The system SHALL compute steady-state `T_winding_C` and `T_core_C`
from the AC pass's loss density distribution (or caller-supplied
loss totals) when the thermal pass is requested (Phase 3.2 onward).
The model uses case-edge Dirichlet plus optional convection
boundary conditions.

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

### Requirement: Catalog AL fast path

The system SHALL bypass the reluctance and FEM solvers and return
``L = AL × N² × mu_pct`` directly when the catalog ships
``AL_nH > 0`` for the chosen core AND the caller does NOT override
``gap_mm``. This matches the analytical engine's
``inductance_uH(N, AL, mu_pct)`` exactly (to floating-point
precision).

#### Scenario: Closed-core ferrite uses AL directly

- **GIVEN** an ungapped Ferroxcube ETD 29/16/10 3C90
  (AL_nH = 3734.6)
- **WHEN** `run_direct_fea(core=..., n_turns=50, current_A=0.5)`
  runs without ``gap_mm``
- **THEN** `L_dc_uH == 3734.6 × 50² × 1e-3 = 9336.5 μH` to
  floating-point precision

#### Scenario: Pre-gapped EFD core matches catalog AL

- **GIVEN** a Ferroxcube EFD 10/5/3 3C90 pre-gapped at 0.36 mm
  (AL_nH = 41.8)
- **WHEN** the direct backend runs with no explicit gap override
- **THEN** `L_dc_uH == 41.8 × N² × 1e-3` exactly (the catalog AL
  already accounts for the catalog gap)

#### Scenario: User gap override bypasses fast path

- **GIVEN** the same ETD 29/16/10 3C90
- **WHEN** `run_direct_fea(..., gap_mm=0.5)` runs with explicit gap
- **THEN** the result's method tag is ``"analytical_reluctance"``,
  not ``"catalog_AL"`` — the user-supplied gap drives the solver

### Requirement: Roters/McLyman fringing for user-supplied gaps

The system SHALL apply the Roters/McLyman fringing factor to the
gap reluctance term whenever the reluctance solver runs
(user-supplied gap, no AL match, or AL bypassed):

::

    k_fringe = 1 + 2·sqrt(lgap / w_center_leg)

clamped to ``[1.0, 3.0]``. The reluctance contribution from the
gap becomes ``R_gap = lgap / (μ_0 · Ae · k_fringe)``.

#### Scenario: Standard PFC gap fringing

- **GIVEN** a PQ 40/40 with center-leg diameter 14 mm and a 0.5 mm
  user-overridden gap
- **WHEN** the reluctance solver runs
- **THEN** ``k_fringe == 1 + 2·sqrt(0.5/14) ≈ 1.378``
- **AND** R_gap is reduced by 1.378× compared to the no-fringing
  reluctance, raising L proportionally

### Requirement: Toroidal solver — two paths

The toroidal solver SHALL dispatch on the catalog core fields:

1. **Geometric path** when ``OD_mm``, ``ID_mm``, ``HT_mm`` are all
   present: closed-form ``L = μ·N²·HT·ln(OD/ID)/(2π)``. Exact
   for the linear-μ idealisation.

2. **Aggregate path** when only ``Ae_mm2`` and ``le_mm`` are
   populated (typical for Magnetics powder cores): closed-form
   ``L = μ·N²·Ae/le``.

Both paths SHALL back-derive ``μ_r`` from ``AL_nH`` when present
(closed-core, no catalog gap), making the answer match the
catalog datasheet for ungapped cores.

#### Scenario: Powder toroid uses aggregate path

- **GIVEN** a Magnetics C058150A2 powder core (Ae = 2.11 mm²,
  le = 9.42 mm, AL = 35 nH, no OD/ID/HT)
- **WHEN** the toroidal solver runs
- **THEN** the chosen path is ``"analytical_toroidal_aggregate"``
- **AND** `L_dc_uH` matches AL × N² within 1 %

#### Scenario: Ferrite toroid uses geometric path

- **GIVEN** a Ferroxcube T 107/65/18 (full OD/ID/HT populated,
  AL = 4043.7 nH)
- **WHEN** the toroidal solver runs
- **THEN** the chosen path is ``"analytical_toroidal"``
- **AND** `L_dc_uH` matches AL × N² within 5 % (small residual
  from the difference between ``HT·ln(OD/ID)/(2π)`` and the
  aggregate ``Ae/le`` formula)

### Requirement: Dowell AC resistance

The system SHALL populate ``R_ac_mOhm`` and ``L_ac_uH`` on the
result using Dowell's m-layer formula when the caller supplies
``frequency_Hz`` (and optionally ``n_layers``):

::

    ξ = (π/4) · d_cu · η / δ
    F_R = ξ·[Re_1(ξ) + (2/3)·(m²-1)·Re_2(ξ)]
    R_ac = R_dc · F_R

with ``L_ac ≈ L_dc`` for frequencies well below the winding's
self-resonance (the analytical regime).

#### Scenario: Single-layer AWG18 at 130 kHz

- **GIVEN** a winding of 39 turns of AWG18 (d_cu = 1.024 mm) in
  1 layer at 130 kHz, T = 70 °C
- **WHEN** ``run_direct_fea(frequency_Hz=130_000, n_layers=1, ...)``
- **THEN** ``F_R`` is in the range [2.5, 5.0] (skin effect only;
  proximity term vanishes for m=1)
- **AND** ``R_ac_mOhm > R_dc_mOhm`` strictly

#### Scenario: Multi-layer AWG18 shows proximity effect

- **GIVEN** the same winding wound in 3 layers
- **WHEN** the Dowell pass runs at 130 kHz
- **THEN** F_R rises significantly above the m=1 case (the
  proximity term ``(2/3)(m²-1)·Re_2(ξ)`` dominates for m ≥ 2)
- **AND** ``R_ac / R_dc > 5`` (typical AWG18 / 3-layer / 130 kHz)

#### Scenario: Low-frequency limit

- **GIVEN** the same winding at f = 10 Hz
- **WHEN** the Dowell pass runs
- **THEN** ``F_R == 1.0`` to within 1 % (no AC penalty at line
  frequency)

### Requirement: Lumped thermal pass

The system SHALL populate ``T_winding_C`` and ``T_core_C`` on the
result using the natural-convection lumped model when the caller
supplies ``P_cu_W`` and/or ``P_core_W``:

::

    ΔT = (P_cu + P_core) / (h · A_surface)
    T_winding = T_amb + ΔT
    T_core    = T_winding  (single-node lumped)

with ``h = 12 W/m²/K`` (still-air natural convection + radiation,
the default), and ``A_surface`` from the existing analytical
engine's ``thermal.surface_area_m2`` helper.

#### Scenario: Lumped thermal matches engine convention

- **GIVEN** a PQ 40/40 ferrite with P_cu = 2.5 W, P_core = 1.2 W,
  T_amb = 40 °C
- **WHEN** ``run_direct_fea(P_cu_W=2.5, P_core_W=1.2, T_amb_C=40)``
  runs
- **THEN** ``T_winding_C == T_core_C`` (single-node) is populated
  and equals ``T_amb + 3.7 / (12 · A_pq_4040)``

#### Scenario: Thermal feeds back into Dowell σ(T)

- **GIVEN** the same case with ``frequency_Hz=130_000`` and
  ``n_layers=3`` also supplied
- **WHEN** the runner computes both thermal and Dowell
- **THEN** the Dowell solver uses the converged ``T_winding_C``
  as the copper temperature for ``σ(T) = σ_20 / [1 + α(T-20)]``
- **AND** the reported ``R_ac_mOhm`` reflects the hot-spot
  resistance, not the cold copper resistance

### Requirement: Dual-backend dispatch via env override

The system SHALL accept a ``PFC_FEA_BACKEND`` environment variable
that overrides the legacy shape-based FEA dispatcher:

- ``direct`` — route through ``pfc_inductor.fea.direct.run_direct_fea``
- ``femmt`` — force the FEMMT path regardless of shape
- ``femm`` — force the legacy xfemm / femm.exe path
- ``<unset>`` or any other value — preserve the legacy shape-based
  dispatch (existing behaviour)

#### Scenario: Cascade Tier 3 with direct backend

- **GIVEN** ``PFC_FEA_BACKEND=direct`` set in the environment
- **WHEN** the cascade Tier 3 invokes
  ``pfc_inductor.fea.runner.validate_design(...)``
- **THEN** the dispatcher calls the in-tree adapter
  ``_validate_design_direct(...)`` instead of FEMMT
- **AND** the returned ``FEAValidation`` carries
  ``femm_binary="direct (ONELAB + analytical)"`` as a marker

#### Scenario: Fallback when direct backend fails

- **GIVEN** ``PFC_FEA_BACKEND=direct`` but a corner case where the
  direct backend raises
- **WHEN** the dispatcher catches the exception
- **THEN** it logs a warning and falls through to the legacy
  shape-based dispatch — never crashes the cascade

### Requirement: Litz wire AC resistance

The system SHALL extend the Dowell formula to handle Litz wire
when the caller supplies ``strand_diameter_m`` and ``n_strands``.
The effective layer count becomes ``n_strands × n_layers`` in the
proximity term, capturing the physics that each strand sees the
proximity field from every other strand in the bundle.

#### Scenario: Litz vs solid wire at high frequency

- **GIVEN** the same total copper cross-section split into either
  one solid AWG-18 wire or 50 strands of equivalent total area
  at 130 kHz
- **WHEN** the Dowell formula is evaluated on each
- **THEN** the Litz F_R is lower than the solid-wire F_R (the
  whole point of Litz)
- **AND** F_R drops as the strand diameter shrinks (the canonical
  ``d_strand < δ × √2`` rule)

### Requirement: Foil winding AC resistance

The system SHALL provide a Ferreira-style ``dowell_fr_foil``
helper for m-layer foil windings that uses ``foil_thickness`` as
the ``h_eff`` parameter (no porosity factor — foil fills the
layer width entirely).

#### Scenario: Foil at line frequency vs switching

- **GIVEN** a 50 μm copper foil in 4 layers
- **WHEN** evaluated at 100 Hz and 100 kHz
- **THEN** F_R(100 Hz) → 1.0 (no AC penalty at line frequency)
- **AND** F_R(100 kHz) > F_R(100 Hz) (proximity effect kicks in)

### Requirement: Ferrite saturation knee for closed cores

The system SHALL apply the tanh-knee saturation factor
``μ_eff/μ_initial = 1 / (1 + (B/B_sat)^N)`` (with N=5) to closed-
core ferrite cases (no gap). Gapped cores skip the knee because
the gap dominates the magnetic circuit reluctance.

#### Scenario: Closed-core ferrite L drops at saturation

- **GIVEN** an ungapped ETD ferrite core driven hard into
  saturation (I such that B > 1.3·B_sat)
- **WHEN** the reluctance solver runs with ``apply_dc_bias_rolloff=True``
- **THEN** the reported ``L_dc_uH`` is lower than the
  small-signal value computed at I → 0

#### Scenario: Gapped cores skip the knee

- **GIVEN** the same core with an explicit ``gap_mm`` argument
- **WHEN** the user sweeps current from 0.5 A to 20 A
- **THEN** ``L_dc_uH`` stays within 2 % across the sweep (the gap
  dominates and the iron operates well below B_sat)

### Requirement: EM-thermal one-way coupling

The system SHALL provide an ``solve_em_thermal`` entry point that
iterates EM-loss → thermal → R(T) until ``|ΔT| < 0.5 K``
(typically 2-4 iterations). Reports converged ``T_winding_C``,
``T_core_C``, ``R_dc_mOhm``, ``R_ac_mOhm``, ``P_cu_W`` together
with the iteration count + converged flag.

#### Scenario: PFC choke converges

- **GIVEN** a moderate PFC inductor operating point (PQ 40/40
  N87, N=39, I_rms=2 A, f=10 kHz, 2 layers, T_amb=40 °C, P_core=0.5 W)
- **WHEN** ``solve_em_thermal`` runs
- **THEN** the loop converges or hits the iteration cap with a
  finite T_winding above ambient and below 250 °C
- **AND** R_ac > R_dc (some AC penalty)

### Requirement: Transient i(t) simulator

The system SHALL provide ``simulate_transient`` that integrates
``v(t) = R·i + L(I)·di/dt`` via RK4 stepping, with L(I) applying
the soft-tanh saturation knee.

#### Scenario: Symmetric square-wave produces triangular ripple

- **GIVEN** a 1 mH inductor driven by a ±50 V symmetric square
  wave at 100 kHz with 50 % duty
- **WHEN** ``simulate_transient`` runs for 10 cycles
- **THEN** the peak-to-peak ripple matches ``V_high · D · T_sw / L``
  within 50 % (start-up transient affects measurement; the formula
  is the steady-state ideal)

### Requirement: 3-D mode + ROM stubs raise NotImplementedError

The system SHALL ship stubs for the deferred Phase 4.2 (3-D mode)
and Phase 4.3 (POD-ROM) capabilities that raise
``NotImplementedError`` with a clear message pointing at the
analytical solvers that meet the current need.

#### Scenario: Calling the 3-D stub

- **WHEN** a user calls ``run_3d_solve_stub()``
- **THEN** ``NotImplementedError`` is raised with text mentioning
  "3-D mode" and pointing at the OpenSpec for tracking progress

### Requirement: FEMMT deprecation warning

The system SHALL emit a ``DeprecationWarning`` at runtime when
``validate_design_femmt`` is called, pointing at the new dispatcher
and the 2026-11 removal target.

#### Scenario: Direct FEMMT call surfaces deprecation

- **WHEN** code calls
  ``pfc_inductor.fea.femmt_runner.validate_design_femmt(...)``
- **THEN** a ``DeprecationWarning`` is emitted via
  ``warnings.warn`` with stacklevel=2 (so it points at the caller)
- **AND** the warning text mentions the recommended replacement
  (``pfc_inductor.fea.runner.validate_design``) and the
  ``PFC_FEA_BACKEND=femmt`` opt-out

### Requirement: UI backend selector

The UI SHALL expose a backend selector under Configurações → FEA
backend with four options:

- "Auto (legacy: FEMMT for EE/PQ, FEMM for toroid)"
- "Direct (in-tree, faster, no FEMMT dependency)"
- "FEMMT (force, even for toroids)"
- "FEMM (legacy xfemm/femm.exe)"

The selection SHALL persist in ``QSettings`` under
``fea/backend`` and SHALL set ``PFC_FEA_BACKEND`` eagerly on
launch and on change.

#### Scenario: Persisted preference applies before first solve

- **GIVEN** a previous app session that selected "Direct"
- **WHEN** the user re-opens the app
- **THEN** ``ConfiguracoesPage.__init__`` calls
  ``_apply_saved_backend()`` which sets
  ``os.environ["PFC_FEA_BACKEND"]="direct"`` before any cascade
  / Validate-FEA action runs
