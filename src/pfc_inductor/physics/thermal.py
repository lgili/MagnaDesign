"""Thermal model (natural-convection lumped).

For a wound toroid or bobbin-mounted core in still air:
    delta_T = P_total / (h * A_surface)
with h ~ 10 W/m^2/K typical natural convection plus radiation.

A Magnetics-style empirical formula for toroid temperature rise is:
    delta_T [C] = (P_total [mW] / A_surface [cm^2]) ** 0.833
We use the lumped-h form for transparency.
"""
from __future__ import annotations

import math
from typing import Callable

from pfc_inductor.models import Core

H_NATURAL_CONV = 12.0  # W / (m^2 * K), incl. radiation, still air


def surface_area_m2(core: Core) -> float:
    """Approximate winding+core outer surface area for thermal exchange."""
    if core.OD_mm and core.ID_mm and core.HT_mm:
        OD, ID, HT = core.OD_mm * 1e-3, core.ID_mm * 1e-3, core.HT_mm * 1e-3
        # Toroid wound surface ~ outer cylinder + inner cylinder + 2 disks
        A_outer = math.pi * OD * HT
        A_inner = math.pi * ID * HT
        A_disks = 2.0 * (math.pi / 4.0) * (OD ** 2 - ID ** 2)
        return A_outer + A_inner + A_disks
    Ve_m3 = core.Ve_mm3 * 1e-9
    side = Ve_m3 ** (1.0 / 3.0) * 1.5
    return 6.0 * side * side


def delta_T_C(P_total_W: float, A_m2: float, h: float = H_NATURAL_CONV) -> float:
    if A_m2 <= 0:
        return 0.0
    return P_total_W / (h * A_m2)


T_HARD_MAX_C = 300.0  # physical sanity ceiling: copper enamel fails ~200C, this is post-failure


def converge_temperature(
    P_loss_at_T: Callable[[float], float],
    A_m2: float,
    T_amb_C: float,
    T_init_C: float = 60.0,
    max_iter: int = 30,
    tol_K: float = 0.5,
    relax: float = 0.5,
    h: float = H_NATURAL_CONV,
    T_max_C: float = T_HARD_MAX_C,
) -> tuple[float, bool, list[tuple[float, float]]]:
    """Iterate T -> P_loss(T) -> deltaT -> T until convergence.

    P_loss_at_T : callable(T_C) -> P_total_W. (Captures Rdc(T) etc.)
    Bounded: hard-clamp temperature each iteration to T_max_C so that runaway
    designs (saturated core, undersized wire) report a finite (large) T rather
    than diverging — the warning system surfaces the issue to the user.

    Returns (T_winding_C, converged, trace).
    """
    T = T_init_C
    trace: list[tuple[float, float]] = []
    for _ in range(max_iter):
        T_eval = min(T, T_max_C)
        P = P_loss_at_T(T_eval)
        T_new = T_amb_C + delta_T_C(P, A_m2, h=h)
        T_new = min(T_new, T_max_C)
        trace.append((T_eval, P))
        if abs(T_new - T) < tol_K:
            return T_new, True, trace
        T = T + relax * (T_new - T)
        T = min(T, T_max_C)
    return T, False, trace
