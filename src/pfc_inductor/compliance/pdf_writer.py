"""ReportLab PDF writer for the compliance report.

Takes a :class:`ComplianceBundle` and lays out a multi-page PDF
suitable for handing to a certification engineer or a quality
auditor:

- Cover page with verdict marker, project context, MagnaDesign
  version, applicable standards.
- One section per standard: header strip (PASS / MARGINAL /
  FAIL), method paragraph, harmonic/limit table, plot,
  conclusion + follow-on action items.
- Footer on every page with paginator + git SHA so the same
  PDF can be referenced by exact build state in audit logs.

Shared layout helpers in
:mod:`pfc_inductor.report.pdf_report` are intentionally NOT
imported — that module is still actively evolving for the
manufacturing-spec / datasheet rewrite. The bits we need here
(palette, style, simple tables, matplotlib embedding) total
~100 LOC; once both modules stabilise the duplicate can move
to a ``report._pdf_kit`` shared module.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import matplotlib

# ``Agg`` backend keeps the PDF generation thread-safe and
# headless-friendly. Set BEFORE pyplot imports anything else.
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
)
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from pfc_inductor.compliance.dispatcher import (
    ComplianceBundle,
    ConclusionLabel,
    StandardResult,
)


# ---------------------------------------------------------------------------
# Visual palette — kept ASCII so the PDF style stays maintainable
# without pulling the full theme module into the printable surface.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Style:
    text: str = "#18181B"
    text_muted: str = "#52525B"
    accent: str = "#A78BFA"
    pass_color: str = "#15803D"
    warn_color: str = "#A16207"
    fail_color: str = "#B91C1C"
    border: str = "#D4D4D8"
    band_bg: str = "#F4F4F5"


_STYLE = _Style()


def _color_for(conclusion: ConclusionLabel) -> str:
    return {
        "PASS": _STYLE.pass_color,
        "MARGINAL": _STYLE.warn_color,
        "FAIL": _STYLE.fail_color,
        "NOT APPLICABLE": _STYLE.text_muted,
    }.get(conclusion, _STYLE.text_muted)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def write_compliance_pdf(
    bundle: ComplianceBundle,
    output_path: Path | str,
    *,
    app_version: str = "",
    git_sha: str = "",
) -> Path:
    """Render ``bundle`` to ``output_path``.

    Returns the absolute output path so callers can chain into a
    "open in browser" or "post to a workflow URL" action.
    """
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title=f"Compliance report — {bundle.project_name}",
        author="MagnaDesign",
    )
    styles = _build_styles()

    story = []
    story.extend(_cover_section(bundle, styles, app_version=app_version))
    story.append(Spacer(1, 6 * mm))

    for std in bundle.standards:
        story.extend(_standard_section(std, styles))
        story.append(Spacer(1, 8 * mm))

    if not bundle.standards:
        story.append(
            Paragraph(
                "No standards were applicable for the supplied "
                "topology + region combination. The compliance report "
                "is a no-op for this design — verify the topology and "
                "region tags are correct.",
                styles["body_muted"],
            )
        )

    doc.build(
        story,
        onFirstPage=_paginator_factory(bundle, app_version, git_sha),
        onLaterPages=_paginator_factory(bundle, app_version, git_sha),
    )
    return out


# ---------------------------------------------------------------------------
# Cover section
# ---------------------------------------------------------------------------
def _cover_section(
    bundle: ComplianceBundle,
    styles: dict[str, ParagraphStyle],
    *,
    app_version: str,
) -> list:
    """Title + verdict + applicable-standards summary."""
    flow = []

    flow.append(
        Paragraph(
            "Compliance report",
            styles["title"],
        )
    )
    flow.append(
        Paragraph(
            f"<b>{bundle.project_name}</b>  ·  topology: "
            f"<b>{bundle.topology}</b>  ·  region: <b>{bundle.region}</b>",
            styles["body_muted"],
        )
    )
    flow.append(Spacer(1, 4 * mm))

    overall = bundle.overall
    color = _color_for(overall)
    flow.append(
        Paragraph(
            f'<font color="{color}"><b>Overall verdict: {overall}</b></font>',
            styles["verdict_strip"],
        )
    )
    flow.append(Spacer(1, 3 * mm))

    # Applicable-standards table
    if bundle.standards:
        rows: list[list[str]] = [["Standard", "Edition", "Conclusion"]]
        for std in bundle.standards:
            rows.append([std.standard, std.edition, std.conclusion])
        table = Table(rows, colWidths=[60 * mm, 35 * mm, 40 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_STYLE.band_bg)),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(_STYLE.border)),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor(_STYLE.border)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TEXTCOLOR", (2, 1), (2, -1), colors.black),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        flow.append(table)

    flow.append(Spacer(1, 4 * mm))
    if app_version:
        flow.append(
            Paragraph(
                f"Generated by MagnaDesign {app_version}.",
                styles["body_muted"],
            )
        )
    return flow


# ---------------------------------------------------------------------------
# Per-standard section
# ---------------------------------------------------------------------------
def _standard_section(
    std: StandardResult,
    styles: dict[str, ParagraphStyle],
) -> list:
    flow = []

    flow.append(Paragraph(std.standard, styles["section_title"]))
    flow.append(
        Paragraph(
            f"{std.edition}  ·  {std.scope}",
            styles["body_muted"],
        )
    )
    flow.append(Spacer(1, 2 * mm))

    color = _color_for(std.conclusion)
    flow.append(
        Paragraph(
            f'<font color="{color}"><b>{std.conclusion}</b></font>  · {std.summary}',
            styles["verdict_strip"],
        )
    )
    flow.append(Spacer(1, 3 * mm))

    # Per-row table — generic shape so any future standard's rows
    # render uniformly. For IEC the rows are
    # ``(harmonic, measured, limit, margin %, pass)``.
    if std.rows:
        rows: list[list[str]] = [
            ["Order", "Measured", "Limit", "Margin", "Result"],
        ]
        for label, value, limit, margin, passed in std.rows:
            rows.append(
                [
                    label,
                    value,
                    limit,
                    f"{margin:+.1f} %",
                    "PASS" if passed else "FAIL",
                ]
            )
        table = Table(rows, colWidths=[20 * mm, 30 * mm, 30 * mm, 25 * mm, 25 * mm])
        style = TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_STYLE.band_bg)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(_STYLE.border)),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor(_STYLE.border)),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
        # Colour the "Result" cells per pass/fail, scanning the
        # source rows so we don't have to re-evaluate predicates.
        for row_idx, row in enumerate(std.rows, start=1):
            _label, _value, _limit, _margin, passed = row
            cell_color = _STYLE.pass_color if passed else _STYLE.fail_color
            style.add("TEXTCOLOR", (-1, row_idx), (-1, row_idx), colors.HexColor(cell_color))
            style.add("FONTNAME", (-1, row_idx), (-1, row_idx), "Helvetica-Bold")
        table.setStyle(style)
        flow.append(table)
        flow.append(Spacer(1, 3 * mm))

    # Harmonic spectrum plot — only when the extras dict carries one.
    if "harmonic_pct" in std.extras:
        img = _harmonic_plot(std)
        if img is not None:
            flow.append(img)
            flow.append(Spacer(1, 3 * mm))

    if std.notes:
        for note in std.notes:
            flow.append(Paragraph(note, styles["note"]))

    return flow


# ---------------------------------------------------------------------------
# Plot helper
# ---------------------------------------------------------------------------
def _harmonic_plot(std: StandardResult) -> Optional[RLImage]:
    """Render the harmonic spectrum (measured vs. limit) as a bar
    chart and return a ReportLab Image flowable. Returns ``None``
    when the extras dict is missing the needed payload — the
    section keeps rendering, just without the plot."""
    pct = std.extras.get("harmonic_pct") or []
    if not pct:
        return None

    fig, ax = plt.subplots(figsize=(6.0, 2.6), dpi=150)
    orders = list(range(1, len(pct) + 1))
    ax.bar(
        orders,
        pct,
        color=_STYLE.accent,
        alpha=0.85,
        width=0.7,
        label="Measured",
    )

    # Overlay per-order limits as percentage of fundamental, so the
    # bar chart and the limit line share the same y axis. Pulled
    # from std.rows because that's the single source of truth for
    # what the dispatcher computed.
    if std.rows and pct[0] > 0:
        # Reverse-engineer "limit % of fundamental" from the rows:
        # we know each row's limit_str carries "<value> mA" and we
        # have the fundamental in extras. Simplest: parse the
        # number out of the string.
        fund_a = float(std.extras.get("fundamental_A", 0.0))
        if fund_a > 0:
            limit_orders, limit_pcts = [], []
            for label, _meas, limit_str, _margin, _passed in std.rows:
                # label is "n = <int>"
                try:
                    order = int(label.split("=")[1].strip())
                    # limit_str is "<x> mA" — convert to A then %.
                    limit_a = float(limit_str.split()[0]) / 1000.0
                    limit_orders.append(order)
                    limit_pcts.append(limit_a / fund_a * 100.0)
                except (ValueError, IndexError):
                    continue
            if limit_orders:
                ax.plot(
                    limit_orders,
                    limit_pcts,
                    color=_STYLE.fail_color,
                    linewidth=1.4,
                    marker="_",
                    markersize=8,
                    label="IEC limit",
                )

    ax.set_xlabel("Harmonic order", fontsize=8)
    ax.set_ylabel("Amplitude (% of fundamental)", fontsize=8)
    ax.set_xlim(0.5, len(pct) + 0.5)
    ax.set_yscale("log")
    ax.set_ylim(0.001, 100.0)
    ax.tick_params(axis="both", labelsize=7)
    ax.grid(True, which="major", color=_STYLE.border, linewidth=0.4)
    ax.legend(fontsize=7, loc="upper right", frameon=False)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return RLImage(buf, width=170 * mm, height=70 * mm)


# ---------------------------------------------------------------------------
# Style sheet
# ---------------------------------------------------------------------------
def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "title": ParagraphStyle(
            "title",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            spaceAfter=4,
            textColor=colors.HexColor(_STYLE.text),
        ),
        "section_title": ParagraphStyle(
            "section_title",
            parent=base,
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            spaceAfter=2,
            textColor=colors.HexColor(_STYLE.text),
        ),
        "verdict_strip": ParagraphStyle(
            "verdict_strip",
            parent=base,
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor(_STYLE.text),
        ),
        "body": ParagraphStyle(
            "body",
            parent=base,
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor(_STYLE.text),
        ),
        "body_muted": ParagraphStyle(
            "body_muted",
            parent=base,
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor(_STYLE.text_muted),
        ),
        "note": ParagraphStyle(
            "note",
            parent=base,
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=11,
            spaceAfter=2,
            textColor=colors.HexColor(_STYLE.text_muted),
        ),
    }


# ---------------------------------------------------------------------------
# Page footer
# ---------------------------------------------------------------------------
def _paginator_factory(
    bundle: ComplianceBundle,
    app_version: str,
    git_sha: str,
):
    """Build a per-page footer renderer.

    ReportLab calls the returned function on every rendered page
    with ``(canvas, doc)``; we draw a single centered line with
    project + page count + build SHA so an auditor can match a
    PDF back to an exact build.
    """

    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor(_STYLE.text_muted))
        page_w, _h = A4
        line = f"{bundle.project_name}  ·  page {doc.page}  ·  MagnaDesign {app_version}"
        if git_sha:
            line += f"  ·  build {git_sha[:7]}"
        canvas.drawCentredString(page_w / 2, 12 * mm, line)
        canvas.restoreState()

    return _draw
