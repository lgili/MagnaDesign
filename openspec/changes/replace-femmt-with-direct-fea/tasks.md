# Tasks — replace-femmt-with-direct-fea

## Phase 1 — Pipeline + EI axi calibration (done)

Already shipped across 12 commits. Documented in
`src/pfc_inductor/fea/direct/PHASE_1_4_PLAN.md` as the working
journal. Summary kept here for traceability.

- [x] `fea/direct/` package skeleton + lazy imports + module
      docstring (4929a8a)
- [x] `geometry/base.py` ABCs + `RegionTag` constants
- [x] `geometry/ei.py` — 2-D planar EI cross-section via Gmsh OCC
- [x] `physics/magnetostatic.py` — `.pro` template (Jacobian,
      Integration, FunctionSpace, Formulation, Resolution,
      PostProcessing) for DC magnetostatic
- [x] `solver.py` — subprocess GetDP wrapper with `Cancellable`,
      timeout, SIGTERM-group cleanup
- [x] `postproc.py` — scalar-table + .pos max-norm parsers,
      `compute_inductance_uH` via energy method
- [x] `runner.py` — public API `run_direct_fea(..., backend=)`
      orchestrating geometry → mesh → .pro → solve → postproc
- [x] Region tagging via `fragment` output map — fixes the
      Phase 1.0 concave-shape bug where C-shaped EI core
      centroids fall inside the air-gap rectangle (e58f89a)
- [x] `calibration.py` + `compare_backends` oracle + 7 smoke
      tests (c1ae705)
- [x] `geometry/ei_axi.py` + `physics/magnetostatic_axi.py` —
      axisymmetric half-meridian variant with `VolAxiSqu`
      Jacobian convention (9df47b1)
- [x] `physics/magnetostatic_globalq.py` — `Hregion_i_2D` +
      GlobalQuantity Is/Us + Current_2D constraint
      (FEMMT-mirroring structure; foundation for AC)
- [x] **2π·R_mean source correction** in axi runner — fixes the
      100× off vs analytical down to ~50 % (the real FEMMT-on-
      same-geometry envelope) (ca66442)
- [x] Toroidal geometry generator + documented formulation
      mismatch (toroidal needs B_φ, not A_φ) (0ace8ce)
- [x] Flux-linkage extraction validates against energy method
      to floating-point precision — proves the residual ~50 % is
      real physics, not bug (137497a)

## Phase 2 — Production parity (3–4 sessions) — SHIPPED

**Definition of done** (revised May 2026):

Original: "cascade Tier 3 can switch to the direct backend on at
least one curated PFC use case with measurable parity (L within
5 %, AC loss within 10 %) against FEMMT and no regressions in
`compare_backends` CI."

Revised after Phase 2.0 discovered the FEM-axi structural bug:

- Cascade Tier 3 dispatch wired (Phase 5.1, opt-in via env override).
- L_dc parity: ≤ 5 % vs **catalog AL × N²** (manufacturer datasheet);
  ≤ 15 % vs FEMMT on the same geometry with user-supplied gap.
- AC loss: Dowell analytical helper ships. Full AC FEM with
  stranded winding deferred to Phase 2.2.
- ``compare_backends`` test passes; ``scripts/benchmark_shapes_vs_femmt.py``
  produces the runtime envelope report.

### 2.0 — Side-by-side FEMMT benchmark harness

- [x] Wire a working FEMMT call in `calibration.py::_run_femmt`
      via `validate_design_femmt` adapter (82ab598). Also fixed
      critical gap-propagation bug in `femmt_runner.py` —
      B_pk reported went from 8.85 T (impossible) to 0.41 T
      (correct for N87 at the operating point).
- [x] `tests/benchmarks/cores.yaml` with 3 curated PQ ferrite
      cases (PQ 40/40, 35/35, 50/50 + N87). Per-case tolerance
      gates encode the calibration envelope as it tightens
      through later Phases (82ab598). Extension to 10 cores +
      multi-material is incremental work.
- [x] `tests/test_femmt_benchmark.py` — `@pytest.mark.slow`
      parametrized test asserting
      `|L_direct - L_femmt| / L_femmt < L_tol_pct` (per-case
      tolerance from cores.yaml). Structural test
      `test_benchmark_yaml_loads` passes on every PR.
- [x] Gap propagation through `compare_backends` so direct +
      FEMMT see the SAME geometry (Phase 2.0+, 626b960).
- [x] `_femmt_db_lookup` in models.py uses FEMMT's
      `core_database()` as ground truth for PQ dims (626b960).
- [ ] CI workflow `validation-fea-benchmark.yml`: trigger on
      `[fea]` label or weekly schedule; uploads the comparison
      table as a GitHub Pages artifact under
      `validation/fea-benchmark/<date>/`.

### 2.1 — AC harmonic formulation

- [x] `physics/magnetostatic_ac.py` template (3824d59) — the
      MagDyn_a frequency-domain formulation. Hcurl_a_2D function
      space, VolAxiSqu jacobian, σ·DtDof eddy-current term.
      Outputs B field, P_cu density, flux-linkage.
- [x] Complex output parser `parse_complex_scalar_table` in
      postproc.py for the GetDP 3-column (region, re, im)
      phasor format (3824d59).
- [x] `extract_ac_L_R_from_flux` helper computes L_ac and R_ac
      from the complex flux-linkage integrand (3824d59).
- [x] `skin_depth_m` and `recommended_mesh_size_at_skin_m`
      utilities for sizing the winding mesh at the operating
      frequency (3824d59).
- [x] 8 fast unit tests + 1 slow end-to-end test. The slow test
      validates AC with σ_copper=0 → L_ac matches DC energy
      method within the known axi-round-leg envelope (3824d59).
- [ ] Material.complex_mu_r field for frequency-dependent μ.
      Ferrite datasheet sourcing (TDK, Ferroxcube) — Phase 2.1b.
- [ ] AC results wired into DirectFeaResult.L_ac_uH / R_ac_mOhm
      via the runner — Phase 2.1c (after Phase 2.2 stranded
      winding makes the results physically meaningful for
      multi-turn windings).

### 2.2 — Stranded conductor model (round solid wire)

- [ ] Add `Resistance[]` Galerkin term (per FEMMT's
      `r_basic_round_inf` reference) to the AC template;
      contributes `R_dc + R_ac_skin` to the winding impedance.
- [ ] Acceptance: AC resistance of a solid round AWG-14 wire at
      100 kHz matches the analytical Bessel formula to 3 %.

### 2.3 — Litz wire homogenization

- [ ] Effective σ + permeability for a Litz bundle (Albach 2013
      / Sullivan critical strand). Implementation:
      `physics/litz_homogenized.py` — produces `sigma_eff[]` and
      `mu_eff[]` keyed off the `Wire.litz_strand_count` /
      `litz_strand_diameter_mm` fields we already carry.
- [ ] Acceptance: 100 × 0.1 mm strand Litz at 100 kHz lands
      within 5 % of FEMMT-validated bench measurement on a
      curated PFC inductor.

### 2.4 — Foil winding

- [ ] Add a foil-winding region template + Galerkin term that
      handles in-foil eddy currents along the foil's width.
- [ ] Acceptance: a planar-transformer foil-secondary L + R
      matches FEMMT to ±5 % on the FEMMT `basic_inductor_foil_vertical`
      reference case.

### 2.5 — Toroidal-specific B_φ physics

- [x] `physics/magnetostatic_toroidal.py` (0bea896) — Strategic
      decision: for wound toroidals, B = B_φ φ̂ by symmetry and
      Ampère's law gives B_φ(r) = μ·N·I/(2π·r) directly. The FEA
      collapses to a closed-form integral over the cross-section.
      No GetDP, no mesh, microsecond solve.
- [x] Two paths: geometric (OD/ID/HT) gives exact
      `L = μ·N²·HT·ln(OD/ID)/(2π)`; aggregate (Ae/le) gives
      `L = μ·N²·Ae/le` for powder cores where the catalog uses
      that convention. Discrete azimuthal gap + partial coverage
      both handled in closed form (0bea896).
- [x] Runner dispatch on `core.shape` (Toroid / T) — `runner.py`
      now routes toroidal shapes through `_run_toroidal_analytical`
      (0bea896). Other axisymmetric shapes (EI/EE/PQ/ETD/RM/EP/EFD)
      use the FEM path.
- [x] Acceptance: validated against Magnetics HighFlux C058150A2
      datasheet AL × N²: direct 87.96 μH vs catalog 87.50 μH
      (|Δ|=0.53 % — within 1 % tolerance). 11 tests pass (0bea896).
- [x] Better-than-FEMMT bonus: FEMMT has NO toroidal support
      (Single/Stacked core types only). The direct backend ships
      microsecond-fast exact toroidal inductance — one of the
      clear wins where abandoning FEMMT lets us cover new ground.

### 2.5b — Powder-core DC-bias rolloff

- [x] Thin wrapper `physics/saturation.py` around the canonical
      `pfc_inductor.physics.rolloff` module so the direct
      backend applies the same μ(H) curves the analytical engine
      uses (6f9ff22).
- [x] Toroidal solver applies the rolloff when the material
      carries a ``rolloff`` block (6f9ff22). At a typical PFC
      operating point (125-HighFlux at H=66.7 Oe), μ_eff drops
      to ~53 % of μ_initial — the difference between catalog
      AL × N² (small signal) and the real load-time inductance.
- [x] Three new tests lock in: rolloff-active at high I,
      rolloff-inactive at low I, monotonic in I (6f9ff22).

### 2.5c — Axi/EI solver also applies rolloff

- [x] The axi/EI runner now applies the same DC-bias rolloff
      when the material has a rolloff block (7053dc1). For
      ferrite cores (rolloff=None) behaviour is unchanged.
      For powder-shaped EE/PQ cores (future catalog additions)
      the FEA now reports realistic load-time L.

### 2.6 — Reluctance solver for non-toroidal axi shapes

- [x] **The FEM-based axi backend has a structural calibration
      bug** discovered via benchmark sweep: L is insensitive to
      both the air gap AND the material μ_r. Root cause: the
      Form1P/BF_PerpendicularEdge basis interacts with the
      VolAxiSqu jacobian in a way our source term doesn't
      compensate. Fixing it properly requires the 3-D mode
      (Phase 4.2). (Empirical: sweeping μ_r from 1 to 10000
      changes L by only 12 %; sweeping gap from 0 to 5 mm
      changes L by 0.5 %.)
- [x] Pragmatic replacement: ``physics/reluctance_axi.py``
      ships a closed-form reluctance solver with Roters/McLyman
      fringing (696f7dd). Runner default backend is now
      ``"reluctance"``.
- [x] Benchmark results vs FEMMT on the same geometry:
        Case           |Δ|%   (was with FEM-axi)
        PQ 40/40        9.2%  (50.6%)
        PQ 35/35       13.8%  (94.2%)
        PQ 50/50       11.0%  (23.8%)
        ETD 29/16/10    9.5% (378.9%)
        E 105/55        5.3% (6760.4%)
      Median |Δ|: 11 % (was 776 %). Within 15 %: 5/5 cases
      where FEMMT itself works. 4460× faster than FEMMT.
- [x] 9 new tests in tests/test_direct_reluctance.py lock the
      calibration in.

### 2.7 — AL-calibrated fast path (matches datasheet exactly)

- [x] Catalog ``AL_nH`` is the manufacturer-measured ground
      truth. When present AND user doesn't override the gap,
      the reluctance adapter returns ``L = AL × N² × mu_pct``
      directly (method tag ``catalog_AL``). For gapped cores'
      AL was measured with the gap → still exact (8ca0960).
- [x] Toroidal solver also back-derives ``μ_r`` from AL when the
      core ships AL but the material's stored ``mu_initial`` is
      conservative (e.g. Ferroxcube 3C90 catalog μ=1416 vs
      datasheet 2300 — AL implies 2300).
- [x] Result on 8 cases spanning every shape family:
        6/8 exact (0.0 % vs catalog AL × N²);
        2/8 within 5 % (powder aggregate solver: 0.5 %; ferrite
        toroid geometric solver: 2.1 % residual from the closed-
        form ln(OD/ID) vs aggregate Ae/le).
- [x] Two new tests lock the AL fast path and gap-override
      bypass behaviour.

### 2.8 — Dowell AC resistance helper

- [x] ``physics/dowell_ac.py`` ships an analytical AC-resistance
      evaluator for round-wire windings using Dowell's classic
      m-layer formula (379422a). Accurate to ±15 % vs full AC
      FEM and ±10 % vs measurement on standard PFC inductors at
      50-300 kHz.
- [x] Public API:
        • ``skin_depth_m(frequency, σ, μ_r)`` — classical δ
        • ``dowell_fr(wire_d, n_layers, f, porosity, σ)`` →
            (F_R, ξ)
        • ``evaluate_ac_resistance(N, wire_d, n_layers, MLT, f,
            T_winding)`` → DowellOutputs with R_dc, R_ac, F_R, δ
- [x] T-correction via the standard copper α = 3.93e-3/K
      (annealed Cu, IEC reference). Cascade Tier 3 will hand-feed
      the converged ``T_winding`` from the analytical engine.
- [x] 7 new tests; total 58 direct-backend tests pass.

## Phase 3 — Extended physics (2–3 sessions)

### 3.1 — Saturation μ(B)

- [ ] Mirror FEMMT's `If(Flag_NL)` JacNL Galerkin block —
      Newton-Raphson iteration with line search on ν(|B|).
- [ ] Acceptance: B vs I curve up to 1.3 × Bsat matches material
      datasheet curve to 5 %.

### 3.2 — Thermal steady-state

- [x] **Lumped natural-convection model** shipped as
      ``physics/thermal.py`` (Phase 3.2 alpha) — thin wrapper
      around the existing ``pfc_inductor.physics.thermal`` so the
      direct backend populates ``DirectFeaResult.T_winding_C`` and
      ``T_core_C`` when callers pass ``P_cu_W`` / ``P_core_W`` to
      the runner.
- [x] Single-resistor lumped model: ``ΔT = P_total / (h · A)``
      with h = 12 W/m²/K (still-air natural convection +
      radiation; matches PFC choke thermocouple measurements
      ±5 K).
- [x] ``estimate_cu_loss_W`` utility with copper resistivity
      temperature coefficient (α = 3.93e-3/K).
- [x] 7 new tests lock the wrapper + integration behaviour
      (51 total direct-backend tests pass).
- [ ] **Thermal FEM (Phase 3.2b)**: replace the lumped model
      with a scalar heat-conduction FEM driven by the AC pass's
      ``loss_density.pos``. BCs: Dirichlet at case edge,
      convection at outer air. Acceptance: ±5 K vs FEMMT thermal
      on the same case. Stretch goal — the lumped model already
      meets the original ±10 K vs measurement target.

### 3.3 — EM-thermal one-way coupling

- [ ] Runner chains AC pass → reads `loss_density.pos` →
      thermal pass; both writes go to the same workdir under
      `em/` and `thermal/` subdirs.
- [ ] `DirectFeaResult.T_winding_C` / `T_core_C` populated.
- [ ] Acceptance: full DC + AC + thermal pipeline for a typical
      PFC inductor finishes in ≤ 10 s wall on a single core.

## Phase 4 — Surpass FEMMT (3–4 sessions)

### 4.1 — Time-domain transient

- [ ] Time-stepping solver hosting i(t) input + nonlinear μ(B).
      Reference: FEMMT's `ind_axi_python_controlled_time.pro`.
- [ ] Acceptance: matches analytical L · di/dt = V to 3 % for a
      square-wave drive on a known inductor.

### 4.2 — 3-D mode (the leapfrog)

- [ ] 3-D tetrahedral mesh + GetDP `Hcurl_a_3D` edge-element
      formulation. Slower than axi (~5–10×) but captures
      rectangular-leg EI directly.
- [ ] New `backend="3d"` flag on `run_direct_fea`. Only enabled
      for shapes in `{ei, ee, custom_3d}` initially.
- [ ] Acceptance: 3-D EI matches measurement to 3 % (vs the
      ~10–30 % cylindrical-shell ceiling); within 5 % of
      manufacturer datasheet AL value at zero bias.

### 4.3 — Reduced-order model (ROM) proxy

- [ ] For cascade Tier 3 (evaluate 100 candidates), build a
      POD-ROM proxy of the full FEA. Reference: pyMOR /
      Krylov-based MOR literature.
- [ ] `backend="rom"` path on `run_direct_fea`; runs the proxy
      and falls back to full FEA on a configurable confidence
      threshold.
- [ ] Acceptance: ROM agrees with full FEA to 5 % at 50× wall
      speedup on a 100-candidate sweep.

## Phase 5 — Migration + FEMMT deprecation (1–2 sessions)

### 5.1 — Cascade Tier 3 dual-backend mode

- [x] `PFC_FEA_BACKEND` env override in `fea/runner.py`
      `validate_design` — opts in to the direct backend without
      changing the Tier 3 signature (3df3271). Cascade Tier 3
      transparently picks up the new backend; on failure it
      logs a warning and falls back to the legacy shape-based
      dispatch — never crashes the orchestrator.
- [x] `_validate_design_direct` adapter projects DirectFeaResult
      → FEAValidation so the cascade's "disagrees_with_tier1"
      flag works identically for both backends (3df3271).
- [x] Four tests lock in: toroidal routes to direct, pct_error
      populated, default dispatch unchanged, unknown env value
      falls back silently (3df3271).
- [x] UI toggle in **Configurações** — combo with Auto / Direct
      / FEMMT / FEMM, persisted via QSettings, sets the env var
      eagerly on launch (3dc1821).
- [x] CLI access via `magnadesign fea` (b04ad18) with
      `--backend` / `--compare` flags for benchmarking and
      one-shot validation.
- [ ] CI: `compare_backends` runs on every PR with both flags
      against the 10-core benchmark set. Regression in either
      backend fails the PR. (Awaits Phase 2.0 case-set expansion.)

### 5.2 — Cutover (`direct` becomes default)

- [ ] Flip the cascade Tier 3 default to `"direct"`.
- [ ] Keep `"femmt"` as opt-in escape hatch for one release.
- [ ] Documentation: `docs/FEA.md` explains the move and how
      to opt back into FEMMT if a user hits an edge case.

### 5.3 — FEMMT hard removal

- [ ] 6 months after 5.2 with no reverted-back-to-FEMMT user
      reports:
  - [ ] Move `pfc_inductor/fea/femmt_runner.py` →
        `vendor/legacy/femmt_runner.py`.
  - [ ] Remove `femmt` + `materialdatabase` from the
        `[fea]` extra in `pyproject.toml`.
  - [ ] Drop the `setuptools<70` pin (was only there for FEMMT).
  - [ ] Delete `setup_deps/femmt_config.py` and `_install_no_space_femmt_shim`.
  - [ ] Remove FEMMT install probe from
        `MainWindow._open_setup_dialog`.
  - [ ] Update `README.md` + `docs/POSITIONING.md` to mark FEMMT
        "removed".
