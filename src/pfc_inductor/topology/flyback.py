"""Flyback DC-DC converter — coupled-inductor energy storage.

A flyback is a buck-boost dressed in a 2-winding magnetic — the
"inductor" is actually a transformer with an air gap that stores
energy on the ON half of every cycle and releases it through the
secondary on the OFF half. That makes it categorically different
from every other topology MagnaDesign covers:

- **Two windings** (primary ``Np`` + secondary ``Ns``) on one
  gapped ferrite core. The turns ratio ``n = Np / Ns`` couples
  the input and output voltage spaces.
- **Energy storage drives the design**: ``E = ½·Lp·Ip² ; Pout =
  E·f_sw·η``. The required primary inductance is the textbook
  ``Lp_max = η·Vin_min²·D_max² / (2·Pout·f_sw)``.
- **Operating mode** is a designer choice: DCM (textbook
  starting point — both currents fall to zero each cycle) or
  CCM (continuous primary current; lower peak stress, but a
  RHP zero in the control loop).
- **Reflected voltage** appears on the primary FET when the
  switch turns OFF: ``V_drain = Vin_max + n·Vout +
  V_leakage_spike``. The secondary diode sees ``Vout +
  Vin_max/n``.
- **Leakage inductance** isn't ideal — energy stored in
  ``L_leak`` becomes the snubber's job and 3–8 % of Pout in
  loss budget. Vendor app notes (TI SLUA535, Coilcraft Doc 158,
  Würth ANP034) provide empirical estimates that we model here
  via a per-shape lookup table.

References:
- Erickson & Maksimovic, *Fundamentals of Power Electronics*,
  Ch. 6 (flyback) and Ch. 13 (transformer-isolated topologies).
- TI SLUA535 — flyback transformer design, primary side.
- Würth ANP034 — leakage inductance vs winding strategy.
- Pomilio Cap. 8 — flyback in DCM and CCM, reflected voltages.

The module is intentionally light on Pydantic glue: pure
functions over ``Spec`` so the engine + cascade dispatch sites
can call into it the same way they call into ``boost_ccm``.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

from pfc_inductor.models import Spec
from pfc_inductor.physics.leakage import leakage_estimate_uH

# ---------------------------------------------------------------------------
# Spec accessors — Vin handling shared with buck_ccm (DC-input topology)
# ---------------------------------------------------------------------------


def _vin_min(spec: Spec) -> float:
    """Worst-case low input voltage for current calculations."""
    return float(
        getattr(spec, "Vin_dc_min_V", None)
        or getattr(spec, "Vin_dc_V", None)
        or getattr(spec, "Vin_min_Vrms", 0.0)
        or 0.0
    )


def _vin_max(spec: Spec) -> float:
    """Worst-case high input voltage for FET-stress calculations."""
    return float(
        getattr(spec, "Vin_dc_max_V", None)
        or getattr(spec, "Vin_dc_V", None)
        or getattr(spec, "Vin_max_Vrms", 0.0)
        or 0.0
    )


def _vin_nom(spec: Spec) -> float:
    """Nominal input voltage for waveform sampling."""
    return float(getattr(spec, "Vin_dc_V", None) or _vin_max(spec) or _vin_min(spec))


def _flyback_mode(spec: Spec) -> Literal["dcm", "ccm"]:
    """Read the design-time operating mode from the spec.

    Defaults to ``"dcm"`` because it's the textbook starting
    point and works with every silicon controller on the market.
    CCM gives lower peak currents but introduces a RHP zero in
    the control loop and is opt-in.
    """
    mode = getattr(spec, "flyback_mode", None) or "dcm"
    return "ccm" if mode == "ccm" else "dcm"


def _eta(spec: Spec) -> float:
    """Spec efficiency, clamped to a physically reasonable floor."""
    return max(float(getattr(spec, "eta", 0.85) or 0.85), 0.5)


# ---------------------------------------------------------------------------
# Output current and duty cycle
# ---------------------------------------------------------------------------


def output_current_A(spec: Spec) -> float:
    """Average output (load) current ``Iout = Pout / Vout``."""
    if spec.Vout_V <= 0:
        return 0.0
    return float(spec.Pout_W) / float(spec.Vout_V)


def average_input_current_A(spec: Spec) -> float:
    """Average primary input current at low line and full load.

    ``I_in_avg = Pout / (Vin_min · η)`` — the fundamental
    energy-balance number every flyback design starts from.
    """
    Vin_min = _vin_min(spec)
    if Vin_min <= 0 or spec.Pout_W <= 0:
        return 0.0
    return spec.Pout_W / (Vin_min * _eta(spec))


def ccm_duty_cycle(spec: Spec, n: float, Vin: float | None = None) -> float:
    """CCM volt-seconds balance gives duty: ``D = n·Vout / (Vin + n·Vout)``.

    At low line ``Vin`` is smallest, so D is largest there —
    that's the worst-case operating point for primary RMS and
    for the demag-time check.
    """
    if n <= 0 or spec.Vout_V <= 0:
        return 0.0
    v = Vin if Vin is not None else _vin_min(spec)
    if v <= 0:
        return 0.0
    return min(0.95, n * spec.Vout_V / (v + n * spec.Vout_V))


def dcm_duty_cycle(spec: Spec, Lp_uH: float) -> float:
    """DCM duty at low line: ``D = √(2·Lp·Pout·fsw / (η·Vin_min²))``.

    Solved from the energy-balance: ``½·Lp·Ip_pk² · fsw·η = Pout``
    with ``Ip_pk = Vin·D·Tsw / Lp``.
    """
    Vin_min = _vin_min(spec)
    f_sw_Hz = float(spec.f_sw_kHz) * 1e3
    if Vin_min <= 0 or f_sw_Hz <= 0 or Lp_uH <= 0 or spec.Pout_W <= 0:
        return 0.0
    Lp = Lp_uH * 1e-6
    eta = _eta(spec)
    arg = 2.0 * Lp * spec.Pout_W * f_sw_Hz / (eta * Vin_min * Vin_min)
    arg = max(arg, 0.0)
    return min(0.95, math.sqrt(arg))


def demag_duty(spec: Spec, n: float, D: float, Vin: float | None = None) -> float:
    """Demag duty ``D₂ = D·Vin / (n·Vout)``.

    DCM requires ``D + D₂ < 1``; CCM has ``D + D₂ = 1`` exactly.
    Returns the time fraction of the secondary conduction
    relative to the full switching period.
    """
    if n <= 0 or spec.Vout_V <= 0 or D <= 0:
        return 0.0
    v = Vin if Vin is not None else _vin_min(spec)
    if v <= 0:
        return 0.0
    return D * v / (n * spec.Vout_V)


# ---------------------------------------------------------------------------
# Required primary inductance
# ---------------------------------------------------------------------------


def required_primary_inductance_uH(
    spec: Spec, *, D_max: float = 0.45, mode: Literal["dcm", "ccm"] | None = None
) -> float:
    """Maximum ``Lp`` such that the design stays in the requested mode.

    DCM textbook: ``Lp_max = η · Vin_min² · D_max² / (2·Pout·f_sw)``.
    Picks the largest Lp that still keeps ``D + D₂ < 1`` at low line.

    CCM: the inductance is sized for a target ripple ratio
    ``r = ΔI_p / I_p_avg``. Default ripple is 60 % so the design
    sits well into CCM at full load while degrading to DCM at
    light load (typical modern controller target).

    ``D_max`` lets the caller cap how aggressive the design is
    — higher D_max → lower peak primary current but tighter demag-
    time margin. 0.45 is the textbook safe default for DCM.
    """
    Vin_min = _vin_min(spec)
    f_sw_Hz = float(spec.f_sw_kHz) * 1e3
    if Vin_min <= 0 or f_sw_Hz <= 0 or spec.Pout_W <= 0:
        return 0.0
    eta = _eta(spec)
    actual_mode = mode if mode is not None else _flyback_mode(spec)
    if actual_mode == "ccm":
        # CCM: size for 60 % primary ripple at low line.
        # ΔI_p = Vin · D · Tsw / Lp ;  r = ΔI_p / I_p_avg.
        I_in_avg = average_input_current_A(spec)
        if I_in_avg <= 0:
            return 0.0
        # D from volt-seconds balance using the optimal turns ratio.
        n = optimal_turns_ratio(spec)
        D_ccm = ccm_duty_cycle(spec, n, Vin=Vin_min)
        if D_ccm <= 0:
            return 0.0
        ripple_target = 0.6  # ΔI_p / I_p_avg
        # I_p_avg primary = I_in_avg / D (the primary only conducts
        # during D·T_sw, so the average over one switching period
        # is I_p_avg_during_ON · D = I_in_avg → I_p_avg = I_in/D).
        I_p_avg = I_in_avg / D_ccm
        delta_target = ripple_target * I_p_avg
        Lp_H = Vin_min * D_ccm / (delta_target * f_sw_Hz)
        return Lp_H * 1e6
    # DCM
    Lp_H = eta * Vin_min * Vin_min * D_max * D_max / (2.0 * spec.Pout_W * f_sw_Hz)
    return Lp_H * 1e6


# ---------------------------------------------------------------------------
# Turns ratio
# ---------------------------------------------------------------------------


def optimal_turns_ratio(spec: Spec, *, V_drain_target_V: float = 600.0) -> float:
    """Pick ``n = Np/Ns`` that equalises FET and diode stress.

    Most flyback designers target a primary FET with a 600 V or
    650 V rating (universal 90–264 Vac input → ~375 Vdc bus
    after PFC, leaving headroom for ``n·Vout + V_leak_spike``).
    Solving ``V_drain_target = Vin_max + n·Vout`` for n gives
    the largest turns ratio that keeps the FET inside its SOA.

    User can override via ``spec.turns_ratio_n``; this helper is
    the engine's default when the spec is silent.
    """
    Vin_max = _vin_max(spec)
    if spec.Vout_V <= 0:
        return 5.0  # safe fallback
    n_user = getattr(spec, "turns_ratio_n", None)
    if n_user is not None and n_user > 0:
        return float(n_user)
    headroom = max(V_drain_target_V - Vin_max, spec.Vout_V)
    n = headroom / spec.Vout_V
    return max(0.5, min(15.0, n))


# ---------------------------------------------------------------------------
# Peak / RMS currents
# ---------------------------------------------------------------------------


def primary_peak_current(
    spec: Spec, Lp_uH: float, *, mode: Literal["dcm", "ccm"] | None = None
) -> float:
    """Peak primary current at low line, full load.

    DCM: ``Ip_pk = Vin_min · D · T_sw / Lp`` with D from
    ``dcm_duty_cycle``.

    CCM: ``Ip_pk = I_p_avg + ΔI_p / 2`` where
    ``ΔI_p = Vin·D·Tsw / Lp`` and ``I_p_avg = I_in / D``.
    """
    f_sw_Hz = float(spec.f_sw_kHz) * 1e3
    Vin_min = _vin_min(spec)
    if Lp_uH <= 0 or f_sw_Hz <= 0 or Vin_min <= 0:
        return 0.0
    Lp = Lp_uH * 1e-6
    Tsw = 1.0 / f_sw_Hz
    actual_mode = mode if mode is not None else _flyback_mode(spec)
    if actual_mode == "ccm":
        n = optimal_turns_ratio(spec)
        D = ccm_duty_cycle(spec, n, Vin=Vin_min)
        if D <= 0:
            return 0.0
        I_in_avg = average_input_current_A(spec)
        I_p_avg = I_in_avg / D
        delta = Vin_min * D * Tsw / Lp
        return I_p_avg + 0.5 * delta
    # DCM
    D = dcm_duty_cycle(spec, Lp_uH)
    return Vin_min * D * Tsw / Lp


def primary_rms_current(
    spec: Spec,
    Lp_uH: float,
    Ip_pk: float,
    *,
    mode: Literal["dcm", "ccm"] | None = None,
) -> float:
    """Primary RMS over a full switching period.

    DCM (triangular pulse, zero outside ``D·T_sw``):
        ``I_p_rms = Ip_pk · √(D / 3)``

    CCM (trapezoidal pulse with ripple ratio ``r``):
        ``I_p_rms ≈ I_p_avg · √(D · (1 + r²/12))``
    """
    if Lp_uH <= 0 or Ip_pk <= 0:
        return 0.0
    actual_mode = mode if mode is not None else _flyback_mode(spec)
    if actual_mode == "ccm":
        Vin_min = _vin_min(spec)
        f_sw_Hz = float(spec.f_sw_kHz) * 1e3
        if Vin_min <= 0 or f_sw_Hz <= 0:
            return 0.0
        n = optimal_turns_ratio(spec)
        D = ccm_duty_cycle(spec, n, Vin=Vin_min)
        if D <= 0:
            return 0.0
        I_in_avg = average_input_current_A(spec)
        I_p_avg = I_in_avg / D
        Lp = Lp_uH * 1e-6
        delta = Vin_min * D / (Lp * f_sw_Hz)
        r = delta / max(I_p_avg, 1e-9)
        return I_p_avg * math.sqrt(D * (1.0 + r * r / 12.0))
    # DCM
    D = dcm_duty_cycle(spec, Lp_uH)
    return Ip_pk * math.sqrt(D / 3.0)


def secondary_peak_current(spec: Spec, Ip_pk: float, n: float) -> float:
    """``Is_pk = n · Ip_pk`` — the energy stored in the primary
    leaves through the secondary at the same flux density,
    which means the secondary current is ``n×`` larger to
    move the same charge per cycle."""
    if n <= 0:
        return 0.0
    return n * Ip_pk


def secondary_rms_current(
    spec: Spec,
    Lp_uH: float,
    Ip_pk: float,
    n: float,
    *,
    mode: Literal["dcm", "ccm"] | None = None,
) -> float:
    """Secondary RMS during the demag interval ``D₂``.

    DCM (triangular pulse over D₂):
        ``Is_rms = Is_pk · √(D₂ / 3) = n·Ip_pk · √(D₂ / 3)``

    CCM (trapezoidal over (1−D)):
        ``Is_rms ≈ I_s_avg · √((1−D) · (1 + r²/12))``
    """
    if Lp_uH <= 0 or Ip_pk <= 0 or n <= 0:
        return 0.0
    Is_pk = secondary_peak_current(spec, Ip_pk, n)
    actual_mode = mode if mode is not None else _flyback_mode(spec)
    if actual_mode == "ccm":
        Vin_min = _vin_min(spec)
        D = ccm_duty_cycle(spec, n, Vin=Vin_min)
        D2 = max(1.0 - D, 1e-6)
        # I_s_avg = Iout / D2 (secondary only conducts during D2).
        Iout = output_current_A(spec)
        I_s_avg = Iout / D2 if D2 > 0 else Iout
        # Same r as primary, scaled by n at the secondary.
        f_sw_Hz = float(spec.f_sw_kHz) * 1e3
        Lp = Lp_uH * 1e-6
        if Vin_min <= 0 or f_sw_Hz <= 0:
            return 0.0
        delta_p = Vin_min * D / (Lp * f_sw_Hz)
        I_p_avg = average_input_current_A(spec) / max(D, 1e-9)
        r = delta_p / max(I_p_avg, 1e-9)
        return I_s_avg * math.sqrt(D2 * (1.0 + r * r / 12.0))
    # DCM
    D = dcm_duty_cycle(spec, Lp_uH)
    n_user = optimal_turns_ratio(spec)  # for D2 calc
    D2 = demag_duty(spec, n_user, D)
    return Is_pk * math.sqrt(D2 / 3.0)


# ---------------------------------------------------------------------------
# Reflected voltages — FET drain stress + diode reverse stress
# ---------------------------------------------------------------------------


def reflected_voltages(spec: Spec, n: float, *, V_clamp_factor: float = 1.5) -> tuple[float, float]:
    """Returns ``(V_drain_pk_V, V_diode_pk_V)`` worst-case stress.

    ``V_drain = Vin_max + n·Vout + V_leak_spike``. The leak spike is
    clamped by the RCD snubber to ``V_clamp = α · n·Vout`` with
    ``α ∈ [1.5, 2.5]``; default 1.5 is conservative (more
    snubber loss, smaller FET).

    ``V_diode = Vout + Vin_max / n`` — the secondary diode must
    block this in reverse during the ON interval.
    """
    Vin_max = _vin_max(spec)
    Vout = float(spec.Vout_V)
    if n <= 0 or Vout <= 0:
        return (Vin_max, 0.0)
    V_clamp = V_clamp_factor * n * Vout
    V_drain = Vin_max + n * Vout + V_clamp
    V_diode = Vout + Vin_max / n
    return (V_drain, V_diode)


# ---------------------------------------------------------------------------
# Snubber dissipation (RCD primary clamp)
# ---------------------------------------------------------------------------


def snubber_dissipation_W(
    L_leak_uH: float,
    Ip_pk: float,
    f_sw_kHz: float,
    *,
    V_clamp_factor: float = 1.5,
    n: float = 1.0,
    Vout: float = 5.0,
) -> float:
    """Average power dissipated in the RCD primary snubber.

    ``P_snubber = ½·L_leak·Ip²·fsw · V_clamp / (V_clamp − n·Vout)``

    The expression collapses to a simpler ``½·L_leak·Ip²·fsw``
    when ``V_clamp ≫ n·Vout`` (light snubber load); the
    correction blows up as ``V_clamp → n·Vout`` (snubber asked
    to clamp at exactly the reflected voltage — physically
    invalid, the formula floors at 1.0× with a wide guard).
    """
    if L_leak_uH <= 0 or Ip_pk <= 0 or f_sw_kHz <= 0:
        return 0.0
    L_leak = L_leak_uH * 1e-6
    f_sw_Hz = f_sw_kHz * 1e3
    base = 0.5 * L_leak * Ip_pk * Ip_pk * f_sw_Hz
    if n <= 0 or Vout <= 0:
        return base
    V_clamp = V_clamp_factor * n * Vout
    denom = max(V_clamp - n * Vout, 0.5 * n * Vout)  # floor at half clamp
    factor = V_clamp / denom
    return base * factor


# ---------------------------------------------------------------------------
# Waveforms — primary + secondary current over a few switching periods
# ---------------------------------------------------------------------------


def waveforms(
    spec: Spec,
    Lp_uH: float,
    n: float,
    *,
    mode: Literal["dcm", "ccm"] | None = None,
    n_periods: int = 6,
    n_points: int = 600,
) -> dict:
    """Sample ``Ip(t)`` and ``Is(t)`` over ``n_periods`` switching cycles.

    DCM: Ip ramps 0 → Ip_pk during D·Tsw, drops to 0 (the OFF
    half is the secondary's job), idle until next ON. Is ramps
    Is_pk → 0 during D₂·Tsw, idle otherwise.

    CCM: Ip ramps from a non-zero floor to Ip_pk during D·Tsw,
    drops to floor during (1−D)·Tsw via the secondary path.
    Is mirror-image, scaled by n.

    Returns dict with same shape as the boost/buck waveform
    helpers so the engine's loss code reads it without a
    topology branch.
    """
    actual_mode = mode if mode is not None else _flyback_mode(spec)
    Ip_pk = primary_peak_current(spec, Lp_uH, mode=actual_mode)
    Is_pk = secondary_peak_current(spec, Ip_pk, n)
    f_sw_Hz = float(spec.f_sw_kHz) * 1e3
    if f_sw_Hz <= 0:
        f_sw_Hz = 1.0
    Tsw = 1.0 / f_sw_Hz

    Vin_min = _vin_min(spec)

    if actual_mode == "ccm":
        D = ccm_duty_cycle(spec, n, Vin=Vin_min)
        I_in_avg = average_input_current_A(spec)
        I_p_avg = I_in_avg / max(D, 1e-9)
        Lp = Lp_uH * 1e-6
        delta_p = Vin_min * D * Tsw / Lp if Lp > 0 else 0.0
        Ip_min = max(I_p_avg - 0.5 * delta_p, 0.0)
        D2 = max(1.0 - D, 1e-6)
    else:
        D = dcm_duty_cycle(spec, Lp_uH)
        D2 = demag_duty(spec, n, D)
        Ip_min = 0.0

    t = np.linspace(0.0, n_periods * Tsw, n_points, endpoint=False)
    phase = (t / Tsw) % 1.0  # in [0, 1)

    # Primary ramps up during ON.
    on_mask = phase < D
    on_norm = phase / max(D, 1e-9)
    ip = np.where(on_mask, Ip_min + (Ip_pk - Ip_min) * on_norm, 0.0)
    if actual_mode == "ccm":
        # In CCM the primary "off" phase still has current — but it
        # flows through the secondary, so the primary winding sees
        # zero. The trace shape stays the same as DCM here; the
        # secondary picks up the energy.
        pass

    # Secondary ramps down during demag (off-D2 window).
    off_mask = (phase >= D) & (phase < (D + D2))
    off_norm = (phase - D) / max(D2, 1e-9)
    Is_min = Ip_min * n  # CCM continuity
    is_ = np.where(off_mask, Is_pk - (Is_pk - Is_min) * off_norm, 0.0)

    return {
        "t_s": t,
        "iL_avg_A": np.full_like(t, average_input_current_A(spec)),
        "delta_iL_pp_A": np.full_like(t, Ip_pk - Ip_min),
        "iL_pk_A": ip,
        "iL_min_A": np.where(on_mask, Ip_min, 0.0),
        "is_pk_A": is_,  # secondary trace for the Análise stack
        "vin_inst_V": np.full_like(t, Vin_min),
        "duty": np.full_like(t, D),
        "demag_duty": np.full_like(t, D2),
    }


def rms_inductor_current_from_waveform(wf: dict) -> float:
    """Total RMS of the primary current from the sampled waveform.

    Mirrors the boost/buck signature so the engine's reading
    code stays uniform across topologies.
    """
    ip = np.asarray(wf["iL_pk_A"])
    if ip.size == 0:
        return 0.0
    return float(math.sqrt(np.mean(ip * ip)))


def estimate_thd_pct(spec: Spec) -> float:
    """Flyback runs from a DC bus — no line current, no THD."""
    return 0.0


# ---------------------------------------------------------------------------
# Leakage inductance + snubber — re-exports of the physics helpers
# ---------------------------------------------------------------------------


def leakage_inductance_uH(
    Lp_uH: float,
    *,
    layout: str = "sandwich",
    n_layers: int = 2,
    core_shape: str | None = None,
) -> float:
    """Empirical estimate of primary leakage inductance.

    Defers to ``pfc_inductor.physics.leakage.leakage_estimate_uH``
    for the lookup table + interpolation rule, but keeps the
    public-API surface here so callers don't have to know about
    the physics submodule layout.
    """
    return leakage_estimate_uH(
        Lp_uH,
        layout=layout,
        n_layers=n_layers,
        core_shape=core_shape,
    )
