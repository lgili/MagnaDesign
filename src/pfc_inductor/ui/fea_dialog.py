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
    QTabWidget,
    QVBoxLayout,
    QWidget,
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
        import traceback

        try:
            v = validate_design(
                self.spec,
                self.core,
                self.wire,
                self.material,
                self.result,
            )
            self.finished.emit(v)
        except FEMMNotAvailable as e:
            self.failed.emit(f"FEA backend unavailable: {e}")
        except FEMMSolveError as e:
            self.failed.emit(f"Solver failed:\n{e}")
        except Exception as e:
            # Capture the bottom of the traceback so future bug reports
            # don't lose the file:line that raised. A generic
            # "TypeError: ... 'NoneType'" without context is the most
            # frustrating thing the user can see — and it's exactly the
            # shape of error FEMMT raises when an ONELAB binary is
            # unresolved at deep call sites.
            tb = traceback.format_exc().splitlines()
            # Last 6 lines is usually enough: the exception line
            # plus the top of the call chain inside our code.
            tail = "\n".join(tb[-6:]) if len(tb) > 6 else "\n".join(tb)
            self.failed.emit(
                f"Unexpected error: {type(e).__name__}: {e}\n\nTraceback (last frames):\n{tail}"
            )


class _SweepWorker(QObject):
    """Worker thread for the Tier-4 swept-FEA evaluation.

    Lives in this module instead of ``optimize.cascade.tier4``
    because it bridges Qt threads to the existing pure-Python
    Tier-4 evaluator — the cascade module shouldn't depend on
    PySide6.
    """

    finished = Signal(object)  # SweptFEAPayload
    failed = Signal(str)

    def __init__(self, spec, core, wire, material, result):
        super().__init__()
        self.spec = spec
        self.core = core
        self.wire = wire
        self.material = material
        self.result = result

    def run(self) -> None:
        import traceback

        try:
            from pfc_inductor.models import Candidate
            from pfc_inductor.optimize.cascade.tier4 import (
                DEFAULT_SWEEP_FRACTIONS,
                evaluate_candidate,
            )
            from pfc_inductor.topology.registry import model_for
            from pfc_inductor.ui.widgets.fea_swept_chart import SweptFEAPayload

            model = model_for(self.spec)
            cand = Candidate(
                core_id=self.core.id,
                material_id=self.material.id,
                wire_id=self.wire.id,
                N=int(self.result.N_turns),
                gap_mm=float(getattr(self.core, "lgap_mm", 0.0) or 0.0),
            )
            t4 = evaluate_candidate(
                model,
                cand,
                self.core,
                self.material,
                self.wire,
                sweep_fractions=DEFAULT_SWEEP_FRACTIONS,
                timeout_s=600,
            )
            if t4 is None:
                self.failed.emit(
                    "Swept FEA returned no result — check the FEA backend "
                    "is configured (Configurações → Setup FEA)."
                )
                return
            # Hot Bsat from material so the chart can draw the
            # warning region. Margin pulls from the spec, default
            # 20 % when the spec field is missing.
            Bsat_T = float(getattr(self.material, "Bsat_100C_T", 0.0) or 0.0)
            margin = float(getattr(self.spec, "Bsat_margin", 0.20) or 0.20)
            payload = SweptFEAPayload.from_tier4(
                t4,
                operating_point_A=float(self.result.I_line_pk_A or 0.0),
                Bsat_T=Bsat_T,
                Bsat_margin=margin,
            )
            self.finished.emit(payload)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc().splitlines()
            tail = "\n".join(tb[-6:]) if len(tb) > 6 else "\n".join(tb)
            self.failed.emit(
                f"Unexpected error: {type(exc).__name__}: {exc}\n\n"
                f"Traceback (last frames):\n{tail}"
            )


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
        # Wider + taller than v3 because the tabbed layout houses
        # 3 chart surfaces (Summary / Field plots / L vs current)
        # + log + progress bar. 1080 × 820 fits all three on a
        # 1366 × 768 laptop without scrolling.
        self.resize(1080, 820)
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

        # Populate the analytical tabs immediately. Geometry +
        # B-H don't depend on a FEA solve; the engineer should be
        # able to scan them as soon as the dialog opens, before
        # ever clicking "Validate".
        self._populate_analytical_tabs()

        self._on_initial_state()

    def _populate_analytical_tabs(self) -> None:
        """Fill the Geometry + B-H tabs from the stored models.

        Both views are pure analytical — no FEA needed — so we
        run this once at dialog construction. Re-runs after a
        successful FEA validation via :meth:`_show_validation`,
        in case the validation produced a refined result with a
        different operating point or N (rare, but cheap to redo).
        """
        from pfc_inductor.ui.widgets.fea_bh_loop import BHLoopPayload
        from pfc_inductor.ui.widgets.fea_geometry_view import GeometryPayload

        try:
            self.geometry_view.show_payload(
                GeometryPayload.from_models(
                    self._core, self._wire, self._result
                )
            )
        except Exception:
            # Defensive — a malformed Core/Wire/Result from a
            # 3rd-party caller shouldn't crash the dialog. The
            # widget just stays in its empty state.
            pass

        try:
            self.bh_chart.show_payload(
                BHLoopPayload.from_models(
                    self._material, self._result, hot=True
                )
            )
        except Exception:
            pass

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
            f"B_pk_analytic = {self._result.B_pk_T * 1000:.0f} mT"
        )

    def _build_results_box(self) -> QGroupBox:
        """Validation result panel — tabbed layout.

        Three surfaces sharing the same payload:

        * **Summary**  — analytic-vs-FEA bars + confidence gauge
          (the existing :class:`FEAValidationChart`) plus the
          form rows with the raw numbers.
        * **Field plots**  — thumbnail grid of PNGs FEMMT
          auto-exports into its working directory
          (:class:`FEAFieldGallery`).
        * **L vs current**  — Tier-4 swept-FEA L(I) + B(I)
          curves with sat-knee detection
          (:class:`SweptFEAChart`).

        The log + progress bar stay below the tabs because they
        track *both* the single-point validation and the swept
        run, so they make sense as a shared bottom surface.

        Lazy imports for the three chart widgets — keeps the
        matplotlib backend out of the dialog's startup path
        when only the form rows are visible.
        """
        from pfc_inductor.ui.widgets.fea_bh_loop import BHLoopChart
        from pfc_inductor.ui.widgets.fea_field_gallery import (
            FEAFieldGallery,
        )
        from pfc_inductor.ui.widgets.fea_geometry_view import GeometryView
        from pfc_inductor.ui.widgets.fea_swept_chart import SweptFEAChart
        from pfc_inductor.ui.widgets.fea_validation_chart import (
            FEAValidationChart,
        )

        box = QGroupBox("Validation result")
        v = QVBoxLayout(box)

        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")

        # ── Summary tab — form + bar chart + gauge ──
        summary_tab = QWidget()
        sv = QVBoxLayout(summary_tab)
        sv.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()
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
        sv.addLayout(form)

        self.chart = FEAValidationChart()
        sv.addWidget(self.chart, 1)

        # ── Geometry tab — datasheet-style cross-section ──
        # Always available (analytical, no FEA needed). Acts as
        # a sanity check that the design landed on the geometry
        # the engineer expected.
        self.geometry_view = GeometryView()

        # ── B-H tab — operating point on the static curve ──
        # Margin to Bsat at a glance; AC trajectory overlay when
        # waveform data is available on the result.
        self.bh_chart = BHLoopChart()

        # ── Field plots tab — FEMMT-auto-exported PNGs ──
        self.gallery = FEAFieldGallery()

        # ── Swept FEA tab — L(I) and B(I) curves ──
        self.swept_chart = SweptFEAChart()

        # Tab container — ordered by "always available first"
        # (Summary, Geometry, B-H) then validation outputs
        # (Field plots, L vs current). Keeps something useful
        # visible even before the user runs FEA.
        self.tabs = QTabWidget()
        self.tabs.addTab(summary_tab, "Summary")
        self.tabs.addTab(self.geometry_view, "Geometry")
        self.tabs.addTab(self.bh_chart, "B-H curve")
        self.tabs.addTab(self.gallery, "Field plots")
        self.tabs.addTab(self.swept_chart, "L vs current")
        v.addWidget(self.tabs, 1)

        # Bottom surfaces shared across all tabs.
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
        # Sweep button — runs the Tier-4 swept-magnetostatic FEA
        # at N bias points across the half-cycle. Same backend
        # the single-point validation uses; just multi-shot.
        # Disabled state mirrors the validate button (FEMMT not
        # configured → both off).
        self.btn_sweep = QPushButton("Run swept FEA")
        self.btn_sweep.setToolTip(
            "Run the Tier-4 swept-magnetostatic FEA at multiple "
            "bias points. Populates the L vs current tab. "
            "Cost: ~N × the single-point solve time."
        )
        self.btn_sweep.clicked.connect(self._run_sweep)
        h.addWidget(self.btn_sweep)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_close)

        # Disable Qt's auto-default button promotion on every
        # action button. Without this, when ``btn_run`` is
        # disabled during a long solve, Qt promotes the next
        # enabled push-button (``btn_sweep``) to "default" — and
        # macOS paints default buttons with the system-blue
        # accent, making it look selected even when the user
        # never touched it. We don't want any button to be the
        # implicit Enter-key target on this dialog (Close-on-
        # Enter is too dangerous mid-solve), so flat is correct.
        for btn in (self.btn_run, self.btn_sweep, self.btn_close):
            btn.setAutoDefault(False)
            btn.setDefault(False)
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
                    f"<b>FEMMT</b> {ver} importable, but <b>ONELAB is not "
                    f"yet configured</b>.<br>"
                    f"<i>See <code>docs/fea-install.md</code> for setup "
                    f"(<code>~/onelab</code> + <code>config.json</code>).</i>"
                )
                self.btn_run.setEnabled(False)
                return
            if fidelity == "high":
                self.lbl_status.setText(
                    f'<span style="color:{p.success}">●</span> '
                    f"<b>FEMMT</b> {ver} — native geometry for "
                    f"<b>{shape.upper()}</b> (high fidelity)"
                )
            else:
                hint = ""
                if not is_femm_available():
                    hint = (
                        "<br><i>For high-fidelity toroid, install legacy FEMM "
                        "and the app uses it automatically "
                        "(<code>brew install xfemm</code> or Wine).</i>"
                    )
                self.lbl_status.setText(
                    f'<span style="color:{p.warning}">●</span> '
                    f"<b>FEMMT</b> {ver} — toroid via PQ-equivalent "
                    f"(<i>approximate</i>, typical 1.5–6× divergence){hint}"
                )
            self.btn_run.setEnabled(True)
            return

        if chosen == "femm":
            ver = femm_version()
            extra = (
                " — native axisymmetric (high fidelity)"
                if fidelity == "high"
                else " (approximate fidelity)"
            )
            color = p.success if fidelity == "high" else p.warning
            self.lbl_status.setText(
                f'<span style="color:{color}">●</span> '
                f"<b>FEMM</b> em <code>{find_femm_binary()}</code>"
                + (f" ({ver})" if ver else "")
                + extra
            )
            self.btn_run.setEnabled(True)
            return

        self.lbl_status.setText(
            f'<span style="color:{p.danger}">●</span> No FEA backend available for '
            f"shape <b>{shape.upper()}</b>.<br>"
            f"<i>{install_hint()}</i>"
        )
        self.btn_run.setEnabled(False)

    def _run(self):
        if self._thread is not None and self._thread.isRunning():
            return
        # Park focus on the log pane before disabling the button.
        # Otherwise Qt auto-shifts focus to the next enabled
        # button in the row (``btn_sweep``), and on macOS the
        # newly-focused button paints with the system blue
        # default-action accent — making it look selected mid-
        # solve. ``btn_close`` would also be a valid park target,
        # but the log is the read-only "where progress shows up"
        # area, so the focus state matches user attention.
        self.txt_log.setFocus()
        self.btn_run.setEnabled(False)
        self.progress.show()
        self.txt_log.clear()
        backend = active_backend()
        if backend == "femmt":
            self.txt_log.appendPlainText("Building FEMMT problem (axisymmetric)...")
        else:
            self.txt_log.appendPlainText("Building geometry and Lua script (legacy FEMM)...")

        self._worker = _ValidationWorker(
            self._spec,
            self._core,
            self._wire,
            self._material,
            self._result,
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
            f"{v.B_pk_FEA_T * 1000:6.0f} mT vs  {v.B_pk_analytic_T * 1000:.0f} mT    "
            f"({self._color_pct(v.B_pct_error)})"
        )
        self.l_solve.setText(f"{v.solve_time_s:.1f} s  ({v.femm_binary})")
        color = {"high": pal.success, "medium": pal.warning, "low": pal.danger}[v.confidence]
        self.l_confidence.setText(
            f'<span style="color:{color};font-weight:bold">{v.confidence}</span>'
        )
        # Render the bar chart + confidence gauge from the same
        # validation payload. The widget caches it internally, so a
        # subsequent theme toggle re-paints without us having to
        # store anything here.
        self.chart.show_validation(v)
        # Repopulate the field-plots gallery from the FEMMT
        # working directory. FEMMT writes a handful of post-
        # processing PNGs there after a successful solve; we
        # surface them in a thumbnail grid the user can click
        # to enlarge. ``populate_from_path`` falls back to its
        # empty state when the directory has no PNGs (e.g. the
        # FEMM legacy backend).
        self.gallery.populate_from_path(v.fem_path)
        self.txt_log.appendPlainText("\nResults:")
        self.txt_log.appendPlainText(f"  fem: {v.fem_path}")
        self.txt_log.appendPlainText(f"  flux linkage: {v.flux_linkage_FEA_Wb:.6e} Wb")
        self.txt_log.appendPlainText(f"  test current: {v.test_current_A:.3f} A")
        if v.log_excerpt:
            self.txt_log.appendPlainText("\nSolver log:")
            self.txt_log.appendPlainText(v.log_excerpt)
        if v.notes:
            self.txt_log.appendPlainText(f"\nNotes: {v.notes}")

    # ------------------------------------------------------------------
    # Swept-FEA path (Tier-4 evaluator from the cascade orchestrator)
    # ------------------------------------------------------------------
    def _run_sweep(self) -> None:
        """Kick off a Tier-4 swept-FEA evaluation on a worker thread.

        The orchestrator's Tier-4 code runs the same FEA backend
        Tier 3 uses but at N bias points across the half-cycle.
        Each point pays the single-point solve cost (5–30 s
        typical for FEMMT, sub-second for FEMM); we use the
        default 5-point sweep so the wall time stays under
        ~2 minutes on a typical workstation.
        """
        if self._thread is not None and self._thread.isRunning():
            return
        # Park focus before disabling — see ``_run`` for rationale.
        self.txt_log.setFocus()
        self.btn_run.setEnabled(False)
        self.btn_sweep.setEnabled(False)
        self.progress.show()
        self.txt_log.appendPlainText("\nStarting swept FEA (5 bias points)...")

        self._sweep_worker = _SweepWorker(
            self._spec, self._core, self._wire, self._material, self._result,
        )
        self._thread = QThread(self)
        self._sweep_worker.moveToThread(self._thread)
        self._thread.started.connect(self._sweep_worker.run)
        self._sweep_worker.finished.connect(self._on_sweep_finished)
        self._sweep_worker.failed.connect(self._on_sweep_failed)
        self._sweep_worker.finished.connect(self._thread.quit)
        self._sweep_worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_sweep_finished(self, payload):
        """Render the swept-FEA payload and switch to that tab."""
        from pfc_inductor.ui.widgets.fea_swept_chart import SweptFEAPayload

        self.progress.hide()
        self.btn_run.setEnabled(True)
        self.btn_sweep.setEnabled(True)
        if not isinstance(payload, SweptFEAPayload):
            self.txt_log.appendPlainText(
                "Swept FEA returned an unexpected payload — see traceback."
            )
            return
        self.swept_chart.show_payload(payload)
        # Auto-switch to the swept tab so the user sees the result
        # without an extra click.
        self.tabs.setCurrentIndex(2)
        self.txt_log.appendPlainText(
            f"Swept FEA done — {payload.n_points} points "
            f"({payload.backend})."
        )

    def _on_sweep_failed(self, msg: str) -> None:
        self.progress.hide()
        self.btn_run.setEnabled(True)
        self.btn_sweep.setEnabled(True)
        self.txt_log.appendPlainText(f"\nSwept FEA failed: {msg}")
        QMessageBox.warning(self, "Swept FEA failed", msg)

    @staticmethod
    def _color_pct(p: float) -> str:
        # Reads palette at call time so light↔dark transitions reflect
        # in any subsequent re-render of the validation table.
        pal = get_theme().palette
        sign = "+" if p >= 0 else ""
        ap = abs(p)
        color = pal.success if ap <= 5 else pal.warning if ap <= 15 else pal.danger
        return f'<span style="color:{color}">{sign}{p:.1f}%</span>'
