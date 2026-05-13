# Design — replace-femmt-with-direct-fea

## Architecture

The replacement lives entirely in `pfc_inductor/fea/direct/`. The
existing `pfc_inductor/fea/femmt_runner.py` adapter stays in tree
through Phase 5.2 as a fallback backend and is moved to
`vendor/legacy/` at Phase 5.3.

Module layout (May 2026 — per responsibility, not per shape):

```
fea/direct/
├── __init__.py             # lazy re-exports (no Gmsh import on toplevel)
├── models.py               # DirectFeaResult, BCKind, EICoreDims, _femmt_db_lookup
├── geometry/               # one file per shape; same RegionTag protocol
│   ├── base.py             # CoreGeometry ABC, RegionTag constants
│   ├── ei.py               # 2-D planar EI
│   ├── ei_axi.py           # 2-D axisymmetric EI
│   └── toroidal.py         # toroidal half-meridian (geometry, kept for
│                           #    future FEM toroidal; current solver is
│                           #    purely analytical so the geometry is
│                           #    bypassed by the dispatcher)
├── physics/                # one file per problem class
│   ├── magnetostatic.py            # planar DC (Phase 1, FEM path)
│   ├── magnetostatic_axi.py        # axisymmetric DC w/ VolAxiSqu
│   │                                #   (Phase 1; has the structural
│   │                                #    calibration bug — opt-in only)
│   ├── magnetostatic_globalq.py    # circuit-coupled DC foundation
│   ├── magnetostatic_ac.py         # Phase 2.1 — AC harmonic (FEM)
│   ├── magnetostatic_toroidal.py   # Phase 2.5 — analytical toroidal
│   │                                #   (closed-form, geometric + aggregate)
│   ├── reluctance_axi.py           # Phase 2.6 — analytical reluctance
│   │                                #   (default for non-toroidal axi)
│   ├── saturation.py               # Phase 2.5b — DC-bias μ rolloff
│   ├── dowell_ac.py                # Phase 2.8 — Dowell AC resistance
│   └── thermal.py                  # Phase 3.2α — lumped natural-conv
├── solver.py               # subprocess GetDP, Cancellable, timeout
├── postproc.py             # parsers + L extraction + complex (AC) scalar
├── calibration.py          # compare_backends oracle
└── runner.py               # public API — dispatches:
                            #   shape ∈ toroidal → analytical toroidal
                            #   else, AL+no-gap-override → AL fast path
                            #   else, backend="reluctance" (default)
                            #   backend="axi" or "planar" → FEM (opt-in)
                            #   + automatic Dowell when frequency_Hz is set
                            #   + automatic thermal when P_cu_W/P_core_W set
```

CLI entry: ``magnadesign fea`` (Phase 5.1) wires this to the
``run_direct_fea`` API for shell access + ``--compare`` mode that
runs both backends side-by-side.

Cascade Tier 3 dispatch (Phase 5.1): the legacy
``pfc_inductor.fea.runner.validate_design`` gained a
``PFC_FEA_BACKEND`` env override that routes through
``_validate_design_direct`` when set. UI selector under
**Configurações → FEA backend** persists the choice via
``QSettings``.

Why per responsibility:

- A new shape adds **one file** (`geometry/<shape>.py`). Physics
  templates reused unchanged.
- A new physics adds **one file** (`physics/<problem>.py`). Every
  existing geometry stays valid.
- ABCs in `geometry/base.py` and the stable `RegionTag` integer
  table are the contract that holds the two layers together —
  geometry emits, physics consumes, neither knows about the other.

## Region-tag protocol

Stable integer ids in `geometry/base.py:RegionTag` are referenced
by the `.pro` templates via `str.format` placeholders that resolve
to those exact constants. The integers are the single source of
truth — change once and the template renders update automatically.

| Tag | Region          | Material         |
|----:|-----------------|------------------|
|   1 | `Core`          | `μ_r` from Material |
|   2 | `AirGap`        | `μ_r = 1`        |
|   3 | `Air`           | `μ_r = 1`        |
|  10 | `Coil_pos`      | `μ_r = 1`, +J source |
|  11 | `Coil_neg`      | `μ_r = 1`, -J source (planar only) |
| 100 | `OuterBoundary` | Dirichlet A = 0  |

## Inductance extraction (two methods, kept in sync)

Every magnetostatic template emits both:

- `W = ∫ ½·ν·|B|² dV` and `L_energy = 2W/I²` — the canonical
  energy-method extraction.
- `Λ = ∫ (CompZ[a]/AreaCell) dA` over the coil region; `L_flux =
  Λ/I` — FEMMT's flux-linkage method.

These must agree to floating-point precision on any case where
both apply. They have agreed across every Phase 1 test
(L_energy = L_flux to ≤ 10⁻⁴ relative). If they ever diverge,
**that's the bug** — the divergence is the diagnostic.

## Axisymmetric source convention

Phase 1.5 settled this:

When using `Jacobian VolAxiSqu` (the FEMMT-matching choice), the
GetDP volume element implicitly includes a `2π·r` factor. For the
source integral `∫ J · v · 2π·r dA` to deliver `N·I` total
ampere-turns through any (r, z) loop in the coil bundle, the
prescribed J must be:

    J = N · I / (A_2d × 2π·R_mean)

Equivalently, the runner passes `coil_area_m2 = A_2d × 2π·R_mean`
to the physics template, which then uses `J = N·I / coil_area_m2`
unchanged.

This is **the** numerical correction that moved Phase 1 from
100 × off to ~50 % off (= same envelope FEMMT has on the same
axisymmetric round-leg approximation).

`R_mean` is the (arithmetic) mean radius of the bundle's
(r_inner, r_outer) extent. Phase 4.2's 3-D mode drops this
correction because the 3-D volume integral doesn't have the
2π·r factor.

## DirectFeaResult mirrors FEMMT's contract

`DirectFeaResult` in `models.py` exposes the field names FEMMT-
derived code expects:

- `L_dc_uH`, `L_ac_uH`, `R_ac_mOhm`
- `B_pk_T`, `B_avg_T`
- `P_cu_ac_W`, `P_core_W`
- `T_winding_C`, `T_core_C`
- `mesh_n_elements`, `mesh_n_nodes`, `solve_wall_s`
- `workdir`, `field_pngs` map

Optional fields are `None` when the corresponding pass wasn't
run (no AC, no thermal). This is what makes the cascade Tier 3
cutover (Phase 5.1) a single `backend` flag flip rather than a
type rewrite.

## Lazy imports everywhere

The `fea/direct/__init__.py` re-exports via `__getattr__` so no
Gmsh import fires until the first call. The runner imports Gmsh
locally inside `run_direct_fea`. The matplotlib backend lives
behind `pos_renderer`, which is itself a lazy import.

This is enforced by `tests/test_perf_cold_import.py` (TODO
Phase 2.0) — `from pfc_inductor.fea.direct import run_direct_fea`
must complete in ≤ 80 ms on a cold cache.

## Subprocess solver with cancellation

GetDP runs in its own process group via `start_new_session=True`.
The runner polls a `Cancellable` flag between `subprocess.communicate`
timeouts; on cancel it SIGTERMs the whole group (catches any
helper processes ONELAB spawned). Hard timeout via the same
polling loop.

This is the same crash-isolation model the existing FEMMT
adapter uses (`_run_validation_in_subprocess`), so the cascade
already handles subprocess-style errors uniformly.

## Toroidal physics — the open question

Phase 1.8 surfaced that toroidals need a *different* problem
class than EI/PQ/pot:

- EI/PQ/pot wires wrap the bobbin axis → B is poloidal (in r, z)
  → `A_φ` formulation.
- Toroidal wires wrap the donut tube → B is azimuthal (in φ) →
  `A_r r̂ + A_z ẑ` formulation.

Phase 2.5 adds `physics/magnetostatic_toroidal.py` with the
second formulation. The geometry generator (`geometry/toroidal.py`)
already lays out the right half-meridian; only the physics
template changes.

FEMMT papers over this by treating toroidals as A_φ with a
nominal poloidal-equivalent geometry. Our calibration shows that
gives ~30 % error on round toroidals vs the analytical
`μ₀μrN²A/(2πR)`. Phase 2.5 fixes it; this is one place we
**will** be more accurate than FEMMT.

## 3-D mode — the leapfrog

Phase 4.2 adds `backend="3d"` with full tetrahedral mesh +
GetDP edge-element `Hcurl_a_3D` basis. Slower than axisymmetric
(~5–10 × wall) but captures rectangular-leg EI directly.

This is the **one feature FEMMT cannot match**. FEMMT's whole
geometry pipeline is 2-D axisymmetric; rectangular-leg EI is
inherently approximated. For users designing line-reactor
laminated cores where the rectangular geometry matters, 3-D is
a categorical accuracy improvement.

Phase 4.3's ROM proxy compensates for the speed penalty: the
proxy approximates 3-D results at 50 × speedup, with the full
3-D pass available as a falsifiable check.

## Risk: GetDP version drift

The `.pro` template syntax could break across GetDP versions.
Mitigations:

- `setup_deps/onelab.py` pins the ONELAB bundle's version
  (currently GetDP 4.0.0). Upgrade is an explicit action.
- Each `.pro` template carries a version-banner comment on its
  first line referencing the GetDP minor that authored it. CI
  checks the banner matches the installed binary's
  `getdp --version`.
- Phase 5 lands a `tests/test_pro_template_renders.py` that
  loads + validates every shipped template against a held-out
  set of inputs and asserts GetDP doesn't error on `-pre`.
