"""Core loss model.

Anchored Steinmetz baseline:
    Pv [mW/cm^3] = Pv_ref * (f/f_ref)^alpha * (B/B_ref)^beta

For PFC inductors the flux waveform has two superimposed components:
- LINE-FREQUENCY ENVELOPE (full-wave rectified at 2*f_line). Dropped for
  powder cores and ferrites at f_line << f_min_kHz — extrapolating Steinmetz
  outside its validated range gives garbage.
- HIGH-FREQUENCY RIPPLE at f_sw with PEAK-TO-PEAK amplitude that varies
  along the line cycle (max near vin = Vout/2 for boost CCM, ~zero at line
  zero crossings).

iGSE for the ripple term:
We sample ΔB_pp(t) along the line cycle and time-average <Pv(t)> with
Steinmetz applied LOCALLY at each phase. Because Pv ~ ΔB^β with β ≈ 2.0–2.7,
<ΔB(t)^β> >> <ΔB(t)>^β by a factor that can reach 1.5–2× for PFC waveforms.
A naïve Steinmetz with ΔB_avg under-predicts loss; iGSE corrects it without
needing any closed-form triangular wave constants.

Reference: J. Mühlethaler et al., "Improved core-loss calculation for
magnetic components employed in power electronic systems," IEEE TPE, 2012.
"""
from __future__ import annotations

import numpy as np

from pfc_inductor.models import Material


def steinmetz_volumetric_mWcm3(
    material: Material, f_kHz: float, B_pk_mT: float
) -> float:
    """Pv [mW/cm^3] anchored at (f_ref, B_ref, Pv_ref)."""
    s = material.steinmetz
    if f_kHz < s.f_min_kHz:
        return 0.0
    f = max(f_kHz, 1e-3)
    B = max(B_pk_mT, 1e-6)
    return s.Pv_ref_mWcm3 * (f / s.f_ref_kHz) ** s.alpha * (B / s.B_ref_mT) ** s.beta


def core_loss_W_sinusoidal(
    material: Material,
    f_kHz: float,
    B_pk_T: float,
    Ve_mm3: float,
) -> float:
    """Total core loss in W given core volume and sinusoidal flux at f, B_pk."""
    Pv_mW_cm3 = steinmetz_volumetric_mWcm3(material, f_kHz, B_pk_T * 1000.0)
    Ve_cm3 = Ve_mm3 * 1e-3
    return Pv_mW_cm3 * Ve_cm3 * 1e-3


def core_loss_W_pfc_ripple_iGSE(
    material: Material,
    f_sw_kHz: float,
    delta_B_pp_T_array,
    Ve_mm3: float,
) -> float:
    """Time-averaged ripple loss over the line cycle (iGSE-style).

    delta_B_pp_T_array : ndarray of ΔB peak-to-peak [T] sampled over half line cycle.
    Local AC peak amplitude per switching cycle = ΔB_pp/2.
    Returns total ripple loss in Watts.
    """
    s = material.steinmetz
    if f_sw_kHz < s.f_min_kHz:
        return 0.0
    f_factor = (f_sw_kHz / s.f_ref_kHz) ** s.alpha
    arr = np.asarray(delta_B_pp_T_array, dtype=float)
    B_pk_mT = np.maximum(arr * 1000.0 / 2.0, 1e-6)
    Pv_per_t = s.Pv_ref_mWcm3 * f_factor * (B_pk_mT / s.B_ref_mT) ** s.beta
    Pv_avg_mW_cm3 = float(np.mean(Pv_per_t))
    Ve_cm3 = Ve_mm3 * 1e-3
    return Pv_avg_mW_cm3 * Ve_cm3 * 1e-3


def core_loss_W_pfc(
    material: Material,
    f_line_Hz: float,
    f_sw_kHz: float,
    B_pk_line_T: float,
    delta_B_ripple_avg_T: float,
    Ve_mm3: float,
    delta_B_pp_T_array=None,
) -> tuple[float, float]:
    """Return (P_line_W, P_ripple_W).

    Line component: only counted if 2*f_line >= material.f_min_kHz.

    Ripple: if `delta_B_pp_T_array` is given (preferred), use iGSE — sample
    Pv(t) along the line cycle and time-average. Otherwise fall back to the
    naïve <ΔB>/2 Steinmetz call.
    """
    f_line_kHz = f_line_Hz * 1e-3
    P_line = core_loss_W_sinusoidal(material, 2 * f_line_kHz, B_pk_line_T, Ve_mm3)
    if delta_B_pp_T_array is not None:
        P_ripple = core_loss_W_pfc_ripple_iGSE(
            material, f_sw_kHz, delta_B_pp_T_array, Ve_mm3
        )
    else:
        B_pk_ripple_T = delta_B_ripple_avg_T / 2.0
        P_ripple = core_loss_W_sinusoidal(material, f_sw_kHz, B_pk_ripple_T, Ve_mm3)
    return P_line, P_ripple
