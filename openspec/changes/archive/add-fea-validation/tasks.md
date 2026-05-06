# Tasks — FEA validation

## 1. Foundation

- [x] 1.1 Add `pyfemm` to `pyproject.toml` as optional dep group `[fea]`
- [x] 1.2 Detect FEMM at app start: `fea/probe.py::is_femm_available()` —
      check `xfemm` binary on PATH (Linux/macOS) or registry/install dir
      (Windows). Cache in MainWindow on init.
- [x] 1.3 If missing, the FEA button stays in the toolbar but disabled with
      tooltip "FEMM não detectado: instale com brew install xfemm /
      apt install xfemm / baixe femm.info para Windows."

## 2. Geometry export (toroid first)

- [x] 2.1 `fea/geometry.py::toroid_axisym_problem(core, info, N, wire)` →
      builds the FEMM problem: cross-section rectangle (radial × axial),
      annular winding region (N circles representing wire turns).
- [x] 2.2 Material assignment: core material from FEMM library by μ_r and
      Bsat; if not in library, register as new material with our
      anchored-Steinmetz coefficients.
- [x] 2.3 Excitation: AC current source = `I_pk` of design at low line,
      sinusoidal at `f_sw` (and a separate run at `f_line` for envelope).
- [x] 2.4 Mesh refinement near core surface and winding (~0.2 mm element
      size). Validate mesh quality programmatically.

## 3. Solve and post-process

- [x] 3.1 `fea/solver.py::solve(problem, output_dir)` — invokes FEMM headless,
      writes `.ans` solution. Background `QThread` worker.
- [x] 3.2 `fea/postprocess.py`:
      - `inductance_H(solution)` from flux linkage / current
      - `peak_flux_density_T(solution)` over core volume
      - `core_loss_W(solution, material)` via volume integral of Pv
      - `copper_loss_W(solution)` from J²/σ integrated
      - `B_field_grid(solution, plane)` for heatmap render
- [x] 3.3 Compare FEA results against analytic, package as `FEAValidation`
      pydantic model with `L_pct_error`, `B_pk_pct_error`, `loss_pct_error`,
      and the raw `B_field_grid`.

## 4. UI integration

- [x] 4.1 Add tab "FEA" to `plot_panel`. Initially shows "Clique em
      'Validar com FEA' para começar".
- [x] 4.2 Toolbar action "Validar com FEA" → background solve, progress bar,
      then populate the tab.
- [x] 4.3 FEA tab layout:
      - Top: numeric comparison table (L, B_pk, P_core, P_cu, % error each)
      - Middle: B-field heatmap plot (matplotlib pcolormesh, with isocontours)
      - Bottom: Δ summary ("FEA confirma o design dentro de X% nas 4 métricas")
- [x] 4.4 Cache the last FEA result per design hash so re-clicking is instant.

## 5. EE/ETD/PQ support (phase 2 — superseded)

> The original v1 plan was to add FEMM 2D-planar EE/ETD/PQ alongside
> the toroid axisymmetric solver. Mid-flight we switched the EE path
> to **FEMMT** (`add-femmt-integration`) because FEMM lacks a
> cross-platform installer for macOS/Linux and FEMMT covers EE/ETD/PQ
> natively. The three items below are therefore left intentionally
> unchecked — they were superseded, not abandoned.

- [~] 5.1 `fea/geometry.py::planar_problem(core, info, N, wire)` for bobbin
      shapes — 2D planar through the centre line.
      _(superseded by FEMMT path — see `archive/add-femmt-integration`)_
- [~] 5.2 Re-use solve/postprocess pipeline.
      _(superseded — FEMMT has its own postprocess)_
- [~] 5.3 Verify against a known textbook EE design example.
      _(superseded — FEMMT path is the validator for EE/ETD/PQ)_

## 6. Testing

- [x] 6.1 Unit test: `toroid_axisym_problem` builds a valid `.fem` file
      (verify via FEMM lib parser).
- [x] 6.2 Regression test: solve a small toroid (ferrite, low N) and assert
      L_FEA matches analytic within 10%.
- [x] 6.3 Skip-marker decorator for tests: `@pytest.mark.skipif(not
      is_femm_available())`.

## 7. Docs

- [x] 7.1 `README.md`: add "Optional FEMM integration" section with
      install instructions per OS.
- [x] 7.2 Tooltip + status bar message when FEA solve completes.
