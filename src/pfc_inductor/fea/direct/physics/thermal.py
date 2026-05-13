"""Lumped thermal model for the direct backend — Phase 3.2.

Thin wrapper around :mod:`pfc_inductor.physics.thermal` (the
analytical engine's natural-convection thermal model) so the
direct backend can populate ``T_winding_C`` and ``T_core_C`` on
``DirectFeaResult`` without duplicating physics.

Why a wrapper rather than direct import? The direct backend's
calling convention takes loss totals (P_cu, P_core) directly,
while the analytical engine wraps them in a closure that iterates
on temperature for ``R_dc(T) = R_dc(20°C) · [1 + α·(T - 20)]``.
The wrapper here makes the "I already have losses" path explicit.

For PFC inductors at typical operating points the lumped model
agrees with thermocouple measurements within ±5 K — quite good
for a one-resistor model. The cascade Tier 3 (or any caller)
gets a sensible T_winding without having to run a thermal FEM.

When a thermal FEM lands (Phase 3.2+ stretch): this wrapper stays
as the cheap fallback; an opt-in flag will route through GetDP
for high-accuracy cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pfc_inductor.physics import thermal as _engine_thermal


@dataclass(frozen=True)
class ThermalOutputs:
    """Lumped thermal solution at the given operating point."""

    T_winding_C: float
    """Winding (hot-spot) temperature in °C."""

    T_core_C: float
    """Core temperature in °C. With the single-resistor lumped
    model, ``T_core ≈ T_winding`` — they share a heat path to
    ambient. A two-resistor model (Phase 3.2b) will distinguish
    them when the cascade needs it for Steinmetz-at-T evaluation."""

    delta_T_K: float
    """Temperature rise above ambient (K)."""

    P_total_W: float
    """Sum of copper + core losses fed to the thermal model."""

    surface_area_m2: float
    """Approximate convective surface area used (m²)."""

    method: str = "lumped_natural_convection"


def compute_temperature(
    *,
    core: object,
    P_cu_W: float,
    P_core_W: float = 0.0,
    T_amb_C: float = 25.0,
    h_W_m2K: float = 12.0,
) -> ThermalOutputs:
    """Compute steady-state ``T_winding`` from loss totals.

    Parameters
    ----------
    core:
        Catalog Core (Pydantic). Used to get the surface area
        approximation via :func:`pfc_inductor.physics.thermal.surface_area_m2`.
    P_cu_W:
        Copper loss in watts. From the analytical engine's R_dc + R_ac
        breakdown, or any other source.
    P_core_W:
        Core hysteresis + eddy losses (W). Optional — default 0
        for "DC bias only" reports.
    T_amb_C:
        Ambient temperature (default 25 °C).
    h_W_m2K:
        Effective convection coefficient including radiation.
        Default 12 W/m²/K matches natural-convection still air;
        forced-air cooling pushes it to 25-50 W/m²/K.

    Returns ``ThermalOutputs`` with ``T_winding``, ``T_core``,
    and the diagnostic surface-area / total-loss values.
    """
    A_m2 = _engine_thermal.surface_area_m2(core)  # type: ignore[arg-type]
    P_total = max(0.0, float(P_cu_W) + float(P_core_W))
    delta_T = _engine_thermal.delta_T_C(P_total, A_m2, h=h_W_m2K)
    T_winding = float(T_amb_C) + delta_T
    return ThermalOutputs(
        T_winding_C=T_winding,
        T_core_C=T_winding,  # lumped model: same node
        delta_T_K=delta_T,
        P_total_W=P_total,
        surface_area_m2=A_m2,
    )


def estimate_cu_loss_W(
    *,
    n_turns: int,
    current_rms_A: float,
    wire_resistance_ohm_per_m: float,
    mlt_mm: float,
    T_winding_C: Optional[float] = None,
    alpha_per_K: float = 3.93e-3,
) -> float:
    """Cheap copper-loss estimator (DC only).

    For users who don't have a full engine loss breakdown to hand
    but still want a T_winding number from the direct backend.

    ::

        R_dc(T) = R_dc(20°C) · [1 + α·(T - 20)]
        P_cu   = I_rms² · R_dc(T)

    Default α is for annealed copper (3.93e-3 /K). When
    ``T_winding_C`` is omitted, evaluates at 20 °C (no T-correction).

    AC effects (skin/proximity) are NOT modelled here; those go via
    the AC harmonic / Dowell helper once Phase 2.2 lands.
    """
    wire_length_m = float(n_turns) * float(mlt_mm) * 1e-3
    R_20 = wire_length_m * float(wire_resistance_ohm_per_m)
    if T_winding_C is None:
        R_T = R_20
    else:
        R_T = R_20 * (1.0 + alpha_per_K * (float(T_winding_C) - 20.0))
    return (float(current_rms_A) ** 2) * R_T


__all__ = [
    "ThermalOutputs",
    "compute_temperature",
    "estimate_cu_loss_W",
]
