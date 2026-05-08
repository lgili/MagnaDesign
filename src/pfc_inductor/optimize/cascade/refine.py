"""Cascade-tier refinement — propagate refined L / B / I into losses + temp.

Tier 1 hands the orchestrator a complete `DesignResult` with
analytical losses and an iterated thermal solve. Tier 2 / 3 / 4
each measure something more accurate (transient waveform, FEA
inductance, FEA flux) but **don't recompute losses** — they
just refine the magnetic state. The cascade table then has a
problem: ``loss_t1_W`` reflects Tier-1's B and i_rms, not the
refined values, so a user who runs all the way through Tier 4
sees ranking numbers that don't match the displayed L_t4_uH /
Bpk_t3_T.

This module closes that gap. Given:

- the candidate's Tier-1 :class:`DesignResult` (the analytical
  baseline), and
- one or more *override* values (a refined ``L_actual_uH`` and
  ``B_pk_T`` from FEA, or a refined ``i_rms_total_A`` and
  ``B_pk_T`` from the transient simulator),

:func:`recompute_with_overrides` re-runs the engine's loss +
thermal block with the refined inputs and returns a
:class:`RefinedDesign` carrying the new ``loss_W``, ``temp_C``
and ``T_rise_C``. The caller (:mod:`...orchestrator`) then
writes those into ``loss_t{N}_W`` / ``temp_t{N}_C`` columns so
the Top-N table ranks on the highest-fidelity number available.

No gambiarra
------------

The recompute calls back into the **same waveform-synthesis
modules + physics functions** the engine uses
(``topology.boost_ccm.waveforms``, ``physics.copper`` /
``physics.core_loss``, ``physics.thermal.converge_temperature``).
For the no-op case (no overrides), the function reproduces the
engine's loss + temp exactly to within the tolerance of the
thermal iterator. The override knobs land at the only places
they belong: ``L_actual`` feeds the waveform synthesizer (so
``ΔiL`` and ``ΔB(t)`` reflect the refined inductance), and
``B_pk_T`` pins the line-band Steinmetz peak directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import copper as cp
from pfc_inductor.physics import core_loss as cl
from pfc_inductor.physics import thermal as th
from pfc_inductor.topology import boost_ccm, buck_ccm


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RefinedDesign:
    """Loss + thermal numbers after Tier 2/3/4 refinement.

    All fields are scalar floats so the orchestrator can write
    them straight into SQLite columns without further unpacking.
    """

    loss_W: float
    """Total loss at the converged temperature (W)."""

    temp_C: float
    """Converged winding temperature (°C)."""

    T_rise_C: float
    """``temp_C - spec.T_amb_C``."""

    P_cu_dc_W: float
    P_cu_ac_W: float
    P_core_line_W: float
    P_core_ripple_W: float

    converged: bool
    """``True`` when the thermal solver hit its tolerance band."""

    # Effective inputs (post-override) so the caller can verify
    # that the override actually flowed through.
    L_actual_uH: float
    B_pk_T: float
    I_rms_total_A: float


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def recompute_with_overrides(
    *,
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    base: DesignResult,
    L_actual_uH: Optional[float] = None,
    B_pk_T: Optional[float] = None,
    I_rms_total_A: Optional[float] = None,
    I_rip_rms_A: Optional[float] = None,
    I_pk_max_A: Optional[float] = None,
) -> RefinedDesign:
    """Refine ``base``'s losses + temp using the supplied overrides.

    Every override is optional. Anything left ``None`` falls back
    to ``base``'s value, so a Tier-3 caller that only knows the
    refined ``L_actual_uH`` and ``B_pk_T`` can pass just those two
    and the rest of the loss inputs come from the analytical
    baseline.

    The thermal solve uses the same iterator
    (``converge_temperature``) the engine uses, so the answer is
    **identical to the engine** when no override is supplied —
    important for the no-op case (e.g. Tier 2 ran but L/B didn't
    actually shift).
    """
    L_uH = float(L_actual_uH if L_actual_uH is not None else base.L_actual_uH)
    B_pk = float(B_pk_T if B_pk_T is not None else base.B_pk_T)

    N = max(int(base.N_turns), 1)
    Ae_m2 = core.Ae_mm2 * 1e-6
    Bsat = float(material.Bsat_100C_T)

    # Cap the loss-model B at Bsat (above that the Steinmetz fit
    # is invalid; engine does the same — keeps a finite number).
    B_pk_for_loss = min(B_pk, Bsat)

    # Build the carrier waveform via the same topology module the
    # engine uses, so ``ΔiL_pp(t)`` and the iGSE input array land
    # *exactly* like the engine's path. The override ``L_actual``
    # flows in here — driving a different ripple amplitude when
    # Tier 3 / 4 reports a different inductance.
    Vin_design = float(spec.Vin_min_Vrms or 0.0)
    delta_B_pp_T_array, I_total_rms, I_rip_rms = _carrier_metrics(
        spec,
        base,
        L_uH,
        N,
        Ae_m2,
        Bsat,
        Vin_design,
    )
    # Pythagorean recover of the line-frequency / DC RMS that the
    # engine's copper-loss DC term wants. Override knobs from the
    # caller win when present.
    if I_rms_total_A is not None:
        I_total_rms = float(I_rms_total_A)
        # When the caller pins the total RMS, recover the ripple
        # RMS via the same Pythagorean we use for the engine path.
        line_rms = float(base.I_line_rms_A or 0.0)
        I_rip_rms = math.sqrt(max(I_total_rms * I_total_rms - line_rms * line_rms, 0.0))
    if I_rip_rms_A is not None:
        I_rip_rms = float(I_rip_rms_A)
    # The DC / line-RMS used by ``loss_dc_W`` is the line current
    # itself — that's invariant across tier refinements (line
    # current is set by the converter's input-power balance, not
    # by the inductor's L). Use the engine's stored value.
    I_dc_line = float(base.I_line_rms_A or I_total_rms)
    # I_pk_max is informational; not used in the loss block.
    _ = I_pk_max_A or base.I_pk_max_A

    # Average ripple-flux for the line band (drives Steinmetz when
    # iGSE array isn't available — fallback path matches the
    # engine's degenerate path).
    delta_B_avg_T = (
        float(np.mean(delta_B_pp_T_array))
        if delta_B_pp_T_array is not None and delta_B_pp_T_array.size
        else 0.0
    )
    delta_B_avg_T = min(delta_B_avg_T, 2.0 * Bsat)

    layers = cp.estimate_layers(N, wire, core.Wa_mm2)

    # Frequency choice mirrors the engine: line reactor uses
    # f_line for both bands; everyone else uses f_sw.
    if spec.topology == "line_reactor":
        fsw_kHz_for_loss = spec.f_line_Hz / 1000.0
        fsw_Hz_for_skin = spec.f_line_Hz
    else:
        fsw_kHz_for_loss = spec.f_sw_kHz
        fsw_Hz_for_skin = spec.f_sw_kHz * 1000.0

    def total_loss_at_T(T_C: float) -> float:
        Rdc = cp.Rdc_ohm(N, core.MLT_mm, wire.A_cu_mm2, T_C)
        Rac = cp.Rac_ohm(wire, fsw_Hz_for_skin, Rdc, layers, T_C)
        P_cu_dc = cp.loss_dc_W(I_dc_line, Rdc)
        P_cu_ac = cp.loss_ac_W(I_rip_rms, Rac)
        P_line, P_ripple = cl.core_loss_W_pfc(
            material,
            spec.f_line_Hz,
            fsw_kHz_for_loss,
            B_pk_for_loss,
            delta_B_avg_T,
            core.Ve_mm3,
            delta_B_pp_T_array=delta_B_pp_T_array,
        )
        return P_cu_dc + P_cu_ac + P_line + P_ripple

    A_surface = th.surface_area_m2(core)
    T_amb = float(spec.T_amb_C)
    T_init = T_amb + 60.0  # same default as the engine

    T_final, conv, _ = th.converge_temperature(
        total_loss_at_T,
        A_surface,
        T_amb,
        T_init_C=T_init,
    )

    # Final breakdown at T_final.
    Rdc_final = cp.Rdc_ohm(N, core.MLT_mm, wire.A_cu_mm2, T_final)
    Rac_final = cp.Rac_ohm(wire, fsw_Hz_for_skin, Rdc_final, layers, T_final)
    P_cu_dc = cp.loss_dc_W(I_dc_line, Rdc_final)
    P_cu_ac = cp.loss_ac_W(I_rip_rms, Rac_final)
    P_line, P_ripple = cl.core_loss_W_pfc(
        material,
        spec.f_line_Hz,
        fsw_kHz_for_loss,
        B_pk_for_loss,
        delta_B_avg_T,
        core.Ve_mm3,
        delta_B_pp_T_array=delta_B_pp_T_array,
    )
    total = P_cu_dc + P_cu_ac + P_line + P_ripple

    return RefinedDesign(
        loss_W=total,
        temp_C=T_final,
        T_rise_C=T_final - T_amb,
        P_cu_dc_W=P_cu_dc,
        P_cu_ac_W=P_cu_ac,
        P_core_line_W=P_line,
        P_core_ripple_W=P_ripple,
        converged=conv,
        L_actual_uH=L_uH,
        B_pk_T=B_pk,
        I_rms_total_A=I_total_rms,
    )


# ---------------------------------------------------------------------------
# Carrier-waveform reconstruction
# ---------------------------------------------------------------------------
def _carrier_metrics(
    spec: Spec,
    base: DesignResult,
    L_uH: float,
    N: int,
    Ae_m2: float,
    Bsat: float,
    Vin_design: float,
) -> tuple[Optional[np.ndarray], float, float]:
    """Return ``(delta_B_pp_T_array, I_total_rms, I_rip_rms)`` for
    the topology + (refined) inductance.

    Mirrors the per-topology branch in ``design.engine.design``:
    boost-CCM and buck-CCM call into their respective
    ``waveforms`` modules to get the carrier-ripple array; line-
    reactor / passive-choke have no carrier ripple, so the array
    is ``None`` (the loss model falls through to its naïve
    Steinmetz path).
    """
    if N <= 0 or Ae_m2 <= 0 or L_uH <= 0:
        return None, float(base.I_rms_total_A or 0.0), 0.0

    # ``spec.topology`` is the ``Topology`` Literal which is always a
    # non-empty string at runtime — no ``or ""`` guard needed.
    topology = spec.topology.lower()

    if topology == "boost_ccm":
        wf = boost_ccm.waveforms(spec, Vin_design, L_uH)
        delta_pp = np.asarray(wf["delta_iL_pp_A"], dtype=float)
        delta_B = delta_pp * (L_uH * 1e-6) / (N * Ae_m2)
        delta_B = np.minimum(delta_B, 2.0 * Bsat)
        I_total_rms = float(boost_ccm.rms_inductor_current_A(wf))
        I_rip_rms = math.sqrt(float(np.mean(delta_pp**2 / 12.0)))
        return delta_B, I_total_rms, I_rip_rms

    if topology == "buck_ccm":
        wf = buck_ccm.waveforms(spec, L_uH)
        delta_pp = np.asarray(wf["delta_iL_pp_A"], dtype=float)
        delta_B = delta_pp * (L_uH * 1e-6) / (N * Ae_m2)
        delta_B = np.minimum(delta_B, 2.0 * Bsat)
        I_total_rms = float(buck_ccm.rms_inductor_current_from_waveform(wf))
        I_rip_rms = math.sqrt(float(np.mean(delta_pp**2 / 12.0)))
        return delta_B, I_total_rms, I_rip_rms

    # Line reactor + passive choke: no carrier ripple — only
    # line-frequency excitation. The naïve Steinmetz fallback in
    # ``core_loss_W_pfc`` handles ``delta_B_pp_T_array=None``
    # correctly (uses ``delta_B_avg_T = 0`` and zeroes the ripple
    # band by construction).
    return None, float(base.I_rms_total_A or 0.0), 0.0
