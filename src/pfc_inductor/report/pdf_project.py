"""Native PDF project / engineering report (ReportLab + matplotlib).

Where the *datasheet* (``pdf_report.py``) is a customer-facing
summary — inputs in, BOM/spec/test plan out — the **project report**
documents *how* the design was derived: theory paragraphs,
symbolic equations, the same equations with the project's values
substituted, and the calculated result. Many engineering teams need
this artefact to file the design in their internal project-tracking
system. Without it they re-derive the calculations by hand from
MagnaDesign's outputs, which loses the traceability the report is
supposed to provide.

Public API
----------
``generate_project_report(spec, core, material, wire, result,
output_path, designer, revision, project_id) -> Path``. Mirrors
``generate_pdf_datasheet`` but the signature carries a
``project_id`` field so customers can tag the report with their
internal project number.

Layout
------
A4 portrait, 18 mm margins (slightly narrower than the datasheet so
the text-heavy body reads better at the engineer's desk). Per-
topology body builders pick the right derivation chain — boost-CCM
walks Erickson Ch.18; line reactor walks Pomilio Cap.11 / NEMA;
passive choke walks Erickson Ch.18 (passive PFC).

Equation rendering
------------------
matplotlib's mathtext backend renders LaTeX-style strings to
tight-cropped PNGs which we embed as flowables. No external LaTeX
install needed — mathtext ships with matplotlib. The
``_eqn_block`` helper takes ``(latex, with_values, result)`` and
stacks the three lines as the standard "equation → substitute →
result" pattern engineers already write by hand:

    L = (V_in · D · T_sw) / Δi
      = (220 V × 0.5 × 1.92 µs) / 3 A
      = 70.4 µH

Style + font infrastructure (palette, paragraph styles, table
styles, page decoration) come from ``pdf_report.py`` so a customer
who receives both artefacts (datasheet + project report) sees
consistent typography across the two.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Image as RLImage

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.report.pdf_report import (
    _fig_bh_trajectory,
    _fig_loss_breakdown,
    _fig_waveform,
    _mpl_flowable,
    _Palette,
    _build_styles,
    _kv_table_style,
    _register_fonts,
)

# ---------------------------------------------------------------------------
# Equation rendering — matplotlib mathtext to PNG flowable.
#
# Engineers reading the report scan equations more than they read prose,
# so we want them tight, sharp, and consistent in size. Rendering at
# 200 dpi gives a sharp print at A4 column width without the file
# bloating from oversized figures.
# ---------------------------------------------------------------------------
def _eqn_image(
    latex: str,
    *,
    fontsize: int = 13,
    dpi: int = 200,
    color: str = "#1a1a1a",
) -> RLImage:
    """Render a LaTeX-style math string to a tight-cropped PNG flowable.

    Uses matplotlib's mathtext backend (no external LaTeX install
    required). The figure is sized minimally — ``bbox_inches="tight"``
    crops to the actual equation extent — and saved with a
    transparent background so the PDF page colour shows through.
    """
    fig = plt.figure(figsize=(0.01, 0.01))  # placeholder; tight-bbox resizes
    fig.text(0.0, 0.0, f"${latex}$", fontsize=fontsize, color=color)
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=dpi,
        bbox_inches="tight", pad_inches=0.02,
        transparent=True,
    )
    plt.close(fig)
    buf.seek(0)
    img = RLImage(buf)
    # Scale down by the DPI ratio so the rendered size matches the
    # nominal point size we asked for. Without this, mathtext at
    # 200 dpi prints physically large because matplotlib treats the
    # bitmap as 72-dpi-equivalent.
    iw, ih = img.imageWidth, img.imageHeight
    scale = 72.0 / dpi
    img.drawWidth = iw * scale
    img.drawHeight = ih * scale
    return img


def _eqn_block(
    latex: str,
    *,
    with_values: Optional[str] = None,
    result: Optional[str] = None,
    note: Optional[str] = None,
    fonts: dict[str, str],
    styles: dict[str, ParagraphStyle],
) -> KeepTogether:
    """Stack the standard 3-line equation pattern as a single block.

    - ``latex``: LaTeX string for the symbolic form (no ``$``
      delimiters; ``_eqn_image`` adds them).
    - ``with_values``: optional second line with the spec's actual
      values substituted, written as plain Unicode so · / × / Greek
      letters land verbatim (mathtext's verbose syntax for a one-
      line "L = (220 V × 0.5 × 1.92 µs) / 3 A" is more pain than
      it's worth — the substitution line just needs to be readable,
      not typeset).
    - ``result``: optional bold result line ("L = 70.4 µH").
    - ``note``: optional muted-italic line below the result for the
      equation reference ("Erickson eq. 18-22") or a caveat
      ("at low-line, worst case").

    Wrapped in ``KeepTogether`` so a page break never splits the
    derivation across pages — a stranded "= 70.4 µH" with the
    setup on the previous page is the single biggest readability
    glitch of equation-heavy reports.
    """
    flowables: list = [_eqn_image(latex, fontsize=14)]
    if with_values:
        # Indent slightly so the eye reads it as a continuation of the
        # equation above, not as a new statement.
        flowables.append(Paragraph(
            f"&nbsp;&nbsp;&nbsp;&nbsp;= {with_values}",
            styles["body"],
        ))
    if result:
        flowables.append(Paragraph(
            f"&nbsp;&nbsp;&nbsp;&nbsp;<b>= {result}</b>",
            styles["body"],
        ))
    if note:
        flowables.append(Paragraph(
            f"<i>{note}</i>", styles["note"],
        ))
    flowables.append(Spacer(1, 2 * mm))
    return KeepTogether(flowables)


# ---------------------------------------------------------------------------
# Page geometry. A4 portrait at 18 mm margins → 174 mm usable width.
# ---------------------------------------------------------------------------
_USABLE_WIDTH_MM = 210 - 2 * 18  # 174


# ---------------------------------------------------------------------------
# Helpers shared with the datasheet.
# ---------------------------------------------------------------------------
def _stamp(spec: Spec, core: Core, material: Material) -> str:
    import hashlib
    src = f"{spec.topology}|{spec.Vin_nom_Vrms}|{spec.Pout_W}|{core.id}|{material.id}"
    return hashlib.sha1(src.encode()).hexdigest()[:8].upper()


def _topology_label(topology: str) -> str:
    return {
        "boost_ccm":     "Active Boost-PFC CCM Inductor",
        "passive_choke": "Passive Line Choke",
        "line_reactor":  "AC Line Reactor (50/60 Hz)",
    }.get(topology, "Inductor")


def _project_header(
    title: str, project_id: str, designer: str, revision: str,
    now: str, *, fonts: dict[str, str],
    styles: dict[str, ParagraphStyle],
) -> Table:
    """Two-column header. Left: title + "Engineering project report"
    subtitle. Right: project id, designer, revision, date.
    """
    left = [
        Paragraph(title, styles["title"]),
        Paragraph("Engineering project report — generated by MagnaDesign",
                   styles["subtitle"]),
    ]
    right = [
        Paragraph(f"Project: <b>{project_id}</b>", styles["meta_value"]),
        Paragraph(f"Revision: <b>{revision}</b>", styles["meta"]),
        Paragraph(f"Designer: <b>{designer}</b>", styles["meta"]),
        Paragraph(f"Date: <b>{now}</b>", styles["meta"]),
    ]
    table = Table([[left, right]], colWidths=[110 * mm, 64 * mm])
    table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW",     (0, 0), (-1, -1), 1.2, _Palette.rule),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return table


def _kv_flow(rows: list[tuple[str, str]], width_mm: float,
              fonts: dict[str, str], styles: dict[str, ParagraphStyle],
              label_col_pct: float = 0.45) -> Table:
    """Two-column key/value table at ``width_mm`` total width.
    Slightly wider label column than the datasheet's KV (0.45 vs
    0.42) because the project report uses longer labels (e.g.
    "Effective magnetic length" instead of just "le")."""
    label_w = width_mm * label_col_pct * mm
    value_w = width_mm * (1.0 - label_col_pct) * mm
    data = [
        [Paragraph(k, styles["body"]), Paragraph(v, styles["body"])]
        for (k, v) in rows
    ]
    t = Table(data, colWidths=[label_w, value_w])
    t.setStyle(_kv_table_style(fonts))
    return t


# ---------------------------------------------------------------------------
# Project inputs — full spec dump, topology-aware. The engineer reading
# the report needs every input that fed the calculation; without these
# the substituted equations (PROJ-3/4) become floating numbers.
# ---------------------------------------------------------------------------
def _spec_input_data(spec: Spec) -> list[tuple[str, str]]:
    """KV rows describing the input specification."""
    if spec.topology == "boost_ccm":
        rows = [
            ("Topology",                "Active boost-PFC, CCM"),
            ("Input voltage range",
             f"{spec.Vin_min_Vrms:.0f} – {spec.Vin_max_Vrms:.0f} Vrms "
             f"(nom. {spec.Vin_nom_Vrms:.0f} Vrms)"),
            ("Output voltage (DC bus)", f"{spec.Vout_V:.0f} V"),
            ("Output power (rated)",    f"{spec.Pout_W:.0f} W"),
            ("Switching frequency",     f"{spec.f_sw_kHz:.0f} kHz"),
            ("Line frequency",          f"{spec.f_line_Hz:.0f} Hz"),
            ("Inductor ripple target",  f"{spec.ripple_pct:.0f} % of I_pk"),
            ("Efficiency assumed",      f"{spec.eta:.2f}"),
        ]
    elif spec.topology == "line_reactor":
        rows = [
            ("Topology",
             f"AC line reactor — {spec.n_phases}φ "
             "(diode-rectifier + DC-link)"),
            ("Line voltage",
             f"{spec.Vin_nom_Vrms:.0f} "
             f"{'V_LL' if spec.n_phases == 3 else 'V_LN'}"),
            ("Rated current",        f"{spec.I_rated_Arms:.2f} Arms"),
            ("Line frequency",       f"{spec.f_line_Hz:.0f} Hz"),
            ("% impedance target",   f"{spec.pct_impedance:.1f} %"),
            ("Efficiency assumed",   f"{spec.eta:.2f}"),
        ]
    else:  # passive_choke
        rows = [
            ("Topology",          "Passive line choke (DC-side)"),
            ("Input voltage",     f"{spec.Vin_nom_Vrms:.0f} Vrms"),
            ("Output power",      f"{spec.Pout_W:.0f} W"),
            ("Line frequency",    f"{spec.f_line_Hz:.0f} Hz"),
            ("Efficiency assumed", f"{spec.eta:.2f}"),
        ]
    # Common environmental constraints — every topology checks
    # against these in the thermal solve.
    rows.extend([
        ("Ambient temperature",  f"{spec.T_amb_C:.0f} °C"),
        ("Max winding temperature", f"{spec.T_max_C:.0f} °C"),
        ("Bsat margin",          f"{spec.Bsat_margin * 100:.0f} %"),
        ("Window utilisation max (Ku_max)",
         f"{spec.Ku_max * 100:.0f} %"),
    ])
    return rows


def _section_project_inputs(spec: Spec, fonts, styles) -> list:
    return [
        Paragraph("1. Project specification", styles["h2"]),
        Paragraph(
            "The design proceeds from the inputs listed below. Every "
            "subsequent equation references one or more of these "
            "values; the substituted-form line shows where each "
            "number entered the calculation.",
            styles["body"],
        ),
        _kv_flow(_spec_input_data(spec), _USABLE_WIDTH_MM,
                  fonts, styles),
    ]


# ---------------------------------------------------------------------------
# Selected components — core / material / wire. The engineer needs to
# see *what was picked* alongside the constraints (Ae, Wa, le, AL,
# MLT, μ, Bsat, A_cu) so the subsequent calculation lines can be
# verified by hand.
# ---------------------------------------------------------------------------
def _component_data_core(core: Core) -> list[tuple[str, str]]:
    return [
        ("Vendor / part number",  f"{core.vendor} — {core.part_number}"),
        ("Shape",                 core.shape.upper()),
        ("Effective area Ae",     f"{core.Ae_mm2:.1f} mm²"),
        ("Effective length le",   f"{core.le_mm:.1f} mm"),
        ("Effective volume Ve",   f"{core.Ve_mm3 / 1000:.2f} cm³"),
        ("Window area Wa",        f"{core.Wa_mm2:.1f} mm²"),
        ("Mean length per turn MLT", f"{core.MLT_mm:.1f} mm"),
        ("Inductance factor AL",  f"{core.AL_nH:.0f} nH/N²"),
        ("Air gap (centre leg)",
         f"{core.lgap_mm:.2f} mm" if core.lgap_mm > 0 else "no air gap"),
    ]


def _component_data_material(material: Material) -> list[tuple[str, str]]:
    return [
        ("Vendor / family",      f"{material.vendor} — {material.name}"),
        ("Type",                 material.type),
        ("Initial permeability", f"μᵢ = {material.mu_initial:.0f}"),
        ("Saturation flux (25°C)", f"{material.Bsat_25C_T * 1000:.0f} mT"),
        ("Saturation flux (100°C)",
         f"{material.Bsat_100C_T * 1000:.0f} mT"),
        ("Density",              f"{material.rho_kg_m3:.0f} kg/m³"),
    ]


def _component_data_wire(wire: Wire,
                          result: DesignResult) -> list[tuple[str, str]]:
    rows = [
        ("Identifier",         f"{wire.id} ({wire.type})"),
        ("Copper area A_cu",   f"{wire.A_cu_mm2:.3f} mm²"),
    ]
    if wire.d_cu_mm:
        rows.append(("Copper diameter d_cu", f"{wire.d_cu_mm:.2f} mm"))
    if wire.d_iso_mm:
        rows.append(("Insulated diameter d_iso", f"{wire.d_iso_mm:.2f} mm"))
    rows.append((
        "Window utilisation Ku (achieved)",
        f"{result.Ku_actual * 100:.1f} %",
    ))
    return rows


def _section_components(core: Core, material: Material, wire: Wire,
                          result: DesignResult, fonts, styles) -> list:
    flowables = [
        Paragraph("2. Selected components", styles["h2"]),
        Paragraph(
            "The optimiser picked the components below from the "
            "in-app catalogue. The values that follow are the "
            "datasheet-grade parameters used directly in the "
            "calculations of section 3 onwards.",
            styles["body"],
        ),
        Paragraph("2.1 Core", styles["h3"]),
        _kv_flow(_component_data_core(core), _USABLE_WIDTH_MM,
                  fonts, styles),
        Paragraph("2.2 Magnetic material", styles["h3"]),
        _kv_flow(_component_data_material(material), _USABLE_WIDTH_MM,
                  fonts, styles),
        Paragraph("2.3 Winding wire", styles["h3"]),
        _kv_flow(_component_data_wire(wire, result), _USABLE_WIDTH_MM,
                  fonts, styles),
    ]
    return flowables


# ---------------------------------------------------------------------------
# Final summary table — appears at the end of the report so the reader
# can see the complete result without scrolling back through the
# derivation chain.
# ---------------------------------------------------------------------------
def _section_result_summary(spec: Spec, result: DesignResult,
                              fonts, styles) -> list:
    is_lr = spec.topology == "line_reactor"
    L_unit = "mH" if is_lr else "µH"
    L_act = result.L_actual_uH / 1000 if is_lr else result.L_actual_uH
    rows: list[tuple[str, str]] = [
        ("Inductance L",          f"{L_act:.2f} {L_unit}"),
        ("Number of turns N",     f"{result.N_turns}"),
        ("Peak flux density B_pk", f"{result.B_pk_T * 1000:.0f} mT"),
        ("Bsat limit",            f"{result.B_sat_limit_T * 1000:.0f} mT"),
        ("Saturation margin",     f"{result.sat_margin_pct:.0f} %"),
        ("Peak current I_pk",     f"{result.I_pk_max_A:.2f} A"),
        ("Total RMS current",     f"{result.I_rms_total_A:.2f} A"),
        ("DC resistance Rdc (hot)",
         f"{result.R_dc_ohm * 1000:.1f} mΩ"),
        ("AC resistance Rac @ fsw",
         f"{result.R_ac_ohm * 1000:.1f} mΩ"),
        ("Copper losses (DC + AC)",
         f"{result.losses.P_cu_dc_W + result.losses.P_cu_ac_W:.2f} W"),
        ("Core losses (line + ripple)",
         f"{result.losses.P_core_line_W + result.losses.P_core_ripple_W:.2f} W"),
        ("Total losses P_total",
         f"{result.losses.P_total_W:.2f} W"),
        ("Temperature rise ΔT",   f"{result.T_rise_C:.0f} K"),
        ("Winding temperature T_w",
         f"{result.T_winding_C:.0f} °C"),
        ("Window utilisation Ku", f"{result.Ku_actual * 100:.1f} %"),
        ("Status",
         "FEASIBLE" if result.is_feasible() else "WARNINGS"),
    ]
    return [
        Paragraph("Final summary", styles["h2"]),
        Paragraph(
            "Consolidated view of the design point computed in the "
            "preceding sections. All values converged at the steady-"
            "state winding temperature.",
            styles["body"],
        ),
        _kv_flow(rows, _USABLE_WIDTH_MM, fonts, styles,
                  label_col_pct=0.55),
    ]


# ---------------------------------------------------------------------------
# Verification plots — waveform + loss breakdown + B–H trajectory.
# Imported from pdf_report so the typography matches the datasheet's
# performance section. Each plot is paired with its h3 header inside
# a KeepTogether so a page break never orphans a header.
# ---------------------------------------------------------------------------
def _section_verification(spec: Spec, core: Core, material: Material,
                            wire: Wire, result: DesignResult,
                            fonts, styles) -> list:
    flowables: list = [
        Paragraph("Verification plots", styles["h2"]),
        Paragraph(
            "Steady-state waveform, loss breakdown, and operating-"
            "point B–H trajectory at the chosen design point. The "
            "plots are the same the datasheet presents — repeated "
            "here so the project report stands on its own without "
            "requiring the datasheet alongside.",
            styles["body"],
        ),
    ]
    fig_wave = _fig_waveform(result, spec.topology)
    if fig_wave is not None:
        flowables.append(KeepTogether([
            Paragraph("Inductor current — steady state", styles["h3"]),
            _mpl_flowable(fig_wave, _USABLE_WIDTH_MM),
        ]))
    fig_loss = _fig_loss_breakdown(result)
    if fig_loss is not None:
        flowables.append(KeepTogether([
            Paragraph("Loss breakdown", styles["h3"]),
            _mpl_flowable(fig_loss, _USABLE_WIDTH_MM),
        ]))
    fig_bh = _fig_bh_trajectory(result, core, material)
    if fig_bh is not None:
        flowables.append(KeepTogether([
            Paragraph("B–H trajectory at operating point",
                       styles["h3"]),
            _mpl_flowable(fig_bh, _USABLE_WIDTH_MM),
        ]))
    return flowables


# ---------------------------------------------------------------------------
# Per-topology body builders — derive the design step-by-step, with
# theory paragraphs, symbolic equations, substituted-form lines, and
# the numerical result the engine computed. Each topology's chain
# lives in its own helper for readability; the common dispatcher
# below picks the right one.
# ---------------------------------------------------------------------------
def _section_topology_body(spec: Spec, core: Core, material: Material,
                             wire: Wire, result: DesignResult,
                             fonts, styles) -> list:
    if spec.topology == "boost_ccm":
        return _body_boost_ccm(
            spec, core, material, wire, result, fonts, styles,
        )
    if spec.topology == "line_reactor":
        return _body_line_reactor(
            spec, core, material, wire, result, fonts, styles,
        )
    if spec.topology == "passive_choke":
        return _body_passive_choke(
            spec, core, material, wire, result, fonts, styles,
        )
    return []


# ---------------------------------------------------------------------------
# Boost-CCM derivation chain.
#
# Reference: Erickson & Maksimovic Ch. 18 (closed-loop average-current
# CCM PFC), ON Semi AND8016, Infineon AN_201111_PL52_001. The engine
# in ``topology/boost_ccm.py`` implements the same equations; we
# reproduce them verbatim so the report's numbers match the engine's
# to the displayed precision.
# ---------------------------------------------------------------------------
def _body_boost_ccm(spec: Spec, core: Core, material: Material,
                     wire: Wire, result: DesignResult,
                     fonts, styles) -> list:
    import math
    # Worst-case operating point — low line for currents.
    Vin_design = spec.Vin_min_Vrms
    Vin_pk = math.sqrt(2.0) * Vin_design
    P_in = spec.Pout_W / spec.eta
    I_pk = math.sqrt(2.0) * P_in / Vin_design
    I_rms_line = spec.Pout_W / (spec.eta * Vin_design)
    fsw_Hz = spec.f_sw_kHz * 1000.0
    delta_max_A = (spec.ripple_pct / 100.0) * I_pk
    L_req_uH = result.L_required_uH
    # Wire current density actually achieved at the chosen wire.
    J = result.I_rms_total_A / max(wire.A_cu_mm2, 1e-9)
    # Mean-length wire length.
    l_wire_m = result.N_turns * core.MLT_mm * 1e-3

    flowables: list = []

    # ----- 3. Theory introduction -----
    flowables.append(Paragraph("3. Boost-PFC CCM — theory",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "The boost-PFC stage shapes the input current into a "
        "scaled image of the input voltage so the converter "
        "presents a near-resistive load to the mains. In "
        "continuous-conduction mode (CCM) the inductor never fully "
        "demagnetises within a switching period, so the current is "
        "the half-wave rectified line current riding on a "
        "switching-frequency triangular ripple.",
        styles["body"],
    ))
    flowables.append(Paragraph(
        "The inductor sizing problem reduces to choosing L large "
        "enough that the worst-case peak-to-peak ripple "
        "Δi<sub>L,pp</sub>(t) stays inside the designer's budget "
        "(here, a fraction of the line peak current). The "
        "derivation below follows Erickson &amp; Maksimovic, "
        "<i>Fundamentals of Power Electronics</i>, ch. 18.",
        styles["body"],
    ))

    # ----- 4. Worst-case currents -----
    flowables.append(Paragraph("4. Worst-case input currents",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "Currents are computed at <b>low line</b>, which maximises "
        "the input current for a given output power. The fundamental "
        "line current is sinusoidal; its peak follows from input "
        "power balance.",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"P_{in} = \frac{P_{out}}{\eta}",
        with_values=f"{spec.Pout_W:.0f} W / {spec.eta:.2f}",
        result=f"{P_in:.1f} W",
        note="Input power at low line, accounting for the assumed efficiency.",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"I_{in,rms} = \frac{P_{in}}{V_{in,min}}",
        with_values=f"{P_in:.1f} W / {Vin_design:.0f} Vrms",
        result=f"{I_rms_line:.2f} Arms",
        note="Fundamental line RMS current at the worst-case input voltage.",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"I_{pk} = \sqrt{2}\,I_{in,rms}",
        with_values=f"√2 × {I_rms_line:.2f} A",
        result=f"{I_pk:.2f} A",
        note="Peak of the rectified line current — sets the inductor's saturation envelope.",
        fonts=fonts, styles=styles,
    ))

    # ----- 5. Required inductance -----
    flowables.append(Paragraph("5. Required inductance",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "For the boost stage the instantaneous duty cycle is "
        "d(t) = 1 − v<sub>in</sub>(t)/V<sub>out</sub>; the "
        "inductor sees v<sub>in</sub>(t) during the ON interval. "
        "The peak-to-peak ripple at line angle θ becomes:",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"\Delta i_{L,pp}(\theta) = \frac{V_{in,pk}\,|\sin\theta|"
        r"\,(1 - V_{in,pk}|\sin\theta|/V_{out})}"
        r"{L\,f_{sw}}",
        note="Worst case occurs at v_in(t) = V_out/2, i.e. when the duty cycle is exactly 0.5.",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"\Delta i_{L,pp,max} = \frac{V_{out}}{4 \cdot L \cdot f_{sw}}",
        note="Maximum ripple, taken at d = 0.5.",
        fonts=fonts, styles=styles,
    ))
    flowables.append(Paragraph(
        f"Setting Δi<sub>L,pp,max</sub> ≤ "
        f"{spec.ripple_pct:.0f}% × I<sub>pk</sub> "
        f"= {delta_max_A:.2f} A and solving for L:",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"L_{req} = \frac{V_{out}}{4 \cdot f_{sw} \cdot \Delta i_{L,pp,max}}",
        with_values=(
            f"{spec.Vout_V:.0f} V / "
            f"(4 × {spec.f_sw_kHz:.0f} kHz × {delta_max_A:.2f} A)"
        ),
        result=f"{L_req_uH:.1f} µH",
        note="Erickson eq. 18-22 (worst-case ripple at d = 0.5).",
        fonts=fonts, styles=styles,
    ))

    # ----- 6. Number of turns -----
    flowables.append(Paragraph("6. Number of turns",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "The inductance factor A<sub>L</sub> sets the no-bias "
        "inductance per turn²; powder-core materials roll off "
        "(μ% drops) under DC bias, so the effective A<sub>L</sub> "
        "at the operating point is reduced by the rolloff factor "
        "μ%(H<sub>pk</sub>). The engine searches the smallest N "
        "satisfying L(N) ≥ L<sub>req</sub> with rolloff applied.",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"L(N) = A_L \cdot N^2 \cdot \mu\%(H_{pk})",
        note=(
            f"At N = {result.N_turns} turns, μ%(H<sub>pk</sub>) = "
            f"{result.mu_pct_at_peak * 100:.1f}% with "
            f"H<sub>pk</sub> = {result.H_dc_peak_Oe:.0f} Oe."
        ),
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"H_{pk} = \frac{N \cdot I_{pk}}{l_e} \cdot 0.4\pi",
        with_values=(
            f"({result.N_turns} × {I_pk:.2f} A / "
            f"{core.le_mm:.1f} mm) × 0.4π"
        ),
        result=f"{result.H_dc_peak_Oe:.0f} Oe",
        note="0.4π converts A·turns/m to oersted (mixed-units convention used by powder-core vendors).",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"L_{actual} = A_L \cdot N^2 \cdot \mu\%",
        with_values=(
            f"{core.AL_nH:.0f} nH/N² × {result.N_turns}² × "
            f"{result.mu_pct_at_peak:.3f}"
        ),
        result=f"{result.L_actual_uH:.1f} µH",
        note=(
            "L_actual ≥ L_req — design is feasible at the "
            "saturation operating point."
            if result.L_actual_uH >= result.L_required_uH
            else "L_actual < L_req — see warnings."
        ),
        fonts=fonts, styles=styles,
    ))

    # ----- 7. Peak flux density -----
    flowables.append(Paragraph("7. Peak flux density",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "From Φ = L·i / N and B = Φ / A<sub>e</sub>, the peak flux "
        "density at the line-cycle envelope follows. The check "
        "is against the hot saturation flux B<sub>sat</sub>(100°C) "
        f"with a {spec.Bsat_margin * 100:.0f} % design margin.",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"B_{pk} = \frac{L_{actual} \cdot I_{pk}}{N \cdot A_e}",
        with_values=(
            f"({result.L_actual_uH:.1f} µH × {I_pk:.2f} A) / "
            f"({result.N_turns} × {core.Ae_mm2:.1f} mm²)"
        ),
        result=f"{result.B_pk_T * 1000:.0f} mT",
        note=(
            f"Bsat limit (with margin) = "
            f"{result.B_sat_limit_T * 1000:.0f} mT; "
            f"saturation margin = {result.sat_margin_pct:.0f} %."
        ),
        fonts=fonts, styles=styles,
    ))

    # ----- 8. Winding -----
    flowables.append(Paragraph("8. Winding design",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "Wire is sized to keep the current density J at a value "
        "that the convection-cooled winding can sustain (5 – 8 "
        "A/mm² typical for natural-convection chokes). The "
        "selected wire's actual J is back-checked against the "
        "engine's total-RMS current.",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"J = \frac{I_{rms,total}}{A_{cu}}",
        with_values=(
            f"{result.I_rms_total_A:.2f} A / "
            f"{wire.A_cu_mm2:.3f} mm²"
        ),
        result=f"{J:.2f} A/mm²",
        note=(
            "Total-RMS current includes the line-frequency RMS "
            "and the line-cycle-average HF ripple RMS."
        ),
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"l_{wire} = N \cdot MLT",
        with_values=f"{result.N_turns} × {core.MLT_mm:.1f} mm",
        result=f"{l_wire_m:.2f} m",
        note="Total winding length for the BOM cut-list.",
        fonts=fonts, styles=styles,
    ))

    # ----- 9-11. Common winding/losses/thermal -----
    flowables.extend(_section_winding_losses_thermal(
        spec, core, wire, result, section_num=9,
        fonts=fonts, styles=styles,
    ))
    return flowables


# ---------------------------------------------------------------------------
# Shared "winding R / losses / thermal" block.
#
# The physics of these three sections is identical across topologies —
# only the excitation frequencies and the role of the ripple term
# change. Factor out so the boost / line-reactor / passive-choke
# bodies stay focused on the topology-specific derivations and the
# common chain isn't reproduced three times.
# ---------------------------------------------------------------------------
def _section_winding_losses_thermal(
    spec: Spec, core: Core, wire: Wire, result: DesignResult,
    *, section_num: int, fonts, styles,
) -> list:
    """Return sections numbered ``section_num``, ``section_num+1``,
    ``section_num+2`` covering winding resistance & copper losses,
    core losses, and thermal verification."""
    flowables: list = []

    # Worst-case currents already on ``result`` — same numbers the
    # engine used so the displayed values match the rest of the
    # report to the printed precision.
    Vin_design = (
        spec.Vin_min_Vrms if spec.topology in ("boost_ccm", "passive_choke")
        else spec.Vin_nom_Vrms
    )
    if spec.topology == "boost_ccm":
        import math
        I_rms_line = spec.Pout_W / (spec.eta * Vin_design)
        I_rms_total = result.I_rms_total_A
    elif spec.topology == "line_reactor":
        I_rms_line = spec.I_rated_Arms
        I_rms_total = I_rms_line
    else:
        I_rms_line = spec.Pout_W / (spec.eta * Vin_design)
        I_rms_total = I_rms_line
    l_wire_m = result.N_turns * core.MLT_mm * 1e-3
    is_ac_relevant = spec.topology == "boost_ccm"

    # ----- Winding resistance + copper losses -----
    flowables.append(Paragraph(
        f"{section_num}. Winding resistance &amp; copper losses",
        styles["h2"],
    ))
    if is_ac_relevant:
        flowables.append(Paragraph(
            "DC resistance follows from the resistivity of copper, "
            "temperature-corrected to the converged winding "
            "temperature; AC resistance at the switching frequency "
            "uses Dowell's analytical 1-D solution for skin + "
            "proximity effects.",
            styles["body"],
        ))
    else:
        flowables.append(Paragraph(
            "Resistance is computed from the resistivity of copper "
            "at the converged winding temperature. The skin-effect "
            "correction at line frequency is negligible at the wire "
            "gauges used here, so R<sub>ac</sub> ≈ R<sub>dc</sub>.",
            styles["body"],
        ))
    flowables.append(_eqn_block(
        r"R_{dc}(T) = \rho_{Cu}(T) \cdot \frac{l_{wire}}{A_{cu}}",
        with_values=(
            f"ρ(T = {result.T_winding_C:.0f}°C) × "
            f"{l_wire_m:.2f} m / {wire.A_cu_mm2:.3f} mm²"
        ),
        result=f"{result.R_dc_ohm * 1000:.1f} mΩ",
        note=(
            f"R_ac at "
            f"{'fsw' if is_ac_relevant else 'f_line'} = "
            f"{result.R_ac_ohm * 1000:.1f} mΩ."
        ),
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"P_{Cu,DC} = R_{dc}(T) \cdot I_{rms}^{\,2}",
        with_values=(
            f"{result.R_dc_ohm * 1000:.1f} mΩ × "
            f"({I_rms_line:.2f} A)²"
        ),
        result=f"{result.losses.P_cu_dc_W:.2f} W",
        fonts=fonts, styles=styles,
    ))
    if is_ac_relevant:
        flowables.append(_eqn_block(
            r"P_{Cu,AC} = R_{ac}(f_{sw}) \cdot I_{ripple,rms}^{\,2}",
            with_values=(
                f"{result.R_ac_ohm * 1000:.1f} mΩ × "
                f"I_ripple_rms²"
            ),
            result=f"{result.losses.P_cu_ac_W:.3f} W",
            note="I_ripple_rms is the line-cycle-average RMS of the triangular HF ripple.",
            fonts=fonts, styles=styles,
        ))
    else:
        flowables.append(Paragraph(
            f"P<sub>Cu,AC</sub> = "
            f"{result.losses.P_cu_ac_W:.4f} W "
            "(negligible — no switching-frequency ripple).",
            styles["body"],
        ))

    # ----- Core losses -----
    flowables.append(Paragraph(
        f"{section_num + 1}. Core losses (anchored Steinmetz / iGSE)",
        styles["h2"],
    ))
    if spec.topology == "line_reactor":
        flowables.append(Paragraph(
            "The reactor is excited solely at the line frequency "
            "(50/60 Hz). The flux swing is the bipolar excursion "
            "around zero driven by the fundamental V across the "
            "winding. Core losses are evaluated with anchored "
            "Steinmetz at f<sub>line</sub>; there is no separate "
            "ripple band.",
            styles["body"],
        ))
    elif spec.topology == "passive_choke":
        flowables.append(Paragraph(
            "Excitation is the rectified line-frequency current "
            "envelope; there is no switching ripple. Loss "
            "evaluation uses anchored Steinmetz at f<sub>line</sub> "
            "with the peak flux density driven by I<sub>pk</sub>.",
            styles["body"],
        ))
    else:  # boost_ccm
        flowables.append(Paragraph(
            "Two distinct excitations: a line-frequency component "
            "swung by the rectified envelope, and a switching-"
            "frequency component swung by the per-cycle ripple. "
            "The engine evaluates the iGSE form of Steinmetz with "
            "material-anchored coefficients, integrated over the "
            "line cycle so the variable Δ B(t) profile is captured "
            "exactly.",
            styles["body"],
        ))
    flowables.append(_eqn_block(
        r"P_{core} = k_i \cdot f^{\alpha} \cdot \Delta B^{\beta} \cdot V_e",
        note=(
            "Material-anchored Steinmetz; the engine evaluates "
            "the iGSE form for the swing the topology actually sees."
        ),
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"P_{core,line} \approx k_i \cdot f_{line}^{\alpha} "
        r"\cdot B_{pk}^{\beta} \cdot V_e",
        with_values=(
            f"line-band Steinmetz at f = {spec.f_line_Hz:.0f} Hz, "
            f"B_pk = {result.B_pk_T * 1000:.0f} mT, "
            f"V_e = {core.Ve_mm3 / 1000:.1f} cm³"
        ),
        result=f"{result.losses.P_core_line_W:.3f} W",
        fonts=fonts, styles=styles,
    ))
    if is_ac_relevant:
        flowables.append(_eqn_block(
            r"P_{core,ripple} = \langle k_i \cdot f_{sw}^{\alpha} "
            r"\cdot \Delta B_{pp}(\theta)^{\beta} \cdot V_e "
            r"\rangle_{\theta}",
            with_values=(
                f"iGSE integrated over θ at f_sw = "
                f"{spec.f_sw_kHz:.0f} kHz"
            ),
            result=f"{result.losses.P_core_ripple_W:.3f} W",
            note=(
                "Integration over θ captures the worst-case ripple "
                "at the cusp where d = 0.5."
            ),
            fonts=fonts, styles=styles,
        ))
    else:
        flowables.append(Paragraph(
            f"P<sub>core,ripple</sub> = "
            f"{result.losses.P_core_ripple_W:.4f} W "
            "(negligible — no switching ripple band).",
            styles["body"],
        ))
    flowables.append(_eqn_block(
        r"P_{total} = P_{Cu,DC} + P_{Cu,AC} + P_{core,line} "
        r"+ P_{core,ripple}",
        with_values=(
            f"{result.losses.P_cu_dc_W:.2f} + "
            f"{result.losses.P_cu_ac_W:.3f} + "
            f"{result.losses.P_core_line_W:.3f} + "
            f"{result.losses.P_core_ripple_W:.3f} W"
        ),
        result=f"{result.losses.P_total_W:.2f} W",
        fonts=fonts, styles=styles,
    ))

    # ----- Thermal -----
    flowables.append(Paragraph(
        f"{section_num + 2}. Thermal verification",
        styles["h2"],
    ))
    flowables.append(Paragraph(
        "Steady-state winding temperature is found from a natural-"
        "convection thermal-resistance model on the core's outer "
        "surface, iterated until the Cu/core losses (which depend "
        "on T through ρ<sub>Cu</sub>) and ΔT are self-consistent.",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"\Delta T = T_{winding} - T_{amb}",
        with_values=(
            f"{result.T_winding_C:.0f} °C − "
            f"{spec.T_amb_C:.0f} °C"
        ),
        result=f"{result.T_rise_C:.0f} K",
        note=(
            "Converged at the engine's iterated steady state. "
            f"T<sub>w</sub> = {result.T_winding_C:.0f} °C is "
            f"{'within' if result.T_winding_C <= spec.T_max_C else 'above'} "
            f"the {spec.T_max_C:.0f} °C limit."
        ),
        fonts=fonts, styles=styles,
    ))
    return flowables


# ---------------------------------------------------------------------------
# Boost CCM — patch the shared block in (sections 9, 10, 11).
# ---------------------------------------------------------------------------


def _body_line_reactor(spec: Spec, core: Core, material: Material,
                        wire: Wire, result: DesignResult,
                        fonts, styles) -> list:
    """AC line reactor derivation chain.

    Reference: Pomilio Cap. 11 (passive PFC), NEMA application notes,
    IEC 61000-3-12 § 9.3 (industrial connection at the PCC). The
    engine in ``topology/line_reactor.py`` implements the same
    %Z-driven sizing convention; we reproduce it here so the report
    matches the engine to displayed precision.
    """
    import math
    is_3ph = spec.n_phases == 3
    V_phase = spec.phase_voltage_Vrms
    Z_base = V_phase / max(spec.I_rated_Arms, 1e-9)
    X_L = Z_base * spec.pct_impedance / 100.0
    omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    L_req_mH = X_L / omega * 1000.0
    L_actual_mH = result.L_actual_uH / 1000.0
    V_drop_rms = omega * L_actual_mH * 1e-3 * spec.I_rated_Arms
    V_drop_pct = result.voltage_drop_pct or 0.0
    THD_pct = result.thd_estimate_pct or 0.0
    # Commutation overlap (Mohan/Undeland eq. 5-65).
    Vac_pk = math.sqrt(2.0) * V_phase
    L_H = max(L_actual_mH * 1e-3, 1e-12)
    cos_mu = 1.0 - (2.0 * omega * L_H * spec.I_rated_Arms) / max(Vac_pk, 1e-9)
    cos_mu = max(-1.0, min(1.0, cos_mu))
    mu_rad = math.acos(cos_mu)
    mu_deg = math.degrees(mu_rad)

    flowables: list = []

    # ----- 3. Theory -----
    flowables.append(Paragraph("3. Line reactor — theory",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "The line reactor sits in series with each phase between "
        "the AC mains and the diode bridge that feeds the DC-link "
        "of a variable-frequency drive (VFD). Its purpose is "
        "twofold:",
        styles["body"],
    ))
    flowables.append(Paragraph(
        "&nbsp;&nbsp;• Inject series impedance at line frequency "
        "to limit the di/dt during diode commutation; this softens "
        "the line-current notches and reduces the harmonic "
        "spectrum.<br/>"
        "&nbsp;&nbsp;• Provide a small voltage drop ahead of the "
        "rectifier so the VFD's input current waveform widens, "
        "approaching a sinusoid; this directly reduces THD.",
        styles["body"],
    ))
    flowables.append(Paragraph(
        "Industry sizing convention (NEMA, Pomilio Cap. 11) is "
        "to specify the reactor as a fraction of the load's base "
        "impedance — typically 3 % to 5 % for general service, "
        "8 % to 12 % for high-distortion-sensitive applications. "
        "The engine uses %Z = "
        f"{spec.pct_impedance:.1f} % for this design.",
        styles["body"],
    ))

    # ----- 4. Base impedance + reactor impedance -----
    flowables.append(Paragraph(
        "4. Base impedance &amp; reactor reactance",
        styles["h2"],
    ))
    if is_3ph:
        flowables.append(Paragraph(
            "For a 3-phase load the per-phase voltage is the "
            "line-to-line rms divided by √3.",
            styles["body"],
        ))
        flowables.append(_eqn_block(
            r"V_{phase} = \frac{V_{LL}}{\sqrt{3}}",
            with_values=f"{spec.Vin_nom_Vrms:.0f} Vrms / √3",
            result=f"{V_phase:.1f} Vrms",
            fonts=fonts, styles=styles,
        ))
    else:
        flowables.append(_eqn_block(
            r"V_{phase} = V_{LN}",
            with_values=f"{spec.Vin_nom_Vrms:.0f} Vrms",
            result=f"{V_phase:.1f} Vrms",
            fonts=fonts, styles=styles,
        ))
    flowables.append(_eqn_block(
        r"Z_{base} = \frac{V_{phase}}{I_{rated}}",
        with_values=f"{V_phase:.1f} V / {spec.I_rated_Arms:.2f} A",
        result=f"{Z_base:.3f} Ω",
        note="Per-phase base impedance — the reference for the %Z spec.",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"X_L = \frac{\%Z}{100} \cdot Z_{base}",
        with_values=(
            f"({spec.pct_impedance:.1f}/100) × {Z_base:.3f} Ω"
        ),
        result=f"{X_L:.3f} Ω",
        note="Reactor reactance at the line frequency.",
        fonts=fonts, styles=styles,
    ))

    # ----- 5. Required inductance -----
    flowables.append(Paragraph("5. Required inductance",
                                 styles["h2"]))
    flowables.append(_eqn_block(
        r"L_{req} = \frac{X_L}{2\pi \cdot f_{line}}",
        with_values=(
            f"{X_L:.3f} Ω / (2π × {spec.f_line_Hz:.0f} Hz)"
        ),
        result=f"{L_req_mH:.3f} mH",
        note="L = X/(ωf); the voltage drop at rated current equals %Z by definition.",
        fonts=fonts, styles=styles,
    ))

    # ----- 6. Number of turns -----
    flowables.append(Paragraph("6. Number of turns",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "The reactor's flux swing is set by the fundamental "
        "voltage across the winding, V<sub>L,rms</sub> = "
        "(%Z/100) · V<sub>phase</sub>. From V = N · dΦ/dt the peak "
        "flux density follows:",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"B_{pk} = \frac{\sqrt{2} \cdot V_{L,rms}}"
        r"{2\pi \cdot f_{line} \cdot N \cdot A_e}",
        with_values=(
            f"(√2 × {V_drop_rms:.2f} V) / "
            f"(2π × {spec.f_line_Hz:.0f} Hz × {result.N_turns} × "
            f"{core.Ae_mm2:.1f} mm²)"
        ),
        result=f"{result.B_pk_T * 1000:.0f} mT",
        note=(
            f"Bsat limit = {result.B_sat_limit_T * 1000:.0f} mT; "
            f"saturation margin = {result.sat_margin_pct:.0f} %. "
            "Solving N from L = A_L · N² (silicon-steel materials "
            "have negligible bias rolloff) gives "
            f"N = {result.N_turns}."
        ),
        fonts=fonts, styles=styles,
    ))

    # ----- 7. Voltage drop & THD -----
    flowables.append(Paragraph(
        "7. Voltage drop &amp; THD prediction",
        styles["h2"],
    ))
    flowables.append(Paragraph(
        "By the definition of base impedance, the voltage drop "
        "across the reactor at rated current is exactly the "
        "specified %Z. The empirical THD prediction follows "
        "Pomilio's textbook fit and matches IEEE 519 application "
        "data within ±5 percentage points.",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"V_{drop}/V_{phase} = \frac{\omega L \cdot I_{rated}}"
        r"{V_{phase}} \cdot 100\%",
        with_values=(
            f"(2π × {spec.f_line_Hz:.0f} × "
            f"{L_actual_mH:.3f} mH × "
            f"{spec.I_rated_Arms:.2f} A) / {V_phase:.1f} V × 100%"
        ),
        result=f"{V_drop_pct:.2f} %",
        note="Equals the spec'd %Z by construction; verifies the L sizing.",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"THD_{est} \approx \frac{75}{\sqrt{\%Z}}",
        with_values=f"75 / √{spec.pct_impedance:.1f}",
        result=f"{THD_pct:.1f} %",
        note="Empirical fit (Pomilio Cap. 11, Bonner): ±5 pp accuracy vs measured.",
        fonts=fonts, styles=styles,
    ))

    # ----- 8. Commutation overlap -----
    flowables.append(Paragraph(
        "8. Commutation overlap (Mohan/Undeland)",
        styles["h2"],
    ))
    flowables.append(Paragraph(
        "During commutation between two diodes of the bridge, the "
        "reactor inductance forces a finite overlap angle μ over "
        "which both diodes conduct simultaneously. The notch in "
        "the line voltage during this interval drives the "
        "harmonic content; longer μ → softer notch → less "
        "high-order harmonics.",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"\cos\mu = 1 - \frac{2 \omega L \cdot I_{d}}"
        r"{\sqrt{2} \cdot V_{phase}}",
        with_values=(
            f"1 − (2 × 2π × {spec.f_line_Hz:.0f} × "
            f"{L_actual_mH:.3f} mH × "
            f"{spec.I_rated_Arms:.2f} A) / "
            f"(√2 × {V_phase:.1f} V)"
        ),
        result=f"μ = {mu_deg:.2f}°",
        note="Mohan & Undeland eq. 5-65 (6-pulse diode rectifier).",
        fonts=fonts, styles=styles,
    ))

    # ----- 9-11. Common winding/losses/thermal -----
    flowables.extend(_section_winding_losses_thermal(
        spec, core, wire, result, section_num=9,
        fonts=fonts, styles=styles,
    ))
    return flowables


def _body_passive_choke(spec: Spec, core: Core, material: Material,
                          wire: Wire, result: DesignResult,
                          fonts, styles) -> list:
    """Passive line choke derivation chain.

    Reference: Erickson &amp; Maksimovic Ch. 18 (passive PFC),
    Pomilio Cap. 13 (capacitive-input rectifier with series choke).
    Electrically the topology is identical to a 1-φ line reactor —
    the choke widens the rectifier's conduction angle, lowers the
    peak charging current and reduces line-current THD.
    """
    import math
    Vin = spec.Vin_nom_Vrms
    P_in = spec.Pout_W / spec.eta
    omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    Z_base = (Vin ** 2) / max(P_in, 1.0)
    L_actual_uH = result.L_actual_uH
    L_actual_mH = L_actual_uH / 1000.0
    V_drop_pct = result.voltage_drop_pct or 0.0
    THD_pct = result.thd_estimate_pct or 0.0
    I_pk = result.I_line_pk_A
    I_rms = spec.Pout_W / (spec.eta * Vin)

    flowables: list = []

    # ----- 3. Theory -----
    flowables.append(Paragraph("3. Passive line choke — theory",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "A passive line choke sits in series with the rectifier "
        "input (or DC bus, electrically equivalent) and shapes the "
        "input current passively — without active switching. "
        "Without the choke, a capacitive-input rectifier draws "
        "current only at the line-voltage peaks, producing a "
        "narrow, distorted pulse with PF ≈ 0.55 and THD ≈ 100 %. "
        "Adding a series L stretches the conduction angle, "
        "raising the PF toward 0.85 – 0.95 and dropping THD to "
        "30 – 50 %.",
        styles["body"],
    ))
    flowables.append(Paragraph(
        "Electrically the topology is identical to a 1-φ line "
        "reactor, so the sizing formulas are the same. The "
        "differences are operational: passive chokes are typically "
        "smaller (lower %Z, since the load is single-phase low-"
        "power rather than 3-phase industrial) and tuned for "
        "compliance with IEC 61000-3-2 Class D rather than "
        "61000-3-12 industrial limits.",
        styles["body"],
    ))

    # ----- 4. Worst-case currents -----
    flowables.append(Paragraph("4. Worst-case input currents",
                                 styles["h2"]))
    flowables.append(_eqn_block(
        r"P_{in} = \frac{P_{out}}{\eta}",
        with_values=f"{spec.Pout_W:.0f} W / {spec.eta:.2f}",
        result=f"{P_in:.1f} W",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"I_{rms} = \frac{P_{in}}{V_{in}}",
        with_values=f"{P_in:.1f} W / {Vin:.0f} Vrms",
        result=f"{I_rms:.2f} Arms",
        note="At unity-PF (idealised); the actual rectifier draws a higher RMS, but the choke is sized against this baseline.",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"I_{pk} = \sqrt{2}\,I_{rms}",
        with_values=f"√2 × {I_rms:.2f} A",
        result=f"{I_pk:.2f} A",
        note="Peak of the fundamental — sets the saturation envelope.",
        fonts=fonts, styles=styles,
    ))

    # ----- 5. Required inductance (empirical) -----
    flowables.append(Paragraph("5. Required inductance",
                                 styles["h2"]))
    flowables.append(Paragraph(
        "Erickson Ch. 18 derives an empirical sizing rule based on "
        "the load's base impedance and a target THD. The "
        "coefficient k(THD) ≈ 0.35 for 30 % THD; smaller k for "
        "looser THD, larger for tighter THD.",
        styles["body"],
    ))
    flowables.append(_eqn_block(
        r"Z_{base} = \frac{V_{in}^{2}}{P_{in}}",
        with_values=f"({Vin:.0f} V)² / {P_in:.1f} W",
        result=f"{Z_base:.2f} Ω",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"L_{req} = \frac{k(THD) \cdot Z_{base}}"
        r"{2\pi \cdot f_{line}}",
        with_values=(
            f"(0.35 × {Z_base:.2f} Ω) / "
            f"(2π × {spec.f_line_Hz:.0f} Hz)"
        ),
        result=f"{result.L_required_uH:.1f} µH",
        note="Erickson eq. 18-44 (empirical, target THD ≈ 30 %).",
        fonts=fonts, styles=styles,
    ))

    # ----- 6. Number of turns + flux -----
    flowables.append(Paragraph("6. Number of turns &amp; peak flux",
                                 styles["h2"]))
    flowables.append(_eqn_block(
        r"L = A_L \cdot N^2 \cdot \mu\%(H_{pk})",
        with_values=(
            f"{core.AL_nH:.0f} nH/N² × {result.N_turns}² × "
            f"{result.mu_pct_at_peak:.3f}"
        ),
        result=f"{L_actual_uH:.1f} µH",
        note=(
            f"At N = {result.N_turns}, "
            f"H<sub>pk</sub> = {result.H_dc_peak_Oe:.0f} Oe "
            f"and μ%(H) = {result.mu_pct_at_peak * 100:.1f} %."
        ),
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"B_{pk} = \frac{L \cdot I_{pk}}{N \cdot A_e}",
        with_values=(
            f"({L_actual_uH:.1f} µH × {I_pk:.2f} A) / "
            f"({result.N_turns} × {core.Ae_mm2:.1f} mm²)"
        ),
        result=f"{result.B_pk_T * 1000:.0f} mT",
        note=(
            f"Bsat limit = {result.B_sat_limit_T * 1000:.0f} mT; "
            f"saturation margin = {result.sat_margin_pct:.0f} %."
        ),
        fonts=fonts, styles=styles,
    ))

    # ----- 7. Voltage drop & THD -----
    flowables.append(Paragraph(
        "7. Voltage drop &amp; THD prediction",
        styles["h2"],
    ))
    flowables.append(_eqn_block(
        r"V_{drop}/V_{in} = \frac{\omega L \cdot I_{dc}}"
        r"{V_{in}} \cdot 100\%",
        with_values=(
            f"(2π × {spec.f_line_Hz:.0f} × "
            f"{L_actual_mH:.3f} mH × I_dc) / {Vin:.0f} V × 100%"
        ),
        result=f"{V_drop_pct:.2f} %",
        note="I_dc = P_out / (η · 0.9·V_pk) ≈ rectifier-output average current.",
        fonts=fonts, styles=styles,
    ))
    flowables.append(_eqn_block(
        r"THD_{est} \approx \frac{75}{\sqrt{\%Z}}",
        with_values=f"75 / √{V_drop_pct:.2f}",
        result=f"{THD_pct:.1f} %",
        note="Same fit used for the line reactor; same physics, single-phase application.",
        fonts=fonts, styles=styles,
    ))

    # ----- 8-10. Common winding/losses/thermal -----
    flowables.extend(_section_winding_losses_thermal(
        spec, core, wire, result, section_num=8,
        fonts=fonts, styles=styles,
    ))
    return flowables


def _page_decoration_factory(project_id: str, fonts: dict[str, str]):
    """Footer painted on every page. Carries the project id so a
    detached page in a binder is still traceable."""
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(fonts["regular"], 8)
        canvas.setFillColor(_Palette.muted)
        canvas.drawString(
            18 * mm, 8 * mm,
            f"MagnaDesign · Project {project_id} · "
            f"{datetime.now().strftime('%Y-%m-%d')}",
        )
        canvas.drawRightString(
            doc.pagesize[0] - 18 * mm, 8 * mm,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()
    return _draw


# ---------------------------------------------------------------------------
# Public API — Phase PROJ-1 stub. PROJ-2 fills in the topology-agnostic
# sections (inputs, summary, common plots); PROJ-3/4 add the per-
# topology derivation bodies; PROJ-5 wires the UI.
# ---------------------------------------------------------------------------
def generate_project_report(
    spec: Spec,
    core: Core,
    material: Material,
    wire: Wire,
    result: DesignResult,
    output_path: str | Path,
    designer: str = "—",
    revision: str = "A.0",
    project_id: Optional[str] = None,
) -> Path:
    """Write an engineering project report and return its absolute path.

    Drop-in companion to ``generate_pdf_datasheet``. Where the
    datasheet is the customer-facing summary, this report walks the
    full derivation: spec → theory → equations → substituted values
    → numerical result, per-topology.

    ``project_id``: the customer's internal project tag. Falls back
    to the spec/core/material hash (same one the datasheet uses for
    its P/N) when not supplied.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fonts = _register_fonts()
    styles = _build_styles(fonts)

    pid = project_id or _stamp(spec, core, material)
    title = _topology_label(spec.topology)
    now = datetime.now().strftime("%Y-%m-%d")

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Project report — {pid}",
        author=designer,
        subject=f"Engineering report for {spec.topology}",
        creator="MagnaDesign",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="main",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="default", frames=[frame],
                     onPage=_page_decoration_factory(pid, fonts)),
    ])

    story: list = []
    story.append(_project_header(
        title, pid, designer, revision, now,
        fonts=fonts, styles=styles,
    ))
    story.append(Spacer(1, 4 * mm))

    # 1. Project specification
    story.extend(_section_project_inputs(spec, fonts, styles))

    # 2. Selected components
    story.extend(_section_components(
        core, material, wire, result, fonts, styles,
    ))

    # 3+. Per-topology theoretical body (filled in PROJ-3 / PROJ-4).
    story.extend(_section_topology_body(
        spec, core, material, wire, result, fonts, styles,
    ))

    # Verification plots — section follows the per-topology body.
    story.extend(_section_verification(
        spec, core, material, wire, result, fonts, styles,
    ))

    # Final consolidated summary table.
    story.extend(_section_result_summary(spec, result, fonts, styles))

    # Warnings, if the design has any.
    if result.warnings:
        story.append(Paragraph("Warnings raised by the engine",
                                 styles["h2"]))
        for w in result.warnings:
            story.append(Paragraph(f"• {w}", styles["note"]))

    doc.build(story)
    return output_path.resolve()
