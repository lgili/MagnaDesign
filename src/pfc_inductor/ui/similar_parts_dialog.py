"""Dialog: find equivalent cores/materials for the current selection."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from pfc_inductor.models import Core, Material
from pfc_inductor.optimize import (
    SimilarityCriteria,
    SimilarMatch,
    find_equivalents,
)


class SimilarPartsDialog(QDialog):
    """Show matches for (target_core, target_material) and allow apply."""

    selection_applied = Signal(str, str)  # material_id, core_id

    def __init__(
        self,
        target_core: Core,
        target_material: Material,
        cores: list[Core],
        materials: list[Material],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Peças similares")
        self.resize(1100, 600)
        self._target_core = target_core
        self._target_material = target_material
        self._cores = cores
        self._materials = materials
        self._current_matches: list[SimilarMatch] = []

        outer = QVBoxLayout(self)
        outer.addWidget(self._build_target_box())
        outer.addWidget(self._build_filter_box())
        outer.addWidget(self._build_table(), 1)
        outer.addLayout(self._build_buttons())

        self._refresh()

    def _build_target_box(self) -> QGroupBox:
        box = QGroupBox("Alvo (selecionado atualmente)")
        h = QHBoxLayout(box)
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        lbl = QLabel(self._format_target())
        lbl.setFont(f)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(lbl, 1)
        return box

    def _format_target(self) -> str:
        c, m = self._target_core, self._target_material
        return (
            f"{c.vendor} — {c.part_number}  ({c.shape})\n"
            f"Ae={c.Ae_mm2:.1f} mm²  Wa={c.Wa_mm2:.1f} mm²  AL={c.AL_nH:.0f} nH  "
            f"Ve={c.Ve_mm3/1000:.1f} cm³\n"
            f"Material: {m.vendor} — {m.name}  μ_r={m.mu_initial:.0f}  "
            f"Bsat(25/100°C)={m.Bsat_25C_T*1000:.0f}/{m.Bsat_100C_T*1000:.0f} mT"
        )

    def _build_filter_box(self) -> QGroupBox:
        box = QGroupBox("Tolerâncias")
        h = QHBoxLayout(box)

        self.sp_Ae = self._tol_spin(10.0)
        self.sp_Wa = self._tol_spin(15.0)
        self.sp_AL = self._tol_spin(20.0)
        self.sp_mu = self._tol_spin(20.0)
        self.sp_Bsat = self._tol_spin(15.0)

        f1 = QFormLayout()
        f1.addRow("Δ Ae (%):", self.sp_Ae)
        f1.addRow("Δ Wa (%):", self.sp_Wa)
        f2 = QFormLayout()
        f2.addRow("Δ AL (%):", self.sp_AL)
        f2.addRow("Δ μ_r (%):", self.sp_mu)
        f3 = QFormLayout()
        f3.addRow("Δ Bsat (%):", self.sp_Bsat)
        self.chk_same_shape = QCheckBox("Mesma forma")
        self.chk_same_shape.setChecked(True)
        self.chk_same_vendor = QCheckBox("Mesmo fabricante")
        self.chk_same_vendor.setChecked(False)
        f3.addRow(self.chk_same_shape)
        f3.addRow(self.chk_same_vendor)

        for spin in (self.sp_Ae, self.sp_Wa, self.sp_AL, self.sp_mu, self.sp_Bsat):
            spin.valueChanged.connect(lambda _v: self._refresh())
        self.chk_same_shape.toggled.connect(lambda _v: self._refresh())
        self.chk_same_vendor.toggled.connect(lambda _v: self._refresh())

        h.addLayout(f1)
        h.addLayout(f2)
        h.addLayout(f3)
        h.addStretch(1)
        return box

    @staticmethod
    def _tol_spin(default: float) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(1.0, 50.0)
        s.setDecimals(0)
        s.setSingleStep(1)
        s.setSuffix(" %")
        s.setValue(default)
        return s

    def _build_table(self) -> QGroupBox:
        box = QGroupBox("Resultados (ordenados por proximidade)")
        v = QVBoxLayout(box)
        self.lbl_count = QLabel("—")
        v.addWidget(self.lbl_count)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Vendor", "Part number", "Forma", "Material",
            "Δ Ae", "Δ Wa", "Δ AL", "Δ μ_r", "d",
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        f = QFont()
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setFamily("Menlo")
        self.table.setFont(f)
        v.addWidget(self.table, 1)
        return box

    def _build_buttons(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.addStretch(1)
        self.btn_apply = QPushButton("Aplicar selecionado")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_apply)
        h.addWidget(self.btn_close)
        return h

    def _criteria(self) -> SimilarityCriteria:
        return SimilarityCriteria(
            Ae_pct=self.sp_Ae.value(),
            Wa_pct=self.sp_Wa.value(),
            AL_pct=self.sp_AL.value(),
            mu_r_pct=self.sp_mu.value(),
            Bsat_pct=self.sp_Bsat.value(),
            same_shape=self.chk_same_shape.isChecked(),
            same_vendor=self.chk_same_vendor.isChecked(),
            exclude_self=True,
        )

    def _refresh(self):
        crit = self._criteria()
        self._current_matches = find_equivalents(
            self._target_core, self._target_material,
            self._cores, self._materials, crit,
        )
        self._populate_table()

    def _populate_table(self):
        self.table.setRowCount(len(self._current_matches))
        for i, m in enumerate(self._current_matches):
            cells = [
                m.core.vendor,
                m.core.part_number,
                m.core.shape,
                m.material.name,
                f"{m.deltas_pct['Ae']:+.1f}%",
                f"{m.deltas_pct['Wa']:+.1f}%",
                f"{m.deltas_pct['AL']:+.1f}%",
                f"{m.deltas_pct['mu_r']:+.1f}%",
                f"{m.distance:.2f}",
            ]
            for c_idx, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                if m.is_cross_material:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                self.table.setItem(i, c_idx, item)
        n_cm = sum(1 for m in self._current_matches if m.is_cross_material)
        self.lbl_count.setText(
            f"{len(self._current_matches)} alternativa(s) encontradas — "
            f"{n_cm} cross-material (mesmo part number, material diferente)"
        )

    def _on_select(self):
        rows = self.table.selectionModel().selectedRows()
        self.btn_apply.setEnabled(len(rows) > 0)

    def _apply(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        if idx >= len(self._current_matches):
            return
        m = self._current_matches[idx]
        self.selection_applied.emit(m.material.id, m.core.id)
        self.accept()
