"""Spec input panel: all fields of `Spec`."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pfc_inductor.models import Spec


class SpecPanel(QWidget):
    """Left-side panel: collects spec, emits when changed."""

    changed = Signal()
    calculate_requested = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        from PySide6.QtWidgets import QFrame, QLabel, QScrollArea
        # Outer fixed: scroll area on top, primary CTA pinned at bottom.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        inner = QWidget()
        scroll.setWidget(inner)

        body = QVBoxLayout(inner)
        body.setContentsMargins(12, 12, 12, 4)
        body.setSpacing(8)

        title = QLabel("Especificação")
        title.setProperty("role", "title")
        body.addWidget(title)

        body.addWidget(self._build_topology_box())
        body.addWidget(self._build_input_box())
        self._converter_box = self._build_converter_box()
        body.addWidget(self._converter_box)
        self._line_reactor_box = self._build_line_reactor_box()
        self._line_reactor_box.setVisible(False)
        body.addWidget(self._line_reactor_box)
        body.addWidget(self._build_thermal_box())
        body.addStretch(1)

        # Primary CTA pinned outside scroll area so it stays visible.
        cta_row = QHBoxLayout()
        cta_row.setContentsMargins(12, 8, 12, 12)
        self.btn_calculate = QPushButton("Calcular")
        self.btn_calculate.setProperty("primary", "true")
        self.btn_calculate.setMinimumHeight(28)
        self.btn_calculate.clicked.connect(self.calculate_requested.emit)
        cta_row.addWidget(self.btn_calculate, 1)
        outer.addLayout(cta_row)

        self._wire_signals()

    def _build_topology_box(self) -> QGroupBox:
        box = QGroupBox("TOPOLOGIA")
        form = QFormLayout(box)
        self.cmb_topology = QComboBox()
        self.cmb_topology.addItem("PFC ativo (boost CCM)", "boost_ccm")
        self.cmb_topology.addItem("Choke passivo de linha", "passive_choke")
        self.cmb_topology.addItem("Reator de linha (50/60 Hz)", "line_reactor")
        self.cmb_topology.currentIndexChanged.connect(self._on_topology_changed)
        form.addRow("Tipo:", self.cmb_topology)
        return box

    def _build_line_reactor_box(self) -> QGroupBox:
        """Hidden by default; visible only when topology = line_reactor."""
        box = QGroupBox("REATOR DE LINHA")
        form = QFormLayout(box)
        self.cmb_phases = QComboBox()
        self.cmb_phases.addItem("Monofásico (1φ)", 1)
        self.cmb_phases.addItem("Trifásico (3φ)", 3)
        self.sp_vline = self._dspin(80, 690, 220.0, 1.0, " Vrms")
        self.sp_irated = self._dspin(0.1, 500, 2.2, 0.5, " A")
        self.sp_l_req = self._dspin(0.1, 1000, 10.0, 0.1, " mH")
        form.addRow("Fases:", self.cmb_phases)
        form.addRow("V de linha:", self.sp_vline)
        form.addRow("I nominal (RMS):", self.sp_irated)
        form.addRow("Indutância alvo:", self.sp_l_req)
        return box

    def _on_topology_changed(self):
        """Show/hide blocks that don't apply to the active topology.

        ``cmb_topology`` is also wired in ``_wire_signals`` to emit
        ``changed``, so we deliberately do *not* emit it again here —
        otherwise the debounce timer in MainWindow gets restarted twice
        per topology pick and the recalc-after-typing-stops semantics
        get fuzzy.
        """
        topo = self.cmb_topology.currentData()
        is_lr = topo == "line_reactor"
        self._line_reactor_box.setVisible(is_lr)
        self._converter_box.setVisible(not is_lr)

    def _build_input_box(self) -> QGroupBox:
        box = QGroupBox("ENTRADA AC")
        form = QFormLayout(box)
        self.sp_vin_min = self._dspin(50, 300, 85.0, 1.0, " Vrms")
        self.sp_vin_max = self._dspin(80, 300, 265.0, 1.0, " Vrms")
        self.sp_vin_nom = self._dspin(50, 300, 220.0, 1.0, " Vrms")
        self.sp_fline = self._dspin(40, 70, 50.0, 1.0, " Hz")
        form.addRow("Vin mín (worst case):", self.sp_vin_min)
        form.addRow("Vin máx:", self.sp_vin_max)
        form.addRow("Vin nominal:", self.sp_vin_nom)
        form.addRow("f rede:", self.sp_fline)
        return box

    def _build_converter_box(self) -> QGroupBox:
        box = QGroupBox("CONVERSOR")
        form = QFormLayout(box)
        self.sp_vout = self._dspin(100, 800, 400.0, 1.0, " V")
        self.sp_pout = self._dspin(50, 5000, 800.0, 10.0, " W")
        self.sp_eta = self._dspin(0.5, 1.0, 0.97, 0.01, "")
        self.sp_fsw = self._dspin(10, 500, 65.0, 1.0, " kHz")
        self.sp_ripple = self._dspin(5, 100, 30.0, 1.0, " %")
        form.addRow("Vout (DC bus):", self.sp_vout)
        form.addRow("Pout:", self.sp_pout)
        form.addRow("Eficiência:", self.sp_eta)
        form.addRow("fsw:", self.sp_fsw)
        form.addRow("Ripple pico-pico:", self.sp_ripple)
        return box

    def _build_thermal_box(self) -> QGroupBox:
        box = QGroupBox("TÉRMICO / JANELA")
        form = QFormLayout(box)
        self.sp_tamb = self._dspin(-20, 80, 40.0, 1.0, " °C")
        self.sp_tmax = self._dspin(60, 180, 125.0, 1.0, " °C")
        self.sp_ku = self._dspin(0.05, 0.7, 0.7, 0.01, "")
        self.sp_bsat_margin = self._dspin(0.0, 0.5, 0.20, 0.01, "")
        form.addRow("T ambiente:", self.sp_tamb)
        form.addRow("T máx enrolamento:", self.sp_tmax)
        form.addRow("Ku máx (uso da janela):", self.sp_ku)
        form.addRow("Margem Bsat:", self.sp_bsat_margin)
        return box

    @staticmethod
    def _dspin(mn, mx, val, step, suffix) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(mn, mx)
        s.setValue(val)
        s.setSingleStep(step)
        s.setDecimals(2)
        s.setSuffix(suffix)
        return s

    def _wire_signals(self):
        widgets = [
            self.cmb_topology, self.sp_vin_min, self.sp_vin_max, self.sp_vin_nom,
            self.sp_fline, self.sp_vout, self.sp_pout, self.sp_eta, self.sp_fsw,
            self.sp_ripple, self.sp_tamb, self.sp_tmax, self.sp_ku, self.sp_bsat_margin,
            self.cmb_phases, self.sp_vline, self.sp_irated, self.sp_l_req,
        ]
        for w in widgets:
            if isinstance(w, QComboBox):
                # QComboBox.currentIndexChanged emits int; discard it.
                w.currentIndexChanged.connect(lambda _idx: self.changed.emit())
            else:
                # QDoubleSpinBox.valueChanged emits float; discard it.
                w.valueChanged.connect(lambda _v: self.changed.emit())

    def get_spec(self) -> Spec:
        topo = self.cmb_topology.currentData()
        # Line reactor uses its own V/I from the dedicated block; for other
        # topologies we fall back to the AC input block values.
        if topo == "line_reactor":
            v_nom = self.sp_vline.value()
            n_phases = int(self.cmb_phases.currentData() or 3)
            i_rated = self.sp_irated.value()
            l_req = self.sp_l_req.value()
        else:
            v_nom = self.sp_vin_nom.value()
            n_phases = 3
            i_rated = 2.2
            l_req = 10.0
        return Spec(
            topology=topo,
            Vin_min_Vrms=self.sp_vin_min.value(),
            Vin_max_Vrms=self.sp_vin_max.value(),
            Vin_nom_Vrms=v_nom,
            f_line_Hz=self.sp_fline.value(),
            Vout_V=self.sp_vout.value(),
            Pout_W=self.sp_pout.value(),
            eta=self.sp_eta.value(),
            f_sw_kHz=self.sp_fsw.value(),
            ripple_pct=self.sp_ripple.value(),
            T_amb_C=self.sp_tamb.value(),
            T_max_C=self.sp_tmax.value(),
            Ku_max=self.sp_ku.value(),
            Bsat_margin=self.sp_bsat_margin.value(),
            n_phases=n_phases,
            L_req_mH=l_req,
            I_rated_Arms=i_rated,
        )
