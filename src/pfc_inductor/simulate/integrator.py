"""Transient analysis driver for cascade Tier 2.

Phase B Step 1 ships an **imposed-trajectory** simulator: for PFC
topologies in steady state, the controller forces the inductor
current to track the rectified line envelope, so the line-frequency
shape `i_L(t) = I_pk · |sin(ω · t)|` is given rather than computed
from a plant ODE. We then compute `B(t)` and the HF ripple envelope
using the **non-linear inductance at every instantaneous current**,
which is what the analytical engine cannot do: Tier 1 evaluates the
rolloff at one operating point (the line-cycle peak), so any
material whose μ varies significantly across the cycle is
under-served by Tier 1.

This catches three things Tier 1 misses:

1. Cycle-averaged L differs from peak-bias L when the rolloff is
   strong (powder cores at high bias).
2. HF ripple-corrected peak flux density `B_pk + ΔB_PP/2` may exceed
   the saturation margin even when the line-envelope `B_pk` does
   not.
3. True peak inductor current with HF ripple included.

A full PWM-resolved ODE driver (state_derivatives + RK4) is reserved
for Phase B Step 2, where it earns its keep on DCM / BCM / transient
startup scenarios that the imposed-trajectory model cannot cover.
The Tier-2 protocol hooks (`state_derivatives`, `initial_state`)
are kept on the boost-CCM model for that future use.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from pfc_inductor.optimize.feasibility import peak_current_A
from pfc_inductor.simulate.nonlinear_inductor import NonlinearInductor
from pfc_inductor.simulate.waveform import CycleStats, Waveform

if TYPE_CHECKING:
    from pfc_inductor.topology.protocol import Tier2ConverterModel


@dataclass(frozen=True)
class SimulationConfig:
    """Knobs for `simulate_to_steady_state`. Defaults are sane for boost-CCM PFC."""

    max_line_cycles: int = 6
    """Hard cap on simulated line cycles (run terminates when reached)."""

    steady_state_window: int = 3
    """Number of trailing line cycles whose peaks must agree."""

    rel_tol: float = 5e-3
    """Relative spread of peaks across `steady_state_window` for convergence."""

    steps_per_switching_period: int = 20
    """RK4 step count per PWM cycle. 20 resolves rising/falling edges plus
    enough mid-period detail to catch ripple peaks accurately."""

    samples_per_line_cycle_minimum: int = 200
    """Floor for output sample rate; ensures even line-only models look smooth."""


def simulate_to_steady_state(
    model: Tier2ConverterModel,
    inductor: NonlinearInductor,
    *,
    config: SimulationConfig | None = None,
) -> Waveform:
    """Steady-state imposed-trajectory simulation for PFC topologies.

    For boost-CCM and other current-controlled PFC front-ends, the
    inductor's line-frequency current is dictated by the regulator,
    not by the open-loop plant equation. We impose the rectified-
    sinusoid envelope `i_L(t) = I_pk · |sin(ω · t)|` and add the
    HF ripple analytically on top. The non-linear inductance is
    evaluated at every instantaneous current, which is the entire
    point of running Tier 2 over Tier 1.

    Returns a `Waveform` whose `cycle_stats.converged` is always
    True (no integration error to converge) and whose `i_L_A` /
    `B_T` arrays already include HF ripple at each line-cycle
    sample.

    Phase B Step 2 will swap this for an RK4 ODE driver in the
    cases where the imposed-trajectory assumption fails (DCM, BCM,
    transient startup). The Tier-2 protocol hook
    `state_derivatives` is already implemented on the boost-CCM
    model in anticipation.
    """
    cfg = config or SimulationConfig()

    spec = model.spec
    f_line_Hz = float(spec.f_line_Hz)
    T_line = 1.0 / max(f_line_Hz, 1e-9)
    omega = 2.0 * math.pi * f_line_Hz

    # ── Line-frequency envelope ────────────────────────────────
    # We sample one full line cycle. The imposed trajectory is
    # already in steady state by construction, so multiple cycles
    # would be redundant for Tier 2 metrics.
    n_samples = max(cfg.samples_per_line_cycle_minimum, 200)
    t = np.linspace(0.0, T_line, n_samples)
    I_pk_line = peak_current_A(spec)
    i_L_line = I_pk_line * np.abs(np.sin(omega * t))

    # ── HF ripple envelope (boost-CCM at switching frequency) ──
    # During the switch-ON portion of each PWM cycle, di_L/dt =
    # v_in / L(i_L). The peak-to-peak ripple over one PWM period
    # is ΔI_PP = (v_in · d · T_sw) / L(i_L), evaluated locally at
    # each line-cycle sample.
    f_sw_Hz = float(getattr(spec, "f_sw_kHz", 0.0)) * 1000.0
    V_in_pk = math.sqrt(2.0) * float(spec.Vin_min_Vrms)
    V_out = float(getattr(spec, "Vout_V", 0.0))
    if f_sw_Hz > 0 and V_out > 0:
        v_in_inst = V_in_pk * np.abs(np.sin(omega * t))
        # Steady-state CCM duty: d = 1 - v_in/V_out.
        duty = np.clip(1.0 - v_in_inst / V_out, 0.0, 1.0)
        T_sw = 1.0 / f_sw_Hz
        L_inst = inductor.L_H_array(i_L_line)
        delta_I_pp = v_in_inst * duty * T_sw / np.maximum(L_inst, 1e-15)
        # Apply the upper edge of the HF ripple — it's the peak
        # current the engineer actually has to design for.
        i_L_with_ripple = i_L_line + 0.5 * delta_I_pp
    else:
        # Line-frequency-only model: no PWM ripple to add.
        i_L_with_ripple = i_L_line

    # ── B(t) at the ripple peak — this is what saturation cares about ──
    B_T = inductor.B_T_array(i_L_with_ripple)

    # ── Per-cycle metadata for Waveform compat. We have one cycle. ──
    i_pk_cycle = float(np.max(np.abs(i_L_with_ripple)))
    B_pk_cycle = float(np.max(np.abs(B_T)))

    return Waveform(
        t_s=t,
        i_L_A=i_L_with_ripple,
        B_T=B_T,
        f_line_Hz=f_line_Hz,
        cycle_stats=CycleStats(
            i_pk_per_cycle_A=np.array([i_pk_cycle]),
            B_pk_per_cycle_T=np.array([B_pk_cycle]),
            converged=True,
            rel_tol=cfg.rel_tol,
            convergence_window=cfg.steady_state_window,
        ),
    )
