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
        Coil turn count. Used as the source ampere-turns
        ``J_s = N·I / A_coil``.
    current_A:
        DC current (A). Linear problem so this only sets the
        absolute scale of the field plots; ``L`` is unaffected.
    workdir:
        Directory for all output. Created if missing. Existing
        files in it are overwritten without warning.
    getdp_exe:
        Override path to the GetDP binary. Defaults to the
        platform-default location resolved by ``FeaPaths``.
    timeout_s:
        Hard cap on the solve wall time. Raises
        :class:`pfc_inductor.fea.direct.solver.SolveError` on
        overrun.

    Returns
    -------
    DirectFeaResult
        L_dc, energy, B_pk + diagnostic paths.

    Raises
    ------
    NotImplementedError
        Non-EI shape (toroidal, EE, PQ, …) — Phase 2+.
    pfc_inductor.fea.direct.solver.SolveError
        GetDP returned non-zero exit code or output files missing.
    """
    shape = str(getattr(core, "shape", "")).lower()
    if shape != "ei":
        raise NotImplementedError(
            f"Direct backend Phase 1 only supports 'ei' cores, got {shape!r}. "
            f"Use the FEMMT backend or wait for Phase 2."
        )

    # Lazy imports — keep cold import cost off the boot path.
    import gmsh

    from pfc_inductor.fea.direct.geometry.ei import build_ei
    from pfc_inductor.fea.direct.physics.magnetostatic import (
        MagnetostaticInputs,
        MagnetostaticTemplate,
    )
    from pfc_inductor.fea.direct.postproc import (
        compute_inductance_uH,
        parse_pos_max_norm,
        parse_scalar_table,
    )
    from pfc_inductor.fea.direct.solver import run_getdp
    from pfc_inductor.setup_deps.paths import FeaPaths

    workdir.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: geometry + mesh ---------------------------------
    # Gmsh's Python API holds a global state, so we initialize +
    # finalize around the whole run. The ``try/finally`` guarantees
    # cleanup even on solver errors.
    gmsh.initialize([])
    try:
        # Quiet Gmsh's chatter to terminal — verbosity 2 = warnings
        # only. Useful logs still come from us via _LOG.
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 2)

        # Discard the build result for now — Phase 2 will use it to
        # apply per-region mesh refinement (gap finer than core, etc.).
        build_ei(gmsh, core=core)

        # Mesh hints — coarsest in air, finer in core, finest in
        # the gap (where flux crowds). The values below are
        # conservative; tune in Phase 2 once we have FEMMT-baseline
        # comparisons.
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
    # μ_r from the material model — Material has ``mu_r`` for
    # ferrites and ``mu_r_initial`` for powder cores; fall back to
    # μ_r = 1 if neither is set (gives a sane open-circuit case).
    mu_r = float(getattr(material, "mu_r", None) or getattr(material, "mu_r_initial", None) or 1.0)

    # Coil bundle area = window area − bobbin clearance ring. We
    # use the rectangle the EI geometry actually drew: window minus
    # 2×clearance on each axis.
    clearance_mm = 1.0  # mirror EIGeometry default
    coil_area_m2 = (
        max(dims.window_w_mm - 2 * clearance_mm, 0.1)
        * max(dims.window_h_mm - 2 * clearance_mm, 0.1)
        * 1e-6
    )

    tpl = MagnetostaticTemplate()
    pro_text = tpl.render(
        MagnetostaticInputs(
            mu_r_core=mu_r,
            n_turns=int(n_turns),
            current_A=float(current_A),
            coil_area_m2=coil_area_m2,
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
    energy_2d = parse_scalar_table(workdir / "energy_2d.txt") or 0.0
    energy_core = parse_scalar_table(workdir / "energy_core.txt") or 0.0
    energy_gap = parse_scalar_table(workdir / "energy_gap.txt") or 0.0
    B_pk = parse_pos_max_norm(workdir / "Magb.pos") or 0.0

    depth_m = dims.center_leg_d_mm * 1e-3
    L_uH = compute_inductance_uH(
        energy_2d_Jm=energy_2d,
        depth_m=depth_m,
        current_A=float(current_A),
    )
    total_energy_J = energy_2d * depth_m

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
