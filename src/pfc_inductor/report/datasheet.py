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
# HTML helpers
# ---------------------------------------------------------------------------
def _row(label: str, value: str, unit: str = "") -> str:
    val = f"{value} {unit}".strip() if unit else value
    return (f'<tr><td class="lbl">{escape(label)}</td>'
            f'<td>{val}</td></tr>')


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


def _spec_rows_choke(spec: Spec, result: DesignResult) -> str:
    return "".join([
        _row("Topology", "Passive line choke"),
        _row("Vin nominal", f"{spec.Vin_nom_Vrms:.0f}", "Vrms"),
        _row("Pout", f"{spec.Pout_W:.0f}", "W"),
        _row("Line freq.", f"{spec.f_line_Hz:.0f}", "Hz"),
        _row("Efficiency assumed", f"{spec.eta:.2f}"),
    ])


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


def _bom_rows(core: Core, wire: Wire, material: Material,
              result: DesignResult) -> str:
    wire_len_m = result.N_turns * core.MLT_mm * 1e-3
    wire_mass = wire_len_m * (wire.mass_per_meter_g or 0.0)
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
             f"{wire_mass:.0f}" if wire_mass else "—",
             "g" if wire_mass else ""),
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
        roll = _rolloff_plot(material, result)
        if roll:
            blocks.append(
                '<h3>DC Bias Roll-off</h3>'
                f'<img src="data:image/png;base64,{roll}" />'
            )
    elif spec.topology == "line_reactor":
        spec_plot = _harmonic_plot(spec, result)
        if spec_plot:
            blocks.append(
                '<h3>IEC 61000-3-2 Class D Compliance</h3>'
                f'<img src="data:image/png;base64,{spec_plot}" />'
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
        spec_rows = _spec_rows_choke(spec, result)

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

  <h2>Engineering Notes</h2>
  <div class="note">{escape(result.notes or '—')}</div>

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
