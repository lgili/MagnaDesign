"""FEA validation dialog: runs FEM cross-check on the active design.

Prefers the FEMMT (Python+ONELAB) backend; falls back to legacy FEMM/xfemm
when only that is installed. Gracefully degrades to a disabled run button
with install instructions when no backend is detected.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from pfc_inductor.fea import (
    FEAValidation,
    FEMMNotAvailable,
    FEMMSolveError,
    active_backend,
    backend_fidelity,
    femm_version,
    femmt_version,
    find_femm_binary,
    install_hint,
    is_femm_available,
    select_backend_for_shape,
    validate_design,
)
from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.visual import infer_shape


class _ValidationWorker(QObject):
    finished = Signal(object)  # FEAValidation or None on error
    failed = Signal(str)

    def __init__(self, spec, core, wire, material, result):
        super().__init__()
        self.spec = spec
        self.core = core
        self.wire = wire
        self.material = material
        self.result = result

    def run(self):
        try:
            v = validate_design(
                self.spec, self.core, self.wire, self.material, self.result,
            )
            self.finished.emit(v)
        except FEMMNotAvailable as e:
            self.failed.emit(f"FEA backend unavailable: {e}")
        except FEMMSolveError as e:
            self.failed.emit(f"Solver failed:\n{e}")
        except Exception as e:
            self.failed.emit(f"Unexpected error: {type(e).__name__}: {e}")


class FEAValidationDialog(QDialog):
    """Modal dialog that runs (or explains how to run) FEA validation."""

    def __init__(
        self,
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
        result: DesignResult,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("FEA validation")
        self.resize(1000, 720)
        self._spec = spec
        self._core = core
        self._wire = wire
        self._material = material
        self._result = result
        self._thread: Optional[QThread] = None

        outer = QVBoxLayout(self)
        outer.addWidget(self._build_header())
        outer.addWidget(self._build_target_box())
        outer.addWidget(self._build_results_box(), 1)
        outer.addLayout(self._build_buttons())

        self._on_initial_state()

    def _build_header(self) -> QGroupBox:
        box = QGroupBox("FEA BACKEND STATUS")
        h = QHBoxLayout(box)
        self.lbl_status = QLabel("...")
        self.lbl_status.setWordWrap(True)
        h.addWidget(self.lbl_status, 1)
        return box

    def _build_target_box(self) -> QGroupBox:
        box = QGroupBox("Target design")
        v = QVBoxLayout(box)
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        lbl = QLabel(self._format_target())
        lbl.setFont(f)
        v.addWidget(lbl)
        return box

    def _format_target(self) -> str:
        return (
            f"{self._material.vendor} — {self._material.name}  +  "
            f"{self._core.vendor} — {self._core.part_number} ({self._core.shape})\n"
            f"N = {self._result.N_turns}   I_pk = {self._result.I_line_pk_A:.2f} A   "
            f"L_analytic = {self._result.L_actual_uH:.0f} µH   "
            f"B_pk_analytic = {self._result.B_pk_T*1000:.0f} mT"
        )

    def _build_results_box(self) -> QGroupBox:
        box = QGroupBox("Validation result")
        v = QVBoxLayout(box)
        form = QFormLayout()
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")

        self.l_L = QLabel("—")
        self.l_L.setFont(f)
        self.l_B = QLabel("—")
        self.l_B.setFont(f)
        self.l_solve = QLabel("—")
        self.l_solve.setFont(f)
        self.l_confidence = QLabel("—")

        form.addRow("Inductance (FEA vs analytic):", self.l_L)
        form.addRow("Peak B (FEA vs analytic):", self.l_B)
        form.addRow("Solve time:", self.l_solve)
        form.addRow("Confidence:", self.l_confidence)
        v.addLayout(form)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.hide()
        v.addWidget(self.progress)

        v.addWidget(QLabel("<b>Log:</b>"))
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(2000)
        f2 = QFont()
        f2.setStyleHint(QFont.StyleHint.Monospace)
        f2.setFamily("Menlo")
        f2.setPointSize(10)
        self.txt_log.setFont(f2)
        v.addWidget(self.txt_log, 1)
        return box

    def _build_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_run = QPushButton("Validate with FEA")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.btn_run.clicked.connect(self._run)
        h.addWidget(self.btn_run)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_close)
        return h

    def _on_initial_state(self):
        from pfc_inductor.fea.probe import is_femmt_onelab_configured
        p = get_theme().palette
        shape = infer_shape(self._core)
        chosen = select_backend_for_shape(shape)
        fidelity = backend_fidelity(shape, chosen)

        if chosen == "femmt":
            ver = femmt_version() or "?"
            if not is_femmt_onelab_configured():
                self.lbl_status.setText(
                    f'<span style="color:{p.warning}">●</span> '
                    f'<b>FEMMT</b> {ver} importable, but <b>ONELAB is not '
                    f'yet configured</b>.<br>'
                    f'<i>See <code>docs/fea-install.md</code> for setup '
                    f'(<code>~/onelab</code> + <code>config.json</code>).</i>'
                )
                self.btn_run.setEnabled(False)
                return
            if fidelity == "high":
                self.lbl_status.setText(
                    f'<span style="color:{p.success}">●</span> '
                    f'<b>FEMMT</b> {ver} — native geometry for '
                    f'<b>{shape.upper()}</b> (high fidelity)'
                )
            else:
                hint = ""
                if not is_femm_available():
                    hint = (
                        '<br><i>For high-fidelity toroid, install legacy FEMM '
                        'and the app uses it automatically '
                        '(<code>brew install xfemm</code> or Wine).</i>'
                    )
                self.lbl_status.setText(
                    f'<span style="color:{p.warning}">●</span> '
                    f'<b>FEMMT</b> {ver} — toroid via PQ-equivalent '
                    f'(<i>approximate</i>, typical 1.5–6× divergence){hint}'
                )
            self.btn_run.setEnabled(True)
            return

        if chosen == "femm":
            ver = femm_version()
            extra = (
                ' — native axisymmetric (high fidelity)'
                if fidelity == "high" else ' (approximate fidelity)'
            )
            color = p.success if fidelity == "high" else p.warning
            self.lbl_status.setText(
                f'<span style="color:{color}">●</span> '
                f'<b>FEMM</b> em <code>{find_femm_binary()}</code>'
                + (f' ({ver})' if ver else '')
                + extra
            )
            self.btn_run.setEnabled(True)
            return

        self.lbl_status.setText(
            f'<span style="color:{p.danger}">●</span> No FEA backend available for '
            f'shape <b>{shape.upper()}</b>.<br>'
            f'<i>{install_hint()}</i>'
        )
        self.btn_run.setEnabled(False)

    def _run(self):
        if self._thread is not None and self._thread.isRunning():
            return
        self.btn_run.setEnabled(False)
        self.progress.show()
        self.txt_log.clear()
        backend = active_backend()
        if backend == "femmt":
            self.txt_log.appendPlainText("Building FEMMT problem (axisymmetric)...")
        else:
            self.txt_log.appendPlainText("Building geometry and Lua script (legacy FEMM)...")

        self._worker = _ValidationWorker(
            self._spec, self._core, self._wire, self._material, self._result,
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_finished(self, v: FEAValidation):
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self._show_validation(v)

    def _on_failed(self, msg: str):
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self.txt_log.appendPlainText(f"\nERROR: {msg}")
        QMessageBox.warning(self, "Validation failed", msg)

    def _show_validation(self, v: FEAValidation):
        pal = get_theme().palette
        self.l_L.setText(
            f"{v.L_FEA_uH:8.1f} µH  vs  {v.L_analytic_uH:.1f} µH    "
            f"({self._color_pct(v.L_pct_error)})"
        )
        self.l_B.setText(
            f"{v.B_pk_FEA_T*1000:6.0f} mT vs  {v.B_pk_analytic_T*1000:.0f} mT    "
            f"({self._color_pct(v.B_pct_error)})"
        )
        self.l_solve.setText(f"{v.solve_time_s:.1f} s  ({v.femm_binary})")
        color = {"high": pal.success, "medium": pal.warning,
                 "low": pal.danger}[v.confidence]
        self.l_confidence.setText(
            f'<span style="color:{color};font-weight:bold">{v.confidence}</span>'
        )
        self.txt_log.appendPlainText("\nResults:")
        self.txt_log.appendPlainText(f"  fem: {v.fem_path}")
        self.txt_log.appendPlainText(f"  flux linkage: {v.flux_linkage_FEA_Wb:.6e} Wb")
        self.txt_log.appendPlainText(f"  test current: {v.test_current_A:.3f} A")
        if v.log_excerpt:
            self.txt_log.appendPlainText("\nSolver log:")
            self.txt_log.appendPlainText(v.log_excerpt)
        if v.notes:
            self.txt_log.appendPlainText(f"\nNotes: {v.notes}")

    @staticmethod
    def _color_pct(p: float) -> str:
        # Reads palette at call time so light↔dark transitions reflect
        # in any subsequent re-render of the validation table.
        pal = get_theme().palette
        sign = "+" if p >= 0 else ""
        ap = abs(p)
        color = pal.success if ap <= 5 else pal.warning if ap <= 15 else pal.danger
        return f'<span style="color:{color}">{sign}{p:.1f}%</span>'
