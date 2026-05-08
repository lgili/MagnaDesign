"""Export tab — datasheet preview + export CTAs."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.icons import icon as ui_icon
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets import Card


class ExportarTab(QWidget):
    """Export workspace tab."""

    export_html_requested = Signal()
    # Native PDF datasheet (ReportLab + matplotlib). Emitted by the
    # secondary "Generate datasheet (PDF)" button alongside the HTML
    # CTA — same content, different file format. See
    # ``pfc_inductor.report.pdf_report`` for the layout.
    export_pdf_requested = Signal()
    # Engineering project report (PDF) — full theory + derivation
    # walkthrough per topology. Emitted by the dedicated CTA on the
    # second card. See ``pfc_inductor.report.pdf_project``.
    export_project_pdf_requested = Signal()
    export_compare_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        intro = QLabel(
            "Three deliverables. The <b>Datasheet</b> is the customer-"
            "facing summary (specs / BOM / FAT plan). The "
            "<b>Project report</b> walks the design derivation — "
            "theory, equations, substituted values, computed result "
            "— so the project can be filed in an engineering "
            "tracking system. The <b>Comparison</b> exports the "
            "side-by-side matrix in PDF, HTML or CSV."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        outer.addWidget(self._build_datasheet_card())
        outer.addWidget(self._build_project_report_card())
        outer.addWidget(self._build_compare_export_card())
        outer.addStretch(1)

        self._last_summary: Optional[str] = None

    # ------------------------------------------------------------------
    def update_from_design(
        self, result: DesignResult, spec: Spec, core: Core, wire: Wire, material: Material
    ) -> None:
        self._summary.setText(
            f"{material.name} · {core.part_number or core.id} · "
            f"L = {result.L_actual_uH:.0f} µH · "
            f"P = {result.losses.P_total_W:.2f} W"
        )

    def clear(self) -> None:
        self._summary.setText("Waiting for calculation…")

    # ------------------------------------------------------------------
    def _build_datasheet_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        # Two formats, same content. PDF is the print/customer artefact
        # (vector text, embedded fonts, deterministic page breaks);
        # HTML is the live screen-grade preview (Slack-pastable, opens
        # in a browser without a reader). The user picks per-recipient.
        desc = QLabel(
            "Manufacturer-grade datasheet — 3 pages, customer-ready. "
            "PDF is the print/shop-floor artefact (vector text, "
            "embedded Inter font, deterministic page breaks). HTML is "
            "the screen-grade preview (open in any browser, paste-able "
            "into Slack).",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)

        self._summary = QLabel("Waiting for calculation…")
        self._summary.setStyleSheet(self._summary_qss())

        # PDF button is "Primary" because it's what most engineers want
        # to ship; HTML stays as the secondary preview path.
        pdf_btn = QPushButton("Generate datasheet (PDF)")
        pdf_btn.setProperty("class", "Primary")
        pdf_btn.setIcon(ui_icon("file-text", color=get_theme().palette.text_inverse, size=14))
        pdf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pdf_btn.clicked.connect(self.export_pdf_requested.emit)

        html_btn = QPushButton("Generate datasheet (HTML)")
        html_btn.setProperty("class", "Secondary")
        html_btn.setIcon(ui_icon("file-text", color=get_theme().palette.text, size=14))
        html_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        html_btn.clicked.connect(self.export_html_requested.emit)

        row = QHBoxLayout()
        row.addWidget(pdf_btn)
        row.addWidget(html_btn)
        row.addStretch(1)

        v.addWidget(desc)
        v.addWidget(self._summary)
        v.addLayout(row)
        return Card("Design datasheet", body)

    def _build_project_report_card(self) -> Card:
        """Engineering project report — the *how it was derived*
        artefact engineers need to file a design in their internal
        project tracking systems."""
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Engineering report tailored to the topology — theory "
            "paragraphs, the design equations symbolically, the "
            "same equations with the project's values substituted, "
            "and the calculated result. As if a senior engineer "
            "(rather than the tool) had walked the calculation "
            "by hand and written it up. Use it for design "
            "review, project filing, or hand-off to a junior "
            "engineer learning the topology."
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)

        btn = QPushButton("Generate project report (PDF)")
        btn.setProperty("class", "Primary")
        btn.setIcon(ui_icon("file-text", color=get_theme().palette.text_inverse, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.export_project_pdf_requested.emit)

        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)

        v.addWidget(desc)
        v.addLayout(row)
        return Card("Engineering project report", body)

    def _build_compare_export_card(self) -> Card:
        body = QFrame()
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        desc = QLabel(
            "Exports the current comparison matrix (up to 4 designs) "
            "as self-contained HTML or CSV.",
        )
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        btn = QPushButton("Export comparison")
        btn.setProperty("class", "Secondary")
        btn.setIcon(ui_icon("compare", color=get_theme().palette.text, size=14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.export_compare_requested.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        v.addWidget(desc)
        v.addLayout(row)
        return Card("Comparison (HTML/CSV)", body)

    @staticmethod
    def _summary_qss() -> str:
        p = get_theme().palette
        t = get_theme().type
        return (
            f"color: {p.text}; font-family: {t.numeric_family};"
            f" font-size: {t.body_md}px; padding: 8px 0;"
        )
