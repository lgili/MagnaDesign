"""Active boost PFC in continuous conduction mode.

Reference: Erickson & Maksimovic, "Fundamentals of Power Electronics" Ch. 18,
and ON Semi AND8016 / Infineon AN_201111_PL52_001.

For ideal PFC with sinusoidal current i_in(t) = I_pk * sin(wt):
    iL(t) = |i_in(t)| (full-wave rectified)
    duty(t) = 1 - vin_inst(t) / Vout = 1 - Vin_pk*|sin(wt)| / Vout
    delta_iL_pp(t) = vin_inst(t) * d(t) / (L * fsw)
                   = Vin_pk*|sin(wt)| * (1 - Vin_pk*|sin(wt)|/Vout) / (L*fsw)

Max ripple occurs when d/dt[delta_iL_pp] = 0, i.e. when vin_inst = Vout/2.
At that point delta_iL_pp_max = Vout / (4 * L * fsw).
"""
from __future__ import annotations

import math

import numpy as np

from pfc_inductor.models import Spec


def line_peak_current_A(spec: Spec, Vin_Vrms: float) -> float:
    """Peak of fundamental line current. I_in_avg_dc = P / (eta*Vrms);
    for sinusoidal, I_pk = sqrt(2)*I_rms = sqrt(2)*P/(eta*Vrms).
    """
    P_in = spec.Pout_W / spec.eta
    return math.sqrt(2.0) * P_in / Vin_Vrms


def line_rms_current_A(spec: Spec, Vin_Vrms: float) -> float:
    return spec.Pout_W / (spec.eta * Vin_Vrms)


def required_inductance_uH(spec: Spec, Vin_Vrms: float) -> float:
    """Inductance needed to keep ripple <= ripple_pct of peak line current.

    Worst-case ripple at vin_inst = Vout/2:
        delta_iL_pp_max = Vout / (4 * L * fsw)
    Set this <= ripple_pct/100 * I_pk:
        L_min = Vout / (4 * fsw * I_pk * ripple_pct/100)
    """
    I_pk = line_peak_current_A(spec, Vin_Vrms)
    delta_max = (spec.ripple_pct / 100.0) * I_pk
    fsw_Hz = spec.f_sw_kHz * 1000.0
    L_H = spec.Vout_V / (4.0 * fsw_Hz * delta_max)
    return L_H * 1e6


def waveforms(
    spec: Spec,
    Vin_Vrms: float,
    L_uH: float,
    n_points_per_half_cycle: int = 200,
) -> dict:
    """Return time-resolved iL(t) over one half line cycle (mains ripple peak).

    Returns dict with t (s), iL_avg (A), delta_iL_pp (A), iL_pk (A).
    The HF ripple is overlaid as triangular envelope; we return the
    peak-to-peak amplitude vs time.
    """
    Vin_pk = math.sqrt(2.0) * Vin_Vrms
    I_pk = line_peak_current_A(spec, Vin_Vrms)
    fsw_Hz = spec.f_sw_kHz * 1000.0
    L_H = L_uH * 1e-6
    half_period = 1.0 / (2.0 * spec.f_line_Hz)

    t = np.linspace(0.0, half_period, n_points_per_half_cycle)
    omega = 2 * math.pi * spec.f_line_Hz
    sin_term = np.abs(np.sin(omega * t))

    iL_avg = I_pk * sin_term
    vin_inst = Vin_pk * sin_term
    duty = np.where(vin_inst < spec.Vout_V, 1.0 - vin_inst / spec.Vout_V, 0.0)
    delta_iL = vin_inst * duty / (L_H * fsw_Hz)

    iL_pk = iL_avg + delta_iL / 2.0
    iL_min = iL_avg - delta_iL / 2.0

    return {
        "t_s": t,
        "iL_avg_A": iL_avg,
        "delta_iL_pp_A": delta_iL,
        "iL_pk_A": iL_pk,
        "iL_min_A": iL_min,
        "vin_inst_V": vin_inst,
        "duty": duty,
    }


def rms_inductor_current_A(wf: dict) -> float:
    """Total RMS of iL = sqrt(I_avg_rms^2 + I_ripple_rms^2).

    I_avg over half cycle: |I_pk * sin(wt)| has RMS = I_pk/sqrt(2).
    I_ripple at fsw is triangular with peak-to-peak delta(t); its RMS
    contribution is delta(t)^2/12 averaged over the line cycle.
    """
    iL_avg = wf["iL_avg_A"]
    delta = wf["delta_iL_pp_A"]
    I_avg_rms_sq = float(np.mean(iL_avg ** 2))
    I_rip_rms_sq = float(np.mean(delta ** 2 / 12.0))
    return math.sqrt(I_avg_rms_sq + I_rip_rms_sq)


def ripple_avg_pp_A(wf: dict) -> float:
    """Average ripple amplitude over the line cycle (used for core loss)."""
    return float(np.mean(wf["delta_iL_pp_A"]))


def ripple_max_pp_A(wf: dict) -> float:
    return float(np.max(wf["delta_iL_pp_A"]))


def peak_inductor_current_A(wf: dict) -> float:
    return float(np.max(wf["iL_pk_A"]))
