# Phase 1.4 — closing the calibration gap

## State at start of session

After Phase 1.0-1.3:

- Pipeline (Gmsh + GetDP + parsers + PNGs): ✅ end-to-end.
- Region tagging via `fragment` output map: ✅ Core ≠ AirGap ≠ Air.
- μ_r is honoured: `|B|_core ≈ 5 mT` vs `|B|_air ≈ 0.8 mT` (6 ×
  concentration measured).
- `L ∝ N²` scales exactly (3 dp).
- `∫J_z dA` over Coil_pos = 400.013 At for N·I = 400 At (source
  delivered correctly).
- **L_dc is 100 × below the analytical ideal** (78 μH measured
  vs 7740 μH expected on the synthetic EI test case at μ_r =
  2000, lgap = 0.5 mm).
- Axisymmetric variant (`ei_axi.py` + `magnetostatic_axi.py`)
  also lands at ~48 μH — topology change alone doesn't fix it.

## Root cause (hypothesis)

The 2-D PLANAR formulation **fundamentally cannot represent a
wound inductor's flux linkage**. With `+J` in one window and
`-J` in the other (the natural 2-D-extrusion of a helical coil),
the physical model becomes "two parallel bus bars with opposite
currents in an iron core", whose inductance per unit length is
the **transmission-line-like** `L' = (μ₀/π)·ln(d/r)` ≈ 12 nH/turn²
for our geometry — exactly what we measure (78 μH at N = 80 →
12.25 nH/turn²).

A wound coil's L is **chain-linkage-amplified**: each of N
turns links the full flux Φ, so `L = N·Φ/I = N²·μ₀·Ae/lgap`.
The N² factor comes from the **chain** linkage, which 2-D planar
extrusion does not encode.

FEMMT recovers this by:

1. Using axisymmetric geometry (revolution around bobbin axis)
   so the wire is naturally a "ring" around the axis.
2. Encoding the coil bundle as a `Hregion_i_2D` function space
   with `BF_RegionZ` basis — a region-wise constant vector
   representing the **total bundle current** as a single global
   DOF.
3. Adding the `GlobalQuantity` machinery that couples this DOF
   to a `Voltage_2D` / `Current_2D` constraint pair, so the
   external "applied current" pins the total Is = I, and Us is
   solved for as the resulting voltage.
4. Applying the source via `[-1/AreaCell × Dof{ir}, {a}]` where
   `AreaCell = A_bundle / NbrCond` is the **per-strand** area
   (not the bundle area). This is the missing N² factor:

       J_FEMMT = N · I / AreaCell = N · I / (A_bundle / N) = N² · I / A_bundle
       J_ours  = N · I / A_bundle

   The ratio is N. With N = 80 and energy ∝ J², that's 80² =
   6400. Times the "2-D-planar miss" of order 1, you land at the
   100 × discrepancy we measure (factor ~80, our 100 is the
   right order).

**This is the missing piece.** Phase 1.4 is implementing it.

## Phase 1.4 deliverables

1. **Per-strand `AreaCell` parameter.** Extend
   `MagnetostaticInputs` (and the axi variant) with
   `area_cell_m2` = `coil_area_m2 / n_turns`. Use this in the
   source term instead of `coil_area_m2`.

2. **GlobalQuantity function space.** Add to the `.pro`
   template:

   ```getdp
   FunctionSpace {
     { Name Hregion_i_2D; Type Vector;
       BasisFunction {
         { Name sr; NameOfCoef ir; Function BF_RegionZ;
           Support Coil_pos; Entity Coil_pos; }
       }
       GlobalQuantity {
         { Name Is; Type AliasOf;        NameOfCoef ir; }
         { Name Us; Type AssociatedWith; NameOfCoef ir; }
       }
       Constraint {
         { NameOfCoef Us; EntityType Region; NameOfConstraint Voltage_2D; }
         { NameOfCoef Is; EntityType Region; NameOfConstraint Current_2D; }
       }
     }
   }

   Constraint {
     { Name Current_2D;
       Case { { Region Coil_pos; Value {current_A}; } } }
     { Name Voltage_2D; Case { } }
   }
   ```

3. **Formulation: replace constant `js[]` with `Dof{ir}`.**

   ```getdp
   Quantity {
     { Name a;  Type Local;  NameOfSpace Hcurl_a; }
     { Name ir; Type Local;  NameOfSpace Hregion_i_2D; }
     { Name Us; Type Global; NameOfSpace Hregion_i_2D[Us]; }
     { Name Is; Type Global; NameOfSpace Hregion_i_2D[Is]; }
   }

   Equation {
     Galerkin { [ nu[] * Dof{d a}, {d a} ];
       In Magnetic; Jacobian JVol; Integration I_Gauss; }
     Galerkin { [ -N_turns / AreaCell * Dof{ir}, {a} ];
       In Coil_pos; Jacobian JVol; Integration I_Gauss; }
     GlobalTerm { [ Dof{Us}, {Is} ];
       In Coil_pos; }
   }
   ```

   Note the `N_turns / AreaCell` factor — this is where the N²
   comes from (`AreaCell` is per-strand).

4. **Validate on a curated EI from the catalog.** 66 EI cores
   in the dataset (all dongxing SI-steel). Use
   `compare_backends` with FEMMT enabled:

   ```python
   from pfc_inductor.fea.direct.calibration import compare_backends
   report = compare_backends(
       core=load_cores()[i_real_ei],
       material=load_materials()[...],
       wire=load_wires()[...],
       n_turns=...,
       current_A=...,
       spec=...,
       design_result=...,
   )
   assert abs(report.diff_pct) < 5.0
   ```

5. **Promote `direct` to `cascade Tier 3` backend flag**
   (deferred — only after step 4 lands).

## Anti-goals (don't do in Phase 1.4)

- AC harmonic (`Freq` parameter, complex μ). That's Phase 2.
- Thermal. Phase 3.
- More core shapes. Phase 2.
- Saturation (`nu[Norm[{d a}], Freq]`). Linear-μ is fine for
  Phase 1.4.

## Verification

The acceptance criterion is `|diff_pct| < 5 %` on **at least one
real EI core** from the catalog, compared against FEMMT as the
oracle. The `compare_backends` test infrastructure (Phase 1.2)
already exists for this.

If FEMMT errors out on the chosen core (silicon-steel + closed,
both are FEMMT-unfriendly), fall back to the analytical
`μ₀N²Ae/(le/μ_r + lgap)` reference for the high-μ_r limit.

## Effort estimate

~1 focused session. The .pro template is the only file that
substantially changes; everything else (geometry, postproc,
runner, calibration) is already in place.

## Phase 1.4 IMPLEMENTATION RESULT (this session)

Implemented `MagnetostaticGlobalQTemplate` in
`physics/magnetostatic_globalq.py` — full FEMMT-mirroring
structure with `Hregion_i_2D` function space, `Is`/`Us`
GlobalQuantity, `Current_2D`/`Voltage_2D` constraints, and
the `-1/AreaCell × Dof{ir}` Galerkin source term.

**Empirical result: L_fem = 78.41 μH** — exactly the same as
the constant-J formulation.

### Why structurally equivalent

For DC magnetostatic with no resistance and no eddy currents,
all three formulations collapse to the same weak form:

- **Constant J**:    ``∫ ν∇A·∇v dΩ = ∫ J_const · v dΩ``
- **CompZ source**:  ``∫ ν∇A·∇v dΩ = ∫ J_const,z · v dΩ``
- **GlobalQuantity**: ``∫ ν∇A·∇v dΩ = ∫ (ir/AreaCell) · v dΩ``
  with the side constraint ``ir = I_prescribed``

In the last form ``ir/AreaCell = I_prescribed/A_bundle = J_const``.
After the constraint resolves, all three integrate to identical
RHS values. The ``GlobalTerm Us · Is_test = 0`` adds a row that
forces ``Us = 0`` (correct for DC), but doesn't affect A.

### So the 100× gap is real (and structural)

This rules out the "missing GlobalQuantity factor" hypothesis.
The remaining options for the calibration gap are:

1. **2-D planar is the wrong geometric simplification** for
   a wound EI inductor. With +J in one window and −J in the
   other, we're solving "two parallel bus bars in iron" — the
   transmission-line geometry. The wound-coil flux-linkage
   factor N² is built-in but the geometric L per turn is
   determined by bus-bar physics, not solenoid physics. The
   measured 12.25 nH/turn² is the bus-bar value for this
   geometry. **This is the canonical, deep result.**

2. **Fix via axisymmetric**: model the EI as a round-leg
   approximation and revolve. The wire becomes a true loop
   around the axis (not a parallel pair) and the flux linkage
   recovers naturally. The Phase 1.3 axi attempt landed at
   48 μH instead of 6930 μH, but that geometry had its own
   issues (mesh near r=0, the cylindrical-shell-outer-leg
   approximation). The right move is to debug + tighten the
   axisymmetric variant, not to keep trying to coax 2-D planar
   into being something it isn't.

3. **Fix via 3-D**: out of scope. 10-100× slower for marginal
   gain.

### Recommended Phase 1.5

Pivot effort onto fixing the existing `ei_axi.py` +
`magnetostatic_axi.py` pair. Concrete steps:

- Audit `EIAxisymmetricGeometry.build`: verify the air-gap
  position, the outer-air-box ranges, the mesh field near
  `r = 0` (which has the natural ``A_φ = 0`` BC).
- Run the `μ_r` sweep on the axi geometry and verify it now
  responds: with the right boundary and mesh, the L should
  rise toward the analytical with high μ_r.
- If axi gets within 10 % of analytical, declare Phase 1
  done and move to Phase 2 (more shapes).

The `GlobalQuantity` template stays in tree — it'll be the
right form once we add AC (where ``Dt[a]`` couples Us = jωL·I
gives a different `L` extraction path) and circuit-coupled
problems. So this implementation isn't wasted work.

## Phase 1.5 RESULT (this session)

Found and applied the **``2π·R_mean`` source-area correction**
for axisymmetric. The runner now ships a working `backend="axi"`
path that gives correct-order-of-magnitude inductance values
on wound EI cores. From `78 μH` (planar, wrong physics) to
`3840 μH` (axi, correct order of magnitude). Analytical ideal:
6930 μH at μ_r=2000, lgap=0.5 mm on the synthetic test case.

## Phase 1.6 characterization (also this session)

Ran 3 parameter sweeps on the axi backend to characterize the
remaining ~50 % residual error:

```
Sweep 1: lgap   (N=80, μ_r=2000)
  lgap=0.1 mm: L_fem= 3852 μH   L_ana=24588 μH   ratio=0.157
  lgap=0.5 mm: L_fem= 3840 μH   L_ana= 6930 μH   ratio=0.554
  lgap=1.0 mm: L_fem= 3828 μH   L_ana= 3652 μH   ratio=1.048
  lgap=2.0 mm: L_fem= 3820 μH   L_ana= 1876 μH   ratio=2.036
  lgap=5.0 mm: L_fem= 3782 μH   L_ana=  763 μH   ratio=4.955

Sweep 2: N   (lgap=0.5 mm, μ_r=2000)
  All N: ratio is EXACTLY 0.554 (N² scaling perfect)

Sweep 3: μ_r   (N=80, lgap=0.5 mm)
  μ_r= 100: ratio=1.627
  μ_r= 500: ratio=0.724
  μ_r=2000: ratio=0.554
  μ_r=10000: ratio=0.509  (plateaus)
```

**The FEM gives a constant ~3840 μH** regardless of `lgap` and
`μ_r`. That's a SYMPTOMATIC of the flux taking a path the model
doesn't expect — equivalent to an effective gap of ~1 mm.

Hypotheses ruled out
--------------------
- **Bobbin clearance**: dropped clearance from 1 mm → 0.02 mm
  and L only varied 3925 → 3731 μH (5 %). Not the bottleneck.
- **Geometric gap**: confirmed AirGap physical group has the
  expected 6.18 mm² area when ``lgap_mm`` is set.

Remaining hypotheses
--------------------
1. **Flux is concentrating at the ``r = 0`` axis singularity**
   instead of distributing through the iron loop. The earlier
   axi field plot showed a bright stripe at r = 0 with little
   B in the legs / yokes. The ``BF_PerpendicularEdge`` basis
   handles ``A_φ = 0`` at the axis automatically, but the
   numerical handling might be problematic.
2. **Wrong outer-leg thickness** in our `EICoreDims.from_core`
   heuristic. The cylindrical shell approximation might give a
   shell that's too thin (current value: ~3 mm thick) producing
   a saturation-like ceiling.
3. **Mesh-induced artifact**: the gap region might not be
   adequately discretized for the axi formulation (the planar
   "fine mesh in the gap" hint was applied uniformly).

Phase 1.7 / next session
------------------------
Focus on item 1 — the r = 0 singularity. Specific test:
geometrically OFFSET the center leg slightly (so r_inner > 0)
and see if the field response improves. If yes, the issue is
the r = 0 boundary handling and we need an explicit Dirichlet
``A_φ = 0`` constraint there.

## Empirical data from Phase 1.3 (end of session)

A quick "what if I just scale J by N?" experiment ruled out the
naive interpretation:

- Original: ``J = N·I/A_coil`` → L_fem = 78 μH at N=80
- Scaled: ``J = N²·I/A_coil`` → L_fem = 502 000 μH
- Expected if energy ∝ J²: ``L_naive × N⁴ / N² = 78 × N² = 499 200 μH`` ✓
- Analytical reference at μ_r = 2000: 6930 μH

So naive J → N² · J scales L by N² (= 6400 ×) which **overshoots
the 100 × gap by ~70 ×**. The right fix is NOT a flat
multiplicative scaling — it's the **circuit-coupled
formulation** (GlobalQuantity / Hregion_i_2D / Current_2D
constraint), which enforces ``∫J·v dΩ = I_total`` as a global
equation instead of distributing N·I across the bundle. The
energy-method extraction then yields the per-N² inductance
amplification automatically because the global current DOF
links flux properly.

This also explains why the axisymmetric variant (Phase 1.3) on
its own didn't fix it: switching the topology without adding
the global-current coupling still leaves you with the
"distributed-J" formulation. **Both pieces are needed** —
axisymmetric topology AND GlobalQuantity.

Open question for Phase 1.4: planar 2-D + GlobalQuantity might
also work mathematically (the global current DOF doesn't care
about topology). If it does, we'd recover correct L without
the round-leg approximation that axisymmetric forces. Worth
trying first because it preserves the geometric fidelity of
the EI's rectangular legs.

## Phase 1.7 SMOKING-GUN result (continuation of this session)

Checked the iron contribution to L by sweeping closed-vs-open
core + comparing with `μ_r = 1`:

```
lgap=0.0 mm (closed): L_fem = 3851 μH   B_pk = 0.305 T
lgap=0.5 mm:          L_fem = 3840 μH   B_pk = 0.304 T
lgap=5.0 mm (huge):   L_fem = 3782 μH   B_pk = 0.305 T

μ_r=1, lgap=0 (NO IRON AT ALL):  L_fem = 3250 μH
```

**The iron contributes only ~18 % to the FEM's L.** A real
wound inductor's iron should multiply L by 100s-1000s vs
air-core. Our axisymmetric model is essentially returning the
air-core inductance with a small iron-concentration boost.

What this means
---------------
The flux is NOT following the magnetic loop through the iron.
Most flux stays in the air around the coil bundle, with only
modest enhancement in the iron regions. Diagnosis: the
**cylindrical-shell outer-leg approximation** (3 mm thick ring
at r ≈ 25 mm) creates leakage paths the analytical
`μ₀N²Ae/lgap` formula doesn't model. The leakage parallel-
combines with the iron path and lowers the effective L.

Confirmation:
- B_core ≈ 6 × B_air (iron presents as low-reluctance but only
  partially — about 18 % of flux goes through it).
- L is insensitive to ``lgap`` (gap reluctance is irrelevant
  because most flux bypasses the iron loop entirely).
- L is insensitive to ``μ_r`` (going from 100 to 10 000 only
  reduces L by 0.3 %).

Path forward for Phase 2 (next session)
---------------------------------------

The cylindrical-shell EI is fundamentally a *poor* axisymmetric
approximation for a rectangular-legged EI. Options:

1. **Pivot to toroidal as first calibrated shape.** Toroidal IS
   naturally axisymmetric (round leg + round window), so the
   cylindrical-shell limitation doesn't apply. Implement
   `geometry/toroidal.py`, run calibration end-to-end on a
   curated toroidal from the catalog (thousands available).
   **Lowest risk, fastest to a working calibrated backend.**
2. **Replace EI axi geometry with TRUE 3-D EI model.** Heavy
   lift but the only way to faithfully model rectangular-leg
   EI cores. ~3-4 sessions of work.
3. **Side-by-side FEMMT run on a curated EI.** Definitively
   distinguish "our formulation has a bug" from "our
   formulation models the wrong physical system". Needs a
   valid `Spec` + `DesignResult` that FEMMT accepts.

**Recommendation:** Option 1 (toroidal first). EI calibration
ranges as Phase 2 after toroidal works.
