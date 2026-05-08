"""Synchronous DC-DC buck (step-down) in continuous conduction mode.

Reference: Erickson & Maksimovic, *Fundamentals of Power Electronics*
Ch. 5–6, and TI Application Report SLVA477 ("Basic Calculation of a
Buck Converter's Power Stage").

The buck inductor sees a fundamentally different waveform from the
PFC chokes the rest of the engine handles:

- **No AC line envelope** — only the high-frequency triangle ripple
  riding on a constant DC average current.
- **Required inductance** comes from
  ``L = Vout · (1 − D) / (ΔI_pp · f_sw)``; the design knob is the
  *ripple ratio* ``r ≡ ΔI_pp / Iout`` (textbook optimum sits around
  0.30, balancing inductor volume against output capacitance).
- **Worst-case ripple** lands at ``Vin_max`` because ``1 − D`` is
  largest there. Saturation peak current uses ``Iout + ΔI_pp / 2``
  with the worst-case ripple.

The module is intentionally light on Pydantic glue: it exposes pure
functions over ``Spec`` so the engine + cascade dispatch sites can
call into it the same way they call into ``boost_ccm``.
"""
from __future__ import annotations

import math

import numpy as np

from pfc_inductor.models import Spec


# ---------------------------------------------------------------------------
# Spec accessors — handle the "DC topology" Vin fields gracefully
# ---------------------------------------------------------------------------

def _vin_min(spec: Spec) -> float:
    """Worst-case low input voltage for current calculations.

    Order of preference: explicit ``Vin_dc_min_V`` if set, else the
    nominal ``Vin_dc_V``, else fall back to the legacy
    ``Vin_min_Vrms`` (treated as DC) so callers that haven't
    migrated their specs keep working.
    """
    return float(
        getattr(spec, "Vin_dc_min_V", None)
        or getattr(spec, "Vin_dc_V", None)
        or getattr(spec, "Vin_min_Vrms", 0.0)
        or 0.0
    )


def _vin_max(spec: Spec) -> float:
    """Worst-case high input voltage for ripple calculations."""
    return float(
        getattr(spec, "Vin_dc_max_V", None)
        or getattr(spec, "Vin_dc_V", None)
        or getattr(spec, "Vin_max_Vrms", 0.0)
        or 0.0
    )


def _vin_nom(spec: Spec) -> float:
    """Nominal input voltage for waveform sampling."""
    return float(
        getattr(spec, "Vin_dc_V", None)
        or _vin_max(spec)
        or _vin_min(spec)
    )


def _ripple_ratio(spec: Spec) -> float:
    """Target ``ΔI_pp / Iout``.

    Reads ``spec.ripple_ratio`` if set; otherwise interprets the
    legacy ``ripple_pct`` (which is *percent of peak line current*
    in boost-CCM semantics) as a percent of ``Iout`` for buck. 30 %
    is the textbook default and matches both interpretations.
    """
    r = getattr(spec, "ripple_ratio", None)
    if r is not None and r > 0:
        return float(r)
    return float(getattr(spec, "ripple_pct", 30.0)) / 100.0


# ---------------------------------------------------------------------------
# Output current
# ---------------------------------------------------------------------------

def output_current_A(spec: Spec) -> float:
    """Average inductor current = output DC current."""
    if spec.Vout_V <= 0:
        return 0.0
    return float(spec.Pout_W) / float(spec.Vout_V)


# ---------------------------------------------------------------------------
# Duty cycle
# ---------------------------------------------------------------------------

def duty_cycle(spec: Spec, Vin: float) -> float:
    """``D = Vout / (Vin · η)`` — CCM volt-seconds balance with η-loss
    lumped into the duty so the engine sees the right Iin.
    """
    if Vin <= 0 or spec.Vout_V <= 0:
        return 0.0
    eta = float(getattr(spec, "eta", 0.97) or 0.97)
    return min(spec.Vout_V / (Vin * max(eta, 0.5)), 0.99)


# ---------------------------------------------------------------------------
# Ripple
# ---------------------------------------------------------------------------

def ripple_pp_at_Vin(spec: Spec, L_uH: float, Vin: float) -> float:
    """Peak-to-peak inductor current ripple at the given ``Vin``.

    ``ΔI_pp = Vout · (1 − D) / (L · f_sw) = Vout · (1 − Vout / (Vin·η))
    / (L · f_sw)``. Worst case is ``Vin_max`` (D smallest, 1 − D
    largest).
    """
    if Vin <= 0 or L_uH <= 0 or spec.Vout_V <= 0:
        return 0.0
    f_sw_Hz = float(spec.f_sw_kHz) * 1e3
    if f_sw_Hz <= 0:
        return 0.0
    L_H = L_uH * 1e-6
    D = duty_cycle(spec, Vin)
    return spec.Vout_V * (1.0 - D) / (L_H * f_sw_Hz)


def worst_case_ripple_pp_A(spec: Spec, L_uH: float) -> float:
    """ΔI_pp at the worst-case operating point (``Vin_max``)."""
    return ripple_pp_at_Vin(spec, L_uH, _vin_max(spec))


# ---------------------------------------------------------------------------
# Required inductance
# ---------------------------------------------------------------------------

def required_inductance_uH(spec: Spec, *,
                           ripple_ratio: float | None = None) -> float:
    """Minimum L to hold ``ΔI_pp ≤ ripple_ratio · Iout`` at ``Vin_max``.

    Worst-case ripple grows with Vin (smaller D → bigger ``1 − D``).
    Solving the ripple equation for L at ``Vin_max``:

        L_min = Vout · (1 − Vout/(Vin_max·η)) / (r · Iout · f_sw)
    """
    Iout = output_current_A(spec)
    Vin_max = _vin_max(spec)
    f_sw_Hz = float(spec.f_sw_kHz) * 1e3
    if Iout <= 0 or Vin_max <= 0 or spec.Vout_V <= 0 or f_sw_Hz <= 0:
        return 0.0
    r = ripple_ratio if ripple_ratio is not None else _ripple_ratio(spec)
    if r <= 0:
        return 0.0
    eta = float(getattr(spec, "eta", 0.97) or 0.97)
    D_min = spec.Vout_V / (Vin_max * max(eta, 0.5))
    L_H = spec.Vout_V * (1.0 - D_min) / (r * Iout * f_sw_Hz)
    return L_H * 1e6


# ---------------------------------------------------------------------------
# Peak / RMS / boundary current
# ---------------------------------------------------------------------------

def peak_inductor_current_A(spec: Spec, L_uH: float | None = None) -> float:
    """Peak inductor current: ``Iout + ΔI_pp / 2`` at worst-case Vin.

    ``L_uH=None`` returns the average current alone (used by the
    feasibility heuristic before L is known). Once L is sized,
    pass it to get the saturation-relevant peak.
    """
    Iout = output_current_A(spec)
    if L_uH is None or L_uH <= 0:
        return Iout
    return Iout + 0.5 * worst_case_ripple_pp_A(spec, L_uH)


def rms_inductor_current_A(spec: Spec, L_uH: float | None = None) -> float:
    """RMS of a triangle ripple riding on a DC level.

    ``I_rms² = Iout² + (ΔI_pp / √12)²`` (closed form for triangle
    on DC). Returns ``Iout`` when L isn't known yet.
    """
    Iout = output_current_A(spec)
    if L_uH is None or L_uH <= 0 or Iout <= 0:
        return Iout
    delta = worst_case_ripple_pp_A(spec, L_uH)
    r = delta / Iout
    return Iout * math.sqrt(1.0 + (r * r) / 12.0)


def ccm_dcm_boundary_A(spec: Spec, L_uH: float) -> float:
    """Output current below which the converter enters DCM.

    DCM begins when ``Iout < ΔI_pp / 2`` (the trough touches zero).
    At constant L this is the largest current at which CCM design
    assumptions break.
    """
    if L_uH <= 0:
        return 0.0
    return 0.5 * worst_case_ripple_pp_A(spec, L_uH)


# ---------------------------------------------------------------------------
# Waveforms
# ---------------------------------------------------------------------------

def waveforms(spec: Spec, L_uH: float, *,
              n_periods: int = 5,
              n_points: int = 600) -> dict:
    """Sample iL(t) over ``n_periods`` switching cycles at ``Vin_nom``.

    Returns a dict with the same shape the boost-CCM module emits so
    the engine's downstream loss code (Steinmetz, Cu loss, etc.)
    works without a topology branch.

    Buck has no line envelope — the full waveform is a triangle on
    a DC level, repeating every ``T_sw``.
    """
    Iout = output_current_A(spec)
    Vin = _vin_nom(spec)
    delta = ripple_pp_at_Vin(spec, L_uH, Vin)
    f_sw_Hz = float(spec.f_sw_kHz) * 1e3
    if f_sw_Hz <= 0:
        f_sw_Hz = 1.0
    T_sw = 1.0 / f_sw_Hz
    D = duty_cycle(spec, Vin)

    t = np.linspace(0.0, n_periods * T_sw, n_points, endpoint=False)
    phase = (t / T_sw) % 1.0  # in [0, 1)
    on = phase < D

    # Triangle: ramp up during D·T_sw from (Iout − ΔI/2) to (Iout + ΔI/2),
    # ramp down during (1 − D)·T_sw symmetrically.
    iL_pk = np.where(
        on,
        Iout - 0.5 * delta + delta * (phase / max(D, 1e-9)),
        Iout + 0.5 * delta - delta * ((phase - D) / max(1.0 - D, 1e-9)),
    )

    # The boost path returns ``iL_avg``, ``delta_iL_pp``, ``iL_pk`` etc.
    # Mirror those keys so the engine's reading code stays unchanged.
    return {
        "t_s": t,
        "iL_avg_A": np.full_like(t, Iout),
        "delta_iL_pp_A": np.full_like(t, delta),
        "iL_pk_A": iL_pk,
        "iL_min_A": iL_pk - delta,
        "vin_inst_V": np.full_like(t, Vin),
        "duty": np.full_like(t, D),
    }


def rms_inductor_current_from_waveform(wf: dict) -> float:
    """Total RMS of iL — closed form for triangle on DC.

    Mirrors the boost-CCM module's signature so the engine code
    that reads ``rms_inductor_current_A(wf)`` keeps working when
    given a buck waveform dict.
    """
    iL_pk = np.asarray(wf["iL_pk_A"])
    if iL_pk.size == 0:
        return 0.0
    # Trapezoidal-rule on iL² over one period — exact for the
    # piecewise-linear ramps and avoids the closed-form's approximations.
    return float(math.sqrt(np.mean(iL_pk * iL_pk)))


def ripple_avg_pp_A(wf: dict) -> float:
    return float(np.mean(wf["delta_iL_pp_A"]))


def ripple_max_pp_A(wf: dict) -> float:
    return float(np.max(wf["delta_iL_pp_A"]))


def peak_inductor_current_from_waveform(wf: dict) -> float:
    return float(np.max(wf["iL_pk_A"]))


# ---------------------------------------------------------------------------
# THD — design-quality metric
# ---------------------------------------------------------------------------

def estimate_thd_pct(spec: Spec) -> float:
    """Buck output is DC. Line-side THD on the input cap is a
    different problem (depends on the input EMI filter, not the
    inductor). Return ``0.0`` so the Análise card's THD tile reads
    "—" the same way it does for any DC-output topology.
    """
    return 0.0
