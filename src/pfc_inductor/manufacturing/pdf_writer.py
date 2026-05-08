"""Manufacturing-spec PDF writer.

Hands a :class:`MfgSpec` to ReportLab and produces a vendor-
quotable PDF with the canonical layout:

1. Cover page — revision block, designer, customer, MagnaDesign
   version + git SHA hint.
2. Construction page — winding diagram (per-layer), insulation
   stack-up, gap detail, hi-pot voltage.
3. Acceptance test plan — one row per :class:`AcceptanceTest`,
   tolerances + instrument class.
4. Signature block — designer / approver / vendor sign-offs.

The writer keeps the heavy reportlab + matplotlib imports
local so the rest of the manufacturing module remains importable
in a CLI script that only needs the engineering payload.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

from pfc_inductor.manufacturing.spec import MfgSpec


# Visual constants — kept ASCII so the writer can be inspected
# without touching the theme module.
_BORDER = "#D4D4D8"
_TEXT = "#18181B"
_TEXT_MUTED = "#52525B"
_BAND_BG = "#F4F4F5"
_PASS = "#15803D"
_WARN = "#A16207"
_FAIL = "#B91C1C"
_ACCENT = "#A78BFA"


def write_mfg_spec_pdf(spec: MfgSpec, output_path: Path | str) -> Path:
    """Write the manufacturing spec to ``output_path`` and return it.

    The output directory is created if missing. On success the
    returned path is the same one passed in (resolved).
    """
    # Lazy import — reportlab is heavy and only this writer needs it.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        BaseDocTemplate, Frame, KeepTogether, PageBreak,
        PageTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base_styles = getSampleStyleSheet()
    styles = _build_styles(base_styles, ParagraphStyle, colors)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Manufacturing Spec — {spec.core.part_number}",
        author=spec.designer,
        subject=f"Vendor manufacturing specification ({spec.spec.topology})",
        creator="MagnaDesign",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="main",
        leftPadding=0, rightPadding=0, topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="default", frames=[frame],
                                       onPage=_make_page_decorator(spec))])

    story: list = []
    story.extend(_cover_page(spec, styles, mm, Paragraph, Spacer,
                             Table, TableStyle, colors))
    story.append(PageBreak())
    story.extend(_construction_page(spec, styles, mm, Paragraph,
                                    Spacer, Table, TableStyle,
                                    colors, KeepTogether))
    story.append(PageBreak())
    story.extend(_acceptance_page(spec, styles, mm, Paragraph,
                                  Spacer, Table, TableStyle, colors))
    story.append(PageBreak())
    story.extend(_signature_page(spec, styles, mm, Paragraph,
                                 Spacer, Table, TableStyle, colors))

    doc.build(story)
    return output_path


# ---------------------------------------------------------------------------
# Style builder
# ---------------------------------------------------------------------------
def _build_styles(base, ParagraphStyle, colors):
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=22, leading=26, textColor=colors.HexColor(_TEXT),
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=16, leading=20, textColor=colors.HexColor(_TEXT),
            spaceBefore=8, spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=16, textColor=colors.HexColor(_TEXT),
            spaceBefore=8, spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9, leading=13, textColor=colors.HexColor(_TEXT),
        ),
        "muted": ParagraphStyle(
            "muted", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8, leading=11, textColor=colors.HexColor(_TEXT_MUTED),
        ),
        "warn": ParagraphStyle(
            "warn", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=9, leading=12, textColor=colors.HexColor(_WARN),
        ),
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _cover_page(spec: MfgSpec, styles, mm, Paragraph, Spacer,
                Table, TableStyle, colors):
    flow: list = []
    flow.append(Paragraph(
        "Manufacturing Specification", styles["title"]))
    flow.append(Paragraph(
        f"<b>{spec.core.part_number}</b> · "
        f"{spec.spec.topology} · {spec.material.name}",
        styles["body"],
    ))
    flow.append(Spacer(1, 8 * mm))

    rev_block = [
        ["Project",       spec.project_name],
        ["Designer",      spec.designer],
        ["Revision",      spec.revision],
        ["Date",          spec.date_iso],
        ["Topology",      spec.spec.topology],
        ["Insulation",    spec.insulation.name],
        ["Hi-pot voltage", f"{spec.hipot_V:.0f} V AC"],
        ["MagnaDesign",   _magnadesign_version()],
    ]
    flow.append(_kv_table(rev_block, mm, Table, TableStyle, colors))
    flow.append(Spacer(1, 8 * mm))

    flow.append(Paragraph("Mechanical summary", styles["h2"]))
    mech_rows = [
        ["Core part number", spec.core.part_number],
        ["Core shape",       spec.core.shape],
        ["OD × ID × HT",     _od_id_ht(spec)],
        ["Wire",             spec.wire.id],
        ["Wire OD",          f"{_wire_od(spec):.3f} mm"],
        ["N turns",          str(int(spec.result.N_turns))],
        ["Layers planned",   f"{spec.winding.n_layers}"],
        ["Bobbin used",      f"{spec.winding.bobbin_used_pct:.0f} %"],
    ]
    flow.append(_kv_table(mech_rows, mm, Table, TableStyle, colors))

    flow.append(Spacer(1, 8 * mm))

    flow.append(Paragraph("Electrical summary", styles["h2"]))
    elec_rows = [
        ["Inductance (target)",
         f"{spec.result.L_required_uH:.1f} µH"],
        ["Inductance (actual)",
         f"{spec.result.L_actual_uH:.1f} µH"],
        ["Peak flux B_pk",
         f"{spec.result.B_pk_T * 1000:.0f} mT"],
        ["Total losses",
         f"{spec.result.losses.P_total_W:.2f} W"],
        ["Winding temperature",
         f"{spec.result.T_winding_C:.1f} °C"],
        ["Temperature rise",
         f"{spec.result.T_rise_C:.1f} °C"],
    ]
    flow.append(_kv_table(elec_rows, mm, Table, TableStyle, colors))

    if spec.notes:
        flow.append(Spacer(1, 6 * mm))
        flow.append(Paragraph("Notes", styles["h2"]))
        for note in spec.notes:
            flow.append(Paragraph(f"• {note}", styles["warn"]))

    return flow


def _construction_page(spec: MfgSpec, styles, mm, Paragraph,
                       Spacer, Table, TableStyle, colors,
                       KeepTogether):
    flow: list = []
    flow.append(Paragraph("Construction", styles["h1"]))

    # Winding diagram — embedded matplotlib figure showing layer
    # stack with cumulative height.
    flow.append(Paragraph("Winding plan", styles["h2"]))
    img = _winding_diagram(spec, mm)
    if img is not None:
        flow.append(img)
    flow.append(Spacer(1, 4 * mm))

    # Per-layer table.
    rows: list[list[str]] = [
        ["Layer", "Turns", "Breadth [mm]", "Stack height [mm]"],
    ]
    for layer in spec.winding.layers:
        rows.append([
            f"{layer.index}",
            f"{layer.turns}",
            f"{layer.breadth_mm:.2f}",
            f"{layer.height_mm:.2f}",
        ])
    if len(rows) == 1:
        rows.append(["—", "—", "—", "—"])
    flow.append(_table(rows, mm, Table, TableStyle, colors,
                       widths=[20 * mm, 25 * mm, 35 * mm, 45 * mm]))
    flow.append(Spacer(1, 6 * mm))

    # Insulation stack.
    flow.append(Paragraph("Insulation stack-up", styles["h2"]))
    insulation_rows = [
        ["Class",                 spec.insulation.name],
        ["T_max",                 f"{spec.insulation.T_max_C:.0f} °C"],
        ["Inter-layer tape",      spec.insulation.inter_layer_tape],
        ["Tape thickness",
         f"{spec.insulation.inter_layer_tape_mm:.2f} mm"],
        ["Wire enamel",           spec.insulation.enamel_grade],
        ["Hi-pot voltage",        f"{spec.hipot_V:.0f} V AC"],
        ["Hi-pot dwell",
         f"{spec.insulation.hipot_dwell_s:.0f} s"],
    ]
    flow.append(_kv_table(insulation_rows, mm, Table, TableStyle, colors))
    flow.append(Spacer(1, 6 * mm))

    # Air-gap detail (when applicable).
    gap_mm = float(getattr(spec.core, "lgap_mm", 0.0) or 0.0)
    flow.append(Paragraph("Air gap", styles["h2"]))
    if gap_mm > 0:
        flow.append(Paragraph(
            f"Total gap <b>{gap_mm:.2f} mm</b> centred on the "
            f"magnetic path. Use shim material per vendor's "
            f"standard practice (typically Mylar or Kapton "
            f"matching the insulation class). Distribute the "
            f"gap across the centre leg only on EE / ETD cores; "
            f"toroids ship with their gap built into the powder "
            f"dilution and need no shim.",
            styles["body"],
        ))
    else:
        flow.append(Paragraph(
            "No discrete air gap (powder-core distributed gap "
            "or ungapped ferrite). No shim required.",
            styles["body"],
        ))

    return flow


def _acceptance_page(spec: MfgSpec, styles, mm, Paragraph,
                     Spacer, Table, TableStyle, colors):
    flow: list = []
    flow.append(Paragraph("Acceptance Test Plan", styles["h1"]))
    flow.append(Paragraph(
        "Every unit must satisfy every row before being released. "
        "Tolerances follow the conservative magnetics-vendor "
        "guideline; the customer may tighten on demand.",
        styles["muted"],
    ))
    flow.append(Spacer(1, 4 * mm))

    rows: list[list[str]] = [
        ["#", "Test", "Condition", "Expected",
         "Tolerance", "Instrument"],
    ]
    for idx, test in enumerate(spec.acceptance_tests, start=1):
        rows.append([
            str(idx),
            test.name,
            test.condition,
            test.expected,
            test.tolerance,
            test.instrument,
        ])
    flow.append(_table(rows, mm, Table, TableStyle, colors,
                       widths=[8 * mm, 32 * mm, 36 * mm,
                               30 * mm, 26 * mm, 38 * mm]))

    return flow


def _signature_page(spec: MfgSpec, styles, mm, Paragraph,
                    Spacer, Table, TableStyle, colors):
    flow: list = []
    flow.append(Paragraph("Sign-off", styles["h1"]))
    flow.append(Paragraph(
        "This specification governs the manufacture of "
        f"part <b>{spec.core.part_number}</b> revision "
        f"<b>{spec.revision}</b>. Vendor confirms acceptance by "
        "signing below; deviations require a written ECN.",
        styles["body"],
    ))
    flow.append(Spacer(1, 8 * mm))

    sig_rows = [
        ["Role",      "Name",                    "Date",
         "Signature"],
        ["Designer",  spec.designer,             spec.date_iso, ""],
        ["Approver",  "",                        "",            ""],
        ["Vendor",    "",                        "",            ""],
    ]
    flow.append(_table(sig_rows, mm, Table, TableStyle, colors,
                       widths=[28 * mm, 50 * mm, 30 * mm, 60 * mm],
                       row_height=18 * mm))

    flow.append(Spacer(1, 8 * mm))
    flow.append(Paragraph(
        "Generated by MagnaDesign — see manifest.json in the "
        "exported bundle for the SHA-256 of this document.",
        styles["muted"],
    ))
    return flow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _kv_table(rows: list[list[str]], mm, Table, TableStyle, colors):
    """Two-column key-value table with the canonical visual."""
    table = Table(rows, colWidths=[55 * mm, 100 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("FONTNAME",   (0, 0), (0, -1),  "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (0, -1),  colors.HexColor(_BAND_BG)),
        ("BOX",        (0, 0), (-1, -1), 0.5, colors.HexColor(_BORDER)),
        ("INNERGRID",  (0, 0), (-1, -1), 0.25, colors.HexColor(_BORDER)),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    return table


def _table(rows: list[list[str]], mm, Table, TableStyle, colors,
           *, widths, row_height: float | None = None):
    """Generic bordered table with a header band."""
    kwargs = {"colWidths": widths}
    if row_height is not None and len(rows) > 1:
        kwargs["rowHeights"] = [None] + [row_height] * (len(rows) - 1)
    table = Table(rows, **kwargs)
    table.setStyle(TableStyle([
        ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("FONTNAME",   (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0),  colors.HexColor(_BAND_BG)),
        ("BOX",        (0, 0), (-1, -1), 0.5, colors.HexColor(_BORDER)),
        ("INNERGRID",  (0, 0), (-1, -1), 0.25, colors.HexColor(_BORDER)),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ]))
    return table


def _winding_diagram(spec: MfgSpec, mm):
    """Render a layer-stack diagram via matplotlib and embed as
    a flowable Image. Returns ``None`` if matplotlib isn't
    importable (CLI-only environments)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from reportlab.platypus import Image as RLImage
    except ImportError:
        return None

    fig, ax = plt.subplots(figsize=(6.5, 2.5), dpi=150)
    if not spec.winding.layers:
        ax.text(0.5, 0.5, "No winding plan available",
                ha="center", va="center", fontsize=10,
                color=_TEXT_MUTED, transform=ax.transAxes)
    else:
        for layer in spec.winding.layers:
            base = layer.height_mm - (layer.height_mm
                                       - (spec.winding.layers[layer.index - 2].height_mm
                                          if layer.index > 1 else 0))
            ax.barh(layer.index, layer.breadth_mm,
                    color=_ACCENT, edgecolor=_TEXT, linewidth=0.6)
            ax.text(layer.breadth_mm + 1, layer.index,
                    f"{layer.turns} turns @ {layer.height_mm:.2f} mm",
                    va="center", fontsize=8, color=_TEXT)
        ax.invert_yaxis()
        ax.set_xlabel("Layer breadth [mm]", fontsize=8)
        ax.set_ylabel("Layer #", fontsize=8)
        ax.set_xlim(0, spec.winding.layer_breadth_mm * 1.4 + 1)
        ax.tick_params(axis="both", labelsize=7)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.grid(True, axis="x", linewidth=0.4, color=_BORDER, alpha=0.6)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return RLImage(buf, width=170 * mm, height=55 * mm)


def _make_page_decorator(spec: MfgSpec):
    """Return an ``onPage`` callback that draws the running
    footer + page-of-N (after pass 2) on every page."""
    project = spec.project_name
    rev = spec.revision

    def _onPage(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        # Hex colour for muted text — converted at the canvas level.
        canvas.setFillColorRGB(0.32, 0.32, 0.36)  # close to _TEXT_MUTED
        canvas.drawString(
            14 * 2.83465,  # 14 mm in points
            10 * 2.83465,
            f"{project}  ·  rev {rev}  ·  page {doc.page}",
        )
        canvas.drawRightString(
            doc.pagesize[0] - 14 * 2.83465,
            10 * 2.83465,
            "MagnaDesign manufacturing spec",
        )
        canvas.restoreState()
    return _onPage


def _od_id_ht(spec: MfgSpec) -> str:
    od = float(spec.core.OD_mm or 0.0)
    id_ = float(spec.core.ID_mm or 0.0)
    ht = float(spec.core.HT_mm or 0.0)
    if od == 0 and id_ == 0 and ht == 0:
        return "—"
    return f"{od:.1f} × {id_:.1f} × {ht:.1f} mm"


def _wire_od(spec: MfgSpec) -> float:
    try:
        return spec.wire.outer_diameter_mm()
    except ValueError:
        return float(spec.wire.d_cu_mm or spec.wire.d_iso_mm or 0.0)


def _magnadesign_version() -> str:
    try:
        from importlib.metadata import version as _v
        return _v("magnadesign")
    except Exception:
        return "unknown"
