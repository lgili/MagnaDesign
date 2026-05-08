"""Multi-column comparison PDF (ReportLab).

Companion to ``html_compare.py``: same data sources (``CompareSlot``
list, ``METRICS``), different output target. Produces a print-grade
A4 *landscape* PDF with up to 4 designs side-by-side. Landscape is
chosen because the comparator's worst case is 5 columns (1 metric
label + 4 designs); portrait squeezes data columns to ~36 mm each
and the longer cell strings (e.g. ``Magnetics — 0058617a2-…
(Toroid)``) wrap into ugly multi-line cells.

Layout
------
- Header: title + date + ``REF`` callout for the leftmost column.
- 3 sections (Specifications, Selection, Compared metrics) — same
  groupings as the HTML version. The Compared-metrics table colours
  cells light-green (better) / light-red (worse) relative to the
  reference column, matching the HTML/dialog colour scheme.
- Footer: ``MagnaDesign · YYYY-MM-DD · Page N``.

The styling helpers (font registration, palette, paragraph styles,
table styles) come from ``pdf_report.py`` so a customer who receives
both a single-design datasheet and a comparison sheet sees consistent
typography across the two artefacts.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
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

from pfc_inductor.compare import METRICS, CompareSlot, categorize
from pfc_inductor.report.pdf_report import (
    _Palette,
    _build_styles,
    _register_fonts,
)

# ---------------------------------------------------------------------------
# Diff colouring — same hex codes as the HTML version (and the in-app
# CompareDialog cell colouring), so the printed PDF matches the screen.
# ---------------------------------------------------------------------------
_DIFF_BG = {
    "better":  HexColor("#dff5e3"),
    "worse":   HexColor("#fbe2e2"),
    "neutral": HexColor("#ffffff"),
}

# A4 landscape, 14 mm margins → 269 mm usable width. Enough for the
# metric label column at 50 mm + up to 4 data columns ≥ 54 mm each.
_USABLE_WIDTH_MM_LS = 297 - 2 * 14  # 269


def generate_compare_pdf(
    slots: list[CompareSlot],
    output_path: str | Path,
) -> Path:
    """Write a comparison PDF and return the absolute path.

    Mirrors ``generate_compare_html`` (same signature). Up to 4
    slots; the ``CompareDialog`` enforces this — we just trust it.
    """
    if not slots:
        raise ValueError("at least one slot is required")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fonts = _register_fonts()
    styles = _build_styles(fonts)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Design comparison",
        author="MagnaDesign",
        subject=f"Comparison of {len(slots)} designs",
        creator="MagnaDesign",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height, id="main",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="default", frames=[frame],
                     onPage=_compare_decoration_factory(fonts)),
    ])

    story: list = []
    story.append(_header(slots, styles, fonts))
    story.append(Spacer(1, 4 * mm))

    # Common column widths for all three tables: metric label = 50 mm,
    # remaining width split equally across data columns.
    n = len(slots)
    label_w_mm = 50.0
    data_w_mm = (_USABLE_WIDTH_MM_LS - label_w_mm) / max(n, 1)
    col_widths = [label_w_mm * mm] + [data_w_mm * mm] * n

    # ---------- Specifications ----------
    story.append(KeepTogether([
        Paragraph("Specifications", styles["h2"]),
        _spec_table(slots, col_widths, fonts, styles),
    ]))

    # ---------- Selection ----------
    story.append(KeepTogether([
        Paragraph("Selection", styles["h2"]),
        _selection_table(slots, col_widths, fonts, styles),
    ]))

    # ---------- Compared metrics (with diff colouring) ----------
    # Single ``KeepTogether`` for header + table is too aggressive —
    # the metrics table has 21 rows and forcing it together can leave
    # the previous page half-empty. Header alone is fine since the
    # table is large enough that the next page won't waste much space.
    story.append(Paragraph("Compared metrics", styles["h2"]))
    story.append(Paragraph(
        "Column 1 is the reference; "
        '<font color="#1c7c3b">green</font> = better, '
        '<font color="#a01818">red</font> = worse.',
        styles["note"],
    ))
    story.append(_metrics_table(slots, col_widths, fonts, styles))

    doc.build(story)
    return output_path.resolve()


# ---------------------------------------------------------------------------
# Header — title + meta + REF callout for the leftmost column.
# ---------------------------------------------------------------------------
def _header(slots: list[CompareSlot], styles, fonts) -> Table:
    n = len(slots)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    left = [
        Paragraph(f"Comparison of {n} designs", styles["title"]),
        Paragraph("Custom designs — generated by MagnaDesign",
                   styles["subtitle"]),
    ]
    right = [
        Paragraph(f"Date: <b>{now}</b>", styles["meta"]),
        Paragraph(
            f"Reference: <b>{_short_label(slots[0])}</b>",
            styles["meta"],
        ),
        Paragraph(f"Slots: <b>{n}</b>", styles["meta"]),
    ]
    table = Table([[left, right]], colWidths=[180 * mm, 89 * mm])
    table.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW",     (0, 0), (-1, -1), 1.2, _Palette.rule),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    return table


def _short_label(slot: CompareSlot) -> str:
    """One-line label for a slot. ``CompareSlot.short_label`` carries
    line-break separators that read fine in tooltip/HTML but look
    awkward when squeezed into a 50-mm-wide table cell — flatten to
    a single dot-separated line."""
    return slot.short_label.replace("\n", " · ")


# ---------------------------------------------------------------------------
# Tables.
# ---------------------------------------------------------------------------
def _column_header_row(slots: list[CompareSlot]) -> list[str]:
    """First row of every comparison table: ``Item`` + per-slot label.
    The leftmost slot gets a ``(REF)`` suffix to match the HTML's
    badge."""
    cells = ["Item"]
    for i, s in enumerate(slots):
        label = _short_label(s)
        if i == 0:
            label = f"{label} (REF)"
        cells.append(label)
    return cells


def _table_style(fonts, n_cols: int) -> TableStyle:
    """Style shared by Specifications + Selection tables. Header row
    gets the label-bg tint and a thicker rule below; data rows get
    soft separators."""
    return TableStyle([
        ("FONTNAME",      (0, 0), (-1, -1), fonts["regular"]),
        ("FONTNAME",      (0, 0), (-1, 0),  fonts["semibold"]),
        ("FONTSIZE",      (0, 0), (-1, -1), 9.0),
        ("FONTNAME",      (0, 1), (0, -1),  fonts["regular"]),
        ("TEXTCOLOR",     (0, 1), (0, -1),  _Palette.muted),
        ("TEXTCOLOR",     (1, 1), (-1, -1), _Palette.text),
        ("BACKGROUND",    (0, 0), (-1, 0),  _Palette.label_bg),
        ("ALIGN",         (0, 0), (0, -1),  "LEFT"),
        ("ALIGN",         (1, 0), (-1, -1), "LEFT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, _Palette.rule),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.25, _Palette.soft_rule),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ])


def _spec_table(slots, col_widths, fonts, styles) -> Table:
    """Topology-adapted spec rows (mirrors ``html_compare._spec_table``).
    Fields with no applicable value across *any* slot are dropped
    rather than shown as a row of dashes."""
    all_fields: list[tuple[str, callable]] = [
        ("Topology",       lambda s: s.spec.topology),
        ("Vin (range)",    lambda s: f"{s.spec.Vin_min_Vrms:.0f}–"
                                      f"{s.spec.Vin_max_Vrms:.0f} Vrms"),
        ("Vout",           lambda s: (
            f"{s.spec.Vout_V:.0f} V"
            if s.spec.topology != "line_reactor" else "—")),
        ("Pout",           lambda s: (
            f"{s.spec.Pout_W:.0f} W"
            if s.spec.topology != "line_reactor" else "—")),
        ("fsw",            lambda s: (
            f"{s.spec.f_sw_kHz:.0f} kHz"
            if s.spec.topology != "line_reactor" else "—")),
        ("Ripple target",  lambda s: (
            f"{s.spec.ripple_pct:.0f} %"
            if s.spec.topology != "line_reactor" else "—")),
        ("Phases",         lambda s: (
            str(s.spec.n_phases)
            if s.spec.topology == "line_reactor" else "—")),
        ("Line V",         lambda s: (
            f"{s.spec.Vin_nom_Vrms:.0f} Vrms"
            if s.spec.topology == "line_reactor" else "—")),
        ("Rated I",        lambda s: (
            f"{s.spec.I_rated_Arms:.1f} A"
            if s.spec.topology == "line_reactor" else "—")),
        ("Target inductance", lambda s: (
            f"{s.spec.L_req_mH:.2f} mH"
            if s.spec.topology == "line_reactor" else "—")),
        ("T amb",          lambda s: f"{s.spec.T_amb_C:.0f} °C"),
    ]
    fields = [
        (label, fn) for (label, fn) in all_fields
        if any(fn(s) != "—" for s in slots)
    ]
    body_style = styles["body"]
    rows = [[Paragraph(c, body_style)
              for c in _column_header_row(slots)]]
    for label, fn in fields:
        rows.append([Paragraph(label, body_style)] +
                     [Paragraph(str(fn(s)), body_style) for s in slots])
    t = Table(rows, colWidths=col_widths)
    t.setStyle(_table_style(fonts, n_cols=len(rows[0])))
    return t


def _selection_table(slots, col_widths, fonts, styles) -> Table:
    fields = [
        ("Core",        lambda s: f"{s.core.vendor} — "
                                   f"{s.core.part_number} ({s.core.shape})"),
        ("Material",    lambda s: f"{s.material.vendor} — "
                                   f"{s.material.name}  "
                                   f"μ={s.material.mu_initial:.0f}"),
        ("Wire",        lambda s: f"{s.wire.id} ({s.wire.type})"),
        ("Core volume", lambda s: f"{s.core.Ve_mm3 / 1000:.1f} cm³"),
    ]
    body_style = styles["body"]
    rows = [[Paragraph(c, body_style)
              for c in _column_header_row(slots)]]
    for label, fn in fields:
        rows.append([Paragraph(label, body_style)] +
                     [Paragraph(str(fn(s)), body_style) for s in slots])
    t = Table(rows, colWidths=col_widths)
    t.setStyle(_table_style(fonts, n_cols=len(rows[0])))
    return t


def _metrics_table(slots, col_widths, fonts, styles) -> Table:
    """Metrics table with per-cell green/red colouring relative to
    the reference column (slot[0]). Cells where the metric direction
    is "neutral" or the value is identical stay white.
    """
    body_style = styles["body"]
    rows: list[list] = [[Paragraph(c, body_style)
                          for c in _column_header_row(slots)]]
    diff_kinds: list[list[str]] = [["neutral"] * (len(slots) + 1)]

    leftmost = slots[0]
    for metric in METRICS:
        try:
            ref_val = metric.value_of(leftmost)
        except Exception:
            ref_val = None
        cell_kinds: list[str] = ["neutral"]  # for label cell
        cells = [Paragraph(metric.label, body_style)]
        for i, s in enumerate(slots):
            try:
                val_text = metric.format(s)
                v = metric.value_of(s)
                kind = (
                    categorize(metric.key, ref_val, v)
                    if (i > 0 and ref_val is not None) else "neutral"
                )
            except Exception:
                val_text = "—"
                kind = "neutral"
            unit = f" {metric.unit}" if metric.unit else ""
            cells.append(Paragraph(f"{val_text}{unit}", body_style))
            cell_kinds.append(kind)
        rows.append(cells)
        diff_kinds.append(cell_kinds)

    t = Table(rows, colWidths=col_widths)
    style = _table_style(fonts, n_cols=len(rows[0]))
    # Add diff backgrounds — applied as per-cell BACKGROUND commands
    # on top of the base style. ReportLab evaluates style commands
    # in order, so later-added BACKGROUND wins.
    for r, kinds in enumerate(diff_kinds):
        for c, kind in enumerate(kinds):
            if kind in ("better", "worse"):
                style.add("BACKGROUND", (c, r), (c, r), _DIFF_BG[kind])
    t.setStyle(style)
    return t


# ---------------------------------------------------------------------------
# Page decoration — same footer style as ``pdf_report.py`` so a
# customer receiving both artefacts sees consistent typography. We
# can't reuse ``pdf_report._page_decoration_factory`` directly — it
# wants a ``Spec`` and a ``Core`` for the (currently unused) stamp;
# this lighter version drops the stamp dependency.
# ---------------------------------------------------------------------------
def _compare_decoration_factory(fonts):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(fonts["regular"], 8)
        canvas.setFillColor(_Palette.muted)
        canvas.drawString(
            14 * mm, 8 * mm,
            f"MagnaDesign · {datetime.now().strftime('%Y-%m-%d')} · "
            f"Comparison",
        )
        canvas.drawRightString(
            doc.pagesize[0] - 14 * mm, 8 * mm,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()
    return _draw
