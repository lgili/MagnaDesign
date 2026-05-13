# OpenSpec — FEA Direct Backend (FEMMT replacement)

**Status**: Phase 1 complete (calibrated EI axisymmetric, ~50 % of textbook
analytical, matches FEMMT-modelled physics).
**Goal**: surpass FEMMT in accuracy, speed, and feature coverage, then
**deprecate the FEMMT dependency entirely**.
**Owner**: pfc_inductor/fea/direct/
**Last updated**: Phase 1.10 (commit 137497a)

---

## 1. Mission

Build a **complete FEA backend** for the MagnaDesign suite that:

1. **Replaces every FEMMT call** in the cascade Tier 3 + validation pipeline.
2. **Is faster** (no `pkg_resources` import cost, no FEMMT init overhead).
3. **Is more accurate** on the geometries we care about (rectangular-leg EI,
   custom shapes the FEMMT cylindrical-shell approximation can't represent).
4. **Is more stable** (no SIGSEGV crashes, no version-pin hell, no
   manufacturer-database lock-in).
5. **Is easier to extend** (clear ABCs per shape, per-physics-template
   pattern, lazy imports, no global state).

When this spec is satisfied, FEMMT becomes an optional alternative
backend (kept around for sanity-checking) rather than the production
default.

---

## 2. Success criteria (what "better than FEMMT" means)

| Metric | FEMMT today | Direct target | Validation |
|---|---|---|---|
| **L_dc accuracy** (vs measurement) | ±5 % on gapped ferrite EI | ≤ ±3 % on same | bench data + side-by-side FEMMT |
| **L_dc accuracy** (vs each other) | n/a | ≤ ±5 % difference on 10 reference cores | `compare_backends` test |
| **AC loss accuracy** | ±15 % core, ±10 % cu | ≤ ±15 % core, ≤ ±10 % cu | measurement + FEMMT |
| **Thermal accuracy** (T_winding) | ±10 °C | ≤ ±10 °C | measurement + FEMMT |
| **Cold-start time** | ~1.5 s | ≤ 0.3 s | `time` on a fresh import |
| **Single solve wall** | ~3-8 s | ≤ 3 s | benchmark suite |
| **SIGSEGV rate** | ~5 % on edge cases | 0 (subprocess isolated already) | CI fuzz |
| **Shape coverage** | EE, EI (as axi), PQ, ETD, toroidal, U | All FEMMT shapes + **rectangular-leg EI 3-D** | shape regression |
| **Custom shapes** | hard (patch FEMMT) | trivial (add `geometry/<name>.py`) | dev experience |
| **Custom output paths** | hardcoded | configurable | UI integration |

A row passes when it's met on **the canonical benchmark suite**
(Phase 3) under CI. Two rows passing makes the backend "production
viable"; **all rows passing triggers FEMMT deprecation**.

---

## 3. Current state (Phase 1 wrap-up, 12 commits)

✅ **Pipeline**: Gmsh + GetDP + parsers + matplotlib PNGs end-to-end.
✅ **Region tagging**: `fragment` output map (robust to concave shapes).
✅ **Calibration scaffold**: `compare_backends` oracle + 7 smoke tests.
✅ **Backends shipped**:
   - `backend="planar"` — 2-D extruded (transmission-line physics).
   - `backend="axi"` — 2-D axisymmetric with 2π·R_mean source correction.
✅ **Three `.pro` templates**: `magnetostatic`, `magnetostatic_axi`,
   `magnetostatic_globalq` (circuit-coupled, ready for AC).
✅ **Toroidal geometry generator** (with documented formulation gap).
✅ **EI axi backend** lands within 50 % of textbook analytical (which is
   itself an over-idealised reference — real FEMMT also misses textbook
   by 30-50 % on the same geometry).

❌ **NOT yet built** (the gap to close):
- AC harmonic formulation (complex μ, eddy currents, skin/proximity)
- Thermal physics template
- Toroidal B_φ formulation (the one we identified as needed)
- Stranded conductor model
- Saturation handling (nonlinear μ(B))
- Side-by-side FEMMT benchmark suite
- Cascade Tier 3 integration
- 3-D mode (the leapfrog feature)

---

## 4. Gap analysis — what FEMMT does and how we'll do it

### 4.1 Physics

| FEMMT capability | Our status | Phase to close |
|---|---|---|
| DC magnetostatic, planar 2-D | ✅ shipped | — |
| DC magnetostatic, axisymmetric | ✅ shipped | — |
| AC harmonic (jω), complex μ | ❌ template stub only | **Phase 2.1** |
| Stranded winding (resistance + induction) | ❌ | **Phase 2.2** |
| Litz wire homogenization | ❌ | **Phase 2.3** |
| Foil winding | ❌ | **Phase 2.4** |
| Toroidal B_φ formulation | ❌ geometry only, no physics | **Phase 2.5** |
| Saturation μ(B) | ❌ | **Phase 3.1** |
| Thermal steady-state | ❌ | **Phase 3.2** |
| Coupled EM-thermal | ❌ | **Phase 3.3** |
| Time-domain transient | ❌ | **Phase 4.1** |
| 3-D, rectangular-leg EI | ❌ | **Phase 4.2** (leapfrog) |

### 4.2 Geometries

| Shape | FEMMT | Direct (axi A_φ) | Direct (B_φ) | Direct (3-D) |
|---|---|---|---|---|
| EE / EI (as cylindrical-shell axi) | ✅ | ✅ | n/a | Phase 4.2 |
| Pot / PQ / RM | ✅ | ✅ | n/a | Phase 4.2 |
| Toroidal | ✅ (poloidal — wrong physics for some uses) | ⚠️ wrong | Phase 2.5 | Phase 4.2 |
| Stacked / split | ✅ | partial | n/a | Phase 4.2 |
| Custom / asymmetric | ❌ | trivial via new `geometry/<name>.py` | trivial | Phase 4.2 |
| **Rectangular-leg EI in 3-D** (true geometry) | ❌ | n/a (axi can't) | n/a | **Phase 4.2 leapfrog** |

### 4.3 Engineering ergonomics

| Concern | FEMMT | Direct |
|---|---|---|
| Cold import cost | ~600 ms (`pkg_resources`) | ≤ 80 ms (Gmsh only, lazy) |
| Crash isolation | manual subprocess wrap | already structured |
| Output dir | hardcoded `e_m/results/` | configurable per-call |
| Catalog integration | rigid (`materialdatabase` enum) | reads catalog Pydantic models |
| Test coverage | external | in-repo tests + `compare_backends` |
| Custom physics tweak | patch FEMMT source | edit template string |

---

## 5. Roadmap

### Phase 2 — Production parity (3-4 sessions)

**2.0 — Side-by-side FEMMT benchmark harness**
   *Why first: every later phase needs an oracle.*
   - Wire up a working FEMMT call in `calibration.py` (currently stubbed).
   - Pick 10 reference cores from the catalog (mix of PQ ferrite, toroidal,
     EI laminated). Run both backends, store both results in a `benchmarks/`
     directory, generate a Markdown report.
   - CI gate: `compare_backends` over the 10 cases — assert
     `|L_direct - L_FEMMT| / L_FEMMT < 5 %` for every shape we support.
   - **Acceptance**: a benchmark report with measured numbers for both
     backends on 10 cases lives in the repo.

**2.1 — AC harmonic formulation**
   - New template `physics/magnetostatic_ac.py` built on the existing
     `GlobalQuantity` foundation (Phase 1.4). The `DtDof` term gives
     the jω coupling between A and ir.
   - Complex μ from `Material.complex_mu_r` if present, otherwise scalar.
   - Extract: `L_ac`, `R_ac`, `P_cu_skin`, `P_cu_proximity`, `P_core`.
   - **Acceptance**: AC sweep at 100 Hz / 50 kHz / 100 kHz lands within
     ±10 % of FEMMT on 5 ferrite EI cases.

**2.2 — Stranded conductor model**
   - Add `Resistance[]` term + the `1/AreaCell²` Galerkin contribution
     FEMMT uses for solid round conductors.
   - **Acceptance**: AC resistance matches analytical Bessel for solid
     round wire to 3 %.

**2.3 — Litz / multi-strand homogenization**
   - Effective conductivity / permeability for bundled Litz.
   - Reference: Albach 2013 homogenization theory.
   - **Acceptance**: 100 × 0.1 mm strand Litz at 100 kHz lands within 5 %
     of FEMMT-validated measurement.

**2.4 — Foil winding**
   - Region template for foil layers + eddy current capture along the
     foil width.
   - **Acceptance**: planar transformer foil-secondary L + R matches FEMMT
     to ±5 %.

**2.5 — Toroidal B_φ physics template**
   - The "different physics class" we identified in Phase 1.8.
   - New formulation: A_r/A_z vector in (r, z) plane, B_φ scalar output.
   - Pair with the existing `geometry/toroidal.py`.
   - **Acceptance**: toroidal L lands within 5 % of `μ₀μr·N²·A/(2πR)`
     for a curated ferrite toroid, ±10 % vs FEMMT.

### Phase 3 — Validation + extended physics (2-3 sessions)

**3.1 — Saturation μ(B)**
   - Newton-Raphson iteration on ν(|B|) inside the existing weak form.
   - Reference: FEMMT's `If(Flag_NL)` JacNL block — mirror their approach.
   - **Acceptance**: B vs I curve up to 1.3 × Bsat matches material
     datasheet to 5 %.

**3.2 — Thermal steady-state**
   - New problem class `physics/thermal.py`: scalar heat-conduction
     formulation with loss-density source from the AC pass.
   - BCs: Dirichlet (case temp), Neumann (insulated), convection.
   - **Acceptance**: T_winding lands within 10 °C of measurement on
     a benched ferrite inductor.

**3.3 — EM-thermal one-way coupling**
   - Read loss density from `loss_density.pos`, hand to thermal solver.
   - **Acceptance**: full DC + AC + thermal pipeline runs end-to-end
     in < 10 s for a typical PFC inductor.

### Phase 4 — Surpass FEMMT (3-4 sessions)

**4.1 — Time-domain transient**
   - Time-stepping solver, accepts arbitrary i(t) input.
   - Lower priority — most PFC analysis is steady-state.
   - **Acceptance**: matches analytical L·di/dt = V for a step input.

**4.2 — 3-D mode** ← **the leapfrog feature**
   - 3-D mesh + 3-D vector A formulation in GetDP.
   - Tetrahedral mesh, edge-element basis.
   - Slower but **finally captures rectangular-leg EI correctly**
     (no cylindrical-shell approximation). FEMMT can't do this.
   - **Acceptance**: 3-D EI matches measurement to 3 % (vs the ~10-30 %
     gap of the axi cylindrical-shell approximation).

**4.3 — Reduced-order model (ROM)**
   - For the cascade Tier 3 use case (evaluate 100 candidates), build a
     proxy model that approximates the full FEA at 10-100× speed.
   - Reference: POD-ROM literature; FEMMT doesn't have this.
   - **Acceptance**: ROM agrees with full FEA to 5 % at 50× speedup.

### Phase 5 — Migration + FEMMT deprecation (1-2 sessions)

**5.1 — Cascade Tier 3 dual-backend mode**
   - Add `backend` flag to `cascade.tier3.run_tier3()`.
   - Both backends produce identical-shape outputs (already enforced via
     `DirectFeaResult` mirroring FEMMT's contract).
   - Surface in UI as a settings toggle.

**5.2 — Cutover**
   - Default `cascade Tier 3` to `backend="direct"` once Phase 4 acceptance
     criteria are met across the benchmark suite.
   - Mark FEMMT as soft-deprecated in `pyproject.toml`: keep as optional
     dep, but no longer auto-installed.

**5.3 — FEMMT removal**
   - 6 months after 5.2 cutover, if no regressions:
     - Drop `femmt` from `dependencies`.
     - Move `fea/femmt_runner.py` to `vendor/legacy/` as historical
       reference.
     - Update docs to mark FEMMT as "removed".

---

## 6. Architecture decisions (already made)

These are settled. New work conforms to them; revisit only with
strong evidence.

### 6.1 — Module layout (per responsibility, not per shape)

```
fea/direct/
├── geometry/       # one file per core shape — extends CoreGeometry ABC
│   ├── base.py     # CoreGeometry ABC, RegionTag constants
│   ├── ei.py
│   ├── ei_axi.py
│   ├── toroidal.py
│   └── (Phase 2+: ee.py, pq.py, etd.py, ...)
├── physics/        # one file per problem class — same RegionTag interface
│   ├── magnetostatic.py        # planar 2-D
│   ├── magnetostatic_axi.py    # 2-D ax with VolAxiSqu
│   ├── magnetostatic_globalq.py  # circuit-coupled (foundation for AC)
│   └── (Phase 2+: ac_harmonic.py, thermal.py, transient.py)
├── solver.py       # subprocess GetDP, cancellable
├── postproc.py     # parsers + L extraction methods
├── calibration.py  # compare_backends oracle
└── runner.py       # public API — run_direct_fea(backend=...)
```

### 6.2 — Region-tag protocol

Stable integer ids shared between geometry (creates) and physics
(references). See `geometry/base.py:RegionTag`.

### 6.3 — Two inductance extraction methods, kept in sync

Every magnetostatic template ships:
- `W = ∫ ½ν|B|² dV` and `L_energy = 2W/I²`
- `L_fluxlink = ∫ (CompZ[a]/AreaCell) / I dA` (FEMMT-style)

They must agree to floating-point precision on any case where both
apply. If they diverge, **that's the bug** — not a numerical artifact.

### 6.4 — Axisymmetric source convention

For `Jacobian VolAxiSqu` (the FEMMT-matching choice):

    A_coil_effective = A_2d × 2π·R_mean

so `∫ J · v · 2π·r dA` delivers the natural N·I ampere-turns. The
runner applies this automatically when `backend="axi"`.

### 6.5 — Lazy imports everywhere

No FEA module imports Gmsh, GetDP, or matplotlib at module load.
Cold-start performance is a Phase 0 goal (already met). Any new
module that breaks this is rejected in review.

### 6.6 — DirectFeaResult mirrors FEMMT's contract

The result dataclass exposes the SAME field names FEMMT-derived code
expects (`L_dc_uH`, `B_pk_T`, `P_core_W`, `T_winding_C`). This is
what makes the dual-backend cutover (Phase 5.1) a flag change rather
than a rewrite.

---

## 7. Testing strategy

### 7.1 — Tiers of validation

1. **Self-consistency** (in CI today): both L extraction methods
   agree to floating-point. Lives in `tests/test_direct_calibration.py`.
2. **Cross-backend** (Phase 2.0): direct vs FEMMT on 10 reference
   cores, asserted in CI.
3. **Analytical** (in CI today): closed-form references in
   `calibration.analytical_L_uH` and per-shape variants.
4. **Bench measurement** (Phase 3+): selected bench data from real
   prototypes built on these designs. Lives in
   `tests/benchmarks/measurements.yaml`.
5. **Stress / fuzz** (Phase 5): random catalog cores fed through both
   backends — assert no crash, results within 10 % envelope.

### 7.2 — When a calibration fails

The failure protocol is documented in `PHASE_1_4_PLAN.md` (working
journal). Summary: identify, isolate (sweeps + probes), pivot if
structural, document in OPENSPEC if persistent.

### 7.3 — Performance budgets

Enforced in `tests/test_direct_perf.py` (TODO Phase 2.0):

- Cold start (`from pfc_inductor.fea.direct import run_direct_fea`):
  ≤ 80 ms
- Single magnetostatic solve on a PQ-class inductor: ≤ 3 s wall
- 10-core regression: ≤ 60 s wall

---

## 8. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GetDP version drift breaks `.pro` syntax | low | high | pin via `setup_deps`; templates carry a version banner |
| 3-D solver too slow for cascade | high | high | Phase 4.3 ROM as fallback; or restrict 3-D to validation only |
| Custom physics templates diverge across shapes | medium | medium | keep them in `physics/` not `geometry/`; same RegionTag protocol |
| Saturation Newton iteration doesn't converge | medium | high | reuse FEMMT's `JacNL` block verbatim; add line search |
| FEMMT-removed users have legacy projects | low | medium | keep `fea/femmt_runner.py` as `vendor/legacy/` for 6 months |
| Toroidal B_φ formulation harder than expected | medium | medium | scope to "round-core toroidal only" first; gapped/composite toroids are Phase 4+ |
| Benchmark suite drift (catalog changes) | low | low | freeze a snapshot at `tests/benchmarks/catalog_snapshot.json` |

---

## 9. Acceptance criteria per phase

Each phase ships when:

1. Its **acceptance test** is in CI and green.
2. Its **calibration table** in OPENSPEC is updated with measured
   numbers.
3. The matching row in **section 4.x** transitions from ❌ to ✅.
4. The relevant **example** in `examples/` runs to completion in
   under the wall-time budget.

**Phase n is NOT done** until 1-4 are met. Documentation alone
doesn't count.

---

## 10. Decision log

Significant pivots, with the data that drove them. Append-only.

| Date | Phase | Decision | Why |
|---|---|---|---|
| Phase 1.1 | bug fix | switch region classification from centroid → `fragment` output map | centroid breaks on concave (C-shaped) cores |
| Phase 1.4 | architecture | keep `magnetostatic_globalq` template even though equivalent to constant-J for DC | it's the right form for AC (Phase 2.1) |
| Phase 1.5 | calibration | apply 2π·R_mean correction to A_coil in axi runner | matches GetDP's `VolAxiSqu` jacobian convention |
| Phase 1.7 | analysis | abandon EI-from-textbook calibration as the target metric | textbook ignores leakage; real reference is FEMMT |
| Phase 1.8 | physics | toroidal needs B_φ formulation, not A_φ | wires wrap around tube, not bobbin axis |
| Phase 1.10 | validation | add flux-linkage extraction alongside energy method | catches bugs neither method alone would |
| (next) | … | … | … |

---

## 11. How to use this document

- **Picking up next session?** Read sections 3, 5, and 10 — current
  state, what's next, what was decided why.
- **Reviewing a PR?** Check section 6 (architecture) and section 9
  (acceptance). New code must conform.
- **Reporting a bug?** Add a row to section 8 (risks) if it surfaces
  one we hadn't anticipated.
- **Pivoting?** Update section 10 (decision log) BEFORE changing code,
  not after. The log is the contract.

---

## 12. Open questions

Things worth investigating but not blocking the current roadmap.

- **Can we use ONELAB's Python `pygetdp` directly** instead of
  subprocess? Faster + better cancellation but more API surface to
  track.
- **Does Gmsh's adaptive mesh refinement** play well with our
  per-region size hints? Could cut mesh time 2-3×.
- **3-D mode**: is gmsh.tetrahedra + GetDP's `Hcurl_a_3D` fast enough,
  or do we need a curl-curl-friendly mesh tool?
- **Should we expose ROM-as-cascade-tier-3** as a separate user-facing
  flag, or transparent fallback?

These get answered when they become relevant. None block Phase 2.
