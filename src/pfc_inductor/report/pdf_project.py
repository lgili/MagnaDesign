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
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Image as RLImage

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.report.pdf_report import (
    _build_styles,
    _fig_bh_trajectory,
    _fig_inductance_vs_current,
    _fig_loss_breakdown,
    _fig_pf_vs_inductance,
    _fig_power_vs_inductance,
    _fig_waveform,
    _kv_table_style,
    _mpl_flowable,
    _Palette,
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
    fontsize: int = 14,
    dpi: int = 220,
    color: str = "#1a1a1a",
) -> RLImage:
    """Render a LaTeX-style math string to a tight-cropped PNG flowable.

    Uses matplotlib's mathtext backend with the Computer Modern
    fontset — the same family classic LaTeX uses, so equations look
    indistinguishable from a real LaTeX render at the engineer's
    desk. The fontset is set inside an ``rc_context`` so the
    project report's typography choice doesn't leak into the
    verification plots imported from ``pdf_report.py``.

    The figure is sized minimally — ``bbox_inches="tight"`` crops
    to the actual equation extent — and saved with a transparent
    background so the PDF page colour shows through.
    """
    with plt.rc_context(
        {
            "mathtext.fontset": "cm",  # Computer Modern (LaTeX look)
            "mathtext.rm": "serif",
            "mathtext.it": "serif:italic",
            "mathtext.bf": "serif:bold",
            "font.family": "serif",
        }
    ):
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0.0, 0.0, f"${latex}$", fontsize=fontsize, color=color)
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=dpi,
            bbox_inches="tight",
            pad_inches=0.04,
            transparent=True,
        )
        plt.close(fig)
    buf.seek(0)
    img = RLImage(buf)
    # Scale down by the DPI ratio so the rendered size matches the
    # nominal point size we asked for. Without this, mathtext at
    # 220 dpi prints physically large because matplotlib treats the
    # bitmap as 72-dpi-equivalent.
    iw, ih = img.imageWidth, img.imageHeight
    scale = 72.0 / dpi
    img.drawWidth = iw * scale
    img.drawHeight = ih * scale
    return img


def _eqn_centered(latex: str, *, fontsize: int = 14):
    """Return an equation flowable horizontally centred on the page.

    The default ``_eqn_image`` is left-aligned because that's what
    flowables do by default. For the standard ``equation → values
    → result`` block centring the symbolic top line and indenting
    the substituted lines reads more like a textbook derivation.
    """
    img = _eqn_image(latex, fontsize=fontsize)
    # Wrap in a single-cell table to get HCENTER alignment without
    # touching the Image flowable's geometry.
    t = Table([[img]], colWidths=[_USABLE_WIDTH_MM * mm])
    t.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return t


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
    flowables: list = [_eqn_centered(latex, fontsize=15)]
    if with_values:
        # Indent slightly so the eye reads it as a continuation of the
        # equation above, not as a new statement.
        flowables.append(
            Paragraph(
                f"&nbsp;&nbsp;&nbsp;&nbsp;= {with_values}",
                styles["body"],
            )
        )
    if result:
        flowables.append(
            Paragraph(
                f"&nbsp;&nbsp;&nbsp;&nbsp;<b>= {result}</b>",
                styles["body"],
            )
        )
    if note:
        flowables.append(
            Paragraph(
                f"<i>{note}</i>",
                styles["note"],
            )
        )
    flowables.append(Spacer(1, 2 * mm))
    return KeepTogether(flowables)


def _derivation_step(
    label: str,
    latex: str,
    *,
    note: Optional[str] = None,
    fonts: dict[str, str],
    styles: dict[str, ParagraphStyle],
) -> KeepTogether:
    """Single derivation step — a labelled equation without
    substituted values. Used to walk a multi-step derivation
    (volt-second balance → duty cycle → ripple → solve for L)
    where each line builds on the previous; the substituted values
    only land at the end.
    """
    flowables: list = [
        Paragraph(f"<b>{label}.</b>", styles["body"]),
        _eqn_centered(latex, fontsize=14),
    ]
    if note:
        flowables.append(Paragraph(f"<i>{note}</i>", styles["note"]))
    flowables.append(Spacer(1, 1 * mm))
    return KeepTogether(flowables)


# ---------------------------------------------------------------------------
# Sizing helpers — implement the same engineering rules of thumb the
# user would apply by hand (area product, energy storage, parallel
# strands). Centralised here so every per-topology body can call into
# them without duplicating the maths.
# ---------------------------------------------------------------------------
def _area_product_mm4(
    L_uH: float,
    I_pk_A: float,
    I_rms_A: float,
    *,
    K_u_target: float = 0.4,
    J_target: float = 5.0,
    B_max_T: float,
) -> float:
    """Required core area-product A_p = W_a × A_e for the given
    storage requirement.

    Standard formula (Kazimierczuk, *High-Frequency Magnetic
    Components*, eq. 4.62):

        A_p = (L · I_pk · I_rms) / (K_u · J · B_max)

    Inputs in their natural units, output in **mm⁴** so it can be
    compared directly to ``core.Wa_mm2 * core.Ae_mm2``.
    """
    L_H = L_uH * 1e-6
    # SI: L [H], I [A], B [T], J [A/m²] → A_p [m⁴].
    J_A_per_m2 = J_target * 1e6  # A/mm² → A/m²
    Ap_m4 = (L_H * I_pk_A * I_rms_A) / (K_u_target * J_A_per_m2 * B_max_T)
    return Ap_m4 * 1e12  # m⁴ → mm⁴


def _stored_energy_J(L_uH: float, I_pk_A: float) -> float:
    """E = ½ L I². Used as a sanity check on the core volume."""
    return 0.5 * (L_uH * 1e-6) * (I_pk_A**2)


def _skin_depth_mm(f_Hz: float, T_C: float = 100.0) -> float:
    """Copper skin depth at the given frequency and temperature.

    δ = √(ρ_Cu(T) / (π · μ₀ · f))

    Returns the depth in millimetres so the d_cu vs 2δ check reads
    naturally against wire-gauge dimensions.
    """
    import math as _math

    rho_20 = 1.724e-8  # Ω·m
    rho = rho_20 * (1.0 + 3.93e-3 * (T_C - 20.0))
    mu_0 = 4.0 * _math.pi * 1e-7
    delta_m = _math.sqrt(rho / (_math.pi * mu_0 * max(f_Hz, 1.0)))
    return delta_m * 1000.0  # m → mm


def _parallel_strands_recommendation(
    wire: Wire,
    I_rms_A: float,
    fsw_Hz: float,
    T_C: float,
    *,
    J_target: float = 5.0,
) -> dict:
    """Return a dict with the wire-sizing verdict.

    Keys:
    - ``A_cu_required_mm2``: from current density target.
    - ``A_cu_selected_mm2``: the chosen wire's copper area.
    - ``J_actual_A_per_mm2``: actual current density at the chosen
      wire.
    - ``delta_mm``: skin depth at the operating frequency.
    - ``two_delta_mm``: 2δ — the conventional limit for AC-effective
      penetration.
    - ``d_cu_mm``: chosen wire's copper diameter (or estimated from
      A_cu if not on the wire record).
    - ``n_strands_for_area``: parallel-strand count needed if the
      chosen wire's A_cu is below the target (≥ 1).
    - ``skin_limited``: True if d_cu > 2δ — single strand suffers
      AC penalty even if its area is sufficient.
    - ``advice``: one-line plain-English verdict.
    """
    import math as _math

    A_cu_required = I_rms_A / max(J_target, 1e-6)
    A_cu_selected = wire.A_cu_mm2
    J_actual = I_rms_A / max(A_cu_selected, 1e-6)
    delta_mm = _skin_depth_mm(fsw_Hz, T_C)
    two_delta = 2.0 * delta_mm
    d_cu = wire.d_cu_mm or 2.0 * _math.sqrt(A_cu_selected / _math.pi)
    # Two distinct strand-count rules:
    # - Area-based: ``n_area`` thinner strands are needed if the
    #   chosen wire's A_cu falls short of the J target.
    # - Skin-based: ``n_skin`` strands are needed if d_cu > 2δ —
    #   each strand should be sized so its diameter is ≤ 2δ.
    # When both bind, the engineer takes the larger.
    n_area = max(1, _math.ceil(A_cu_required / max(A_cu_selected, 1e-6)))
    n_skin = max(1, _math.ceil(d_cu / max(two_delta, 1e-6)))
    skin_limited = d_cu > two_delta
    n_recommend = max(n_area, n_skin)

    if A_cu_selected >= A_cu_required and not skin_limited:
        advice = (
            f"Single strand of {wire.id} is sufficient "
            f"(A_cu = {A_cu_selected:.3f} mm² ≥ required "
            f"{A_cu_required:.3f} mm² and d_cu = {d_cu:.2f} mm "
            f"≤ 2δ = {two_delta:.2f} mm)."
        )
    elif A_cu_selected >= A_cu_required and skin_limited:
        advice = (
            f"Single-strand area is sufficient but d_cu = "
            f"{d_cu:.2f} mm exceeds 2δ = {two_delta:.2f} mm at "
            f"f_sw = {fsw_Hz / 1000:.0f} kHz — proximity / skin "
            f"losses penalty. Use Litz wire, or split into "
            f"{n_skin} thinner parallel strands so each strand's "
            "diameter stays within 2δ."
        )
    else:
        advice = (
            f"Single strand A_cu = {A_cu_selected:.3f} mm² is below "
            f"the {A_cu_required:.3f} mm² target. Use "
            f"{n_recommend} strands in parallel"
            + (
                " (also satisfies the skin-depth constraint)."
                if n_recommend >= n_skin and skin_limited
                else "."
            )
        )
    return {
        "A_cu_required_mm2": A_cu_required,
        "A_cu_selected_mm2": A_cu_selected,
        "J_actual_A_per_mm2": J_actual,
        "delta_mm": delta_mm,
        "two_delta_mm": two_delta,
        "d_cu_mm": d_cu,
        "n_strands_for_area": n_area,
        "n_strands_for_skin": n_skin,
        "n_strands_recommend": n_recommend,
        "skin_limited": skin_limited,
        "advice": advice,
    }


# ---------------------------------------------------------------------------
# Sizing plots — show the design point in the context of the search
# space. ``B_pk vs N`` traces the saturation knee the engine landed
# on; ``Ku vs N`` shows the window-fill headroom.
# ---------------------------------------------------------------------------
def _fig_bpk_vs_N(spec: Spec, core: Core, material: Material, result: DesignResult, I_pk_A: float):
    """B_pk(N) sweep with the design point marked. Engineer reads
    the saturation knee and where the chosen N sits relative to it."""
    import numpy as _np

    from pfc_inductor.physics import rolloff as rf

    Ns = _np.arange(5, max(result.N_turns + 30, 80))
    B = _np.zeros_like(Ns, dtype=float)
    for i, N in enumerate(Ns):
        H_pk_Oe = rf.H_from_NI(int(N), I_pk_A, core.le_mm, units="Oe")
        mu = rf.mu_pct(material, H_pk_Oe)
        L_uH = rf.inductance_uH(int(N), core.AL_nH, mu)
        Ae_m2 = core.Ae_mm2 * 1e-6
        if N > 0 and Ae_m2 > 0:
            B[i] = (L_uH * 1e-6) * I_pk_A / (N * Ae_m2)
        else:
            B[i] = 0.0
    fig, ax = plt.subplots(figsize=(7.0, 3.0), dpi=110)
    ax.plot(Ns, B * 1000.0, color="#3a78b5", linewidth=1.6, label="B_pk(N) at I_pk")
    Bsat_mT = result.B_sat_limit_T * 1000.0
    ax.axhline(
        Bsat_mT, color="#a01818", linestyle="--", alpha=0.7, label=f"Bsat limit = {Bsat_mT:.0f} mT"
    )
    ax.axvline(
        result.N_turns,
        color="#1c7c3b",
        linestyle=":",
        alpha=0.8,
        label=f"Selected N = {result.N_turns}",
    )
    ax.plot([result.N_turns], [result.B_pk_T * 1000.0], "o", color="#1c7c3b", markersize=7)
    ax.set_xlabel("Number of turns N")
    ax.set_ylabel("B_pk [mT]")
    ax.set_title("Saturation envelope vs turn count", fontsize=10)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper right", fontsize=8)
    return fig


def _fig_ku_vs_N(spec: Spec, core: Core, wire: Wire, result: DesignResult):
    """K_u(N) sweep — window utilisation as a function of turn
    count, with the design point and the spec's K_u_max line."""
    import numpy as _np

    from pfc_inductor.physics import copper as cp

    Ns = _np.arange(5, max(result.N_turns + 30, 80))
    Ku = _np.zeros_like(Ns, dtype=float)
    for i, N in enumerate(Ns):
        Ku[i] = cp.window_utilization(int(N), wire, core.Wa_mm2)
    fig, ax = plt.subplots(figsize=(7.0, 3.0), dpi=110)
    ax.plot(Ns, Ku * 100.0, color="#3a78b5", linewidth=1.6, label="K_u(N) for selected wire")
    ax.axhline(
        spec.Ku_max * 100.0,
        color="#a01818",
        linestyle="--",
        alpha=0.7,
        label=f"K_u limit = {spec.Ku_max * 100:.0f}%",
    )
    ax.axvline(
        result.N_turns,
        color="#1c7c3b",
        linestyle=":",
        alpha=0.8,
        label=f"Selected N = {result.N_turns}",
    )
    ax.plot([result.N_turns], [result.Ku_actual * 100.0], "o", color="#1c7c3b", markersize=7)
    ax.set_xlabel("Number of turns N")
    ax.set_ylabel("Window utilisation K_u [%]")
    ax.set_title("Window fill vs turn count", fontsize=10)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper left", fontsize=8)
    return fig


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
        "boost_ccm": "Active Boost-PFC CCM Inductor",
        "passive_choke": "Passive Line Choke",
        "line_reactor": "AC Line Reactor (50/60 Hz)",
    }.get(topology, "Inductor")


def _project_header(
    title: str,
    project_id: str,
    designer: str,
    revision: str,
    now: str,
    *,
    fonts: dict[str, str],
    styles: dict[str, ParagraphStyle],
) -> Table:
    """Two-column header. Left: title + "Engineering project report"
    subtitle. Right: project id, designer, revision, date.
    """
    left = [
        Paragraph(title, styles["title"]),
        Paragraph("Engineering project report — generated by MagnaDesign", styles["subtitle"]),
    ]
    right = [
        Paragraph(f"Project: <b>{project_id}</b>", styles["meta_value"]),
        Paragraph(f"Revision: <b>{revision}</b>", styles["meta"]),
        Paragraph(f"Designer: <b>{designer}</b>", styles["meta"]),
        Paragraph(f"Date: <b>{now}</b>", styles["meta"]),
    ]
    table = Table([[left, right]], colWidths=[110 * mm, 64 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, _Palette.rule),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _kv_flow(
    rows: list[tuple[str, str]],
    width_mm: float,
    fonts: dict[str, str],
    styles: dict[str, ParagraphStyle],
    label_col_pct: float = 0.45,
) -> Table:
    """Two-column key/value table at ``width_mm`` total width.
    Slightly wider label column than the datasheet's KV (0.45 vs
    0.42) because the project report uses longer labels (e.g.
    "Effective magnetic length" instead of just "le")."""
    label_w = width_mm * label_col_pct * mm
    value_w = width_mm * (1.0 - label_col_pct) * mm
    data = [[Paragraph(k, styles["body"]), Paragraph(v, styles["body"])] for (k, v) in rows]
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
            ("Topology", "Active boost-PFC, CCM"),
            (
                "Input voltage range",
                f"{spec.Vin_min_Vrms:.0f} – {spec.Vin_max_Vrms:.0f} Vrms "
                f"(nom. {spec.Vin_nom_Vrms:.0f} Vrms)",
            ),
            ("Output voltage (DC bus)", f"{spec.Vout_V:.0f} V"),
            ("Output power (rated)", f"{spec.Pout_W:.0f} W"),
            ("Switching frequency", f"{spec.f_sw_kHz:.0f} kHz"),
            ("Line frequency", f"{spec.f_line_Hz:.0f} Hz"),
            ("Inductor ripple target", f"{spec.ripple_pct:.0f} % of I_pk"),
            ("Efficiency assumed", f"{spec.eta:.2f}"),
        ]
    elif spec.topology == "line_reactor":
        rows = [
            ("Topology", f"AC line reactor — {spec.n_phases}φ (diode-rectifier + DC-link)"),
            ("Line voltage", f"{spec.Vin_nom_Vrms:.0f} {'V_LL' if spec.n_phases == 3 else 'V_LN'}"),
            ("Rated current", f"{spec.I_rated_Arms:.2f} Arms"),
            ("Line frequency", f"{spec.f_line_Hz:.0f} Hz"),
            ("% impedance target", f"{spec.pct_impedance:.1f} %"),
            ("Efficiency assumed", f"{spec.eta:.2f}"),
        ]
    else:  # passive_choke
        rows = [
            ("Topology", "Passive line choke (DC-side)"),
            ("Input voltage", f"{spec.Vin_nom_Vrms:.0f} Vrms"),
            ("Output power", f"{spec.Pout_W:.0f} W"),
            ("Line frequency", f"{spec.f_line_Hz:.0f} Hz"),
            ("Efficiency assumed", f"{spec.eta:.2f}"),
        ]
    # Common environmental constraints — every topology checks
    # against these in the thermal solve.
    rows.extend(
        [
            ("Ambient temperature", f"{spec.T_amb_C:.0f} °C"),
            ("Max winding temperature", f"{spec.T_max_C:.0f} °C"),
            ("Bsat margin", f"{spec.Bsat_margin * 100:.0f} %"),
            ("Window utilisation max (Ku_max)", f"{spec.Ku_max * 100:.0f} %"),
        ]
    )
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
        _kv_flow(_spec_input_data(spec), _USABLE_WIDTH_MM, fonts, styles),
    ]


# ---------------------------------------------------------------------------
# Selected components — core / material / wire. The engineer needs to
# see *what was picked* alongside the constraints (Ae, Wa, le, AL,
# MLT, μ, Bsat, A_cu) so the subsequent calculation lines can be
# verified by hand.
# ---------------------------------------------------------------------------
def _component_data_core(core: Core) -> list[tuple[str, str]]:
    return [
        ("Vendor / part number", f"{core.vendor} — {core.part_number}"),
        ("Shape", core.shape.upper()),
        ("Effective area Ae", f"{core.Ae_mm2:.1f} mm²"),
        ("Effective length le", f"{core.le_mm:.1f} mm"),
        ("Effective volume Ve", f"{core.Ve_mm3 / 1000:.2f} cm³"),
        ("Window area Wa", f"{core.Wa_mm2:.1f} mm²"),
        ("Mean length per turn MLT", f"{core.MLT_mm:.1f} mm"),
        ("Inductance factor AL", f"{core.AL_nH:.0f} nH/N²"),
        ("Air gap (centre leg)", f"{core.lgap_mm:.2f} mm" if core.lgap_mm > 0 else "no air gap"),
    ]


def _component_data_material(material: Material) -> list[tuple[str, str]]:
    return [
        ("Vendor / family", f"{material.vendor} — {material.name}"),
        ("Type", material.type),
        ("Initial permeability", f"μᵢ = {material.mu_initial:.0f}"),
        ("Saturation flux (25°C)", f"{material.Bsat_25C_T * 1000:.0f} mT"),
        ("Saturation flux (100°C)", f"{material.Bsat_100C_T * 1000:.0f} mT"),
        ("Density", f"{material.rho_kg_m3:.0f} kg/m³"),
    ]


def _component_data_wire(wire: Wire, result: DesignResult) -> list[tuple[str, str]]:
    rows = [
        ("Identifier", f"{wire.id} ({wire.type})"),
        ("Copper area A_cu", f"{wire.A_cu_mm2:.3f} mm²"),
    ]
    if wire.d_cu_mm:
        rows.append(("Copper diameter d_cu", f"{wire.d_cu_mm:.2f} mm"))
    if wire.d_iso_mm:
        rows.append(("Insulated diameter d_iso", f"{wire.d_iso_mm:.2f} mm"))
    rows.append(
        (
            "Window utilisation Ku (achieved)",
            f"{result.Ku_actual * 100:.1f} %",
        )
    )
    return rows


def _section_components(
    core: Core, material: Material, wire: Wire, result: DesignResult, fonts, styles
) -> list:
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
        _kv_flow(_component_data_core(core), _USABLE_WIDTH_MM, fonts, styles),
        Paragraph("2.2 Magnetic material", styles["h3"]),
        _kv_flow(_component_data_material(material), _USABLE_WIDTH_MM, fonts, styles),
        Paragraph("2.3 Winding wire", styles["h3"]),
        _kv_flow(_component_data_wire(wire, result), _USABLE_WIDTH_MM, fonts, styles),
    ]
    return flowables


# ---------------------------------------------------------------------------
# Final summary table — appears at the end of the report so the reader
# can see the complete result without scrolling back through the
# derivation chain.
# ---------------------------------------------------------------------------
def _section_result_summary(spec: Spec, result: DesignResult, fonts, styles) -> list:
    is_lr = spec.topology == "line_reactor"
    L_unit = "mH" if is_lr else "µH"
    L_act = result.L_actual_uH / 1000 if is_lr else result.L_actual_uH
    rows: list[tuple[str, str]] = [
        ("Inductance L", f"{L_act:.2f} {L_unit}"),
        ("Number of turns N", f"{result.N_turns}"),
        ("Peak flux density B_pk", f"{result.B_pk_T * 1000:.0f} mT"),
        ("Bsat limit", f"{result.B_sat_limit_T * 1000:.0f} mT"),
        ("Saturation margin", f"{result.sat_margin_pct:.0f} %"),
        ("Peak current I_pk", f"{result.I_pk_max_A:.2f} A"),
        ("Total RMS current", f"{result.I_rms_total_A:.2f} A"),
        ("DC resistance Rdc (hot)", f"{result.R_dc_ohm * 1000:.1f} mΩ"),
        ("AC resistance Rac @ fsw", f"{result.R_ac_ohm * 1000:.1f} mΩ"),
        ("Copper losses (DC + AC)", f"{result.losses.P_cu_dc_W + result.losses.P_cu_ac_W:.2f} W"),
        (
            "Core losses (line + ripple)",
            f"{result.losses.P_core_line_W + result.losses.P_core_ripple_W:.2f} W",
        ),
        ("Total losses P_total", f"{result.losses.P_total_W:.2f} W"),
        ("Temperature rise ΔT", f"{result.T_rise_C:.0f} K"),
        ("Winding temperature T_w", f"{result.T_winding_C:.0f} °C"),
        ("Window utilisation Ku", f"{result.Ku_actual * 100:.1f} %"),
        ("Status", "FEASIBLE" if result.is_feasible() else "WARNINGS"),
    ]
    return [
        Paragraph("Final summary", styles["h2"]),
        Paragraph(
            "Consolidated view of the design point computed in the "
            "preceding sections. All values converged at the steady-"
            "state winding temperature.",
            styles["body"],
        ),
        _kv_flow(rows, _USABLE_WIDTH_MM, fonts, styles, label_col_pct=0.55),
    ]


# ---------------------------------------------------------------------------
# Verification plots — waveform + loss breakdown + B–H trajectory.
# Imported from pdf_report so the typography matches the datasheet's
# performance section. Each plot is paired with its h3 header inside
# a KeepTogether so a page break never orphans a header.
# ---------------------------------------------------------------------------
def _section_verification(
    spec: Spec, core: Core, material: Material, wire: Wire, result: DesignResult, fonts, styles
) -> list:
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
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Inductor current — steady state", styles["h3"]),
                    _mpl_flowable(fig_wave, _USABLE_WIDTH_MM),
                ]
            )
        )
    fig_loss = _fig_loss_breakdown(result)
    if fig_loss is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Loss breakdown", styles["h3"]),
                    _mpl_flowable(fig_loss, _USABLE_WIDTH_MM),
                ]
            )
        )
    fig_bh = _fig_bh_trajectory(result, core, material)
    if fig_bh is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("B–H trajectory at operating point", styles["h3"]),
                    _mpl_flowable(fig_bh, _USABLE_WIDTH_MM),
                ]
            )
        )
    return flowables


# ---------------------------------------------------------------------------
# Per-topology body builders — derive the design step-by-step, with
# theory paragraphs, symbolic equations, substituted-form lines, and
# the numerical result the engine computed. Each topology's chain
# lives in its own helper for readability; the common dispatcher
# below picks the right one.
# ---------------------------------------------------------------------------
def _section_topology_body(
    spec: Spec, core: Core, material: Material, wire: Wire, result: DesignResult, fonts, styles
) -> list:
    if spec.topology == "boost_ccm":
        return _body_boost_ccm(
            spec,
            core,
            material,
            wire,
            result,
            fonts,
            styles,
        )
    if spec.topology == "line_reactor":
        return _body_line_reactor(
            spec,
            core,
            material,
            wire,
            result,
            fonts,
            styles,
        )
    if spec.topology == "passive_choke":
        return _body_passive_choke(
            spec,
            core,
            material,
            wire,
            result,
            fonts,
            styles,
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
def _body_boost_ccm(
    spec: Spec, core: Core, material: Material, wire: Wire, result: DesignResult, fonts, styles
) -> list:
    import math

    # Worst-case operating point — low line for currents.
    # ``_Vin_pk`` / ``_Tsw_us`` / ``_J_actual`` are computed for
    # readability of the analytical chain (every intermediate step
    # the textbook formulas reference) even though the report only
    # surfaces a subset directly. Underscore-prefixed so the unused-
    # variable lint doesn't fire while the analytical context stays
    # visible to a reader following the derivation.
    Vin_design = spec.Vin_min_Vrms
    _Vin_pk = math.sqrt(2.0) * Vin_design
    P_in = spec.Pout_W / spec.eta
    I_pk = math.sqrt(2.0) * P_in / Vin_design
    I_rms_line = spec.Pout_W / (spec.eta * Vin_design)
    fsw_Hz = spec.f_sw_kHz * 1000.0
    _Tsw_us = 1e6 / fsw_Hz
    delta_max_A = (spec.ripple_pct / 100.0) * I_pk
    L_req_uH = result.L_required_uH
    # Wire current density actually achieved at the chosen wire.
    _J_actual = result.I_rms_total_A / max(wire.A_cu_mm2, 1e-9)
    # Mean-length wire length.
    l_wire_m = result.N_turns * core.MLT_mm * 1e-3
    # Energy + area-product sizing requirements.
    E_J = _stored_energy_J(L_req_uH, I_pk)
    B_max_T = result.B_sat_limit_T  # the engine's Bsat × (1 − margin)
    Ap_required_mm4 = _area_product_mm4(
        L_uH=L_req_uH,
        I_pk_A=I_pk,
        I_rms_A=result.I_rms_total_A,
        K_u_target=spec.Ku_max,
        J_target=5.0,
        B_max_T=B_max_T,
    )
    Ap_selected_mm4 = core.Wa_mm2 * core.Ae_mm2
    Ap_margin_pct = (
        (Ap_selected_mm4 - Ap_required_mm4) / Ap_required_mm4 * 100.0
        if Ap_required_mm4 > 0
        else 0.0
    )

    flowables: list = []

    # ----- 3. Theory introduction -----
    flowables.append(Paragraph("3. Boost-PFC CCM — theory", styles["h2"]))
    flowables.append(
        Paragraph(
            "The boost-PFC stage shapes the input current into a "
            "scaled image of the input voltage so the converter "
            "presents a near-resistive load to the mains. In "
            "continuous-conduction mode (CCM) the inductor never fully "
            "demagnetises within a switching period, so the inductor "
            "current is the half-wave rectified line current riding on "
            "a switching-frequency triangular ripple.",
            styles["body"],
        )
    )
    flowables.append(
        Paragraph(
            "The derivation below follows Erickson &amp; Maksimovic, "
            "<i>Fundamentals of Power Electronics</i>, ch. 18 (averaged "
            "small-signal model of CCM PFC). The inductor sizing "
            "problem reduces to choosing L large enough that the "
            "worst-case peak-to-peak ripple Δi<sub>L,pp</sub>(t) stays "
            "inside the designer's budget — here, "
            f"{spec.ripple_pct:.0f}% of the line peak current.",
            styles["body"],
        )
    )

    # ----- 4. Worst-case currents -----
    flowables.append(Paragraph("4. Worst-case input currents", styles["h2"]))
    flowables.append(
        Paragraph(
            "Currents are computed at <b>low line</b> (V<sub>in,min</sub> "
            f"= {Vin_design:.0f} V<sub>rms</sub>), which maximises "
            "the input current for the rated output power.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"P_{in} = \frac{P_{out}}{\eta}",
            with_values=f"{spec.Pout_W:.0f} W / {spec.eta:.2f}",
            result=f"{P_in:.1f} W",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"I_{in,rms} = \frac{P_{in}}{V_{in,min}}",
            with_values=f"{P_in:.1f} W / {Vin_design:.0f} Vrms",
            result=f"{I_rms_line:.2f} Arms",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"I_{pk} = \sqrt{2}\,I_{in,rms}",
            with_values=f"√2 × {I_rms_line:.2f} A",
            result=f"{I_pk:.2f} A",
            note="Peak of the rectified line current — saturation envelope.",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 5. Inductance derivation -----
    flowables.append(
        Paragraph(
            "5. Inductance derivation (from first principles)",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "Consider a single switching cycle near the line peak. "
            "When the switch is ON, the inductor sees v<sub>in</sub>(t) "
            "across it and its current ramps up; when the switch is "
            "OFF, the inductor sees v<sub>in</sub>(t) − V<sub>out</sub> "
            "and the current ramps down. Steady-state volt-second "
            "balance over the switching period requires:",
            styles["body"],
        )
    )
    flowables.append(
        _derivation_step(
            "5.1 Volt-second balance",
            r"\langle v_L \rangle_{T_{sw}} = "
            r"v_{in}(t)\,d - (V_{out} - v_{in}(t))\,(1-d) = 0",
            note="Average inductor voltage over one switching period vanishes at steady state.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _derivation_step(
            "5.2 Solving for the duty cycle",
            r"d(t) = 1 - \frac{v_{in}(t)}{V_{out}}",
            note="With v_in(t) = V_in,pk · |sin θ|, the duty traces a smooth profile across the line cycle.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _derivation_step(
            "5.3 Per-cycle current ramp during the ON interval",
            r"\Delta i_{L,pp}(t) = \frac{v_{in}(t)\,d(t)}"
            r"{L\,f_{sw}}",
            note="Linear-ramp approximation valid in CCM where Δi << I_avg.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _derivation_step(
            "5.4 Substituting d(t)",
            r"\Delta i_{L,pp}(\theta) = \frac{V_{in,pk}|\sin\theta|"
            r"\,(1 - V_{in,pk}|\sin\theta|/V_{out})}{L\,f_{sw}}",
            note="Differentiating Δi vs θ shows the maximum at v_in = V_out/2, i.e. d = 0.5.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _derivation_step(
            "5.5 Worst-case ripple at d = 0.5",
            r"\Delta i_{L,pp,max} = \frac{V_{out}}{4\,L\,f_{sw}}",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        Paragraph(
            f"Setting Δi<sub>L,pp,max</sub> ≤ "
            f"{spec.ripple_pct:.0f}% × I<sub>pk</sub> = "
            f"{delta_max_A:.2f} A (the design budget) and solving "
            "for the minimum inductance:",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"L_{req} = \frac{V_{out}}{4\,f_{sw}\,\Delta i_{L,pp,max}}",
            with_values=(
                f"{spec.Vout_V:.0f} V / (4 × {spec.f_sw_kHz:.0f} kHz × {delta_max_A:.2f} A)"
            ),
            result=f"{L_req_uH:.1f} µH",
            note="Erickson eq. 18-22.",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 6. Required core size (BEFORE selection) -----
    flowables.append(
        Paragraph(
            "6. Required core size",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "Before picking a specific part, we estimate the smallest "
            "core that can store the design's energy and host the "
            "winding. The standard <i>area-product</i> "
            "(A<sub>p</sub> = W<sub>a</sub> × A<sub>e</sub>) "
            "metric ties together the four design knobs in a single "
            "scalar, and lets us compare any candidate core's "
            "datasheet number against a target.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"E = \frac{1}{2}\,L\,I_{pk}^{2}",
            with_values=(f"½ × {L_req_uH:.1f} µH × ({I_pk:.2f} A)²"),
            result=f"{E_J * 1000:.2f} mJ",
            note="Stored energy at peak current — the irreducible volume the magnetic field needs to occupy.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"A_p = W_a \cdot A_e \,\geq\, "
            r"\frac{L\,I_{pk}\,I_{rms}}"
            r"{K_u\,J\,B_{max}}",
            with_values=(
                f"({L_req_uH:.1f} µH × {I_pk:.2f} A × "
                f"{result.I_rms_total_A:.2f} A) / "
                f"({spec.Ku_max:.2f} × 5 A/mm² × "
                f"{B_max_T * 1000:.0f} mT)"
            ),
            result=f"{Ap_required_mm4 / 1e6:.2f} cm⁴",
            note="Kazimierczuk eq. 4.62. Targets: K_u = "
            f"{spec.Ku_max * 100:.0f}%, J = 5 A/mm², "
            "B_max = Bsat with safety margin.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        Paragraph(
            f"<b>Selected core's A<sub>p</sub></b> = W<sub>a</sub> × "
            f"A<sub>e</sub> = {core.Wa_mm2:.0f} × "
            f"{core.Ae_mm2:.1f} mm² = "
            f"<b>{Ap_selected_mm4 / 1e6:.2f} cm⁴</b> "
            f"(margin <b>{Ap_margin_pct:+.0f} %</b> over the "
            "required minimum). "
            + (
                "Selected core fits with comfortable headroom."
                if Ap_margin_pct >= 0
                else "Selected core's A_p is below the target — expect "
                "high winding fill or current density."
            ),
            styles["body"],
        )
    )

    # ----- 7. Number of turns + rolloff -----
    flowables.append(
        Paragraph(
            "7. Number of turns (with rolloff)",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "The inductance factor A<sub>L</sub> sets the no-bias "
            "inductance per turn²; powder-core materials roll off "
            "(μ%(H) drops with increasing DC bias), so the effective "
            "A<sub>L</sub> at the operating point is reduced by the "
            "rolloff factor μ%(H<sub>pk</sub>). The engine searches "
            "the smallest N satisfying L(N) ≥ L<sub>req</sub> with "
            "rolloff applied at the saturation peak.",
            styles["body"],
        )
    )
    flowables.append(
        _derivation_step(
            "7.1 Inductance with rolloff",
            r"L(N) = A_L \cdot N^2 \cdot \mu\%(H_{pk}(N))",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _derivation_step(
            "7.2 First-order estimate (no rolloff)",
            r"N_{0} \approx \sqrt{L_{req} / A_L}",
            note=(
                f"= √({L_req_uH:.1f} µH / {core.AL_nH:.0f} nH) ≈ "
                f"{int(math.sqrt(L_req_uH * 1000.0 / max(core.AL_nH, 1.0)))} "
                "turns; the iteration adds turns to compensate for "
                "rolloff at I<sub>pk</sub>."
            ),
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"H_{pk} = 0.4\pi \cdot \frac{N\,I_{pk}}{l_e}",
            with_values=(f"0.4π × ({result.N_turns} × {I_pk:.2f} A) / {core.le_mm:.1f} mm"),
            result=f"{result.H_dc_peak_Oe:.0f} Oe",
            note="Mixed-units convention used by powder-core vendors (Magnetics, ATM).",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"L_{actual} = A_L\,N^{2}\,\mu\%",
            with_values=(
                f"{core.AL_nH:.0f} nH/N² × {result.N_turns}² × {result.mu_pct_at_peak:.3f}"
            ),
            result=f"{result.L_actual_uH:.1f} µH",
            note=(
                f"L_actual ≥ L_req — feasible with "
                f"{(result.L_actual_uH / L_req_uH - 1) * 100:.0f} % margin."
                if result.L_actual_uH >= L_req_uH
                else "L_actual < L_req — engine raised a warning."
            ),
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 8. Peak flux density verification -----
    flowables.append(
        Paragraph(
            "8. Peak flux density verification",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "From Φ = L·i / N and B = Φ / A<sub>e</sub>, the peak "
            "flux density at the line-cycle envelope follows. The "
            "check is against the hot saturation flux "
            "B<sub>sat</sub>(100 °C) with a "
            f"{spec.Bsat_margin * 100:.0f}% design margin.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"B_{pk} = \frac{L_{actual}\,I_{pk}}{N\,A_e}",
            with_values=(
                f"({result.L_actual_uH:.1f} µH × {I_pk:.2f} A) / "
                f"({result.N_turns} × {core.Ae_mm2:.1f} mm²)"
            ),
            result=f"{result.B_pk_T * 1000:.0f} mT",
            note=(
                f"Bsat limit (with margin) = "
                f"{result.B_sat_limit_T * 1000:.0f} mT; saturation "
                f"margin = {result.sat_margin_pct:.0f} %."
            ),
            fonts=fonts,
            styles=styles,
        )
    )
    # Saturation curve.
    fig_b = _fig_bpk_vs_N(spec, core, material, result, I_pk_A=I_pk)
    if fig_b is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Saturation curve at I<sub>pk</sub>", styles["h3"]),
                    _mpl_flowable(fig_b, _USABLE_WIDTH_MM),
                    Paragraph(
                        "B<sub>pk</sub> as a function of N at the same "
                        "I<sub>pk</sub>. The selected N sits on the linear "
                        "side of the saturation knee; halving N would push "
                        "B above the limit.",
                        styles["note"],
                    ),
                ]
            )
        )
    # L(I) saturation rolloff — paired complement to B(N): B(N) shows
    # the headroom when sweeping turn count at fixed I, this one shows
    # the headroom when sweeping current at the chosen N.
    fig_LI = _fig_inductance_vs_current(material, core, result, I_pk_A=I_pk)
    if fig_LI is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Inductance vs current — bias rolloff", styles["h3"]),
                    _mpl_flowable(fig_LI, _USABLE_WIDTH_MM),
                    Paragraph(
                        "Direct read of how much L drops as the DC bias "
                        "rises. Useful for the protection / control "
                        "engineer: the small-signal control loop sees "
                        "L(I) at the operating point, not L₀.",
                        styles["note"],
                    ),
                ]
            )
        )

    # ----- 9. Wire sizing (with parallel-strands check) -----
    flowables.append(
        Paragraph(
            "9. Wire sizing &amp; parallel-strands check",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "The wire is sized in two steps. First a target current "
            "density picks the cross-section; then a skin-depth check "
            "decides whether a single solid strand is acceptable or "
            "whether the winding needs Litz / parallel strands to "
            "avoid AC resistance penalties.",
            styles["body"],
        )
    )
    pp = _parallel_strands_recommendation(
        wire,
        result.I_rms_total_A,
        fsw_Hz,
        result.T_winding_C,
        J_target=5.0,
    )
    flowables.append(
        _eqn_block(
            r"A_{cu,req} = \frac{I_{rms,total}}{J_{target}}",
            with_values=(f"{result.I_rms_total_A:.2f} A / 5 A/mm²"),
            result=f"{pp['A_cu_required_mm2']:.3f} mm²",
            note=(
                "J = 5 A/mm² is the natural-convection mid-range for "
                "copper; reduce to 3 – 4 A/mm² for sealed enclosures."
            ),
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        Paragraph(
            f"Selected wire: <b>{wire.id}</b>, A<sub>cu</sub> = "
            f"<b>{pp['A_cu_selected_mm2']:.3f} mm²</b>, d<sub>cu</sub> = "
            f"<b>{pp['d_cu_mm']:.2f} mm</b>; actual current density "
            f"J = <b>{pp['J_actual_A_per_mm2']:.2f} A/mm²</b>.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"\delta(f_{sw},T) = "
            r"\sqrt{\frac{\rho_{Cu}(T)}{\pi\,\mu_0\,f_{sw}}}",
            with_values=(f"√[ρ({result.T_winding_C:.0f}°C) / (π · µ₀ · {spec.f_sw_kHz:.0f} kHz)]"),
            result=f"{pp['delta_mm']:.3f} mm (2δ = {pp['two_delta_mm']:.3f} mm)",
            note="Skin depth in copper at the switching frequency and converged winding temperature.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        Paragraph(
            f"<b>Verdict:</b> {pp['advice']}",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"l_{wire} = N \cdot \mathrm{MLT}",
            with_values=f"{result.N_turns} × {core.MLT_mm:.1f} mm",
            result=f"{l_wire_m:.2f} m",
            note="Total winding length for the BOM cut-list (single strand; multiply by n_strands if parallelled).",
            fonts=fonts,
            styles=styles,
        )
    )
    # Window-fill curve.
    fig_ku = _fig_ku_vs_N(spec, core, wire, result)
    if fig_ku is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Window-fill curve", styles["h3"]),
                    _mpl_flowable(fig_ku, _USABLE_WIDTH_MM),
                    Paragraph(
                        "K<sub>u</sub> as a function of N for the selected "
                        "wire — the design point sits below the limit, "
                        "leaving room for insulation and an outer wrap.",
                        styles["note"],
                    ),
                ]
            )
        )

    # ----- 10-12. Common winding/losses/thermal -----
    flowables.extend(
        _section_winding_losses_thermal(
            spec,
            core,
            wire,
            result,
            section_num=10,
            fonts=fonts,
            styles=styles,
        )
    )
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
    spec: Spec,
    core: Core,
    wire: Wire,
    result: DesignResult,
    *,
    section_num: int,
    fonts,
    styles,
) -> list:
    """Return sections numbered ``section_num``, ``section_num+1``,
    ``section_num+2`` covering winding resistance & copper losses,
    core losses, and thermal verification."""
    flowables: list = []

    # Worst-case currents already on ``result`` — same numbers the
    # engine used so the displayed values match the rest of the
    # report to the printed precision.
    Vin_design = (
        spec.Vin_min_Vrms if spec.topology in ("boost_ccm", "passive_choke") else spec.Vin_nom_Vrms
    )
    if spec.topology == "boost_ccm":
        I_rms_line = spec.Pout_W / (spec.eta * Vin_design)
    elif spec.topology == "line_reactor":
        I_rms_line = spec.I_rated_Arms
    else:
        I_rms_line = spec.Pout_W / (spec.eta * Vin_design)
    l_wire_m = result.N_turns * core.MLT_mm * 1e-3
    is_ac_relevant = spec.topology == "boost_ccm"

    # ----- Winding resistance + copper losses -----
    flowables.append(
        Paragraph(
            f"{section_num}. Winding resistance &amp; copper losses",
            styles["h2"],
        )
    )
    if is_ac_relevant:
        flowables.append(
            Paragraph(
                "DC resistance follows from the resistivity of copper, "
                "temperature-corrected to the converged winding "
                "temperature; AC resistance at the switching frequency "
                "uses Dowell's analytical 1-D solution for skin + "
                "proximity effects.",
                styles["body"],
            )
        )
    else:
        flowables.append(
            Paragraph(
                "Resistance is computed from the resistivity of copper "
                "at the converged winding temperature. The skin-effect "
                "correction at line frequency is negligible at the wire "
                "gauges used here, so R<sub>ac</sub> ≈ R<sub>dc</sub>.",
                styles["body"],
            )
        )
    flowables.append(
        _eqn_block(
            r"R_{dc}(T) = \rho_{Cu}(T) \cdot \frac{l_{wire}}{A_{cu}}",
            with_values=(
                f"ρ(T = {result.T_winding_C:.0f}°C) × {l_wire_m:.2f} m / {wire.A_cu_mm2:.3f} mm²"
            ),
            result=f"{result.R_dc_ohm * 1000:.1f} mΩ",
            note=(
                f"R_ac at "
                f"{'fsw' if is_ac_relevant else 'f_line'} = "
                f"{result.R_ac_ohm * 1000:.1f} mΩ."
            ),
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"P_{Cu,DC} = R_{dc}(T) \cdot I_{rms}^{\,2}",
            with_values=(f"{result.R_dc_ohm * 1000:.1f} mΩ × ({I_rms_line:.2f} A)²"),
            result=f"{result.losses.P_cu_dc_W:.2f} W",
            fonts=fonts,
            styles=styles,
        )
    )
    if is_ac_relevant:
        flowables.append(
            _eqn_block(
                r"P_{Cu,AC} = R_{ac}(f_{sw}) \cdot I_{ripple,rms}^{\,2}",
                with_values=(f"{result.R_ac_ohm * 1000:.1f} mΩ × I_ripple_rms²"),
                result=f"{result.losses.P_cu_ac_W:.3f} W",
                note="I_ripple_rms is the line-cycle-average RMS of the triangular HF ripple.",
                fonts=fonts,
                styles=styles,
            )
        )
    else:
        flowables.append(
            Paragraph(
                f"P<sub>Cu,AC</sub> = "
                f"{result.losses.P_cu_ac_W:.4f} W "
                "(negligible — no switching-frequency ripple).",
                styles["body"],
            )
        )

    # ----- Core losses -----
    flowables.append(
        Paragraph(
            f"{section_num + 1}. Core losses (anchored Steinmetz / iGSE)",
            styles["h2"],
        )
    )
    if spec.topology == "line_reactor":
        flowables.append(
            Paragraph(
                "The reactor is excited solely at the line frequency "
                "(50/60 Hz). The flux swing is the bipolar excursion "
                "around zero driven by the fundamental V across the "
                "winding. Core losses are evaluated with anchored "
                "Steinmetz at f<sub>line</sub>; there is no separate "
                "ripple band.",
                styles["body"],
            )
        )
    elif spec.topology == "passive_choke":
        flowables.append(
            Paragraph(
                "Excitation is the rectified line-frequency current "
                "envelope; there is no switching ripple. Loss "
                "evaluation uses anchored Steinmetz at f<sub>line</sub> "
                "with the peak flux density driven by I<sub>pk</sub>.",
                styles["body"],
            )
        )
    else:  # boost_ccm
        flowables.append(
            Paragraph(
                "Two distinct excitations: a line-frequency component "
                "swung by the rectified envelope, and a switching-"
                "frequency component swung by the per-cycle ripple. "
                "The engine evaluates the iGSE form of Steinmetz with "
                "material-anchored coefficients, integrated over the "
                "line cycle so the variable Δ B(t) profile is captured "
                "exactly.",
                styles["body"],
            )
        )
    flowables.append(
        _eqn_block(
            r"P_{core} = k_i \cdot f^{\alpha} \cdot \Delta B^{\beta} \cdot V_e",
            note=(
                "Material-anchored Steinmetz; the engine evaluates "
                "the iGSE form for the swing the topology actually sees."
            ),
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"P_{core,line} \approx k_i \cdot f_{line}^{\alpha} "
            r"\cdot B_{pk}^{\beta} \cdot V_e",
            with_values=(
                f"line-band Steinmetz at f = {spec.f_line_Hz:.0f} Hz, "
                f"B_pk = {result.B_pk_T * 1000:.0f} mT, "
                f"V_e = {core.Ve_mm3 / 1000:.1f} cm³"
            ),
            result=f"{result.losses.P_core_line_W:.3f} W",
            fonts=fonts,
            styles=styles,
        )
    )
    if is_ac_relevant:
        flowables.append(
            _eqn_block(
                r"P_{core,ripple} = \langle k_i \cdot f_{sw}^{\alpha} "
                r"\cdot \Delta B_{pp}(\theta)^{\beta} \cdot V_e "
                r"\rangle_{\theta}",
                with_values=(f"iGSE integrated over θ at f_sw = {spec.f_sw_kHz:.0f} kHz"),
                result=f"{result.losses.P_core_ripple_W:.3f} W",
                note=(
                    "Integration over θ captures the worst-case ripple at the cusp where d = 0.5."
                ),
                fonts=fonts,
                styles=styles,
            )
        )
    else:
        flowables.append(
            Paragraph(
                f"P<sub>core,ripple</sub> = "
                f"{result.losses.P_core_ripple_W:.4f} W "
                "(negligible — no switching ripple band).",
                styles["body"],
            )
        )
    flowables.append(
        _eqn_block(
            r"P_{total} = P_{Cu,DC} + P_{Cu,AC} + P_{core,line} "
            r"+ P_{core,ripple}",
            with_values=(
                f"{result.losses.P_cu_dc_W:.2f} + "
                f"{result.losses.P_cu_ac_W:.3f} + "
                f"{result.losses.P_core_line_W:.3f} + "
                f"{result.losses.P_core_ripple_W:.3f} W"
            ),
            result=f"{result.losses.P_total_W:.2f} W",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- Thermal -----
    flowables.append(
        Paragraph(
            f"{section_num + 2}. Thermal verification",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "Steady-state winding temperature is found from a natural-"
            "convection thermal-resistance model on the core's outer "
            "surface, iterated until the Cu/core losses (which depend "
            "on T through ρ<sub>Cu</sub>) and ΔT are self-consistent.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"\Delta T = T_{winding} - T_{amb}",
            with_values=(f"{result.T_winding_C:.0f} °C − {spec.T_amb_C:.0f} °C"),
            result=f"{result.T_rise_C:.0f} K",
            note=(
                "Converged at the engine's iterated steady state. "
                f"T<sub>w</sub> = {result.T_winding_C:.0f} °C is "
                f"{'within' if result.T_winding_C <= spec.T_max_C else 'above'} "
                f"the {spec.T_max_C:.0f} °C limit."
            ),
            fonts=fonts,
            styles=styles,
        )
    )
    return flowables


# ---------------------------------------------------------------------------
# Boost CCM — patch the shared block in (sections 9, 10, 11).
# ---------------------------------------------------------------------------


def _body_line_reactor(
    spec: Spec, core: Core, material: Material, wire: Wire, result: DesignResult, fonts, styles
) -> list:
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
    flowables.append(Paragraph("3. Line reactor — theory", styles["h2"]))
    flowables.append(
        Paragraph(
            "The line reactor sits in series with each phase between "
            "the AC mains and the diode bridge that feeds the DC-link "
            "of a variable-frequency drive (VFD). Its purpose is "
            "twofold:",
            styles["body"],
        )
    )
    flowables.append(
        Paragraph(
            "&nbsp;&nbsp;• Inject series impedance at line frequency "
            "to limit the di/dt during diode commutation; this softens "
            "the line-current notches and reduces the harmonic "
            "spectrum.<br/>"
            "&nbsp;&nbsp;• Provide a small voltage drop ahead of the "
            "rectifier so the VFD's input current waveform widens, "
            "approaching a sinusoid; this directly reduces THD.",
            styles["body"],
        )
    )
    flowables.append(
        Paragraph(
            "Industry sizing convention (NEMA, Pomilio Cap. 11) is "
            "to specify the reactor as a fraction of the load's base "
            "impedance — typically 3 % to 5 % for general service, "
            "8 % to 12 % for high-distortion-sensitive applications. "
            "The engine uses %Z = "
            f"{spec.pct_impedance:.1f} % for this design.",
            styles["body"],
        )
    )

    # ----- 4. Base impedance + reactor impedance -----
    flowables.append(
        Paragraph(
            "4. Base impedance &amp; reactor reactance",
            styles["h2"],
        )
    )
    if is_3ph:
        flowables.append(
            Paragraph(
                "For a 3-phase load the per-phase voltage is the line-to-line rms divided by √3.",
                styles["body"],
            )
        )
        flowables.append(
            _eqn_block(
                r"V_{phase} = \frac{V_{LL}}{\sqrt{3}}",
                with_values=f"{spec.Vin_nom_Vrms:.0f} Vrms / √3",
                result=f"{V_phase:.1f} Vrms",
                fonts=fonts,
                styles=styles,
            )
        )
    else:
        flowables.append(
            _eqn_block(
                r"V_{phase} = V_{LN}",
                with_values=f"{spec.Vin_nom_Vrms:.0f} Vrms",
                result=f"{V_phase:.1f} Vrms",
                fonts=fonts,
                styles=styles,
            )
        )
    flowables.append(
        _eqn_block(
            r"Z_{base} = \frac{V_{phase}}{I_{rated}}",
            with_values=f"{V_phase:.1f} V / {spec.I_rated_Arms:.2f} A",
            result=f"{Z_base:.3f} Ω",
            note="Per-phase base impedance — the reference for the %Z spec.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"X_L = \frac{\%Z}{100} \cdot Z_{base}",
            with_values=(f"({spec.pct_impedance:.1f}/100) × {Z_base:.3f} Ω"),
            result=f"{X_L:.3f} Ω",
            note="Reactor reactance at the line frequency.",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 5. Required inductance -----
    flowables.append(Paragraph("5. Required inductance", styles["h2"]))
    flowables.append(
        _eqn_block(
            r"L_{req} = \frac{X_L}{2\pi \cdot f_{line}}",
            with_values=(f"{X_L:.3f} Ω / (2π × {spec.f_line_Hz:.0f} Hz)"),
            result=f"{L_req_mH:.3f} mH",
            note="L = X/(ωf); the voltage drop at rated current equals %Z by definition.",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 6. Required core size -----
    I_pk_lr = math.sqrt(2.0) * spec.I_rated_Arms
    E_lr = _stored_energy_J(L_req_mH * 1000.0, I_pk_lr)
    Ap_required_lr = _area_product_mm4(
        L_uH=L_req_mH * 1000.0,
        I_pk_A=I_pk_lr,
        I_rms_A=spec.I_rated_Arms,
        K_u_target=spec.Ku_max,
        J_target=4.0,
        B_max_T=result.B_sat_limit_T,
    )
    Ap_selected_lr = core.Wa_mm2 * core.Ae_mm2
    Ap_margin_lr = (
        (Ap_selected_lr - Ap_required_lr) / Ap_required_lr * 100.0 if Ap_required_lr > 0 else 0.0
    )
    flowables.append(Paragraph("6. Required core size", styles["h2"]))
    flowables.append(
        Paragraph(
            "The line reactor stores the energy associated with its "
            "fundamental flux swing. The area-product formula gives a "
            "lower bound on the core size; the actual selection is "
            "driven by saturation flux (silicon-steel: ~1.5 T) and "
            "thermal headroom rather than window cramp.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"E = \frac{1}{2}\,L\,I_{pk}^{2}",
            with_values=f"½ × {L_req_mH:.3f} mH × ({I_pk_lr:.2f} A)²",
            result=f"{E_lr * 1000:.1f} mJ",
            note="Stored energy at peak line current.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"A_p = W_a \cdot A_e \,\geq\, "
            r"\frac{L\,I_{pk}\,I_{rms}}{K_u\,J\,B_{max}}",
            with_values=(
                f"({L_req_mH:.3f} mH × {I_pk_lr:.2f} A × "
                f"{spec.I_rated_Arms:.2f} A) / "
                f"({spec.Ku_max:.2f} × 4 A/mm² × "
                f"{result.B_sat_limit_T * 1000:.0f} mT)"
            ),
            result=f"{Ap_required_lr / 1e6:.2f} cm⁴",
            note="Kazimierczuk eq. 4.62. J = 4 A/mm² for line-frequency operation (no skin penalty, more conservative thermal target).",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        Paragraph(
            f"<b>Selected core's A<sub>p</sub></b> = "
            f"{core.Wa_mm2:.0f} × {core.Ae_mm2:.1f} mm² = "
            f"<b>{Ap_selected_lr / 1e6:.2f} cm⁴</b> "
            f"(margin <b>{Ap_margin_lr:+.0f} %</b>). "
            + (
                "Selected core fits with comfortable headroom."
                if Ap_margin_lr >= 0
                else "Core is below the area-product minimum — review."
            ),
            styles["body"],
        )
    )

    # ----- 7. Number of turns + flux verification -----
    flowables.append(
        Paragraph(
            "7. Number of turns &amp; peak flux verification",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "Silicon-steel cores have a well-defined air gap that "
            "linearises L vs N (no powder-style bias rolloff), so the "
            "turn count comes directly from L = A<sub>L</sub> · N². "
            "The flux swing is set by the fundamental voltage across "
            "the winding, V<sub>L,rms</sub> = (%Z/100) · "
            "V<sub>phase</sub>; from V = N · dΦ/dt the peak flux "
            "density follows.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"N \approx \sqrt{L_{req} / A_L}",
            with_values=(f"√({L_req_mH * 1000:.0f} µH / {core.AL_nH:.0f} nH/N²)"),
            result=f"{result.N_turns} turns",
            note="No bias rolloff for laminated silicon-steel; the engine's iteration converges in one step.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
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
                f"saturation margin = {result.sat_margin_pct:.0f} %."
            ),
            fonts=fonts,
            styles=styles,
        )
    )
    fig_b_lr = _fig_bpk_vs_N(spec, core, material, result, I_pk_A=I_pk_lr)
    if fig_b_lr is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Saturation curve at I<sub>pk</sub>", styles["h3"]),
                    _mpl_flowable(fig_b_lr, _USABLE_WIDTH_MM),
                    Paragraph(
                        "Without an air gap, B<sub>pk</sub>(N) follows the "
                        "1/N inverse curve closely. The selected N sits in "
                        "the linear region with the desired flux density.",
                        styles["note"],
                    ),
                ]
            )
        )
    fig_LI_lr = _fig_inductance_vs_current(
        material,
        core,
        result,
        I_pk_A=I_pk_lr,
    )
    if fig_LI_lr is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Inductance vs current — bias rolloff", styles["h3"]),
                    _mpl_flowable(fig_LI_lr, _USABLE_WIDTH_MM),
                    Paragraph(
                        "Reactor inductance vs DC bias current. For "
                        "silicon-steel laminations the trace is essentially "
                        "flat until B approaches Bsat, where μ collapses; "
                        "the design's headroom is read directly from the "
                        "knee location.",
                        styles["note"],
                    ),
                ]
            )
        )
    fig_PF_lr = _fig_pf_vs_inductance(spec, result)
    if fig_PF_lr is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph(
                        "Power factor vs inductance — design-space view",
                        styles["h3"],
                    ),
                    _mpl_flowable(fig_PF_lr, _USABLE_WIDTH_MM),
                    Paragraph(
                        "PF rises sharply with the first few mH of "
                        "reactance and saturates past ~5 % impedance — "
                        "the diminishing-returns plateau lets the "
                        "engineer pick the smallest L that still meets "
                        "the THD / PF spec. The dashed red trace is the "
                        "apparent power S = P_active / PF the source "
                        "has to deliver, in kVA.",
                        styles["note"],
                    ),
                ]
            )
        )
    fig_PL_lr = _fig_power_vs_inductance(
        spec,
        core,
        material,
        result,
        I_pk_A=I_pk_lr,
    )
    if fig_PL_lr is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph(
                        "Active power vs inductance — saturation impact",
                        styles["h3"],
                    ),
                    _mpl_flowable(fig_PL_lr, _USABLE_WIDTH_MM),
                    Paragraph(
                        "Parametric trace: as the bias current rises, "
                        "the effective L drops AND the input PF "
                        "degrades, so the active power throughput "
                        "doesn't scale linearly with I — the choke is "
                        "protecting the source from delivering "
                        "uncontrolled apparent power into a saturated "
                        "magnetic. The operating point sits at "
                        "(L_op, P_rated).",
                        styles["note"],
                    ),
                ]
            )
        )

    # ----- 8. Voltage drop & THD -----
    flowables.append(
        Paragraph(
            "8. Voltage drop &amp; THD prediction",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "By the definition of base impedance, the voltage drop "
            "across the reactor at rated current is exactly the "
            "specified %Z. The empirical THD prediction follows "
            "Pomilio's textbook fit and matches IEEE 519 application "
            "data within ±5 percentage points.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"V_{drop}/V_{phase} = \frac{\omega L \cdot I_{rated}}"
            r"{V_{phase}} \cdot 100\%",
            with_values=(
                f"(2π × {spec.f_line_Hz:.0f} × "
                f"{L_actual_mH:.3f} mH × "
                f"{spec.I_rated_Arms:.2f} A) / {V_phase:.1f} V × 100%"
            ),
            result=f"{V_drop_pct:.2f} %",
            note="Equals the spec'd %Z by construction; verifies the L sizing.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"THD_{est} \approx \frac{75}{\sqrt{\%Z}}",
            with_values=f"75 / √{spec.pct_impedance:.1f}",
            result=f"{THD_pct:.1f} %",
            note="Empirical fit (Pomilio Cap. 11, Bonner): ±5 pp accuracy vs measured.",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 9. Commutation overlap -----
    flowables.append(
        Paragraph(
            "9. Commutation overlap (Mohan/Undeland)",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "During commutation between two diodes of the bridge, the "
            "reactor inductance forces a finite overlap angle μ over "
            "which both diodes conduct simultaneously. The notch in "
            "the line voltage during this interval drives the "
            "harmonic content; longer μ → softer notch → less "
            "high-order harmonics.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
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
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 10. Wire sizing (no skin penalty at line frequency) -----
    flowables.append(
        Paragraph(
            "10. Wire sizing &amp; window-fill check",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "Line reactors carry only fundamental current; skin depth "
            "at 50/60 Hz is ~9 mm so any reasonable solid wire is "
            "fully penetrated. The wire is sized purely against a "
            "current-density target.",
            styles["body"],
        )
    )
    pp_lr = _parallel_strands_recommendation(
        wire,
        spec.I_rated_Arms,
        spec.f_line_Hz,
        result.T_winding_C,
        J_target=4.0,
    )
    flowables.append(
        _eqn_block(
            r"A_{cu,req} = \frac{I_{rated}}{J_{target}}",
            with_values=f"{spec.I_rated_Arms:.2f} A / 4 A/mm²",
            result=f"{pp_lr['A_cu_required_mm2']:.3f} mm²",
            note="J = 4 A/mm² is the conservative target for line-frequency operation.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        Paragraph(
            f"Selected wire: <b>{wire.id}</b>, A<sub>cu</sub> = "
            f"<b>{pp_lr['A_cu_selected_mm2']:.3f} mm²</b>; actual J "
            f"= <b>{pp_lr['J_actual_A_per_mm2']:.2f} A/mm²</b>. "
            f"<b>Verdict:</b> {pp_lr['advice']}",
            styles["body"],
        )
    )
    fig_ku_lr = _fig_ku_vs_N(spec, core, wire, result)
    if fig_ku_lr is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Window-fill curve", styles["h3"]),
                    _mpl_flowable(fig_ku_lr, _USABLE_WIDTH_MM),
                    Paragraph(
                        "K<sub>u</sub>(N) for the selected wire — the "
                        "design point sits below the limit, leaving room "
                        "for inter-layer insulation.",
                        styles["note"],
                    ),
                ]
            )
        )

    # ----- 11-13. Common winding/losses/thermal -----
    flowables.extend(
        _section_winding_losses_thermal(
            spec,
            core,
            wire,
            result,
            section_num=11,
            fonts=fonts,
            styles=styles,
        )
    )
    return flowables


def _body_passive_choke(
    spec: Spec, core: Core, material: Material, wire: Wire, result: DesignResult, fonts, styles
) -> list:
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
    # ``_omega`` is part of the canonical Z = ωL derivation used in
    # the choke-design flowchart this report walks through; assigned
    # for chain-of-thought clarity even though Z_base goes through
    # a different path here.
    _omega = 2.0 * math.pi * max(spec.f_line_Hz, 1.0)
    Z_base = (Vin**2) / max(P_in, 1.0)
    L_actual_uH = result.L_actual_uH
    L_actual_mH = L_actual_uH / 1000.0
    V_drop_pct = result.voltage_drop_pct or 0.0
    THD_pct = result.thd_estimate_pct or 0.0
    I_pk = result.I_line_pk_A
    I_rms = spec.Pout_W / (spec.eta * Vin)

    flowables: list = []

    # ----- 3. Theory -----
    flowables.append(Paragraph("3. Passive line choke — theory", styles["h2"]))
    flowables.append(
        Paragraph(
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
        )
    )
    flowables.append(
        Paragraph(
            "Electrically the topology is identical to a 1-φ line "
            "reactor, so the sizing formulas are the same. The "
            "differences are operational: passive chokes are typically "
            "smaller (lower %Z, since the load is single-phase low-"
            "power rather than 3-phase industrial) and tuned for "
            "compliance with IEC 61000-3-2 Class D rather than "
            "61000-3-12 industrial limits.",
            styles["body"],
        )
    )

    # ----- 4. Worst-case currents -----
    flowables.append(Paragraph("4. Worst-case input currents", styles["h2"]))
    flowables.append(
        _eqn_block(
            r"P_{in} = \frac{P_{out}}{\eta}",
            with_values=f"{spec.Pout_W:.0f} W / {spec.eta:.2f}",
            result=f"{P_in:.1f} W",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"I_{rms} = \frac{P_{in}}{V_{in}}",
            with_values=f"{P_in:.1f} W / {Vin:.0f} Vrms",
            result=f"{I_rms:.2f} Arms",
            note="At unity-PF (idealised); the actual rectifier draws a higher RMS, but the choke is sized against this baseline.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"I_{pk} = \sqrt{2}\,I_{rms}",
            with_values=f"√2 × {I_rms:.2f} A",
            result=f"{I_pk:.2f} A",
            note="Peak of the fundamental — sets the saturation envelope.",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 5. Required inductance (empirical) -----
    flowables.append(Paragraph("5. Required inductance", styles["h2"]))
    flowables.append(
        Paragraph(
            "Erickson Ch. 18 derives an empirical sizing rule based on "
            "the load's base impedance and a target THD. The "
            "coefficient k(THD) ≈ 0.35 for 30 % THD; smaller k for "
            "looser THD, larger for tighter THD.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"Z_{base} = \frac{V_{in}^{2}}{P_{in}}",
            with_values=f"({Vin:.0f} V)² / {P_in:.1f} W",
            result=f"{Z_base:.2f} Ω",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"L_{req} = \frac{k(THD) \cdot Z_{base}}"
            r"{2\pi \cdot f_{line}}",
            with_values=(f"(0.35 × {Z_base:.2f} Ω) / (2π × {spec.f_line_Hz:.0f} Hz)"),
            result=f"{result.L_required_uH:.1f} µH",
            note="Erickson eq. 18-44 (empirical, target THD ≈ 30 %).",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 6. Required core size -----
    E_pc = _stored_energy_J(result.L_required_uH, I_pk)
    Ap_required_pc = _area_product_mm4(
        L_uH=result.L_required_uH,
        I_pk_A=I_pk,
        I_rms_A=I_rms,
        K_u_target=spec.Ku_max,
        J_target=4.0,
        B_max_T=result.B_sat_limit_T,
    )
    Ap_selected_pc = core.Wa_mm2 * core.Ae_mm2
    Ap_margin_pc = (
        (Ap_selected_pc - Ap_required_pc) / Ap_required_pc * 100.0 if Ap_required_pc > 0 else 0.0
    )
    flowables.append(Paragraph("6. Required core size", styles["h2"]))
    flowables.append(
        Paragraph(
            "Same energy-storage / area-product reasoning as a "
            "line reactor: the choke must accommodate the peak flux "
            "without saturating and host the winding without "
            "exceeding K<sub>u,max</sub>.",
            styles["body"],
        )
    )
    flowables.append(
        _eqn_block(
            r"E = \frac{1}{2}\,L\,I_{pk}^{2}",
            with_values=(f"½ × {result.L_required_uH:.1f} µH × ({I_pk:.2f} A)²"),
            result=f"{E_pc * 1000:.2f} mJ",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"A_p = W_a \cdot A_e \,\geq\, "
            r"\frac{L\,I_{pk}\,I_{rms}}{K_u\,J\,B_{max}}",
            with_values=(
                f"({result.L_required_uH:.1f} µH × {I_pk:.2f} A × "
                f"{I_rms:.2f} A) / ({spec.Ku_max:.2f} × 4 A/mm² × "
                f"{result.B_sat_limit_T * 1000:.0f} mT)"
            ),
            result=f"{Ap_required_pc / 1e6:.2f} cm⁴",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        Paragraph(
            f"<b>Selected core's A<sub>p</sub></b> = "
            f"{core.Wa_mm2:.0f} × {core.Ae_mm2:.1f} mm² = "
            f"<b>{Ap_selected_pc / 1e6:.2f} cm⁴</b> "
            f"(margin <b>{Ap_margin_pc:+.0f} %</b>). "
            + (
                "Selected core fits with comfortable headroom."
                if Ap_margin_pc >= 0
                else "Core is below the area-product minimum — review."
            ),
            styles["body"],
        )
    )

    # ----- 7. Number of turns + flux -----
    flowables.append(
        Paragraph(
            "7. Number of turns &amp; peak flux",
            styles["h2"],
        )
    )
    flowables.append(
        _eqn_block(
            r"L = A_L \cdot N^2 \cdot \mu\%(H_{pk})",
            with_values=(
                f"{core.AL_nH:.0f} nH/N² × {result.N_turns}² × {result.mu_pct_at_peak:.3f}"
            ),
            result=f"{L_actual_uH:.1f} µH",
            note=(
                f"At N = {result.N_turns}, "
                f"H<sub>pk</sub> = {result.H_dc_peak_Oe:.0f} Oe "
                f"and μ%(H) = {result.mu_pct_at_peak * 100:.1f} %."
            ),
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
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
            fonts=fonts,
            styles=styles,
        )
    )
    fig_b_pc = _fig_bpk_vs_N(spec, core, material, result, I_pk_A=I_pk)
    if fig_b_pc is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Saturation curve at I<sub>pk</sub>", styles["h3"]),
                    _mpl_flowable(fig_b_pc, _USABLE_WIDTH_MM),
                ]
            )
        )
    fig_LI_pc = _fig_inductance_vs_current(
        material,
        core,
        result,
        I_pk_A=I_pk,
    )
    if fig_LI_pc is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Inductance vs current — bias rolloff", styles["h3"]),
                    _mpl_flowable(fig_LI_pc, _USABLE_WIDTH_MM),
                    Paragraph(
                        "L drops from L₀ (zero-bias) to the operating "
                        "point as the rectified line current rises through "
                        "its envelope. The extent of rolloff sets the "
                        "effective %Z seen by the rectifier across the "
                        "line cycle.",
                        styles["note"],
                    ),
                ]
            )
        )
    fig_PF_pc = _fig_pf_vs_inductance(spec, result)
    if fig_PF_pc is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph(
                        "Power factor vs inductance — design-space view",
                        styles["h3"],
                    ),
                    _mpl_flowable(fig_PF_pc, _USABLE_WIDTH_MM),
                    Paragraph(
                        "Capacitor-input rectifier without choke sits at "
                        "PF ≈ 0.55. Adding the series choke widens the "
                        "rectifier's conduction angle and pushes PF "
                        "asymptotically toward ≈ 0.95 (Erickson Ch. 18 / "
                        "Pomilio Cap. 13). The dashed red trace is the "
                        "apparent power S = P_active / PF the source "
                        "has to deliver, in kVA.",
                        styles["note"],
                    ),
                ]
            )
        )
    fig_PL_pc = _fig_power_vs_inductance(
        spec,
        core,
        material,
        result,
        I_pk_A=I_pk,
    )
    if fig_PL_pc is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph(
                        "Active power vs inductance — saturation impact",
                        styles["h3"],
                    ),
                    _mpl_flowable(fig_PL_pc, _USABLE_WIDTH_MM),
                    Paragraph(
                        "Same parametric construction as the L vs I "
                        "curve, re-plotted in P → L coordinates. As "
                        "the rectified line current pulses through I_pk "
                        "the choke saturates and PF degrades, so the "
                        "real-power throughput tapers — exactly the "
                        "behaviour the choke must contain.",
                        styles["note"],
                    ),
                ]
            )
        )

    # ----- 8. Voltage drop & THD -----
    flowables.append(
        Paragraph(
            "8. Voltage drop &amp; THD prediction",
            styles["h2"],
        )
    )
    flowables.append(
        _eqn_block(
            r"V_{drop}/V_{in} = \frac{\omega L \cdot I_{dc}}"
            r"{V_{in}} \cdot 100\%",
            with_values=(
                f"(2π × {spec.f_line_Hz:.0f} × {L_actual_mH:.3f} mH × I_dc) / {Vin:.0f} V × 100%"
            ),
            result=f"{V_drop_pct:.2f} %",
            note="I_dc = P_out / (η · 0.9·V_pk) ≈ rectifier-output average current.",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        _eqn_block(
            r"THD_{est} \approx \frac{75}{\sqrt{\%Z}}",
            with_values=f"75 / √{V_drop_pct:.2f}",
            result=f"{THD_pct:.1f} %",
            note="Same fit used for the line reactor; same physics, single-phase application.",
            fonts=fonts,
            styles=styles,
        )
    )

    # ----- 9. Wire sizing -----
    flowables.append(
        Paragraph(
            "9. Wire sizing &amp; window-fill check",
            styles["h2"],
        )
    )
    flowables.append(
        Paragraph(
            "Passive chokes carry only the rectified line-current "
            "envelope, no switching ripple, so sizing is purely "
            "against a current-density target — no skin penalty.",
            styles["body"],
        )
    )
    pp_pc = _parallel_strands_recommendation(
        wire,
        I_rms,
        spec.f_line_Hz,
        result.T_winding_C,
        J_target=4.0,
    )
    flowables.append(
        _eqn_block(
            r"A_{cu,req} = \frac{I_{rms}}{J_{target}}",
            with_values=f"{I_rms:.2f} A / 4 A/mm²",
            result=f"{pp_pc['A_cu_required_mm2']:.3f} mm²",
            fonts=fonts,
            styles=styles,
        )
    )
    flowables.append(
        Paragraph(
            f"Selected wire: <b>{wire.id}</b>, A<sub>cu</sub> = "
            f"<b>{pp_pc['A_cu_selected_mm2']:.3f} mm²</b>; actual J "
            f"= <b>{pp_pc['J_actual_A_per_mm2']:.2f} A/mm²</b>. "
            f"<b>Verdict:</b> {pp_pc['advice']}",
            styles["body"],
        )
    )
    fig_ku_pc = _fig_ku_vs_N(spec, core, wire, result)
    if fig_ku_pc is not None:
        flowables.append(
            KeepTogether(
                [
                    Paragraph("Window-fill curve", styles["h3"]),
                    _mpl_flowable(fig_ku_pc, _USABLE_WIDTH_MM),
                ]
            )
        )

    # ----- 10-12. Common winding/losses/thermal -----
    flowables.extend(
        _section_winding_losses_thermal(
            spec,
            core,
            wire,
            result,
            section_num=10,
            fonts=fonts,
            styles=styles,
        )
    )
    return flowables


def _page_decoration_factory(project_id: str, fonts: dict[str, str]):
    """Footer painted on every page. Carries the project id so a
    detached page in a binder is still traceable."""

    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(fonts["regular"], 8)
        canvas.setFillColor(_Palette.muted)
        canvas.drawString(
            18 * mm,
            8 * mm,
            f"MagnaDesign · Project {project_id} · {datetime.now().strftime('%Y-%m-%d')}",
        )
        canvas.drawRightString(
            doc.pagesize[0] - 18 * mm,
            8 * mm,
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
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="main",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="default", frames=[frame], onPage=_page_decoration_factory(pid, fonts)),
        ]
    )

    story: list = []
    story.append(
        _project_header(
            title,
            pid,
            designer,
            revision,
            now,
            fonts=fonts,
            styles=styles,
        )
    )
    story.append(Spacer(1, 4 * mm))

    # 1. Project specification
    story.extend(_section_project_inputs(spec, fonts, styles))

    # 2. Selected components
    story.extend(
        _section_components(
            core,
            material,
            wire,
            result,
            fonts,
            styles,
        )
    )

    # 3+. Per-topology theoretical body (filled in PROJ-3 / PROJ-4).
    story.extend(
        _section_topology_body(
            spec,
            core,
            material,
            wire,
            result,
            fonts,
            styles,
        )
    )

    # Verification plots — section follows the per-topology body.
    story.extend(
        _section_verification(
            spec,
            core,
            material,
            wire,
            result,
            fonts,
            styles,
        )
    )

    # Final consolidated summary table.
    story.extend(_section_result_summary(spec, result, fonts, styles))

    # Warnings, if the design has any.
    if result.warnings:
        story.append(Paragraph("Warnings raised by the engine", styles["h2"]))
        for w in result.warnings:
            story.append(Paragraph(f"• {w}", styles["note"]))

    doc.build(story)
    return output_path.resolve()
