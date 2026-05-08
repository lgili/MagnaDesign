"""Pydantic models and exceptions for the FEA validation flow."""

from __future__ import annotations

from pydantic import BaseModel


class FEMMNotAvailable(RuntimeError):
    """Raised when no FEMM/xfemm install was detected."""


class FEMMSolveError(RuntimeError):
    """Raised when the external solver fails."""


class FEAValidation(BaseModel):
    """Comparison of analytic vs FEA results.

    Percent errors are signed: ``(FEA - analytic) / analytic * 100``.
    """

    L_FEA_uH: float
    L_analytic_uH: float
    L_pct_error: float

    B_pk_FEA_T: float
    B_pk_analytic_T: float
    B_pct_error: float

    flux_linkage_FEA_Wb: float
    test_current_A: float

    solve_time_s: float
    femm_binary: str
    fem_path: str
    log_excerpt: str = ""
    notes: str = ""

    @property
    def confidence(self) -> str:
        """Coarse confidence label based on the worst error band."""
        worst = max(abs(self.L_pct_error), abs(self.B_pct_error))
        if worst <= 5.0:
            return "high"
        if worst <= 15.0:
            return "medium"
        return "low"
