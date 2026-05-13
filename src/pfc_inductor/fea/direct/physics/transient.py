"""Time-domain transient solver — Phase 4.1.

For a single inductor driven by a voltage waveform v(t), the
governing equation is:

::

    v(t) = R · i(t) + L(I) · di/dt

where ``L(I)`` is the inductance at the operating current (the
saturation curve). This module solves it numerically using
explicit RK4 stepping on a configurable time grid.

Why analytical and not FEM-transient: a full transient FEM solve
(GetDP's TimeLoopTheta) for a 10 kHz switching cycle takes 30+
seconds per cycle — too slow for cascade Tier 3. The analytical
ODE solve runs in microseconds and captures the dominant physics
(L(I) saturation knee, R·I voltage drop) that drive the design's
peak current and ripple. Phase 4.x stretch (3-D + transient FEM)
will replace this for high-accuracy validation only.

Acceptance: matches ``L·di/dt = V`` to 3 % for a square-wave drive
on a known inductor (Phase 4.1 OpenSpec target).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class TransientOutputs:
    """Solution of the i(t) ODE on the requested time grid."""

    t_s: list[float]
    """Time points (s)."""

    i_A: list[float]
    """Current at each time point (A)."""

    v_drive_V: list[float]
    """Driving voltage at each time point (V)."""

    L_inst_uH: list[float]
    """Instantaneous L(I) at each time point (μH)."""

    i_pk_A: float
    """Peak |i(t)| over the simulated interval."""

    i_ripple_pkpk_A: float
    """Peak-to-peak ripple after the first half-cycle (steady state
    approximation)."""

    n_steps: int = field(default=0)
    method: str = "rk4_analytical"


def _L_at_current_uH(
    *,
    L_dc_uH: float,
    i_A: float,
    Bsat_T: float,
    Ae_mm2: float,
    n_turns: int,
    knee_sharpness: float = 5.0,
) -> float:
    """Saturation-aware L(I) via the soft tanh knee.

    Same formula the analytical engine uses (``physics/rolloff.py``):

    ::

        B_lin(I) = L_dc · I / (N · Ae)
        L(I) = L_dc / (1 + (B_lin/Bsat)^N)
    """
    if Ae_mm2 <= 0 or n_turns <= 0 or Bsat_T <= 0:
        return L_dc_uH
    L_dc_H = L_dc_uH * 1e-6
    Ae_m2 = Ae_mm2 * 1e-6
    B_lin = L_dc_H * abs(i_A) / (n_turns * Ae_m2)
    knee = 1.0 / (1.0 + (B_lin / Bsat_T) ** knee_sharpness)
    return L_dc_uH * knee


def simulate_transient(
    *,
    v_drive: Callable[[float], float],
    L_dc_uH: float,
    R_dc_Ohm: float,
    Bsat_T: float,
    Ae_mm2: float,
    n_turns: int,
    t_end_s: float,
    dt_s: Optional[float] = None,
    i_init_A: float = 0.0,
) -> TransientOutputs:
    """RK4-step the inductor ODE ``v = R·i + L(i)·di/dt``.

    Parameters
    ----------
    v_drive:
        Callable returning the driving voltage at time t. Typical
        usage: ``lambda t: Vbus if math.fmod(t, T_sw) < T_sw*D else 0``
        for a boost-PFC switching waveform.
    L_dc_uH, R_dc_Ohm:
        Small-signal inductance and DC resistance.
    Bsat_T, Ae_mm2, n_turns:
        Core saturation knee + geometry for L(I).
    t_end_s, dt_s:
        Simulation horizon and timestep. When ``dt_s`` is None we
        use ``t_end / 1000`` (1000 sample points).
    i_init_A:
        Initial current (default 0, cold start).
    """
    if dt_s is None:
        dt_s = t_end_s / 1000.0
    if dt_s <= 0:
        raise ValueError("dt_s must be positive")
    if t_end_s <= 0:
        raise ValueError("t_end_s must be positive")

    def dI_dt(t: float, i: float) -> float:
        v = v_drive(t)
        L_uH = _L_at_current_uH(
            L_dc_uH=L_dc_uH, i_A=i, Bsat_T=Bsat_T, Ae_mm2=Ae_mm2, n_turns=n_turns
        )
        L_H = max(L_uH * 1e-6, 1e-12)
        return (v - R_dc_Ohm * i) / L_H

    t_list = [0.0]
    i_list = [i_init_A]
    v_list = [v_drive(0.0)]
    L_list = [
        _L_at_current_uH(
            L_dc_uH=L_dc_uH, i_A=i_init_A, Bsat_T=Bsat_T, Ae_mm2=Ae_mm2, n_turns=n_turns
        )
    ]

    t = 0.0
    i = i_init_A
    n_steps = math.ceil(t_end_s / dt_s)
    for _ in range(n_steps):
        # RK4
        k1 = dI_dt(t, i)
        k2 = dI_dt(t + dt_s / 2, i + dt_s * k1 / 2)
        k3 = dI_dt(t + dt_s / 2, i + dt_s * k2 / 2)
        k4 = dI_dt(t + dt_s, i + dt_s * k3)
        i = i + (dt_s / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
        t = t + dt_s
        t_list.append(t)
        i_list.append(i)
        v_list.append(v_drive(t))
        L_list.append(
            _L_at_current_uH(L_dc_uH=L_dc_uH, i_A=i, Bsat_T=Bsat_T, Ae_mm2=Ae_mm2, n_turns=n_turns)
        )

    i_pk = max(abs(v) for v in i_list)
    # Ripple from second half (skip initial transient)
    half = len(i_list) // 2
    i_ripple = max(i_list[half:]) - min(i_list[half:])

    return TransientOutputs(
        t_s=t_list,
        i_A=i_list,
        v_drive_V=v_list,
        L_inst_uH=L_list,
        i_pk_A=i_pk,
        i_ripple_pkpk_A=i_ripple,
        n_steps=n_steps,
    )


def square_wave_drive(
    *, V_high: float, V_low: float, period_s: float, duty: float = 0.5
) -> Callable[[float], float]:
    """Convenience: return a v(t) for a square-wave drive.

    Useful for benchmarking against ``L · di/dt = V`` on the
    classic step-input case (set V_low = 0).
    """

    def _v(t: float) -> float:
        phase = math.fmod(t, period_s)
        return V_high if phase < period_s * duty else V_low

    return _v


__all__ = [
    "TransientOutputs",
    "simulate_transient",
    "square_wave_drive",
]
