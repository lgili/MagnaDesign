"""Finite-element validation. FEMMT (Python+ONELAB) preferred; FEMM legacy.

Usage:
    from pfc_inductor.fea import active_backend, validate_design
    if active_backend() != "none":
        result = validate_design(spec, core, wire, material, design_result)
        print(result.L_pct_error, result.B_pct_error)
"""
from pfc_inductor.fea.probe import (
    is_femm_available, is_femmt_available,
    find_femm_binary, femm_version, femmt_version,
    active_backend, select_backend_for_shape, backend_fidelity,
    install_hint,
)
from pfc_inductor.fea.models import (
    FEAValidation, FEMMNotAvailable, FEMMSolveError,
)
from pfc_inductor.fea.runner import validate_design

__all__ = [
    "is_femm_available", "is_femmt_available",
    "find_femm_binary", "femm_version", "femmt_version",
    "active_backend", "select_backend_for_shape", "backend_fidelity",
    "install_hint",
    "FEAValidation", "FEMMNotAvailable", "FEMMSolveError",
    "validate_design",
]
