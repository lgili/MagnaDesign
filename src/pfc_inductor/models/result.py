from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class LossBreakdown(BaseModel):
    P_cu_dc_W: float
    P_cu_ac_W: float
    P_core_line_W: float
    P_core_ripple_W: float

    @property
    def P_cu_total_W(self) -> float:
        return self.P_cu_dc_W + self.P_cu_ac_W

    @property
    def P_core_total_W(self) -> float:
        return self.P_core_line_W + self.P_core_ripple_W

    @property
    def P_total_W(self) -> float:
        return self.P_cu_total_W + self.P_core_total_W


class DesignResult(BaseModel):
    """Full result of a design pass."""

    L_required_uH: float
    L_actual_uH: float
    N_turns: int

    I_line_pk_A: float
    I_line_rms_A: float
    I_ripple_pk_pk_A: float
    I_pk_max_A: float
    I_rms_total_A: float

    H_dc_peak_Oe: float
    mu_pct_at_peak: float

    B_pk_T: float
    B_sat_limit_T: float
    sat_margin_pct: float

    R_dc_ohm: float
    R_ac_ohm: float

    losses: LossBreakdown
    T_rise_C: float
    T_winding_C: float

    Ku_actual: float
    Ku_max: float

    converged: bool
    warnings: list[str]
    notes: str = ""

    waveform_t_s: Optional[list[float]] = None
    waveform_iL_A: Optional[list[float]] = None
    waveform_B_T: Optional[list[float]] = None

    # --- line reactor only ---
    pct_impedance_actual: Optional[float] = None
    voltage_drop_pct: Optional[float] = None
    thd_estimate_pct: Optional[float] = None
    # Active input power (W) used for IEC 61000-3-2 Class D limit
    # back-calc and the compliance plot. Single-phase: V_phase·I·pf;
    # 3-phase: √3·V_LL·I·pf. None for non-line-reactor designs.
    Pi_W: Optional[float] = None

    def is_feasible(self) -> bool:
        return (
            self.converged
            and self.B_pk_T <= self.B_sat_limit_T
            and self.Ku_actual <= self.Ku_max
            and self.T_winding_C <= 130.0
        )
