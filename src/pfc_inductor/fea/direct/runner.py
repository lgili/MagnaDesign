"""Top-level orchestrator for the direct ONELAB backend.

End-to-end pipeline for the **DC magnetostatic Phase 1** of the
FEMMT migration:

::

    Core + Material + Wire + N + I
        │
        ▼
    geometry/ei.build_ei  →  Gmsh model (regions tagged)
        │
        ▼
    mesh.generate  →  ei.msh
        │
        ▼
    physics/magnetostatic.render  →  ei.pro
        │
        ▼
    solver.run_getdp  →  energy_2d.txt + B_field.pos + Magb.pos
        │
        ▼
    postproc.compute_inductance_uH  →  L_dc_uH
    postproc.parse_pos_max_norm      →  B_pk_T
        │
        ▼
    DirectFeaResult

The Phase 1 surface accepts only EI cores. Other shapes raise
``NotImplementedError`` until their ``geometry/<shape>.py`` lands.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pfc_inductor.fea.direct.models import DirectFeaResult, EICoreDims

_LOG = logging.getLogger(__name__)


# ─── Public API ───────────────────────────────────────────────────


def run_direct_fea(
    *,
    core: object,
    material: object,
    wire: object,
    n_turns: int,
    current_A: float,
    workdir: Path,
    backend: str = "axi",
    getdp_exe: Optional[Path] = None,
    timeout_s: float = 600.0,
) -> DirectFeaResult:
    """Run the direct ONELAB pipeline end-to-end.

    Parameters
    ----------
    core, material, wire:
        Same Pydantic models the analytical engine uses
        (``pfc_inductor.models``).
    n_turns:
        Coil turn count.
    current_A:
        DC current (A).
    workdir:
        Directory for all output.
    backend:
        ``"axi"`` (default, recommended) uses the axisymmetric
        formulation with the ``2π·R_mean`` source-area correction
        — gives correct wound-coil inductance magnitudes within
        ~50 % of the analytical ideal on EI cores. ``"planar"``
        uses the simpler 2-D extruded geometry, which only
        captures the bus-bar-pair inductance and is 100 × off
        for wound coils. Use ``"planar"`` only for non-coiled
        geometries (busbars, planar transformers).
    getdp_exe:
        Override path to the GetDP binary.
    timeout_s:
        Hard cap on the solve wall time.
    """
    import math as _math

    shape = str(getattr(core, "shape", "")).lower()
    if shape != "ei":
        raise NotImplementedError(
            f"Direct backend Phase 1 only supports 'ei' cores, got {shape!r}. "
            f"Use the FEMMT backend or wait for Phase 2."
        )

    # Lazy imports — keep cold import cost off the boot path.
    import gmsh

    from pfc_inductor.fea.direct.physics.magnetostatic import MagnetostaticInputs
    from pfc_inductor.fea.direct.postproc import (
        compute_inductance_uH,
        parse_pos_max_norm,
        parse_scalar_table,
    )
    from pfc_inductor.fea.direct.solver import run_getdp
    from pfc_inductor.setup_deps.paths import FeaPaths

    if backend == "axi":
        from pfc_inductor.fea.direct.geometry.ei_axi import build_ei_axi as _build
        from pfc_inductor.fea.direct.physics.magnetostatic_axi import (
            MagnetostaticAxiTemplate as _Template,
        )
    elif backend == "planar":
        from pfc_inductor.fea.direct.geometry.ei import build_ei as _build
        from pfc_inductor.fea.direct.physics.magnetostatic import (
            MagnetostaticTemplate as _Template,
        )
    else:
        raise ValueError(f"backend must be 'axi' or 'planar', got {backend!r}")

    workdir.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: geometry + mesh ---------------------------------
    gmsh.initialize([])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 2)

        _build(gmsh, core=core)

        dims = EICoreDims.from_core(core)
        diag = max(dims.total_w_mm, dims.total_h_mm) * 1e-3
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", diag * 0.05)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", diag * 0.005)
        gmsh.model.mesh.generate(2)

        mesh_path = workdir / "ei.msh"
        gmsh.write(str(mesh_path))
        n_nodes, n_elements = _mesh_stats(gmsh)
    finally:
        gmsh.finalize()

    # ---- Step 2: ``.pro`` rendering ------------------------------
    mu_r = float(getattr(material, "mu_r", None) or getattr(material, "mu_r_initial", None) or 1.0)

    # Coil bundle area calculation. For PLANAR, this is just the
    # window-minus-clearance rectangle. For AXISYMMETRIC, we apply
    # the ``2π·R_mean`` source-area correction so the GetDP source
    # integral ``∫J·v·(2π·r)dA`` recovers the proper ``N·I``
    # ampere-turns (rather than ``2π·R_mean × N·I``, which is what
    # the un-corrected source would deliver). This is the Phase 1.5
    # calibration fix — drops the L_dc error on wound EI cores
    # from ~100× off to ~50 % of analytical on a synthetic test.
    clearance_mm = 1.0
    A_2d_mm2 = max(dims.window_w_mm - 2 * clearance_mm, 0.1) * max(
        dims.window_h_mm - 2 * clearance_mm, 0.1
    )
    if backend == "axi":
        # Same back-derivation as EIAxisymmetricGeometry: center
        # leg modelled as cylinder of radius sqrt(Ae/π).
        r_cl_mm = _math.sqrt(dims.center_leg_w_mm * dims.center_leg_d_mm / _math.pi)
        R_inner_mm = r_cl_mm + clearance_mm
        R_outer_mm = r_cl_mm + dims.window_w_mm - clearance_mm
        R_mean_mm = (R_inner_mm + R_outer_mm) / 2.0
        coil_area_m2 = A_2d_mm2 * 2 * _math.pi * R_mean_mm * 1e-9  # mm² × mm → m³? no, scale below.
        # A_2d in mm² × (2π·R_mean) in mm → result in mm³, divide by
        # 1e9 → m³? That's not right dimensionally. Let me redo.
        # ``coil_area_m2`` is what the template substitutes into the
        # divisor of ``J_amp = N·I/A_coil``. For the axi source
        # integral with VolAxiSqu jacobian to deliver ``N·I``
        # ampere-turns, we need:
        #   A_coil_effective = A_2d × 2π·R_mean    (units: m² × m = m³)
        # The "extra m" comes from the revolution. The .pro then
        # computes J = N·I/A_coil_effective which has units A/m³ —
        # consistent with VolAxiSqu's 3-D-volume integration.
        coil_area_m2 = (A_2d_mm2 * 1e-6) * (2 * _math.pi * R_mean_mm * 1e-3)
    else:
        coil_area_m2 = A_2d_mm2 * 1e-6

    pro_text = _Template().render(
        MagnetostaticInputs(
            mu_r_core=mu_r,
            n_turns=int(n_turns),
            current_A=float(current_A),
            coil_area_m2=coil_area_m2,
            # For axi the depth scaling is handled by VolAxiSqu inside
            # GetDP; the runner doesn't multiply afterward.
            depth_m=dims.center_leg_d_mm * 1e-3,
        )
    )
    pro_path = workdir / "ei.pro"
    pro_path.write_text(pro_text, encoding="utf-8")

    # ---- Step 3: GetDP solve + post ------------------------------
    if getdp_exe is None:
        fp = FeaPaths.detect()
        getdp_exe = fp.onelab_binary_path(fp.default_onelab_dir, "getdp")
    solve_result = run_getdp(
        getdp_exe=getdp_exe,
        pro_path=pro_path,
        msh_path=mesh_path,
        workdir=workdir,
        resolution="Magnetostatic",
        postop="Magnetostatic_out",
        timeout_s=timeout_s,
    )

    # ---- Step 4: parse outputs -----------------------------------
    energy_raw = parse_scalar_table(workdir / "energy_2d.txt") or 0.0
    energy_core = parse_scalar_table(workdir / "energy_core.txt") or 0.0
    energy_gap = parse_scalar_table(workdir / "energy_gap.txt") or 0.0
    B_pk = parse_pos_max_norm(workdir / "Magb.pos") or 0.0

    # Depth scaling: PLANAR returns J/m (per unit z-depth) and the
    # runner multiplies by ``cl_d`` to get 3-D-equivalent energy.
    # AXISYMMETRIC's ``VolAxiSqu`` jacobian already integrates over
    # the 2π·r revolution, so the GetDP scalar IS the full 3-D
    # energy in J — depth multiplier = 1.0.
    depth_m = dims.center_leg_d_mm * 1e-3 if backend == "planar" else 1.0
    total_energy_J = energy_raw * depth_m
    L_uH = compute_inductance_uH(
        energy_2d_Jm=energy_raw,
        depth_m=depth_m,
        current_A=float(current_A),
    )

    # Field PNGs — reuse the FEMMT-era pos_renderer. It scans the
    # workdir for ``.pos`` files and emits matplotlib heatmaps; the
    # UI's FEAFieldGallery is already wired to consume those.
    field_pngs: dict[str, Path] = {}
    try:
        from pfc_inductor.fea.pos_renderer import render_field_pngs

        rendered = render_field_pngs(str(workdir))
        if rendered:
            field_pngs = {p.stem: p for p in rendered}
    except Exception as exc:
        _LOG.warning("pos_renderer failed: %s", exc)

    _LOG.info(
        "direct EI solve: L=%.3f μH · W=%.3e J (core %.3e + gap %.3e) · B_pk=%.3f T · %.2fs",
        L_uH,
        total_energy_J,
        energy_core * depth_m,
        energy_gap * depth_m,
        B_pk,
        solve_result.wall_s,
    )

    return DirectFeaResult(
        L_dc_uH=L_uH,
        energy_J=total_energy_J,
        B_pk_T=B_pk,
        B_avg_T=0.0,  # TODO Phase 1.1 — emit volume-avg in .pro
        mesh_n_elements=n_elements,
        mesh_n_nodes=n_nodes,
        solve_wall_s=solve_result.wall_s,
        workdir=workdir,
        field_pngs=field_pngs,
    )


# ─── Helpers ──────────────────────────────────────────────────────


def _mesh_stats(gmsh_module) -> tuple[int, int]:
    """Quick node + 2-D element count from the active mesh."""
    nodes = gmsh_module.model.mesh.getNodes()
    n_nodes = len(nodes[0])
    n_elements = 0
    _elem_types, elem_tags, _ = gmsh_module.model.mesh.getElements(dim=2)
    for tags in elem_tags:
        n_elements += len(tags)
    return n_nodes, n_elements
