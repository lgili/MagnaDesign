# 12 — FEM Templates (GetDP) — Research Path

**Status**: MIXED — `MagSta_a` planar + axi are LIVE; `MagDyn_a`, `GlobalQ`, `3D` are RESEARCH / FUTURE
**Code**: `physics/magnetostatic.py`, `magnetostatic_axi.py`, `magnetostatic_globalq.py`, `magnetostatic_ac.py`, `magnetostatic_3d.py`
**Tests**: `tests/test_direct_phase_2_3_2_4_3_1.py`

The reluctance solver is the default for one reason: it's faster and
just as accurate on the catalog we ship. But there are research /
verification cases where you want a "real" FEM model — to anchor
calibration, to render field heatmaps that look right, or to chase
3-D effects the reluctance model can't see. This file documents the
GetDP templates that exist, their state, and what each one is for.

## 1. Background — what GetDP gives us

GetDP is the FEM solver we call as a subprocess. It consumes:
- A **mesh** (`.msh`) from Gmsh.
- A **physics template** (`.pro`) we generate from Jinja2-style
  rendering.

It emits:
- Energy and per-region integrals (`OnGlobal` postops).
- Field files (`.pos`) for `|B|`, eddy current density, etc.
- Per-conductor circuit quantities (impedance, voltage, current).

The templates in this directory each target one **formulation** —
the choice of solver, boundary conditions, and excitation.

## 2. Templates currently in the repo

| Module | Formulation | Source | Status |
|---|---|---|---|
| `magnetostatic.py` | DC `MagSta_a` planar 2-D | fixed `J = NI/A_coil` | **LIVE** (`backend="planar"`) |
| `magnetostatic_axi.py` | DC `MagSta_a` axisymmetric | fixed `J` + `VolAxiSqu` jacobian | **LIVE** (`backend="axi"`, recommended for EI) |
| `magnetostatic_globalq.py` | DC `MagSta_a` planar with circuit-coupled bundle | `GlobalQuantity Is/Us` DOF | **RESEARCH** (Phase 1.4) |
| `magnetostatic_ac.py` | Harmonic `MagDyn_a` | complex `j ω σ A + ∇×ν∇×A = J_s` | **RESEARCH** (Phase 2.1) |
| `magnetostatic_3d.py` | 3-D tetrahedral `Hcurl_a_3D` | placeholder | **FUTURE** (Phase 4.2) |

## 3. DC Magnetostatic `MagSta_a` — the weak form

The weak form of the magnetostatic problem (`MagSta_a` in GetDP
terminology):

```
∫_Ω   ν · (∇ × A) · (∇ × A')   dΩ   =   ∫_Ω   J_s · A'   dΩ


ν   =   1 / μ   =   1 / (μ_0 · μ_r)
J_s =   N · I / A_coil       (homogenised — for fixed-J formulation)
```

`A` is the magnetic vector potential. In 2-D planar `A` has only
out-of-plane (z) component; in 2-D axisymmetric `A` has only
azimuthal (φ) component with the special `r²` jacobian.

Once `A` is solved, inductance comes from the **energy method**:

```
W   =   ½  ·  ∫_Ω  ν · |B|²  dΩ   =   ½  ·  L · I²


L   =   2W / I²
```

## 4. Planar 2-D template (`magnetostatic.py`)

**File**: `physics/magnetostatic.py` (renders `.pro` from
`MagnetostaticInputs` dataclass).

**Geometry**: 2-D EI cross-section in (x, y). Each region (core, gap,
coil ±, air) is a closed contour.

**Excitation**: fixed homogenised `J = NI/A_coil` in each coil
bundle. The "±" pair runs current up in one column, down in the
adjacent one — the textbook bus-bar pair.

**Output integration**:
- 2-D integral returns **per-unit-depth** energy (J/m).
- Runner multiplies by `center_leg_d_mm × 10⁻³` to recover 3-D
  energy in J.

**Known calibration trap**: in Phase 1.4 we discovered the planar
template captures the **bus-bar-pair inductance** of two infinite
columns, not the wound-coil inductance. The two differ by 100× for
real wound coils. The fix was to switch to `backend="axi"` for EI
geometries, which recovers the correct linkage via the `2π·R_mean`
revolution.

**When to use**: bus-bar-style planar transformers, or as a
debugging cross-check on the axi template. For wound-coil EI cores,
prefer `backend="axi"`.

## 5. Axisymmetric template (`magnetostatic_axi.py`)

**File**: `physics/magnetostatic_axi.py`.

**Geometry**: half-meridian (r, z) plane, `r ≥ 0` everywhere. The
real 3-D geometry is recovered by revolving around the z-axis.

**Excitation**: fixed `J` in the coil region, with the
`VolAxiSqu` jacobian that internally integrates over the `2π·r`
revolution and applies the `r²` factor for `A_φ`.

**Output integration**:
- GetDP integral **already** returns 3-D energy in J (no depth
  multiplier needed). The runner multiplies by `1.0` for the axi
  backend.

**Important runner-side correction (Phase 1.5)**:

The fixed-J excitation needs the source area to be the
`2π·R_mean`-corrected version, **not** the 2-D `A_2d`:

```
A_coil_effective   =   A_2d   ·   2π · R_mean     (units: m² · m = m³)
J_amp              =   N · I / A_coil_effective    (units: A / m³)
```

This is done in `runner.py:309`. Off by `2π · R_mean` → off by ~50 ×
on EI core L.

**When to use**: default FEM backend (`backend="axi"`) for any
non-toroidal shape. Captures the round-leg approximation correctly.

## 6. GlobalQuantity template (`magnetostatic_globalq.py`) — RESEARCH

**File**: `physics/magnetostatic_globalq.py`.

**What's different**: instead of fixed `J`, the coil bundle is
modelled as a **circuit element** with degrees of freedom for the
flux linkage. The source equation becomes:

```
Coil region:    -1/A_AreaCell  ·  Dof(i_r)


Global eq:      Dof(U_s)  ·  (I_s)   =   0
```

`Hregion_i_2D` space + `GlobalQuantity Is/Us` declarations. Solves
for **both** the field and the flux linkage simultaneously.

**Why it exists**: FEMMT's Phase 1.4 calibration story documented
that distributed-J under-estimates flux linkage on wound coils by
~100×. This template was meant to recover the right answer
analytically.

**Why it's not LIVE**: the reluctance solver (Phase 2.6) hit our
accuracy target without needing GlobalQuantity, so we never wired
this template into the dispatcher. It remains as research for a
future "needs a real circuit-coupled FEM" use case (e.g. transformer
coupling matrices).

## 7. AC harmonic template (`magnetostatic_ac.py`) — RESEARCH

**File**: `physics/magnetostatic_ac.py`.

**Formulation**: frequency-domain `MagDyn_a`:

```
∇ × (ν · ∇ × A)   +   jω · σ · A   =   J_s
```

Yields complex `A`, from which:

```
Z   =   R_ac   +   jω · L_ac
```

is computed via energy integrals over conductor regions.

**Why it exists**: Phase 2.1 wanted a "real" AC-FEM result for
cross-checking Dowell's closed-form. With complex `μ_r` material
data, this template would give `L_ac(f)` and core-loss volume
integral.

**Why it's not LIVE**: Dowell + complex-μ-correction (Phase 2.8) is
much faster (microseconds) and matches the AC-FEM to ~5% on
representative cases. The template is preserved for future cases
where Dowell's 1-D-skin assumption breaks (axial flux variation in
tall windings).

## 8. 3-D template (`magnetostatic_3d.py`) — FUTURE

**File**: `physics/magnetostatic_3d.py` (stub).

**Formulation**: 3-D `Hcurl_a_3D` on a tet mesh. True rectangular-leg
EI geometry, full window with bobbin, accurate fringing flux
patterns.

**What it would solve**:
- The Roters clamp at `k = 3` failure mode for large gaps.
- The axisymmetric round-leg approximation (~5–10 % L error on
  rectangular EI).
- Partial-winding-coverage error on toroids.

**Why it's a stub**: 3-D FEM is **expensive** (1–10 min per solve),
and our current accuracy target (≤ 15 % vs FEMMT) is already
exceeded by the reluctance solver. Phase 4.2 will revisit when 2-D
becomes the bottleneck.

## 9. Region tagging — the glue layer

All FEM templates rely on **consistent region tags** between the
geometry builder and the physics template. The contract:

```python
# In models.py:
class RegionTag(IntEnum):
    CORE           = 1
    AIR_GAP        = 2
    AIR_OUTER      = 3
    COIL_POS       = 10
    COIL_NEG       = 11
    OUTER_BOUNDARY = 100
```

Geometry builder must tag every surface with one of these. Physics
template references the tags via `Region { ... }` / `Function { ... }`
blocks.

**Phase 1.0 bug**: the original geometry builder used centroid-based
region detection, which silently broke on concave shapes (the
C-shaped core's centroid falls inside its window-hole). The fix in
`geometry/ei.py` was to track regions via Gmsh's OCC `fragment`
output map — every surface tagged at construction time.

## 10. How to invoke a FEM backend

```python
result = run_direct_fea(
    core=ee_core,
    material=n87,
    wire=awg14,
    n_turns=80,
    current_A=5.0,
    workdir=Path("/tmp/fea_test"),
    backend="axi",          # ← FEM backend
    timeout_s=120,
)
print(result.L_dc_uH)       # FEM L
print(result.field_pngs)    # dict of label → PNG paths
```

Wall time: 2–10 s on a modern laptop. The mesh is the bottleneck
(~3 s); the actual GetDP solve is ~1 s.

## 11. Code map

| Concern | Location |
|---|---|
| Planar template | `physics/magnetostatic.py` |
| Axi template | `physics/magnetostatic_axi.py` |
| GlobalQuantity (research) | `physics/magnetostatic_globalq.py` |
| AC harmonic (research) | `physics/magnetostatic_ac.py` |
| 3-D stub | `physics/magnetostatic_3d.py` |
| Solver wrapper | `solver.py:run_getdp` |
| Postproc parsers | `postproc.py` |
| Region tags | `models.py:RegionTag` |
| Geometry builders | `geometry/ei.py`, `ei_axi.py`, `toroidal.py` |
| FEM dispatch | `runner.py:182–193` |

## 12. References

- GetDP user manual — http://getdp.info/
- Geuzaine, C. & Remacle, J.-F., "Gmsh: A 3-D finite element mesh
  generator", *Int. J. Numerical Methods Eng.* (2009).
- Dular, P. & Geuzaine, C., "GetDP reference manual: the discrete
  geometric approach" — formulation details for `MagSta_a`,
  `MagDyn_a`, `Hcurl_a_3D`.
- Kaltenbacher, M., *Numerical Simulation of Mechatronic Sensors and
  Actuators* — finite-element treatment of magnetic field problems.
