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

## Phase 2 — Production parity (3–4 sessions)

**Definition of done**: cascade Tier 3 can switch to the direct
backend on at least one curated PFC use case with measurable
parity (L within 5 %, AC loss within 10 %) against FEMMT and
no regressions in `compare_backends` CI.

### 2.0 — Side-by-side FEMMT benchmark harness

- [ ] Wire a working FEMMT call in `calibration.py::_run_femmt`
      (currently stubbed): construct `MagneticComponent`, set
      core/wire/insulation, run `single_simulation`, parse the
      `log['single_sweeps'][0]['winding1']['flux_over_current']`
      output back into `BackendOutcome`.
- [ ] `tests/benchmarks/` directory + `tests/benchmarks/cores.yaml`
      with 10 curated reference cases: 4 ferrite PQ (small / mid /
      large + saturated), 3 ferrite EI / EE, 3 toroidal (1
      Magnetics, 1 Magmattec, 1 Micrometals). For each: spec, N,
      I, expected L from FEMMT (recorded at first run).
- [ ] `tests/test_femmt_benchmark.py` — pytest-marked
      `slow` (~5 min per case). Run-on-CI gate:
      `pytest -m slow tests/test_femmt_benchmark.py`. Asserts
      `|L_direct - L_femmt| / L_femmt < 0.05` on each shape; for
      now AC and thermal columns are recorded but not asserted.
- [ ] CI workflow `validation-fea-benchmark.yml`: trigger on
      `[fea]` label or weekly schedule; uploads the comparison
      table as a GitHub Pages artifact under
      `validation/fea-benchmark/<date>/`.

### 2.1 — AC harmonic formulation

- [ ] `physics/magnetostatic_ac.py` template — extends
      `magnetostatic_globalq` with the `DtDof` Galerkin term that
      couples ``Dt[a]`` to ``ir`` (jω in frequency domain). Use
      complex `nu[Norm[{d a}], Freq]` if available, scalar
      otherwise.
- [ ] Add `Material.complex_mu_r` field (optional; falls back to
      scalar `mu_r`). Sourcing for ferrites: manufacturer
      datasheets (TDK, Ferroxcube) — record a small table in
      `data/material_datasheets/complex_mu/` and consume it via
      a `data_loader` extension.
- [ ] Extract `L_ac`, `R_ac`, `P_cu_skin`, `P_cu_proximity`,
      `P_core` in `postproc.py` from the AC pass. Store on
      `DirectFeaResult` (already declared as Optional fields).
- [ ] `compare_backends` test slice for AC: same 10 cores,
      sweep at 100 Hz, 50 kHz, 100 kHz; assert
      `|L_ac_direct - L_ac_femmt| / L_ac_femmt < 0.05` and
      `|R_ac| / R_ac_femmt < 0.10` on every case.

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

- [ ] New `physics/magnetostatic_toroidal.py` — solves for
      `A_r r̂ + A_z ẑ` (in-plane vector potential); `B = curl(A)`
      has only φ component. Source J in (r, z) plane.
- [ ] Pair with existing `geometry/toroidal.py`. Update
      `runner.run_direct_fea` to dispatch on `core.shape`
      to the right physics+geometry pair.
- [ ] Acceptance: toroidal L lands within 5 % of
      `μ₀μrN²A/(2πR)` for an ideal ferrite toroid AND within
      10 % of FEMMT on a curated case from the catalog.

## Phase 3 — Extended physics (2–3 sessions)

### 3.1 — Saturation μ(B)

- [ ] Mirror FEMMT's `If(Flag_NL)` JacNL Galerkin block —
      Newton-Raphson iteration with line search on ν(|B|).
- [ ] Acceptance: B vs I curve up to 1.3 × Bsat matches material
      datasheet curve to 5 %.

### 3.2 — Thermal steady-state

- [ ] New problem class `physics/thermal.py` — scalar
      heat-conduction equation with `loss_density.pos` from the
      AC pass as source. BCs: Dirichlet (case-edge T), Neumann
      (insulated), convection (h × ΔT).
- [ ] `geometry/<shape>.py` gains optional thermal regions
      (case, ambient ring); when absent, the thermal solver
      falls back to a Dirichlet `T_amb` on the air box.
- [ ] Acceptance: T_winding-steady on a benched ferrite
      inductor within 10 °C of measurement; within 5 °C of
      FEMMT on the same case.

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

- [ ] `backend` kwarg on `optimize/cascade/tier3.run_tier3()` —
      `"femmt"` (default through Phase 5.2) or `"direct"`.
- [ ] UI: add a "FEA backend" toggle in **Configurações** with
      a "Recommended: direct (faster, more accurate)" hint when
      the benchmark gates have all passed.
- [ ] CI: `compare_backends` runs on every PR with both flags
      against the 10-core benchmark set. Regression in either
      backend fails the PR.

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
