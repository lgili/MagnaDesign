# Replace FEMMT with a direct ONELAB FEA backend

## Why

FEMMT is the current cascade Tier 3 backend. It works, but every
production run pays its costs:

- **Cold-start tax** ~600 ms from a `pkg_resources` import on its
  toplevel (deprecated, removed in setuptools ≥ 70 — we already
  pin `setuptools<70` to keep it alive).
- **Hardcoded output paths** under `e_m/results/`. The cascade
  has to copy artifacts back to its own working directory; the
  UI's `FEAFieldGallery` likewise can't point at FEMMT's tree
  directly.
- **SIGSEGV in C extensions** on edge geometries (high N, tight
  windows). We already subprocess-wrap FEMMT to contain the blast
  radius; that's another ~150 ms of overhead per call.
- **Manufacturer-database lock-in** (`materialdatabase` enum with
  per-vendor measurement-setup-specific permeability) makes it
  painful to swap our own Pydantic Material in.
- **Geometry is rigid** — every shape (EE, EI, PQ, ETD, toroidal)
  is modelled as the same axisymmetric cylindrical-shell, which
  is correct for round-leg cores but misses rectangular-leg EI
  by ~10–30 %. Custom shapes (asymmetric gaps, foil layers off
  the bobbin) require patching FEMMT source.

We have already built the **pipeline** to replace it (12 commits,
`pfc_inductor/fea/direct/`): Gmsh + GetDP + parsers + matplotlib
PNGs, with calibrated EI axisymmetric output that mirrors FEMMT
physics within ~5 %. The remaining work is AC harmonic, thermal,
toroidal-specific formulation, and the side-by-side benchmark
that proves "as good or better than FEMMT" on a curated set.

Without this change, every operational FEA cost above stays in
the cascade indefinitely and the rectangular-leg-EI accuracy
ceiling is permanent.

## What Changes

Build the FEA pipeline that fully replaces FEMMT for every
cascade Tier 3 + validation use case in the app:

1. **FEMMT side-by-side benchmark harness** — a CI gate that runs
   both backends on 10 curated cores and asserts
   `|L_direct - L_femmt| / L_femmt < 5 %` per shape.
2. **AC harmonic formulation** — complex μ, eddy-current coupling
   via the existing `GlobalQuantity` template; extract L_ac,
   R_ac, P_cu skin/proximity, P_core.
3. **Stranded / Litz / foil winding models** matching FEMMT's
   accuracy on bench measurements.
4. **Toroidal-specific B_φ physics** — Phase 1.8 identified that
   toroidal flux is azimuthal, not poloidal; A_φ formulation is
   the wrong problem class. A new `physics/magnetostatic_toroidal.py`
   solves the right one.
5. **Saturation + thermal + EM-thermal coupling** — matches
   FEMMT's full physics chain.
6. **3-D mode (leapfrog feature)** — captures rectangular-leg EI
   directly, beating FEMMT's cylindrical-shell approximation by
   ~10–30 % on the geometries we care about.
7. **Cascade dual-backend mode** — a `backend` flag on
   `cascade.tier3.run_tier3()` runs either path; cutover happens
   once benchmark gates pass.
8. **FEMMT deprecation** — soft-remove from `[fea]` extra after
   6 months stable on the new default; hard-remove from
   `dependencies` after.

The work is **strictly additive** through Phase 4 (5.1
introduces dual mode). Existing FEMMT-based code paths stay
operational; users opt into the new backend per setting until
the cutover.

## Impact

- **Capability added**: `fea-direct-backend`
- **Capabilities deprecated**: `fea-femmt-integration` (kept as
  optional alternative through Phase 5.2, removed at 5.3).
- **New code**: ~3000 LOC already in `pfc_inductor/fea/direct/`
  from Phase 1; another ~2500 LOC estimated through Phase 5.
- **New dependencies**: none — Gmsh + GetDP are already bundled
  via `setup_deps/onelab.py`. The matplotlib + numpy stack is
  unchanged.
- **Removed dependencies** (after 5.3): `femmt`,
  `materialdatabase`, the `setuptools<70` pin.
- **New CI gates**: `tests/test_direct_calibration.py` (already
  in CI), `tests/test_femmt_benchmark.py` (Phase 2.0), per-phase
  acceptance tests as each lands.
- **Performance**: cold start of the FEA module path drops from
  ~1.5 s to ≤ 0.3 s; single-solve wall drops 3–8 s → ≤ 3 s.
- **Stability**: SIGSEGV rate goes to zero (no `femmt.functions`
  segfaults in C extensions).
- **UI**: no immediate change — the cascade Tier 3 page keeps
  the same controls. A "FEA backend" toggle lands in
  Configurações during Phase 5.1.

## Non-goals

- We do **not** replace FEMMT for users of FEMMT outside our
  app. The `femmt_runner.py` adapter stays in tree (moved to
  `vendor/legacy/` at 5.3) so anyone vendoring our code keeps
  the FEMMT path available.
- We do **not** support every FEMMT feature on day one. Niche
  features (axi-coupled inductor pairs, custom material rolloff
  curves via FEMMT's `MaterialDataSource.Measurement`) are
  deferred to Phase 4+ and prioritised by demand.
- We do **not** chase 100 % of the textbook analytical
  `μ₀N²Aᵉ/lgap` — Phase 1 measured this is unreachable in
  axisymmetric (real-world inductors leak by 30–50 %). Our
  reference is **FEMMT on the same geometry plus measurement**,
  not the textbook ideal.

## Strategic pivot — May 2026

Phase 2.0 benchmarking surfaced a structural calibration bug in
the axisymmetric FEM: the combination of Form1P /
BF_PerpendicularEdge basis + VolAxiSqu jacobian + our source
term produces an ``L`` that is essentially insensitive to both
the air gap (0.5 % change for 0 → 5 mm sweep) and the material
``μ_r`` (12 % change for 1 → 10 000 sweep). Fixing it in place
needs the function-space pair FEMMT also uses
(``Hregion_u_2D`` + ``Hregion_i_2D`` with circuit-coupled global
quantities) — that's effectively Phase 4.2 (3-D mode), a 3-4
session commitment.

Pragmatic pivot, all shipped May 2026:

- **Phase 2.5**: toroidal closed-form `μ·N²·HT·ln(OD/ID)/(2π)`
  + powder aggregate `μ·N²·Ae/le`. Exact for the linear-μ case.
- **Phase 2.6**: analytical reluctance with Roters/McLyman
  fringing for non-toroidal axi shapes (EE/EI/PQ/ETD/RM/P/EP/EFD).
  Matches FEMMT median 11 % on the curated benchmark — was 776 %
  with the FEM-axi path.
- **Phase 2.7**: AL fast path. When the catalog ships
  ``AL_nH`` and the caller doesn't override the gap, return
  ``L = AL × N² × mu_pct`` directly. 8/8 within 5 % of catalog,
  6/8 exact.
- **Phase 2.8**: Dowell m-layer AC resistance — analytical
  closed-form for round-wire windings. Skin + proximity at
  ±15 % vs FEMMT AC FEM.
- **Phase 3.2 alpha**: Lumped thermal wrapping the existing
  engine module — `T_winding_C` and `T_core_C` populated on
  ``DirectFeaResult`` when callers pass loss totals.

The FEM-axi path stays in tree as ``backend="axi"`` for research
/ cross-check. Phase 4.2 (3-D mode) will replace it with a
proper rectangular-leg solver that doesn't have the structural
bug, targeting the original ≤ 5 % vs FEMMT requirement.

Coverage win is independent of accuracy: direct backend handles
12/12 shapes in the curated set; FEMMT covers 6/12 (no toroidal,
no RM, no P, no EP, no EFD). For shapes FEMMT doesn't support,
the direct backend is the only option short of Ansys/COMSOL.

Speedup is also independent: median wall time for the direct
analytical solvers is ~1 ms; FEMMT averages ~10 s. 5000×+ on the
benchmark.
