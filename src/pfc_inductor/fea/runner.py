"""High-level orchestration for FEA validation — picks the right backend."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from pfc_inductor.fea.legacy.femm_geometry import FEAJobInputs, write_lua_script
from pfc_inductor.fea.legacy.femm_postprocess import parse_results_file
from pfc_inductor.fea.legacy.femm_solver import solve_lua
from pfc_inductor.fea.models import FEAValidation, FEMMNotAvailable
from pfc_inductor.fea.probe import select_backend_for_shape
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

    Toroide → prefere FEMM (axissimétrico nativo, alta fidelidade).
    EE/ETD/PQ → prefere FEMMT (mapeamento exato).
    Fallback automático quando o backend preferido não está instalado.
    """
    shape = infer_shape(core)
    backend = select_backend_for_shape(shape)
    if backend == "femmt":
        from pfc_inductor.fea.femmt_runner import validate_design_femmt
        return validate_design_femmt(
            spec, core, wire, material, result,
            output_dir=output_dir, timeout_s=timeout_s,
        )
    if backend == "femm":
        return _validate_design_femm(
            spec, core, wire, material, result,
            output_dir=output_dir, timeout_s=timeout_s,
        )
    raise FEMMNotAvailable(
        "Nenhum backend FEA disponível. Instale FEMMT "
        "(`pip install pfc-inductor-designer[fea]`) ou um binário FEMM."
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
        core=core, material=material,
        N_turns=result.N_turns,
        I_pk_A=result.I_line_pk_A,
        output_dir=output_dir,
    )
    write_lua_script(inputs)
    out = solve_lua(
        inputs.lua_path, inputs.fem_path, inputs.results_path,
        timeout_s=timeout_s,
    )
    raw = parse_results_file(inputs.results_path)

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
        fem_path=str(inputs.fem_path),
        log_excerpt=(out.stdout or out.stderr)[-400:],
        notes=(
            "Backend legado FEMM. Static magnetostatic; AC/eddy não "
            "modelados nesta v1."
        ),
    )


def _pct(reference: float, value: float) -> float:
    if abs(reference) < 1e-12:
        return 0.0
    return (value - reference) / reference * 100.0
