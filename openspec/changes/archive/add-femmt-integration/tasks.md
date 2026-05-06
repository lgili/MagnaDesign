# Tasks — FEMMT integration

## 1. Dependency

- [x] 1.1 Add `femmt>=0.5` to `pyproject.toml` extras `[fea]`.
- [x] 1.2 Vendor a smoke-test FEMMT script under `tests/fixtures/femmt/`
      that exercises a tiny toroid problem and runs in <5 s.

## 2. Probe + dispatcher

- [x] 2.1 `fea/probe.py::is_femmt_available()` — try `import femmt` and
      probe ONELAB binary; cache the answer.
- [x] 2.2 `fea/probe.py::active_backend()` — returns `"femmt" | "femm" |
      "none"`. Honours `PFC_FEA_BACKEND` env var.
- [x] 2.3 `fea/runner.py::validate_design` becomes a dispatcher.

## 3. FEMMT runner

- [x] 3.1 `fea/femmt_runner.py::build_problem(core, material, wire,
      result) -> femmt.MagneticComponent`. Map our Toroid →
      FEMMT geometry primitives.
- [x] 3.2 Material registration: emit FEMMT material objects from our
      internal `Material` (μ_initial, Bsat, optionally B-H curve).
- [x] 3.3 Excitation: peak DC current on the coil; static magnetic
      problem.
- [x] 3.4 Run + read back: FEMMT exposes flux linkage and field maps via
      its API — no need to parse `.ans` files.
- [x] 3.5 Build `FEAValidation` instance from FEMMT outputs.

## 4. Legacy FEMM path

- [x] 4.1 Move `fea/geometry.py`, `fea/solver.py`, `fea/postprocess.py`
      to `fea/legacy/femm_*.py` without behaviour changes.
- [x] 4.2 Re-export at `fea/__init__.py` so existing call sites keep
      working.

## 5. UI

- [x] 5.1 `ui/fea_dialog.py`: status header now displays
      "Backend: FEMMT (recomendado)" or "Backend: FEMM (legado)".
- [x] 5.2 Add a settings menu (or env-var doc tooltip) to switch
      backends.
- [x] 5.3 Drop the macOS Wine warning when FEMMT is detected.

## 6. EE / ETD / PQ support

- [x] 6.1 Bobbin shapes: FEMMT natively supports E and PQ cores. Build
      mappers `_make_ee_problem`, `_make_etd_problem`, `_make_pq_problem`.
- [x] 6.2 Validate against published FEMMT examples for a small EE.
- [x] 6.3 Update the toolbar action's "shape unsupported" gate so it
      now allows EE/ETD/PQ when FEMMT is the active backend.

## 7. Tests

- [x] 7.1 `@pytest.mark.skipif(not is_femmt_available())` for FEMMT
      tests; they always pass when run on CI with `[fea]` installed.
- [x] 7.2 Smoke: validate a small toroid against ours; assert L_FEA
      within 5%.
- [x] 7.3 Smoke: validate an EE; same tolerance.

## 8. Docs

- [x] 8.1 README: "FEM validation" section. Default install instruction
      becomes `pip install pfc-inductor-designer[fea]`.
- [x] 8.2 README appendix: "Legacy FEMM backend" with the existing
      install hints.
