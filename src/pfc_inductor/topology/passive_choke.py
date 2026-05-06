"""Passive line-frequency choke (no active switch).

A passive PFC choke sits in series with the rectifier input or DC bus and
shapes input current passively. Common topologies:
- AC-side LC: line choke + capacitor across mains. Reduces THD to ~70-80% of
  capacitor-only rectifier.
- DC-side: choke between rectifier and bulk cap (50/60 Hz current shaping).

The inductor sees mostly line-frequency current. Core saturation set by peak
line current. No HF ripple (no switching).
"""
from __future__ import annotations

import math

from pfc_inductor.models import Spec


def line_peak_current_A(spec: Spec, Vin_Vrms: float) -> float:
    P_in = spec.Pout_W / spec.eta
    return math.sqrt(2.0) * P_in / Vin_Vrms


def line_rms_current_A(spec: Spec, Vin_Vrms: float) -> float:
    return spec.Pout_W / (spec.eta * Vin_Vrms)


def required_inductance_uH(spec: Spec, Vin_Vrms: float, target_thd: float = 0.30) -> float:
    """Rough inductance target to achieve given THD on AC-side LC passive PFC.

    Empirical: L ~ Vrms^2 / (Pout * 2*pi*f_line) * k(THD)
    For target_thd=0.3 (30% THD), k ~ 0.3-0.4 (Erickson Ch.18).
    """
    omega_line = 2 * math.pi * spec.f_line_Hz
    Z_base = (Vin_Vrms ** 2) / max(spec.Pout_W / spec.eta, 1.0)
    k = 0.35 * (0.30 / max(target_thd, 0.05))
    L_H = k * Z_base / omega_line
    return L_H * 1e6


def flux_swing_T(N: int, Ipk_A: float, Ae_mm2: float, AL_nH: float, mu_pct: float = 1.0) -> float:
    """Peak flux density at peak line current."""
    L_uH = (N * N * AL_nH * mu_pct) * 1e-3
    L_H = L_uH * 1e-6
    Ae_m2 = Ae_mm2 * 1e-6
    if N == 0 or Ae_m2 == 0:
        return 0.0
    return L_H * Ipk_A / (N * Ae_m2)
