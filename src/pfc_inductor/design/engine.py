"""Design engine: orchestrates everything from (Spec, Core, Wire, Material) -> DesignResult.

Workflow:
1. Compute operating point from spec + Vin_nom (currents, required L).
2. Solve N: smallest integer N such that L_actual(N) >= L_required.
   - L_actual(N) = N^2 * AL * mu_pct(H_dc(N, I_dc_pk))
   - For powder cores this is iterative: H depends on N, mu depends on H.
3. Compute B_pk and check saturation.
4. Compute losses at temperature T:
   - DC copper at I_line_rms.
   - AC copper at I_ripple_rms (Dowell with layers from window).
   - Core loss line + ripple (Steinmetz, both bands).
5. Iterate on temperature until converged.
6. Generate waveforms for plotting.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from pfc_inductor.models import (
    Core,
    DesignResult,
    LossBreakdown,
    Material,
    Spec,
    Wire,
)
from pfc_inductor.physics import copper as cp
from pfc_inductor.physics import core_loss as cl
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.physics import thermal as th
from pfc_inductor.topology import boost_ccm, line_reactor, passive_choke


def _solve_N(
    L_required_uH: float,
    core: Core,
    material: Material,
    I_dc_pk_A: float,
    N_max: int = 500,
) -> tuple[int, float, float]:
    """Smallest N such that L(N) >= L_required, with rolloff applied at peak DC bias.

    Returns (N, L_actual_uH, mu_pct_at_peak).
    """
    AL = core.AL_nH
    le = core.le_mm
    for N in range(1, N_max + 1):
        H_pk = rf.H_from_NI(N, I_dc_pk_A, le, units="Oe")
        mu = rf.mu_pct(material, H_pk)
        L_uH = rf.inductance_uH(N, AL, mu)
        if L_uH >= L_required_uH:
            return N, L_uH, mu
    H_pk = rf.H_from_NI(N_max, I_dc_pk_A, le, units="Oe")
    mu = rf.mu_pct(material, H_pk)
    L_uH = rf.inductance_uH(N_max, AL, mu)
    return N_max, L_uH, mu


def _line_envelope_B_pk_T(
    N: int, I_line_pk_A: float, Ae_mm2: float, AL_nH: float, mu_pct_at_peak: float
) -> float:
    """Peak flux density from the line-frequency envelope (peak DC current)."""
    return rf.B_dc_T(N, I_line_pk_A, AL_nH, Ae_mm2, mu_pct_at_peak)


# Initial guess for the iterative thermal solver. The first ``total_loss``
# evaluation needs *some* temperature; +30 K above ambient is a reasonable
# midpoint between "design works comfortably" and "near thermal runaway"
# for typical PFC chokes — it converges in 2–4 iterations from there.
# Exposed as a module constant so tweaks are visible to git blame.
_T_INIT_RISE_K_DEFAULT: float = 30.0


def design(
    spec: Spec,
    core: Core,
    wire: Wire,
    material: Material,
    Vin_design_Vrms: Optional[float] = None,
    *,
    T_init_rise_K: float = _T_INIT_RISE_K_DEFAULT,
) -> DesignResult:
    """Run the full design pipeline.

    Parameters
    ----------
    spec, core, wire, material
        Inputs as documented at module level.
    Vin_design_Vrms
        Override for the worst-case input voltage used in current
        calculations. Defaults to ``spec.Vin_min_Vrms``.
    T_init_rise_K
        Initial winding-temperature rise above ambient handed to the
        thermal solver. Pure tuning knob — does not change the converged
        answer, only the iteration count. Keep at the module default
        unless profiling a slow case.
    """
    warnings: list[str] = []

    # Worst-case for current is low line.
    Vin_design = Vin_design_Vrms or spec.Vin_min_Vrms

    if spec.topology == "boost_ccm":
        I_pk = boost_ccm.line_peak_current_A(spec, Vin_design)
        I_rms_line = boost_ccm.line_rms_current_A(spec, Vin_design)
        L_req = boost_ccm.required_inductance_uH(spec, Vin_design)
    elif spec.topology == "line_reactor":
        # Line reactor: sized by %Z at f_line. Rated current already
        # respected via spec.I_rated_Arms; Vin_design is ignored.
        I_pk = line_reactor.line_pk_current_A(spec)
        I_rms_line = line_reactor.line_rms_current_A(spec)
        L_req = line_reactor.required_inductance_uH(spec)
    else:
        I_pk = passive_choke.line_peak_current_A(spec, Vin_design)
        I_rms_line = passive_choke.line_rms_current_A(spec, Vin_design)
        L_req = passive_choke.required_inductance_uH(spec, Vin_design)

    N, L_actual, mu_at_peak = _solve_N(L_req, core, material, I_pk)

    H_pk = rf.H_from_NI(N, I_pk, core.le_mm, units="Oe")
    if spec.topology == "line_reactor":
        # B_pk for a line reactor comes from the fundamental V across it,
        # not from the DC bias envelope (we are at line frequency, not
        # switching frequency, and silicon-steel laminations have no
        # gradual rolloff — μ stays roughly constant up to Bsat).
        L_actual_mH = L_actual / 1000.0
        V_L_rms = line_reactor.voltage_drop_Vrms(L_actual_mH, spec)
        B_pk = line_reactor.fundamental_B_pk_T(N, V_L_rms, core.Ae_mm2, spec.f_line_Hz)
    else:
        B_pk = _line_envelope_B_pk_T(N, I_pk, core.Ae_mm2, core.AL_nH, mu_at_peak)
    T_amb = spec.T_amb_C
    Bsat = material.Bsat_100C_T  # use hot Bsat as safe limit
    Bsat_limit = Bsat * (1.0 - spec.Bsat_margin)
    # Cap B used in the Steinmetz loss model to Bsat (above that the material
    # is saturated and the loss model is invalid; we keep a sane number so the
    # warning is the user-facing signal, not absurd loss values).
    B_pk_for_loss = min(B_pk, Bsat)

    Ku = cp.window_utilization(N, wire, core.Wa_mm2)
    layers = cp.estimate_layers(N, wire, core.Wa_mm2)
    if Ku > spec.Ku_max:
        warnings.append(
            f"Window utilization {Ku*100:.1f}% exceeds limit {spec.Ku_max*100:.1f}%"
        )
    if B_pk > Bsat_limit:
        warnings.append(
            f"B_pk={B_pk*1000:.0f} mT exceeds saturation limit "
            f"{Bsat_limit*1000:.0f} mT (margin {spec.Bsat_margin*100:.0f}%)"
        )

    # Waveforms (only meaningful for boost CCM). Line reactors and
    # passive chokes carry only fundamental + harmonics, no fsw ripple.
    if spec.topology == "boost_ccm":
        wf = boost_ccm.waveforms(spec, Vin_design, L_actual)
        I_total_rms = boost_ccm.rms_inductor_current_A(wf)
        delta_iL_avg = boost_ccm.ripple_avg_pp_A(wf)
        delta_iL_max = boost_ccm.ripple_max_pp_A(wf)
        I_pk_total = boost_ccm.peak_inductor_current_A(wf)
        # AC RMS of ripple component: from delta_iL(t)^2/12 averaged
        I_rip_rms = math.sqrt(float(np.mean(wf["delta_iL_pp_A"] ** 2 / 12.0)))
    else:
        wf = None
        I_total_rms = I_rms_line
        delta_iL_avg = 0.0
        delta_iL_max = 0.0
        I_pk_total = I_pk
        I_rip_rms = 0.0

    # For a line reactor we treat the line frequency as the only
    # excitation, so the fsw column in the loss model is set to f_line.
    # That keeps `core_loss_W_pfc`'s "line band" computation honest and
    # zeroes out the "ripple band" by construction (delta_iL_avg = 0).
    fsw_kHz_for_loss = (
        spec.f_line_Hz / 1000.0 if spec.topology == "line_reactor"
        else spec.f_sw_kHz
    )
    fsw_Hz_for_skin = (
        spec.f_line_Hz if spec.topology == "line_reactor"
        else spec.f_sw_kHz * 1000.0
    )

    Ae_m2 = core.Ae_mm2 * 1e-6
    delta_B_avg_T = (L_actual * 1e-6) * delta_iL_avg / (max(N, 1) * Ae_m2) if N > 0 else 0.0
    delta_B_avg_T = min(delta_B_avg_T, 2.0 * Bsat)
    # Per-instant ΔB(t) array along line cycle for iGSE.
    if wf is not None and N > 0:
        delta_B_pp_T_array = (L_actual * 1e-6) * wf["delta_iL_pp_A"] / (N * Ae_m2)
        delta_B_pp_T_array = np.minimum(delta_B_pp_T_array, 2.0 * Bsat)
    else:
        delta_B_pp_T_array = None

    # Thermal-coupled loss iteration
    A_surface = th.surface_area_m2(core)

    def total_loss_at_T(T_C: float) -> float:
        Rdc = cp.Rdc_ohm(N, core.MLT_mm, wire.A_cu_mm2, T_C)
        Rac = cp.Rac_ohm(wire, fsw_Hz_for_skin, Rdc, layers, T_C)
        P_cu_dc = cp.loss_dc_W(I_rms_line, Rdc)
        P_cu_ac = cp.loss_ac_W(I_rip_rms, Rac)
        P_line, P_ripple = cl.core_loss_W_pfc(
            material, spec.f_line_Hz, fsw_kHz_for_loss,
            B_pk_for_loss, delta_B_avg_T, core.Ve_mm3,
            delta_B_pp_T_array=delta_B_pp_T_array,
        )
        return P_cu_dc + P_cu_ac + P_line + P_ripple

    T_init = T_amb + T_init_rise_K
    T_final, conv, _ = th.converge_temperature(
        total_loss_at_T, A_surface, T_amb, T_init_C=T_init,
    )
    if not conv:
        warnings.append("Thermal solve did not fully converge")

    # Final breakdown at T_final
    Rdc_final = cp.Rdc_ohm(N, core.MLT_mm, wire.A_cu_mm2, T_final)
    Rac_final = cp.Rac_ohm(wire, fsw_Hz_for_skin, Rdc_final, layers, T_final)
    P_cu_dc = cp.loss_dc_W(I_rms_line, Rdc_final)
    P_cu_ac = cp.loss_ac_W(I_rip_rms, Rac_final)
    P_line, P_ripple = cl.core_loss_W_pfc(
        material, spec.f_line_Hz, fsw_kHz_for_loss, B_pk_for_loss, delta_B_avg_T, core.Ve_mm3
    )
    losses = LossBreakdown(
        P_cu_dc_W=P_cu_dc, P_cu_ac_W=P_cu_ac,
        P_core_line_W=P_line, P_core_ripple_W=P_ripple,
    )
    T_rise = T_final - T_amb

    if T_final > spec.T_max_C:
        warnings.append(
            f"Winding temperature {T_final:.1f}°C exceeds limit {spec.T_max_C:.1f}°C"
        )

    sat_margin_pct = ((Bsat_limit - B_pk) / Bsat_limit) * 100.0 if Bsat_limit > 0 else 0.0

    # Line-reactor specific outputs (None for other topologies)
    pct_Z_actual: Optional[float] = None
    v_drop_pct: Optional[float] = None
    thd_pct: Optional[float] = None
    Pi_W: Optional[float] = None
    lr_waveform_t: Optional[list[float]] = None
    lr_waveform_i: Optional[list[float]] = None
    if spec.topology == "line_reactor":
        L_actual_mH = L_actual / 1000.0
        v_drop_pct = line_reactor.voltage_drop_pct(L_actual_mH, spec)
        # %Z actual is the realised drop expressed as a fraction of V_phase.
        pct_Z_actual = v_drop_pct
        thd_pct = line_reactor.estimate_thd_pct(pct_Z_actual, n_phases=spec.n_phases)
        # Synthesise the line current from its harmonic decomposition so
        # the plot panel can show the waveform + spectrum without doing
        # any solver work.
        t_arr, i_arr = line_reactor.line_current_waveform(
            spec, L_actual_mH, n_cycles=2, n_points=1200,
        )
        lr_waveform_t = t_arr.tolist()
        lr_waveform_i = i_arr.tolist()
        # Active input power used by IEC 61000-3-2 Class D limit. For a
        # diode bridge + cap + reactor the actual power factor sits in
        # the 0.93–0.97 band; we use 0.95 as a defensible default. The
        # user can override per-design later if calibration data exists.
        ASSUMED_PF = 0.95
        if spec.n_phases == 3:
            # Total 3-phase active power: √3 · V_LL · I · pf
            Pi_W = math.sqrt(3.0) * spec.Vin_nom_Vrms * spec.I_rated_Arms * ASSUMED_PF
        else:
            Pi_W = spec.Vin_nom_Vrms * spec.I_rated_Arms * ASSUMED_PF
    elif spec.topology == "boost_ccm":
        # Active PFC: line-side THD is a *control quality* metric
        # (the PFC loop forces i_in ≈ k·v_in). Calibrated empirical:
        # THD% ≈ ripple_pct/6 + 1, matching published TI / ON-Semi
        # reference designs.
        thd_pct = boost_ccm.estimate_thd_pct(spec)
    elif spec.topology == "passive_choke":
        # Topologically identical to a 1-φ line reactor: same
        # series-L + diode-bridge + bulk-cap loop. Reuse the
        # IEEE-519 fit through the choke's pct_Z.
        thd_pct = passive_choke.estimate_thd_pct(spec, L_actual)
        # Surface pct_Z too so the Análise label can show "pct_Z = X %"
        # the same way line_reactor does.
        pct_Z_actual = passive_choke.voltage_drop_pct(
            L_actual / 1000.0, spec.Vin_min_Vrms, spec.Pout_W,
            spec.f_line_Hz,
        )

    res = DesignResult(
        L_required_uH=L_req,
        L_actual_uH=L_actual,
        N_turns=N,
        I_line_pk_A=I_pk,
        I_line_rms_A=I_rms_line,
        I_ripple_pk_pk_A=delta_iL_max,
        I_pk_max_A=I_pk_total,
        I_rms_total_A=I_total_rms,
        H_dc_peak_Oe=H_pk,
        mu_pct_at_peak=mu_at_peak,
        B_pk_T=B_pk,
        B_sat_limit_T=Bsat_limit,
        sat_margin_pct=sat_margin_pct,
        R_dc_ohm=Rdc_final,
        R_ac_ohm=Rac_final,
        losses=losses,
        T_rise_C=T_rise,
        T_winding_C=T_final,
        Ku_actual=Ku,
        Ku_max=spec.Ku_max,
        converged=conv,
        warnings=warnings,
        waveform_t_s=(
            wf["t_s"].tolist() if wf is not None
            else lr_waveform_t
        ),
        waveform_iL_A=(
            wf["iL_pk_A"].tolist() if wf is not None
            else lr_waveform_i
        ),
        waveform_B_T=None,
        pct_impedance_actual=pct_Z_actual,
        voltage_drop_pct=v_drop_pct,
        thd_estimate_pct=thd_pct,
        Pi_W=Pi_W,
        notes=(
            f"Design at Vin={Vin_design:.0f} Vrms (worst-case current). "
            f"Layers~{layers}. Material {material.name} ({material.vendor})."
        ),
    )
    return res
