# `pfc_inductor.fea.direct` — direct ONELAB backend

A FEMMT-free finite-element pipeline. Talks to Gmsh (Python API)
and GetDP (subprocess) directly, generates artifacts where we
want them, returns the same `FeaResult` shape the cascade
already consumes.

## 📋 Canonical roadmap

**See [`OPENSPEC.md`](./OPENSPEC.md)** — the contract that defines
what "better than FEMMT" means in measurable terms, the phased
plan to get there, and the acceptance criteria each phase has to
meet. Read that first if you're picking up this work.

This README is the elevator pitch. `OPENSPEC.md` is the spec.
`PHASE_1_4_PLAN.md` is the working journal that tracks **what
happened during Phase 1** in raw detail.

## Status

**Phase 1.1 — DC magnetostatic on EI cores, pipeline + correct
region tagging.** Closed the "can we solve it ourselves at all?"
question:

- ✅ Gmsh + GetDP pipeline end-to-end (mesh, solve, parse, render).
- ✅ Region tagging via `fragment` output map (the centroid-based
  approach in Phase 1.0 silently broke on concave shapes — the
  C-shaped core's centroid falls inside its window-hole, so
  the `Core` physical group was empty and the solver saw
  `μ_r = μ₀` everywhere).
- ⚠️ **L_dc absolute magnitude still ~89× below the analytical
  ideal** `μ₀·N²·Ae / lgap`. The result *does* now respond to
  `μ_r` (was constant in Phase 1.0), but saturates at ~78 μH
  instead of ~7 mH for a 2000-permeability ferrite EI with a
  0.5 mm gap. Working hypotheses (in order of likelihood):

  1. Source-current convention. Standard GetDP `js[]` lookup
     for a union region may need a different region structure;
     the per-region split we tried didn't move the needle but
     a single global `js0[Vol_S_Mag]` form might.
  2. Form0 + BF_Node vs Form1P + BF_PerpendicularEdge — we
     tried both; numerically identical in our tests, so probably
     not the issue, but worth a closer look.
  3. Geometry heuristic (`EICoreDims.from_core`) producing
     inconsistent dimensions vs the analytical formula's
     assumptions about `Ae` / `lgap`.

## Phase 1.3 diagnostics (this session)

The 89-99 × discrepancy after Phase 1.1 is **not** a region-
tagging or function-space bug — that was Phase 1.1's territory.
Phase 1.3 ran four targeted experiments that narrowed the
remaining work:

1. **`L ∝ N²` scaling** holds exactly across N ∈ {40, 80, 160,
   320} (ratios 4.000 / 16.000 to 3 dp). Source is being
   applied consistently.
2. **GetDP source integral** ``∫J_z dA over Coil_pos = 400.013``
   for N·I = 400 — the prescribed source IS correctly handed
   to the solver.
3. **Region-tagged ν** distinguishes Core vs Air in the field
   plot: ``|B|_core ≈ 5 mT`` vs ``|B|_air ≈ 0.8 mT`` (a 6 ×
   concentration), but the absolute magnitude is 200 × smaller
   than the analytical ~1 T in the gap. So μ_r IS being
   honoured but the field doesn't *amplify* the way a wound
   coil's would.
4. **Axisymmetric variant** (new `geometry/ei_axi.py` +
   `physics/magnetostatic_axi.py`) using FEMMT's `VolAxiSqu`
   convention also produces ~50-78 μH plateaus. Topology
   change alone doesn't recover the missing factor.

The remaining gap is the **flux-linkage convention**. FEMMT
models the coil bundle as a **circuit-coupled stranded
winding** — a `GlobalQuantity` current DOF `ir` over the
bundle with `BF_RegionZ` basis, coupled to the field via
``-1/AreaCell × Dof{ir}`` in the Galerkin. Externally, a
`Constraint Current_2D` pins `Is = I_prescribed`. Our direct
backend prescribes J directly as a numerical constant, which
is mathematically equivalent for the DC case **but only when
the GlobalQuantity-coupled flux-linkage equation is also
present**. Without it, the formulation captures the field
strength but misses the per-turn linkage amplification.

Phase 1.4 will add the GlobalQuantity / Hregion_i_2D /
Voltage-Current constraint structure to our `.pro` template
and run side-by-side against a curated EI from the catalog.

## Status

**Phase 1.1 — DC magnetostatic on EI cores, pipeline + correct
region tagging.** Closed the "can we solve it ourselves at all?"
question:

- ✅ Gmsh + GetDP pipeline end-to-end (mesh, solve, parse, render).
- ✅ Region tagging via `fragment` output map.
- ✅ μ_r is honoured (B_core 6 × > B_air).
- ✅ Calibration scaffold (`compare_backends`) ships an oracle
  for Phase 1.4 iteration.
- ✅ Axisymmetric variant (`ei_axi.py` + `magnetostatic_axi.py`)
  ships as an alternative topology — same architecture, different
  jacobian convention.
- ⚠️ **L_dc ~100 × below the analytical ideal** on synthetic
  test cases. Diagnosed (Phase 1.3) as a missing
  `GlobalQuantity` circuit-coupling term. Phase 1.4 is the fix.

Once L_dc lands within 5 % of FEMMT, Phase 2 adds more shapes;
Phase 3 adds AC + thermal.

## Why this exists

FEMMT is a great research tool but, as a library dependency, it:

- bundles a rigid geometry generator that won't accept custom
  shapes;
- spends ~500 ms in `MagneticComponent()` construction before
  the solver even starts (50 s of pure waste in a 100-candidate
  sweep);
- hardcodes output paths under `e_m/results/`, fights us when we
  want artifacts next to the user's project;
- pulls `pkg_resources` at import (deprecated + slow);
- aggregates losses; we want per-region breakdowns for PFC.

This package owns the full pipeline so we control all four.

## Stack

| Layer    | What we use it for                          |
|----------|---------------------------------------------|
| Gmsh     | Geometry + mesh (Python API, no GUI)        |
| GetDP    | FEM solve via `.pro` templates (subprocess) |
| `pos_renderer.py` | `.pos` → matplotlib PNGs (reused) |

Both Gmsh and GetDP are open source. Gmsh ships as a `pip`
wheel; GetDP comes from ONELAB and is already managed by our
`setup_deps/` module.

## Module map

```
direct/
├── README.md             ← you are here
├── __init__.py           ← lazy re-exports
├── models.py             ← DirectFeaResult, BCKind, EICoreDims
├── geometry/
│   ├── base.py           ← CoreGeometry ABC, RegionTag constants
│   └── ei.py             ← EI geometry via gmsh.model.occ
├── physics/
│   └── magnetostatic.py  ← .pro template (DC + L by energy method)
├── solver.py             ← getdp subprocess + Cancellable + timeout
├── postproc.py           ← .txt + .pos parsers, L = 2 W / I²
└── runner.py             ← top-level orchestrator (public API)
```

The package is organized **by responsibility**, not by shape, so
adding EE / PQ / toroidal is `geometry/ee.py` etc. without
touching physics / solver / runner.

## Region-tag convention

Stable integers shared between the geometry layer (which
*creates* the physical groups) and the physics layer (which
*references* them by number in the `.pro` template):

| Tag | Region          | Material        |
|-----|-----------------|-----------------|
| 1   | `Core`          | `μ_r` from `Material` |
| 2   | `AirGap`        | `μ_r = 1`       |
| 3   | `Air`           | `μ_r = 1`       |
| 10  | `Coil_pos`      | `μ_r = 1`, `J_z = +N·I/A` |
| 11  | `Coil_neg`      | `μ_r = 1`, `J_z = -N·I/A` |
| 100 | `OuterBoundary` | Dirichlet `A = 0` |

`RegionTag` in `geometry/base.py` is the source of truth.

## Formulation

**A-formulation, planar 2-D.** Solve for the z-component of the
magnetic vector potential `A`. Find `A_z` such that

    curl(ν · curl A_z) = J_s    inside the domain
    A_z = 0                      on OuterBoundary

with `ν = 1/μ` (reluctivity) and `J_s = N·I/A_coil` (uniform
across the homogenized bundle).

**Inductance via energy method.** Compute energy per unit depth

    W_2d = ∫ ½ · ν · |B|² dΩ        (J/m)

then scale by the out-of-plane depth `d_z` and apply

    L = 2 · (W_2d · d_z) / I²

This is preferred over the flux-linkage method because it
generalizes cleanly to nonlinear `μ(B)` (co-energy) and works
without needing to draw individual turns.

## Coordinate system

`(x, y)` is the 2-D plane the geometry is drawn in. `x` runs
left-to-right along the core; `y` runs bottom-to-top. The
out-of-plane axis `z` is the center-leg depth — currents
(`J_z`) and vector potential (`A_z`) point along `z`.

For an EI core this is the standard side-view cross-section:
yokes top + bottom, three legs (outer, center with gap, outer),
two windows holding the winding.

## Adding a new core shape

1. Create `geometry/<shape>.py`.
2. Subclass `CoreGeometry`, populate `build()`:
   - draw the 2-D outline via `gmsh.model.occ`,
   - tag the regions using `RegionTag.*` so the existing `.pro`
     template works without changes,
   - return a `GeometryBuildResult`.
3. Update `runner.run_direct_fea` to dispatch on `core.shape`.
4. Add a parity test against FEMMT.

The physics / solver / postproc layers don't change.

## Known limitations (Phase 1)

- **EI only.** Other shapes raise `NotImplementedError`.
- **Linear `μ_r`.** No saturation. AC pass with `μ(B)` is Phase 3.
- **Homogenized winding.** Bundle modeled as uniform current
  density — fine for `L`/`B_pk`, wrong for `R_ac` (Phase 3).
- **No thermal.** Steady-state heat pass is Phase 3.
- **Approximate dimensions.** `EICoreDims.from_core()` heuristic
  back-derives geometry from `Ae`/`Wa`. Real datasheet dims for
  every catalog part is a Phase 2 ingestion task.

## Validation plan

Once Phase 1 lands, add `tests/test_direct_fea_ei.py`:

- Pick one canonical EI core + material + winding spec from
  the existing FEMMT regression set.
- Run both backends; assert `|L_direct - L_FEMMT| / L_FEMMT < 0.05`.
- Assert `|B_pk_direct - B_pk_FEMMT| / B_pk_FEMMT < 0.10`.

5 % L tolerance is realistic given the geometry-back-derivation
heuristic; tighten to 1 % once explicit dims land in Phase 2.
