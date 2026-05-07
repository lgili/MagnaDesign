"""Transient analysis driver for cascade Tier 2.

Two complementary simulators ship in Phase B:

- `simulate_to_steady_state` (Step 1) — **imposed-trajectory** form
  that forces `i_L(t) = I_pk · |sin(ω · t)|` and adds HF ripple
  analytically. Sub-millisecond per candidate; the right tool for
  ranking all of Tier 1's survivors.

- `simulate_transient` (Step 2) — **RK4 PWM-resolved ODE** with
  closed-loop current control and a diode clamp. Simulates from
  cold start through several line cycles. Slower (10–100 ms per
  candidate) but covers DCM / BCM, soft-start transients, and
  serves as a sanity check on Step 1 in CCM steady state.

Both produce a `Waveform` with the same shape, so post-processing
(loss envelope, saturation flag) is identical downstream.

The Tier-2 protocol hooks (`state_derivatives`, `initial_state`)
on each topology adapter are reserved for Step 2's plant equation;
Step 1 does not call them.
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


# ─── Step 2 — RK4 PWM-resolved ODE with closed-loop control ────────


def _default_kp(spec: object, inductor_L_H: float) -> float:
    """Default proportional gain that yields ~f_sw/40 closed-loop bandwidth.

    Plant: di/dt_avg = Kp · V_out · error / L. Time constant
    τ = L / (Kp · V_out). Setting `ω_BW = 2π · f_sw / 40` gives
    a controller fast enough to track the line envelope without
    fighting the PWM ripple.
    """
    f_sw_Hz = float(getattr(spec, "f_sw_kHz", 0.0)) * 1000.0
    V_out = float(getattr(spec, "Vout_V", 0.0))
    if f_sw_Hz <= 0 or V_out <= 0 or inductor_L_H <= 0:
        return 0.05  # generic fallback
    omega_bw = 2.0 * math.pi * f_sw_Hz / 40.0
    return float(np.clip(omega_bw * inductor_L_H / V_out, 1e-3, 1.0))


def simulate_transient(
    model: Tier2ConverterModel,
    inductor: NonlinearInductor,
    *,
    n_line_cycles: int = 5,
    Kp: float | None = None,
    config: SimulationConfig | None = None,
) -> Waveform:
    """RK4 PWM-resolved transient simulation with closed-loop control.

    Solves the actual plant ODE `L(i_L) · di_L/dt = v_in − s · V_out`
    where `s ∈ {0, 1}` is the switch state recovered from a sawtooth
    PWM carrier and the duty `d` comes from a P-controller forcing
    `i_L(t) → I_pk · |sin(ω · t)|` (PFC unity power factor). The
    diode is clamped at `i_L ≥ 0`, so DCM / BCM behaviour emerges
    naturally for under-loaded designs without extra logic.

    Suitable for:

    - **DCM / BCM** topologies where the imposed-trajectory model
      (`simulate_to_steady_state`) is wrong by construction.
    - **Soft-start** / startup transient analysis (current ramps
      from rest).
    - **Sanity check** of the imposed-trajectory result on a known
      CCM design — both must agree on `i_pk`, `B_pk`, `L_avg`
      after the controller has settled.

    Phase B Step 2 ships the boost-CCM path. Other topologies
    raise `NotImplementedError`; their state-space equations land
    when their own `simulate_transient` shim does.

    Parameters
    ----------
    n_line_cycles
        How many line cycles to simulate end-to-end (from cold
        start). 3–5 is enough for the controller to converge in
        the typical PFC bandwidth regime; the trailing cycle is
        the one Tier 2 reports.
    Kp
        Proportional gain of the current controller. If ``None``
        we auto-tune for a closed-loop bandwidth of f_sw / 40
        based on the inductor's at-rest inductance.
    """
    if model.name != "boost_ccm":
        raise NotImplementedError(
            f"simulate_transient: only 'boost_ccm' is implemented yet "
            f"(got {model.name!r}). Other topologies extend this in "
            f"Phase B Step 3.",
        )

    cfg = config or SimulationConfig()
    spec = model.spec

    f_line_Hz = float(spec.f_line_Hz)
    omega_line = 2.0 * math.pi * f_line_Hz
    T_line = 1.0 / max(f_line_Hz, 1e-9)
    f_sw_Hz = float(spec.f_sw_kHz) * 1000.0
    V_out = float(spec.Vout_V)
    V_in_pk = math.sqrt(2.0) * float(spec.Vin_min_Vrms)
    I_pk_des = peak_current_A(spec)

    # Step / cycle bookkeeping — lock to integer step count per cycle
    # so cycle boundaries don't drift over the trace.
    steps_per_cycle = max(cfg.steps_per_switching_period, 8) * max(
        int(round(f_sw_Hz / max(f_line_Hz, 1e-9))), 1,
    )
    dt = T_line / steps_per_cycle
    n_steps = steps_per_cycle * n_line_cycles

    if Kp is None:
        Kp = _default_kp(spec, inductor.L_H(0.0))

    t_buf = np.empty(n_steps + 1, dtype=float)
    i_buf = np.empty(n_steps + 1, dtype=float)
    t_buf[0] = 0.0
    i_buf[0] = 0.0

    # ── Closed-loop duty cycle (sample-and-hold per PWM period) ──
    # Real PWM controllers latch the duty once per switching cycle —
    # they do not re-sample at every RK4 sub-step. Computing duty
    # inside the RK4 derivative would let the controller "see" its
    # own HF ripple, causing 2-cycle limit cycles around the
    # reference. We hold `duty_latched` over each PWM period and
    # only refresh it when the integer PWM index advances.
    duty_latched = 0.0
    last_pwm_idx = -1

    def derivative(t: float, i_L: float) -> float:
        v_in = V_in_pk * abs(math.sin(omega_line * t))
        carrier = (t * f_sw_Hz) % 1.0
        if carrier < duty_latched:
            v_L = v_in              # switch closed: V_out shorted out
        else:
            v_L = v_in - V_out      # switch open: V_out across L
        L = inductor.L_H(i_L)
        if L <= 1e-15:
            return 0.0
        return v_L / L

    # Per-line-cycle peak tracking.
    i_pk_per_cycle: list[float] = []
    B_pk_per_cycle: list[float] = []
    cycle_i_pk = 0.0
    cycle_B_pk = 0.0
    samples_in_cycle = 0
    converged = False

    i_L = 0.0
    for k in range(n_steps):
        t = t_buf[k]
        # Refresh the latched duty at every new PWM period. We use
        # the integer-floored carrier index, which is monotonic in
        # `t` regardless of float wraparound noise.
        pwm_idx = int(t * f_sw_Hz)
        if pwm_idx != last_pwm_idx:
            v_in_pwm = V_in_pk * abs(math.sin(omega_line * t))
            i_ref_pwm = I_pk_des * abs(math.sin(omega_line * t))
            if V_out > 0:
                duty_ff = 1.0 - v_in_pwm / V_out
            else:
                duty_ff = 0.0
            if duty_ff < 0.0:
                duty_ff = 0.0
            elif duty_ff > 1.0:
                duty_ff = 1.0
            duty_latched = duty_ff + Kp * (i_ref_pwm - i_L)
            if duty_latched < 0.0:
                duty_latched = 0.0
            elif duty_latched > 1.0:
                duty_latched = 1.0
            last_pwm_idx = pwm_idx

        # Classical RK4 with the latched duty held constant across
        # all four sub-stage evaluations.
        k1 = derivative(t, i_L)
        k2 = derivative(t + 0.5 * dt, i_L + 0.5 * dt * k1)
        k3 = derivative(t + 0.5 * dt, i_L + 0.5 * dt * k2)
        k4 = derivative(t + dt, i_L + dt * k3)
        i_L = i_L + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        # Diode clamp: boost-CCM input diode prevents reverse
        # current. DCM / BCM behaviour emerges naturally — at
        # light load, i_L hits zero mid-PWM cycle.
        if i_L < 0.0:
            i_L = 0.0
        t_buf[k + 1] = t + dt
        i_buf[k + 1] = i_L
        cycle_i_pk = max(cycle_i_pk, i_L)
        cycle_B_pk = max(cycle_B_pk, abs(inductor.B_T(i_L)))
        samples_in_cycle += 1
        if samples_in_cycle >= steps_per_cycle:
            i_pk_per_cycle.append(cycle_i_pk)
            B_pk_per_cycle.append(cycle_B_pk)
            cycle_i_pk = 0.0
            cycle_B_pk = 0.0
            samples_in_cycle = 0
            if len(i_pk_per_cycle) >= cfg.steady_state_window:
                window = np.asarray(i_pk_per_cycle[-cfg.steady_state_window:])
                spread = (window.max() - window.min()) / max(window.max(), 1e-12)
                if spread <= cfg.rel_tol:
                    converged = True

    B_arr = inductor.B_T_array(i_buf)

    return Waveform(
        t_s=t_buf,
        i_L_A=i_buf,
        B_T=B_arr,
        f_line_Hz=f_line_Hz,
        cycle_stats=CycleStats(
            i_pk_per_cycle_A=np.asarray(i_pk_per_cycle),
            B_pk_per_cycle_T=np.asarray(B_pk_per_cycle),
            converged=converged,
            rel_tol=cfg.rel_tol,
            convergence_window=cfg.steady_state_window,
        ),
    )
