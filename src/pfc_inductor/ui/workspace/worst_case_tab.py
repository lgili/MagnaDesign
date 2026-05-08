"""Worst-case + production-tolerance tab.

Mounts inside :class:`ProjetoPage` between "Validate" and
"Export". The user kicks off a corner DOE and / or a Monte-Carlo
yield from this surface; results land inline (no modal) so the
operator can iterate without losing context.

UI shape
--------

::

    Tolerance set: [Default (IPC + IEC + vendor) ▼]
    [Run corner DOE]   [Run yield (1000 samples)]    143 corners · 30 ms

    ┌── Worst per metric ────────────────────────────────────┐
    │ T_winding   103 °C   nominal   +63 °C  ✗ over T_max    │
    │ B_pk        384 mT   AL=+1     +12 %   ✓                │
    │ P_total      14.5 W   …                 ✓                │
    └────────────────────────────────────────────────────────┘

    ┌── Yield ──────────────────────────────────────────────┐
    │ 96.4 %    seed=0    1000 samples                      │
    │ Failures: T_winding (23 %)  Bsat (11 %)              │
    └────────────────────────────────────────────────────────┘

Worker thread runs the engine — `evaluate_corners` already
takes ~30 ms for the bundled tolerance set, so the UI rarely
blocks; but we use a `QThread` anyway for forward-compat with
the next iteration that adds 1 000+ corner sweeps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Core, DesignResult, Material, Spec, Wire
from pfc_inductor.ui.theme import get_theme, on_theme_changed
from pfc_inductor.ui.widgets import Card
from pfc_inductor.worst_case import (
    DEFAULT_TOLERANCES,
    ToleranceSet,
    WorstCaseSummary,
    YieldReport,
    evaluate_corners,
    simulate_yield,
)


# ---------------------------------------------------------------------------
# Worker — runs the engine off the GUI thread so the user can keep typing
# ---------------------------------------------------------------------------
@dataclass
class _DesignContext:
    spec: Spec
    core: Core
    wire: Wire
    material: Material


class _WorstCaseWorker(QObject):
    """Runs ``evaluate_corners`` + ``simulate_yield`` in a worker
    thread. Emits one signal per phase so the UI can refresh
    incrementally even when both passes were requested at once."""

    corners_done = Signal(object)   # WorstCaseSummary
    yield_done   = Signal(object)   # YieldReport
    failed       = Signal(str)
    finished     = Signal()

    def __init__(
        self,
        ctx: _DesignContext,
        tolerances: ToleranceSet,
        *,
        run_corners: bool,
        run_yield: bool,
        n_samples: int,
        seed: int,
    ) -> None:
        super().__init__()
        self._ctx = ctx
        self._tols = tolerances
        self._run_corners = run_corners
        self._run_yield = run_yield
        self._n_samples = n_samples
        self._seed = seed

    def run(self) -> None:
        try:
            if self._run_corners:
                summary = evaluate_corners(
                    self._ctx.spec, self._ctx.core,
                    self._ctx.wire, self._ctx.material,
                    self._tols,
                )
                self.corners_done.emit(summary)
            if self._run_yield:
                report = simulate_yield(
                    self._ctx.spec, self._ctx.core,
                    self._ctx.wire, self._ctx.material,
                    self._tols,
                    n_samples=self._n_samples,
                    seed=self._seed,
                )
                self.yield_done.emit(report)
        except Exception as exc:  # noqa: BLE001 — surface anything
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------
class WorstCaseTab(QWidget):
    """Tab body — controls + worst-per-metric table + yield card."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)

        self._ctx: Optional[_DesignContext] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_WorstCaseWorker] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        # ---- Controls row -------------------------------------------------
        controls = QFrame()
        ch = QHBoxLayout(controls)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(10)

        ch.addWidget(QLabel("Tolerance set:"))
        self._cmb_tolerances = QComboBox()
        # Bundled sets only — custom JSON loading lives behind the
        # Settings tab once that ships. For now the user picks
        # "Default" (IPC + IEC + vendor blend) which is what every
        # other entry point in the app honours by default.
        self._cmb_tolerances.addItem(
            "Default — IPC + IEC + vendor", DEFAULT_TOLERANCES,
        )
        self._cmb_tolerances.setMinimumWidth(280)
        ch.addWidget(self._cmb_tolerances)

        ch.addSpacing(20)
        ch.addWidget(QLabel("Yield samples:"))
        self._spin_samples = QSpinBox()
        self._spin_samples.setRange(50, 100_000)
        self._spin_samples.setValue(1000)
        self._spin_samples.setSingleStep(100)
        self._spin_samples.setMinimumWidth(110)
        ch.addWidget(self._spin_samples)

        ch.addStretch(1)

        self._btn_corners = QPushButton("Run corner DOE")
        self._btn_corners.setProperty("class", "Primary")
        self._btn_corners.clicked.connect(
            lambda: self._launch(run_corners=True, run_yield=False),
        )
        ch.addWidget(self._btn_corners)

        self._btn_yield = QPushButton("Run yield")
        self._btn_yield.clicked.connect(
            lambda: self._launch(run_corners=False, run_yield=True),
        )
        ch.addWidget(self._btn_yield)

        self._btn_both = QPushButton("Run both")
        self._btn_both.setProperty("class", "Secondary")
        self._btn_both.clicked.connect(
            lambda: self._launch(run_corners=True, run_yield=True),
        )
        ch.addWidget(self._btn_both)

        outer.addWidget(controls)

        # ---- Status line --------------------------------------------------
        self._status = QLabel(
            "Pick a tolerance set and a run mode. Default 7-tolerance "
            "set evaluates 143 corners in ~30 ms.",
        )
        self._status.setProperty("role", "muted")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        # ---- Worst per metric --------------------------------------------
        self._worst_table = QTableWidget(0, 5)
        self._worst_table.setHorizontalHeaderLabels(
            ["Metric", "Worst value", "Corner", "Margin to limit", "Result"],
        )
        self._worst_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers,
        )
        self._worst_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection,
        )
        self._worst_table.verticalHeader().setVisible(False)
        self._worst_table.setMinimumHeight(150)
        self._worst_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )
        h = self._worst_table.horizontalHeader()
        h.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents,
        )
        h.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents,
        )
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents,
        )
        h.setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents,
        )

        outer.addWidget(Card("Worst per metric", self._worst_table))

        # ---- Yield card ---------------------------------------------------
        yield_body = QFrame()
        yv = QVBoxLayout(yield_body)
        yv.setContentsMargins(12, 8, 12, 8)
        yv.setSpacing(6)

        self._lbl_yield_pct = QLabel("—")
        self._lbl_yield_pct.setObjectName("WorstCaseYieldHero")
        self._lbl_yield_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        yv.addWidget(self._lbl_yield_pct)

        self._lbl_yield_meta = QLabel(
            "Run a yield estimate to see the pass-rate.",
        )
        self._lbl_yield_meta.setProperty("role", "muted")
        self._lbl_yield_meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_yield_meta.setWordWrap(True)
        yv.addWidget(self._lbl_yield_meta)

        self._fail_modes = QLabel("")
        self._fail_modes.setProperty("role", "muted")
        self._fail_modes.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fail_modes.setWordWrap(True)
        yv.addWidget(self._fail_modes)

        outer.addWidget(Card("Yield estimate (Monte-Carlo)", yield_body))

        outer.addStretch(1)

        on_theme_changed(self._refresh_qss)
        self._refresh_qss()

    # ------------------------------------------------------------------
    # Public API — host calls this after every recompute
    # ------------------------------------------------------------------
    def update_from_design(
        self,
        result: DesignResult,
        spec: Spec,
        core: Core,
        wire: Wire,
        material: Material,
    ) -> None:
        """Cache the engine inputs so the user can hit Run.

        We don't auto-run the corner DOE on every recompute — it's
        a deliberate "pull" action: the user toggles a tolerance set
        and clicks Run when they want the snapshot. Auto-running
        would re-burn the worker every time the spec drawer
        emitted ``changed``, which is dozens of times per minute.
        """
        self._ctx = _DesignContext(
            spec=spec, core=core, wire=wire, material=material,
        )
        # When the user hasn't run anything yet, bump the status
        # line to confirm the inputs are ready.
        if self._worst_table.rowCount() == 0:
            self._status.setText(
                f"Ready · {spec.topology} · "
                f"{material.name} on {core.part_number}.",
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _launch(self, *, run_corners: bool, run_yield: bool) -> None:
        if self._ctx is None:
            self._status.setText(
                "Run a design first — the worst-case engine needs an "
                "engine snapshot to perturb.",
            )
            return
        # Defensive guard: ``deleteLater`` (wired to ``_thread.finished``
        # below) tears down the Qt C++ object as soon as the previous
        # run completes, but the Python wrapper on ``self._thread``
        # lingers until ``_on_run_finished`` clears it. If the
        # ``finished`` slot races the next click we'd hit
        # "Internal C++ object (QThread) already deleted" — wrap the
        # ``isRunning()`` probe so the dead-wrapper case short-circuits.
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    return
            except RuntimeError:
                # C++ side gone; treat the slot as not running and
                # let the launch proceed with a fresh thread.
                self._thread = None
                self._worker = None

        tolerances = self._cmb_tolerances.currentData()
        if tolerances is None:
            tolerances = DEFAULT_TOLERANCES

        # Disable the buttons while the worker runs so the user
        # doesn't double-fire and clobber the table mid-render.
        for btn in (self._btn_corners, self._btn_yield, self._btn_both):
            btn.setEnabled(False)

        if run_corners:
            self._status.setText("Running corner DOE…")
        elif run_yield:
            self._status.setText(
                f"Running yield ({self._spin_samples.value()} samples)…",
            )
        else:
            return

        self._worker = _WorstCaseWorker(
            self._ctx, tolerances,
            run_corners=run_corners,
            run_yield=run_yield,
            n_samples=int(self._spin_samples.value()),
            seed=0,
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.corners_done.connect(self._on_corners_done)
        self._worker.yield_done.connect(self._on_yield_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_run_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_corners_done(self, summary: WorstCaseSummary) -> None:
        self._populate_worst_table(summary)
        self._status.setText(
            f"Corner DOE: {summary.n_corners_evaluated} corners "
            f"({summary.n_corners_failed} engine failures).",
        )

    def _on_yield_done(self, report: YieldReport) -> None:
        rate = report.pass_rate * 100.0
        self._lbl_yield_pct.setText(f"{rate:.1f} %")
        self._refresh_yield_color(rate)
        self._lbl_yield_meta.setText(
            f"{report.n_pass} of {report.n_samples} samples passed "
            f"(seed = 0). {report.n_engine_error} engine errors.",
        )
        if report.fail_modes:
            top = sorted(
                report.fail_modes.items(), key=lambda kv: -kv[1],
            )[:4]
            modes = " · ".join(
                f"{mode} ({count})" for mode, count in top
            )
            self._fail_modes.setText(f"Failures: {modes}")
        else:
            self._fail_modes.setText("Failures: none")

    def _on_failed(self, message: str) -> None:
        self._status.setText(f"Run failed: {message}")

    def _on_run_finished(self) -> None:
        for btn in (self._btn_corners, self._btn_yield, self._btn_both):
            btn.setEnabled(True)
        # Clear references to the worker + thread so the next launch
        # builds fresh ones. Without this the Python wrappers outlive
        # their C++ counterparts (deleteLater is wired below) and the
        # next ``_launch`` reaches a dead QThread on its ``isRunning``
        # probe.
        self._worker = None
        self._thread = None

    # ------------------------------------------------------------------
    def _populate_worst_table(self, summary: WorstCaseSummary) -> None:
        # Sorted so the most-engineered metric (T_winding) sits at the
        # top; the sweep result for boost / line-reactor differs in
        # which metric is at the limit, so the order is fixed by
        # importance, not by which metric won.
        metric_order = ("T_winding_C", "B_pk_T", "P_total_W", "T_rise_C")
        rows: list[tuple[str, float, str, str, bool]] = []

        # ``worst_per_metric`` is a dict of CornerResult; some
        # metrics may be missing if every corner failed for that
        # metric (rare but possible).
        spec = summary.nominal.spec if summary.nominal else None
        material = summary.nominal.material if summary.nominal else None

        for metric in metric_order:
            cr = summary.worst_per_metric.get(metric)
            if cr is None or cr.result is None:
                continue
            value = self._read_metric(cr.result, metric)
            if value is None:
                continue
            margin_text, passed = self._margin_for(
                metric, value, spec, material,
            )
            rows.append((
                metric,
                float(value),
                cr.label,
                margin_text,
                passed,
            ))

        self._worst_table.setRowCount(len(rows))
        for r, (metric, value, label, margin, passed) in enumerate(rows):
            self._worst_table.setItem(
                r, 0, QTableWidgetItem(self._pretty_metric(metric)),
            )
            self._worst_table.setItem(
                r, 1, QTableWidgetItem(self._format_value(metric, value)),
            )
            self._worst_table.setItem(r, 2, QTableWidgetItem(label))
            self._worst_table.setItem(r, 3, QTableWidgetItem(margin))
            mark = QTableWidgetItem("✓" if passed else "✗")
            mark.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter,
            )
            self._worst_table.setItem(r, 4, mark)

    @staticmethod
    def _read_metric(result: DesignResult, metric: str) -> Optional[float]:
        v = getattr(result, metric, None)
        if v is None and hasattr(result, "losses"):
            v = getattr(result.losses, metric, None)
        if v is None or not isinstance(v, (int, float)):
            return None
        if not math.isfinite(v):
            return None
        return float(v)

    @staticmethod
    def _pretty_metric(metric: str) -> str:
        return {
            "T_winding_C": "T winding",
            "T_rise_C":    "ΔT",
            "B_pk_T":      "B peak",
            "P_total_W":   "Losses",
        }.get(metric, metric)

    @staticmethod
    def _format_value(metric: str, value: float) -> str:
        if metric in ("T_winding_C", "T_rise_C"):
            return f"{value:.1f} °C"
        if metric == "B_pk_T":
            return f"{value * 1000:.0f} mT"
        if metric == "P_total_W":
            return f"{value:.2f} W"
        return f"{value:.3g}"

    @staticmethod
    def _margin_for(
        metric: str,
        value: float,
        spec: Optional[Spec],
        material: Optional[Material],
    ) -> tuple[str, bool]:
        """Return ``(text, passed)`` describing how close ``value``
        is to its acceptance limit. Same envelope as the Monte-Carlo
        default `_default_pass_fn` so the table verdict and the
        yield report agree."""
        if metric == "T_winding_C" and spec is not None:
            limit = float(spec.T_max_C)
            delta = limit - value
            return f"{delta:+.1f} °C to T_max", value <= limit
        if metric == "B_pk_T" and material is not None and spec is not None:
            bsat = float(getattr(material, "Bsat_100C_T", 0.0))
            margin_pct = float(spec.Bsat_margin)
            limit = bsat * max(1.0 - margin_pct, 0.0)
            if limit <= 0:
                return "—", value <= 0
            ratio = value / limit * 100.0
            return f"{ratio:.0f} % of B_sat", value <= limit
        if metric == "P_total_W" and spec is not None:
            limit = max(spec.Pout_W, 1.0) * 0.10
            ratio = value / limit * 100.0
            return f"{ratio:.0f} % of 10% Pout", value <= limit
        return "—", True

    # ------------------------------------------------------------------
    def _refresh_yield_color(self, rate_pct: float) -> None:
        p = get_theme().palette
        if rate_pct >= 95:
            color = p.success
        elif rate_pct >= 90:
            color = p.warning
        else:
            color = p.danger
        t = get_theme().type
        self._lbl_yield_pct.setStyleSheet(
            f"color: {color}; "
            f"font-family: {t.numeric_family}; "
            f"font-size: {t.title_lg}px; "
            f"font-weight: {t.semibold};"
        )

    def _refresh_qss(self) -> None:
        # The hero label colours from the latest reading; reset
        # to neutral when nothing's been computed yet.
        if self._lbl_yield_pct.text() == "—":
            p = get_theme().palette
            t = get_theme().type
            self._lbl_yield_pct.setStyleSheet(
                f"color: {p.text_muted}; "
                f"font-family: {t.numeric_family}; "
                f"font-size: {t.title_lg}px; "
                f"font-weight: {t.semibold};"
            )
