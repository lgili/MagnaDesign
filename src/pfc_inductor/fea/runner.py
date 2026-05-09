"""High-level orchestration for FEA validation — picks the right backend."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from pfc_inductor.fea.legacy.femm_geometry import FEAJobInputs, write_lua_script
from pfc_inductor.fea.legacy.femm_postprocess import parse_results_file
from pfc_inductor.fea.legacy.femm_solver import solve_lua
from pfc_inductor.fea.models import FEAValidation, FEMMNotAvailable
from pfc_inductor.fea.probe import (
    is_femm_available,
    select_backend_for_shape,
)
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.visual.core_3d import infer_shape


def validate_design(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    output_dir: Optional[Path] = None,
    keep_files: bool = False,
    timeout_s: int = 120,
) -> FEAValidation:
    """Dispatch to the best backend for this design's core shape.

    Toroid → prefers FEMM (native axisymmetric, high fidelity).
    EE/ETD/PQ → prefers FEMMT (exact mapping).
    Automatic fallback when the preferred backend is not installed.

    High-N override
    ---------------
    FEMMT models each winding turn as a separate gmsh curve loop;
    designs above ~150 turns are out of FEMMT's comfortable
    geometric range. For toroids we transparently re-dispatch to
    the legacy FEMM backend (which represents the winding as a
    bulk-current region — no geometric cost from N). This means a
    typical 121-turn high-AL Kool-Mu / High-Flux design no longer
    surfaces the "FEA skipped: N exceeds gmsh ceiling" error: the
    user gets a result, just from a different backend.
    """
    shape = infer_shape(core)
    backend = select_backend_for_shape(shape)

    # Deferred import — keeps the FEMMT module out of the orchestrator's
    # startup path when only the legacy FEMM backend is needed.
    from pfc_inductor.fea.femmt_runner import _FEMMT_MAX_TURNS_FOR_FEA

    # High-N toroid → re-route to legacy FEMM if available.
    high_N_toroid = (
        backend == "femmt"
        and shape == "toroid"
        and result.N_turns > _FEMMT_MAX_TURNS_FOR_FEA
        and is_femm_available()
    )
    if high_N_toroid:
        return _validate_design_femm(
            spec,
            core,
            wire,
            material,
            result,
            output_dir=output_dir,
            timeout_s=timeout_s,
        )

    if backend == "femmt":
        from pfc_inductor.fea.femmt_runner import validate_design_femmt

        return validate_design_femmt(
            spec,
            core,
            wire,
            material,
            result,
            output_dir=output_dir,
            timeout_s=timeout_s,
        )
    if backend == "femm":
        return _validate_design_femm(
            spec,
            core,
            wire,
            material,
            result,
            output_dir=output_dir,
            timeout_s=timeout_s,
        )
    raise FEMMNotAvailable(
        "No FEA backend available. Install FEMMT "
        "(`pip install pfc-inductor-designer[fea]`) or a FEMM binary."
    )


def _validate_design_femm(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    result: DesignResult,
    output_dir: Optional[Path] = None,
    timeout_s: int = 120,
) -> FEAValidation:
    """Legacy FEMM (Lua + xfemm/femm.exe) path."""
    use_temp = output_dir is None
    if use_temp:
        output_dir = Path(tempfile.mkdtemp(prefix="pfc_fea_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    inputs = FEAJobInputs(
        core=core,
        material=material,
        N_turns=result.N_turns,
        I_pk_A=result.I_line_pk_A,
        output_dir=output_dir,
    )
    write_lua_script(inputs)
    out = solve_lua(
        inputs.lua_path,
        inputs.fem_path,
        inputs.results_path,
        timeout_s=timeout_s,
    )
    raw = parse_results_file(inputs.results_path)

    # Render the |B| heatmap, centerline and histogram from the
    # ``b_field_grid.csv`` the LUA script wrote during the solve.
    # These land in the same working directory as the .fem file
    # so the FEAFieldGallery's recursive PNG scan picks them up
    # automatically — same UX as the FEMMT backend.
    try:
        from pfc_inductor.fea.legacy.grid_renderer import (
            render_legacy_field_pngs,
        )

        render_legacy_field_pngs(output_dir)
    except Exception:  # pragma: no cover — defensive
        pass

    L_FEA_H = float(raw["L_H"])
    L_FEA_uH = L_FEA_H * 1e6
    L_an_uH = result.L_actual_uH
    B_FEA = float(raw["B_pk_T"])
    B_an = result.B_pk_T

    return FEAValidation(
        L_FEA_uH=L_FEA_uH,
        L_analytic_uH=L_an_uH,
        L_pct_error=_pct(L_an_uH, L_FEA_uH),
        B_pk_FEA_T=B_FEA,
        B_pk_analytic_T=B_an,
        B_pct_error=_pct(B_an, B_FEA),
        flux_linkage_FEA_Wb=float(raw["flux_linkage_Wb"]),
        test_current_A=float(raw["I_test_A"]),
        solve_time_s=out.elapsed_s,
        femm_binary=out.binary,
        # ``fem_path`` must point at the *directory* the FEA
        # artefacts live in — the gallery recursively scans it
        # for PNGs (Magb.png, centerline, histogram). Pointing
        # at the .fem file itself made ``Path.is_dir()`` return
        # False and collapsed the gallery to its empty state.
        fem_path=str(inputs.output_dir),
        log_excerpt=(out.stdout or out.stderr)[-400:],
        notes=("Legacy FEMM backend. Static magnetostatic; AC/eddy not modelled in this v1."),
    )


def _pct(reference: float, value: float) -> float:
    if abs(reference) < 1e-12:
        return 0.0
    return (value - reference) / reference * 100.0
