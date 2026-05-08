"""Compliance tab — regulatory checks per topology + region.

Mounts inside :class:`ProjetoPage` between "Worst-case" and
"Export". The user picks a region + edition, hits Evaluate,
and the dispatcher in :mod:`pfc_inductor.compliance` runs every
applicable standard. Each result lands in its own card with a
colour-coded verdict strip; an "Export PDF" action turns the
on-screen layout into the auditor-ready PDF
:func:`pfc_inductor.compliance.pdf_writer.write_compliance_pdf`
produces.

UI shape
--------

::

    Region: [Worldwide ▼]   Edition: [5.0 ▼]   [ Evaluate ]   [ Export PDF ]

    Overall: ✓ PASS

    ┌── IEC 61000-3-2 (Edition 5.0) ────────────────────────┐
    │ ✓ PASS — worst margin 18.4 % at h=5.                  │
    │                                                       │
    │  Order   Measured   Limit    Margin    Result         │
    │  n = 3   2018 mA    1585 mA  -27.3 %   ✗ FAIL         │
    │  …                                                    │
    └───────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.compliance import (
    ComplianceBundle,
    StandardResult,
    evaluate,
)
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import Card


# ---------------------------------------------------------------------------
# Worker — runs the dispatcher off the GUI thread
# ---------------------------------------------------------------------------
@dataclass
class _DesignContext:
    spec: Spec
    core: Core
    wire: Wire
    material: Material
    result: DesignResult


class _ComplianceWorker(QObject):
    done = Signal(object)  # ComplianceBundle
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        ctx: _DesignContext,
        project_name: str,
        region: str,
        edition: str,
    ) -> None:
        super().__init__()
        self._ctx = ctx
        self._project_name = project_name
        self._region = region
        self._edition = edition

    def run(self) -> None:
        try:
            bundle = evaluate(
                self._ctx.spec,
                self._ctx.core,
                self._ctx.wire,
                self._ctx.material,
                self._ctx.result,
                project_name=self._project_name,
                region=self._region,  # type: ignore[arg-type]
                edition=self._edition,  # type: ignore[arg-type]
            )
            self.done.emit(bundle)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


# ---------------------------------------------------------------------------
# Verdict strip — small reusable widget
# ---------------------------------------------------------------------------
class _VerdictStrip(QFrame):
    """One-line band with the verdict label coloured per state."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ComplianceVerdictStrip")
        self.setFrameShape(QFrame.Shape.NoFrame)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(8)

        self._marker = QLabel("•")
        self._marker.setObjectName("ComplianceVerdictMarker")
        self._label = QLabel("—")
        self._label.setObjectName("ComplianceVerdictLabel")
        self._label.setWordWrap(True)
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        h.addWidget(self._marker)
        h.addWidget(self._label, 1)
        self._refresh("NOT APPLICABLE", "")

    def show_verdict(self, conclusion: str, summary: str) -> None:
        self._refresh(conclusion, summary)

    def _refresh(self, conclusion: str, summary: str) -> None:
        p = get_theme().palette
        t = get_theme().type
        color = {
            "PASS": p.success,
            "MARGINAL": p.warning,
            "FAIL": p.danger,
            "NOT APPLICABLE": p.text_muted,
        }.get(conclusion, p.text_muted)
        marker = {
            "PASS": "✓",
            "MARGINAL": "~",
            "FAIL": "✗",
        }.get(conclusion, "•")
        self._marker.setText(marker)
        self._marker.setStyleSheet(
            f"color: {color}; font-weight: {t.semibold};font-size: {t.title_md}px;"
        )
        text = f"{conclusion}"
        if summary:
            text += f" — {summary}"
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {p.text}; font-size: {t.body_md}px;")
        # Background uses the existing ``surface`` token; the
        # verdict colour lives on the marker + the left border so
        # we don't have to invent new pass/warn/fail subtle-bg
        # tokens. Same effect, fewer palette entries.
        r = get_theme().radius
        border_left = (
            f"  border-left: 4px solid {color};"
            if conclusion in ("PASS", "MARGINAL", "FAIL")
            else ""
        )
        self.setStyleSheet(
            f"QFrame#ComplianceVerdictStrip {{"
            f"  background: {p.surface};"
            f"  border: 1px solid {p.border};"
            f"{border_left}"
            f"  border-radius: {r.button}px;"
            f"}}"
        )


# ---------------------------------------------------------------------------
# Per-standard card body
# ---------------------------------------------------------------------------
class _StandardCardBody(QFrame):
    """Verdict strip + harmonic table + notes for one standard."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.verdict = _VerdictStrip()
        v.addWidget(self.verdict)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Order", "Measured", "Limit", "Margin", "Result"],
        )
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers,
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection,
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(140)
        h = self.table.horizontalHeader()
        for col in range(5):
            h.setSectionResizeMode(
                col,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        v.addWidget(self.table)

        self.notes = QLabel("")
        self.notes.setProperty("role", "muted")
        self.notes.setWordWrap(True)
        v.addWidget(self.notes)

    def populate(self, std: StandardResult) -> None:
        self.verdict.show_verdict(std.conclusion, std.summary)
        self.table.setRowCount(len(std.rows))
        for r, (label, value, limit, margin, passed) in enumerate(std.rows):
            self.table.setItem(r, 0, QTableWidgetItem(label))
            self.table.setItem(r, 1, QTableWidgetItem(value))
            self.table.setItem(r, 2, QTableWidgetItem(limit))
            self.table.setItem(r, 3, QTableWidgetItem(f"{margin:+.1f} %"))
            mark = QTableWidgetItem("PASS" if passed else "FAIL")
            mark.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setForeground(
                Qt.GlobalColor.darkGreen if passed else Qt.GlobalColor.darkRed,
            )
            self.table.setItem(r, 4, mark)
        if std.notes:
            self.notes.setText("\n".join(f"• {n}" for n in std.notes))
        else:
            self.notes.setText("")
        # Hide table when there are no rows — keeps the boost-PFC
        # "trivially compliant" path looking clean.
        self.table.setVisible(bool(std.rows))


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------
class ComplianceTab(QWidget):
    """Tab body — controls + overall verdict + per-standard cards."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._ctx: Optional[_DesignContext] = None
        self._project_name: str = "Untitled Project"
        self._bundle: Optional[ComplianceBundle] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ComplianceWorker] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        # ---- Controls row ------------------------------------------------
        controls = QFrame()
        ch = QHBoxLayout(controls)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(10)

        ch.addWidget(QLabel("Region:"))
        self._cmb_region = QComboBox()
        for tag in ("Worldwide", "EU", "BR", "US"):
            self._cmb_region.addItem(tag, tag)
        self._cmb_region.setMinimumWidth(110)
        ch.addWidget(self._cmb_region)

        ch.addSpacing(20)
        ch.addWidget(QLabel("IEC 61000-3-2 edition:"))
        self._cmb_edition = QComboBox()
        for ed in ("5.0", "4.0"):
            self._cmb_edition.addItem(ed, ed)
        ch.addWidget(self._cmb_edition)

        ch.addStretch(1)

        self._btn_evaluate = QPushButton("Evaluate")
        self._btn_evaluate.setProperty("class", "Primary")
        self._btn_evaluate.clicked.connect(self._launch)
        ch.addWidget(self._btn_evaluate)

        self._btn_pdf = QPushButton("Export PDF…")
        self._btn_pdf.setEnabled(False)
        self._btn_pdf.clicked.connect(self._export_pdf)
        ch.addWidget(self._btn_pdf)

        outer.addWidget(controls)

        # ---- Status / overall verdict -----------------------------------
        self._overall = _VerdictStrip()
        outer.addWidget(self._overall)

        self._status = QLabel(
            "Pick region + edition, then Evaluate. The dispatcher "
            "runs every standard the topology triggers — IEC 61000-3-2 "
            "today; UL 1411 / EN 55032 / IEC 60335-1 land in follow-up "
            "commits.",
        )
        self._status.setProperty("role", "muted")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        # ---- Per-standard cards container -------------------------------
        self._cards_holder = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_holder)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        outer.addWidget(self._cards_holder, 1)

        outer.addStretch(0)

        on_theme_changed(self._refresh_qss)
        self._refresh_qss()

    # ------------------------------------------------------------------
    def update_from_design(
        self,
        result: DesignResult,
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
    ) -> None:
        self._ctx = _DesignContext(
            spec=spec,
            core=core,
            wire=wire,
            material=material,
            result=result,
        )
        # Don't auto-run — same rationale as Worst-case tab. The
        # user clicks Evaluate when they're ready to see the
        # snapshot; otherwise every spec keystroke would re-run.
        if self._bundle is None:
            self._status.setText(
                f"Ready · {spec.topology}. Click Evaluate to run the standards dispatcher.",
            )

    def set_project_name(self, name: str) -> None:
        """Host calls this when the WorkflowState's project name
        changes — propagates into the PDF metadata."""
        self._project_name = name or "Untitled Project"

    # ------------------------------------------------------------------
    def _launch(self) -> None:
        if self._ctx is None:
            self._status.setText(
                "Run a design first — the dispatcher needs a "
                "DesignResult to extract the harmonic spectrum from.",
            )
            return
        if self._thread is not None and self._thread.isRunning():
            return

        self._btn_evaluate.setEnabled(False)
        self._btn_pdf.setEnabled(False)
        self._status.setText("Running compliance dispatcher…")

        self._worker = _ComplianceWorker(
            self._ctx,
            project_name=self._project_name,
            region=str(self._cmb_region.currentData() or "Worldwide"),
            edition=str(self._cmb_edition.currentData() or "5.0"),
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_run_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_done(self, bundle: ComplianceBundle) -> None:
        self._bundle = bundle
        self._render_bundle(bundle)
        # PDF export is enabled when there's *anything* to write
        # — even a "no applicable standards" bundle still produces
        # a useful cover-page artefact for the audit trail.
        self._btn_pdf.setEnabled(True)
        self._status.setText(
            f"Evaluated {len(bundle.standards)} standard(s) for region = {bundle.region}.",
        )

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"Compliance run failed: {message}")

    def _on_run_finished(self) -> None:
        self._btn_evaluate.setEnabled(True)

    # ------------------------------------------------------------------
    def _render_bundle(self, bundle: ComplianceBundle) -> None:
        """Replace the per-standard card stack with fresh widgets."""
        # Clear existing cards.
        while self._cards_layout.count() > 0:
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        overall_summary = ""
        if not bundle.standards:
            overall_summary = (
                "No applicable standards for this topology / region. "
                "The compliance pass is a no-op for this design."
            )
        self._overall.show_verdict(bundle.overall, overall_summary)

        for std in bundle.standards:
            body = _StandardCardBody()
            body.populate(std)
            card = Card(
                f"{std.standard} — {std.edition}",
                body,
            )
            self._cards_layout.addWidget(card)

    # ------------------------------------------------------------------
    def _export_pdf(self) -> None:
        if self._bundle is None:
            return
        # File-dialog title carries the project + verdict so the
        # default filename suggestion ("Compliance — <project>")
        # makes sense.
        suggested = f"compliance_{self._project_name}.pdf".replace(" ", "_").replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export compliance report",
            suggested,
            "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            from importlib.metadata import version as _version

            try:
                app_version = _version("magnadesign")
            except Exception:
                app_version = ""
            from pfc_inductor.compliance.pdf_writer import (
                write_compliance_pdf,
            )

            out = write_compliance_pdf(
                self._bundle,
                path,
                app_version=app_version,
            )
        except Exception as exc:
            self._status.setText(f"PDF export failed: {exc}")
            return
        self._status.setText(f"PDF saved to {out}")

    # ------------------------------------------------------------------
    def _refresh_qss(self) -> None:
        # No persistent styling beyond what the verdict strip
        # repaints itself; placeholder for future polish hooks.
        pass
