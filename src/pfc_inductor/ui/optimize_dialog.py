"""Optimizer: sweep cores × wires for the selected material, show Pareto.

Two surfaces:

- :class:`OptimizerEmbed` — a ``QWidget`` containing the entire
  optimizer body (controls, table, plot, "Apply" button). Mountable
  in any page; used by the v3 :class:`OtimizadorPage
  <pfc_inductor.ui.workspace.otimizador_page.OtimizadorPage>`.

- :class:`OptimizerDialog` — modal wrapper that composes
  ``OptimizerEmbed`` plus a ``Close`` button. Kept for back-compat
  with the legacy overflow-menu launch path.
"""

from __future__ import annotations

from typing import Optional

import matplotlib
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.optimize import SweepResult, pareto_front, sweep
from pfc_inductor.optimize.sweep import rank
from pfc_inductor.ui.theme import get_theme
from pfc_inductor.ui.widgets.optimizer_filters_bar import OptimizerFiltersBar


class _SweepWorker(QObject):
    progress = Signal(int, int)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, spec, cores, wires, materials, only_compat):
        super().__init__()
        self.spec = spec
        self.cores = cores
        self.wires = wires
        self.materials = materials
        self.only_compat = only_compat

    def run(self):
        try:
            # ``materials`` is now the *already-filtered* list from
            # the OptimizerFiltersBar — no separate ``material_id``
            # path. The single-id parameter on ``sweep()`` is kept
            # for back-compat callers but we leave it unset; the
            # engine iterates the full list we hand in.
            results = sweep(
                self.spec,
                self.cores,
                self.wires,
                self.materials,
                only_compatible_cores=self.only_compat,
                progress_cb=lambda d, t: self.progress.emit(d, t),
            )
            self.done.emit(results)
        except Exception as e:
            self.failed.emit(str(e))


class OptimizerEmbed(QWidget):
    """Optimizer body — controls + ranked table + Pareto plot + Apply.

    Designed to be embedded inline in a workspace page or wrapped in a
    modal :class:`OptimizerDialog`. The constructor accepts an
    optional spec; if ``None`` the run button is disabled until
    :meth:`set_inputs` is called with a valid spec + catalogs.
    """

    selection_applied = Signal(str, str, str)  # material_id, core_id, wire_id

    def __init__(
        self,
        spec: Optional[Spec] = None,
        materials: Optional[list[Material]] = None,
        cores: Optional[list[Core]] = None,
        wires: Optional[list[Wire]] = None,
        current_material_id: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._spec = spec
        self._materials = list(materials) if materials else []
        self._cores = list(cores) if cores else []
        self._wires = list(wires) if wires else []
        self._results: list[SweepResult] = []
        self._pareto: list[SweepResult] = []
        self._row_to_result: list[SweepResult] = []
        self._thread: Optional[QThread] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        outer.addWidget(self._build_controls(current_material_id))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_plot())
        splitter.setSizes([700, 500])
        outer.addWidget(splitter, 1)

        outer.addLayout(self._build_buttons())

        # Disable run if no spec yet.
        if self._spec is None:
            self.btn_run.setEnabled(False)
            self.lbl_count.setText(
                "Waiting for a spec — calculate a design first.",
            )

    # ------------------------------------------------------------------
    def set_inputs(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        current_material_id: str = "",
    ) -> None:
        """(Re)bind the optimizer inputs without rebuilding the UI.

        Called by the host whenever the user edits the spec / reloads
        the catalogs in another part of the app — the optimizer page
        always reflects the latest state."""
        self._spec = spec
        self._materials = list(materials)
        self._cores = list(cores)
        self._wires = list(wires)
        # Hand the topology-filtered catalogue to the filter bar.
        self.filters_bar.set_catalogs(
            self._materials,
            self._cores,
            self._wires,
        )
        # Pre-select the project's current material so the default
        # sweep is narrow (~1 material × its compatible cores × all
        # wires). Without this seed the chip would default to the
        # wildcard "All N materials" and hitting Run would launch a
        # full N×M×K combinatorial sweep — with the current 470
        # material / 10 k core / 1 k wire catalogue that's billions
        # of evaluations and locks the worker thread for hours. Users
        # who genuinely want a wide search can clear the chip and add
        # whatever subset they like.
        if current_material_id:
            self.filters_bar.chip_materials.set_selected(
                [current_material_id],
            )
        self.btn_run.setEnabled(True)
        self._refresh_estimate()
        if not self._results:
            self.lbl_count.setText(
                "Ready — pick filters and an objective, then click "
                "<b>Run sweep</b> to generate the Pareto front.",
            )

    def _build_controls(self, current_material_id: str) -> QGroupBox:
        box = QGroupBox("Sweep configuration")
        v = QVBoxLayout(box)
        v.setSpacing(8)

        # ---- Multi-select filters + objective (shared widget) -----
        self.filters_bar = OptimizerFiltersBar()
        self.filters_bar.set_catalogs(
            self._materials,
            self._cores,
            self._wires,
        )
        # Re-rank the visible table on objective change without a
        # full re-sweep — the underlying ``self._results`` cache is
        # already enough to ``rank()`` again client-side.
        self.filters_bar.objective_changed.connect(
            lambda _key: self._refresh_table(),
        )
        # The estimate label tracks chip selection too — refresh on
        # any filter change so the user always sees what they're
        # about to run before they click.
        self.filters_bar.filters_changed.connect(self._refresh_estimate)
        v.addWidget(self.filters_bar)

        # ---- Secondary toggles + run button -----------------------
        h = QHBoxLayout()
        h.setSpacing(12)

        self.chk_compat = QCheckBox(
            "Restrict to cores compatible with the material",
        )
        self.chk_compat.setChecked(True)
        self.chk_feasible = QCheckBox("Hide infeasible designs")
        # Default ON: show only candidates that satisfy Ku/Bsat/T limits.
        # Most users want a list of "what can I actually build", not a
        # catalogue of failures. Toggle off to inspect borderline cases.
        self.chk_feasible.setChecked(True)
        self.chk_curated_only = QCheckBox("Curated only")
        self.chk_curated_only.setToolTip(
            "Limits the sweep to curated materials and wires, ignoring "
            "the OpenMagnetics catalog — avoids rankings dominated by "
            "entries without Steinmetz/rolloff calibration.",
        )
        self.chk_compat.stateChanged.connect(self._refresh_estimate)
        h.addWidget(self.chk_compat)
        h.addWidget(self.chk_feasible)
        h.addWidget(self.chk_curated_only)
        h.addStretch(1)

        # Cardinality estimate — surfaces the "this run will evaluate
        # ~N combinations" reality before the user clicks Run, so
        # they don't kick off a 6-billion-combo sweep by accident.
        # Refreshed on any filter / compat-toggle change.
        self.lbl_estimate = QLabel("")
        self.lbl_estimate.setProperty("role", "muted")
        self.lbl_estimate.setToolTip(
            "Approximate number of (material × core × wire) "
            "combinations the sweep will evaluate. Sweeping the full "
            "catalogue can take many minutes and tens of GB of RAM —\n"
            "narrow the chips above to keep runtime sane.",
        )
        h.addWidget(self.lbl_estimate)

        self.btn_run = QPushButton("Run sweep")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 4px 10px;")
        self.btn_run.clicked.connect(self._run_sweep)
        h.addWidget(self.btn_run)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMaximumWidth(160)
        h.addWidget(self.progress)
        v.addLayout(h)

        self.chk_feasible.stateChanged.connect(self._refresh_table)
        return box

    def _build_table(self) -> QGroupBox:
        box = QGroupBox("Results")
        v = QVBoxLayout(box)
        self.lbl_count = QLabel("No sweep yet.")
        v.addWidget(self.lbl_count)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            [
                "Core",
                "Wire",
                "Material",
                "Vol [cm³]",
                "L [µH]",
                "N",
                "P [W]",
                "T [°C]",
                "Cost",
                "Status",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        self.table.setFont(f)
        v.addWidget(self.table, 1)
        return box

    def _build_plot(self) -> QGroupBox:
        box = QGroupBox("Volume × Total loss (Pareto highlighted)")
        v = QVBoxLayout(box)
        self.fig = Figure(figsize=(5, 5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Volume [cm³]")
        self.ax.set_ylabel("P_total [W]")
        # Empty-state painting: a 0..1 axis with the default ticks
        # reads as "broken plot" before the first sweep. Hide the
        # spines/ticks and centre an instructional caption — the
        # canvas now communicates "no data yet, here's how to get
        # data" instead of "this chart is empty".
        self._paint_empty_plot()
        v.addWidget(self.canvas)
        return box

    def _paint_empty_plot(self) -> None:
        """Draw a clean empty state on the matplotlib canvas.

        Called once at construction and again whenever ``set_inputs``
        runs without yet having results. Replaced with the real
        Pareto scatter as soon as a sweep produces data.
        """
        self.ax.clear()
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in ("top", "right", "bottom", "left"):
            self.ax.spines[spine].set_visible(False)
        self.ax.text(
            0.5,
            0.55,
            "Multi-objective Pareto sweep",
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            transform=self.ax.transAxes,
            color="#52525B",
        )
        self.ax.text(
            0.5,
            0.42,
            'Configure material and ordering above,\nthen click "Run sweep".',
            ha="center",
            va="center",
            fontsize=9,
            transform=self.ax.transAxes,
            color="#71717A",
        )
        self.canvas.draw_idle()

    def _build_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_apply = QPushButton("Apply selection")
        self.btn_apply.setProperty("class", "Primary")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_selection)
        h.addWidget(self.btn_apply)
        return h

    # Above this many evaluations the sweep stops being interactive
    # (minutes of CPU + GBs of RAM). We confirm with the user before
    # launching so they don't lock up the app by accident. The
    # baseline single-material run is ~65 k combinations
    # (1 material × ~45 compatible cores × ~1.4 k wires) so we set
    # the threshold above that — multi-material sweeps cross the
    # bar and trigger the dialog.
    _SWEEP_CONFIRM_THRESHOLD = 250_000

    def _estimate_combinations(self) -> int:
        """Best-effort estimate of (material × core × wire) cardinality.

        Used by both the inline label and the run-time confirmation
        dialog. Honours the ``Restrict to compatible cores`` toggle:
        when on we count only the cores whose ``default_material_id``
        matches at least one selected material, which is the same
        rule ``sweep()`` applies internally.
        """
        try:
            mats = self.filters_bar.selected_materials()
            cores = self.filters_bar.selected_cores()
            wires = self.filters_bar.selected_wires()
        except AttributeError:
            return 0

        n_wires = len(wires)
        if not mats or not cores or not n_wires:
            return 0

        if self.chk_compat.isChecked():
            mat_ids = {m.id for m in mats}
            compat_cores = sum(
                1 for c in cores if getattr(c, "default_material_id", None) in mat_ids
            )
            return compat_cores * n_wires
        return len(mats) * len(cores) * n_wires

    def _refresh_estimate(self) -> None:
        n = self._estimate_combinations()
        if n == 0:
            self.lbl_estimate.setText("Filters reject every candidate.")
            return
        if n >= self._SWEEP_CONFIRM_THRESHOLD:
            self.lbl_estimate.setText(
                f"≈ {n:,} combinations · <b>large run</b>",
            )
        else:
            self.lbl_estimate.setText(f"≈ {n:,} combinations")

    def _run_sweep(self):
        if self._thread is not None and self._thread.isRunning():
            return

        # Confirm before launching anything that will take minutes /
        # GBs. The threshold is conservative (≈50 k combos = a few
        # seconds on a modern CPU); above it the worker thread blocks
        # interactivity and the process pool can leak semaphores if
        # the user hits Cancel.
        n_estimate = self._estimate_combinations()
        if n_estimate >= self._SWEEP_CONFIRM_THRESHOLD:
            from PySide6.QtWidgets import QMessageBox

            reply = QMessageBox.question(
                self,
                "Large sweep",
                f"This will evaluate roughly <b>{n_estimate:,}</b> "
                f"combinations.\n\n"
                f"That can take several minutes and noticeable RAM. "
                f"Narrow the Materials / Cores / Wires chips above "
                f"to keep things interactive.\n\n"
                f"Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.btn_run.setEnabled(False)
        self.progress.setValue(0)
        only_compat = self.chk_compat.isChecked()

        # ``selected_*`` returns the full topology-filtered catalogue
        # when the user hasn't picked anything (empty chip → wildcard).
        mats = self.filters_bar.selected_materials()
        cores = self.filters_bar.selected_cores()
        wires = self.filters_bar.selected_wires()

        # ``Curated only`` then narrows materials + wires further.
        # We intersect with whatever the user already selected so the
        # two filters compose predictably (curated *and* hand-picked).
        if self.chk_curated_only.isChecked():
            from pfc_inductor.data_loader import load_curated_ids

            cur_mats = load_curated_ids("materials")
            cur_wires = load_curated_ids("wires")
            filtered_mats = [m for m in mats if m.id in cur_mats]
            filtered_wires = [w for w in wires if w.id in cur_wires]
            # If the curated intersection is empty, fall back to the
            # user's selection — better to honour their explicit pick
            # than to silently sweep an empty set.
            mats = filtered_mats or mats
            wires = filtered_wires or wires

        self._worker = _SweepWorker(
            self._spec,
            cores,
            wires,
            mats,
            only_compat,
        )
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.progress.setValue(int(100 * done / total))

    def _on_done(self, results: list[SweepResult]):
        self._results = results
        self._pareto = pareto_front(results)
        self._refresh_table()
        self._refresh_plot()
        self.progress.setValue(100)
        self.btn_run.setEnabled(True)

    def _on_failed(self, msg: str):
        QMessageBox.critical(self, "Sweep error", msg)
        self.btn_run.setEnabled(True)

    def _refresh_table(self):
        rank_key = self.filters_bar.objective()
        feasible_only = self.chk_feasible.isChecked()
        n_total = len(self._results)
        n_feasible = sum(1 for x in self._results if x.feasible)
        rows = [r for r in self._results if (not feasible_only or r.feasible)]
        rows = rank(rows, by=rank_key, feasible_first=True)
        rows = rows[:200]  # cap at 200 for UI responsiveness

        self.table.setRowCount(len(rows))
        pareto_set = {id(r) for r in self._pareto}
        for i, r in enumerate(rows):
            r0 = r.result
            in_pareto = id(r) in pareto_set
            cost_cell = f"{r.cost.currency} {r.cost.total_cost:.2f}" if r.cost is not None else "—"
            cells = [
                r.core.part_number,
                r.wire.id,
                r.material.name,
                f"{r.volume_cm3:.1f}",
                f"{r0.L_actual_uH:.0f}",
                f"{r0.N_turns}",
                f"{r0.losses.P_total_W:.2f}",
                f"{r0.T_winding_C:.0f}",
                cost_cell,
                ("✓ Pareto" if in_pareto else "✓") if r.feasible else f"⚠ {r.n_warnings}",
            ]
            for c_idx, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if not r.feasible:
                    item.setForeground(Qt.GlobalColor.red)
                elif in_pareto:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                self.table.setItem(i, c_idx, item)
        self._row_to_result = list(rows)

        # Header: clearly say "X viable / Y total". When 0 viable, give
        # the user a concrete remediation path instead of just an empty
        # table.
        if n_total == 0:
            self.lbl_count.setText("No designs evaluated yet. Click <b>Run sweep</b>.")
        elif n_feasible == 0:
            self.lbl_count.setText(
                f"<b>0 feasible designs</b> out of {n_total} evaluated. "
                "Try: increasing <i>Ku max</i> or <i>Bsat margin</i>; "
                "reducing Pout; selecting (sweep all) materials; "
                "unchecking <i>Curated only</i>."
            )
        else:
            pct = 100.0 * n_feasible / n_total
            extra = "" if feasible_only else f" — {n_total - n_feasible} infeasible hidden below"
            self.lbl_count.setText(
                f"<b>{n_feasible} feasible</b> out of {n_total} evaluated ({pct:.1f}%). "
                f"Showing top {len(rows)}{extra}."
            )

    def _refresh_plot(self):
        self.ax.clear()
        p = get_theme().palette
        all_results = self._results
        feas = [(r.volume_cm3, r.P_total_W) for r in all_results if r.feasible]
        infeas = [(r.volume_cm3, min(r.P_total_W, 100.0)) for r in all_results if not r.feasible]
        if infeas:
            xi, yi = zip(*infeas, strict=False)
            self.ax.scatter(xi, yi, c=p.plot_pareto_infeasible, s=8, alpha=0.4, label="infeasible")
        if feas:
            xf, yf = zip(*feas, strict=False)
            self.ax.scatter(xf, yf, c=p.plot_pareto_feasible, s=10, alpha=0.7, label="feasible")
        if self._pareto:
            xp = [r.volume_cm3 for r in self._pareto]
            yp = [r.P_total_W for r in self._pareto]
            self.ax.plot(
                xp, yp, "-o", c=p.plot_pareto_frontier, label="Pareto", linewidth=2, markersize=8
            )
        self.ax.set_xlabel("Volume [cm³]")
        self.ax.set_ylabel("P_total [W]")
        self.ax.set_xscale("log")
        self.ax.legend(loc="upper right")
        self.ax.grid(True, alpha=0.4, which="both")
        self.canvas.draw()

    def _on_row_selected(self):
        rows = self.table.selectionModel().selectedRows()
        self.btn_apply.setEnabled(len(rows) > 0)

    def _apply_selection(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx >= len(self._row_to_result):
            return
        sr = self._row_to_result[idx]
        self.selection_applied.emit(sr.material.id, sr.core.id, sr.wire.id)


class OptimizerDialog(QDialog):
    """Modal wrapper around :class:`OptimizerEmbed`.

    Kept for back-compat with callers that prefer a dialog. New code
    should embed :class:`OptimizerEmbed` directly inside a page.
    """

    selection_applied = Signal(str, str, str)

    def __init__(
        self,
        spec: Spec,
        materials: list[Material],
        cores: list[Core],
        wires: list[Wire],
        current_material_id: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Optimizer — sweep cores × wires")
        self.resize(1200, 700)
        layout = QVBoxLayout(self)

        self._embed = OptimizerEmbed(
            spec,
            materials,
            cores,
            wires,
            current_material_id,
            parent=self,
        )
        # Forward the inner signal AND auto-accept so callers that wait
        # for ``dlg.exec() == Accepted`` keep working unchanged.
        self._embed.selection_applied.connect(self._on_inner_applied)
        layout.addWidget(self._embed, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

    def _on_inner_applied(self, material_id: str, core_id: str, wire_id: str) -> None:
        self.selection_applied.emit(material_id, core_id, wire_id)
        self.accept()
