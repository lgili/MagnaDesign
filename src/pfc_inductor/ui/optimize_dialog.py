"""Optimizer dialog: sweep cores × wires for the selected material, show Pareto."""
from __future__ import annotations
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QCheckBox, QProgressBar, QGroupBox, QFormLayout, QMessageBox,
)
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from pfc_inductor.models import Spec, Core, Wire, Material
from pfc_inductor.optimize import sweep, pareto_front, SweepResult
from pfc_inductor.optimize.sweep import rank


_OK = "#1c7c3b"
_BAD = "#a01818"


class _SweepWorker(QObject):
    progress = Signal(int, int)
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, spec, cores, wires, materials, material_id, only_compat):
        super().__init__()
        self.spec = spec
        self.cores = cores
        self.wires = wires
        self.materials = materials
        self.material_id = material_id
        self.only_compat = only_compat

    def run(self):
        try:
            results = sweep(
                self.spec, self.cores, self.wires, self.materials,
                material_id=self.material_id,
                only_compatible_cores=self.only_compat,
                progress_cb=lambda d, t: self.progress.emit(d, t),
            )
            self.done.emit(results)
        except Exception as e:
            self.failed.emit(str(e))


class OptimizerDialog(QDialog):
    """Modal optimizer. On accept, returns chosen (core_id, wire_id, material_id)."""

    selection_applied = Signal(str, str, str)  # material_id, core_id, wire_id

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
        self.setWindowTitle("Otimizador — varredura núcleos × fios")
        self.resize(1200, 700)
        self._spec = spec
        self._materials = materials
        self._cores = cores
        self._wires = wires
        self._results: list[SweepResult] = []
        self._pareto: list[SweepResult] = []
        self._thread: Optional[QThread] = None

        outer = QVBoxLayout(self)

        outer.addWidget(self._build_controls(current_material_id))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_plot())
        splitter.setSizes([700, 500])
        outer.addWidget(splitter, 1)

        outer.addLayout(self._build_buttons())

    def _build_controls(self, current_material_id: str) -> QGroupBox:
        box = QGroupBox("Configuração da varredura")
        h = QHBoxLayout(box)
        f = QFormLayout()
        self.cmb_material = QComboBox()
        self.cmb_material.addItem("(varrer todos)", None)
        for m in self._materials:
            self.cmb_material.addItem(f"{m.vendor} — {m.name}", m.id)
        # Pre-select current material
        for i in range(self.cmb_material.count()):
            if self.cmb_material.itemData(i) == current_material_id:
                self.cmb_material.setCurrentIndex(i)
                break
        f.addRow("Material:", self.cmb_material)

        self.cmb_rank = QComboBox()
        for label, key in [
            ("Menor perda total", "loss"),
            ("Menor volume", "volume"),
            ("Menor temperatura", "temp"),
            ("Menor custo", "cost"),
            ("Score (60% perda + 40% volume)", "score"),
            ("Score 40/30/30 (perda/volume/custo)", "score_with_cost"),
        ]:
            self.cmb_rank.addItem(label, key)
        f.addRow("Ordenar por:", self.cmb_rank)

        self.chk_compat = QCheckBox("Restringir a núcleos compatíveis com o material")
        self.chk_compat.setChecked(True)
        self.chk_feasible = QCheckBox("Ocultar designs inviáveis")
        # Default ON: show only candidates that satisfy Ku/Bsat/T limits.
        # Most users want a list of "what can I actually build", not a
        # catalogue of failures. Toggle off to inspect borderline cases.
        self.chk_feasible.setChecked(True)
        self.chk_curated_only = QCheckBox("Apenas curados")
        self.chk_curated_only.setToolTip(
            "Limita a varredura aos materiais e fios curados, ignorando o "
            "catálogo OpenMagnetics — evita ranking dominado por entradas "
            "sem calibração de Steinmetz/rolloff."
        )
        h.addLayout(f)

        side = QVBoxLayout()
        side.addWidget(self.chk_compat)
        side.addWidget(self.chk_feasible)
        side.addWidget(self.chk_curated_only)
        self.btn_run = QPushButton("Rodar varredura")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 4px 10px;")
        self.btn_run.clicked.connect(self._run_sweep)
        side.addWidget(self.btn_run)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        side.addWidget(self.progress)
        h.addLayout(side)
        h.addStretch(1)

        self.cmb_rank.currentIndexChanged.connect(self._refresh_table)
        self.chk_feasible.stateChanged.connect(self._refresh_table)
        return box

    def _build_table(self) -> QGroupBox:
        box = QGroupBox("Resultados")
        v = QVBoxLayout(box)
        self.lbl_count = QLabel("Nenhuma varredura ainda.")
        v.addWidget(self.lbl_count)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Núcleo", "Fio", "Material", "Vol [cm³]",
            "L [µH]", "N", "P [W]", "T [°C]", "Custo", "Status",
        ])
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
        box = QGroupBox("Volume × Perda total (Pareto destacado)")
        v = QVBoxLayout(box)
        self.fig = Figure(figsize=(5, 5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Volume [cm³]")
        self.ax.set_ylabel("P_total [W]")
        v.addWidget(self.canvas)
        return box

    def _build_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_apply = QPushButton("Aplicar selecionado")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_selection)
        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_apply)
        h.addWidget(self.btn_close)
        return h

    def _run_sweep(self):
        if self._thread is not None and self._thread.isRunning():
            return
        self.btn_run.setEnabled(False)
        self.progress.setValue(0)
        material_id = self.cmb_material.currentData()
        only_compat = self.chk_compat.isChecked()

        if self.chk_curated_only.isChecked():
            from pfc_inductor.data_loader import load_curated_ids
            cur_mats = load_curated_ids("materials")
            cur_wires = load_curated_ids("wires")
            mats = [m for m in self._materials if m.id in cur_mats] or self._materials
            wires = [w for w in self._wires if w.id in cur_wires] or self._wires
        else:
            mats = self._materials
            wires = self._wires

        self._worker = _SweepWorker(
            self._spec, self._cores, wires, mats,
            material_id, only_compat,
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
        QMessageBox.critical(self, "Erro na varredura", msg)
        self.btn_run.setEnabled(True)

    def _refresh_table(self):
        rank_key = self.cmb_rank.currentData()
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
            cost_cell = (
                f"{r.cost.currency} {r.cost.total_cost:.2f}"
                if r.cost is not None else "—"
            )
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
            self.lbl_count.setText("Nenhum design avaliado ainda. Clique em <b>Rodar varredura</b>.")
        elif n_feasible == 0:
            self.lbl_count.setText(
                f"<b>0 designs viáveis</b> entre {n_total} avaliados. "
                "Tente: aumentar <i>Ku máx</i> ou <i>Margem Bsat</i>; "
                "reduzir Pout; selecionar (varrer todos) materiais; "
                "desmarcar <i>Apenas curados</i>."
            )
        else:
            pct = 100.0 * n_feasible / n_total
            extra = "" if feasible_only else f" — {n_total - n_feasible} inviáveis ocultos abaixo"
            self.lbl_count.setText(
                f"<b>{n_feasible} viáveis</b> de {n_total} avaliados ({pct:.1f}%). "
                f"Mostrando top {len(rows)}{extra}."
            )

    def _refresh_plot(self):
        self.ax.clear()
        all_results = self._results
        feas = [(r.volume_cm3, r.P_total_W) for r in all_results if r.feasible]
        infeas = [(r.volume_cm3, min(r.P_total_W, 100.0)) for r in all_results if not r.feasible]
        if infeas:
            xi, yi = zip(*infeas)
            self.ax.scatter(xi, yi, c="#aaa", s=8, alpha=0.4, label="inviável")
        if feas:
            xf, yf = zip(*feas)
            self.ax.scatter(xf, yf, c="#3a78b5", s=10, alpha=0.7, label="viável")
        if self._pareto:
            xp = [r.volume_cm3 for r in self._pareto]
            yp = [r.P_total_W for r in self._pareto]
            self.ax.plot(xp, yp, "-o", c="#d04040", label="Pareto", linewidth=2, markersize=8)
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
        self.accept()
