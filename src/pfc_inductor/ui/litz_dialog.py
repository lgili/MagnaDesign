"""Litz wire optimizer dialog.

Runs `optimize.litz.recommend` for the active spec/core/material and
displays the recommended construction next to the best round-wire
baseline. The recommendation can be saved to the user-data wires.json so
it persists in the wire combobox.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from pfc_inductor.data_loader import load_wires, save_wires
from pfc_inductor.models import Core, Material, Spec, Wire
from pfc_inductor.optimize import (
    LitzRecommendation,
    closest_strand_AWG,
    optimal_strand_diameter_mm,
    recommend_litz,
)


class LitzOptimizerDialog(QDialog):
    """Modal dialog that finds the best Litz construction for a given design."""

    wire_saved = Signal(str)  # emits wire id when saved

    def __init__(
        self,
        spec: Spec,
        core: Core,
        material: Material,
        wires: list[Wire],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Otimizador de Litz")
        self.resize(1100, 640)
        self._spec = spec
        self._core = core
        self._material = material
        self._wires = wires
        self._rec: Optional[LitzRecommendation] = None

        outer = QVBoxLayout(self)
        outer.addWidget(self._build_target_box())
        outer.addWidget(self._build_inputs_box())
        outer.addWidget(self._build_result_box(), 1)
        outer.addLayout(self._build_buttons())

    def _build_target_box(self) -> QGroupBox:
        box = QGroupBox("Target design")
        v = QVBoxLayout(box)
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        lbl = QLabel(
            f"{self._material.vendor} — {self._material.name}  +  "
            f"{self._core.vendor} — {self._core.part_number} ({self._core.shape})\n"
            f"Pout = {self._spec.Pout_W:.0f} W   fsw = {self._spec.f_sw_kHz:.0f} kHz   "
            f"Vin (min) = {self._spec.Vin_min_Vrms:.0f} Vrms"
        )
        lbl.setFont(f)
        v.addWidget(lbl)
        return box

    def _build_inputs_box(self) -> QGroupBox:
        box = QGroupBox("Optimization criteria")
        h = QHBoxLayout(box)
        f = QFormLayout()

        self.sp_J = QDoubleSpinBox()
        self.sp_J.setRange(1.0, 10.0)
        self.sp_J.setDecimals(1)
        self.sp_J.setSingleStep(0.5)
        self.sp_J.setSuffix(" A/mm²")
        self.sp_J.setValue(4.0)
        f.addRow("Target current density:", self.sp_J)

        self.sp_AC_DC = QDoubleSpinBox()
        self.sp_AC_DC.setRange(1.001, 2.0)
        self.sp_AC_DC.setDecimals(3)
        self.sp_AC_DC.setSingleStep(0.01)
        self.sp_AC_DC.setValue(1.10)
        f.addRow("Target AC/DC ratio:", self.sp_AC_DC)

        self.sp_max_bundle = QDoubleSpinBox()
        self.sp_max_bundle.setRange(0.5, 30.0)
        self.sp_max_bundle.setDecimals(1)
        self.sp_max_bundle.setSingleStep(0.5)
        self.sp_max_bundle.setSuffix(" mm")
        self.sp_max_bundle.setValue(8.0)
        f.addRow("Max bundle diameter:", self.sp_max_bundle)

        self.sp_layers = QSpinBox()
        self.sp_layers.setRange(1, 30)
        self.sp_layers.setValue(1 if "tor" in (self._core.shape or "").lower() else 5)
        f.addRow("Effective layers (Nₗ):", self.sp_layers)

        h.addLayout(f)

        side = QVBoxLayout()
        self.lbl_d_opt = QLabel("d_opt: —")
        side.addWidget(self.lbl_d_opt)
        self.btn_run = QPushButton("Optimize")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.btn_run.clicked.connect(self._run)
        side.addWidget(self.btn_run)
        side.addStretch(1)
        h.addLayout(side)

        for spin in (self.sp_J, self.sp_AC_DC, self.sp_layers):
            spin.valueChanged.connect(lambda _v: self._update_d_opt())
        self._update_d_opt()
        return box

    def _build_result_box(self) -> QGroupBox:
        box = QGroupBox("Recommendation")
        v = QVBoxLayout(box)
        self.lbl_summary = QLabel("Click 'Optimize' to generate candidates.")
        self.lbl_summary.setStyleSheet("color:#555;")
        v.addWidget(self.lbl_summary)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            [
                "Construction",
                "AWG strand",
                "N strands",
                "d_bundle [mm]",
                "A_cu [mm²]",
                "AC/DC",
                "P_total [W]",
                "T [°C]",
                "Cost",
            ]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        self.table.setFont(f)
        v.addWidget(self.table, 1)
        return box

    def _build_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_save = QPushButton("Save selected as new wire")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_selected)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_save)
        h.addWidget(self.btn_close)
        return h

    def _update_d_opt(self):
        f_Hz = self._spec.f_sw_kHz * 1000.0
        layers = self.sp_layers.value()
        ac_dc = self.sp_AC_DC.value()
        d = optimal_strand_diameter_mm(f_Hz, layers, ac_dc)
        awg, d_actual = closest_strand_AWG(d)
        self.lbl_d_opt.setText(f"d_opt = {d:.3f} mm  →  AWG{awg} ({d_actual:.3f} mm)")

    def _run(self):
        self.btn_run.setEnabled(False)
        try:
            rec = recommend_litz(
                self._spec,
                self._core,
                self._material,
                self._wires,
                target_J_A_mm2=self.sp_J.value(),
                target_AC_DC=self.sp_AC_DC.value(),
                max_bundle_mm=self.sp_max_bundle.value(),
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            self.btn_run.setEnabled(True)
            return
        self._rec = rec
        self._populate_table()
        self.btn_run.setEnabled(True)
        self.btn_save.setEnabled(self.table.rowCount() > 0)

    def _populate_table(self):
        rec = self._rec
        if rec is None:
            return
        rows: list[tuple[str, object]] = []
        for c in rec.candidates:
            tag = "Litz"
            if rec.best is c:
                tag = "Litz ★"
            rows.append((tag, c))
        if rec.round_wire_baseline is not None:
            rows.append(("Round (baseline)", rec.round_wire_baseline))

        self.table.setRowCount(len(rows))
        for i, (tag, c) in enumerate(rows):
            r0 = c.result
            cells = [
                tag,
                f"{c.awg_strand}" if c.awg_strand else c.wire.id,
                f"{c.n_strands}" if c.n_strands > 0 else "—",
                f"{c.d_bundle_mm:.2f}" if c.d_bundle_mm > 0 else "—",
                f"{c.A_cu_mm2:.2f}",
                f"{c.AC_DC_ratio:.3f}",
                f"{r0.losses.P_total_W:.2f}" if r0 else "—",
                f"{r0.T_winding_C:.0f}" if r0 else "—",
                f"USD {c.cost:.2f}" if c.cost is not None else "—",
            ]
            for cidx, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if not c.feasible:
                    item.setForeground(Qt.GlobalColor.red)
                elif tag == "Litz ★":
                    item.setForeground(Qt.GlobalColor.darkGreen)
                self.table.setItem(i, cidx, item)
        self._row_to_cand = rows

        if rec.best is not None and rec.round_wire_baseline is not None:
            dp = rec.best.result.losses.P_total_W
            rp = rec.round_wire_baseline.result.losses.P_total_W
            delta_pct = (dp - rp) / rp * 100.0
            verdict = (
                f"Litz wins (−{abs(delta_pct):.1f}% loss)"
                if dp < rp
                else f"Round-wire wins (Litz is {delta_pct:+.1f}%)"
            )
            self.lbl_summary.setText(
                f"{len(rec.candidates)} Litz candidates evaluated, "
                f"round-wire baseline: {rec.round_wire_baseline.wire.id}. {verdict}"
            )
        else:
            self.lbl_summary.setText("No feasible candidates found.")

    def _save_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "Select a row", "Pick a row first.")
            return
        idx = rows[0].row()
        if idx >= len(self._row_to_cand):
            return
        _tag, cand = self._row_to_cand[idx]
        if cand.wire.type != "litz":
            QMessageBox.information(
                self,
                "Non-Litz row",
                "Only Litz constructions can be saved as a new wire.",
            )
            return
        suggested = cand.wire.id
        new_id, ok = QInputDialog.getText(
            self, "Save Litz", "Unique ID for the new wire:", text=suggested
        )
        if not ok or not new_id.strip():
            return
        new_id = new_id.strip()
        all_wires = list(load_wires())
        if any(w.id == new_id for w in all_wires):
            QMessageBox.warning(self, "ID in use", f"'{new_id}' already exists.")
            return
        new_wire = cand.wire.model_copy(update={"id": new_id})
        all_wires.append(new_wire)
        try:
            save_wires(all_wires)
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))
            return
        self.wire_saved.emit(new_id)
        QMessageBox.information(
            self,
            "Saved",
            f"Litz wire '{new_id}' added to the user database.\n"
            f"Re-open the app or reload the database to see it in the combobox.",
        )
