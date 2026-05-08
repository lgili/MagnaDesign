"""Generate a self-contained HTML report for a PFC inductor design.

The HTML embeds plots as base64 PNG so the file is portable (no asset folder).
For PDF: open the HTML in a browser and use Print -> Save as PDF, or run a
headless converter (weasyprint/wkhtmltopdf) externally.
"""

from __future__ import annotations

import base64
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")  # non-interactive
import matplotlib.pyplot as plt

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.physics import rolloff as rf


def _plot_to_base64(fig) -> str:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _waveform_plot(result: DesignResult) -> str:
    fig, ax = plt.subplots(figsize=(8, 3.5), tight_layout=True)
    if result.waveform_t_s and result.waveform_iL_A:
        t_ms = np.array(result.waveform_t_s) * 1000.0
        iL = np.array(result.waveform_iL_A)
        ax.plot(t_ms, iL, color="#3a78b5", linewidth=1.5)
        ax.fill_between(t_ms, 0, iL, alpha=0.15, color="#3a78b5")
        ax.set_xlabel("t [ms]")
        ax.set_ylabel("iL peak [A]")
        ax.set_title("Inductor current — half line cycle")
        ax.grid(True, alpha=0.4)
    return _plot_to_base64(fig)


def _loss_plot(result: DesignResult) -> str:
    fig, ax = plt.subplots(figsize=(6, 3.5), tight_layout=True)
    L = result.losses
    labels = ["Cu DC", "Cu AC", "Core (line)", "Core (ripple)"]
    values = [L.P_cu_dc_W, L.P_cu_ac_W, L.P_core_line_W, L.P_core_ripple_W]
    colors = ["#3a78b5", "#7eaee0", "#b53a3a", "#e07e7e"]
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylabel("Loss [W]")
    ax.set_title(f"Losses (total = {L.P_total_W:.2f} W)")
    ax.grid(True, axis="y", alpha=0.4)
    for b, v in zip(bars, values, strict=False):
        ax.text(
            b.get_x() + b.get_width() / 2,
            v + 0.02,
            f"{v:.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    return _plot_to_base64(fig)


def _rolloff_plot(material: Material, result: DesignResult) -> str | None:
    if material.rolloff is None:
        return None
    fig, ax = plt.subplots(figsize=(6, 3.5), tight_layout=True)
    H = np.logspace(0, 3.5, 200)
    mu = np.array([rf.mu_pct(material, h) for h in H]) * 100
    ax.semilogx(H, mu, linewidth=1.8)
    ax.axvline(
        result.H_dc_peak_Oe,
        color="r",
        linestyle="--",
        alpha=0.6,
        label=f"H operating = {result.H_dc_peak_Oe:.0f} Oe",
    )
    ax.axhline(
        result.mu_pct_at_peak * 100,
        color="r",
        linestyle=":",
        alpha=0.6,
        label=f"μ% = {result.mu_pct_at_peak * 100:.1f}%",
    )
    ax.set_xlabel("H [Oe]")
    ax.set_ylabel("μ% (% initial)")
    ax.set_title(f"Permeability rolloff — {material.name}")
    ax.set_ylim(0, 105)
    ax.legend(loc="lower left")
    ax.grid(True, which="both", alpha=0.4)
    return _plot_to_base64(fig)


def _row(label: str, value: str, unit: str = "") -> str:
    return f'<tr><td class="lbl">{escape(label)}</td><td>{escape(value)}{(" " + unit) if unit else ""}</td></tr>'


def generate_html_report(
    spec: Spec,
    core: Core,
    material: Material,
    wire: Wire,
    result: DesignResult,
    output_path: str | Path,
    title: str = "PFC Inductor Design",
) -> Path:
    """Write an HTML report and return its absolute path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img_wave = _waveform_plot(result)
    img_loss = _loss_plot(result)
    img_roll = _rolloff_plot(material, result)

    feasible = result.is_feasible()
    feasible_html = (
        '<span class="badge ok">FEASIBLE</span>'
        if feasible
        else '<span class="badge bad">INFEASIBLE</span>'
    )

    warnings_html = ""
    if result.warnings:
        items = "".join(f"<li>{escape(w)}</li>" for w in result.warnings)
        warnings_html = f'<div class="warnings"><h3>Warnings</h3><ul>{items}</ul></div>'

    # Topology-aware spec rows. Buck-CCM swaps the AC-line block for
    # the DC input range; AC topologies keep the original Vin/f_line
    # rows. The shared rows (Vout, Pout, η, fsw, thermal, Ku, Bsat)
    # are appended unconditionally.
    if spec.topology == "buck_ccm":
        from pfc_inductor.topology import buck_ccm

        Vin_min = buck_ccm._vin_min(spec)
        Vin_max = buck_ccm._vin_max(spec)
        Vin_nom = buck_ccm._vin_nom(spec)
        spec_rows_input = [
            _row("Topology", "buck_ccm"),
            _row("Vin DC (range)", f"{Vin_min:.2f}–{Vin_max:.2f}", "V_dc"),
            _row("Vin DC nominal", f"{Vin_nom:.2f}", "V_dc"),
            _row("Vout (regulated)", f"{spec.Vout_V:.2f}", "V_dc"),
        ]
    elif spec.topology == "flyback":
        from pfc_inductor.topology import flyback as _fb

        Vin_min = _fb._vin_min(spec)
        Vin_max = _fb._vin_max(spec)
        Vin_nom = _fb._vin_nom(spec)
        n_ratio = (
            result.Np_turns / max(result.Ns_turns, 1)
            if (result.Np_turns and result.Ns_turns)
            else _fb.optimal_turns_ratio(spec)
        )
        mode = (spec.flyback_mode or "dcm").upper()
        spec_rows_input = [
            _row("Topology", f"flyback ({mode})"),
            _row("Vin DC (range)", f"{Vin_min:.2f}–{Vin_max:.2f}", "V_dc"),
            _row("Vin DC nominal", f"{Vin_nom:.2f}", "V_dc"),
            _row("Vout (regulated)", f"{spec.Vout_V:.2f}", "V_dc"),
            _row("Turns ratio Np/Ns", f"{n_ratio:.2f}"),
        ]
    else:
        spec_rows_input = [
            _row("Topology", spec.topology),
            _row("Vin (range)", f"{spec.Vin_min_Vrms:.0f}–{spec.Vin_max_Vrms:.0f}", "Vrms"),
            _row("Vin nominal", f"{spec.Vin_nom_Vrms:.0f}", "Vrms"),
            _row("f line", f"{spec.f_line_Hz:.0f}", "Hz"),
            _row("Vout (DC bus)", f"{spec.Vout_V:.0f}", "V"),
        ]
    ripple_label, ripple_value, ripple_unit = (
        (
            "Δi_pp / Iout (target)",
            f"{(spec.ripple_ratio or spec.ripple_pct / 100.0) * 100:.0f}",
            "% of Iout",
        )
        if spec.topology == "buck_ccm"
        else ("Ripple target (pp)", f"{spec.ripple_pct:.0f}", "%")
    )
    spec_rows = "".join(
        [
            *spec_rows_input,
            _row("Pout", f"{spec.Pout_W:.0f}", "W"),
            _row("η assumed", f"{spec.eta:.2f}", ""),
            _row("fsw", f"{spec.f_sw_kHz:.0f}", "kHz"),
            _row(ripple_label, ripple_value, ripple_unit),
            _row("T ambient", f"{spec.T_amb_C:.0f}", "°C"),
            _row("T max winding", f"{spec.T_max_C:.0f}", "°C"),
            _row("Ku max", f"{spec.Ku_max * 100:.0f}", "%"),
            _row("Bsat margin", f"{spec.Bsat_margin * 100:.0f}", "%"),
        ]
    )

    sel_rows = "".join(
        [
            _row("Core", f"{core.vendor} — {core.part_number} ({core.shape})"),
            _row("Material", f"{material.vendor} — {material.name}  μ={material.mu_initial:.0f}"),
            _row(
                "Bsat (25/100 °C)",
                f"{material.Bsat_25C_T * 1000:.0f} / {material.Bsat_100C_T * 1000:.0f}",
                "mT",
            ),
            _row("Ae", f"{core.Ae_mm2:.1f}", "mm²"),
            _row("le", f"{core.le_mm:.1f}", "mm"),
            _row("Ve", f"{core.Ve_mm3 / 1000:.1f}", "cm³"),
            _row("Wa (window)", f"{core.Wa_mm2:.1f}", "mm²"),
            _row("MLT", f"{core.MLT_mm:.1f}", "mm"),
            _row("AL nominal", f"{core.AL_nH:.0f}", "nH/N²"),
            _row("Wire", f"{wire.id} ({wire.type}, A_cu={wire.A_cu_mm2:.3f} mm²)"),
        ]
    )

    res_rows = "".join(
        [
            _row("L required", f"{result.L_required_uH:.0f}", "µH"),
            _row("L actual (with rolloff)", f"{result.L_actual_uH:.0f}", "µH"),
            _row("N (turns)", f"{result.N_turns}"),
            _row("μ% at DC peak", f"{result.mu_pct_at_peak * 100:.1f}", "%"),
            _row("Peak DC H", f"{result.H_dc_peak_Oe:.0f}", "Oe"),
            _row("Peak B", f"{result.B_pk_T * 1000:.0f}", "mT"),
            _row("B limit (Bsat·(1−margin))", f"{result.B_sat_limit_T * 1000:.0f}", "mT"),
            _row("Saturation margin", f"{result.sat_margin_pct:.0f}", "%"),
            _row("Line peak I", f"{result.I_line_pk_A:.2f}", "A"),
            _row("Line RMS I", f"{result.I_line_rms_A:.2f}", "A"),
            _row("Max peak-to-peak ripple", f"{result.I_ripple_pk_pk_A:.2f}", "A"),
            _row("Total peak I", f"{result.I_pk_max_A:.2f}", "A"),
            _row("Total RMS I", f"{result.I_rms_total_A:.2f}", "A"),
            _row("Ku actual", f"{result.Ku_actual * 100:.1f}", "%"),
        ]
    )

    L = result.losses
    loss_rows = "".join(
        [
            _row("P copper DC", f"{L.P_cu_dc_W:.2f}", "W"),
            _row("P copper AC (fsw)", f"{L.P_cu_ac_W:.3f}", "W"),
            _row("P core (line)", f"{L.P_core_line_W:.3f}", "W"),
            _row("P core (ripple, iGSE)", f"{L.P_core_ripple_W:.3f}", "W"),
            _row("P total", f"<b>{L.P_total_W:.2f}</b>", "W"),
            _row("Rdc (at final T)", f"{result.R_dc_ohm * 1000:.1f}", "mΩ"),
            _row("Rac at fsw", f"{result.R_ac_ohm * 1000:.1f}", "mΩ"),
            _row("ΔT", f"{result.T_rise_C:.0f}", "K"),
            _row("T winding", f"<b>{result.T_winding_C:.0f}</b>", "°C"),
        ]
    )

    rolloff_section = ""
    if img_roll:
        rolloff_section = (
            "<h2>Permeability rolloff</h2>"
            f'<img src="data:image/png;base64,{img_roll}" alt="Rolloff curve" />'
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          max-width: 1100px; margin: 24px auto; padding: 0 24px; color: #222; }}
  h1 {{ border-bottom: 2px solid #3a78b5; padding-bottom: 6px; }}
  h2 {{ margin-top: 28px; color: #3a78b5; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0 16px; }}
  td {{ padding: 4px 10px; border-bottom: 1px solid #eee; font-variant-numeric: tabular-nums; }}
  td.lbl {{ color: #555; width: 40%; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px;
            font-weight: bold; font-size: 0.9em; }}
  .badge.ok {{ background: #e0f4e8; color: #1c7c3b; }}
  .badge.bad {{ background: #f8e0e0; color: #a01818; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  img {{ max-width: 100%; height: auto; border: 1px solid #eee; border-radius: 4px; }}
  .warnings {{ background: #fff7e0; border-left: 4px solid #d09000;
               padding: 12px 16px; margin: 16px 0; }}
  .warnings ul {{ margin: 4px 0 0 18px; padding: 0; }}
  .meta {{ color: #888; font-size: 0.85em; }}
</style>
</head>
<body>

<h1>{escape(title)}</h1>
<p class="meta">Generated on {now} by MagnaDesign · Status: {feasible_html}</p>

{warnings_html}

<h2>Design specifications</h2>
<table>{spec_rows}</table>

<h2>Selection</h2>
<table>{sel_rows}</table>

<h2>Electrical / magnetic results</h2>
<div class="grid">
  <table>{res_rows}</table>
  <table>{loss_rows}</table>
</div>

<h2>Inductor current waveform</h2>
<img src="data:image/png;base64,{img_wave}" alt="Inductor current waveform" />

<h2>Loss breakdown</h2>
<img src="data:image/png;base64,{img_loss}" alt="Loss breakdown" />

{rolloff_section}

<p class="meta">{escape(result.notes)}</p>

</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path.resolve()
