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
    """Steady-state imposed-trajectory simulator (topology-aware).

    The trajectory shape is dictated by the topology:

    - **boost_ccm** — rectified sinusoid `I_pk · |sin(ω · t)|` with
      analytical HF ripple `ΔI_PP = v_in · d · T_sw / L(i_L)` added
      at each line-cycle sample. The PFC controller forces this
      shape in steady state.
    - **passive_choke** — bidirectional AC sinusoid; no PWM, no
      ripple. The line voltage and load impedance fix the current
      shape.
    - **line_reactor** — the diode-bridge-aware waveform from
      ``topology.line_reactor.line_current_waveform`` (handles 1φ
      and 3φ cases natively, including commutation overlap).

    For passive topologies Step 1 IS the answer — there's no
    PWM-driven HF ripple to capture and no controller transient to
    settle. The `simulate_transient` driver (Step 2) for these
    topologies just delegates back to this function.
    """
    cfg = config or SimulationConfig()
    if model.name == "boost_ccm":
        return _simulate_boost_ccm_imposed(model, inductor, cfg)
    if model.name == "passive_choke":
        return _simulate_passive_choke_imposed(model, inductor, cfg)
    if model.name == "line_reactor":
        return _simulate_line_reactor_imposed(model, inductor, cfg)
    raise NotImplementedError(
        f"simulate_to_steady_state: no imposed-trajectory implementation "
        f"for topology {model.name!r}",
    )


def _simulate_boost_ccm_imposed(
    model: Tier2ConverterModel,
    inductor: NonlinearInductor,
    cfg: SimulationConfig,
) -> Waveform:
    spec = model.spec
    f_line_Hz = float(spec.f_line_Hz)
    T_line = 1.0 / max(f_line_Hz, 1e-9)
    omega = 2.0 * math.pi * f_line_Hz

    n_samples = max(cfg.samples_per_line_cycle_minimum, 200)
    t = np.linspace(0.0, T_line, n_samples)
    I_pk_line = peak_current_A(spec)
    i_L_line = I_pk_line * np.abs(np.sin(omega * t))

    # HF ripple from PFC PWM at f_sw.
    f_sw_Hz = float(spec.f_sw_kHz) * 1000.0
    V_in_pk = math.sqrt(2.0) * float(spec.Vin_min_Vrms)
    V_out = float(spec.Vout_V)
    if f_sw_Hz > 0 and V_out > 0:
        v_in_inst = V_in_pk * np.abs(np.sin(omega * t))
        duty = np.clip(1.0 - v_in_inst / V_out, 0.0, 1.0)
        T_sw = 1.0 / f_sw_Hz
        L_inst = inductor.L_H_array(i_L_line)
        delta_I_pp = v_in_inst * duty * T_sw / np.maximum(L_inst, 1e-15)
        i_L_with_ripple = i_L_line + 0.5 * delta_I_pp
    else:
        i_L_with_ripple = i_L_line

    return _waveform_from_trace(t, i_L_with_ripple, inductor, f_line_Hz, cfg)


def _simulate_passive_choke_imposed(
    model: Tier2ConverterModel,
    inductor: NonlinearInductor,
    cfg: SimulationConfig,
) -> Waveform:
    """Bidirectional AC sinusoid; no PWM ripple."""
    spec = model.spec
    f_line_Hz = float(spec.f_line_Hz)
    T_line = 1.0 / max(f_line_Hz, 1e-9)
    omega = 2.0 * math.pi * f_line_Hz

    n_samples = max(cfg.samples_per_line_cycle_minimum, 200)
    t = np.linspace(0.0, T_line, n_samples)
    # `peak_current_A` for passive_choke returns the line peak from the
    # spec's Pout_W and Vin_min_Vrms (worst case for sizing).
    I_pk = peak_current_A(spec)
    i_L = I_pk * np.sin(omega * t)
    return _waveform_from_trace(t, i_L, inductor, f_line_Hz, cfg)


def _simulate_line_reactor_imposed(
    model: Tier2ConverterModel,
    inductor: NonlinearInductor,
    cfg: SimulationConfig,
) -> Waveform:
    """Reuse the existing diode-bridge-aware waveform generator."""
    # Local import — `topology.line_reactor` pulls in `physics`, so
    # importing it lazily keeps `simulate.integrator` cheap.
    from pfc_inductor.topology import line_reactor as lr

    spec = model.spec
    f_line_Hz = float(spec.f_line_Hz)
    n_samples = max(cfg.samples_per_line_cycle_minimum, 200)
    L_actual_mH = inductor.L_uH(0.0) / 1000.0
    t, i_L = lr.line_current_waveform(
        spec, L_actual_mH, n_cycles=1, n_points=n_samples,
    )
    return _waveform_from_trace(t, i_L, inductor, f_line_Hz, cfg)


def _waveform_from_trace(
    t: np.ndarray,
    i_L: np.ndarray,
    inductor: NonlinearInductor,
    f_line_Hz: float,
    cfg: SimulationConfig,
) -> Waveform:
    """Wrap a sampled (t, i_L) trace into a `Waveform` with B(t)
    and cycle stats. Single-cycle, always converged by construction
    — the imposed trajectory has no integration error to settle."""
    B_T = inductor.B_T_array(i_L)
    i_pk_cycle = float(np.max(np.abs(i_L))) if i_L.size > 0 else 0.0
    B_pk_cycle = float(np.max(np.abs(B_T))) if B_T.size > 0 else 0.0
    return Waveform(
        t_s=t, i_L_A=i_L, B_T=B_T, f_line_Hz=f_line_Hz,
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
    cfg = config or SimulationConfig()

    # ── Topology dispatch ───────────────────────────────────────
    # For passive topologies the imposed-trajectory simulator IS
    # the steady-state answer — no PWM ripple to capture, no
    # controller transient to settle, no DCM to detect. Calling
    # `simulate_transient` on them just hands back to Step 1 so
    # the same `cascade.tier2.evaluate_candidate` flow works for
    # every topology without orchestrator-level branching.
    if model.name in ("passive_choke", "line_reactor"):
        return simulate_to_steady_state(model, inductor, config=cfg)

    if model.name != "boost_ccm":
        raise NotImplementedError(
            f"simulate_transient: no transient driver for topology "
            f"{model.name!r}. Add one to `simulate.integrator` and "
            f"register in this dispatch.",
        )
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
