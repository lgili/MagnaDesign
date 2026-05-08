"""Generate a datasheet-style HTML report for a designed inductor.

Layout follows the conventions used by TDK SLF, Würth WE-PD and Vishay
IHLP datasheets:

  Page 1 — Header • mechanical (4 views + dimensions table) • electrical
           specifications table.
  Page 2 — Performance: waveforms + losses + topology-specific charts
           (rolloff for boost, harmonic spectrum for line reactor).
  Page 3 — Bill of materials and engineering notes.

The HTML is fully self-contained: every plot is base64-PNG, no
external assets. Open in a browser and "Print → Save as PDF" for a
shareable artifact.

All copy is in English, optimised for an engineer-reader who scans
specs first and reads narrative only on demand.
"""
from __future__ import annotations

import base64
import hashlib
import math
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Optional

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.report.views_3d import derive_dimensions, render_views


# ---------------------------------------------------------------------------
# Plot helpers (small, sharply-styled charts; matches datasheet aesthetic)
# ---------------------------------------------------------------------------
def _b64(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _waveform_plot(result: DesignResult, topology: str) -> Optional[str]:
    if not result.waveform_t_s or not result.waveform_iL_A:
        return None
    t_ms = np.array(result.waveform_t_s) * 1000.0
    iL = np.array(result.waveform_iL_A)
    fig, ax = plt.subplots(figsize=(7.0, 3.4), dpi=110)
    if topology == "line_reactor":
        title = "Line Current — Phase A (steady state)"
        ax.plot(t_ms, iL, color="#a01818", linewidth=1.4)
        ax.axhline(0, color="#999", linewidth=0.5)
    elif topology == "boost_ccm":
        title = "Inductor Current — half line cycle"
        ax.plot(t_ms, iL, color="#3a78b5", linewidth=1.4)
        ax.fill_between(t_ms, 0, iL, alpha=0.12, color="#3a78b5")
    else:
        title = "Inductor Current"
        ax.plot(t_ms, iL, color="#3a78b5", linewidth=1.4)
    ax.set_xlabel("t [ms]")
    ax.set_ylabel("i [A]")
    ax.set_title(title, fontsize=10)
    ax.grid(True, alpha=0.35)
    return _b64(fig)


def _loss_plot(result: DesignResult) -> str:
    L = result.losses
    labels = ["Cu DC", "Cu AC", "Core (line)", "Core (ripple)"]
    values = [L.P_cu_dc_W, L.P_cu_ac_W, L.P_core_line_W, L.P_core_ripple_W]
    colors = ["#3a78b5", "#7eaee0", "#b53a3a", "#e07e7e"]
    fig, ax = plt.subplots(figsize=(6.0, 3.0), dpi=110)
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylabel("Loss [W]")
    ax.set_title(f"Loss breakdown — total {L.P_total_W:.2f} W", fontsize=10)
    ax.grid(True, axis="y", alpha=0.35)
    for b, v in zip(bars, values, strict=False):
        ax.text(b.get_x() + b.get_width()/2, v + 0.02, f"{v:.2f}",
                ha="center", va="bottom", fontsize=8)
    return _b64(fig)


def _rolloff_plot(material: Material, result: DesignResult) -> Optional[str]:
    if material.rolloff is None:
        return None
    H = np.logspace(0, 3.5, 200)
    mu = np.array([rf.mu_pct(material, h) for h in H]) * 100
    fig, ax = plt.subplots(figsize=(7.0, 3.4), dpi=110)
    ax.semilogx(H, mu, linewidth=1.6, color="#3a78b5")
    ax.axvline(result.H_dc_peak_Oe, color="#a01818", linestyle="--",
               alpha=0.6, label=f"H = {result.H_dc_peak_Oe:.0f} Oe")
    ax.axhline(result.mu_pct_at_peak * 100, color="#a01818",
               linestyle=":", alpha=0.6,
               label=f"μ% = {result.mu_pct_at_peak*100:.1f}%")
    ax.set_xlabel("H [Oe]")
    ax.set_ylabel("μ% [% initial]")
    ax.set_title(f"DC bias roll-off — {escape(material.name)}",
                 fontsize=10)
    ax.set_ylim(0, 105)
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(True, which="both", alpha=0.35)
    return _b64(fig)


def _harmonic_plot(spec: Spec, result: DesignResult) -> Optional[str]:
    """Bar chart of harmonics in mA RMS with IEC 61000-3-2 Class D
    limit overlaid (only relevant for line_reactor).
    """
    if spec.topology != "line_reactor":
        return None
    if not result.waveform_t_s or not result.waveform_iL_A:
        return None
    from pfc_inductor.standards import iec61000_3_2 as iec
    from pfc_inductor.topology import line_reactor as lr

    t = np.array(result.waveform_t_s)
    i = np.array(result.waveform_iL_A)
    n_axis, pct, thd = lr.harmonic_spectrum(t, i, f_line_Hz=spec.f_line_Hz,
                                             n_harmonics=39)
    I_rms = float(np.sqrt(np.mean(i * i)))
    sum_sq = float(np.sum((pct[1:] / 100.0) ** 2))
    I1 = I_rms / math.sqrt(1.0 + sum_sq) if (1.0 + sum_sq) > 0 else 0.0
    harmonics_A = {int(h): (pct[idx] / 100.0) * I1
                    for idx, h in enumerate(n_axis)}
    Pi = result.Pi_W or 0.0
    compliance = iec.evaluate_compliance(harmonics_A, Pi)
    limits = iec.class_d_limits(Pi) if Pi > 0 else {}

    plot_orders = [1] + iec.ODD_HARMONICS
    plot_amps_mA = [harmonics_A.get(h, 0.0) * 1000 for h in plot_orders]
    colors = []
    for h, amp_mA in zip(plot_orders, plot_amps_mA, strict=False):
        if h == 1:
            colors.append("#1c7c3b")
        else:
            lim = limits.get(h, 0.0) * 1000
            colors.append("#a01818" if (lim > 0 and amp_mA > lim) else "#3a78b5")

    fig, ax = plt.subplots(figsize=(8.0, 3.6), dpi=110)
    ax.bar(plot_orders, plot_amps_mA, width=0.7, color=colors,
           label="Predicted (RMS)")
    if limits:
        lo = sorted(limits.keys())
        lv_mA = [limits[h] * 1000 for h in lo]
        ax.plot(lo, lv_mA, color="#a06700", linestyle="--", marker="o",
                markersize=4, linewidth=1.5,
                label="IEC 61000-3-2 Class D")
    # IEC 61000-3-12 — industrial-equipment connection at the PCC,
    # for input current 16 A < I ≤ 75 A. Default compatibility level
    # 2 (general industrial environment), Table 4: per-harmonic
    # current limits expressed as % of fundamental.
    iec_3_12_pct = {
        3: 21.6, 5: 10.7, 7: 7.2, 9: 3.8, 11: 3.1, 13: 2.0,
        15: 0.7, 17: 1.2, 19: 1.1, 21: 0.6, 23: 0.9, 25: 0.8,
        27: 0.6, 29: 0.7, 31: 0.7, 33: 0.6, 35: 0.6, 37: 0.5,
        39: 0.5,
    }
    if I1 > 0:
        lo312 = sorted(iec_3_12_pct.keys())
        lv312_mA = [iec_3_12_pct[h] / 100.0 * I1 * 1000.0 for h in lo312]
        ax.plot(lo312, lv312_mA, color="#3a78b5", linestyle=":",
                marker="s", markersize=3, linewidth=1.2,
                label="IEC 61000-3-12 (industrial)")
    # IEEE 519-2014 Table 10-3 — TDD (Total Demand Distortion) at the
    # PCC. The standard expresses limits as % of I_L (max demand
    # load current at the fundamental). Without a specific Isc/IL
    # ratio we plot the most-common 50≤Isc/IL<100 column (industrial
    # mid-range), which gives 7 % per individual h<11.
    ieee_519_pct = {
        3: 7.0, 5: 7.0, 7: 7.0, 9: 7.0,
        11: 3.5, 13: 3.5, 15: 3.5,
        17: 2.5, 19: 2.5, 21: 2.5,
        23: 1.0, 25: 1.0, 27: 1.0, 29: 1.0,
        31: 0.5, 33: 0.5, 35: 0.5, 37: 0.5, 39: 0.5,
    }
    if I1 > 0:
        lo519 = sorted(ieee_519_pct.keys())
        lv519_mA = [ieee_519_pct[h] / 100.0 * I1 * 1000.0 for h in lo519]
        ax.plot(lo519, lv519_mA, color="#52525B", linestyle="-.",
                marker="^", markersize=3, linewidth=1.0,
                label="IEEE 519-2014 (50≤Isc/IL<100)")
    verdict = "PASS" if compliance.passes else "FAIL"
    extra = ""
    if Pi > 600:
        extra = "  ⚠ Pi > 600 W: outside Class D scope; use Class A"
    elif Pi < 75:
        extra = "  ⚠ Pi < 75 W: outside Class D scope"
    ax.set_xlabel("Harmonic order")
    ax.set_ylabel("Current [mA RMS]")
    ax.set_title(
        f"Harmonic spectrum — Pi = {Pi:.0f} W · {verdict} · "
        f"THD {thd:.1f}%{extra}", fontsize=10,
    )
    ax.set_xticks(plot_orders[::2])
    ax.grid(True, axis="y", alpha=0.35)
    ax.legend(loc="upper right", fontsize=8)
    return _b64(fig)


# ---------------------------------------------------------------------------
# Revision history — even when only the current rev exists, a labelled
# slot for it sets the expectation that future revs will append. The
# datasheet keeps the same P/N across revs (P/N hashes spec + core +
# material; identical inputs produce the same hash) so any change
# the engineer makes is obvious in the history table.
# ---------------------------------------------------------------------------
def _revision_history_rows(revision: str, designer: str,
                            now: str) -> str:
    head = (
        '<thead><tr>'
        '<th class="lbl">Rev</th>'
        '<th>Date</th>'
        '<th>Author</th>'
        '<th>Change</th>'
        '</tr></thead>'
    )
    rows: list[tuple[str, str, str, str]] = [
        (revision, now, designer, "Initial release of this design"),
    ]
    body = "".join(
        f'<tr><td class="lbl">{escape(rv)}</td>'
        f'<td>{escape(d)}</td>'
        f'<td>{escape(a)}</td>'
        f'<td>{escape(ch)}</td></tr>'
        for (rv, d, a, ch) in rows
    )
    return f'<table class="dim">{head}<tbody>{body}</tbody></table>'


# ---------------------------------------------------------------------------
# Project metadata footer — the engineer needs to be able to re-open
# the design six months later. Without QR code support (would add a
# new dep), we emit a structured metadata block: P/N hash, source file
# format, exact spec/core/material keys. Anyone wanting to reproduce
# the design feeds those four ids back into MagnaDesign.
# ---------------------------------------------------------------------------
def _project_metadata_rows(spec: Spec, core: Core, material: Material,
                            wire: Wire, pn: str) -> str:
    rows = {
        "Project P/N (this design)":  f"<code>{pn}</code>",
        "Topology key":               f"<code>{escape(spec.topology)}</code>",
        "Material id":                f"<code>{escape(material.id)}</code>",
        "Core id":                    f"<code>{escape(core.id)}</code>",
        "Wire id":                    f"<code>{escape(wire.id)}</code>",
        "Source format":              ".pfc (JSON, MagnaDesign)",
        "Reproduce in MagnaDesign":
            "Open the .pfc file or recreate the spec with the four "
            "ids above; the engine is deterministic given the same "
            "spec + core + material + wire.",
    }
    return _kv_table(rows, extra_class="dim")


# ---------------------------------------------------------------------------
# B–H operating-point trajectory — same plot the dashboard's BHLoopCard
# already builds, rendered to PNG so the printed datasheet carries it.
# ---------------------------------------------------------------------------
def _bh_trajectory_plot(result: DesignResult, core: Core,
                         material: Material) -> Optional[str]:
    try:
        from pfc_inductor.visual import compute_bh_trajectory
        tr = compute_bh_trajectory(result, core, material)
    except Exception:
        return None
    fig, ax = plt.subplots(figsize=(7.0, 3.6), dpi=110)
    ax.plot(tr["H_static_Oe"], tr["B_static_T"] * 1000.0,
            color="#bbb", linewidth=1.2, label="Static B–H curve")
    Bsat_mT = float(tr["Bsat_T"]) * 1000.0
    ax.axhline(Bsat_mT, color="#a01818", linestyle="--", alpha=0.7,
               linewidth=1.0, label=f"Bsat (100°C) = {Bsat_mT:.0f} mT")
    ax.plot(tr["H_envelope_Oe"], tr["B_envelope_T"] * 1000.0,
            color="#3a78b5", linewidth=1.8, alpha=0.9,
            label="Line-cycle envelope")
    if tr["H_ripple_Oe"] is not None and tr["B_ripple_T"] is not None:
        ax.plot(tr["H_ripple_Oe"], tr["B_ripple_T"] * 1000.0,
                color="#a06700", linewidth=1.4, alpha=0.9,
                label="HF ripple at peak")
    ax.plot([tr["H_pk_Oe"]], [tr["B_pk_T"] * 1000.0],
             "o", color="#a01818", markersize=6,
             label=f"Operating peak ({tr['H_pk_Oe']:.0f} Oe / "
                   f"{tr['B_pk_T']*1000.0:.0f} mT)")
    ax.set_xlabel("H [Oe]")
    ax.set_ylabel("B [mT]")
    ax.set_title("B–H trajectory at operating point", fontsize=10)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="lower right", fontsize=8)
    return _b64(fig)


# ---------------------------------------------------------------------------
# Tolerance bands — datasheets need these. The engine doesn't compute
# manufacturing variance natively, so the report layer applies industry-
# standard tolerance buckets keyed off the material family.
# ---------------------------------------------------------------------------
def _tolerance_band_pct(material_type: str) -> float:
    """Return the typical inductance tolerance for a given material
    family (in %, ±). These mirror the bands published by Magnetics,
    Würth, TDK and ATM Magnetics for production-grade parts.
    """
    return {
        "powder":           15.0,
        "ferrite":          20.0,
        "nanocrystalline":  12.0,
        "amorphous":        12.0,
        "silicon-steel":    25.0,   # gapped silicon-steel is the worst
    }.get(material_type, 20.0)


def _tolerance_rows(result: DesignResult, material: Material) -> str:
    """Per-parameter tolerance table.

    Inductance band is keyed off material family; Rdc and turn count
    inherit the canonical magnetics-industry numbers (Vishay,
    Magnetics, Würth datasheets).
    """
    L_pct = _tolerance_band_pct(material.type)
    L_act = float(result.L_actual_uH)
    L_lo = L_act * (1.0 - L_pct / 100.0)
    L_hi = L_act * (1.0 + L_pct / 100.0)
    rdc_act_mohm = float(result.R_dc_ohm) * 1000.0
    rdc_lo = rdc_act_mohm * 0.90
    rdc_hi = rdc_act_mohm * 1.10
    rows = {
        "Inductance L (typ ± tol)":
            f"{L_act:.1f} µH (± {L_pct:.0f} %), range {L_lo:.1f} – {L_hi:.1f} µH",
        "DC resistance Rdc (typ ± 10 %)":
            f"{rdc_act_mohm:.1f} mΩ, range {rdc_lo:.1f} – {rdc_hi:.1f} mΩ",
        "Turn count N":
            f"{result.N_turns} (exact, no tolerance)",
        "Mass":
            "± 10 % around the BOM estimate",
        "Mechanical envelope":
            "± 0.5 mm on linear dimensions, ± 1° on angular",
        "Dielectric strength":
            "Pass criterion: no flashover during the hi-pot test",
    }
    return _kv_table(rows, extra_class="dim")


# ---------------------------------------------------------------------------
# Build instructions — quick reference for the bobbin / wind room.
# ---------------------------------------------------------------------------
def _build_instructions_rows(core: Core, wire: Wire,
                              result: DesignResult) -> str:
    wire_len_m = result.N_turns * core.MLT_mm * 1e-3
    # Estimate layer count: turns_per_layer ≈ Wa_mm² ÷ (d_outer · h_window).
    # Without a dedicated window-height field on Core we fall back to
    # a conservative √Wa as the layer height — close enough for the
    # build-room hand-off, which is approximate by definition.
    d_outer_mm = (wire.d_iso_mm or wire.d_cu_mm or 0.5)
    layer_height = math.sqrt(max(core.Wa_mm2, 1.0))
    turns_per_layer = max(1, int(layer_height / max(d_outer_mm, 0.01)))
    n_layers = max(1, math.ceil(result.N_turns / turns_per_layer))
    air_gap = (
        f"{core.lgap_mm:.2f} mm" if core.lgap_mm > 0 else "no air gap"
    )
    rows = {
        "Bobbin / former":
            f"{core.shape.upper()} compatible — single-section",
        "Wire":
            f"{wire.id} ({wire.type}, A_cu = {wire.A_cu_mm2:.3f} mm²)",
        "Total turns N":
            f"{result.N_turns} (single layer if window allows)",
        "Estimated turns per layer":
            f"{turns_per_layer}",
        "Estimated layer count":
            f"{n_layers}",
        "Wire length (with 5 % margin)":
            f"{wire_len_m * 1.05:.2f} m (cut length)",
        "Air gap (centre leg)":
            air_gap,
        "Inter-layer insulation":
            "1 layer of polyester tape (35 µm) between layers",
        "Outer wrap":
            "2 layers of polyester tape, overlapped 50 %",
        "Impregnation":
            "Vacuum-impregnated with class-F (155 °C) varnish",
        "Lead termination":
            "Tinned 30 mm leads, dressed at the bobbin's start/end pads",
    }
    return _kv_table(rows, extra_class="dim")


# ---------------------------------------------------------------------------
# Test plan / FAT — the parameters QA must check before shipping.
# ---------------------------------------------------------------------------
def _test_plan_rows(spec: Spec, result: DesignResult,
                     material: Material) -> str:
    """Factory acceptance-test table.

    Each row: parameter, target spec, instrument, pass/fail band.
    Bands are derived from ``_tolerance_band_pct`` so the wind-room
    and the datasheet agree on what "in spec" means.
    """
    L_pct = _tolerance_band_pct(material.type)
    L_act = float(result.L_actual_uH)
    rdc_mohm = float(result.R_dc_ohm) * 1000.0
    rows: list[tuple[str, str, str, str]] = [
        ("L @ 1 kHz, low signal",
         f"{L_act:.1f} µH",
         "LCR meter (4 kHz, 0.5 V)",
         f"± {L_pct:.0f} %"),
        ("Rdc @ 25 °C",
         f"{rdc_mohm:.1f} mΩ",
         "4-wire micro-Ω meter",
         "± 10 %"),
        ("Turn count N",
         f"{result.N_turns}",
         "Visual inspection of bobbin",
         "Exact"),
        ("Hi-pot (winding-to-core)",
         "1 min",
         "5 kV hi-pot tester",
         "No flashover, leakage ≤ 5 mA"),
        ("Insulation resistance",
         "≥ 100 MΩ",
         "500 V megohmmeter",
         "≥ 100 MΩ"),
    ]
    if spec.topology == "boost_ccm":
        rows.append((
            "Saturation current Isat",
            f"≥ {result.I_pk_max_A:.2f} A",
            "Curve tracer (DC bias sweep)",
            "L drops ≤ 30 % at Isat",
        ))
    elif spec.topology == "line_reactor":
        rows.append((
            "Voltage drop @ rated I",
            f"{(result.voltage_drop_pct or 0):.2f} %",
            "AC source + true-RMS voltmeter",
            "± 15 %",
        ))
    elif spec.topology == "passive_choke":
        rows.append((
            "Saturation onset",
            f"≥ {result.I_pk_max_A:.2f} A",
            "Curve tracer (DC bias)",
            "L drops ≤ 30 %",
        ))
    rows.append((
        "Visual / mechanical",
        "—",
        "Calliper, bobbin gauge",
        "± 0.5 mm",
    ))
    head = (
        '<thead><tr>'
        '<th class="lbl">Parameter</th>'
        '<th>Target</th>'
        '<th>Instrument</th>'
        '<th>Pass band</th>'
        '</tr></thead>'
    )
    body = "".join(
        f'<tr><td class="lbl">{escape(p)}</td>'
        f'<td>{escape(t)}</td>'
        f'<td>{escape(inst)}</td>'
        f'<td>{escape(b)}</td></tr>'
        for (p, t, inst, b) in rows
    )
    return f'<table class="dim">{head}<tbody>{body}</tbody></table>'


# ---------------------------------------------------------------------------
# Boost-CCM switching-period zoom — the line-cycle envelope hides the
# Δi pp ripple; this plot synthesises a few switching periods at the
# worst-case operating point so the user actually sees the parameter
# they sized L for.
# ---------------------------------------------------------------------------
def _switching_ripple_plot(spec: Spec, result: DesignResult) -> Optional[str]:
    if spec.topology != "boost_ccm" or spec.f_sw_kHz <= 0:
        return None
    L_H = float(result.L_actual_uH) * 1e-6
    if L_H <= 0:
        return None
    Vin_min_pk = math.sqrt(2.0) * float(spec.Vin_min_Vrms)
    Vout = float(spec.Vout_V)
    if Vout <= Vin_min_pk:
        return None
    # Worst-case ripple sits at the line-current peak, when the duty
    # cycle is D = 1 − Vin_pk/Vout. There the inductor sees Vin_pk
    # during ON and (Vin_pk − Vout) during OFF.
    Tsw = 1.0 / (float(spec.f_sw_kHz) * 1000.0)
    D = 1.0 - Vin_min_pk / Vout
    t_on = D * Tsw
    delta_i = (Vin_min_pk * t_on) / L_H              # peak-to-peak
    iL_dc = float(result.I_line_pk_A)
    iL_min = iL_dc - delta_i / 2.0
    iL_max = iL_dc + delta_i / 2.0
    # Build 3 switching periods of the triangular ripple riding on iL_dc.
    n_periods = 3
    t = []
    iL = []
    for k in range(n_periods):
        t0 = k * Tsw
        t.extend([t0, t0 + t_on, t0 + Tsw])
        iL.extend([iL_min, iL_max, iL_min])
    t_us = np.array(t) * 1e6
    fig, ax = plt.subplots(figsize=(7.0, 3.0), dpi=110)
    ax.plot(t_us, iL, color="#3a78b5", linewidth=1.6)
    ax.fill_between(t_us, iL_min, iL, alpha=0.12, color="#3a78b5")
    ax.axhline(iL_dc, color="#777", linestyle=":", linewidth=0.8,
               label=f"I_dc = {iL_dc:.2f} A")
    ax.axhline(iL_max, color="#a01818", linestyle="--", linewidth=0.8,
               label=f"I_pk = {iL_max:.2f} A")
    ax.axhline(iL_min, color="#1c7c3b", linestyle="--", linewidth=0.8,
               label=f"I_valley = {iL_min:.2f} A")
    ax.set_xlabel("t [µs]")
    ax.set_ylabel("iL [A]")
    ax.set_title(
        f"Switching ripple at Vin_min — Δi_pp = {delta_i:.2f} A "
        f"({100.0*delta_i/max(iL_dc, 1e-6):.0f} %)",
        fontsize=10,
    )
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper right", fontsize=8)
    return _b64(fig)


# ---------------------------------------------------------------------------
# η-vs-load curve — sweep Pout from 10 % to 100 % using the engine's
# closed-form pass at each point and plot the resulting efficiency.
# Re-running ``design()`` is cheap (sub-millisecond) so this is fine
# inline.
# ---------------------------------------------------------------------------
def _efficiency_curve_plot(
    spec: Spec, core: Core, wire: Wire, material: Material,
    result: DesignResult,
) -> Optional[str]:
    if spec.topology not in ("boost_ccm", "passive_choke"):
        return None
    if float(spec.Pout_W) <= 0 or float(result.losses.P_total_W) <= 0:
        return None
    # Sweep at 10/25/50/75/100/110 % of nominal Pout. The 110 % point
    # tells the user how the design behaves at headroom — overload is
    # often the parameter that decides MTBF.
    fractions = (0.10, 0.25, 0.50, 0.75, 1.00, 1.10)
    P_nom = float(spec.Pout_W)
    from pfc_inductor.design import design as _design
    pts: list[tuple[float, float]] = []
    for f in fractions:
        try:
            spec_p = spec.model_copy(update={"Pout_W": P_nom * f})
            r = _design(spec_p, core, wire, material)
            P_in = r.Pi_W if r.Pi_W else (P_nom * f + r.losses.P_total_W)
            eta_pct = 100.0 * (P_nom * f) / max(P_in, 1e-6)
            pts.append((100.0 * f, eta_pct))
        except Exception:
            # If the engine refuses (e.g. infeasible at 10 % load),
            # skip the point — partial curves are still useful.
            continue
    if len(pts) < 2:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    fig, ax = plt.subplots(figsize=(6.0, 3.0), dpi=110)
    ax.plot(xs, ys, "-o", color="#3a78b5", linewidth=1.5, markersize=5)
    ax.set_xlabel("Pout [% of nominal]")
    ax.set_ylabel("η [%]")
    ax.set_ylim(min(ys) - 2.0, max(100.0, max(ys) + 0.5))
    ax.set_title("Efficiency vs Load (inductor only)", fontsize=10)
    ax.axvline(100.0, color="#777", linestyle=":", linewidth=0.8)
    ax.grid(True, alpha=0.35)
    return _b64(fig)


# ---------------------------------------------------------------------------
# Commutation notch summary — engine has the ``commutation_overlap_rad``
# helper but the report never called it before. The notch depth /
# duration coordinates protection / gate-drive timing upstream.
# ---------------------------------------------------------------------------
def _commutation_notch_block(spec: Spec, result: DesignResult) -> Optional[str]:
    if spec.topology != "line_reactor":
        return None
    from pfc_inductor.topology import line_reactor as lr
    L_mH = float(result.L_actual_uH) / 1000.0
    if L_mH <= 0:
        return None
    mu = lr.commutation_overlap_rad(spec, L_mH)
    mu_deg = math.degrees(mu)
    # Notch depth: during overlap, the line-to-line voltage at the
    # commutating phase pair drops to roughly V_pk · (1 − cos µ).
    V_pk = math.sqrt(2.0) * float(spec.Vin_nom_Vrms)
    notch_depth_V = V_pk * (1.0 - math.cos(mu))
    notch_pct = 100.0 * notch_depth_V / V_pk if V_pk > 0 else 0.0
    notch_us = (mu / (2.0 * math.pi)) * (1.0 / max(spec.f_line_Hz, 1.0)) * 1e6
    rows = {
        "Overlap angle µ":         f"{mu_deg:.2f}°",
        "Notch duration":          f"{notch_us:.0f} µs",
        "Notch depth (line-line)": f"{notch_depth_V:.0f} V "
                                   f"({notch_pct:.1f} % of V_pk)",
        "Reference":               "Mohan/Undeland eq. (5-65), "
                                   "6-pulse diode rectifier",
    }
    return _kv_table(rows, extra_class="dim")


# ---------------------------------------------------------------------------
# Choke before/after PF + Vripple comparison chart
# ---------------------------------------------------------------------------
def _choke_comparison_plot(spec: Spec, result: DesignResult,
                            core: Core) -> Optional[str]:
    if spec.topology != "passive_choke":
        return None
    ex = _passive_choke_extras(spec, result, core)
    pf_no = float(ex["pf_no_choke"])
    pf_yes = float(ex["pf_with_choke"])
    # Capacitor-input rectifier ripple without choke: rule of thumb
    # 2× the with-choke value (the choke smooths the rectifier
    # current pulse, halving its DC-link bucket excursion).
    v_ripple_yes = float(ex["v_ripple_dc_pp"])
    v_ripple_no = v_ripple_yes * 2.0
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 2.8), dpi=110)
    ax_pf, ax_v = axes
    bars_pf = ax_pf.bar(["No choke", "With choke"], [pf_no, pf_yes],
                          color=["#a01818", "#1c7c3b"], width=0.55)
    ax_pf.set_ylim(0, 1.0)
    ax_pf.set_ylabel("Power factor")
    ax_pf.set_title("PF — before vs after", fontsize=10)
    ax_pf.grid(True, axis="y", alpha=0.35)
    for b, v in zip(bars_pf, [pf_no, pf_yes], strict=False):
        ax_pf.text(b.get_x() + b.get_width()/2, v + 0.02, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=9)
    bars_v = ax_v.bar(["No choke", "With choke"],
                       [v_ripple_no, v_ripple_yes],
                       color=["#a01818", "#1c7c3b"], width=0.55)
    ax_v.set_ylabel("V_ripple pp [V]")
    ax_v.set_title("DC-link ripple — before vs after", fontsize=10)
    ax_v.grid(True, axis="y", alpha=0.35)
    for b, v in zip(bars_v, [v_ripple_no, v_ripple_yes], strict=False):
        ax_v.text(b.get_x() + b.get_width()/2, v + 0.5, f"{v:.0f}",
                   ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    return _b64(fig)


# ---------------------------------------------------------------------------
# Engineering constants for derived data the engine doesn't compute
# ---------------------------------------------------------------------------
_CU_DENSITY_KG_M3 = 8960.0  # pure copper at 20 °C — for wire-mass fallback


# Default environmental ratings shared by every magnetic component the
# tool ships. These are conservative values that match the IEC 60068
# qualification levels typical for industrial inverters and PFC stages.
# Anyone needing tighter limits should override the ``EnvRatings`` dict
# at call site (left as a future enhancement; currently global).
_ENV_RATINGS: dict[str, str] = {
    "Operating temperature":   "−25 to +105 °C (winding hot-spot)",
    "Storage temperature":     "−40 to +85 °C",
    "Humidity":                "5 to 95 % RH, non-condensing",
    "Altitude (no derate)":    "≤ 2000 m (per IEC 60664-1)",
    "Vibration":               "IEC 60068-2-6, 10–500 Hz, 5 g",
    "Shock":                   "IEC 60068-2-27, 30 g, 11 ms half-sine",
    "Pollution degree":        "2 (clean indoor)",
}


# Per-topology safety ratings. Line reactors are line-voltage devices
# and need explicit hi-pot / isolation numbers; boost / passive are
# commonly enclosed in a converter so the chassis carries those duties,
# but engineers still expect a coil-level rating block for QA.
_SAFETY_BOOST: dict[str, str] = {
    "Insulation class":        "B (130 °C) winding-to-core",
    "Hi-pot test":             "1500 Vrms, 60 s (winding-to-core)",
    "Dielectric strength":     "≥ 4 kVrms, 1 min",
    "Overvoltage category":    "II (per IEC 60664-1)",
    "Pollution degree":        "2",
}
_SAFETY_LINE_REACTOR: dict[str, str] = {
    "Insulation class":        "F (155 °C) winding-to-core",
    "Hi-pot test":             "2500 Vrms, 60 s, leakage ≤ 5 mA",
    "Dielectric strength":     "≥ 6 kVrms, 1 min, winding-to-core",
    "Overvoltage category":    "III (per IEC 60664-1, industrial mains)",
    "Pollution degree":        "2",
    "Surge withstand":         "IEC 61000-4-5, 4 kV line-to-earth",
}
_SAFETY_PASSIVE_CHOKE: dict[str, str] = {
    "Insulation class":        "B (130 °C) winding-to-core",
    "Hi-pot test":             "2000 Vrms, 60 s (winding-to-core)",
    "Dielectric strength":     "≥ 5 kVrms, 1 min",
    "Overvoltage category":    "II/III (per integrator's chassis class)",
    "Pollution degree":        "2",
}


def _safety_table_for(topology: str) -> dict[str, str]:
    return {
        "boost_ccm":      _SAFETY_BOOST,
        "line_reactor":   _SAFETY_LINE_REACTOR,
        "passive_choke":  _SAFETY_PASSIVE_CHOKE,
    }.get(topology, _SAFETY_BOOST)


# ---------------------------------------------------------------------------
# Wire mass with copper-density fallback
# ---------------------------------------------------------------------------
def _wire_mass_g(wire: Wire, length_m: float) -> float:
    """Return the wire mass in grams.

    Prefers the catalog's ``mass_per_meter_g`` when set; otherwise
    derives from copper density × A_cu × length. The fallback is
    accurate to within ~3 % for round magnet wire (the polymer
    insulation adds 0.5–2 % mass, ignored here).
    """
    if wire.mass_per_meter_g and wire.mass_per_meter_g > 0:
        return float(length_m) * float(wire.mass_per_meter_g)
    a_cu_m2 = float(wire.A_cu_mm2) * 1e-6
    return float(length_m) * a_cu_m2 * _CU_DENSITY_KG_M3 * 1000.0  # → g


# ---------------------------------------------------------------------------
# Passive choke estimates (engine doesn't surface these natively)
# ---------------------------------------------------------------------------
def _passive_choke_extras(
    spec: Spec, result: DesignResult, core: Core,
) -> dict[str, str]:
    """Compute %Z, achievable PF, and DC-link ripple for a passive
    line choke. The engine doesn't carry topology-specific fields for
    this configuration, so the report layer fills them analytically.

    The PF estimate uses the empirical curve documented in Pomilio
    Cap. 13 and Mohan §4.5: a series choke before a capacitive-input
    rectifier raises the PF from ~0.55 (no choke) toward ~0.85
    asymptotically, with a knee around ωL ≈ 0.4 · V_pk / I_pk_load.
    """
    omega = 2.0 * math.pi * float(spec.f_line_Hz)
    L_H = float(result.L_actual_uH) * 1e-6
    Vin_rms = float(spec.Vin_nom_Vrms)
    # Approximate fundamental load current from Pout / (η · V_rms · PF₀).
    pf0 = 0.55  # capacitive rectifier baseline
    eta = max(float(spec.eta), 0.5)
    I_load_rms = float(spec.Pout_W) / max(eta * Vin_rms * pf0, 1e-6)
    z_base = Vin_rms / max(I_load_rms, 1e-6)
    z_react = omega * L_H
    pct_z = 100.0 * z_react / z_base if z_base > 0 else 0.0
    # PF saturation curve: PF ≈ pf0 + (0.95−pf0) · (1 − exp(−x))
    # with x = z_react / (0.4 · V_pk / I_pk_load).
    Vpk = math.sqrt(2.0) * Vin_rms
    Ipk_load = math.sqrt(2.0) * I_load_rms
    x = z_react / max(0.4 * Vpk / max(Ipk_load, 1e-6), 1e-6)
    pf_estimate = pf0 + (0.95 - pf0) * (1.0 - math.exp(-x))
    pf_estimate = max(0.55, min(0.95, pf_estimate))
    # DC-link ripple voltage estimate assuming a "typical" bulk cap
    # sized at 1 µF/W (industry rule of thumb). Engine doesn't carry
    # the cap value, so this is a guidance number, not a guarantee.
    C_dc_uF = max(float(spec.Pout_W) * 1.0, 100.0)
    I_dc = float(spec.Pout_W) / max(eta * Vin_rms * 1.41, 1.0)
    f_ripple = 2.0 * float(spec.f_line_Hz)  # full-wave
    v_ripple_pp = I_dc / (C_dc_uF * 1e-6 * f_ripple)
    return {
        "pct_z":           f"{pct_z:.2f}",
        "pf_no_choke":     f"{pf0:.2f}",
        "pf_with_choke":   f"{pf_estimate:.2f}",
        "pf_delta":        f"+{(pf_estimate - pf0)*100:.0f} pp",
        "v_ripple_dc_pp":  f"{v_ripple_pp:.0f}",
        "c_dc_assumed":    f"{C_dc_uF:.0f}",
    }


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def _row(label: str, value: str, unit: str = "") -> str:
    val = f"{value} {unit}".strip() if unit else value
    return (f'<tr><td class="lbl">{escape(label)}</td>'
            f'<td>{val}</td></tr>')


def _kv_table(rows: dict[str, str], extra_class: str = "") -> str:
    """Render a simple two-column key/value table from a dict."""
    body = "".join(_row(k, v) for k, v in rows.items())
    cls = f' class="{extra_class}"' if extra_class else ""
    return f"<table{cls}>{body}</table>"


def _stamp(spec: Spec, core: Core, material: Material) -> str:
    """Stable short hash used as the project P/N."""
    src = f"{spec.topology}|{spec.Vin_nom_Vrms}|{spec.Pout_W}|{core.id}|{material.id}"
    return hashlib.sha1(src.encode()).hexdigest()[:8].upper()


def _topology_label(topology: str) -> str:
    return {
        "boost_ccm":     "Boost-PFC CCM Inductor",
        "passive_choke": "Passive Line Choke",
        "line_reactor":  "AC Line Reactor (50/60 Hz)",
    }.get(topology, "Inductor")


# ---------------------------------------------------------------------------
# Topology-specific specification rows
# ---------------------------------------------------------------------------
def _spec_rows_boost(spec: Spec, result: DesignResult) -> str:
    return "".join([
        _row("Topology", "Boost PFC, CCM"),
        _row("Vin range", f"{spec.Vin_min_Vrms:.0f} – {spec.Vin_max_Vrms:.0f}", "Vrms"),
        _row("Vout (DC bus)", f"{spec.Vout_V:.0f}", "V"),
        _row("Pout", f"{spec.Pout_W:.0f}", "W"),
        _row("Switching freq.", f"{spec.f_sw_kHz:.0f}", "kHz"),
        _row("Line freq.", f"{spec.f_line_Hz:.0f}", "Hz"),
        _row("Ripple target (pp)", f"{spec.ripple_pct:.0f}", "%"),
        _row("Efficiency assumed", f"{spec.eta:.2f}"),
    ])


def _spec_rows_choke(spec: Spec, result: DesignResult,
                     core: Optional[Core] = None) -> str:
    """Passive choke spec table.

    Includes the analytically estimated %Z, achievable PF, and the
    rough DC-link ripple voltage to give the engineer a sense of
    *what the choke does* — a line-frequency choke without those
    numbers is undifferentiable from any other inductor.
    """
    rows = [
        _row("Topology", "Passive line choke"),
        _row("Vin nominal", f"{spec.Vin_nom_Vrms:.0f}", "Vrms"),
        _row("Pout", f"{spec.Pout_W:.0f}", "W"),
        _row("Line freq.", f"{spec.f_line_Hz:.0f}", "Hz"),
        _row("Efficiency assumed", f"{spec.eta:.2f}"),
    ]
    if core is not None:
        ex = _passive_choke_extras(spec, result, core)
        rows.extend([
            _row("Estimated % impedance", ex["pct_z"], "%"),
            _row("PF without choke (baseline)", ex["pf_no_choke"]),
            _row("PF with this choke (est.)",
                 f'<b>{ex["pf_with_choke"]}</b>'),
            _row("PF improvement", ex["pf_delta"]),
            _row("DC-link ripple (peak-to-peak, est.)",
                 ex["v_ripple_dc_pp"], "V"),
            _row("Bulk cap assumed for ripple",
                 ex["c_dc_assumed"], "µF"),
        ])
    return "".join(rows)


def _spec_rows_line_reactor(spec: Spec, result: DesignResult) -> str:
    pct_z = result.pct_impedance_actual or 0.0
    v_drop = result.voltage_drop_pct or 0.0
    thd = result.thd_estimate_pct or 0.0
    return "".join([
        _row("Topology", "AC line reactor (diode-rectifier + DC-link)"),
        _row("Phases", "1-phase" if spec.n_phases == 1 else "3-phase"),
        _row("V line",
             f"{spec.Vin_nom_Vrms:.0f}",
             "V_LL" if spec.n_phases == 3 else "V_LN"),
        _row("Rated current", f"{spec.I_rated_Arms:.2f}", "Arms"),
        _row("Line freq.", f"{spec.f_line_Hz:.0f}", "Hz"),
        _row("Target % impedance", f"{spec.pct_impedance:.1f}", "%"),
        _row("Achieved % impedance", f"{pct_z:.2f}", "%"),
        _row("Voltage drop @ rated I", f"{v_drop:.2f}", "%"),
        _row("THD estimate", f"{thd:.1f}", "%"),
        _row("Pi (active input power)",
             f"{result.Pi_W:.0f}" if result.Pi_W else "—",
             "W" if result.Pi_W else ""),
    ])


def _result_rows(spec: Spec, result: DesignResult) -> str:
    is_lr = spec.topology == "line_reactor"
    L_unit = "mH" if is_lr else "µH"
    L_act = result.L_actual_uH / 1000 if is_lr else result.L_actual_uH
    L_req = result.L_required_uH / 1000 if is_lr else result.L_required_uH
    rows = [
        _row("Inductance (required)", f"{L_req:.2f}", L_unit),
        _row("Inductance (actual)", f"<b>{L_act:.2f}</b>", L_unit),
        _row("Number of turns N", f"<b>{result.N_turns}</b>"),
        _row("μ% at peak DC bias", f"{result.mu_pct_at_peak*100:.1f}", "%"),
        _row("H peak DC", f"{result.H_dc_peak_Oe:.0f}", "Oe"),
        _row("B peak", f"<b>{result.B_pk_T*1000:.0f}</b>", "mT"),
        _row("Bsat limit", f"{result.B_sat_limit_T*1000:.0f}", "mT"),
        _row("Saturation margin", f"{result.sat_margin_pct:.0f}", "%"),
        _row("I peak (line env.)", f"{result.I_line_pk_A:.2f}", "A"),
        _row("I RMS (line env.)", f"{result.I_line_rms_A:.2f}", "A"),
    ]
    if not is_lr:
        rows.append(_row("Δi pp max", f"{result.I_ripple_pk_pk_A:.2f}", "A"))
        rows.append(_row("I peak total", f"{result.I_pk_max_A:.2f}", "A"))
        rows.append(_row("I RMS total", f"{result.I_rms_total_A:.2f}", "A"))
    rows.append(_row("Window utilisation Ku", f"{result.Ku_actual*100:.1f}", "%"))
    return "".join(rows)


def _loss_rows(result: DesignResult) -> str:
    L = result.losses
    return "".join([
        _row("P copper DC", f"{L.P_cu_dc_W:.2f}", "W"),
        _row("P copper AC (fsw)", f"{L.P_cu_ac_W:.3f}", "W"),
        _row("P core (line band)", f"{L.P_core_line_W:.3f}", "W"),
        _row("P core (ripple, iGSE)", f"{L.P_core_ripple_W:.3f}", "W"),
        _row("P TOTAL", f"<b>{L.P_total_W:.2f}</b>", "W"),
        _row("Rdc @ T_winding", f"{result.R_dc_ohm*1000:.1f}", "mΩ"),
        _row("Rac @ fsw", f"{result.R_ac_ohm*1000:.1f}", "mΩ"),
        _row("ΔT (rise)", f"{result.T_rise_C:.0f}", "K"),
        _row("T winding", f"<b>{result.T_winding_C:.0f}</b>", "°C"),
    ])


def _validation_status_rows(result: DesignResult) -> str:
    """Tell the reader which numbers are analytical vs FEA / measured.

    Today every number in the report comes from the closed-form
    engine pass (no transient ODE, no FEA cross-check). When the
    engine starts persisting validation provenance on
    ``DesignResult`` we'll read it here; until then everything is
    "analytical (current run)". The point of carving this out as a
    section is to set the reader's confidence calibration correctly.
    """
    status: dict[str, str] = {
        "L_actual":       "Analytical (closed-form, with rolloff)",
        "B_pk":           "Analytical (V·s / N·Ae)",
        "R_dc":           "Analytical (ρ_Cu · l / A_cu, T-corrected)",
        "R_ac @ fsw":     "Analytical (Dowell skin/proximity)",
        "Core losses":    "Analytical (anchored Steinmetz / iGSE)",
        "ΔT (rise)":      "Analytical (natural-convection R_th model)",
        "FEA cross-check": "Not run for this revision (Validate tab)",
        "Transient (RK4)": "Not run for this revision",
        "Lab measurement": "Pending — see Test Plan section",
    }
    return _kv_table(status, extra_class="dim")


def _bom_rows(core: Core, wire: Wire, material: Material,
              result: DesignResult) -> str:
    wire_len_m = result.N_turns * core.MLT_mm * 1e-3
    # Prefer the catalog mass; fall back to copper-density × A_cu × L
    # so the BOM never reads "—" for a real magnet wire.
    wire_mass = _wire_mass_g(wire, wire_len_m)
    mass_origin = (
        " (catalog)" if (wire.mass_per_meter_g and wire.mass_per_meter_g > 0)
        else " (derived from Cu density)"
    )
    rows = [
        _row("Core", f"{core.vendor} — {core.part_number} ({core.shape})"),
        _row("  Ae × le × Ve",
             f"{core.Ae_mm2:.0f} mm² × {core.le_mm:.0f} mm × "
             f"{core.Ve_mm3/1000:.1f} cm³"),
        _row("  Wa × MLT",
             f"{core.Wa_mm2:.0f} mm² × {core.MLT_mm:.0f} mm"),
        _row("  AL nominal", f"{core.AL_nH:.0f}", "nH/N²"),
        _row("Material", f"{material.vendor} — {material.name}"),
        _row("  μ initial / Bsat (25°C)",
             f"{material.mu_initial:.0f} / "
             f"{material.Bsat_25C_T*1000:.0f} mT"),
        _row("  Density", f"{material.rho_kg_m3:.0f}", "kg/m³"),
        _row("Wire", f"{wire.id} ({wire.type})"),
        _row("  A_cu / d_cu",
             f"{wire.A_cu_mm2:.3f} mm² / "
             f"{wire.d_cu_mm or 0:.2f} mm"),
        _row("  Wire length", f"{wire_len_m:.2f}", "m"),
        _row("  Wire mass (est.)",
             f"{wire_mass:.0f}{mass_origin}", "g"),
    ]
    return "".join(rows)


# ---------------------------------------------------------------------------
# Page composition
# ---------------------------------------------------------------------------
def _views_grid(views: dict[str, Optional[str]]) -> str:
    """4-cell grid: iso (big) + front + top + side."""
    def cell(name: str, label: str) -> str:
        b64 = views.get(name)
        if not b64:
            return (f'<div class="view-cell missing"><span>{label}</span>'
                    '<small>(3D viewer unavailable)</small></div>')
        return (f'<div class="view-cell"><span>{label}</span>'
                f'<img src="data:image/png;base64,{b64}" alt="{label}"></div>')
    return f"""
    <div class="views-grid">
      {cell('iso', 'Isometric')}
      {cell('front', 'Front')}
      {cell('top', 'Top')}
      {cell('side', 'Side')}
    </div>
    """


def _dim_table(dims: dict[str, str]) -> str:
    rows = "".join(f'<tr><td class="lbl">{escape(k)}</td>'
                   f'<td>{escape(v)}</td></tr>'
                   for k, v in dims.items())
    return f'<table class="dim">{rows}</table>'


def _topology_section(spec: Spec, core: Core, wire: Wire,
                      material: Material, result: DesignResult) -> str:
    """Topology-specific charts laid out so they always print on the
    same A4 page. Each row pairs two narrow charts side-by-side.
    """
    blocks: list[str] = []
    wave = _waveform_plot(result, spec.topology)
    loss_b64 = _loss_plot(result)
    blocks.append('<div class="chart-row">')
    if wave:
        blocks.append(
            '<div class="chart-cell"><h3>Current Waveform</h3>'
            f'<img src="data:image/png;base64,{wave}" /></div>'
        )
    blocks.append(
        '<div class="chart-cell"><h3>Loss Breakdown</h3>'
        f'<img src="data:image/png;base64,{loss_b64}" /></div>'
    )
    blocks.append('</div>')

    if spec.topology == "boost_ccm":
        # Switching-period zoom + roll-off + η-curve.
        switch = _switching_ripple_plot(spec, result)
        if switch:
            blocks.append(
                '<h3>Switching Ripple (Vin_min, peak operating point)</h3>'
                f'<img src="data:image/png;base64,{switch}" />'
            )
        roll = _rolloff_plot(material, result)
        if roll:
            blocks.append(
                '<h3>DC Bias Roll-off</h3>'
                f'<img src="data:image/png;base64,{roll}" />'
            )
        eta_curve = _efficiency_curve_plot(spec, core, wire, material, result)
        if eta_curve:
            blocks.append(
                '<h3>Efficiency vs Load</h3>'
                f'<img src="data:image/png;base64,{eta_curve}" />'
            )
    elif spec.topology == "line_reactor":
        spec_plot = _harmonic_plot(spec, result)
        if spec_plot:
            blocks.append(
                '<h3>Harmonic Compliance — IEC 61000-3-2 / 61000-3-12 / IEEE 519</h3>'
                f'<img src="data:image/png;base64,{spec_plot}" />'
            )
        notch = _commutation_notch_block(spec, result)
        if notch:
            blocks.append(
                '<h3>Commutation Notch (6-pulse rectifier)</h3>'
                + notch
            )
    elif spec.topology == "passive_choke":
        cmp = _choke_comparison_plot(spec, result, core)
        if cmp:
            blocks.append(
                '<h3>Choke Effect — before vs after (estimated)</h3>'
                f'<img src="data:image/png;base64,{cmp}" />'
            )
        eta_curve = _efficiency_curve_plot(spec, core, wire, material, result)
        if eta_curve:
            blocks.append(
                '<h3>Efficiency vs Load</h3>'
                f'<img src="data:image/png;base64,{eta_curve}" />'
            )
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
    font: 11.5px/1.4 -apple-system, "Segoe UI", "Helvetica Neue", sans-serif;
    color: #1a1a1a; background: #fafafa;
}
.sheet {
    max-width: 940px; margin: 12px auto; background: white;
    border: 1px solid #d0d0d0; padding: 32px 36px;
    page-break-after: always;
}
.sheet:last-child { page-break-after: auto; }
.header {
    display: flex; align-items: flex-start; justify-content: space-between;
    border-bottom: 3px solid #1a1a1a; padding-bottom: 6px;
}
.header .title h1 { margin: 0; font-size: 18px; }
.header .title h2 { margin: 0; color: #555; font-weight: 400;
                     font-size: 12px; }
.header .meta { text-align: right; font-size: 10.5px; color: #444; }
.header .meta b { font-family: "SF Mono", Menlo, monospace; color: #000; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 3px;
         font-weight: 700; font-size: 11px; }
.badge.ok   { background: #e0f4e8; color: #1c7c3b;
              border: 1px solid #1c7c3b; }
.badge.bad  { background: #f8e0e0; color: #a01818;
              border: 1px solid #a01818; }
h2 { font-size: 13px; margin: 16px 0 6px;
     border-bottom: 1px solid #888; padding-bottom: 2px; }
h3 { font-size: 12px; margin: 14px 0 4px; color: #333; }
table { border-collapse: collapse; width: 100%; font-size: 10.5px;
        font-variant-numeric: tabular-nums; }
table td { padding: 2px 8px; border-bottom: 1px solid #eee;
           vertical-align: top; }
td.lbl { color: #555; width: 55%; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid table { font-size: 10.5px; }
.views-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 6px; margin-top: 8px;
}
.view-cell {
    position: relative; border: 1px solid #d0d0d0; background: #fff;
    text-align: center; aspect-ratio: 4 / 3;
    overflow: hidden;
}
.view-cell img {
    width: 100%; height: 100%; display: block;
    object-fit: contain;
}
.view-cell span {
    position: absolute; top: 4px; left: 6px; background: rgba(255,255,255,0.85);
    padding: 1px 5px; font-size: 10px; font-weight: 700; color: #444;
    border: 1px solid #ccc; letter-spacing: 0.5px; text-transform: uppercase;
}
.view-cell.missing {
    display: flex; flex-direction: column; align-items: center;
    justify-content: center; min-height: 200px; color: #999;
}
.view-cell.missing span { position: static; background: none;
                          border: none; }
.view-cell small { display: block; margin-top: 4px; font-size: 9.5px; }
img { max-width: 100%; }
.warnings {
    background: #fff7e0; border-left: 3px solid #d09000;
    padding: 8px 12px; margin: 12px 0; font-size: 10.5px;
}
.warnings ul { margin: 4px 0 0 18px; padding: 0; }
.note { color: #666; font-size: 10px; margin-top: 14px;
        font-style: italic; }
.mech-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 18px; }
.chart-row {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 12px; margin-top: 4px;
}
.chart-cell h3 { margin-top: 6px; }
.chart-cell img { width: 100%; height: auto; }
@media print {
    body { background: white; }
    .sheet { border: none; padding: 12mm 14mm; margin: 0; box-shadow: none; }
}
"""


def generate_datasheet(
    spec: Spec,
    core: Core,
    material: Material,
    wire: Wire,
    result: DesignResult,
    output_path: str | Path,
    designer: str = "—",
    revision: str = "A.0",
) -> Path:
    """Write a 3-page datasheet HTML and return its absolute path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pn = _stamp(spec, core, material)
    title = _topology_label(spec.topology)
    now = datetime.now().strftime("%Y-%m-%d")
    feasible = result.is_feasible()
    badge = ('<span class="badge ok">FEASIBLE</span>' if feasible
             else f'<span class="badge bad">{len(result.warnings)} WARNING(S)</span>')

    # Topology-specific spec table
    if spec.topology == "boost_ccm":
        spec_rows = _spec_rows_boost(spec, result)
    elif spec.topology == "line_reactor":
        spec_rows = _spec_rows_line_reactor(spec, result)
    else:
        spec_rows = _spec_rows_choke(spec, result, core=core)

    # Page 1 — mechanical & spec
    print("[datasheet] rendering 3D views (offscreen)…")
    views = render_views(core, wire, result.N_turns, material)
    dims = derive_dimensions(core)
    mech_html = (
        '<div class="mech-grid">'
        + _views_grid(views)
        + '<div>'
        + '<h3>Mechanical dimensions</h3>'
        + _dim_table(dims)
        + '<h3>Construction</h3>'
        + '<table class="dim"><tr><td class="lbl">Core shape</td>'
        + f'<td>{escape(core.shape.upper())}</td></tr>'
        + f'<tr><td class="lbl">Air gap</td><td>{core.lgap_mm:.2f} mm</td></tr>'
        + f'<tr><td class="lbl">Wire</td><td>{escape(wire.id)}</td></tr>'
        + f'<tr><td class="lbl">Turns</td><td>{result.N_turns}</td></tr>'
        + '</table>'
        + '</div></div>'
    )

    warnings_html = ""
    if result.warnings:
        items = "".join(f"<li>{escape(w)}</li>" for w in result.warnings)
        warnings_html = (
            f'<div class="warnings"><b>Warnings</b><ul>{items}</ul></div>'
        )

    # Page 2 — performance
    perf_section = _topology_section(spec, core, wire, material, result)

    # Page 3 — BOM + notes
    bom_rows = _bom_rows(core, wire, material, result)
    res_rows = _result_rows(spec, result)
    loss_rows = _loss_rows(result)

    # Validation-status block — engineer needs to know which numbers
    # are analytical, which are FEA-cross-checked, which are lab-
    # measured. Without this the report looks definitive when it's
    # actually all closed-form.
    validation_rows = _validation_status_rows(result)
    environment_table = _kv_table(_ENV_RATINGS, extra_class="dim")
    safety_table = _kv_table(_safety_table_for(spec.topology),
                              extra_class="dim")
    tolerance_table = _tolerance_rows(result, material)
    build_table = _build_instructions_rows(core, wire, result)
    test_plan_table = _test_plan_rows(spec, result, material)
    bh_plot = _bh_trajectory_plot(result, core, material)
    bh_section = (
        '<h3>B–H trajectory at operating point</h3>'
        f'<img src="data:image/png;base64,{bh_plot}" />'
    ) if bh_plot else ""
    revision_table = _revision_history_rows(revision, designer, now)
    metadata_table = _project_metadata_rows(spec, core, material, wire, pn)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)} — {pn}</title>
<style>{_CSS}</style>
</head>
<body>

<!-- ============================== PAGE 1 ============================== -->
<div class="sheet">
  <div class="header">
    <div class="title">
      <h1>{escape(title)}</h1>
      <h2>Custom design — generated by MagnaDesign</h2>
    </div>
    <div class="meta">
      <div>Project P/N: <b>{pn}</b></div>
      <div>Revision: <b>{escape(revision)}</b></div>
      <div>Designer: <b>{escape(designer)}</b></div>
      <div>Date: <b>{now}</b></div>
      <div style="margin-top:6px">Status: {badge}</div>
    </div>
  </div>

  <h2>Mechanical</h2>
  {mech_html}

  <h2>Specification</h2>
  <div class="grid">
    <table>{spec_rows}</table>
    <table>{res_rows}</table>
  </div>
</div>

<!-- ============================== PAGE 2 ============================== -->
<div class="sheet">
  <div class="header">
    <div class="title">
      <h1>{escape(title)} — Performance</h1>
      <h2>P/N {pn} · {now}</h2>
    </div>
    <div class="meta">{badge}</div>
  </div>

  <h2>Operating Point & Losses</h2>
  <div class="grid">
    <div>
      <h3>Operating point</h3>
      <table>{res_rows}</table>
    </div>
    <div>
      <h3>Losses & thermal</h3>
      <table>{loss_rows}</table>
    </div>
  </div>

  <h2>Performance Curves</h2>
  {perf_section}

  {bh_section}

  {warnings_html}
</div>

<!-- ============================== PAGE 3 ============================== -->
<div class="sheet">
  <div class="header">
    <div class="title">
      <h1>{escape(title)} — Bill of Materials & Notes</h1>
      <h2>P/N {pn} · {now}</h2>
    </div>
    <div class="meta">Revision <b>{escape(revision)}</b></div>
  </div>

  <h2>Bill of Materials</h2>
  <table>{bom_rows}</table>

  <h2>Tolerance Bands</h2>
  <p class="note" style="margin-top:0;">Acceptance bands for incoming
  inspection. Inductance band is keyed off the material family —
  silicon-steel gapped designs run wider, powder cores tighter.</p>
  {tolerance_table}

  <h2>Build Instructions</h2>
  <p class="note" style="margin-top:0;">Wind-room hand-off.
  Layer counts are estimated from the window envelope; verify
  against the actual bobbin before committing.</p>
  {build_table}

  <h2>Test Plan / Factory Acceptance Test</h2>
  <p class="note" style="margin-top:0;">Every parameter QA must
  measure before signing off the batch. Pass bands inherit from the
  Tolerance section above so the wind-room and the QA bench agree.</p>
  {test_plan_table}

  <h2>Environmental Ratings</h2>
  {environment_table}

  <h2>Insulation &amp; Safety</h2>
  {safety_table}

  <h2>Validation Status</h2>
  <p class="note" style="margin-top:0;">Provenance of every figure
  in this datasheet — useful when stakeholders ask "is this number
  measured?".</p>
  {validation_rows}

  <h2>Engineering Notes</h2>
  <div class="note">{escape(result.notes or '—')}</div>

  <h2>Revision History</h2>
  {revision_table}

  <h2>Project Metadata</h2>
  <p class="note" style="margin-top:0;">Identifiers needed to
  reproduce this design in MagnaDesign. The engine is
  deterministic — feeding the four ids below back into the same
  topology recovers an identical result.</p>
  {metadata_table}

  <h2>Disclaimer</h2>
  <div class="note">
    This datasheet describes a custom inductor designed with the
    MagnaDesign tool. Curated material parameters come from
    manufacturer datasheets and Steinmetz fits to vendor data; cores
    and wires are dimensional database entries. Always verify
    against a built sample (LCR meter for L &amp; Rdc, dyno-loaded
    operation for thermal) before committing to production.
  </div>

  <p style="margin-top:24px; font-size:9.5px; color:#888;">
    Generated by MagnaDesign · {now}
  </p>
</div>

</body>
</html>"""
    output_path.write_text(html, encoding="utf-8")
    return output_path.resolve()
