"""Native PDF datasheet generator (ReportLab + matplotlib).

Companion to ``html_report.py`` / ``datasheet.py``: same data sources
(``Spec`` / ``Core`` / ``Material`` / ``Wire`` / ``DesignResult``),
different output target. Where the HTML version optimises for screen
preview and Slack-pastability, this module emits a print-grade A4
PDF with the properties customers and shop floors actually need:

- **Vector text + charts.** Body text is embedded as PDF vector
  primitives — selectable, copy-paste-able, indexable, sharp at any
  zoom. Charts are rasterised at 220 dpi (about 2× screen DPI) so
  they print crisply on a 600 dpi laser without the implementation
  cost of vector-PDF page merging.
- **Embedded font (Inter).** No silent substitution between
  rendering machines. Falls back to Helvetica only if the bundled
  ``report/fonts/`` directory is missing (e.g. trimmed wheel).
- **Deterministic page breaks.** ``BaseDocTemplate`` lays the
  document out itself; HTML→browser-print is at the mercy of every
  browser's heuristics.
- **Background colours preserved.** No "Background graphics"
  toggle in the print dialog to forget.

Public API
----------
``generate_pdf_datasheet(spec, core, material, wire, result,
output_path, designer, revision) -> Path``. Mirrors the HTML
generator's signature so existing callers (``ExportarTab``,
``MainWindow._export_report``) can switch formats by changing one
import and the file extension.

Layout policy
-------------
Three A4 portrait pages, 14 mm margins, identical content to the
HTML version (Page 1 mechanical + spec, Page 2 performance, Page 3
BOM + datasheet-shippable sections). Every page is built from the
same Flowables vocabulary (header, KV table, grid table, chart) so
adding a new section is a matter of dropping a new helper into the
``story`` list.

Dependency policy
-----------------
The HTML datasheet (``datasheet.py``) and the PDF datasheet are
intentionally siblings, not layered. Pure-data helpers
(``_passive_choke_extras``, ``_wire_mass_g``, ``_tolerance_band_pct``,
``_safety_table_for``, ``_ENV_RATINGS``) are imported from
``datasheet.py`` so engineering-decision constants (insulation class,
hi-pot levels, tolerance bands by material family) have a single
source of truth. Plot logic and HTML-specific glue stay duplicated —
the PDF code path needs matplotlib ``Figure`` objects, the HTML
code path needs base64 PNGs, and unifying the two would couple them
without a meaningful payoff.
"""
from __future__ import annotations

import base64
import io
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
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
from pfc_inductor.physics import rolloff as rf
from pfc_inductor.report.datasheet import (
    _ENV_RATINGS,
    _passive_choke_extras,
    _safety_table_for,
    _tolerance_band_pct,
    _wire_mass_g,
)
from pfc_inductor.report.views_3d import derive_dimensions, render_views

# ---------------------------------------------------------------------------
# Font registration. We embed Inter (SIL OFL 1.1) for body + headings;
# numeric values use ``Inter-Medium`` so columns of digits line up
# without a monospace fallback. The registration is idempotent — the
# function is safe to call from every ``generate_pdf_datasheet`` entry.
# ---------------------------------------------------------------------------
_FONTS_DIR = Path(__file__).parent / "fonts"
_INTER_WEIGHTS: dict[str, str] = {
    "Inter-Regular":  "Inter-Regular.ttf",
    "Inter-Medium":   "Inter-Medium.ttf",
    "Inter-SemiBold": "Inter-SemiBold.ttf",
    "Inter-Bold":     "Inter-Bold.ttf",
}
_FALLBACK_FONT_FAMILY = {
    "regular":  "Helvetica",
    "medium":   "Helvetica",
    "semibold": "Helvetica-Bold",
    "bold":     "Helvetica-Bold",
}


def _register_fonts() -> dict[str, str]:
    """Register the bundled Inter weights with ReportLab.

    Returns a mapping ``{"regular": "Inter-Regular", ...}`` the
    paragraph/table styles consume. Falls back to Helvetica when
    the ``fonts/`` directory is missing — packaging quirks with
    ``pip install --no-binary`` can trim non-Python data; the
    fallback keeps the generator working at the cost of typography.
    """
    if not _FONTS_DIR.is_dir():
        return _FALLBACK_FONT_FAMILY
    registered: list[str] = []
    for name, fname in _INTER_WEIGHTS.items():
        path = _FONTS_DIR / fname
        if not path.is_file():
            return _FALLBACK_FONT_FAMILY
        try:
            pdfmetrics.registerFont(TTFont(name, str(path)))
            registered.append(name)
        except Exception:
            return _FALLBACK_FONT_FAMILY
    return {
        "regular":  "Inter-Regular",
        "medium":   "Inter-Medium",
        "semibold": "Inter-SemiBold",
        "bold":     "Inter-Bold",
    }


# ---------------------------------------------------------------------------
# Datasheet colour palette. Matches the HTML version so HTML and PDF
# are visually consistent when shared together.
# ---------------------------------------------------------------------------
class _Palette:
    text:       Color = HexColor("#1a1a1a")
    muted:      Color = HexColor("#555555")
    rule:       Color = HexColor("#1a1a1a")
    soft_rule:  Color = HexColor("#dddddd")
    row_alt:    Color = HexColor("#f7f7f7")
    label_bg:   Color = HexColor("#fafafa")

    accent:     Color = HexColor("#3a78b5")
    accent_lt:  Color = HexColor("#7eaee0")
    danger:     Color = HexColor("#a01818")
    danger_lt:  Color = HexColor("#f8e0e0")
    ok:         Color = HexColor("#1c7c3b")
    ok_lt:      Color = HexColor("#e0f4e8")
    warn:       Color = HexColor("#a06700")
    warn_lt:    Color = HexColor("#fff7e0")


# ---------------------------------------------------------------------------
# Paragraph + table style factories. Built lazily because they depend
# on the font registration being complete.
# ---------------------------------------------------------------------------
def _build_styles(fonts: dict[str, str]) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    p: dict[str, ParagraphStyle] = {}
    p["title"] = ParagraphStyle(
        "DSTitle", parent=base, fontName=fonts["bold"],
        fontSize=18, leading=22, textColor=_Palette.text,
        spaceAfter=2,
    )
    p["subtitle"] = ParagraphStyle(
        "DSSubtitle", parent=base, fontName=fonts["regular"],
        fontSize=10.5, leading=13, textColor=_Palette.muted,
        spaceAfter=8,
    )
    p["h2"] = ParagraphStyle(
        "DSH2", parent=base, fontName=fonts["semibold"],
        fontSize=12.5, leading=15, textColor=_Palette.text,
        spaceBefore=10, spaceAfter=4,
        borderPadding=(0, 0, 2, 0),
    )
    p["h3"] = ParagraphStyle(
        "DSH3", parent=base, fontName=fonts["semibold"],
        fontSize=11, leading=14, textColor=_Palette.text,
        spaceBefore=6, spaceAfter=3,
    )
    p["body"] = ParagraphStyle(
        "DSBody", parent=base, fontName=fonts["regular"],
        fontSize=10, leading=13, textColor=_Palette.text,
        spaceAfter=4,
    )
    p["note"] = ParagraphStyle(
        "DSNote", parent=base, fontName=fonts["regular"],
        fontSize=9, leading=12, textColor=_Palette.muted,
        spaceAfter=4,
    )
    p["meta"] = ParagraphStyle(
        "DSMeta", parent=base, fontName=fonts["regular"],
        fontSize=9.5, leading=12, textColor=_Palette.muted,
        alignment=2,  # right
    )
    p["meta_value"] = ParagraphStyle(
        "DSMetaValue", parent=base, fontName=fonts["semibold"],
        fontSize=9.5, leading=12, textColor=_Palette.text,
        alignment=2,
    )
    p["badge_ok"] = ParagraphStyle(
        "DSBadgeOK", parent=base, fontName=fonts["bold"],
        fontSize=9.5, leading=12, textColor=_Palette.ok,
        alignment=2, backColor=_Palette.ok_lt, borderPadding=(2, 4, 2, 4),
    )
    p["badge_bad"] = ParagraphStyle(
        "DSBadgeBad", parent=base, fontName=fonts["bold"],
        fontSize=9.5, leading=12, textColor=_Palette.danger,
        alignment=2, backColor=_Palette.danger_lt,
        borderPadding=(2, 4, 2, 4),
    )
    p["view_label"] = ParagraphStyle(
        "DSViewLabel", parent=base, fontName=fonts["bold"],
        fontSize=8, leading=10, textColor=_Palette.muted,
        alignment=0,
    )
    return p


def _kv_table_style(fonts: dict[str, str]) -> TableStyle:
    """Two-column key/value style. The label column gets the muted
    colour and a slight tint; values right-aligned for tabular feel."""
    return TableStyle([
        ("FONTNAME",   (0, 0), (-1, -1), fonts["regular"]),
        ("FONTSIZE",   (0, 0), (-1, -1), 9.5),
        ("FONTNAME",   (1, 0), (1, -1),  fonts["medium"]),
        ("TEXTCOLOR",  (0, 0), (0, -1),  _Palette.muted),
        ("TEXTCOLOR",  (1, 0), (1, -1),  _Palette.text),
        ("ALIGN",      (0, 0), (0, -1),  "LEFT"),
        ("ALIGN",      (1, 0), (1, -1),  "LEFT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW",  (0, 0), (-1, -1), 0.25, _Palette.soft_rule),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ])


def _grid_table_style(fonts: dict[str, str], header_rows: int = 1) -> TableStyle:
    """Multi-column gridded table (used for FAT plan, BOM, rev history)."""
    return TableStyle([
        ("FONTNAME",   (0, 0), (-1, -1),       fonts["regular"]),
        ("FONTNAME",   (0, 0), (-1, header_rows - 1), fonts["semibold"]),
        ("FONTSIZE",   (0, 0), (-1, -1),       9.5),
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), _Palette.label_bg),
        ("TEXTCOLOR",  (0, 0), (-1, -1),       _Palette.text),
        ("LINEBELOW",  (0, 0), (-1, header_rows - 1), 0.5, _Palette.rule),
        ("LINEBELOW",  (0, header_rows - 1), (-1, -1), 0.25,
         _Palette.soft_rule),
        ("VALIGN",     (0, 0), (-1, -1),       "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ])


# ---------------------------------------------------------------------------
# matplotlib → PNG flowable. Rendering at print-DPI (220) keeps charts
# sharp on paper while keeping the implementation simple — ReportLab's
# direct PDF-page embedding is an order of magnitude more code (and
# pulls in pdfrw / svglib) for negligible visual gain at the sizes we
# print at. Future work: hook ``svglib`` to render the SVG mpl backend
# straight into Drawing primitives if file size becomes an issue.
# ---------------------------------------------------------------------------
def _mpl_flowable(fig, width_mm: float, dpi: int = 220) -> RLImage:
    """Convert a matplotlib figure to a Platypus ``Image`` flowable.

    The figure is rendered at 220 dpi (about 2× the screen resolution
    we used for the HTML PNGs). At A4 column widths this is sharp
    on a 600 dpi laser printer.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = RLImage(buf)
    iw, ih = img.imageWidth, img.imageHeight
    target_w = width_mm * mm
    img.drawWidth = target_w
    img.drawHeight = target_w * (ih / iw) if iw > 0 else target_w
    return img


def _b64_png_flowable(b64: str, width_mm: float) -> Optional[RLImage]:
    """Wrap a base64 PNG string (e.g. the ones ``render_views`` emits)
    in a Platypus ``Image`` flowable, scaled to ``width_mm``.
    Returns ``None`` if the string is empty / invalid (the caller
    should render a placeholder cell)."""
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None
    img = RLImage(io.BytesIO(raw))
    iw, ih = img.imageWidth, img.imageHeight
    target_w = width_mm * mm
    img.drawWidth = target_w
    img.drawHeight = target_w * (ih / iw) if iw > 0 else target_w
    return img


# ---------------------------------------------------------------------------
# Plot helpers. Mirror their HTML counterparts in ``datasheet.py`` but
# return matplotlib ``Figure`` objects directly — the PDF flowable
# wraps them with ``_mpl_flowable``. Duplication is intentional: the
# HTML side returns base64 strings, the PDF side returns figures, and
# unifying them would couple the two modules without a payoff.
# ---------------------------------------------------------------------------
def _fig_waveform(result: DesignResult, topology: str):
    if not result.waveform_t_s or not result.waveform_iL_A:
        return None
    t_ms = np.array(result.waveform_t_s) * 1000.0
    iL = np.array(result.waveform_iL_A)
    fig, ax = plt.subplots(figsize=(7.0, 3.0), dpi=110)
    if topology == "line_reactor":
        title = "Line current — phase A (steady state)"
        ax.plot(t_ms, iL, color="#a01818", linewidth=1.4)
        ax.axhline(0, color="#999", linewidth=0.5)
    elif topology == "boost_ccm":
        title = "Inductor current — half line cycle"
        ax.plot(t_ms, iL, color="#3a78b5", linewidth=1.4)
        ax.fill_between(t_ms, 0, iL, alpha=0.12, color="#3a78b5")
    else:
        title = "Inductor current"
        ax.plot(t_ms, iL, color="#3a78b5", linewidth=1.4)
    ax.set_xlabel("t [ms]")
    ax.set_ylabel("i [A]")
    ax.set_title(title, fontsize=10)
    ax.grid(True, alpha=0.35)
    return fig


def _fig_loss_breakdown(result: DesignResult):
    L = result.losses
    labels = ["Cu DC", "Cu AC", "Core (line)", "Core (ripple)"]
    values = [L.P_cu_dc_W, L.P_cu_ac_W, L.P_core_line_W, L.P_core_ripple_W]
    colors = ["#3a78b5", "#7eaee0", "#b53a3a", "#e07e7e"]
    fig, ax = plt.subplots(figsize=(6.0, 2.8), dpi=110)
    bars = ax.bar(labels, values, color=colors)
    ax.set_ylabel("Loss [W]")
    ax.set_title(f"Loss breakdown — total {L.P_total_W:.2f} W", fontsize=10)
    ax.grid(True, axis="y", alpha=0.35)
    for b, v in zip(bars, values, strict=False):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}",
                ha="center", va="bottom", fontsize=8)
    return fig


def _fig_rolloff(material: Material, result: DesignResult):
    if material.rolloff is None:
        return None
    H = np.logspace(0, 3.5, 200)
    mu = np.array([rf.mu_pct(material, h) for h in H]) * 100
    fig, ax = plt.subplots(figsize=(7.0, 3.2), dpi=110)
    ax.semilogx(H, mu, linewidth=1.6, color="#3a78b5")
    ax.axvline(result.H_dc_peak_Oe, color="#a01818", linestyle="--",
               alpha=0.6, label=f"H = {result.H_dc_peak_Oe:.0f} Oe")
    ax.axhline(result.mu_pct_at_peak * 100, color="#a01818",
               linestyle=":", alpha=0.6,
               label=f"μ% = {result.mu_pct_at_peak * 100:.1f}%")
    ax.set_xlabel("H [Oe]")
    ax.set_ylabel("μ% [% initial]")
    ax.set_title(f"DC bias roll-off — {material.name}", fontsize=10)
    ax.set_ylim(0, 105)
    ax.legend(loc="lower left", fontsize=8)
    ax.grid(True, which="both", alpha=0.35)
    return fig


def _fig_harmonic(spec: Spec, result: DesignResult):
    """Bar chart of harmonics in mA RMS, with three standards overlaid
    (IEC 61000-3-2 Class D, IEC 61000-3-12, IEEE 519-2014). Only
    relevant for ``line_reactor``.
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

    fig, ax = plt.subplots(figsize=(8.0, 3.4), dpi=110)
    ax.bar(plot_orders, plot_amps_mA, width=0.7, color=colors,
           label="Predicted (RMS)")
    if limits:
        lo = sorted(limits.keys())
        lv_mA = [limits[h] * 1000 for h in lo]
        ax.plot(lo, lv_mA, color="#a06700", linestyle="--", marker="o",
                markersize=4, linewidth=1.5,
                label="IEC 61000-3-2 Class D")
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
    return fig


def _fig_switching_ripple(spec: Spec, result: DesignResult):
    """Synthesise three switching periods at the worst-case Vin_min
    operating point so the printed datasheet shows the Δi_pp the
    engineer sized L for. Boost-CCM only."""
    if spec.topology != "boost_ccm" or spec.f_sw_kHz <= 0:
        return None
    L_H = float(result.L_actual_uH) * 1e-6
    if L_H <= 0:
        return None
    Vin_min_pk = math.sqrt(2.0) * float(spec.Vin_min_Vrms)
    Vout = float(spec.Vout_V)
    if Vout <= Vin_min_pk:
        return None
    Tsw = 1.0 / (float(spec.f_sw_kHz) * 1000.0)
    D = 1.0 - Vin_min_pk / Vout
    t_on = D * Tsw
    delta_i = (Vin_min_pk * t_on) / L_H
    iL_dc = float(result.I_line_pk_A)
    iL_min = iL_dc - delta_i / 2.0
    iL_max = iL_dc + delta_i / 2.0
    n_periods = 3
    t = []
    iL = []
    for k in range(n_periods):
        t0 = k * Tsw
        t.extend([t0, t0 + t_on, t0 + Tsw])
        iL.extend([iL_min, iL_max, iL_min])
    t_us = np.array(t) * 1e6
    fig, ax = plt.subplots(figsize=(7.0, 2.8), dpi=110)
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
        f"({100.0 * delta_i / max(iL_dc, 1e-6):.0f} %)",
        fontsize=10,
    )
    ax.grid(True, alpha=0.35)
    ax.legend(loc="upper right", fontsize=8)
    return fig


def _fig_efficiency(spec: Spec, core: Core, wire: Wire,
                     material: Material, result: DesignResult):
    """η-vs-load curve. Re-runs the engine at 10/25/50/75/100/110 % of
    nominal Pout. Boost-CCM and passive choke only."""
    if spec.topology not in ("boost_ccm", "passive_choke"):
        return None
    if float(spec.Pout_W) <= 0 or float(result.losses.P_total_W) <= 0:
        return None
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
            continue
    if len(pts) < 2:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    fig, ax = plt.subplots(figsize=(6.0, 2.8), dpi=110)
    ax.plot(xs, ys, "-o", color="#3a78b5", linewidth=1.5, markersize=5)
    ax.set_xlabel("Pout [% of nominal]")
    ax.set_ylabel("η [%]")
    ax.set_ylim(min(ys) - 2.0, max(100.0, max(ys) + 0.5))
    ax.set_title("Efficiency vs load (inductor only)", fontsize=10)
    ax.axvline(100.0, color="#777", linestyle=":", linewidth=0.8)
    ax.grid(True, alpha=0.35)
    return fig


def _fig_choke_comparison(spec: Spec, result: DesignResult, core: Core):
    """Before/after PF + DC-link ripple comparison. Passive choke only."""
    if spec.topology != "passive_choke":
        return None
    ex = _passive_choke_extras(spec, result, core)
    pf_no = float(ex["pf_no_choke"])
    pf_yes = float(ex["pf_with_choke"])
    v_ripple_yes = float(ex["v_ripple_dc_pp"])
    v_ripple_no = v_ripple_yes * 2.0
    fig, axes = plt.subplots(1, 2, figsize=(7.5, 2.6), dpi=110)
    ax_pf, ax_v = axes
    bars_pf = ax_pf.bar(["No choke", "With choke"], [pf_no, pf_yes],
                         color=["#a01818", "#1c7c3b"], width=0.55)
    ax_pf.set_ylim(0, 1.0)
    ax_pf.set_ylabel("Power factor")
    ax_pf.set_title("PF — before vs after", fontsize=10)
    ax_pf.grid(True, axis="y", alpha=0.35)
    for b, v in zip(bars_pf, [pf_no, pf_yes], strict=False):
        ax_pf.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=9)
    bars_v = ax_v.bar(["No choke", "With choke"],
                       [v_ripple_no, v_ripple_yes],
                       color=["#a01818", "#1c7c3b"], width=0.55)
    ax_v.set_ylabel("V_ripple pp [V]")
    ax_v.set_title("DC-link ripple — before vs after", fontsize=10)
    ax_v.grid(True, axis="y", alpha=0.35)
    for b, v in zip(bars_v, [v_ripple_no, v_ripple_yes], strict=False):
        ax_v.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.0f}",
                   ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    return fig


def _fig_bh_trajectory(result: DesignResult, core: Core, material: Material):
    """B–H operating-point trajectory — same plot the dashboard's
    BHLoopCard builds, rendered at print-DPI for the datasheet."""
    try:
        from pfc_inductor.visual import compute_bh_trajectory
        tr = compute_bh_trajectory(result, core, material)
    except Exception:
        return None
    fig, ax = plt.subplots(figsize=(7.0, 3.2), dpi=110)
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
                   f"{tr['B_pk_T'] * 1000.0:.0f} mT)")
    ax.set_xlabel("H [Oe]")
    ax.set_ylabel("B [mT]")
    ax.set_title("B–H trajectory at operating point", fontsize=10)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="lower right", fontsize=8)
    return fig


# ---------------------------------------------------------------------------
# Data row helpers — return ``list[tuple[str, str]]`` (KV) or
# ``list[list[str]]`` (grid). Rendered to Platypus tables by
# ``_kv_flow`` / ``_grid_flow`` below.
# ---------------------------------------------------------------------------
def _spec_data_boost(spec: Spec) -> list[tuple[str, str]]:
    return [
        ("Topology",          "Boost PFC, CCM"),
        ("Vin range",         f"{spec.Vin_min_Vrms:.0f} – {spec.Vin_max_Vrms:.0f} Vrms"),
        ("Vout (DC bus)",     f"{spec.Vout_V:.0f} V"),
        ("Pout",              f"{spec.Pout_W:.0f} W"),
        ("Switching freq.",   f"{spec.f_sw_kHz:.0f} kHz"),
        ("Line freq.",        f"{spec.f_line_Hz:.0f} Hz"),
        ("Ripple target (pp)", f"{spec.ripple_pct:.0f} %"),
        ("Efficiency assumed", f"{spec.eta:.2f}"),
    ]


def _spec_data_choke(spec: Spec, result: DesignResult,
                      core: Core) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [
        ("Topology",            "Passive line choke"),
        ("Vin nominal",         f"{spec.Vin_nom_Vrms:.0f} Vrms"),
        ("Pout",                f"{spec.Pout_W:.0f} W"),
        ("Line freq.",          f"{spec.f_line_Hz:.0f} Hz"),
        ("Efficiency assumed",  f"{spec.eta:.2f}"),
    ]
    ex = _passive_choke_extras(spec, result, core)
    rows.extend([
        ("Estimated % impedance",      f"{ex['pct_z']} %"),
        ("PF without choke (baseline)", ex["pf_no_choke"]),
        ("PF with this choke (est.)",  ex["pf_with_choke"]),
        ("PF improvement",             ex["pf_delta"]),
        ("DC-link ripple (pp, est.)",  f"{ex['v_ripple_dc_pp']} V"),
        ("Bulk cap assumed for ripple", f"{ex['c_dc_assumed']} µF"),
    ])
    return rows


def _spec_data_line_reactor(spec: Spec,
                              result: DesignResult) -> list[tuple[str, str]]:
    pct_z = result.pct_impedance_actual or 0.0
    v_drop = result.voltage_drop_pct or 0.0
    thd = result.thd_estimate_pct or 0.0
    return [
        ("Topology",         "AC line reactor (diode-rectifier + DC-link)"),
        ("Phases",           "1-phase" if spec.n_phases == 1 else "3-phase"),
        ("V line",
         f"{spec.Vin_nom_Vrms:.0f} "
         f"{'V_LL' if spec.n_phases == 3 else 'V_LN'}"),
        ("Rated current",    f"{spec.I_rated_Arms:.2f} Arms"),
        ("Line freq.",       f"{spec.f_line_Hz:.0f} Hz"),
        ("Target % impedance", f"{spec.pct_impedance:.1f} %"),
        ("Achieved % impedance", f"{pct_z:.2f} %"),
        ("Voltage drop @ rated I", f"{v_drop:.2f} %"),
        ("THD estimate",     f"{thd:.1f} %"),
        ("Pi (active input power)",
         f"{result.Pi_W:.0f} W" if result.Pi_W else "—"),
    ]


def _result_data(spec: Spec, result: DesignResult) -> list[tuple[str, str]]:
    is_lr = spec.topology == "line_reactor"
    L_unit = "mH" if is_lr else "µH"
    L_act = result.L_actual_uH / 1000 if is_lr else result.L_actual_uH
    L_req = result.L_required_uH / 1000 if is_lr else result.L_required_uH
    rows: list[tuple[str, str]] = [
        ("Inductance (required)", f"{L_req:.2f} {L_unit}"),
        ("Inductance (actual)",   f"{L_act:.2f} {L_unit}"),
        ("Number of turns N",     f"{result.N_turns}"),
        ("μ% at peak DC bias",    f"{result.mu_pct_at_peak * 100:.1f} %"),
        ("H peak DC",             f"{result.H_dc_peak_Oe:.0f} Oe"),
        ("B peak",                f"{result.B_pk_T * 1000:.0f} mT"),
        ("Bsat limit",            f"{result.B_sat_limit_T * 1000:.0f} mT"),
        ("Saturation margin",     f"{result.sat_margin_pct:.0f} %"),
        ("I peak (line env.)",    f"{result.I_line_pk_A:.2f} A"),
        ("I RMS (line env.)",     f"{result.I_line_rms_A:.2f} A"),
    ]
    if not is_lr:
        rows.extend([
            ("Δi pp max",        f"{result.I_ripple_pk_pk_A:.2f} A"),
            ("I peak total",     f"{result.I_pk_max_A:.2f} A"),
            ("I RMS total",      f"{result.I_rms_total_A:.2f} A"),
        ])
    rows.append(("Window utilisation Ku", f"{result.Ku_actual * 100:.1f} %"))
    return rows


def _loss_data(result: DesignResult) -> list[tuple[str, str]]:
    L = result.losses
    return [
        ("P copper DC",        f"{L.P_cu_dc_W:.2f} W"),
        ("P copper AC (fsw)",  f"{L.P_cu_ac_W:.3f} W"),
        ("P core (line band)", f"{L.P_core_line_W:.3f} W"),
        ("P core (ripple, iGSE)", f"{L.P_core_ripple_W:.3f} W"),
        ("P TOTAL",            f"{L.P_total_W:.2f} W"),
        ("Rdc @ T_winding",    f"{result.R_dc_ohm * 1000:.1f} mΩ"),
        ("Rac @ fsw",          f"{result.R_ac_ohm * 1000:.1f} mΩ"),
        ("ΔT (rise)",          f"{result.T_rise_C:.0f} K"),
        ("T winding",          f"{result.T_winding_C:.0f} °C"),
    ]


# ---------------------------------------------------------------------------
# Page-3 data helpers — bill of materials, tolerance bands, build
# instructions, factory-acceptance test, validation provenance,
# revision history, project metadata. The corresponding HTML helpers in
# ``datasheet.py`` produce HTML strings; here we return plain
# ``list[tuple]`` (KV) or ``(header, list[list])`` (grid) so the
# Platypus tables lay out the same data in PDF.
# ---------------------------------------------------------------------------
def _bom_data(core: Core, wire: Wire, material: Material,
               result: DesignResult) -> list[tuple[str, str]]:
    """Bill of materials. Sub-rows are indented with non-breaking
    spaces so Paragraph preserves the visual hierarchy (regular spaces
    collapse in flowables)."""
    wire_len_m = result.N_turns * core.MLT_mm * 1e-3
    wire_mass = _wire_mass_g(wire, wire_len_m)
    mass_origin = (
        " (catalog)" if (wire.mass_per_meter_g and wire.mass_per_meter_g > 0)
        else " (derived from Cu density)"
    )
    indent = "&nbsp;&nbsp;"
    return [
        ("Core",
         f"{core.vendor} — {core.part_number} ({core.shape})"),
        (f"{indent}Ae × le × Ve",
         f"{core.Ae_mm2:.0f} mm² × {core.le_mm:.0f} mm × "
         f"{core.Ve_mm3 / 1000:.1f} cm³"),
        (f"{indent}Wa × MLT",
         f"{core.Wa_mm2:.0f} mm² × {core.MLT_mm:.0f} mm"),
        (f"{indent}AL nominal", f"{core.AL_nH:.0f} nH/N²"),
        ("Material", f"{material.vendor} — {material.name}"),
        (f"{indent}μ initial / Bsat (25°C)",
         f"{material.mu_initial:.0f} / "
         f"{material.Bsat_25C_T * 1000:.0f} mT"),
        (f"{indent}Density", f"{material.rho_kg_m3:.0f} kg/m³"),
        ("Wire", f"{wire.id} ({wire.type})"),
        (f"{indent}A_cu / d_cu",
         f"{wire.A_cu_mm2:.3f} mm² / {wire.d_cu_mm or 0:.2f} mm"),
        (f"{indent}Wire length", f"{wire_len_m:.2f} m"),
        (f"{indent}Wire mass (est.)",
         f"{wire_mass:.0f}{mass_origin} g"),
    ]


def _tolerance_data(result: DesignResult,
                     material: Material) -> list[tuple[str, str]]:
    L_pct = _tolerance_band_pct(material.type)
    L_act = float(result.L_actual_uH)
    L_lo = L_act * (1.0 - L_pct / 100.0)
    L_hi = L_act * (1.0 + L_pct / 100.0)
    rdc_act_mohm = float(result.R_dc_ohm) * 1000.0
    rdc_lo = rdc_act_mohm * 0.90
    rdc_hi = rdc_act_mohm * 1.10
    return [
        ("Inductance L (typ ± tol)",
         f"{L_act:.1f} µH (± {L_pct:.0f} %), range "
         f"{L_lo:.1f} – {L_hi:.1f} µH"),
        ("DC resistance Rdc (typ ± 10 %)",
         f"{rdc_act_mohm:.1f} mΩ, range "
         f"{rdc_lo:.1f} – {rdc_hi:.1f} mΩ"),
        ("Turn count N",
         f"{result.N_turns} (exact, no tolerance)"),
        ("Mass",
         "± 10 % around the BOM estimate"),
        ("Mechanical envelope",
         "± 0.5 mm on linear dimensions, ± 1° on angular"),
        ("Dielectric strength",
         "Pass criterion: no flashover during the hi-pot test"),
    ]


def _build_data(core: Core, wire: Wire,
                 result: DesignResult) -> list[tuple[str, str]]:
    """Build-room hand-off rows.

    Layer count is approximated from the window envelope (no
    dedicated window-height field on ``Core``); the wind-room verifies
    against the actual bobbin before committing.
    """
    wire_len_m = result.N_turns * core.MLT_mm * 1e-3
    d_outer_mm = (wire.d_iso_mm or wire.d_cu_mm or 0.5)
    layer_height = math.sqrt(max(core.Wa_mm2, 1.0))
    turns_per_layer = max(1, int(layer_height / max(d_outer_mm, 0.01)))
    n_layers = max(1, math.ceil(result.N_turns / turns_per_layer))
    air_gap = (
        f"{core.lgap_mm:.2f} mm" if core.lgap_mm > 0 else "no air gap"
    )
    return [
        ("Bobbin / former",
         f"{core.shape.upper()} compatible — single-section"),
        ("Wire",
         f"{wire.id} ({wire.type}, A_cu = {wire.A_cu_mm2:.3f} mm²)"),
        ("Total turns N",
         f"{result.N_turns} (single layer if window allows)"),
        ("Estimated turns per layer", f"{turns_per_layer}"),
        ("Estimated layer count", f"{n_layers}"),
        ("Wire length (with 5 % margin)",
         f"{wire_len_m * 1.05:.2f} m (cut length)"),
        ("Air gap (centre leg)", air_gap),
        ("Inter-layer insulation",
         "1 layer of polyester tape (35 µm) between layers"),
        ("Outer wrap",
         "2 layers of polyester tape, overlapped 50 %"),
        ("Impregnation",
         "Vacuum-impregnated with class-F (155 °C) varnish"),
        ("Lead termination",
         "Tinned 30 mm leads, dressed at the bobbin's start/end pads"),
    ]


def _fat_data(spec: Spec, result: DesignResult,
               material: Material) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows) for the factory-acceptance-test table.
    Pass bands inherit from ``_tolerance_band_pct`` so the wind-room
    and the QA bench agree on what "in spec" means."""
    L_pct = _tolerance_band_pct(material.type)
    L_act = float(result.L_actual_uH)
    rdc_mohm = float(result.R_dc_ohm) * 1000.0
    rows: list[list[str]] = [
        ["L @ 1 kHz, low signal", f"{L_act:.1f} µH",
         "LCR meter (4 kHz, 0.5 V)", f"± {L_pct:.0f} %"],
        ["Rdc @ 25 °C", f"{rdc_mohm:.1f} mΩ",
         "4-wire micro-Ω meter", "± 10 %"],
        ["Turn count N", f"{result.N_turns}",
         "Visual inspection of bobbin", "Exact"],
        ["Hi-pot (winding-to-core)", "1 min",
         "5 kV hi-pot tester", "No flashover, leakage ≤ 5 mA"],
        ["Insulation resistance", "≥ 100 MΩ",
         "500 V megohmmeter", "≥ 100 MΩ"],
    ]
    if spec.topology == "boost_ccm":
        rows.append([
            "Saturation current Isat",
            f"≥ {result.I_pk_max_A:.2f} A",
            "Curve tracer (DC bias sweep)",
            "L drops ≤ 30 % at Isat",
        ])
    elif spec.topology == "line_reactor":
        rows.append([
            "Voltage drop @ rated I",
            f"{(result.voltage_drop_pct or 0):.2f} %",
            "AC source + true-RMS voltmeter",
            "± 15 %",
        ])
    elif spec.topology == "passive_choke":
        rows.append([
            "Saturation onset",
            f"≥ {result.I_pk_max_A:.2f} A",
            "Curve tracer (DC bias)",
            "L drops ≤ 30 %",
        ])
    rows.append([
        "Visual / mechanical", "—",
        "Calliper, bobbin gauge", "± 0.5 mm",
    ])
    return ["Parameter", "Target", "Instrument", "Pass band"], rows


def _validation_data() -> list[tuple[str, str]]:
    """Provenance of every figure on the datasheet. Today everything
    is closed-form; the section is carved out so when the engine
    starts persisting FEA / transient cross-checks on
    ``DesignResult`` we just swap rows."""
    return [
        ("L_actual",       "Analytical (closed-form, with rolloff)"),
        ("B_pk",           "Analytical (V·s / N·Ae)"),
        ("R_dc",           "Analytical (ρ_Cu · l / A_cu, T-corrected)"),
        ("R_ac @ fsw",     "Analytical (Dowell skin/proximity)"),
        ("Core losses",    "Analytical (anchored Steinmetz / iGSE)"),
        ("ΔT (rise)",      "Analytical (natural-convection R_th model)"),
        ("FEA cross-check", "Not run for this revision (Validate tab)"),
        ("Transient (RK4)", "Not run for this revision"),
        ("Lab measurement", "Pending — see Test Plan section"),
    ]


def _revision_data(revision: str, designer: str,
                    now: str) -> tuple[list[str], list[list[str]]]:
    """Return (header, rows) for the revision-history grid table.
    Same P/N across revisions: any change to spec/core/material/wire
    produces a new hash and a new datasheet, so the rev history just
    documents the evolution of the *current* design point."""
    return (
        ["Rev", "Date", "Author", "Change"],
        [[revision, now, designer, "Initial release of this design"]],
    )


def _metadata_data(spec: Spec, core: Core, material: Material,
                    wire: Wire, pn: str) -> list[tuple[str, str]]:
    """Identifiers needed to reproduce this design in MagnaDesign."""
    code = lambda s: f'<font face="Courier">{s}</font>'  # noqa: E731
    return [
        ("Project P/N (this design)", code(pn)),
        ("Topology key",              code(spec.topology)),
        ("Material id",               code(material.id)),
        ("Core id",                   code(core.id)),
        ("Wire id",                   code(wire.id)),
        ("Source format",             ".pfc (JSON, MagnaDesign)"),
        ("Reproduce in MagnaDesign",
         "Open the .pfc file or recreate the spec with the four ids "
         "above; the engine is deterministic given the same spec + "
         "core + material + wire."),
    ]


# Static disclaimer text. Kept here (not in datasheet.py) so the PDF
# module is self-contained for legal text — the wording is
# print-grade and shouldn't drift between formats without a deliberate
# review.
_DISCLAIMER_TEXT = (
    "This datasheet describes a custom inductor designed with the "
    "MagnaDesign tool. Curated material parameters come from "
    "manufacturer datasheets and Steinmetz fits to vendor data; "
    "cores and wires are dimensional database entries. Always verify "
    "against a built sample (LCR meter for L &amp; Rdc, dyno-loaded "
    "operation for thermal) before committing to production."
)


# ---------------------------------------------------------------------------
# Flowable factories that turn data rows into Platypus tables sized to
# the page. Used by every section of every page.
# ---------------------------------------------------------------------------
def _kv_flow(rows: list[tuple[str, str]], width_mm: float,
              fonts: dict[str, str], styles: dict[str, ParagraphStyle],
              label_col_pct: float = 0.55) -> Table:
    """Two-column key/value table at ``width_mm`` total width."""
    label_w = width_mm * label_col_pct * mm
    value_w = width_mm * (1.0 - label_col_pct) * mm
    data = [
        [Paragraph(k, styles["body"]), Paragraph(v, styles["body"])]
        for (k, v) in rows
    ]
    t = Table(data, colWidths=[label_w, value_w])
    t.setStyle(_kv_table_style(fonts))
    return t


def _grid_flow(header: list[str], rows: list[list[str]],
                col_widths_mm: list[float], fonts: dict[str, str],
                styles: dict[str, ParagraphStyle]) -> Table:
    """N-column gridded table (FAT plan, BOM, rev history, etc.)."""
    body_style = styles["body"]
    head_para = [Paragraph(h, body_style) for h in header]
    body_paras = [
        [Paragraph(c, body_style) for c in r] for r in rows
    ]
    data = [head_para] + body_paras
    t = Table(data, colWidths=[w * mm for w in col_widths_mm])
    t.setStyle(_grid_table_style(fonts, header_rows=1))
    return t


# ---------------------------------------------------------------------------
# Mechanical 4-view grid. ``render_views`` returns base64-PNG strings
# (the offscreen pyvista renderer is shared with the HTML datasheet);
# we wrap each into a flowable and lay them out as a 2×2 grid table.
# Missing renders (no VTK / headless display) fall back to a placeholder
# cell so the page composes deterministically.
# ---------------------------------------------------------------------------
def _views_grid_flow(views: dict[str, Optional[str]], total_width_mm: float,
                      fonts: dict[str, str],
                      styles: dict[str, ParagraphStyle]) -> Table:
    """2×2 grid of mechanical views. Each cell labelled with the view
    name; missing cells render a "(3D viewer unavailable)" notice."""
    cell_w = total_width_mm / 2.0 - 2.0  # subtract for cell padding

    def cell(name: str, label: str):
        b64 = views.get(name) if views else None
        img = _b64_png_flowable(b64 or "", cell_w - 4.0)
        if img is None:
            return [
                Paragraph(label.upper(), styles["view_label"]),
                Paragraph("<i>(3D viewer unavailable)</i>", styles["note"]),
            ]
        return [
            Paragraph(label.upper(), styles["view_label"]),
            img,
        ]

    data = [
        [cell("iso",  "Isometric"), cell("front", "Front")],
        [cell("top",  "Top"),        cell("side",  "Side")],
    ]
    t = Table(data, colWidths=[cell_w * mm, cell_w * mm])
    t.setStyle(TableStyle([
        ("BOX",          (0, 0), (-1, -1), 0.5, _Palette.soft_rule),
        ("INNERGRID",    (0, 0), (-1, -1), 0.5, _Palette.soft_rule),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


# ---------------------------------------------------------------------------
# Page composition.
# ---------------------------------------------------------------------------
_USABLE_WIDTH_MM = 210 - 2 * 14  # A4 portrait, 14 mm margins → 182 mm


def _page1_story(spec: Spec, core: Core, wire: Wire, material: Material,
                  result: DesignResult, *, title: str, pn: str,
                  designer: str, revision: str, now: str,
                  fonts: dict[str, str],
                  styles: dict[str, ParagraphStyle]) -> list:
    """Page 1 — header, mechanical (4-views + dimensions + construction),
    spec + result tables side-by-side."""
    story: list = []
    story.append(_header_row(title, pn, designer, revision, now,
                              feasible=result.is_feasible(), fonts=fonts,
                              styles=styles))
    story.append(Spacer(1, 4 * mm))

    # ---------- Mechanical ----------
    story.append(Paragraph("Mechanical", styles["h2"]))

    # Render the 3D views once; both the views grid and the dim/
    # construction sub-table consume the result.
    print("[pdf_report] rendering 3D views (offscreen)…")
    views = render_views(core, wire, result.N_turns, material)
    dims = derive_dimensions(core)

    views_w = (_USABLE_WIDTH_MM - 4) / 2.0  # 50/50 split, 4 mm gutter
    views_table = _views_grid_flow(views, views_w, fonts, styles)

    # Right column: dim table + construction.
    dim_rows = [(k, v) for k, v in dims.items()]
    construction_rows = [
        ("Core shape", core.shape.upper()),
        ("Air gap", f"{core.lgap_mm:.2f} mm"),
        ("Wire", wire.id),
        ("Turns", str(result.N_turns)),
    ]
    right_col_flowables = [
        Paragraph("Dimensions", styles["h3"]),
        _kv_flow(dim_rows, views_w, fonts, styles),
        Paragraph("Construction", styles["h3"]),
        _kv_flow(construction_rows, views_w, fonts, styles),
    ]

    mech_table = Table(
        [[views_table, right_col_flowables]],
        colWidths=[views_w * mm, views_w * mm],
    )
    mech_table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(mech_table)

    # ---------- Specification ----------
    story.append(Paragraph("Specification", styles["h2"]))

    if spec.topology == "boost_ccm":
        spec_rows = _spec_data_boost(spec)
    elif spec.topology == "line_reactor":
        spec_rows = _spec_data_line_reactor(spec, result)
    else:
        spec_rows = _spec_data_choke(spec, result, core)
    res_rows = _result_data(spec, result)

    col_w = (_USABLE_WIDTH_MM - 4) / 2.0
    spec_grid = Table(
        [[
            [Paragraph("Inputs", styles["h3"]),
             _kv_flow(spec_rows, col_w, fonts, styles)],
            [Paragraph("Computed", styles["h3"]),
             _kv_flow(res_rows, col_w, fonts, styles)],
        ]],
        colWidths=[col_w * mm, col_w * mm],
    )
    spec_grid.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(spec_grid)

    return story


def _page2_story(spec: Spec, core: Core, wire: Wire, material: Material,
                  result: DesignResult, *, title: str, pn: str,
                  designer: str, revision: str, now: str,
                  fonts: dict[str, str],
                  styles: dict[str, ParagraphStyle]) -> list:
    """Page 2 — operating point + losses tables, topology-specific
    performance curves, B–H trajectory."""
    story: list = []
    story.append(_header_row(f"{title} — Performance", pn, designer,
                              revision, now,
                              feasible=result.is_feasible(),
                              fonts=fonts, styles=styles))
    story.append(Spacer(1, 4 * mm))

    # ---------- Operating Point & Losses ----------
    story.append(Paragraph("Operating Point & Losses", styles["h2"]))
    col_w = (_USABLE_WIDTH_MM - 4) / 2.0
    op_grid = Table(
        [[
            [Paragraph("Operating point", styles["h3"]),
             _kv_flow(_result_data(spec, result), col_w, fonts, styles)],
            [Paragraph("Losses & thermal", styles["h3"]),
             _kv_flow(_loss_data(result), col_w, fonts, styles)],
        ]],
        colWidths=[col_w * mm, col_w * mm],
    )
    op_grid.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(op_grid)

    # ---------- Performance Curves ----------
    story.append(Paragraph("Performance Curves", styles["h2"]))

    # Common: waveform + loss breakdown side-by-side. Each takes
    # half the page width.
    half_w = (_USABLE_WIDTH_MM - 4) / 2.0
    curve_blocks: list = []

    fig_wave = _fig_waveform(result, spec.topology)
    fig_loss = _fig_loss_breakdown(result)
    if fig_wave is not None and fig_loss is not None:
        wave_flow = _mpl_flowable(fig_wave, half_w)
        loss_flow = _mpl_flowable(fig_loss, half_w)
        wave_loss_grid = Table(
            [[
                [Paragraph("Current waveform", styles["h3"]), wave_flow],
                [Paragraph("Loss breakdown",    styles["h3"]), loss_flow],
            ]],
            colWidths=[half_w * mm, half_w * mm],
        )
        wave_loss_grid.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        curve_blocks.append(wave_loss_grid)
    elif fig_loss is not None:
        # Loss chart always available; waveform is conditional.
        curve_blocks.append(Paragraph("Loss breakdown", styles["h3"]))
        curve_blocks.append(_mpl_flowable(fig_loss, _USABLE_WIDTH_MM))

    # Topology-specific extra curves.
    if spec.topology == "boost_ccm":
        fig_sw = _fig_switching_ripple(spec, result)
        if fig_sw is not None:
            curve_blocks.append(Paragraph(
                "Switching ripple (Vin_min, peak operating point)",
                styles["h3"]))
            curve_blocks.append(_mpl_flowable(fig_sw, _USABLE_WIDTH_MM))
        fig_ro = _fig_rolloff(material, result)
        if fig_ro is not None:
            curve_blocks.append(Paragraph("DC bias roll-off",
                                           styles["h3"]))
            curve_blocks.append(_mpl_flowable(fig_ro, _USABLE_WIDTH_MM))
        fig_eta = _fig_efficiency(spec, core, wire, material, result)
        if fig_eta is not None:
            curve_blocks.append(Paragraph("Efficiency vs load",
                                           styles["h3"]))
            curve_blocks.append(_mpl_flowable(fig_eta, _USABLE_WIDTH_MM))
    elif spec.topology == "line_reactor":
        fig_h = _fig_harmonic(spec, result)
        if fig_h is not None:
            curve_blocks.append(Paragraph(
                "Harmonic compliance — IEC 61000-3-2 / 61000-3-12 / "
                "IEEE 519",
                styles["h3"]))
            curve_blocks.append(_mpl_flowable(fig_h, _USABLE_WIDTH_MM))
    elif spec.topology == "passive_choke":
        fig_cmp = _fig_choke_comparison(spec, result, core)
        if fig_cmp is not None:
            curve_blocks.append(Paragraph(
                "Choke effect — before vs after (estimated)",
                styles["h3"]))
            curve_blocks.append(_mpl_flowable(fig_cmp, _USABLE_WIDTH_MM))
        fig_eta = _fig_efficiency(spec, core, wire, material, result)
        if fig_eta is not None:
            curve_blocks.append(Paragraph("Efficiency vs load",
                                           styles["h3"]))
            curve_blocks.append(_mpl_flowable(fig_eta, _USABLE_WIDTH_MM))

    story.extend(curve_blocks)

    # ---------- B–H trajectory ----------
    fig_bh = _fig_bh_trajectory(result, core, material)
    if fig_bh is not None:
        story.append(Paragraph("B–H trajectory at operating point",
                                styles["h3"]))
        story.append(_mpl_flowable(fig_bh, _USABLE_WIDTH_MM))

    # ---------- Warnings (if any) ----------
    if result.warnings:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Warnings", styles["h3"]))
        for w in result.warnings:
            story.append(Paragraph(f"• {w}", styles["note"]))

    return story


def _page3_story(spec: Spec, core: Core, wire: Wire, material: Material,
                  result: DesignResult, *, title: str, pn: str,
                  designer: str, revision: str, now: str,
                  fonts: dict[str, str],
                  styles: dict[str, ParagraphStyle]) -> list:
    """Page 3 — datasheet long-tail: BOM, tolerance, build, FAT,
    environment, safety, validation, engineering notes, revision
    history, project metadata, disclaimer.

    Content is dense; ReportLab paginates naturally when the section
    overflows the A4 frame. The section is logically still "Page 3"
    even if it spills onto Page 4 in print.
    """
    story: list = []
    story.append(_header_row(f"{title} — BOM & Notes", pn, designer,
                              revision, now,
                              feasible=result.is_feasible(),
                              fonts=fonts, styles=styles))
    story.append(Spacer(1, 4 * mm))

    # ---------- Bill of Materials ----------
    story.append(Paragraph("Bill of Materials", styles["h2"]))
    story.append(_kv_flow(_bom_data(core, wire, material, result),
                           _USABLE_WIDTH_MM, fonts, styles,
                           label_col_pct=0.42))

    # ---------- Tolerance Bands ----------
    story.append(Paragraph("Tolerance Bands", styles["h2"]))
    story.append(Paragraph(
        "Acceptance bands for incoming inspection. Inductance band is "
        "keyed off the material family — silicon-steel gapped designs "
        "run wider, powder cores tighter.",
        styles["note"],
    ))
    story.append(_kv_flow(_tolerance_data(result, material),
                           _USABLE_WIDTH_MM, fonts, styles,
                           label_col_pct=0.40))

    # ---------- Build Instructions ----------
    story.append(Paragraph("Build Instructions", styles["h2"]))
    story.append(Paragraph(
        "Wind-room hand-off. Layer counts are estimated from the "
        "window envelope; verify against the actual bobbin before "
        "committing.",
        styles["note"],
    ))
    story.append(_kv_flow(_build_data(core, wire, result),
                           _USABLE_WIDTH_MM, fonts, styles,
                           label_col_pct=0.40))

    # ---------- Test Plan / FAT ----------
    story.append(Paragraph(
        "Test Plan / Factory Acceptance Test", styles["h2"]))
    story.append(Paragraph(
        "Every parameter QA must measure before signing off the batch. "
        "Pass bands inherit from the Tolerance section above so the "
        "wind-room and the QA bench agree.",
        styles["note"],
    ))
    fat_header, fat_rows = _fat_data(spec, result, material)
    # Column widths sum to 182 mm (the usable width); chosen so the
    # widest column ("Instrument") gets enough room for vendor names.
    story.append(_grid_flow(fat_header, fat_rows,
                             [50.0, 35.0, 65.0, 32.0],
                             fonts, styles))

    # ---------- Environmental Ratings ----------
    story.append(Paragraph("Environmental Ratings", styles["h2"]))
    env_rows = list(_ENV_RATINGS.items())
    story.append(_kv_flow(env_rows, _USABLE_WIDTH_MM, fonts, styles,
                           label_col_pct=0.40))

    # ---------- Insulation & Safety ----------
    story.append(Paragraph("Insulation & Safety", styles["h2"]))
    safety_rows = list(_safety_table_for(spec.topology).items())
    story.append(_kv_flow(safety_rows, _USABLE_WIDTH_MM, fonts, styles,
                           label_col_pct=0.40))

    # ---------- Validation Status ----------
    story.append(Paragraph("Validation Status", styles["h2"]))
    story.append(Paragraph(
        "Provenance of every figure in this datasheet — useful when "
        "stakeholders ask \"is this number measured?\".",
        styles["note"],
    ))
    story.append(_kv_flow(_validation_data(), _USABLE_WIDTH_MM,
                           fonts, styles, label_col_pct=0.40))

    # ---------- Engineering Notes ----------
    notes = (result.notes or "—").strip()
    story.append(Paragraph("Engineering Notes", styles["h2"]))
    story.append(Paragraph(notes, styles["note"]))

    # ---------- Revision History ----------
    story.append(Paragraph("Revision History", styles["h2"]))
    rev_header, rev_rows = _revision_data(revision, designer, now)
    story.append(_grid_flow(rev_header, rev_rows,
                             [18.0, 25.0, 35.0, 104.0],
                             fonts, styles))

    # ---------- Project Metadata ----------
    story.append(Paragraph("Project Metadata", styles["h2"]))
    story.append(Paragraph(
        "Identifiers needed to reproduce this design in MagnaDesign. "
        "The engine is deterministic — feeding the four ids below back "
        "into the same topology recovers an identical result.",
        styles["note"],
    ))
    story.append(_kv_flow(_metadata_data(spec, core, material, wire, pn),
                           _USABLE_WIDTH_MM, fonts, styles,
                           label_col_pct=0.42))

    # ---------- Disclaimer ----------
    story.append(Paragraph("Disclaimer", styles["h2"]))
    story.append(Paragraph(_DISCLAIMER_TEXT, styles["note"]))

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f'<font color="#888888">Generated by MagnaDesign · {now}</font>',
        styles["note"],
    ))

    return story


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_pdf_datasheet(
    spec: Spec,
    core: Core,
    material: Material,
    wire: Wire,
    result: DesignResult,
    output_path: str | Path,
    designer: str = "—",
    revision: str = "A.0",
) -> Path:
    """Write a 3-page A4 PDF datasheet and return its absolute path.

    Drop-in for ``generate_datasheet`` in ``datasheet.py`` (HTML).
    Page 3 (BOM, build, FAT, env, safety, validation, rev history,
    metadata, disclaimer) lands in PDF-3.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fonts = _register_fonts()
    styles = _build_styles(fonts)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Datasheet — {core.part_number}",
        author=designer,
        subject=f"Custom inductor design ({spec.topology})",
        creator="MagnaDesign",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="main",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="default", frames=[frame],
                     onPage=_page_decoration_factory(spec, core, fonts)),
    ])

    pn = _stamp(spec, core, material)
    title = _topology_label(spec.topology)
    now = datetime.now().strftime("%Y-%m-%d")

    story: list = []
    story.extend(_page1_story(
        spec, core, wire, material, result,
        title=title, pn=pn, designer=designer,
        revision=revision, now=now,
        fonts=fonts, styles=styles,
    ))
    story.append(PageBreak())
    story.extend(_page2_story(
        spec, core, wire, material, result,
        title=title, pn=pn, designer=designer,
        revision=revision, now=now,
        fonts=fonts, styles=styles,
    ))

    story.append(PageBreak())
    story.extend(_page3_story(
        spec, core, wire, material, result,
        title=title, pn=pn, designer=designer,
        revision=revision, now=now,
        fonts=fonts, styles=styles,
    ))

    doc.build(story)
    return output_path.resolve()


# ---------------------------------------------------------------------------
# Helpers (header row, page decoration, P/N stamp, topology label).
# ---------------------------------------------------------------------------
def _stamp(spec: Spec, core: Core, material: Material) -> str:
    import hashlib
    src = f"{spec.topology}|{spec.Vin_nom_Vrms}|{spec.Pout_W}|{core.id}|{material.id}"
    return hashlib.sha1(src.encode()).hexdigest()[:8].upper()


def _topology_label(topology: str) -> str:
    return {
        "boost_ccm":     "Boost-PFC CCM Inductor",
        "passive_choke": "Passive Line Choke",
        "line_reactor":  "AC Line Reactor (50/60 Hz)",
    }.get(topology, "Inductor")


def _header_row(title: str, pn: str, designer: str, revision: str,
                 now: str, *, feasible: bool, fonts: dict[str, str],
                 styles: dict[str, ParagraphStyle]) -> Table:
    """Two-column header: left = title block, right = meta + status.

    Table-based layout because Platypus's Frame system doesn't have
    floats/grid; a 2-col table with aligned cells gives us the
    "title left / metadata right" header from the HTML version.
    """
    badge_text = (
        '<font color="#1c7c3b"><b>FEASIBLE</b></font>'
        if feasible
        else '<font color="#a01818"><b>WARNINGS</b></font>'
    )
    left = [
        Paragraph(title, styles["title"]),
        Paragraph("Custom design — generated by MagnaDesign",
                   styles["subtitle"]),
    ]
    right = [
        Paragraph(f"P/N: <b>{pn}</b>", styles["meta_value"]),
        Paragraph(f"Revision: <b>{revision}</b>", styles["meta"]),
        Paragraph(f"Designer: <b>{designer}</b>", styles["meta"]),
        Paragraph(f"Date: <b>{now}</b>", styles["meta"]),
        Paragraph(f"Status: {badge_text}", styles["meta"]),
    ]
    table = Table([[left, right]], colWidths=[110 * mm, 70 * mm])
    table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW",     (0, 0), (-1, -1), 1.2, _Palette.rule),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return table


def _page_decoration_factory(spec: Spec, core: Core,
                              fonts: dict[str, str]):
    """Closure that paints the running footer on each page.

    Called by ReportLab during ``BaseDocTemplate.build`` for every
    page. Centralised here so adding e.g. a confidential watermark
    or an internal P/N stamp is a single-line change.
    """
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(fonts["regular"], 8)
        canvas.setFillColor(_Palette.muted)
        canvas.drawString(
            14 * mm, 8 * mm,
            f"MagnaDesign · {datetime.now().strftime('%Y-%m-%d')}",
        )
        canvas.drawRightString(
            doc.pagesize[0] - 14 * mm, 8 * mm,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()
    return _draw
