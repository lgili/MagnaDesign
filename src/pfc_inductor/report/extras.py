"""Optional datasheet sections — modulation envelope + worst-case.

These flowable factories produce the per-page content for the
two opt-in datasheet sections proposed in
``add-vfd-modulation-workflow`` (Phase 7) and
``add-worst-case-tolerance-doe`` (Phase 6). They live in a
separate module from ``pdf_report.py`` so the main datasheet
generator + the new sections evolve independently — both can
import the shared style helpers without coupling their layout
decisions.

Usage from the main report
--------------------------

The primary ``generate_pdf_datasheet`` orchestrator builds a
``story`` list and hands it to ``SimpleDocTemplate``. To add
the new sections it imports + calls these factories with the
already-resolved engine + worst-case payloads:

.. code-block:: python

    from pfc_inductor.report.extras import (
        modulation_envelope_flowables,
        worst_case_envelope_flowables,
    )

    if banded is not None:
        story.extend(modulation_envelope_flowables(banded, styles))
    if wc_summary is not None:
        story.extend(worst_case_envelope_flowables(
            wc_summary, yield_report, styles,
        ))

The factories return ``list[Flowable]`` so the host's existing
``story`` flow stays linear.

Why separate module
-------------------

``pdf_report.py`` is being heavily edited (typography, Inter
font registration, native PDF datasheet) by the parallel
agent. Splitting these new sections into a sibling module
avoids merge churn and keeps each surface independently
testable.
"""
from __future__ import annotations

import io
import math
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from pfc_inductor.models.banded_result import BandedDesignResult
from pfc_inductor.worst_case import WorstCaseSummary, YieldReport


# ---------------------------------------------------------------------------
# Shared visual constants — kept ASCII so this module stays
# free of theme dependencies.
# ---------------------------------------------------------------------------
_BORDER = "#D4D4D8"
_TEXT = "#18181B"
_TEXT_MUTED = "#52525B"
_BAND_BG = "#F4F4F5"
_PASS = "#15803D"
_WARN = "#A16207"
_FAIL = "#B91C1C"
_ACCENT = "#A78BFA"


def _fallback_style(
    name: str, *, size: float = 9, leading: float = 13, bold: bool = False,
) -> ParagraphStyle:
    """Build a safe ParagraphStyle when the host's style dict
    doesn't have the requested key. Lets the factories work
    even when called with a minimal style sheet."""
    return ParagraphStyle(
        name,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=leading,
        textColor=colors.HexColor(_TEXT),
    )


def _style(styles: Optional[dict[str, ParagraphStyle]], key: str,
           **fallback: Any) -> ParagraphStyle:
    if styles and key in styles:
        return styles[key]
    return _fallback_style(key, **fallback)


# ---------------------------------------------------------------------------
# Modulation envelope page
# ---------------------------------------------------------------------------
def modulation_envelope_flowables(
    banded: BandedDesignResult,
    styles: Optional[dict[str, ParagraphStyle]] = None,
) -> list:
    """Return the flowables for the "Modulation envelope" page.

    Three small line charts (P_total / B_pk / ΔT) vs. fsw
    rendered as a single matplotlib figure → embedded as a
    flowable Image. Plus a small worst-case summary table
    showing which fsw drove each metric to its peak.

    Returns an empty list when the band has no successful
    points — keeps the host's story append-loop branch-free
    (``story.extend(modulation_envelope_flowables(...))``
    is always safe).
    """
    if not banded.band:
        return []

    successful = [bp for bp in banded.band if bp.result is not None]
    if not successful:
        return []

    flow: list = []
    flow.append(PageBreak())

    flow.append(Paragraph(
        "Modulation envelope (fsw band)",
        _style(styles, "h2", size=16, leading=20, bold=True),
    ))

    spec = banded.spec
    profile_text = (
        spec.fsw_modulation.profile if spec.fsw_modulation else "—"
    )
    band_lo = successful[0].fsw_kHz
    band_hi = successful[-1].fsw_kHz
    flow.append(Paragraph(
        f"Band: <b>{band_lo:.1f} → {band_hi:.1f} kHz</b>  ·  "
        f"{len(banded.band)} points  ·  "
        f"profile = <b>{profile_text}</b>",
        _style(styles, "body", size=9, leading=13),
    ))
    flow.append(Spacer(1, 4 * mm))

    flow.append(_render_band_chart(banded))
    flow.append(Spacer(1, 4 * mm))

    # Worst-case summary table.
    rows = [["Metric", "Worst value", "Worst fsw", "Margin"]]
    for metric, label, fmt in (
        ("T_winding_C", "T winding", "{:.1f} °C"),
        ("B_pk_T",      "B peak",    "{:.0f} mT"),
        ("P_total_W",   "Losses",    "{:.2f} W"),
        ("T_rise_C",    "ΔT rise",   "{:.1f} °C"),
    ):
        bp = banded.worst(metric)
        if bp is None or bp.result is None:
            continue
        value = _read_metric(bp.result, metric)
        if value is None:
            continue
        if metric == "B_pk_T":
            value_text = fmt.format(value * 1000)
        else:
            value_text = fmt.format(value)
        rows.append([
            label, value_text, f"{bp.fsw_kHz:.1f} kHz", "—",
        ])

    if len(rows) > 1:
        table = Table(rows, colWidths=[40 * mm, 35 * mm, 30 * mm, 25 * mm])
        table.setStyle(TableStyle([
            ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("FONTNAME",   (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0),  colors.HexColor(_BAND_BG)),
            ("BOX",        (0, 0), (-1, -1), 0.5, colors.HexColor(_BORDER)),
            ("INNERGRID",  (0, 0), (-1, -1), 0.25, colors.HexColor(_BORDER)),
            ("ALIGN",      (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        flow.append(table)

    if banded.flagged_points:
        flow.append(Spacer(1, 3 * mm))
        flow.append(Paragraph(
            f"<b>{len(banded.flagged_points)} band point(s) failed</b> — "
            f"the engine raised at one or more fsw values. The "
            f"worst-case table above ignores those points.",
            _style(styles, "note", size=8, leading=11),
        ))
    return flow


def _render_band_chart(banded: BandedDesignResult) -> RLImage:
    fig, axes = plt.subplots(1, 3, figsize=(7.5, 2.4), dpi=150)
    metrics = (
        ("P_total_W",  "Total losses [W]",      1.0),
        ("B_pk_T",     "B peak [mT]",           1000.0),
        ("T_rise_C",   "ΔT rise [°C]",          1.0),
    )
    for ax, (key, title, scale) in zip(axes, metrics, strict=True):
        xs: list[float] = []
        ys: list[float] = []
        for bp in banded.band:
            if bp.result is None:
                continue
            v = _read_metric(bp.result, key)
            if v is None:
                continue
            xs.append(bp.fsw_kHz)
            ys.append(v * scale)
        if xs:
            ax.plot(xs, ys, "-o", color=_ACCENT, linewidth=1.4,
                    markersize=4)
            worst = banded.worst(key)
            if worst is not None and worst.result is not None:
                wv = _read_metric(worst.result, key)
                if wv is not None:
                    ax.scatter([worst.fsw_kHz], [wv * scale],
                               color=_FAIL, s=50, zorder=5,
                               edgecolor="white", linewidth=0.6)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("fsw [kHz]", fontsize=8)
        ax.tick_params(axis="both", labelsize=7)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        ax.grid(True, color=_BORDER, linewidth=0.4, alpha=0.6)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return RLImage(buf, width=170 * mm, height=58 * mm)


# ---------------------------------------------------------------------------
# Worst-case envelope page
# ---------------------------------------------------------------------------
def worst_case_envelope_flowables(
    summary: WorstCaseSummary,
    yield_report: Optional[YieldReport] = None,
    styles: Optional[dict[str, ParagraphStyle]] = None,
) -> list:
    """Return flowables for the "Production worst-case envelope"
    page. Carries:

    - Headline corner count + engine-failure count.
    - Per-metric worst-case table (T_winding / B_pk / P_total /
      T_rise) with the corner label that drove each peak.
    - Yield estimate (when provided): pass-rate + bucketed
      fail modes.

    Empty corner list → empty flowable list (host's
    ``story.extend`` stays branch-free)."""
    if summary.n_corners_evaluated == 0:
        return []

    flow: list = []
    flow.append(PageBreak())

    flow.append(Paragraph(
        "Production worst-case envelope",
        _style(styles, "h2", size=16, leading=20, bold=True),
    ))
    flow.append(Paragraph(
        f"<b>{summary.n_corners_evaluated} corners</b> evaluated · "
        f"{summary.n_corners_failed} engine failure(s).",
        _style(styles, "body", size=9, leading=13),
    ))
    flow.append(Spacer(1, 4 * mm))

    # Per-metric worst case.
    metric_rows = [["Metric", "Worst value", "Driving corner"]]
    for metric, label, fmt in (
        ("T_winding_C", "T winding (worst)", "{:.1f} °C"),
        ("B_pk_T",      "B peak (worst)",    "{:.0f} mT"),
        ("P_total_W",   "Total losses",      "{:.2f} W"),
        ("T_rise_C",    "ΔT rise (worst)",   "{:.1f} °C"),
    ):
        cr = summary.worst_per_metric.get(metric)
        if cr is None or cr.result is None:
            continue
        value = _read_metric(cr.result, metric)
        if value is None:
            continue
        if metric == "B_pk_T":
            value_text = fmt.format(value * 1000)
        else:
            value_text = fmt.format(value)
        metric_rows.append([label, value_text, cr.label])

    if len(metric_rows) > 1:
        table = Table(metric_rows, colWidths=[55 * mm, 40 * mm, 75 * mm])
        table.setStyle(TableStyle([
            ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("FONTNAME",   (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0),  colors.HexColor(_BAND_BG)),
            ("BOX",        (0, 0), (-1, -1), 0.5, colors.HexColor(_BORDER)),
            ("INNERGRID",  (0, 0), (-1, -1), 0.25, colors.HexColor(_BORDER)),
            ("ALIGN",      (1, 1), (1, -1), "RIGHT"),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ]))
        flow.append(table)

    if yield_report is not None:
        flow.append(Spacer(1, 6 * mm))
        flow.append(Paragraph(
            "Yield estimate (Monte-Carlo)",
            _style(styles, "h3", size=12, leading=16, bold=True),
        ))
        rate = yield_report.pass_rate * 100.0
        color = _PASS if rate >= 95 else _WARN if rate >= 90 else _FAIL
        flow.append(Paragraph(
            f"<font color='{color}' size='14'><b>{rate:.2f} %</b></font>"
            f" pass-rate over <b>{yield_report.n_samples:,}</b> samples "
            f"(seed-reproducible). "
            f"{yield_report.n_engine_error} engine errors.",
            _style(styles, "body", size=10, leading=14),
        ))

        if yield_report.fail_modes:
            flow.append(Spacer(1, 2 * mm))
            modes = ", ".join(
                f"{mode} ({count})"
                for mode, count in
                sorted(yield_report.fail_modes.items(),
                       key=lambda kv: -kv[1])[:5]
            )
            flow.append(Paragraph(
                f"<b>Top fail modes:</b> {modes}",
                _style(styles, "note", size=9, leading=13),
            ))

    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(
        "Production-tolerance corners drawn from the bundled "
        "IPC + IEC + vendor default set — see "
        "<i>validation/thresholds.yaml</i> for the per-metric "
        "tolerance bands. Auditor-friendly: cite this page in "
        "the design dossier when responding to ISO 9001 / "
        "IATF 16949 / IEC 60335 review questions.",
        _style(styles, "note", size=8, leading=11),
    ))
    return flow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _read_metric(result: Any, metric: str) -> Optional[float]:
    """Pull a numeric metric off a DesignResult. Mirrors the
    helper inside ``worst_case.engine`` but kept private here so
    the report module doesn't import the worst-case package's
    internals."""
    v = getattr(result, metric, None)
    if v is None and hasattr(result, "losses"):
        v = getattr(result.losses, metric, None)
    if not isinstance(v, (int, float)):
        return None
    if not math.isfinite(v):
        return None
    return float(v)
